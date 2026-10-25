# OurSport backend → front-end gap analysis kit

**Who reads this:** the front-end developer and their Claude Code session, on another machine.
**Goal:** compare the front end with the backend API that exists **today** (2026-10-24) and list every difference and mismatch.

This folder contains:

| File | What it is |
| --- | --- |
| `README.md` (this file) | Features, every endpoint, auth, errors, live sockets, what is not built yet, and how to report gaps |
| `openapi.json` | The exact OpenAPI 3.1 contract generated from the running code: 122 paths, 136 operations, 172 schemas (regenerated after T-066). **This file is the source of truth for field names and types.** |

The live backend also serves the same contract at `GET /api/v1/openapi.json` and interactive docs at `/docs`. The two match.

> **Update (T-066, after the first gap report).** The gaps the report found are now closed for the fan pages,
> sign-in, follows, notifications and the scorer area: the front end (`frontend/src/api/client.js` + `adapt.js`) calls
> this contract, and `mock_backend/` serves the same contract (`mock_backend/tests/test_contract.py` checks every mock
> operation against this `openapi.json`). New and changed operations are listed in `docs/05-api.md` and in the
> "Resolution" section of `gap_analysis/GAP-REPORT.md`. Sections 3 and 7 below describe the API before T-066; where they
> disagree with `openapi.json`, `openapi.json` wins. Still on the mock-only routes (next version, T-070 and the
> organisation portal): the club portal, the publisher wizard and the editor desk.

---

## 1. Instructions for the Claude Code session on the front-end machine

Copy this folder into the front-end repository, for example to `docs/backend-contract/`, then run the prompt below.

> Read `docs/backend-contract/README.md` and `docs/backend-contract/openapi.json`. Then search this front-end codebase for every call to the backend API: fetch/axios/generated-client calls, WebSocket connections, cookie and header handling, and the TypeScript types for request and response bodies.
> For each one, compare the method, the path, path and query parameters, the request body fields, the response fields and their types, nullability, enums, status codes and error handling against `openapi.json`.
> Also check the screens and features the front end has against section 2 (features) and section 7 (not built yet).
> Write `docs/backend-contract/GAP-REPORT.md` in the format of section 8. Do not change any code; report only.

Rules for the comparison:

- Field names are **snake_case**. IDs are UUID strings. Timestamps are ISO 8601 UTC with `Z`. The front end renders them in the viewer's time zone.
- If the front end uses a generated client, regenerate it from `openapi.json` and diff it against the committed client. That is the fastest way to catch field-level mismatches.
- Treat `operationId` as the stable name of each endpoint. A generated client uses it for method names.

---

## 2. Features the backend supports today

Status: ✅ built and tested · 🟡 partly built (see note) · ⛔ not built yet (section 7)

| # | Feature | Status | Endpoints (operationId) |
| --- | --- | --- | --- |
| F1 | Sign up and sign in with a magic link (email); session cookies, refresh, logout, logout on all devices | ✅ | `signUp`, `requestMagicLink`, `verifyMagicLink`, `refreshSession`, `logout`, `logoutAll` |
| F2 | My profile: language (fi/en/bn), time zone, roles, staff tournaments, family links, unread count | ✅ | `getMe`, `updateMe` |
| F3 | Create an organisation; organisation and series pages | ✅ | `createOrganisation`, `getOrganisation`, `getSeries` |
| F4 | **Automatic tournament setup:** upload the rulebook and team list (file, URL or pasted text), AI extraction to a draft, open questions, assumptions, editing the draft | ✅ (extraction runs on the fake AI provider in development) | `startSetup`, `addSetupFile`, `extractSetup`, `getSetup`, `answerSetupQuestions`, `changeSetupDraft` |
| F5 | Draw groups (seeded, with reasons), generate the schedule across pitches and days, move one match, redraw, publish | ✅ | `redrawSetup`, `regenerateSchedule`, `moveSetupMatch`, `publishSetup`, `getPublishedDraw` |
| F6 | Plain-language rules summary in fi/en/bn | ✅ | `getRulesSummary` (`?lang=`) |
| F7 | **Match-day console** for organisers: pitches now and next, delays, unscored matches, live viewers | ✅ | `getConsole` |
| F8 | Rescheduling: delay, pitch closed, match postponed, team withdrawn → preview → confirm; announcements | ✅ | `previewScheduleChange`, `confirmScheduleChange`, `sendAnnouncement` |
| F9 | **Scorer passes (QR):** create, list, revoke; scorers use `Authorization: Pass <token>` with no account | ✅ | `createScorerPass`, `listScorerPasses`, `revokeScorerPass` |
| F10 | **Live scoring:** my matches, event pad definition, start, post event (idempotent by `client_seq`), undo, finish, or results-only entry | ✅ | `getScorerMatches`, `getEventTypes`, `startMatch`, `postMatchEvent`, `undoMatchEvent`, `finishMatch`, `enterResult` |
| F11 | **Fan pages:** tournament, livecast (all live matches), standings, bracket with `could_be`, schedule filters, scenarios ("what does our team need"), venue screen, embeddable widget | ✅ | `getTournament`, `getLive`, `getStandings`, `getBracket`, `getSchedule`, `getScenarios`, `getScreen`, `getWidget` |
| F12 | Match page, event timeline, team page | ✅ | `getMatch`, `getTimeline`, `getTeam` |
| F13 | **Predictions with reasons** (ranges + confidence, no betting language), team comparison, post-match analysis | ✅ | `getPrediction`, `getComparison`, `getMatchAnalysis` |
| F14 | **Live updates over WebSocket** for one match or a whole tournament | ✅ (no `commentary` messages yet) | `getLiveToken` + the sockets in section 5 |
| F15 | **My Team hub:** home, hub for any followed team, personal feed, tournament feed | ✅ (feed has no AI stories yet) | `getMyHome`, `getTeamHub`, `getMyFeed`, `getTournamentFeed` |
| F16 | Follows and notification preferences | ✅ | `listFollows`, `follow`, `unfollow`, `setFollowNotifications` |
| F17 | Notifications (in-app list, mark as read) and web push subscription | ✅ (no weekly email digest) | `listNotifications`, `markNotificationsRead`, `addPushSubscription` |
| F18 | Admin: failed background jobs, retry | ✅ | `listFailedJobs`, `retryJob` |
| F19 | Health checks | ✅ | `get_health_live`, `get_health_ready` |
| F20 | AI stories, match recaps, live commentary, editor review queue | ⛔ next phase (T-050 to T-054) | see section 7 |
| F21 | GDPR export/delete, consents, filming check, streams, share cards, billing | ⛔ later phases | see section 7 |

---

## 3. Every endpoint that exists today

All paths start with `/api/v1` except the health checks. **Auth** column: `public` = no login needed (the live access policy can still restrict live data) · `member` = signed-in user cookie · `organiser` = tournament staff or organisation admin · `pass` = scorer pass or staff · `admin` = global admin. Request and response schema names refer to `components.schemas` in `openapi.json`.

### Auth and profile

| Method | Path | operationId | Auth | Request | Success → response |
| --- | --- | --- | --- | --- | --- |
| POST | `/auth/signup` | `signUp` | public | `SignupRequest` | 202 `Accepted` (always, even for an existing email) |
| POST | `/auth/magic-link` | `requestMagicLink` | public | `MagicLinkRequest` | 202 `Accepted` (always) |
| POST | `/auth/magic-link/verify` | `verifyMagicLink` | public | `VerifyRequest` | 200 `SessionInfo` + sets cookies |
| POST | `/auth/refresh` | `refreshSession` | refresh cookie | — | 200 `SessionInfo` + new cookies |
| POST | `/auth/logout` | `logout` | member | — | 204 |
| POST | `/auth/logout-all` | `logoutAll` | member | — | 204 |
| GET | `/me` | `getMe` | member | — | 200 `Me` |
| PATCH | `/me` | `updateMe` | member | `MePatch` | 200 `Me` |

### Organisations and rules

| Method | Path | operationId | Auth | Request | Success → response |
| --- | --- | --- | --- | --- | --- |
| POST | `/organisations` | `createOrganisation` | member | `OrganisationCreate` | 201 `OrganisationOut` |
| GET | `/organisations/{organisation_id}` | `getOrganisation` | public | — | 200 `OrganisationPage` |
| GET | `/series/{series_id}` | `getSeries` | public | — | 200 `SeriesPage` |
| GET | `/tournaments/{tournament_id}/rules/summary` | `getRulesSummary` | public | `?lang=fi\|en\|bn` | 200 `RulesSummary` |

### Organiser: automatic setup

| Method | Path | operationId | Auth | Request | Success → response |
| --- | --- | --- | --- | --- | --- |
| POST | `/setup` | `startSetup` | organiser | `SetupStart` | 201 `SetupOut` |
| POST | `/setup/{session_id}/files` | `addSetupFile` | organiser | multipart `Body_addSetupFile` | 201 `IntakeFileOut` |
| POST | `/setup/{session_id}/extract` | `extractSetup` | organiser | — | 202 `SetupOut` (poll `getSetup`) |
| GET | `/setup/{session_id}` | `getSetup` | organiser | — | 200 `SetupOut` |
| POST | `/setup/{session_id}/answers` | `answerSetupQuestions` | organiser | `AnswersRequest` | 200 `SetupOut` |
| PATCH | `/setup/{session_id}/draft` | `changeSetupDraft` | organiser | `DraftChange` | 200 `SetupOut` |
| POST | `/setup/{session_id}/draw` | `redrawSetup` | organiser | — | 200 `SetupOut` |
| POST | `/setup/{session_id}/schedule` | `regenerateSchedule` | organiser | `RegenerateSchedule` | 200 `SetupOut` |
| PATCH | `/setup/{session_id}/schedule/matches/{code}` | `moveSetupMatch` | organiser | `MoveMatch` | 200 `SetupOut` |
| POST | `/setup/{session_id}/publish` | `publishSetup` | organiser | — | 200 `Published` (409 `open_questions_remaining` / `setup_not_ready`) |
| GET | `/tournaments/{tournament_id}/draw` | `getPublishedDraw` | public | — | 200 `DrawOut` |

### Organiser: match day

| Method | Path | operationId | Auth | Request | Success → response |
| --- | --- | --- | --- | --- | --- |
| GET | `/tournaments/{tournament_id}/console` | `getConsole` | organiser | — | 200 `ConsoleOut` |
| POST | `/tournaments/{tournament_id}/schedule/changes` | `previewScheduleChange` | organiser | `ScheduleChangeIn` (delay, pitch closed, postponed, withdrawn) | 200 `ChangePreview` |
| POST | `/tournaments/{tournament_id}/schedule/{plan_id}/confirm` | `confirmScheduleChange` | organiser | — | 200 `ChangeConfirmed` |
| POST | `/tournaments/{tournament_id}/announcements` | `sendAnnouncement` | organiser | `AnnouncementIn` | 204 |
| GET | `/tournaments/{tournament_id}/scorer-passes` | `listScorerPasses` | organiser | — | 200 `PassOut[]` |
| POST | `/tournaments/{tournament_id}/scorer-passes` | `createScorerPass` | organiser | `PassCreate` | 201 `PassOut` (token shown once, for the QR) |
| POST | `/tournaments/{tournament_id}/scorer-passes/{pass_id}/revoke` | `revokeScorerPass` | organiser | — | 204 |

### Scoring

| Method | Path | operationId | Auth | Request | Success → response |
| --- | --- | --- | --- | --- | --- |
| GET | `/scoring/me` | `getScorerMatches` | pass | — | 200 `ScorerMatch[]` |
| GET | `/sports/{code}/event-types` | `getEventTypes` | public | — | 200 array (event pad definition) |
| POST | `/matches/{match_id}/start` | `startMatch` | pass | — | 200 `MatchStatus` |
| POST | `/matches/{match_id}/events` | `postMatchEvent` | pass | `EventIn` (`client_seq` makes it idempotent) | 201 `EventAccepted`; a duplicate `client_seq` returns the original |
| POST | `/matches/{match_id}/events/{seq}/undo` | `undoMatchEvent` | pass | `UndoIn` | 201 `EventAccepted` (undo is a new event) |
| POST | `/matches/{match_id}/finish` | `finishMatch` | pass | `FinishIn` | 200 `MatchStatus` |
| POST | `/matches/{match_id}/result` | `enterResult` | pass | `ResultIn` (results-only, no live events) | 200 `MatchStatus` |

### Fan: browse (public unless the tournament's live access policy restricts live data)

| Method | Path | operationId | Query | Success → response |
| --- | --- | --- | --- | --- |
| GET | `/tournaments/{tournament_id}` | `getTournament` | — | 200 `TournamentPage` |
| GET | `/tournaments/{tournament_id}/live` | `getLive` | — | 200 `LivePage` |
| GET | `/tournaments/{tournament_id}/standings` | `getStandings` | — | 200 `StandingsPage` |
| GET | `/tournaments/{tournament_id}/bracket` | `getBracket` | — | 200 `BracketPage` |
| GET | `/tournaments/{tournament_id}/schedule` | `getSchedule` | `day`, `pitch_id`, `team_id` | 200 `SchedulePage` |
| GET | `/tournaments/{tournament_id}/scenarios` | `getScenarios` | `team_id` | 200 `ScenarioPage` (shares are hidden when the organiser turns probabilities off) |
| GET | `/tournaments/{tournament_id}/screen` | `getScreen` | — | 200 `ScreenPage` (venue big screen) |
| GET | `/tournaments/{tournament_id}/widget` | `getWidget` | — | 200 `WidgetPage` (embeddable) |
| GET | `/tournaments/{tournament_id}/feed` | `getTournamentFeed` | `cursor`, `limit` | 200 `Feed` |
| GET | `/matches/{match_id}` | `getMatch` | — | 200 `MatchPage` |
| GET | `/matches/{match_id}/timeline` | `getTimeline` | `since_seq` | 200 `TimelinePage` |
| GET | `/matches/{match_id}/prediction` | `getPrediction` | — | 200 `MatchPrediction` (percentages `null` when hidden) |
| GET | `/matches/{match_id}/comparison` | `getComparison` | — | 200 `ComparisonPage` |
| GET | `/matches/{match_id}/analysis` | `getMatchAnalysis` | — | 200 `AnalysisPage` |
| GET | `/teams/{team_id}` | `getTeam` | — | 200 `TeamPage` |
| GET | `/live/token` | `getLiveToken` | exactly one of `match_id`, `tournament_id` | 200 `LiveToken` (valid 60 s) |

### Fan: personal (member)

| Method | Path | operationId | Request / query | Success → response |
| --- | --- | --- | --- | --- |
| GET | `/me/home` | `getMyHome` | — | 200 `Home` (My Team hub of the primary team) |
| GET | `/me/teams/{team_id}/hub` | `getTeamHub` | `tournament_id` | 200 `TeamHub` |
| GET | `/me/feed` | `getMyFeed` | `cursor`, `limit` | 200 `Feed` |
| GET | `/me/follows` | `listFollows` | — | 200 `FollowOut[]` |
| POST | `/me/follows` | `follow` | `FollowIn` | 201 `FollowOut` |
| DELETE | `/me/follows/{follow_id}` | `unfollow` | — | 204 |
| PATCH | `/me/follows/{follow_id}/notifications` | `setFollowNotifications` | `NotifyPatch` | 200 `FollowOut` |
| GET | `/me/notifications` | `listNotifications` | — | 200 `NotificationOut[]` |
| POST | `/me/notifications/read` | `markNotificationsRead` | `MarkRead` | 204 |
| POST | `/me/push-subscriptions` | `addPushSubscription` | `PushSubscriptionIn` | 204 |

### Admin and health

| Method | Path | operationId | Auth | Success → response |
| --- | --- | --- | --- | --- |
| GET | `/admin/jobs/failed` | `listFailedJobs` | admin | 200 `FailedJob[]` |
| POST | `/admin/jobs/{job_id}/retry` | `retryJob` | admin | 204 |
| GET | `/health/live` (no `/api/v1`) | `get_health_live` | public | 200 `LiveStatus` |
| GET | `/health/ready` (no `/api/v1`) | `get_health_ready` | public | 200 `ReadyStatus` |

---

## 4. Auth, cookies, CSRF and caching (check these carefully, they cause most bugs)

| Topic | How the backend works |
| --- | --- |
| Sign-in flow | `signUp` or `requestMagicLink` → the user gets an email link → the front end takes the token from the link and calls `verifyMagicLink` → cookies are set. In development the emails go to Mailpit at `http://localhost:8025`. |
| Access cookie | `oursport_access`: an httpOnly JWT, 15 minutes, `SameSite=Lax` |
| Refresh cookie | `oursport_refresh`: httpOnly, **path `/api/v1/auth`** only. Rotated on each `refreshSession`; reusing an old one revokes the session. On a 401 `not_authenticated`, call `refreshSession` once, then retry. |
| CSRF | `oursport_csrf` cookie, readable by JavaScript. For every **unsafe request (POST/PATCH/DELETE) made with cookies**, send its value in the header **`X-CSRF-Token`**. A missing or wrong value returns 403. |
| Credentials | Requests must include cookies: `fetch(..., { credentials: "include" })` or axios `withCredentials: true`. The front-end origin must be listed in the backend's `CORS_ORIGINS`. |
| Scorer pass | Scorers have no account. The QR code holds the pass token; send `Authorization: Pass <token>`. No CSRF needed. |
| Caching | Fan reads return an `ETag`. Send `If-None-Match` to get `304 Not Modified`. Live pages use `max-age=5`; personal data uses `private, no-store`. |
| Language | `?lang=fi\|en\|bn` on the rules summary; the user's language is in `Me.language`. |
| Pagination | Feeds use `?cursor=&limit=` (default 20, max 100) and return `{ items: [...], next_cursor: string \| null }`. |

### Error format (every error)

RFC 9457 problem details, `Content-Type: application/problem+json`:

```json
{ "type": "/problems/validation_error", "title": "…", "status": 422, "detail": "…",
  "code": "validation_error", "errors": [ { "field": "email", "message": "…" } ] }
```

The front end should branch on **`code`**, not on `title` or `detail`. Codes in use: `not_authenticated` (401), `forbidden` (403), `not_found` (404), `validation_error` (422), `conflict` (409), `stale_version` (409), `rules_not_confirmed`, `setup_not_ready`, `open_questions_remaining`, `draw_infeasible`, `schedule_infeasible`, `match_not_live`, `scorer_not_assigned`, `pass_revoked`, `rate_limited` (429 + `Retry-After`), `upstream_unavailable` (503).

---

## 5. Live WebSocket protocol

1. Call `GET /api/v1/live/token?match_id=…` (or `?tournament_id=…`). Signed-out viewers get a token for public tournaments. Otherwise you get 401 or 403.
2. Connect within 60 seconds:
   - one match: `ws(s)://<host>/api/v1/live/matches/{match_id}?token=…&since_seq=<last seq you have>`
   - whole tournament: `ws(s)://<host>/api/v1/live/tournaments/{tournament_id}?token=…`
3. A bad or expired token closes the socket with code **4401**. Get a new token and reconnect, passing your last `seq` as `since_seq`.

Every message uses the same envelope:

```json
{ "type": "event", "match_id": "uuid|null", "seq": 12, "server_time": "2026-06-12T10:15:03Z", "data": { } }
```

| `type` | Socket | `data` |
| --- | --- | --- |
| `snapshot` | match | `{ score, timeline }`: the current score and every event after `since_seq`. Always the first message. |
| `snapshot` | tournament | `{ tournament_id }` |
| `event` | match + tournament | The new event and the updated `score` |
| `correction` | match + tournament | An undo: the new score plus `undone_seq` |
| `match_finished` | match + tournament | `{ result }`. The match socket closes after this message. |
| `schedule` | tournament | `{ matches: [{code, starts_at, pitch}], walkovers }` after a confirmed reschedule |
| `announcement` | tournament | `{ text }` |
| `ping` | both | `{}` when the socket is quiet (keep-alive) |

Each `seq` is sent once and in order. Ignore any message whose `seq` is ≤ the last one you have.
**Not sent yet:** `commentary` (T-053), `state` (clock and period updates), `match_started`. To catch a match starting, re-fetch `getLive` or `getMatch`.

---

## 6. Rules the UI must follow (product and legal)

- **AI text must be labelled.** Every AI-written story or commentary item will carry `author_type: "ai"` and an `ai_label`; show the label. (No AI text is served yet; this applies once F20 lands.)
- **No betting.** Never show odds or betting wording. Predictions are chances with ranges and reasons. When `show_percentages` is false the numbers are `null`; show only the reasons.
- **Junior players.** The API never returns hidden players. Don't assume every player has a name or a photo.
- **Times** come in UTC with `Z`; show them in the viewer's time zone, since many relatives watch from abroad.
- **Languages:** fi, en and bn. Bengali needs a font that renders it.

---

## 7. Planned in the API docs but NOT built yet

If the front end already calls any of these, report it as **"front end ahead of backend"**, not as a bug.

| Area | Endpoints | Planned task |
| --- | --- | --- |
| Passkeys | `/auth/passkeys/register/*`, `/auth/passkeys/login/*` | not scheduled |
| GDPR | `POST /me/export`, `DELETE /me` | T-060 |
| Setup extras | `POST /setup/{id}/teams/merge`, `GET /setup/{id}/pitch-sheets.pdf`, `GET /setup/{id}/filming-notice.pdf`; live draw-reveal mode `{live:true}` on `/setup/{id}/draw` | T-061, T-062 |
| Match-day extras | `GET /tournaments/{id}/announcements` (list of drafts), `PATCH /tournaments/{id}` (settings), `POST /tournaments/{id}/staff`, `POST /tournaments/{id}/bracket/resolve-lots`, `POST /tournaments/{id}/schedule/delay` (use `previewScheduleChange` with a delay instead) | follow-up |
| Scorer pass revoke | the docs say `DELETE /scorer-passes/{id}`; **built as `POST /tournaments/{id}/scorer-passes/{pass_id}/revoke`** | built differently |
| Browse extras | `GET /search`, `/organisations/{id}/teams` · `/stories` · `/matches`, `/teams/{id}/matches`, `/tournaments/{id}/stories`, `/matches/{id}/stories`, `/stories/{id}`, `/players/{id}`, `/cards/{id}.png`, `/feed/public` | T-052, T-063, follow-up |
| Personal extras | `POST /me/redeem-code`, `GET /invites/{token}`, `POST /invites/{token}/accept` | T-070 |
| Organisation portal | `/organisations/{id}/dashboard`, `/members`, `/invites`, `/teams`, `/teams/{id}/players`, consents, family links, billing, corrections | T-060, T-061, T-070 |
| Media | `POST /matches/{id}/stream`, `POST /tournaments/{id}/filming-optouts` | T-062 |
| Editor | `/review-queue…`, `PATCH /stories/{id}`, `/stories/{id}/check` · `/approve` · `/reject` · `/regenerate` · `/unpublish` | T-054 |
| Live | WebSocket `commentary` and `state` messages | T-053 |
| Sports | only football today; ice hockey, floorball, futsal later | T-071, T-072 |

---

## 8. Gap report format (`GAP-REPORT.md`)

```markdown
# Front end ↔ OurSport API gap report
Front-end commit: <hash> · Contract date: 2026-10-24

## Summary
<counts per category, plus the 5 most important problems>

## A. Mismatches (both sides exist but disagree) — fix first
| # | Front-end file:line | Endpoint (operationId) | What differs | Backend says | Front end does | Severity | Suggested fix side |

## B. Front end calls an endpoint the backend does not have
| # | File:line | Method + path | In section 7? (planned / unknown) | Suggestion |

## C. Backend endpoint with no front-end use (missing screen or feature)
| # | operationId | Feature (F#) | Needed for the demo? |

## D. Auth / CSRF / cookies / CORS / WebSocket issues
| # | File:line | Problem | Fix |

## E. Product-rule issues (AI label, betting words, time zones, languages, junior data)
| # | File:line | Problem |

## F. Questions for the backend
- …
```

**Severity:** `blocker` (breaks a screen or the demo) · `major` (wrong data or a broken edge case) · `minor` (naming, unused fields).
**Suggested fix side:** `frontend` / `backend` / `discuss`. Changes to public field names need agreement from both sides.

When the report is done, send `GAP-REPORT.md` back to the backend developer.
