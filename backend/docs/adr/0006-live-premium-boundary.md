# ADR 0006 — What is premium during live matches

- Status: amended by ADR 0011 (the boundary below now applies when a tournament's `live_access = premium`)
- Date: 2026-10-24

## Context

Clubs pay for premium seats; premium must have clear value. Fans without premium still need a reason to follow and share.

## Decision

- Premium (any organisation's seat, or an event pass) unlocks live features for **all** live matches with `live_access = premium`: live score, timeline, commentary, live stakes, embedded stream.
- Non-premium users see that a match is live, but no score until full time. After full time everything (result, timeline, commentary, report, analysis) is public.
- Scorers, staff, admins of the participating organisations and editors always have live access.

## Consequences

- Simple entitlement check (`can_watch_live`).
- If the boundary changes, only `can_watch_live` and the live serializer change.
