"""Live sockets: ordered delivery, resync without gaps, fan-out across two API instances."""

import datetime as dt
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.main import create_app
from app.modules.competitions import service as competitions
from app.modules.scoring import service as scoring

MATCH_DAY = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)


def next_of(ws: WebSocketTestSession, type_: str, tries: int = 40) -> dict[str, Any]:
    for _ in range(tries):
        message: dict[str, Any] = ws.receive_json()
        if message["type"] == type_:
            return message
    raise AssertionError(f"no {type_} message")


@pytest.fixture
async def match_setup(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> dict[str, Any]:
    clock.set(MATCH_DAY)
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    passes = await scoring.list_passes(db, published_cup["settings"], owner, tid)
    match = next(
        m
        for m in await competitions.list_matches(db, tid)
        if m.stage == "group" and m.pitch_id == passes[0].pitch_id
    )
    return {"match": match, "pass": passes[0].token, "tournament_id": tid}


def goal(client: TestClient, setup: dict[str, Any], n: int) -> int:
    match = setup["match"]
    response = client.post(
        f"/api/v1/matches/{match.id}/events",
        json={"client_seq": n, "type": "goal", "team_id": str(match.home_team_id)},
        headers={"Authorization": f"Pass {setup['pass']}"},
    )
    assert response.status_code == 201, response.text
    seq: int = response.json()["seq"]
    return seq


def test_events_reach_viewers_on_two_instances_in_order_and_resync_without_gaps(
    database_url: str,
    make_settings: Callable[..., Settings],
    clock: FrozenClock,
    match_setup: dict[str, Any],
) -> None:
    settings = make_settings(database_url=database_url, live_ping_seconds=0.3)
    match = match_setup["match"]
    with (
        TestClient(create_app(settings, clock=clock)) as one,
        TestClient(create_app(settings, clock=clock)) as two,
    ):
        started = one.post(
            f"/api/v1/matches/{match.id}/start",
            headers={"Authorization": f"Pass {match_setup['pass']}"},
        )
        assert started.status_code == 200
        token = one.get(f"/api/v1/live/token?match_id={match.id}").json()["token"]
        url = f"/api/v1/live/matches/{match.id}?token={token}"
        with (
            one.websocket_connect(url + "&since_seq=0") as ws1,
            two.websocket_connect(url + "&since_seq=0") as ws2,
        ):
            assert next_of(ws1, "snapshot")["data"]["timeline"] == []
            next_of(ws2, "snapshot")
            seqs = [goal(one, match_setup, n) for n in (1, 2, 3)]
            got1 = [next_of(ws1, "event")["seq"] for _ in seqs]
            got2 = [next_of(ws2, "event")["seq"] for _ in seqs]
            assert got1 == got2 == seqs == [1, 2, 3]
        # Forced disconnect: two more goals while the viewer is away, then resync.
        later = [goal(one, match_setup, n) for n in (4, 5)]
        token = two.get(f"/api/v1/live/token?match_id={match.id}").json()["token"]
        with two.websocket_connect(
            f"/api/v1/live/matches/{match.id}?token={token}&since_seq=3"
        ) as ws:
            snapshot = next_of(ws, "snapshot")
            assert [e["seq"] for e in snapshot["data"]["timeline"]] == later
            assert snapshot["data"]["score"]["home_goals"] == 5
            sixth = goal(one, match_setup, 6)
            event = next_of(ws, "event")
            assert event["seq"] == sixth == 6
            assert event["data"]["score"]["home_goals"] == 6


def test_a_socket_without_a_valid_token_is_refused(
    database_url: str,
    make_settings: Callable[..., Settings],
    clock: FrozenClock,
    match_setup: dict[str, Any],
) -> None:
    settings = make_settings(database_url=database_url)
    with TestClient(create_app(settings, clock=clock)) as client:
        with (
            pytest.raises(WebSocketDisconnect) as closed,
            client.websocket_connect(
                f"/api/v1/live/matches/{match_setup['match'].id}?token=nope"
            ) as ws,
        ):
            ws.receive_json()
        assert closed.value.code == 4401


async def test_members_policy_needs_a_signed_in_viewer_for_a_token(
    api: TestClient, db: AsyncSession, match_setup: dict[str, Any]
) -> None:
    await competitions.update_settings(db, match_setup["tournament_id"], {"live_access": "members"})

    response = api.get(f"/api/v1/live/token?match_id={match_setup['match'].id}")

    assert response.status_code == 401
