"""Tes memakai Postgres sungguhan (DB terpisah *_test), dimigrasi via Alembic."""

import os
from collections.abc import Callable, Iterator
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text

_base = make_url(
    os.environ.get(
        "LOCALCBT_DATABASE_URL",
        "postgresql+psycopg://localcbt:localcbt-dev@127.0.0.1:5432/localcbt",
    )
)
TEST_DB = f"{_base.database}_test"
os.environ["LOCALCBT_DATABASE_URL"] = _base.set(database=TEST_DB).render_as_string(
    hide_password=False
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password, limiter  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402

ORIGIN = "http://localhost:5173"
PASSWORD = "rahasia-uji-123"
_HASH = hash_password(PASSWORD)


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    admin_engine = create_engine(_base, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        if not conn.scalar(text("select 1 from pg_database where datname = :d"), {"d": TEST_DB}):
            conn.execute(text(f'create database "{TEST_DB}"'))
    admin_engine.dispose()
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    limiter.reset()
    monkeypatch.setattr(settings, "media_dir", tmp_path / "media")
    yield
    with engine.begin() as conn:
        conn.execute(
            text("""
            truncate exam_question_snapshots, exam_assignments, exams,
              question_statements, question_options, questions, stimuli, media_assets,
              bank_shares, question_banks, import_jobs, teaching_assignments, subjects,
              class_memberships, classes,
              sessions, user_roles, users
            """)
        )


def make_user(username: str, *roles: str, name: str | None = None) -> str:
    with engine.begin() as conn:
        user_id = conn.scalar(
            text("""
            insert into users (username, password_hash, display_name)
            values (:u, :h, :n) returning id
            """),
            {"u": username, "h": _HASH, "n": name or username},
        )
        for role in roles:
            conn.execute(
                text("insert into user_roles (user_id, role) values (:id, :r)"),
                {"id": user_id, "r": role},
            )
    return str(user_id)


def new_client() -> TestClient:
    # https: cookie Secure hanya dikirim lewat https.
    return TestClient(app, base_url="https://testserver", headers={"Origin": ORIGIN})


def login(username: str, password: str = PASSWORD) -> TestClient:
    client = new_client()
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return client


def xlsx(rows: list[list[object]], header: list[str] | None = None) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(header or ["NIS", "Nama", "Kelas"])
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def admin() -> TestClient:
    make_user("admin", "ADMIN")
    return login("admin")


@pytest.fixture
def make_class(admin: TestClient) -> Callable[[str], str]:
    def create(code: str) -> str:
        r = admin.post(
            "/api/v1/admin/classes",
            json={"code": code, "label": f"Kelas {code}", "academic_year": "2026/2027"},
        )
        assert r.status_code == 201, r.text
        return str(r.json()["id"])

    return create
