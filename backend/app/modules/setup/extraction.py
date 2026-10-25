"""From redacted documents to a validated draft (docs/12-tournament-setup.md §1-4).

AI proposes (structured extraction with quotes), the engine decides (catalogue defaults,
format_auto, validation). The draft is complete: anything unclear or missing becomes a
recorded assumption the organiser can change on Review, and what does not fit (validation
issues, a schedule that does not fit the days and pitches) is fixed by the engine and noted.
The one open question left is a team list with fewer than 2 teams: only the organiser has it.
"""

import datetime as dt
import difflib
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.core.llm import LLMError, LLMGateway
from app.modules.competitions import service as competitions
from app.modules.setup import review
from app.modules.setup.schemas import (
    Assumption,
    DraftTeam,
    ExtractedQuestion,
    ExtractionInputs,
    FormatExtraction,
    OpenQuestion,
    RulesExtraction,
    ScheduleExtraction,
    SeedingExtraction,
    SetupDraftData,
    TeamsExtraction,
)
from app.modules.setup.team_lists import teams_from_rows, teams_from_text
from engine.format_auto import format_auto
from engine.rules.config import HEAD_TO_HEAD, POINTS_TIEBREAKERS, RuleConfig, Tiebreaker
from engine.rules.format import (
    FormatChoice,
    first_round_for,
    groups_then_knockout,
    league,
    max_matches_per_team,
)
from engine.rules.presets import (
    PRESETS,
    TIEBREAKER_PRESETS,
    match_rules_for,
    preset_for,
    schedule_community_weekend,
    schedule_junior,
    seeding_previous_placement,
    separation_same_organisation,
    sport_rules,
)
from engine.rules.schedule_policy import DayWindow, SchedulePolicy
from engine.rules.seeding import FixedPlacement, SeedingPolicy, SeedingSource, Separation
from engine.rules.validate import validate_setup
from engine.sports.registry import SPORTS, get_sport

FUZZY_MATCH = 0.8
JUNIOR_SCHEDULE = frozenset({"u12", "u11", "u10", "u9"})
_ASSUMED_DAY = (dt.time(9, 0), dt.time(18, 0))
_ASSUMED_PITCHES = 2
_MAX_PITCHES = 16  # pitches added until the matches fit; beyond this the organiser decides
_FIT_SEED = b"setup-fit"
_TIEBREAKER_ISSUES = frozenset(
    {"tiebreaker_order", "tiebreaker_duplicate", "tiebreaker_not_supported", "draw_lots_not_last"}
)
_IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class IntakeText:
    kind: str
    text: str
    rows: list[list[str]] | None = None
    image: tuple[str, bytes] | None = None


@dataclass
class TournamentFacts:
    tournament_id: str
    sport: str
    age_group: str
    time_zone: str
    starts_on: dt.date | None
    ends_on: dt.date | None
    language: str


@dataclass
class Draft:
    data: SetupDraftData
    assumptions: list[Assumption] = field(default_factory=list)
    questions: list[OpenQuestion] = field(default_factory=list)


class _Builder:
    def __init__(self, facts: TournamentFacts, llm: LLMGateway) -> None:
        self.facts = facts
        self.llm = llm
        self.assumptions: list[Assumption] = []
        self.questions: list[OpenQuestion] = []
        self.quotes: dict[str, str] = {}

    def assume(
        self,
        field_: str,
        chosen: str,
        reason: str,
        catalogue_id: str | None = None,
        alternatives: Sequence[str] = (),
    ) -> None:
        self.assumptions.append(
            Assumption(
                id=f"a{len(self.assumptions) + 1}",
                field=field_,
                chosen=chosen,
                catalogue_id=catalogue_id,
                reason=reason,
                alternatives=list(alternatives),
            )
        )

    def ask(
        self,
        field_: str,
        text: str,
        *,
        quotes: Sequence[str] = (),
        options: Sequence[str] = (),
        impact: str = "medium",
        ref: dict[str, str] | None = None,
    ) -> None:
        self.questions.append(
            OpenQuestion(
                id=f"q{len(self.questions) + 1}",
                field=field_,
                text=text,
                quotes=list(quotes),
                options=list(options),
                impact=impact,  # type: ignore[arg-type]  # one of the Impact literals
                ref=ref or {},
            )
        )

    def assume_extracted(self, questions: Sequence[ExtractedQuestion]) -> None:
        """What the AI found unclear: the draft keeps the usual setting and says so."""
        for q in questions:
            if any(a.field == f"documents.{q.field}" for a in self.assumptions):
                continue  # one note per field is enough
            self.assume(
                f"documents.{q.field}",
                "Usual setting kept",
                f"Not clear in your rules: {q.text}",
            )

    async def extract[T: BaseModel](
        self, task: str, text: str, output: type[T], team_count: int | None = None
    ) -> T | None:
        if not text.strip():
            return None
        catalogue = [{"id": p.id, "summary": p.summary} for p in PRESETS.values()]
        inputs = ExtractionInputs(
            document=text,
            organiser_language=self.facts.language,
            catalogue=catalogue,
            team_count=team_count,
        )
        try:
            result = await self.llm.generate(
                task, inputs, output=output, tournament_id=self.facts.tournament_id
            )
        except LLMError as exc:
            self.assume(
                f"documents.{task}",
                "Usual settings",
                f"Part of the documents could not be read automatically ({exc}).",
            )
            return None
        return result.output

    # --- teams ---------------------------------------------------------------------------

    async def teams(self, files: Sequence[IntakeText]) -> list[DraftTeam]:
        found: list[tuple[str, str | None, str]] = []
        for f in files:
            if f.kind != "team_list":
                continue
            parsed = (
                teams_from_rows(f.rows) if f.rows else teams_from_text(f.text) if f.text else None
            )
            source = "table" if f.rows else "text"
            if parsed is None:
                images = [f.image] if f.image else []
                try:
                    result = await self.llm.generate(
                        "teams_extract.v1",
                        ExtractionInputs(document=f.text, organiser_language=self.facts.language),
                        output=TeamsExtraction,
                        tournament_id=self.facts.tournament_id,
                        images=images,
                    )
                    parsed = [(t.name, t.organisation) for t in result.output.teams]
                    source = "photo" if f.image else "llm"
                except LLMError:
                    parsed = []
            found += [(name, org, source) for name, org in parsed]
        unique: dict[str, tuple[str, str | None, str]] = {}
        for name, org, source in found:
            unique.setdefault(competitions.normalise_alias(name), (name, org, source))
        teams = [
            DraftTeam(key=f"t{i:02d}", name=name, organisation=org, source=source)  # type: ignore[arg-type]  # source is one of the literals
            for i, (name, org, source) in enumerate(unique.values(), start=1)
        ]
        self._near_duplicates(teams)
        if len(teams) < 2:
            self.ask(
                "teams",
                f"We found {len(teams)} team(s) in the team list; a tournament needs at least 2. "
                "Add the list with one team per line.",
                impact="high",
            )
        return teams

    def _near_duplicates(self, teams: Sequence[DraftTeam]) -> None:
        names = [competitions.normalise_alias(t.name) for t in teams]
        for i, a in enumerate(names):
            for j in range(i + 1, len(names)):
                if difflib.SequenceMatcher(None, a, names[j]).ratio() >= FUZZY_MATCH:
                    self.assume(
                        "teams.duplicates",
                        "Different teams",
                        f"'{teams[i].name}' and '{teams[j].name}' look alike; both are kept.",
                    )

    # --- rules ---------------------------------------------------------------------------

    def rules_parts(
        self, ex: RulesExtraction | None
    ) -> tuple[str, dict[str, object], dict[str, int], dict[str, int] | None, list[Tiebreaker]]:
        """(tiebreaker preset, match rules, walkover, points override, explicit tiebreakers)."""
        sport = self.facts.sport
        match = match_rules_for(sport)
        h2h, gd = preset_for(sport, "h2h_first"), preset_for(sport, "gd_first")
        walkover: dict[str, int] = {"score_for": 3, "score_against": 0}
        points: dict[str, int] | None = None
        explicit: list[Tiebreaker] = []
        if ex is None:
            self.assume(
                "rules",
                f"community {sport} defaults",
                "No rulebook was given.",
                h2h,
            )
            return h2h, match, walkover, None, []
        self.assume_extracted(ex.questions)
        if ex.ignored_instructions:
            self.assume(
                "documents",
                "Instructions ignored",
                "A document contained instructions to the system; they were ignored.",
            )
        for name, value in (
            ("periods", ex.periods),
            ("period_minutes", ex.period_minutes),
            ("half_time_minutes", ex.half_time_minutes),
        ):
            if value.value is not None and value.quote:
                match[name] = value.value
                self.quotes[f"rules.match.{name}"] = value.quote
        if ex.extra_time.value is not None and ex.extra_time.quote:
            match["extra_time"] = ex.extra_time.value
        if ex.walkover_score_for.value is not None and ex.walkover_score_for.quote:
            walkover = {
                "score_for": ex.walkover_score_for.value,
                "score_against": ex.walkover_score_against.value or 0,
            }
        quoted_points = [ex.win_points, ex.draw_points, ex.loss_points]
        if all(p.value is not None and p.quote for p in quoted_points):
            points = {
                "win": ex.win_points.value or 0,
                "draw": ex.draw_points.value or 0,
                "loss": ex.loss_points.value or 0,
            }
        if ex.tiebreakers and ex.tiebreakers_quote:
            explicit = list(ex.tiebreakers)
            self.quotes["rules.tiebreakers"] = ex.tiebreakers_quote
        else:
            self.assume(
                "rules.tiebreakers",
                h2h,
                "Your rules don't say how ties are broken; we used the matches between the tied "
                "teams first, as short tournaments usually do.",
                h2h,
                [gd],
            )
        return h2h, match, walkover, points, explicit

    # --- schedule ------------------------------------------------------------------------

    def schedule(self, ex: ScheduleExtraction | None, match: dict[str, object]) -> SchedulePolicy:
        zone = ZoneInfo(self.facts.time_zone)

        def window(
            date: dt.date, start: dt.time, end: dt.time, blocked: list[tuple[dt.time, dt.time]]
        ) -> DayWindow:
            offset = dt.datetime.combine(date, start, zone).utcoffset() or dt.timedelta()
            return DayWindow(
                date=date,
                start=start,
                end=end,
                blocked=blocked,
                utc_offset_minutes=int(offset.total_seconds() // 60),
            )

        blocked = [
            (dt.time.fromisoformat(b.start), dt.time.fromisoformat(b.end))
            for b in (ex.breaks if ex else [])
        ]
        if ex and ex.days:
            days = [
                window(
                    d.date, dt.time.fromisoformat(d.start), dt.time.fromisoformat(d.end), blocked
                )
                for d in ex.days
            ]
            self.quotes["schedule.days"] = ex.days[0].quote
        else:
            start = self.facts.starts_on or dt.date.today()
            end = self.facts.ends_on or start
            dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
            days = [window(d, *_ASSUMED_DAY, blocked) for d in dates]
            self.assume(
                "schedule.days",
                "09:00-18:00",
                "Playing times were not given; every day of the event is used.",
            )
        if ex and ex.pitches.value and ex.pitches.quote:
            pitches = ex.pitch_names or [f"Pitch {i}" for i in range(1, ex.pitches.value + 1)]
        else:
            pitches = [f"Pitch {i}" for i in range(1, _ASSUMED_PITCHES + 1)]
            self.assume(
                "schedule.pitches",
                f"{_ASSUMED_PITCHES} pitches",
                "The number of pitches was not given; more are added if the matches don't fit.",
            )
        build = (
            schedule_junior
            if self.facts.age_group in JUNIOR_SCHEDULE
            else schedule_community_weekend
        )
        policy = build(
            days, pitches, match, sport=get_sport(self.facts.sport), time_zone=self.facts.time_zone
        )
        updates: dict[str, int] = {}
        if ex:
            for name in (
                "match_minutes",
                "break_minutes",
                "min_rest_minutes",
                "max_matches_per_team_per_day",
            ):
                value = getattr(ex, name)
                if value.value is not None and value.quote:
                    updates[name] = value.value
                    self.quotes[f"schedule.{name}"] = value.quote
            self.assume_extracted(ex.questions)
        return policy.model_copy(update=updates)

    # --- format --------------------------------------------------------------------------

    def format(
        self, ex: FormatExtraction | None, team_count: int, schedule: SchedulePolicy
    ) -> tuple[FormatChoice | None, SchedulePolicy]:
        """The format, and the schedule with any pitches added so the format fits."""
        if ex is not None:
            self.assume_extracted(ex.questions)
        if team_count < 2:
            return None, schedule  # the teams question asks for the list; no format fits
        if ex and ex.group_count.value and ex.group_count.quote and ex.per_group.value:
            groups = ex.group_count.value
            base, extra = divmod(team_count, groups)
            sizes = [base + 1] * extra + [base] * (groups - extra)
            through = _advancing(groups, min(sizes), ex.per_group.value, ex.best_of_rest.value or 0)
            if base >= 2 and through is not None:
                per_group, best_of_rest = through
                if per_group != ex.per_group.value:
                    self.assume(
                        "format.advancement",
                        f"Top {per_group} of each group",
                        f"{ex.per_group.value} from each of {groups} groups cannot fill a "
                        f"knockout bracket; {per_group} from each can.",
                    )
                choice = groups_then_knockout(
                    sizes,
                    per_group=per_group,
                    best_of_rest=best_of_rest,
                    third_place_match=bool(ex.third_place_match.value),
                )
                self.quotes["format.groups"] = ex.group_count.quote
                return choice, schedule
            self.assume(
                "documents.format",
                "Format chosen to fit",
                f"The format in your rules does not work for {team_count} teams.",
            )
        policy = schedule
        candidates = format_auto(team_count, policy)
        while not candidates and len(policy.pitches) < _MAX_PITCHES:
            policy = _with_pitches(policy, len(policy.pitches) + 1)
            candidates = format_auto(team_count, policy)
        if not candidates:
            self.assume(
                "format",
                "league",
                "Nothing shorter fits the days and pitches; everyone plays everyone once.",
            )
            return league(team_count), schedule
        if len(policy.pitches) > len(schedule.pitches):
            self.assume(
                "schedule.pitches.added",
                f"{len(policy.pitches)} pitches",
                f"{team_count} teams did not fit on {len(schedule.pitches)} pitches.",
            )
        best = candidates[0]
        self.assume(
            "format",
            best.summary,
            "Chosen to fit the days and pitches.",
            "format_auto",
            [c.summary for c in candidates[1:]],
        )
        return best.choice, policy

    # --- fixes the engine makes instead of asking ------------------------------------------

    def settle(
        self,
        rules: RuleConfig,
        choice: FormatChoice,
        seeding: SeedingPolicy,
        schedule: SchedulePolicy,
        keys: list[str],
    ) -> tuple[RuleConfig, SeedingPolicy, SchedulePolicy]:
        """Fix the validation issues that have one sensible answer, and note each fix."""
        for _ in range(8):
            issues = validate_setup(rules, choice.format, seeding, schedule, keys)
            codes = {i.code for i in issues}
            if codes & _TIEBREAKER_ISSUES:
                rules = self._tiebreakers(rules)
            elif "match_too_short_for_rules" in codes and rules.sport in SPORTS:
                needed = SPORTS[rules.sport].match_duration_minutes(rules.match)
                schedule = schedule.model_copy(update={"match_minutes": needed})
                self.assume(
                    "schedule.match_minutes",
                    f"{needed} minutes per match",
                    "The pitch time per match was shorter than a match under your rules.",
                )
            elif "schedule_last_round_needs_pitches" in codes:
                schedule = schedule.model_copy(update={"simultaneous_last_group_round": False})
                self.assume(
                    "schedule.simultaneous_last_group_round",
                    "Last group round not kicked off together",
                    "There are not enough pitches to start every last-round match at once.",
                )
            elif "schedule_team_days_insufficient" in codes:
                per_day = math.ceil(max_matches_per_team(choice.format) / len(schedule.days))
                schedule = schedule.model_copy(update={"max_matches_per_team_per_day": per_day})
                self.assume(
                    "schedule.max_matches_per_team_per_day",
                    f"Up to {per_day} matches per team per day",
                    "Fewer would not fit every team's matches into the days.",
                )
            elif codes & {"separation_unsatisfiable", "separation_unknown_team"}:
                seeding = seeding.model_copy(update={"separations": []})
                self.assume(
                    "seeding.separation",
                    "No teams kept apart",
                    "The teams to keep apart could not all be put in different groups.",
                )
            else:
                break
        return rules, seeding, schedule

    def _tiebreakers(self, rules: RuleConfig) -> RuleConfig:
        """Points first, each step once, drawing of lots last; else the matching preset."""
        listed = list(dict.fromkeys(rules.tiebreakers))
        if not any(t in POINTS_TIEBREAKERS for t in listed):
            listed.insert(0, Tiebreaker.POINTS)
        if Tiebreaker.DRAW_LOTS in listed:
            listed = [t for t in listed if t != Tiebreaker.DRAW_LOTS] + [Tiebreaker.DRAW_LOTS]
        if listed != list(rules.tiebreakers):
            self.assume(
                "rules.tiebreakers.order",
                "Points first, then your tiebreakers",
                "Teams are ranked by points first; your tiebreakers follow in your order.",
            )
            return rules.model_copy(update={"tiebreakers": listed})
        kind = "h2h_first" if any(t in HEAD_TO_HEAD for t in listed) else "gd_first"
        preset = preset_for(rules.sport, kind)
        other = preset_for(rules.sport, "gd_first" if kind == "h2h_first" else "h2h_first")
        self.assume(
            "rules.tiebreakers",
            preset,
            "Your tiebreakers can't be used as written; this is the closest standard order.",
            preset,
            [other],
        )
        return rules.model_copy(update={"tiebreakers": list(TIEBREAKER_PRESETS[preset])})

    def fit(self, data: SetupDraftData) -> SetupDraftData:
        """Draw and schedule a trial run; when the matches do not fit, add pitches. Playing
        times and match length stay as the rules (or the stated assumptions) give them."""
        start = len(data.schedule["pitches"]) if data.schedule else 0
        for _ in range(_MAX_PITCHES):
            generated = review.generate(data, _FIT_SEED)
            schedule = data.schedule
            if not generated.questions or schedule is None:
                break
            if generated.questions[0].field == "seeding":
                data = data.model_copy(
                    update={"seeding": {**data.seeding, "separations": [], "fixed": []}}
                )
                self.assume(
                    "seeding.separation",
                    "No teams kept apart",
                    "The teams to keep apart could not all be put in different groups.",
                )
                continue
            pitches = len(schedule["pitches"])
            if pitches >= _MAX_PITCHES:
                break
            policy = SchedulePolicy.model_validate(schedule)
            data = review.apply_change(
                data, "schedule", _with_pitches(policy, pitches + 1).model_dump_json()
            )
        if data.schedule and len(data.schedule["pitches"]) > start:
            self.assume(
                "schedule.pitches.added",
                f"{len(data.schedule['pitches'])} pitches",
                f"All matches did not fit on {start} pitches.",
            )
        return data

    # --- seeding -------------------------------------------------------------------------

    def _match_team(
        self, name: str, teams: Sequence[DraftTeam], quote: str, placement: int | None = None
    ) -> DraftTeam | None:
        wanted = competitions.normalise_alias(name)
        for team in teams:
            if competitions.normalise_alias(team.name) == wanted:
                return team
        best = max(
            teams,
            key=lambda t: difflib.SequenceMatcher(
                None, wanted, competitions.normalise_alias(t.name)
            ).ratio(),
            default=None,
        )
        if (
            best
            and difflib.SequenceMatcher(
                None, wanted, competitions.normalise_alias(best.name)
            ).ratio()
            >= FUZZY_MATCH
        ):
            self.assume(
                "seeding.history",
                "Not matched",
                f"'{name}' from last time may be '{best.name}'; it was not used for seeding.",
            )
        return None

    def seeding(
        self, ex: SeedingExtraction | None, teams: list[DraftTeam], group_count: int
    ) -> SeedingPolicy:
        separations: list[Separation] = []
        fixed: list[FixedPlacement] = []
        if ex:
            self.assume_extracted(ex.questions)
            for p in ex.previous_placements:
                team = self._match_team(p.team, teams, p.quote, p.placement)
                if team:
                    team.previous_placement = p.placement
        placed = [t for t in teams if t.previous_placement is not None]
        semis = [t.key for t in placed if (t.previous_placement or 99) <= 4]
        quarters = [t.key for t in placed if (t.previous_placement or 99) <= 8]
        rules = {k.rule for k in ex.keep_apart} if ex else set()
        if ex:
            for keep in ex.keep_apart:
                if keep.rule == "listed_teams":
                    keys = [
                        t.key
                        for name in keep.teams
                        if (t := self._match_team(name, teams, keep.quote))
                    ]
                    if len(keys) >= 2:
                        separations.append(Separation(teams=keys, reason=keep.quote))
            for f in ex.fixed:
                team = self._match_team(f.team, teams, f.quote)
                index = ord(f.group.strip().upper()[:1] or "A") - ord("A")
                if team and 0 <= index < group_count:
                    fixed.append(FixedPlacement(team=team.key, group_index=index))
        if "previous_quarter_finalists" in rules and len(quarters) >= 2:
            policy = seeding_previous_placement(
                group_count=max(group_count, 8), previous_quarter_finalists=quarters
            )
            separations += [
                s.model_copy(update={"reason": "last edition's quarter-finalists"})
                for s in policy.separations
            ]
        elif semis and ("previous_semi_finalists" in rules or not rules):
            if not rules:
                self.assume(
                    "seeding.separation",
                    "last year's semi-finalists in different groups",
                    "Your rules don't say; this is the usual practice.",
                    "seeding_previous_placement",
                )
            separations += seeding_previous_placement(
                group_count=group_count, previous_semi_finalists=semis
            ).separations
        by_org: dict[str, list[str]] = defaultdict(list)
        for team in teams:
            if team.organisation:
                by_org[competitions.normalise_alias(team.organisation)].append(team.key)
        if any(len(v) >= 2 for v in by_org.values()):
            if "same_organisation" not in rules:
                self.assume(
                    "seeding.separation",
                    "teams of the same club in different groups",
                    "Usual practice when a club enters several teams.",
                    "separation_same_organisation",
                )
            separations += separation_same_organisation(by_org, group_count=group_count)
        source = (
            [SeedingSource.PREVIOUS_PLACEMENT, SeedingSource.RATING, SeedingSource.NONE]
            if placed
            else [SeedingSource.NONE]
        )
        return SeedingPolicy(
            source=source,
            pots="by_group_position" if placed else "none",
            separations=separations,
            fixed=fixed,
        )


def _advancing(groups: int, size: int, per_group: int, best_of_rest: int) -> tuple[int, int] | None:
    """Teams through from each group (and best of the rest) that fill a knockout bracket:
    as written when it works, else the nearest that does (top 2 when unsure)."""
    if 1 <= per_group < size and first_round_for(groups * per_group + best_of_rest):
        return per_group, best_of_rest
    fitting = [n for n in range(1, size) if first_round_for(groups * n)]
    if not fitting:
        return None
    return min(fitting, key=lambda n: (n != 2, abs(n - per_group))), 0


def _with_pitches(policy: SchedulePolicy, count: int) -> SchedulePolicy:
    names = list(policy.pitches)
    n = len(names)
    while len(names) < count:
        n += 1
        if f"Pitch {n}" not in names:
            names.append(f"Pitch {n}")
    return policy.model_copy(update={"pitches": names})


async def build_draft(
    facts: TournamentFacts, files: Sequence[IntakeText], llm: LLMGateway
) -> Draft:
    """Run every extraction step and return a complete draft the engine has validated,
    drawn and scheduled in a trial run (only a missing team list stays a question)."""
    b = _Builder(facts, llm)
    rulebook = "\n\n".join(f.text for f in files if f.kind in ("rulebook", "venue", "other"))
    history = "\n\n".join(f.text for f in files if f.kind == "history")
    teams = await b.teams(files)

    rules_ex = await b.extract("rules_extract.v1", rulebook, RulesExtraction)
    schedule_ex = await b.extract("schedule_extract.v1", rulebook, ScheduleExtraction)
    format_ex = await b.extract(
        "format_extract.v1", rulebook, FormatExtraction, team_count=len(teams)
    )
    seeding_ex = await b.extract(
        "seeding_extract.v1", f"{rulebook}\n\n{history}".strip(), SeedingExtraction
    )

    preset, match, walkover, points, explicit = b.rules_parts(rules_ex)
    schedule = b.schedule(schedule_ex, match)
    found, schedule = b.format(format_ex, len(teams), schedule)
    choice = found or league(max(len(teams), 2))
    rules = sport_rules(facts.sport, preset, choice, match=match, walkover=walkover)
    updates: dict[str, object] = {}
    if explicit:
        updates["tiebreakers"] = explicit
    if points:
        updates["points"] = rules.points.model_copy(update={"table": points})
    rules = rules.model_copy(update=updates)
    seeding = b.seeding(seeding_ex, teams, max(choice.format.group_count, 1))
    keys = [t.key for t in teams]
    if len(teams) >= 2:
        rules, seeding, schedule = b.settle(rules, choice, seeding, schedule, keys)

    data = SetupDraftData(
        rules=rules.model_dump(mode="json"),
        format=choice.format.model_dump(mode="json"),
        seeding=seeding.model_dump(mode="json"),
        schedule=schedule.model_dump(mode="json"),
        teams=teams,
        quotes=b.quotes,
    )
    if len(teams) >= 2:
        data = b.fit(data)
        # What the engine could not settle on its own is still asked (rare).
        b.questions += review.validation_questions(data)
    questions = sorted(b.questions, key=lambda q: _IMPACT_ORDER[q.impact])
    return Draft(data, b.assumptions, questions)
