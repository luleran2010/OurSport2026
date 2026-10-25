# 10 — Operations: environments, deployment, observability, performance

## Environments

| Env | Purpose | Data |
| --- | --- | --- |
| local | Development (Docker Compose: Postgres, Redis, SeaweedFS for S3 — MinIO no longer publishes community images — Mailpit for email) | Seed script |
| staging | Integration with front end, demo, load tests, setup eval runs | Seed + anonymised copies |
| production | Real users (EU region) | Real |

Same image everywhere; behaviour differs only by environment variables.

## Configuration (`app/core/config.py`, pydantic-settings)

`ENV`, `DATABASE_URL`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `REDIS_URL`, `REDIS_MAX_CONNECTIONS`, `REDIS_POOL_TIMEOUT_S`, `SHARED_CACHE_ENABLED`, `S3_*`, `PUBLIC_BASE_URL`, `CORS_ORIGINS`, `WIDGET_EMBED_ORIGINS`, `JWT_SECRET`, `COOKIE_DOMAIN`, `EMAIL_*`, `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL_<TASK>`, `LLM_DAILY_TOKEN_BUDGET`, `LLM_TOURNAMENT_TOKEN_BUDGET`, `POLICY_CATALOGUE_VERSION`, `UPLOAD_MAX_MB`, `MALWARE_SCAN_URL`, `SENTRY_DSN`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `FEATURE_FLAGS`. Validated at startup.

## Deployment

- One Docker image (multi-stage, `uv sync --frozen --no-dev`, non-root).
- Release: `alembic upgrade head` as a one-off job → API → workers. Expand → migrate → contract over two releases.
- **No deploys during an active tournament's match hours** unless it is a hotfix (release calendar reads `tournaments.status = active` windows).
- Platform: managed container service in an EU region (or one VM with Docker Compose at the very start). Managed PostgreSQL with backups and PITR; managed Redis.
- CDN in front of public GET endpoints, the venue screen, the widget and images.

### Sizing for bursty usage

| Component | Baseline | Tournament day |
| --- | --- | --- |
| API | 1–2 instances | autoscale to 4+ on CPU or connection count |
| Worker `engine` | 1 | 1–2 |
| Worker `content` + `setup` | 1 | 2–4 (scheduled scale-up on tournament days from the tournament calendar) |
| Scheduler | 1 | 1 |
| PostgreSQL | small managed tier | same; read replica only when metrics demand |

## Observability

- **Logs:** JSON (structlog) with `request_id`, `user_id` (hashed), `pass_id`, `organisation_id`, `tournament_id`, `match_id`, `job_id`.
- **Tracing:** OpenTelemetry for FastAPI, SQLAlchemy, Redis, HTTP client; context propagated into jobs.
- **Errors:** Sentry (API + workers) with release tags.
- **Health:** `GET /health/live`, `GET /health/ready` (DB + Redis, migrations current).
- **Metrics / dashboards:**
  - HTTP p50/p95/p99 by route, error rate
  - setup: time to ready, extraction failures, open questions per setup, publish rate, guided-form fallbacks
  - queue depth and oldest job age per queue; job durations; failures
  - event-to-fan latency; pitches live; viewers per match and per tournament
  - schedule drift per pitch on active tournaments
  - LLM calls, latency, failures, cache hit rate, cost per tournament
  - claim-checker block rate, review queue size
- **Alerts** (runbook each in `docs/runbooks/`): API error rate > 2% 5 min; p95 > 500 ms 10 min; `engine` queue age > 30 s; `setup` > 2 min; `content` > 5 min; event-to-fan p95 > 5 s; LLM failure rate > 20%; budget 80%; DB CPU > 70% 15 min; backup failure; data breach suspicion (security runbook, 72 h clock).

## Performance targets

| Measure | Target |
| --- | --- |
| Setup: upload → reviewable draft with draw and schedule (32 teams) | < 2 min |
| Draw / reschedule computation | < 1 s / < 5 s |
| Public read endpoints | p95 < 150 ms |
| My Team hub, personal feed | p95 < 300 ms |
| `POST /matches/{id}/events` | p95 < 200 ms |
| Event visible to live viewers | < 2 s |
| Standings, scenarios, bracket after a result | < 10 s |
| Next-round previews and predictions after a group finishes | < 2 min |
| Live commentary item | < 15 s or skipped |
| Match report (auto path) | < 2 min after finish |
| Availability during scheduled match windows | 99.5% |
| Load test | 1,000 viewers on one match + 8 pitches live in one tournament + 50 live matches overall |

### Load test (T-064)

Run: `uv run python -m app.scripts.loadtest [--base URL] [--check]`. It provisions its own cups through the setup pipeline (fake LLM; the first cup on 8 pitches), starts the live matches, and measures with real clients:
- 1,000 WebSocket viewers on one match;
- a goal per live match per round, spread over `--spread_ms`;
- 600 concurrent public reads;
- personal pages.

`tests/test_loadtest.py` runs a small version in CI.

Result on a development laptop (2026-10-24; gunicorn with 2 workers as in the Dockerfile, Postgres and Redis in Docker, load generator on the same machine):

| Measure | p50 | p95 | Target |
| --- | --- | --- | --- |
| Event → 1,000 viewers (100% delivered) | 32 ms | 47 ms | < 2 s |
| `POST /matches/{id}/events` (50 live matches, 8 pitches live in one cup) | 17 ms | 27 ms | < 200 ms |
| Public reads (50 concurrent) | 17 ms | 48 ms | < 150 ms |
| Personal pages | 39 ms | 91 ms | < 300 ms |

Stress case (`--spread_ms 0`, all 50 goals in the same instant): one event costs about 10 ms of server time, so the burst queues and POST p95 reaches about 270 ms on 2 workers. Event delivery stays below 0.3 s. Add workers or API instances for more pitches.

Changes made for this:
- **Shared cache:** `SharedCacheMiddleware` (`SHARED_CACHE_ENABLED`) serves anonymous public reads from Redis for their `max-age` (≤ 30 s). A page is computed once per process at a time.
- **Pools:** the Redis pool is blocking and sized (`REDIS_MAX_CONNECTIONS` 200, `REDIS_POOL_TIMEOUT_S` 5), and the database pool is configurable (`DB_POOL_SIZE` 20, `DB_MAX_OVERFLOW` 20 per process).
- **Fan-out:** live messages are serialised once per process, not once per socket.

## Backups and recovery

- Managed PostgreSQL daily snapshots + PITR (7–14 days); quarterly restore drill.
- Object storage versioning on.
- Read models rebuildable: `python -m app.scripts.rebuild --tournament <id>`.
- Match-day fallback: if the API is unreachable, the scorer app keeps queueing events offline; the organiser console can export the schedule and printables as PDF ahead of time.

## Demo data

`uv run python -m app.scripts.seed` builds, through the real setup pipeline with recorded extraction answers (fake LLM provider, no API key), the *Demo Community Cup 2026* (16 teams, 4×4 + QF/SF/3P/F, previous-edition placements for seeding) and the *Demo Junior League U12* (8 teams, league, half the matches played). Organiser: `demo.organiser@example.com` (sign in by magic link through Mailpit). Idempotent; all names invented. Data in `app/scripts/seed_data/`.
