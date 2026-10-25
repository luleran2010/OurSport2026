"""Competitions endpoints. Public reads arrive with the fan read models (T-033)."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import RootModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.http_cache import cached
from app.core.pagination import Page, PageParams, page_params
from app.core.time import Clock, get_clock
from app.core.viewer import Member
from app.modules.competitions import service
from app.modules.competitions.schemas import (
    AgreementOut,
    ConsentCreate,
    ConsentOut,
    FamilyLinkIn,
    OrganisationCreate,
    OrganisationOut,
    OrganisationPage,
    OrganisationSummary,
    ParticipantData,
    PlayerCreate,
    PlayerOut,
    RosterPlayer,
    SearchResult,
    SeriesPage,
    SettingsPatch,
    SportOut,
    StaffIn,
    StaffOut,
    TeamListItem,
    TeamOut,
    TournamentListItem,
    TournamentOut,
    VisibilityPatch,
)

router = APIRouter(tags=["organisations"])
organiser_router = APIRouter(tags=["organiser"])

Db = Annotated[AsyncSession, Depends(get_session)]
Now = Annotated[Clock, Depends(get_clock)]
Paging = Annotated[PageParams, Depends(page_params)]
SportList = RootModel[list[SportOut]]
TeamList = RootModel[list[TeamOut]]


@router.post(
    "/organisations",
    status_code=201,
    response_model=OrganisationOut,
    operation_id="createOrganisation",
)
async def create_organisation(
    body: OrganisationCreate, viewer: Member, db: Db, clock: Now
) -> OrganisationOut:
    """Create an organisation (first time); requires accepting the processing terms."""
    return await service.create_organisation(db, clock, viewer, body)


@router.get(
    "/organisations/{organisation_id}",
    response_model=OrganisationPage,
    operation_id="getOrganisation",
    tags=["fan"],
)
async def get_organisation(organisation_id: UUID, request: Request, db: Db) -> Response:
    """An organisation and its published tournaments."""
    return cached(request, await service.organisation_page(db, organisation_id))


@router.get(
    "/series/{series_id}", response_model=SeriesPage, operation_id="getSeries", tags=["fan"]
)
async def get_series(series_id: UUID, request: Request, db: Db) -> Response:
    """A tournament series with its published editions."""
    return cached(request, await service.series_page(db, series_id))


@organiser_router.get(
    "/tournaments/{tournament_id}/participants/export",
    response_model=ParticipantData,
    operation_id="exportParticipantData",
)
async def export_participants(
    tournament_id: UUID, viewer: Member, db: Db, clock: Now
) -> ParticipantData:
    """Every team contact, player and consent of the tournament (data requests)."""
    return await service.participant_data(db, clock, viewer, tournament_id)


@organiser_router.post(
    "/tournaments/{tournament_id}/players/{player_id}/erase",
    status_code=204,
    operation_id="erasePlayer",
)
async def erase_player(tournament_id: UUID, player_id: UUID, viewer: Member, db: Db) -> Response:
    """Erase a player's personal data (name, number, birth year, consents, family links)."""
    await service.erase_player(db, viewer, tournament_id, player_id)
    return Response(status_code=204)


@organiser_router.post(
    "/tournaments/{tournament_id}/teams/{team_id}/contact/erase",
    status_code=204,
    operation_id="eraseTeamContact",
)
async def erase_contact(tournament_id: UUID, team_id: UUID, viewer: Member, db: Db) -> Response:
    """Remove a team's contact person details."""
    await service.erase_team_contact(db, viewer, tournament_id, team_id)
    return Response(status_code=204)


@router.post(
    "/organisations/{organisation_id}/processing-agreement",
    status_code=201,
    response_model=AgreementOut,
    operation_id="acceptProcessingAgreement",
)
async def accept_agreement(
    organisation_id: UUID, viewer: Member, db: Db, clock: Now
) -> AgreementOut:
    """Accept the current processing terms (needed before uploading tournament documents)."""
    return await service.accept_processing_agreement(db, clock, viewer, organisation_id)


@organiser_router.get(
    "/tournaments/{tournament_id}/teams/{team_id}/players",
    response_model=list[RosterPlayer],
    operation_id="listRoster",
)
async def roster(tournament_id: UUID, team_id: UUID, viewer: Member, db: Db) -> list[RosterPlayer]:
    """A team's players with visibility and consents (organisers)."""
    return await service.roster(db, viewer, tournament_id, team_id)


@organiser_router.post(
    "/tournaments/{tournament_id}/teams/{team_id}/players",
    status_code=201,
    response_model=PlayerOut,
    operation_id="addRosterPlayer",
)
async def add_player(
    tournament_id: UUID, team_id: UUID, body: PlayerCreate, viewer: Member, db: Db, clock: Now
) -> PlayerOut:
    """Add a player; under-18s start hidden until a guardian consents."""
    return await service.add_roster_player(db, clock, viewer, tournament_id, team_id, body)


@organiser_router.patch(
    "/tournaments/{tournament_id}/players/{player_id}",
    response_model=PlayerOut,
    operation_id="setPlayerVisibility",
)
async def set_visibility(
    tournament_id: UUID, player_id: UUID, body: VisibilityPatch, viewer: Member, db: Db, clock: Now
) -> PlayerOut:
    """Who may see the player (a junior needs the matching consents)."""
    return await service.change_visibility(
        db, clock, viewer, tournament_id, player_id, body.visibility
    )


@organiser_router.post(
    "/tournaments/{tournament_id}/players/{player_id}/consents",
    status_code=201,
    response_model=ConsentOut,
    operation_id="recordConsent",
)
async def add_consent(
    tournament_id: UUID, player_id: UUID, body: ConsentCreate, viewer: Member, db: Db, clock: Now
) -> ConsentOut:
    """Record a guardian's consent (`profile`, `stats`, `filming`)."""
    return await service.add_consent(db, clock, viewer, tournament_id, player_id, body)


@organiser_router.post(
    "/tournaments/{tournament_id}/consents/{consent_id}/withdraw",
    response_model=PlayerOut,
    operation_id="withdrawConsent",
)
async def withdraw_consent(
    tournament_id: UUID, consent_id: UUID, viewer: Member, db: Db, clock: Now
) -> PlayerOut:
    """Withdraw a consent: visibility drops at once and content naming the player is
    refreshed."""
    return await service.remove_consent(db, clock, viewer, tournament_id, consent_id)


@organiser_router.post(
    "/tournaments/{tournament_id}/players/{player_id}/family-links",
    status_code=204,
    operation_id="linkGuardian",
)
async def link_guardian(
    tournament_id: UUID, player_id: UUID, body: FamilyLinkIn, viewer: Member, db: Db, clock: Now
) -> Response:
    """Link a guardian's OurSport account to the player."""
    await service.link_guardian(db, clock, viewer, tournament_id, player_id, str(body.email))
    return Response(status_code=204)


# --- catalogue, search and organisation teams (T-066) ---------------------------------------


@router.get("/sports", response_model=list[SportOut], operation_id="listSports", tags=["fan"])
async def list_sports(request: Request, db: Db) -> Response:
    """The sports OurSport runs."""
    return cached(request, SportList(await service.list_sports(db)))


@router.get(
    "/organisations",
    response_model=Page[OrganisationSummary],
    operation_id="listOrganisations",
    tags=["fan"],
)
async def list_organisations(
    request: Request,
    db: Db,
    paging: Paging,
    sport: Annotated[str | None, Query(max_length=20)] = None,
) -> Response:
    """Every organisation (clubs, associations, communities), by name."""
    return cached(request, await service.list_organisations(db, paging, sport))


@router.get(
    "/tournaments",
    response_model=Page[TournamentListItem],
    operation_id="listTournaments",
    tags=["fan"],
)
async def list_tournaments(
    request: Request,
    db: Db,
    paging: Paging,
    organisation_id: Annotated[UUID | None, Query()] = None,
    sport: Annotated[str | None, Query(max_length=20)] = None,
    status: Annotated[Literal["upcoming", "active", "finished"] | None, Query()] = None,
) -> Response:
    """Published tournaments, newest first."""
    page = await service.list_tournaments(
        db, paging, organisation_id=organisation_id, sport=sport, status=status
    )
    return cached(request, page)


@router.get("/teams", response_model=Page[TeamListItem], operation_id="listTeams", tags=["fan"])
async def list_teams(
    request: Request,
    db: Db,
    paging: Paging,
    tournament_id: Annotated[UUID | None, Query()] = None,
    organisation_id: Annotated[UUID | None, Query()] = None,
) -> Response:
    """Teams of published tournaments, by name."""
    page = await service.list_teams(
        db, paging, tournament_id=tournament_id, organisation_id=organisation_id
    )
    return cached(request, page)


@router.get(
    "/organisations/{organisation_id}/teams",
    response_model=list[TeamOut],
    operation_id="listOrganisationTeams",
    tags=["fan"],
)
async def organisation_teams(organisation_id: UUID, request: Request, db: Db) -> Response:
    """An organisation's teams (no contact details)."""
    return cached(request, TeamList(await service.organisation_teams(db, organisation_id)))


@router.get("/search", response_model=SearchResult, operation_id="search", tags=["fan"])
async def search(
    request: Request,
    db: Db,
    q: Annotated[str, Query(min_length=2, max_length=80)],
    type: Annotated[Literal["organisation", "tournament", "team", "player"] | None, Query()] = None,
    sport: Annotated[str | None, Query(max_length=20)] = None,
    region: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> Response:
    """Organisations, published tournaments, their teams and public players by name."""
    return cached(request, await service.search(db, q, type, sport, region, limit))


@organiser_router.patch(
    "/tournaments/{tournament_id}",
    response_model=TournamentOut,
    operation_id="changeTournamentSettings",
)
async def change_settings(
    tournament_id: UUID, body: SettingsPatch, viewer: Member, db: Db
) -> TournamentOut:
    """Fan-facing settings: languages, live access, probabilities, filming policy."""
    return await service.change_settings(db, viewer, tournament_id, body)


@organiser_router.get(
    "/tournaments/{tournament_id}/staff", response_model=list[StaffOut], operation_id="listStaff"
)
async def list_staff(tournament_id: UUID, viewer: Member, db: Db) -> list[StaffOut]:
    """The tournament's owners, organisers and scorers."""
    return await service.list_staff(db, viewer, tournament_id)


@organiser_router.post(
    "/tournaments/{tournament_id}/staff",
    status_code=201,
    response_model=StaffOut,
    operation_id="addStaff",
)
async def add_staff(tournament_id: UUID, body: StaffIn, viewer: Member, db: Db) -> StaffOut:
    """Make an existing account an organiser or scorer of the tournament."""
    return await service.invite_staff(db, viewer, tournament_id, body)


@organiser_router.delete(
    "/tournaments/{tournament_id}/staff/{user_id}", status_code=204, operation_id="removeStaff"
)
async def remove_staff(tournament_id: UUID, user_id: UUID, viewer: Member, db: Db) -> Response:
    """Take someone off the tournament staff (never the owner)."""
    await service.remove_staff(db, viewer, tournament_id, user_id)
    return Response(status_code=204)
