# 03 — Data model

## Conventions (all tables)

- **Primary key:** `id UUID` (UUIDv7, generated in the app via `app.core.ids.new_id()`). Exposed in the API as a string.
- **Timestamps:** `created_at timestamptz not null default now()`, `updated_at timestamptz not null` (set by the app). Always UTC.
- **Soft delete:** `deleted_at timestamptz null` only on `stories`, `organisation_members`, `teams`. Personal data is hard-deleted on account deletion.
- **JSONB payloads:** each JSONB column has a Pydantic model in the owning module's `schemas.py` and a `schema_version` key inside the JSON.
- **Read models:** carry `version int`, `source_seq bigint` (or `source_version`), `computed_at timestamptz`.
- **Enums:** stored as `text` with a `CHECK` constraint (easier migrations than Postgres enums).
- **Foreign keys:** always declared; `ON DELETE RESTRICT` by default, `CASCADE` only for pure child rows.
- **Naming:** plural snake_case tables, `<table>_id` foreign keys, indexes `ix_<table>_<cols>`, unique `uq_<table>_<cols>`.

## accounts

| Table | Columns | Notes |
| --- | --- | --- |
| users | id, email (citext, unique), display_name, language (`fi`/`en`/`bn`), time_zone, birth_year_confirmed_13_plus bool, privacy_accepted_at, email_verified_at, created_at, updated_at, deleted_at null (anonymous tombstone after `DELETE /me`), preferences jsonb (`analytics_cookies`, `marketing_emails`, `updated_at`) | No passwords (magic link). Accounts are for people aged 13+ (see `13-compliance-finland.md`) |
| signup_intents | id, email (citext), display_name, language, time_zone, follow_target jsonb null, login_token_id, created_at, expires_at | Pending sign-up until the magic link is opened; deleted after 24 h |
| login_tokens | id, user_id null (null for a sign-up), token_hash (unique), purpose (`login`, `verify`), created_at, expires_at, used_at | Single use, 15 min |
| passkeys | id, user_id, credential_id, public_key, sign_count, created_at | Optional WebAuthn |
| sessions | id, user_id, refresh_token_hash, user_agent, created_at, last_used_at, revoked_at | Rotating refresh tokens |
| user_roles | user_id, role (`editor`, `platform_admin`) | Global roles only |
| family_links | user_id, player_id, created_by, created_at | Parent/guardian ↔ junior player |

## competitions

| Table | Columns | Notes |
| --- | --- | --- |
| sports | code (`football`, `ice_hockey`; later `floorball`, `futsal`, `volleyball`, `cricket`), name, event_types jsonb | Seeded; drives scorer UI and engine module |
| organisations | id, kind (`club`, `association`, `school`, `community`), name, slug, town, sports text[], logo_url, colors jsonb, sponsors jsonb, created_at | Hosts tournaments and/or owns teams. GDPR controller for the participant data it uploads |
| processing_agreements | id, organisation_id, version, accepted_by, accepted_at | Data processing terms accepted before the first setup (OurSport = processor) |
| tournament_series | id, organisation_id, name, slug, sport, created_at | "FinBangla Cup"; links editions for history and seeding |
| tournaments | id, series_id null, edition_label, name, slug, sport, season, organisation_id, status (`draft`, `upcoming`, `active`, `finished`, `archived`), starts_on, ends_on, time_zone, age_group (`adult`, `u19`…`u9`), is_junior bool, settings jsonb, rule_config_id null, format_spec jsonb null, policy_catalogue_version | `settings`: languages, show_probabilities (default false for U12 and younger, set in `create_tournament`), live_access (`public`, `members`, `premium`), publisher_review, filming_policy |
| tournament_staff | tournament_id, user_id, role (`owner`, `organiser`, `scorer`) | Replaces `tournament_publishers`; owner/organiser can publish and manage match day |
| groups | id, tournament_id, name, order | |
| teams | id, organisation_id null, name, short_name, age_group, contact_name null, contact_email null, contact_phone null, created_at | Contact fields only for organiser use; never sent to the LLM; never public |
| team_aliases | team_id, alias_normalised, source (`setup`, `organiser`, `import`), created_at | uq(alias_normalised, team_id); matching across editions |
| tournament_teams | tournament_id, team_id, group_id null, seed int null, pot int null, seeding_reason jsonb null, withdrawn_at null | |
| players | id, team_id, display_name, shirt_number null, birth_year null, visibility (`public`, `family_only`, `hidden`), created_at | Juniors default `hidden` |
| consents | id, player_id, guardian_user_id null, guardian_contact, scope (`profile`, `stats`, `filming`), granted_at, withdrawn_at | |
| venues | id, name, town, lat, lon, notes | |
| pitches | id, venue_id, name, order, is_main bool | |
| lots_draws | id, tournament_id, group_id null, order jsonb (team ids as drawn), drawn_by null, created_at | A drawing of lots the organiser held for teams nothing else separates (`resolveLots`); a later draw for the group replaces an earlier one. Index on tournament_id (migration 0022) |
| matches | id, tournament_id, group_id null, stage (`group`, `round_of_16`, `quarter_final`, `semi_final`, `third_place`, `final`), code (`A3`, `QF1`), round, home_team_id null, away_team_id null, home_source text null, away_source text null, venue_id null, pitch_id null, starts_at, schedule_version, status (`scheduled`, `live`, `finished`, `postponed`, `cancelled`, `walkover`), data_level (`results`, `events`), result jsonb null, last_seq bigint default 0 | Knockout teams null until resolved from `*_source` placeholders (`group:A:1`, `best_rest:2`, `winner:QF1`, `loser:SF1`) |

## subscriptions

| Table | Columns | Notes |
| --- | --- | --- |
| organisation_members | id, organisation_id, user_id, role (`member`, `scorer`, `admin`), status (`invited`, `active`, `removed`), joined_at | uq(organisation_id, user_id) |
| seats | id, organisation_id, total int, period_start, period_end | Bought premium seats per period |
| entitlements | id, user_id, kind (`premium`, `event_pass`), source_organisation_id, tournament_id null, valid_from, valid_until, revoked_at | `event_pass` = access bought per tournament |
| invites | id, organisation_id, email, role, grant_premium bool, token_hash, expires_at, accepted_at, created_by | Token stored hashed |
| billing_customers | organisation_id, provider, provider_customer_id, status | Payment provider reference only |

## integrations

| Table | Columns | Notes |
| --- | --- | --- |
| import_jobs | id, source (`csv`, `xlsx`, `liiga`, `federation`), tournament_id, status, stats jsonb, errors jsonb, created_by, created_at | |
| external_refs | entity_type, entity_id, source, external_id | uq(source, external_id, entity_type) |

## rules

| Table | Columns | Notes |
| --- | --- | --- |
| rulebooks | id, tournament_id, intake_file_id null, source_url null, text, uploaded_by, created_at | Redacted text |
| rule_configs | id, tournament_id, version int (0 while draft; 1, 2, … on each confirmation), config jsonb, status (`draft`, `confirmed`, `superseded`), confirmed_by, confirmed_at, extraction jsonb | `config` validated by `engine.rules.RuleConfig`; `extraction` holds source quotes, assumptions, open questions |
| rule_tests | id, rule_config_id, kind (`worked_example`, `edge_case`, `golden`), input jsonb, expected jsonb, organiser_verdict (`correct`, `incorrect`, null), passed bool | |

## setup

| Table | Columns | Notes |
| --- | --- | --- |
| setup_sessions | id, tournament_id, status (`intake`, `extracting`, `needs_answers`, `drawing`, `ready`, `published`, `failed`), failure_reason null, organiser_language, created_by, created_at, updated_at | One per setup run |
| intake_files | id, setup_session_id, kind (`rulebook`, `team_list`, `history`, `venue`, `other`), file_url null, source_url null, filename, mime, text_extracted (redacted), rows jsonb null (redacted table cells), image bytea null (photos, until object storage), redaction_report jsonb, created_at | Raw files retained until tournament archived + 1 year |
| setup_drafts | id, setup_session_id, version, draft jsonb, assumptions jsonb, open_questions jsonb, decisions jsonb, status (`draft`, `ready`, `published`, `superseded`), created_at | `draft` = RuleConfig + FormatSpec + SeedingPolicy + SchedulePolicy + teams, each value with source quote and confidence |
| draws | id, tournament_id, setup_draft_id, seed bytea, pots jsonb, constraints jsonb, result jsonb, explanation jsonb, engine_version, status (`proposed`, `published`, `discarded`), revealed int (live draw progress), created_at | Every draw kept for audit; reproducible from seed |
| schedule_plans | id, tournament_id, version, based_on_draw_id, plan jsonb, policy jsonb, quality jsonb, reason (`initial`, `regenerate`, `delay`, `withdrawal`, `manual`), status (`proposed`, `published`, `superseded`), created_at | Plan versions; `matches.schedule_version` points at the published one |

## scoring

| Table | Columns | Notes |
| --- | --- | --- |
| match_events | id, match_id, seq bigint, client_seq bigint, type, payload jsonb, team_id null, player_id null, period, clock, entered_by_user_id null, entered_by_pass_id null, created_at, undoes_seq null | **Append-only.** uq(match_id, seq), uq(match_id, client_seq) |
| live_state | match_id (pk), seq, state jsonb, updated_at | Small row updated in the event transaction |
| scorer_passes | id, tournament_id, pitch_id null, match_id null, label, token_hash, valid_from, valid_until, revoked_at, created_by, created_at | QR-based scoring permission; scoped to a pitch (all its matches that day) or one match |

## analysis (read models)

| Table | Columns | Notes |
| --- | --- | --- |
| standings_snapshots | id, tournament_id, group_id null, version, source_version, provisional bool (live "if it ended now"), rows jsonb, computed_at | Latest non-provisional per group is served |
| analysis_versions | tournament_id (pk), version, source_version (hash of everything read), live_seq jsonb (match → last computed seq), computed_at | Coalescing: unchanged inputs are never recomputed |
| scenario_snapshots | id, tournament_id, team_id, version, scenario jsonb, computed_at | Status, paths, margins, matches remaining, season chances |
| bracket_snapshots | id, tournament_id, version, bracket jsonb, computed_at | Knockout tree with resolved/unresolved placeholders and "could face" sets |
| relevance_snapshots | id, tournament_id, team_id, version, items jsonb, computed_at | "Matches that matter to this team", ranked by impact |
| final_placements | tournament_id, team_id, placement int, stage_reached, computed_at | Feeds seeding of the next edition |
| team_journeys | tournament_id, team_id, version, journey jsonb, computed_at | Per-team story of the tournament: results, moments, position over time |
| ratings | team_id, sport, age_group, rating float, games int, prior_source (`default`, `division`, `seeding`, `history`), updated_after_match_id, updated_at | Current rating |
| rating_history | team_id, match_id, before, after, created_at | Explainability and backtests |
| predictions | match_id (pk), version, home_win_low, home_win_high, draw_low null, draw_high null, away_win_low, away_win_high, confidence (`low`, `medium`, `high`, `none`), factors jsonb, model_version, computed_at | `confidence = none` → no percentages shown |
| team_comparisons | match_id (pk), version, comparison jsonb, computed_at | |
| match_analyses | match_id (pk), version, analysis jsonb, computed_at | |
| player_stats | player_id, tournament_id, stats jsonb, version, computed_at | Visibility rules applied at read time |
| fact_sheets | id, subject_type (`match`, `team`, `tournament`), subject_id, kind (`preview`, `report`, `team_recap`, `summary`), facts jsonb, context jsonb, inputs_hash (unique), created_at | Facts: id, kind, claim, value, unit, source, team_id. One row per distinct input; index (subject_type, subject_id, kind) |

## content

| Table | Columns | Notes |
| --- | --- | --- |
| stories | id, tournament_id, kind (`preview`, `report`, `summary`, `news`, `team_recap`), subject_type, subject_id, language, headline, body, sentences jsonb ([{text, facts}]), fact_sheet_id null, status (`draft`, `in_review`, `published`, `blocked`, `unpublished`), check_result jsonb, author_type (`ai`, `human`), author_user_id null, model, template (`report.v1`), published_at, version, corrected_at null, review_reason null (`blocked_claim`, `sensitive`), reviewed_by null, reviewed_at null, removal_reason null (statement of reasons), created_at, updated_at | AI label derived from `author_type`. uq(subject_type, subject_id, kind, language); ix(tournament_id, published_at). A rewrite keeps the row and bumps `version` |
| story_versions | story_id, version, headline, body, edited_by null, created_at | The text before each rewrite or edit; pk(story_id, version) |
| commentary_items | id, match_id, tournament_id, seq (last event covered), kind (`moment`), moments jsonb, texts jsonb (language → {text, facts}), fact_sheet_id null, check_result jsonb, author_type (`ai`, `template`), reason null (`priority`, `llm_error`, `checker`), created_at | One line per language in `texts`. ix(match_id, created_at) |
| announcements | id, tournament_id, kind (`result`, `schedule_change`, `next_up`, `custom`), ref (match id, …), texts jsonb (language → text), source jsonb (fact sheet, check result), author_type (`ai`, `template`, `human`), status (`draft`, `sent`, `dismissed`), created_by null, created_at, sent_at | Organiser announcements (PA, WhatsApp, venue screen); auto-drafted in every tournament language, one tap to send. uq(tournament_id, kind, ref) |
| share_cards | id, subject_type, subject_id, kind, image_url, version, created_at | |

## editorial

| Table | Columns | Notes |
| --- | --- | --- |
| review_claims | story_id (pk), editor_id, claimed_at | The review queue is the stories with `status = in_review` (and `review_reason` `blocked_claim` or `sensitive`); a claim says which editor has one. Removed on a decision |
| corrections | id, tournament_id, story_id, reported_by null, kind (`mistake`, `privacy`, `illegal`, `other`), text, status (`open`, `fixed`, `rejected`), note null, resolved_by null, created_at, resolved_at null | Readers' reports (notice and action). ix(status, created_at) |
| audit_log | id, actor_id null, actor_pass_id null, action, target_type, target_id, before jsonb, after jsonb, at | Append-only |

## audience

| Table | Columns | Notes |
| --- | --- | --- |
| follows | id, user_id, target_type (`organisation`, `team`, `tournament`, `series`), target_id, is_primary bool, notify jsonb, created_at | uq(user_id, target_type, target_id); `is_primary` = "my team" (at most one per user) |
| notifications | id, user_id, kind, payload jsonb, created_at, read_at | Retained 90 days |
| push_subscriptions | id, user_id, endpoint, keys jsonb, created_at | Web push, one per browser the user enabled |

## media

| Table | Columns | Notes |
| --- | --- | --- |
| streams | id, match_id, tournament_id, provider (`youtube`, `mux`, `cloudflare`, `other`), playback_url, status (`live`, `paused`, `ended`), keep_replay, consent_check jsonb (what was confirmed), rights_confirmed_by null, started_at, ended_at null, created_at | Attached only after the filming check passes; an opt-out pauses live ones. ix(match_id, created_at) |
| filming_notices | id, tournament_id, texts jsonb (language → text), version, published_by null, created_at | The venue notice (QR in printables); a stream needs one |
| filming_attestations | id, tournament_id, statement, attested_by null, created_at | The organiser attests that filming consents were collected offline |
| filming_optouts | id, tournament_id, team_id, player_id null, requested_by null, reason null, created_at, resolved_at null, resolution null | Blocks streams of the team's matches until resolved. ix(tournament_id, resolved_at) |
| highlights | id, match_id, event_seq, start_offset_s, end_offset_s, clip_url | Later |

## Key indexes

- `matches (tournament_id, starts_at)`, `matches (pitch_id, starts_at)`, `matches (home_team_id)`, `matches (away_team_id)`, `matches (status, starts_at)`
- `match_events (match_id, seq)` unique, `(match_id, client_seq)` unique
- `standings_snapshots (tournament_id, group_id, version desc)`
- `scenario_snapshots (tournament_id, team_id, version desc)`, `relevance_snapshots (tournament_id, team_id, version desc)`
- `stories (subject_type, subject_id, published_at desc)` where `status = 'published'`
- `follows (user_id)`, `follows (target_type, target_id)`, unique `follows (user_id) where is_primary`
- `scorer_passes (token_hash)` unique where `revoked_at is null`
- `team_aliases (alias_normalised)`
- `review_items (status, priority, created_at)`
- `organisation_members (user_id)`, `entitlements (user_id, kind) where revoked_at is null`

## Tournament lifecycle

| State | Entered when | Enables |
| --- | --- | --- |
| `draft` | Created by setup | Setup, review; not public |
| `upcoming` | Organiser publishes the setup | Public pages, schedule, previews, predictions, follows, team share links |
| `active` | First match starts (scheduler) | Live features, match-day console, rolling recalculation |
| `finished` | Last match finished | Tournament summary, team recaps, final placements (for next edition), final ratings |
| `archived` | 90 days after finish (scheduler) | Read-only; heavy read models compacted to latest version; raw intake files deleted after a further year |
