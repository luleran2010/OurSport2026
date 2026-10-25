"""Media endpoints (docs/05-api.md, Media)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.time import Clock, get_clock
from app.core.viewer import CurrentViewer, Member
from app.modules.media import printables, service
from app.modules.media.schemas import (
    AttestationIn,
    AttestationOut,
    FilmingNoticeOut,
    OptOutIn,
    OptOutOut,
    ResolveIn,
    StreamIn,
    StreamOut,
)

router = APIRouter(tags=["media"])
Db = Annotated[AsyncSession, Depends(get_session)]
Now = Annotated[Clock, Depends(get_clock)]


@router.post(
    "/matches/{match_id}/stream",
    status_code=201,
    response_model=StreamOut,
    operation_id="attachStream",
)
async def attach(
    match_id: UUID, body: StreamIn, request: Request, viewer: Member, db: Db, clock: Now
) -> StreamOut:
    """Attach a playback link; 409 `filming_not_permitted` lists every failing check."""
    return await service.attach_stream(db, clock, viewer, match_id, body, request.app.state.live)


@router.delete("/matches/{match_id}/stream", status_code=204, operation_id="endStream")
async def end(match_id: UUID, request: Request, viewer: Member, db: Db, clock: Now) -> Response:
    """End the match's stream."""
    await service.end_stream(db, clock, viewer, match_id, request.app.state.live)
    return Response(status_code=204)


@router.get("/matches/{match_id}/stream", response_model=StreamOut, operation_id="getStream")
async def stream(match_id: UUID, viewer: CurrentViewer, db: Db) -> StreamOut:
    """The live stream of a match (live access policy); 404 when there is none."""
    return await service.match_stream(db, viewer, match_id)


@router.post(
    "/tournaments/{tournament_id}/filming-notice",
    status_code=201,
    response_model=FilmingNoticeOut,
    operation_id="publishFilmingNotice",
)
async def publish_notice(
    tournament_id: UUID, viewer: Member, db: Db, clock: Now
) -> FilmingNoticeOut:
    """Publish the venue filming notice in the tournament languages (needed to stream)."""
    return await service.publish_notice(db, clock, viewer, tournament_id)


@router.get(
    "/tournaments/{tournament_id}/filming-notice",
    response_model=FilmingNoticeOut,
    operation_id="getFilmingNotice",
)
async def get_notice(tournament_id: UUID, viewer: CurrentViewer, db: Db) -> FilmingNoticeOut:
    """The filming notice (venue QR code)."""
    return await service.notice(db, viewer, tournament_id)


@router.post(
    "/tournaments/{tournament_id}/filming-attestation",
    status_code=201,
    response_model=AttestationOut,
    operation_id="attestFilmingConsents",
)
async def attest(
    tournament_id: UUID, body: AttestationIn, viewer: Member, db: Db, clock: Now
) -> AttestationOut:
    """Attest that filming consents were collected offline (signed forms)."""
    return await service.attest(db, clock, viewer, tournament_id, body)


@router.post(
    "/tournaments/{tournament_id}/filming-optouts",
    status_code=201,
    response_model=OptOutOut,
    operation_id="optOutOfFilming",
)
async def opt_out(
    tournament_id: UUID, body: OptOutIn, request: Request, viewer: Member, db: Db, clock: Now
) -> OptOutOut:
    """Ask not to be filmed (organiser, guardian or player 15+): live streams of the
    team's matches pause, and new ones wait until the organiser resolves it."""
    return await service.opt_out(db, clock, viewer, tournament_id, body, request.app.state.live)


@router.get(
    "/tournaments/{tournament_id}/filming-optouts",
    response_model=list[OptOutOut],
    operation_id="listFilmingOptOuts",
)
async def list_optouts(tournament_id: UUID, viewer: Member, db: Db) -> list[OptOutOut]:
    """Opt-outs of the tournament (organisers)."""
    return await service.optouts(db, viewer, tournament_id)


@router.post(
    "/tournaments/{tournament_id}/filming-optouts/{optout_id}/resolve",
    response_model=OptOutOut,
    operation_id="resolveFilmingOptOut",
)
async def resolve(
    tournament_id: UUID, optout_id: UUID, body: ResolveIn, viewer: Member, db: Db, clock: Now
) -> OptOutOut:
    """Resolve an opt-out (streams may be attached again)."""
    return await service.resolve_optout(
        db, clock, viewer, tournament_id, optout_id, body.resolution
    )


@router.get(
    "/tournaments/{tournament_id}/printables/pitch-sheets",
    response_class=HTMLResponse,
    operation_id="printPitchSheets",
)
async def pitch_sheets(tournament_id: UUID, request: Request, viewer: Member, db: Db) -> str:
    """Printable sheets, one per pitch: scorer QR code, how to score, the day's matches."""
    return await printables.pitch_sheets(db, request.app.state.settings, viewer, tournament_id)


@router.get(
    "/tournaments/{tournament_id}/printables/filming-notice",
    response_class=HTMLResponse,
    operation_id="printFilmingNotice",
)
async def notice_sheet(tournament_id: UUID, request: Request, viewer: Member, db: Db) -> str:
    """The printable venue filming notice with a QR code to the privacy notice."""
    return await printables.filming_notice_sheet(
        db, request.app.state.settings, viewer, tournament_id
    )
