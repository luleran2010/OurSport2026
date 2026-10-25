"""End to end: FinBangla-style files → draft → draw and schedule → publish."""

import datetime as dt
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import OpenQuestionsRemaining, SetupNotReady, StaleVersion
from app.core.llm import FakeProvider, LLMGateway
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import OrganisationCreate
from app.modules.setup import review
from app.modules.setup import service as setup
from app.modules.setup.schemas import Answer, SetupDraftData, SetupStart
from engine.draw import SeedEntry, make_draw

EVAL_SET = Path(__file__).parent / "eval_set"


@pytest.fixture
async def redis(require_services: None) -> AsyncIterator[Redis]:
    client = Redis.from_url(os.environ["REDIS_URL"])
    await client.flushdb()
    yield client
    await client.aclose()


async def run_case(
    name: str, db: AsyncSession, clock: FrozenClock, user: UUID, llm: LLMGateway
) -> UUID:
    case: dict[str, Any] = json.loads((EVAL_SET / name / "case.json").read_text())
    viewer = Viewer(user_id=user)
    org = await competitions.create_organisation(
        db,
        clock,
        viewer,
        OrganisationCreate(
            kind="community", name="Flow Org", sports=["football"], accept_processing_terms=True
        ),
    )
    session = await setup.start(
        db,
        clock,
        viewer,
        SetupStart(
            organisation_id=org.id,
            name=f"Flow {name}",
            starts_on=dt.date(2026, 6, 12),
            ends_on=dt.date(2026, 6, 14),
        ),
    )
    for f in case["files"]:
        path = EVAL_SET / name / f["file"]
        mime = "text/csv" if path.suffix == ".csv" else "text/plain"
        await setup.add_file(
            db,
            clock,
            viewer,
            session.id,
            kind=f["kind"],
            filename=path.name,
            mime=mime,
            data=path.read_bytes(),
        )
    provider = FakeProvider(responses=case["llm"])
    llm._provider = provider
    await setup.run_extraction(db, clock, llm, viewer, session.id)
    return session.id


@pytest.fixture
def llm(redis: Redis, make_settings: Callable[..., Settings], clock: FrozenClock) -> LLMGateway:
    return LLMGateway(FakeProvider(), make_settings(), redis, clock)


async def test_finbangla_cup_publishes_16_teams_4_groups_32_matches(
    db: AsyncSession, clock: FrozenClock, make_user: Callable[[], Awaitable[UUID]], llm: LLMGateway
) -> None:
    user = await make_user()
    session_id = await run_case("en_full_cup", db, clock, user, llm)
    viewer = Viewer(user_id=user)

    ready = await setup.get(db, viewer, session_id)
    assert ready.status == "ready", ready.draft and ready.draft.open_questions
    assert ready.draft is not None and len(ready.draft.open_questions) <= 5
    assert ready.schedule is not None and ready.draw is not None
    assert {m.day for m in ready.schedule.matches} == {1, 2, 3}
    assert len({m.pitch for m in ready.schedule.matches}) == 4
    assert ready.schedule.quality["hard_violations"] == 0

    with pytest.raises(StaleVersion):
        await setup.publish(db, clock, viewer, session_id, if_match='"999"')
    with pytest.raises(SetupNotReady):  # no filming policy chosen yet
        await setup.publish(db, clock, viewer, session_id, if_match=f'"{ready.draft.version}"')
    published = await setup.publish(
        db, clock, viewer, session_id, if_match=f'"{ready.draft.version}"', filming_policy="notice"
    )

    assert (published.teams, published.groups, published.matches) == (16, 4, 32)
    assert (await setup.get(db, viewer, session_id)).status == "published"


async def test_semi_finalists_end_up_in_different_groups_and_the_draw_reproduces(
    db: AsyncSession, clock: FrozenClock, make_user: Callable[[], Awaitable[UUID]], llm: LLMGateway
) -> None:
    user = await make_user()
    session_id = await run_case("en_full_cup", db, clock, user, llm)
    out = await setup.get(db, Viewer(user_id=user), session_id)
    assert out.draft is not None and out.draw is not None
    data = SetupDraftData.model_validate(out.draft.draft)
    _, fmt, seeding, _ = review.engine_inputs(data)
    entries = [
        SeedEntry(team=t.key, previous_placement=t.previous_placement, organiser_rank=i)
        for i, t in enumerate(data.teams, start=1)
    ]

    again = make_draw(entries, fmt, seeding, seed=bytes.fromhex(out.draw.seed))

    assert [[t.key for t in g.teams] for g in out.draw.groups] == [list(g) for g in again.groups]
    semis = {t.key for t in data.teams if (t.previous_placement or 99) <= 4}
    for group in again.groups:
        assert len(semis & set(group)) <= 1


async def test_missing_days_and_pitches_are_assumed_so_the_setup_is_ready_to_publish(
    db: AsyncSession, clock: FrozenClock, make_user: Callable[[], Awaitable[UUID]], llm: LLMGateway
) -> None:
    user = await make_user()
    viewer = Viewer(user_id=user)
    session_id = await run_case("no_rulebook", db, clock, user, llm)
    ready = await setup.get(db, viewer, session_id)

    assert ready.status == "ready" and ready.draft is not None
    assert ready.draft.open_questions == []
    assert {"schedule.days", "schedule.pitches"} <= {a.field for a in ready.draft.assumptions}
    assert ready.schedule is not None and ready.schedule.matches
    published = await setup.publish(
        db, clock, viewer, session_id, if_match=None, filming_policy="not_allowed"
    )
    assert published.teams == 10


async def test_moving_a_match_pins_it_and_redraw_changes_the_seed(
    db: AsyncSession, clock: FrozenClock, make_user: Callable[[], Awaitable[UUID]], llm: LLMGateway
) -> None:
    user = await make_user()
    viewer = Viewer(user_id=user)
    session_id = await run_case("en_full_cup", db, clock, user, llm)
    before = await setup.get(db, viewer, session_id)
    assert before.draw is not None

    redrawn = await setup.redraw(db, clock, viewer, session_id)
    from app.modules.setup.schemas import MoveMatch

    moved = await setup.move_match(
        db,
        clock,
        viewer,
        session_id,
        "A1",
        MoveMatch(date=dt.date(2026, 6, 12), start="10:40", pitch="Pitch 3"),
    )

    assert redrawn.draw is not None and redrawn.draw.seed != before.draw.seed
    assert moved.schedule is not None
    a1 = next(m for m in moved.schedule.matches if m.code == "A1")
    assert (a1.local_time, a1.pitch) == ("10:40", "Pitch 3")


async def test_validation_issues_are_checked_again_until_a_schedule_change_fixes_them(
    db: AsyncSession, clock: FrozenClock, make_user: Callable[[], Awaitable[UUID]], llm: LLMGateway
) -> None:
    user = await make_user()
    viewer = Viewer(user_id=user)
    session_id = await run_case("no_rulebook", db, clock, user, llm)
    ready = await setup.get(db, viewer, session_id)
    assert ready.draft is not None and ready.draft.draft.schedule is not None
    # The organiser's own edit is taken as given: what no longer fits is asked, not fixed.
    tight = dict(ready.draft.draft.schedule)
    tight["pitches"] = ["Pitch 1"]
    tight["days"] = [{**d, "start": "09:00", "end": "10:00"} for d in tight["days"]]

    answered = await setup.change(
        db, clock, viewer, session_id, "schedule", json.dumps(tight), if_match=None
    )

    assert answered.status == "needs_answers" and answered.draft is not None
    issues = answered.draft.open_questions
    assert issues and all("issue" in q.ref for q in issues)
    with pytest.raises(OpenQuestionsRemaining):
        await setup.publish(db, clock, viewer, session_id, if_match=None)
    schedule = dict(answered.draft.draft.schedule or {})
    schedule["pitches"] = ["Pitch 1", "Pitch 2", "Pitch 3", "Pitch 4"]
    schedule["days"] = [{**d, "start": "09:00", "end": "19:00"} for d in schedule["days"]]
    changed = await setup.change(
        db,
        clock,
        viewer,
        session_id,
        "schedule",
        json.dumps(schedule),
        if_match=str(answered.draft.version),
    )
    assert changed.status == "ready", changed.draft and changed.draft.open_questions


async def test_a_team_list_without_two_teams_asks_for_it_instead_of_failing(
    db: AsyncSession, clock: FrozenClock, make_user: Callable[[], Awaitable[UUID]], llm: LLMGateway
) -> None:
    viewer = Viewer(user_id=await make_user())
    org = await competitions.create_organisation(
        db,
        clock,
        viewer,
        OrganisationCreate(
            kind="community", name="Short Org", sports=["football"], accept_processing_terms=True
        ),
    )
    session = await setup.start(
        db, clock, viewer, SetupStart(organisation_id=org.id, name="Short Cup")
    )
    await setup.add_file(
        db,
        clock,
        viewer,
        session.id,
        kind="team_list",
        filename="pasted.txt",
        mime="text/plain",
        data=b"Northside Rovers",
    )

    out = await setup.run_extraction(db, clock, llm, viewer, session.id)

    assert out.status == "needs_answers" and out.draft is not None
    assert any(q.field == "teams" for q in out.draft.open_questions)


async def test_issues_one_answer_fixes_are_offered_as_options(
    db: AsyncSession, clock: FrozenClock, make_user: Callable[[], Awaitable[UUID]], llm: LLMGateway
) -> None:
    user = await make_user()
    viewer = Viewer(user_id=user)
    session_id = await run_case("no_rulebook", db, clock, user, llm)
    waiting = await setup.get(db, viewer, session_id)
    assert waiting.draft is not None
    times = {"schedule.days": "09:00-19:00", "schedule.pitches": "4"}
    ready = await setup.answer(
        db,
        clock,
        viewer,
        session_id,
        [Answer(question_id=q.id, value=times[q.field]) for q in waiting.draft.open_questions],
        if_match=str(waiting.draft.version),
    )
    assert ready.draft is not None and ready.draft.draft.schedule is not None
    short = {**ready.draft.draft.schedule, "match_minutes": 10}

    changed = await setup.change(
        db, clock, viewer, session_id, "schedule", json.dumps(short), if_match=None
    )
    assert changed.draft is not None
    [too_short] = [q for q in changed.draft.open_questions if q.field == "schedule.match_minutes"]
    fixed = await setup.answer(
        db,
        clock,
        viewer,
        session_id,
        [Answer(question_id=too_short.id, value=too_short.options[0])],
        if_match=None,
    )
    data = SetupDraftData.model_validate(ready.draft.draft)
    data.rules["tiebreakers"] = ["score_diff", "points"]
    [order] = review.validation_questions(data)
    reordered = review.apply_change(data, order.field, order.options[0], order)

    assert too_short.ref == {"issue": "match_too_short_for_rules"} and too_short.options
    assert fixed.status == "ready", fixed.draft and fixed.draft.open_questions
    assert (order.field, order.options) == (
        "rules.tiebreakers",
        ["goal difference", "head-to-head"],
    )
    assert review.validation_questions(reordered) == []
