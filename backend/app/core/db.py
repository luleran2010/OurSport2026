"""Async SQLAlchemy engine, session factory and the declarative base for all modules.

Request sessions do not auto-commit: a service that writes wraps its work in
`async with transaction(session):`, so the commit happens before the response is built and
jobs deferred in that block share its transaction (docs/08-jobs.md).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings

# Names follow docs/03-data-model.md: ix_<table>_<cols>, uq_<table>_<cols>.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def one_of(column: str, values: tuple[str, ...]) -> str:
    """SQL for a CHECK constraint keeping a text column within `values` (docs/03, Enums)."""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the process-wide engine; connections are opened lazily."""
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={"timeout": settings.health_check_timeout_s},
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back if left uncommitted."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


async def check_database(engine: AsyncEngine) -> None:
    """Raise if the database cannot answer a trivial query."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


@asynccontextmanager
async def transaction(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Commit the work in the block (rolling back on error).

    Blocks nest: an inner block (a service called by another service) joins the outer one,
    and only the outermost commits, so a whole publish is one transaction. Reads before a
    write already started a transaction (SQLAlchemy autobegin); that one is committed too.
    """
    depth = session.info.get("transaction_depth", 0)
    session.info["transaction_depth"] = depth + 1
    try:
        if depth > 0:
            yield session
            return
        if not session.in_transaction():
            async with session.begin():
                yield session
            return
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        await session.commit()
    finally:
        session.info["transaction_depth"] = depth
