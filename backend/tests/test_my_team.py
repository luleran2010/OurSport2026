"""My Team: the sign-up follow, the hub (never hidden players), feeds, speed."""

import datetime as dt
import statistics
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time import FrozenClock
from app.core.viewer import CSRF_HEADER, Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import PlayerCreate
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import ResultIn
from conftest import Mailpit


def sign_up_following(api: TestClient, mailpit: Mailpit, team_id: Any) -> dict[str, Any]:
    email = f"fan-{uuid4().hex[:10]}@example.com"
    api.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "display_name": "Fan",
            "language": "en",
            "time_zone": "Europe/Helsinki",
            "age_13_plus": True,
            "privacy_accepted": True,
            "follow": {"target_type": "team", "target_id": str(team_id)},
        },
    )
    session = api.post(
        "/api/v1/auth/magic-link/verify", json={"token": mailpit.latest_token(email)}
    )
    assert session.status_code == 200
    body: dict[str, Any] = session.json()
    return body


def test_personal_endpoints_need_an_account(api: TestClient) -> None:
    for path in ("/api/v1/me/home", "/api/v1/me/feed", "/api/v1/me/follows"):
        assert api.get(path).status_code == 401


async def test_the_team_chosen_before_sign_up_becomes_my_team(
    api: TestClient,
    mailpit: Mailpit,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
) -> None:
    tid = published_cup["tournament_id"]
    await analysis.recalc_tournament(db, clock, tid)
    team = (await competitions.entries_of(db, tid))[0]

    sign_up_following(api, mailpit, team.team_id)
    home = api.get("/api/v1/me/home")

    assert home.status_code == 200
    body = home.json()
    assert body["primary"]["team"]["id"] == str(team.team_id)
    assert body["primary"]["status_chip"].startswith(("1st", "2nd", "3rd", "4th"))
    assert body["primary"]["now_or_next"]["status"] == "scheduled"
    assert body["primary"]["league"]["group"] in "ABCD"
    assert home.headers["Cache-Control"] == "private, no-store"


async def test_the_hub_never_shows_hidden_players(
    api: TestClient,
    mailpit: Mailpit,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
) -> None:
    team = (await competitions.entries_of(db, published_cup["tournament_id"]))[0].team_id
    await competitions.create_player(db, clock, team, PlayerCreate(display_name="Grown Up"))
    await competitions.create_player(
        db, clock, team, PlayerCreate(display_name="Young Junior", birth_year=clock.now().year - 12)
    )

    sign_up_following(api, mailpit, team)
    hub = api.get(f"/api/v1/me/teams/{team}/hub")

    names = {p["display_name"] for p in hub.json()["players"]}
    assert "Grown Up" in names
    assert "Young Junior" not in names
    assert "Young Junior" not in hub.text


async def test_feeds_show_results_of_what_i_follow(
    api: TestClient,
    mailpit: Mailpit,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
) -> None:
    clock.set(dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC))
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    first = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")
    await scoring.enter_result(db, clock, owner, first.id, ResultIn(home_goals=2, away_goals=1))
    session = sign_up_following(api, mailpit, first.home_team_id)
    api.post(
        "/api/v1/me/follows",
        json={"target_type": "tournament", "target_id": str(tid)},
        headers={CSRF_HEADER: session["csrf_token"]},
    )

    mine = api.get("/api/v1/me/feed?limit=2").json()
    public = api.get(f"/api/v1/tournaments/{tid}/feed").json()

    assert mine["items"][0]["kind"] in ("result", "next_match")
    assert any(i["kind"] == "result" and i["match"]["id"] == str(first.id) for i in mine["items"])
    assert mine["next_cursor"] is not None
    assert [i["match"]["id"] for i in public["items"]] == [str(first.id)]


async def test_hub_is_fast_on_the_seed_data(
    api: TestClient,
    mailpit: Mailpit,
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
    team = (await competitions.entries_of(db, cup.id))[0].team_id
    sign_up_following(api, mailpit, team)
    timings = []
    for _ in range(15):
        started = time.perf_counter()
        assert api.get("/api/v1/me/home").status_code == 200
        timings.append(time.perf_counter() - started)

    assert statistics.quantiles(timings, n=20)[-1] < 0.3
