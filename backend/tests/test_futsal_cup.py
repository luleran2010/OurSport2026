"""A futsal cup through the whole pipeline: setup, scoring with fouls and timeouts,
commentary on the sixth foul, standings and the match report (T-065)."""

import datetime as dt
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ValidationFailed
from app.core.llm import FakeProvider, LLMGateway
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import OrganisationCreate
from app.modules.content import commentary, fake_writer
from app.modules.content import service as content
from app.modules.rules import service as rules
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn
from app.modules.setup import service as setup
from app.modules.setup.schemas import SetupStart
from engine.rules.config import RuleConfig

FOLDER = Path(__file__).parents[1] / "app" / "scripts" / "seed_data" / "futsal"
MATCH_DAY = dt.datetime(2026, 11, 14, 7, 0, tzinfo=dt.UTC)


@pytest.fixture
async def futsal_cup(
    db: AsyncSession,
    clock: FrozenClock,
    make_settings: Callable[..., Settings],
    make_user: Callable[[], Awaitable[UUID]],
) -> AsyncIterator[dict[str, Any]]:
    settings = make_settings()
    scoring.register(settings, clock)
    case = json.loads((FOLDER / "case.json").read_text())
    owner = Viewer(user_id=await make_user())
    org = await competitions.create_organisation(
        db,
        clock,
        owner,
        OrganisationCreate(
            kind="club", name="Futsal Club", sports=["futsal"], accept_processing_terms=True
        ),
    )
    session = await setup.start(
        db,
        clock,
        owner,
        SetupStart(
            organisation_id=org.id,
            name="Futsal Cup",
            sport="futsal",
            starts_on=dt.date(2026, 11, 14),
            ends_on=dt.date(2026, 11, 14),
        ),
    )
    for f in case["files"]:
        path = FOLDER / f["file"]
        await setup.add_file(
            db,
            clock,
            owner,
            session.id,
            kind=f["kind"],
            filename=path.name,
            mime="text/csv" if path.suffix == ".csv" else "text/plain",
            data=path.read_bytes(),
        )
    redis = Redis.from_url(os.environ["REDIS_URL"])
    await redis.flushdb()
    llm = LLMGateway(FakeProvider(responses=case["llm"]), settings, redis, clock)
    ready = await setup.run_extraction(db, clock, llm, owner, session.id)
    published = await setup.publish(db, clock, owner, session.id, None, "notice")
    writer = LLMGateway(FakeProvider(responses=fake_writer.responses()), settings, redis, clock)
    yield {"tournament_id": published.tournament_id, "owner": owner, "ready": ready, "llm": writer}
    await redis.aclose()


async def test_a_futsal_cup_goes_from_setup_to_scoring_to_stories(
    api: TestClient, db: AsyncSession, clock: FrozenClock, futsal_cup: dict[str, Any]
) -> None:
    tid, owner, llm = futsal_cup["tournament_id"], futsal_cup["owner"], futsal_cup["llm"]
    config = RuleConfig.model_validate((await rules.confirmed_config(db, tid)).config)
    clock.set(MATCH_DAY)
    await analysis.recalc_tournament(db, clock, tid)
    match = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")
    home, away = match.home_team_id, match.away_team_id
    pad = api.get("/api/v1/sports/futsal/event-types").json()

    await scoring.start(db, clock, owner, match.id)
    n = 0

    async def post(type_: str, team: UUID | None, **payload: Any) -> Any:
        nonlocal n
        n += 1
        return await scoring.post_event(
            db,
            clock,
            owner,
            match.id,
            EventIn(client_seq=n, type=type_, team_id=team, payload=payload, clock="10:00"),
        )

    await post("period_start", None, period=1)
    fouls = [await post("foul", home) for _ in range(6)]
    timeout = await post("timeout", away)
    with pytest.raises(ValidationFailed) as again:
        await post("timeout", away)
    await post("goal", home)
    await post("goal", away)
    await post("goal", home)
    line = await commentary.write_commentary(
        db, clock, llm, None, match.id, fouls[-1].seq, fouls[-1].moments
    )
    clock.set(MATCH_DAY + dt.timedelta(minutes=50))
    await scoring.finish(db, clock, owner, match.id, 2, 1)
    await analysis.recalc_tournament(db, clock, tid)
    tables = {str(s.group_id): s.rows for s in await analysis.latest_standings(db, tid)}
    stories = await content.write_story(db, clock, llm, "match", match.id, "report")

    assert config.sport == "futsal"
    assert config.match["period_minutes"] == 20 and config.match["foul_limit"] == 5
    assert [t.value for t in config.tiebreakers[:2]] == ["points", "head_to_head_points"]
    assert {"foul", "timeout"} <= set(pad["event_types"])
    assert [f.moments for f in fouls[:5]] == [[]] * 5 and fouls[5].moments == ["sixth_foul"]
    assert timeout.moments == ["timeout"] and "timeout_used" in str(again.value)
    assert line is not None and "sixth_foul" in line.moments
    winner = next(r for r in tables[str(match.group_id)] if r["team_id"] == str(home))
    assert winner["points"] == 3 and winner["goals_for"] == 2
    assert {s.language for s in stories} == {"fi", "en"}
    assert all(s.ai_label for s in stories)
