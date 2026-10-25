"""GDPR rights across modules (docs/09-security-privacy.md, GDPR).

Every module that keeps personal data about a user registers an exporter (what it holds)
and an eraser (remove or anonymise it). `export_user` collects everything for
`POST /me/export`; `erase_user` runs every eraser inside one transaction for `DELETE /me`,
accounts last. Modules never import each other for this, like events.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import transaction

type Exporter = Callable[[AsyncSession, UUID], Awaitable[dict[str, Any]]]
type Eraser = Callable[[AsyncSession, UUID], Awaitable[None]]


@dataclass(frozen=True)
class _Entry:
    exporter: Exporter | None
    eraser: Eraser | None
    last: bool


_registry: dict[str, _Entry] = {}


def register(
    module: str,
    *,
    exporter: Exporter | None = None,
    eraser: Eraser | None = None,
    last: bool = False,
) -> None:
    """Register a module's handlers; registering again replaces them (app startup)."""
    _registry[module] = _Entry(exporter, eraser, last)


async def export_user(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Everything every module holds about this user, by module."""
    return {
        module: await entry.exporter(db, user_id)
        for module, entry in sorted(_registry.items())
        if entry.exporter is not None
    }


async def erase_user(db: AsyncSession, user_id: UUID) -> list[str]:
    """Erase or anonymise the user's data in every module; returns the modules run."""
    order = sorted(_registry.items(), key=lambda item: (item[1].last, item[0]))
    ran = []
    async with transaction(db):
        for module, entry in order:
            if entry.eraser is not None:
                await entry.eraser(db, user_id)
                ran.append(module)
    return ran
