"""Setup endpoints (docs/05-api.md, Organiser: automatic setup)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import ValidationFailed
from app.core.http_cache import cached
from app.core.llm import LLMGateway, get_llm
from app.core.time import Clock, get_clock
from app.core.viewer import Member
from app.modules.competitions.schemas import FilmingPolicy
from app.modules.setup import matchday, service
from app.modules.setup.schemas import (
    AnswersRequest,
    ChangeConfirmed,
    ChangePreview,
    ConsoleOut,
    DraftChange,
    DrawOut,
    DrawReveal,
    FileKind,
    IntakeFileOut,
    MoveMatch,
    Published,
    RegenerateSchedule,
    ScheduleChangeIn,
    SetupOut,
    SetupStart,
    SetupSummary,
)

router = APIRouter(prefix="/setup", tags=["setup"])
Db = Annotated[AsyncSession, Depends(get_session)]
Now = Annotated[Clock, Depends(get_clock)]
Llm = Annotated[LLMGateway, Depends(get_llm)]


@router.get("", response_model=list[SetupSummary], operation_id="listSetups")
async def list_setups(viewer: Member, db: Db) -> list[SetupSummary]:
    """My setups (tournaments I own or organise), most recently changed first: resume a draft."""
    return await service.list_setups(db, viewer)


@router.post("", status_code=201, response_model=SetupOut, operation_id="startSetup")
async def start_setup(body: SetupStart, viewer: Member, db: Db, clock: Now) -> SetupOut:
    """Start a setup: creates the draft tournament and its session."""
    return await service.start(db, clock, viewer, body)


@router.post(
    "/{session_id}/files",
    status_code=201,
    response_model=IntakeFileOut,
    operation_id="addSetupFile",
)
async def add_setup_file(
    session_id: UUID,
    request: Request,
    viewer: Member,
    db: Db,
    clock: Now,
    kind: Annotated[FileKind, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
) -> IntakeFileOut:
    """Upload a rulebook, team list, history or venue info (a file or pasted text)."""
    settings: Settings = request.app.state.settings
    if file is not None:
        data = await file.read(settings.upload_max_mb * 1024 * 1024 + 1)
        if len(data) > settings.upload_max_mb * 1024 * 1024:
            raise ValidationFailed(f"files up to {settings.upload_max_mb} MB")
        name, mime = file.filename or "upload", file.content_type or ""
    elif text:
        data, name, mime = text.encode(), "pasted.txt", "text/plain"
    else:
        raise ValidationFailed("send a file or text")
    return await service.add_file(
        db, clock, viewer, session_id, kind=kind, filename=name, mime=mime, data=data
    )


@router.post(
    "/{session_id}/extract", status_code=202, response_model=SetupOut, operation_id="extractSetup"
)
async def extract_setup(session_id: UUID, viewer: Member, db: Db, clock: Now, llm: Llm) -> SetupOut:
    """Read the documents and build the draft (runs inline until the job queue, T-031)."""
    return await service.run_extraction(db, clock, llm, viewer, session_id)


@router.get("/{session_id}", response_model=SetupOut, operation_id="getSetup")
async def get_setup(session_id: UUID, viewer: Member, db: Db) -> SetupOut:
    """Status, progress, the draft, assumptions and open questions."""
    return await service.get(db, viewer, session_id)


@router.delete("/{session_id}", status_code=204, operation_id="deleteSetup")
async def delete_setup(session_id: UUID, viewer: Member, db: Db) -> Response:
    """Remove an event that was never published, with its uploads and drafts."""
    await service.delete_setup(db, viewer, session_id)
    return Response(status_code=204)


IfMatch = Annotated[str | None, Header(alias="If-Match")]


@router.post("/{session_id}/answers", response_model=SetupOut, operation_id="answerSetupQuestions")
async def answer_questions(
    session_id: UUID,
    body: AnswersRequest,
    viewer: Member,
    db: Db,
    clock: Now,
    if_match: IfMatch = None,
) -> SetupOut:
    """Answer open questions; when none are left the engine draws and schedules."""
    return await service.answer(db, clock, viewer, session_id, body.answers, if_match)


@router.patch("/{session_id}/draft", response_model=SetupOut, operation_id="changeSetupDraft")
async def change_draft(
    session_id: UUID,
    body: DraftChange,
    viewer: Member,
    db: Db,
    clock: Now,
    if_match: IfMatch = None,
) -> SetupOut:
    """Change an assumption or value; the engine re-validates."""
    return await service.change(db, clock, viewer, session_id, body.field, body.value, if_match)


@router.post("/{session_id}/draw", response_model=SetupOut, operation_id="redrawSetup")
async def redraw(session_id: UUID, viewer: Member, db: Db, clock: Now) -> SetupOut:
    """A new draw with a new seed."""
    return await service.redraw(db, clock, viewer, session_id)


@router.post("/{session_id}/schedule", response_model=SetupOut, operation_id="regenerateSchedule")
async def regenerate_schedule(
    session_id: UUID, body: RegenerateSchedule, viewer: Member, db: Db, clock: Now
) -> SetupOut:
    """Regenerate the schedule, optionally applying one of the engine's suggestions."""
    return await service.regenerate_schedule(db, clock, viewer, session_id, body.relaxation)


@router.patch(
    "/{session_id}/schedule/matches/{code}", response_model=SetupOut, operation_id="moveSetupMatch"
)
async def move_match(
    session_id: UUID, code: str, body: MoveMatch, viewer: Member, db: Db, clock: Now
) -> SetupOut:
    """Move one match; the engine checks it and rebuilds the rest."""
    return await service.move_match(db, clock, viewer, session_id, code, body)


class PublishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filming_policy: FilmingPolicy | None = None  # required unless chosen before


@router.post("/{session_id}/publish", response_model=Published, operation_id="publishSetup")
async def publish(
    session_id: UUID,
    viewer: Member,
    db: Db,
    clock: Now,
    if_match: IfMatch = None,
    body: PublishIn | None = None,
) -> Published:
    """Publish: groups, teams, matches and rules in one transaction; pages go live. The
    filming policy must be chosen (409 `setup_not_ready` otherwise)."""
    policy = body.filming_policy if body else None
    return await service.publish(db, clock, viewer, session_id, if_match, policy)


draw_router = APIRouter(tags=["fan"])


@draw_router.get(
    "/tournaments/{tournament_id}/draw", response_model=DrawOut, operation_id="getPublishedDraw"
)
async def published_draw(tournament_id: UUID, request: Request, db: Db) -> Response:
    """The published draw: pots, groups, reasons and the seed (anyone can reproduce it)."""
    return cached(request, await service.published_draw(db, tournament_id))


matchday_router = APIRouter(prefix="/tournaments/{tournament_id}", tags=["organiser"])


@matchday_router.get("/console", response_model=ConsoleOut, operation_id="getConsole")
async def get_console(
    tournament_id: UUID, request: Request, viewer: Member, db: Db, clock: Now
) -> ConsoleOut:
    """All pitches now/next, delays, live viewers and unscored matches."""
    return await matchday.console(db, clock, viewer, tournament_id, request.app.state.live)


@matchday_router.post(
    "/schedule/changes", response_model=ChangePreview, operation_id="previewScheduleChange"
)
async def preview_schedule_change(
    tournament_id: UUID, body: ScheduleChangeIn, viewer: Member, db: Db, clock: Now
) -> ChangePreview:
    """Pitch late or closed, match postponed, team withdrawn: preview what moves."""
    return await matchday.preview_change(db, clock, viewer, tournament_id, body)


@matchday_router.post(
    "/schedule/{plan_id}/confirm",
    response_model=ChangeConfirmed,
    operation_id="confirmScheduleChange",
)
async def confirm_schedule_change(
    tournament_id: UUID, plan_id: UUID, request: Request, viewer: Member, db: Db, clock: Now
) -> ChangeConfirmed:
    """Publish the rescheduled plan; followers of affected teams are notified."""
    live = request.app.state.live
    return await matchday.confirm_change(db, clock, viewer, tournament_id, plan_id, live)


class AnnouncementIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@matchday_router.post("/announcements", status_code=204, operation_id="sendAnnouncement")
async def send_announcement(
    tournament_id: UUID, body: AnnouncementIn, request: Request, viewer: Member, db: Db, clock: Now
) -> Response:
    """Send a short announcement to the live page and venue screen."""
    await matchday.announce(db, clock, viewer, tournament_id, body.text, request.app.state.live)
    return Response(status_code=204)


@draw_router.get(
    "/tournaments/{tournament_id}/draw/reveal",
    response_model=DrawReveal,
    operation_id="getDrawReveal",
)
async def draw_reveal(tournament_id: UUID, db: Db) -> DrawReveal:
    """The live draw so far (venue screen or stream): teams revealed pot by pot."""
    return await service.draw_reveal(db, tournament_id)


@matchday_router.post("/draw/reveal/next", response_model=DrawReveal, operation_id="revealNext")
async def reveal_next(
    tournament_id: UUID, request: Request, viewer: Member, db: Db, clock: Now
) -> DrawReveal:
    """Reveal the next team of the live draw (sends a `draw_step` live message)."""
    return await service.reveal_next(db, clock, viewer, tournament_id, request.app.state.live)


@matchday_router.post("/draw/reveal/reset", response_model=DrawReveal, operation_id="resetReveal")
async def reset_reveal(tournament_id: UUID, viewer: Member, db: Db) -> DrawReveal:
    """Start the live draw again."""
    return await service.reset_reveal(db, viewer, tournament_id)
