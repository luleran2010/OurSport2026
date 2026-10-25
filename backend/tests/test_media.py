"""Streams with the filming check, opt-outs and the live draw (docs/06, docs/13 §4)."""

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FilmingNotPermitted, NotFound
from app.core.live import LiveHub, tournament_channel
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import ConsentCreate, PlayerCreate
from app.modules.media import service as media
from app.modules.media.schemas import AttestationIn, OptOutIn, StreamIn
from app.modules.setup import service as setup

GOOD = StreamIn(
    provider="youtube",
    playback_url="https://www.youtube.com/watch?v=example",  # type: ignore[arg-type]  # pydantic parses it
    rights_confirmed=True,
    venue_permission=True,
)


@pytest.fixture
async def hub() -> AsyncIterator[LiveHub]:
    redis = Redis.from_url(os.environ["REDIS_URL"])
    live = LiveHub(redis)
    yield live
    await live.close()
    await redis.aclose()


def failing(exc: FilmingNotPermitted) -> set[str]:
    return {e.field or "" for e in exc.errors}


async def first_match(db: AsyncSession, cup: dict[str, Any]) -> Any:
    return (await competitions.list_matches(db, cup["tournament_id"]))[0]


async def test_a_stream_needs_rights_and_the_filming_notice(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    owner = Viewer(user_id=published_cup["owner"])
    match = await first_match(db, published_cup)
    no_rights = GOOD.model_copy(update={"rights_confirmed": False, "venue_permission": False})

    with pytest.raises(FilmingNotPermitted) as refused:
        await media.attach_stream(db, clock, owner, match.id, no_rights)
    denied = api.post(f"/api/v1/matches/{match.id}/stream", json=GOOD.model_dump(mode="json"))
    await media.publish_notice(db, clock, owner, published_cup["tournament_id"])
    stream = await media.attach_stream(db, clock, owner, match.id, GOOD)
    notice = api.get(f"/api/v1/tournaments/{published_cup['tournament_id']}/filming-notice")
    served = api.get(f"/api/v1/matches/{match.id}/stream")

    assert failing(refused.value) == {"rights_confirmed", "venue_permission", "filming_notice"}
    assert denied.status_code == 401
    assert stream.status == "live"
    assert notice.status_code == 200 and set(notice.json()["texts"]) == {"fi", "en"}
    assert served.status_code == 200 and served.json()["playback_url"].startswith("https://")


async def test_junior_players_need_filming_consent_or_an_attestation(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    match = await first_match(db, published_cup)
    assert match.home_team_id
    junior = await competitions.create_player(
        db, clock, match.home_team_id, PlayerCreate(display_name="Junior Keeper", birth_year=2013)
    )
    await media.publish_notice(db, clock, owner, tid)

    with pytest.raises(FilmingNotPermitted) as refused:
        await media.attach_stream(db, clock, owner, match.id, GOOD)
    await competitions.record_consent(
        db, clock, junior.id, ConsentCreate(scope="filming", guardian_contact="guardian")
    )
    allowed = await media.attach_stream(db, clock, owner, match.id, GOOD)
    await competitions.update_settings(db, tid, {"filming_policy": "consent_required"})
    adult = await competitions.create_player(
        db, clock, match.home_team_id, PlayerCreate(display_name="Adult Without Consent")
    )
    with pytest.raises(FilmingNotPermitted) as everyone:
        await media.attach_stream(db, clock, owner, match.id, GOOD)
    await media.attest(
        db,
        clock,
        owner,
        tid,
        AttestationIn(statement="Signed filming consent forms collected for all players."),
    )
    attested = await media.attach_stream(db, clock, owner, match.id, GOOD)
    await competitions.update_settings(db, tid, {"filming_policy": "not_allowed"})
    with pytest.raises(FilmingNotPermitted) as forbidden:
        await media.attach_stream(db, clock, owner, match.id, GOOD)

    assert failing(refused.value) == {"consents"}
    assert allowed.status == "live" and attested.status == "live"
    assert failing(everyone.value) == {"consents"} and adult.visibility == "public"
    assert failing(forbidden.value) == {"filming_policy"}


async def test_an_opt_out_pauses_the_stream_and_blocks_the_next_attach(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_user: Callable[[], Awaitable[UUID]],
    hub: LiveHub,
) -> None:
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    match = await first_match(db, published_cup)
    await media.publish_notice(db, clock, owner, tid)
    await media.attach_stream(db, clock, owner, match.id, GOOD)
    guardian = Viewer(user_id=await make_user())

    optout = await media.opt_out(
        db, clock, guardian, tid, OptOutIn(team_id=match.home_team_id, reason="No filming"), hub
    )
    gone = api.get(f"/api/v1/matches/{match.id}/stream")
    with pytest.raises(FilmingNotPermitted) as blocked:
        await media.attach_stream(db, clock, owner, match.id, GOOD)
    with pytest.raises(NotFound):
        await media.optouts(db, guardian, tid)
    listed = await media.optouts(db, owner, tid)
    await media.resolve_optout(db, clock, owner, tid, optout.id, "The child will not be filmed.")
    again = await media.attach_stream(db, clock, owner, match.id, GOOD)

    assert gone.status_code == 404
    assert failing(blocked.value) == {"optouts"}
    assert [o.id for o in listed] == [optout.id]
    assert again.status == "live"


async def test_the_live_draw_reveals_pot_by_pot_then_shows_the_seed(
    api: TestClient,
    db: AsyncSession,
    clock: FrozenClock,
    published_cup: dict[str, Any],
    make_user: Callable[[], Awaitable[UUID]],
    hub: LiveHub,
) -> None:
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    socket = await hub.subscribe(tournament_channel(tid))

    start = api.get(f"/api/v1/tournaments/{tid}/draw/reveal").json()
    first = await setup.reveal_next(db, clock, owner, tid, hub)
    with pytest.raises(NotFound):
        await setup.reveal_next(db, clock, Viewer(user_id=await make_user()), tid, hub)
    message = await asyncio.wait_for(socket.get(), timeout=3)
    for _ in range(first.total - 1):
        last = await setup.reveal_next(db, clock, owner, tid, None)
    reset = await setup.reset_reveal(db, owner, tid)

    assert start["revealed"] == 0 and start["steps"] == [] and start["seed"] is None
    assert first.steps[0].pot == 1 and first.revealed == 1
    assert message["type"] == "draw_step" and message["data"]["team"] == first.steps[0].team
    assert last.revealed == last.total == 16 and last.seed
    assert [s.pot for s in last.steps] == sorted(s.pot or 99 for s in last.steps)
    assert reset.revealed == 0
