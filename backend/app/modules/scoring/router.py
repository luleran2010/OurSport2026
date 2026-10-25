"""Scoring endpoints (docs/05-api.md, Scoring). Scorers authenticate with
`Authorization: Pass <token>`; staff with their session (CSRF-checked)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.time import Clock, get_clock
from app.core.viewer import CurrentViewer, verify_csrf
from app.modules.scoring import service
from app.modules.scoring.schemas import (
    EventAccepted,
    EventIn,
    EventPad,
    FinishIn,
    MatchStatus,
    PassCreate,
    PassOut,
    ResultIn,
    ScorerMatch,
    ScoringState,
)

router = APIRouter(tags=["scoring"], dependencies=[Depends(verify_csrf)])
Db = Annotated[AsyncSession, Depends(get_session)]
Now = Annotated[Clock, Depends(get_clock)]


class UndoIn(BaseModel):
    client_seq: int = Field(ge=1)


@router.get("/scoring/me", response_model=list[ScorerMatch], operation_id="getScorerMatches")
async def scorer_matches(viewer: CurrentViewer, db: Db, clock: Now) -> list[ScorerMatch]:
    """My matches to score, in kick-off order: today's for a scorer pass; every open one of
    the tournaments an organiser runs."""
    return await service.my_matches(db, clock, viewer)


@router.get("/sports/{code}/event-types", response_model=EventPad, operation_id="getEventTypes")
async def event_types(code: str) -> EventPad:
    """The event pad definition for a sport: buttons, labels, and what each one posts."""
    return service.event_pad(code)


@router.get(
    "/matches/{match_id}/scoring", response_model=ScoringState, operation_id="getScoringState"
)
async def scoring_state(match_id: UUID, viewer: CurrentViewer, db: Db, clock: Now) -> ScoringState:
    """The scoring console's view of a match (scorer pass for its pitch, or organisers):
    score, period, rosters and every event with its `seq` (for undo) and `client_seq`."""
    return await service.scoring_state(db, clock, viewer, match_id)


@router.post("/matches/{match_id}/start", response_model=MatchStatus, operation_id="startMatch")
async def start_match(match_id: UUID, viewer: CurrentViewer, db: Db, clock: Now) -> MatchStatus:
    """Kick-off: the match goes live."""
    return await service.start(db, clock, viewer, match_id)


@router.post(
    "/matches/{match_id}/events",
    status_code=201,
    response_model=EventAccepted,
    operation_id="postMatchEvent",
)
async def post_event(
    match_id: UUID,
    body: EventIn,
    request: Request,
    response: Response,
    viewer: CurrentViewer,
    db: Db,
    clock: Now,
) -> EventAccepted:
    """Append an event; a retry with the same client_seq returns 200 and the original seq."""
    accepted = await service.post_event(db, clock, viewer, match_id, body, request.app.state.live)
    if accepted.duplicate:
        response.status_code = 200
    return accepted


@router.post(
    "/matches/{match_id}/events/{seq}/undo",
    status_code=201,
    response_model=EventAccepted,
    operation_id="undoMatchEvent",
)
async def undo_event(
    match_id: UUID,
    seq: int,
    body: UndoIn,
    request: Request,
    viewer: CurrentViewer,
    db: Db,
    clock: Now,
) -> EventAccepted:
    """Undo an event (appends an undo event)."""
    live = request.app.state.live
    return await service.undo(db, clock, viewer, match_id, seq, body.client_seq, live)


@router.post("/matches/{match_id}/finish", response_model=MatchStatus, operation_id="finishMatch")
async def finish_match(
    match_id: UUID, body: FinishIn, request: Request, viewer: CurrentViewer, db: Db, clock: Now
) -> MatchStatus:
    """Confirm the final score."""
    live = request.app.state.live
    return await service.finish(db, clock, viewer, match_id, body.home_goals, body.away_goals, live)


@router.post("/matches/{match_id}/result", response_model=MatchStatus, operation_id="enterResult")
async def enter_result(
    match_id: UUID, body: ResultIn, viewer: CurrentViewer, db: Db, clock: Now
) -> MatchStatus:
    """Results-only entry."""
    return await service.enter_result(db, clock, viewer, match_id, body)


@router.get(
    "/tournaments/{tournament_id}/scorer-passes",
    response_model=list[PassOut],
    operation_id="listScorerPasses",
)
async def list_passes(
    tournament_id: UUID, request: Request, viewer: CurrentViewer, db: Db
) -> list[PassOut]:
    """Scorer passes with their QR tokens (organisers)."""
    return await service.list_passes(db, request.app.state.settings, viewer, tournament_id)


@router.post(
    "/tournaments/{tournament_id}/scorer-passes",
    status_code=201,
    response_model=PassOut,
    operation_id="createScorerPass",
)
async def create_pass(
    tournament_id: UUID,
    body: PassCreate,
    request: Request,
    viewer: CurrentViewer,
    db: Db,
    clock: Now,
) -> PassOut:
    """A pass for a pitch or one match."""
    settings = request.app.state.settings
    return await service.create_pass(db, clock, settings, viewer, tournament_id, body)


@router.post(
    "/tournaments/{tournament_id}/scorer-passes/{pass_id}/revoke",
    status_code=204,
    operation_id="revokeScorerPass",
)
async def revoke_pass(
    tournament_id: UUID, pass_id: UUID, viewer: CurrentViewer, db: Db, clock: Now
) -> Response:
    """Revoke a pass at once (lost phone)."""
    await service.revoke_pass(db, clock, viewer, tournament_id, pass_id)
    return Response(status_code=204)
