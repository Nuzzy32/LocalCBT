"""Upload & akses gambar soal.

Hanya PNG/JPEG/WebP, dikenali dari magic bytes (bukan dari nama berkas/MIME kiriman klien).
"""

import hashlib
import os
import struct
import tempfile
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import Connection, text

from app.auth import CurrentUser, User, require_roles
from app.config import settings
from app.db import DB
from app.errors import ApiError, not_found

router = APIRouter(prefix="/api/v1/media", tags=["Question Bank"])
Teacher = Annotated[CurrentUser, Depends(require_roles("TEACHER"))]

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_SIDE = 4096
MAX_PIXELS = 16_000_000

# Bank yang terlihat oleh :uid (dimiliki atau dibagikan). Dipakai ulang oleh questions.py.
VISIBLE_BANKS = """
  select id from question_banks where owner_teacher_id = :uid
  union select bank_id from bank_shares where teacher_id = :uid
"""


def sniff_image(data: bytes) -> tuple[str, int, int] | None:
    """(mime, lebar, tinggi) dari header berkas, atau None bila bukan PNG/JPEG/WebP."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            w, h = struct.unpack(">II", data[16:24])
            return "image/png", w, h
        if data[:3] == b"\xff\xd8\xff":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    return None
                marker = data[i + 1]
                if marker == 0xFF:  # byte pengisi
                    i += 1
                    continue
                if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # marker tanpa panjang
                    i += 2
                    continue
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # SOFn
                    h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                    return "image/jpeg", w, h
                i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
            return None
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
                w, h = struct.unpack("<HH", data[26:30])
                return "image/webp", w & 0x3FFF, h & 0x3FFF
            if chunk == b"VP8L" and data[20] == 0x2F:
                bits = int.from_bytes(data[21:25], "little")
                return "image/webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if chunk == b"VP8X":
                w = int.from_bytes(data[24:27], "little") + 1
                h = int.from_bytes(data[27:30], "little") + 1
                return "image/webp", w, h
    except (struct.error, IndexError):
        return None
    return None


def media_path(sha256: str) -> str:
    return os.path.join(settings.media_dir, sha256[:2], sha256)


def media_readable(db: Connection, user_id: UUID, media_id: UUID) -> bool:
    # Pengunggah, guru yang bisa melihat bank/ujian pemakai, atau siswa yang punya attempt
    # di ujian yang snapshot-nya memakai gambar ini.
    return bool(
        db.scalar(
            text(f"""
            select 1 from media_assets m
            where m.id = :id and (
              m.created_by = :uid
              or exists (select 1 from questions q
                         where q.media_asset_id = m.id and q.bank_id in ({VISIBLE_BANKS}))
              or exists (select 1 from stimuli s
                         where s.media_asset_id = m.id and s.bank_id in ({VISIBLE_BANKS}))
              or exists (select 1 from exam_question_snapshots x join exams e on e.id = x.exam_id
                         where m.id in (x.media_asset_id, x.stimulus_media_asset_id)
                           and e.author_teacher_id = :uid)
              or exists (select 1 from exam_question_snapshots x
                         join exam_attempts a on a.exam_id = x.exam_id
                         where m.id in (x.media_asset_id, x.stimulus_media_asset_id)
                           and a.student_id = :uid))
            """),  # noqa: S608 — fragmen konstan, bukan input
            {"id": media_id, "uid": user_id},
        )
    )


def media_attachable(db: Connection, user_id: UUID, media_id: UUID) -> bool:
    """Boleh dipasang ke soal/stimulus milik sendiri: pengunggah, atau gambar dipakai di bank
    yang dimiliki / dibagikan minimal COPY. Izin VIEW hanya untuk melihat (M9-02)."""
    return bool(
        db.scalar(
            text("""
            select 1 from media_assets m
            where m.id = :id and (
              m.created_by = :uid
              or exists (
                select 1 from question_banks b
                left join bank_shares s on s.bank_id = b.id and s.teacher_id = :uid
                where (b.owner_teacher_id = :uid or s.permission in ('COPY', 'EDIT'))
                  and (exists (select 1 from questions q
                               where q.bank_id = b.id and q.media_asset_id = m.id)
                       or exists (select 1 from stimuli st
                                  where st.bank_id = b.id and st.media_asset_id = m.id))))
            """),
            {"id": media_id, "uid": user_id},
        )
    )


def media_url(media_id: Any) -> str | None:
    return f"/api/v1/media/{media_id}" if media_id else None


@router.post("", status_code=201)
def upload_media(
    file: UploadFile,
    user: Teacher,
    db: DB,
    alt_text: Annotated[str | None, Form(max_length=300)] = None,
) -> dict[str, Any]:
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "Ukuran gambar maksimal 2 MB.")
    info = sniff_image(data)
    if info is None:
        raise ApiError(415, "UNSUPPORTED_IMAGE", "Gunakan gambar PNG, JPEG, atau WebP.")
    mime, width, height = info
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE and width * height <= MAX_PIXELS):
        raise ApiError(422, "IMAGE_DIMENSIONS", "Dimensi gambar maksimal 4096×4096 piksel.")

    sha = hashlib.sha256(data).hexdigest()
    path = media_path(sha)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Tulis atomik: berkas tidak pernah terlihat setengah jadi.
        # ponytail: berkas yatim bila transaksi gagal; GC media tak terpakai di M8.
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(path), delete=False) as tmp:
            tmp.write(data)
        os.replace(tmp.name, path)

    row = db.execute(
        text("""
        insert into media_assets (sha256, mime, size_bytes, width, height, alt_text, created_by)
        values (:sha, :mime, :size, :w, :h, :alt, :uid)
        on conflict (created_by, sha256)
          do update set alt_text = coalesce(:alt, media_assets.alt_text)
        returning id
        """),
        {
            "sha": sha,
            "mime": mime,
            "size": len(data),
            "w": width,
            "h": height,
            "alt": alt_text or None,
            "uid": user.id,
        },
    ).one()
    return {
        "id": str(row.id),
        "mime": mime,
        "width": width,
        "height": height,
        "size_bytes": len(data),
        "url": media_url(row.id),
    }


@router.get("/{media_id}")
def get_media(media_id: UUID, user: User, db: DB) -> FileResponse:
    if not media_readable(db, user.id, media_id):
        raise not_found()
    row = db.execute(
        text("select sha256, mime from media_assets where id = :id"), {"id": media_id}
    ).one()
    # nosniff + sandbox: berkas polyglot (mis. PNG berisi HTML) tidak bisa dijalankan browser.
    return FileResponse(
        media_path(row.sha256),
        media_type=row.mime,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
