"""Story and announcement endpoints (docs/05-api.md). Stories are public read models with
the AI label; announcement drafts are for the tournament's organisers."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import RootModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.http_cache import cached
from app.core.pagination import Page, PageParams, page_params
from app.core.time import Clock, get_clock
from app.core.viewer import CurrentViewer, Member
from app.modules.content import cards, commentary, service
from app.modules.content.schemas import (
    AnnouncementOut,
    CommentaryOut,
    ScreenRotation,
    StoryDetail,
    StoryOut,
)

router = APIRouter(tags=["fan"])
organiser_router = APIRouter(tags=["organiser"])
Db = Annotated[AsyncSession, Depends(get_session)]
Now = Annotated[Clock, Depends(get_clock)]
Lang = Annotated[Literal["fi", "en", "bn"] | None, Query()]
Stories = RootModel[list[StoryOut]]
Paging = Annotated[PageParams, Depends(page_params)]


@router.get(
    "/tournaments/{tournament_id}/stories",
    response_model=list[StoryOut],
    operation_id="getTournamentStories",
)
async def tournament_stories(
    tournament_id: UUID, request: Request, viewer: CurrentViewer, db: Db, lang: Lang = None
) -> Response:
    """Published stories of a tournament, newest first (every language unless `lang`)."""
    stories = await service.tournament_stories(db, viewer, tournament_id, lang)
    return cached(request, Stories(stories))


@router.get(
    "/matches/{match_id}/stories", response_model=list[StoryOut], operation_id="getMatchStories"
)
async def match_stories(
    match_id: UUID,
    request: Request,
    viewer: CurrentViewer,
    db: Db,
    kind: Annotated[Literal["preview", "report"] | None, Query()] = None,
    lang: Lang = None,
) -> Response:
    """Preview and report of a match."""
    stories = await service.match_stories(db, viewer, match_id, kind, lang)
    return cached(request, Stories(stories))


@router.get(
    "/matches/{match_id}/commentary",
    response_model=list[CommentaryOut],
    operation_id="getMatchCommentary",
)
async def match_commentary(match_id: UUID, viewer: CurrentViewer, db: Db) -> list[CommentaryOut]:
    """Live commentary lines, newest first (live access policy while the match is live;
    new lines also arrive on the match socket as `commentary` messages)."""
    return await commentary.match_commentary(db, viewer, match_id)


@router.get("/stories/{story_id}", response_model=StoryDetail, operation_id="getStory")
async def story(story_id: UUID, request: Request, viewer: CurrentViewer, db: Db) -> Response:
    """A story with the facts behind each sentence (the "Why?" view)."""
    return cached(request, await service.story(db, viewer, story_id))


@organiser_router.get(
    "/tournaments/{tournament_id}/announcements",
    response_model=list[AnnouncementOut],
    operation_id="listAnnouncements",
)
async def announcements(tournament_id: UUID, viewer: Member, db: Db) -> list[AnnouncementOut]:
    """Auto-drafted announcements (all languages) and the ones already sent."""
    return await service.list_announcements(db, viewer, tournament_id)


@organiser_router.post(
    "/tournaments/{tournament_id}/announcements/{announcement_id}/send",
    response_model=AnnouncementOut,
    operation_id="sendAnnouncementDraft",
)
async def send(
    tournament_id: UUID, announcement_id: UUID, request: Request, viewer: Member, db: Db, clock: Now
) -> AnnouncementOut:
    """Send a draft to the live page and venue screen in one tap."""
    return await service.send_announcement(
        db, clock, viewer, tournament_id, announcement_id, request.app.state.live
    )


SVG = "image/svg+xml"


@router.get(
    "/cards/matches/{match_id}.svg",
    response_class=Response,
    responses={200: {"content": {SVG: {}}}},
    operation_id="getMatchCard",
)
async def match_card(match_id: UUID, viewer: CurrentViewer, db: Db) -> Response:
    """A 1200×630 share image of the match (teams, score or kick-off)."""
    svg = await cards.match_card(db, viewer, match_id)
    return Response(svg, media_type=SVG, headers={"Cache-Control": "public, max-age=30"})


@router.get(
    "/cards/stories/{story_id}.svg",
    response_class=Response,
    responses={200: {"content": {SVG: {}}}},
    operation_id="getStoryCard",
)
async def story_card(story_id: UUID, viewer: CurrentViewer, db: Db) -> Response:
    """A 1200×630 share image of a story, with its AI label."""
    svg = await cards.story_card(db, viewer, story_id)
    return Response(svg, media_type=SVG, headers={"Cache-Control": "public, max-age=300"})


@router.get(
    "/tournaments/{tournament_id}/screen/rotation",
    response_model=ScreenRotation,
    operation_id="getScreenRotation",
)
async def screen_rotation(
    tournament_id: UUID, request: Request, viewer: CurrentViewer, db: Db, clock: Now
) -> Response:
    """The venue screen's timed panels (live, commentary, next up, tables, announcements)."""
    rotation = await cards.screen_rotation(db, clock, viewer, tournament_id)
    return cached(request, rotation, max_age=5)


@router.get("/stories", response_model=Page[StoryOut], operation_id="listStories")
async def list_stories(
    request: Request,
    db: Db,
    paging: Paging,
    tournament_id: Annotated[UUID | None, Query()] = None,
    lang: Lang = None,
) -> Response:
    """Published stories of every tournament (or one), newest first: the public news feed."""
    ids = [tournament_id] if tournament_id else None
    page = await service.list_stories(db, paging, tournament_ids=ids, language=lang)
    return cached(request, page)


@router.get(
    "/organisations/{organisation_id}/stories",
    response_model=Page[StoryOut],
    operation_id="listOrganisationStories",
)
async def organisation_stories(
    organisation_id: UUID, request: Request, db: Db, paging: Paging, lang: Lang = None
) -> Response:
    """Published stories of an organisation's tournaments, newest first."""
    return cached(request, await service.organisation_stories(db, organisation_id, paging, lang))
