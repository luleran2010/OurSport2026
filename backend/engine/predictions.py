"""Match predictions with honest uncertainty (docs/04-engine.md, Predictions).

The point estimate comes from the Elo expectation; draws (not in knockouts) take a share
that grows as the teams get closer. Rating uncertainty `350 / sqrt(games + 1)` per team
gives a range at ±0.67 combined standard deviations. With fewer than 3 rated games either
side, confidence is `none` and only the factors (reasons) are shown.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from engine.ratings import RatingInfo, expected

MODEL_VERSION = "elo-1"
DRAW_RATE = 0.26  # share of draws between evenly matched football teams
UNCERTAINTY = 350.0
RANGE_Z = 0.67

type Confidence = Literal["none", "low", "medium", "high"]
type Range = tuple[float, float]
type Side = Literal["home", "away"]
SIDES: tuple[Side, ...] = ("home", "away")


@dataclass(frozen=True)
class Factor:
    id: str
    kind: str  # "seeding", "rating", "form", "position", "head_to_head"
    team: Literal["home", "away"] | None
    text: str


@dataclass(frozen=True)
class MatchContext:
    knockout: bool = False
    home_advantage: float = 0.0  # 0 at a single venue (the usual community cup)
    seeding: dict[str, str] = field(default_factory=dict)  # "home"/"away" -> "2025 runner-up"
    form: dict[str, Sequence[str]] = field(default_factory=dict)  # side -> ("W", "D", "L", …)
    positions: dict[str, str] = field(default_factory=dict)  # side -> "2nd in Group A"


@dataclass(frozen=True)
class Prediction:
    home_win: Range
    draw: Range | None  # None in knockouts (decided on the day)
    away_win: Range
    point: tuple[float, float | None, float]
    confidence: Confidence
    factors: tuple[Factor, ...]
    model_version: str = MODEL_VERSION


def _split(e: float, knockout: bool) -> tuple[float, float | None, float]:
    if knockout:
        return e, None, 1 - e
    closeness = 1 - abs(e - 0.5) * 2
    draw = DRAW_RATE * (0.4 + 0.6 * closeness)
    home = max(e - draw / 2, 0.01)
    away = max(1 - e - draw / 2, 0.01)
    total = home + draw + away
    return home / total, draw / total, away / total


def confidence(home: RatingInfo, away: RatingInfo) -> Confidence:
    games = min(home.games, away.games)
    if games < 3:
        return "none"
    if games < 6:
        return "low"
    if games < 12:
        return "medium"
    return "high"


def _range(values: Sequence[float]) -> Range:
    return (round(min(values), 4), round(max(values), 4))


def _gap_words(diff: float) -> str:
    gap = abs(diff)
    if gap < 50:
        return "evenly matched on form so far"
    side = "home" if diff > 0 else "away"
    strength = "slight" if gap < 150 else "clear"
    return f"{strength} edge for the {side} side on results so far"


def _form_text(results: Sequence[str]) -> str | None:
    recent = list(results)[-3:]
    if not recent:
        return None
    wins = recent.count("W")
    return f"won {wins} of last {len(recent)}"


def predict_match(home: RatingInfo, away: RatingInfo, ctx: MatchContext) -> Prediction:
    """Win/draw/loss chances with ranges, confidence and the reasons behind them."""
    diff = home.rating + ctx.home_advantage - away.rating
    point = _split(expected(home.rating, away.rating, ctx.home_advantage), ctx.knockout)
    sd = math.hypot(
        UNCERTAINTY / math.sqrt(home.games + 1), UNCERTAINTY / math.sqrt(away.games + 1)
    )
    low = _split(
        expected(home.rating - RANGE_Z * sd, away.rating, ctx.home_advantage), ctx.knockout
    )
    high = _split(
        expected(home.rating + RANGE_Z * sd, away.rating, ctx.home_advantage), ctx.knockout
    )
    home_range = _range([low[0], point[0], high[0]])
    away_range = _range([low[2], point[2], high[2]])
    draw_range = None
    if not ctx.knockout:
        draws = [p[1] for p in (low, point, high) if p[1] is not None]
        draw_range = _range(draws)
    factors: list[Factor] = []
    for side in SIDES:
        if side in ctx.seeding:
            factors.append(Factor(f"f{len(factors) + 1}", "seeding", side, ctx.seeding[side]))
    for side in SIDES:
        text = _form_text(ctx.form.get(side, ()))
        if text:
            factors.append(Factor(f"f{len(factors) + 1}", "form", side, text))
        if side in ctx.positions:
            factors.append(Factor(f"f{len(factors) + 1}", "position", side, ctx.positions[side]))
    if home.games or away.games:
        factors.append(Factor(f"f{len(factors) + 1}", "rating", None, _gap_words(diff)))
    return Prediction(
        home_win=home_range,
        draw=draw_range,
        away_win=away_range,
        point=(
            round(point[0], 4),
            None if point[1] is None else round(point[1], 4),
            round(point[2], 4),
        ),
        confidence=confidence(home, away),
        factors=tuple(factors),
    )


def placement_label(placement: int | None, year: int | None) -> str | None:
    """ "2025 runner-up" from a previous placement (1 winner, 2 runner-up, 3-4 semis, …)."""
    if placement is None:
        return None
    if placement == 1:
        words = "winner"
    elif placement == 2:
        words = "runner-up"
    elif placement <= 4:
        words = "semi-finalist"
    elif placement <= 8:
        words = "quarter-finalist"
    else:
        return None
    return f"{year} {words}" if year else f"last edition's {words}"
