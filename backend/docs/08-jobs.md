# 08 — Background jobs and schedules

Queue: **Procrastinate** (PostgreSQL). Jobs are enqueued **inside the same transaction** as the data change that causes them (`await job.defer_async(...)` on the request's connection), so a committed change always has its follow-up job and a rolled-back change never does.

**Implementation (T-031):** `app.core.jobs.defer(session, name, **args)` calls Procrastinate's `procrastinate_defer_jobs_v1` on the caller's SQLAlchemy (asyncpg) session, so the job row is part of the same transaction; the queue comes from `JOB_QUEUES`. The worker app is `app.worker` (`uv run procrastinate --app=app.worker.app worker`, psycopg connector); its schema is applied by migration 0008. Jobs whose module arrives later are registered as logging placeholders. Failed jobs: `GET /admin/jobs/failed`, `POST /admin/jobs/{id}/retry` (platform admins; others get 404).

## Queues and workers

| Queue | Purpose | Workers (start) | Notes |
| --- | --- | --- | --- |
| `setup` | Document extraction, draw, schedule generation | shared with `content` | Organiser waits for it: target < 2 min |
| `engine` | Recalculation, ratings, predictions, analysis, bracket, relevance | 1 dedicated | Never blocked by slow LLM calls |
| `content` | Stories, commentary, explanations, announcements | 1 (scale up on tournament days) | LLM-bound |
| `media` | Share cards, printables (pitch sheets, filming notices), later highlights | shared with `notify` | |
| `notify` | Notifications, web push, email | shared with `media` | |
| `imports` | CSV/XLSX and API imports | shared with `content` | |
| `periodic` | Scheduled tasks | scheduler process | |

## Jobs

| Job | Module | Trigger | Idempotency key | Retries |
| --- | --- | --- | --- | --- |
| `extract_setup(session_id)` | setup | Files uploaded | session_id + files hash | 2 |
| `generate_draw_and_schedule(session_id, draft_version)` | setup | Draft ready / answers / redraw | session_id + draft_version + seed | 1 |
| `publish_setup_followups(tournament_id)` | setup | Publish | tournament_id | 3 |
| `reschedule_preview(tournament_id, change_id)` | setup | Delay / change requested | change_id | 1 |
| `recalc_live(match_id, seq)` | analysis | Each event | match_id + seq (skip if newer processed) | 2, 1 s |
| `write_commentary(match_id, seq, moments)` | content | Moment detected (scoring), full time; re-deferred to the end of the 45 s window | match_id + seq (a line covering a later seq makes it a no-op) | 0 |
| `recalc_tournament(tournament_id, reason)` | analysis | Result, finish, correction, rule version, schedule change | tournament_id + source_version | 3, 5 s |
| `update_ratings(match_id)` | analysis | Match finished | match_id | 3 |
| `compute_predictions(tournament_id)` | analysis | After ratings update; bracket resolved; prematch build | tournament_id + ratings version | 3 |
| `analyse_match(match_id)` | analysis | Match finished | match_id + last_seq | 3 |
| `build_comparisons(match_id)` | analysis | Fixture teams known | match_id + inputs hash | 3 |
| `write_story(subject_type, subject_id, kind, tournament_id?)` | content | Deferred by `recalc_tournament`: knockout teams known (preview), match analysed (report), team out (team_recap), final analysed (summary) | subject + kind + fact sheet | 3, exponential |
| `write_explanation(subject, kind)` | content | Scenario/prediction/relevance changed | subject + version | 2 |
| `draft_announcement(tournament_id, kind, ref)` | content | Result (deferred by `recalc_tournament`); schedule change and next up later | tournament + kind + ref | 2 |
| `prepare_live_context(match_id)` | content | Fixture teams known | match_id + inputs hash | 2 |
| `extract_rules(rulebook_id)` | rules | Rulebook uploaded outside setup | rulebook_id | 2 |
| `generate_rule_tests(rule_config_id)` | rules | Draft saved | config id + version | 2 |
| `render_card(subject, kind)` | content | Story published, result, qualification | subject + version | 3 |
| `render_printables(tournament_id)` | media | Publish, schedule version | tournament_id + plan version | 3 |
| `notify_followers(event)` | audience | Match start, goal, result, scenario/relevance change, schedule change, next opponent, story | notification key | 3 |
| `send_email(message)` | audience | Login links, invites, team schedule links, digests | message id | 5 |
| `run_import(import_job_id)` | integrations | Import requested | import id | 1 |

**Coalescing:** recalculation jobs check `source_seq`/`source_version` first and exit if a newer version exists. Bursts during a busy match day therefore cost one or two recalculations per tournament, not dozens.

**Rolling builds (short tournaments):** as soon as a knockout placeholder resolves or a group round finishes, `build_comparisons`, `compute_predictions`, `write_story(preview)` and `prepare_live_context` run for the newly determined fixtures — there is no "evening before" in a 3-day cup.

## Scheduled tasks (periodic queue)

| Task | Schedule | Does |
| --- | --- | --- |
| `prematch_build` | Every 10 min | Safety sweep: matches starting in the next 26 h whose builds are missing or stale |
| `match_reminders` | Every 5 min | "Starts in 1 hour / 15 min" to followers |
| `lifecycle_transitions` | Every 5 min | `upcoming → active`, `active → finished`, `finished → archived` |
| `schedule_drift_check` | Every 2 min on active tournaments | Compare actual vs planned start per pitch; surface "running late" to the organiser console with a suggested delay |
| `stale_live_check` | Every 5 min | Live matches with no event for 2× match length → nudge scorer/organiser |
| `unscored_check` | Every 5 min on active tournaments | Matches past planned end without result → organiser console + one push |
| `consistency_check` | Nightly 03:00 | Rebuild a sample of snapshots from events and compare |
| `cleanup` | Nightly 03:30 | Expired tokens, invites, passes, old notifications, LLM cache, unverified sign-up intents (24 h), intake files past retention |
| `weekly_digest` | Mondays 08:00 Europe/Helsinki | Optional email for followed teams with activity |

## Failure handling

- Structured error logs with ids; Sentry captures exceptions.
- Exhausted retries → failed state; `POST /admin/jobs/{id}/retry` and a dashboard.
- Setup failures surface to the organiser with a plain reason and the guided-form fallback.
- Alerts: queue age > 30 s on `engine`, > 2 min on `setup`, > 5 min on `content`; failed jobs > 10 in 15 min.
