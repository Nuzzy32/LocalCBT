"""Fixture rumus PROPOSED-1 (DEC-01 belum disahkan sekolah: ganti tabel ini bila rumus berubah)."""

from collections import Counter
from decimal import Decimal
from typing import Any

import pytest

from app.scoring import RULE_VERSION, InvalidAnswer, permute, score, validate_answer

PG = {
    "type": "SINGLE_CHOICE",
    "weight": "2",
    "option_ids": ["a", "b", "c"],
    "answer_key": {"correct_option_ids": ["b"]},
}
MCMA = {
    "type": "MULTIPLE_CHOICE",
    "weight": "3",
    "option_ids": ["A", "B", "C", "D"],
    "answer_key": {"correct_option_ids": ["A", "B"]},
}
MCMA_ALL_CORRECT = {
    "type": "MULTIPLE_CHOICE",
    "weight": "1",
    "option_ids": ["A", "B", "C"],
    "answer_key": {"correct_option_ids": ["A", "B", "C"]},
}
KAT = {
    "type": "CATEGORY_CHOICE",
    "weight": "2",
    "statement_ids": ["s1", "s2", "s3"],
    "answer_key": {"statements": {"s1": True, "s2": False, "s3": True}},
}


def pg(i: str) -> dict[str, Any]:
    return {"type": "SINGLE_CHOICE", "selected_option_id": i}


def mc(*ids: str) -> dict[str, Any]:
    return {"type": "MULTIPLE_CHOICE", "selected_option_ids": list(ids)}


def kat(**values: bool) -> dict[str, Any]:
    return {
        "type": "CATEGORY_CHOICE",
        "choices": [{"statement_id": k, "value": v} for k, v in values.items()],
    }


@pytest.mark.parametrize(
    ("q", "answer", "expected"),
    [
        (PG, pg("b"), "2.00"),
        (PG, pg("a"), "0.00"),
        (PG, None, "0.00"),
        (MCMA, mc("A", "B"), "3.00"),
        (MCMA, mc("A"), "1.50"),
        (MCMA, mc("A", "B", "C"), "1.50"),
        (MCMA, mc("A", "C"), "0.00"),
        (MCMA, mc("A", "B", "C", "D"), "0.00"),  # pilih semua tidak menguntungkan
        (MCMA, mc("C"), "0.00"),  # tidak pernah negatif
        (MCMA, None, "0.00"),
        (MCMA_ALL_CORRECT, mc("A"), "0.33"),
        (MCMA_ALL_CORRECT, mc("A", "B"), "0.67"),
        (MCMA_ALL_CORRECT, mc("A", "B", "C"), "1.00"),
        ({**MCMA, "weight": "0.25"}, mc("A"), "0.13"),  # half-up (half-even = 0.12)
        ({**MCMA, "weight": "0.05"}, mc("A"), "0.03"),
        (KAT, kat(s1=True, s2=False, s3=True), "2.00"),
        (KAT, kat(s1=True, s2=False), "1.33"),
        (KAT, kat(s1=True, s2=True), "0.67"),
        (KAT, kat(s1=False, s2=True, s3=False), "0.00"),
        (KAT, None, "0.00"),
    ],
)
def test_proposed_1_fixtures(
    q: dict[str, Any], answer: dict[str, Any] | None, expected: str
) -> None:
    result = score(RULE_VERSION, q, validate_answer(q, answer))
    assert result == Decimal(expected) and str(result) == expected


def test_unknown_rule_version_refused() -> None:
    with pytest.raises(ValueError, match="tidak dikenal"):
        score("V0", PG, pg("b"))


@pytest.mark.parametrize(
    ("q", "payload"),
    [
        (PG, pg("zz")),  # id soal lain
        (PG, {"type": "SINGLE_CHOICE", "selected_option_id": ["a", "b"]}),
        (PG, mc("a")),  # jenis tidak cocok
        (MCMA, mc("A", "A")),  # duplikat
        (MCMA, mc("A", "X")),
        (KAT, {"type": "CATEGORY_CHOICE", "choices": [{"statement_id": "s1", "value": "ya"}]}),
        (KAT, kat(s9=True)),
        (
            KAT,
            {
                "type": "CATEGORY_CHOICE",
                "choices": [
                    {"statement_id": "s1", "value": True},
                    {"statement_id": "s1", "value": False},
                ],
            },
        ),
    ],
)
def test_invalid_answers_rejected(q: dict[str, Any], payload: dict[str, Any]) -> None:
    with pytest.raises(InvalidAnswer):
        validate_answer(q, payload)


def test_empty_answers_count_as_skipped() -> None:
    assert validate_answer(MCMA, mc()) is None
    assert validate_answer(KAT, {"type": "CATEGORY_CHOICE", "choices": []}) is None
    assert validate_answer(PG, None) is None


QS = [
    {"id": "q1", "stimulus_id": None, "option_ids": ["a", "b", "c", "d"], "statement_ids": []},
    {"id": "q2", "stimulus_id": "S", "option_ids": ["e", "f"], "statement_ids": []},
    {"id": "q3", "stimulus_id": "S", "option_ids": [], "statement_ids": ["x", "y", "z"]},
    {"id": "q4", "stimulus_id": None, "option_ids": ["g", "h", "i"], "statement_ids": []},
    {"id": "q5", "stimulus_id": "S", "option_ids": ["j", "k"], "statement_ids": []},
    {"id": "q6", "stimulus_id": None, "option_ids": ["l", "m"], "statement_ids": []},
]


def test_permutation_is_deterministic_and_preserves_ids_and_groups() -> None:
    a, b = permute(QS, 42), permute(QS, 42)
    assert a == b
    assert any(permute(QS, s) != a for s in range(1, 20))

    order = [p["question_id"] for p in a]
    assert Counter(order) == Counter(q["id"] for q in QS)
    # Grup stimulus berdampingan dengan urutan internal tetap.
    i = order.index("q2")
    assert order[i : i + 3] == ["q2", "q3", "q5"]
    for p in a:
        src = next(q for q in QS if q["id"] == p["question_id"])
        assert sorted(p["option_ids"]) == sorted(src["option_ids"])
        assert sorted(p["statement_ids"]) == sorted(src["statement_ids"])
