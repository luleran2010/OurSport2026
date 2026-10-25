"""Personal endpoints (docs/05-api.md, Fan: personal). Signed-in members only, except the
public tournament feed."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.http_cache import cached
from app.core.pagination import Page, PageParams, page_params
from app.core.time import Clock, get_clock
from app.core.viewer import CurrentViewer, Member
from app.modules.analysis.schemas import TeamHub
from app.modules.audience import service
from app.modules.audience.schemas import (
    Feed,
    FollowIn,
    FollowOut,
    Home,
    MarkRead,
    NotificationsPage,
    NotifyPatch,
    PushSubscriptionIn,
)
from app.modules.content.schemas import StoryOut

router = APIRouter(tags=["me"])
public_router = APIRouter(tags=["fan"])
Db = Annotated[AsyncSession, Depends(get_session)]
Now = Annotated[Clock, Depends(get_clock)]
Paging = Annotated[PageParams, Depends(page_params)]


def _private(request: Request, payload: BaseModel) -> Response:
    return cached(request, payload, private=True)


@router.get("/me/home", response_model=Home, operation_id="getMyHome")
async def my_home(request: Request, viewer: Member, db: Db) -> Response:
    """My Team hub: my team first, then everything I follow."""
    return _private(request, await service.home(db, viewer))


@router.get("/me/teams/{team_id}/hub", response_model=TeamHub, operation_id="getTeamHub")
async def team_hub(
    team_id: UUID,
    request: Request,
    viewer: Member,
    db: Db,
    tournament_id: Annotated[UUID | None, Query()] = None,
) -> Response:
    """The hub of any team (usually one I follow)."""
    return _private(request, await service.team_hub(db, viewer, team_id, tournament_id))


@router.get("/me/feed", response_model=Feed, operation_id="getMyFeed")
async def my_feed(request: Request, viewer: Member, db: Db, paging: Paging) -> Response:
    """Results, live matches and next matches of everything I follow."""
    return _private(request, await service.feed(db, viewer, paging))


@router.get("/me/follows", response_model=list[FollowOut], operation_id="listFollows")
async def list_follows(viewer: Member, db: Db) -> list[FollowOut]:
    return await service.list_follows(db, viewer)


@router.post("/me/follows", status_code=201, response_model=FollowOut, operation_id="follow")
async def follow(body: FollowIn, viewer: Member, db: Db, clock: Now) -> FollowOut:
    """Follow a team, tournament, organisation or series (`is_primary`: my team)."""
    return await service.follow(db, clock, viewer, body)


@router.delete("/me/follows/{follow_id}", status_code=204, operation_id="unfollow")
async def unfollow(follow_id: UUID, viewer: Member, db: Db) -> Response:
    await service.unfollow(db, viewer, follow_id)
    return Response(status_code=204)


@router.patch(
    "/me/follows/{follow_id}/notifications",
    response_model=FollowOut,
    operation_id="setFollowNotifications",
)
async def set_notifications(
    follow_id: UUID, body: NotifyPatch, viewer: Member, db: Db
) -> FollowOut:
    """Turn notification kinds on or off for one follow."""
    return await service.set_notifications(db, viewer, follow_id, body)


@public_router.get(
    "/tournaments/{tournament_id}/feed", response_model=Feed, operation_id="getTournamentFeed"
)
async def tournament_feed(
    tournament_id: UUID, request: Request, viewer: CurrentViewer, db: Db, paging: Paging
) -> Response:
    """Results and live matches of a tournament, newest first."""
    return cached(request, await service.public_feed(db, viewer, tournament_id, paging), max_age=5)


@router.get("/me/notifications", response_model=NotificationsPage, operation_id="listNotifications")
async def notifications(request: Request, viewer: Member, db: Db, paging: Paging) -> Response:
    """My newest notifications, a page at a time, with the unread count."""
    return _private(request, await service.my_notifications(db, viewer, paging))


@router.get("/me/stories", response_model=Page[StoryOut], operation_id="listMyStories")
async def my_stories(
    request: Request,
    viewer: Member,
    db: Db,
    paging: Paging,
    lang: Annotated[Literal["fi", "en", "bn"] | None, Query()] = None,
) -> Response:
    """Stories of everything I follow, newest first: my news feed."""
    return _private(request, await service.my_stories(db, viewer, paging, lang))


@router.post("/me/notifications/read", status_code=204, operation_id="markNotificationsRead")
async def mark_read(body: MarkRead, viewer: Member, db: Db, clock: Now) -> Response:
    await service.mark_read(db, clock, viewer, body.ids)
    return Response(status_code=204)


@router.post("/me/push-subscriptions", status_code=204, operation_id="addPushSubscription")
async def add_push(body: PushSubscriptionIn, viewer: Member, db: Db, clock: Now) -> Response:
    """Register this browser for web push."""
    await service.add_push_subscription(db, clock, viewer, body)
    return Response(status_code=204)
