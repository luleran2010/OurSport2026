# 12 — Automatic tournament setup

Goal: an organiser uploads **the rules** and **the list of teams** and gets a complete, fair, ready-to-publish tournament — groups, seeding, schedule over days and pitches, knockout bracket, rule config — with **no manual data entry**. The organiser's only work is answering a handful of questions (often none) and tapping *Publish*.

Principle (golden rule 2): **AI proposes, the engine decides, the organiser publishes.**

| Who | Does | Never does |
| --- | --- | --- |
| LLM (via `core.llm`) | Reads documents; extracts rules, format, teams, seeding instructions, schedule constraints; chooses policies **from the catalogue** where rules are silent; writes plain-language explanations | Draws groups, places teams, sets times, invents rules, outputs anything not tied to a source quote or a catalogue default |
| Engine (`engine/`) | Validates the format; ranks teams into pots; runs the constrained random draw from a stored seed; builds round-robin fixtures, bracket and schedule; checks every constraint | Reads documents, calls the LLM |
| Organiser | Answers open questions, optionally redraws or tweaks, taps *Publish* | Types teams, groups or fixtures by hand (possible but never required) |

## Flow

```
 1 Intake            2 Extract (AI)            3 Fill gaps           4 Match history
 rules, teams,  ──▶  rules_extract,       ──▶  policy catalogue ──▶  previous editions,
 history, venue      teams_extract,            → assumptions         team_aliases
                     seeding_extract                                       │
                                                                           ▼
 8 Publish      ◀──  7 Review (organiser)  ◀── 6 Schedule (engine) ◀── 5 Draw (engine)
 one transaction     ≤ 5 questions,            days × pitches ×          pots, separation,
 → live pages        redraw, tweak             times, rest, bracket      seeded, reproducible
```

Status of a `setup_session`: `intake → extracting → needs_answers → drawing → ready → published` (or `failed` with a reason; the guided form is always available as fallback).

Time budget: steps 2–6 complete in **< 2 minutes** for 32 teams; the organiser sees progress live.

## 1. Intake

| Input | Accepted forms | Required |
| --- | --- | --- |
| Rulebook | PDF, DOCX, TXT, URL, photo(s) of a printed page, pasted text | Recommended (without it: catalogue defaults for everything, clearly marked) |
| Team list | XLSX, CSV, pasted text, WhatsApp message paste, photo | Yes |
| History | Last year's final results / placements, or "linked previous edition" if it ran on OurSport | Optional (needed for placement-based seeding) |
| Venue and days | Usually in the rulebook; otherwise a 4-field form: days + times, number of pitches, match length, break | Yes (asked if missing) |

Processing (`core.documents`, `core.redaction`):

- Structured files (XLSX/CSV) are parsed **deterministically first**; the LLM sees only columns it needs (team name, club, group hints). Phone numbers, emails, birth dates and addresses are removed before any LLM call and never stored in setup drafts. Team contact persons are stored only in `competitions` with the organiser as controller (see `13-compliance-finland.md`).
- Each file gets a `redaction_report` (counts of removed fields, never the values).
- Files are stored in object storage with retention tied to the tournament (archived + 1 year).

## 2. Extraction (LLM tasks, structured output)

| Task | Output model (in `setup.schemas`) |
| --- | --- |
| `rules_extract.v1` | `RuleConfig` draft (points, tiebreakers, match length, extra time, penalties, walkover, fair play) mapped onto presets + overrides |
| `format_extract.v1` | `FormatSpec`: number and size of groups, advancement (top N, best thirds), knockout shape, third-place match, crossover pattern |
| `teams_extract.v1` | Team list: name, short name, organisation, age group, group hints ("host team in Group A") |
| `seeding_extract.v1` | `SeedingPolicy`: seeding source (previous placement, rating, none), pots, separation constraints ("last year's quarter-finalists in different groups", "two teams from the same club apart"), fixed placements |
| `schedule_extract.v1` | `SchedulePolicy`: days and daily windows, pitches, match duration, breaks, minimum rest, max matches per team per day, fixed slots (opening match, final time), prayer/meal breaks |

Every extracted value carries `{value, source_quote, confidence}`. Rules:

- A value without a source quote is not "extracted"; it must come from step 3 as an assumption.
- Low confidence or contradictory quotes → the usual setting is kept and recorded as an **assumption** with the AI's doubt as the reason (`documents.<field>`), so the organiser sees it on Review.
- Ambiguous team names ("Tigers" vs "Tigers FC") → merged only if the organiser confirms; shown as a question with both rows.

**Implementation (T-024):** `setup.team_lists` parses tables, pasted lists and WhatsApp exports deterministically (header words in fi/en/bn); only photos and unparseable lists go to `teams_extract.v1`. `setup.extraction.build_draft` runs the four rulebook tasks, fills gaps from the catalogue (`format_auto`, presets), maps keep-apart rules onto `Separation`s, matches history names by normalised alias (near matches are noted, not used), then **completes the draft without asking**: validation issues with one sensible answer are fixed (points first in the tiebreakers, pitch time long enough for a match, last group round not simultaneous on too few pitches, enough matches per team per day, unsatisfiable separations dropped), teams-through that cannot fill a bracket fall back to the nearest that can (top 2 when unsure), and a trial draw and schedule (`fit`) adds pitches until every match fits; playing times and match length are kept. Every fix is an assumption. The only open question left after extraction is a team list with fewer than 2 teams; anything the engine still cannot settle (rare) stays a question. Edits the organiser makes on Review are taken as given: what no longer fits after them is asked, not fixed. Extraction runs inline until the job queue (T-031). The eval set in `tests/setup/eval_set/` (9 cases, fi/en/bn, photo, WhatsApp, contacts, prompt injection) uses recorded model answers, so it tests everything around the model; a live-model run is a follow-up.

## 3. Filling gaps: the policy catalogue

When the rules are silent, the AI may only **choose from a closed catalogue** of fair, internationally used practices implemented in `engine/rules/` (presets). Each choice is stored as an `assumption {field, chosen, catalogue_id, reason, alternatives}` and shown to the organiser in plain words ("Your rules don't say how ties are broken; we used goal difference first, as most leagues do.").

| Area | Catalogue (default first) | Used internationally by |
| --- | --- | --- |
| Group format for N teams, D days, P pitches | Groups of 4 (top 2 advance) → QF/SF/F; groups of 3 or 5 when N doesn't divide; best-third-placed teams when needed for a power-of-two bracket | FIFA/UEFA tournaments, youth cups |
| Seeding source | 1) previous edition placement; 2) OurSport rating; 3) unseeded random draw | UEFA pots, World Cup pots |
| Pots | One pot per group position: pot 1 = top seeds (one per group), pot 2 = next, … | UEFA / FIFA pot system |
| Separation | Previous semi-finalists (or quarter-finalists if groups ≥ 8) in different groups; same-organisation teams apart; host team fixed in Group A | UEFA country protection, FIFA confederation separation |
| Round-robin order | Berger tables (circle method); in each group, the **last round kicks off simultaneously** | FIFA/UEFA simultaneous final group matches |
| Bracket crossover | A1–B2, B1–A2, C1–D2, D1–C2; group winners kept apart until the semi-final where possible | World Cup / Euro brackets |
| Tiebreakers | `football_gd_first` for leagues; `football_h2h_first` for short tournaments | Leagues vs UEFA tournaments |
| Knockout draws | Penalties directly (no extra time) when the day is tight; extra time + penalties for the final if time allows | Common youth/community practice |
| Rest | ≥ 1 match slot between a team's matches; ≥ 60 min if match length ≥ 40 min; max 3 matches per team per day (junior: 2 for U12 and younger) | Youth tournament guidelines |
| Walkover | 3–0, points to the opponent | Football default |

The catalogue is versioned (`policy_catalogue_version`) so a published tournament always records which defaults it used.

## 4. Matching history (seeding data)

- If the tournament belongs to a **series** with a previous edition on OurSport, `analysis.final_placements` gives each team's placement (1, 2, 3–4 = semi-finalist, 5–8 = quarter-finalist, …).
- If history is uploaded (e.g. "2025: winner X, runner-up Y, semi-finalists Z, W"), it is extracted like rules, with source quotes.
- Team identity across years uses `team_aliases` (exact → normalised → fuzzy match). Fuzzy matches below the threshold are noted as assumptions and not used for seeding.
- New teams have no placement; they go into the lowest pots (or are ranked by rating if they have OurSport history elsewhere).

## 5. Draw (engine)

`engine.draw.make_draw(teams, format, seeding, *, seed) -> Draw`

1. **Rank** teams by the seeding source; build pots of size = number of groups.
2. **Place** fixed teams (e.g. host in Group A).
3. **Assign.** The engine samples **uniformly among all complete assignments that satisfy every constraint** (exact enumeration when there are at most 2,000 valid draws, rejection sampling otherwise; a randomised search flagged `uniform=false` only if the rules make a uniform draw impractical), so the draw cannot be biased by the order of drawing — avoiding the known flaw of sequential "skip to next valid group" draws.
4. **Infeasible** constraints (e.g. 6 semi-finalist-separations into 4 groups) → result `infeasible` with the minimal conflicting set, turned into one organiser question ("6 teams must be kept apart but there are only 4 groups. Keep apart only last year's top 4?").
5. Output: groups, pots, constraints checked, `seed`, `engine_version`, and an explanation per team ("Pot 1 as 2025 runner-up; kept apart from the other 2025 semi-finalists").

Fairness and trust:

- `seed` is generated from a CSPRNG at draw time and stored; the engine's own SHA-256-based generator means anyone with the inputs can reproduce the draw exactly, on any platform.
- **Live draw mode (optional):** the organiser can run the draw on the venue screen or a livestream; the engine still computes the result from the seed, the screen reveals it pot by pot. Gives the event a ceremony and the bragging rights of a "real" draw.
- **Redraw** creates a new draw with a new seed; previous draws are kept for audit. After publish, a redraw requires an explicit confirmation and notifies teams.

## 6. Schedule (engine)

`engine.bracket.build_bracket(format) -> Bracket` — knockout matches with **placeholders** (`group:A:1`, `group:B:2`, `best_rest:1`, `winner:QF1`, `loser:SF1`).

`engine.schedule.build_schedule(groups, bracket, policy, *, seed) -> SchedulePlan`

- Inputs: slots = days × daily windows × pitches × (match length + break); constraints from `SchedulePolicy`.
- Hard constraints: no team in two places at once; minimum rest; max matches per team per day; group stage before the knockout matches that depend on it; simultaneous last group round; fixed slots (opening match, final); breaks (prayer, meals) kept free.
- Soft objectives (weighted, in order): finish group stage by the configured day; balance early/late kick-offs and pitch usage per team; minimise idle gaps for teams; put the final in the best slot (main pitch, last slot of the last day).
- Algorithm: Berger round-robin per group → greedy slot assignment ordered by constraint tightness → local search (swap/shift) to improve soft objectives; deterministic for a given seed. Returns `quality {hard_violations: 0, rest_min, gaps, pitch_balance}`.
- Infeasible (too many matches for the time available) → question with concrete options computed by the engine (`suggest_relaxations`, and `format_auto` for smaller groups): "add a pitch", "shorten matches to 2×15", "groups of 3", "start 1 h earlier".

**Implementation (T-034):** `setup.matchday` previews a change with the engine's `reschedule` (frozen until the injectable clock's now) as a proposed `schedule_plans` row, then confirms it: `competitions.apply_schedule` moves matches (new `schedule_version`), records walkovers (sport walkover score) and withdrawals, defers `notify_followers(kind=schedule_change, team_ids)` and `recalc_tournament`. Published plans keep the full engine plan and the draft-key → team-id map. The console shows now/next per pitch, minutes late and unscored matches; `lifecycle_transitions` runs every 5 minutes.

**Rescheduling during the tournament:** `engine.schedule.reschedule(plan, frozen_until, changes)` — keeps finished and running matches fixed, shifts the rest ("pitch 2 is running 20 min late", "pitch 4 closed", "team withdrew → walkovers"). Used by the match-day console; changes are published as a new plan version and pushed to followers.

## 7. Review (organiser)

One screen, readable on a phone:

1. **Summary:** "16 teams · 4 groups of 4 · QF/SF/Final · 3 days · 4 pitches · 31 matches (32 with a third-place match)"
2. **Groups** with each team's seeding reason.
3. **Schedule** by day and pitch; tap a team to see its matches.
4. **Rules in plain words** (from `rules/summary`) with source quotes.
5. **Assumptions** (where we filled gaps) — each can be changed with one tap from its alternatives.
6. **Open questions** (≤ 5, ordered by impact). *Publish* is disabled until all are answered.
7. Actions: *Redraw*, *Regenerate schedule*, *Move a match*, *Publish*.

The organiser's answers and edits are stored as decisions on the setup draft (audit), and the engine re-validates after every change.

**Implementation (T-025):** `setup.review` applies answers and edits (`schedule.days` as `HH:MM-HH:MM`, `schedule.pitches`, `rules.tiebreakers`, team merges, history matches, an engine relaxation for `schedule`) and re-validates. Engine validation issues are questions marked `ref.issue` (the issue code). Where one answer fixes an issue, the question names that field and offers it as options (a tiebreaker order that does not start with points: `rules.tiebreakers` with `goal difference` / `head-to-head`; a match longer than the pitch time: `schedule.match_minutes` with the minutes the rules need). Other issues are not settled by a text answer; after every answer or change they are checked again, so they stay open until a change to the draft (usually the whole `schedule`) fixes them. A change to a field also settles the questions about its parts (`schedule` settles `schedule.days`). Once nothing is open the engine draws (CSPRNG seed, stored in `draws`) and schedules (`schedule_plans`, same seed). Moving a match adds a fixed slot and rebuilds around it. Drafts carry a version used with `If-Match`.

## 8. Publish

`POST /setup/{id}/publish` (If-Match on the draft version), in one transaction:

- Writes groups, `tournament_teams`, matches (with pitch and time), confirmed `rule_configs` version 1 (organiser = confirmer), bracket placeholders.
- Creates staff roles, one **scorer pass + QR** per pitch, a printable **pitch sheet** (QR + schedule) and a **filming notice** (see `13-compliance-finland.md`). Implementation: publish emits `TournamentPublished(tournament_id, pitch_ids)`; scoring creates the passes (T-030); the printables arrive with the passes (T-030) and the compliance flows (T-061).
- Tournament status `draft → upcoming`; public tournament page, share link and team invite links become available.
- Enqueues `recalc_tournament`, `prematch_build`, `notify_teams` (each team's contact gets their schedule link).

## Edge cases

| Case | Behaviour |
| --- | --- |
| No rulebook at all | Full catalogue defaults, all marked as assumptions; organiser sees "We used standard rules" |
| Odd number of teams / not divisible by group size | Catalogue picks mixed group sizes; tiebreak across groups of different sizes uses points per game (marked as assumption) |
| Rules contradict each other | Usual setting kept, recorded as an assumption with the AI's doubt |
| Team list has duplicates or typos | Merge suggestions as questions |
| Team withdraws after publish | Walkover rule applied to its remaining matches; `reschedule` frees slots |
| Late entry after publish | Organiser adds team → engine proposes placement in the smallest group without breaking constraints; republish |
| LLM unavailable | Guided form with the same fields; deterministic CSV/XLSX parsing still works; draw and schedule are unaffected |
| Junior tournament | Extraction marks `is_junior`; defaults: `show_probabilities = false` for U12 and younger, rest limits for juniors, players hidden by default |

## Testing

- Extraction: an evaluation set of real-style rulebooks and team lists (anonymised, in fi/en/bn) under `tests/setup/eval_set/` with expected drafts; unclear rules must become recorded assumptions the organiser can see and change.
- Draw: property tests — every constraint holds; reproducible for the same seed; uniformity check (chi-square over 10k seeds on a small instance); infeasibility reports a minimal conflicting set.
- Schedule: property tests — no double booking, rest respected, dependencies ordered, simultaneous last rounds; performance: 32 teams, 3 days, 6 pitches < 5 s.
- End-to-end: upload sample files → publish → seeded matches appear → scoring a full group fills the bracket placeholders.
