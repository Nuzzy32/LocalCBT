"""Login, sesi server-side, CSRF, rate limit, dan dependency otorisasi (default deny)."""

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.config import settings
from app.db import DB, audit
from app.errors import ApiError, forbidden

COOKIE = "localcbt_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_ph = PasswordHasher()  # Argon2id, parameter default argon2-cffi
_DUMMY_HASH = _ph.hash(secrets.token_urlsafe(16))
# Tanpa karakter mirip (0/o, 1/l/i) karena dibagikan di kertas kepada siswa.
_PW_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def generate_password(length: int = 10) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def _token_hash(token: str) -> str:
    # Hanya hash yang disimpan: dump DB tidak bisa dipakai untuk membajak sesi.
    return hashlib.sha256(token.encode()).hexdigest()


class LoginRateLimiter:
    # ponytail: memori per-proses, reset saat restart; pindah ke tabel DB bila uvicorn >1 worker.
    def __init__(self, per_user: int = 5, per_ip: int = 30, window: float = 300) -> None:
        self.per_user, self.per_ip, self.window = per_user, per_ip, window
        self._fails: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _keys(self, username: str, ip: str) -> list[tuple[str, int]]:
        # Kunci (username, ip): teman sekelas di perangkat lain tidak bisa mengunci akun siswa.
        return [(f"u:{username}|{ip}", self.per_user), (f"ip:{ip}", self.per_ip)]

    def retry_after(self, username: str, ip: str) -> int:
        now = time.monotonic()
        with self._lock:
            wait = 0.0
            for key, limit in self._keys(username, ip):
                fails = self._fails.get(key)
                if not fails:
                    continue
                while fails and fails[0] <= now - self.window:
                    fails.popleft()
                if len(fails) >= limit:
                    wait = max(wait, fails[0] + self.window - now)
            return int(wait) + 1 if wait else 0

    def fail(self, username: str, ip: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key, _ in self._keys(username, ip):
                self._fails.setdefault(key, deque()).append(now)

    def success(self, username: str, ip: str) -> None:
        with self._lock:
            self._fails.pop(self._keys(username, ip)[0][0], None)

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()


limiter = LoginRateLimiter()


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    username: str
    display_name: str
    roles: frozenset[str]
    csrf_token: str
    session_hash: str

    def has(self, *roles: str) -> bool:
        return not self.roles.isdisjoint(roles)

    def public(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "username": self.username,
            "display_name": self.display_name,
            "roles": sorted(self.roles),
        }


def session_user(db: Connection, token: str | None) -> CurrentUser | None:
    """Pengguna dari cookie sesi (tanpa cek CSRF). Dipakai HTTP dan WebSocket."""
    if not token:
        return None
    row = (
        db.execute(
            text("""
            select s.token_hash, s.csrf_token,
                   s.last_seen_at < now() - interval '60 seconds' as touch,
                   u.id, u.username, u.display_name,
                   array_remove(array_agg(r.role), null) as roles
            from sessions s
            join users u on u.id = s.user_id
            left join user_roles r on r.user_id = u.id
            where s.token_hash = :h and s.expires_at > now() and u.status = 'ACTIVE'
            group by s.token_hash, u.id
            """),
            {"h": _token_hash(token)},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    if row["touch"]:  # tulis paling sering 1x/menit, bukan tiap request
        db.execute(
            text("update sessions set last_seen_at = now() where token_hash = :h"),
            {"h": row["token_hash"]},
        )
    return CurrentUser(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        roles=frozenset(row["roles"]),
        csrf_token=row["csrf_token"],
        session_hash=row["token_hash"],
    )


def current_user(request: Request, db: DB) -> CurrentUser:
    token = request.cookies.get(COOKIE)
    if not token:
        raise ApiError(401, "UNAUTHENTICATED", "Silakan masuk terlebih dahulu.")
    user = session_user(db, token)
    if user is None:
        raise ApiError(401, "SESSION_EXPIRED", "Sesi berakhir. Silakan masuk kembali.")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get("x-csrf-token", "").encode()
        if not hmac.compare_digest(sent, user.csrf_token.encode()):
            raise ApiError(403, "CSRF_INVALID", "Permintaan ditolak. Muat ulang halaman.")
    return user


User = Annotated[CurrentUser, Depends(current_user)]


def require_roles(*roles: str) -> Callable[[CurrentUser], CurrentUser]:
    def dependency(user: User) -> CurrentUser:
        if not user.has(*roles):
            raise forbidden()
        return user

    return dependency


router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: DB) -> dict[str, Any]:
    ip = request.client.host if request.client else "-"
    username = body.username.strip().lower()
    wait = limiter.retry_after(username, ip)
    if wait:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "Terlalu banyak percobaan masuk. Coba lagi beberapa menit lagi.",
            {"Retry-After": str(wait)},
        )

    row = (
        db.execute(
            text("select id, password_hash, status from users where lower(username) = :u"),
            {"u": username},
        )
        .mappings()
        .first()
    )
    # Username tak dikenal tetap memverifikasi hash dummy: waktu respons tidak membocorkan akun.
    valid = verify_password(row["password_hash"] if row else _DUMMY_HASH, body.password)
    if row is None or not valid or row["status"] != "ACTIVE":
        limiter.fail(username, ip)
        raise ApiError(401, "INVALID_CREDENTIALS", "NIS/username atau kata sandi tidak sesuai.")

    user_id = row["id"]
    # Kunci baris user: dua login bersamaan tidak bisa sama-sama lolos cek sesi aktif.
    db.execute(text("select 1 from users where id = :id for update"), {"id": user_id})
    roles = set(
        db.scalars(text("select role from user_roles where user_id = :id"), {"id": user_id})
    )
    # Pindah perangkat disetujui pengawas: izin sekali pakai mengizinkan login ini meski sesi
    # lama masih aktif; sesi lama dicabut di bawah sehingga perangkat lama tidak bisa merebut.
    permitted = "STUDENT" in roles and db.scalar(
        text("""
        update exam_attempts set switch_permit_until = null
        where student_id = :id and switch_permit_until > now()
          and state in ('IN_PROGRESS', 'PAUSED')
        returning id
        """),
        {"id": user_id},
    )
    if "STUDENT" in roles and not permitted:
        # BR-21: selama attempt berjalan, sesi lama yang belum habis selalu memblokir; hanya
        # izin pengawas (atau reset sandi admin) yang membukanya. Di luar ujian, sesi yang diam
        # > stale dianggap ditinggal dan boleh diambil alih (diaudit).
        live = db.execute(
            text("""
            select last_seen_at > now() - make_interval(secs => :stale) as fresh,
                   exists (select 1 from exam_attempts where student_id = :id
                           and state in ('IN_PROGRESS', 'PAUSED')) as in_exam
            from sessions where user_id = :id and expires_at > now()
            order by last_seen_at desc limit 1
            """),
            {"id": user_id, "stale": settings.student_session_stale_seconds},
        ).first()
        if live and (live.fresh or live.in_exam):
            raise ApiError(
                409,
                "SESSION_ACTIVE",
                "Akun masih aktif pada perangkat lain. Hubungi pengawas untuk pindah perangkat.",
            )
        if live:
            audit(db, user_id, "STALE_SESSION_TAKEOVER", "user", user_id)
    # Staf: login terbaru menang. Siswa: yang terhapus di sini hanya sesi basi.
    db.execute(text("delete from sessions where user_id = :id"), {"id": user_id})

    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.execute(
        text("""
        insert into sessions (token_hash, user_id, csrf_token, expires_at)
        values (:h, :id, :csrf, now() + make_interval(secs => :ttl))
        """),
        {"h": _token_hash(token), "id": user_id, "csrf": csrf, "ttl": settings.session_ttl_seconds},
    )
    limiter.success(username, ip)
    response.set_cookie(
        COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite="strict", path="/api"
    )
    user = db.execute(
        text("select username, display_name from users where id = :id"), {"id": user_id}
    ).one()
    return {
        "user": {
            "id": str(user_id),
            "username": user.username,
            "display_name": user.display_name,
            "roles": sorted(roles),
        },
        "csrf_token": csrf,
    }


@router.get("/me")
def me(user: User) -> dict[str, Any]:
    # csrf_token ikut dikirim agar SPA bisa memulihkannya setelah reload.
    return {**user.public(), "csrf_token": user.csrf_token}


@router.post("/logout", status_code=204)
def logout(user: User, response: Response, db: DB) -> None:
    db.execute(text("delete from sessions where token_hash = :h"), {"h": user.session_hash})
    response.delete_cookie(COOKIE, path="/api")
