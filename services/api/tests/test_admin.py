import logging
import zipfile
from collections.abc import Callable
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from tests.conftest import login, make_user, new_client, xlsx

PREVIEW = "/api/v1/admin/students/import/preview"
COMMIT = "/api/v1/admin/students/import/commit"


def _upload(client: TestClient, data: bytes) -> dict:  # type: ignore[type-arg]
    r = client.post(PREVIEW, files={"file": ("siswa.xlsx", data)})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def _count(table: str) -> int:
    with engine.connect() as c:
        return int(c.scalar(text(f"select count(*) from {table}")) or 0)  # noqa: S608


def test_one_account_can_be_teacher_and_proctor(admin: TestClient) -> None:
    r = admin.post(
        "/api/v1/admin/staff",
        json={"username": "bu.sari", "display_name": "Bu Sari", "roles": ["TEACHER", "PROCTOR"]},
    )
    assert r.status_code == 201
    staff = login("bu.sari", r.json()["temporary_password"])
    assert staff.get("/api/v1/auth/me").json()["roles"] == ["PROCTOR", "TEACHER"]


def test_import_preview_then_commit_creates_students_with_unique_passwords(
    admin: TestClient, make_class: Callable[[str], str], caplog: pytest.LogCaptureFixture
) -> None:
    make_class("IX-A")
    preview = _upload(admin, xlsx([[12345, "Ahmad", "IX-A"], ["0012346", "Budi", "ix-a"]]))
    assert preview["errors"] == [] and preview["valid_rows"] == 2

    with caplog.at_level(logging.DEBUG):
        r = admin.post(COMMIT, json={"preview_id": preview["preview_id"], "confirm": True})
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    creds = r.json()["credentials"]
    assert [c["nis"] for c in creds] == ["12345", "0012346"]
    passwords = [c["password"] for c in creds]
    assert len(set(passwords)) == 2
    assert not any(p in caplog.text for p in passwords)

    # Siswa langsung bisa login dengan NIS + kata sandi dari berkas kredensial.
    login("0012346", passwords[1])
    # Preview yang sama tidak bisa di-commit dua kali; data siswa di job sudah dihapus.
    again = admin.post(COMMIT, json={"preview_id": preview["preview_id"], "confirm": True})
    assert again.status_code == 409
    with engine.connect() as c:
        assert c.scalar(text("select rows from import_jobs")) is None


def test_import_reports_duplicate_and_invalid_rows_and_never_writes_partially(
    admin: TestClient, make_class: Callable[[str], str]
) -> None:
    make_class("IX-A")
    make_user("777", "STUDENT")
    preview = _upload(
        admin,
        xlsx(
            [
                ["100", "Ani", "IX-A"],  # valid
                ["200", "Dua", "IX-A"],  # duplikat di berkas
                ["200", "Dua Lagi", "IX-A"],
                ["777", "Sudah Ada", "IX-A"],  # duplikat di DB
                ["ab cd", "", "X-Z"],  # NIS, nama, kelas salah
            ]
        ),
    )
    by_row = {(e["row_number"], e["field"]) for e in preview["errors"]}
    assert {(3, "NIS"), (4, "NIS"), (5, "NIS"), (6, "NIS"), (6, "Nama"), (6, "Kelas")} == by_row
    assert preview["valid_rows"] == 1

    users_before = _count("users")
    r = admin.post(COMMIT, json={"preview_id": preview["preview_id"], "confirm": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "IMPORT_HAS_ERRORS"
    assert _count("users") == users_before and _count("class_memberships") == 0


def test_commit_rolls_back_everything_when_nis_registered_after_preview(
    admin: TestClient, make_class: Callable[[str], str]
) -> None:
    make_class("IX-A")
    preview = _upload(admin, xlsx([["100", "Ani", "IX-A"], ["200", "Budi", "IX-A"]]))
    make_user("200", "STUDENT")  # muncul di antara preview dan commit
    users_before = _count("users")

    r = admin.post(COMMIT, json={"preview_id": preview["preview_id"], "confirm": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "IMPORT_CONFLICT"
    assert _count("users") == users_before and _count("class_memberships") == 0


def test_rejects_wrong_template_oversize_and_zip_bomb(admin: TestClient) -> None:
    r = admin.post(PREVIEW, files={"file": ("x.xlsx", xlsx([["1", "A", "B"]], ["No", "Nama"]))})
    assert r.json()["error"]["code"] == "INVALID_TEMPLATE"

    r = admin.post(PREVIEW, files={"file": ("x.xlsx", b"0" * (2 * 1024 * 1024 + 1))})
    assert r.status_code == 413

    bomb = BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"\0" * (10 * 1024 * 1024))
    r = admin.post(PREVIEW, files={"file": ("x.xlsx", bomb.getvalue())})
    assert r.status_code == 413

    r = admin.post(PREVIEW, files={"file": ("x.xlsx", b"bukan zip")})
    assert r.json()["error"]["code"] == "INVALID_FILE"


def test_another_admin_cannot_commit_someone_elses_preview(
    admin: TestClient, make_class: Callable[[str], str]
) -> None:
    make_class("IX-A")
    preview = _upload(admin, xlsx([["100", "Ani", "IX-A"]]))
    make_user("admin2", "ADMIN")
    other = login("admin2")
    r = other.post(COMMIT, json={"preview_id": preview["preview_id"], "confirm": True})
    assert r.status_code == 404


ADMIN_ONLY = [
    ("POST", "/api/v1/admin/classes"),
    ("POST", "/api/v1/admin/subjects"),
    ("GET", "/api/v1/admin/staff"),
    ("POST", "/api/v1/admin/staff"),
    ("POST", "/api/v1/admin/teaching-assignments"),
    ("POST", "/api/v1/admin/students/00000000-0000-0000-0000-000000000000/password-reset"),
    ("GET", "/api/v1/admin/students?nis=0012345"),
    ("GET", "/api/v1/admin/interventions"),
    ("POST", PREVIEW),
    ("POST", COMMIT),
]


@pytest.mark.parametrize("role", ["STUDENT", "TEACHER", "PROCTOR"])
@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY)
def test_non_admin_cannot_call_admin_routes(role: str, method: str, path: str) -> None:
    make_user("bukanadmin", role)
    client = login("bukanadmin")
    r = client.request(method, path, json={})
    assert r.status_code == 403, r.text


def test_student_and_proctor_cannot_list_classes() -> None:
    for i, role in enumerate(["STUDENT", "PROCTOR"]):
        make_user(f"u{i}", role)
        assert login(f"u{i}").get("/api/v1/admin/classes").status_code == 403


def test_teacher_sees_only_classes_they_teach(
    admin: TestClient, make_class: Callable[[str], str]
) -> None:
    mine, _other = make_class("IX-A"), make_class("IX-B")
    teacher_id = make_user("guru1", "TEACHER")
    subject = admin.post("/api/v1/admin/subjects", json={"code": "MTK", "name": "Matematika"})
    r = admin.post(
        "/api/v1/admin/teaching-assignments",
        json={"teacher_id": teacher_id, "class_id": mine, "subject_id": subject.json()["id"]},
    )
    assert r.status_code == 201
    classes = login("guru1").get("/api/v1/admin/classes").json()
    assert [c["id"] for c in classes] == [mine]
    assert len(admin.get("/api/v1/admin/classes").json()) == 2


def test_teaching_assignment_requires_teacher_role(
    admin: TestClient, make_class: Callable[[str], str]
) -> None:
    student_id = make_user("0012345", "STUDENT")
    subject = admin.post("/api/v1/admin/subjects", json={"code": "MTK", "name": "Matematika"})
    r = admin.post(
        "/api/v1/admin/teaching-assignments",
        json={
            "teacher_id": student_id,
            "class_id": make_class("IX-A"),
            "subject_id": subject.json()["id"],
        },
    )
    assert r.status_code == 422


def test_password_reset_only_for_students_and_revokes_sessions(admin: TestClient) -> None:
    student_id = make_user("0012345", "STUDENT")
    teacher_id = make_user("guru1", "TEACHER")
    session = login("0012345")
    url = "/api/v1/admin/students/{}/password-reset"
    reason = {"reason": "Siswa lupa kata sandi saat ujian"}

    assert admin.post(url.format(teacher_id), json=reason).status_code == 404
    r = admin.post(url.format(student_id), json=reason)
    assert r.status_code == 200
    assert session.get("/api/v1/auth/me").status_code == 401
    login("0012345", r.json()["temporary_password"])
    with engine.connect() as c:
        row = c.execute(text("select action, target_id::text, reason from audit_events")).one()
    assert tuple(row) == ("STUDENT_PASSWORD_RESET", student_id, reason["reason"])


def test_find_student_by_nis_only_returns_students(admin: TestClient) -> None:
    student_id = make_user("0012345", "STUDENT", name="Ahmad")
    make_user("guru1", "TEACHER")
    r = admin.get("/api/v1/admin/students", params={"nis": " 0012345 "})
    assert r.json() == {"id": student_id, "nis": "0012345", "display_name": "Ahmad"}
    assert admin.get("/api/v1/admin/students", params={"nis": "guru1"}).status_code == 404


def test_duplicate_class_is_conflict(admin: TestClient, make_class: Callable[[str], str]) -> None:
    make_class("IX-A")
    r = admin.post(
        "/api/v1/admin/classes",
        json={"code": "IX-A", "label": "lagi", "academic_year": "2026/2027"},
    )
    assert r.status_code == 409


def test_validation_error_does_not_echo_password() -> None:
    r = new_client().post("/api/v1/auth/login", json={"username": "", "password": "rahasia-banget"})
    assert r.status_code == 422 and "rahasia-banget" not in r.text
