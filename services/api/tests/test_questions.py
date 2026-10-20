import json
import struct
import zipfile
import zlib
from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.question_import import HEADER, build_docx
from tests.conftest import login, make_user, xlsx

QB = "/api/v1/question-banks"
PG: dict[str, Any] = {
    "type": "SINGLE_CHOICE",
    "stem": "2 + 2 = …",
    "weight": 1,
    "options": [{"text": "3", "is_correct": False}, {"text": "4", "is_correct": True}],
}
MCMA: dict[str, Any] = {
    "type": "MULTIPLE_CHOICE",
    "stem": "Bilangan prima?",
    "weight": 2.5,
    "options": [
        {"text": "2", "is_correct": True},
        {"text": "3", "is_correct": True},
        {"text": "4", "is_correct": False},
    ],
}
KATEGORI: dict[str, Any] = {
    "type": "CATEGORY_CHOICE",
    "stem": "Benar atau salah?",
    "weight": 3,
    "statements": [
        {"text": "4 genap", "correct_value": True},
        {"text": "9 prima", "correct_value": False},
    ],
}


def png(w: int = 2, h: int = 3) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def jpeg(w: int, h: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def webp(w: int, h: int) -> bytes:
    body = b"WEBP" + b"VP8X" + struct.pack("<I", 10) + b"\x00" * 4
    body += (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.fixture
def subject_id() -> str:
    with engine.begin() as c:
        return str(
            c.scalar(
                text("insert into subjects (code, name) values ('MTK', 'Matematika') returning id")
            )
        )


@pytest.fixture
def owner(subject_id: str) -> TestClient:
    make_user("guru.a", "TEACHER")
    return login("guru.a")


def new_bank(client: TestClient, subject_id: str, title: str = "Bank A") -> str:
    r = client.post(QB, json={"title": title, "subject_id": subject_id})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def upload(client: TestClient, data: bytes, name: str = "x.png") -> Any:
    return client.post("/api/v1/media", files={"file": (name, data)})


def walk_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in walk_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in walk_keys(v)}
    return set()


# ---- Tiga tipe soal & validator ------------------------------------------------


def test_create_three_types_edit_bumps_version_delete_hides(
    owner: TestClient, subject_id: str
) -> None:
    bank = new_bank(owner, subject_id)
    ids = []
    for body in (PG, MCMA, KATEGORI):
        r = owner.post(f"{QB}/{bank}/questions", json=body)
        assert r.status_code == 201, r.text
        assert r.json()["version"] == 1
        ids.append(r.json()["id"])
    listed = owner.get(f"{QB}/{bank}/questions").json()
    assert [q["type"] for q in listed] == ["SINGLE_CHOICE", "MULTIPLE_CHOICE", "CATEGORY_CHOICE"]
    assert listed[0]["options"][1]["is_correct"] is True  # staf melihat kunci

    r = owner.put(f"{QB}/{bank}/questions/{ids[0]}", json={**PG, "stem": "3 + 1 = …"})
    assert r.json()["version"] == 2 and r.json()["stem"] == "3 + 1 = …"

    assert owner.delete(f"{QB}/{bank}/questions/{ids[0]}").status_code == 204
    assert len(owner.get(f"{QB}/{bank}/questions").json()) == 2
    assert len(owner.get(f"{QB}/{bank}/preview").json()) == 2


@pytest.mark.parametrize(
    "body",
    [
        {**PG, "options": [{**o, "is_correct": False} for o in PG["options"]]},  # PG tanpa kunci
        {**PG, "options": [{**o, "is_correct": True} for o in PG["options"]]},  # PG dua kunci
        {**MCMA, "options": [{**o, "is_correct": False} for o in MCMA["options"]]},
        {**PG, "options": PG["options"][:1]},  # satu opsi
        {
            **PG,
            "options": [{"text": "4", "is_correct": True}, {"text": " 4 ", "is_correct": False}],
        },
        {**PG, "options": [{"text": " ", "is_correct": True}, {"text": "4", "is_correct": False}]},
        {**KATEGORI, "statements": KATEGORI["statements"][:1]},
        {**KATEGORI, "options": PG["options"]},
        {**PG, "statements": KATEGORI["statements"]},
        {**PG, "weight": 0},
        {**PG, "weight": -1},
        {**PG, "weight": 1.234},
        {**PG, "stem": ""},
    ],
)
def test_invalid_questions_rejected(
    owner: TestClient, subject_id: str, body: dict[str, Any]
) -> None:
    bank = new_bank(owner, subject_id)
    r = owner.post(f"{QB}/{bank}/questions", json=body)
    assert r.status_code == 422, r.text


def test_rule_message_is_shown_to_user(owner: TestClient, subject_id: str) -> None:
    bank = new_bank(owner, subject_id)
    r = owner.post(
        f"{QB}/{bank}/questions",
        json={**PG, "options": [{**o, "is_correct": True} for o in PG["options"]]},
    )
    assert r.json()["error"]["message"] == "Pilihan ganda harus punya tepat satu kunci jawaban."


# ---- Kunci tidak bocor ---------------------------------------------------------


def test_student_preview_never_contains_keys(owner: TestClient, subject_id: str) -> None:
    bank = new_bank(owner, subject_id)
    for body in (PG, MCMA, KATEGORI):
        owner.post(f"{QB}/{bank}/questions", json=body)
    r = owner.get(f"{QB}/{bank}/preview")
    keys = walk_keys(r.json())
    assert not keys & {"is_correct", "correct_value", "answer_key"}
    assert "correct" not in r.text
    assert keys <= {
        "id",
        "type",
        "stem",
        "weight",
        "stimulus_id",
        "stimulus",
        "stimulus_image_url",
        "image_url",
        "options",
        "statements",
        "text",
    }


# ---- Hak akses & berbagi -------------------------------------------------------


def _share(owner: TestClient, bank: str, teacher_id: str, permission: str) -> None:
    r = owner.post(f"{QB}/{bank}/shares", json={"teacher_id": teacher_id, "permission": permission})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize(
    ("permission", "expected"),
    [
        # (list soal, preview, buat soal, salin keluar, kelola share)
        (None, (404, 404, 404, 404, 404)),
        ("VIEW", (200, 200, 403, 403, 403)),
        ("COPY", (200, 200, 403, 200, 403)),
        ("EDIT", (200, 200, 201, 200, 403)),
    ],
)
def test_share_permission_matrix(
    owner: TestClient, subject_id: str, permission: str | None, expected: tuple[int, ...]
) -> None:
    bank = new_bank(owner, subject_id)
    owner.post(f"{QB}/{bank}/questions", json=PG)
    b_id = make_user("guru.b", "TEACHER")
    if permission:
        _share(owner, bank, b_id, permission)
    other = login("guru.b")
    own_bank = new_bank(other, subject_id, "Bank B")

    got = (
        other.get(f"{QB}/{bank}/questions").status_code,
        other.get(f"{QB}/{bank}/preview").status_code,
        other.post(f"{QB}/{bank}/questions", json=PG).status_code,
        other.post(f"{QB}/{bank}/copy", json={"target_bank_id": own_bank}).status_code,
        other.get(f"{QB}/{bank}/shares").status_code,
    )
    assert got == expected


def test_revoked_share_loses_access_and_owner_sees_both_lists(
    owner: TestClient, subject_id: str
) -> None:
    bank = new_bank(owner, subject_id)
    b_id = make_user("guru.b", "TEACHER")
    _share(owner, bank, b_id, "EDIT")
    other = login("guru.b")
    assert [b["access"] for b in other.get(QB).json()] == ["EDIT"]
    assert owner.delete(f"{QB}/{bank}/shares/{b_id}").status_code == 204
    assert other.get(f"{QB}/{bank}/questions").status_code == 404
    assert other.get(QB).json() == []
    with engine.connect() as conn:
        actions = conn.scalars(text("select action from audit_events order by created_at")).all()
    assert actions == ["BANK_SHARED", "BANK_SHARE_REVOKED"]


def test_cannot_copy_into_bank_without_edit(owner: TestClient, subject_id: str) -> None:
    mine = new_bank(owner, subject_id)
    owner.post(f"{QB}/{mine}/questions", json=PG)
    make_user("guru.b", "TEACHER")
    other = login("guru.b")
    theirs = new_bank(other, subject_id, "Bank B")
    copy = {"target_bank_id": theirs}
    assert owner.post(f"{QB}/{mine}/copy", json=copy).status_code == 404  # target tak terlihat
    _share(other, theirs, owner.get("/api/v1/auth/me").json()["id"], "VIEW")
    assert owner.post(f"{QB}/{mine}/copy", json=copy).status_code == 403  # terlihat, bukan EDIT
    assert other.get(f"{QB}/{theirs}/questions").json() == []


@pytest.mark.parametrize("role", ["STUDENT", "PROCTOR", "ADMIN"])
def test_non_teachers_cannot_use_question_banks(role: str) -> None:
    make_user("x", role)
    client = login("x")
    assert client.get(QB).status_code == 403
    assert client.post("/api/v1/media", files={"file": ("a.png", png())}).status_code == 403


# ---- Stimulus ------------------------------------------------------------------


def test_shared_stimulus_groups_questions_and_survives_copy(
    owner: TestClient, subject_id: str
) -> None:
    bank = new_bank(owner, subject_id)
    stim = owner.post(f"{QB}/{bank}/stimuli", json={"body_text": "Bacaan tentang bilangan."})
    assert stim.status_code == 201
    sid = stim.json()["id"]
    owner.post(f"{QB}/{bank}/questions", json={**PG, "stimulus_id": sid})
    owner.post(f"{QB}/{bank}/questions", json={**MCMA, "stimulus_id": sid})
    preview = owner.get(f"{QB}/{bank}/preview").json()
    assert {q["stimulus"] for q in preview} == {"Bacaan tentang bilangan."}

    target = new_bank(owner, subject_id, "Salinan")
    assert owner.post(f"{QB}/{bank}/copy", json={"target_bank_id": target}).json() == {"copied": 2}
    copied = owner.get(f"{QB}/{target}/questions").json()
    assert len({q["stimulus_id"] for q in copied}) == 1 and copied[0]["stimulus_id"] != sid


def test_stimulus_from_another_bank_is_rejected(owner: TestClient, subject_id: str) -> None:
    a, b = new_bank(owner, subject_id), new_bank(owner, subject_id, "B")
    sid = owner.post(f"{QB}/{a}/stimuli", json={"body_text": "Teks"}).json()["id"]
    r = owner.post(f"{QB}/{b}/questions", json={**PG, "stimulus_id": sid})
    assert r.status_code == 422


# ---- Media ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "mime", "size"),
    [
        (png(5, 7), "image/png", (5, 7)),
        (jpeg(640, 480), "image/jpeg", (640, 480)),
        (webp(300, 200), "image/webp", (300, 200)),
    ],
)
def test_accepts_png_jpeg_webp_with_dimensions(
    owner: TestClient, data: bytes, mime: str, size: tuple[int, int]
) -> None:
    r = upload(owner, data, "apa-saja.bin")
    assert r.status_code == 201, r.text
    assert (r.json()["mime"], r.json()["width"], r.json()["height"]) == (mime, *size)


@pytest.mark.parametrize(
    "data",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"GIF89a\x01\x00\x01\x00\x00\x00\x00",
        b"<html><script>alert(1)</script></html>",
    ],
)
def test_rejects_svg_gif_html_even_if_named_png(owner: TestClient, data: bytes) -> None:
    assert upload(owner, data, "gambar.png").status_code == 415


def test_size_and_pixel_limits(owner: TestClient) -> None:
    assert upload(owner, png() + b"\x00" * (2 * 1024 * 1024)).status_code == 413
    assert upload(owner, jpeg(5000, 100)).status_code == 422


def test_polyglot_served_as_image_with_nosniff_and_sandbox(
    owner: TestClient, subject_id: str
) -> None:
    r = upload(owner, png() + b"<html><script>alert(1)</script></html>")
    media_id = r.json()["id"]
    got = owner.get(f"/api/v1/media/{media_id}")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in got.headers["content-security-policy"]


def test_same_image_twice_is_one_asset(owner: TestClient) -> None:
    a, b = upload(owner, png()), upload(owner, png())
    assert a.json()["id"] == b.json()["id"]


def test_media_visible_only_through_shared_bank(owner: TestClient, subject_id: str) -> None:
    bank = new_bank(owner, subject_id)
    media_id = upload(owner, png()).json()["id"]
    owner.post(f"{QB}/{bank}/questions", json={**PG, "media_asset_id": media_id})
    b_id = make_user("guru.b", "TEACHER")
    other = login("guru.b")
    assert other.get(f"/api/v1/media/{media_id}").status_code == 404
    # Media orang lain juga tidak bisa ditempel ke soal sendiri.
    own = new_bank(other, subject_id, "B")
    assert (
        other.post(f"{QB}/{own}/questions", json={**PG, "media_asset_id": media_id}).status_code
        == 422
    )

    _share(owner, bank, b_id, "VIEW")
    assert other.get(f"/api/v1/media/{media_id}").status_code == 200
    assert other.get(f"{QB}/{bank}/preview").json()[0]["image_url"] == f"/api/v1/media/{media_id}"


# ---- Import XLSX ---------------------------------------------------------------

PREVIEW = "imports/preview"
COMMIT = "imports/commit"


def _row(**cells: str) -> list[str]:
    return [cells.get(h.replace(" ", "_"), "") for h in HEADER]


def _preview(client: TestClient, bank: str, data: bytes, name: str = "soal.xlsx") -> Any:
    r = client.post(f"{QB}/{bank}/{PREVIEW}", files={"file": (name, data)})
    return r


def test_xlsx_import_reports_exact_row_errors_and_writes_nothing(
    owner: TestClient, subject_id: str
) -> None:
    bank = new_bank(owner, subject_id)
    data = xlsx(
        [
            _row(Jenis="PG", Pertanyaan="Valid", Kunci="A", Opsi_A="1", Opsi_B="2"),
            _row(Jenis="ESAI", Pertanyaan="x"),
            _row(Jenis="PG", Pertanyaan="Kunci salah", Kunci="E", Opsi_A="1", Opsi_B="2"),
            _row(Jenis="PG", Pertanyaan="Dua kunci", Kunci="A,B", Opsi_A="1", Opsi_B="2"),
            _row(Jenis="KATEGORI", Pertanyaan="BS", Kunci="B", Opsi_A="p", Opsi_B="q"),
            _row(Jenis="MCMA", Pertanyaan="", Kunci="A", Opsi_A="1", Opsi_B="2"),
            _row(Jenis="PG", Pertanyaan="Bobot", Bobot="nol", Kunci="A", Opsi_A="1", Opsi_B="2"),
        ],
        HEADER,
    )
    r = _preview(owner, bank, data)
    assert r.status_code == 200, r.text
    got = {(e["row_number"], e["field"]) for e in r.json()["errors"]}
    assert got == {
        (3, "Jenis"),
        (4, "Kunci"),
        (5, "Soal"),
        (6, "Kunci"),
        (7, "Pertanyaan"),
        (8, "Bobot"),
    }
    assert r.json()["valid_rows"] == 1

    commit = owner.post(
        f"{QB}/{bank}/{COMMIT}", json={"preview_id": r.json()["preview_id"], "confirm": True}
    )
    assert commit.status_code == 409
    assert owner.get(f"{QB}/{bank}/questions").json() == []


def test_xlsx_import_commits_and_groups_stimulus(owner: TestClient, subject_id: str) -> None:
    bank = new_bank(owner, subject_id)
    data = xlsx(
        [
            _row(
                Jenis="PG",
                Stimulus="Teks bersama",
                Pertanyaan="S1",
                Kunci="b",
                Opsi_A="1",
                Opsi_B="2",
            ),
            _row(
                Jenis="MCMA",
                Stimulus="Teks bersama",
                Pertanyaan="S2",
                Bobot="2,5",
                Kunci="A, C",
                Opsi_A="x",
                Opsi_B="y",
                Opsi_C="z",
            ),
            _row(Jenis="KATEGORI", Pertanyaan="S3", Kunci="B,S", Opsi_A="p", Opsi_B="q"),
        ],
        HEADER,
    )
    preview = _preview(owner, bank, data).json()
    assert preview["errors"] == []
    body = {"preview_id": preview["preview_id"], "confirm": True}
    assert owner.post(f"{QB}/{bank}/{COMMIT}", json=body).json()["imported"] == 3
    assert owner.post(f"{QB}/{bank}/{COMMIT}", json=body).status_code == 409

    qs = owner.get(f"{QB}/{bank}/questions").json()
    assert qs[1]["weight"] == 2.5 and [o["is_correct"] for o in qs[1]["options"]] == [
        True,
        False,
        True,
    ]
    assert qs[0]["stimulus_id"] == qs[1]["stimulus_id"] is not None and qs[2]["stimulus_id"] is None
    assert [s["correct_value"] for s in qs[2]["statements"]] == [True, False]

    other_bank = new_bank(owner, subject_id, "Lain")
    preview2 = _preview(owner, bank, data).json()
    r = owner.post(
        f"{QB}/{other_bank}/{COMMIT}", json={"preview_id": preview2["preview_id"], "confirm": True}
    )
    assert r.status_code == 404


@pytest.mark.parametrize("fmt", ["xlsx", "docx"])
def test_downloaded_templates_import_without_errors(
    owner: TestClient, subject_id: str, fmt: str
) -> None:
    bank = new_bank(owner, subject_id)
    template = owner.get(f"/api/v1/question-import-templates/{fmt}")
    assert template.status_code == 200
    r = _preview(owner, bank, template.content, f"t.{fmt}")
    assert r.status_code == 200, r.text
    assert r.json()["errors"] == [] and r.json()["valid_rows"] == 3


# ---- Import DOCX (T-016) -------------------------------------------------------


def _zip(files: dict[str, bytes | str]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def test_docx_joins_split_runs_and_imports(owner: TestClient, subject_id: str) -> None:
    bank = new_bank(owner, subject_id)
    data = build_docx(
        [
            [
                ("Jenis", "PG"),
                ("Pertanyaan", "Ibu kota RI?"),
                ("Kunci", "A"),
                ("Opsi A", "Jakarta"),
                ("Opsi B", "Bandung"),
            ]
        ]
    )
    # Simulasikan Word yang memecah satu kata menjadi beberapa run.
    data = _zip(
        {
            **{
                n: zipfile.ZipFile(BytesIO(data)).read(n)
                for n in zipfile.ZipFile(BytesIO(data)).namelist()
            },
            "word/document.xml": zipfile.ZipFile(BytesIO(data))
            .read("word/document.xml")
            .replace(
                b'<w:t xml:space="preserve">Jakarta</w:t>',
                b"<w:t>Jak</w:t></w:r><w:r><w:t>arta</w:t>",
            ),
        }
    )
    preview = _preview(owner, bank, data, "soal.docx").json()
    assert preview["errors"] == [], preview
    owner.post(f"{QB}/{bank}/{COMMIT}", json={"preview_id": preview["preview_id"], "confirm": True})
    assert owner.get(f"{QB}/{bank}/questions").json()[0]["options"][0]["text"] == "Jakarta"


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (b"bukan zip", 422, "INVALID_FILE"),
        (_zip({"word/other.xml": "<x/>", "word/document.xml.bak": "x"}), 422, "INVALID_FILE"),
        (
            _zip(
                {
                    "word/document.xml": '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa">'
                    '<!ENTITY b "&a;&a;&a;&a;">]><w:document '
                    + W_NS
                    + "><w:body>&b;</w:body></w:document>"
                }
            ),
            422,
            "INVALID_FILE",
        ),
        (
            _zip({"word/document.xml": "<x/>", "word/vbaProject.bin": "macro"}),
            422,
            "MACRO_NOT_ALLOWED",
        ),
        (
            _zip(
                {
                    "word/document.xml": "<w:document "
                    + W_NS
                    + "><w:body>"
                    + " " * 5_000_000
                    + "</w:body></w:document>"
                }
            ),
            413,
            "FILE_TOO_LARGE",
        ),
        (
            _zip(
                {
                    "word/document.xml": "<w:document "
                    + W_NS
                    + "><w:body><w:p/></w:body></w:document>"
                }
            ),
            422,
            "INVALID_TEMPLATE",
        ),
    ],
)
def test_malicious_or_malformed_docx_rejected(
    owner: TestClient, subject_id: str, data: bytes, status: int, code: str
) -> None:
    bank = new_bank(owner, subject_id)
    r = _preview(owner, bank, data, "soal.docx")
    assert (r.status_code, r.json()["error"]["code"]) == (status, code)


def test_docx_unknown_label_and_image_in_cell_are_row_errors(
    owner: TestClient, subject_id: str
) -> None:
    bank = new_bank(owner, subject_id)
    doc = build_docx(
        [[("Jenis", "PG"), ("Soalnya", "x")], [("Jenis", "PG"), ("Pertanyaan", "IMG")]]
    )
    z = zipfile.ZipFile(BytesIO(doc))
    xml = z.read("word/document.xml").replace(
        b"IMG</w:t></w:r>", b"IMG</w:t></w:r><w:r><w:drawing/></w:r>"
    )
    data = _zip({**{n: z.read(n) for n in z.namelist()}, "word/document.xml": xml})
    errors = _preview(owner, bank, data, "soal.docx").json()["errors"]
    assert {(e["row_number"], e["field"]) for e in errors} == {(1, "Tabel"), (2, "Pertanyaan")}
    assert json.dumps(errors).count("belum didukung") == 1
