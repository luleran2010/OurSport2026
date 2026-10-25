from collections.abc import Callable

from alembic import command
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.support import UNREACHABLE_DATABASE_URL, UNREACHABLE_REDIS_URL, alembic_config


def test_health_live_returns_ok(make_settings: Callable[..., Settings]) -> None:
    client = TestClient(create_app(make_settings()))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_is_served_under_api_prefix(make_settings: Callable[..., Settings]) -> None:
    client = TestClient(create_app(make_settings()))

    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "OurSport API"


def test_ready_is_ok_when_all_checks_pass(make_settings: Callable[..., Settings]) -> None:
    async def ok() -> None:
        return None

    with TestClient(create_app(make_settings())) as client:
        client.app.state.readiness_checks = {"database": ok, "redis": ok}  # type: ignore[attr-defined]  # TestClient.app is typed as the ASGI callable
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def test_ready_fails_when_a_check_hangs(make_settings: Callable[..., Settings]) -> None:
    async def ok() -> None:
        return None

    async def hangs() -> None:
        import asyncio

        await asyncio.sleep(10)

    with TestClient(create_app(make_settings(health_check_timeout_s=0.1))) as client:
        client.app.state.readiness_checks = {"database": ok, "redis": hangs}  # type: ignore[attr-defined]  # TestClient.app is typed as the ASGI callable
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "error"}


def test_ready_fails_when_database_is_down(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(database_url=UNREACHABLE_DATABASE_URL)

    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"] == "error"


def test_ready_fails_when_redis_is_down(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(redis_url=UNREACHABLE_REDIS_URL)

    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "error"


def test_ready_is_ok_against_migrated_database(
    database_url: str, make_settings: Callable[..., Settings]
) -> None:
    with TestClient(create_app(make_settings(database_url=database_url))) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "migrations": "ok", "redis": "ok"}


def test_ready_fails_when_migrations_are_behind(
    database_url: str, make_settings: Callable[..., Settings]
) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "base")
    try:
        with TestClient(create_app(make_settings(database_url=database_url))) as client:
            response = client.get("/health/ready")
    finally:
        command.upgrade(config, "head")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "migrations": "error", "redis": "ok"}
