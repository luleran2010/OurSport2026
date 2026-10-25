"""Ratings and predictions in the tournament: priors, the seeding factor, confidence, juniors."""

import datetime as dt
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import ResultIn


async def test_predictions_name_last_years_runner_up_and_have_no_percentages_yet(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    tid = published_cup["tournament_id"]
    await analysis.recalc_tournament(db, clock, tid)
    runner_up = next(e for e in await competitions.entries_of(db, tid) if e.name == "Harbour Lions")
    match = next(
        m
        for m in await competitions.list_matches(db, tid)
        if m.stage == "group" and runner_up.team_id in (m.home_team_id, m.away_team_id)
    )

    response = api.get(f"/api/v1/matches/{match.id}/prediction")

    body = response.json()
    assert response.status_code == 200
    assert body["confidence"] == "none"  # nobody has 3 rated games yet
    assert body["home_win"] is None  # so only reasons, no percentages
    assert "2025 runner-up" in {f["text"] for f in body["factors"]}


async def test_results_update_ratings_and_knockout_predictions_gain_confidence(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC))
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    strength = {e.team_id: -(e.seed or 0) for e in await competitions.entries_of(db, tid)}
    for m in (m for m in await competitions.list_matches(db, tid) if m.stage == "group"):
        assert m.home_team_id and m.away_team_id
        home_wins = strength[m.home_team_id] > strength[m.away_team_id]
        await scoring.enter_result(
            db,
            clock,
            owner,
            m.id,
            ResultIn(home_goals=3 if home_wins else 0, away_goals=0 if home_wins else 2),
        )
    await analysis.recalc_tournament(db, clock, tid)
    qf = next(m for m in await competitions.list_matches(db, tid) if m.code == "QF1")

    body = api.get(f"/api/v1/matches/{qf.id}/prediction").json()

    assert body["confidence"] == "low"  # 3 group games each
    assert body["draw"] is None  # knockout
    low, high = body["home_win"]
    assert 0 < low <= high < 1


async def test_junior_tournaments_never_show_percentages(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    tid = published_cup["tournament_id"]
    await competitions.update_settings(db, tid, {"show_probabilities": False})
    await analysis.recalc_tournament(db, clock, tid)
    match = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")

    body = api.get(f"/api/v1/matches/{match.id}/prediction").json()

    assert (body["home_win"], body["draw"], body["away_win"]) == (None, None, None)
