"""Opaque tokens and access JWTs (docs/09-security-privacy.md, Authentication).

Opaque tokens (magic links, refresh tokens, scorer passes) are random and stored only as
SHA-256 hashes. Access tokens are short-lived HS256 JWTs; expiry is checked against the
injectable clock, not the system time, so tests can travel in time.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import jwt

from app.core.time import ensure_utc

ACCESS_TOKEN_TTL = timedelta(minutes=15)
_ALGORITHM = "HS256"
_ACCESS_TYPE = "access"


def new_token() -> str:
    """A random URL-safe token with 256 bits of entropy."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


@dataclass(frozen=True)
class AccessClaims:
    user_id: UUID
    session_id: UUID
    roles: frozenset[str]
    expires_at: datetime


def encode_access_token(claims: AccessClaims, secret: str) -> str:
    payload = {
        "typ": _ACCESS_TYPE,
        "sub": str(claims.user_id),
        "sid": str(claims.session_id),
        "roles": sorted(claims.roles),
        "exp": int(claims.expires_at.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_access_token(token: str, secret: str, now: datetime) -> AccessClaims | None:
    """The claims of a valid, unexpired access token; None for anything else."""
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM], options={"verify_exp": False})
        if payload.get("typ") != _ACCESS_TYPE:
            return None
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=ensure_utc(now).tzinfo)
        if expires_at <= ensure_utc(now):
            return None
        return AccessClaims(
            user_id=UUID(payload["sub"]),
            session_id=UUID(payload["sid"]),
            roles=frozenset(payload.get("roles", [])),
            expires_at=expires_at,
        )
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return None


LIVE_TOKEN_TTL = timedelta(seconds=60)
_LIVE_TYPE = "live"


def encode_live_token(scope: str, subject: str, expires_at: datetime, secret: str) -> str:
    """A short token for one live socket: `scope` is "match:<id>" or "tournament:<id>"."""
    payload = {
        "typ": _LIVE_TYPE,
        "scope": scope,
        "sub": subject,
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_live_token(token: str, secret: str, now: datetime) -> str | None:
    """The scope of a valid, unexpired live token; None otherwise."""
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM], options={"verify_exp": False})
    except jwt.InvalidTokenError:
        return None
    if (
        payload.get("typ") != _LIVE_TYPE
        or int(payload.get("exp", 0)) <= ensure_utc(now).timestamp()
    ):
        return None
    scope = payload.get("scope")
    return scope if isinstance(scope, str) else None
