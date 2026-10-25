"""Scoring: passes, idempotent events, validation, undo, finish, results-only."""

import asyncio
import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.errors import Conflict
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut
from app.modules.scoring import service
from app.modules.scoring.models import MatchEvent
from app.modules.scoring.schemas import EventIn

MATCH_DAY = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)  # 10:00 in Helsinki


async def setting(
    db: AsyncSession, cup: dict[str, Any], clock: FrozenClock
) -> tuple[list[Any], list[MatchOut]]:
    clock.set(MATCH_DAY)
    owner = Viewer(user_id=cup["owner"])
    passes = await service.list_passes(db, cup["settings"], owner, cup["tournament_id"])
    matches = await competitions.list_matches(db, cup["tournament_id"])
    return passes, matches


def pass_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Pass {token}"}


async def test_publish_creates_a_pass_per_pitch(
    db: AsyncSession, published_cup: dict[str, Any], clock: FrozenClock
) -> None:
    passes, _ = await setting(db, published_cup, clock)

    assert [p.label for p in passes] == ["Pitch 1", "Pitch 2", "Pitch 3", "Pitch 4"]
    assert all(p.scan_url.endswith(p.token) for p in passes)


async def test_scoring_over_http_with_a_pitch_pass(
    api: TestClient, db: AsyncSession, published_cup: dict[str, Any], clock: FrozenClock
) -> None:
    passes, matches = await setting(db, published_cup, clock)
    pitch2 = passes[1]
    on_2 = next(m for m in matches if m.pitch_id == pitch2.pitch_id and m.stage == "group")
    on_3 = next(m for m in matches if m.pitch_id == passes[2].pitch_id and m.stage == "group")
    headers = pass_header(pitch2.token)
    base = f"/api/v1/matches/{on_2.id}"

    wrong_pitch = api.post(f"/api/v1/matches/{on_3.id}/start", headers=headers)
    started = api.post(f"{base}/start", headers=headers)
    goal = {"client_seq": 1, "type": "goal", "team_id": str(on_2.home_team_id)}
    first = api.post(f"{base}/events", json=goal, headers=headers)
    retry = api.post(f"{base}/events", json=goal, headers=headers)
    unknown = api.post(f"{base}/events", json={"client_seq": 2, "type": "dance"}, headers=headers)
    stranger = api.post(
        f"{base}/events",
        json={"client_seq": 2, "type": "goal", "team_id": str(on_3.home_team_id)},
        headers=headers,
    )
    mine = api.get("/api/v1/scoring/me", headers=headers)

    assert wrong_pitch.status_code == 403
    assert wrong_pitch.json()["code"] == "scorer_not_assigned"
    assert started.status_code == 200
    assert (first.status_code, retry.status_code) == (201, 200)
    assert first.json()["seq"] == retry.json()["seq"] == 1
    assert first.json()["live"]["home_goals"] == 1
    assert "goal" in first.json()["moments"]
    assert (unknown.status_code, stranger.status_code) == (422, 422)
    assert on_2.id in {m["match_id"] for m in mine.json()} or str(on_2.id) in {
        m["match_id"] for m in mine.json()
    }

    await service.revoke_pass(
        db, clock, Viewer(user_id=published_cup["owner"]), published_cup["tournament_id"], pitch2.id
    )
    revoked = api.post(f"{base}/events", json={**goal, "client_seq": 3}, headers=headers)
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "pass_revoked"


async def test_concurrent_duplicates_store_one_event(
    db: AsyncSession, database_url: str, published_cup: dict[str, Any], clock: FrozenClock
) -> None:
    _, matches = await setting(db, published_cup, clock)
    match = next(m for m in matches if m.stage == "group")
    owner = Viewer(user_id=published_cup["owner"])
    await service.start(db, clock, owner, match.id)
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    event = EventIn(client_seq=1, type="goal", team_id=match.away_team_id)

    async def post() -> int:
        async with sessions() as session:
            return (await service.post_event(session, clock, owner, match.id, event)).seq

    try:
        seqs = await asyncio.gather(post(), post(), post())
    finally:
        await engine.dispose()

    count = await db.scalar(
        select(func.count()).select_from(MatchEvent).where(MatchEvent.match_id == match.id)
    )
    assert len(set(seqs)) == 1
    assert count == 1


async def test_undo_finish_and_results_only(
    db: AsyncSession, published_cup: dict[str, Any], clock: FrozenClock
) -> None:
    _, matches = await setting(db, published_cup, clock)
    group = [m for m in matches if m.stage == "group"]
    match, other = group[0], group[1]
    owner = Viewer(user_id=published_cup["owner"])
    await service.start(db, clock, owner, match.id)
    home, away = match.home_team_id, match.away_team_id

    for seq, (type_, team) in enumerate([("goal", home), ("goal", away), ("goal", home)], start=1):
        await service.post_event(
            db, clock, owner, match.id, EventIn(client_seq=seq, type=type_, team_id=team)
        )
    undone = await service.undo(db, clock, owner, match.id, seq=3, client_seq=4)
    with pytest.raises(Conflict):
        await service.finish(db, clock, owner, match.id, 2, 1)
    await service.post_event(
        db, clock, owner, match.id, EventIn(client_seq=6, type="yellow_card", team_id=home)
    )
    with pytest.raises(Conflict):  # 5 would land before the already accepted 6
        await service.post_event(
            db, clock, owner, match.id, EventIn(client_seq=5, type="yellow_card", team_id=away)
        )
    finished = await service.finish(db, clock, owner, match.id, 1, 1)
    from app.modules.scoring.schemas import ResultIn

    quick = await service.enter_result(
        db, clock, owner, other.id, ResultIn(home_goals=2, away_goals=0)
    )

    assert (undone.live.home_goals, undone.live.away_goals) == (1, 1)
    assert finished.status == "finished"
    assert finished.result == {
        "home_goals": 1,
        "away_goals": 1,
        "decided_by": "regulation",
        "home_penalties": None,
        "away_penalties": None,
    }
    assert quick.result is not None and quick.result["home_goals"] == 2
    stored = await competitions.get_match(db, other.id)
    assert (stored.status, stored.data_level) == ("finished", "results")


def test_event_types_endpoint(api: TestClient) -> None:
    response = api.get("/api/v1/sports/football/event-types")

    assert response.status_code == 200
    pad = response.json()
    assert "goal" in pad["event_types"]
    assert {b["id"] for b in pad["buttons"]} >= {"goal", "yellow_card", "period_start"}
