import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.auth import verify_password
from app.db import engine
from tests.conftest import login, make_user
from tests.test_questions import KATEGORI, MCMA, PG, QB

TOKEN = "RAHASIA42"  # noqa: S105


def _now() -> datetime:
    return datetime.now(UTC)


def _insert(sql: str, **params: Any) -> str:
    with engine.begin() as c:
        return str(c.scalar(text(sql + " returning id"), params))


@pytest.fixture
def setup() -> dict[str, Any]:
    subject = _insert("insert into subjects (code, name) values ('MTK', 'Matematika')")
    other_subject = _insert("insert into subjects (code, name) values ('IPA', 'IPA')")
    cls = _insert(
        "insert into classes (code, label, academic_year) values ('IX-A', 'IX A', '2026/2027')"
    )
    cls_b = _insert(
        "insert into classes (code, label, academic_year) values ('IX-B', 'IX B', '2026/2027')"
    )
    teacher_id = make_user("guru.a", "TEACHER")
    _insert(
        "insert into teaching_assignments (teacher_id, class_id, subject_id) values (:t, :c, :s)",
        t=teacher_id,
        c=cls,
        s=subject,
    )
    client = login("guru.a")
    bank = client.post(QB, json={"title": "Bank", "subject_id": subject}).json()["id"]
    stim = client.post(f"{QB}/{bank}/stimuli", json={"body_text": "Bacaan"}).json()["id"]
    qids = [
        client.post(f"{QB}/{bank}/questions", json=PG).json()["id"],
        client.post(f"{QB}/{bank}/questions", json={**MCMA, "stimulus_id": stim}).json()["id"],
        client.post(f"{QB}/{bank}/questions", json=KATEGORI).json()["id"],
        client.post(
            f"{QB}/{bank}/questions", json={**PG, "stem": "S4", "stimulus_id": stim}
        ).json()["id"],
    ]
    return {
        "client": client,
        "subject": subject,
        "other_subject": other_subject,
        "class": cls,
        "class_b": cls_b,
        "bank": bank,
        "qids": qids,
        "teacher_id": teacher_id,
    }


def exam_body(s: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {
        "title": "PTS Matematika",
        "subject_id": s["subject"],
        "class_ids": [s["class"]],
        "question_ids": s["qids"],
        "start_window_from": (_now() + timedelta(hours=1)).isoformat(),
        "start_window_until": (_now() + timedelta(hours=2)).isoformat(),
        "duration_seconds": 3600,
        "token": TOKEN,
        **over,
    }


PUBLISH = {"confirm": True, "scoring_rule_version": "PROPOSED-1"}


def _create(s: dict[str, Any], **over: Any) -> str:
    r = s["client"].post("/api/v1/exams", json=exam_body(s, **over))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_published_snapshot_is_immutable_against_source_edits(setup: dict[str, Any]) -> None:
    s, c = setup, setup["client"]
    exam = _create(s)
    r = c.post(f"/api/v1/exams/{exam}/publish", json=PUBLISH)
    assert r.status_code == 200 and r.json()["status"] == "PUBLISHED", r.text
    assert r.json()["scoring_rule_version"] == "PROPOSED-1"

    def snapshot() -> list[Any]:
        with engine.connect() as conn:
            return [
                tuple(row)
                for row in conn.execute(
                    text(
                        "select stem, weight, options_payload, answer_key, ordinal "
                        "from exam_question_snapshots order by ordinal"
                    )
                )
            ]

    before = snapshot()
    # Stimulus bersama dibekukan berdampingan: MCMA (q2) dan S4 (q4) bersebelahan.
    stems = [row[0] for row in before]
    assert stems.index("S4") == stems.index(MCMA["stem"]) + 1

    flipped = {
        **PG,
        "stem": "diubah",
        "options": [{**o, "is_correct": not o["is_correct"]} for o in PG["options"]],
    }
    c.put(f"{QB}/{s['bank']}/questions/{s['qids'][0]}", json=flipped)
    c.delete(f"{QB}/{s['bank']}/questions/{s['qids'][2]}")
    assert snapshot() == before
    preview = c.get(f"/api/v1/teacher/exams/{exam}/preview").json()
    assert "diubah" not in str(preview) and len(preview["questions"]) == 4

    with pytest.raises(DBAPIError, match="immutable"), engine.begin() as conn:
        conn.execute(text("update exam_question_snapshots set stem = 'hack'"))

    assert c.put(f"/api/v1/exams/{exam}", json=exam_body(s)).status_code == 409
    assert c.post(f"/api/v1/exams/{exam}/publish", json=PUBLISH).status_code == 409


def test_answer_key_frozen_in_snapshot_never_in_preview(setup: dict[str, Any]) -> None:
    s, c = setup, setup["client"]
    exam = _create(s)
    c.post(f"/api/v1/exams/{exam}/publish", json=PUBLISH)
    with engine.connect() as conn:
        keys = [r[0] for r in conn.execute(text("select answer_key from exam_question_snapshots"))]
    assert {"correct_option_ids"} in [set(k) for k in keys] and {"statements"} in [
        set(k) for k in keys
    ]
    body = c.get(f"/api/v1/teacher/exams/{exam}/preview").text
    assert "correct" not in body and "answer_key" not in body


@pytest.mark.parametrize(
    ("over", "fragment"),
    [
        (
            {
                "start_window_until": (_now() - timedelta(minutes=5)).isoformat(),
                "start_window_from": (_now() - timedelta(hours=1)).isoformat(),
            },
            "sudah lewat",
        ),
    ],
)
def test_publish_rejects_past_window(
    setup: dict[str, Any], over: dict[str, Any], fragment: str
) -> None:
    exam = _create(setup, **over)
    r = setup["client"].post(f"/api/v1/exams/{exam}/publish", json=PUBLISH)
    assert r.status_code == 422 and fragment in r.json()["error"]["message"]


def test_publish_requires_rule_confirmation(setup: dict[str, Any]) -> None:
    exam = _create(setup)
    c = setup["client"]
    for bad in (
        {"confirm": False, "scoring_rule_version": "PROPOSED-1"},
        {"confirm": True, "scoring_rule_version": "V2"},
        {"confirm": True},
    ):
        assert c.post(f"/api/v1/exams/{exam}/publish", json=bad).status_code == 422


def test_publish_rejects_question_deleted_after_draft(setup: dict[str, Any]) -> None:
    s, c = setup, setup["client"]
    exam = _create(s)
    c.delete(f"{QB}/{s['bank']}/questions/{s['qids'][1]}")
    r = c.post(f"/api/v1/exams/{exam}/publish", json=PUBLISH)
    assert r.status_code == 422 and "soal" in r.json()["error"]["message"]
    preview = c.get(f"/api/v1/teacher/exams/{exam}/preview").json()
    assert len(preview["questions"]) == 3 and preview["validation_errors"]


@pytest.mark.parametrize(
    "over",
    [
        {"start_window_until": (_now() + timedelta(minutes=30)).isoformat()},  # until < from
        {"start_window_from": "2026-12-01T08:00:00"},  # tanpa zona waktu
        {"duration_seconds": 30},
        {"question_ids": []},
        {"class_ids": []},
        {"token": "abc"},
        {"shuffle_options": False},
        {"result_policy": {"visibility": "IMMEDIATE", "show_explanations": True}},
    ],
)
def test_invalid_exam_bodies(setup: dict[str, Any], over: dict[str, Any]) -> None:
    r = setup["client"].post("/api/v1/exams", json=exam_body(setup, **over))
    assert r.status_code == 422, r.text


def test_cannot_use_untaught_class_other_subject_or_view_only_bank(setup: dict[str, Any]) -> None:
    s, c = setup, setup["client"]
    assert c.post("/api/v1/exams", json=exam_body(s, class_ids=[s["class_b"]])).status_code == 422
    assert (
        c.post("/api/v1/exams", json=exam_body(s, subject_id=s["other_subject"])).status_code == 422
    )

    make_user("guru.b", "TEACHER")
    other = login("guru.b")
    their_bank = other.post(QB, json={"title": "B", "subject_id": s["subject"]}).json()["id"]
    their_q = other.post(f"{QB}/{their_bank}/questions", json=PG).json()["id"]
    body = exam_body(s, question_ids=[their_q])
    assert c.post("/api/v1/exams", json=body).status_code == 422
    other.post(
        f"{QB}/{their_bank}/shares", json={"teacher_id": s["teacher_id"], "permission": "VIEW"}
    )
    assert c.post("/api/v1/exams", json=body).status_code == 422
    other.post(
        f"{QB}/{their_bank}/shares", json={"teacher_id": s["teacher_id"], "permission": "COPY"}
    )
    assert c.post("/api/v1/exams", json=body).status_code == 201


def test_other_teacher_and_student_cannot_see_exam(setup: dict[str, Any]) -> None:
    exam = _create(setup)
    make_user("guru.b", "TEACHER")
    other = login("guru.b")
    assert other.get(f"/api/v1/exams/{exam}").status_code == 404
    assert other.post(f"/api/v1/exams/{exam}/publish", json=PUBLISH).status_code == 404
    assert other.get(f"/api/v1/teacher/exams/{exam}/preview").status_code == 404
    assert other.get("/api/v1/exams").json() == []
    make_user("0012345", "STUDENT")
    assert login("0012345").get("/api/v1/exams").status_code == 403


def test_token_is_hashed_never_returned_or_logged(
    setup: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    c = setup["client"]
    with caplog.at_level(logging.DEBUG):
        r = c.post("/api/v1/exams", json=exam_body(setup))
        exam = r.json()["id"]
        bodies = [
            r.text,
            c.get("/api/v1/exams").text,
            c.get(f"/api/v1/exams/{exam}").text,
            c.put(f"/api/v1/exams/{exam}", json=exam_body(setup, token=None)).text,
            c.post(f"/api/v1/exams/{exam}/publish", json=PUBLISH).text,
            c.get(f"/api/v1/teacher/exams/{exam}/preview").text,
        ]
        assert c.put(f"/api/v1/exams/{exam}/token", json={"token": "BARU1234"}).status_code == 204
    assert not any(TOKEN in b or "token_hash" in b for b in bodies)
    assert TOKEN not in caplog.text and "BARU1234" not in caplog.text
    with engine.connect() as conn:
        stored = conn.scalar(text("select token_hash from exams"))
    assert stored != "BARU1234" and verify_password(stored, "BARU1234")
    assert not verify_password(stored, TOKEN)


def test_unpublish_only_before_window_opens(setup: dict[str, Any]) -> None:
    c = setup["client"]
    exam = _create(setup)
    c.post(f"/api/v1/exams/{exam}/publish", json=PUBLISH)
    r = c.post(f"/api/v1/exams/{exam}/unpublish")
    assert r.status_code == 200 and r.json()["status"] == "DRAFT"
    with engine.connect() as conn:
        assert conn.scalar(text("select count(*) from exam_question_snapshots")) == 0

    started = _create(setup, start_window_from=(_now() - timedelta(minutes=1)).isoformat())
    assert c.post(f"/api/v1/exams/{started}/publish", json=PUBLISH).json()["status"] == "ACTIVE"
    assert c.post(f"/api/v1/exams/{started}/unpublish").status_code == 409


def test_publish_unpublish_and_token_rotation_are_audited(setup: dict[str, Any]) -> None:
    c = setup["client"]
    exam = _create(setup)
    c.post(f"/api/v1/exams/{exam}/publish", json=PUBLISH)
    c.put(f"/api/v1/exams/{exam}/token", json={"token": "BARU1234"})
    c.post(f"/api/v1/exams/{exam}/unpublish")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "select action, target_id::text, metadata::text from audit_events"
                " order by created_at"
            )
        ).all()
    assert [r.action for r in rows] == ["EXAM_PUBLISHED", "EXAM_TOKEN_ROTATED", "EXAM_UNPUBLISHED"]
    assert all(r.target_id == exam for r in rows)
    assert not any("BARU1234" in r.metadata or TOKEN in r.metadata for r in rows)


def test_result_policy_editable_after_publish(setup: dict[str, Any]) -> None:
    c = setup["client"]
    exam = _create(setup)
    c.post(f"/api/v1/exams/{exam}/publish", json=PUBLISH)
    policy = {
        "visibility": "AFTER_PUBLICATION",
        "review_enabled": True,
        "review_available_from": (_now() + timedelta(days=1)).isoformat(),
        "show_correct_answers": True,
    }
    r = c.put(f"/api/v1/teacher/exams/{exam}/result-policy", json=policy)
    assert r.status_code == 200
    got = c.get(f"/api/v1/exams/{exam}").json()["result_policy"]
    assert (
        got["visibility"] == "AFTER_PUBLICATION"
        and got["review_enabled"]
        and got["show_correct_answers"]
    )
