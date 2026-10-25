"""In-process domain events, handled inside the publisher's transaction.

A module publishes an event without knowing who listens, so modules that may not import
each other (accounts → audience) can still react: handlers get the same database session.
Events are plain frozen dataclasses defined here, since both sides need them.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

type Handler = Callable[[AsyncSession, Any], Awaitable[None]]

_handlers: dict[type, list[Handler]] = defaultdict(list)
_keyed: dict[tuple[type, str], Handler] = {}


@dataclass(frozen=True)
class UserSignedUp:
    """A new account was verified; `follow_target` is what the person chose before."""

    user_id: UUID
    follow_target: dict[str, str] | None


@dataclass(frozen=True)
class OrganisationCreated:
    """The creator becomes the organisation's first admin (subscriptions owns members)."""

    organisation_id: UUID
    user_id: UUID


@dataclass(frozen=True)
class TournamentPublished:
    """Scoring creates a scorer pass per pitch; analysis builds the first read models."""

    tournament_id: UUID
    pitch_ids: tuple[UUID, ...]


def subscribe(event_type: type, handler: Handler, *, key: str | None = None) -> None:
    """Add a handler; with `key`, a later subscription under the same key replaces it
    (every app instance registers its handlers at startup)."""
    if key is not None:
        previous = _keyed.pop((event_type, key), None)
        if previous is not None:
            _handlers[event_type].remove(previous)
        _keyed[(event_type, key)] = handler
    _handlers[event_type].append(handler)


def unsubscribe(event_type: type, handler: Handler) -> None:
    _handlers[event_type].remove(handler)


async def publish(session: AsyncSession, event: object) -> None:
    for handler in list(_handlers[type(event)]):
        await handler(session, event)
