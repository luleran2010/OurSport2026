# CLAUDE.md — OurSport backend

Instructions for Claude (and any developer) working in this repository. Read this file fully before every task.

## What we are building

**OurSport** makes every local tournament feel like a big league — and makes running one easier than a spreadsheet. An organiser uploads the tournament rules and the list of teams; OurSport sets up the whole tournament (groups drawn by the rules, fair seeding, full match schedule across pitches and days), the organising team keeps score from their phones, and families, friends and the community follow live: scores, AI commentary, standings, "what does our team need", predictions with reasons, match analysis and stories — in Finnish, English and Bengali.

The reference customer is a **FinBangla community football tournament**: 3 days, many teams, several pitches, groups then knockout. **Football and futsal are this release's sports** (ice hockey and floorball in the next version; volleyball after; cricket later). Scoring comes from the score sheet (scorer events); video processing is for the next version.

Two audiences, both must feel it is *theirs*:

- **Organisers** — zero manual setup, scoring is no extra work, they get the pride of a livecast tournament.
- **Supporters** — "my team" first: everything about the team they support and the league it plays in, while all other matches stay one tap away.

The backend is a **FastAPI modular monolith** on **PostgreSQL** and **Redis**. A separate web front end consumes it through the OpenAPI contract.

## Read before you code

| Doc | Read when |
| --- | --- |
| `docs/01-overview.md` | Always, once per session: product, users, principles, glossary |
| `docs/02-architecture.md` | Any structural change, new module, new dependency |
| `docs/03-data-model.md` | Any table, migration or query |
| `docs/04-engine.md` | Anything that calculates: standings, draw, schedule, bracket, scenarios, predictions, analysis |
| `docs/05-api.md` | Any endpoint, schema or error |
| `docs/06-live.md` | Live scoring, match-day console, WebSocket, commentary, livecast |
| `docs/07-content-pipeline.md` | Fact sheets, LLM calls, extraction, stories, claim checker, review |
| `docs/08-jobs.md` | Background jobs and scheduled tasks |
| `docs/09-security-privacy.md` | Auth, permissions, junior data, consent |
| `docs/10-operations.md` | Deployment, config, logging, performance |
| `docs/11-build-plan.md` | Picking the next task and its acceptance criteria |
| `docs/12-tournament-setup.md` | Upload → AI extraction → draw → schedule → publish |
| `docs/13-compliance-finland.md` | GDPR, Finnish law, filming/streaming, minors, AI labelling |
| `docs/14-personal-experience.md` | My Team hub, relevance, personal feed, notifications |
| `docs/adr/` | Before proposing to change a recorded decision |

## Golden rules (never break these)

1. **Numbers come from the engine, never from an LLM.** The LLM only writes text from a verified fact sheet.
2. **AI proposes, the engine decides, the organiser publishes.** In setup the LLM extracts rules, teams and seeding instructions into structured drafts and may only choose policies from the engine's closed catalogue. The draw and the schedule are computed by the engine with a stored seed. Nothing becomes public until an organiser taps *Publish*.
3. **The engine (`engine/`) is a pure library.** It must not import from `app/`, touch the database, do I/O, read the clock or call the network. Input in, result out. Randomness only from an explicit seed.
4. **LLM calls only through `app/core/llm/`.** No provider SDK imports anywhere else. Uploaded documents are redacted (phone numbers, emails, birth dates, addresses) before they reach the gateway.
5. **Match events are append-only.** Never update or delete a `match_events` row; undo is a new event. Everything else is derived and rebuildable.
6. **Compute on write.** Fan-facing read endpoints only read precomputed read-model tables. They never call the engine or the LLM.
7. **Module boundaries.** A module may use another module only through that module's `service.py` and `schemas.py`. Never import another module's `models.py` or `repository.py`. `import-linter` enforces this in CI.
8. **Layering inside a module:** `router.py` → `service.py` → `repository.py`. Routers contain no business logic and no SQL.
9. **Junior data protection.** Player queries always go through the visibility filter in the repository (`visibility_filter(viewer)`). Never return a hidden player from any endpoint. Never send contact details or birth dates to the LLM. Never attach a stream to a match without the filming check.
10. **AI text is labelled.** Every AI-written story and commentary item is stored with `author_type = "ai"` and served with a visible label.
11. **No betting.** No odds, no betting language, no betting integrations, anywhere.
12. **Every schema change is an Alembic migration** that is backward compatible with the previous app version.

## Commands

```bash
uv sync                                  # install dependencies
docker compose up -d db redis            # start Postgres and Redis
uv run alembic upgrade head              # apply migrations
uv run python -m app.scripts.seed        # demo data: 3-day community cup (16 teams, 4 groups + knockout), one-day futsal cup, junior football league
uv run python -m app.scripts.review_demo # demo work for the editor desk: AI stories held by the claim checker (local/test only)
uv run python -m app.scripts.loadtest    # load test (docs/10): 1,000 viewers, 50 live matches; --check fails on missed targets
uv run uvicorn app.main:app --reload     # API on :8000 (docs at /docs)
uv run procrastinate --app=app.worker.app worker   # background worker (Windows: uv run python -m app.worker)
uv run pytest                            # all tests; DB tests use a fresh `<db>_test` database
                                         # (skipped if Postgres/Redis are not running)
uv run pytest engine -q                  # engine tests only (fast)
uv run ruff check . && uv run ruff format --check .
uv run mypy                              # strict on engine and app/core
uv run lint-imports                      # module boundary contracts (pyproject.toml)
uv run alembic revision --autogenerate -m "…"   # new migration after changing models
```

## How to work on a task

1. Pick the next unchecked task in `docs/11-build-plan.md`. Work on **one task at a time**.
2. Re-read the docs that task references. If the docs and the task disagree, stop and ask.
3. For engine work: **write tests first** (unit + at least one property-based test), then implement.
4. Keep changes inside the task's scope. If you discover needed work outside it, note it under "Follow-ups" in your summary instead of doing it.
5. Run the full check before finishing: `ruff`, `mypy`, `lint-imports`, `pytest`.
6. Update docs in the same change when you alter behaviour, an endpoint, a table or a decision.
7. Finish with a short summary: what changed, how it was tested, follow-ups.

## Definition of done

- Acceptance criteria in the task are met and demonstrably tested.
- All checks pass; no new `type: ignore` or `noqa` without a comment explaining why.
- New endpoints have explicit request/response models, an `operation_id`, a tag, and tests for one allowed and one denied case.
- New tables have a migration, indexes for their main queries, and are documented in `docs/03-data-model.md`.
- No secrets, personal data or real player names in code, tests or fixtures (use generated names).

## Style

- Python 3.12+, full type hints, `from __future__ import annotations` not needed.
- Pydantic v2 models for all API schemas and JSONB payloads.
- SQLAlchemy 2.0 typed ORM (`Mapped[...]`), async sessions.
- Small functions, descriptive names, docstrings on public service functions.
- UTC everywhere in the backend; ISO 8601 with `Z` in the API. The front end renders in the viewer's time zone (relatives abroad).
- Logging through `structlog`; never `print`.
- Errors: raise domain errors from `app/core/errors.py`; the handler maps them to the problem-details format.

## Ask instead of guessing when

- A tournament rule, tiebreaker, seeding rule or sport rule is unclear.
- A change would alter a public endpoint or response field (it may break the front end).
- A task seems to require breaking a golden rule.
- A legal or compliance point in `docs/13-compliance-finland.md` is marked *needs legal review* and the task depends on it.
