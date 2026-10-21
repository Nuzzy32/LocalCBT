"""M9-02: matriks akses SEMUA route × peran (PRD §11, FR-AUTH-06, TC-18).

Menggantikan tes lama berbasis app.routes: sejak FastAPI 0.14x route router yang di-include
tidak muncul di app.routes, sehingga tes itu diam-diam hanya memeriksa /healthz.

Kontrak keamanan tertulis: setiap route wajib cocok dengan satu baris POLICY. Route baru yang
belum diklasifikasikan membuat tes gagal, jadi hak aksesnya harus diputuskan secara sadar.
Yang diuji di sini gerbang peran (role); kepemilikan objek diuji di tes per modul.
"""

import re
import uuid
from typing import Any

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import (
    admin,
    attempts,
    auth,
    exams,
    media,
    ops,
    proctor,
    question_import,
    questions,
    results,
)
from tests.conftest import ORIGIN, login, make_user, new_client

PUBLIC = "PUBLIC"
ROLES = ("STUDENT", "PROCTOR", "TEACHER", "ADMIN")
ALL = set(ROLES)

# (metode | "*", regex path, peran yang boleh). Baris pertama yang cocok berlaku.
POLICY: list[tuple[str, str, set[str] | str]] = [
    ("POST", r"/api/v1/auth/login", PUBLIC),
    ("*", r"/api/v1/auth/(me|logout)", ALL),
    ("*", r"/api/v1/ops/(probe|probe\.js|probe-reports)", PUBLIC),
    ("*", r"/api/v1/ops/.*", {"ADMIN"}),
    ("GET", r"/api/v1/admin/(classes|subjects)", {"ADMIN", "TEACHER"}),
    ("*", r"/api/v1/admin/.*", {"ADMIN"}),
    ("GET", r"/api/v1/media/\{media_id\}", ALL),  # objek: hanya bila soalnya boleh dilihat
    ("POST", r"/api/v1/media", {"TEACHER"}),
    ("*", r"/api/v1/student/.*", {"STUDENT"}),
    ("*", r"/api/v1/proctor/.*", {"TEACHER", "PROCTOR"}),
    ("*", r"/api/v1/exams/\{exam_id\}/proctors.*", {"TEACHER"}),
    (
        "*",
        r"/api/v1/(exams|teacher|question-banks|question-import-templates|teachers)\b.*",
        {"TEACHER"},
    ),  # fmt: skip
]
MODULES = (auth, admin, questions, question_import, media, exams, attempts, proctor, results, ops)


def _routes() -> list[tuple[str, str]]:
    out = []
    for m in MODULES:
        for r in m.router.routes:
            if isinstance(r, APIRoute):
                out += [(method, r.path) for method in sorted(r.methods)]
            elif not isinstance(r, APIWebSocketRoute):
                raise AssertionError(f"jenis route tak dikenal: {r}")
    return out


def _policy(method: str, path: str) -> set[str] | str:
    for m, pattern, allowed in POLICY:
        if m in ("*", method) and re.fullmatch(pattern, path):
            return allowed
    raise AssertionError(f"Route belum diklasifikasikan di POLICY: {method} {path}")


ROUTES = _routes()


def test_every_route_is_classified() -> None:
    assert len(ROUTES) > 70
    for method, path in ROUTES:
        _policy(method, path)


@pytest.fixture
def clients() -> dict[str, TestClient]:
    out = {"ANON": new_client()}
    for role in ROLES:
        make_user(f"akses.{role.lower()}", role)
        out[role] = login(f"akses.{role.lower()}")
    return out


def _call(client: TestClient, method: str, path: str) -> Any:
    url = re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)
    url = url.replace(str(uuid.UUID(int=0)), "xlsx")
    if "{fmt}" in path:
        url = path.replace("{fmt}", "xlsx")
    body = None if method in ("GET", "DELETE") else {}
    return client.request(method, url, json=body)


def test_role_gate_on_every_route(clients: dict[str, TestClient]) -> None:
    problems = []
    for method, path in ROUTES:
        allowed = _policy(method, path)
        if path == "/api/v1/auth/logout":
            continue  # memutus sesi klien bersama; diuji di test_auth
        for who, client in clients.items():
            status = _call(client, method, path).status_code
            if allowed == PUBLIC:
                ok = status not in (401, 403)
            elif who == "ANON":
                ok = status == 401
            elif who in allowed:
                ok = status not in (401, 403) or (status == 403 and path.endswith("/token/verify"))
            else:
                ok = status in (403, 404) and not (who in ("ADMIN", "TEACHER") and status == 404)
            if not ok:
                problems.append(f"{who:<8} {method:<6} {path} -> {status}")
    assert not problems, "\n" + "\n".join(problems)


def test_mutations_without_csrf_or_origin_rejected(clients: dict[str, TestClient]) -> None:
    teacher = clients["TEACHER"]
    body = {"title": "x", "subject_id": str(uuid.uuid4())}
    no_csrf = new_client()
    no_csrf.cookies = teacher.cookies
    r = no_csrf.post("/api/v1/question-banks", json=body)
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_INVALID"
    for origin in ("https://evil.example", "null", ""):
        r = teacher.post("/api/v1/question-banks", json=body, headers={"Origin": origin})
        assert r.status_code == 403 and r.json()["error"]["code"] == "ORIGIN_REJECTED", origin


def test_monitor_websocket_rejects_anon_wrong_origin_and_students(
    clients: dict[str, TestClient],
) -> None:
    exam = str(uuid.uuid4())
    for who, headers in [
        ("ANON", {"Origin": ORIGIN}),
        ("TEACHER", {"Origin": "https://evil.example"}),  # Cross-Site WebSocket Hijacking
        ("STUDENT", {"Origin": ORIGIN}),
        ("TEACHER", {"Origin": ORIGIN}),  # bukan pengawas ujian ini
    ]:
        c = clients[who]
        with (
            pytest.raises(WebSocketDisconnect) as exc,
            c.websocket_connect(f"/api/v1/ws/exams/{exam}", headers=headers),
        ):
            pass
        assert exc.value.code == 1008, who
