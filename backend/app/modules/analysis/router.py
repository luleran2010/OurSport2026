"""Fan read endpoints (docs/05-api.md, Fan: browse). Public unless the live access policy
says otherwise; drafts are 404. Every response carries an ETag and Cache-Control."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import RootModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.http_cache import LIVE_MAX_AGE, cached
from app.core.time import Clock, get_clock
from app.core.viewer import CurrentViewer, Member
from app.modules.analysis import reads, service
from app.modules.analysis.schemas import (
    AnalysisPage,
    BracketPage,
    ComparisonPage,
    LivePage,
    MatchList,
    MatchPage,
    MatchPrediction,
    PlayerPage,
    ScenarioPage,
    SchedulePage,
    ScreenPage,
    StandingsPage,
    TeamPage,
    TimelinePage,
    TournamentPage,
    WidgetPage,
)
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import LotsIn

router = APIRouter(tags=["fan"])
Db = Annotated[AsyncSession, Depends(get_session)]
Now = Annotated[Clock, Depends(get_clock)]


def _private(viewer: CurrentViewer) -> bool:
    return viewer.is_member  # a signed-in view may differ (live access), so never shared


@router.get(
    "/tournaments/{tournament_id}", response_model=TournamentPage, operation_id="getTournament"
)
async def tournament(
    tournament_id: UUID, request: Request, viewer: CurrentViewer, db: Db
) -> Response:
    """Tournament, groups, status, fan-visible settings, live-now count."""
    page = await reads.tournament_page(db, viewer, tournament_id)
    return cached(request, page, private=_private(viewer))


@router.get("/tournaments/{tournament_id}/live", response_model=LivePage, operation_id="getLive")
async def live(tournament_id: UUID, request: Request, viewer: CurrentViewer, db: Db) -> Response:
    """All live matches now (scores per the live access policy): the livecast page."""
    page = await reads.live_page(db, viewer, tournament_id)
    return cached(request, page, max_age=LIVE_MAX_AGE, private=_private(viewer))


@router.get(
    "/tournaments/{tournament_id}/standings",
    response_model=StandingsPage,
    operation_id="getStandings",
)
async def standings(
    tournament_id: UUID, request: Request, viewer: CurrentViewer, db: Db
) -> Response:
    """Standings per group."""
    return cached(request, await reads.standings_page(db, viewer, tournament_id))


@router.get(
    "/tournaments/{tournament_id}/bracket", response_model=BracketPage, operation_id="getBracket"
)
async def bracket(tournament_id: UUID, request: Request, viewer: CurrentViewer, db: Db) -> Response:
    """The knockout bracket with placeholders and could-be sets."""
    return cached(request, await reads.bracket_page(db, viewer, tournament_id))


@router.get(
    "/tournaments/{tournament_id}/schedule", response_model=SchedulePage, operation_id="getSchedule"
)
async def schedule(
    tournament_id: UUID,
    request: Request,
    viewer: CurrentViewer,
    db: Db,
    day: Annotated[date | None, Query()] = None,
    pitch_id: Annotated[UUID | None, Query()] = None,
    team_id: Annotated[UUID | None, Query()] = None,
) -> Response:
    """The schedule, filtered by day, pitch or team."""
    page = await reads.schedule_page(
        db, viewer, tournament_id, day=day, pitch_id=pitch_id, team_id=team_id
    )
    return cached(request, page, max_age=LIVE_MAX_AGE, private=_private(viewer))


Scenarios = RootModel[list[ScenarioPage]]


@router.get(
    "/tournaments/{tournament_id}/scenarios",
    response_model=list[ScenarioPage],
    operation_id="getScenarios",
)
async def scenarios(
    tournament_id: UUID,
    request: Request,
    viewer: CurrentViewer,
    db: Db,
    team_id: Annotated[UUID | None, Query()] = None,
) -> Response:
    """What each team needs."""
    return cached(
        request, Scenarios(await reads.scenarios_page(db, viewer, tournament_id, team_id))
    )


@router.get(
    "/tournaments/{tournament_id}/screen", response_model=ScreenPage, operation_id="getScreen"
)
async def screen(tournament_id: UUID, request: Request, viewer: CurrentViewer, db: Db) -> Response:
    """Venue big-screen payload."""
    page = await reads.screen_page(db, viewer, tournament_id)
    return cached(request, page, max_age=LIVE_MAX_AGE, private=_private(viewer))


@router.get(
    "/tournaments/{tournament_id}/widget", response_model=WidgetPage, operation_id="getWidget"
)
async def widget(tournament_id: UUID, request: Request, viewer: CurrentViewer, db: Db) -> Response:
    """Compact embeddable payload."""
    page = await reads.widget_page(db, viewer, tournament_id)
    return cached(request, page, max_age=LIVE_MAX_AGE, private=_private(viewer))


@router.get("/matches/{match_id}", response_model=MatchPage, operation_id="getMatch")
async def match(match_id: UUID, request: Request, viewer: CurrentViewer, db: Db) -> Response:
    """A match with teams, pitch, result and live score (per live access)."""
    page = await reads.match_page(db, viewer, match_id)
    return cached(request, page, max_age=LIVE_MAX_AGE, private=_private(viewer))


@router.get("/matches/{match_id}/timeline", response_model=TimelinePage, operation_id="getTimeline")
async def timeline(
    match_id: UUID,
    request: Request,
    viewer: CurrentViewer,
    db: Db,
    since_seq: Annotated[int, Query(ge=0)] = 0,
) -> Response:
    """Events after `since_seq` (per live access while live; everyone after the finish)."""
    page = await reads.timeline_page(db, viewer, match_id, since_seq)
    return cached(request, page, max_age=LIVE_MAX_AGE, private=_private(viewer))


@router.get("/teams/{team_id}", response_model=TeamPage, operation_id="getTeam")
async def team(team_id: UUID, request: Request, viewer: CurrentViewer, db: Db) -> Response:
    """Team, its tournaments and journeys, fixtures, results and the players this viewer
    may see (so a signed-in view is never shared)."""
    return cached(request, await reads.team_page(db, viewer, team_id), private=_private(viewer))


@router.get(
    "/matches/{match_id}/prediction", response_model=MatchPrediction, operation_id="getPrediction"
)
async def prediction(match_id: UUID, request: Request, viewer: CurrentViewer, db: Db) -> Response:
    """Chances with ranges and the reasons behind them (factors only for juniors)."""
    return cached(request, await reads.prediction_page(db, viewer, match_id))


@router.get(
    "/matches/{match_id}/comparison", response_model=ComparisonPage, operation_id="getComparison"
)
async def comparison(match_id: UUID, request: Request, viewer: CurrentViewer, db: Db) -> Response:
    """The two teams side by side, with previous editions' meetings."""
    page = ComparisonPage.model_validate(await reads.comparison_page(db, viewer, match_id))
    return cached(request, page)


@router.get(
    "/matches/{match_id}/analysis", response_model=AnalysisPage, operation_id="getMatchAnalysis"
)
async def match_analysis(
    match_id: UUID, request: Request, viewer: CurrentViewer, db: Db
) -> Response:
    """What decided the match: comeback, late winner, upset, table and qualification."""
    page = AnalysisPage.model_validate(await reads.analysis_page(db, viewer, match_id))
    return cached(request, page)


When = Literal["live", "today", "upcoming", "recent"]


@router.get("/matches", response_model=MatchList, operation_id="listMatches")
async def list_matches(
    request: Request,
    viewer: CurrentViewer,
    db: Db,
    clock: Now,
    when: Annotated[When | None, Query()] = None,
) -> Response:
    """Matches of every published tournament (scores per live access): the app's feed.
    Poll it (it is cached for 5 s); the tournament WebSocket pushes changes in between."""
    cards = await service.all_matches(db, viewer, clock, when)
    page = MatchList(matches=cards, server_time=clock.now())
    return cached(request, page, max_age=LIVE_MAX_AGE, private=_private(viewer))


@router.get(
    "/organisations/{organisation_id}/matches",
    response_model=MatchList,
    operation_id="listOrganisationMatches",
)
async def organisation_matches(
    organisation_id: UUID,
    request: Request,
    viewer: CurrentViewer,
    db: Db,
    clock: Now,
    when: Annotated[When | None, Query()] = None,
) -> Response:
    """Matches of an organisation's published tournaments."""
    await competitions.organisation_page(db, organisation_id)  # unknown: 404
    cards = await service.organisation_matches(db, viewer, organisation_id, when, clock)
    page = MatchList(matches=cards, server_time=clock.now())
    return cached(request, page, max_age=LIVE_MAX_AGE, private=_private(viewer))


@router.get("/players/{player_id}", response_model=PlayerPage, operation_id="getPlayer")
async def player(player_id: UUID, request: Request, viewer: CurrentViewer, db: Db) -> Response:
    """A player page; 404 for anyone the visibility rules hide the player from."""
    page = await service.player_page(db, viewer, player_id)
    return cached(request, page, private=_private(viewer))


@router.post(
    "/tournaments/{tournament_id}/bracket/resolve-lots",
    response_model=StandingsPage,
    operation_id="resolveLots",
    tags=["organiser"],
)
async def resolve_lots(
    tournament_id: UUID, body: LotsIn, viewer: Member, db: Db, clock: Now
) -> StandingsPage:
    """Record a drawing of lots for teams the tiebreakers leave level, then recompute."""
    return await service.resolve_lots(db, clock, viewer, tournament_id, body.group_id, body.order)
