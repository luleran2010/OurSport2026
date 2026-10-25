.PHONY: install up down dev test test-engine lint format typecheck imports migrate check

install:        ## install dependencies and create .env from the example if missing
	uv sync
	cp -n .env.example .env || true

up:             ## start Postgres, Redis, S3 and Mailpit
	docker compose up -d

down:           ## stop local infrastructure
	docker compose down

dev:            ## run the API with reload on :8000
	uv run uvicorn app.main:app --reload

test:           ## all tests
	uv run pytest

test-engine:    ## engine tests only (fast)
	uv run pytest engine -q

lint:           ## lint and format check
	uv run ruff check .
	uv run ruff format --check .

format:         ## apply formatting and safe lint fixes
	uv run ruff format .
	uv run ruff check --fix .

typecheck:      ## mypy: strict on engine and app/core, standard elsewhere
	uv run mypy

imports:        ## module boundary contracts
	uv run lint-imports

migrate:        ## apply migrations to the local database
	uv run alembic upgrade head

check: lint typecheck imports test   ## everything CI runs
