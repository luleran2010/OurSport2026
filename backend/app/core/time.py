"""UTC time helpers and an injectable clock.

The backend works in UTC only. Code that needs "now" takes a `Clock` (in requests via the
`get_clock` dependency) so tests can freeze and move time.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Protocol

from fastapi import Request
from pydantic import AfterValidator, PlainSerializer


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as an aware UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Clock for tests: stands still until moved."""

    def __init__(self, at: datetime) -> None:
        self._at = ensure_utc(at)

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = ensure_utc(at)

    def advance(self, delta: timedelta) -> None:
        self._at += delta


def ensure_utc(value: datetime) -> datetime:
    """Return `value` converted to UTC; naive datetimes are rejected, never guessed."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime: a timezone is required")
    return value.astimezone(UTC)


def isoformat_z(value: datetime) -> str:
    """Format as ISO 8601 UTC with a `Z` suffix, e.g. `2026-10-24T14:03:11Z`."""
    utc = ensure_utc(value)
    timespec = "milliseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string with an explicit offset (or `Z`) into UTC."""
    return ensure_utc(datetime.fromisoformat(value))


# Use in Pydantic models for every API timestamp: validates to UTC, serialises with `Z`.
UtcDatetime = Annotated[
    datetime,
    AfterValidator(ensure_utc),
    PlainSerializer(isoformat_z, return_type=str, when_used="json"),
]


def get_clock(request: Request) -> Clock:
    """FastAPI dependency returning the application's clock."""
    clock: Clock = request.app.state.clock
    return clock
