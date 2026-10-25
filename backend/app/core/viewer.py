"""Who is asking: the `Viewer` every endpoint receives (docs/09-security-privacy.md).

Built from the access cookie (a signed JWT, no database read) and an optional
`Authorization: Pass <token>` header. Scorer passes are resolved by the scoring module;
here the raw token is only carried along.
"""

from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.core.config import Settings
from app.core.errors import Forbidden, NotAuthenticated
from app.core.security import decode_access_token, tokens_match
from app.core.time import Clock

ACCESS_COOKIE = "oursport_access"
REFRESH_COOKIE = "oursport_refresh"
CSRF_COOKIE = "oursport_csrf"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_PASS_SCHEME = "pass "


@dataclass(frozen=True)
class Viewer:
    user_id: UUID | None = None
    session_id: UUID | None = None
    global_roles: frozenset[str] = field(default_factory=frozenset)
    pass_token: str | None = None  # raw scorer pass token, resolved by scoring

    @property
    def is_member(self) -> bool:
        return self.user_id is not None


def current_viewer(request: Request) -> Viewer:
    """FastAPI dependency: the signed-in user, a scorer pass holder, or anonymous."""
    settings: Settings = request.app.state.settings
    clock: Clock = request.app.state.clock
    pass_token = None
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith(_PASS_SCHEME):
        pass_token = authorization[len(_PASS_SCHEME) :].strip() or None
    token = request.cookies.get(ACCESS_COOKIE)
    claims = (
        decode_access_token(token, settings.jwt_secret.get_secret_value(), clock.now())
        if token
        else None
    )
    if claims is None:
        return Viewer(pass_token=pass_token)
    return Viewer(
        user_id=claims.user_id,
        session_id=claims.session_id,
        global_roles=claims.roles,
        pass_token=pass_token,
    )


def verify_csrf(request: Request) -> None:
    """Double-submit check for unsafe requests that carry session cookies."""
    if request.method in _SAFE_METHODS:
        return
    if ACCESS_COOKIE not in request.cookies and REFRESH_COOKIE not in request.cookies:
        return
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not tokens_match(cookie, header):
        raise Forbidden("CSRF token missing or does not match")


def require_member(
    viewer: Annotated[Viewer, Depends(current_viewer)],
    _: Annotated[None, Depends(verify_csrf)],
) -> Viewer:
    """FastAPI dependency: a signed-in user (CSRF-checked on unsafe methods)."""
    if not viewer.is_member:
        raise NotAuthenticated()
    return viewer


CurrentViewer = Annotated[Viewer, Depends(current_viewer)]
Member = Annotated[Viewer, Depends(require_member)]
