"""Cursor pagination: `?cursor=&limit=` → `{"items": [...], "next_cursor": ...}`.

A cursor is an opaque, URL-safe token holding the keyset position of the last item returned
(for example its `(starts_at, id)`). Repositories still apply all scoping filters, so a
tampered cursor can only move the starting point, never widen what a viewer may see.
"""

import base64
import binascii
import json
from collections.abc import Mapping
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

from app.core.errors import FieldError, ValidationFailed

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
_CURSOR_VERSION = 1
_MAX_CURSOR_LENGTH = 1024

CursorValue = str | int | float | bool | None


class Page[ItemT](BaseModel):
    items: list[ItemT]
    next_cursor: str | None


class PageParams(BaseModel):
    cursor: str | None = None
    limit: int = DEFAULT_LIMIT


def encode_cursor(position: Mapping[str, CursorValue]) -> str:
    """Encode a keyset position as an opaque cursor."""
    payload = {"v": _CURSOR_VERSION, "p": dict(position)}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(cursor: str) -> dict[str, CursorValue]:
    """Decode a cursor from `encode_cursor`; anything else is a validation error."""
    try:
        if len(cursor) > _MAX_CURSOR_LENGTH:
            raise ValueError("too long")
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
            raise ValueError("unknown cursor version")
        position = payload["p"]
        if not isinstance(position, dict) or not all(
            isinstance(v, str | int | float | bool | None) for v in position.values()
        ):
            raise ValueError("malformed position")
    except (ValueError, KeyError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationFailed(
            "Invalid pagination cursor",
            errors=[FieldError(field="query.cursor", message="invalid cursor")],
        ) from exc
    return position


def page_params(
    cursor: Annotated[str | None, Query(max_length=_MAX_CURSOR_LENGTH)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> PageParams:
    """FastAPI dependency parsing the standard pagination query parameters."""
    return PageParams(cursor=cursor, limit=limit)
