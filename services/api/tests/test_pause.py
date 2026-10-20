"""M6: jeda otomatis (≤300 dtk/insiden, ≤600 dtk total), outage server, pindah perangkat.

Waktu dimajukan dengan memundurkan kolom server (last_heartbeat_at/paused_at/last_sweep_at)
lalu memanggil sweep_once() secara langsung.
"""

import threading
from datetime import timedelta
from typing import Any

import pytest

from app.config import settings
from app.sweeper import sweep_once
from tests.conftest import PASSWORD, login, make_user, new_client
from tests.test_attempts import _sql, exam, start  # noqa: F401
from tests.test_exams import setup  # noqa: F401


def _attempt(exam: dict[str, Any]) -> str:
    return str(start(exam["student"], exam["exam"]).json()["id"])


def _row() -> Any:
    return _sql(
        "select state, paused_at, pause_consumed_sec, effective_deadline_at from exam_attempts"
    ).one()


def _go_silent(seconds: int) -> None:
    """Majukan waktu: heartbeat terakhir dan riwayat insiden mundur bersama `seconds`."""
    _sql(
        "update exam_attempts set last_heartbeat_at = now() - make_interval(secs => :s)", s=seconds
    )
    _sql(
        "update pause_incidents set detected_at = detected_at - make_interval(secs => :s), "
        "resumed_at = resumed_at - make_interval(secs => :s)",
        s=seconds,
    )


def _beat(exam: dict[str, Any], attempt_id: str) -> Any:
    return exam["student"].post(f"/api/v1/student/attempts/{attempt_id}/heartbeat", json={}).json()


def test_fresh_heartbeat_never_pauses(exam: dict[str, Any]) -> None:
    _attempt(exam)
    _go_silent(10)
    sweep_once()
    assert _row().state == "IN_PROGRESS"


def test_t005_single_long_disconnect_credits_exactly_300(exam: dict[str, Any]) -> None:
    _attempt(exam)
    deadline = _row().effective_deadline_at
    _go_silent(400)
    sweep_once()  # terdeteksi putus → PAUSED sejak heartbeat terakhir + 15 dtk
    row = _row()
    assert row.state == "PAUSED"
    sweep_once()  # sudah 385 dtk dijeda ≥ batas 300 → waktu berjalan lagi meski masih offline
    row = _row()
    assert row.state == "IN_PROGRESS" and row.pause_consumed_sec == 300
    assert row.effective_deadline_at - deadline == timedelta(seconds=300)
    for _ in range(3):  # masih offline: putus yang sama tidak membuka insiden baru
        sweep_once()
    assert _row().state == "IN_PROGRESS"
    assert _sql("select count(*), min(end_reason) from pause_incidents").one() == (1, "CAP")


def test_t006_repeated_disconnects_never_exceed_600(exam: dict[str, Any]) -> None:
    attempt_id = _attempt(exam)
    for _ in range(3):
        _go_silent(265)  # jeda mulai 250 dtk lalu
        sweep_once()
        assert _row().state == "PAUSED"
        assert _beat(exam, attempt_id)["state"] == "IN_PROGRESS"  # reconnect menutup insiden
    credits = [r[0] for r in _sql("select credited_sec from pause_incidents order by resumed_at")]
    assert credits[0] in (250, 251) and credits[1] in (250, 251) and sum(credits) == 600
    assert _row().pause_consumed_sec == 600

    _go_silent(400)  # jatah habis: putus berikutnya tidak dijeda lagi
    sweep_once()
    assert _row().state == "IN_PROGRESS"
    timer = _beat(exam, attempt_id)
    assert timer["pause_consumed_seconds"] == 600 and timer["pause_allowance_seconds"] == 0


def test_any_request_while_paused_resumes_with_elapsed_credit(exam: dict[str, Any]) -> None:
    attempt_id = _attempt(exam)
    _go_silent(75)
    sweep_once()
    got = exam["student"].get(f"/api/v1/student/attempts/{attempt_id}").json()
    assert got["state"] == "IN_PROGRESS" and len(got["questions"]) == 4
    credited = _sql("select credited_sec, end_reason from pause_incidents").one()
    assert credited[0] in (60, 61) and credited[1] == "RECONNECT"


def test_no_pause_when_deadline_passes_before_detection(exam: dict[str, Any]) -> None:
    _attempt(exam)
    # Heartbeat terakhir 30 dtk lalu → titik deteksi 15 dtk lalu; batas waktu 20 dtk lalu.
    _sql(
        "update exam_attempts set effective_deadline_at = now() - interval '20 seconds', "
        "last_heartbeat_at = now() - interval '30 seconds'"
    )
    sweep_once()
    sweep_once()  # idempoten
    assert _row().state == "GRADED"
    assert _sql("select count(*) from question_scores").scalar() == 4
    assert _sql("select count(*) from pause_incidents").scalar() == 0


def test_sweep_and_reconnect_race_never_overcredit(exam: dict[str, Any]) -> None:
    attempt_id = _attempt(exam)
    _sql(
        "update exam_attempts set state = 'PAUSED', paused_at = now() - interval '400 seconds', "
        "pause_consumed_sec = 500"
    )
    barrier = threading.Barrier(2)

    def run_sweep() -> None:
        barrier.wait()
        sweep_once()

    def run_beat() -> None:
        barrier.wait()
        _beat(exam, attempt_id)

    threads = [threading.Thread(target=f) for f in (run_sweep, run_beat)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _row().state == "IN_PROGRESS" and _row().pause_consumed_sec == 600
    assert _sql("select count(*), sum(credited_sec) from pause_incidents").one() == (1, 100)


# ---- Outage server -------------------------------------------------------------


def test_outage_freezes_time_instead_of_mass_auto_submit(exam: dict[str, Any]) -> None:
    _attempt(exam)
    # Server mati 120 dtk; batas waktu siswa jatuh di tengah outage.
    _sql("update server_clock set last_sweep_at = now() - interval '120 seconds'")
    _sql(
        "update exam_attempts set effective_deadline_at = now() - interval '60 seconds', "
        "last_heartbeat_at = now() - interval '120 seconds'"
    )
    sweep_once()
    row = _row()
    assert row.state == "IN_PROGRESS"  # tidak dikumpulkan & tidak dianggap putus
    remaining = _sql(
        "select extract(epoch from effective_deadline_at - now()) from exam_attempts"
    ).scalar()
    assert 55 <= remaining <= 61
    outage = _sql("select credited_sec, affected_attempts from server_outages").one()
    assert outage[0] in (119, 120, 121) and outage[1] == 1


def test_outage_without_freeze_only_records(
    exam: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "outage_freeze", False)
    _attempt(exam)
    _sql("update server_clock set last_sweep_at = now() - interval '120 seconds'")
    _sql("update exam_attempts set effective_deadline_at = now() - interval '60 seconds'")
    sweep_once()
    assert _row().state == "GRADED"
    assert _sql("select credited_sec from server_outages").scalar() == 0


def test_short_gap_is_not_an_outage(exam: dict[str, Any]) -> None:
    _attempt(exam)
    _sql("update server_clock set last_sweep_at = now() - interval '8 seconds'")
    sweep_once()
    assert _sql("select count(*) from server_outages").scalar() == 0


# ---- Pindah perangkat (T-007) --------------------------------------------------


def test_t007_device_switch_requires_supervisor_permit(exam: dict[str, Any]) -> None:
    attempt_id = _attempt(exam)
    old = exam["student"]
    creds = {"username": "0012345", "password": PASSWORD}
    assert new_client().post("/api/v1/auth/login", json=creds).status_code == 409

    url = f"/api/v1/proctor/attempts/{attempt_id}/approve-device-switch"
    assert exam["client"].post(url, json={"reason": "pendek"}).status_code == 422
    make_user("guru.b", "TEACHER")
    assert login("guru.b").post(url, json={"reason": "Laptop siswa mati total"}).status_code == 404
    r = exam["client"].post(url, json={"reason": "Laptop siswa mati total"})
    assert r.status_code == 200 and r.json()["permit_expires_at"]
    assert old.get("/api/v1/auth/me").status_code == 401  # dicabut saat disetujui (FR-REC-07)

    new = login("0012345")  # izin dipakai
    assert new.get(f"/api/v1/student/attempts/{attempt_id}").json()["id"] == attempt_id
    assert new_client().post("/api/v1/auth/login", json=creds).status_code == 409  # sekali pakai
    assert _sql("select switch_permit_until from exam_attempts").scalar() is None
    audit = _sql(
        "select action, reason from audit_events where target_type = 'exam_attempt'"
        " order by created_at"
    ).all()
    assert [tuple(r) for r in audit] == [
        ("PROCTOR_ACTION_DENIED", None),  # guru lain yang bukan pengawas (T-021)
        ("DEVICE_SWITCH_APPROVED", "Laptop siswa mati total"),
    ]


def test_device_switch_rejected_for_finished_attempt(exam: dict[str, Any]) -> None:
    attempt_id = _attempt(exam)
    _sql("update exam_attempts set effective_deadline_at = now() - interval '1 second'")
    sweep_once()
    r = exam["client"].post(
        f"/api/v1/proctor/attempts/{attempt_id}/reset-session",
        json={"reason": "Siswa minta pindah perangkat"},
    )
    assert r.status_code == 409


def test_reset_session_revokes_old_device_and_is_audited_as_reset(exam: dict[str, Any]) -> None:
    attempt_id = _attempt(exam)
    old = exam["student"]
    r = exam["client"].post(
        f"/api/v1/proctor/attempts/{attempt_id}/reset-session",
        json={"reason": "Browser siswa macet total"},
    )
    assert r.status_code == 200
    assert old.get("/api/v1/auth/me").status_code == 401
    assert _sql(
        "select action, reason from audit_events where target_type = 'exam_attempt'"
    ).one() == (
        "SESSION_RESET",
        "Browser siswa macet total",
    )


def test_idle_session_cannot_switch_device_during_exam(exam: dict[str, Any]) -> None:
    # BR-21: jendela "sesi basi" tidak berlaku selama attempt berjalan.
    _attempt(exam)
    _sql(
        "update sessions set last_seen_at = now() - make_interval(secs => :s)",
        s=settings.student_session_stale_seconds + 60,
    )
    creds = {"username": "0012345", "password": PASSWORD}
    r = new_client().post("/api/v1/auth/login", json=creds)
    assert r.status_code == 409 and r.json()["error"]["code"] == "SESSION_ACTIVE"
