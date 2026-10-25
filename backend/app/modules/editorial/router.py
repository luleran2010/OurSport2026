"""Editor endpoints (docs/05-api.md, Editor) and readers' correction reports."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ValidationFailed
from app.core.llm import LLMGateway, get_llm
from app.core.time import Clock, get_clock
from app.core.viewer import Member
from app.modules.content.schemas import (
    CheckResult,
    ReviewSummary,
    StoryAction,
    StoryEdit,
    StoryOut,
)
from app.modules.editorial import service
from app.modules.editorial.schemas import (
    CorrectionIn,
    CorrectionOut,
    CorrectionPatch,
    QueueEntry,
    QueueItem,
    UnpublishIn,
)

router = APIRouter(tags=["editor"])
reader_router = APIRouter(tags=["fan"])
Db = Annotated[AsyncSession, Depends(get_session)]
Now = Annotated[Clock, Depends(get_clock)]
Llm = Annotated[LLMGateway, Depends(get_llm)]
Reason = Literal["blocked_claim", "sensitive"]


@router.get("/review-queue", response_model=list[QueueEntry], operation_id="listReviewQueue")
async def review_queue(
    viewer: Member, db: Db, reason: Annotated[Reason | None, Query()] = None
) -> list[QueueEntry]:
    """Stories held for an editor, oldest first."""
    return await service.queue(db, viewer, reason)


@router.post(
    "/review-queue/take-next", response_model=QueueItem | None, operation_id="takeNextReview"
)
async def take_next(viewer: Member, db: Db, clock: Now) -> QueueItem | None:
    """Claim the oldest unclaimed item (null when the queue is empty)."""
    return await service.take_next(db, clock, viewer)


@router.get("/review-queue/{story_id}", response_model=QueueItem, operation_id="getReviewItem")
async def review_item(story_id: UUID, viewer: Member, db: Db) -> QueueItem:
    """Text, the fact sheet, the check result and earlier versions."""
    return await service.item(db, viewer, story_id)


@router.post("/review-queue/{story_id}/claim", response_model=QueueItem, operation_id="claimReview")
async def claim(story_id: UUID, viewer: Member, db: Db, clock: Now) -> QueueItem:
    """Take an item (409 when another editor has it)."""
    return await service.claim(db, clock, viewer, story_id)


@router.patch("/stories/{story_id}", response_model=QueueItem, operation_id="editStory")
async def edit_story(
    story_id: UUID,
    body: StoryEdit,
    viewer: Member,
    db: Db,
    clock: Now,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> QueueItem:
    """New headline and body (If-Match: the story version); run `check` before approving."""
    version = "".join(c for c in (if_match or "") if c.isdigit())
    if not version:
        raise ValidationFailed("send If-Match with the story version")
    return await service.edit(db, clock, viewer, story_id, body, int(version))


@router.post("/stories/{story_id}/check", response_model=CheckResult, operation_id="checkStory")
async def check_story(story_id: UUID, viewer: Member, db: Db) -> CheckResult:
    """Run the claim checker on the current text."""
    return await service.check(db, viewer, story_id)


def _decision(action: StoryAction, operation_id: str, summary: str) -> None:
    async def decide(story_id: UUID, viewer: Member, db: Db, clock: Now) -> ReviewSummary:
        return await service.decide(db, clock, viewer, story_id, action)

    decide.__doc__ = summary
    router.post(
        f"/stories/{{story_id}}/{action}", response_model=ReviewSummary, operation_id=operation_id
    )(decide)


_decision("approve", "approveStory", 'Publish, labelled "reviewed by an editor".')
_decision("reject", "rejectStory", "Block the story; it is not published.")


@router.post(
    "/stories/{story_id}/unpublish", response_model=ReviewSummary, operation_id="unpublishStory"
)
async def unpublish(
    story_id: UUID, body: UnpublishIn, viewer: Member, db: Db, clock: Now
) -> ReviewSummary:
    """Take a published story down with a statement of reasons (sent to its reporters)."""
    return await service.decide(db, clock, viewer, story_id, "unpublish", body.reason)


@router.post(
    "/stories/{story_id}/regenerate",
    response_model=list[StoryOut],
    operation_id="regenerateStory",
)
async def regenerate(
    story_id: UUID, viewer: Member, db: Db, clock: Now, llm: Llm
) -> list[StoryOut]:
    """Write the story again from the current facts."""
    return await service.regenerate(db, clock, llm, viewer, story_id)


@router.get("/editor/stories", response_model=list[ReviewSummary], operation_id="listEditorStories")
async def editor_stories(
    viewer: Member,
    db: Db,
    status: Annotated[Literal["published", "unpublished"], Query()] = "published",
) -> list[ReviewSummary]:
    """Published or unpublished stories, latest change first (editors)."""
    return await service.stories(db, viewer, status)


@router.get("/corrections", response_model=list[CorrectionOut], operation_id="listCorrections")
async def corrections(
    viewer: Member,
    db: Db,
    status: Annotated[Literal["open", "fixed", "rejected"] | None, Query()] = "open",
) -> list[CorrectionOut]:
    """Readers' correction reports (default: open ones)."""
    return await service.corrections(db, viewer, status)


@router.patch(
    "/corrections/{correction_id}", response_model=CorrectionOut, operation_id="resolveCorrection"
)
async def resolve(
    correction_id: UUID, body: CorrectionPatch, viewer: Member, db: Db, clock: Now
) -> CorrectionOut:
    """Mark a report fixed or rejected."""
    return await service.resolve_correction(db, clock, viewer, correction_id, body)


@reader_router.post(
    "/stories/{story_id}/corrections",
    status_code=201,
    response_model=CorrectionOut,
    operation_id="reportCorrection",
)
async def report(
    story_id: UUID, body: CorrectionIn, viewer: Member, db: Db, clock: Now
) -> CorrectionOut:
    """Report a mistake in a published story."""
    return await service.report_correction(db, clock, viewer, story_id, body)


@reader_router.get("/me/reports", response_model=list[CorrectionOut], operation_id="listMyReports")
async def my_reports(viewer: Member, db: Db) -> list[CorrectionOut]:
    """Your reports about stories, with the outcome and the editor's reasons."""
    return await service.my_reports(db, viewer)
