# ADR 0012 — Supporters create accounts for personal features

- Status: accepted
- Date: 2026-10-24

## Context

OurSport should feel personal: a supporter's team, notifications, family links and history across tournaments and devices. We also want maximum reach for organisers' tournaments, which arrive through shared links during the event. An anonymous-device design (follows and push without an account) was considered and rejected by the product owner: users will create accounts.

## Decision

- **Public pages need no account:** tournament, live page (per live access policy), standings, bracket, matches, stories, venue screen, widget.
- **Personal features need an account:** follows, primary team, My Team hub, personal feed, notifications, family links, redeem codes, premium.
- Sign-up is one short sheet (email, display name, 13+ confirmation, privacy acknowledgement; language and time zone pre-filled) followed by a magic link. The account exists only after the email is verified.
- The team a visitor picked before signing up (`signup_intents.follow_target`) is followed as primary on verification, so the intent is never lost.
- Login stays passwordless (ADR 0008); passkeys for one-tap return.

## Alternatives considered

- Anonymous device follows with optional account: lowest friction, but weaker identity, data split between devices and accounts, harder export/delete and cross-device experience.

## Consequences

- One identity model for all personal data: simpler privacy handling (export, delete, retention) and cross-device use.
- Sign-up friction at the "This is my team" moment; mitigated by the short sheet and keeping the chosen team through verification.
- Email deliverability becomes critical on tournament days (monitored; resend in UI).
