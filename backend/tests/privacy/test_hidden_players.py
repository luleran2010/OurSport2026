"""Hidden and family-only players never appear where they should not (docs/09, Junior
data protection): every public GET endpoint, the venue screen and widget, the live
socket, personal pages of other members, and every piece of AI content."""

import datetime as dt
import json
import os
import re
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.live import LiveHub
from app.core.llm import FakeProvider, LLMGateway
from app.core.time import FrozenClock
from app.core.viewer import CSRF_HEADER, Viewer
from app.modules.accounts import service as accounts
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import PlayerCreate, Visibility
from app.modules.content import commentary, fake_writer
from app.modules.content import service as content
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn

KICK_OFF = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)
HIDDEN, FAMILY, PUBLIC = "Hidden Keeper", "Family Winger", "Public Striker"
VISIBILITY: dict[str, Visibility] = {PUBLIC: "public", HIDDEN: "hidden", FAMILY: "family_only"}
# Public GET routes that need no organiser, editor or scorer rights.
NOT_PUBLIC = (
    "/api/v1/me",
    "/api/v1/admin",
    "/api/v1/setup",
    "/api/v1/review-queue",
    "/api/v1/corrections",
    "/api/v1/scoring",
    "/api/v1/openapi.json",
)
ORGANISER_ONLY = ("/console", "/scorer-passes", "/announcements", "/participants")


@pytest.fixture
async def cup(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_settings: Any,
) -> AsyncIterator[dict[str, Any]]:
    """A finished match where a public, a hidden and a family-only player scored, a live
    match where the hidden player scored, and every story, line and draft written."""
    clock.set(KICK_OFF)
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    await competitions.update_settings(db, tid, {"languages": ["fi", "en", "bn"]})
    await analysis.recalc_tournament(db, clock, tid)
    group = [m for m in await competitions.list_matches(db, tid) if m.stage == "group"]
    finished, live = (
        group[0],
        next(
            m
            for m in group[1:]
            if m.home_team_id == group[0].home_team_id or m.away_team_id == group[0].home_team_id
        ),
    )
    team = finished.home_team_id
    assert team is not None
    players = {
        name: await competitions.create_player(
            db, clock, team, PlayerCreate(display_name=name, visibility=visibility)
        )
        for name, visibility in VISIBILITY.items()
    }
    redis = Redis.from_url(os.environ["REDIS_URL"])
    hub = LiveHub(redis)
    llm = LLMGateway(FakeProvider(responses=fake_writer.responses()), make_settings(), redis, clock)
    await scoring.start(db, clock, owner, finished.id)
    for n, name in enumerate((PUBLIC, HIDDEN, FAMILY), start=1):
        clock.set(KICK_OFF + dt.timedelta(minutes=5 * n))
        accepted = await scoring.post_event(
            db,
            clock,
            owner,
            finished.id,
            EventIn(
                client_seq=n,
                type="goal",
                team_id=team,
                player_id=players[name].id,
                clock=f"{5 * n}:00",
            ),
        )
        await commentary.write_commentary(
            db, clock, llm, hub, finished.id, accepted.seq, accepted.moments
        )
    clock.set(KICK_OFF + dt.timedelta(minutes=40))
    await scoring.finish(db, clock, owner, finished.id, 3, 0)
    await analysis.recalc_tournament(db, clock, tid)
    await content.write_story(db, clock, llm, "match", finished.id, "report")
    await content.write_story(db, clock, llm, "team", team, "team_recap", tournament_id=tid)
    await content.draft_announcement(db, clock, llm, tid, "result", str(finished.id))
    await scoring.start(db, clock, owner, live.id)
    await scoring.post_event(
        db,
        clock,
        owner,
        live.id,
        EventIn(client_seq=1, type="goal", team_id=team, player_id=players[HIDDEN].id),
    )
    yield {
        "tournament_id": tid,
        "organisation_id": None,
        "finished": finished,
        "live": live,
        "team": team,
        "players": players,
    }
    await hub.close()
    await redis.aclose()


def secrets_of(cup: dict[str, Any]) -> list[str]:
    players = cup["players"]
    return [HIDDEN, FAMILY, str(players[HIDDEN].id), str(players[FAMILY].id)]


def assert_clean(body: str, cup: dict[str, Any], where: str) -> None:
    leaked = [s for s in secrets_of(cup) if s in body]
    assert not leaked, f"{where} leaks {leaked}"


async def ids_for(db: AsyncSession, api: TestClient, cup: dict[str, Any]) -> dict[str, str]:
    tournament = api.get(f"/api/v1/tournaments/{cup['tournament_id']}").json()
    stories = api.get(f"/api/v1/matches/{cup['finished'].id}/stories").json()
    series = await db.scalar(
        text("SELECT series_id FROM tournaments WHERE id = :id"), {"id": cup["tournament_id"]}
    )
    org = await db.scalar(
        text("SELECT organisation_id FROM tournaments WHERE id = :id"), {"id": cup["tournament_id"]}
    )
    return {
        "tournament_id": str(cup["tournament_id"]),
        "match_id": str(cup["finished"].id),
        "team_id": str(cup["team"]),
        "story_id": stories[0]["id"],
        "organisation_id": str(org or tournament.get("organisation_id")),
        "series_id": str(series) if series else "",
        "player_id": str(cup["players"][HIDDEN].id),  # must 404 without leaking
        "code": "football",
        "document": "privacy",
    }


def public_get_routes(api: TestClient) -> list[str]:
    """Every GET path of the contract that a fan can call."""
    spec = api.get("/api/v1/openapi.json").json()
    routes = []
    for path, operations in spec["paths"].items():
        top = "/".join(path.split("/")[:4])  # "/api/v1/<first segment>"
        if "get" not in operations or not path.startswith("/api/v1/") or top in NOT_PUBLIC:
            continue
        if any(part in path for part in ORGANISER_ONLY):
            continue
        routes.append(path)
    return routes


async def test_no_public_endpoint_shows_hidden_or_family_players(
    api: TestClient, db: AsyncSession, cup: dict[str, Any], signed_in: dict[str, str]
) -> None:
    ids = await ids_for(db, api, cup)
    routes = public_get_routes(api)
    checked = []
    for path in routes:
        params = re.findall(r"{(\w+)}", path)
        if any(not ids.get(p) for p in params):
            assert params == ["series_id"], f"no test value for {params} in {path}"
            continue
        url = path.format(**ids)
        for match in ("", f"?team_id={ids['team_id']}", "?since_seq=0"):
            response = api.get(url + match)
            assert response.status_code < 500, (url, response.text)
            assert_clean(response.text, cup, url + match)
        checked.append(path)
    for name in (HIDDEN, FAMILY):
        player = cup["players"][name].id
        assert api.get(f"/api/v1/players/{player}").status_code == 404
        hits = api.get(f"/api/v1/search?q={name}").json()["hits"]  # the query is echoed back
        assert_clean(json.dumps(hits), cup, f"search {name}")
    live_url = f"/api/v1/matches/{cup['live'].id}"
    for suffix in ("", "/timeline", "/commentary", "/stories"):
        assert_clean(api.get(live_url + suffix).text, cup, live_url + suffix)

    assert len(checked) >= 20, checked
    for must in ("/screen", "/widget", "/timeline", "/stories", "/commentary", "/feed"):
        assert any(must in p for p in checked), must


async def test_other_members_never_see_them_and_family_sees_only_their_own(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    cup: dict[str, Any],
    signed_in: dict[str, str],
) -> None:
    headers = {CSRF_HEADER: signed_in["csrf_token"]}
    api.post(
        "/api/v1/me/follows",
        json={"target_type": "team", "target_id": str(cup["team"]), "is_primary": True},
        headers=headers,
    )
    for url in (
        "/api/v1/me/home",
        f"/api/v1/me/teams/{cup['team']}/hub",
        "/api/v1/me/feed",
        "/api/v1/me/notifications",
    ):
        assert_clean(api.get(url).text, cup, url)

    await accounts.link_family(
        db, clock, UUID(signed_in["user_id"]), cup["players"][FAMILY].id, None
    )
    hub = api.get(f"/api/v1/me/teams/{cup['team']}/hub").text
    assert FAMILY in hub
    assert HIDDEN not in hub and str(cup["players"][HIDDEN].id) not in hub


async def test_the_live_socket_never_carries_them(api: TestClient, cup: dict[str, Any]) -> None:
    match = cup["live"]
    token = api.get(f"/api/v1/live/token?match_id={match.id}").json()["token"]
    with api.websocket_connect(f"/api/v1/live/matches/{match.id}?token={token}") as ws:
        snapshot = ws.receive_text()

    assert '"snapshot"' in snapshot
    assert_clean(snapshot, cup, "match socket snapshot")


async def test_ai_content_never_names_them(db: AsyncSession, cup: dict[str, Any]) -> None:
    rows = await db.execute(
        text(
            "SELECT 'story', headline || ' ' || body || sentences::text FROM stories "
            "UNION ALL SELECT 'commentary', texts::text FROM commentary_items "
            "UNION ALL SELECT 'announcement', texts::text FROM announcements "
            "UNION ALL SELECT 'fact_sheet', facts::text FROM fact_sheets"
        )
    )
    found = rows.all()

    kinds = {kind for kind, _ in found}
    assert {"story", "commentary", "announcement", "fact_sheet"} <= kinds
    for kind, body in found:
        assert_clean(body, cup, kind)
    assert any(PUBLIC in body for kind, body in found if kind == "story")
