# 09 — Security, privacy and access control

Legal background and Finland-specific rules are in `13-compliance-finland.md`; this document is the technical enforcement.

## Authentication

Users open the app rarely, and volunteers score once a year, so nothing may depend on remembering a password.

- **Magic link (default):** `POST /auth/magic-link` emails a single-use link (token stored hashed, 15 min). Always 202.
- **Passkeys (optional):** WebAuthn after first login.
- **Sessions:** access JWT (15 min) + rotating refresh token (60 days sliding) in `httpOnly; Secure; SameSite=Lax` cookies. Refresh reuse revokes the session family.
- **Sign-up:** `POST /auth/signup` collects only email, display name, language, time zone, the 13+ confirmation and privacy acknowledgement; the account is created only when the magic link is opened (verified email). Same 202 response whether or not the email exists. On creation, accounts publishes the in-process event `UserSignedUp(user_id, follow_target)` (`app/core/events.py`, same transaction); audience subscribes to make the chosen team the primary follow (T-040).
- **Implementation:** refresh token = `<session id>.<secret>` (hash stored), cookie path `/api/v1/auth`; CSRF cookie `oursport_csrf` (readable) is echoed in `X-CSRF-Token`; access cookie `oursport_access`. Cookies are `Secure` and domain-scoped outside local/test.
- **Scorer passes:** QR contains a random 128-bit token (stored hashed), scoped to a tournament + pitch or match, valid only for the tournament days, revocable instantly; rate-limited; every event records the pass id.
- **CSRF:** double-submit token header on cookie-authenticated unsafe requests.
- **Rate limits:** magic-link 5/hour/email and 20/hour/IP; uploads 30/hour/tournament; scorer endpoints per pass.

## Authorization

FastAPI dependencies + scoped repositories.

```python
viewer: Viewer = Depends(current_viewer)           # user or anonymous; may carry a scorer pass
Depends(require_member)
Depends(require_global_role("editor"))
Depends(require_organisation_role(organisation_id, "admin"))
Depends(require_tournament_staff(tournament_id, "organiser"))
Depends(require_match_scorer(match_id))             # scorer pass for pitch/match, or staff
Depends(require_live_access(match_id))              # live access policy
```

- `Viewer` = user id (or anonymous), global roles, organisation memberships, tournament staff roles, scorer pass scope, family player ids, premium/event-pass flags. Built once per request (cached in Redis 60 s, invalidated on role/seat/pass change).
- Repositories apply scoping in SQL; no unscoped variants exist.
- Private resources return 404, not 403, to non-authorised viewers (hidden players, draft tournaments).
- A scorer pass grants **nothing** except posting events/results for its scope and reading that scope's match list and visible rosters.

### Live access

`can_watch_live(viewer, match)` evaluates `tournaments.settings.live_access` (`public` / `members` / `premium`; ADR 0011) and always allows staff, scorers, admins of participating organisations and editors.

## Data minimisation in setup

| Rule | Where enforced |
| --- | --- |
| Uploaded documents are redacted before any LLM call (phone, email, Finnish personal identity code, dates of birth, street addresses) | `core.redaction`, plus gateway guard |
| XLSX/CSV parsed deterministically; only needed columns sent to the LLM | `setup.service` |
| Team contact details stored only in `teams.contact_*`, visible to tournament staff only | `competitions.repository` |
| Birth dates in team lists converted to birth year; full dates discarded | `setup.service` |
| Redaction reports store counts, never values | `setup.models` |
| Raw intake files deleted at archive + 1 year | `cleanup` |
| Text inside uploads is data, not instructions (prompt-injection guard) | Extraction prompts + structured output |

## Junior data protection

| Rule | Where enforced |
| --- | --- |
| Players under 18 (by `birth_year`) default to `visibility = hidden` | `competitions.service.create_player` |
| `family_only` requires consent scope `profile` | Service validation |
| `public` for a junior requires consent scopes `profile` + `stats` | Service validation |
| Every player query applies `visibility_filter(viewer)` | `competitions.repository` |
| Hidden players never appear in public responses, fact sheets, stories, commentary, cards, screen or widget | Repository + fact builder + claim checker |
| Live events for hidden players shown as "a {team} player" | Live serializer |
| No percentages where `show_probabilities = false` (default U12 and younger) | `competitions.service.create_tournament` default + API serializer + prompts |
| Streaming a junior match requires the filming check | `media.service.attach_stream` |
| Data minimisation: birth year only, no junior photos by default | Schema |
| Accounts only for 13+ | `accounts.service` (age confirmation at signup) |

`tests/privacy/` creates hidden, family-only and public junior players and asserts, for every public GET endpoint, the venue screen, the widget, every WebSocket message type and every content task, that hidden players never appear.

## GDPR (technical)

- Roles: the hosting organisation is **controller** of participant data it uploads (teams, players, contacts); OurSport is **processor** for that data (processing agreement accepted in `processing_agreements` before the first setup) and **controller** for fan accounts and follows.
- Rights: `POST /me/export`, `DELETE /me` (hard delete; authored content anonymised); organisers can export/delete their tournament's participant data.
- Retention: login tokens 1 day, scorer passes 30 days after tournament end (a pass that recorded events is kept for them but revoked, with an unusable token and the label "Expired pass": events are append-only), notifications 90 days, unverified sign-ups 24 h, audit log 2 years, intake files archive + 1 year, LLM call logs 90 days (no personal data).
- Consent withdrawal: sets `withdrawn_at`, switches player to `hidden`, enqueues regeneration of content that named the player, blocks future streams for the player's matches.

**Implementation (T-060):**
- **Registry:** `app/core/privacy.py`. Each module registers an exporter and an eraser at startup (`app.main.register_privacy`).
- **Export:** `POST /me/export` (`exportMyData`) returns `{user_id, generated_at, data: {module: …}}`.
- **Delete:** `DELETE /me` (`deleteMe`) runs every eraser in one transaction, accounts last.
  - Follows, notifications, push subscriptions, sessions, login tokens, roles, family links and staff roles are deleted.
  - The person's name is taken off stories, edits, corrections, rulebooks and passes.
  - The user row becomes an anonymous tombstone (`deleted-<id>@deleted.invalid`, "Deleted user", `deleted_at`). Append-only match events and setup sessions point at it, so it stays; no personal data does.
  - Processing agreements and consents are kept as records, without the account link.
- **Organisers:**
  - `GET /tournaments/{id}/participants/export` (`exportParticipantData`): teams, contacts, players and consents.
  - `POST /tournaments/{id}/players/{player_id}/erase` (`erasePlayer`): the player row stays for the events but becomes "Removed player", hidden, with no number, birth year, consents or family links.
  - `POST /tournaments/{id}/teams/{team_id}/contact/erase` (`eraseTeamContact`).
- **Retention:** the daily `cleanup` job.
  - Login tokens older than 1 day, expired sign-ups (24 h), sessions revoked 30 days ago or idle past 60 days.
  - Notifications older than 90 days.
  - Scorer passes 30 days after the tournament ends.
  - Intake files 1 year after the tournament ends.
- **Privacy tests:** `tests/privacy/` plants hidden, family-only and public scorers and checks:
  - every public GET path in the OpenAPI contract, with and without `team_id` / `since_seq`, including screen, widget, timeline, stories, commentary and feeds;
  - other members' hub, home, feed and notifications (a family member sees only their own family-only player);
  - the match socket snapshot;
  - every story, commentary line, announcement and fact sheet.

## Platform security

- Secrets via environment / secret manager; separate per environment.
- Uploads: allow-listed MIME types (PDF, DOCX, XLSX, CSV, TXT, PNG, JPG, HEIC), size limits (documents 10 MB, images 5 MB), malware scan, stored in object storage, served via signed URLs.
- Security headers (HSTS, nosniff, Referrer-Policy, `frame-ancestors none` except the widget route, which allows configured embed origins).
- CORS: configured front-end origins only; credentials allowed.
- SQL only through SQLAlchemy.
- `pip-audit` and image scanning in CI.
- Audit log: role/seat changes, setup publish, draws and redraws, schedule changes, rule confirmations, scorer pass creation/revocation, approvals/rejections, unpublish, corrections, consent changes, filming opt-outs, stream attach, exports/deletions.
- Abuse: report button on stories (notice-and-action, see `13-compliance-finland.md`); editors can unpublish.
