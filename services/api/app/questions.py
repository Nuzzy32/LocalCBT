"""Bank soal: akses (owner/share), CRUD soal 3 tipe, stimulus, salin, preview tanpa kunci."""

from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import Connection, RowMapping, text

from app.auth import CurrentUser, require_roles
from app.db import DB, audit
from app.errors import ApiError, forbidden, not_found
from app.media import media_readable, media_url

router = APIRouter(prefix="/api/v1", tags=["Question Bank"])
Teacher = Annotated[CurrentUser, Depends(require_roles("TEACHER"))]

Access = Literal["VIEW", "COPY", "EDIT", "OWNER"]
LEVEL = {"VIEW": 1, "COPY": 2, "EDIT": 3, "OWNER": 4}

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class OptionIn(BaseModel):
    text: Text
    is_correct: bool


class StatementIn(BaseModel):
    text: Text
    correct_value: bool


class QuestionIn(BaseModel):
    """Satu-satunya validator soal: dipakai editor, import, dan salin."""

    type: Literal["SINGLE_CHOICE", "MULTIPLE_CHOICE", "CATEGORY_CHOICE"]
    stem: LongText
    weight: Decimal = Field(gt=0, max_digits=8, decimal_places=2)
    stimulus_id: UUID | None = None
    media_asset_id: UUID | None = None
    options: list[OptionIn] = []
    statements: list[StatementIn] = []

    @model_validator(mode="after")
    def check_by_type(self) -> Self:
        if self.type == "CATEGORY_CHOICE":
            if self.options:
                raise ValueError("Soal Benar/Salah tidak memakai opsi pilihan.")
            if not 2 <= len(self.statements) <= 20:
                raise ValueError("Soal Benar/Salah butuh 2–20 pernyataan.")
            texts = [s.text for s in self.statements]
        else:
            if self.statements:
                raise ValueError("Soal pilihan ganda tidak memakai pernyataan Benar/Salah.")
            if not 2 <= len(self.options) <= 10:
                raise ValueError("Soal pilihan ganda butuh 2–10 opsi.")
            keys = sum(o.is_correct for o in self.options)
            if self.type == "SINGLE_CHOICE" and keys != 1:
                raise ValueError("Pilihan ganda harus punya tepat satu kunci jawaban.")
            if self.type == "MULTIPLE_CHOICE" and keys < 1:
                raise ValueError("Pilihan ganda kompleks minimal punya satu kunci jawaban.")
            texts = [o.text for o in self.options]
        if len({t.lower() for t in texts}) != len(texts):
            raise ValueError("Isi opsi/pernyataan dalam satu soal tidak boleh sama.")
        return self


def get_bank(db: Connection, user: CurrentUser, bank_id: UUID, need: Access) -> RowMapping:
    """Bank yang terlihat oleh user; 404 bila tidak terlihat, 403 bila izinnya kurang."""
    row = (
        db.execute(
            text("""
            select b.id, b.title, b.subject_id, sub.name as subject_name, b.owner_teacher_id,
                   case when b.owner_teacher_id = :uid then 'OWNER' else s.permission end as access
            from question_banks b
            join subjects sub on sub.id = b.subject_id
            left join bank_shares s on s.bank_id = b.id and s.teacher_id = :uid
            where b.id = :id and (b.owner_teacher_id = :uid or s.teacher_id is not null)
            """),
            {"id": bank_id, "uid": user.id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    if LEVEL[row["access"]] < LEVEL[need]:
        raise forbidden()
    return row


def load_questions(
    db: Connection, bank_id: UUID | None, ids: list[UUID] | None = None
) -> list[dict[str, Any]]:
    """Soal aktif lengkap DENGAN kunci (hanya untuk staf). Untuk siswa: to_student_question."""
    rows = db.execute(
        text("""
        select q.id, q.type, q.stem, q.weight, q.version, q.stimulus_id, q.media_asset_id,
               s.body_text as stimulus, s.media_asset_id as stimulus_media_id,
               coalesce((select json_agg(json_build_object(
                           'id', o.id, 'text', o.content, 'is_correct', o.is_correct)
                         order by o.sort_order)
                         from question_options o where o.question_id = q.id), '[]') as options,
               coalesce((select json_agg(json_build_object(
                           'id', st.id, 'text', st.content, 'correct_value', st.correct_value)
                         order by st.sort_order)
                         from question_statements st where st.question_id = q.id), '[]')
                 as statements
        from questions q
        left join stimuli s on s.id = q.stimulus_id
        where (cast(:b as uuid) is null or q.bank_id = :b) and q.active
          and (cast(:ids as uuid[]) is null or q.id = any(:ids))
        order by coalesce(s.created_at, q.created_at), q.created_at
        """),
        {"b": bank_id, "ids": ids},
    ).mappings()
    return [
        {
            "id": str(r["id"]),
            "type": r["type"],
            "stem": r["stem"],
            "weight": float(r["weight"]),
            "version": r["version"],
            "stimulus_id": str(r["stimulus_id"]) if r["stimulus_id"] else None,
            "stimulus": r["stimulus"],
            "stimulus_media_id": str(r["stimulus_media_id"]) if r["stimulus_media_id"] else None,
            "stimulus_image_url": media_url(r["stimulus_media_id"]),
            "media_asset_id": str(r["media_asset_id"]) if r["media_asset_id"] else None,
            "image_url": media_url(r["media_asset_id"]),
            "options": r["options"],
            "statements": r["statements"],
        }
        for r in rows
    ]


def to_student_question(q: dict[str, Any]) -> dict[str, Any]:
    """Whitelist eksplisit: kunci (is_correct/correct_value) tidak pernah ikut. Dipakai ulang M5."""
    return {
        "id": q["id"],
        "type": q["type"],
        "stem": q["stem"],
        "weight": float(q["weight"]),
        "stimulus_id": q["stimulus_id"],
        "stimulus": q["stimulus"],
        "stimulus_image_url": q["stimulus_image_url"],
        "image_url": q["image_url"],
        "options": [{"id": o["id"], "text": o["text"]} for o in q["options"]],
        "statements": [{"id": s["id"], "text": s["text"]} for s in q["statements"]],
    }


def check_refs(db: Connection, user: CurrentUser, bank_id: UUID, q: QuestionIn) -> None:
    if q.stimulus_id and not db.scalar(
        text("select 1 from stimuli where id = :s and bank_id = :b"),
        {"s": q.stimulus_id, "b": bank_id},
    ):
        raise ApiError(422, "INVALID_REFERENCE", "Stimulus tidak ada di bank soal ini.")
    if q.media_asset_id and not media_readable(db, user.id, q.media_asset_id):
        raise ApiError(422, "INVALID_REFERENCE", "Gambar tidak ditemukan.")


def save_question(
    db: Connection,
    bank_id: UUID,
    q: QuestionIn,
    user_id: UUID,
    question_id: UUID | None = None,
) -> UUID:
    """Insert atau update di tempat (version+1). Snapshot ujian (M4) menyalin isi sebagai jsonb,
    jadi mengganti baris opsi di sini tidak mengubah ujian yang sudah dipublish."""
    params = {
        "b": bank_id,
        "s": q.stimulus_id,
        "m": q.media_asset_id,
        "type": q.type,
        "stem": q.stem,
        "w": q.weight,
        "uid": user_id,
        "id": question_id,
    }
    if question_id is None:
        question_id = db.scalar(
            text("""
            insert into questions (bank_id, stimulus_id, media_asset_id, type, stem, weight,
                                   created_by)
            values (:b, :s, :m, :type, :stem, :w, :uid) returning id
            """),
            params,
        )
    else:
        # ponytail: last-write-wins antar editor; tambah If-Match: version bila guru sering bentrok.
        updated = db.scalar(
            text("""
            update questions set stimulus_id = :s, media_asset_id = :m, type = :type,
              stem = :stem, weight = :w, version = version + 1, updated_at = now()
            where id = :id and bank_id = :b and active returning id
            """),
            params,
        )
        if updated is None:
            raise not_found()
        db.execute(text("delete from question_options where question_id = :id"), params)
        db.execute(text("delete from question_statements where question_id = :id"), params)
    assert question_id is not None
    if q.options:
        db.execute(
            text("""
            insert into question_options (question_id, content, sort_order, is_correct)
            values (:q, :c, :n, :k)
            """),
            [
                {"q": question_id, "c": o.text, "n": n, "k": o.is_correct}
                for n, o in enumerate(q.options)
            ],
        )
    if q.statements:
        db.execute(
            text("""
            insert into question_statements (question_id, content, sort_order, correct_value)
            values (:q, :c, :n, :k)
            """),
            [
                {"q": question_id, "c": s.text, "n": n, "k": s.correct_value}
                for n, s in enumerate(q.statements)
            ],
        )
    return question_id


# ---- Bank ------------------------------------------------------------------------


class BankIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    subject_id: UUID


@router.get("/question-banks")
def list_banks(user: Teacher, db: DB) -> list[dict[str, Any]]:
    rows = db.execute(
        text("""
        select b.id, b.title, b.subject_id, sub.name as subject_name, u.display_name as owner_name,
               case when b.owner_teacher_id = :uid then 'OWNER' else s.permission end as access,
               (select count(*) from questions q where q.bank_id = b.id and q.active)
                 as question_count
        from question_banks b
        join subjects sub on sub.id = b.subject_id
        join users u on u.id = b.owner_teacher_id
        left join bank_shares s on s.bank_id = b.id and s.teacher_id = :uid
        where b.owner_teacher_id = :uid or s.teacher_id is not null
        order by b.created_at desc
        """),
        {"uid": user.id},
    ).mappings()
    return [{**r, "id": str(r["id"]), "subject_id": str(r["subject_id"])} for r in rows]


@router.post("/question-banks", status_code=201)
def create_bank(body: BankIn, user: Teacher, db: DB) -> dict[str, Any]:
    if not db.scalar(text("select 1 from subjects where id = :s"), {"s": body.subject_id}):
        raise ApiError(422, "INVALID_REFERENCE", "Mata pelajaran tidak ditemukan.")
    bank_id = db.scalar(
        text("""
        insert into question_banks (owner_teacher_id, subject_id, title)
        values (:uid, :s, :t) returning id
        """),
        {"uid": user.id, "s": body.subject_id, "t": body.title},
    )
    assert bank_id is not None
    return _bank_out(get_bank(db, user, bank_id, "OWNER"))


def _bank_out(bank: RowMapping) -> dict[str, Any]:
    return {
        "id": str(bank["id"]),
        "title": bank["title"],
        "subject_id": str(bank["subject_id"]),
        "subject_name": bank["subject_name"],
        "owner_teacher_id": str(bank["owner_teacher_id"]),
        "access": bank["access"],
    }


@router.get("/question-banks/{bank_id}")
def get_bank_detail(bank_id: UUID, user: Teacher, db: DB) -> dict[str, Any]:
    return _bank_out(get_bank(db, user, bank_id, "VIEW"))


@router.get("/teachers")
def list_teachers(user: Teacher, db: DB) -> list[dict[str, str]]:
    # Untuk dialog berbagi: nama saja, tanpa username/peran lain.
    rows = db.execute(
        text("""
        select u.id, u.display_name from users u
        join user_roles r on r.user_id = u.id and r.role = 'TEACHER'
        where u.status = 'ACTIVE' and u.id <> :uid order by u.display_name
        """),
        {"uid": user.id},
    )
    return [{"id": str(r.id), "display_name": r.display_name} for r in rows]


# ---- Soal ------------------------------------------------------------------------


@router.get("/question-banks/{bank_id}/questions")
def list_questions(bank_id: UUID, user: Teacher, db: DB) -> list[dict[str, Any]]:
    get_bank(db, user, bank_id, "VIEW")
    return load_questions(db, bank_id)


@router.post("/question-banks/{bank_id}/questions", status_code=201)
def create_question(bank_id: UUID, body: QuestionIn, user: Teacher, db: DB) -> dict[str, Any]:
    get_bank(db, user, bank_id, "EDIT")
    check_refs(db, user, bank_id, body)
    question_id = save_question(db, bank_id, body, user.id)
    return load_questions(db, bank_id, [question_id])[0]


@router.put("/question-banks/{bank_id}/questions/{question_id}")
def update_question(
    bank_id: UUID, question_id: UUID, body: QuestionIn, user: Teacher, db: DB
) -> dict[str, Any]:
    get_bank(db, user, bank_id, "EDIT")
    check_refs(db, user, bank_id, body)
    save_question(db, bank_id, body, user.id, question_id)
    return load_questions(db, bank_id, [question_id])[0]


@router.delete("/question-banks/{bank_id}/questions/{question_id}", status_code=204)
def delete_question(bank_id: UUID, question_id: UUID, user: Teacher, db: DB) -> None:
    get_bank(db, user, bank_id, "EDIT")
    # Soft delete: snapshot ujian & riwayat nilai tetap bisa merujuk soal sumber.
    if not db.scalar(
        text("""
        update questions set active = false, updated_at = now()
        where id = :q and bank_id = :b and active returning id
        """),
        {"q": question_id, "b": bank_id},
    ):
        raise not_found()


@router.get("/question-banks/{bank_id}/preview")
def preview_bank(bank_id: UUID, user: Teacher, db: DB) -> list[dict[str, Any]]:
    get_bank(db, user, bank_id, "VIEW")
    return [to_student_question(q) for q in load_questions(db, bank_id)]


# ---- Stimulus --------------------------------------------------------------------


class StimulusIn(BaseModel):
    body_text: LongText | None = None
    media_asset_id: UUID | None = None

    @model_validator(mode="after")
    def not_empty(self) -> Self:
        if self.body_text is None and self.media_asset_id is None:
            raise ValueError("Stimulus harus berisi teks atau gambar.")
        return self


@router.get("/question-banks/{bank_id}/stimuli")
def list_stimuli(bank_id: UUID, user: Teacher, db: DB) -> list[dict[str, Any]]:
    get_bank(db, user, bank_id, "VIEW")
    rows = db.execute(
        text("""
        select id, body_text, media_asset_id from stimuli where bank_id = :b order by created_at
        """),
        {"b": bank_id},
    )
    return [
        {
            "id": str(r.id),
            "body_text": r.body_text,
            "media_asset_id": str(r.media_asset_id) if r.media_asset_id else None,
            "image_url": media_url(r.media_asset_id),
        }
        for r in rows
    ]


@router.post("/question-banks/{bank_id}/stimuli", status_code=201)
def create_stimulus(bank_id: UUID, body: StimulusIn, user: Teacher, db: DB) -> dict[str, Any]:
    get_bank(db, user, bank_id, "EDIT")
    if body.media_asset_id and not media_readable(db, user.id, body.media_asset_id):
        raise ApiError(422, "INVALID_REFERENCE", "Gambar tidak ditemukan.")
    stimulus_id = db.scalar(
        text("""
        insert into stimuli (bank_id, body_text, media_asset_id) values (:b, :t, :m) returning id
        """),
        {"b": bank_id, "t": body.body_text, "m": body.media_asset_id},
    )
    return {
        "id": str(stimulus_id),
        "body_text": body.body_text,
        "media_asset_id": str(body.media_asset_id) if body.media_asset_id else None,
        "image_url": media_url(body.media_asset_id),
    }


# ---- Salin & berbagi -------------------------------------------------------------


class CopyIn(BaseModel):
    target_bank_id: UUID
    question_ids: list[UUID] | None = None


@router.post("/question-banks/{bank_id}/copy")
def copy_questions(bank_id: UUID, body: CopyIn, user: Teacher, db: DB) -> dict[str, int]:
    get_bank(db, user, bank_id, "COPY")
    get_bank(db, user, body.target_bank_id, "EDIT")
    stimulus_map: dict[str, UUID] = {}
    copied = 0
    for q in load_questions(db, bank_id, body.question_ids):
        sid = q["stimulus_id"]
        if sid and sid not in stimulus_map:  # satu stimulus disalin sekali: pengelompokan utuh
            new_sid = db.scalar(
                text("""
                insert into stimuli (bank_id, body_text, media_asset_id)
                values (:b, :t, :m) returning id
                """),
                {"b": body.target_bank_id, "t": q["stimulus"], "m": q["stimulus_media_id"]},
            )
            assert new_sid is not None
            stimulus_map[sid] = new_sid
        payload = QuestionIn.model_validate(
            {**q, "stimulus_id": stimulus_map.get(sid) if sid else None}
        )
        save_question(db, body.target_bank_id, payload, user.id)
        copied += 1
    return {"copied": copied}


class ShareIn(BaseModel):
    teacher_id: UUID
    permission: Literal["VIEW", "COPY", "EDIT"]


@router.get("/question-banks/{bank_id}/shares")
def list_shares(bank_id: UUID, user: Teacher, db: DB) -> list[dict[str, str]]:
    get_bank(db, user, bank_id, "OWNER")
    rows = db.execute(
        text("""
        select s.teacher_id, u.display_name, s.permission from bank_shares s
        join users u on u.id = s.teacher_id where s.bank_id = :b order by u.display_name
        """),
        {"b": bank_id},
    )
    return [
        {
            "teacher_id": str(r.teacher_id),
            "display_name": r.display_name,
            "permission": r.permission,
        }
        for r in rows
    ]


@router.post("/question-banks/{bank_id}/shares")
def share_bank(bank_id: UUID, body: ShareIn, user: Teacher, db: DB) -> dict[str, str]:
    bank = get_bank(db, user, bank_id, "OWNER")
    if body.teacher_id == bank["owner_teacher_id"] or not db.scalar(
        text("select 1 from user_roles where user_id = :t and role = 'TEACHER'"),
        {"t": body.teacher_id},
    ):
        raise ApiError(422, "INVALID_REFERENCE", "Pilih guru lain sebagai penerima.")
    db.execute(
        text("""
        insert into bank_shares (bank_id, teacher_id, permission, granted_by)
        values (:b, :t, :p, :uid)
        on conflict (bank_id, teacher_id) do update set permission = :p, granted_by = :uid
        """),
        {"b": bank_id, "t": body.teacher_id, "p": body.permission, "uid": user.id},
    )
    audit(
        db,
        user.id,
        "BANK_SHARED",
        "question_bank",
        bank_id,
        metadata={"teacher_id": str(body.teacher_id), "permission": body.permission},
    )
    return {"teacher_id": str(body.teacher_id), "permission": body.permission}


@router.delete("/question-banks/{bank_id}/shares/{teacher_id}", status_code=204)
def revoke_share(bank_id: UUID, teacher_id: UUID, user: Teacher, db: DB) -> None:
    get_bank(db, user, bank_id, "OWNER")
    db.execute(
        text("delete from bank_shares where bank_id = :b and teacher_id = :t"),
        {"b": bank_id, "t": teacher_id},
    )
    audit(
        db,
        user.id,
        "BANK_SHARE_REVOKED",
        "question_bank",
        bank_id,
        metadata={"teacher_id": str(teacher_id)},
    )
