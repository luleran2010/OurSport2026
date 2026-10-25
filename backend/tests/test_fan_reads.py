"""Fan reads: caching, live access policy, drafts hidden, speed on the seed data."""

import datetime as dt
import statistics
import time
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn

MATCH_DAY = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)


async def test_standings_carry_an_etag_and_304_when_unchanged(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    tid = published_cup["tournament_id"]
    await analysis.recalc_tournament(db, clock, tid)

    first = api.get(f"/api/v1/tournaments/{tid}/standings")
    again = api.get(
        f"/api/v1/tournaments/{tid}/standings", headers={"If-None-Match": first.headers["ETag"]}
    )

    assert first.status_code == 200
    assert len(first.json()["groups"]) == 4
    assert first.headers["Cache-Control"] == "public, max-age=30"
    assert again.status_code == 304


async def test_members_policy_hides_the_live_score_from_anonymous_viewers(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    signed_in: dict[str, str],
) -> None:
    clock.set(MATCH_DAY)
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    match = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")
    await scoring.start(db, clock, owner, match.id)
    await scoring.post_event(
        db, clock, owner, match.id, EventIn(client_seq=1, type="goal", team_id=match.home_team_id)
    )
    await competitions.update_settings(db, tid, {"live_access": "members"})

    member = api.get(f"/api/v1/matches/{match.id}")
    api.cookies.clear()
    anonymous = api.get(f"/api/v1/matches/{match.id}")
    live_anon = api.get(f"/api/v1/tournaments/{tid}/live")

    assert member.json()["match"]["score"]["home_goals"] == 1
    assert member.headers["Cache-Control"] == "private, no-store"
    assert anonymous.status_code == 200
    assert anonymous.json()["match"]["score"] is None
    assert live_anon.json()["matches"][0]["score"] is None


async def test_drafts_are_not_public(
    api: TestClient, db: AsyncSession, clock: FrozenClock, make_user: Callable[[], Any]
) -> None:
    from app.modules.competitions.schemas import OrganisationCreate, TournamentCreate

    user = await make_user()
    owner = Viewer(user_id=user)
    org = await competitions.create_organisation(
        db,
        clock,
        owner,
        OrganisationCreate(
            kind="club", name="Draft Org", sports=["football"], accept_processing_terms=True
        ),
    )
    draft = await competitions.create_tournament(
        db,
        clock,
        user,
        TournamentCreate(organisation_id=org.id, name="Draft Cup", sport="football"),
    )

    assert api.get(f"/api/v1/tournaments/{draft.id}").status_code == 404
    assert api.get(f"/api/v1/tournaments/{draft.id}/standings").status_code == 404


async def test_published_draw_and_team_pages(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    tid = published_cup["tournament_id"]
    await analysis.recalc_tournament(db, clock, tid)
    team = (await competitions.entries_of(db, tid))[0]

    draw = api.get(f"/api/v1/tournaments/{tid}/draw")
    page = api.get(f"/api/v1/teams/{team.team_id}")
    screen = api.get(f"/api/v1/tournaments/{tid}/screen")

    assert draw.status_code == 200 and len(draw.json()["groups"]) == 4
    assert page.status_code == 200 and len(page.json()["matches"]) == 3
    assert "contact" not in page.text
    assert screen.status_code == 200 and len(screen.json()["next_up"]) == 4


async def test_reads_are_fast_on_the_seed_data(
    api: TestClient,
    database_url: str,
    make_settings: Callable[..., Settings],
    db: AsyncSession,
    clock: FrozenClock,
) -> None:
    from app.scripts.seed import seed

    await seed(make_settings(database_url=database_url))
    cup = await competitions.find_tournament(db, "demo-community-cup-2026")
    assert cup is not None
    await analysis.recalc_tournament(db, clock, cup.id)
    paths = ["", "/standings", "/schedule", "/live", "/bracket", "/screen"]
    timings = []
    for _ in range(5):
        for path in paths:
            started = time.perf_counter()
            assert api.get(f"/api/v1/tournaments/{cup.id}{path}").status_code == 200
            timings.append(time.perf_counter() - started)

    p95 = statistics.quantiles(timings, n=20)[-1]
    assert p95 < 0.15, p95
