"""Fact sheets: only verified facts, and hidden players never appear in any of them."""

import datetime as dt
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.analysis import service as analysis
from app.modules.analysis.facts import fact_payload
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut, PlayerCreate
from app.modules.scoring import service as scoring
from app.modules.scoring.schemas import EventIn

MATCH_DAY = dt.datetime(2026, 6, 12, 7, 0, tzinfo=dt.UTC)
SECRET_NAMES = ("Hidden Keeper", "Family Winger")


async def play_with_named_scorers(
    db: AsyncSession, clock: FrozenClock, cup: dict[str, Any]
) -> MatchOut:
    """A group match where a public, a hidden and a family-only player each score."""
    tid = cup["tournament_id"]
    owner = Viewer(user_id=cup["owner"])
    match = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")
    assert match.home_team_id and match.away_team_id
    home, away = match.home_team_id, match.away_team_id
    scorers = [
        await competitions.create_player(
            db, clock, home, PlayerCreate(display_name="Public Striker")
        ),
        await competitions.create_player(
            db, clock, home, PlayerCreate(display_name=SECRET_NAMES[0], visibility="hidden")
        ),
        await competitions.create_player(
            db, clock, away, PlayerCreate(display_name=SECRET_NAMES[1], visibility="family_only")
        ),
    ]
    await analysis.recalc_tournament(db, clock, tid)
    await scoring.start(db, clock, owner, match.id)
    for n, (player, minute) in enumerate(zip(scorers, (5, 17, 31), strict=True), start=1):
        await scoring.post_event(
            db,
            clock,
            owner,
            match.id,
            EventIn(
                client_seq=n,
                type="goal",
                team_id=player.team_id,
                player_id=player.id,
                clock=f"{minute}:00",
            ),
        )
    await scoring.finish(db, clock, owner, match.id, 2, 1)
    await analysis.recalc_tournament(db, clock, tid)
    return await competitions.get_match(db, match.id)


async def test_hidden_players_never_appear_in_any_fact_sheet(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(MATCH_DAY)
    tid = published_cup["tournament_id"]
    match = await play_with_named_scorers(db, clock, published_cup)
    assert match.home_team_id and match.away_team_id
    upcoming = next(
        m
        for m in await competitions.list_matches(db, tid)
        if m.status == "scheduled" and m.home_team_id == match.home_team_id
    )

    report = await analysis.match_fact_sheet(db, clock, match.id, "report")
    preview = await analysis.match_fact_sheet(db, clock, upcoming.id, "preview")
    sheets = [
        report,
        preview,
        await analysis.team_fact_sheet(db, clock, tid, match.home_team_id),
        await analysis.team_fact_sheet(db, clock, tid, match.away_team_id),
        await analysis.tournament_fact_sheet(db, clock, tid),
    ]

    assert report is not None and preview is not None
    goals = [f.claim for f in report.facts if f.kind == "goal"]
    assert goals[0].startswith("Public Striker scored for")
    assert len(goals) == 3 and not any("Hidden" in g or "Family" in g for g in goals)
    for sheet in sheets:
        assert sheet is not None
        text = sheet.model_dump_json()
        assert not any(name in text for name in SECRET_NAMES)
        assert str(published_cup["owner"]) not in text  # no account ids either
        assert [f.id for f in sheet.facts] == [f"f{n}" for n in range(1, len(sheet.facts) + 1)]


async def test_report_states_the_result_and_the_analysis_with_sources(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(MATCH_DAY)
    match = await play_with_named_scorers(db, clock, published_cup)

    report = await analysis.match_fact_sheet(db, clock, match.id, "report")

    assert report is not None
    kinds = {f.kind: f for f in report.facts}
    assert kinds["result"].value == "2-1"
    assert kinds["goal"].source.startswith(f"match_event:{match.id}:")
    assert kinds["position"].source.startswith("standings_snapshot:v")
    assert report.context.tone_profile == "adult"
    payload = fact_payload(report)
    assert set(payload) == {"facts", "context"}


async def test_same_inputs_give_the_same_sheet_and_new_facts_a_new_one(
    db: AsyncSession, clock: FrozenClock, published_cup: dict[str, Any]
) -> None:
    clock.set(MATCH_DAY)
    tid = published_cup["tournament_id"]
    await analysis.recalc_tournament(db, clock, tid)
    match = next(m for m in await competitions.list_matches(db, tid) if m.stage == "group")

    first = await analysis.match_fact_sheet(db, clock, match.id, "preview")
    again = await analysis.match_fact_sheet(db, clock, match.id, "preview")
    await competitions.update_settings(db, tid, {"show_probabilities": False})
    hidden = await analysis.match_fact_sheet(db, clock, match.id, "preview")

    assert first is not None and again is not None and hidden is not None
    assert again.id == first.id and again.inputs_hash == first.inputs_hash
    assert hidden.inputs_hash != first.inputs_hash
    assert not any(f.kind == "win_chance" for f in hidden.facts)
    assert await analysis.match_fact_sheet(db, clock, match.id, "report") is None  # not played
