"""Penilaian, validasi jawaban, dan pengacakan. Murni (tanpa DB) agar mudah diuji dan dipakai M5.

Bentuk soal yang diharapkan (dari snapshot):
  {"id", "type", "weight", "stimulus_id", "option_ids": [...], "statement_ids": [...],
   "answer_key": {"correct_option_ids": [...]} | {"statements": {statement_id: bool}}}
"""

import math
import random
from decimal import Decimal
from fractions import Fraction
from typing import Any

RULE_VERSION = "PROPOSED-1"
RULE_TEXT = (
    "Aturan penilaian PROPOSED-1 (usulan DATABASE_DESIGN, BELUM DISAHKAN SEKOLAH). "
    "Pilihan Ganda: bobot penuh bila jawaban tepat, selain itu 0. "
    "Pilihan Ganda Kompleks: bobot × (opsi benar dipilih ÷ jumlah opsi benar − opsi salah "
    "dipilih ÷ jumlah opsi salah), dibatasi 0 sampai 1; bila tidak ada opsi salah, hanya "
    "suku pertama. Benar/Salah per Pernyataan: bobot × (pernyataan dijawab benar ÷ jumlah "
    "pernyataan); pernyataan kosong bernilai 0. Jawaban kosong bernilai 0. Nilai tiap soal "
    "dibulatkan 2 desimal (setengah ke atas); total = jumlah nilai soal."
)


class InvalidAnswer(ValueError):
    pass


def group_order(qs: list[dict[str, Any]]) -> list[str]:
    """Id soal; soal ber-stimulus sama dibuat berdampingan di posisi kemunculan pertama."""
    groups: dict[str, list[str]] = {}
    for q in qs:
        groups.setdefault(q.get("stimulus_id") or f"solo:{q['id']}", []).append(q["id"])
    return [qid for ids in groups.values() for qid in ids]


def permute(qs: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """Urutan per peserta: grup stimulus diacak (urutan di dalam grup tetap), opsi & pernyataan
    diacak. Hanya mengurutkan ulang id, tidak pernah mengubahnya: kunci tetap merujuk id."""
    rng = random.Random(seed)  # noqa: S311 — pengacakan tampilan, bukan kriptografi
    by_id = {q["id"]: q for q in qs}
    groups: dict[str, list[str]] = {}
    for qid in group_order(qs):
        q = by_id[qid]
        groups.setdefault(q.get("stimulus_id") or f"solo:{qid}", []).append(qid)
    order = list(groups.values())
    rng.shuffle(order)
    out = []
    for qid in (qid for group in order for qid in group):
        option_ids = list(by_id[qid].get("option_ids", []))
        statement_ids = list(by_id[qid].get("statement_ids", []))
        rng.shuffle(option_ids)
        rng.shuffle(statement_ids)
        out.append({"question_id": qid, "option_ids": option_ids, "statement_ids": statement_ids})
    return out


def validate_answer(q: dict[str, Any], payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalisasi jawaban terhadap id snapshot. None = tidak dijawab."""
    if not payload:
        return None
    if payload.get("type") != q["type"]:
        raise InvalidAnswer("Jenis jawaban tidak sesuai soal.")
    if q["type"] == "SINGLE_CHOICE":
        selected = payload.get("selected_option_id")
        if not isinstance(selected, str) or selected not in q["option_ids"]:
            raise InvalidAnswer("Opsi tidak ada di soal ini.")
        return {"type": q["type"], "selected_option_id": selected}
    if q["type"] == "MULTIPLE_CHOICE":
        ids = payload.get("selected_option_ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise InvalidAnswer("Format jawaban tidak valid.")
        if len(set(ids)) != len(ids) or not set(ids) <= set(q["option_ids"]):
            raise InvalidAnswer("Opsi tidak ada di soal ini.")
        return {"type": q["type"], "selected_option_ids": ids} if ids else None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not all(
        isinstance(c, dict)
        and isinstance(c.get("statement_id"), str)
        and isinstance(c.get("value"), bool)
        for c in choices
    ):
        raise InvalidAnswer("Format jawaban tidak valid.")
    ids = [c["statement_id"] for c in choices]
    if len(set(ids)) != len(ids) or not set(ids) <= set(q["statement_ids"]):
        raise InvalidAnswer("Pernyataan tidak ada di soal ini.")
    if not choices:
        return None
    return {
        "type": q["type"],
        "choices": [{"statement_id": c["statement_id"], "value": c["value"]} for c in choices],
    }


def _fraction_correct(q: dict[str, Any], answer: dict[str, Any]) -> Fraction:
    key = q["answer_key"]
    if q["type"] == "SINGLE_CHOICE":
        return (
            Fraction(1)
            if answer["selected_option_id"] in key["correct_option_ids"]
            else Fraction(0)
        )
    if q["type"] == "MULTIPLE_CHOICE":
        correct = set(key["correct_option_ids"])
        wrong = set(q["option_ids"]) - correct
        selected = set(answer["selected_option_ids"])
        frac = Fraction(len(selected & correct), len(correct))
        if wrong:
            frac -= Fraction(len(selected & wrong), len(wrong))
        return min(max(frac, Fraction(0)), Fraction(1))
    statements: dict[str, bool] = key["statements"]
    right = sum(1 for c in answer["choices"] if statements.get(c["statement_id"]) == c["value"])
    return Fraction(right, len(statements))


def score(rule: str, q: dict[str, Any], answer: dict[str, Any] | None) -> Decimal:
    """Nilai satu soal, 2 desimal ROUND_HALF_UP, dihitung eksak dengan Fraction."""
    if rule != RULE_VERSION:
        raise ValueError(f"Aturan penilaian tidak dikenal: {rule}")
    if answer is None:
        return Decimal("0.00")
    points = Fraction(str(q["weight"])) * _fraction_correct(q, answer)
    return Decimal(math.floor(points * 100 + Fraction(1, 2))).scaleb(-2)
