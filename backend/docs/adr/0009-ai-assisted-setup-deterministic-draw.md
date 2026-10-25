# ADR 0009 — AI-assisted tournament setup with an engine-computed draw and schedule

- Status: accepted
- Date: 2026-10-24

## Context

Organisers of community tournaments (e.g. a 3-day FinBangla cup) have rules in documents and team lists in spreadsheets or chat messages. Setting up groups, seeding and a schedule by hand is the main barrier to using any platform. The organiser wants "no manual work", and seeding instructions such as "last year's semi-finalists must not meet in the group stage" must be honoured. A draw is also a matter of trust: teams must believe it is fair.

## Decision

- The LLM **reads** documents and produces structured drafts (rules, format, teams, seeding policy, schedule policy), each value with a source quote.
- Where the rules are silent, the LLM may only **choose from a closed, versioned policy catalogue** of internationally used practice (pots by previous placement, separation of previous semi-finalists, standard crossover, simultaneous last group round, rest rules). Each choice is an *assumption* shown to the organiser.
- The **engine** computes the draw (uniform sampling over all assignments satisfying the constraints, from a stored CSPRNG seed) and the schedule (deterministic heuristic over days × pitches × times).
- Uncertainty becomes **open questions** (at most a handful), never guesses. The organiser publishes; nothing is public before that.
- The published draw exposes pots, reasons and the seed for transparency; an optional live draw mode reveals it on screen.

## Alternatives considered

- LLM produces groups and schedule directly: fast to build, but not reproducible, cannot guarantee constraints, and cannot be defended to teams.
- Fully manual setup form: reliable but fails the "no manual work" goal (kept as fallback when the LLM is unavailable).
- Sequential UEFA-style drawing with "skip to next valid group": familiar but known to be biased; uniform sampling avoids it while keeping pots and separations.

## Consequences

- Setup is minutes, not hours; trust comes from reproducibility and visible reasons.
- The catalogue must be maintained and versioned; published tournaments record the catalogue version.
- An extraction evaluation set (fi/en/bn documents) is required to keep quality measurable.
