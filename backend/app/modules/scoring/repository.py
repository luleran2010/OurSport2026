"""Scoring persistence. Events are only ever inserted."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scoring.models import LiveState, MatchEvent, ScorerPass


async def events_of(db: AsyncSession, match_id: UUID) -> list[MatchEvent]:
    result = await db.execute(
        select(MatchEvent).where(MatchEvent.match_id == match_id).order_by(MatchEvent.seq)
    )
    return list(result.scalars())


async def event_by_client_seq(
    db: AsyncSession, match_id: UUID, client_seq: int
) -> MatchEvent | None:
    result = await db.execute(
        select(MatchEvent).where(
            MatchEvent.match_id == match_id, MatchEvent.client_seq == client_seq
        )
    )
    return result.scalar_one_or_none()


async def max_client_seq(db: AsyncSession, match_id: UUID) -> int:
    result = await db.execute(
        select(func.max(MatchEvent.client_seq)).where(MatchEvent.match_id == match_id)
    )
    return int(result.scalar_one() or 0)


async def pass_by_hash(db: AsyncSession, token_hash: str) -> ScorerPass | None:
    result = await db.execute(select(ScorerPass).where(ScorerPass.token_hash == token_hash))
    return result.scalar_one_or_none()


async def passes_of(db: AsyncSession, tournament_id: UUID) -> list[ScorerPass]:
    result = await db.execute(
        select(ScorerPass)
        .where(ScorerPass.tournament_id == tournament_id)
        .order_by(ScorerPass.created_at, ScorerPass.label)
    )
    return list(result.scalars())


async def live_state(db: AsyncSession, match_id: UUID) -> LiveState | None:
    return await db.get(LiveState, match_id)


async def pass_tournaments(session: AsyncSession) -> list[UUID]:
    result = await session.scalars(
        select(ScorerPass.tournament_id).where(ScorerPass.label != "Expired pass").distinct()
    )
    return list(result)


async def delete_passes(
    session: AsyncSession, tournament_id: UUID, scrubbed_hash: Callable[[], str], now: datetime
) -> int:
    """Delete a tournament's passes. Passes that recorded events cannot go (events are
    append-only and keep `entered_by_pass_id`), so they are revoked and made unusable instead:
    a random token hash nobody holds, and an anonymous label."""
    used = select(MatchEvent.entered_by_pass_id).where(MatchEvent.entered_by_pass_id.is_not(None))
    result = await session.execute(
        delete(ScorerPass).where(
            ScorerPass.tournament_id == tournament_id, ScorerPass.id.not_in(used)
        )
    )
    kept = await session.scalars(
        select(ScorerPass).where(ScorerPass.tournament_id == tournament_id, ScorerPass.id.in_(used))
    )
    for row in kept:
        row.token_hash, row.label = scrubbed_hash(), "Expired pass"
        row.revoked_at = row.revoked_at or now
    return result.rowcount or 0  # type: ignore[attr-defined]  # CursorResult has rowcount
