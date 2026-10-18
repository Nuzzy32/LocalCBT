"""Tindakan pengawasan. M6: izin pindah perangkat / reset sesi. M7: monitor, tambah waktu,
pengumuman, dan pengawas yang ditugaskan (sekarang hanya guru pemilik ujian)."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.auth import CurrentUser, require_roles
from app.db import DB
from app.errors import ApiError, not_found

router = APIRouter(prefix="/api/v1/proctor", tags=["Supervision"])
Supervisor = Annotated[CurrentUser, Depends(require_roles("TEACHER", "PROCTOR"))]

SWITCH_PERMIT_SECONDS = 300


class ReasonIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


def audit(
    db: Connection,
    actor: CurrentUser,
    action: str,
    target_type: str,
    target_id: UUID,
    reason: str | None = None,
) -> None:
    db.execute(
        text("""
        insert into audit_events (actor_id, action, target_type, target_id, reason)
        values (:a, :act, :tt, :tid, :r)
        """),
        {"a": actor.id, "act": action, "tt": target_type, "tid": target_id, "r": reason},
    )


def supervised_attempt(db: Connection, user: CurrentUser, attempt_id: UUID) -> Any:
    row = db.execute(
        text("""
        select a.id, a.state from exam_attempts a join exams e on e.id = a.exam_id
        where a.id = :id and e.author_teacher_id = :uid
        for update of a
        """),
        {"id": attempt_id, "uid": user.id},
    ).first()
    if row is None:
        raise not_found()
    return row


@router.post("/attempts/{attempt_id}/approve-device-switch")
@router.post("/attempts/{attempt_id}/reset-session")
def approve_device_switch(
    attempt_id: UUID, body: ReasonIn, user: Supervisor, db: DB
) -> dict[str, Any]:
    """Izin sekali pakai (5 menit) agar siswa bisa login di perangkat lain. Sesi lama dicabut
    saat login baru memakai izin ini; attempt, jawaban, dan jatah jeda tidak berubah."""
    attempt = supervised_attempt(db, user, attempt_id)
    if attempt.state not in ("IN_PROGRESS", "PAUSED"):
        raise ApiError(409, "ATTEMPT_LOCKED", "Ujian peserta ini sudah selesai.")
    until = db.scalar(
        text("""
        update exam_attempts set switch_permit_until = now() + make_interval(secs => :s)
        where id = :id returning switch_permit_until
        """),
        {"id": attempt_id, "s": SWITCH_PERMIT_SECONDS},
    )
    audit(db, user, "DEVICE_SWITCH_APPROVED", "exam_attempt", attempt_id, body.reason)
    return {"attempt_id": str(attempt_id), "permit_expires_at": until}
