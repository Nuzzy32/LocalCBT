"""Pengawasan: penugasan pengawas, monitor (HTTP + WebSocket), pindah perangkat, tambah waktu,
pengumuman. Pengawas = guru pemilik ujian atau pengguna yang ditugaskan pada ujian itu."""

import asyncio
from collections import Counter
from typing import Annotated, Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Request, WebSocket
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.attempts import HEARTBEAT_TIMEOUT, expire_due
from app.auth import COOKIE, CurrentUser, require_roles, session_user
from app.config import settings
from app.db import DB, audit, engine
from app.errors import ApiError, not_found
from app.exams import ROSTER, get_exam

router = APIRouter(prefix="/api/v1", tags=["Supervision"])
Supervisor = Annotated[CurrentUser, Depends(require_roles("TEACHER", "PROCTOR"))]
Teacher = Annotated[CurrentUser, Depends(require_roles("TEACHER"))]

SWITCH_PERMIT_SECONDS = 300
MONITOR_PUSH_SECONDS = 3
SUPERVISES = """e.status = 'PUBLISHED' and (e.author_teacher_id = :uid or exists (
  select 1 from proctor_assignments p where p.exam_id = e.id and p.user_id = :uid))"""


class ReasonIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


def _deny(user: CurrentUser, action: str, target_id: UUID) -> ApiError:
    # Ditolak & diaudit (T-021). Transaksi request di-rollback oleh error → transaksi sendiri.
    with engine.begin() as own:
        audit(
            own,
            user.id,
            "PROCTOR_ACTION_DENIED",
            "exam_attempt",
            target_id,
            metadata={"action": action},
        )
    return not_found()


def supervised_attempt(db: Connection, user: CurrentUser, attempt_id: UUID, action: str) -> Any:
    row = db.execute(
        text(f"""
        select a.id, a.state from exam_attempts a join exams e on e.id = a.exam_id
        where a.id = :id and {SUPERVISES}
        for update of a
        """),  # noqa: S608 — fragmen konstan
        {"id": attempt_id, "uid": user.id},
    ).first()
    if row is None:
        raise _deny(user, action, attempt_id)
    return row


def supervises(db: Connection, user: CurrentUser, exam_id: UUID) -> bool:
    return bool(
        db.scalar(
            text(f"select 1 from exams e where e.id = :e and {SUPERVISES}"),  # noqa: S608
            {"e": exam_id, "uid": user.id},
        )
    )


# ---- Penugasan pengawas (oleh guru pemilik ujian) ---------------------------------


@router.get("/exams/{exam_id}/proctors")
def list_proctors(exam_id: UUID, user: Teacher, db: DB) -> dict[str, Any]:
    exam = get_exam(db, user, exam_id)
    assigned = db.execute(
        text("""
        select u.id, u.display_name from proctor_assignments p join users u on u.id = p.user_id
        where p.exam_id = :e order by u.display_name
        """),
        {"e": exam_id},
    )
    candidates = db.execute(
        text("""
        select distinct u.id, u.display_name from users u
        join user_roles r on r.user_id = u.id and r.role in ('PROCTOR', 'TEACHER')
        where u.status = 'ACTIVE' and u.id <> :author order by u.display_name
        """),
        {"author": exam["author_teacher_id"]},
    )
    return {
        "assigned": [{"id": str(r.id), "display_name": r.display_name} for r in assigned],
        "candidates": [{"id": str(r.id), "display_name": r.display_name} for r in candidates],
    }


class ProctorIn(BaseModel):
    user_id: UUID


@router.post("/exams/{exam_id}/proctors", status_code=201)
def assign_proctor(exam_id: UUID, body: ProctorIn, user: Teacher, db: DB) -> dict[str, str]:
    get_exam(db, user, exam_id, lock=True)
    added = db.scalar(
        text("""
        insert into proctor_assignments (exam_id, user_id, assigned_by)
        select :e, u.id, :by from users u
        where u.id = :u and u.status = 'ACTIVE' and exists (
          select 1 from user_roles r where r.user_id = u.id and r.role in ('PROCTOR', 'TEACHER'))
        returning user_id
        """),
        {"e": exam_id, "u": body.user_id, "by": user.id},
    )
    if added is None:
        raise not_found()
    audit(db, user.id, "PROCTOR_ASSIGNED", "exam", exam_id, metadata={"user_id": str(body.user_id)})
    return {"user_id": str(body.user_id)}


@router.delete("/exams/{exam_id}/proctors/{user_id}", status_code=204)
def unassign_proctor(exam_id: UUID, user_id: UUID, user: Teacher, db: DB) -> None:
    get_exam(db, user, exam_id, lock=True)
    db.execute(
        text("delete from proctor_assignments where exam_id = :e and user_id = :u"),
        {"e": exam_id, "u": user_id},
    )
    audit(db, user.id, "PROCTOR_UNASSIGNED", "exam", exam_id, metadata={"user_id": str(user_id)})


# ---- Monitor ---------------------------------------------------------------------


def monitor(db: Connection, exam_id: UUID) -> dict[str, Any]:
    """Snapshot pengawasan: tanpa jawaban, kunci, nilai, maupun status penilaian."""
    rows = db.execute(
        text(
            ROSTER  # noqa: S608 — ROSTER konstan
            + """
        select u.id as student_id, u.username as nis, u.display_name, a.id as attempt_id,
               case when a.id is null then 'NOT_STARTED'
                    when a.state in ('SUBMITTED', 'GRADED') then 'SUBMITTED'
                    when a.state = 'PAUSED' then 'PAUSED'
                    when a.last_heartbeat_at < now() - make_interval(secs => :hb)
                      then 'DISCONNECTED'
                    else 'ACTIVE' end as status,
               coalesce(a.pause_consumed_sec, 0) as pause_consumed_sec,
               case when a.state in ('IN_PROGRESS', 'PAUSED') then greatest(0, ceil(extract(
                 epoch from a.effective_deadline_at
                   - case when a.state = 'PAUSED' then a.paused_at else now() end)))::int
               end as remaining_seconds,
               (select count(*) from student_answers s
                where s.attempt_id = a.id and s.answer is not null) as answered_count,
               (select count(*) from audit_events x where x.target_type = 'exam_attempt'
                and x.target_id = a.id and x.action = 'TAB_HIDDEN') as tab_hidden,
               coalesce(a.switch_permit_until > now(), false) as permit_pending
        from roster r join users u on u.id = r.student_id
        left join exam_attempts a on a.exam_id = :e and a.student_id = r.student_id
        order by u.display_name
        """
        ),
        {"e": exam_id, "hb": HEARTBEAT_TIMEOUT},
    ).mappings()
    participants = [
        {
            **r,
            "student_id": str(r["student_id"]),
            "attempt_id": str(r["attempt_id"]) if r["attempt_id"] else None,
        }
        for r in rows
    ]
    total = db.scalar(
        text("select count(*) from exam_question_snapshots where exam_id = :e"), {"e": exam_id}
    )
    announcements = db.execute(
        text("""
        select a.message, a.issued_at, u.display_name as sender
        from announcements a join users u on u.id = a.created_by
        where a.exam_id = :e order by a.issued_at desc limit 20
        """),
        {"e": exam_id},
    )
    counts = Counter(p["status"] for p in participants)
    return {
        "type": "snapshot",
        "exam_id": str(exam_id),
        "server_now": db.scalar(text("select now()")),
        "total_count": total,
        "counts": {
            k.lower(): counts.get(k, 0)
            for k in ("NOT_STARTED", "ACTIVE", "DISCONNECTED", "PAUSED", "SUBMITTED")
        },
        "participants": participants,
        "announcements": [
            {"message": a.message, "issued_at": a.issued_at, "sender": a.sender}
            for a in announcements
        ],
    }


@router.get("/proctor/exams")
def list_supervised_exams(user: Supervisor, db: DB) -> list[dict[str, Any]]:
    rows = db.execute(
        text(f"""
        select e.id, e.title, sub.name as subject_name, e.start_window_from,
               e.start_window_until, e.duration_sec, e.author_teacher_id = :uid as is_author,
               case when now() < e.start_window_from then 'PUBLISHED'
                    when now() <= e.start_window_until + make_interval(secs => e.duration_sec)
                      or exists (select 1 from exam_attempts x where x.exam_id = e.id
                                 and x.state in ('IN_PROGRESS', 'PAUSED'))
                      then 'ACTIVE'
                    else 'CLOSED' end as status
        from exams e join subjects sub on sub.id = e.subject_id
        where {SUPERVISES}
        order by e.start_window_from desc
        """),  # noqa: S608 — fragmen konstan
        {"uid": user.id},
    ).mappings()
    return [{**r, "id": str(r["id"])} for r in rows]


@router.get("/proctor/exams/{exam_id}/monitor")
def get_monitor(exam_id: UUID, user: Supervisor, db: DB) -> dict[str, Any]:
    if not supervises(db, user, exam_id):
        raise not_found()
    return monitor(db, exam_id)


@router.websocket("/ws/exams/{exam_id}")
async def monitor_ws(websocket: WebSocket, exam_id: UUID) -> None:
    """Snapshot penuh tiap 3 dtk. Autentikasi & hak diperiksa ulang tiap kirim: logout, sesi
    habis, atau penugasan dicabut langsung memutus aliran. Reconnect = snapshot baru."""
    # Middleware Origin hanya untuk HTTP; WebSocket wajib dicek sendiri.
    if websocket.headers.get("origin") not in settings.allowed_origins:
        await websocket.close(code=1008)
        return
    token = websocket.cookies.get(COOKIE)

    def tick() -> dict[str, Any] | None:
        with engine.begin() as db:
            user = session_user(db, token)
            if user is None or not user.has("TEACHER", "PROCTOR"):
                return None
            if not supervises(db, user, exam_id):
                return None
            return monitor(db, exam_id)

    snapshot = await anyio.to_thread.run_sync(tick)
    if snapshot is None:
        await websocket.close(code=1008)  # sebelum accept: tidak membocorkan keberadaan ujian
        return
    await websocket.accept()
    try:
        while snapshot is not None:
            await websocket.send_json(jsonable_encoder(snapshot))
            await asyncio.sleep(MONITOR_PUSH_SECONDS)
            snapshot = await anyio.to_thread.run_sync(tick)
        await websocket.close(code=1008)  # akses dicabut
    except Exception:  # klien menutup koneksi
        return


@router.get("/proctor/attempts/{attempt_id}/events")
def attempt_events(attempt_id: UUID, user: Supervisor, db: DB) -> list[dict[str, Any]]:
    supervised_attempt(db, user, attempt_id, "VIEW_EVENTS")
    rows = db.execute(
        text("""
        select 'PAUSE' as kind, resumed_at as at, end_reason as detail, credited_sec as seconds,
               null as reason
        from pause_incidents where attempt_id = :a
        union all
        select action, created_at, null, (metadata ->> 'seconds')::int, reason
        from audit_events where target_type = 'exam_attempt' and target_id = :a
          and action <> 'PROCTOR_ACTION_DENIED'
        order by at desc
        """),
        {"a": attempt_id},
    ).mappings()
    return [dict(r) for r in rows]


# ---- Tindakan --------------------------------------------------------------------


@router.post("/proctor/attempts/{attempt_id}/approve-device-switch")
@router.post("/proctor/attempts/{attempt_id}/reset-session")
def approve_device_switch(
    attempt_id: UUID, body: ReasonIn, user: Supervisor, db: DB, request: Request
) -> dict[str, Any]:
    """FR-REC-07: sesi lama siswa langsung dicabut, lalu izin sekali pakai (5 menit) agar siswa
    bisa login lagi di perangkat mana pun. Attempt, jawaban, dan jatah jeda tidak berubah."""
    attempt = supervised_attempt(db, user, attempt_id, "DEVICE_SWITCH")
    if attempt.state not in ("IN_PROGRESS", "PAUSED"):
        raise ApiError(409, "ATTEMPT_LOCKED", "Ujian peserta ini sudah selesai.")
    until = db.scalar(
        text("""
        update exam_attempts set switch_permit_until = now() + make_interval(secs => :s)
        where id = :id returning switch_permit_until
        """),
        {"id": attempt_id, "s": SWITCH_PERMIT_SECONDS},
    )
    db.execute(
        text(
            "delete from sessions where user_id = (select student_id from exam_attempts"
            " where id = :id)"
        ),
        {"id": attempt_id},
    )
    action = (
        "SESSION_RESET" if request.url.path.endswith("/reset-session") else "DEVICE_SWITCH_APPROVED"
    )
    audit(db, user.id, action, "exam_attempt", attempt_id, body.reason)
    return {"attempt_id": str(attempt_id), "permit_expires_at": until}


class ExtensionIn(ReasonIn):
    seconds: int = Field(ge=60, le=7200)


@router.post("/proctor/attempts/{attempt_id}/time-extensions", status_code=201)
def extend_time(attempt_id: UUID, body: ExtensionIn, user: Supervisor, db: DB) -> dict[str, Any]:
    # Batas waktu yang sudah lewat dikumpulkan dulu (transaksi sendiri agar tetap tersimpan meski
    # permintaan ini berakhir 409): tambahan waktu tidak boleh "menghidupkan" attempt yang selesai.
    # Hak pengawas dicek dulu (tanpa kunci baris, M9-02): pengguna lain tidak boleh memicu
    # auto-submit attempt ujian yang tidak ia awasi.
    exam_id = db.scalar(
        text("select exam_id from exam_attempts where id = :id"), {"id": attempt_id}
    )
    if exam_id is None or not supervises(db, user, exam_id):
        supervised_attempt(db, user, attempt_id, "EXTEND_TIME")  # 404 + audit penolakan
    with engine.begin() as own:
        expire_due(own, attempt_id=attempt_id)
    supervised_attempt(db, user, attempt_id, "EXTEND_TIME")
    deadline = db.scalar(
        text("""
        update exam_attempts
        set effective_deadline_at = effective_deadline_at + make_interval(secs => :s)
        where id = :id and state in ('IN_PROGRESS', 'PAUSED')
        returning effective_deadline_at
        """),
        {"id": attempt_id, "s": body.seconds},
    )
    if deadline is None:
        raise ApiError(409, "ATTEMPT_LOCKED", "Ujian peserta ini sudah selesai.")
    audit(
        db,
        user.id,
        "TIME_EXTENDED",
        "exam_attempt",
        attempt_id,
        body.reason,
        {"seconds": body.seconds},
    )
    return {"attempt_id": str(attempt_id), "deadline_at": deadline}


class AnnouncementIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


@router.post("/proctor/exams/{exam_id}/announcements", status_code=201)
def create_announcement(
    exam_id: UUID, body: AnnouncementIn, user: Supervisor, db: DB
) -> dict[str, Any]:
    if not supervises(db, user, exam_id):
        raise not_found()
    issued = db.scalar(
        text("""
        insert into announcements (exam_id, created_by, message) values (:e, :u, :m)
        returning issued_at
        """),
        {"e": exam_id, "u": user.id, "m": body.message.strip()},
    )
    audit(
        db,
        user.id,
        "ANNOUNCEMENT_SENT",
        "exam",
        exam_id,
        metadata={"message": body.message.strip()},
    )
    return {"message": body.message.strip(), "issued_at": issued}
