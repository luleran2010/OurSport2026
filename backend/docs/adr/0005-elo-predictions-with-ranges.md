# ADR 0005 — Elo-based predictions shown as ranges with reasons

- Status: accepted
- Date: 2026-10-24

## Context

Users want "what are our chances against a team that won 10 of their last 12". Local and junior football has little data, changing squads and uneven quality; a 3-day cup gives each team only 3–6 matches. False precision would mislead, and blunt numbers can discourage children.

## Decision

- Team strength = Elo rating per sport and age group, with home advantage (0 at single-venue tournaments), goal-difference multiplier, season/edition carry-over, and priors from seeding or OurSport history for one-off tournaments.
- Predictions are probability **ranges** derived from rating uncertainty (based on games played), with a confidence level; below 3 games no percentages are shown.
- Form, streaks, head-to-head and seeding ("last year's runner-up") are always shown as **reasons**; a capped form adjustment is off until a backtest shows it helps.
- Junior tournaments (default U12 and younger) hide percentages; content uses gentle wording.
- Every model change is validated with a backtest (Brier score must not get worse).

## Alternatives considered

- Glicko-2: built-in uncertainty, but harder to explain; may replace the uncertainty heuristic later behind the same interface.
- Machine-learning models: not justified by data volume; hard to explain.

## Consequences

- Explainable, cheap, deterministic predictions.
- On day 1 of a short tournament most predictions show reasons only; this is intended honesty, not a gap.
- Uncertainty heuristic needs calibration as data grows.
