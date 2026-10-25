# ADR 0011 — Live access is a per-tournament policy

- Status: accepted (product owner may revise the defaults)
- Date: 2026-10-24

## Context

ADR 0006 made live features premium-only. For community tournaments, the organiser's main motivation is the pride and reach of a livecast tournament ("bragging rights"); hiding the live score from families undermines that and the organiser's willingness to adopt the platform. Other customers (clubs selling seats) still want a premium boundary.

## Decision

- `tournaments.settings.live_access` ∈ `public` | `members` | `premium`.
- Default for community tournaments: `public`. ADR 0006's boundary applies when set to `premium`.
- `can_watch_live` evaluates the policy; staff, scorers, admins of participating organisations and editors always have access.
- Monetisation options (premium seats, event passes, organiser plans) stay possible without changing endpoints.

## Consequences

- Maximum reach for community events; live viewer counts become a selling point for organisers.
- Business model decision (who pays: organiser, clubs or fans) is deferred and configurable.
