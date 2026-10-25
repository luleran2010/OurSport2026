"""Claim checker eval set: every planted error is caught, every good draft passes."""

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.analysis.schemas import Fact, FactContext, FactSheetOut
from app.modules.content.checker import check, numbers_in
from app.modules.content.schemas import NameBook, WrittenSentence, WrittenText

EVAL_SET = Path(__file__).parent / "eval_set"
SHEETS = json.loads((EVAL_SET / "sheets.json").read_text())
CASES = json.loads((EVAL_SET / "cases.json").read_text())
NAMES = NameBook.model_validate(SHEETS["names"])


def sheet_for(case: dict[str, Any]) -> FactSheetOut:
    data = SHEETS["sheets"][case["sheet"]]
    context = dict(data["context"], languages=case.get("languages", data["context"]["languages"]))
    return FactSheetOut(
        id=uuid.uuid4(),
        subject_type=data["subject_type"],
        subject_id=uuid.uuid4(),
        kind=data["kind"],
        facts=[Fact.model_validate(f) for f in data["facts"]],
        context=FactContext.model_validate(context),
        inputs_hash="eval",
        created_at=dt.datetime(2026, 6, 12, tzinfo=dt.UTC),
    )


def drafts_for(case: dict[str, Any]) -> dict[str, WrittenText]:
    headlines = case.get("headline", {})
    return {
        language: WrittenText(
            headline=WrittenSentence(text=headlines[language][0], facts=headlines[language][1])
            if language in headlines
            else None,
            sentences=[WrittenSentence(text=t, facts=f) for t, f in sentences],
        )
        for language, sentences in case["drafts"].items()
    }


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_eval_case(case: dict[str, Any]) -> None:
    result = check(
        drafts_for(case), sheet_for(case), NAMES, task=case["task"], length=case.get("length")
    )

    found = {i.kind for i in result.issues}
    if case["expect"]:
        assert not result.passed
        assert set(case["expect"]) <= found, result.issues
    else:
        assert result.passed, result.issues


def test_the_eval_set_plants_every_kind_of_error() -> None:
    planted = {kind for c in CASES for kind in c["expect"]}
    languages = {lang for c in CASES if c["expect"] for lang in c["drafts"]}

    assert planted == {
        "number", "name", "hidden_name", "status", "banned", "fact_ref", "length", "language"
    }  # fmt: skip
    assert languages == {"en", "fi", "bn"}
    assert sum(1 for c in CASES if c["expect"]) >= 30


def test_plain_string_headline_inherits_citations_from_report_sentences() -> None:
    draft = WrittenText.model_validate(
        {
            "headline": "Pinewood Wanderers win 2-1",
            "sentences": [
                {"text": "Pinewood Wanderers beat Meadow City 2-1.", "facts": ["score", "fixture"]},
                {"text": "They move top of the group.", "facts": ["standing"]},
            ],
        }
    )

    assert draft.headline == WrittenSentence(
        text="Pinewood Wanderers win 2-1",
        facts=["score", "fixture", "standing"],
    )


@given(st.integers(min_value=0, max_value=10_000))
def test_bengali_digits_read_as_the_same_number(n: int) -> None:
    bengali = str(n).translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))

    assert numbers_in(f"মোট {bengali} গোল", "bn") == [n]
    assert numbers_in(f"total {n} goals", "en") == [n]
