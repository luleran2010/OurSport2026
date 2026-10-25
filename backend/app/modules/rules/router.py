"""Rules endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.viewer import CurrentViewer
from app.modules.rules import service
from app.modules.rules.schemas import Language, RulesSummary

router = APIRouter(tags=["rules"])
Db = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "/tournaments/{tournament_id}/rules/summary",
    response_model=RulesSummary,
    operation_id="getRulesSummary",
)
async def get_rules_summary(
    tournament_id: UUID, viewer: CurrentViewer, db: Db, lang: Annotated[Language, Query()] = "en"
) -> RulesSummary:
    """The tournament's confirmed rules in plain words."""
    return await service.rules_summary(db, viewer, tournament_id, lang)
