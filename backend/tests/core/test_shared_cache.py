"""The shared cache serves repeated anonymous reads from Redis; never signed-in ones."""

import os
from collections.abc import Callable

import redis as sync_redis
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.time import FrozenClock
from app.main import create_app


def test_anonymous_public_reads_are_shared_and_private_ones_are_not(
    database_url: str, make_settings: Callable[..., Settings], clock: FrozenClock
) -> None:
    store = sync_redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    store.flushdb()
    settings = make_settings(database_url=database_url, shared_cache_enabled=True)
    with TestClient(create_app(settings, clock=clock)) as client:
        first = client.get("/api/v1/legal/privacy?lang=fi")
        stored = store.ttl("resp:/api/v1/legal/privacy?lang=fi")
        again = client.get("/api/v1/legal/privacy?lang=fi")
        unchanged = client.get(
            "/api/v1/legal/privacy?lang=fi", headers={"If-None-Match": first.headers["ETag"]}
        )
        client.cookies.set("oursport_access", "x")
        signed_in = client.get("/api/v1/legal/privacy?lang=en")
        private = store.exists("resp:/api/v1/legal/privacy?lang=en")
        client.cookies.clear()
        health = client.get("/health/live")  # not public-cacheable

    assert first.status_code == again.status_code == 200
    assert again.text == first.text and again.headers["ETag"] == first.headers["ETag"]
    assert 0 < stored <= 30
    assert unchanged.status_code == 304
    assert signed_in.status_code == 200 and private == 0
    assert health.status_code == 200 and not store.exists("resp:/health/live?")
    store.close()
