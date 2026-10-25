# 02 — System architecture

## Shape

One FastAPI codebase → one container image → three process types:

| Process | Start command | Does |
| --- | --- | --- |
| `api` | `gunicorn app.main:app -k uvicorn_worker.UvicornWorker` | REST + WebSocket. Short requests only |
| `worker` | `procrastinate --app=app.worker.app worker --queues=…` | Setup extraction, draw/schedule generation, recalculation, content, cards, notifications, imports |
| `scheduler` | `procrastinate … worker --queues=periodic` (periodic tasks) | Rolling pre-match builds, lifecycle transitions, schedule drift checks, cleanup, consistency checks |

Infrastructure:

| Component | Role | If it is down |
| --- | --- | --- |
| PostgreSQL 16+ | Source of truth: data, append-only events, read models, job queue | App is down (managed service with backups + PITR) |
| Redis 7+ | Live pub/sub fan-out, short cache, rate-limit counters, live viewer counts | Live push pauses; clients resync from Postgres |
| Object storage (S3-compatible) | Uploaded rulebooks and team lists, logos, share-card images, filming notices | Uploads and new cards fail; everything else works |
| LLM provider (external, EU processing) | Setup extraction, story and commentary text | Setup falls back to the guided form; template text fallback; stories queue for retry |
| OCR (inside the LLM provider's vision input, or a local OCR library) | Photos of paper rules and team lists | Organiser is asked for a text/Excel file instead |
| Stream provider (external, later) | Live video hosting | Video unavailable; data and commentary continue |
| Email / web push provider | Magic links, invites, notifications | Notifications delayed |

```
 Fan web app / venue screen / widget      Organiser console + setup wizard      Pitch scorer (QR)
                 \                                   |                                /
                  +---------------- Load balancer + CDN (TLS, WS) -------------------+
                                                     |
                           +-------------------------+-------------------+
                           |  api (REST + WebSocket) |  worker  | scheduler |
                           +------------+------------+-----+-------------+
                                        |                  |
               +------------------------+------+-----------+--------------+
               | PostgreSQL (truth, queue)     |  Redis (live fan-out)    | Object storage |
               +-------------------------------+--------------------------+----------------+
                                       worker → LLM provider, stream provider
```

## Modules

Code lives in `app/modules/<name>/`. Each module owns its tables and exposes `service.py` (+ `schemas.py`) as its only public interface.

| Module | Owns | Responsibilities | May call |
| --- | --- | --- | --- |
| `accounts` | users, signup_intents, login_tokens, sessions, passkeys, user_roles, family_links | Sign-up, magic-link/passkey login, sessions, `/me`, role checks | — |
| `competitions` | sports, organisations, processing_agreements, tournament_series, tournaments, tournament_staff, groups, teams, team_aliases, tournament_teams, players, consents, venues, pitches, matches | Organisations, editions, setup target tables, fixtures, rosters, lifecycle, junior visibility, live access policy | accounts |
| `subscriptions` | organisation_members, seats, entitlements, invites, billing_customers | Membership, premium seats, invites, `can_watch_live`, billing webhooks | accounts, competitions |
| `integrations` | import_jobs, external_refs | Adapters: CSV/XLSX, Liiga API, federation result services, other scoring apps | competitions, scoring |
| `rules` | rulebooks, rule_configs, rule_tests | Rule config drafts, presets, worked examples, versioning | competitions, core.llm (+ `engine` for validation) |
| **`setup`** | setup_sessions, intake_files, setup_drafts, draws, schedule_plans | The automatic setup pipeline: intake, redaction, AI extraction, gap filling from the policy catalogue, draw, schedule, review, publish, mid-tournament reschedule | competitions, rules, analysis, core.llm (+ `engine`) |
| `scoring` | match_events, live_state, scorer_passes | Event ingestion (idempotent), undo, finish, live state, moment detection, pitch scorer passes | competitions, rules (+ `engine.sports`) |
| `analysis` | standings_snapshots, scenario_snapshots, bracket_snapshots, relevance_snapshots, final_placements, ratings, rating_history, predictions, player_stats, team_comparisons, match_analyses, team_journeys, fact_sheets | Runs the engine, stores read models, resolves knockout placeholders, builds fact sheets | scoring, competitions, rules (+ `engine`) |
| `content` | stories, story_versions, commentary_items, share_cards, announcements | Previews, reports, summaries, live commentary, organiser announcements via LLM gateway; claim checker; cards | analysis, core.llm |
| `editorial` | review_items, review_decisions, corrections, audit_log | Review queue, approve/reject, unpublish, corrections → rebuilds | content, analysis |
| `audience` | follows, notifications, push_subscriptions | Follows, My Team hub, feed, notifications, web push, email digests | accounts (language, time zone, email), competitions, content, subscriptions, analysis |
| `media` | streams, filming_notices, filming_optouts, highlights (later) | Stream links per match with consent checks, venue filming notices, opt-outs, highlights | competitions, scoring |

`engine/` is a top-level pure Python package (not a module): no app imports, no I/O. Only `analysis`, `rules` (validating worked examples) and `setup` (draw, schedule, format validation) import it, plus `scoring`, which may import only `engine.sports` and `engine.model` (event validation, live-state replay and moment detection during ingestion; decided in T-030 because analysis calls scoring, so scoring cannot go through analysis).

`app/core/` holds shared infrastructure: settings, db session (writes commit explicitly with `async with session.begin()`), Redis client, auth dependencies, errors, pagination, ids, time, job queue setup, live publisher, `llm` gateway, `redaction` (PII scrubbing before LLM calls), `documents` (text extraction from PDF/DOCX/XLSX/images), logging, rate limiting.

### Module dependency rules (import-linter contracts)

- `engine` imports nothing from `app`.
- `app.modules.X` may import `app.modules.Y.service` and `app.modules.Y.schemas` only.
- No cycles between modules. Dependency direction follows the "May call" column. It limits direct calls: using an allowed module's service that itself calls further (scoring → competitions.service → accounts.service) is fine.
- Modules that may not call each other react through in-process events (`app/core/events.py`, handled in the publisher's transaction), e.g. `UserSignedUp`, `OrganisationCreated`.
- Only `app.core.llm` may import LLM provider SDKs.

## Inside a module

```
app/modules/scoring/
  router.py       # HTTP: parse request, call service, return schema. No SQL, no logic
  schemas.py      # Pydantic request/response models (also the public data types)
  service.py      # business logic; public interface for other modules
  repository.py   # SQLAlchemy queries; applies scoping and visibility filters
  models.py       # ORM tables owned by this module
  jobs.py         # Procrastinate tasks owned by this module
  events.py       # internal domain events this module emits (optional)
  tests/
```

Rules: services receive an explicit `AsyncSession` and the acting `Viewer` (user or anonymous + roles + scorer pass); services return schemas or plain dataclasses, never ORM objects to routers.

## Setup path (organiser uploads rules and teams)

Details in `12-tournament-setup.md`.

1. `POST /setup` creates a draft tournament + setup session; `POST /setup/{id}/files` uploads rulebook, team list, optional history and venue info.
2. Job `extract_setup`: text extraction (`core.documents`) → redaction (`core.redaction`) → LLM gateway tasks `rules_extract`, `teams_extract`, `seeding_extract` → structured `SetupDraft` with source quotes, confidence, assumptions and open questions.
3. Gap filling: anything the rules do not specify is filled from the engine's **policy catalogue** (internationally used formats, seeding and scheduling practice), recorded as an *assumption*.
4. Team matching: teams matched to previous editions (`team_aliases`, `final_placements`) for seeding.
5. Job `generate_draw_and_schedule`: engine `make_draw` (seeded, constraint-checked) → `build_bracket` → `build_schedule` (days × pitches × times). Infeasible constraints become open questions.
6. Organiser reviews one screen (groups, schedule, rule summary, assumptions, ≤ 5 questions), optionally redraws or edits, then `POST /setup/{id}/publish`: one transaction writes groups, tournament_teams, matches, confirmed rule config, staff and pitch QR passes; enqueues `recalc_tournament` and `prematch_build`.

## Write path (example: pitch scorer enters a goal)

1. `POST /api/v1/matches/{id}/events` — auth (scorer pass for this pitch/match, or tournament staff), idempotency on (`match_id`, `client_seq`).
2. One transaction: insert `match_events` row with next `seq`; update `live_state`; run moment detection; enqueue `recalc_live(match_id, seq)` and, if a moment, `write_commentary(match_id, seq)`.
3. After commit: publish `event` message to Redis channels `match:{id}` and `tournament:{id}`. Return `201 {seq}`.
4. Worker `recalc_live`: engine computes live stakes (table "if it ends now") and live relevance for other teams; writes read models; publishes `state`.
5. Worker `write_commentary`: fact sheet → LLM gateway → claim checker → store → publish `commentary`.
6. On finish: `recalc_tournament` (standings, scenarios, bracket resolution → fills "Winner Group A" placeholders, relevance, journeys), `update_ratings`, `compute_predictions` for the next round, `analyse_match`, `write_story(report)`, `render_card`, `notify_followers`.

## Read path

- Fan endpoints read only read models (`*_snapshots`, `predictions`, `team_comparisons`, `match_analyses`, `team_journeys`, `stories`, `live_state`).
- Each read model has `version` + `updated_at` → `ETag`. Public data gets `Cache-Control: public, max-age=30` (live tournament pages: `max-age=5`).
- Rolling pre-match builds (immediately after each result, plus a periodic sweep) mean match-day reads are always warm even in a 3-day cup.

## Tech stack

| Concern | Choice |
| --- | --- |
| Language | Python 3.12+ |
| Web | FastAPI, Uvicorn/Gunicorn |
| Schemas, settings | Pydantic v2, pydantic-settings |
| ORM, migrations | SQLAlchemy 2.0 async + asyncpg, Alembic |
| Jobs | Procrastinate (PostgreSQL-backed queue, periodic tasks) |
| Cache, pub/sub | Redis via `redis.asyncio` |
| Auth | Magic links + optional passkeys (WebAuthn); PyJWT for access tokens; scorer passes |
| Documents | `pypdf`, `python-docx`, `openpyxl`; images through the LLM provider's vision input |
| Printables and cards | `segno` (pure-Python QR codes as inline SVG); printables are print-ready HTML, share cards are SVG |
| Scheduling solver | Own deterministic heuristic in `engine/schedule.py` (OR-Tools CP-SAT only if the heuristic proves insufficient; single worker + fixed seed for determinism) |
| Images | Pillow (or a headless HTML renderer) for share cards, QR codes (`segno`) for pitch passes and filming notices |
| Dependencies | uv with committed lockfile |
| Quality | Ruff, mypy (strict for `engine`, `app/core`), import-linter |
| Tests | pytest, pytest-asyncio, Hypothesis, testcontainers |
| Observability | structlog, OpenTelemetry, Sentry |
| Packaging | Docker (one image), Docker Compose for local dev |

## Repository layout

```
.
├── CLAUDE.md
├── docs/                       # these documents + adr/
├── pyproject.toml  uv.lock
├── docker-compose.yml  Dockerfile  Makefile
├── alembic/                    # migrations
├── engine/                     # pure library
│   ├── model.py                # input/output dataclasses
│   ├── rules/                  # RuleConfig, FormatSpec, SeedingPolicy, SchedulePolicy, presets, validation
│   ├── standings.py  tiebreakers.py  scenarios.py  simulation.py
│   ├── draw.py  schedule.py  bracket.py  relevance.py
│   ├── ratings.py  predictions.py  comparison.py
│   ├── sports/                 # base.py, football.py (first), ice_hockey.py (next); later floorball.py, futsal.py, volleyball.py
│   └── tests/                  # unit, property-based, golden/
├── app/
│   ├── main.py  worker.py
│   ├── core/                   # config, db, auth, errors, ids, time, pagination, jobs, live, llm/, documents, redaction, logging, ratelimit
│   ├── modules/                # accounts, competitions, subscriptions, integrations, rules, setup,
│   │                           # scoring, analysis, content, editorial, audience, media
│   └── scripts/                # seed, rebuild, backfill
└── tests/                      # cross-module integration, API, privacy and setup end-to-end tests
```
