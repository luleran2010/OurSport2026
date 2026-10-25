"""Accounts: sign-up, magic links, sessions and the profile (docs/09-security-privacy.md).

No passwords. A sign-up is only an intent until its magic link is opened; then the account
is created (verified email) and `UserSignedUp` carries the team the person chose to follow.
Refresh tokens rotate on every use; presenting an old one revokes the whole session.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events, privacy, rate_limit
from app.core.config import Settings
from app.core.db import transaction
from app.core.email import EmailSender, OutgoingEmail
from app.core.errors import NotAuthenticated, NotFound
from app.core.ids import new_id
from app.core.security import (
    ACCESS_TOKEN_TTL,
    AccessClaims,
    encode_access_token,
    hash_token,
    new_token,
    tokens_match,
)
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.accounts import repository
from app.modules.accounts.models import (
    AuthSession,
    FamilyLink,
    LoginToken,
    SignupIntent,
    User,
    UserRole,
)
from app.modules.accounts.schemas import (
    DemoPersona,
    Me,
    MeParts,
    MePatch,
    MyData,
    Preferences,
    Profile,
    SignupRequest,
)

log = structlog.get_logger("accounts")
LOGIN_TOKEN_TTL = timedelta(minutes=15)
SIGNUP_INTENT_TTL = timedelta(hours=24)
SESSION_IDLE_TTL = timedelta(days=60)
_HOUR = 3600

_LINK_TEXT = {
    "en": ("Your OurSport sign-in link", "Open this link within 15 minutes to sign in:"),
    "fi": ("OurSport-kirjautumislinkkisi", "Avaa linkki 15 minuutin kuluessa kirjautuaksesi:"),
    "bn": ("আপনার OurSport সাইন-ইন লিঙ্ক", "সাইন ইন করতে ১৫ মিনিটের মধ্যে এই লিঙ্কটি খুলুন:"),
}


@dataclass(frozen=True)
class AuthContext:
    settings: Settings
    clock: Clock
    email: EmailSender
    redis: Redis


@dataclass(frozen=True)
class IssuedSession:
    user_id: UUID
    access_token: str
    refresh_token: str  # "<session id>.<secret>"
    csrf_token: str
    account_created: bool


# --- magic links ------------------------------------------------------------------------------


async def _limit(ctx: AuthContext, email: str, ip: str) -> None:
    settings = ctx.settings
    await rate_limit.enforce(
        ctx.redis,
        f"magic:email:{email.lower()}",
        limit=settings.magic_link_per_email_per_hour,
        window_s=_HOUR,
    )
    await rate_limit.enforce(
        ctx.redis, f"magic:ip:{ip}", limit=settings.magic_link_per_ip_per_hour, window_s=_HOUR
    )


def _login_token(
    db: AsyncSession, now: datetime, purpose: str, user_id: UUID | None
) -> tuple[str, LoginToken]:
    raw = new_token()
    row = LoginToken(
        id=new_id(),
        user_id=user_id,
        token_hash=hash_token(raw),
        purpose=purpose,
        created_at=now,
        expires_at=now + LOGIN_TOKEN_TTL,
    )
    db.add(row)
    return raw, row


def _link_email(ctx: AuthContext, to: str, language: str, token: str) -> OutgoingEmail:
    subject, lead = _LINK_TEXT.get(language, _LINK_TEXT["en"])
    link = f"{ctx.settings.web_base_url}/auth/verify?token={token}"
    return OutgoingEmail(to=to, subject=subject, text=f"{lead}\n\n{link}\n")


async def sign_up(db: AsyncSession, ctx: AuthContext, request: SignupRequest, ip: str) -> None:
    """Send a magic link that creates the account when opened.

    An email that already has an account simply gets a sign-in link; the caller always
    answers 202, so nobody can probe which emails are registered.
    """
    await _limit(ctx, request.email, ip)
    now = ctx.clock.now()
    async with transaction(db):
        user = await repository.user_by_email(db, request.email)
        if user is not None:
            token, _ = _login_token(db, now, "login", user.id)
            email = _link_email(ctx, user.email, user.language, token)
        else:
            token, row = _login_token(db, now, "verify", None)
            db.add(
                SignupIntent(
                    id=new_id(),
                    email=request.email,
                    display_name=request.display_name,
                    language=request.language,
                    time_zone=request.time_zone,
                    follow_target=request.follow.model_dump(mode="json")
                    if request.follow
                    else None,
                    login_token_id=row.id,
                    created_at=now,
                    expires_at=now + SIGNUP_INTENT_TTL,
                )
            )
            email = _link_email(ctx, request.email, request.language, token)
    await ctx.email.send(email)


async def request_magic_link(db: AsyncSession, ctx: AuthContext, email: str, ip: str) -> None:
    """Send a sign-in link if the email has an account; silently nothing otherwise."""
    await _limit(ctx, email, ip)
    now = ctx.clock.now()
    async with transaction(db):
        user = await repository.user_by_email(db, email)
        if user is None:
            return
        token, _ = _login_token(db, now, "login", user.id)
        message = _link_email(ctx, user.email, user.language, token)
    await ctx.email.send(message)


async def verify(
    db: AsyncSession, ctx: AuthContext, token: str, user_agent: str | None
) -> IssuedSession:
    """Use a magic link: completes a pending sign-up, then starts a session."""
    now = ctx.clock.now()
    expired = NotAuthenticated("This link has expired or was already used")
    async with transaction(db):
        row = await repository.login_token_by_hash(db, hash_token(token))
        if row is None or row.used_at is not None or row.expires_at <= now:
            raise expired
        row.used_at = now
        created = False
        if row.purpose == "verify":
            intent = await repository.intent_for_token(db, row.id)
            if intent is None or intent.expires_at <= now:
                raise expired
            user = await repository.user_by_email(db, intent.email)
            if user is None:
                user = User(
                    id=new_id(),
                    email=intent.email,
                    display_name=intent.display_name,
                    language=intent.language,
                    time_zone=intent.time_zone,
                    birth_year_confirmed_13_plus=True,
                    privacy_accepted_at=intent.created_at,
                    email_verified_at=now,
                    created_at=now,
                    updated_at=now,
                )
                db.add(user)
                await db.flush()
                created = True
                await events.publish(db, events.UserSignedUp(user.id, intent.follow_target))
            await db.delete(intent)
        else:
            user = await repository.user_by_id(db, row.user_id) if row.user_id else None
            if user is None:
                raise expired
            if user.email_verified_at is None:
                user.email_verified_at = now
        return await _start_session(db, ctx, user.id, user_agent, now, created=created)


# --- sessions ---------------------------------------------------------------------------------


async def _access_token(
    db: AsyncSession, ctx: AuthContext, user_id: UUID, session_id: UUID, now: datetime
) -> str:
    claims = AccessClaims(
        user_id=user_id,
        session_id=session_id,
        roles=await repository.roles_of(db, user_id),
        expires_at=now + ACCESS_TOKEN_TTL,
    )
    return encode_access_token(claims, ctx.settings.jwt_secret.get_secret_value())


async def _start_session(
    db: AsyncSession,
    ctx: AuthContext,
    user_id: UUID,
    user_agent: str | None,
    now: datetime,
    *,
    created: bool,
) -> IssuedSession:
    secret = new_token()
    row = AuthSession(
        id=new_id(),
        user_id=user_id,
        refresh_token_hash=hash_token(secret),
        user_agent=(user_agent or "")[:300] or None,
        created_at=now,
        last_used_at=now,
    )
    db.add(row)
    return IssuedSession(
        user_id=user_id,
        access_token=await _access_token(db, ctx, user_id, row.id, now),
        refresh_token=f"{row.id}.{secret}",
        csrf_token=new_token(),
        account_created=created,
    )


def _split_refresh(token: str) -> tuple[UUID, str]:
    session_id, _, secret = token.partition(".")
    try:
        return UUID(session_id), secret
    except ValueError as exc:
        raise NotAuthenticated("Invalid session") from exc


async def refresh(db: AsyncSession, ctx: AuthContext, refresh_token: str) -> IssuedSession:
    """Rotate the refresh token. An old (already rotated) token revokes the session."""
    session_id, secret = _split_refresh(refresh_token)
    now = ctx.clock.now()
    reused = False
    async with transaction(db):
        row = await repository.session_by_id(db, session_id)
        if row is None or row.revoked_at is not None or row.last_used_at + SESSION_IDLE_TTL <= now:
            raise NotAuthenticated("Session ended")
        if not tokens_match(hash_token(secret), row.refresh_token_hash):
            row.revoked_at = now  # a stolen copy is in use somewhere: end the session
            reused = True
        else:
            new_secret = new_token()
            row.refresh_token_hash = hash_token(new_secret)
            row.last_used_at = now
            issued = IssuedSession(
                user_id=row.user_id,
                access_token=await _access_token(db, ctx, row.user_id, row.id, now),
                refresh_token=f"{row.id}.{new_secret}",
                csrf_token=new_token(),
                account_created=False,
            )
    if reused:
        raise NotAuthenticated("Session ended")
    return issued


async def logout(
    db: AsyncSession, ctx: AuthContext, viewer: Viewer, refresh_token: str | None
) -> None:
    """End this device's session."""
    now = ctx.clock.now()
    ids = {viewer.session_id} if viewer.session_id else set()
    if refresh_token:
        ids.add(_split_refresh(refresh_token)[0])
    async with transaction(db):
        for session_id in ids:
            row = await repository.session_by_id(db, session_id)
            if row is not None and row.user_id == viewer.user_id and row.revoked_at is None:
                row.revoked_at = now


async def logout_all(db: AsyncSession, ctx: AuthContext, viewer: Viewer) -> None:
    """End every session of the user (all devices)."""
    assert viewer.user_id is not None
    async with transaction(db):
        await repository.revoke_sessions(db, viewer.user_id, ctx.clock.now())


# The seed script makes demo.organiser@example.com the owner of the demo tournaments.
DEMO_ACCOUNTS: dict[DemoPersona, tuple[str, str, str | None]] = {
    "fan": ("demo.fan@example.com", "Demo Fan", None),
    "organiser": ("demo.organiser@example.com", "Demo Organiser", None),
    "editor": ("demo.editor@example.com", "Demo Editor", "editor"),
}


async def demo_login(
    db: AsyncSession, ctx: AuthContext, persona: DemoPersona, user_agent: str | None
) -> IssuedSession:
    """Development only (`ENV=local|test`): a session for a demo account, no email needed."""
    if not ctx.settings.is_dev:
        raise NotFound()
    email, name, role = DEMO_ACCOUNTS[persona]
    user_id = await ensure_user(db, ctx.clock, email, name)
    async with transaction(db):
        if role and role not in await repository.roles_of(db, user_id):
            db.add(UserRole(user_id=user_id, role=role))
            await db.flush()
        return await _start_session(db, ctx, user_id, user_agent, ctx.clock.now(), created=False)


# --- profile ----------------------------------------------------------------------------------


MeContributor = Callable[[AsyncSession, UUID], Awaitable[MeParts]]
_me_contributors: dict[str, MeContributor] = {}


def contribute_to_me(key: str, contributor: MeContributor) -> None:
    """Let a module fill part of `Me` (staff roles, follows, unread count). Accounts may
    not call other modules, so they register here at start-up (like the privacy hooks)."""
    _me_contributors[key] = contributor


async def _me(db: AsyncSession, user: User) -> Me:
    me = Me(
        id=user.id,
        display_name=user.display_name,
        email=user.email,
        language=user.language,  # type: ignore[arg-type]  # CHECK constraint keeps it valid
        time_zone=user.time_zone,
        global_roles=sorted(await repository.roles_of(db, user.id)),
        family_player_ids=sorted(await repository.family_player_ids(db, user.id)),
        preferences=Preferences.model_validate(user.preferences or {}),
    )
    for contributor in _me_contributors.values():
        parts = await contributor(db, user.id)
        me = me.model_copy(update=parts.model_dump(exclude_none=True))
    return Me.model_validate(me.model_dump())


async def get_me(db: AsyncSession, viewer: Viewer) -> Me:
    """The signed-in user's profile."""
    assert viewer.user_id is not None
    user = await repository.user_by_id(db, viewer.user_id)
    if user is None:
        raise NotFound()
    return await _me(db, user)


async def update_me(db: AsyncSession, ctx: AuthContext, viewer: Viewer, patch: MePatch) -> Me:
    """Change display name, language, time zone or consent preferences."""
    assert viewer.user_id is not None
    async with transaction(db):
        user = await repository.user_by_id(db, viewer.user_id)
        if user is None:
            raise NotFound()
        for name, value in patch.model_dump(exclude_none=True, exclude={"preferences"}).items():
            setattr(user, name, value)
        if patch.preferences is not None:
            changes = patch.preferences.model_dump(exclude_none=True)
            current = Preferences.model_validate(user.preferences or {})
            user.preferences = current.model_copy(
                update={**changes, "updated_at": ctx.clock.now()}
            ).model_dump(mode="json")
        user.updated_at = ctx.clock.now()
        return await _me(db, user)


# --- family links -----------------------------------------------------------------------------


async def family_player_ids(db: AsyncSession, user_id: UUID | None) -> frozenset[UUID]:
    """Players the user is a linked parent or guardian of."""
    if user_id is None:
        return frozenset()
    return await repository.family_player_ids(db, user_id)


async def link_family(
    db: AsyncSession, ctx: Clock, user_id: UUID, player_id: UUID, created_by: UUID | None
) -> None:
    """Link a guardian account to a player (consent is checked by the caller)."""
    async with transaction(db):
        db.add(
            FamilyLink(
                user_id=user_id, player_id=player_id, created_by=created_by, created_at=ctx.now()
            )
        )


async def ensure_user(
    db: AsyncSession, clock: Clock, email: str, display_name: str, language: str = "en"
) -> UUID:
    """A verified user for scripts (demo data); created once, then found by email."""
    async with transaction(db):
        user = await repository.user_by_email(db, email)
        if user is None:
            now = clock.now()
            user = User(
                id=new_id(),
                email=email,
                display_name=display_name,
                language=language,
                time_zone="Europe/Helsinki",
                birth_year_confirmed_13_plus=True,
                privacy_accepted_at=now,
                email_verified_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(user)
    return user.id


async def profiles(db: AsyncSession, user_ids: list[UUID]) -> dict[UUID, Profile]:
    """Language, time zone and email of these users."""
    return {
        u.id: Profile(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            language=u.language,  # type: ignore[arg-type]  # CHECK constraint keeps it valid
            time_zone=u.time_zone,
        )
        for u in await repository.users_by_ids(db, user_ids)
    }


# --- data rights ------------------------------------------------------------------------------


async def export_me(db: AsyncSession, ctx: AuthContext, viewer: Viewer) -> MyData:
    """A copy of everything held about the signed-in user, from every module."""
    assert viewer.user_id is not None
    data = await privacy.export_user(db, viewer.user_id)
    return MyData(user_id=viewer.user_id, generated_at=ctx.clock.now(), data=data)


async def delete_me(db: AsyncSession, viewer: Viewer) -> None:
    """Erase the account: every module removes or anonymises what it holds, then the
    account becomes an anonymous tombstone and every session ends."""
    assert viewer.user_id is not None
    await privacy.erase_user(db, viewer.user_id)
    log.info("account_deleted")


async def unlink_player(db: AsyncSession, player_id: UUID) -> None:
    """Remove every family link to a player (the player's data is being erased)."""
    await repository.unlink_player(db, player_id)


async def purge_expired(db: AsyncSession, clock: Clock) -> int:
    """Retention (docs/09): login tokens 1 day, unverified sign-ups 24 h, sessions ended
    30 days ago or idle past the session lifetime."""
    async with transaction(db):
        return await repository.purge_expired(db, clock.now(), idle=SESSION_IDLE_TTL)


async def user_id_by_email(db: AsyncSession, email: str) -> UUID | None:
    """The account with this email (organisers link a guardian's account)."""
    user = await repository.user_by_email(db, email)
    return user.id if user is not None and user.deleted_at is None else None


async def display_name(db: AsyncSession, user_id: UUID) -> str:
    """A user's display name (staff lists)."""
    user = await repository.user_by_id(db, user_id)
    return user.display_name if user is not None else "Unknown"
