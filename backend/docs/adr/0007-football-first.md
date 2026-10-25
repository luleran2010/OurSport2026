# ADR 0007 — Football first, then ice hockey

- Status: accepted
- Date: 2026-10-24

## Context

The target audience is local, school and community sport — the sports local children and communities play. Football has the most players and teams in Finland and is the sport of our reference customer (a FinBangla community cup); ice hockey is next and has sample Liiga data for testing.

## Decision

- v1 implements only the football sport module (11-a-side and small-sided formats via configuration).
- Ice hockey is the second module; floorball and futsal follow (same goal-based logic); volleyball after; cricket and others on demand.
- The engine stays sport-agnostic (sport module protocol), so later sports add a module without changing standings, scenarios, draw, schedule, ratings or the API.

## Consequences

- Faster, deeper v1 for the biggest audience.
- Seed data, golden tests and examples are football-based.
- Communities playing other sports wait for their module.
