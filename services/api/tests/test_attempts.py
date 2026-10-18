import logging
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from tests.conftest import login, make_user, new_client
from tests.test_exams import PUBLISH, TOKEN, _now, exam_body, setup  # noqa: F401
from tests.test_questions import KATEGORI, MCMA, PG, png

KEY_WORDS = ("is_correct", "correct_value", "answer_key", "correct_option_ids")


def _sql(sql: str, **params: Any) -> Any:
    with engine.begin() as c:
        return c.execute(text(sql), params)


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture
def exam(setup: dict[str, Any]) -> dict[str, Any]:
    """Ujian terbit yang sedang dibuka + satu siswa di kelas yang ditugaskan."""
    body = exam_body(setup, start_window_from=(_now() - timedelta(minutes=1)).isoformat())
    exam_id = setup["client"].post("/api/v1/exams", json=body).json()["id"]
    r = setup["client"].post(f"/api/v1/exams/{exam_id}/publish", json=PUBLISH)
    assert r.status_code == 200, r.text
    student_id = make_user("0012345", "STUDENT", name="Ahmad")
    _sql(
        "insert into class_memberships (class_id, student_id) values (:c, :s)",
        c=setup["class"],
        s=student_id,
    )
    return {**setup, "exam": exam_id, "student_id": student_id, "student": login("0012345")}


def start(client: TestClient, exam_id: str, token: str = TOKEN) -> Any:
    r = client.post(f"/api/v1/student/exams/{exam_id}/token/verify", json={"token": token})
    assert r.status_code == 200, r.text
    return client.post(
        f"/api/v1/student/exams/{exam_id}/attempts",
        json={"start_grant": r.json()["start_grant"], "confirm_start": True},
        headers=idem(),
    )


def by_stem(attempt: dict[str, Any], stem: str) -> dict[str, Any]:
    return next(q for q in attempt["questions"] if q["stem"] == stem)


def save(
    client: TestClient,
    attempt_id: str,
    qid: str,
    answer: Any,
    rev: int,
    marked: bool = False,
    key: str | None = None,
) -> Any:
    return client.put(
        f"/api/v1/student/attempts/{attempt_id}/answers/{qid}",
        json={"answer": answer, "client_revision": rev, "marked_for_review": marked},
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


# ---- Mulai ---------------------------------------------------------------------


def test_start_flow_and_resume_without_keys(exam: dict[str, Any]) -> None:
    s = exam["student"]
    listed = s.get("/api/v1/student/exams").json()
    assert [e["status"] for e in listed] == ["AVAILABLE"]

    wrong = s.post(f"/api/v1/student/exams/{exam['exam']}/token/verify", json={"token": "SALAH1"})
    assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "TOKEN_INVALID"

    first = start(s, exam["exam"])
    assert first.status_code == 201, first.text
    attempt = first.json()
    assert attempt["state"] == "IN_PROGRESS" and len(attempt["questions"]) == 4
    assert 3500 <= attempt["timer"]["remaining_seconds"] <= 3600
    assert not any(k in first.text for k in KEY_WORDS)

    again = start(s, exam["exam"])
    assert again.status_code == 200 and again.json()["id"] == attempt["id"]
    assert s.get("/api/v1/student/exams").json()[0]["status"] == "IN_PROGRESS"


def test_concurrent_start_creates_exactly_one_attempt(exam: dict[str, Any]) -> None:
    s = exam["student"]
    grant = s.post(
        f"/api/v1/student/exams/{exam['exam']}/token/verify", json={"token": TOKEN}
    ).json()["start_grant"]
    other = new_client()
    other.cookies = s.cookies
    other.headers.update(s.headers)
    barrier, results = threading.Barrier(2), []

    def go(client: TestClient) -> None:
        barrier.wait()
        results.append(
            client.post(
                f"/api/v1/student/exams/{exam['exam']}/attempts",
                json={"start_grant": grant, "confirm_start": True},
                headers=idem(),
            )
        )

    threads = [threading.Thread(target=go, args=(c,)) for c in (s, other)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.status_code for r in results) == [200, 201]
    assert len({r.json()["id"] for r in results}) == 1
    assert _sql("select count(*) from exam_attempts").scalar() == 1


def test_not_assigned_or_outside_window_cannot_start(exam: dict[str, Any]) -> None:
    make_user("0099999", "STUDENT")
    outsider = login("0099999")
    assert outsider.get("/api/v1/student/exams").json() == []
    r = outsider.post(f"/api/v1/student/exams/{exam['exam']}/token/verify", json={"token": TOKEN})
    assert r.status_code == 404

    _sql(
        "update exams set start_window_from = now() + interval '1 hour', "
        "start_window_until = now() + interval '2 hours'"
    )
    s = exam["student"]
    assert s.get("/api/v1/student/exams").json()[0]["status"] == "SCHEDULED"
    r = s.post(f"/api/v1/student/exams/{exam['exam']}/token/verify", json={"token": TOKEN})
    assert r.status_code == 403 and r.json()["error"]["code"] == "EXAM_NOT_OPEN"
    assert _sql("select count(*) from exam_attempts").scalar() == 0


def test_token_rate_limited_and_never_logged(
    exam: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    s = exam["student"]
    url = f"/api/v1/student/exams/{exam['exam']}/token/verify"
    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            assert s.post(url, json={"token": "SALAH1"}).status_code == 403
        r = s.post(url, json={"token": TOKEN})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert TOKEN not in caplog.text and "SALAH1" not in caplog.text


def test_grant_is_bound_to_student_and_exam(exam: dict[str, Any]) -> None:
    grant = (
        exam["student"]
        .post(f"/api/v1/student/exams/{exam['exam']}/token/verify", json={"token": TOKEN})
        .json()["start_grant"]
    )
    other_id = make_user("0012346", "STUDENT")
    _sql(
        "insert into class_memberships (class_id, student_id) values (:c, :s)",
        c=exam["class"],
        s=other_id,
    )
    other = login("0012346")
    r = other.post(
        f"/api/v1/student/exams/{exam['exam']}/attempts",
        json={"start_grant": grant, "confirm_start": True},
        headers=idem(),
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "START_GRANT_INVALID"


# ---- Simpan jawaban ------------------------------------------------------------


def test_save_is_durable_idempotent_and_revision_checked(exam: dict[str, Any]) -> None:
    s = exam["student"]
    att = start(s, exam["exam"]).json()
    q = by_stem(att, PG["stem"])
    answer = {"type": "SINGLE_CHOICE", "selected_option_id": q["options"][0]["id"]}
    key = str(uuid.uuid4())

    r = save(s, att["id"], q["id"], answer, rev=1, key=key)
    assert r.status_code == 200 and r.json()["status"] == "persisted"
    # ACK = sudah commit: koneksi lain langsung melihatnya.
    stored = _sql("select answer from student_answers").scalar()
    assert stored == answer

    replay = save(s, att["id"], q["id"], answer, rev=1, key=key)
    assert replay.json() == r.json()
    other_body = save(s, att["id"], q["id"], None, rev=1, key=key)
    assert (
        other_body.status_code == 409
        and other_body.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    )

    assert save(s, att["id"], q["id"], answer, rev=3, marked=True).json()["server_revision"] == 2
    stale = save(s, att["id"], q["id"], None, rev=2)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "REVISION_CONFLICT"

    cleared = save(s, att["id"], q["id"], None, rev=4, marked=True)
    assert cleared.status_code == 200
    got = next(a for a in s.get(f"/api/v1/student/attempts/{att['id']}").json()["answers"])
    assert (
        got["answer"] is None and got["marked_for_review"] is True and got["client_revision"] == 4
    )


def test_invalid_answers_rejected(exam: dict[str, Any]) -> None:
    s = exam["student"]
    att = start(s, exam["exam"]).json()
    pg, mcma = by_stem(att, PG["stem"]), by_stem(att, MCMA["stem"])
    foreign = {"type": "SINGLE_CHOICE", "selected_option_id": mcma["options"][0]["id"]}
    assert save(s, att["id"], pg["id"], foreign, rev=1).status_code == 422
    wrong_type = {"type": "MULTIPLE_CHOICE", "selected_option_ids": []}
    assert save(s, att["id"], pg["id"], wrong_type, rev=1).status_code == 422
    assert save(s, att["id"], str(uuid.uuid4()), None, rev=1).status_code == 404


def test_deadline_locks_answers_and_auto_submits(exam: dict[str, Any]) -> None:
    s = exam["student"]
    att = start(s, exam["exam"]).json()
    q = by_stem(att, PG["stem"])
    answer = {"type": "SINGLE_CHOICE", "selected_option_id": q["options"][1]["id"]}
    key = str(uuid.uuid4())
    assert save(s, att["id"], q["id"], answer, rev=1, key=key).status_code == 200

    _sql("update exam_attempts set effective_deadline_at = now() - interval '1 second'")
    late = save(s, att["id"], q["id"], None, rev=2)
    assert late.status_code == 409 and late.json()["error"]["code"] == "ATTEMPT_LOCKED"
    # Simpanan yang sudah commit sebelum batas tetap bisa dikonfirmasi ulang.
    assert save(s, att["id"], q["id"], answer, rev=1, key=key).status_code == 200

    got = s.get(f"/api/v1/student/attempts/{att['id']}").json()
    assert got["state"] == "GRADED" and got["questions"] == [] and got["receipt_id"]
    assert got["timer"]["remaining_seconds"] == 0
    assert _sql("select submit_reason from exam_attempts").scalar() == "DEADLINE"
    assert _sql("select count(*) from question_scores").scalar() == 4


# ---- Submit & penilaian --------------------------------------------------------


def test_submit_once_with_proposed_1_scores(exam: dict[str, Any]) -> None:
    s = exam["student"]
    att = start(s, exam["exam"]).json()
    pg, mcma, kat = (by_stem(att, x["stem"]) for x in (PG, MCMA, KATEGORI))
    pg_key = next(o["id"] for o in pg["options"] if o["text"] == "4")
    two = next(o["id"] for o in mcma["options"] if o["text"] == "2")
    first_statement = next(st["id"] for st in kat["statements"] if st["text"] == "4 genap")
    save(s, att["id"], pg["id"], {"type": "SINGLE_CHOICE", "selected_option_id": pg_key}, 1)
    save(s, att["id"], mcma["id"], {"type": "MULTIPLE_CHOICE", "selected_option_ids": [two]}, 1)
    save(
        s,
        att["id"],
        kat["id"],
        {"type": "CATEGORY_CHOICE", "choices": [{"statement_id": first_statement, "value": True}]},
        1,
    )

    url = f"/api/v1/student/attempts/{att['id']}/submit"
    barrier, results = threading.Barrier(2), []
    other = new_client()
    other.cookies = s.cookies
    other.headers.update(s.headers)

    def go(client: TestClient) -> None:
        barrier.wait()
        results.append(client.post(url, json={"confirm": True}, headers=idem()))

    threads = [threading.Thread(target=go, args=(c,)) for c in (s, other)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    replays = [s.post(url, json={"confirm": True}, headers=idem()) for _ in range(5)]
    assert sorted(r.status_code for r in results) == [200, 201]
    assert {r.status_code for r in replays} == {200}
    assert len({r.json()["receipt_id"] for r in results + replays}) == 1
    assert _sql("select count(*) from question_scores").scalar() == 4

    total, maximum = _sql("select score_total, score_max from exam_attempts").one()
    # PG 1.00 + MCMA 2.5×½ = 1.25 + Kategori 3×½ = 1.50 + soal kosong 0 = 3.75 dari 7.50
    assert (total, maximum) == (Decimal("3.75"), Decimal("7.50"))


# ---- Akses & visibilitas -------------------------------------------------------


def test_other_student_and_teacher_cannot_touch_attempt(exam: dict[str, Any]) -> None:
    att = start(exam["student"], exam["exam"]).json()
    qid = att["questions"][0]["id"]
    make_user("0099999", "STUDENT")
    other = login("0099999")
    base = f"/api/v1/student/attempts/{att['id']}"
    assert other.get(base).status_code == 404
    assert save(other, att["id"], qid, None, 1).status_code == 404
    assert other.post(f"{base}/submit", json={"confirm": True}, headers=idem()).status_code == 404
    assert other.post(f"{base}/heartbeat", json={}).status_code == 404
    assert other.get(f"{base}/result").status_code == 404
    assert other.get(f"{base}/review").status_code == 404
    assert exam["client"].get(base).status_code == 403


def test_student_sees_only_images_of_own_exam(exam: dict[str, Any]) -> None:
    c, s = exam["client"], exam["student"]
    mine = c.post("/api/v1/media", files={"file": ("a.png", png(4, 4))}).json()["id"]
    other = c.post("/api/v1/media", files={"file": ("b.png", png(5, 5))}).json()["id"]
    qid = c.post(
        f"/api/v1/question-banks/{exam['bank']}/questions",
        json={**PG, "stem": "Bergambar", "media_asset_id": mine},
    ).json()["id"]
    body = exam_body(
        exam,
        title="Ujian bergambar",
        question_ids=[qid],
        start_window_from=(_now() - timedelta(minutes=1)).isoformat(),
    )
    second = c.post("/api/v1/exams", json=body).json()["id"]
    c.post(f"/api/v1/exams/{second}/publish", json=PUBLISH)

    assert s.get(f"/api/v1/media/{mine}").status_code == 404  # belum mulai ujiannya
    att = start(s, second).json()
    assert att["questions"][0]["image_url"] == f"/api/v1/media/{mine}"
    assert s.get(f"/api/v1/media/{mine}").status_code == 200
    assert s.get(f"/api/v1/media/{other}").status_code == 404


def _finish(exam: dict[str, Any]) -> str:
    att = start(exam["student"], exam["exam"]).json()
    exam["student"].post(
        f"/api/v1/student/attempts/{att['id']}/submit", json={"confirm": True}, headers=idem()
    )
    return str(att["id"])


def test_result_visibility_matrix(exam: dict[str, Any]) -> None:
    s = exam["student"]
    attempt_id = _finish(exam)
    url = f"/api/v1/student/attempts/{attempt_id}/result"
    r = s.get(url)
    assert r.status_code == 403 and r.json()["error"]["code"] == "RESULT_HIDDEN"
    assert "score" not in r.text

    _sql("update exams set result_visibility = 'AFTER_PUBLICATION'")
    assert s.get(url).status_code == 403
    _sql("update exams set results_published_at = now() + interval '1 day'")
    assert s.get(url).status_code == 403
    _sql("update exams set results_published_at = now() - interval '1 second'")
    assert s.get(url).json()["max_score"] == 7.5  # Decimal dikirim sebagai angka JSON

    _sql("update exams set result_visibility = 'IMMEDIATE', results_published_at = null")
    assert s.get(url).status_code == 200


def test_review_requires_policy_and_closed_exam_and_hides_keys(exam: dict[str, Any]) -> None:
    s = exam["student"]
    attempt_id = _finish(exam)
    url = f"/api/v1/student/attempts/{attempt_id}/review"
    assert s.get(url).status_code == 403  # pembahasan tidak diaktifkan

    _sql('update exams set review_policy = \'{"enabled": true, "show_correct_answers": false}\'')
    r = s.get(url)
    assert r.status_code == 403 and r.json()["error"]["code"] == "REVIEW_CLOSED"  # ujian belum usai

    _sql(
        "update exams set start_window_from = now() - interval '3 hours', "
        "start_window_until = now() - interval '2 hours', duration_sec = 60"
    )
    r = s.get(url)
    assert r.status_code == 200 and len(r.json()["questions"]) == 4
    assert not any(k in r.text for k in KEY_WORDS) and "earned" not in r.text

    _sql(
        'update exams set review_policy = \'{"enabled": true, "show_correct_answers": true}\', '
        "result_visibility = 'IMMEDIATE'"
    )
    r = s.get(url)
    assert "correct_option_ids" in r.text and "earned" in r.text


def test_unpublish_blocked_once_an_attempt_exists(exam: dict[str, Any]) -> None:
    start(exam["student"], exam["exam"])
    _sql(
        "update exams set start_window_from = now() + interval '1 hour', "
        "start_window_until = now() + interval '2 hours'"
    )
    r = exam["client"].post(f"/api/v1/exams/{exam['exam']}/unpublish")
    assert r.status_code == 409


def test_heartbeat_reports_server_timer(exam: dict[str, Any]) -> None:
    s = exam["student"]
    att = start(s, exam["exam"]).json()
    timer = s.post(
        f"/api/v1/student/attempts/{att['id']}/heartbeat", json={"tab_visible": True}
    ).json()
    assert timer["state"] == "IN_PROGRESS" and timer["pause_consumed_seconds"] == 0
    assert 0 < timer["remaining_seconds"] <= 3600
