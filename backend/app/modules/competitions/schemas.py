"""Competitions schemas: API bodies and the typed `tournaments.settings` payload."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Visibility = Literal["public", "family_only", "hidden"]
ConsentScope = Literal["profile", "stats", "filming"]
AgeGroup = Literal[
    "adult", "u19", "u18", "u17", "u16", "u15", "u14", "u13", "u12", "u11", "u10", "u9"
]
StaffRole = Literal["owner", "organiser", "scorer"]
LiveAccess = Literal["public", "members", "premium"]
FilmingPolicy = Literal["allowed", "notice", "consent_required", "not_allowed"]


class TournamentSettings(BaseModel):
    """`tournaments.settings` (JSONB). Defaults depend on the age group (see the service)."""

    model_config = ConfigDict(extra="forbid")

    languages: list[Literal["fi", "en", "bn"]] = ["fi", "en"]
    show_probabilities: bool = True
    live_access: LiveAccess = "public"
    publisher_review: bool = True
    filming_policy: FilmingPolicy = "notice"
    filming_confirmed: bool = False  # the organiser chose the policy (required to publish)


class OrganisationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["club", "association", "school", "community"]
    name: str = Field(min_length=2, max_length=120)
    town: str | None = Field(default=None, max_length=80)
    sports: list[Literal["football", "futsal", "ice_hockey"]] = Field(min_length=1)
    # OurSport processes the participant data the organisation uploads (docs/13).
    accept_processing_terms: Literal[True]


class OrganisationOut(BaseModel):
    id: UUID
    kind: str
    name: str
    slug: str
    town: str | None
    sports: list[str]


class TournamentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organisation_id: UUID
    name: str = Field(min_length=2, max_length=120)
    sport: Literal["football", "futsal", "ice_hockey"]
    age_group: AgeGroup = "adult"
    time_zone: str = "Europe/Helsinki"
    starts_on: date | None = None
    ends_on: date | None = None
    series_id: UUID | None = None
    edition_label: str | None = None
    settings: TournamentSettings | None = None  # None: defaults for the age group


class TournamentOut(BaseModel):
    id: UUID
    organisation_id: UUID
    name: str
    slug: str
    sport: str
    status: str
    age_group: str
    is_junior: bool
    time_zone: str
    starts_on: date | None
    ends_on: date | None
    settings: TournamentSettings


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    short_name: str | None = Field(default=None, max_length=20)
    age_group: AgeGroup = "adult"
    organisation_id: UUID | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class TeamOut(BaseModel):
    id: UUID
    name: str
    short_name: str | None
    age_group: str
    organisation_id: UUID | None


class TeamContacts(BaseModel):
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None


class TeamDetail(TeamOut):
    contacts: TeamContacts | None = None  # tournament staff only


class PlayerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=80)
    shirt_number: int | None = Field(default=None, ge=0, le=999)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    visibility: Visibility | None = None  # None: the default for the player's age


class PlayerOut(BaseModel):
    id: UUID
    team_id: UUID
    display_name: str
    shirt_number: int | None
    visibility: Visibility


class ConsentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: ConsentScope
    guardian_contact: str = Field(min_length=3, max_length=254)
    guardian_user_id: UUID | None = None


class TeamEntry(BaseModel):
    """A team to enter at publish; `key` is the setup draft's id for it."""

    key: str
    name: str
    short_name: str | None = None
    organisation_name: str | None = None
    group: str | None = None  # "A"
    seed: int | None = None
    pot: int | None = None
    seeding_reason: dict[str, object] | None = None


class MatchEntry(BaseModel):
    code: str
    stage: str
    group: str | None = None
    round: int | None = None
    home_key: str | None = None
    away_key: str | None = None
    home_source: str | None = None
    away_source: str | None = None
    pitch: str
    starts_at: datetime


class TournamentStructure(BaseModel):
    format_spec: dict[str, object]
    policy_catalogue_version: int
    venue_name: str
    pitches: list[str]  # first = main pitch
    groups: list[str]
    teams: list[TeamEntry]
    matches: list[MatchEntry]


class MatchOut(BaseModel):
    id: UUID
    tournament_id: UUID
    code: str
    stage: str
    group_id: UUID | None
    home_team_id: UUID | None
    away_team_id: UUID | None
    home_source: str | None
    away_source: str | None
    pitch_id: UUID | None
    starts_at: datetime
    status: str
    result: dict[str, object] | None
    data_level: str = "events"
    last_seq: int = 0


class GroupOut(BaseModel):
    id: UUID
    name: str
    order: int


class EntryOut(BaseModel):
    """A team entered in a tournament."""

    team_id: UUID
    name: str
    short_name: str | None
    group_id: UUID | None
    seed: int | None
    pot: int | None
    withdrawn: bool
    seed_reason: dict[str, object] | None = None


class PitchOut(BaseModel):
    id: UUID
    name: str
    is_main: bool


class OrganisationColors(BaseModel):
    primary: str | None = None  # "#1d4ed8"
    secondary: str | None = None


class OrganisationSummary(BaseModel):
    """An organisation in lists and search (no contacts)."""

    id: UUID
    name: str
    slug: str
    kind: str
    town: str | None
    sports: list[str]
    logo_url: str | None = None
    colors: OrganisationColors | None = None


class OrganisationPage(OrganisationSummary):
    sponsors: list[dict[str, object]] = []
    tournaments: list[TournamentOut]


class SportOut(BaseModel):
    code: str  # "football", "futsal"
    name: str


class TournamentListItem(TournamentOut):
    organisation_name: str
    team_count: int


class TeamListItem(TeamOut):
    """A team of a published tournament, with where it plays."""

    sports: list[str]
    tournament_ids: list[UUID]  # published tournaments, newest first


class SeriesPage(BaseModel):
    id: UUID
    name: str
    slug: str
    sport: str
    editions: list[TournamentOut]


class MatchMove(BaseModel):
    code: str
    starts_at: datetime
    pitch: str  # pitch name


class ScheduleUpdate(BaseModel):
    """A confirmed reschedule: moved matches and walkovers (code -> result)."""

    moves: list[MatchMove]
    walkovers: dict[str, dict[str, object]] = {}
    withdrawn_team_ids: list[UUID] = []


class ParticipantConsent(BaseModel):
    scope: str
    guardian_contact: str
    granted_at: datetime
    withdrawn_at: datetime | None


class ParticipantPlayer(BaseModel):
    id: UUID
    display_name: str
    shirt_number: int | None
    birth_year: int | None
    visibility: str
    consents: list[ParticipantConsent]


class ParticipantTeam(BaseModel):
    id: UUID
    name: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    players: list[ParticipantPlayer]


class ParticipantData(BaseModel):
    """A tournament's participant data, for the organiser's data requests (GDPR)."""

    tournament_id: UUID
    generated_at: datetime
    teams: list[ParticipantTeam]


class AgreementOut(BaseModel):
    organisation_id: UUID
    version: str
    accepted_at: datetime


class ConsentOut(BaseModel):
    id: UUID
    scope: str
    guardian_contact: str
    granted_at: datetime
    withdrawn_at: datetime | None


class RosterPlayer(PlayerOut):
    """A player as the tournament's organisers see them."""

    birth_year: int | None
    consents: list[ConsentOut]


class VisibilityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Visibility


class FamilyLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr  # the guardian's OurSport account


class FilmingPlayer(BaseModel):
    """What the filming check needs about a player (never served to fans)."""

    player_id: UUID
    team_id: UUID
    is_junior: bool
    filming_consent: bool


class SearchHit(BaseModel):
    type: Literal["organisation", "tournament", "team", "player"]
    id: UUID
    name: str
    detail: str | None = None  # town, sport, team of a player


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit]


class SettingsPatch(BaseModel):
    """Fan-facing settings an organiser may change after publishing."""

    model_config = ConfigDict(extra="forbid")

    languages: list[Literal["fi", "en", "bn"]] | None = Field(default=None, min_length=1)
    live_access: LiveAccess | None = None
    show_probabilities: bool | None = None
    filming_policy: FilmingPolicy | None = None
    publisher_review: bool | None = None


class StaffIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr  # the person's OurSport account
    role: Literal["organiser", "scorer"]


class StaffOut(BaseModel):
    user_id: UUID
    display_name: str
    role: str


class LotsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: UUID
    order: list[UUID] = Field(min_length=2)  # team ids as drawn, first drawn first
