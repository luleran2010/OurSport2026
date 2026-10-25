"""Match analysis from real events, comparisons and simulated chances, through the API."""

import datetime as dt
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.analysis import service as analysis
from app.modules.competitions import service as competitions
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn


async def test_a_late_comeback_is_analysed_and_chances_are_simulated(
    api: TestClient, db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC))
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    await analysis.recalc_tournament(db, clock, tid)
    match = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")
    home, away = match.home_team_id, match.away_team_id
    await scoring.start(db, clock, owner, match.id)
    for n, (team, minute) in enumerate(
        [(away, 10), (away, 22), (home, 30), (home, 33), (home, 38)], start=1
    ):
        await scoring.post_event(
            db,
            clock,
            owner,
            match.id,
            EventIn(client_seq=n, type="goal", team_id=team, clock=f"{minute}:00"),
        )
    await scoring.finish(db, clock, owner, match.id, 3, 2)
    await analysis.recalc_tournament(db, clock, tid)
    upcoming = next(
        m
        for m in await competitions.list_matches(db, tid)
        if m.status == "scheduled" and m.home_team_id
    )

    facts = api.get(f"/api/v1/matches/{match.id}/analysis").json()["facts"]
    comparison = api.get(f"/api/v1/matches/{upcoming.id}/comparison")
    scenarios = api.get(f"/api/v1/tournaments/{tid}/scenarios").json()

    kinds = {f["kind"]: f for f in facts}
    assert kinds["comeback"]["value"] == 2
    assert kinds["late_winner"]["value"] == 38
    assert "table" in kinds
    assert comparison.status_code == 200 and "head_to_head" in comparison.json()
    chances = scenarios[0]["scenario"]["chances"]
    assert 0 <= chances["qualify"] <= 1 and "quarter_final" in chances["reach"]
