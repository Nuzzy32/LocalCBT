"""M9-02: regresi untuk temuan audit keamanan (lihat docs/evidence/M9-02_SECURITY_AUDIT.md)."""

import threading
import time
import uuid
import zipfile
from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import attempts, question_import
from app.auth import LoginRateLimiter
from app.db import engine
from app.errors import ApiError
from tests.conftest import login, make_user, new_client
from tests.test_attempts import exam, start  # noqa: F401
from tests.test_exams import setup  # noqa: F401
from tests.test_questions import PG, QB, new_bank, owner, png, subject_id, upload  # noqa: F401


def test_rate_limiter_is_atomic_under_parallel_guesses() -> None:
    # Dulu: cek & catat terpisah, permintaan paralel lolos semua sebelum gagalnya tercatat.
    lim = LoginRateLimiter(per_user=5, per_ip=30)
    allowed, barrier = [], threading.Barrier(40)

    def guess() -> None:
        barrier.wait()
        allowed.append(lim.acquire("token-ujian", "10.0.0.5") == 0)

    threads = [threading.Thread(target=guess) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(allowed) == 5


def test_successful_logins_behind_nat_do_not_exhaust_ip_quota() -> None:
    lim = LoginRateLimiter(per_user=5, per_ip=3)
    for n in range(10):  # satu lab di balik NAT, semua berhasil
        assert lim.acquire(f"siswa{n}", "10.0.0.1") == 0
        lim.success(f"siswa{n}", "10.0.0.1")
    assert lim.acquire("siswa-x", "10.0.0.1") == 0


def test_correct_password_with_active_session_does_not_burn_attempts() -> None:
    make_user("0011111", "STUDENT")
    login("0011111")
    with engine.begin() as db:  # sedang ujian di perangkat lain -> 409 berulang
        db.execute(text("update sessions set last_seen_at = now()"))
    c = new_client()
    codes = {
        c.post(
            "/api/v1/auth/login", json={"username": "0011111", "password": "rahasia-uji-123"}
        ).status_code
        for _ in range(8)
    }
    assert codes == {409}


def test_student_session_expires_after_idle_but_staff_does_not() -> None:
    make_user("0012222", "STUDENT")
    make_user("guru.idle", "TEACHER")
    student, teacher = login("0012222"), login("guru.idle")
    with engine.begin() as db:
        db.execute(text("update sessions set last_seen_at = now() - interval '31 minutes'"))
    assert student.get("/api/v1/auth/me").status_code == 401  # komputer lab bersama
    assert teacher.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize("grant", ["²³.abc", "1.é", "99999999999999999999.x", "", "."])
def test_malformed_start_grant_is_rejected_not_500(grant: str) -> None:
    assert attempts._grant_ok(grant, uuid.uuid4(), uuid.uuid4()) is False


def test_view_share_cannot_attach_owners_image(owner: TestClient, subject_id: str) -> None:  # noqa: F811
    bank = new_bank(owner, subject_id)
    media_id = upload(owner, png()).json()["id"]
    owner.post(f"{QB}/{bank}/questions", json={**PG, "media_asset_id": media_id})
    b_id = make_user("guru.b", "TEACHER")
    owner.post(f"{QB}/{bank}/shares", json={"teacher_id": b_id, "permission": "VIEW"})
    b = login("guru.b")
    assert b.get(f"/api/v1/media/{media_id}").status_code == 200  # boleh melihat
    own = new_bank(b, subject_id, "Bank B")
    r = b.post(f"{QB}/{own}/questions", json={**PG, "media_asset_id": media_id})
    assert r.status_code == 422  # tidak boleh memasang ke banknya sendiri
    r = b.post(f"{QB}/{own}/stimuli", json={"body_text": "x", "media_asset_id": media_id})
    assert r.status_code == 422
    with engine.begin() as db:
        db.execute(text("update bank_shares set permission = 'COPY'"))
    assert (
        b.post(f"{QB}/{own}/questions", json={**PG, "media_asset_id": media_id}).status_code == 201
    )


def test_unassigned_supervisor_cannot_trigger_auto_submit(exam: dict[str, Any]) -> None:  # noqa: F811
    attempt = start(exam["student"], exam["exam"]).json()["id"]
    with engine.begin() as db:
        db.execute(
            text("update exam_attempts set effective_deadline_at = now() - interval '1 second'")
        )
    make_user("pengawas.lain", "PROCTOR")
    r = login("pengawas.lain").post(
        f"/api/v1/proctor/attempts/{attempt}/time-extensions",
        json={"seconds": 60, "reason": "mencoba ujian orang lain"},
    )
    assert r.status_code == 404
    with engine.connect() as db:
        assert db.scalar(text("select state from exam_attempts")) == "IN_PROGRESS"


# ---- Import: berkas tak tepercaya ----------------------------------------------------


def _xlsx_with_far_row(row: int, col: str = "A") -> bytes:
    """XLSX valid kecil dengan satu sel di baris/kolom sangat jauh, tanpa <dimension>."""
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        + '<row r="1">'
        + "".join(
            f'<c r="{chr(65 + i)}1" t="inlineStr"><is><t>{h}</t></is></c>'
            for i, h in enumerate(question_import.HEADER)
        )
        + "</row>"
        + f'<row r="{row}"><c r="{col}{row}" t="inlineStr"><is><t>x</t></is></c></row>'
        + "</sheetData></worksheet>"
    )
    files = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',  # noqa: E501
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',  # noqa: E501
        "xl/workbook.xml": '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>',  # noqa: E501
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',  # noqa: E501
        "xl/worksheets/sheet1.xml": sheet,
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


@pytest.mark.parametrize(("row", "col"), [(10**15, "A"), (6000, "A"), (2, "XFD")])
def test_xlsx_with_huge_claimed_row_or_column_is_cheap(row: int, col: str) -> None:
    # Dulu: 5 KB berkas = worker macet bertahun-tahun (openpyxl menghasilkan setiap baris kosong).
    t0 = time.perf_counter()
    try:
        question_import.parse_xlsx(_xlsx_with_far_row(row, col))
    except ApiError as e:
        assert e.status == 413 or e.code == "INVALID_FILE"
    assert time.perf_counter() - t0 < 2


def _docx(document_xml: bytes, method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        z.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def test_docx_oversized_or_corrupt_rejected_without_500() -> None:
    big = b"<w:document>" + b"<w:p/>" * (question_import.MAX_DOCX_XML // 6 + 10) + b"</w:document>"
    with pytest.raises(ApiError) as e:
        question_import.parse_docx(_docx(big))
    assert e.value.status == 413
    corrupt = bytearray(_docx(b"<w:document>" + b"x" * 5000 + b"</w:document>"))
    corrupt[60:80] = b"\x00" * 20  # aliran deflate rusak
    with pytest.raises(ApiError) as e:
        question_import.parse_docx(bytes(corrupt))
    assert e.value.status in (413, 422)
