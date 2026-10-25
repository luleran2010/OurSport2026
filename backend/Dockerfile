# syntax=docker/dockerfile:1

# --- build stage: resolve dependencies into a virtualenv with uv ---
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv

# Dependencies first so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY engine ./engine
# Migrations ship in the image: releases run `alembic upgrade head` from it, and
# /health/ready compares the database against these heads.
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

# --- runtime stage: same image for api, worker and scheduler ---
FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 oursport
WORKDIR /srv
COPY --from=build --chown=oursport:oursport /srv /srv
ENV PATH="/srv/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER oursport
EXPOSE 8000
CMD ["gunicorn", "app.main:app", "-k", "uvicorn_worker.UvicornWorker", "--bind", "0.0.0.0:8000", "--workers", "2"]
