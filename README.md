# OurSport

OurSport helps local sports tournaments manage setup and scoring, and gives
supporters live scores, standings, predictions and AI-written coverage in
Finnish, English and Bengali.

An organiser uploads the rules and the team list. OurSport drafts the
tournament: groups, seeding and a full match schedule. The organising team then
keeps score from their phones, and fans follow along live.

## Simple way to run

```
# in backend
uv run uvicorn app.main:app --reload --port 8000
uv run python -m app.worker
# in frontend
npm run dev
```

## Project layout

| Path | What it is |
| --- | --- |
| `frontend/` | React 19 + React Router web app, built with Vite |
| `backend/` | Main FastAPI service (modular monolith) on PostgreSQL, Redis and S3-compatible storage |
| `backend/engine/` | Pure tournament engine (standings, tiebreakers, draws, schedules, ratings), with no I/O |
| `backend/docs/` | Architecture, API, data model and ADRs |
| `mock_backend/` | Lightweight FastAPI server with in-memory mock data, serving the same API v1 contract, so you can run the frontend without the main backend's infrastructure |
| `gap_analysis/` | Project analysis and planning material |

## Prerequisites

- **Node.js** and npm (for the frontend)
- **Python 3.12+** and [uv](https://docs.astral.sh/uv/) (uv will install Python 3.12 if needed)
- **Docker** with Docker Compose (only for the main backend)
- Optional: [Ollama](https://ollama.com/) or an LLM API key for AI features (see [LLM provider](#llm-provider))

## Quick start: frontend + mock backend

This is the fastest way to get the app running. No database is needed. Run each
command in its own terminal, starting from the project root.

**Terminal 1: mock API on port 8000**

```bash
cd mock_backend
uv run uvicorn app.main:app --reload --port 8000
```

**Terminal 2: web app on port 5173**

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api`, `/health`,
`/mock` and the older portal routes to `http://127.0.0.1:8000`. Mock API docs
are at <http://localhost:8000/docs>.

Mock-only sign-in shortcuts:

- `POST /api/v1/auth/demo-login` with `{"persona": "fan" | "organiser" | "editor"}`
- Magic links sent by the mock are listed at <http://localhost:8000/mock/outbox>
- Demo scorer passes are listed at <http://localhost:8000/mock/scorer-passes>

For more, see [mock_backend/README.md](mock_backend/README.md).

## Running the main backend

All commands below run from `backend/`.

### 1. Configure and start infrastructure

```bash
cd backend
cp .env.example .env          # or: make install (also runs uv sync)
docker compose up -d          # Postgres :5432, Redis :6379, S3 (SeaweedFS) :8333, Mailpit :1025/:8025
```

You can run only the database and cache with `docker compose up -d db redis`.
Media uploads need the S3 service, and sign-in emails need Mailpit.

### 2. Install dependencies, migrate and seed

```bash
uv sync
uv run alembic upgrade head
uv run python -m app.scripts.seed     # optional demo data: community cup, futsal cup, junior league
```

The seed script uses recorded LLM answers, so it doesn't need an API key, and
you can safely run it more than once.

### 3. Run the API

```bash
uv run uvicorn app.main:app --reload --port 8002
```

API docs: <http://localhost:8002/docs>. We use port 8002 so the main backend can
run alongside the mock backend on 8000. If you only run the main backend, the
default port (`make dev`, :8000) also works.

> **Windows:** set `PYTHONUTF8=1` before starting the backend
> (`$env:PYTHONUTF8 = "1"` in PowerShell), as the `.claude/launch.json` presets
> do, so Python reads the project's UTF-8 files correctly.

### 4. Run the background worker (optional)

Background jobs (AI content, notifications, recalculations) run on a
Procrastinate worker:

```bash
uv run procrastinate --app=app.worker.app worker
# Windows:
uv run python -m app.worker
```

### 5. Point the frontend at the main backend

From `frontend/`, start Vite with `API_PROXY` set to the backend's address:

```bash
# macOS / Linux / Git Bash
API_PROXY=http://127.0.0.1:8002 npm run dev -- --port 5180
```

```powershell
# Windows PowerShell
$env:API_PROXY = "http://127.0.0.1:8002"
npm run dev -- --port 5180
```

Open <http://localhost:5180>. Sign-in uses magic links. Read the emails in
Mailpit at <http://localhost:8025>.

### LLM provider

AI features go through the LLM gateway and are configured in `backend/.env`:

| `LLM_PROVIDER` | Notes |
| --- | --- |
| `ollama` (example default) | Needs a local Ollama at `LLM_OLLAMA_BASE_URL` with `LLM_MODEL` pulled (e.g. `ollama pull qwen3.5:9b`) |
| `fake` | Deterministic offline provider. Good for development and tests, but not allowed in staging or production |
| `anthropic` / `deepseek` | Set `LLM_API_KEY` and `LLM_MODEL` |

Never commit `backend/.env`.

## Running everything from Claude Code

[.claude/launch.json](.claude/launch.json) defines these dev-server presets:

| Name | Runs | Port |
| --- | --- | --- |
| `backend` | mock backend | 8000 |
| `frontend` | frontend → mock backend | 5173 |
| `real-backend` | main backend | 8002 |
| `frontend-real-backend` | frontend → main backend | 5180 |

## Development commands

**Frontend** (from `frontend/`):

```bash
npm run lint      # oxlint
npm run build     # production build into dist/
npm run preview   # serve the build
```

**Backend** (from `backend/`; `make` targets shown where available):

```bash
uv run pytest                  # make test: all tests (DB tests are skipped if Postgres/Redis aren't running)
uv run pytest engine -q        # make test-engine: fast engine-only tests
uv run ruff check .            # make lint: also runs the ruff format check
uv run mypy                    # make typecheck
uv run lint-imports            # make imports: module boundary contracts
make check                     # everything CI runs
uv run alembic revision --autogenerate -m "describe change"   # new migration
```

**Mock backend** (from `mock_backend/`):

```bash
uv run pytest                  # includes the contract test against backend/docs/frontend-handoff/openapi.json
```

## Further reading

- [backend/CLAUDE.md](backend/CLAUDE.md): product principles and backend conventions
- [backend/docs/](backend/docs/): overview, architecture, API, live updates, jobs, security and privacy, operations
- [backend/docs/adr/](backend/docs/adr/): architecture decision records
- [mock_backend/README.md](mock_backend/README.md): the mock API and its demo shortcuts
