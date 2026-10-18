"""Hasil ujian untuk guru pemilik: daftar nilai, publikasi, nilai ulang, ekspor XLSX."""

from io import BytesIO
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from openpyxl import Workbook
from sqlalchemy import Connection, text

from app.attempts import regrade
from app.auth import CurrentUser, require_roles
from app.db import DB, audit
from app.exams import ROSTER, get_exam

router = APIRouter(prefix="/api/v1/teacher/exams", tags=["Results"])
Teacher = Annotated[CurrentUser, Depends(require_roles("TEACHER"))]


def _rows(db: Connection, exam_id: UUID) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in db.execute(
            text(
                ROSTER  # noqa: S608 — ROSTER konstan
                + """
            select u.id as student_id, u.username as nis, u.display_name,
                   (select string_agg(c.code, ', ' order by c.code)
                    from class_memberships m join classes c on c.id = m.class_id
                    join exam_assignments ea on ea.class_id = c.id and ea.exam_id = :e
                    where m.student_id = u.id) as class_codes,
                   a.id as attempt_id, coalesce(a.state, 'NOT_STARTED') as status,
                   a.score_total, a.score_max, a.submitted_at, a.submit_reason
            from roster r join users u on u.id = r.student_id
            left join exam_attempts a on a.exam_id = :e and a.student_id = r.student_id
            order by class_codes nulls last, u.display_name
            """
            ),
            {"e": exam_id},
        ).mappings()
    ]


def _num(value: Any) -> float | None:
    return float(value) if value is not None else None


@router.get("/{exam_id}/results")
def list_results(exam_id: UUID, user: Teacher, db: DB) -> dict[str, Any]:
    exam = get_exam(db, user, exam_id)
    published = db.scalar(
        text("select results_published_at from exams where id = :e"), {"e": exam_id}
    )
    return {
        "exam_id": str(exam_id),
        "title": exam["title"],
        "visibility": exam["result_visibility"],
        "results_published_at": published,
        "rows": [
            {
                "student_id": str(r["student_id"]),
                "nis": r["nis"],
                "display_name": r["display_name"],
                "class_codes": r["class_codes"],
                "attempt_id": str(r["attempt_id"]) if r["attempt_id"] else None,
                "status": r["status"],
                "score": _num(r["score_total"]),
                "max_score": _num(r["score_max"]),
                "submitted_at": r["submitted_at"],
                "submit_reason": r["submit_reason"],
            }
            for r in _rows(db, exam_id)
        ],
    }


@router.post("/{exam_id}/results/publish")
def publish_results(exam_id: UUID, user: Teacher, db: DB) -> dict[str, Any]:
    get_exam(db, user, exam_id, lock=True)
    at = db.scalar(
        text("update exams set results_published_at = now() where id = :e returning now()"),
        {"e": exam_id},
    )
    audit(db, user.id, "RESULTS_PUBLISHED", "exam", exam_id)
    return {"results_published_at": at}


@router.post("/{exam_id}/results/unpublish")
def unpublish_results(exam_id: UUID, user: Teacher, db: DB) -> dict[str, Any]:
    get_exam(db, user, exam_id, lock=True)
    db.execute(text("update exams set results_published_at = null where id = :e"), {"e": exam_id})
    audit(db, user.id, "RESULTS_UNPUBLISHED", "exam", exam_id)
    return {"results_published_at": None}


@router.post("/{exam_id}/regrade")
def regrade_pending(exam_id: UUID, user: Teacher, db: DB) -> dict[str, int]:
    get_exam(db, user, exam_id)
    pending = db.scalars(
        text("select id from exam_attempts where exam_id = :e and state = 'SUBMITTED'"),
        {"e": exam_id},
    ).all()
    graded = sum(regrade(db, attempt_id) for attempt_id in pending)
    audit(db, user.id, "REGRADED", "exam", exam_id, metadata={"graded": graded})
    return {"pending": len(pending), "graded": graded}


STATUS_LABEL = {
    "NOT_STARTED": "Belum mulai",
    "IN_PROGRESS": "Mengerjakan",
    "PAUSED": "Dijeda",
    "SUBMITTED": "Penilaian tertunda",
    "GRADED": "Dinilai",
}


@router.get("/{exam_id}/results/export")
def export_results(exam_id: UUID, user: Teacher, db: DB) -> Response:
    get_exam(db, user, exam_id)
    ordinals = db.execute(
        text("select id, ordinal from exam_question_snapshots where exam_id = :e order by ordinal"),
        {"e": exam_id},
    ).all()
    scores: dict[tuple[str, str], Any] = {
        (str(r.attempt_id), str(r.snapshot_question_id)): r.earned
        for r in db.execute(
            text("""
            select qs.attempt_id, qs.snapshot_question_id, qs.earned
            from question_scores qs join exam_attempts a on a.id = qs.attempt_id
            where a.exam_id = :e
            """),
            {"e": exam_id},
        )
    }
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Nilai"
    ws.append(
        ["NIS", "Nama", "Kelas", "Status", "Nilai", "Maks"] + [f"S{o.ordinal}" for o in ordinals]
    )
    for r in _rows(db, exam_id):
        attempt = str(r["attempt_id"]) if r["attempt_id"] else None
        ws.append(
            [
                r["nis"],
                r["display_name"],
                r["class_codes"] or "",
                STATUS_LABEL[r["status"]],
                r["score_total"],
                r["score_max"],
            ]
            + [scores.get((attempt, str(o.id))) if attempt else None for o in ordinals]
        )
    # Nama/NIS dari pengguna: teks diawali "=" diubah openpyxl jadi rumus. Paksa jadi teks.
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    buf = BytesIO()
    wb.save(buf)
    return Response(
        buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="nilai-{exam_id}.xlsx"'},
    )
