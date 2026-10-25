"""Backtest the rating model: `uv run python -m engine.tests.backtest` prints the Brier score.

Without imported history yet, matches are simulated from hidden team strengths (seeded,
reproducible); the model only sees results, as it would in a real tournament series.
"""

import math

from engine.predictions import MatchContext, predict_match
from engine.ratings import RatingInfo, update
from engine.rng import DeterministicRng

TEAMS = 24
SEASONS = 4


def _goals(rng: DeterministicRng, rate: float) -> int:
    # Poisson by inversion with a deterministic uniform.
    u, k, p = rng.randbelow(1_000_000) / 1_000_000, 0, math.exp(-rate)
    total = p
    while u > total and k < 10:
        k += 1
        p *= rate / k
        total += p
    return k


def run(seed: bytes = b"backtest") -> tuple[float, float]:
    """(model Brier score, always-uniform Brier score) over simulated round robins."""
    rng = DeterministicRng(seed)
    strength = {f"t{i}": (rng.randbelow(600) - 300) for i in range(TEAMS)}
    ratings = {t: RatingInfo(t, 1500, 0) for t in strength}
    total = baseline = 0.0
    n = 0
    teams = sorted(strength)
    for _ in range(SEASONS):
        for i, home in enumerate(teams):
            for away in teams[i + 1 :]:
                p = predict_match(ratings[home], ratings[away], MatchContext())
                diff = (strength[home] - strength[away]) / 400
                hg = _goals(rng, 1.3 * 10 ** (diff / 2))
                ag = _goals(rng, 1.3 * 10 ** (-diff / 2))
                outcome = (1, 0, 0) if hg > ag else (0, 1, 0) if hg == ag else (0, 0, 1)
                probs = (p.point[0], p.point[1] or 0.0, p.point[2])
                total += sum((pr - o) ** 2 for pr, o in zip(probs, outcome, strict=True))
                baseline += sum((1 / 3 - o) ** 2 for o in outcome)
                n += 1
                ratings[home], ratings[away] = update(ratings[home], ratings[away], hg, ag)
    return total / n, baseline / n


if __name__ == "__main__":
    brier, base = run()
    print(f"Brier score {brier:.4f} (uniform guess {base:.4f})")
