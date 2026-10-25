# ADR 0010 — Organiser-run scoring with QR scorer passes

- Status: accepted
- Date: 2026-10-24

## Context

At a community cup, scoring is done by volunteers from the organising team on several pitches at once. They will not create accounts, remember passwords or install anything, and phones get lost or swapped between people.

## Decision

- Each pitch (or match) gets a **scorer pass**: a random token in a printed QR code, scoped to the tournament + pitch/match, valid only on tournament days, revocable instantly.
- A pass allows only posting events/results for its scope; every event records the pass id for audit.
- Organisers with accounts can score any match of their tournament and enter results-only scores from the console.
- Scoring is offline-first with `client_seq` idempotency.

## Consequences

- Zero onboarding for volunteers; scoring is no more work than a paper sheet.
- A leaked QR allows scoring for that pitch until revoked; mitigated by scope, time limits, rate limits, audit and instant revoke from the console.
