"""Competitions' personal data about a user: staff roles, agreements, guardian consents.

Processing agreements and consents are kept as records (who accepted, what was agreed);
erasure removes the link to the account, not the record.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import privacy
from app.modules.competitions.models import Consent, ProcessingAgreement, TournamentStaff


async def export(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    staff = await db.scalars(select(TournamentStaff).where(TournamentStaff.user_id == user_id))
    agreements = await db.scalars(
        select(ProcessingAgreement).where(ProcessingAgreement.accepted_by == user_id)
    )
    consents = await db.scalars(select(Consent).where(Consent.guardian_user_id == user_id))
    return {
        "tournament_staff": [
            {"tournament_id": str(s.tournament_id), "role": s.role} for s in staff
        ],
        "processing_agreements": [
            {
                "organisation_id": str(a.organisation_id),
                "version": a.version,
                "accepted_at": a.accepted_at.isoformat(),
            }
            for a in agreements
        ],
        "consents_given": [{"player_id": str(c.player_id), "scope": c.scope} for c in consents],
    }


async def erase(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(delete(TournamentStaff).where(TournamentStaff.user_id == user_id))
    await db.execute(
        update(Consent).where(Consent.guardian_user_id == user_id).values(guardian_user_id=None)
    )


def register() -> None:
    privacy.register("competitions", exporter=export, eraser=erase)
