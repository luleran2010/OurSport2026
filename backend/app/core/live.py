"""Live fan-out over Redis pub/sub (docs/06-live.md, WebSocket protocol).

Every API instance runs one `LiveHub`: it subscribes to the channels its connected viewers
need and hands each message to their queues, so a message published by any instance
reaches viewers on all of them. Redis is the fast path only; clients resync gaps from the
timeline (`since_seq`).
"""

import asyncio
import contextlib
import json
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.core.time import isoformat_z

log = structlog.get_logger("live")


def match_channel(match_id: UUID | str) -> str:
    return f"live:match:{match_id}"


def tournament_channel(tournament_id: UUID | str) -> str:
    return f"live:tournament:{tournament_id}"


def viewers_key(match_id: UUID | str) -> str:
    return f"live:viewers:{match_id}"


def envelope(
    type_: str, now: datetime, data: dict[str, Any], *, match_id: UUID | None = None,
    seq: int | None = None,
) -> dict[str, Any]:  # fmt: skip
    return {
        "type": type_,
        "match_id": str(match_id) if match_id else None,
        "seq": seq,
        "server_time": isoformat_z(now),
        "data": data,
    }


class LiveMessage(dict[str, Any]):
    """A message as received from Redis, keeping its JSON text: a match with 1,000 viewers
    serialises it once per process, not once per socket."""

    raw: str = ""


def as_text(message: dict[str, Any]) -> str:
    return message.raw if isinstance(message, LiveMessage) and message.raw else json.dumps(message)


class LiveHub:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._pubsub: PubSub | None = None
        self._queues: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._reader: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        await self._redis.publish(channel, json.dumps(message))

    async def subscribe(self, channel: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            if self._pubsub is None:
                self._pubsub = self._redis.pubsub()
            if not self._queues[channel]:
                await self._pubsub.subscribe(channel)
            self._queues[channel].add(queue)
            if self._reader is None or self._reader.done():
                self._reader = asyncio.create_task(self._read())
        return queue

    async def unsubscribe(self, channel: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._queues[channel].discard(queue)
            if not self._queues[channel] and self._pubsub is not None:
                await self._pubsub.unsubscribe(channel)

    async def _read(self) -> None:
        assert self._pubsub is not None
        while True:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # a dropped connection: viewers resync from the timeline
                log.warning("live_reader_error", exc_info=True)
                await asyncio.sleep(0.5)
                continue
            if message is None:
                continue
            channel = message["channel"]
            channel = channel.decode() if isinstance(channel, bytes) else channel
            raw = message["data"]
            data = LiveMessage(json.loads(raw))
            data.raw = raw.decode() if isinstance(raw, bytes) else raw
            for queue in list(self._queues.get(channel, ())):
                queue.put_nowait(data)

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
        if self._pubsub is not None:
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py leaves it unannotated

    async def add_viewer(self, match_id: UUID, delta: int) -> int:
        return int(await self._redis.incrby(viewers_key(match_id), delta))

    async def viewers(self, match_id: UUID) -> int:
        return max(int(await self._redis.get(viewers_key(match_id)) or 0), 0)
