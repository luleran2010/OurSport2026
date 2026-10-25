"""Audience: follows, the My Team hub and the personal and public feeds (docs/14).

Everything shown comes from analysis read models; the hub never shows players the
viewer may not see (analysis applies the visibility filter).
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.db import transaction
from app.core.errors import NotFound, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import Page, PageParams, decode_cursor, encode_cursor
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.accounts import service as accounts
from app.modules.accounts.schemas import FollowRef, MeParts
from app.modules.analysis import service as analysis
from app.modules.analysis.schemas import MatchCard, TeamHub
from app.modules.audience import repository
from app.modules.audience.models import NOTIFY_DEFAULTS, Follow, PushSubscription
from app.modules.audience.schemas import (
    Feed,
    FeedItem,
    FollowIn,
    FollowOut,
    FollowTarget,
    Home,
    NotificationOut,
    NotificationsPage,
    NotifyPatch,
    PushSubscriptionIn,
)
from app.modules.competitions import service as competitions
from app.modules.content import service as content
from app.modules.content.schemas import StoryOut

SIGNUP_HANDLER_KEY = "audience.signup_follow"


def _out(f: Follow) -> FollowOut:
    return FollowOut.model_validate(
        {
            "id": f.id,
            "target_type": f.target_type,
            "target_id": f.target_id,
            "is_primary": f.is_primary,
            "notify": {**NOTIFY_DEFAULTS, **f.notify},
            "created_at": f.created_at,
        }
    )


async def _check_target(db: AsyncSession, viewer: Viewer, data: FollowIn) -> None:
    """Only public things can be followed (drafts are 404)."""
    if data.target_type == "team":
        await competitions.get_team(db, Viewer(), data.target_id)
    elif data.target_type == "tournament":
        await competitions.get_tournament(db, viewer, data.target_id)
    elif data.target_type == "organisation":
        await competitions.organisation_page(db, data.target_id)
    else:
        await competitions.series_page(db, data.target_id)


async def follow(db: AsyncSession, clock: Clock, viewer: Viewer, data: FollowIn) -> FollowOut:
    """Follow a team, tournament, organisation or series; `is_primary` makes it "my team"."""
    assert viewer.user_id is not None
    await _check_target(db, viewer, data)
    if data.is_primary and data.target_type != "team":
        data = data.model_copy(update={"is_primary": False})
    async with transaction(db):
        existing = await repository.follow_of(db, viewer.user_id, data.target_type, data.target_id)
        if data.is_primary:
            await repository.clear_primary(db, viewer.user_id)
        if existing is None:
            existing = Follow(
                id=new_id(),
                user_id=viewer.user_id,
                target_type=data.target_type,
                target_id=data.target_id,
                is_primary=data.is_primary,
                notify={},
                created_at=clock.now(),
            )
            db.add(existing)
        elif data.is_primary:
            existing.is_primary = True
    return await _with_target(db, _out(existing))


async def unfollow(db: AsyncSession, viewer: Viewer, follow_id: UUID) -> None:
    async with transaction(db):
        row = await db.get(Follow, follow_id)
        if row is None or row.user_id != viewer.user_id:
            raise NotFound()
        await db.delete(row)


async def set_notifications(
    db: AsyncSession, viewer: Viewer, follow_id: UUID, patch: NotifyPatch
) -> FollowOut:
    """Turn notification kinds on or off for one follow."""
    async with transaction(db):
        row = await db.get(Follow, follow_id)
        if row is None or row.user_id != viewer.user_id:
            raise NotFound()
        row.notify = {**row.notify, **patch.model_dump(exclude_none=True)}
    return await _with_target(db, _out(row))


async def list_follows(db: AsyncSession, viewer: Viewer) -> list[FollowOut]:
    """Everything the user follows, with the target's name for lists."""
    assert viewer.user_id is not None
    return [
        await _with_target(db, _out(f)) for f in await repository.follows_of(db, viewer.user_id)
    ]


async def _with_target(db: AsyncSession, follow: FollowOut) -> FollowOut:
    try:
        target = await _target(db, follow.target_type, follow.target_id)
    except NotFound:
        target = None  # no longer public (a tournament back in draft, a removed team)
    return follow.model_copy(update={"target": target})


async def _target(db: AsyncSession, target_type: str, target_id: UUID) -> FollowTarget:
    if target_type == "team":
        team = await competitions.get_team(db, Viewer(), target_id)
        return FollowTarget(name=team.name, short_name=team.short_name, subtitle=team.age_group)
    if target_type == "tournament":
        t = await competitions.get_tournament(db, Viewer(), target_id)
        names = await competitions.organisation_names(db, [t.organisation_id])
        return FollowTarget(
            name=t.name,
            subtitle=names.get(t.organisation_id),
            sport=t.sport,
            starts_on=t.starts_on,
            ends_on=t.ends_on,
        )
    if target_type == "organisation":
        org = await competitions.organisation_page(db, target_id)
        return FollowTarget(
            name=org.name, subtitle=org.town, sport=org.sports[0] if org.sports else None
        )
    series = await competitions.series_page(db, target_id)
    return FollowTarget(name=series.name, sport=series.sport)


async def home(db: AsyncSession, viewer: Viewer) -> Home:
    """The My Team hub of the primary team, plus everything followed."""
    follows = await list_follows(db, viewer)
    primary = next((f for f in follows if f.is_primary), None)
    hub = await analysis.team_hub(db, viewer, primary.target_id) if primary else None
    return Home(primary=await _with_stories(db, viewer, hub) if hub else None, following=follows)


async def team_hub(
    db: AsyncSession, viewer: Viewer, team_id: UUID, tournament_id: UUID | None
) -> TeamHub:
    """The hub of any team the viewer follows (or opens)."""
    return await _with_stories(
        db, viewer, await analysis.team_hub(db, viewer, team_id, tournament_id)
    )


async def _with_stories(db: AsyncSession, viewer: Viewer, hub: TeamHub) -> TeamHub:
    """Add the team's published stories (recaps, previews and reports of its matches)."""
    tournament_id = hub.tournament.id if hub.tournament else None
    try:
        cards = await analysis.team_cards(db, viewer, hub.team.id)
    except NotFound:
        cards = []
    stories = await content.team_stories(db, hub.team.id, tournament_id, [c.id for c in cards])
    return hub.model_copy(update={"stories": [s.model_dump(mode="json") for s in stories]})


async def _attach_reports(db: AsyncSession, feed: Feed) -> Feed:
    """Results carry their published match report (every language)."""
    ids = [i.match.id for i in feed.items if i.kind == "result"]
    reports = await content.match_reports(db, ids)
    for item in feed.items:
        if item.kind == "result":
            item.stories = reports.get(item.match.id, [])
    return feed


def _items(cards: list[MatchCard], team_id: UUID | None) -> list[FeedItem]:
    items: list[FeedItem] = []
    next_given = False
    for card in sorted(cards, key=lambda c: c.starts_at):
        if card.status in ("finished", "walkover"):
            items.append(FeedItem(kind="result", at=card.starts_at, team_id=team_id, match=card))
        elif card.status == "live":
            items.append(FeedItem(kind="live", at=card.starts_at, team_id=team_id, match=card))
        elif card.status == "scheduled" and not next_given:
            items.append(
                FeedItem(kind="next_match", at=card.starts_at, team_id=team_id, match=card)
            )
            next_given = True
    return items


def _page(items: list[FeedItem], params: PageParams) -> Feed:
    unique: dict[tuple[str, UUID], FeedItem] = {}
    for item in items:
        unique.setdefault((item.kind, item.match.id), item)
    ordered = sorted(
        unique.values(), key=lambda i: (i.kind != "live", -i.at.timestamp(), str(i.match.id))
    )
    start = 0
    if params.cursor:
        offset = decode_cursor(params.cursor).get("o", 0)
        start = int(offset) if isinstance(offset, int) else 0
    window = ordered[start : start + params.limit]
    more = start + params.limit < len(ordered)
    return Feed(
        items=window, next_cursor=encode_cursor({"o": start + params.limit}) if more else None
    )


async def feed(db: AsyncSession, viewer: Viewer, params: PageParams) -> Feed:
    """Results, live matches and the next match of everything the viewer follows."""
    items: list[FeedItem] = []
    for f in await list_follows(db, viewer):
        try:
            if f.target_type == "team":
                items += _items(await analysis.team_cards(db, viewer, f.target_id), f.target_id)
            elif f.target_type == "tournament":
                items += _items(await analysis.tournament_cards(db, viewer, f.target_id), None)
        except NotFound:
            continue  # a followed team with no public tournament yet
    return await _attach_reports(db, _page(items, params))


async def public_feed(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, params: PageParams
) -> Feed:
    """A tournament's results and live matches for everyone."""
    cards = await analysis.tournament_cards(db, viewer, tournament_id)
    items = [i for i in _items(cards, None) if i.kind != "next_match"]
    return await _attach_reports(db, _page(items, params))


async def followers(db: AsyncSession, target_type: str, target_ids: list[UUID]) -> list[Any]:
    """Follows of these targets (notifications, T-041)."""
    return await repository.followers_of(db, target_type, target_ids)


def register(clock: Clock) -> None:
    """Make the team chosen before sign-up the new user's primary follow."""

    async def on_signed_up(db: AsyncSession, event: events.UserSignedUp) -> None:
        target = event.follow_target
        if not target or target.get("target_type") != "team":
            return
        db.add(
            Follow(
                id=new_id(),
                user_id=event.user_id,
                target_type="team",
                target_id=UUID(target["target_id"]),
                is_primary=True,
                notify={},
                created_at=clock.now(),
            )
        )

    events.subscribe(events.UserSignedUp, on_signed_up, key=SIGNUP_HANDLER_KEY)
    accounts.contribute_to_me("audience", me_parts)


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


async def my_notifications(
    db: AsyncSession, viewer: Viewer, params: PageParams
) -> NotificationsPage:
    """The newest notifications (kept 90 days), a page at a time, with the unread count."""
    assert viewer.user_id is not None
    after = None
    if params.cursor:
        position = decode_cursor(params.cursor)
        try:
            after = (datetime.fromisoformat(str(position["at"])), UUID(str(position["id"])))
        except (KeyError, ValueError):
            raise ValidationFailed("Invalid pagination cursor") from None
    rows = await repository.notifications_page(db, viewer.user_id, after, params.limit + 1)
    items = rows[: params.limit]
    cursor = None
    if len(rows) > params.limit:
        cursor = encode_cursor({"at": items[-1].created_at.isoformat(), "id": str(items[-1].id)})
    return NotificationsPage(
        items=[
            NotificationOut(
                id=n.id,
                kind=n.kind,
                text=n.payload.get("text", ""),
                team_id=n.team_id,
                match_id=_uuid(n.payload.get("match_id")),
                tournament_id=_uuid(n.payload.get("tournament_id")),
                created_at=n.created_at,
                read=n.read_at is not None,
            )
            for n in items
        ],
        next_cursor=cursor,
        unread_count=await repository.unread_count(db, viewer.user_id),
    )


async def mark_read(db: AsyncSession, clock: Clock, viewer: Viewer, ids: list[UUID] | None) -> None:
    assert viewer.user_id is not None
    async with transaction(db):
        await repository.mark_read(db, viewer.user_id, ids, clock.now())


async def add_push_subscription(
    db: AsyncSession, clock: Clock, viewer: Viewer, data: PushSubscriptionIn
) -> None:
    """Remember a browser that allowed notifications."""
    assert viewer.user_id is not None
    async with transaction(db):
        if not await repository.has_push(db, viewer.user_id, data.endpoint):
            db.add(
                PushSubscription(
                    id=new_id(),
                    user_id=viewer.user_id,
                    endpoint=data.endpoint,
                    keys=data.keys.model_dump(),
                    created_at=clock.now(),
                )
            )


NOTIFICATION_RETENTION = timedelta(days=90)


async def purge_notifications(db: AsyncSession, clock: Clock) -> int:
    """Retention (docs/09): notifications are kept 90 days."""
    async with transaction(db):
        return await repository.purge_notifications(db, clock.now() - NOTIFICATION_RETENTION)


async def my_stories(
    db: AsyncSession, viewer: Viewer, params: PageParams, language: str | None
) -> Page[StoryOut]:
    """Stories of the tournaments I follow, directly or through a team or organisation."""
    assert viewer.user_id is not None
    ids: set[UUID] = set()
    for f in await repository.follows_of(db, viewer.user_id):
        if f.target_type == "tournament":
            ids.add(f.target_id)
        elif f.target_type == "team":
            ids |= {t.id for t in await competitions.public_tournaments(db, team_id=f.target_id)}
        elif f.target_type == "organisation":
            ids |= set(await competitions.organisation_tournament_ids(db, f.target_id))
    return await content.list_stories(db, params, tournament_ids=sorted(ids), language=language)


async def me_parts(db: AsyncSession, user_id: UUID) -> MeParts:
    """Follows, "my team" and the unread count for `GET /me`."""
    follows = await repository.follows_of(db, user_id)
    return MeParts(
        follows=[
            FollowRef(
                id=f.id, target_type=f.target_type, target_id=f.target_id, is_primary=f.is_primary
            )
            for f in follows
        ],
        primary_team_id=next((f.target_id for f in follows if f.is_primary), None),
        unread_notifications=await repository.unread_count(db, user_id),
    )
