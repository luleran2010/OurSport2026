# 11 — Build plan (task list for agentic development)

Work top to bottom, one task at a time. Each task lists the docs to read, the scope and acceptance criteria. Tick the box in the same commit that completes the task. **Football is the only sport until Phase 7.**

The plan is ordered around the core promise: **upload rules + teams → automatic tournament → organiser scores → everyone follows live and personally.** Phases 0–4 together are the first shippable product (a FinBangla-style 3-day cup end to end).

Conventions for every task: tests included, `ruff` + `mypy` + `lint-imports` + `pytest` green, docs updated if behaviour changed.

---

## Phase 0 — Foundation

- [x] **T-001 Repository scaffold** · docs: 02, 10
  - Scope: `pyproject.toml` (uv), folder layout from `02-architecture.md`, `Dockerfile`, `docker-compose.yml` (Postgres 16, Redis 7, SeaweedFS S3, Mailpit), `Makefile`, `.env.example`.
  - Accept: `docker compose up -d` + `uv run uvicorn app.main:app` serves `/health/live` → 200; `uv run pytest` runs.

- [x] **T-002 Core infrastructure** · docs: 02, 05, 10
  - Scope: `config.py`, `db.py`, `ids.py` (UUIDv7), `time.py` (injectable clock), `errors.py` (RFC 9457), `pagination.py`, `logging.py`, `redis_client.py`, `/health/ready` (DB + Redis).
  - Accept: unit tests for error mapping, cursor encode/decode, ready check fails when DB is down.

- [x] **T-003 Quality gates and CI** · docs: 02, CLAUDE.md
  - Scope: Ruff, mypy (strict on `engine`, `app/core`), import-linter contracts (engine imports nothing from app; modules only via `service`/`schemas`), GitHub Actions with Postgres/Redis, Alembic initialised (async env using `app.core.db.Base.metadata`), `/health/ready` also checks that migrations are at head.
  - Accept: a deliberate cross-module import fails `lint-imports` in CI.

## Phase 1 — Engine: rules, standings, draw, schedule, bracket

- [x] **T-010 Engine model and rule config** · docs: 04
  - Scope: `engine/model.py`, `engine/rules/` (`RuleConfig`, `FormatSpec`, `SeedingPolicy`, `SchedulePolicy`), presets/catalogue with ids + version, `validate.py`, sport registry.
  - Accept: invalid configs rejected with clear messages (unknown outcome key, advancement not fitting the bracket, unsatisfiable separation, too few slots); all presets validate.

- [x] **T-011 Football sport module** · docs: 04
  - Scope: `FootballResult`, `outcome_key`, `team_stats`, `metric`, `hypothetical_outcomes`, `margin_axis`, `knockout_winner`, `validate_event`, walkovers, extra time and penalties.
  - Accept: tests for regulation/extra-time/penalty results in group vs knockout, own goals, walkovers, fair-play totals.

- [x] **T-012 Standings and tiebreakers** · docs: 04
  - Scope: `compute_standings` with ordered tiebreakers, h2h mini-tables with re-application, `tied_unresolved`, `decided_by`, form, cross-group ranking (best thirds, points per game).
  - Accept: 2-, 3- and 4-way ties under both presets; Hypothesis tests (order independence, points sum); ≥ 2 golden tests from real anonymised community/junior tables.

- [x] **T-013 Draw** · docs: 04 (Draw), 12 §5
  - Scope: `make_draw` with pots, fixed placements, separations, uniform sampling over valid assignments, infeasibility with minimal conflict, per-team reasons.
  - Accept: property test: all constraints hold; same seed → same draw; chi-square uniformity on a small instance; "6 separated teams into 4 groups" returns a minimal conflict; 32 teams with 8 separations < 1 s.

- [x] **T-014 Bracket** · docs: 04 (Bracket)
  - Scope: `build_bracket` (standard crossover, best-third mapping, third-place match), `resolve_bracket` (resolve only when final, `could_be` sets, `blocked` on lots).
  - Accept: 16-team 4×4 → QF/SF/F bracket; 24-team best-thirds mapping; property: a resolved placeholder never changes when more results are added.

- [x] **T-015 Schedule** · docs: 04 (Schedule), 12 §6
  - Scope: `build_schedule` (Berger round robin, slots from days × windows × pitches, hard constraints, soft objectives, simultaneous last round), `reschedule`, `suggest_relaxations`, catalogue `format_auto(n, days, pitches)` (ranked candidate formats that fit).
  - Accept: property tests: no double booking, rest respected, dependencies ordered; reschedule moves only matches after `frozen_until`; infeasible input returns relaxations with slot counts; 32 teams / 3 days / 6 pitches < 5 s.

- [x] **T-016 Scenarios and relevance** · docs: 04 (Scenarios, Relevance)
  - Scope: exact enumeration, status classification, threshold search, path summarisation, simulation hook, knockout path; `match_relevance`.
  - Accept: hand-built cases ("a draw is enough unless X win by 3+"); property: `clinched` qualifies in every completion; relevance ranks a directly competing rival's match above an irrelevant one; 6 teams / 6 matches left < 1 s.

## Phase 2 — Automatic setup

- [x] **T-020 Accounts** (primary follow from the sign-up intent lands with T-040: accounts publishes `UserSignedUp`) · docs: 09, 05, 14
  - Scope: users (13+ confirmation), sign-up with intended follow (`signup_intents`), login_tokens, sessions; magic link; refresh rotation; logout; CSRF; `GET/PATCH /me`; `Viewer` dependency (user, anonymous, pass).
  - Accept: full sign-up and login flows via Mailpit; account created only after the link is opened; the team chosen before sign-up is followed as primary after verification; sign-up for an existing email returns 202 and sends a login link; reused refresh token revokes the session.

- [x] **T-021 Competitions module** · docs: 03, 05
  - Scope: sports, organisations (+ processing agreements), series, tournaments (lifecycle, settings defaults incl. `show_probabilities` and `live_access`), staff, groups, teams (+ aliases, contacts), tournament_teams, players (+ visibility, consents), venues, pitches, matches with placeholders.
  - Accept: junior players default `hidden`; U12 tournaments default `show_probabilities = false`; contacts visible to staff only; visibility tests from `09-security-privacy.md`.

- [x] **T-022 LLM gateway, documents and redaction** · docs: 07, 09
  - Scope: provider interface + one adapter + fake provider; prompt templates with versions; structured output; timeouts, retries, breaker, cache, budget, call log; `core.documents` (PDF/DOCX/XLSX/CSV/image); `core.redaction` + gateway PII guard.
  - Accept: no provider SDK import outside `app/core/llm` (lint); breaker opens after 5 failures; planted phone numbers/emails/birth dates/personal identity codes never reach the provider in tests.

- [x] **T-023 Rules module** · docs: 04, 05
  - Scope: rule_configs draft/confirm/versioning, presets, worked examples and edge-case tests via the engine, plain-language rules summary.
  - Accept: confirming creates version n+1 and enqueues `recalc_tournament` (stub until T-031).

- [x] **T-024 Setup: intake and extraction** · docs: 12, 07
  - Scope: setup module tables; `POST /setup`, files, extract; deterministic CSV/XLSX team parsing; extraction tasks (`rules`, `format`, `teams`, `seeding`, `schedule`) with quotes; catalogue gap filling → assumptions; open questions; team history matching with `team_aliases`.
  - Accept: on `tests/setup/eval_set/` (≥ 8 rulebooks + team lists in fi/en/bn, incl. a photo and a WhatsApp paste) drafts validate; unclear tiebreakers and seeding become open questions, never guesses; "last year's semi-finalists apart" becomes a `Separation`.

- [x] **T-025 Setup: draw, schedule, review, publish** (scorer passes and printables follow from `TournamentPublished` in T-030/T-061) · docs: 12, 05
  - Scope: `generate_draw_and_schedule` job; answers, draft edits, redraw, regenerate, move match; publish transaction (groups, matches, rule config v1, staff, scorer passes); printables (pitch sheets with QR, filming notice).
  - Accept: end-to-end: sample FinBangla-style files → ready draft with ≤ 5 questions → publish → 16 teams, 4 groups, 32 matches (24 group + QF/SF/third place/final) over 3 days on 4 pitches; publish blocked with open questions; draws reproducible from stored seed.

- [x] **T-026 Seed data** · docs: 10, 12
  - Scope: `app/scripts/seed.py` runs the setup pipeline (fake LLM provider) to create a 3-day community cup (16 teams, 4×4 + QF/SF/F, previous edition with placements for seeding) and a junior league (8 teams, half played). Anonymised names.
  - Accept: seed is idempotent and used by later tasks.

## Phase 3 — Match day: scoring, jobs, read models, live

- [x] **T-030 Scoring and scorer passes** · docs: 06
  - Scope: scorer passes (QR, scope, revoke); start/finish; idempotent events; undo; results-only entry; live_state replay; moment detection.
  - Accept: concurrent duplicate posts produce one event; a pass for pitch 2 cannot score pitch 3 (403); revoked pass → 401 `pass_revoked`; invalid football events → 422.

- [x] **T-031 Job queue** · docs: 08
  - Scope: Procrastinate setup, queues, transactional `defer`, periodic registration, failed-job admin endpoint.
  - Accept: a job deferred in a rolled-back transaction never runs; one deferred in a committed transaction always runs.

- [x] **T-032 Analysis read models** (ratings, predictions and analyses follow in T-042/T-043) · docs: 02, 03, 08
  - Scope: `recalc_tournament` (standings, scenarios, bracket resolution writing match teams, relevance, journeys, final placements), `recalc_live`; coalescing.
  - Accept: finishing the last group match fills QF placeholders; 20 rapid events cause ≤ 3 recalculations; snapshots rebuild identically from events.

- [x] **T-033 Fan read endpoints** (stories, predictions and comparisons endpoints arrive with their read models) · docs: 05
  - Scope: tournament, live, standings, bracket, schedule, scenarios, draw, match, timeline, team, organisation, series, screen, widget; ETag/304; Cache-Control; live access policy.
  - Accept: p95 < 150 ms locally with seed data; 304 on unchanged version; `members` policy hides live score from anonymous viewers.

- [x] **T-034 Organiser console and rescheduling** (notifications are delivered from the deferred job in T-041) · docs: 06, 05, 08
  - Scope: console endpoint, delay/changes preview + confirm (engine `reschedule`), drift check, unscored check, lifecycle transitions, team withdrawal walkovers.
  - Accept: time-travel tests with the injectable clock: a 20-min delay on pitch 2 moves only later pitch-2 matches (and dependent ones), followers of affected teams get a `schedule_change` notification.

- [x] **T-035 Live WebSocket** · docs: 06
  - Scope: live token (policy-aware, anonymous for `public`), match and tournament sockets, Redis fan-out, seq handling, ping, viewer counts, `schedule`/`announcement` messages.
  - Accept: ordered delivery; resync with `since_seq` after forced disconnect with no gaps or duplicates; two API instances both deliver.

## Phase 4 — Personal experience and predictions

- [x] **T-040 Follows and My Team hub** · docs: 14, 05
  - Scope: follows (primary team), `/me/home`, team hub, feed, public feed.
  - Accept: hub p95 < 300 ms with seed data; personal endpoints return 401 when signed out; hub never shows hidden players.

- [x] **T-041 Notifications** (weekly email digest is a follow-up) · docs: 14, 08
  - Scope: notifications, `notify_followers`, reminders, web push (VAPID), quiet hours, rate limits, email.
  - Accept: following a team yields start, result, scenario, relevance, schedule-change and next-opponent notifications in tests; quiet hours respected.

- [x] **T-042 Ratings and predictions** (backtest on imported real history once integrations exist) · docs: 04, ADR 0005
  - Scope: Elo with seeding/history priors, single-venue home advantage 0, carry-over between editions, predictions with ranges and factors, backtest.
  - Accept: confidence `none` below 3 games; seeding factor present ("2025 runner-up"); ranges contain the point estimate; backtest prints Brier score.

- [x] **T-043 Comparison, analysis, simulation** · docs: 04
  - Scope: `compare_teams` (incl. previous editions), football `analyse`, `detect_moment`, season/tournament simulation (reach each round, win the cup).
  - Accept: analysis facts for comeback, late winner, upset, table and qualification impact; simulation deterministic per seed; 10k runs × 30 fixtures < 3 s.

## Phase 5 — Content

- [x] **T-050 Fact builder** · docs: 07
  - Accept: hidden players never appear in any fact sheet.
- [x] **T-051 Claim checker (fi/en/bn)** · docs: 07
  - Accept: catches 100% of planted errors in `tests/content/eval_set/`, including Bengali digits.
- [x] **T-052 Stories, team recaps, announcements** · docs: 07
  - Accept: report published < 2 min after finish (fake provider); all three languages produced; AI label on every item.
- [x] **T-053 Live commentary** · docs: 06, 07
  - Scope: written from the scorer's events (goals, cards, score, minute) and the tournament stakes; no video is needed.
  - Accept: 5 goals in 2 minutes → ≤ 3 commentary items; LLM timeout → template line; audience-based prioritisation across pitches.
- [x] **T-054 Editorial** · docs: 05, 07
  - Accept: correcting a goal republishes the report with "Corrected" and sends a `correction` live message if live.

## Phase 6 — Compliance, media, livecast extras

- [x] **T-060 Privacy test suite and GDPR endpoints** · docs: 09, 13
  - Scope: `tests/privacy/` across endpoints, screen, widget, WebSocket and content; export/delete for users and organisers; retention jobs.
- [x] **T-061 Compliance flows** · docs: 13
  - Scope: processing agreement gate, filming policy at publish, cookie consent support, notice-and-action for stories, accessibility statement; team rosters with junior consents and family links (organiser endpoints).
- [x] **T-062 Media: streams with filming check, opt-outs, live draw mode** · docs: 06, 13
  - Scope: attaching a stream link someone else produces (no video processing).
  - Accept: stream attach blocked (409) without rights confirmation, notice or junior consents; an opt-out blocks the next attach.
- [x] **T-063 Share cards, printables and venue screen polish** · docs: 06
  - Scope: share card images, printable pitch sheets with scorer-pass QR codes and the filming notice, venue screen rotation.
- [x] **T-064 Load test** (1,000 viewers on one match + 8 pitches live + 50 live matches) · docs: 10

## Phase 7 — Futsal and API completion (this version: football and futsal)

- [x] **T-065 Futsal module** · docs: 04
  - Scope: futsal sport module (2 × 20 min, accumulated fouls, timeouts, extra time and penalties), tiebreaker presets, setup extraction and seed data for a futsal tournament.
  - Accept: golden tests for futsal results, standings and accumulated-foul events; a futsal cup goes through setup → scoring → stories.
- [x] **T-066 API completion for the front end** · docs: 05
  - Scope: endpoints in docs/05 not built yet and not moved to the next version: search, players, team matches, organisation teams and matches, tournament settings (PATCH), staff, drawing of lots, public feed, schedule delay.
  - Built: `search`, `getPlayer`, `listOrganisationTeams`, `listOrganisationMatches`, `changeTournamentSettings`, `listStaff` / `addStaff` / `removeStaff`, `resolveLots` (+ the missing `lots_draws` migration 0022). For the web front end also: the catalogue lists (`listSports`, `listOrganisations`, `listTournaments`, `listTeams`), the match feed `listMatches`, `listStories` / `listOrganisationStories` / `listMyStories`, paged `listNotifications` with links, follow target names, `Me` parts from other modules, the scorer pad (`EventPad`), `getScoringState`, organiser accounts in `getScorerMatches`, and `demoLogin` (local/test only).
  - Built differently: team matches are in `getTeam`; the public feed is `listMatches` + `listStories`; a schedule delay is `previewScheduleChange` with `kind: "delay"`.

## Next version (not in this release)

Moved out on 2026-10-24: this release covers football and futsal, scored from the score sheet (scorer events), with no video processing.

- **T-070 Billing and the organisation portal business side** (seats, event passes, provider-hosted checkout, webhooks, member invites, redeem codes) · docs: 05
- **T-071 Ice hockey module** (+ Liiga golden tests and backtest) · docs: 04
- **T-072 Floorball module** · docs: 04
- **T-073 Cricket module discovery** (community demand) · docs: 04
- **T-074 Live win probability (Poisson v2)** · docs: 04
- **T-075 Video**: processing streams, automatic highlights, moments detected from video, commentary from video.
- **T-076 Passkeys** (`/auth/passkeys/…`) · docs: 05, 09
- Weekly email digest; backtest on imported real history (needs integrations); live-model evaluation runs.
