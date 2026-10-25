"""Team strength: Elo with priors (docs/04-engine.md, Ratings).

One rating per team, sport and age group. New teams start from a prior (the seeding pot
for one-off tournaments); between editions a rating is pulled back towards 1500. Single-
venue tournaments have no home advantage. Walkovers do not change ratings; a knockout
match decided on penalties counts as a draw.
"""

import math
from dataclasses import dataclass, replace
from typing import Literal

START = 1500.0
HOME_ADVANTAGE = 40.0
K_NEW, K_SETTLED, NEW_GAMES = 40.0, 24.0, 10
MAX_MULTIPLIER = 2.5
SEEDING_PRIOR = {1: 75.0, 2: 25.0, 3: -25.0, 4: -75.0}
CARRY_OVER = {"adult": 0.75, "junior": 0.5}

type PriorSource = Literal["default", "division", "seeding", "history"]


@dataclass(frozen=True)
class RatingInfo:
    team: str
    rating: float
    games: int
    prior_source: PriorSource = "default"


def prior(team: str, *, pot: int | None = None) -> RatingInfo:
    """A first rating: the seeding pot when there is one, else 1500."""
    if pot is not None and pot in SEEDING_PRIOR:
        return RatingInfo(team, START + SEEDING_PRIOR[pot], 0, "seeding")
    if pot is not None and pot > 4:
        return RatingInfo(team, START + SEEDING_PRIOR[4], 0, "seeding")
    return RatingInfo(team, START, 0, "default")


def carry_over(info: RatingInfo, *, junior: bool) -> RatingInfo:
    """Into a new season or edition: part of the distance from 1500 is kept."""
    keep = CARRY_OVER["junior" if junior else "adult"]
    return replace(info, rating=keep * info.rating + (1 - keep) * START, prior_source="history")


def expected(home: float, away: float, home_advantage: float = 0.0) -> float:
    """The home side's expected score (win 1, draw 0.5)."""
    return 1 / (1 + 10 ** (-(home + home_advantage - away) / 400))


def margin_multiplier(margin: int, winner_elo_diff: float) -> float:
    if margin <= 0:
        return 1.0
    value = math.log(1 + margin) * 2.2 / (0.001 * winner_elo_diff + 2.2)
    return min(max(value, 0.0), MAX_MULTIPLIER)


def _k(info: RatingInfo) -> float:
    return K_NEW if info.games < NEW_GAMES else K_SETTLED


def update(
    home: RatingInfo,
    away: RatingInfo,
    home_goals: int,
    away_goals: int,
    *,
    penalties: bool = False,
    home_advantage: float = 0.0,
) -> tuple[RatingInfo, RatingInfo]:
    """Ratings after one match. A shootout result counts as a draw."""
    if penalties or home_goals == away_goals:
        score, margin = 0.5, 0
    else:
        score, margin = (
            (1.0, home_goals - away_goals)
            if home_goals > away_goals
            else (0.0, away_goals - home_goals)
        )
    e = expected(home.rating, away.rating, home_advantage)
    winner_diff = (home.rating - away.rating) if score == 1.0 else (away.rating - home.rating)
    m = margin_multiplier(margin, winner_diff) if margin else 1.0
    delta_home = _k(home) * m * (score - e)
    delta_away = _k(away) * m * ((1 - score) - (1 - e))
    return (
        replace(home, rating=home.rating + delta_home, games=home.games + 1),
        replace(away, rating=away.rating + delta_away, games=away.games + 1),
    )
