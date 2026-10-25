"""Media's personal data about a user: opt-outs they asked for; their name on streams,
notices and attestations is removed on erasure (the records stay)."""

from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import privacy
from app.modules.media.models import FilmingAttestation, FilmingNotice, FilmingOptOut, Stream


async def export(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    rows = await db.scalars(select(FilmingOptOut).where(FilmingOptOut.requested_by == user_id))
    return {
        "filming_optouts": [
            {
                "tournament_id": str(r.tournament_id),
                "team_id": str(r.team_id),
                "reason": r.reason,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


async def erase(db: AsyncSession, user_id: UUID) -> None:
    links = (
        (FilmingOptOut, FilmingOptOut.requested_by),
        (Stream, Stream.rights_confirmed_by),
        (FilmingNotice, FilmingNotice.published_by),
        (FilmingAttestation, FilmingAttestation.attested_by),
    )
    for model, column in links:
        await db.execute(update(model).where(column == user_id).values({column.key: None}))


def register() -> None:
    privacy.register("media", exporter=export, eraser=erase)
