"""Live sockets for fans (docs/06-live.md, WebSocket protocol).

1. `GET /live/token?match_id=` (or `tournament_id=`) checks the live access policy and
   returns a 60-second token; public tournaments give tokens to signed-out viewers too.
2. `/live/matches/{id}?token=&since_seq=` sends a `snapshot` (score and every event after
   `since_seq`), then each new message once, in `seq` order; `ping` when quiet.
   `/live/tournaments/{id}?token=` carries score-level messages of all its matches.
"""

import asyncio
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import Forbidden, NotAuthenticated, ValidationFailed
from app.core.live import LiveHub, as_text, envelope, match_channel, tournament_channel
from app.core.security import LIVE_TOKEN_TTL, decode_live_token, encode_live_token
from app.core.time import Clock
from app.core.viewer import CurrentViewer
from app.modules.analysis import reads
from app.modules.competitions import service as competitions
from app.modules.scoring import service as scoring

router = APIRouter(tags=["live"])
Db = Annotated[AsyncSession, Depends(get_session)]
UNAUTHORISED = 4401  # application close code (4000-4999)


class LiveToken(BaseModel):
    token: str
    expires_at: datetime
    scope: str


@router.get("/live/token", response_model=LiveToken, operation_id="getLiveToken")
async def live_token(
    request: Request,
    viewer: CurrentViewer,
    db: Db,
    match_id: Annotated[UUID | None, Query()] = None,
    tournament_id: Annotated[UUID | None, Query()] = None,
) -> LiveToken:
    """A 60-second token for one live socket, if the live access policy allows it."""
    if (match_id is None) == (tournament_id is None):
        raise ValidationFailed("ask for one match_id or one tournament_id")
    if match_id is not None:
        tournament_id = (await competitions.get_match(db, match_id)).tournament_id
        scope = f"match:{match_id}"
    else:
        scope = f"tournament:{tournament_id}"
    assert tournament_id is not None
    tournament = await competitions.get_tournament(db, viewer, tournament_id)
    if not await reads.can_watch_live(db, viewer, tournament):
        raise Forbidden("live coverage is for members") if viewer.is_member else NotAuthenticated()
    settings: Settings = request.app.state.settings
    clock: Clock = request.app.state.clock
    expires = clock.now() + LIVE_TOKEN_TTL
    subject = str(viewer.user_id) if viewer.user_id else "anonymous"
    token = encode_live_token(scope, subject, expires, settings.jwt_secret.get_secret_value())
    return LiveToken(token=token, expires_at=expires, scope=scope)


def _scope(websocket: WebSocket, token: str) -> str | None:
    settings: Settings = websocket.app.state.settings
    clock: Clock = websocket.app.state.clock
    return decode_live_token(token, settings.jwt_secret.get_secret_value(), clock.now())


async def _snapshot(websocket: WebSocket, match_id: UUID, since_seq: int) -> dict[str, Any]:
    sessions: async_sessionmaker[AsyncSession] = websocket.app.state.sessionmaker
    clock: Clock = websocket.app.state.clock
    async with sessions() as db:
        live = await scoring.live_snapshot(db, match_id)
        events = await scoring.timeline(db, match_id, since_seq)
    seq = live[0] if live else 0
    data = {"score": live[1].model_dump() if live else None, "timeline": events}
    return envelope("snapshot", clock.now(), data, match_id=match_id, seq=seq)


async def _pump(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, Any]],
    last_seq: dict[str, int],
    *,
    stop_on_finish: bool,
) -> None:
    """Forward hub messages in order, each once; ping when quiet."""
    settings: Settings = websocket.app.state.settings
    clock: Clock = websocket.app.state.clock
    while True:
        try:
            message = await asyncio.wait_for(queue.get(), timeout=settings.live_ping_seconds)
        except TimeoutError:
            await websocket.send_json(envelope("ping", clock.now(), {}))
            continue
        match, seq = message.get("match_id"), message.get("seq")
        if match and isinstance(seq, int):
            if seq <= last_seq.get(match, 0):
                continue  # already in the snapshot or sent
            last_seq[match] = seq
        await websocket.send_text(as_text(message))
        if stop_on_finish and message["type"] == "match_finished":
            return


@router.websocket("/live/matches/{match_id}")
async def match_socket(
    websocket: WebSocket, match_id: UUID, token: str = "", since_seq: int = 0
) -> None:
    """One match: snapshot, then events, corrections, state and the final whistle."""
    if _scope(websocket, token) != f"match:{match_id}":
        await websocket.close(code=UNAUTHORISED)
        return
    hub: LiveHub = websocket.app.state.live
    await websocket.accept()
    channel = match_channel(match_id)
    queue = await hub.subscribe(channel)  # before the snapshot, so nothing falls between
    await hub.add_viewer(match_id, 1)
    try:
        snapshot = await _snapshot(websocket, match_id, since_seq)
        await websocket.send_json(snapshot)
        last = {str(match_id): max(snapshot["seq"] or 0, since_seq)}
        await _pump(websocket, queue, last, stop_on_finish=True)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe(channel, queue)
        await hub.add_viewer(match_id, -1)


@router.websocket("/live/tournaments/{tournament_id}")
async def tournament_socket(websocket: WebSocket, tournament_id: UUID, token: str = "") -> None:
    """All live matches of a tournament (score-level), schedule changes, announcements."""
    if _scope(websocket, token) != f"tournament:{tournament_id}":
        await websocket.close(code=UNAUTHORISED)
        return
    hub: LiveHub = websocket.app.state.live
    clock: Clock = websocket.app.state.clock
    await websocket.accept()
    channel = tournament_channel(tournament_id)
    queue = await hub.subscribe(channel)
    try:
        await websocket.send_json(
            envelope("snapshot", clock.now(), {"tournament_id": str(tournament_id)})
        )
        await _pump(websocket, queue, {}, stop_on_finish=False)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe(channel, queue)
