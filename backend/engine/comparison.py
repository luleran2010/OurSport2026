"""Two teams side by side (docs/04-engine.md, Comparison): form, rates per game, clean
sheets, head-to-head across this tournament and previous editions, rating gap in words."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from engine.model import MatchResult
from engine.ratings import RatingInfo
from engine.sports.football import FootballResult


@dataclass(frozen=True)
class TeamRecord:
    team: str
    played: int
    points_per_game: float
    goals_for_per_game: float
    goals_against_per_game: float
    clean_sheets: int
    form: tuple[str, ...]  # last five, oldest first


@dataclass(frozen=True)
class Meeting:
    match_id: str
    home: str
    away: str
    home_goals: int
    away_goals: int
    winner: str | None


@dataclass(frozen=True)
class Comparison:
    a: TeamRecord
    b: TeamRecord
    head_to_head: tuple[Meeting, ...]  # oldest first
    rating_gap: str


def _record(team: str, results: Sequence[MatchResult], points: Mapping[str, int]) -> TeamRecord:
    games = [r for r in results if team in (r.home, r.away)]
    games.sort(key=lambda r: (r.starts_at, r.match_id))
    pts = gf = ga = clean = 0
    form: list[str] = []
    for r in games:
        o = r.outcome
        assert isinstance(o, FootballResult)
        mine, theirs = (
            (o.home_goals, o.away_goals) if r.home == team else (o.away_goals, o.home_goals)
        )
        gf, ga = gf + mine, ga + theirs
        clean += theirs == 0
        letter = "W" if mine > theirs else "D" if mine == theirs else "L"
        pts += points.get({"W": "win", "D": "draw", "L": "loss"}[letter], 0)
        form.append(letter)
    n = max(len(games), 1)
    return TeamRecord(
        team,
        len(games),
        round(pts / n, 2),
        round(gf / n, 2),
        round(ga / n, 2),
        clean,
        tuple(form[-5:]),
    )


def _gap(a: RatingInfo | None, b: RatingInfo | None) -> str:
    if a is None or b is None or not (a.games or b.games):
        return "no results to compare yet"
    diff = a.rating - b.rating
    if abs(diff) < 50:
        return "evenly matched"
    side = "first" if diff > 0 else "second"
    return f"{'slight' if abs(diff) < 150 else 'clear'} edge for the {side} team"


def compare_teams(
    results: Sequence[MatchResult],
    team_a: str,
    team_b: str,
    *,
    ratings: Mapping[str, RatingInfo] | None = None,
    points: Mapping[str, int] | None = None,
) -> Comparison:
    """`results` may include previous editions (same team ids across years)."""
    table = points or {"win": 3, "draw": 1, "loss": 0}
    meetings = []
    for r in sorted(results, key=lambda r: (r.starts_at, r.match_id)):
        if {r.home, r.away} == {team_a, team_b}:
            o = r.outcome
            assert isinstance(o, FootballResult)
            winner = (
                r.home
                if o.home_goals > o.away_goals
                else r.away
                if o.away_goals > o.home_goals
                else None
            )
            meetings.append(Meeting(r.match_id, r.home, r.away, o.home_goals, o.away_goals, winner))
    ratings = ratings or {}
    return Comparison(
        _record(team_a, results, table),
        _record(team_b, results, table),
        tuple(meetings),
        _gap(ratings.get(team_a), ratings.get(team_b)),
    )
