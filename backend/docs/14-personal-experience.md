# 14 — The personal experience ("my team, my league")

OurSport should feel like *our* sport: a supporter opens the app and it is about **their** team first, **their** league second, and everything else one tap away. This document defines the personal surfaces and the data behind them. All numbers come from read models (golden rules 1 and 6).

## Accounts: quick to create, required for personal features

Public pages (tournament, live page, standings, bracket, match pages, stories, venue screen, widget) are open to everyone. Everything personal — following, My Team hub, notifications, family features — needs an account (ADR 0012).

| Step | What the user does | What we store |
| --- | --- | --- |
| 1 | Opens a shared link (organiser, team or WhatsApp card) and browses public pages | Nothing |
| 2 | Taps **"This is my team"** → sign-up sheet: email, display name, "I am 13 or older", privacy notice. Language and time zone pre-filled from the browser | Pending sign-up with the intended follow (`signup_intents`), no account yet |
| 3 | Opens the magic link from the email | `user` created and verified; the intended team followed as primary; lands on the My Team hub |
| 4 | (Optional) allows notifications; adds a passkey for one-tap return | `push_subscription`, `passkey` |

Rules: the sign-up sheet asks for nothing else; the team chosen before sign-up is never lost; returning users sign in with a magic link or passkey and land on their hub. Accounts are for people aged 13+ (see `13-compliance-finland.md`); a guardian follows on behalf of a younger child.

## My Team hub (`GET /me/home`)

Composed from read models; a single request, p95 < 300 ms.

| Section | Content | Source |
| --- | --- | --- |
| Header | Team name, colours, organisation, current tournament, position/status chip ("2nd in Group A · alive") | standings, scenarios |
| **Now / next** | Live score if playing; otherwise next match: opponent, pitch, local time countdown | matches, live_state |
| **What we need** | Scenario in plain words ("A draw is enough unless Royals win by 3+") | scenario_snapshots (+ `scenario_explain` text) |
| **Our chances** | Prediction band and reasons; factors only when confidence is `none` or percentages are hidden | predictions |
| **Who we could face** | Knockout path: next opponent or `could_be` list | bracket_snapshots |
| **Matches that matter to us** | Other fixtures ranked by impact, with why | relevance_snapshots |
| **Our journey** | Results so far, key moments, position over time, scorers (visible players only) | team_journeys |
| **Head-to-head & history** | Previous editions: best finish, last meetings with today's opponent | final_placements, comparisons |
| **Stories** | Preview of the next match, report of the last one, team recap | stories |
| **The league** | Compact table with my team highlighted; link to the full tournament | standings |

Everything else (all groups, bracket, every match, live page) is one tap from the hub; the personal view never hides the full tournament.

**Implementation (T-040):** the hub is built by `analysis.service.team_hub` (read models only; players through the visibility filter) and served by `audience` at `/me/home` and `/me/teams/{id}/hub` (`private, no-store`). The intended follow of a sign-up becomes the primary follow through the `UserSignedUp` event. `/me/feed` (cursor paged) and the public `/tournaments/{id}/feed` list results, live matches and the next match. Chances and stories join the hub with T-042 and T-052. The `members` live policy stays "any signed-in user": follows live in `audience`, which depends on `analysis`, so the policy cannot read them without a cycle.

## Personal notifications

Defaults for a primary team (each togglable):

| Kind | Example | Trigger |
| --- | --- | --- |
| `match_start` | "Tigers kick off now on pitch 3" | match started |
| `goal` (opt-in) | "GOAL Tigers! 1–0" | goal event (live access permitting) |
| `result` | "Full time: Tigers 2–1 Royals. You're top of Group A." | match finished |
| `scenario_change` | "Tigers need just a draw in the last game" | scenario status/paths changed |
| `relevance` | "Royals vs Lions now matters for you: a Lions win helps Tigers" | relevance impact above threshold for a live/next fixture |
| `schedule_change` | "Your 15:40 match moved to 16:00, pitch 2" | reschedule confirmed |
| `next_opponent` | "Quarter-final: Tigers vs Eagles, Sunday 11:20, main pitch" | bracket placeholder resolved |
| `news` | "Match report is ready" | story published |

Rules: at most one notification per team per 5 minutes except `match_start`, `result` and `schedule_change`; quiet hours in the viewer's time zone (22–08) except for `schedule_change` within the next 2 hours; language = the user's language.

**Implementation (T-041):** `audience.notifications` turns `notify_followers` jobs into notifications (templates in fi/en/bn, never the LLM); triggers: match start and result (scoring), schedule change (setup), scenario change, relevance (top impact ≥ 0.3, new) and next opponent (analysis, after the first computation). Delivery: web push with VAPID (`VAPID_PRIVATE_KEY`; unset → in-app only) and, without a push subscription, email for schedule changes. `match_reminders` runs every 5 minutes (1 h and 15 min before). Endpoints: `/me/notifications`, `/me/notifications/read`, `/me/push-subscriptions`. Audience may call accounts (language, time zone, email).

## Language and time

- Content language: the user's language (or, on public pages, the browser's) if the tournament supports it, otherwise the tournament's first language; team names never translated.
- Times are always shown in the viewer's time zone, with the venue's local time as a secondary label for viewers abroad ("17:20 Dhaka · 14:20 at the venue").

## Families

- A guardian linked to a junior player (`family_links`) sees that player's own stats and moments even when the player is `family_only`; the public never does.
- The hub can highlight "your player" moments to the guardian only.

## Engagement beyond the tournament

- When a tournament finishes: team recap story and share card ("Semi-finalists at FinBangla Cup 2026").
- The series page keeps history; next year's edition invites last year's followers ("FinBangla Cup 2027 schedule is out — Tigers are in Group C").
- Follows of a team carry over to the team's next tournament automatically.

## Read models added for personal features

| Read model | Built by | When |
| --- | --- | --- |
| `relevance_snapshots` | `recalc_tournament`, `recalc_live` (live deltas only, not stored per event) | Every result; live stakes per event |
| `team_journeys` | `recalc_tournament` | Every result |
| `bracket_snapshots` | `recalc_tournament` | Every result |
| `final_placements` | `recalc_tournament` on finish | Tournament finished |

## Privacy guardrails for personal features

- Follows are personal data: never exposed to other users; deleted with the account; unverified sign-up intents are deleted after 24 h.
- The hub never shows hidden players; scorers' lists come from the visibility-filtered repository.
- "Most followed teams" or audience numbers are shown only as aggregates (≥ 10) to organisers.
