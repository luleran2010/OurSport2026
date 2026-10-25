"""ETag and Cache-Control for fan reads (docs/05-api.md, Caching).

The ETag is a hash of the serialised read model, so it changes exactly when the version
a fan sees changes; `If-None-Match` with the same tag gets `304 Not Modified`.
`SharedCacheMiddleware` serves repeated anonymous reads from Redis (T-064).
"""

import asyncio
import contextlib
import hashlib
import json
import re
from typing import Any

from fastapi import Request, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PUBLIC_MAX_AGE = 30
LIVE_MAX_AGE = 5


def cached(
    request: Request, payload: BaseModel, *, max_age: int = PUBLIC_MAX_AGE, private: bool = False
) -> Response:
    body = payload.model_dump_json().encode()
    etag = f'W/"{hashlib.sha256(body).hexdigest()[:32]}"'
    control = "private, no-store" if private else f"public, max-age={max_age}"
    headers = {"ETag": etag, "Cache-Control": control}
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


SHARED_CACHE_CAP_S = 30
_PRIVATE_HEADERS = (b"cookie", b"authorization")
_inflight: dict[str, asyncio.Event] = {}  # one computation per page per process


class SharedCacheMiddleware:
    """A shared cache for anonymous fan reads, like a CDN in front of the API.

    Only anonymous GETs (no cookie, no Authorization) of responses marked
    `Cache-Control: public, max-age=N` are stored, for N seconds (at most 30), keyed by
    path and query. A hit is answered from Redis with the same ETag, so `If-None-Match`
    still gets 304. Signed-in and scorer requests always reach the application.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "GET":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        settings = scope["app"].state.settings
        if not settings.shared_cache_enabled or any(h in headers for h in _PRIVATE_HEADERS):
            await self.app(scope, receive, send)
            return
        redis: Redis = scope["app"].state.redis
        key = f"resp:{scope['path']}?{scope['query_string'].decode()}"
        try:
            hit = await redis.get(key)
        except RedisError:
            hit = None  # without Redis every read goes to the application
        if hit is None and key in _inflight:  # another request is computing this page
            await _inflight[key].wait()
            with contextlib.suppress(RedisError):
                hit = await redis.get(key)
        if hit is not None:
            await _replay(json.loads(hit), headers.get(b"if-none-match"), send)
            return
        done = _inflight.setdefault(key, asyncio.Event())
        try:
            await self._fill(scope, receive, send, redis, key)
        finally:
            done.set()
            _inflight.pop(key, None)

    async def _fill(
        self, scope: Scope, receive: Receive, send: Send, redis: Redis, key: str
    ) -> None:
        captured: dict[str, Any] = {"body": b""}

        async def capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                captured["headers"] = message.get("headers", [])
            elif message["type"] == "http.response.body":
                captured["body"] += message.get("body", b"")
            await send(message)

        await self.app(scope, receive, capture)
        ttl = _shareable_for(captured)
        if ttl:
            stored = {
                "status": captured["status"],
                "headers": [[k.decode(), v.decode()] for k, v in captured["headers"]],
                "body": captured["body"].decode(),
            }
            with contextlib.suppress(RedisError):
                await redis.set(key, json.dumps(stored), ex=ttl)


def _shareable_for(captured: dict[str, Any]) -> int:
    """Seconds a captured response may be shared (0: not at all)."""
    if captured.get("status") != 200:
        return 0
    headers = {k.lower(): v for k, v in captured.get("headers", [])}
    if b"set-cookie" in headers:
        return 0
    control = headers.get(b"cache-control", b"").decode()
    match = re.search(r"\bpublic\b.*max-age=(\d+)", control)
    if match is None:
        return 0
    try:
        captured["body"].decode()
    except UnicodeDecodeError:
        return 0
    return min(int(match.group(1)), SHARED_CACHE_CAP_S)


async def _replay(stored: dict[str, Any], if_none_match: bytes | None, send: Send) -> None:
    headers = [(k.encode(), v.encode()) for k, v in stored["headers"]]
    etag = next((v for k, v in stored["headers"] if k.lower() == "etag"), None)
    if etag is not None and if_none_match is not None and if_none_match.decode() == etag:
        keep = [(k, v) for k, v in headers if k.lower() in (b"etag", b"cache-control")]
        await send({"type": "http.response.start", "status": 304, "headers": keep})
        await send({"type": "http.response.body", "body": b""})
        return
    await send({"type": "http.response.start", "status": stored["status"], "headers": headers})
    await send({"type": "http.response.body", "body": stored["body"].encode()})
