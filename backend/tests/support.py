"""Shared test constants and helpers (importable, unlike conftest)."""

from alembic.config import Config

from app.core.migrations import ALEMBIC_INI

# Nothing listens on port 1, so connections are refused immediately.
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://oursport:oursport@127.0.0.1:1/oursport"
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"


def alembic_config(database_url: str) -> Config:
    """Alembic config pointed at `database_url`, leaving pytest's logging alone."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logger"] = False
    return config
