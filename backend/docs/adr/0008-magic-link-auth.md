# ADR 0008 — Magic-link login with optional passkeys

- Status: accepted (extended by ADR 0010 for scorers and ADR 0012 for sign-up)
- Date: 2026-10-24

## Context

Members use the app occasionally (around tournaments). Forgotten passwords would block them exactly when a match starts. Many users arrive through a share link on their phone.

## Decision

- Default login: emailed single-use magic link (15 min). Optional passkey registration for one-tap return.
- Long sliding sessions (refresh token 60 days) in httpOnly cookies.
- No passwords stored. Newsroom editors can later use OIDC SSO on the same session model.

## Consequences

- Lower friction, no password storage or reset flows.
- Depends on reliable email delivery (monitored; resend option in UI).
- Shared family devices: sessions can be revoked from account settings.
