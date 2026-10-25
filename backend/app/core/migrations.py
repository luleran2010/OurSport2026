"""Readiness support: is the database schema at the migration head this code expects?"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# alembic.ini sits at the project root (/srv in the container), two levels above app/core.
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


class MigrationsNotCurrent(Exception):
    pass


def expected_heads(alembic_ini: Path = ALEMBIC_INI) -> frozenset[str]:
    """Head revisions shipped with this code."""
    script = ScriptDirectory.from_config(Config(str(alembic_ini)))
    return frozenset(script.get_heads())


async def check_migrations(engine: AsyncEngine, heads: frozenset[str]) -> None:
    """Raise unless the database is stamped with exactly the expected head revisions."""
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT version_num FROM alembic_version"))
        current = frozenset(row[0] for row in rows)
    if current != heads:
        raise MigrationsNotCurrent(f"database at {sorted(current)}, code expects {sorted(heads)}")
