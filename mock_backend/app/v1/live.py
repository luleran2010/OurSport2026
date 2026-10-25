"""Live WebSockets in the backend's protocol (backend/docs/06-live.md).

Envelope: `{type, match_id, seq, server_time, data}`. A match socket starts with a `snapshot`
(`{score, timeline}` after `since_seq`), then sends `event` / `correction` deltas and
`match_finished` (then closes). The tournament socket sends every score change of its
matches. A bad or expired token closes with 4401. `ping` keeps quiet sockets open.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..main_store import store
from ..models import Match
from . import auth as A
from . import project as P
from .ids import slug, uid

router = APIRouter(prefix="/api/v1/live")
POLL_SECONDS = 1.0
PING_SECONDS = 15.0


def _envelope(type_: str, match_id: str | None, seq: int | None, data: dict) -> dict:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {"type": type_, "match_id": match_id, "seq": seq, "server_time": now, "data": data}


def _scope_ok(token: str | None, scope: str) -> bool:
    found = A.state(store).live_tokens.get(token or "")
    return bool(found and found[0] == scope and found[1] > A._now())


def _score(m: Match) -> dict:
    s = P.score_of(m)
    return s.model_dump() if s else {"home_goals": 0, "away_goals": 0, "period": None, "finished": False}


@router.websocket("/matches/{match_id}")
async def match_socket(ws: WebSocket, match_id: str, token: str | None = None, since_seq: int = 0) -> None:
    m = store.get_match(slug("match", match_id))
    await ws.accept()
    if m is None or not _scope_ok(token, f"match:{m.id}"):
        await ws.close(code=4401)
        return
    mid = uid("match", m.id)
    events = P.timeline(store, m)
    last = since_seq
    await ws.send_json(_envelope("snapshot", mid, len(events), {
        "score": _score(m), "timeline": [e for e in events if e["seq"] > since_seq]}))
    last = max(last, len(events))
    quiet = 0.0
    try:
        while True:
            await asyncio.sleep(POLL_SECONDS)
            m = store.get_match(m.id) or m
            events = P.timeline(store, m)
            for e in events[last:]:
                kind = "correction" if e["type"] == "undo" else "event"
                data = {"event": e["type"], "team_id": e["team_id"], "score": _score(m), "moments": []}
                if kind == "correction":
                    data["undone_seq"] = None
                await ws.send_json(_envelope(kind, mid, e["seq"], data))
                last, quiet = e["seq"], 0.0
            if m.status == "finished":
                result = {"home_goals": m.score[0], "away_goals": m.score[1]} if m.score else None
                await ws.send_json(_envelope("match_finished", mid, last + 1, {"result": result}))
                await ws.close()
                return
            quiet += POLL_SECONDS
            if quiet >= PING_SECONDS:
                await ws.send_json(_envelope("ping", mid, None, {}))
                quiet = 0.0
    except WebSocketDisconnect:
        return


@router.websocket("/tournaments/{tournament_id}")
async def tournament_socket(ws: WebSocket, tournament_id: str, token: str | None = None) -> None:
    key = slug("tournament", tournament_id)
    await ws.accept()
    if not _scope_ok(token, f"tournament:{key}"):
        await ws.close(code=4401)
        return
    await ws.send_json(_envelope("snapshot", None, 0, {"tournament_id": uid("tournament", key)}))

    def scores() -> dict[str, tuple]:
        return {m.id: (m.status, tuple(m.score or ())) for m in store.matches if P.tournament_key(m) == key}

    seen, seq, quiet = scores(), 0, 0.0
    try:
        while True:
            await asyncio.sleep(POLL_SECONDS)
            now = scores()
            for mid, value in now.items():
                if seen.get(mid) == value:
                    continue
                m = store.get_match(mid)
                seq += 1
                if m.status == "finished":
                    result = {"home_goals": m.score[0], "away_goals": m.score[1]} if m.score else None
                    await ws.send_json(_envelope("match_finished", uid("match", mid), seq, {"result": result}))
                else:
                    await ws.send_json(_envelope("event", uid("match", mid), seq, {"score": _score(m)}))
                quiet = 0.0
            seen = now
            quiet += POLL_SECONDS
            if quiet >= PING_SECONDS:
                await ws.send_json(_envelope("ping", None, None, {}))
                quiet = 0.0
    except WebSocketDisconnect:
        return
