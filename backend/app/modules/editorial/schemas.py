"""Editorial schemas (docs/05-api.md, Editor)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.content.schemas import ReviewItem, ReviewSummary


class QueueEntry(BaseModel):
    story: ReviewSummary
    claimed_by: UUID | None
    claimed_at: datetime | None


class QueueItem(BaseModel):
    story: ReviewItem
    claimed_by: UUID | None
    claimed_at: datetime | None


class CorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["mistake", "privacy", "illegal", "other"] = "mistake"
    text: str = Field(min_length=3, max_length=2000)


class CorrectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["fixed", "rejected"]
    note: str | None = Field(default=None, max_length=2000)  # statement of reasons


class CorrectionOut(BaseModel):
    id: UUID
    tournament_id: UUID
    story_id: UUID
    kind: str
    text: str
    status: str
    note: str | None  # the editor's statement of reasons
    created_at: datetime
    resolved_at: datetime | None
    story_headline: str | None = None  # editors only
    story_status: str | None = None  # editors only


class UnpublishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=2000)  # statement of reasons (DSA)
