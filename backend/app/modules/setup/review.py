"""Organiser review: answers and edits applied to a draft, then the engine's draw and
schedule (docs/12-tournament-setup.md §5-7). Pure functions over the draft data."""

import dataclasses
import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.setup.schemas import (
    DraftTeam,
    DrawGroupOut,
    DrawOut,
    DrawTeamOut,
    OpenQuestion,
    PlannedMatch,
    ScheduleOut,
    SetupDraftData,
)
from engine.bracket import build_bracket
from engine.draw import Draw, DrawInfeasible, SeedEntry, make_draw
from engine.rules.config import RuleConfig
from engine.rules.format import FormatSpec, group_letter, league
from engine.rules.issues import Issue
from engine.rules.presets import TIEBREAKER_PRESETS, preset_for, sport_rules
from engine.rules.schedule_policy import FixedSlot, SchedulePolicy
from engine.rules.seeding import SeedingPolicy, SeedingSource
from engine.rules.validate import validate_setup
from engine.schedule import (
    Relaxation,
    ScheduledMatch,
    ScheduleInfeasible,
    SchedulePlan,
    ScheduleQuality,
    build_schedule,
    suggest_relaxations,
)
from engine.sports.registry import SPORTS

_TIEBREAKER_ANSWERS = {
    "goal difference": "football_gd_first",
    "head-to-head": "football_h2h_first",
    "football_gd_first": "football_gd_first",
    "football_h2h_first": "football_h2h_first",
}


class UnknownAnswer(ValueError):
    pass


def apply_change(
    data: SetupDraftData, field: str, value: str, question: OpenQuestion | None = None
) -> SetupDraftData:
    """The draft with one answer or edit applied; unknown fields are only recorded."""
    draft = data.model_copy(deep=True)
    value = value.strip()
    if field == "schedule.days" and draft.schedule:
        start, _, end = value.partition("-")
        try:
            start_t, end_t = (
                dt.time.fromisoformat(start.strip()),
                dt.time.fromisoformat(end.strip()),
            )
        except ValueError as exc:
            raise UnknownAnswer("give the times as HH:MM-HH:MM") from exc
        for day in draft.schedule["days"]:
            day["start"], day["end"] = start_t.isoformat("minutes"), end_t.isoformat("minutes")
    elif field == "schedule.pitches" and draft.schedule:
        if not value.isdigit() or int(value) < 1:
            raise UnknownAnswer("give the number of pitches")
        draft.schedule["pitches"] = [f"Pitch {i}" for i in range(1, int(value) + 1)]
    elif field == "schedule.match_minutes" and draft.schedule:
        if not value.isdigit() or not 1 <= int(value) <= 240:
            raise UnknownAnswer("give the minutes per match (1-240)")
        draft.schedule["match_minutes"] = int(value)
    elif field == "rules.tiebreakers":
        preset = _TIEBREAKER_ANSWERS.get(value.casefold())
        if preset is None:
            raise UnknownAnswer(f"choose one of: {', '.join(sorted(_TIEBREAKER_ANSWERS))}")
        draft.rules["tiebreakers"] = [t.value for t in TIEBREAKER_PRESETS[preset]]
    elif field == "teams" and question and question.ref and value == "same team":
        drop = question.ref["drop"]
        draft.teams = [t for t in draft.teams if t.key != drop]
    elif field == "seeding.history" and question and question.ref and value == "yes":
        placement = question.ref.get("placement")
        for team in draft.teams:
            if team.key == question.ref["team"] and placement:
                team.previous_placement = int(placement)
    elif field == "format" and value in ("league", "double_league"):
        choice = league(len(draft.teams), double=value == "double_league")
        rules = RuleConfig.model_validate(draft.rules)
        preset = preset_for(rules.sport, "gd_first")  # leagues: goal difference first
        rebuilt = sport_rules(
            rules.sport, preset, choice, match=rules.match, walkover=rules.walkover
        )
        draft.rules = rebuilt.model_copy(update={"points": rules.points}).model_dump(mode="json")
        draft.format = choice.format.model_dump(mode="json")
        draft.seeding = SeedingPolicy(source=[SeedingSource.NONE], pots="none").model_dump(
            mode="json"
        )
        if draft.schedule and len(draft.schedule["pitches"]) < len(draft.teams) // 2:
            # A league's last round cannot kick off together on too few pitches.
            draft.schedule["simultaneous_last_group_round"] = False
    elif field == "schedule" and value.startswith("{"):
        draft.schedule = SchedulePolicy.model_validate_json(value).model_dump(mode="json")
    return draft


def validation_questions(data: SetupDraftData) -> list[OpenQuestion]:
    """The engine's validation issues as questions, marked with ``ref.issue``: they are
    resolved by changing the draft (schedule, format), not by a text answer."""
    rules, fmt, seeding, schedule = engine_inputs(data)
    issues = validate_setup(rules, fmt, seeding, schedule, [t.key for t in data.teams])
    return [issue_question(f"v{i}", issue, rules) for i, issue in enumerate(issues, start=1)]


_TIEBREAKER_ISSUES = frozenset(
    {"tiebreaker_order", "tiebreaker_duplicate", "tiebreaker_not_supported", "draw_lots_not_last"}
)


def issue_question(question_id: str, issue: Issue, rules: RuleConfig | None) -> OpenQuestion:
    """An engine validation issue as a question (`ref.issue`). Where one answer fixes it,
    the question names the field that answer changes and offers it as options: a
    tiebreaker preset (both rank by points first), or the match length the rules need."""
    field, options = issue.path, list[str]()
    if issue.code in _TIEBREAKER_ISSUES and issue.path.startswith("tiebreakers"):
        field, options = "rules.tiebreakers", ["goal difference", "head-to-head"]
    elif issue.code == "match_too_short_for_rules" and rules is not None and rules.sport in SPORTS:
        needed = SPORTS[rules.sport].match_duration_minutes(rules.match)
        field, options = "schedule.match_minutes", [str(needed)]
    return OpenQuestion(
        id=question_id,
        field=field,
        text=issue.message,
        options=options,
        impact="high",
        ref={"issue": issue.code},
    )


def refresh_questions(
    data: SetupDraftData, questions: Sequence[OpenQuestion], changed: str | None = None
) -> list[OpenQuestion]:
    """The questions still open after answers or a change: those about the changed field
    (or a part of it) are settled, and the validation issues are checked again."""

    def settled(q: OpenQuestion) -> bool:
        return changed is not None and (q.field == changed or q.field.startswith(f"{changed}."))

    kept = [q for q in questions if "issue" not in q.ref and not settled(q)]
    return kept + validation_questions(data)


def engine_inputs(
    data: SetupDraftData,
) -> tuple[RuleConfig, FormatSpec, SeedingPolicy, SchedulePolicy | None]:
    fmt = FormatSpec.model_validate(data.format)
    if fmt.team_count != len(data.teams) and fmt.group_sizes:
        # Teams were merged: keep the group count, rebalance the sizes.
        count = len(fmt.group_sizes)
        base, extra = divmod(len(data.teams), count)
        sizes = [base + 1] * extra + [base] * (count - extra)
        fmt = fmt.model_copy(update={"team_count": len(data.teams), "group_sizes": sizes})
    keys = {t.key for t in data.teams}
    seeding = SeedingPolicy.model_validate(data.seeding)
    separations = [
        s.model_copy(update={"teams": [t for t in s.teams if t in keys]})
        for s in seeding.separations
        if len([t for t in s.teams if t in keys]) >= 2
    ]
    seeding = seeding.model_copy(update={"separations": separations})
    schedule = SchedulePolicy.model_validate(data.schedule) if data.schedule else None
    return RuleConfig.model_validate(data.rules), fmt, seeding, schedule


@dataclass(frozen=True)
class Generated:
    draw: Draw | None
    plan: SchedulePlan | None
    questions: list[OpenQuestion]
    relaxations: list[Relaxation]


def generate(data: SetupDraftData, seed: bytes) -> Generated:
    """The engine's draw and schedule for a draft; infeasibility becomes a question."""
    rules, fmt, seeding, schedule = engine_inputs(data)
    entries = [
        SeedEntry(team=t.key, previous_placement=t.previous_placement, organiser_rank=i)
        for i, t in enumerate(data.teams, start=1)
    ]
    draw: Draw | None = None
    groups: Sequence[Sequence[str]] = []
    if fmt.group_sizes:
        try:
            draw = make_draw(entries, fmt, seeding, seed=seed)
        except DrawInfeasible as exc:
            question = OpenQuestion(id="d1", field="seeding", text=str(exc), impact="high")
            return Generated(None, None, [question], [])
        groups = draw.groups
    if schedule is None:
        question = OpenQuestion(
            id="s0", field="schedule.days", text="When and where is it played?", impact="high"
        )
        return Generated(draw, None, [question], [])
    bracket = build_bracket(fmt, rules.advancement) if fmt.knockout else None
    group_rounds = fmt.group_rounds
    try:
        plan = build_schedule(groups, bracket, schedule, seed=seed, group_rounds=group_rounds)
    except ScheduleInfeasible as exc:
        relaxations = suggest_relaxations(
            groups, bracket, schedule, seed=seed, group_rounds=group_rounds
        )
        options = [r.summary for r in relaxations if r.feasible]
        question = OpenQuestion(
            id="s1",
            field="schedule",
            text=f"The matches do not fit: {exc}. What should we change?",
            options=options,
            impact="high",
        )
        return Generated(draw, None, [question], relaxations)
    return Generated(draw, plan, [], [])


def move_match(
    data: SetupDraftData, code: str, date: dt.date, start: str, pitch: str | None
) -> SetupDraftData:
    """Pin one match to a slot; the schedule is rebuilt around it."""
    if not data.schedule:
        raise UnknownAnswer("there is no schedule yet")
    draft = data.model_copy(deep=True)
    assert draft.schedule is not None
    slots = [s for s in draft.schedule.get("fixed_slots", []) if s["match_code"] != code]
    slot = FixedSlot(match_code=code, date=date, start=dt.time.fromisoformat(start), pitch=pitch)
    draft.schedule["fixed_slots"] = [*slots, slot.model_dump(mode="json")]
    return draft


def draw_out(draw: Draw, teams: Sequence[DraftTeam]) -> DrawOut:
    names = {t.key: t.name for t in teams}
    placements = {p.team: p for p in draw.placements}
    groups = []
    for index, members in enumerate(draw.groups):
        rows = []
        for key in members:
            p = placements[key]
            reason = f"Pot {p.pot}" if p.pot else "Unseeded"
            if p.seed_value is not None and p.seeded_by.value == "previous_placement":
                reason += f" (placed {int(p.seed_value)} last time)"
            if p.kept_apart:
                reason += "; kept apart: " + ", ".join(p.kept_apart)
            rows.append(DrawTeamOut(key=key, name=names.get(key, key), pot=p.pot, reason=reason))
        groups.append(DrawGroupOut(group=group_letter(index), teams=rows))
    return DrawOut(seed=draw.seed.hex(), method=draw.method, groups=groups)


def schedule_out(plan: SchedulePlan) -> ScheduleOut:
    matches = [
        PlannedMatch(
            code=m.code,
            stage=m.stage,
            group=m.group,
            round=m.round,
            home=m.home,
            away=m.away,
            home_source=m.home_source,
            away_source=m.away_source,
            day=m.day,
            pitch=m.pitch,
            starts_at=m.starts_at,
            ends_at=m.ends_at,
            local_date=m.local_date,
            local_time=m.local_time.isoformat("minutes"),
        )
        for m in plan.matches
    ]
    quality = {
        "hard_violations": plan.quality.hard_violations,
        "min_rest_minutes": plan.quality.min_rest_minutes,
        "max_idle_minutes": plan.quality.max_idle_minutes,
        "main_pitch_spread": plan.quality.main_pitch_spread,
        "group_stage_last_day": plan.quality.group_stage_last_day,
        "final_in_best_slot": plan.quality.final_in_best_slot,
    }
    return ScheduleOut(matches=matches, quality=quality)


def engine_plan_json(plan: SchedulePlan) -> dict[str, object]:
    """The engine plan in full (rescheduling needs every field back)."""
    matches = []
    for m in plan.matches:
        data = dataclasses.asdict(m)
        data["local_date"] = m.local_date.isoformat()
        data["local_time"] = m.local_time.isoformat("minutes")
        matches.append(data)
    return {"matches": matches, "walkovers": list(plan.walkovers), "seed": plan.seed.hex()}


def engine_plan_from(data: dict[str, Any], policy: SchedulePolicy) -> SchedulePlan:
    matches = []
    for m in data["matches"]:
        fields = dict(m)
        for name in ("teams", "depends_on", "follows"):
            fields[name] = tuple(fields[name])
        fields["local_date"] = dt.date.fromisoformat(fields["local_date"])
        fields["local_time"] = dt.time.fromisoformat(fields["local_time"])
        matches.append(ScheduledMatch(**fields))
    quality = ScheduleQuality(0, None, None, 0, None, None)
    return SchedulePlan(
        tuple(matches),
        tuple(data.get("walkovers", [])),
        quality,
        bytes.fromhex(data["seed"]),
        "reschedule",
    )
