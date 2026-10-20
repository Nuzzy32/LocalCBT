"""Ujian: draft, publish (snapshot immutable), token, kebijakan hasil, pratinjau acak."""

import json
import secrets
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import Connection, RowMapping, text

from app import scoring
from app.auth import CurrentUser, hash_password, require_roles
from app.db import DB, audit
from app.errors import ApiError, not_found
from app.media import media_url
from app.questions import load_questions, to_student_question

router = APIRouter(prefix="/api/v1", tags=["Exams"])
Teacher = Annotated[CurrentUser, Depends(require_roles("TEACHER"))]

Token = Annotated[str, StringConstraints(min_length=4, max_length=32)]


class ResultPolicy(BaseModel):
    visibility: Literal["TEACHER_ONLY", "IMMEDIATE", "AFTER_PUBLICATION"] = "TEACHER_ONLY"
    review_enabled: bool = False
    review_available_from: AwareDatetime | None = None
    show_correct_answers: bool = False
    # Pembahasan belum ada di bank soal; aktifkan bila field penjelasan ditambahkan.
    show_explanations: Literal[False] = False


class ExamIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    subject_id: UUID
    class_ids: list[UUID] = Field(min_length=1, max_length=100)
    question_ids: list[UUID] = Field(min_length=1, max_length=500)
    start_window_from: AwareDatetime
    start_window_until: AwareDatetime
    duration_seconds: int = Field(ge=60, le=86400)
    token: Token | None = None  # wajib saat membuat; kosong saat edit = tidak diubah
    shuffle_questions: Literal[True] = True
    shuffle_options: Literal[True] = True
    result_policy: ResultPolicy = ResultPolicy()

    @model_validator(mode="after")
    def check(self) -> Self:
        if self.start_window_until <= self.start_window_from:
            raise ValueError("Batas akhir mulai harus setelah waktu mulai dibuka.")
        if len(set(self.class_ids)) != len(self.class_ids):
            raise ValueError("Kelas tidak boleh dipilih dua kali.")
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("Soal tidak boleh dipilih dua kali.")
        return self


EXAM_SELECT = """
select e.id, e.title, e.subject_id, sub.name as subject_name, e.author_teacher_id,
       e.status as stored_status,
       case when e.status = 'DRAFT' then 'DRAFT'
            when now() < e.start_window_from then 'PUBLISHED'
            when now() <= e.start_window_until + make_interval(secs => e.duration_sec)
              then 'ACTIVE'
            else 'CLOSED' end as status,
       e.start_window_from, e.start_window_until, e.duration_sec, e.question_ids,
       e.result_visibility, e.review_policy, e.scoring_rule_version, e.published_at,
       coalesce((select array_agg(a.class_id) from exam_assignments a where a.exam_id = e.id),
                '{}') as class_ids,
       coalesce((select string_agg(c.code, ', ' order by c.code)
                 from exam_assignments a join classes c on c.id = a.class_id
                 where a.exam_id = e.id), '') as class_names,
       case when e.status = 'DRAFT' then cardinality(e.question_ids)
            else (select count(*) from exam_question_snapshots x where x.exam_id = e.id)
       end as question_count
from exams e join subjects sub on sub.id = e.subject_id
"""


# Peserta ujian: siswa di kelas yang ditugaskan + siswa yang sudah punya attempt (walau sudah
# dipindah kelas). UNION: siswa di dua kelas yang sama-sama ditugaskan tetap muncul sekali.
ROSTER = """
with roster as (
  select m.student_id from exam_assignments ea
  join class_memberships m on m.class_id = ea.class_id where ea.exam_id = :e
  union
  select student_id from exam_attempts where exam_id = :e
)
"""


def get_exam(db: Connection, user: CurrentUser, exam_id: UUID, lock: bool = False) -> RowMapping:
    # M7: pengawas yang ditugaskan juga boleh membaca (tanpa kunci).
    row = (
        db.execute(
            text(EXAM_SELECT + " where e.id = :id and e.author_teacher_id = :uid"),
            {"id": exam_id, "uid": user.id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    if lock:
        db.execute(text("select 1 from exams where id = :id for update"), {"id": exam_id})
    return row


def exam_out(row: RowMapping) -> dict[str, Any]:
    policy = row["review_policy"] or {}
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "subject_id": str(row["subject_id"]),
        "subject_name": row["subject_name"],
        "status": row["status"],
        "start_window_from": row["start_window_from"],
        "start_window_until": row["start_window_until"],
        "duration_seconds": row["duration_sec"],
        "class_ids": [str(c) for c in row["class_ids"]],
        "class_names": row["class_names"],
        "question_ids": [str(q) for q in row["question_ids"]],
        "question_count": row["question_count"],
        "shuffle_questions": True,
        "shuffle_options": True,
        "result_policy": {
            "visibility": row["result_visibility"],
            "review_enabled": policy.get("enabled", False),
            "review_available_from": policy.get("available_from"),
            "show_correct_answers": policy.get("show_correct_answers", False),
            "show_explanations": False,
        },
        "scoring_rule_version": row["scoring_rule_version"],
        "published_at": row["published_at"],
        # Token tidak pernah dikirim balik (hanya hash yang disimpan).
    }


def usable_question_ids(
    db: Connection, user: CurrentUser, subject_id: UUID, ids: list[UUID]
) -> set[UUID]:
    """Soal aktif, mapel sama, di bank milik sendiri atau dibagikan minimal COPY."""
    return set(
        db.scalars(
            text("""
            select q.id from questions q
            join question_banks b on b.id = q.bank_id
            left join bank_shares s on s.bank_id = b.id and s.teacher_id = :uid
            where q.id = any(:ids) and q.active and b.subject_id = :s
              and (b.owner_teacher_id = :uid or s.permission in ('COPY', 'EDIT'))
            """),
            {"ids": ids, "uid": user.id, "s": subject_id},
        )
    )


def reference_errors(
    db: Connection,
    user: CurrentUser,
    subject_id: UUID,
    class_ids: list[UUID],
    question_ids: list[UUID],
) -> list[str]:
    errors = []
    taught = db.scalar(
        text("""
        select count(*) from classes c
        where c.id = any(:c) and c.active and exists (
          select 1 from teaching_assignments t
          where t.class_id = c.id and t.teacher_id = :uid and t.subject_id = :s)
        """),
        {"c": class_ids, "uid": user.id, "s": subject_id},
    )
    if taught != len(class_ids):
        errors.append("Ada kelas yang tidak Anda ajar untuk mata pelajaran ini.")
    if len(usable_question_ids(db, user, subject_id, question_ids)) != len(question_ids):
        errors.append(
            "Ada soal yang sudah dihapus, beda mata pelajaran, atau tidak boleh Anda pakai."
        )
    return errors


def publish_errors(db: Connection, user: CurrentUser, exam: RowMapping) -> list[str]:
    errors = reference_errors(
        db, user, exam["subject_id"], list(exam["class_ids"]), list(exam["question_ids"])
    )
    if not exam["class_ids"]:
        errors.append("Pilih minimal satu kelas.")
    if not exam["question_ids"]:
        errors.append("Pilih minimal satu soal.")
    if db.scalar(text("select now() >= :t"), {"t": exam["start_window_until"]}):
        errors.append("Batas akhir mulai ujian sudah lewat. Ubah jadwal terlebih dahulu.")
    return errors


def _review_json(p: ResultPolicy) -> str:
    return json.dumps(
        {
            "enabled": p.review_enabled,
            "available_from": p.review_available_from.isoformat()
            if p.review_available_from
            else None,
            "show_correct_answers": p.show_correct_answers,
            "show_explanations": False,
        }
    )


def _save(db: Connection, user: CurrentUser, body: ExamIn, exam_id: UUID | None) -> UUID:
    errors = reference_errors(db, user, body.subject_id, body.class_ids, body.question_ids)
    if errors:
        raise ApiError(422, "INVALID_REFERENCE", " ".join(errors))
    p = body.result_policy
    params = {
        "id": exam_id,
        "uid": user.id,
        "s": body.subject_id,
        "title": body.title,
        "from": body.start_window_from,
        "until": body.start_window_until,
        "dur": body.duration_seconds,
        "q": body.question_ids,
        "vis": p.visibility,
        "review": _review_json(p),
        "token": hash_password(body.token) if body.token else None,
    }
    if exam_id is None:
        exam_id = db.scalar(
            text("""
            insert into exams (author_teacher_id, subject_id, title, start_window_from,
              start_window_until, duration_sec, token_hash, question_ids, result_visibility,
              review_policy)
            values (:uid, :s, :title, :from, :until, :dur, :token, :q, :vis,
              cast(:review as jsonb))
            returning id
            """),
            params,
        )
    elif not db.scalar(
        text("""
        update exams set subject_id = :s, title = :title, start_window_from = :from,
          start_window_until = :until, duration_sec = :dur,
          token_hash = coalesce(:token, token_hash), question_ids = :q,
          result_visibility = :vis, review_policy = cast(:review as jsonb), updated_at = now()
        where id = :id and status = 'DRAFT' returning id
        """),
        params,
    ):
        raise ApiError(409, "EXAM_PUBLISHED", "Ujian sudah dipublish dan tidak bisa diubah.")
    db.execute(text("delete from exam_assignments where exam_id = :id"), {"id": exam_id})
    db.execute(
        text("insert into exam_assignments (exam_id, class_id) values (:e, :c)"),
        [{"e": exam_id, "c": c} for c in body.class_ids],
    )
    assert exam_id is not None
    return exam_id


# ---- Endpoint --------------------------------------------------------------------


@router.get("/exams")
def list_exams(user: Teacher, db: DB) -> list[dict[str, Any]]:
    rows = db.execute(
        text(EXAM_SELECT + " where e.author_teacher_id = :uid order by e.start_window_from desc"),
        {"uid": user.id},
    ).mappings()
    return [exam_out(r) for r in rows]


@router.post("/exams", status_code=201)
def create_exam(body: ExamIn, user: Teacher, db: DB) -> dict[str, Any]:
    if not body.token:
        raise ApiError(422, "VALIDATION_ERROR", "Token ujian wajib diisi (4–32 karakter).")
    exam_id = _save(db, user, body, None)
    return exam_out(get_exam(db, user, exam_id))


@router.get("/exams/{exam_id}")
def get_exam_detail(exam_id: UUID, user: Teacher, db: DB) -> dict[str, Any]:
    return {
        **exam_out(get_exam(db, user, exam_id)),
        "scoring_rule": {"version": scoring.RULE_VERSION, "text": scoring.RULE_TEXT},
    }


@router.put("/exams/{exam_id}")
def update_exam(exam_id: UUID, body: ExamIn, user: Teacher, db: DB) -> dict[str, Any]:
    if get_exam(db, user, exam_id, lock=True)["stored_status"] != "DRAFT":
        raise ApiError(409, "EXAM_PUBLISHED", "Ujian sudah dipublish dan tidak bisa diubah.")
    _save(db, user, body, exam_id)
    return exam_out(get_exam(db, user, exam_id))


class TokenIn(BaseModel):
    token: Token


@router.put("/exams/{exam_id}/token", status_code=204)
def rotate_token(exam_id: UUID, body: TokenIn, user: Teacher, db: DB) -> None:
    # Boleh kapan pun (mis. token bocor saat ujian). Token tidak ikut diaudit, hanya kejadiannya.
    get_exam(db, user, exam_id, lock=True)
    db.execute(
        text("update exams set token_hash = :h, updated_at = now() where id = :id"),
        {"h": hash_password(body.token), "id": exam_id},
    )
    audit(db, user.id, "EXAM_TOKEN_ROTATED", "exam", exam_id)


@router.put("/teacher/exams/{exam_id}/result-policy")
def update_result_policy(
    exam_id: UUID, body: ResultPolicy, user: Teacher, db: DB
) -> dict[str, Any]:
    get_exam(db, user, exam_id, lock=True)
    db.execute(
        text("""
        update exams set result_visibility = :vis, review_policy = cast(:review as jsonb),
          updated_at = now() where id = :id
        """),
        {
            "id": exam_id,
            "vis": body.visibility,
            "review": _review_json(body),
        },
    )
    audit(
        db, user.id, "RESULT_POLICY_CHANGED", "exam", exam_id, metadata=body.model_dump(mode="json")
    )
    return exam_out(get_exam(db, user, exam_id))["result_policy"]  # type: ignore[no-any-return]


class PublishIn(BaseModel):
    confirm: Literal[True]
    # Guru wajib mengonfirmasi versi aturan penilaian secara eksplisit (DEC-01 belum disahkan).
    scoring_rule_version: Literal["PROPOSED-1"]


SNAPSHOT_INSERT = """
insert into exam_question_snapshots (exam_id, source_question_id, snapshot_version,
  question_type, stem, weight, media_asset_id, stimulus_media_asset_id, stimulus_payload,
  options_payload, statements_payload, answer_key, ordinal)
select :e, q.id, q.version, q.type, q.stem, q.weight, q.media_asset_id, s.media_asset_id,
  case when s.id is null then null
       else jsonb_build_object('id', s.id, 'text', s.body_text) end,
  coalesce((select jsonb_agg(jsonb_build_object('id', o.id, 'text', o.content)
                             order by o.sort_order)
            from question_options o where o.question_id = q.id), '[]'),
  coalesce((select jsonb_agg(jsonb_build_object('id', st.id, 'text', st.content)
                             order by st.sort_order)
            from question_statements st where st.question_id = q.id), '[]'),
  case when q.type = 'CATEGORY_CHOICE' then jsonb_build_object('statements',
         coalesce((select jsonb_object_agg(st.id, st.correct_value)
                   from question_statements st where st.question_id = q.id), '{}'))
       else jsonb_build_object('correct_option_ids',
         coalesce((select jsonb_agg(o.id order by o.sort_order)
                   from question_options o where o.question_id = q.id and o.is_correct), '[]'))
  end,
  t.ord
from unnest(cast(:ids as uuid[])) with ordinality as t(qid, ord)
join questions q on q.id = t.qid and q.active
left join stimuli s on s.id = q.stimulus_id
"""


@router.post("/exams/{exam_id}/publish")
def publish_exam(exam_id: UUID, body: PublishIn, user: Teacher, db: DB) -> dict[str, Any]:
    exam = get_exam(db, user, exam_id, lock=True)
    if exam["stored_status"] != "DRAFT":
        raise ApiError(409, "EXAM_PUBLISHED", "Ujian sudah dipublish.")
    errors = publish_errors(db, user, exam)
    if errors:
        raise ApiError(422, "PUBLISH_INVALID", " ".join(errors))
    # Soal ber-stimulus sama dibekukan berdampingan; satu INSERT..SELECT = satu snapshot konsisten.
    order = scoring.group_order(load_questions(db, None, list(exam["question_ids"])))
    inserted = db.execute(text(SNAPSHOT_INSERT), {"e": exam_id, "ids": order}).rowcount
    if inserted != len(exam["question_ids"]):
        raise ApiError(409, "SOURCE_CHANGED", "Ada soal yang baru saja dihapus. Coba lagi.")
    db.execute(
        text("""
        update exams set status = 'PUBLISHED', published_at = now(),
          scoring_rule_version = :rule, updated_at = now() where id = :id
        """),
        {"id": exam_id, "rule": body.scoring_rule_version},
    )
    audit(
        db,
        user.id,
        "EXAM_PUBLISHED",
        "exam",
        exam_id,
        metadata={"scoring_rule_version": body.scoring_rule_version, "questions": inserted},
    )
    return exam_out(get_exam(db, user, exam_id))


@router.post("/exams/{exam_id}/unpublish")
def unpublish_exam(exam_id: UUID, user: Teacher, db: DB) -> dict[str, Any]:
    exam = get_exam(db, user, exam_id, lock=True)
    if exam["status"] != "PUBLISHED":  # turunan: belum masuk start window
        raise ApiError(
            409, "EXAM_STARTED", "Ujian yang sudah dibuka atau masih draft tidak bisa ditarik."
        )
    if db.scalar(text("select 1 from exam_attempts where exam_id = :id limit 1"), {"id": exam_id}):
        raise ApiError(409, "EXAM_STARTED", "Sudah ada siswa yang mulai; ujian tidak bisa ditarik.")
    db.execute(text("delete from exam_question_snapshots where exam_id = :id"), {"id": exam_id})
    db.execute(
        text("""
        update exams set status = 'DRAFT', published_at = null, scoring_rule_version = null,
          updated_at = now() where id = :id
        """),
        {"id": exam_id},
    )
    audit(db, user.id, "EXAM_UNPUBLISHED", "exam", exam_id)
    return exam_out(get_exam(db, user, exam_id))


def load_snapshot(
    db: Connection, exam_id: UUID, question_id: UUID | None = None
) -> list[dict[str, Any]]:
    """Soal ujian beku DENGAN kunci (staf/grading). Untuk siswa lewat to_student_question.
    Bentuknya juga memenuhi masukan scoring.permute/validate_answer/score."""
    rows = db.execute(
        text("""
        select id, question_type, stem, weight, media_asset_id, stimulus_media_asset_id,
               stimulus_payload, options_payload, statements_payload, answer_key
        from exam_question_snapshots
        where exam_id = :e and (cast(:q as uuid) is null or id = :q) order by ordinal
        """),
        {"e": exam_id, "q": question_id},
    ).mappings()
    out = []
    for r in rows:
        stim = r["stimulus_payload"]
        out.append(
            {
                "id": str(r["id"]),
                "type": r["question_type"],
                "stem": r["stem"],
                "weight": r["weight"],
                "stimulus_id": stim["id"] if stim else None,
                "stimulus": stim["text"] if stim else None,
                "stimulus_image_url": media_url(r["stimulus_media_asset_id"]),
                "image_url": media_url(r["media_asset_id"]),
                "options": r["options_payload"],
                "statements": r["statements_payload"],
                "option_ids": [o["id"] for o in r["options_payload"]],
                "statement_ids": [s["id"] for s in r["statements_payload"]],
                "answer_key": r["answer_key"],
            }
        )
    return out


def apply_permutation(qs: list[dict[str, Any]], perm: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {q["id"]: q for q in qs}
    out = []
    for p in perm:
        q = by_id[p["question_id"]]
        options = {o["id"]: o for o in q["options"]}
        statements = {s["id"]: s for s in q["statements"]}
        out.append(
            {
                **q,
                "options": [options[i] for i in p["option_ids"]],
                "statements": [statements[i] for i in p["statement_ids"]],
            }
        )
    return out


@router.get("/teacher/exams/{exam_id}/preview")
def preview_exam(exam_id: UUID, user: Teacher, db: DB) -> dict[str, Any]:
    exam = get_exam(db, user, exam_id)
    if exam["stored_status"] == "DRAFT":
        allowed = usable_question_ids(db, user, exam["subject_id"], list(exam["question_ids"]))
        qs = load_questions(db, None, list(allowed)) if allowed else []
        for q in qs:
            q["option_ids"] = [o["id"] for o in q["options"]]
            q["statement_ids"] = [s["id"] for s in q["statements"]]
        errors = publish_errors(db, user, exam)
    else:
        qs, errors = load_snapshot(db, exam_id), []
    # Contoh urutan acak seperti yang akan diterima satu peserta.
    sample = apply_permutation(qs, scoring.permute(qs, secrets.randbits(32)))
    return {
        "questions": [to_student_question(q) for q in sample],
        "validation_errors": errors,
    }
