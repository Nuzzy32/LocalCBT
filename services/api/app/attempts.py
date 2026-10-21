"""Mesin ujian siswa: daftar, token, mulai (atomik), simpan jawaban, submit, hasil, pembahasan.

Prinsip: server authoritative. Waktu = now() database; satu attempt per (ujian, siswa);
ACK simpan dikirim hanya setelah commit; kunci jawaban tidak pernah keluar kecuali policy membuka.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection, RowMapping, text

from app import scoring
from app.auth import CurrentUser, LoginRateLimiter, require_roles, verify_password
from app.db import DB, audit
from app.errors import ApiError, not_found
from app.exams import apply_permutation, load_snapshot
from app.questions import to_student_question

router = APIRouter(prefix="/api/v1", tags=["Student Attempts"])
Student = Annotated[CurrentUser, Depends(require_roles("STUDENT"))]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
log = logging.getLogger("localcbt.attempts")

token_limiter = LoginRateLimiter(per_user=5, per_ip=30)
# ponytail: kunci grant per proses; restart server = siswa memasukkan token lagi.
_GRANT_KEY = secrets.token_bytes(32)
GRANT_TTL = 300


def _grant(exam_id: UUID, user_id: UUID, exp: int) -> str:
    mac = hmac.new(_GRANT_KEY, f"{exam_id}:{user_id}:{exp}".encode(), hashlib.sha256)
    return f"{exp}.{mac.hexdigest()}"


def _grant_ok(grant: str, exam_id: UUID, user_id: UUID) -> bool:
    exp_text, _, _ = grant.partition(".")
    if not (exp_text.isascii() and exp_text.isdigit()) or int(exp_text) < time.time():
        return False
    return hmac.compare_digest(grant.encode(), _grant(exam_id, user_id, int(exp_text)).encode())


ASSIGNED = """exists (select 1 from exam_assignments ea
  join class_memberships m on m.class_id = ea.class_id
  where ea.exam_id = e.id and m.student_id = :uid)"""


def exam_for_student(db: Connection, user: CurrentUser, exam_id: UUID) -> RowMapping:
    row = (
        db.execute(
            text(f"""
            select e.id, e.token_hash,
                   now() between e.start_window_from and e.start_window_until as open
            from exams e where e.id = :id and e.status = 'PUBLISHED' and {ASSIGNED}
            """),  # noqa: S608 — fragmen konstan
            {"id": exam_id, "uid": user.id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    return row


def _ensure_open(exam: RowMapping) -> None:
    if not exam["open"]:
        raise ApiError(
            403, "EXAM_NOT_OPEN", "Ujian belum tersedia atau periode mulai sudah berakhir."
        )


ATTEMPT_SELECT = """
select a.id, a.exam_id, a.student_id, a.state, a.started_at, a.effective_deadline_at,
       a.question_order, a.submitted_at, a.graded_at, a.score_total, a.score_max,
       e.title as exam_title, e.scoring_rule_version, e.result_visibility, e.review_policy,
       e.results_published_at,
       a.pause_consumed_sec, now() as server_now,
       a.effective_deadline_at > now() as answerable,
       -- Selama jeda, sisa waktu dibekukan pada saat jeda dimulai.
       greatest(0, ceil(extract(epoch from a.effective_deadline_at
         - case when a.state = 'PAUSED' then a.paused_at else now() end)))::int as remaining,
       case when a.state = 'PAUSED'
            then greatest(0, floor(extract(epoch from now() - a.paused_at)))::int
            else 0 end as incident_sec,
       (select count(*) from announcements n where n.exam_id = a.exam_id) as announcements_count,
       -- Ujian "usai" baru bila jendela mulai lewat DAN tidak ada peserta yang masih mengerjakan
       -- (jeda, outage, dan tambahan waktu bisa melewati start_window_until + durasi).
       now() > e.start_window_until + make_interval(secs => e.duration_sec)
         and not exists (select 1 from exam_attempts x
                         where x.exam_id = e.id and x.state in ('IN_PROGRESS', 'PAUSED'))
         as exam_closed
from exam_attempts a join exams e on e.id = a.exam_id
"""


def get_attempt(db: Connection, user: CurrentUser, attempt_id: UUID) -> RowMapping:
    row = (
        db.execute(
            text(ATTEMPT_SELECT + " where a.id = :id and a.student_id = :uid"),
            {"id": attempt_id, "uid": user.id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    return row


def _lock(db: Connection, attempt_id: UUID) -> None:
    db.execute(text("select 1 from exam_attempts where id = :id for update"), {"id": attempt_id})


HEARTBEAT_TIMEOUT = 15  # ADR-004 (usulan): heartbeat 5 dtk, putus setelah 15 dtk tanpa heartbeat
PAUSE_CAP = 300  # per insiden
PAUSE_TOTAL = 600  # akumulasi per attempt, tidak di-reset oleh reconnect/ganti perangkat


def close_pause(db: Connection, attempt_id: UUID, reason: Literal["RECONNECT", "CAP"]) -> None:
    """Tutup jeda yang sedang berjalan (baris attempt sudah dikunci pemanggil): geser deadline
    sebesar kredit = min(lama jeda, 300, sisa jatah 600)."""
    db.execute(
        text("""
        with c as (
          select id, paused_at,
                 least(greatest(0, floor(extract(epoch from now() - paused_at)))::int,
                       :cap, :total - pause_consumed_sec) as credit
          from exam_attempts where id = :id and state = 'PAUSED'
        ), u as (
          update exam_attempts a set state = 'IN_PROGRESS', paused_at = null,
            effective_deadline_at = a.effective_deadline_at + make_interval(secs => c.credit),
            pause_consumed_sec = a.pause_consumed_sec + c.credit
          from c where a.id = c.id returning a.id
        )
        insert into pause_incidents (attempt_id, detected_at, resumed_at, credited_sec, end_reason)
        select c.id, c.paused_at, now(), c.credit, :reason from c join u using (id)
        """),
        {"id": attempt_id, "reason": reason, "cap": PAUSE_CAP, "total": PAUSE_TOTAL},
    )


def live(
    db: Connection, user: CurrentUser, attempt_id: UUID, tab_visible: bool | None = None
) -> RowMapping:
    """Setiap permintaan siswa ke attempt-nya = bukti hidup: catat heartbeat, akhiri jeda,
    lalu auto-submit bila batas waktu lewat. Mengembalikan status terbaru."""
    get_attempt(db, user, attempt_id)
    _lock(db, attempt_id)
    # Pindah tab hanya indikator untuk ditinjau manusia (T-022), dicatat pada transisi saja.
    if tab_visible is False and db.scalar(
        text("select last_tab_visible is distinct from false from exam_attempts where id = :id"),
        {"id": attempt_id},
    ):
        audit(db, user.id, "TAB_HIDDEN", "exam_attempt", attempt_id)
    db.execute(
        text("""
        update exam_attempts set last_heartbeat_at = now(),
          last_tab_visible = coalesce(:tv, last_tab_visible)
        where id = :id
        """),
        {"id": attempt_id, "tv": tab_visible},
    )
    close_pause(db, attempt_id, "RECONNECT")
    expire_due(db, attempt_id=attempt_id)
    return get_attempt(db, user, attempt_id)


def _grade(db: Connection, attempt_id: UUID, exam_id: UUID, rule: str) -> None:
    answers = {
        str(r.snapshot_question_id): r.answer
        for r in db.execute(
            text("select snapshot_question_id, answer from student_answers where attempt_id = :a"),
            {"a": attempt_id},
        )
    }
    scores = [
        {
            "a": attempt_id,
            "q": q["id"],
            "e": scoring.score(rule, q, answers.get(q["id"])),
            "m": q["weight"],
        }
        for q in load_snapshot(db, exam_id)
    ]
    db.execute(
        text("""
        insert into question_scores (attempt_id, snapshot_question_id, earned, max_score)
        values (:a, :q, :e, :m)
        """),
        scores,
    )
    db.execute(
        text("""
        update exam_attempts set state = 'GRADED', graded_at = now(), grading_version = :rule,
          score_total = :total, score_max = :max where id = :a
        """),
        {
            "a": attempt_id,
            "rule": rule,
            "total": sum(s["e"] for s in scores),
            "max": sum(s["m"] for s in scores),
        },
    )


def finalize(db: Connection, attempt_id: UUID, reason: Literal["STUDENT", "DEADLINE"]) -> bool:
    """Kumpulkan sekali (idempotent) lalu nilai. True bila panggilan ini yang mengumpulkan."""
    _lock(db, attempt_id)
    row = db.execute(
        text("""
        update exam_attempts set state = 'SUBMITTED', submit_reason = :r,
          submitted_at = least(now(), effective_deadline_at)
        where id = :id and state in ('IN_PROGRESS', 'PAUSED')
        returning exam_id, (select scoring_rule_version from exams where id = exam_id) as rule
        """),
        {"id": attempt_id, "r": reason},
    ).first()
    if row is None:
        return False
    # Penilaian sinkron di savepoint: bila gagal, attempt tetap SUBMITTED dengan jawaban utuh
    # (dinilai ulang lewat M7). ponytail: pindah ke outbox/worker bila ujian sangat besar.
    try:
        with db.begin_nested():
            _grade(db, attempt_id, row.exam_id, row.rule)
    except Exception:
        log.exception("grading failed", extra={"extra_fields": {"attempt_id": str(attempt_id)}})
    return True


def regrade(db: Connection, attempt_id: UUID) -> bool:
    """Nilai ulang attempt yang SUBMITTED tapi gagal dinilai. GRADED tidak pernah disentuh."""
    _lock(db, attempt_id)
    row = db.execute(
        text("""
        select a.exam_id, e.scoring_rule_version as rule
        from exam_attempts a join exams e on e.id = a.exam_id
        where a.id = :id and a.state = 'SUBMITTED'
        """),
        {"id": attempt_id},
    ).first()
    if row is None:
        return False
    try:
        with db.begin_nested():
            _grade(db, attempt_id, row.exam_id, row.rule)
        return True
    except Exception:
        log.exception("regrade failed", extra={"extra_fields": {"attempt_id": str(attempt_id)}})
        return False


def expire_due(
    db: Connection, *, student_id: UUID | None = None, attempt_id: UUID | None = None
) -> None:
    """Auto-submit attempt yang melewati batas waktu server (lazy + sweep periodik)."""
    for (due,) in db.execute(
        text("""
        select id from exam_attempts
        where state = 'IN_PROGRESS' and effective_deadline_at <= now()
          and (cast(:s as uuid) is null or student_id = :s)
          and (cast(:a as uuid) is null or id = :a)
        """),
        {"s": student_id, "a": attempt_id},
    ):
        finalize(db, due, "DEADLINE")


def _receipt_id(attempt_id: UUID) -> str:
    return f"LCBT-{attempt_id.hex[:8].upper()}"


def _timer(att: RowMapping) -> dict[str, Any]:
    return {
        "server_now": att["server_now"],
        "state": att["state"],
        "deadline_at": att["effective_deadline_at"],
        "remaining_seconds": att["remaining"] if att["state"] in ("IN_PROGRESS", "PAUSED") else 0,
        "pause_consumed_seconds": att["pause_consumed_sec"],
        "incident_pause_seconds": att["incident_sec"],
        # Untuk tampilan klien saat offline: jatah jeda insiden berikutnya.
        "pause_allowance_seconds": min(PAUSE_CAP, PAUSE_TOTAL - att["pause_consumed_sec"]),
        "heartbeat_timeout_seconds": HEARTBEAT_TIMEOUT,
        "announcements_count": att["announcements_count"],
    }


def _answers(db: Connection, attempt_id: UUID) -> dict[str, RowMapping]:
    rows = db.execute(
        text("""
        select snapshot_question_id, answer, marked, server_revision, client_revision, saved_at,
               idempotency_key
        from student_answers where attempt_id = :a
        """),
        {"a": attempt_id},
    ).mappings()
    return {str(r["snapshot_question_id"]): r for r in rows}


def attempt_out(db: Connection, att: RowMapping) -> dict[str, Any]:
    done = att["state"] in ("SUBMITTED", "GRADED")
    out: dict[str, Any] = {
        "id": str(att["id"]),
        "exam_id": str(att["exam_id"]),
        "exam_title": att["exam_title"],
        "state": att["state"],
        "timer": _timer(att),
        "submitted_at": att["submitted_at"],
        "receipt_id": _receipt_id(att["id"]) if done else None,
        # Setelah dikumpulkan soal tidak dikirim lagi (perangkat bersama, USER_FLOW §8).
        "questions": [],
        "answers": [],
    }
    if not done:
        qs = apply_permutation(load_snapshot(db, att["exam_id"]), att["question_order"])
        out["questions"] = [to_student_question(q) for q in qs]
        out["answers"] = [
            {
                "question_id": qid,
                "answer": a["answer"],
                "marked_for_review": a["marked"],
                "server_revision": a["server_revision"],
                "client_revision": a["client_revision"],
                "saved_at": a["saved_at"],
            }
            for qid, a in _answers(db, att["id"]).items()
        ]
    return out


# ---- Endpoint --------------------------------------------------------------------


@router.get("/student/exams")
def list_student_exams(user: Student, db: DB) -> list[dict[str, Any]]:
    expire_due(db, student_id=user.id)
    rows = db.execute(
        text(f"""
        select e.id, e.title, sub.name as subject_name, e.duration_sec, e.start_window_from,
               e.start_window_until, a.id as attempt_id,
               case when a.state in ('SUBMITTED', 'GRADED') then 'COMPLETED'
                    when a.id is not null then 'IN_PROGRESS'
                    when now() < e.start_window_from then 'SCHEDULED'
                    when now() <= e.start_window_until then 'AVAILABLE'
                    else 'CLOSED' end as status
        from exams e join subjects sub on sub.id = e.subject_id
        left join exam_attempts a on a.exam_id = e.id and a.student_id = :uid
        where e.status = 'PUBLISHED' and {ASSIGNED}
        order by e.start_window_from
        """),  # noqa: S608 — fragmen konstan
        {"uid": user.id},
    ).mappings()
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "subject_name": r["subject_name"],
            "duration_seconds": r["duration_sec"],
            "start_window_from": r["start_window_from"],
            "start_window_until": r["start_window_until"],
            "status": r["status"],
            "attempt_id": str(r["attempt_id"]) if r["attempt_id"] else None,
        }
        for r in rows
    ]


class TokenIn(BaseModel):
    token: str = Field(min_length=4, max_length=32)


@router.post("/student/exams/{exam_id}/token/verify")
def verify_token(
    exam_id: UUID, body: TokenIn, request: Request, user: Student, db: DB
) -> dict[str, Any]:
    exam = exam_for_student(db, user, exam_id)
    _ensure_open(exam)
    ip = request.client.host if request.client else "-"
    key = f"{exam_id}:{user.id}"
    wait = token_limiter.acquire(key, ip)
    if wait:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "Terlalu banyak percobaan token. Hubungi pengawas.",
            {"Retry-After": str(wait)},
        )
    if not verify_password(exam["token_hash"], body.token):
        raise ApiError(403, "TOKEN_INVALID", "Token tidak sesuai. Tanyakan token kepada pengawas.")
    token_limiter.success(key, ip)
    exp = int(time.time()) + GRANT_TTL
    return {
        "start_grant": _grant(exam_id, user.id, exp),
        "expires_at": db.scalar(text("select to_timestamp(:t)"), {"t": exp}),
    }


class StartIn(BaseModel):
    start_grant: str = Field(max_length=200)
    confirm_start: Literal[True]


@router.post("/student/exams/{exam_id}/attempts")
def start_attempt(
    exam_id: UUID,
    body: StartIn,
    response: Response,
    user: Student,
    db: DB,
    _key: IdempotencyKey,
) -> dict[str, Any]:
    exam = exam_for_student(db, user, exam_id)
    existing = db.scalar(
        text("select id from exam_attempts where exam_id = :e and student_id = :uid"),
        {"e": exam_id, "uid": user.id},
    )
    if existing is None:
        _ensure_open(exam)
        if not _grant_ok(body.start_grant, exam_id, user.id):
            raise ApiError(403, "START_GRANT_INVALID", "Masukkan token ujian lagi.")
        qs = load_snapshot(db, exam_id)
        seed = secrets.randbits(63)
        existing = db.scalar(
            text("""
            insert into exam_attempts (exam_id, student_id, effective_deadline_at,
              randomization_seed, question_order)
            select :e, :uid, now() + make_interval(secs => duration_sec), :seed,
                   cast(:order as jsonb)
            from exams where id = :e
            on conflict (exam_id, student_id) do nothing
            returning id
            """),
            {
                "e": exam_id,
                "uid": user.id,
                "seed": seed,
                "order": json.dumps(scoring.permute(qs, seed)),
            },
        )
        if existing is not None:
            response.status_code = 201
        else:  # balapan dengan permintaan paralel: pakai attempt yang sudah ada
            existing = db.scalar(
                text("select id from exam_attempts where exam_id = :e and student_id = :uid"),
                {"e": exam_id, "uid": user.id},
            )
    assert existing is not None
    expire_due(db, attempt_id=existing)
    return attempt_out(db, get_attempt(db, user, existing))


@router.get("/student/attempts/{attempt_id}")
def get_student_attempt(attempt_id: UUID, user: Student, db: DB) -> dict[str, Any]:
    return attempt_out(db, live(db, user, attempt_id))


class SaveAnswerIn(BaseModel):
    answer: dict[str, Any] | None
    client_revision: int = Field(ge=1, le=2_000_000_000)
    marked_for_review: bool


@router.put("/student/attempts/{attempt_id}/answers/{question_id}")
def save_answer(
    attempt_id: UUID,
    question_id: UUID,
    body: SaveAnswerIn,
    key: IdempotencyKey,
    user: Student,
    db: DB,
) -> dict[str, Any]:
    # ponytail: mengunci attempt menserialkan simpanan satu siswa; cukup untuk 1 perangkat/siswa.
    att = live(db, user, attempt_id)
    snapshot = load_snapshot(db, att["exam_id"], question_id)
    if not snapshot:
        raise not_found()
    try:
        answer = scoring.validate_answer(snapshot[0], body.answer)
    except scoring.InvalidAnswer as e:
        raise ApiError(422, "INVALID_ANSWER", str(e)) from e

    stored = _answers(db, attempt_id).get(str(question_id))
    if stored is not None and stored["idempotency_key"] == key:
        # Permintaan ulang (mis. ACK hilang di jaringan): kembalikan tanda terima yang sama.
        if (stored["client_revision"], stored["answer"], stored["marked"]) != (
            body.client_revision,
            answer,
            body.marked_for_review,
        ):
            raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "Kunci permintaan dipakai ulang.")
        return {
            "status": "persisted",
            "server_revision": stored["server_revision"],
            "saved_at": stored["saved_at"],
        }

    if att["state"] != "IN_PROGRESS" or not att["answerable"]:
        raise ApiError(
            409, "ATTEMPT_LOCKED", "Ujian telah selesai. Jawaban baru tidak dapat disimpan."
        )
    saved = db.execute(
        text("""
        insert into student_answers (attempt_id, snapshot_question_id, answer, marked,
          server_revision, client_revision, idempotency_key)
        values (:a, :q, cast(:ans as jsonb), :m, 1, :cr, :k)
        on conflict (attempt_id, snapshot_question_id) do update set
          answer = excluded.answer, marked = excluded.marked,
          server_revision = student_answers.server_revision + 1,
          client_revision = excluded.client_revision,
          idempotency_key = excluded.idempotency_key, saved_at = now()
        where student_answers.client_revision < excluded.client_revision
        returning server_revision, saved_at
        """),
        {
            "a": attempt_id,
            "q": question_id,
            "ans": json.dumps(answer) if answer is not None else None,
            "m": body.marked_for_review,
            "cr": body.client_revision,
            "k": key,
        },
    ).first()
    if saved is None:
        raise ApiError(409, "REVISION_CONFLICT", "Perubahan jawaban perlu disinkronkan. Coba lagi.")
    return {
        "status": "persisted",
        "server_revision": saved.server_revision,
        "saved_at": saved.saved_at,
    }


class HeartbeatIn(BaseModel):
    tab_visible: bool | None = None  # indikator saja, bukan bukti curang


@router.post("/student/attempts/{attempt_id}/heartbeat")
def heartbeat(attempt_id: UUID, body: HeartbeatIn, user: Student, db: DB) -> dict[str, Any]:
    return _timer(live(db, user, attempt_id, body.tab_visible))


class SubmitIn(BaseModel):
    confirm: Literal[True]


@router.post("/student/attempts/{attempt_id}/submit")
def submit_attempt(
    attempt_id: UUID,
    body: SubmitIn,
    response: Response,
    user: Student,
    db: DB,
    _key: IdempotencyKey,
) -> dict[str, Any]:
    att = live(db, user, attempt_id)
    reason: Literal["STUDENT", "DEADLINE"] = "STUDENT" if att["answerable"] else "DEADLINE"
    if finalize(db, attempt_id, reason):
        response.status_code = 201
    att = get_attempt(db, user, attempt_id)
    return {
        "attempt_id": str(attempt_id),
        "status": att["state"],
        "submitted_at": att["submitted_at"],
        "receipt_id": _receipt_id(attempt_id),
    }


def _result_visible(att: RowMapping) -> bool:
    if att["state"] != "GRADED":
        return False
    if att["result_visibility"] == "IMMEDIATE":
        return True
    published = att["results_published_at"]
    return bool(
        att["result_visibility"] == "AFTER_PUBLICATION"
        and published
        and published <= att["server_now"]
    )


@router.get("/student/attempts/{attempt_id}/result")
def get_result(attempt_id: UUID, user: Student, db: DB) -> dict[str, Any]:
    att = live(db, user, attempt_id)
    if not _result_visible(att):
        raise ApiError(
            403, "RESULT_HIDDEN", "Nilai belum tersedia. Guru akan menentukan waktu publikasi."
        )
    return {
        "attempt_id": str(attempt_id),
        # Kontrak API: number. Dihitung & disimpan sebagai Decimal 2 desimal.
        "total_score": float(att["score_total"]),
        "max_score": float(att["score_max"]),
        "graded_at": att["graded_at"],
    }


@router.get("/student/attempts/{attempt_id}/review")
def get_review(attempt_id: UUID, user: Student, db: DB) -> dict[str, Any]:
    att = live(db, user, attempt_id)
    policy = att["review_policy"] or {}
    available_from = policy.get("available_from")
    is_open = (
        att["state"] in ("SUBMITTED", "GRADED")
        and policy.get("enabled")
        # Kunci tidak boleh terbuka selama peserta lain masih mengerjakan.
        and att["exam_closed"]
        and (
            available_from is None
            or db.scalar(text("select now() >= cast(:t as timestamptz)"), {"t": available_from})
        )
    )
    if not is_open:
        raise ApiError(403, "REVIEW_CLOSED", "Pembahasan belum dibuka oleh guru.")
    show_score = _result_visible(att)
    show_key = bool(policy.get("show_correct_answers"))
    answers = _answers(db, attempt_id)
    earned = (
        {
            str(r.snapshot_question_id): r.earned
            for r in db.execute(
                text(
                    "select snapshot_question_id, earned from question_scores where attempt_id = :a"
                ),
                {"a": attempt_id},
            )
        }
        if show_score
        else {}
    )
    items = []
    for q in apply_permutation(load_snapshot(db, att["exam_id"]), att["question_order"]):
        own = answers.get(q["id"])
        item: dict[str, Any] = {
            "question": to_student_question(q),
            "own_answer": own["answer"] if own else None,
            "marked": bool(own and own["marked"]),
        }
        if show_score:
            points = earned.get(q["id"])
            item["earned"] = float(points) if points is not None else None
        if show_key:
            item["correct_answer"] = q["answer_key"]
        items.append(item)
    return {"attempt_id": str(attempt_id), "questions": items}


@router.get("/student/attempts/{attempt_id}/announcements")
def list_announcements(attempt_id: UUID, user: Student, db: DB) -> list[dict[str, Any]]:
    """Pengumuman pengawas untuk ujian ini; diambil ulang setelah reconnect (teks saja)."""
    att = get_attempt(db, user, attempt_id)
    rows = db.execute(
        text("select message, issued_at from announcements where exam_id = :e order by issued_at"),
        {"e": att["exam_id"]},
    )
    return [{"message": r.message, "issued_at": r.issued_at} for r in rows]
