"""Scoring API schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_seq: int = Field(ge=1)
    type: str
    payload: dict[str, Any] = {}
    team_id: UUID | None = None
    player_id: UUID | None = None
    clock: str | None = Field(default=None, max_length=10)


class LiveScore(BaseModel):
    home_goals: int
    away_goals: int
    period: int
    finished: bool
    home_shootout: int = 0
    away_shootout: int = 0


class EventAccepted(BaseModel):
    seq: int
    duplicate: bool
    live: LiveScore
    moments: list[str]


class FinishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_goals: int = Field(ge=0)
    away_goals: int = Field(ge=0)


class ResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_goals: int = Field(ge=0)
    away_goals: int = Field(ge=0)
    decided_by: Literal["regulation", "extra_time", "penalties"] = "regulation"
    home_penalties: int | None = Field(default=None, ge=0)
    away_penalties: int | None = Field(default=None, ge=0)


class MatchStatus(BaseModel):
    match_id: UUID
    status: str
    result: dict[str, Any] | None = None


class PassCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pitch_id: UUID | None = None
    match_id: UUID | None = None
    label: str = Field(min_length=1, max_length=80)
    valid_until: datetime | None = None


class PassOut(BaseModel):
    id: UUID
    label: str
    pitch_id: UUID | None
    match_id: UUID | None
    valid_from: datetime  # passes work on the tournament days only
    valid_until: datetime
    revoked: bool
    token: str  # shown in the QR; organisers only
    scan_url: str


class ScorerTeam(BaseModel):
    id: UUID
    name: str
    short_name: str | None = None


class ScorerMatch(BaseModel):
    match_id: UUID
    code: str
    starts_at: datetime
    status: str
    home_team_id: UUID | None
    away_team_id: UUID | None
    tournament_id: UUID
    tournament_name: str
    sport: str
    stage: str
    pitch: str | None
    home: ScorerTeam | None
    away: ScorerTeam | None
    data_level: str  # "events" (live scoring) or "results" (final score only)
    events_recorded: int
    last_event_at: datetime | None


class EventPadButton(BaseModel):
    """One button of the scorer pad. `type` and `payload` are what to post as `EventIn`;
    `period_start`/`period_end` also need `payload.period` (the period starting or ending)."""

    id: str  # unique on the pad, e.g. "shootout_scored"
    type: str  # the event type to post, e.g. "shootout_kick"
    label: str
    group: Literal["score", "play", "discipline", "control"]
    team: bool  # needs `team_id`
    player: Literal["required", "optional", "none"] = "none"
    player_prompt: str | None = None
    points: int = 0  # added to the team's score
    follow_up: str | None = None  # button offered right after (goal -> assist), skippable
    payload: dict[str, Any] = {}
    knockout_only: bool = False


class EventPad(BaseModel):
    """The scorer pad for a sport (`getEventTypes`)."""

    sport: str
    clock: bool  # a running match clock in minutes
    periods: list[str]  # regulation periods; extra time follows when the rules allow it
    score_label: str
    event_types: list[str]  # every type `postMatchEvent` accepts
    buttons: list[EventPadButton]


class ScoredEvent(BaseModel):
    seq: int
    client_seq: int
    type: str
    team_id: UUID | None
    player_id: UUID | None
    period: int | None
    clock: str | None
    payload: dict[str, Any]
    undone: bool
    undoes_seq: int | None
    created_at: datetime


class ScorerRosterPlayer(BaseModel):
    """A player the scorer may see (hidden juniors never appear)."""

    id: UUID
    display_name: str
    shirt_number: int | None


class ScoringState(BaseModel):
    """Everything the scoring console needs (`getScoringState`), for a pass or staff."""

    match_id: UUID
    tournament_id: UUID
    sport: str
    code: str
    stage: str
    status: str
    data_level: str
    starts_at: datetime
    pitch: str | None
    home: ScorerTeam
    away: ScorerTeam
    score: LiveScore
    period: int  # 0 before kick-off
    periods: int  # regulation periods
    period_minutes: int | None
    between_periods: bool  # a period ended and the next has not started
    home_roster: list[ScorerRosterPlayer]
    away_roster: list[ScorerRosterPlayer]
    events: list[ScoredEvent]  # newest first, undone ones included
    last_client_seq: int  # new events must use a higher client_seq
    role: Literal["scorer", "organiser"]
    server_time: datetime
