# 04 — The engine (pure calculation library)

`engine/` produces every number and every structural decision the product shows: standings, tiebreakers, **draw, schedule, bracket**, scenarios, season chances, ratings, predictions, comparisons, relevance and match analysis. It is the product's credibility, so it is pure, deterministic and heavily tested.

## Hard constraints

- No imports from `app/`, no database, no network, no file I/O, no `datetime.now()`, no global random state.
- Inputs and outputs are frozen dataclasses (or Pydantic models) defined in `engine/model.py` and `engine/rules/`.
- Same input → same output, always. Randomised algorithms take an explicit `seed` (draws: a stored CSPRNG seed; simulations: a hash of the input).
- Every public function has unit tests; core invariants have Hypothesis property tests; real tournaments have golden tests.
- `mypy --strict` must pass on `engine/`.

## Core data types (`engine/model.py`)

```python
@dataclass(frozen=True)
class TeamRef:
    id: str
    name: str

@dataclass(frozen=True)
class MatchResult:            # a finished (or hypothetical) match
    match_id: str
    group_id: str | None
    home: str                 # team id
    away: str
    outcome: SportResult      # sport-specific, see sports/
    walkover: bool = False

@dataclass(frozen=True)
class Fixture:                # a match not yet played
    match_id: str
    group_id: str | None
    home: str | None          # None while a knockout placeholder is unresolved
    away: str | None
    home_source: str | None   # "group:A:1", "winner:QF1" (placeholder grammar below)
    away_source: str | None
    starts_at: str            # ISO string, used only for ordering

@dataclass(frozen=True)
class TournamentState:
    teams: tuple[TeamRef, ...]
    groups: dict[str | None, tuple[str, ...]]   # group id -> team ids
    results: tuple[MatchResult, ...]
    fixtures: tuple[Fixture, ...]
    rules: RuleConfig
    format: FormatSpec
```

## Rule configuration (`engine/rules/`)

### `RuleConfig` (`config.py`)

```python
class PointsRule(BaseModel):
    table: dict[str, int]            # football: {"win": 3, "draw": 1, "loss": 0}

class Tiebreaker(str, Enum):
    POINTS = "points"
    POINTS_PER_GAME = "points_per_game"             # comparing across groups of different sizes
    WINS = "wins"
    HEAD_TO_HEAD_POINTS = "head_to_head_points"
    HEAD_TO_HEAD_DIFF = "head_to_head_diff"
    HEAD_TO_HEAD_FOR = "head_to_head_for"
    SCORE_DIFF = "score_diff"
    SCORE_FOR = "score_for"
    AWAY_SCORE_FOR = "away_score_for"
    FAIR_PLAY = "fair_play"
    DRAW_LOTS = "draw_lots"                         # last resort; engine reports "undecided"

class AdvancementRule(BaseModel):
    per_group: int
    best_of_rest: int = 0
    rest_ranking: list[Tiebreaker] = []
    promotion: int = 0
    relegation: int = 0

class RuleConfig(BaseModel):
    schema_version: int = 1
    sport: str
    format: Literal["round_robin", "double_round_robin", "groups_then_knockout", "knockout"]
    points: PointsRule
    tiebreakers: list[Tiebreaker]
    head_to_head_reapply: bool = True
    advancement: AdvancementRule
    standings_visible: bool = True
    match: dict[str, Any]
    walkover: dict[str, Any]
    fair_play_points: dict[str, int] = {"yellow": 1, "second_yellow": 3, "red": 3}
```

### `FormatSpec` (`format.py`)

```python
class KnockoutSpec(BaseModel):
    rounds: list[Literal["round_of_16", "quarter_final", "semi_final", "final"]]
    third_place_match: bool = False
    crossover: Literal["standard", "custom"] = "standard"   # A1-B2, B1-A2, …
    custom_pairs: list[tuple[str, str]] = []               # e.g. ("group:A:1", "best_rest:2")
    draws_decided_by: Literal["penalties", "extra_time_then_penalties"] = "penalties"
    final_draws_decided_by: Literal["penalties", "extra_time_then_penalties"] | None = None

class FormatSpec(BaseModel):
    team_count: int
    group_sizes: list[int]             # [4, 4, 4, 4] or [4, 4, 3]
    group_rounds: Literal[1, 2] = 1    # single or double round robin
    knockout: KnockoutSpec | None
```

**Placeholder grammar** for knockout slots not yet decided: `group:A:1` (1st in group A), `best_rest:2` (2nd-best team ranked across groups, e.g. best thirds), `winner:QF1`, `loser:SF1`. Match codes: group matches `A1`…, knockout `R16_1`…, `QF1`–`QF4`, `SF1`, `SF2`, `3P`, `F`. Builders: `groups_then_knockout(...)`, `league(n, double=)`, `knockout_only(n)` return a `FormatChoice(format, advancement)`.

### `SeedingPolicy` (`seeding.py`)

```python
class SeedingSource(str, Enum):
    PREVIOUS_PLACEMENT = "previous_placement"
    RATING = "rating"
    ORGANISER_ORDER = "organiser_order"
    NONE = "none"

class Separation(BaseModel):            # teams in `teams` must all be in different groups
    kind: Literal["distinct_groups", "max_per_group"]
    teams: list[str]
    max_per_group: int = 1
    reason: str                         # "2025 semi-finalists", "same club"

class FixedPlacement(BaseModel):
    team: str
    group_index: int
    position_in_group: int | None = None

class SeedingPolicy(BaseModel):
    source: list[SeedingSource]         # in priority order; fallback for teams without data
    pots: Literal["by_group_position", "none"] = "by_group_position"
    separations: list[Separation] = []
    fixed: list[FixedPlacement] = []
```

### `SchedulePolicy` (`schedule_policy.py`)

```python
class DayWindow(BaseModel):
    date: dt.date                   # local date
    start: dt.time                  # local time the first match may start
    end: dt.time                    # local time the last match must end by
    utc_offset_minutes: int         # computed by the app from the time zone (see below)
    blocked: list[tuple[dt.time, dt.time]] = []   # prayer / meal breaks

class FixedSlot(BaseModel):
    match_code: str                 # "A1", "F"
    date: dt.date
    start: dt.time
    pitch: str | None = None

class SchedulePolicy(BaseModel):
    time_zone: str                  # "Europe/Helsinki"; informational for the engine
    days: list[DayWindow]
    pitches: list[str]              # pitch ids; first = main pitch
    match_minutes: int
    break_minutes: int              # between matches on the same pitch
    min_rest_minutes: int
    max_matches_per_team_per_day: int
    simultaneous_last_group_round: bool = True
    group_stage_ends_by_day: int | None = None
    fixed_slots: list[FixedSlot] = []
    final_on_main_pitch_last_slot: bool = True
```

The engine never reads time-zone data (that would be file I/O): each `DayWindow` carries its UTC offset, computed by the app from `time_zone`. A per-day offset also covers a daylight-saving change during a tournament. Slots per pitch per day: each free segment (window minus blocked breaks) fits `(length + break) // (match + break)` matches.

Validation (`engine/rules/validate.py`) returns **every** problem as `Issue(code, path, message)` (`ensure_valid` raises `InvalidConfig` with all of them), so the organiser fixes everything in one pass. It checks: sport registered; outcome keys exist for the sport (unknown and missing keys named); a win is worth more than a loss; tiebreakers start with points, are supported by the sport, appear once, draw lots last; head-to-head never ranks teams across groups; match rules, walkover and fair-play keys valid for the sport; competition format agrees with the structure; team count matches groups; advancement fits group sizes and fills the bracket exactly (e.g. 4 groups × top 2 = 8 = QF); groups of different sizes rank across groups by `POINTS_PER_GAME` first; knockout rounds consecutive to the final; knockout draws decidable (penalties; extra time configured if used); custom pairs use every qualifier once; separations satisfiable in principle (`len(teams) <= groups * max_per_group`) and not broken by fixed placements; calendar sane (ordered days, breaks inside windows, unique pitches); match slot at least as long as a match under the rules; slots ≥ matches; a simultaneous last round has a pitch for each of its matches; enough days for the busiest team; fixed slots name a real match, day, pitch and playing time.

### Presets and the policy catalogue

Presets are the closed catalogue the setup AI chooses from when rules are silent (see `12-tournament-setup.md` §3). Each has an id and version.

| Preset id | Content |
| --- | --- |
| `football_gd_first` | points → goal difference → goals scored → h2h points → h2h goal difference → fair play → draw lots |
| `football_h2h_first` | points → h2h points → h2h goal difference → h2h goals → goal difference → goals scored → fair play → draw lots |
| `format_groups_of_4_sf` | N=8: 2×4, top 2 → SF/3P/F |
| `format_groups_of_4_qf` | N=16: 4×4, top 2 → QF/SF/3P/F |
| `format_groups_of_4_r16_best_thirds` | N=24: 6×4, top 2 + 4 best thirds → R16 |
| `format_groups_of_4_r16` | N=32: 8×4, top 2 → R16 |
| `format_league` / `format_league_double` | Everyone plays everyone once / twice |
| `format_auto` | Ranked candidate formats for any team count that the scheduler fits into the days and pitches (`engine.format_auto.format_auto(n, policy)`, see Schedule) |
| `seeding_previous_placement` | Pots by last edition placement, then rating, then unseeded; previous semi-finalists separated |
| `separation_same_organisation` | Teams of the same organisation in different groups when feasible |
| `schedule_community_weekend` | Match length from the rules (community default 2×20 + 5 min half-time), 5 min changeover, rest ≥ one slot (≥ 60 min for matches of 40+ min), max 3 per day, last round simultaneous |
| `schedule_junior` | Shorter matches, max 2 per day for U12 and younger, rest ≥ 60 min |
| `ice_hockey_standard` | points → wins → h2h points → goal difference → goals scored (added with the ice hockey module) |

The catalogue lives in `engine/rules/presets.py` (`PRESETS` with id, kind, summary, practice; `CATALOGUE_VERSION`, now 2 with `format_auto`), with builders `football_rules`, `FORMAT_PRESETS`, `seeding_previous_placement`, `separation_same_organisation`, `schedule_community_weekend`, `schedule_junior`.

## Sport modules (`engine/sports/`)

Every sport implements the same protocol. Adding a sport = one new file + tests.

```python
class SportRules(Protocol):               # what configuration validation needs
    code: str
    outcome_keys: tuple[str, ...]         # best outcome first
    supported_tiebreakers: frozenset[Tiebreaker]
    fair_play_keys: tuple[str, ...]
    def match_rules_issues(self, match) -> list[Issue]: ...
    def walkover_issues(self, walkover) -> list[Issue]: ...
    def knockout_issues(self, match, uses_extra_time: bool) -> list[Issue]: ...
    def match_duration_minutes(self, match) -> int: ...

class SportModule(SportRules, Protocol):
    def outcome_key(self, result: MatchResult, team: str) -> str: ...
    def knockout_winner(self, result: MatchResult) -> str: ...        # ValueError if no winner
    def team_stats(self, results: Sequence[MatchResult], team: str, rules: RuleConfig) -> TeamStats: ...
    def metric(self, tb: Tiebreaker, stats: TeamStats) -> float | None: ...   # higher ranks higher
    def hypothetical_outcomes(self, f: Fixture, rules: RuleConfig, *, knockout: bool) -> Sequence[SportResult]: ...
    def margin_axis(self) -> MarginAxis: ...
    def walkover_result(self, rules: RuleConfig, winner: Literal["home", "away"]) -> SportResult: ...
    def validate_event(self, state: LiveStateLite, event: EventLite, rules: RuleConfig,
                       *, allow_after_full_time: bool = False) -> None: ...  # raises InvalidEvent(code)
    # Added by T-017:
    def analyse(self, result: MatchResult, events: Sequence[EventLite]) -> list[Fact]: ...
    def detect_moment(self, state: LiveStateLite, event: EventLite) -> Moment | None: ...
```

`TeamStats` (in `engine/model.py`): played, won, drawn, lost, `outcome_counts`, points, score for/against/diff, away score for, fair-play points. `metric` returns `None` for head-to-head tiebreakers (standings computes them on the mini-table) and for drawing lots; fair play is returned negated so that higher always ranks higher.

| Order | Sport | Result shape | Outcomes for scenarios | Margin axis |
| --- | --- | --- | --- | --- |
| **1 (v1)** | **Football** | goals home/away; `decided_by` regulation/extra_time/penalties; penalty score | win, draw, loss (knockout: win/loss incl. penalties) | goal difference, goals scored |
| **1 (v1)** | **Futsal** | as football (`FootballResult`) | as football | goal difference, goals scored |
| 2 (next version) | Ice hockey | goals; regulation/OT/shootout | reg win, OT win, OT loss, reg loss | goal difference |
| 3 (next version) | Floorball | as hockey with own OT rules | as configured | goal difference |
| 4 | Volleyball | sets won, points per set | 3-0 … 0-3 | set ratio, point ratio |
| Later | Cricket, others | sport-specific | sport-specific | sport-specific |

### Football module (`engine/sports/football.py`) — v1

**Match rules (`RuleConfig.match`)**

```json
{ "periods": 2, "period_minutes": 45, "half_time_minutes": 15, "extra_time": false,
  "extra_time_minutes": 15, "penalties_in_knockout": true, "squad_size": 11,
  "rolling_substitutions": true }
```

Validated by `FootballMatchRules` (unknown keys rejected). Pitch time per match = `periods × period_minutes + (periods − 1) × half_time_minutes`. Small-sided and short formats are configuration: 7-a-side `{"periods": 2, "period_minutes": 25, "squad_size": 7}`; community cup `{"periods": 2, "period_minutes": 20, "half_time_minutes": 5}` (the `football_match_rules()` default); school `{"periods": 1, "period_minutes": 15}`.

**Result**

```python
@dataclass(frozen=True)
class FootballResult:
    home_goals: int                       # after regulation and extra time
    away_goals: int
    decided_by: Literal["regulation", "extra_time", "penalties"] = "regulation"
    home_penalties: int | None = None     # shootout score, only when decided_by == "penalties"
    away_penalties: int | None = None
    home_cards: Cards = Cards()           # yellow, second_yellow, red counts for fair play
    away_cards: Cards = Cards()
```

The result checks itself: no negative scores; shootout scores only with `decided_by="penalties"`, only after a level score, and with a winner; an extra-time result cannot be level. In `Cards`, `yellow` counts cautions that did not lead to a sending-off; a second caution counts once as `second_yellow` (FIFA/UEFA fair-play convention).

- Group outcome uses the score after regulation (and extra time if played); a shootout only decides knockout progression (`knockout_winner`), so for points a match level after extra time is a draw. Points for shootout wins are not supported in v1.
- Own goals: the goal event's `team_id` is the team whose player scored; `credited_team` gives the goal to the opponents.
- Scenario outcomes: group fixtures enumerate 1-0, 0-0, 0-1; knockout fixtures 1-0 and 0-1. Margin axis: goal difference up to 10.
- Walkover: `RuleConfig.walkover = {"score_for": 3, "score_against": 0}` (default 3-0); the winner gets the points of a win.

**Event types** (`sports.event_types` seed for `football`, also drives the scorer pad)

| Type | Payload | Notes |
| --- | --- | --- |
| `period_start`, `period_end` | `period` | Half time, full time, extra time |
| `goal` | `team_id`, `player_id?`, `assist_player_id?`, `kind` (`open_play`, `penalty`, `own_goal`, `free_kick`, `header`), `minute?` | Own goal credits the other team |
| `penalty_missed` | `team_id`, `player_id?` | |
| `yellow_card`, `second_yellow`, `red_card` | `team_id`, `player_id?` | Feed fair-play points |
| `substitution` | `team_id`, `player_out?`, `player_in?` | Optional |
| `shootout_kick` | `team_id`, `scored` | Knockout only |
| `undo` | `undoes_seq` | Any event |

`validate_event` rejects: events after full time (except corrections by staff), goals for teams not in the match, a second red for the same player, shootout kicks outside knockout.

**Analysis facts (`analyse`)** — with events: goal timeline, comeback (from 2+ down), late winner (last 5 minutes, changed the result), equaliser timing, scoring run, clean sheet, hat-trick (public adult players only), penalties scored/missed, cards affecting the result. With results only: margin, biggest win of the tournament, upset vs prediction, table impact, qualification secured/lost.

**Moments (`detect_moment`)** — goal, equaliser, lead change, penalty awarded/scored/missed, red card, comeback, last 5 minutes with one-goal margin, half time, full time, shootout decided.

**Threshold search** varies goal difference from 1 to 10 for the team (and opponent results where relevant).

### Futsal module (`engine/sports/futsal.py`) — v1 (T-065)

`FutsalSport` extends the football module: the same `FootballResult`, points, tables, shootouts and tiebreaker steps (`futsal_gd_first`, `futsal_h2h_first`). What differs is the match:

- **`FutsalMatchRules`:** 2 × 20 minutes, 10 minute half-time, `stopped_clock` (scheduling counts a half as 1.5 × its length), extra time 2 × 5 minutes, penalties in knockouts, 5 players on court.
- **Accumulated fouls:** `foul` events per team per half (`LiveStateLite.home_fouls` / `away_fouls`). The count resets at half-time and carries into extra time. When a team reaches `foul_limit + 1` (the sixth), the `sixth_foul` moment fires: every foul from then on gives a direct free kick.
- **Timeouts:** `timeout` events (moment `timeout`), up to `timeouts_per_period` per team per half (`timeout_used`), none in extra time (`no_timeout_in_extra_time`).
- **Schedule:** the community schedule allows 5 futsal matches per team per day (one-day indoor cups), against 3 for football.
- **Presets:** `futsal_rules`, `futsal_match_rules`, `sport_rules(sport, …)`, `match_rules_for(sport)`, `preset_for(sport, order)`; catalogue version 3.
- **Choosing the module:** the app picks it from `RuleConfig.sport` through the registry (scoring, walkovers, setup). `SportModule` now includes `event_types`, `replay`, `result_of` and `detect_moments(…, rules)`.

### Ice hockey module (v2)

Regulation/OT/shootout result; points `3-2-1-0` by default; moments include power-play goal, empty-net, overtime, shootout. Liiga sample data for golden and backtest suites.

## Draw (`engine/draw.py`)

```python
def make_draw(teams: Sequence[SeedEntry], fmt: FormatSpec, policy: SeedingPolicy, *, seed: bytes) -> Draw
# SeedEntry(team, previous_placement=None, rating=None, organiser_rank=None)
```

1. **Rank** teams by `policy.source` in order: teams with data for the first source come first (placement and organiser rank: lower is better; rating: higher is better), then the next source as fallback; teams without any data, and exact ties, in random order. Input order never matters.
2. **Pots** (`by_group_position`): pot k holds one team for every group with more than k places, so with groups of 4, 4, 3 the pots hold 3, 3, 3, 2 teams and the last pot goes to the bigger groups. `pots="none"`: one pool.
3. **Sample uniformly among all valid complete draws** (pots, capacities, fixed placements, separations):
   - at most `enumeration_limit` (2,000) valid draws: list them all and pick one (`method="enumeration"`, `valid_draws` = the count);
   - otherwise rejection sampling: uniform among draws that respect pots and fixed placements, discarding any that break a separation (`method="rejection"`); accepted draws are exactly uniform;
   - if separations make that too rare (`max_rejections`, 20,000): a randomised constraint search (`method="randomized_search"`, `uniform=False`), still valid.
   Sequential "skip to the next valid group" drawing is not used (it is biased).
4. **Positions** in a group follow the pot (pot 1 → A1); a fixed `position_in_group` (host = A1) is honoured by swapping.
5. **Infeasible** → `DrawInfeasible` with `conflict`: a minimal set of clashing separations and fixed placements (deletion filter: every listed rule is needed for the clash) and a plain message, e.g. "6 teams (2025 quarter-finalists) must be in different groups, but there are only 4 groups".
6. **Output** `Draw`: groups (by position), pots, `TeamPlacement` per team (group, position, pot, `seeded_by` + `seed_value`, `fixed`, `kept_apart` reasons — structured so the app explains it in any language), seed, method, uniform, valid_draws, algorithm `draw-1`.

**Reproducibility:** randomness comes only from `engine/rng.py` — `DeterministicRng`, a SHA-256 counter stream (Python's `random` does not promise identical shuffles across versions). Anyone with the inputs and the published seed can reproduce the draw.

Tests: every draw satisfies every constraint (property), same seed → same draw, input order irrelevant, chi-square uniformity over 3,000 seeds for both enumeration and rejection, minimal conflicts (including fixed placements), 32 teams with 8 separations well under 1 s.

## Bracket (`engine/bracket.py`)

```python
def build_bracket(fmt: FormatSpec, advancement: AdvancementRule) -> Bracket
def resolve_bracket(bracket, state, *, knockout_results: Mapping[code, MatchResult] = {}, seeds: Mapping["seed:k", team] = {}) -> BracketResolution
```

**Building** — first-round pairs, then later rounds (`winner:QF1` v `winner:QF2`, …), the third-place match (`loser:SF1` v `loser:SF2`) just before the final:

| Qualifiers | Pairing |
| --- | --- |
| Top 2 per group | World Cup pattern: A1–B2, C1–D2 (top half), B1–A2, D1–C2 (bottom half); teams of the same group can meet again only in the final |
| Group winners only | Neighbouring groups: A1–B1, C1–D1 |
| With best of the rest (e.g. best thirds) | Winners face the best-of-rest qualifiers first, then runners-up of another group (preferably the paired group); remaining teams pair across groups. Pairs are then split into halves so teams of the same group sit in opposite halves where possible (24 teams: each half holds one team of every group) |
| A single group, other shapes | Standard seeding by (place, group): 1 v 8, 4 v 5, 2 v 7, 3 v 6 |
| Pure knockout | Standard seeding of `seed:1…n` (the app supplies `seeds` from its draw) |
| `crossover="custom"` | The organiser's `custom_pairs`, as given |

**Resolving** — a slot is filled only when it can no longer change:
- `group:X:p`: when the group is finished and place p is decided; or earlier, when points bounds (current points + remaining matches × best/worst points) leave a single possible team. Otherwise `pending` with `could_be` (a safe superset: it never omits a team that can still finish there). A tie at p that only lots can break → `blocked` (`blocked_reason="draw_lots"`, `could_be` = the tied teams).
- `best_rest:k`: when every group is finished, ranked by `Standings.rest`; then teams are swapped (first fitting permutation) so none faces the winner of its own group. Our own deterministic rule, not a copy of a competition's published table; organisers who need a specific table use custom pairs. A tie among the qualifiers → `blocked`.
- `winner:CODE` / `loser:CODE`: from the knockout result (shootouts via the sport's `knockout_winner`); before that, `could_be` = both participants (or their candidates).

`state.fixtures` must list every group match still to play; `state.groups` must be in the format's group order (A, B, …). Exact `could_be` sets and earlier certainty from scenario enumeration can replace the points bounds later (T-016).

## Schedule (`engine/schedule.py`)

```python
def build_schedule(groups, bracket: Bracket | None, policy: SchedulePolicy, *, seed: bytes, group_rounds=1) -> SchedulePlan
def reschedule(plan, *, frozen_until: str, changes: Sequence[ScheduleChange], policy) -> SchedulePlan
def suggest_relaxations(groups, bracket, policy, *, seed: bytes, group_rounds=1) -> list[Relaxation]
def schedule_violations(plan, policy, *, check_fixed=True) -> list[ScheduleViolation]
def berger_rounds(teams) -> list[list[tuple[str, str]]]
```

`groups` are team ids per group in draw order (`Draw.groups`); `bracket` comes from `build_bracket` (None for a league). The seed is bytes, like the draw's.

**Matches.** Group matches follow Berger tables (circle method, home and away alternating; double round robin reverses the first leg); in a group of four the top two seeds meet in the last round. Codes `A1…` run in round order. Knockout matches come from the bracket with their placeholders. Each `ScheduledMatch` carries `teams` (everyone who could play in it: the group's teams for `group:A:1`, every group team for `best_rest:k`), `depends_on` (group matches feeding a placeholder, or the match a winner/loser comes from; needs rest), `follows` (the final follows the third-place match; no rest) and `together` (a group's last round when `simultaneous_last_group_round`).

**Slots.** Days × free segments (window minus blocked breaks) × pitches; the same start times on every pitch. Times are UTC minutes from each day's `utc_offset_minutes`; matches also carry `local_date`/`local_time`, and `starts_at`/`ends_at` as ISO 8601 with `Z`.

**Hard constraints** (checked while placing, and again by `schedule_violations` from the plan alone): no pitch double-booked (including the changeover); inside the playing time and outside breaks; a team's next match starts at least `min_rest_minutes` after its previous one ends; at most `max_matches_per_team_per_day` (counting each knockout round a team could reach); dependencies and `follows` ordered; a last round kicks off together; fixed slots kept. Matches of the same knockout round never clash with each other (a team plays only one of them); the third-place match and the final count as one round.

**Algorithm** (deterministic; the seed only decides which group goes first in each round, and the order rotates every round to balance early and late kick-offs):
1. Fixed slots first.
2. Strategy `knockout_last_spread`: knockout matches latest first, each as late as it fits (final on the main pitch in the last slot, the third-place match just before it); then group rounds as early as possible, each released no earlier than its day, spreading the rounds evenly over the days before the knockout (or up to `group_stage_ends_by_day`). A last round is placed as one unit.
3. If anything does not fit: `knockout_last` (no spreading), then `in_order` (everything as early as possible in round order). Otherwise `ScheduleInfeasible` with `unplaced`, `matches` and `slots`.
4. Pitch balancing: matches kicking off together swap pitches so the main pitch (usually the filmed one) goes to the latest knockout round, else to the teams that have played on it least. Fixed pitches and the final stay.

`SchedulePlan.quality`: `hard_violations` (0), `min_rest_minutes`, `max_idle_minutes` (longest same-day wait), `main_pitch_spread` (most minus fewest main-pitch group matches per team; with groups of four it is 2 when a group gets two main-pitch kick-offs, since two of its matches from different rounds always share a team), `group_stage_last_day`, `final_in_best_slot`.

**Rescheduling** (`reschedule`) keeps every match that started before `frozen_until` exactly as it was. Changes: `PitchDelay(pitch, minutes)` (the running match ends later; with none running the pitch is blocked that long), `PitchClosed(pitch, until=None)`, `TeamWithdrawn(team)` (its unplayed group matches become `walkovers`), `MatchPostponed(code, not_before=None)`. Unaffected matches stay put; affected ones move to the earliest slot from their planned time, preferring their own pitch (a last round moves together). If that fails, all later matches are re-placed the same way; as a last resort, matches on days that have not started may also move earlier that day. `plan.moved` lists what changed; fixed slots may move (`schedule_violations(..., check_fixed=False)`).

**Relaxations** (`suggest_relaxations`) — empty when the schedule fits; otherwise, feasible options first, each the smallest step of its kind that fits (or the largest tried, `feasible=False`) with the relaxed `policy` and its `slots`: `add_pitch` (+1, +2), `longer_days` (start 30–120 min earlier; end 30–120 min later), `shorter_matches` (5-minute steps down to half), `more_matches_per_day` (+1), `last_round_not_together`. Smaller groups change the format and come from `format_auto`.

**`format_auto(team_count, policy, *, limit=5)`** (`engine/format_auto.py`, catalogue id `format_auto`) lists formats for any team count that the scheduler actually fits into the policy: groups of 3–6 (sizes differing by at most one) with group winners or top 2 (top 2 or 4 from a single group) plus best-of-the-rest to fill a bracket, a league up to 8 teams, a pure knockout for 2/4/8/16. Ranked by a penalty (distance from groups of 4, best-of-the-rest, unequal groups, under 3 matches per team, no knockout), then more knockout places, a third-place match, fewer matches. A third-place match is dropped when only that does not fit. Each `FormatCandidate` has a plain summary ("4 groups of 4 · top 2 → quarter-finals · third-place match · 32 matches"), match counts per team and qualifiers.

## Standings (`engine/standings.py`, `engine/tiebreakers.py`)

```python
def compute_standings(state: TournamentState) -> Standings          # groups, rest, visible
def rank_teams(teams, results, rules, sport, *, tiebreakers=None, stats=None) -> list[RankedTeam]
```

1. Per group, only that group's results count (`result.group_id` matches and both teams belong to the group); knockout results never enter a table. Stats per team from the sport module.
2. Rank by `tiebreakers` in order. Head-to-head tiebreakers use a mini-table of only the matches between the teams still tied.
   - A split by a non-head-to-head tiebreaker starts a fresh mini-table for the teams still level.
   - A split by a head-to-head tiebreaker with `head_to_head_reapply` (default) restarts the ranking from the top for the teams still level, so head-to-head is re-applied to just them (UEFA style). Without re-application, the next tiebreaker decides and the original mini-table is kept.
3. `draw_lots` stops the engine: teams still level are `tied_unresolved`, share a position, are listed by id, and the organiser records the lots. The engine never invents an order.
4. Each row carries `decided_by` (the tiebreaker that gave the team its own place; `points` when points alone did) and `tiebreak_value` (the team's value on it, e.g. goal difference +5; fair play negated).
5. Cross-group ranking (best third-placed teams): the team just below the automatic places in each group, ranked by `advancement.rest_ranking` on its own group record (`POINTS_PER_GAME` first when group sizes differ). Returned as `Standings.rest`.
6. Form: the last 5 outcomes (`W`/`D`/`L`), oldest first, ordered by `MatchResult.starts_at`, then match id.
7. Input order never matters: teams are processed by id and results only by content (property-tested).

Output rows (`StandingRow`): position, team, stats (played, W/D/L, points, goals for/against/diff, fair play), form, decided_by, tiebreak_value, tied_unresolved. Status (`qualified`, `alive`, `eliminated`) is filled by scenarios. `Standings.visible` passes `rules.standings_visible` through.

## Scenarios (`engine/scenarios.py`)

```python
def compute_scenarios(state, team, *, bracket=None, knockout_results=None, max_branches=1_000_000, samples=2_000, seed=b"scenarios", weights=None) -> Scenario
```

1. Fixtures that can affect the team: its group (every group when best-of-the-rest places exist), with both teams known.
2. Up to `max_branches` completions: exact enumeration of each fixture's representative outcomes (`hypothetical_outcomes`: 1-0, 0-0, 0-1). Above: `samples` completions drawn with `DeterministicRng(seed)`, uniform or by `weights(fixture)` (the simulation hook for predictions); `exact = False`.
3. Each completion is judged by **points alone** (surely through: fewer than `per_group` other teams can reach the team's points; surely out: at least `per_group` (+1 with best-of-the-rest) have strictly more) and by the **full table** at the representative scores (1 through, 0 out, 0.5 when only lots decide).
4. Status: `clinched` / `eliminated` (surely through / out in every completion; with sampling, from points bounds), `in_control` (surely through whenever it wins its remaining matches), `must_win` (surely out whenever it does not win its next match), else `alive`. Points-only certainty means these never mislead (property-tested against random scores).
5. Paths (≤ 4), one per outcome of the team's next match: `through` / `out` (with `unless` = margins of other matches that flip it, found by a threshold search along the sport's margin axis), or `depends` (`through_if` / `out_if` single results). Each has a plain `summary`, e.g. "Draw: through unless A2 beat A3 by 2 or more."
6. **Knockout** (with `bracket`): once the team holds a resolved bracket slot, the scenario is the bracket path: `next_match`, `opponent` (or `opponent_could_be`), `route` to the final, `eliminated_in`.

Group-stage tournaments of 4-team groups are tiny (≤ 3⁶ = 729 branches per group), so community cups are always exact.

## Relevance (`engine/relevance.py`)

```python
def match_relevance(state: TournamentState, team: str) -> list[RelevanceItem]
```

For each remaining fixture without the team: the share of completions in which the team goes through, per outcome of that fixture (1 surely through, 0 surely out, 0.5 when lots or other margins decide, else the table value); impact = max − min. Ranked by impact; fixtures that cannot affect the team come last with impact 0. Each item has per-outcome `shares`, `best_outcome` and a plain `reason`. Drives "matches that matter to us" and live relevance alerts.

## Ratings (`engine/ratings.py`)

Elo-based team strength, one rating per team per sport and age group.

- Start: 1500, or a prior: division prior from config; **seeding prior** for one-off tournaments (pot 1: +75, pot 2: +25, pot 3: −25, pot 4: −75, recorded as `prior_source = "seeding"`); OurSport history when the team has played other tournaments.
- Expected score: `E_home = 1 / (1 + 10 ** (-(R_home + H - R_away) / 400))`, home advantage `H` default 40; **0 for single-venue tournaments** (the usual community cup).
- Update: `R' = R + K * M * (S - E)`, `S` = 1/0.5/0; knockout matches decided on penalties count as draws for rating.
- `K` = 40 for a team's first 10 matches, then 24.
- Margin multiplier `M = ln(1 + margin_units) * 2.2 / (0.001 * winner_elo_diff + 2.2)`, capped at 2.5.
- Season carry-over: adult `0.75 * R + 0.25 * 1500`; junior `0.5 * R + 0.5 * 1500`. Between tournament editions the same carry-over applies.
- Walkovers and abandoned matches do not change ratings.
- `games` counter feeds prediction confidence.

## Predictions (`engine/predictions.py`)

```python
def predict_match(home: RatingInfo, away: RatingInfo, ctx: MatchContext) -> Prediction
```

1. Point estimate from the Elo expectation; for football, split a draw probability using a sport-level draw rate scaled by rating closeness (knockout: no draw outcome, the draw share is split by rating to "wins on penalties").
2. Uncertainty: `sd = 350 / sqrt(games + 1)` per team, combined `sd_c`; report probability at `± 0.67 * sd_c` as `[low, high]`.
3. Confidence: `none` if either team has < 3 rated games (including carried-over history); `low` < 6; `medium` < 12; `high` otherwise. In a 3-day cup most day-1 predictions are `none` → factors only; that is intended.
4. Form adjustment: off by default; enable only if a backtest improves calibration.
5. Factors (always produced, ordered by salience): record in last N, streak, head-to-head (including previous editions), seeding/pot ("last year's runner-up"), rating gap in words, standings positions, what's at stake.

```json
{ "match_id": "…", "home_win": [0.22, 0.34], "draw": [0.20, 0.26], "away_win": [0.44, 0.56],
  "confidence": "medium", "model_version": "elo-1",
  "factors": [ {"id": "f1", "kind": "form", "team": "away", "text": "won 10 of last 12"},
               {"id": "f2", "kind": "seeding", "team": "away", "text": "2025 runner-up"} ] }
```

Junior rule: where `settings.show_probabilities` is false, the API omits percentages; content uses factors only, in gentle language.

Validation: `engine/tests/backtest.py` (Brier score, calibration buckets) on imported football history; Liiga data for hockey.

**Implementation (T-042):** `engine/ratings.py` (priors, carry-over, `update`; draws and shootouts use margin multiplier 1) and `engine/predictions.py` (`predict_match`, `placement_label`). The draw share is `0.26 × (0.4 + 0.6 × closeness)`. `analysis.ratings` applies every finished match once (`rating_history` ledger; walkovers skipped), carries a rating over on a team's first match in a new tournament, and stores a prediction for every scheduled fixture with known teams on each `recalc_tournament`. `GET /matches/{id}/prediction` and the hub's `chances` hide percentages when `show_probabilities` is false or confidence is `none`. Backtest: `uv run python -m engine.tests.backtest` (simulated round robins until imported history exists; Brier 0.43 vs 0.67 uniform).

## Season simulation (`engine/simulation.py`)

- For each remaining fixture, sample an outcome from `predict_match`, then a margin from the empirical margin distribution; knockout placeholders resolved inside each run.
- 10,000 runs by default; seed = hash of (state, rating versions).
- Output per team: probability of each final position, qualify, win group, reach each knockout round, win the tournament.

## Comparison (`engine/comparison.py`)

`compare_teams(state, ratings, history, team_a, team_b) -> Comparison`: form, points per game, goals for/against per game, head-to-head (this tournament and previous editions), rating gap words, current positions, key stats (goals per game, clean sheets, first-half vs second-half goals, cards).

## Match analysis (`sports/*.analyse`)

Facts explaining what decided a finished match (football list above). Every sport also produces: margin vs prediction (upset or as expected), table impact (position before → after) and **qualification impact** (secured, kept alive, eliminated).

**Implementation (T-043):** `engine/comparison.py` (`compare_teams`, previous editions through the same team ids), `engine/analysis.py` (`analyse_match`: result, comeback, late winner (minute ≥ length − 5), upset (pre-match chance < 0.35), table, qualified/eliminated) and `engine/simulation.py` (`simulate`: groups rank by points, goal difference, goals, then a seeded draw instead of head-to-head; knockout by Elo; 10k runs × 30 fixtures ≈ 0.8 s). `analysis.insights` stores comparisons for scheduled matches, analyses for finished ones (events from scoring, minutes from the event clock) and adds simulated `chances` (2,000 runs) to each scenario snapshot; hidden like other percentages when `show_probabilities` is false. Endpoints `/matches/{id}/comparison` and `/matches/{id}/analysis`. Moment detection itself landed in T-030 (`detect_moments`).

## Live calculations

- `live_stakes(state, live_match, current_score)`: standings "if it ended now", what changes with one more goal for either side, and live relevance for other teams ("if this ends now, Tigers are through"). Cheap; recomputed on every event.
- `detect_moment` per sport.
- Live win probability: **not in v1** (T-067, Poisson model blended with pre-match prediction).

## Testing the engine

- **Unit tests:** every tiebreaker and preset, football outcome mapping, h2h mini-tables with 2/3/4 tied teams, fair-play ranking, bracket crossover, best-third mapping, reschedule cases.
- **Property tests (Hypothesis):** points total = sum over matches; `clinched` advances in every completion; standings invariant to result order; adding a win never lowers points; draw constraints always hold; schedule never double-books and respects rest; resolved placeholders never change afterwards.
- **Golden tests:** real past tournaments (team names replaced) in `engine/tests/golden/*.json` with the official final table and the reason for each tie. Currently: World Cup 1994 Group E (four-way tie → goals scored → head-to-head), EURO 2004 Group C (three-way head-to-head goals), World Cup 2018 Group H (fair play). Community and junior tables (e.g. a FinBangla cup) are to be added when available.
- **Backtests:** prediction calibration.
- **Performance:** scenarios 6 teams / 6 matches left < 1 s; simulation 10k runs × 30 fixtures < 3 s; schedule 32 teams / 3 days / 6 pitches < 5 s; draw 32 teams with 8 separations < 1 s.
