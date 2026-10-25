"""Accounts endpoints: sign-up, magic links, sessions and `/me` (docs/05-api.md)."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import API_PREFIX, Settings
from app.core.db import get_session
from app.core.errors import NotAuthenticated
from app.core.security import ACCESS_TOKEN_TTL
from app.core.viewer import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, Member, verify_csrf
from app.modules.accounts import service
from app.modules.accounts.schemas import (
    Accepted,
    DemoLoginRequest,
    MagicLinkRequest,
    Me,
    MePatch,
    MyData,
    SessionInfo,
    SignupRequest,
    VerifyRequest,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(prefix="/me", tags=["me"])

Db = Annotated[AsyncSession, Depends(get_session)]
REFRESH_PATH = f"{API_PREFIX}/auth"


def _context(request: Request) -> service.AuthContext:
    state = request.app.state
    return service.AuthContext(state.settings, state.clock, state.email_sender, state.redis)


Context = Annotated[service.AuthContext, Depends(_context)]


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_cookies(response: Response, issued: service.IssuedSession, settings: Settings) -> None:
    secure = not settings.is_dev
    domain = None if settings.is_dev else settings.cookie_domain
    idle = int(service.SESSION_IDLE_TTL.total_seconds())
    response.set_cookie(
        ACCESS_COOKIE,
        issued.access_token,
        max_age=int(ACCESS_TOKEN_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        domain=domain,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=idle,
        path=REFRESH_PATH,
        httponly=True,
        secure=secure,
        domain=domain,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE, issued.csrf_token, max_age=idle, secure=secure, domain=domain, samesite="lax"
    )


def _clear_cookies(response: Response, settings: Settings) -> None:
    domain = None if settings.is_dev else settings.cookie_domain
    response.delete_cookie(ACCESS_COOKIE, domain=domain)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, domain=domain)
    response.delete_cookie(CSRF_COOKIE, domain=domain)


def _session_info(issued: service.IssuedSession) -> SessionInfo:
    return SessionInfo(
        user_id=issued.user_id,
        csrf_token=issued.csrf_token,
        account_created=issued.account_created,
    )


@auth_router.post("/signup", status_code=202, response_model=Accepted, operation_id="signUp")
async def sign_up(body: SignupRequest, request: Request, db: Db, ctx: Context) -> Accepted:
    """Start a sign-up: emails a magic link that creates the account. Always 202."""
    await service.sign_up(db, ctx, body, _ip(request))
    return Accepted()


@auth_router.post(
    "/magic-link", status_code=202, response_model=Accepted, operation_id="requestMagicLink"
)
async def request_magic_link(
    body: MagicLinkRequest, request: Request, db: Db, ctx: Context
) -> Accepted:
    """Email a sign-in link. Always 202, whether or not the email has an account."""
    await service.request_magic_link(db, ctx, body.email, _ip(request))
    return Accepted()


@auth_router.post("/magic-link/verify", response_model=SessionInfo, operation_id="verifyMagicLink")
async def verify_magic_link(
    body: VerifyRequest, request: Request, response: Response, db: Db, ctx: Context
) -> SessionInfo:
    """Open a magic link: sets the session cookies (and creates a pending account)."""
    issued = await service.verify(db, ctx, body.token, request.headers.get("User-Agent"))
    _set_cookies(response, issued, ctx.settings)
    return _session_info(issued)


@auth_router.post("/demo-login", response_model=SessionInfo, operation_id="demoLogin")
async def demo_login(
    body: DemoLoginRequest, request: Request, response: Response, db: Db, ctx: Context
) -> SessionInfo:
    """Development only (404 elsewhere): sign in as a demo fan, organiser or editor."""
    issued = await service.demo_login(db, ctx, body.persona, request.headers.get("User-Agent"))
    _set_cookies(response, issued, ctx.settings)
    return _session_info(issued)


@auth_router.post(
    "/refresh",
    response_model=SessionInfo,
    operation_id="refreshSession",
    dependencies=[Depends(verify_csrf)],
)
async def refresh_session(
    response: Response,
    db: Db,
    ctx: Context,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> SessionInfo:
    """Rotate the refresh token and issue a new access token."""
    if not refresh_token:
        raise NotAuthenticated()
    issued = await service.refresh(db, ctx, refresh_token)
    _set_cookies(response, issued, ctx.settings)
    return _session_info(issued)


@auth_router.post("/logout", status_code=204, operation_id="logout")
async def logout(
    viewer: Member,
    db: Db,
    ctx: Context,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> Response:
    """End this device's session."""
    await service.logout(db, ctx, viewer, refresh_token)
    response = Response(status_code=204)
    _clear_cookies(response, ctx.settings)
    return response


@auth_router.post("/logout-all", status_code=204, operation_id="logoutAll")
async def logout_all(viewer: Member, db: Db, ctx: Context) -> Response:
    """End every session of this account."""
    await service.logout_all(db, ctx, viewer)
    response = Response(status_code=204)
    _clear_cookies(response, ctx.settings)
    return response


@me_router.get("", response_model=Me, operation_id="getMe")
async def get_me(viewer: Member, db: Db) -> Me:
    """The signed-in user's profile."""
    return await service.get_me(db, viewer)


@me_router.post("/export", response_model=MyData, operation_id="exportMyData")
async def export_me(viewer: Member, db: Db, ctx: Context) -> MyData:
    """Everything OurSport holds about you, from every part of the service (JSON)."""
    return await service.export_me(db, ctx, viewer)


@me_router.delete("", status_code=204, operation_id="deleteMe")
async def delete_me(viewer: Member, db: Db, ctx: Context) -> Response:
    """Delete your account: follows, notifications and sessions are removed, your name is
    taken off anything you edited or reported, and you are signed out everywhere."""
    await service.delete_me(db, viewer)
    response = Response(status_code=204)
    _clear_cookies(response, ctx.settings)
    return response


@me_router.patch("", response_model=Me, operation_id="updateMe")
async def update_me(body: MePatch, viewer: Member, db: Db, ctx: Context) -> Me:
    """Change display name, language or time zone."""
    return await service.update_me(db, ctx, viewer, body)
