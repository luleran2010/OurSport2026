"""Media API schemas (docs/05-api.md, Media)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StreamIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["youtube", "mux", "cloudflare", "other"]
    playback_url: HttpUrl
    rights_confirmed: bool  # the organiser holds the rights to stream this event
    venue_permission: bool  # the venue owner allows streaming
    federation_rules_checked: bool | None = None  # sanctioned competitions only
    keep_replay: bool = False


class StreamOut(BaseModel):
    id: UUID
    match_id: UUID
    provider: str
    playback_url: str
    status: str  # "live", "paused" (an opt-out), "ended"
    keep_replay: bool
    started_at: datetime
    ended_at: datetime | None


class FilmingNoticeOut(BaseModel):
    tournament_id: UUID
    version: int
    texts: dict[str, str]
    published_at: datetime


class AttestationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=20, max_length=2000)


class AttestationOut(BaseModel):
    id: UUID
    statement: str
    created_at: datetime


class OptOutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: UUID | None = None
    player_id: UUID | None = None  # known to the organiser and the family
    reason: str | None = Field(default=None, max_length=1000)


class OptOutOut(BaseModel):
    id: UUID
    team_id: UUID
    player_id: UUID | None
    reason: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolution: str | None


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: str = Field(min_length=3, max_length=1000)
