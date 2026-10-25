# ADR 0003 — Append-only match events and compute-on-write read models

- Status: accepted
- Date: 2026-10-24

## Context

Fans need fast, consistent pages during traffic peaks. Scorers make mistakes; results get corrected. Calculations (scenarios, simulations, bracket resolution) can take seconds.

## Decision

- `match_events` is append-only; undo and corrections are new events.
- Every change triggers background recalculation that writes versioned read-model snapshots (standings, scenarios, bracket, relevance, journeys, ratings, predictions, comparisons, analyses).
- Fan endpoints read only snapshots and never call the engine or the LLM.

## Consequences

- Flat, fast read latency regardless of rule complexity; easy HTTP caching via versions/ETags.
- Full audit trail; any read model can be rebuilt from events (`scripts/rebuild`).
- Slight delay (seconds) between a result and updated scenarios; acceptable and shown via `computed_at`.
- More tables and jobs to maintain; coalescing is required to avoid redundant recalculations.
