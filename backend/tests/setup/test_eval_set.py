"""Setup eval set: real documents in fi/en/bn with recorded extraction answers.

Each case checks the pipeline around the model: deterministic parsing, redaction,
catalogue gap filling, engine validation, and the recorded assumptions that replace
questions: a complete draft, drawn and scheduled, whose every choice the organiser can see.
"""

import datetime as dt
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.llm import FakeProvider, LLMGateway
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import OrganisationCreate
from app.modules.setup import service as setup
from app.modules.setup.schemas import SetupStart
from engine.rules.config import RuleConfig
from engine.rules.format import FormatSpec
from engine.rules.schedule_policy import SchedulePolicy
from engine.rules.seeding import SeedingPolicy
from engine.rules.validate import validate_setup

EVAL_SET = Path(__file__).parent / "eval_set"
CASES = sorted(p.name for p in EVAL_SET.iterdir() if (p / "case.json").exists())
MIME = {".csv": "text/csv", ".png": "image/png", ".txt": "text/plain", ".xlsx": ""}


def test_eval_set_has_enough_cases() -> None:
    assert len(CASES) >= 8


@pytest.mark.parametrize("name", CASES)
async def test_eval_case(
    name: str,
    db: AsyncSession,
    clock: FrozenClock,
    make_user: Callable[[], Awaitable[UUID]],
    make_settings: Callable[..., Settings],
) -> None:
    case: dict[str, Any] = json.loads((EVAL_SET / name / "case.json").read_text())
    expect = case["expect"]
    viewer = Viewer(user_id=await make_user())
    org = await competitions.create_organisation(
        db,
        clock,
        viewer,
        OrganisationCreate(
            kind="community", name="Eval Org", sports=["football"], accept_processing_terms=True
        ),
    )
    session = await setup.start(
        db,
        clock,
        viewer,
        SetupStart(
            organisation_id=org.id,
            name=f"Eval {name}",
            starts_on=dt.date(2026, 6, 12),
            ends_on=dt.date(2026, 6, 14),
        ),
    )
    for f in case["files"]:
        path = EVAL_SET / name / f["file"]
        await setup.add_file(
            db,
            clock,
            viewer,
            session.id,
            kind=f["kind"],
            filename=path.name,
            mime=MIME.get(path.suffix, ""),
            data=path.read_bytes(),
        )
    provider = FakeProvider(responses=case["llm"])
    redis = Redis.from_url(os.environ["REDIS_URL"])
    try:
        await redis.flushdb()  # recorded answers: no cache from earlier runs
        llm = LLMGateway(provider, make_settings(), redis, clock)
        result = await setup.run_extraction(db, clock, llm, viewer, session.id)
    finally:
        await redis.aclose()

    assert result.draft is not None
    draft = result.draft.draft
    questions = {q.field for q in result.draft.open_questions}
    assert len(draft.teams) == expect["teams"]
    if "max_questions" in expect:
        assert len(result.draft.open_questions) <= expect["max_questions"], (
            result.draft.open_questions
        )
    for field in expect.get("question_fields", []):
        assert field in questions, questions
    assumed = {a.field for a in result.draft.assumptions}
    if "assumption" in expect:
        assert expect["assumption"] in assumed
    for field in expect.get("assumption_fields", []):
        assert field in assumed, assumed
    if "groups" in expect:
        assert draft.format["group_sizes"] == expect["groups"]
    if "separation" in expect:
        reasons = " ".join(s["reason"] for s in draft.seeding["separations"])
        assert expect["separation"] in reasons
    if "team_source" in expect:
        assert {t.source for t in draft.teams} == {expect["team_source"]}
    for kind in expect.get("redacted", []):
        assert any(f.redaction_report.get(kind) for f in result.files)
    sent = " ".join(prompt for _, prompt in provider.calls)
    for value in expect.get("never_sent", []):
        assert value not in sent
    # Whatever the questions, the draft itself is something the engine accepts.
    issues = validate_setup(
        RuleConfig.model_validate(draft.rules),
        FormatSpec.model_validate(draft.format),
        SeedingPolicy.model_validate(draft.seeding),
        SchedulePolicy.model_validate(draft.schedule) if draft.schedule else None,
        [t.key for t in draft.teams],
    )
    assert not issues or questions, issues
    # No questions: the engine has already drawn and scheduled the tournament.
    assert result.status == ("needs_answers" if result.draft.open_questions else "ready")
