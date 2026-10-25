"""Editorial: the review queue for held AI stories and readers' correction reports.

Editors (global role `editor`) claim stories that the checker held back (`blocked_claim`)
or that need a human (`sensitive`), edit and re-check them, then approve, reject,
regenerate or unpublish. Readers report mistakes in published stories as corrections.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import transaction
from app.core.errors import Conflict, NotFound
from app.core.llm import LLMGateway
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.content import service as content
from app.modules.content.schemas import (
    CheckResult,
    ReviewSummary,
    StoryAction,
    StoryEdit,
    StoryOut,
)
from app.modules.editorial.models import Correction, ReviewClaim
from app.modules.editorial.schemas import (
    CorrectionIn,
    CorrectionOut,
    CorrectionPatch,
    QueueEntry,
    QueueItem,
)


def require_editor(viewer: Viewer) -> UUID:
    """The editor's user id; everyone else does not even see the editorial area."""
    if "editor" not in viewer.global_roles or viewer.user_id is None:
        raise NotFound()
    return viewer.user_id


async def _claims(db: AsyncSession, story_ids: list[UUID]) -> dict[UUID, ReviewClaim]:
    if not story_ids:
        return {}
    rows = await db.scalars(select(ReviewClaim).where(ReviewClaim.story_id.in_(story_ids)))
    return {r.story_id: r for r in rows}


async def queue(db: AsyncSession, viewer: Viewer, reason: str | None) -> list[QueueEntry]:
    """Open review items, oldest first, with who has claimed them."""
    require_editor(viewer)
    stories = await content.stories_in_review(db, reason)
    claims = await _claims(db, [s.id for s in stories])
    return [_entry(s, claims.get(s.id)) for s in stories]


def _entry(story: ReviewSummary, claim: ReviewClaim | None) -> QueueEntry:
    return QueueEntry(
        story=story,
        claimed_by=claim.editor_id if claim else None,
        claimed_at=claim.claimed_at if claim else None,
    )


async def item(db: AsyncSession, viewer: Viewer, story_id: UUID) -> QueueItem:
    """One review item: text, fact sheet, check result and history."""
    require_editor(viewer)
    claim = await db.get(ReviewClaim, story_id)
    return QueueItem(
        story=await content.review_item(db, story_id),
        claimed_by=claim.editor_id if claim else None,
        claimed_at=claim.claimed_at if claim else None,
    )


async def claim(db: AsyncSession, clock: Clock, viewer: Viewer, story_id: UUID) -> QueueItem:
    """Take a story; 409 when another editor already has it."""
    editor = require_editor(viewer)
    await content.review_item(db, story_id)  # 404 for an unknown story
    async with transaction(db):
        existing = await db.get(ReviewClaim, story_id)
        if existing is not None and existing.editor_id != editor:
            raise Conflict("another editor is working on this story")
        if existing is None:
            db.add(ReviewClaim(story_id=story_id, editor_id=editor, claimed_at=clock.now()))
    return await item(db, viewer, story_id)


async def take_next(db: AsyncSession, clock: Clock, viewer: Viewer) -> QueueItem | None:
    """Claim the oldest unclaimed story in review, if any."""
    require_editor(viewer)
    stories = await content.stories_in_review(db)
    claims = await _claims(db, [s.id for s in stories])
    free = next((s for s in stories if s.id not in claims), None)
    return await claim(db, clock, viewer, free.id) if free else None


async def edit(
    db: AsyncSession, clock: Clock, viewer: Viewer, story_id: UUID, data: StoryEdit, version: int
) -> QueueItem:
    editor = require_editor(viewer)
    await content.edit_story(db, clock, editor, story_id, data, version)
    return await item(db, viewer, story_id)


async def check(db: AsyncSession, viewer: Viewer, story_id: UUID) -> CheckResult:
    require_editor(viewer)
    return await content.check_story(db, story_id)


async def decide(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    story_id: UUID,
    action: StoryAction,
    reason: str | None = None,
) -> ReviewSummary:
    """Approve, reject or unpublish (with a statement of reasons); the item leaves the
    queue, and open reports about the story are closed with the reason."""
    editor = require_editor(viewer)
    summary = await content.decide_story(db, clock, editor, story_id, action, reason)
    if action == "unpublish":
        async with transaction(db):
            reports = await db.scalars(
                select(Correction).where(
                    Correction.story_id == story_id, Correction.status == "open"
                )
            )
            for report in reports:
                report.status, report.note = "fixed", reason
                report.resolved_by, report.resolved_at = editor, clock.now()
    async with transaction(db):
        existing = await db.get(ReviewClaim, story_id)
        if existing is not None:
            await db.delete(existing)
    return summary


async def regenerate(
    db: AsyncSession, clock: Clock, llm: LLMGateway, viewer: Viewer, story_id: UUID
) -> list[StoryOut]:
    require_editor(viewer)
    return await content.regenerate_story(db, clock, llm, story_id)


def _correction_out(row: Correction) -> CorrectionOut:
    return CorrectionOut(
        id=row.id,
        tournament_id=row.tournament_id,
        story_id=row.story_id,
        kind=row.kind,
        text=row.text,
        status=row.status,
        note=row.note,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


async def report_correction(
    db: AsyncSession, clock: Clock, viewer: Viewer, story_id: UUID, data: CorrectionIn
) -> CorrectionOut:
    """A signed-in reader reports a mistake in a published story."""
    tournament_id = await content.story_tournament(db, story_id)
    async with transaction(db):
        row = Correction(
            tournament_id=tournament_id,
            story_id=story_id,
            reported_by=viewer.user_id,
            kind=data.kind,
            text=data.text,
            status="open",
            created_at=clock.now(),
        )
        db.add(row)
    return _correction_out(row)


async def corrections(db: AsyncSession, viewer: Viewer, status: str | None) -> list[CorrectionOut]:
    """Reported corrections, oldest first (editors)."""
    require_editor(viewer)
    query = select(Correction)
    if status:
        query = query.where(Correction.status == status)
    rows = list(await db.scalars(query.order_by(Correction.created_at, Correction.id)))
    stories = await content.story_summaries(db, list({r.story_id for r in rows}))
    out = []
    for row in rows:
        story = stories.get(row.story_id)
        out.append(
            _correction_out(row).model_copy(
                update={
                    "story_headline": story.headline if story else None,
                    "story_status": story.status if story else None,
                }
            )
        )
    return out


async def stories(db: AsyncSession, viewer: Viewer, status: str) -> list[ReviewSummary]:
    """Published or unpublished stories (editors), latest change first."""
    require_editor(viewer)
    return await content.editor_stories(db, status)


async def resolve_correction(
    db: AsyncSession, clock: Clock, viewer: Viewer, correction_id: UUID, data: CorrectionPatch
) -> CorrectionOut:
    editor = require_editor(viewer)
    async with transaction(db):
        row = await db.get(Correction, correction_id)
        if row is None:
            raise NotFound()
        row.status, row.note = data.status, data.note
        row.resolved_by = editor
        row.resolved_at = clock.now()
    return _correction_out(row)


async def my_reports(db: AsyncSession, viewer: Viewer) -> list[CorrectionOut]:
    """The signed-in reader's reports with their outcome and the reasons."""
    rows = await db.scalars(
        select(Correction)
        .where(Correction.reported_by == viewer.user_id)
        .order_by(Correction.created_at.desc())
    )
    return [_correction_out(r) for r in rows]
