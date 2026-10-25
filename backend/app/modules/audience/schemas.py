"""Audience API schemas."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.analysis.schemas import MatchCard, TeamHub
from app.modules.content.schemas import StoryOut

TargetType = Literal["organisation", "team", "tournament", "series"]


class FollowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: TargetType
    target_id: UUID
    is_primary: bool = False


class FollowTarget(BaseModel):
    """What a follow points at, for lists (names only; never contacts)."""

    name: str
    short_name: str | None = None
    subtitle: str | None = None  # town, sport, organisation
    sport: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None


class FollowOut(BaseModel):
    id: UUID
    target_type: TargetType
    target_id: UUID
    is_primary: bool
    notify: dict[str, bool]
    created_at: datetime
    target: FollowTarget | None = None  # None when the target is no longer public


class NotifyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_start: bool | None = None
    goal: bool | None = None
    result: bool | None = None
    scenario_change: bool | None = None
    relevance: bool | None = None
    schedule_change: bool | None = None
    next_opponent: bool | None = None
    news: bool | None = None


class Home(BaseModel):
    primary: TeamHub | None  # None until the user picks "my team"
    following: list[FollowOut]


class FeedItem(BaseModel):
    kind: Literal["result", "next_match", "live"]
    at: datetime
    team_id: UUID | None
    match: MatchCard
    stories: list[StoryOut] = []  # the match report of a result, in every language


class Feed(BaseModel):
    items: list[FeedItem]
    next_cursor: str | None


class NotificationOut(BaseModel):
    id: UUID
    kind: str
    text: str
    team_id: UUID | None
    match_id: UUID | None = None  # what to open when tapped
    tournament_id: UUID | None = None
    created_at: datetime
    read: bool


class NotificationsPage(BaseModel):
    items: list[NotificationOut]  # newest first
    next_cursor: str | None
    unread_count: int


class MarkRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] | None = None  # None: all


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str
    keys: PushKeys
