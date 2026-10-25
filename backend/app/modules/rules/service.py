"""Rules: draft and confirmed rule configs, worked examples and a plain-language summary.

A config is validated by the engine before it can be confirmed. Each confirmation is a new
version (1, 2, …); the previous one is superseded and a recalculation is deferred.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.db import transaction
from app.core.errors import NotFound, RulesNotConfirmed, ValidationFailed
from app.core.ids import new_id
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.rules.models import RuleConfigRecord, RuleTest
from app.modules.rules.schemas import Language, RuleConfigOut, RulesSummary, WorkedExample
from engine.model import MatchResult, TeamRef, TournamentState
from engine.rules.config import RuleConfig, Tiebreaker
from engine.rules.format import FormatSpec
from engine.rules.validate import validate_rule_config
from engine.sports.football import FootballResult
from engine.standings import compute_standings

# --- versions --------------------------------------------------------------------------------


def _out(record: RuleConfigRecord) -> RuleConfigOut:
    return RuleConfigOut(
        id=record.id,
        tournament_id=record.tournament_id,
        version=record.version,
        status=record.status,
        config=record.config,
    )


async def save_draft(
    db: AsyncSession,
    clock: Clock,
    tournament_id: UUID,
    config: RuleConfig,
    extraction: dict[str, Any] | None = None,
) -> RuleConfigOut:
    """Store (or replace) the tournament's draft rules; drafts may still have issues."""
    async with transaction(db):
        draft = (
            await db.execute(
                select(RuleConfigRecord).where(
                    RuleConfigRecord.tournament_id == tournament_id,
                    RuleConfigRecord.status == "draft",
                )
            )
        ).scalar_one_or_none()
        if draft is None:
            draft = RuleConfigRecord(
                id=new_id(),
                tournament_id=tournament_id,
                version=0,
                status="draft",
                created_at=clock.now(),
                config={},
            )
            db.add(draft)
        draft.config = config.model_dump(mode="json")
        draft.extraction = extraction
    return _out(draft)


async def confirm(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID
) -> RuleConfigOut:
    """Confirm the draft as the next version; the engine must accept it first."""
    async with transaction(db):
        draft = (
            await db.execute(
                select(RuleConfigRecord)
                .where(
                    RuleConfigRecord.tournament_id == tournament_id,
                    RuleConfigRecord.status == "draft",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if draft is None:
            raise NotFound("no draft rules to confirm")
        issues = validate_rule_config(RuleConfig.model_validate(draft.config))
        if issues:
            raise ValidationFailed("; ".join(f"{i.path}: {i.message}" for i in issues))
        latest = (
            await db.execute(
                select(func.max(RuleConfigRecord.version)).where(
                    RuleConfigRecord.tournament_id == tournament_id
                )
            )
        ).scalar_one()
        for previous in (
            await db.execute(
                select(RuleConfigRecord).where(
                    RuleConfigRecord.tournament_id == tournament_id,
                    RuleConfigRecord.status == "confirmed",
                )
            )
        ).scalars():
            previous.status = "superseded"
        draft.version = (latest or 0) + 1
        draft.status = "confirmed"
        draft.confirmed_by = viewer.user_id
        draft.confirmed_at = clock.now()
        await db.flush()
        await competitions.set_rule_config(db, tournament_id, draft.id)
        for example in worked_examples(RuleConfig.model_validate(draft.config)):
            db.add(
                RuleTest(
                    id=new_id(),
                    rule_config_id=draft.id,
                    kind=example.kind,
                    input=example.input,
                    expected=example.expected,
                    passed=example.passed,
                )
            )
        await jobs.defer(db, "recalc_tournament", tournament_id=tournament_id)
    return _out(draft)


async def confirmed_config(db: AsyncSession, tournament_id: UUID) -> RuleConfigOut:
    """The tournament's current confirmed rules, or `rules_not_confirmed`."""
    record = (
        await db.execute(
            select(RuleConfigRecord).where(
                RuleConfigRecord.tournament_id == tournament_id,
                RuleConfigRecord.status == "confirmed",
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise RulesNotConfirmed()
    return _out(record)


# --- worked examples -------------------------------------------------------------------------

_EXAMPLE_TEAMS = ("Team A", "Team B", "Team C")


def _mini_state(config: RuleConfig, results: Sequence[MatchResult]) -> TournamentState:
    teams = tuple(TeamRef(t, t) for t in _EXAMPLE_TEAMS)
    fmt = FormatSpec(team_count=3, group_sizes=[3])
    return TournamentState(teams, {"X": _EXAMPLE_TEAMS}, tuple(results), (), config, fmt)


def worked_examples(config: RuleConfig) -> list[WorkedExample]:
    """Examples run through the engine so the organiser can check the rules do what they
    expect: points per result and how a tie on points is broken."""
    examples = [
        WorkedExample(
            kind="worked_example",
            title=f"A {outcome} is worth {points} points",
            input={"outcome": outcome},
            expected={"points": points},
            passed=True,
        )
        for outcome, points in config.points.table.items()
    ]
    if config.sport != "football":
        return examples
    a, b, c = _EXAMPLE_TEAMS

    def result(home: str, away: str, hg: int, ag: int) -> MatchResult:
        return MatchResult(f"{home}-{away}", "X", home, away, FootballResult(hg, ag))

    # A and B both beat C and draw each other: level on points, A by more goals.
    results = [result(a, c, 2, 0), result(b, c, 1, 0), result(a, b, 1, 1)]
    rows = compute_standings(_mini_state(config, results)).groups[0].rows
    decided = next((r.decided_by for r in rows if r.position == 1), None)
    examples.append(
        WorkedExample(
            kind="edge_case",
            title="Two teams level on points",
            input={"results": [f"{r.home} {r.outcome} {r.away}" for r in results]},
            expected={
                "order": [r.team for r in rows],
                "decided_by": decided.value if isinstance(decided, Tiebreaker) else None,
            },
            passed=rows[0].team == a or rows[0].tied_unresolved,
        )
    )
    return examples


# --- summary ---------------------------------------------------------------------------------

_TIEBREAKER_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "points": "points", "points_per_game": "points per game", "wins": "wins",
        "head_to_head_points": "points in the matches between the tied teams",
        "head_to_head_diff": "goal difference in those matches",
        "head_to_head_for": "goals scored in those matches",
        "score_diff": "goal difference", "score_for": "goals scored",
        "away_score_for": "away goals", "fair_play": "fair play (fewer cards)",
        "draw_lots": "drawing lots",
    },
    "fi": {
        "points": "pisteet", "points_per_game": "pisteet per ottelu", "wins": "voitot",
        "head_to_head_points": "keskinäisten otteluiden pisteet",
        "head_to_head_diff": "keskinäisten otteluiden maaliero",
        "head_to_head_for": "keskinäisten otteluiden tehdyt maalit",
        "score_diff": "maaliero", "score_for": "tehdyt maalit",
        "away_score_for": "vierasmaalit", "fair_play": "fair play (vähemmän kortteja)",
        "draw_lots": "arvonta",
    },
    "bn": {
        "points": "পয়েন্ট", "points_per_game": "ম্যাচ প্রতি পয়েন্ট", "wins": "জয়",
        "head_to_head_points": "সমান দলগুলোর নিজেদের ম্যাচের পয়েন্ট",
        "head_to_head_diff": "সেই ম্যাচগুলোর গোল ব্যবধান",
        "head_to_head_for": "সেই ম্যাচগুলোতে করা গোল",
        "score_diff": "গোল ব্যবধান", "score_for": "করা গোল",
        "away_score_for": "অ্যাওয়ে গোল", "fair_play": "ফেয়ার প্লে (কম কার্ড)",
        "draw_lots": "লটারি",
    },
}  # fmt: skip
_PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "points": "A win is worth {win} points, a draw {draw} and a loss {loss}.",
        "ties": "Teams level on points are separated by {list}.",
        "advance": "The top {n} of each group go through.",
        "rest": "The best {n} of the remaining teams also go through.",
        "length": "Matches last {periods} x {minutes} minutes.",
        "knockout": "A drawn knockout match goes to {decider}.",
        "penalties": "penalties", "extra_time": "extra time, then penalties",
        "walkover": "A walkover counts as {for_}-{against}.",
    },
    "fi": {
        "points": "Voitosta saa {win} pistettä, tasapelistä {draw} ja tappiosta {loss}.",
        "ties": "Tasapisteissä järjestyksen ratkaisee {list}.",
        "advance": "Jokaisen lohkon {n} parasta jatkaa.",
        "rest": "Lisäksi {n} parasta muista joukkueista jatkaa.",
        "length": "Ottelut kestävät {periods} x {minutes} minuuttia.",
        "knockout": "Tasapelin jälkeen pudotuspelissä on {decider}.",
        "penalties": "rangaistuspotkukilpailu",
        "extra_time": "jatkoaika ja sitten rangaistuspotkut",
        "walkover": "Luovutusvoitto kirjataan {for_}-{against}.",
    },
    "bn": {
        "points": "জয়ে {win} পয়েন্ট, ড্রয়ে {draw} এবং হারে {loss}।",
        "ties": "পয়েন্ট সমান হলে ক্রম ঠিক হয়: {list}।",
        "advance": "প্রতিটি গ্রুপের সেরা {n} দল পরের পর্বে যায়।",
        "rest": "বাকি দলগুলোর মধ্যে সেরা {n} দলও পরের পর্বে যায়।",
        "length": "প্রতিটি ম্যাচ {periods} x {minutes} মিনিট।",
        "knockout": "নকআউট ম্যাচ ড্র হলে {decider}।",
        "penalties": "পেনাল্টি শুটআউট", "extra_time": "অতিরিক্ত সময়, তারপর পেনাল্টি",
        "walkover": "ওয়াকওভার {for_}-{against} হিসেবে গণ্য হয়।",
    },
}  # fmt: skip


def summarise(config: RuleConfig, language: Language) -> list[str]:
    """The rules in plain words, in the organiser's or the viewer's language."""
    words, phrase = _TIEBREAKER_WORDS[language], _PHRASES[language]
    table = config.points.table
    lines = []
    if {"win", "draw", "loss"} <= set(table):
        lines.append(phrase["points"].format(**table))
    order = [words[t.value] for t in config.tiebreakers if t not in (Tiebreaker.POINTS,)]
    if order:
        lines.append(phrase["ties"].format(list=", ".join(order)))
    advancement = config.advancement
    if config.format == "groups_then_knockout" and advancement.per_group:
        lines.append(phrase["advance"].format(n=advancement.per_group))
        if advancement.best_of_rest:
            lines.append(phrase["rest"].format(n=advancement.best_of_rest))
    match = config.match
    if "periods" in match and "period_minutes" in match:
        lines.append(
            phrase["length"].format(periods=match["periods"], minutes=match["period_minutes"])
        )
    if config.format in ("groups_then_knockout", "knockout"):
        decider = phrase["extra_time"] if match.get("extra_time") else phrase["penalties"]
        lines.append(phrase["knockout"].format(decider=decider))
    if "score_for" in config.walkover:
        lines.append(
            phrase["walkover"].format(
                for_=config.walkover["score_for"], against=config.walkover.get("score_against", 0)
            )
        )
    return lines


async def rules_summary(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, language: Language
) -> RulesSummary:
    """Plain-language rules of a tournament the viewer may see."""
    await competitions.get_tournament(db, viewer, tournament_id)
    record = await confirmed_config(db, tournament_id)
    config = RuleConfig.model_validate(record.config)
    return RulesSummary(
        tournament_id=tournament_id,
        version=record.version,
        language=language,
        lines=summarise(config, language),
    )
