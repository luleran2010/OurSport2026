from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.errors import ValidationFailed
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import OrganisationCreate, TournamentCreate
from app.modules.rules import service
from engine.rules.config import Tiebreaker
from engine.rules.format import groups_then_knockout
from engine.rules.presets import football_rules

MakeUser = Callable[[], Awaitable[UUID]]
CUP = groups_then_knockout([4, 4, 4, 4], per_group=2, third_place_match=True)


async def new_tournament(db: AsyncSession, clock: FrozenClock, owner: UUID) -> UUID:
    viewer = Viewer(user_id=owner)
    org = await competitions.create_organisation(
        db,
        clock,
        viewer,
        OrganisationCreate(
            kind="community", name="Rules Org", sports=["football"], accept_processing_terms=True
        ),
    )
    created = await competitions.create_tournament(
        db,
        clock,
        owner,
        TournamentCreate(organisation_id=org.id, name="Rules Cup", sport="football"),
    )
    return created.id


async def test_confirming_creates_the_next_version_and_defers_a_recalc(
    db: AsyncSession, clock: FrozenClock, make_user: MakeUser
) -> None:
    owner = await make_user()
    cup = await new_tournament(db, clock, owner)
    jobs.deferred.clear()

    await service.save_draft(db, clock, cup, football_rules("football_gd_first", CUP))
    first = await service.confirm(db, clock, Viewer(user_id=owner), cup)
    await service.save_draft(db, clock, cup, football_rules("football_h2h_first", CUP))
    second = await service.confirm(db, clock, Viewer(user_id=owner), cup)

    assert (first.version, second.version) == (1, 2)
    assert (await service.confirmed_config(db, cup)).id == second.id
    assert [j.name for j in jobs.deferred] == ["recalc_tournament", "recalc_tournament"]


async def test_rules_the_engine_rejects_cannot_be_confirmed(
    db: AsyncSession, clock: FrozenClock, make_user: MakeUser
) -> None:
    owner = await make_user()
    cup = await new_tournament(db, clock, owner)
    broken = football_rules("football_gd_first", CUP).model_copy(
        update={"tiebreakers": [Tiebreaker.SCORE_DIFF, Tiebreaker.POINTS]}
    )
    await service.save_draft(db, clock, cup, broken)

    with pytest.raises(ValidationFailed):
        await service.confirm(db, clock, Viewer(user_id=owner), cup)


def test_worked_examples_show_points_and_the_tiebreak() -> None:
    examples = service.worked_examples(football_rules("football_gd_first", CUP))

    tie = next(e for e in examples if e.kind == "edge_case")
    assert {e.title for e in examples} >= {"A win is worth 3 points", "A draw is worth 1 points"}
    assert tie.expected["order"] == ["Team A", "Team B", "Team C"]
    assert tie.expected["decided_by"] == "score_diff"
    assert all(e.passed for e in examples)


@pytest.mark.parametrize("language", ["en", "fi", "bn"])
def test_summary_in_every_language(language: str) -> None:
    lines = service.summarise(football_rules("football_gd_first", CUP), language)  # type: ignore[arg-type]  # parametrised Literal

    assert len(lines) >= 5
    assert "3" in lines[0]


async def test_summary_endpoint_hides_drafts(
    api: TestClient, db: AsyncSession, clock: FrozenClock, make_user: MakeUser
) -> None:
    owner = await make_user()
    cup = await new_tournament(db, clock, owner)
    await service.save_draft(db, clock, cup, football_rules("football_gd_first", CUP))
    await service.confirm(db, clock, Viewer(user_id=owner), cup)
    url = f"/api/v1/tournaments/{cup}/rules/summary?lang=fi"

    hidden = api.get(url)
    async with db.begin():
        await competitions.set_status(db, cup, "upcoming")
    shown = api.get(url)

    assert hidden.status_code == 404
    assert shown.status_code == 200
    assert shown.json()["version"] == 1
    assert shown.json()["lines"][0].startswith("Voitosta saa 3")
