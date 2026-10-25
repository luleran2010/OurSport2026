"""Organiser match day with an injectable clock: delays, withdrawals, console, lifecycle."""

import datetime as dt
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.setup import matchday
from app.modules.setup.schemas import ScheduleChangeIn

TEN_AM = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)  # 10:00 in Helsinki, day 1
FIRST_MATCHES = dt.datetime(2026, 6, 12, 6, 10, tzinfo=dt.UTC)  # 09:10: the 09:00 round is on


async def test_a_20_minute_delay_on_pitch_2_moves_only_later_pitch_2_and_dependent_matches(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(FIRST_MATCHES)  # next pitch-2 match at 09:50, right after the running one
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    pitches = {p.id: p.name for p in await competitions.pitches_of(db, tid)}
    before = {m.code: m for m in await competitions.list_matches(db, tid)}
    jobs.deferred.clear()

    preview = await matchday.preview_change(
        db, clock, owner, tid, ScheduleChangeIn(kind="delay", pitch="Pitch 2", minutes=20)
    )

    assert preview.moved, "the next match on pitch 2 must move"
    on_pitch_2 = {c for c, m in before.items() if m.pitch_id and pitches[m.pitch_id] == "Pitch 2"}
    moved_teams: set[Any] = set()
    for moved in preview.moved:
        m = before[moved.code]
        assert m.starts_at >= FIRST_MATCHES, "started matches never move"
        moved_teams |= {m.home_team_id, m.away_team_id}
    for moved in preview.moved:
        m = before[moved.code]
        shares = bool({m.home_team_id, m.away_team_id} & moved_teams - {None})
        assert moved.code in on_pitch_2 or shares or m.stage != "group"

    confirmed = await competitions.list_matches(db, tid)  # nothing changed before confirm
    assert [m.starts_at for m in confirmed] == [before[m.code].starts_at for m in confirmed]
    result = await matchday.confirm_change(db, clock, owner, tid, preview.plan_id)
    after = {m.code: m for m in await competitions.list_matches(db, tid)}

    assert result.moved == len(preview.moved)
    first = preview.moved[0]
    assert after[first.code].starts_at.isoformat().replace("+00:00", "Z") == first.starts_at_after
    notify = [j for j in jobs.deferred if j.name == "notify_followers"]
    assert notify and notify[0].args["kind"] == "schedule_change"
    assert set(notify[0].args["team_ids"].split(",")) == {str(t) for t in preview.affected_team_ids}


async def test_a_withdrawn_team_hands_its_opponents_walkovers(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(TEN_AM - dt.timedelta(days=1))  # before the tournament starts
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    team = (await competitions.entries_of(db, tid))[0].team_id

    preview = await matchday.preview_change(
        db, clock, owner, tid, ScheduleChangeIn(kind="withdrawn", team_id=team)
    )
    await matchday.confirm_change(db, clock, owner, tid, preview.plan_id)
    matches = await competitions.list_matches(db, tid)

    theirs = [m for m in matches if team in (m.home_team_id, m.away_team_id)]
    assert len(preview.walkovers) == 3
    assert {m.status for m in theirs} == {"walkover"}
    for m in theirs:
        assert m.result is not None
        winner_goals = m.result["away_goals"] if m.home_team_id == team else m.result["home_goals"]
        assert winner_goals == 3


async def test_console_shows_late_pitches_and_unscored_matches(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    tid = published_cup["tournament_id"]
    owner = Viewer(user_id=published_cup["owner"])
    clock.set(TEN_AM)

    console = await matchday.console(db, clock, owner, tid)

    assert len(console.pitches) == 4
    assert all(
        p.delay_minutes > 0
        for p in console.pitches
        if p.next and p.next.starts_at < "2026-06-12T07:00:00Z"
    )
    assert console.unscored, "the 09:00 matches ended without a result"


async def test_lifecycle_moves_the_tournament_to_active_on_its_first_day(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(TEN_AM)

    moved = await competitions.lifecycle_transitions(db, clock)

    assert moved["active"] >= 1
    tournament = await competitions.tournament_window(db, published_cup["tournament_id"])
    assert tournament.status == "active"
