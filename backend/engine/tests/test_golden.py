"""Golden tests: the engine must reproduce official final tables (engine/tests/golden/*.json).

Each file holds real results with team names replaced, the tiebreaker preset of that
competition, and the official table. Add community and junior tables here as they arrive.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from engine.model import MatchResult, TeamRef, TournamentState
from engine.rules.config import Tiebreaker
from engine.rules.format import FormatSpec
from engine.rules.presets import TIEBREAKER_PRESETS
from engine.sports.football import Cards, FootballResult
from engine.standings import compute_standings
from engine.tests.conftest import make_rules

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("*.json"))


def _result(index: int, raw: dict[str, Any]) -> MatchResult:
    home_goals, away_goals = raw["score"]
    return MatchResult(
        match_id=f"g{index}",
        group_id="G",
        home=raw["home"],
        away=raw["away"],
        outcome=FootballResult(
            home_goals,
            away_goals,
            home_cards=Cards(yellow=raw.get("home_yellow", 0), red=raw.get("home_red", 0)),
            away_cards=Cards(yellow=raw.get("away_yellow", 0), red=raw.get("away_red", 0)),
        ),
        starts_at=raw["at"],
    )


def test_there_are_golden_tables() -> None:
    assert len(GOLDEN_FILES) >= 2


@pytest.mark.parametrize("path", GOLDEN_FILES, ids=lambda p: p.stem)
def test_engine_reproduces_the_official_table(path: Path) -> None:
    golden = json.loads(path.read_text())
    results = [_result(i, raw) for i, raw in enumerate(golden["results"])]
    teams = sorted({t for r in results for t in (r.home, r.away)})
    state = TournamentState(
        teams=tuple(TeamRef(t, t) for t in teams),
        groups={"G": tuple(teams)},
        results=tuple(results),
        fixtures=(),
        rules=make_rules(
            format="round_robin", tiebreakers=list(TIEBREAKER_PRESETS[golden["tiebreakers"]])
        ),
        format=FormatSpec(team_count=len(teams), group_sizes=[len(teams)]),
    )

    rows = compute_standings(state).groups[0].rows

    actual = [
        {
            "team": row.team,
            "position": row.position,
            "points": row.stats.points,
            "goals_for": row.stats.score_for,
            "goals_against": row.stats.score_against,
        }
        for row in rows
    ]
    expected = [
        {key: value for key, value in entry.items() if key != "decided_by"}
        for entry in golden["expected"]
    ]
    assert actual == expected, golden["why"]
    assert not any(row.tied_unresolved for row in rows)
    for entry, row in zip(golden["expected"], rows, strict=True):
        if "decided_by" in entry:
            assert row.decided_by is Tiebreaker(entry["decided_by"])
