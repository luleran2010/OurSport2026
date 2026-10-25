# ADR 0004 — Pure calculation engine; numbers from code, words from AI

- Status: accepted
- Date: 2026-10-24

## Context

The product's credibility depends on correct standings, scenarios and predictions. LLMs are good at explaining but unreliable at arithmetic and rule application.

## Decision

- All numbers are produced by `engine/`, a pure, deterministic Python library with no I/O and no app imports.
- The LLM writes text only from a fact sheet built from engine output; a deterministic claim checker verifies every number, name and status before publishing.
- LLMs are used for rule, team and seeding *extraction* only as a draft that the organiser publishes; the engine runs the confirmed config (extended by ADR 0009 for draw and schedule).

## Consequences

- The engine can be tested exhaustively (unit, property-based, golden, backtests).
- Content may be less "creative", by design.
- New sports require code (a sport module), not prompting.
