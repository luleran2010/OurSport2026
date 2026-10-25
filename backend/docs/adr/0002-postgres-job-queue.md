# ADR 0002 — PostgreSQL-backed job queue (Procrastinate)

- Status: accepted
- Date: 2026-10-24

## Context

Most writes trigger follow-up work (setup extraction, recalculation, stories, notifications). A separate broker (Celery + Redis/RabbitMQ) adds a system to operate and the classic "data committed, job lost" or "job ran, data rolled back" bugs unless an outbox is built.

## Decision

Use Procrastinate on PostgreSQL. Jobs are deferred inside the same database transaction as the data change. Separate queues per workload (`setup`, `engine`, `content`, `media`, `notify`, `imports`, `periodic`). Periodic tasks replace a separate cron.

## Consequences

- Exactly the jobs for committed changes run; no outbox needed.
- One less infrastructure component; job state is queryable with SQL.
- PostgreSQL carries queue load; fine at our scale (thousands of jobs per hour). If queue load becomes significant, move to a Redis-backed queue behind the same `defer` helper.
- Redis remains for live pub/sub and caching only.
