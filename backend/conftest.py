"""Shared test fixtures for engine, app and architecture tests (repository root, so the
module tests under `app/modules/*/tests` see them too)."""

import asyncio
import json
import os
import socket
import sys
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import asyncpg
import pytest

# `app.main` builds an app at import time; give it a complete local configuration so tests
# never depend on a developer's `.env`. Real environment variables still win (CI services).
_TEST_ENV = {
    "ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://oursport:oursport@localhost:5432/oursport",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": "test-secret-not-for-real-use-0123456789abcdef",
}
for _key, _value in _TEST_ENV.items():
    os.environ.setdefault(_key, _value)

# psycopg (the job queue's driver) cannot run on Windows' default Proactor event loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from alembic import command  # noqa: E402  (must follow the environment setup above)
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.time import FrozenClock  # noqa: E402
from tests.support import alembic_config  # noqa: E402

MAILPIT_API = os.environ.get("MAILPIT_API", "http://localhost:8025/api/v1")


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Build Settings from explicit test values (ignores `.env`), with overrides."""

    def build(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "env": "test",
            "database_url": os.environ["DATABASE_URL"],
            "redis_url": os.environ["REDIS_URL"],
            "jwt_secret": os.environ["JWT_SECRET"],
            "health_check_timeout_s": 1.0,
            "shared_cache_enabled": False,  # tests read their own writes at once
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return build


def _reachable(url: str, default_port: int) -> bool:
    parts = urlsplit(url.replace("+asyncpg", ""))
    try:
        with socket.create_connection(
            (parts.hostname or "localhost", parts.port or default_port), 0.5
        ):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def require_services() -> None:
    """Skip a test that needs the real Postgres and Redis when they are not running."""
    if not (
        _reachable(os.environ["DATABASE_URL"], 5432) and _reachable(os.environ["REDIS_URL"], 6379)
    ):
        pytest.skip("Postgres/Redis not reachable; run `docker compose up -d db redis`")


async def _recreate_database(admin_url: str, name: str) -> None:
    conn = await asyncpg.connect(admin_url.replace("+asyncpg", ""))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def database_url(require_services: None) -> Iterator[str]:
    """URL of a fresh `<db>_test` database migrated to head, shared by the test session."""
    admin_url = os.environ["DATABASE_URL"]
    parts = urlsplit(admin_url)
    name = f"{parts.path.lstrip('/')}_test"
    asyncio.run(_recreate_database(admin_url, name))
    url = urlunsplit(parts._replace(path=f"/{name}"))
    command.upgrade(alembic_config(url), "head")
    yield url


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime.now(UTC))


@pytest.fixture
def api(
    database_url: str, make_settings: Callable[..., Settings], clock: FrozenClock
) -> Iterator[TestClient]:
    """The app on the test database, Redis and Mailpit, with a frozen clock."""
    from app.main import create_app

    settings = make_settings(database_url=database_url, magic_link_per_ip_per_hour=100_000)
    with TestClient(create_app(settings, clock=clock)) as client:
        yield client


class Mailpit:
    """Reads what the app sent through Mailpit's HTTP API."""

    def _get(self, path: str) -> Any:
        with urllib.request.urlopen(f"{MAILPIT_API}{path}", timeout=5) as response:
            return json.load(response)

    def messages_to(self, address: str) -> list[str]:
        """Plain-text bodies sent to `address`, newest first."""
        query = urllib.parse.quote(f'to:"{address}"')
        found = self._get(f"/search?query={query}")["messages"]
        return [self._get(f"/message/{m['ID']}")["Text"] for m in found]

    def latest_token(self, address: str) -> str:
        """The token of the newest magic link sent to `address`."""
        text = self.messages_to(address)[0]
        return text.split("token=", 1)[1].split()[0]


@pytest.fixture
def mailpit(require_services: None) -> Mailpit:
    if not _reachable(MAILPIT_API, 8025):
        pytest.skip("Mailpit not reachable; run `docker compose up -d mailpit`")
    return Mailpit()


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[AsyncSession]:
    """A session on the test database; services open their own transactions."""
    engine = create_async_engine(database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def make_user(db: AsyncSession, clock: FrozenClock) -> Callable[[], Awaitable[UUID]]:
    """Insert a verified user with a generated email; returns the id."""
    from app.modules.accounts.models import User

    async def create() -> UUID:
        now = clock.now()
        user = User(
            id=uuid4(),
            email=f"user-{uuid4().hex[:12]}@example.com",
            display_name="Test User",
            language="en",
            time_zone="Europe/Helsinki",
            birth_year_confirmed_13_plus=True,
            privacy_accepted_at=now,
            email_verified_at=now,
            created_at=now,
            updated_at=now,
        )
        from app.core.db import transaction

        async with transaction(db):
            db.add(user)
        return user.id

    return create


@pytest.fixture
def signed_in(api: TestClient, mailpit: Mailpit) -> dict[str, str]:
    """Sign a new user up through the real magic-link flow; returns the session info."""
    email = f"member-{uuid4().hex[:12]}@example.com"
    api.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "display_name": "Test Member",
            "language": "en",
            "time_zone": "Europe/Helsinki",
            "age_13_plus": True,
            "privacy_accepted": True,
        },
    )
    response = api.post(
        "/api/v1/auth/magic-link/verify", json={"token": mailpit.latest_token(email)}
    )
    assert response.status_code == 200, response.text
    body: dict[str, str] = response.json()
    return body


@pytest.fixture
async def published_cup(
    db: AsyncSession,
    clock: FrozenClock,
    make_user: Callable[[], Awaitable[UUID]],
    make_settings: Callable[..., Settings],
) -> dict[str, Any]:
    """The FinBangla-style eval cup published through the setup pipeline (16 teams, 32
    matches, 12-14 June 2026, four pitches), with its pitch scorer passes."""
    import datetime as dt
    from pathlib import Path

    from redis.asyncio import Redis

    from app.core.llm import FakeProvider, LLMGateway
    from app.core.viewer import Viewer
    from app.modules.competitions import service as competitions
    from app.modules.competitions.schemas import OrganisationCreate
    from app.modules.scoring import service as scoring
    from app.modules.setup import service as setup
    from app.modules.setup.schemas import SetupStart

    settings = make_settings()
    scoring.register(settings, clock)
    folder = Path(__file__).parent / "tests" / "setup" / "eval_set" / "en_full_cup"
    case = json.loads((folder / "case.json").read_text())
    owner = await make_user()
    viewer = Viewer(user_id=owner)
    org = await competitions.create_organisation(
        db,
        clock,
        viewer,
        OrganisationCreate(
            kind="community", name="Cup Org", sports=["football"], accept_processing_terms=True
        ),
    )
    session = await setup.start(
        db,
        clock,
        viewer,
        SetupStart(
            organisation_id=org.id,
            name="Published Cup",
            starts_on=dt.date(2026, 6, 12),
            ends_on=dt.date(2026, 6, 14),
        ),
    )
    for f in case["files"]:
        path = folder / f["file"]
        mime = "text/csv" if path.suffix == ".csv" else "text/plain"
        await setup.add_file(
            db,
            clock,
            viewer,
            session.id,
            kind=f["kind"],
            filename=path.name,
            mime=mime,
            data=path.read_bytes(),
        )
    redis = Redis.from_url(os.environ["REDIS_URL"])
    try:
        await redis.flushdb()
        llm = LLMGateway(FakeProvider(responses=case["llm"]), settings, redis, clock)
        await setup.run_extraction(db, clock, llm, viewer, session.id)
    finally:
        await redis.aclose()
    published = await setup.publish(db, clock, viewer, session.id, None, "notice")
    return {"tournament_id": published.tournament_id, "owner": owner, "settings": settings}
