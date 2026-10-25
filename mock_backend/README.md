# OurSport – mock backend

FastAPI service with **mock data** (Oulu-area teams and games) in memory that simulates live
play. It serves the **OurSport API v1** — the same contract as the real backend
(`../backend/docs/05-api.md`, `../backend/docs/frontend-handoff/openapi.json`) — so the front end
runs against either one unchanged.

## Run

The project is managed with [uv](https://docs.astral.sh/uv/). `uv sync` creates
the virtual environment in `backend\.venv` (installing Python 3.12 if needed) and
installs the locked dependencies, including the dev group (pytest).

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs. The frontend dev server (`npm run dev`)
proxies `/api`, `/health`, `/mock` and the older portal routes to port 8000 (`API_PROXY=…`
for another port), so start both.

Add a dependency with `uv add <package>` (or `uv add --dev <package>` for tools);
this updates `pyproject.toml` and `uv.lock`, which should both be committed.

## The v1 contract (`app/v1/`)

Every route under `/api/v1` has the backend's path, `operationId`, parameters and schemas
(snake_case, UUID ids, ISO 8601 UTC, problem+json errors). `tests/test_contract.py` checks all of
them against the backend's `openapi.json`; run it after the backend contract changes.

- **Ids** are stable UUIDs derived from the mock's slugs (`app/v1/ids.py`); slugs are accepted too.
- **Sign-in** is a magic link: `POST /api/v1/auth/signup` or `/auth/magic-link`, then open the link
  listed at `GET /mock/outbox` (mock only; the backend emails it, see Mailpit). Development
  shortcut: `POST /api/v1/auth/demo-login {persona: fan|organiser|editor}`. Unsafe requests need the
  `oursport_csrf` cookie value in `X-CSRF-Token`; `POST /api/v1/auth/refresh` rotates the session.
- **Scorers** send `Authorization: Pass <token>`. Demo tokens: `GET /mock/scorer-passes`
  (`demo-pass-<tournament slug>`); the app opens `/score?pass=<token>`. The organiser persona can
  score every event match.
- **Live**: `GET /api/v1/live/token?match_id=` then the WebSocket `/api/v1/live/matches/{id}` with the
  backend's `{type, match_id, seq, server_time, data}` envelope.
- Live access is `public` per tournament (the backend's default); `app.v1.project.LIVE_ACCESS` can
  set `members` or `premium` for one.

## Older mock-only endpoints

The routes below serve the areas not on v1 yet (club portal, publisher wizard, editor desk,
invites, redeem codes). The old fan, sign-in and scorer routes were removed: use v1.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/me/redeem-code` | F10 (members): `{ "code": "OLS-FAMILY-2026" }` grants Premium "via" that club until the end of the season; 400 `invalid_code` otherwise. Demo codes: `OLS-FAMILY-2026`, `KARPAT-U20`, `HOOPS-SEASON`, `TARMO-2026` |
| GET | `/api/invites/{token}` | F13 (anyone with the link): club, offer (`premium_seat` or a `role` such as scorer), who invited, message, `expiresAt`, `status` (`valid` / `expired` / `used` / `accepted_by_you`); 404 `invalid`. Demo links: `/invite/ols-premium-2026`, `/invite/tarmo-scorer-2026`, `/invite/karpat-premium-expired`, `/invite/hoops-premium-used` |
| POST | `/api/invites/{token}/accept` | F13 (members): grants Premium via the club or adds the role (`me.roles`), follows the club; single use, 410 when expired/used |
| GET | `/clubs/{id}/dashboard` | Club portal dashboard (club admins only; 401 / 403 otherwise): KPIs, next matches with assigned scorer, latest club stories |
| GET | `/clubs/{id}/members` | Club members and invites with the Premium seat count (admins). `inviteLink` only in dev mode |
| POST | `/clubs/{id}/invites` | Bulk invite `{rows: [{email, name, role, premium}], dryRun}`. Dry run = preview with row errors; otherwise all or nothing: 409 / 422 `invalid_rows` with every row |
| PATCH | `/clubs/{id}/members/{memberId}` | `{premium?, role?}`. 409 `seat_limit` (no free seat), 409 `self` (your own admin role) |
| POST | `/clubs/{id}/members/{memberId}/resend` | New 14-day invite link for an invited / expired member. 409 `already_active` |
| DELETE | `/clubs/{id}/members/{memberId}` | Remove a member or cancel an invite; frees the seat. 409 `self` |
| GET / POST | `/clubs/{id}/teams` | C3: club teams (name, sport, age group, competitions, squad counts) / add a team. 409 `team_exists` |
| PATCH | `/clubs/{id}/teams/{teamId}` | Edit name, short name, age group, league |
| GET / POST | `/teams/{id}/players` | Roster for club admins (number, birth year, visibility, consent, family links; `allowed` per player) / add a player (under-18s default to hidden) |
| PATCH | `/teams/{id}/players/{playerId}` | Edit a player or its visibility. 409 `consent_required` (with `allowed`), 409 `number_taken` |
| POST / DELETE | `/players/{id}/consent` | Record consent `{givenBy, email, relation: guardian\|player, scope: family\|public, linkFamily}` / withdraw it (profile falls back to hidden) |
| POST / DELETE | `/players/{id}/family[/{linkId}]` | Link / unlink a family member of an under-18 by email (works when they sign up) |
| GET | `/clubs/{id}/matches` | C4: upcoming (live, awaiting result, scheduled) and past matches with scorer, data level, status; the club's scorers |
| PATCH | `/matches/{id}` | Club admins of either team: `{scorerId, dataLevel}`. 409 `finished` / `started` (data level only before kick-off), 422 `not_a_scorer` |
| POST | `/matches/{id}/finish` | Final score `{score: [home, away]}` (club admins and the assigned scorer): a started results-only match, or end a live one. Same score again = 200 (retries); 409 `finished` / `not_started` |
| GET / PATCH | `/clubs/{id}` | C5 club profile (admins): name, short name, `logoUrl`, `color`, `secondaryColor`, town, sports, description, contact email. 409 `sport_in_use` |
| POST | `/clubs/{id}/sponsors` · PATCH / DELETE `/clubs/{id}/sponsors/{sponsorId}` | Sponsors: name, link, logo, `showOn` (`cards`, `club_page`, `reports`) |
| POST | `/uploads` | Image upload (club admins): the file as the body with its `Content-Type` (PNG, JPEG, WebP, GIF; max 2 MB). Kept in memory |
| GET | `/uploads/{id}` | The uploaded image |
| GET | `/clubs/{id}/billing` | C6: plan, seats total / in use, price per seat (cents, VAT 0 %), VAT rate, next invoice date and estimate, payment method summary, invoices |
| POST | `/clubs/{id}/billing/seats` | `{seats, preview}`: change the Premium seat count (preview only prices it). 409 `seats_in_use` / `no_change`, 402 `payment_method_required` |
| POST | `/clubs/{id}/billing/portal` | `{returnPath}` → short-lived URL of the payment provider's hosted page (mock: `/billing-provider/session/{token}`) |
| GET | `/clubs/{id}/billing/invoices/{invoiceId}.pdf` | Invoice PDF (admins) |
| GET | `/corrections?club={id}` | C7: error reports about the club's matches and stories (fans: anonymous; club: with name), status open / fixed / rejected, editor's note. Club admins |
| POST | `/corrections` | Club report `{clubId, matchId, field, message, correctValue}`. 422 not the club's match, 409 `duplicate` |
| PATCH | `/corrections/{id}` | E3 (editors): resolve without editing `{status: fixed\|rejected, note}`; note required to reject (the club sees it); a fixed match correction shows the "Corrected" tag to fans. 409 `resolved` |
| GET | `/matches/{id}?device=` | S2 scorer console (assigned scorer or club admin): match, period, clock, wickets/balls, rosters (names only for public profiles), events, `deviceLastSeq` |
| GET | `/review-queue?scope=mine` | P1: AI texts for the publisher's events with publisher review on, oldest first (the default for publishers) |
| POST | `/review-queue/{id}/claim[?force=true]` | E1: assign an item to me. `next` takes the oldest high-priority item nobody has (404 `empty`). 409 `claimed` if another editor has it |
| GET | `/review-queue/{id}` | E2: one item — `text` (working copy), `annotated` (every sentence with the fact ids it uses and the checker's red flags: number not in the fact sheet, junior player named or aged, unsupported claim, sensitive topic), `check` (passed / flagged / stale), `facts` (the fact sheet), `match`, `ruleVersion`, `history`, `correction` (for error reports), `nav` (previous / next item in queue order) |
| PATCH | `/stories/{id}` | E2: save the editor's edits `{itemId, version, title, summary, body[]}`; the live story changes only on approve. Marks the check stale. 409 `stale_version`, `claimed` |
| POST | `/stories/{id}/check` | E2: re-run the checker on the current text |
| POST | `/stories/{id}/approve` | E2: approve and publish `{itemId, verified, note}`. 409 `check_stale`, `red_flags` (allowed only with `verified` and a 10+ character note, which is logged), `claimed`, `decided`. A correction updates the published story and marks the report fixed |
| POST | `/stories/{id}/reject` | E2: reject `{itemId, reason}` (reason required). A correction is marked rejected |
| POST | `/stories/{id}/regenerate` | E2: send back to the AI writer `{itemId, note}`; the mock writer returns a new version (flagged sentences dropped) to the queue about 8 s later |
| GET | `/stories?status=published\|unpublished\|all&q=&date=24h\|7d\|30d&event=&author=ai\|manual&corrected=yes\|no\|reported&cursor=` | E3 (editors): published stories, newest first, with counts, event options and `correctItemId` (the E2 item "Correct" opens: the open report's `corr-…` item, else `fix-{storyId}`) |
| POST | `/stories/{id}/unpublish` | E3: take a story off OurSport `{reason}` (required, kept). 409 `unpublished` |
| GET | `/corrections?status=open\|fixed\|rejected\|all` | E3 (editors, no `club`): every error report with the story or match it is about and its E2 item |
| POST | `/tournaments` | P2 step 1: create a draft event `{name, sport, startDate, endDate, venues, ageGroup, languages, logoUrl}` (publishers) |
| GET / PATCH | `/tournaments/{id}` | The wizard draft / save changes: basics, `groups`, `teamGroups`, `fixtures` (422 with per-row `problems`), `step` (marks a step done if valid) |
| POST / DELETE | `/tournaments/{id}/teams[/{teamId}]` | Add an existing team `{teamId}` (same sport) or a new one `{name, short}` / remove it |
| POST | `/tournaments/{id}/import` | Fixtures: `{kind: csv, csv}` (date, time, home, away, venue, group) or `{kind: round_robin, firstTime, minutesBetween}`; `dryRun`. All rows or none (422 per-row `problems`) |
| POST | `/tournaments/{id}/rulebook` | The file as the body (PDF / DOCX, `X-Filename`) or JSON `{url}` / `{text}`. 202: starts reading the rules (mock AI, ~6 s) |
| GET | `/tournaments/{id}/rules/status` | `reading` (progress, step) → `done` with the extracted rules (points, match length, tiebreakers, who goes through, `uncertain`) |
| GET | `/tournaments/{id}/rules/summary` | P3: rule cards (plain language, source quote with highlight, edit fields), AI questions, worked examples ranked by the engine (with marks), edge-case tests, blockers, rule versions. `state`: reading / failed / draft / confirmed |
| PATCH | `/tournaments/{id}/rules/draft` | `{values: {"points.win": 3, "tiebreakers": [...]}, answers: {questionId: optionId}, marks: {exampleId: {status, note}}, manual}`; returns the new summary. Marks reset when an example changes |
| POST | `/tournaments/{id}/rules/confirm` | Saves the draft as a new rule version. 409 `not_ready` with `blockers` |
| POST | `/tournaments/{id}/rules/retry` | Read the rulebook again after `failed` |
| GET | `/tournaments/{id}` (published) | P4: `kind: "managed"` — status, counts (played, live, results to enter, live-data games without scorer), groups, teams with standings, every match with status / scorer / data level, the event's scorers and settings. Unpublished events still return the wizard draft |
| PATCH | `/tournaments/{id}` (published) | P4 settings: `languages`, `reviewEnabled`, `visibility` (public / unlisted: not listed / hidden: fans get 404). Other fields: 409 `published` |
| POST | `/tournaments/{id}/matches` | P4: add a fixture `{home, away, startsAt, venue, group}`. 422 teams / time, 409 `clash` |
| PATCH | `/matches/{id}` (publisher) | P4 on their event's matches: `startsAt`, `venue`, `dataLevel` (before kick-off), `scorerId` (an event scorer), `score` (enter the result once started; on a finished match: correct it, fans see a note) |
| DELETE | `/matches/{id}` | P4: remove a fixture that hasn't started (its preview goes too) |
| POST | `/tournaments/{id}/scorer-invites` | P4: invite scorers by email `{emails, name, message}`; `skipped` lists bad / already active ones. The invite turns active when that email signs in (they get the scorer area); 14 days |
| DELETE | `/tournaments/{id}/scorers/{scorerId}` | P4: remove a scorer / cancel an invite (taken off unfinished matches) |
| GET | `/tournaments/{id}/stories?status=&author=ai\|manual&language=&q=` | P5: every story about the event with status draft / scheduled / in_review / published / blocked / unpublished, plus teams, matches, content languages and `canPublish` |
| POST | `/stories` | P5: manual post `{eventId, title, summary, body, imageUrl, teamIds, matchIds, language, publishAt, submit}`. `submit: false` = draft; with publish rights it is published (or scheduled), otherwise it goes to the editor desk as manual news |
| PATCH | `/stories/{id}` (publisher) | P5: change your own post (drafts; posts in review until an editor picks them up; published ones with publish rights). `submit: true` sends a draft |

Timestamps are epoch milliseconds; JSON fields are camelCase. Each browser gets a session cookie (`lp_sid`) that holds its follows and demo sign-in state; sessions live in memory, so they reset when the server restarts.

## Settings (environment variables)

| Variable | Default | |
|---|---|---|
| `OURSPORT_TICK_SECONDS` | `4` | Seconds between simulated live updates |
| `OURSPORT_SIMULATE` | `1` | `0` turns the live simulation off |
| `OURSPORT_DEV_EMAIL` | `1` | `0` stops returning password-reset links to the page (set this in production) |
| `OURSPORT_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed browser origins |

## Tests

```powershell
uv run pytest
```

## Structure

- `pyproject.toml` / `uv.lock` – dependencies (managed by uv)
- `app/models.py` – Pydantic models (the API contract)
- `app/mock_data.py` – seed data; replace with a database
- `app/store.py` – in-memory store and live simulation
- `app/tournaments.py` – events: seed data, standings, qualification scenarios, rules
- `app/match_detail.py` – match page sections, live stakes, timeline insights, previews/reports
- `app/players.py` – player visibility rules and the (mock) season profile
- `app/notifications.py` – shared event log, filtered per member for notifications
- `app/auth.py` – accounts: scrypt password hashes, password-reset tokens
- `app/search.py` – Explore search, filters and "near you" (distance) logic
- `app/main.py` – routes and SSE stream
