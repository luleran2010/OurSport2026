# ADR 0001 — Modular monolith on FastAPI

- Status: accepted
- Date: 2026-10-24

## Context

Small team, bursty traffic (tournament days), need to move fast and keep operations simple. The domain has clear areas (accounts, competitions, setup, scoring, analysis, content…) but they share one database and one release cycle.

## Decision

One FastAPI codebase, one container image, three process types (api, worker, scheduler). Domain code is split into modules under `app/modules/` with their own tables and a `service.py` (+ `schemas.py`) public interface. Module boundaries are enforced with import-linter.

## Consequences

- One deploy, one database, simple local development and debugging.
- Boundaries keep the code splittable later if a module needs independent scaling.
- Requires discipline: no cross-module table access; CI enforces imports, code review enforces the rest.
- Revisit when a module needs different scaling or release cadence (see `10-operations.md`).
