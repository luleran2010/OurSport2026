"""Setup schemas: what the extraction tasks return, the stored draft, and the API.

Every extracted value carries the quote it came from; a value without a quote is not
used (the catalogue fills the gap as an assumption instead).
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from engine.rules.config import Tiebreaker

Impact = Literal["high", "medium", "low"]
FileKind = Literal["rulebook", "team_list", "history", "venue", "other"]


# --- extraction outputs (structured LLM output) ---------------------------------------------


class QuotedInt(BaseModel):
    value: int | None = None
    quote: str | None = None


class QuotedBool(BaseModel):
    value: bool | None = None
    quote: str | None = None


class ExtractedQuestion(BaseModel):
    field: str
    text: str
    quotes: list[str] = []
    options: list[str] = []


class RulesExtraction(BaseModel):
    win_points: QuotedInt = QuotedInt()
    draw_points: QuotedInt = QuotedInt()
    loss_points: QuotedInt = QuotedInt()
    tiebreakers: list[Tiebreaker] = []
    tiebreakers_quote: str | None = None
    periods: QuotedInt = QuotedInt()
    period_minutes: QuotedInt = QuotedInt()
    half_time_minutes: QuotedInt = QuotedInt()
    extra_time: QuotedBool = QuotedBool()
    walkover_score_for: QuotedInt = QuotedInt()
    walkover_score_against: QuotedInt = QuotedInt()
    questions: list[ExtractedQuestion] = []
    ignored_instructions: bool = False


class FormatExtraction(BaseModel):
    group_count: QuotedInt = QuotedInt()
    per_group: QuotedInt = QuotedInt()
    best_of_rest: QuotedInt = QuotedInt()
    third_place_match: QuotedBool = QuotedBool()
    questions: list[ExtractedQuestion] = []


class PlacementQuote(BaseModel):
    team: str
    placement: int = Field(ge=1)
    quote: str


class KeepApart(BaseModel):
    rule: Literal[
        "previous_semi_finalists", "previous_quarter_finalists", "same_organisation", "listed_teams"
    ]
    teams: list[str] = []
    quote: str


class FixedGroup(BaseModel):
    team: str
    group: str  # "A"
    quote: str


class SeedingExtraction(BaseModel):
    previous_placements: list[PlacementQuote] = []
    keep_apart: list[KeepApart] = []
    fixed: list[FixedGroup] = []
    questions: list[ExtractedQuestion] = []


class DayQuote(BaseModel):
    date: date
    start: str  # "09:00"
    end: str
    quote: str


class BreakQuote(BaseModel):
    start: str
    end: str
    quote: str


class ScheduleExtraction(BaseModel):
    days: list[DayQuote] = []
    pitches: QuotedInt = QuotedInt()
    pitch_names: list[str] = []
    match_minutes: QuotedInt = QuotedInt()
    break_minutes: QuotedInt = QuotedInt()
    min_rest_minutes: QuotedInt = QuotedInt()
    max_matches_per_team_per_day: QuotedInt = QuotedInt()
    breaks: list[BreakQuote] = []
    questions: list[ExtractedQuestion] = []


class TeamRow(BaseModel):
    name: str
    short_name: str | None = None
    organisation: str | None = None


class TeamsExtraction(BaseModel):
    teams: list[TeamRow] = []


class ExtractionInputs(BaseModel):
    """What an extraction task sees: redacted text plus the closed catalogue."""

    document: str
    organiser_language: str
    catalogue: list[dict[str, str]] = []
    team_count: int | None = None


# --- the stored draft ------------------------------------------------------------------------


class DraftTeam(BaseModel):
    key: str  # "t01": the id used in engine seeding and draw inputs
    name: str
    short_name: str | None = None
    organisation: str | None = None
    previous_placement: int | None = None
    source: Literal["table", "text", "photo", "llm"] = "table"


class Assumption(BaseModel):
    id: str
    field: str
    chosen: str
    catalogue_id: str | None = None
    reason: str
    alternatives: list[str] = []


class OpenQuestion(BaseModel):
    id: str
    field: str
    text: str
    quotes: list[str] = []
    options: list[str] = []
    impact: Impact = "medium"
    ref: dict[str, str] = {}  # what an answer changes, e.g. the two team keys of a merge


class SetupDraftData(BaseModel):
    rules: dict[str, Any]  # engine RuleConfig
    format: dict[str, Any]  # engine FormatSpec
    seeding: dict[str, Any]  # engine SeedingPolicy
    schedule: dict[str, Any] | None  # engine SchedulePolicy; None until days and pitches are known
    teams: list[DraftTeam]
    quotes: dict[str, str] = {}  # field -> source quote


# --- API -------------------------------------------------------------------------------------


class SetupStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organisation_id: UUID
    name: str = Field(min_length=2, max_length=120)
    sport: Literal["football", "futsal"] = "football"  # this release (ice hockey: next)
    age_group: str = "adult"
    time_zone: str = "Europe/Helsinki"
    starts_on: date | None = None
    ends_on: date | None = None
    series_id: UUID | None = None
    organiser_language: Literal["fi", "en", "bn"] = "en"


class IntakeFileOut(BaseModel):
    id: UUID
    kind: FileKind
    mime: str
    characters: int
    redaction_report: dict[str, int]


class DraftOut(BaseModel):
    version: int
    draft: SetupDraftData
    assumptions: list[Assumption]
    open_questions: list[OpenQuestion]


class DrawTeamOut(BaseModel):
    key: str
    name: str
    pot: int | None
    reason: str


class DrawGroupOut(BaseModel):
    group: str
    teams: list[DrawTeamOut]


class DrawOut(BaseModel):
    seed: str  # hex; anyone can reproduce the draw from it
    method: str
    groups: list[DrawGroupOut]


class PlannedMatch(BaseModel):
    code: str
    stage: str
    group: str | None
    round: int | None
    home: str | None  # draft team key
    away: str | None
    home_source: str | None
    away_source: str | None
    day: int
    pitch: str
    starts_at: str
    ends_at: str
    local_date: date
    local_time: str


class ScheduleOut(BaseModel):
    matches: list[PlannedMatch]
    quality: dict[str, Any]


class SetupTournament(BaseModel):
    """The draft tournament a setup builds (what the wizard shows and resumes)."""

    name: str
    organisation_id: UUID
    sport: str
    age_group: str
    is_junior: bool
    time_zone: str
    starts_on: date | None
    ends_on: date | None


class SetupSummary(BaseModel):
    """One of my setups (`listSetups`), newest first."""

    id: UUID
    tournament_id: UUID
    status: str
    tournament: SetupTournament
    updated_at: datetime


class SetupOut(BaseModel):
    id: UUID
    tournament_id: UUID
    tournament: SetupTournament | None = None
    status: str
    failure_reason: str | None = None
    files: list[IntakeFileOut] = []
    draft: DraftOut | None = None
    draw: DrawOut | None = None
    schedule: ScheduleOut | None = None


class Answer(BaseModel):
    question_id: str
    value: str


class AnswersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[Answer] = Field(min_length=1)


class DraftChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str  # "schedule.days", "schedule.pitches", "rules.tiebreakers", …
    value: str


class RegenerateSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relaxation: str | None = None  # the summary of an engine suggestion to apply


class MoveMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    start: str  # "14:00", local time
    pitch: str | None = None


class Published(BaseModel):
    tournament_id: UUID
    status: str
    teams: int
    groups: int
    matches: int


class ScheduleChangeIn(BaseModel):
    """A match-day change: a pitch running late, a closed pitch, a postponed match or a
    withdrawn team."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["delay", "pitch_closed", "postponed", "withdrawn"]
    pitch: str | None = None  # pitch name
    minutes: int | None = Field(default=None, ge=1, le=240)
    match_code: str | None = None
    team_id: UUID | None = None
    not_before: str | None = None  # ISO 8601 UTC


class MovedMatch(BaseModel):
    code: str
    starts_at_before: str
    starts_at_after: str
    pitch_before: str
    pitch_after: str


class ChangePreview(BaseModel):
    plan_id: UUID
    moved: list[MovedMatch]
    walkovers: list[str]
    affected_team_ids: list[UUID]


class ChangeConfirmed(BaseModel):
    schedule_version: int
    moved: int
    walkovers: int


class ConsoleMatch(BaseModel):
    code: str
    status: str
    starts_at: str
    home_team_id: UUID | None
    away_team_id: UUID | None


class ConsolePitch(BaseModel):
    pitch: str
    now: ConsoleMatch | None
    next: ConsoleMatch | None
    delay_minutes: int
    viewers: int = 0  # watching the match on this pitch live


class ConsoleOut(BaseModel):
    pitches: list[ConsolePitch]
    unscored: list[str]  # match codes past their planned end without a result


class RevealStep(BaseModel):
    step: int
    pot: int | None
    group: str
    team: str  # team name


class DrawReveal(BaseModel):
    """The live draw ceremony: the steps revealed so far (pot by pot); the seed shows once
    every team is drawn, so anyone can check the result."""

    tournament_id: UUID
    total: int
    revealed: int
    steps: list[RevealStep]
    seed: str | None
