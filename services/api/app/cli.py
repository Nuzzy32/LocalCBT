"""CLI operator. Juga dipanggil Control Center (opsi --json), jadi tetap jalan saat API mati.

  uv run python -m app.cli create-admin <username> --name "..."
  uv run python -m app.cli status|backups|preflight [--json]
  uv run python -m app.cli backup                 backup manual sekarang (terenkripsi, diverifikasi)
  uv run python -m app.cli rehearse [JOB_ID]      uji restore ke DB sementara, lalu dihapus
  uv run python -m app.cli restore JOB_ID --into NAMA_DB [--switch]
  uv run python -m app.cli attest-network --by NAMA --items a,b --note "..."
  uv run python -m app.cli upgrade                backup PRE_UPGRADE lalu migrasi skema

Membuat database (rehearse/restore) butuh hak CREATEDB. Bila akun aplikasi tidak punya,
isi LOCALCBT_ADMIN_DATABASE_URL (env, bukan argumen: kata sandi tidak terlihat di daftar proses).
"""

import argparse
import getpass
import json
import os
import re
import sys
import tempfile
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Connection, create_engine, make_url, text

from app import backup, ops
from app.auth import hash_password
from app.config import settings
from app.db import audit, database_ok, engine

ATTEST_ITEMS = {
    "wan_ipv4": "Internet IPv4 tertutup dari SSID ujian (diuji dari perangkat siswa)",
    "wan_ipv6": "Internet IPv6 tertutup / IPv6 dimatikan di SSID ujian",
    "dns": "DNS hanya ke resolver lokal; DoH/DoT umum diblokir",
    "staff_isolated": "Perangkat siswa tidak bisa menjangkau jaringan staf",
    "client_isolation": "Isolasi antar-klien aktif di SSID ujian",
    "router_admin": "Halaman admin router tidak terjangkau dari SSID ujian",
    "portal_only": "Hanya port 443 server LocalCBT yang terbuka untuk siswa",
}


class CliError(Exception):
    pass


def create_admin(username: str, name: str, password: str, force: bool) -> None:
    with engine.begin() as db:
        if not force and db.scalar(text("select 1 from user_roles where role = 'ADMIN' limit 1")):
            raise CliError("Admin sudah ada. Pakai --force untuk menambah admin lain.")
        user_id = db.scalar(
            text("""
            insert into users (username, password_hash, display_name)
            values (:u, :h, :n) returning id
            """),
            {"u": username, "h": hash_password(password), "n": name},
        )
        db.execute(
            text("insert into user_roles (user_id, role) values (:id, 'ADMIN')"), {"id": user_id}
        )


def status() -> dict[str, Any]:
    if not database_ok():
        return ops.health_data(None)
    with engine.connect() as db:
        out = ops.health_data(db)
        out["alembic_rev"] = db.scalar(text("select version_num from alembic_version"))
        out["network"] = ops.network_data(db)
        out["settings"] = _retention(db)
    return out


def set_retention(hour: int, keep_daily: int, keep_manual_days: int, reason: str) -> dict[str, Any]:
    body = ops.OpsSettingsIn(
        backup_hour=hour,
        backup_keep_daily=keep_daily,
        backup_keep_manual_days=keep_manual_days,
        reason=reason,
    )  # validasi sama dengan endpoint HTTP
    values = body.model_dump(exclude={"reason"})
    with engine.begin() as db:
        before = _retention(db)
        db.execute(
            text("""
            update ops_settings set backup_hour = :backup_hour,
              backup_keep_daily = :backup_keep_daily,
              backup_keep_manual_days = :backup_keep_manual_days, updated_by = null,
              updated_at = now()
            """),
            values,
        )
        audit(db, None, "OPS_SETTINGS_CHANGED", "ops_settings", ops.NETWORK, reason,
              {**_os_actor(), "before": before, "after": values})  # fmt: skip
    return values


def _retention(db: Connection) -> dict[str, Any]:
    sql = "select backup_hour, backup_keep_daily, backup_keep_manual_days from ops_settings"
    return dict(db.execute(text(sql)).mappings().one())


SERVICE_ACTIONS = ("START", "STOP", "RESTART")


def service_action(action: str, reason: str) -> dict[str, Any]:
    """Catat start/stop service dari Control Center. Stop saat ujian berjalan wajib alasan."""
    active = 0
    if database_ok():
        with engine.connect() as db:
            active = backup.active_attempts(db)
    if action in ("STOP", "RESTART") and active and len(reason.strip()) < 10:
        raise CliError(f"Ada {active} ujian berjalan. Isi alasan darurat (min. 10 karakter).")
    if database_ok():
        with engine.begin() as db:
            audit(db, None, f"SERVICE_{action}", "service", ops.NETWORK, reason or None,
                  {**_os_actor(), "active_attempts": active})  # fmt: skip
    return {"action": action, "active_attempts": active}


def list_backups() -> list[dict[str, Any]]:
    with engine.connect() as db:
        rows = db.execute(
            text("""
            select id, trigger, status, path, size_bytes, error, created_at, verified_at,
              restore_verified_at, pruned_at
            from backup_jobs order by created_at desc limit 50
            """)
        ).mappings()
        return [dict(r) for r in rows]


def run_backup(trigger: str = "MANUAL") -> dict[str, Any]:
    with backup.ops_lock() as got:
        if not got:
            raise CliError("Backup/restore lain sedang berjalan. Coba lagi beberapa menit lagi.")
        backup._fail_stale()  # job RUNNING & folder kerja sisa proses yang mati
        with engine.begin() as db:
            job_id = db.scalar(text("select id from backup_jobs where status = 'QUEUED'"))
            if job_id is None or trigger != "MANUAL":
                if job_id is not None:
                    raise CliError("Ada backup lain yang sedang antre.")
                job_id = backup.queue_backup(db, trigger, None)
                audit(db, None, "BACKUP_REQUESTED", "backup", job_id, metadata=_os_actor())
        result = backup.run_job(job_id)
    job = next(j for j in list_backups() if j["id"] == job_id)
    if result != "VERIFIED":
        raise CliError(f"Backup GAGAL: {job['error']}")
    return job


def _job_folder(job_ref: str | None) -> tuple[UUID, Path]:
    with engine.connect() as db:
        row = db.execute(
            text("""
            select id, path from backup_jobs
            where status = 'VERIFIED' and pruned_at is null
              and (cast(:id as uuid) is null or id = cast(:id as uuid))
            order by verified_at desc limit 1
            """),
            {"id": job_ref},
        ).first()
    if row is None:
        raise CliError("Backup terverifikasi tidak ditemukan.")
    return row.id, Path(row.path)


def rehearse(job_ref: str | None, admin_url: str | None) -> dict[str, Any]:
    """FR-OPS-06: restore sungguhan ke DB sementara, cocokkan, lalu hapus. Data asli aman."""
    job_id, folder = _job_folder(job_ref)
    name = f"{make_url(settings.database_url).database}_restore_check"
    with backup.ops_lock() as got:
        if not got:
            raise CliError("Backup/restore lain sedang berjalan.")
        backup.drop_database(name, admin_url)
        with tempfile.TemporaryDirectory() as media:
            manifest = backup.restore_backup(
                folder, settings.backup_passphrase, name, Path(media), admin_url
            )
        backup.drop_database(name, admin_url)
    with engine.begin() as db:
        db.execute(
            text("update backup_jobs set restore_verified_at = now() where id = :id"),
            {"id": job_id},
        )
        audit(db, None, "RESTORE_REHEARSED", "backup", job_id, metadata=_os_actor())
    return {"job_id": job_id, "counts": manifest["counts"], "alembic_rev": manifest["alembic_rev"]}


def _set_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [ln for ln in lines if not ln.startswith(f"{key}=")] + [f"{key}={value}"]
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = path.with_name(f"{path.name}.bak-{stamp}")
        # Berisi kata sandi DB & kunci backup: 0600 sejak dibuat, bukan umask (M9-02).
        with os.fdopen(os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
            f.write(path.read_text())
    tmp = path.with_name(f".{path.name}.new")
    tmp.unlink(missing_ok=True)
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def restore(
    job_ref: str, into: str, switch: bool, incident_reason: str | None, admin_url: str | None
) -> dict[str, Any]:
    """Restore ke DB BARU. --switch mengarahkan .env ke DB itu (service perlu di-restart)."""
    reason = (incident_reason or "").strip()
    if incident_reason is not None and len(reason) < 10:
        raise CliError("Alasan insiden minimal 10 karakter.")
    if database_ok():
        with engine.connect() as db:
            active = backup.active_attempts(db)
        if active and not reason:
            raise CliError(
                f"Ada {active} ujian sedang berjalan. Restore saat ujian aktif hanya untuk insiden "
                'kritis: ulangi dengan --incident-reason "...".'
            )
    job_id, folder = _job_folder(job_ref)
    # DB lama mati = tidak ada proses lain yang bisa memegang lock.
    with backup.ops_lock() if database_ok() else nullcontext(True) as got:
        if not got:
            raise CliError("Backup/restore lain sedang berjalan.")
        manifest = backup.restore_backup(
            folder, settings.backup_passphrase, into, Path(settings.media_dir), admin_url
        )
    target = make_url(settings.database_url).set(database=into)
    target_url = target.render_as_string(hide_password=False)
    restored = create_engine(target_url)
    try:
        with restored.begin() as db:
            audit(db, None, "RESTORE_PERFORMED", "backup", job_id, reason or None,
                  {**_os_actor(), "into": into, "switched": switch})  # fmt: skip
    finally:
        restored.dispose()
    if switch:
        _set_env(Path(".env"), "LOCALCBT_DATABASE_URL", target_url)
    return {"job_id": job_id, "database": into, "counts": manifest["counts"], "switched": switch}


def attest(by: str, items: list[str], note: str) -> dict[str, Any]:
    unknown = set(items) - ATTEST_ITEMS.keys()
    if unknown:
        raise CliError(f"Item tidak dikenal: {', '.join(sorted(unknown))}")
    if len(by.strip()) < 3:
        raise CliError("Isi nama petugas yang memeriksa.")
    meta = {**_os_actor(), "by": by.strip(), "checked": sorted(items),
            "unchecked": sorted(ATTEST_ITEMS.keys() - set(items))}  # fmt: skip
    with engine.begin() as db:
        audit(db, None, "NETWORK_ATTESTED", "network", ops.NETWORK, note or None, meta)
    return meta


def preflight() -> list[dict[str, str]]:
    if not database_ok():
        return ops.run_preflight(None)
    with engine.begin() as db:
        checks = ops.run_preflight(db)
        audit(db, None, "PREFLIGHT_SERVER", "network", ops.NETWORK,
              metadata={**_os_actor(), "checks": checks})  # fmt: skip
    return checks


def upgrade() -> dict[str, Any]:
    """Pembaruan versi: tolak bila ada ujian berjalan, backup terverifikasi, lalu migrasi.
    Migrasi berjalan dalam satu transaksi (alembic/env.py): gagal = otomatis kembali."""
    from alembic import command
    from alembic.config import Config

    with engine.connect() as db:
        if active := backup.active_attempts(db):
            raise CliError(f"Ada {active} ujian sedang berjalan. Tunggu sampai selesai.")
        before = db.scalar(text("select version_num from alembic_version"))
    job = run_backup("PRE_UPGRADE")
    command.upgrade(Config(str(Path(__file__).parent.parent / "alembic.ini")), "head")
    with engine.connect() as db:
        after = db.scalar(text("select version_num from alembic_version"))
    return {"backup_job": job["id"], "from_rev": before, "to_rev": after}


def _os_actor() -> dict[str, str]:
    try:
        user = getpass.getuser()
    except OSError:
        user = "?"
    return {"os_user": user, "via": "cli"}


def _print(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, default=str))
    elif isinstance(data, list):
        for row in data:
            print(" | ".join(f"{k}={v}" for k, v in row.items() if v is not None))
    else:
        for k, v in data.items():
            print(f"{k}: {v}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("--json", action="store_true", help="keluaran JSON (Control Center)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin")
    p.add_argument("username")
    p.add_argument("--name", required=True)
    p.add_argument("--force", action="store_true")
    p.add_argument("--password-stdin", action="store_true")
    for name in (
        "status",
        "backups",
        "backup",
        "preflight",
        "upgrade",
        "attest-items",
        "probe-link",
    ):
        sub.add_parser(name)
    p = sub.add_parser("rehearse")
    p.add_argument("job_id", nargs="?")
    p = sub.add_parser("restore")
    p.add_argument("job_id")
    p.add_argument("--into", required=True)
    p.add_argument("--switch", action="store_true")
    p.add_argument("--incident-reason")
    p = sub.add_parser("set-retention")
    p.add_argument("--hour", type=int, required=True)
    p.add_argument("--keep-daily", type=int, required=True)
    p.add_argument("--keep-manual-days", type=int, required=True)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("service-action")
    p.add_argument("action", choices=SERVICE_ACTIONS)
    p.add_argument("--reason", default="")
    p = sub.add_parser("attest-network")
    p.add_argument("--by", required=True)
    p.add_argument("--items", default="")
    p.add_argument("--note", default="")
    args = parser.parse_args(argv)
    admin_url = os.environ.get("LOCALCBT_ADMIN_DATABASE_URL")

    try:
        data: Any
        if args.cmd == "create-admin":
            if args.password_stdin:
                password = sys.stdin.readline().rstrip("\n")
            else:
                password = getpass.getpass("Kata sandi admin (min. 12 karakter): ")
                if getpass.getpass("Ulangi kata sandi: ") != password:
                    raise CliError("Kata sandi tidak sama.")
            if len(password) < 12:
                raise CliError("Kata sandi terlalu pendek.")
            if not re.fullmatch(r"[0-9A-Za-z._-]{1,64}", args.username):
                raise CliError("Nama pengguna tidak valid.")
            create_admin(args.username, args.name, password, args.force)
            data = {"created": args.username}
        elif args.cmd == "status":
            data = status()
        elif args.cmd == "backups":
            data = list_backups()
        elif args.cmd == "backup":
            data = run_backup()
        elif args.cmd == "rehearse":
            data = rehearse(args.job_id, admin_url)
        elif args.cmd == "restore":
            data = restore(args.job_id, args.into, args.switch, args.incident_reason, admin_url)
        elif args.cmd == "preflight":
            data = preflight()
        elif args.cmd == "set-retention":
            data = set_retention(args.hour, args.keep_daily, args.keep_manual_days, args.reason)
        elif args.cmd == "service-action":
            data = service_action(args.action, args.reason)
        elif args.cmd == "probe-link":
            with engine.begin() as db:
                data = ops.create_probe_link(db, None)
        elif args.cmd == "attest-items":
            data = ATTEST_ITEMS
        elif args.cmd == "attest-network":
            items = [i for i in args.items.split(",") if i]
            data = attest(args.by, items, args.note)
        else:
            data = upgrade()
    except ValidationError as e:
        msg = "; ".join(str(err["msg"]) for err in e.errors())
        print(json.dumps({"error": msg}) if args.json else f"GAGAL: {msg}")
        return 1
    except (CliError, backup.BackupError) as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"GAGAL: {e}", file=sys.stderr)
        return 1
    _print(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
