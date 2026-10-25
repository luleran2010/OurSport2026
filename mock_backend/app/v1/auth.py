"""v1 identity, as the backend does it (backend/docs/09): an httpOnly access cookie (15 min), a
refresh cookie limited to `/api/v1/auth` that rotates on every use, a JS-readable CSRF cookie
that unsafe requests echo in `X-CSRF-Token`, and `Authorization: Pass <token>` for scorers.

Profiles are the mock's `Session` objects, so the old portal routes (still on the `lp_sid`
cookie) see the same signed-in person. Magic links go to an outbox (`GET /mock/outbox`)
instead of email, standing in for Mailpit.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import Request, Response

from .errors import problem

if TYPE_CHECKING:
    from ..store import FeedStore, Session

ACCESS_COOKIE = "oursport_access"
REFRESH_COOKIE = "oursport_refresh"
CSRF_COOKIE = "oursport_csrf"
CSRF_HEADER = "X-CSRF-Token"
LEGACY_COOKIE = "lp_sid"
REFRESH_PATH = "/api/v1/auth"
ACCESS_TTL = 15 * 60
REFRESH_TTL = 60 * 24 * 3600
LINK_TTL = 15 * 60
LIVE_TOKEN_TTL = 60
_SAFE = {"GET", "HEAD", "OPTIONS"}


def _now() -> float:
    return time.time()


@dataclass
class Grant:
    profile: Session
    expires: float


@dataclass
class V1State:
    access: dict[str, Grant] = field(default_factory=dict)
    refresh: dict[str, Grant] = field(default_factory=dict)
    links: dict[str, dict] = field(default_factory=dict)  # token -> {email, signup, expires}
    outbox: list[dict] = field(default_factory=list)
    accounts: dict[str, Session] = field(default_factory=dict)  # email -> profile
    live_tokens: dict[str, tuple[str, float]] = field(default_factory=dict)  # token -> (scope, expires)
    follow_created: dict[tuple[str, str], float] = field(default_factory=dict)


def state(store: FeedStore) -> V1State:
    if getattr(store, "v1", None) is None:
        store.v1 = V1State()
    return store.v1


@dataclass(frozen=True)
class Viewer:
    profile: Session | None = None
    pass_tournament: str | None = None  # tournament slug of a scorer pass

    @property
    def is_member(self) -> bool:
        return bool(self.profile and self.profile.signed_in)


# Scorer passes: one demo pass per tournament (a pitch QR in the real backend).
def pass_token(tournament_slug: str) -> str:
    return f"demo-pass-{tournament_slug}"


def viewer_of(store: FeedStore, request: Request) -> Viewer:
    grant = state(store).access.get(request.cookies.get(ACCESS_COOKIE, ""))
    profile = grant.profile if grant and grant.expires > _now() and grant.profile.signed_in else None
    tournament = None
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("pass "):
        token = authorization[5:].strip()
        if not token.startswith("demo-pass-"):
            raise problem(401, "not_authenticated", "unknown scorer pass")
        tournament = token.removeprefix("demo-pass-")
        if tournament not in store.tournaments:
            raise problem(401, "not_authenticated", "unknown scorer pass")
    return Viewer(profile=profile, pass_tournament=tournament)


def check_csrf(request: Request) -> None:
    if request.method in _SAFE:
        return
    if ACCESS_COOKIE not in request.cookies and REFRESH_COOKIE not in request.cookies:
        return
    cookie, header = request.cookies.get(CSRF_COOKIE, ""), request.headers.get(CSRF_HEADER, "")
    if not cookie or not secrets.compare_digest(cookie, header):
        raise problem(403, "forbidden", "CSRF token missing or does not match")


def issue(store: FeedStore, response: Response, profile: Session) -> str:
    """New session cookies for this profile; returns the CSRF token."""
    s = state(store)
    access, refresh, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(16)
    s.access[access] = Grant(profile, _now() + ACCESS_TTL)
    s.refresh[refresh] = Grant(profile, _now() + REFRESH_TTL)
    response.set_cookie(ACCESS_COOKIE, access, max_age=ACCESS_TTL, httponly=True, samesite="lax")
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=REFRESH_TTL, path=REFRESH_PATH, httponly=True, samesite="lax")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=REFRESH_TTL, samesite="lax")
    # the portal pages that still use the old routes read the same person from lp_sid
    sid = secrets.token_urlsafe(16)
    store.bind(sid, profile)
    response.set_cookie(LEGACY_COOKIE, sid, httponly=True, samesite="lax", max_age=REFRESH_TTL)
    return csrf


def rotate(store: FeedStore, request: Request, response: Response) -> tuple[Session, str]:
    s = state(store)
    token = request.cookies.get(REFRESH_COOKIE, "")
    grant = s.refresh.pop(token, None)
    if grant is None or grant.expires <= _now() or not grant.profile.signed_in:
        raise problem(401, "not_authenticated", "Sign in again")
    return grant.profile, issue(store, response, grant.profile)


def end(store: FeedStore, request: Request, response: Response, *, everywhere: bool = False) -> None:
    s = state(store)
    grant = s.access.get(request.cookies.get(ACCESS_COOKIE, ""))
    s.refresh.pop(request.cookies.get(REFRESH_COOKIE, ""), None)
    s.access.pop(request.cookies.get(ACCESS_COOKIE, ""), None)
    if everywhere and grant:
        s.access = {k: g for k, g in s.access.items() if g.profile is not grant.profile}
        s.refresh = {k: g for k, g in s.refresh.items() if g.profile is not grant.profile}
    response.delete_cookie(ACCESS_COOKIE)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)
    response.delete_cookie(CSRF_COOKIE)
    response.delete_cookie(LEGACY_COOKIE)


def send_link(store: FeedStore, email: str, signup: dict | None, origin: str) -> None:
    s = state(store)
    token = secrets.token_urlsafe(24)
    s.links[token] = {"email": email, "signup": signup, "expires": _now() + LINK_TTL}
    link = f"{origin}/auth/verify?token={token}"
    s.outbox.insert(0, {"to": email, "subject": "Your OurSport sign-in link", "link": link, "token": token})
    print(f"[magic link] {email}: {link}", flush=True)
