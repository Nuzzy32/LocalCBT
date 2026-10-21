"""Operasional: health, backup, retensi, preflight server, probe jaringan ujian (M8).

Restore TIDAK lewat HTTP: memulihkan DB yang sedang dipakai service tidak aman. Restore memakai
`python -m app.cli restore` (dipanggil wizard Control Center) ke DB baru, lalu service dialihkan.
"""

import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import socket
import ssl
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Connection, text

from app import backup
from app.auth import CurrentUser, LoginRateLimiter, require_roles
from app.config import settings
from app.db import DB, audit
from app.errors import ApiError

router = APIRouter(prefix="/api/v1/ops", tags=["Operations"])
Admin = Annotated[CurrentUser, Depends(require_roles("ADMIN"))]
NETWORK = UUID(int=0)  # target_id audit untuk kejadian tingkat jaringan
DISK_WARNING, DISK_CRITICAL = 0.15, 0.05
PROBE_VALID = timedelta(days=7)
probe_limiter = LoginRateLimiter(per_user=10, per_ip=10, window=600)


# ---- Health ---------------------------------------------------------------------


def disk_status(paths: list[Path]) -> tuple[str, float | None]:
    """Status terburuk dari partisi yang dipakai. Tidak bisa dibaca = CRITICAL, bukan OK."""
    worst: float | None = None
    for p in paths:
        try:
            p.mkdir(parents=True, exist_ok=True)
            u = shutil.disk_usage(p)
        except OSError:
            return "CRITICAL", None
        free = u.free / u.total
        worst = free if worst is None else min(worst, free)
    if worst is None or worst < DISK_CRITICAL:
        return "CRITICAL", worst
    return ("WARNING" if worst < DISK_WARNING else "OK"), worst


def _same_device(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def health_data(db: Connection | None) -> dict[str, Any]:
    disk, free = disk_status([Path(settings.media_dir), Path(settings.backup_dir)])
    out: dict[str, Any] = {
        "server_status": "OK",
        "database_status": "DOWN",
        "disk_status": disk,
        "disk_free_ratio": None if free is None else round(free, 4),
        "last_verified_backup_at": None,
        "last_backup": None,
        "active_attempts": None,
        "backup_passphrase_set": len(settings.backup_passphrase) >= 12,
        "backup_same_disk_as_media": _same_device(
            Path(settings.backup_dir), Path(settings.media_dir)
        ),
    }
    if db is None:
        out["server_status"] = "DEGRADED"
        return out
    out["database_status"] = "OK"
    out["last_verified_backup_at"] = db.scalar(
        text("select max(verified_at) from backup_jobs where status = 'VERIFIED'")
    )
    last = (
        db.execute(
            text("""
            select id, trigger, status, error, created_at, verified_at
            from backup_jobs order by created_at desc limit 1
            """)
        )
        .mappings()
        .first()
    )
    out["last_backup"] = dict(last) if last else None
    out["active_attempts"] = backup.active_attempts(db)
    if disk != "OK" or not out["backup_passphrase_set"]:
        out["server_status"] = "DEGRADED"
    return out


@router.get("/health")
def ops_health(_: Admin, db: DB) -> dict[str, Any]:
    return health_data(db)


# ---- Backup ---------------------------------------------------------------------


@router.get("/backups")
def list_backups(_: Admin, db: DB) -> list[dict[str, Any]]:
    rows = db.execute(
        text("""
        select id, trigger, status, size_bytes, alembic_rev, error, created_at, started_at,
          verified_at, restore_verified_at, pruned_at
        from backup_jobs order by created_at desc limit 100
        """)
    ).mappings()
    return [dict(r) for r in rows]


@router.post("/backups", status_code=202)
def create_manual_backup(user: Admin, db: DB) -> dict[str, Any]:
    if db.scalar(text("select 1 from backup_jobs where status in ('QUEUED', 'RUNNING')")):
        raise ApiError(409, "BACKUP_BUSY", "Backup lain sedang antre atau berjalan.")
    job_id = backup.queue_backup(db, "MANUAL", user.id)
    audit(db, user.id, "BACKUP_REQUESTED", "backup", job_id)
    return {"job_id": str(job_id), "status": "QUEUED"}


class OpsSettingsIn(BaseModel):
    backup_hour: int = Field(ge=0, le=23)
    backup_keep_daily: int = Field(ge=1, le=365)
    backup_keep_manual_days: int = Field(ge=1, le=3650)
    reason: str = Field(min_length=10, max_length=500)


_SETTINGS_COLS = "backup_hour, backup_keep_daily, backup_keep_manual_days, updated_at"


@router.get("/settings")
def get_settings(_: Admin, db: DB) -> dict[str, Any]:
    return dict(db.execute(text(f"select {_SETTINGS_COLS} from ops_settings")).mappings().one())  # noqa: S608


@router.put("/settings")
def put_settings(body: OpsSettingsIn, user: Admin, db: DB) -> dict[str, Any]:
    # Masa simpan memengaruhi penghapusan data (FR-ADM-06): wajib alasan dan diaudit.
    before = get_settings(user, db)
    values = body.model_dump(exclude={"reason"})
    db.execute(
        text("""
        update ops_settings set backup_hour = :backup_hour,
          backup_keep_daily = :backup_keep_daily,
          backup_keep_manual_days = :backup_keep_manual_days,
          updated_by = :uid, updated_at = now()
        """),
        {**values, "uid": user.id},
    )
    old = {k: before[k] for k in values}
    audit(db, user.id, "OPS_SETTINGS_CHANGED", "ops_settings", NETWORK, body.reason,
          {"before": old, "after": values})  # fmt: skip
    return get_settings(user, db)


# ---- Preflight server -------------------------------------------------------------

Status = Literal["OK", "WARNING", "FAILED", "UNTESTED"]


def _check(cid: str, status: Status, detail: str) -> dict[str, str]:
    return {"id": cid, "status": status, "detail": detail}


def _dns_check(host: str) -> dict[str, str]:
    try:
        addrs = {str(a[4][0]) for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return _check("dns", "FAILED", f"{host} tidak dapat di-resolve dari server.")
    return _check("dns", "OK", f"{host} → {', '.join(sorted(addrs))}")


def _tls_check(host: str) -> dict[str, str]:
    ctx = ssl.create_default_context()
    try:
        with (
            socket.create_connection((host, 443), timeout=3) as sock,
            ctx.wrap_socket(sock, server_hostname=host) as tls,
        ):
            cert = tls.getpeercert() or {}
    except ssl.SSLCertVerificationError as e:
        return _check("https", "FAILED", f"Sertifikat tidak dipercaya: {e.verify_message}")
    except OSError as e:
        return _check("https", "FAILED", f"HTTPS {host}:443 tidak terjangkau ({e}).")
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(str(cert["notAfter"])), UTC)
    days = (expires - datetime.now(UTC)).days
    status: Status = "FAILED" if days < 0 else "WARNING" if days < 14 else "OK"
    return _check("https", status, f"Sertifikat berlaku sampai {expires:%Y-%m-%d} ({days} hari).")


def network_verdict(reports: list[dict[str, Any]], now: datetime) -> dict[str, str]:
    """Probe dari perangkat siswa, satu putaran link probe. 'OK' hanya bila ada laporan dari
    subnet ujian < 7 hari dan SEMUA laporan putaran itu: kontrol lokal lolos & semua target
    terblokir. Diambil yang terburuk: laporan palsu "terblokir" tidak bisa menutupi laporan
    asli "terjangkau" (M9-02). Selain itu tidak pernah hijau."""
    if not settings.exam_subnets:
        return _check("wan_blocked", "UNTESTED", "Subnet jaringan ujian belum diatur.")
    fresh = [r for r in reports if now - r["created_at"] <= PROBE_VALID]
    if not fresh:
        return _check("wan_blocked", "UNTESTED", "Belum ada probe dari jaringan ujian (7 hari).")
    for r in fresh:
        reachable = [t for t, x in r["metadata"]["results"].items() if x.get("reachable")]
        if reachable:
            return _check(
                "wan_blocked",
                "FAILED",
                f"Internet MASIH terjangkau dari {r['metadata']['ip']}: {', '.join(reachable)}",
            )
    if not all(r["metadata"].get("control_ok") for r in fresh):
        return _check("wan_blocked", "FAILED", "Probe tidak sah: portal lokal tidak terjangkau.")
    last = max(fresh, key=lambda r: r["created_at"])
    return _check(
        "wan_blocked",
        "OK",
        f"HTTPS ke internet terblokir ({len(fresh)} laporan, terakhir dari "
        f"{last['metadata']['ip']} pada {last['created_at']:%Y-%m-%d %H:%M}).",
    )


def probe_round(db: Connection) -> list[dict[str, Any]]:
    """Semua laporan sah (subnet ujian) dari link probe terbaru yang sudah punya laporan."""
    rows = db.execute(
        text("""
        with latest as (
          select metadata ->> 'link_id' as link_id from audit_events
          where action = 'NETWORK_PROBE' and target_type = 'network'
            and (metadata ->> 'in_exam_subnet')::boolean and metadata ? 'link_id'
          order by created_at desc limit 1)
        select metadata, created_at from audit_events
        where action = 'NETWORK_PROBE' and (metadata ->> 'in_exam_subnet')::boolean
          and metadata ->> 'link_id' = (select link_id from latest)
        """)
    ).mappings()
    return [dict(r) for r in rows]


PROBE_LINK_TTL = timedelta(hours=24)


def _key_hash(k: str) -> str:
    return hashlib.sha256(k.encode()).hexdigest()


def create_probe_link(db: Connection, actor_id: UUID | None) -> dict[str, Any]:
    """Link probe sekali-putaran untuk dibuka admin di perangkat SSID ujian. Hanya hash
    kuncinya yang disimpan; laporan tanpa kunci sah ditolak (M9-02)."""
    k = secrets.token_urlsafe(16)
    audit(db, actor_id, "NETWORK_PROBE_LINK", "network", NETWORK,
          metadata={"k_hash": _key_hash(k)})  # fmt: skip
    host = settings.public_host
    return {
        "url": f"https://{host}/api/v1/ops/probe?k={k}" if host else None,
        "path": f"/api/v1/ops/probe?k={k}",
        "valid_hours": int(PROBE_LINK_TTL.total_seconds() // 3600),
    }


CLOCK_SKEW_MAX = 5


def clock_check(db: Connection | None) -> dict[str, str]:
    """NFR-14. Jam DB & jam proses API harus sama: batas waktu ujian dihitung dari jam DB,
    izin mulai/token dari jam proses. Sinkron NTP tetap harus dicek operator."""
    if db is None:
        return _check("clock", "UNTESTED", "Database mati.")
    skew = abs(float(db.scalar(text("select extract(epoch from now())")) or 0) - time.time())
    if skew > CLOCK_SKEW_MAX:
        return _check("clock", "FAILED", f"Jam database berselisih {skew:.0f} dtk dari jam server.")
    return _check(
        "clock", "WARNING",
        f"Jam DB & server cocok (selisih {skew:.1f} dtk). Pastikan juga tersinkron NTP.",
    )  # fmt: skip


def run_preflight(db: Connection | None) -> list[dict[str, str]]:
    health = health_data(db)
    checks = [
        _check("database", "OK" if db else "FAILED", "Database terhubung." if db else "DB mati."),
        _check(
            "disk",
            {"OK": "OK", "WARNING": "WARNING"}.get(health["disk_status"], "FAILED"),  # type: ignore[arg-type]
            f"Ruang kosong terkecil: {health['disk_free_ratio']}",
        ),
    ]
    if not health["backup_passphrase_set"]:
        checks.append(_check("backup", "FAILED", "Kata sandi enkripsi backup belum diatur."))
    elif (last := health["last_verified_backup_at"]) is None:
        checks.append(_check("backup", "FAILED", "Belum ada backup terverifikasi."))
    else:
        age = datetime.now(UTC) - last
        status: Status = "OK" if age < backup.OVERDUE else "WARNING"
        checks.append(
            _check("backup", status, f"Backup terverifikasi terakhir {last:%Y-%m-%d %H:%M}.")
        )
    if health["backup_same_disk_as_media"]:
        checks.append(_check("backup_disk", "WARNING", "Backup satu disk dengan data utama."))
    try:
        backup.pg_tool("pg_dump", db)
        backup.pg_tool("pg_restore", db)
        checks.append(_check("pg_tools", "OK", "pg_dump & pg_restore tersedia, versi cocok."))
    except backup.BackupError as e:
        checks.append(_check("pg_tools", "FAILED", str(e)))
    if settings.public_host:
        checks += [_dns_check(settings.public_host), _tls_check(settings.public_host)]
    else:
        checks.append(_check("https", "UNTESTED", "PUBLIC_HOST belum diatur."))
    checks.append(clock_check(db))
    if db is not None:
        checks.append(network_verdict(probe_round(db), datetime.now(UTC)))
    return checks


@router.post("/preflight")
def preflight(user: Admin, db: DB) -> dict[str, Any]:
    # Sinkron (~3 detik) alih-alih job 202: hasil langsung terlihat operator.
    checks = run_preflight(db)
    audit(db, user.id, "PREFLIGHT_SERVER", "network", NETWORK, metadata={"checks": checks})
    return {"checks": checks, "ran_at": datetime.now(UTC)}


# ---- Probe jaringan ujian (dibuka dari perangkat siswa, tanpa login) -------------------

PROBE_TARGETS = {
    "ipv4_cloudflare": "https://1.1.1.1/",
    "ipv6_cloudflare": "https://[2606:4700:4700::1111]/",
    "google": "https://www.google.com/generate_204",
    "ipv6_only_dns": "https://ipv6.google.com/",
    "chatgpt": "https://chatgpt.com/",
}
TargetId = Literal["ipv4_cloudflare", "ipv6_cloudflare", "google", "ipv6_only_dns", "chatgpt"]

_PROBE_HTML = """<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cek Jaringan Ujian</title>
<style>body{font:16px system-ui,sans-serif;max-width:32rem;margin:2rem auto;padding:0 1rem}
li{margin:.3rem 0}.ok{color:#0a6b2e}.bad{color:#b3261e}</style></head>
<body><h1>Cek Jaringan Ujian</h1>
<p>Halaman ini menguji apakah internet tertutup dari perangkat ini. Tidak ada data pribadi
yang dikirim.</p><ul id="out"><li>Memeriksa…</li></ul><p id="done"></p>
<script src="/api/v1/ops/probe.js"></script></body></html>"""

_PROBE_JS = """(async () => {
  const targets = %s;
  const out = document.getElementById("out");
  const hit = async (url, opts) => {
    const ctl = new AbortController(), t0 = performance.now();
    const timer = setTimeout(() => ctl.abort(), 4000);
    try { await fetch(url, {...opts, signal: ctl.signal, cache: "no-store"});
      return {reachable: true, ms: Math.round(performance.now() - t0)}; }
    catch { return {reachable: false, ms: Math.round(performance.now() - t0)}; }
    finally { clearTimeout(timer); }
  };
  const control = await hit("/api/v1/healthz", {});
  const results = {};
  await Promise.all(Object.entries(targets).map(async ([id, url]) => {
    results[id] = await hit(url, {mode: "no-cors"}); }));
  out.innerHTML = "";
  const row = (label, bad) => { const li = document.createElement("li");
    li.textContent = label; li.className = bad ? "bad" : "ok"; out.append(li); };
  row(control.reachable ? "Portal lokal: terjangkau" : "Portal lokal: TIDAK terjangkau",
      !control.reachable);
  for (const [id, r] of Object.entries(results))
    row(`${id}: ${r.reachable ? "TERJANGKAU (internet terbuka!)" : "terblokir"}`, r.reachable);
  const res = await fetch("/api/v1/ops/probe-reports", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({control_ok: control.reachable, results,
      k: new URLSearchParams(location.search).get("k") || ""})});
  document.getElementById("done").textContent = res.ok
    ? "Hasil terkirim ke operator. Terima kasih."
    : "Hasil gagal dikirim (link probe tidak sah/kedaluwarsa? minta link baru ke operator).";
})();"""


@router.get("/probe", include_in_schema=False)
def probe_page() -> HTMLResponse:
    # CSP khusus: halaman ini harus boleh mencoba menghubungi internet (Caddy memakai `?CSP`).
    csp = (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
        "connect-src 'self' https:"
    )
    return HTMLResponse(_PROBE_HTML, headers={"Content-Security-Policy": csp})


@router.get("/probe.js", include_in_schema=False)
def probe_js() -> Response:
    return Response(_PROBE_JS % json.dumps(PROBE_TARGETS), media_type="text/javascript")


class ProbeResult(BaseModel):
    reachable: bool
    ms: int = Field(ge=0, le=60000)


class ProbeReport(BaseModel):
    control_ok: bool
    results: dict[TargetId, ProbeResult]
    k: str = Field(min_length=10, max_length=64)

    @model_validator(mode="after")
    def all_targets(self) -> "ProbeReport":
        # Laporan parsial (mis. hanya target yang memang terblokir) tidak boleh dihitung.
        if set(self.results) != set(PROBE_TARGETS):
            raise ValueError("Laporan probe harus memuat semua target.")
        return self


def in_exam_subnet(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in ipaddress.ip_network(n, strict=False) for n in settings.exam_subnets)
    except ValueError:
        return False


@router.post("/probe-reports", status_code=201)
def probe_report(body: ProbeReport, request: Request, db: DB) -> dict[str, Any]:
    ip = request.client.host if request.client else "-"
    if wait := probe_limiter.acquire("probe", ip):
        raise ApiError(429, "RATE_LIMITED", "Terlalu sering.", {"Retry-After": str(wait)})
    link_id = db.scalar(
        text("""
        select id from audit_events
        where action = 'NETWORK_PROBE_LINK' and metadata ->> 'k_hash' = :h
          and created_at > now() - make_interval(secs => :ttl)
        """),
        {"h": _key_hash(body.k), "ttl": int(PROBE_LINK_TTL.total_seconds())},
    )
    if link_id is None:
        raise ApiError(403, "PROBE_LINK_INVALID", "Link probe tidak sah atau kedaluwarsa.")
    meta = {
        "link_id": str(link_id),
        "ip": ip,
        "in_exam_subnet": in_exam_subnet(ip),
        "control_ok": body.control_ok,
        "results": {k: v.model_dump() for k, v in body.results.items()},
    }
    audit(db, None, "NETWORK_PROBE", "network", NETWORK, metadata=meta)
    return {"in_exam_subnet": meta["in_exam_subnet"]}


def network_data(db: Connection) -> dict[str, Any]:
    attest = (
        db.execute(
            text("""
            select reason, metadata, created_at from audit_events
            where action = 'NETWORK_ATTESTED' order by created_at desc limit 1
            """)
        )
        .mappings()
        .first()
    )
    return {
        "probe": network_verdict(probe_round(db), datetime.now(UTC)),
        "last_attestation": dict(attest) if attest else None,
    }


@router.post("/probe-links", status_code=201)
def new_probe_link(user: Admin, db: DB) -> dict[str, Any]:
    return create_probe_link(db, user.id)


@router.get("/network")
def network_status(_: Admin, db: DB) -> dict[str, Any]:
    return network_data(db)
