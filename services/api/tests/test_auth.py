import re

from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.main import app
from tests.conftest import PASSWORD, login, make_user, new_client

LOGIN = "/api/v1/auth/login"


def test_login_with_nis_sets_secure_session_and_returns_csrf() -> None:
    make_user("0012345", "STUDENT", name="Ahmad")
    client = new_client()
    r = client.post(LOGIN, json={"username": "0012345", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["roles"] == ["STUDENT"] and body["csrf_token"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert "path=/api" in cookie

    me = client.get("/api/v1/auth/me").json()
    assert me["display_name"] == "Ahmad" and me["csrf_token"] == body["csrf_token"]
    assert "password_hash" not in me


def test_wrong_password_and_unknown_user_same_generic_401() -> None:
    make_user("guru1", "TEACHER")
    a = new_client().post(LOGIN, json={"username": "guru1", "password": "salah"})
    b = new_client().post(LOGIN, json={"username": "tidakada", "password": "salah"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"] == b.json()["error"]


def test_disabled_user_cannot_login() -> None:
    make_user("guru1", "TEACHER")
    with engine.begin() as c:
        c.execute(text("update users set status = 'DISABLED'"))
    r = new_client().post(LOGIN, json={"username": "guru1", "password": PASSWORD})
    assert r.status_code == 401


def test_rate_limit_after_5_failures_even_for_correct_password() -> None:
    make_user("guru1", "TEACHER")
    client = new_client()
    for _ in range(5):
        assert client.post(LOGIN, json={"username": "guru1", "password": "x"}).status_code == 401
    r = client.post(LOGIN, json={"username": "GURU1", "password": PASSWORD})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_mutation_without_csrf_is_rejected() -> None:
    make_user("admin", "ADMIN")
    client = login("admin")
    del client.headers["X-CSRF-Token"]
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_INVALID"


def test_foreign_or_missing_origin_is_rejected_even_on_login() -> None:
    make_user("admin", "ADMIN")
    evil = new_client()
    evil.headers["Origin"] = "https://evil.example"
    assert evil.post(LOGIN, json={"username": "admin", "password": PASSWORD}).status_code == 403
    del evil.headers["Origin"]
    assert evil.post(LOGIN, json={"username": "admin", "password": PASSWORD}).status_code == 403


def test_logout_revokes_session() -> None:
    make_user("admin", "ADMIN")
    client = login("admin")
    assert client.post("/api/v1/auth/logout").status_code == 204
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_expired_session_reports_session_expired() -> None:
    make_user("admin", "ADMIN")
    client = login("admin")
    with engine.begin() as c:
        c.execute(text("update sessions set expires_at = now() - interval '1 second'"))
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "SESSION_EXPIRED"


def test_staff_second_login_revokes_first() -> None:
    make_user("guru1", "TEACHER")
    first = login("guru1")
    login("guru1")
    assert first.get("/api/v1/auth/me").status_code == 401


def test_student_second_login_blocked_until_session_stale() -> None:
    make_user("0012345", "STUDENT")
    first = login("0012345")
    r = new_client().post(LOGIN, json={"username": "0012345", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SESSION_ACTIVE"
    assert first.get("/api/v1/auth/me").status_code == 200

    with engine.begin() as c:
        c.execute(
            text("update sessions set last_seen_at = now() - make_interval(secs => :s)"),
            {"s": settings.student_session_stale_seconds + 1},
        )
    login("0012345")
    assert first.get("/api/v1/auth/me").status_code == 401


def test_every_route_requires_auth_except_allowlist() -> None:
    # Default deny: route baru tanpa dependency current_user akan menggagalkan tes ini.
    public = {
        "/api/v1/healthz",
        "/api/v1/auth/login",
        "/api/v1/docs",
        "/api/v1/openapi.json",
    }
    client = new_client()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in public:
            continue
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
            url = re.sub(r"\{[a-z_]+\}", "00000000-0000-0000-0000-000000000000", path)
            r = client.request(method, url)
            assert r.status_code == 401, (method, path, r.status_code)
