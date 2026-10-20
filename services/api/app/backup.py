"""Backup terenkripsi & terverifikasi, restore ke DB baru (BR-22, FR-OPS-05/06, NFR-11).

Satu backup = folder <backup_dir>/<waktu>-<trigger>/:
  manifest.json  metadata: revisi skema, jumlah baris, hash db.dump, daftar media. Tanpa data siswa.
  data.lcbk      tar (db.dump + media/) terenkripsi AES-256-GCM per potongan 1 MiB;
                 kunci = scrypt(passphrase, salt). Potongan terakhir bertanda final (anti-potong).
Status VERIFIED hanya setelah arsip didekripsi ulang, semua hash cocok, dan pg_restore --list lulus.
Restore tidak pernah menimpa DB yang sedang dipakai: selalu ke DB baru, lalu dicocokkan.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import struct
import subprocess  # noqa: S404 — pg_dump/pg_restore, argumen list tanpa shell
import tarfile
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Connection, create_engine, make_url, text

from app.config import settings
from app.db import engine

log = logging.getLogger("localcbt.backup")

FORMAT = "localcbt-backup/1"
MAGIC = b"LCBK1\n"
CHUNK = 1 << 20
LOCK_KEY = 0x4C434231  # advisory lock: satu proses backup/restore pada satu waktu
COUNT_TABLES = (
    "users",
    "classes",
    "questions",
    "media_assets",
    "exams",
    "exam_attempts",
    "student_answers",
    "question_scores",
    "audit_events",
)
OVERDUE = timedelta(hours=36)
_DB_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_MEDIA_MEMBER = re.compile(r"^media/([0-9a-f]{2})/(\1[0-9a-f]{62})$")


class BackupError(Exception):
    pass


# ---- Enkripsi stream ------------------------------------------------------------


def _key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        passphrase.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 2**20, dklen=32
    )


def _aad(idx: int, final: bool) -> bytes:
    return struct.pack(">IB", idx, final)


class Encryptor:
    def __init__(self, out: IO[bytes], passphrase: str) -> None:
        salt, self._prefix = os.urandom(16), os.urandom(8)
        self._aes = AESGCM(_key(passphrase, salt))
        self._out, self._buf, self._idx = out, bytearray(), 0
        out.write(MAGIC + salt + self._prefix)

    def write(self, data: bytes) -> int:
        self._buf += data
        while len(self._buf) > CHUNK:
            self._frame(bytes(self._buf[:CHUNK]), final=False)
            del self._buf[:CHUNK]
        return len(data)

    def _frame(self, plain: bytes, final: bool) -> None:
        nonce = self._prefix + struct.pack(">I", self._idx)
        ct = self._aes.encrypt(nonce, plain, _aad(self._idx, final))
        self._out.write(struct.pack(">I", len(ct)) + ct)
        self._idx += 1

    def finish(self) -> None:
        self._frame(bytes(self._buf), final=True)


class Decryptor:
    def __init__(self, src: IO[bytes], passphrase: str) -> None:
        head = src.read(len(MAGIC) + 24)
        if len(head) != len(MAGIC) + 24 or not head.startswith(MAGIC):
            raise BackupError("Berkas backup tidak dikenali.")
        salt, self._prefix = head[len(MAGIC) : len(MAGIC) + 16], head[-8:]
        self._aes = AESGCM(_key(passphrase, salt))
        self._src, self._buf, self._idx, self._done = src, bytearray(), 0, False

    def _next(self) -> bytes:
        raw = self._src.read(4)
        if len(raw) != 4:
            raise BackupError("Arsip backup terpotong.")
        (size,) = struct.unpack(">I", raw)
        ct = self._src.read(size) if size <= CHUNK + 16 else b""
        if not ct or len(ct) != size:
            raise BackupError("Arsip backup rusak atau terpotong.")
        nonce = self._prefix + struct.pack(">I", self._idx)
        for final in (False, True):
            try:
                plain = self._aes.decrypt(nonce, ct, _aad(self._idx, final))
            except InvalidTag:
                continue
            self._idx += 1
            self._done = final
            if final and self._src.read(1):
                raise BackupError("Ada data asing di akhir arsip backup.")
            return plain
        raise BackupError("Kata sandi backup salah atau arsip rusak.")

    def read(self, n: int = -1) -> bytes:
        while not self._done and (n < 0 or len(self._buf) < n):
            self._buf += self._next()
        if n < 0:
            n = len(self._buf)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def finish(self) -> None:
        self.read()
        if not self._done:
            raise BackupError("Arsip backup terpotong.")


# ---- Postgres tools -------------------------------------------------------------


def pg_tool(name: str, db: Connection | None = None) -> str:
    """Path pg_dump/pg_restore. Dengan db: versi mayor klien wajib sama dengan server, karena
    pg_restore yang lebih baru mengirim perintah yang belum dikenal server lama."""
    path = str(settings.pg_bin_dir) if settings.pg_bin_dir else None
    found = shutil.which(name, path=path)
    if not found:
        raise BackupError(f"{name} tidak ditemukan. Pasang klien PostgreSQL atau atur PG_BIN_DIR.")
    if db is not None:
        out = subprocess.run([found, "--version"], capture_output=True, text=True, check=False)  # noqa: S603
        m = re.search(r"(\d+)\.", out.stdout)
        client = int(m[1]) if m else 0
        server = int(db.scalar(text("show server_version_num")) or 0) // 10000
        if client != server:
            raise BackupError(
                f"{name} versi {client} tidak cocok dengan server PostgreSQL {server}. "
                f"Pasang klien PostgreSQL {server} lalu atur PG_BIN_DIR."
            )
    return found


def _pg_env(url: str) -> dict[str, str]:
    # Kredensial lewat env, tidak pernah di argv (terlihat di daftar proses).
    u = make_url(url)
    return {
        **os.environ,
        "PGHOST": u.host or "127.0.0.1",
        "PGPORT": str(u.port or 5432),
        "PGUSER": u.username or "",
        "PGPASSWORD": u.password or "",
        "PGDATABASE": u.database or "",
        "PGCONNECT_TIMEOUT": "5",
    }


def _run(args: list[str], env: dict[str, str]) -> None:
    proc = subprocess.run(args, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        raise BackupError(f"{Path(args[0]).name} gagal: {tail}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _counts(db: Connection) -> dict[str, int]:
    return {t: int(db.scalar(text(f"select count(*) from {t}")) or 0) for t in COUNT_TABLES}  # noqa: S608


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _open_private(path: Path) -> IO[bytes]:
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")


# ---- Membuat & memverifikasi ----------------------------------------------------


def create_backup(folder: Path, passphrase: str) -> dict[str, Any]:
    """Tulis data.lcbk + manifest.json ke folder baru. Snapshot DB konsisten dengan daftar media."""
    if len(passphrase) < 12:
        raise BackupError("Kata sandi backup belum diatur (min. 12 karakter).")
    with engine.connect() as db:
        pg_dump = pg_tool("pg_dump", db)
    _private_dir(folder.parent)
    folder.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(dir=folder.parent, prefix=".tmp-") as tmp:
        dump = Path(tmp) / "db.dump"
        snap_engine = engine.execution_options(isolation_level="REPEATABLE READ")
        with snap_engine.connect() as snap, snap.begin():
            snapshot = snap.scalar(text("select pg_export_snapshot()"))
            counts = _counts(snap)
            media = list(snap.scalars(text("select sha256 from media_assets order by sha256")))
            rev = snap.scalar(text("select version_num from alembic_version"))
            server_version = snap.scalar(text("show server_version"))
            env = _pg_env(settings.database_url)
            _run([pg_dump, "-Fc", "--snapshot", str(snapshot), "-f", str(dump)], env)
        dump_sha, dump_size = _sha256(dump), dump.stat().st_size
        with _open_private(folder / "data.lcbk") as out:
            enc = Encryptor(out, passphrase)
            with tarfile.open(fileobj=enc, mode="w|") as tar:  # type: ignore[call-overload]
                tar.add(dump, arcname="db.dump")
                for sha in media:
                    src = Path(settings.media_dir) / sha[:2] / sha
                    if not src.is_file():
                        raise BackupError(f"Berkas media hilang: {sha[:12]}…")
                    tar.add(src, arcname=f"media/{sha[:2]}/{sha}")
            enc.finish()
    manifest = {
        "format": FORMAT,
        "created_at": datetime.now().astimezone().isoformat(),
        "alembic_rev": rev,
        "pg_server_version": server_version,
        "counts": counts,
        "db_dump": {"sha256": dump_sha, "size": dump_size},
        "media": media,
    }
    with _open_private(folder / "manifest.json") as f:
        f.write(json.dumps(manifest, indent=1).encode())
    return manifest


def read_manifest(folder: Path) -> dict[str, Any]:
    try:
        manifest: dict[str, Any] = json.loads((folder / "manifest.json").read_text())
    except (OSError, ValueError) as e:
        raise BackupError("manifest.json tidak ada atau rusak.") from e
    if manifest.get("format") != FORMAT:
        raise BackupError("Format backup tidak dikenali.")
    return manifest


def unpack(folder: Path, passphrase: str, workdir: Path, media_out: Path | None) -> dict[str, Any]:
    """Dekripsi & cek integritas. db.dump ditulis ke workdir; media ke media_out bila diberikan."""
    manifest = read_manifest(folder)
    seen: set[str] = set()
    dump_sha = None
    with (folder / "data.lcbk").open("rb") as src:
        dec = Decryptor(src, passphrase)
        with tarfile.open(fileobj=dec, mode="r|") as tar:  # type: ignore[call-overload]
            for member in tar:
                data = tar.extractfile(member) if member.isreg() else None
                if data is None:
                    raise BackupError(f"Isi arsip tidak dikenal: {member.name}")
                h = hashlib.sha256()
                if member.name == "db.dump":
                    with _open_private(workdir / "db.dump") as out:
                        while chunk := data.read(CHUNK):
                            h.update(chunk)
                            out.write(chunk)
                    dump_sha = h.hexdigest()
                    continue
                m = _MEDIA_MEMBER.match(member.name)
                if not m:
                    raise BackupError(f"Isi arsip tidak dikenal: {member.name}")
                content = data.read()
                if hashlib.sha256(content).hexdigest() != m[2]:
                    raise BackupError(f"Media rusak: {m[2][:12]}…")
                seen.add(m[2])
                if media_out is not None:
                    dest = media_out / m[1] / m[2]
                    if not dest.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(content)
        dec.finish()
    if dump_sha != manifest["db_dump"]["sha256"]:
        raise BackupError("db.dump tidak cocok dengan manifest.")
    if seen != set(manifest["media"]):
        raise BackupError("Daftar media tidak cocok dengan manifest.")
    return manifest


def verify_backup(folder: Path, passphrase: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(dir=folder.parent, prefix=".verify-") as tmp:
        manifest = unpack(folder, passphrase, Path(tmp), None)
        with engine.connect() as db:
            pg_restore = pg_tool("pg_restore", db)
        _run([pg_restore, "--list", str(Path(tmp) / "db.dump")], dict(os.environ))
    return manifest


# ---- Restore ----------------------------------------------------------------------


def restore_backup(
    folder: Path,
    passphrase: str,
    target_db: str,
    media_out: Path,
    admin_url: str | None = None,
) -> dict[str, Any]:
    """Pulihkan ke DB BARU target_db lalu cocokkan jumlah baris & revisi dengan manifest."""
    if not _DB_NAME.match(target_db):
        raise BackupError("Nama database tujuan tidak valid (huruf kecil, angka, garis bawah).")
    app_url = make_url(settings.database_url)
    admin = create_engine(
        make_url(admin_url or settings.database_url).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as conn:
            pg_restore = pg_tool("pg_restore", conn)
            if conn.scalar(text("select 1 from pg_database where datname = :d"), {"d": target_db}):
                raise BackupError(f"Database {target_db} sudah ada. Restore tidak menimpa data.")
            owner = (app_url.username or "").replace('"', '""')
            conn.execute(text(f'create database "{target_db}" owner "{owner}"'))
        target_url = app_url.set(database=target_db).render_as_string(hide_password=False)
        try:
            with tempfile.TemporaryDirectory(dir=folder.parent, prefix=".restore-") as tmp:
                manifest = unpack(folder, passphrase, Path(tmp), media_out)
                args = [pg_restore, "--no-owner", "--no-privileges", "--exit-on-error"]
                _run([*args, "-d", target_db, str(Path(tmp) / "db.dump")], _pg_env(target_url))
            target = create_engine(target_url)
            try:
                with target.connect() as conn:
                    counts = _counts(conn)
                    rev = conn.scalar(text("select version_num from alembic_version"))
            finally:
                target.dispose()
            if counts != manifest["counts"] or rev != manifest["alembic_rev"]:
                raise BackupError(
                    f"Hasil restore tidak cocok dengan manifest: {counts} rev {rev} vs "
                    f"{manifest['counts']} rev {manifest['alembic_rev']}"
                )
            return manifest
        except BaseException:
            drop_database(target_db, admin_url)
            raise
    finally:
        admin.dispose()


def drop_database(name: str, admin_url: str | None = None) -> None:
    if not _DB_NAME.match(name) or name == make_url(settings.database_url).database:
        raise BackupError("Menolak menghapus database ini.")
    admin = create_engine(
        make_url(admin_url or settings.database_url).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as conn:
            conn.execute(text(f'drop database if exists "{name}" with (force)'))
    finally:
        admin.dispose()


# ---- Job & jadwal ---------------------------------------------------------------


def active_attempts(db: Connection) -> int:
    return int(
        db.scalar(
            text("select count(*) from exam_attempts where state in ('IN_PROGRESS', 'PAUSED')")
        )
        or 0
    )


def daily_due(
    now: datetime,
    backup_hour: int,
    last_daily_at: datetime | None,
    last_verified_at: datetime | None,
    active: int,
) -> bool:
    """Backup harian: sekali sehari setelah jam backup_hour bila tidak ada ujian berjalan.
    Bila backup terverifikasi terakhir > 36 jam (server sering mati malam hari), paksa,
    dicoba ulang paling sering sejam sekali."""
    if last_verified_at is None or now - last_verified_at > OVERDUE:
        return last_daily_at is None or now - last_daily_at > timedelta(hours=1)
    today = last_daily_at is not None and last_daily_at.date() == now.date()
    return not today and now.hour >= backup_hour and active == 0


@contextmanager
def ops_lock() -> Iterator[bool]:
    """True bila lock didapat. Dipegang selama backup/restore oleh service maupun CLI."""
    with engine.connect() as conn:
        got = bool(conn.scalar(text("select pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}))
        conn.commit()
        try:
            yield got
        finally:
            if got:
                conn.execute(text("select pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                conn.commit()


def queue_backup(db: Connection, trigger: str, requested_by: UUID | None) -> UUID:
    job_id: UUID = db.scalar(
        text("insert into backup_jobs (trigger, requested_by) values (:t, :u) returning id"),
        {"t": trigger, "u": requested_by},
    )
    return job_id


def _fail_stale() -> None:
    # Dipanggil sambil memegang ops_lock: RUNNING yang tersisa pasti dari proses yang mati.
    with engine.begin() as db:
        db.execute(
            text("""
            update backup_jobs set status = 'FAILED',
              error = 'Terhenti: proses berhenti sebelum backup selesai.'
            where status = 'RUNNING'
            """)
        )


def _queue_daily_if_due() -> None:
    with engine.begin() as db:
        row = db.execute(
            text("""
            select (select backup_hour from ops_settings) as hour,
              (select max(created_at) from backup_jobs where trigger = 'DAILY') as last_daily,
              (select max(verified_at) from backup_jobs where status = 'VERIFIED') as last_ok,
              now() as now
            """)
        ).one()
        now = row.now.astimezone()
        if daily_due(
            now,
            row.hour,
            row.last_daily and row.last_daily.astimezone(),
            row.last_ok and row.last_ok.astimezone(),
            active_attempts(db),
        ):
            db.execute(
                text("""
                insert into backup_jobs (trigger) values ('DAILY') on conflict do nothing
                """)
            )


def run_job(job_id: UUID) -> str:
    """Jalankan satu job QUEUED (pemanggil memegang ops_lock). Mengembalikan status akhir."""
    with engine.begin() as db:
        trigger = db.scalar(
            text("""
            update backup_jobs set status = 'RUNNING', started_at = now()
            where id = :id and status = 'QUEUED' returning trigger
            """),
            {"id": job_id},
        )
    if trigger is None:
        return "SKIPPED"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = Path(settings.backup_dir).resolve() / f"{stamp}-{trigger.lower()}"
    try:
        manifest = create_backup(folder, settings.backup_passphrase)
        verify_backup(folder, settings.backup_passphrase)
    except Exception as e:
        shutil.rmtree(folder, ignore_errors=True)
        msg = str(e) if isinstance(e, BackupError) else f"{type(e).__name__}: {e}"
        log.error("backup failed", extra={"extra_fields": {"job": str(job_id), "error": msg}})
        with engine.begin() as db:
            db.execute(
                text("update backup_jobs set status = 'FAILED', error = :e where id = :id"),
                {"id": job_id, "e": msg[:2000]},
            )
        return "FAILED"
    size = sum(p.stat().st_size for p in folder.iterdir())
    with engine.begin() as db:
        db.execute(
            text("""
            update backup_jobs set status = 'VERIFIED', verified_at = now(), path = :p,
              alembic_rev = :r, size_bytes = :s
            where id = :id
            """),
            {"id": job_id, "p": str(folder), "r": manifest["alembic_rev"], "s": size},
        )
    log.info("backup verified", extra={"extra_fields": {"job": str(job_id), "bytes": size}})
    prune()
    return "VERIFIED"


def prune() -> list[str]:
    """Hapus backup di luar masa simpan. Backup terverifikasi terbaru tidak pernah dihapus."""
    with engine.begin() as db:
        rows = db.execute(
            text("""
            with s as (select * from ops_settings),
            ranked as (
              select j.id, j.path, j.trigger, j.verified_at,
                row_number() over (partition by j.trigger = 'DAILY'
                                   order by j.verified_at desc) as rn,
                row_number() over (order by j.verified_at desc) as overall
              from backup_jobs j
              where j.status = 'VERIFIED' and j.pruned_at is null)
            update backup_jobs b set pruned_at = now()
            from ranked r, s
            where b.id = r.id and r.overall > 1 and (
              (r.trigger = 'DAILY' and r.rn > s.backup_keep_daily)
              or (r.trigger <> 'DAILY'
                  and r.verified_at < now() - make_interval(days => s.backup_keep_manual_days)))
            returning b.path
            """)
        ).scalars()
        paths = [p for p in rows if p]
    root = Path(settings.backup_dir).resolve()
    for p in paths:
        if Path(p).resolve().parent == root:  # jangan pernah menghapus di luar backup_dir
            shutil.rmtree(p, ignore_errors=True)
    return paths


def tick() -> None:
    with ops_lock() as got:
        if not got:
            return
        _fail_stale()
        _queue_daily_if_due()
        with engine.connect() as db:
            job = db.scalar(
                text("select id from backup_jobs where status = 'QUEUED' order by created_at")
            )
        if job:
            run_job(job)


class BackupScheduler:
    """Thread terpisah dari sweeper: pg_dump yang lama tidak boleh menunda sweep jeda 5 detik."""

    INTERVAL = 30

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="backup", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.INTERVAL):
            try:
                tick()
            except Exception:
                log.exception("backup tick failed")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
