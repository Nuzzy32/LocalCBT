"""M8: backup terenkripsi & terverifikasi, restore, retensi, health, probe jaringan.

Tes backup memakai pg_dump/pg_restore sungguhan: alat hilang = tes GAGAL, bukan dilewati.
Di Mac: LOCALCBT_PG_BIN_DIR=/opt/homebrew/opt/libpq/bin.
"""

import io
import json
import subprocess
from collections import namedtuple
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text

from app import backup, cli, ops
from app.config import settings
from app.db import engine
from app.main import app
from tests.conftest import ORIGIN, login, make_user
from tests.test_questions import png

PASS = "kata-sandi-backup-uji"


@pytest.fixture
def backups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "backups")
    monkeypatch.setattr(settings, "backup_passphrase", PASS)
    ops.probe_limiter.reset()
    return tmp_path / "backups"


def _seed_media() -> str:
    make_user("guru.m", "TEACHER")
    r = login("guru.m").post("/api/v1/media", files={"file": ("a.png", png())})
    assert r.status_code == 201, r.text
    with engine.connect() as db:
        return str(db.scalar(text("select sha256 from media_assets")))


# ---- Enkripsi ---------------------------------------------------------------------


def _encrypt(data: bytes, passphrase: str = PASS) -> bytes:
    buf = io.BytesIO()
    enc = backup.Encryptor(buf, passphrase)
    enc.write(data)
    enc.finish()
    return buf.getvalue()


def _decrypt(blob: bytes, passphrase: str = PASS) -> bytes:
    dec = backup.Decryptor(io.BytesIO(blob), passphrase)
    out = dec.read()
    dec.finish()
    return out


def test_encryption_roundtrip_multi_chunk() -> None:
    data = bytes(range(256)) * (backup.CHUNK // 256 * 2 + 7)
    blob = _encrypt(data)
    assert data[:4096] not in blob
    assert _decrypt(blob) == data
    assert _decrypt(_encrypt(b"")) == b""


def test_encryption_detects_tamper_truncation_and_wrong_key() -> None:
    blob = _encrypt(b"x" * (backup.CHUNK * 2 + 10))
    flipped = bytearray(blob)
    flipped[len(blob) // 2] ^= 1
    with pytest.raises(backup.BackupError):
        _decrypt(bytes(flipped))
    # Potong tepat di batas frame: tanpa penanda final harus ditolak.
    first_frame_end = len(backup.MAGIC) + 24 + 4 + backup.CHUNK + 16
    with pytest.raises(backup.BackupError, match="terpotong"):
        _decrypt(blob[:first_frame_end])
    with pytest.raises(backup.BackupError, match="salah"):
        _decrypt(blob, "kata-sandi-lain-123")


# ---- Jadwal ---------------------------------------------------------------------


def test_daily_due_rules() -> None:
    now = datetime(2026, 10, 20, 9, 0).astimezone()
    recent = now - timedelta(hours=10)
    yesterday = now - timedelta(days=1)
    assert backup.daily_due(now, 2, yesterday, recent, active=0)
    assert not backup.daily_due(now, 2, yesterday, recent, active=3)  # ujian berjalan: tunggu
    assert not backup.daily_due(now, 10, yesterday, recent, active=0)  # belum jamnya
    assert not backup.daily_due(now, 2, now - timedelta(hours=2), recent, active=0)  # sudah
    # Terlambat > 36 jam: paksa walau ada ujian, coba ulang paling sering sejam sekali.
    stale = now - timedelta(hours=40)
    assert backup.daily_due(now, 23, yesterday, stale, active=5)
    assert not backup.daily_due(now, 23, now - timedelta(minutes=20), stale, active=5)
    assert backup.daily_due(now, 23, None, None, active=5)


# ---- Backup end-to-end --------------------------------------------------------------


def test_backup_is_encrypted_verified_and_private(backups: Path) -> None:
    sha = _seed_media()
    job = cli.run_backup()
    assert job["status"] == "VERIFIED" and job["size_bytes"] > 0
    folder = Path(job["path"])
    assert folder.parent == backups.resolve()
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["counts"]["users"] == 1 and manifest["counts"]["media_assets"] == 1
    assert manifest["media"] == [sha]
    assert manifest["alembic_rev"] == "0007"
    raw = (folder / "data.lcbk").read_bytes()
    assert b"guru.m" not in raw and png() not in raw  # tidak ada data mentah
    assert (folder / "data.lcbk").stat().st_mode & 0o077 == 0
    assert folder.stat().st_mode & 0o077 == 0


def test_corrupted_backup_never_verifies(backups: Path) -> None:
    _seed_media()
    folder = Path(cli.run_backup()["path"])
    blob = bytearray((folder / "data.lcbk").read_bytes())
    blob[len(blob) // 2] ^= 1
    (folder / "data.lcbk").write_bytes(bytes(blob))
    with pytest.raises(backup.BackupError):
        backup.verify_backup(folder, PASS)


def test_missing_passphrase_fails_loudly(backups: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "backup_passphrase", "")
    with pytest.raises(cli.CliError, match="Kata sandi backup"):
        cli.run_backup()
    with engine.connect() as db:
        assert db.scalar(text("select status from backup_jobs")) == "FAILED"
    assert not any(backups.glob("*-manual"))  # sisa parsial dibersihkan


def test_db_password_never_on_argv(backups: Path) -> None:
    calls: list[list[str]] = []
    real = subprocess.run

    def spy(args: list[str], **kw: Any) -> Any:
        calls.append(args)
        return real(args, **kw)

    with patch("app.backup.subprocess.run", side_effect=spy):
        cli.run_backup()
    password = make_url(settings.database_url).password
    assert calls and password
    assert not any(password in a for args in calls for a in args)


def test_rehearsal_restores_matching_data_then_drops(backups: Path) -> None:
    _seed_media()
    job = cli.run_backup()
    result = cli.rehearse(None, None)
    assert result["counts"]["users"] == 1
    check_db = f"{make_url(settings.database_url).database}_restore_check"
    with engine.connect() as db:
        assert (
            db.scalar(text("select 1 from pg_database where datname = :d"), {"d": check_db}) is None
        )
        assert db.scalar(
            text("select restore_verified_at from backup_jobs where id = :id"), {"id": job["id"]}
        )


def test_restore_into_new_db_and_refusals(backups: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sha = _seed_media()
    job = cli.run_backup()
    target = f"{make_url(settings.database_url).database}_restored"
    backup.drop_database(target)
    # Media dipulihkan ke media_dir: kosongkan dulu untuk membuktikan media ikut kembali.
    media_file = Path(settings.media_dir) / sha[:2] / sha
    media_file.unlink()
    try:
        result = cli.restore(str(job["id"]), target, False, None, None)
        assert result["counts"]["media_assets"] == 1
        assert media_file.read_bytes() == png()
        restored = create_engine(make_url(settings.database_url).set(database=target))
        with restored.connect() as db:
            assert db.scalar(text("select username from users")) == "guru.m"
            assert (
                db.scalar(
                    text("select count(*) from audit_events where action = 'RESTORE_PERFORMED'")
                )
                == 1
            )
        restored.dispose()
        with pytest.raises(backup.BackupError, match="sudah ada"):
            cli.restore(str(job["id"]), target, False, None, None)
    finally:
        backup.drop_database(target)
    with pytest.raises(backup.BackupError, match="Menolak"):
        backup.drop_database(str(make_url(settings.database_url).database))
    monkeypatch.setattr(backup, "active_attempts", lambda db: 2)
    with pytest.raises(cli.CliError, match="ujian sedang berjalan"):
        cli.restore(str(job["id"]), target, False, None, None)
    with pytest.raises(cli.CliError, match="10 karakter"):
        cli.restore(str(job["id"]), target, False, "x", None)


def test_switch_rewrites_env_with_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text("LOCALCBT_DATABASE_URL=postgresql+psycopg://a@h/old\nLOCALCBT_LOG_LEVEL=INFO\n")
    cli._set_env(env, "LOCALCBT_DATABASE_URL", "postgresql+psycopg://a@h/new")
    lines = env.read_text().splitlines()
    assert "LOCALCBT_DATABASE_URL=postgresql+psycopg://a@h/new" in lines
    assert "LOCALCBT_LOG_LEVEL=INFO" in lines and len(lines) == 2
    (bak,) = tmp_path.glob(".env.bak-*")
    assert "old" in bak.read_text()


def test_prune_keeps_newest_and_respects_retention(backups: Path) -> None:
    backups.mkdir(parents=True)
    with engine.begin() as db:
        db.execute(
            text("update ops_settings set backup_keep_daily = 2, backup_keep_manual_days = 30")
        )
        for i, (trigger, age_days) in enumerate(
            [("DAILY", 0), ("DAILY", 1), ("DAILY", 2), ("DAILY", 3), ("MANUAL", 10), ("MANUAL", 40)]
        ):
            folder = backups.resolve() / f"b{i}"
            folder.mkdir()
            db.execute(
                text("""
                insert into backup_jobs (trigger, status, path, verified_at)
                values (:t, 'VERIFIED', :p, now() - make_interval(days => :d))
                """),
                {"t": trigger, "p": str(folder), "d": age_days},
            )
    pruned = sorted(Path(p).name for p in backup.prune())
    assert pruned == ["b2", "b3", "b5"]
    assert sorted(p.name for p in backups.iterdir()) == ["b0", "b1", "b4"]


# ---- HTTP: health, backup, settings ---------------------------------------------------


def test_ops_endpoints_admin_only(backups: Path) -> None:
    make_user("guru", "TEACHER")
    teacher = login("guru")
    for path in ("/api/v1/ops/health", "/api/v1/ops/backups", "/api/v1/ops/network"):
        assert teacher.get(path).status_code == 403
    assert teacher.post("/api/v1/ops/backups").status_code == 403
    assert teacher.post("/api/v1/ops/preflight").status_code == 403


def test_health_disk_thresholds_and_backup_state(backups: Path) -> None:
    make_user("admin", "ADMIN")
    admin = login("admin")
    body = admin.get("/api/v1/ops/health").json()
    assert body["database_status"] == "OK" and body["last_verified_backup_at"] is None
    assert body["backup_passphrase_set"] is True
    Usage = namedtuple("Usage", "total used free")
    with patch("app.ops.shutil.disk_usage", return_value=Usage(100, 97, 3)):
        body = admin.get("/api/v1/ops/health").json()
    assert body["disk_status"] == "CRITICAL" and body["server_status"] == "DEGRADED"
    with patch("app.ops.shutil.disk_usage", return_value=Usage(100, 90, 10)):
        assert admin.get("/api/v1/ops/health").json()["disk_status"] == "WARNING"
    with patch("app.ops.shutil.disk_usage", side_effect=OSError):
        assert admin.get("/api/v1/ops/health").json()["disk_status"] == "CRITICAL"


def test_manual_backup_request_queues_once(backups: Path) -> None:
    make_user("admin", "ADMIN")
    admin = login("admin")
    r = admin.post("/api/v1/ops/backups")
    assert r.status_code == 202 and r.json()["status"] == "QUEUED"
    assert admin.post("/api/v1/ops/backups").status_code == 409
    backup.tick()  # scheduler mengambil job antrean
    (job,) = admin.get("/api/v1/ops/backups").json()
    assert job["status"] == "VERIFIED"
    assert admin.get("/api/v1/ops/health").json()["last_verified_backup_at"]


def test_settings_change_requires_reason_and_is_audited(backups: Path) -> None:
    make_user("admin", "ADMIN")
    admin = login("admin")
    body = {"backup_hour": 3, "backup_keep_daily": 30, "backup_keep_manual_days": 180}
    assert admin.put("/api/v1/ops/settings", json=body).status_code == 422
    r = admin.put("/api/v1/ops/settings", json={**body, "reason": "Kebijakan sekolah 2026"})
    assert r.status_code == 200 and r.json()["backup_keep_daily"] == 30
    with engine.connect() as db:
        meta = db.scalar(
            text("select metadata from audit_events where action = 'OPS_SETTINGS_CHANGED'")
        )
    assert meta["before"]["backup_keep_daily"] == 14 and meta["after"]["backup_keep_daily"] == 30


# ---- Probe jaringan ---------------------------------------------------------------


def _probe_client(ip: str) -> TestClient:
    return TestClient(
        app, base_url="https://testserver", headers={"Origin": ORIGIN}, client=(ip, 1)
    )


ALL_BLOCKED = {t: {"reachable": False, "ms": 4000} for t in ops.PROBE_TARGETS}


def test_probe_page_has_own_csp_and_no_auth() -> None:
    r = _probe_client("10.20.0.5").get("/api/v1/ops/probe")
    assert (
        r.status_code == 200 and "connect-src 'self' https:" in r.headers["content-security-policy"]
    )
    js = _probe_client("10.20.0.5").get("/api/v1/ops/probe.js")
    assert "1.1.1.1" in js.text and "probe-reports" in js.text


def test_probe_verdict_only_green_from_exam_subnet(
    backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "exam_subnets", ["10.20.0.0/22"])
    make_user("admin", "ADMIN")
    admin = login("admin")

    def verdict() -> dict[str, str]:
        return admin.get("/api/v1/ops/network").json()["probe"]

    bad = {"control_ok": True, "results": {"nope": {"reachable": False, "ms": 1}}}
    assert _probe_client("10.20.0.5").post("/api/v1/ops/probe-reports", json=bad).status_code == 422
    # Dari jaringan staf: tidak dihitung.
    r = _probe_client("192.168.1.9").post(
        "/api/v1/ops/probe-reports", json={"control_ok": True, "results": ALL_BLOCKED}
    )
    assert r.status_code == 201 and r.json()["in_exam_subnet"] is False
    assert verdict()["status"] == "UNTESTED"
    # Kontrol lokal gagal: laporan tidak sah.
    _probe_client("10.20.0.6").post(
        "/api/v1/ops/probe-reports", json={"control_ok": False, "results": ALL_BLOCKED}
    )
    assert verdict()["status"] == "FAILED"
    _probe_client("10.20.0.7").post(
        "/api/v1/ops/probe-reports", json={"control_ok": True, "results": ALL_BLOCKED}
    )
    assert verdict()["status"] == "OK"
    leaky = {**ALL_BLOCKED, "ipv6_cloudflare": {"reachable": True, "ms": 30}}
    _probe_client("10.20.1.8").post(
        "/api/v1/ops/probe-reports", json={"control_ok": True, "results": leaky}
    )
    v = verdict()
    assert v["status"] == "FAILED" and "ipv6_cloudflare" in v["detail"]


def test_probe_verdict_expires_and_rate_limit(
    backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "exam_subnets", ["10.20.0.0/22"])
    meta = {"ip": "10.20.0.1", "control_ok": True, "results": {}}
    now = datetime.now().astimezone()
    old = {"metadata": meta, "created_at": now - timedelta(days=8)}
    assert ops.network_verdict(old, now)["status"] == "UNTESTED"
    monkeypatch.setattr(settings, "exam_subnets", [])
    assert ops.network_verdict({"metadata": meta, "created_at": now}, now)["status"] == "UNTESTED"
    c = _probe_client("10.20.0.9")
    body = {"control_ok": True, "results": ALL_BLOCKED}
    codes = [c.post("/api/v1/ops/probe-reports", json=body).status_code for _ in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429


def test_preflight_reports_untested_never_green_by_default(backups: Path) -> None:
    make_user("admin", "ADMIN")
    checks = {c["id"]: c for c in login("admin").post("/api/v1/ops/preflight").json()["checks"]}
    assert checks["database"]["status"] == "OK"
    assert checks["backup"]["status"] == "FAILED"  # belum ada backup terverifikasi
    assert checks["https"]["status"] == "UNTESTED"
    assert checks["wan_blocked"]["status"] == "UNTESTED"
    assert checks["pg_tools"]["status"] == "OK"


def test_attest_network_records_checklist() -> None:
    meta = cli.attest("Pak Budi", ["wan_ipv4", "dns"], "Diuji dari HP Android lab")
    assert meta["checked"] == ["dns", "wan_ipv4"] and "wan_ipv6" in meta["unchecked"]
    with pytest.raises(cli.CliError):
        cli.attest("Pak Budi", ["bukan_item"], "")
    with engine.connect() as db:
        assert (
            db.scalar(text("select count(*) from audit_events where action = 'NETWORK_ATTESTED'"))
            == 1
        )


def test_cli_json_output_and_errors(backups: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--json", "status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["database_status"] == "OK" and out["alembic_rev"] == "0007"
    assert cli.main(["--json", "rehearse"]) == 1
    assert "error" in json.loads(capsys.readouterr().out)


def test_client_server_version_mismatch_is_refused(
    backups: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    tool = fake / "pg_dump"
    tool.write_text("#!/bin/sh\necho 'pg_dump (PostgreSQL) 99.1'\n")
    tool.chmod(0o755)
    monkeypatch.setattr(settings, "pg_bin_dir", fake)
    with pytest.raises(cli.CliError, match="versi 99 tidak cocok"):
        cli.run_backup()


def test_upgrade_refuses_during_exams_then_backs_up(
    backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "active_attempts", lambda db: 1)
    with pytest.raises(cli.CliError, match="ujian sedang berjalan"):
        cli.upgrade()
    monkeypatch.setattr(backup, "active_attempts", lambda db: 0)
    result = cli.upgrade()
    assert result["to_rev"] == "0007"
    (job,) = cli.list_backups()
    assert job["trigger"] == "PRE_UPGRADE" and job["status"] == "VERIFIED"


def test_cli_retention_and_service_action_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    assert cli.main(["set-retention", "--hour=1", "--keep-daily=7",
                     "--keep-manual-days=30", "--reason=pendek"]) == 1  # fmt: skip
    values = cli.set_retention(1, 7, 30, "Rapat kebijakan sekolah")
    assert values["backup_keep_daily"] == 7
    assert cli.status()["settings"]["backup_hour"] == 1
    monkeypatch.setattr(backup, "active_attempts", lambda db: 4)
    with pytest.raises(cli.CliError, match="4 ujian"):
        cli.service_action("STOP", "")
    cli.service_action("STOP", "Server hang, diputuskan kepala sekolah")
    cli.service_action("START", "")
    with engine.connect() as db:
        actions = list(
            db.scalars(
                text("""
                select action from audit_events
                where action like 'SERVICE_%' or action = 'OPS_SETTINGS_CHANGED'
                order by created_at
                """)
            )
        )
    assert actions == ["OPS_SETTINGS_CHANGED", "SERVICE_STOP", "SERVICE_START"]
