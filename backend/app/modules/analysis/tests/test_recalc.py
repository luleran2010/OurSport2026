"""Read models: placeholders fill, recalculations coalesce, snapshots rebuild identically."""

import datetime as dt
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.analysis import service
from app.modules.competitions import service as competitions
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn, ResultIn

MATCH_DAY = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)


async def play_group_stage(db: AsyncSession, clock: FrozenClock, cup: dict[str, Any]) -> None:
    owner = Viewer(user_id=cup["owner"])
    matches = await competitions.list_matches(db, cup["tournament_id"])
    strength = {
        e.team_id: -(e.seed or 0) for e in await competitions.entries_of(db, cup["tournament_id"])
    }
    for m in (m for m in matches if m.stage == "group"):
        assert m.home_team_id and m.away_team_id
        home_wins = strength[m.home_team_id] > strength[m.away_team_id]
        result = ResultIn(home_goals=2 if home_wins else 0, away_goals=0 if home_wins else 1)
        await scoring.enter_result(db, clock, owner, m.id, result)  # clear tables, no lots


async def test_finishing_the_group_stage_fills_the_quarter_finals(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(MATCH_DAY)
    tid = published_cup["tournament_id"]
    await play_group_stage(db, clock, published_cup)

    assert await service.recalc_tournament(db, clock, tid)

    matches = {m.code: m for m in await competitions.list_matches(db, tid)}
    tables = {s.group_id: s.rows for s in await service.latest_standings(db, tid)}
    groups = {g.name: g.id for g in await competitions.groups_of(db, tid)}
    a_winner = tables[groups["A"]][0]["team_id"]
    b_second = tables[groups["B"]][1]["team_id"]
    assert str(matches["QF1"].home_team_id) == a_winner
    assert str(matches["QF1"].away_team_id) == b_second
    assert all(matches[c].home_team_id for c in ("QF1", "QF2", "QF3", "QF4"))
    assert matches["SF1"].home_team_id is None


async def test_unchanged_tournament_is_not_recomputed_and_rebuilds_identically(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(MATCH_DAY)
    tid = published_cup["tournament_id"]
    await play_group_stage(db, clock, published_cup)
    await service.recalc_tournament(db, clock, tid)
    before = sorted((str(s.group_id), s.rows) for s in await service.latest_standings(db, tid))

    skipped = await service.recalc_tournament(db, clock, tid)
    rebuilt = await service.recalc_tournament(db, clock, tid, force=True)
    after = sorted((str(s.group_id), s.rows) for s in await service.latest_standings(db, tid))

    assert skipped is False
    assert rebuilt is True
    assert after == before


async def test_twenty_rapid_events_cause_at_most_three_recalculations(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(MATCH_DAY)
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    match = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")
    await scoring.start(db, clock, owner, match.id)
    seqs = []
    for n in range(1, 21):
        team = match.home_team_id if n % 3 else match.away_team_id
        type_ = "goal" if n % 4 == 0 else "yellow_card"
        accepted = await scoring.post_event(
            db, clock, owner, match.id, EventIn(client_seq=n, type=type_, team_id=team)
        )
        seqs.append(accepted.seq)

    runs = [await service.recalc_live(db, clock, match.id, seq) for seq in seqs]

    assert sum(runs) <= 3
    provisional = [
        s
        for s in await service.all_standings(db, tid)
        if s.provisional and s.group_id == match.group_id
    ]
    goals = sum(r["goals_for"] for r in provisional[-1].rows)
    assert goals == 5
