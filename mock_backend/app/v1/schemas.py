"""The OurSport API v1 contract as the real backend serves it (backend/docs/frontend-handoff/
openapi.json). snake_case, UUID strings, ISO 8601 UTC timestamps, `YYYY-MM-DD` dates.

Keep every model here field-for-field equal to the backend's; `tests/test_contract.py` compares
the mock's OpenAPI with the backend's for every operation the mock serves.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["fi", "en", "bn"]


# ---- auth and me (accounts) ------------------------------------------------------------------


class FollowTargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid", title="FollowTarget-Input")

    target_type: Literal["team", "tournament", "organisation"]
    target_id: str


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=80)
    language: Language
    time_zone: str
    age_13_plus: Literal[True]
    privacy_accepted: Literal[True]
    follow: FollowTargetIn | None = None


class MagicLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=200)


class DemoLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: Literal["fan", "organiser", "editor"] = "fan"


class Accepted(BaseModel):
    status: Literal["accepted"] = "accepted"


class SessionInfo(BaseModel):
    user_id: str
    csrf_token: str
    account_created: bool = False


class PlanInfo(BaseModel):
    tier: str
    granted_by_organisation_id: str | None = None
    valid_until: str | None = None


class Membership(BaseModel):
    organisation_id: str
    organisation_name: str = ""
    role: str


class StaffTournament(BaseModel):
    tournament_id: str
    tournament_name: str = ""
    organisation_id: str | None = None
    role: str


class FollowRef(BaseModel):
    id: str
    target_type: str
    target_id: str
    is_primary: bool = False


class Preferences(BaseModel):
    analytics_cookies: bool = False
    marketing_emails: bool = False
    updated_at: datetime | None = None


class PreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analytics_cookies: bool | None = None
    marketing_emails: bool | None = None


class Me(BaseModel):
    id: str
    display_name: str
    email: str
    language: Language
    time_zone: str
    plan: PlanInfo | None = None
    memberships: list[Membership] = []
    staff_tournaments: list[StaffTournament] = []
    global_roles: list[str] = []
    primary_team_id: str | None = None
    family_player_ids: list[str] = []
    follows: list[FollowRef] = []
    unread_notifications: int = 0
    preferences: Preferences = Preferences()


class MePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    language: Language | None = None
    time_zone: str | None = None
    preferences: PreferencesPatch | None = None


# ---- catalogue (competitions) ------------------------------------------------------------------


class SportOut(BaseModel):
    code: str
    name: str


class OrganisationColors(BaseModel):
    primary: str | None = None
    secondary: str | None = None


class OrganisationSummary(BaseModel):
    id: str
    name: str
    slug: str
    kind: str
    town: str | None
    sports: list[str]
    logo_url: str | None = None
    colors: OrganisationColors | None = None


class TournamentSettings(BaseModel):
    languages: list[Language] = ["fi", "en"]
    show_probabilities: bool = True
    live_access: Literal["public", "members", "premium"] = "public"
    publisher_review: bool = True
    filming_policy: Literal["allowed", "notice", "consent_required", "not_allowed"] = "notice"
    filming_confirmed: bool = False


class TournamentOut(BaseModel):
    id: str
    organisation_id: str
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


class TournamentListItem(TournamentOut):
    organisation_name: str
    team_count: int


class OrganisationPage(OrganisationSummary):
    sponsors: list[dict[str, Any]] = []
    tournaments: list[TournamentOut]


class TeamOut(BaseModel):
    id: str
    name: str
    short_name: str | None
    age_group: str
    organisation_id: str | None


class TeamListItem(TeamOut):
    sports: list[str]
    tournament_ids: list[str]


class SearchHit(BaseModel):
    type: Literal["organisation", "tournament", "team", "player"]
    id: str
    name: str
    detail: str | None = None


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit]


class PageOrganisations(BaseModel):
    model_config = ConfigDict(title="Page[OrganisationSummary]")

    items: list[OrganisationSummary]
    next_cursor: str | None


class PageTournaments(BaseModel):
    model_config = ConfigDict(title="Page[TournamentListItem]")

    items: list[TournamentListItem]
    next_cursor: str | None


class PageTeams(BaseModel):
    model_config = ConfigDict(title="Page[TeamListItem]")

    items: list[TeamListItem]
    next_cursor: str | None


# ---- fan reads (analysis) ----------------------------------------------------------------------


class TeamName(BaseModel):
    id: str
    name: str
    short_name: str | None = None


class GroupPage(BaseModel):
    id: str
    name: str
    teams: list[TeamName]


class TournamentPage(BaseModel):
    id: str
    name: str
    slug: str
    sport: str
    status: str
    age_group: str
    starts_on: date | None
    ends_on: date | None
    time_zone: str
    languages: list[str]
    live_access: str
    show_probabilities: bool
    groups: list[GroupPage]
    live_now: int
    organisation_id: str
    organisation_name: str
    is_junior: bool


class Score(BaseModel):
    home_goals: int
    away_goals: int
    period: int | None = None
    finished: bool = False


class MatchCard(BaseModel):
    id: str
    tournament_id: str
    sport: str
    code: str
    stage: str
    group: str | None
    pitch: str | None
    starts_at: datetime
    status: str
    home: TeamName | None
    away: TeamName | None
    home_source: str | None
    away_source: str | None
    score: Score | None
    data_level: str = "events"


class StandingsRow(BaseModel):
    position: int
    team: TeamName
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int
    form: list[str]
    tied_unresolved: bool
    status: Literal["through", "out", "alive"] = "alive"


class GroupTable(BaseModel):
    group: str
    group_id: str | None = None
    rows: list[StandingsRow]


class StandingsPage(BaseModel):
    version: int
    groups: list[GroupTable]


class ScenarioPage(BaseModel):
    team: TeamName
    scenario: dict[str, Any]


class SchedulePage(BaseModel):
    matches: list[MatchCard]


class LivePage(BaseModel):
    matches: list[MatchCard]


class MatchList(BaseModel):
    matches: list[MatchCard]
    server_time: datetime


class MatchPage(BaseModel):
    match: MatchCard
    tournament_id: str
    live_access: bool


class TimelinePage(BaseModel):
    events: list[dict[str, Any]]


class HubPlayer(BaseModel):
    id: str
    display_name: str
    shirt_number: int | None


class TeamPage(BaseModel):
    id: str
    name: str
    short_name: str | None
    tournaments: list[dict[str, Any]]
    matches: list[MatchCard]
    organisation_id: str | None = None
    age_group: str = "adult"
    players: list[HubPlayer] = []


class PlayerPage(BaseModel):
    id: str
    display_name: str
    shirt_number: int | None
    team: TeamName
    goals: int
    tournaments: list[dict[str, Any]]


class RulesSummary(BaseModel):
    tournament_id: str
    version: int
    language: Language
    lines: list[str]


class LiveToken(BaseModel):
    token: str
    expires_at: datetime
    scope: str


# ---- content ---------------------------------------------------------------------------------


class StoryOut(BaseModel):
    id: str
    tournament_id: str | None = None
    kind: str
    subject_type: str
    subject_id: str
    language: str
    headline: str
    body: str
    author_type: str
    ai_label: str | None
    published_at: datetime | None
    corrected_at: datetime | None
    version: int


class StoryFact(BaseModel):
    id: str
    claim: str


class StoryDetail(StoryOut):
    sentences: list[dict[str, Any]]
    facts: list[StoryFact]


class PageStories(BaseModel):
    model_config = ConfigDict(title="Page[StoryOut]")

    items: list[StoryOut]
    next_cursor: str | None


class CommentaryLine(BaseModel):
    language: str
    text: str
    fact_ids: list[str]


class CommentaryOut(BaseModel):
    id: str
    match_id: str
    seq: int
    kind: str
    moments: list[str]
    items: list[CommentaryLine]
    author_type: str
    ai_labels: dict[str, str] | None
    created_at: datetime


class CorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["mistake", "privacy", "illegal", "other"] = "mistake"
    text: str = Field(min_length=5, max_length=2000)


class CorrectionOut(BaseModel):
    id: str
    tournament_id: str
    story_id: str
    kind: str
    text: str
    status: str
    note: str | None
    created_at: datetime
    resolved_at: datetime | None


# ---- audience --------------------------------------------------------------------------------

TargetType = Literal["organisation", "team", "tournament", "series"]


class FollowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: TargetType
    target_id: str
    is_primary: bool = False


class FollowTarget(BaseModel):
    model_config = ConfigDict(title="FollowTarget-Output")

    name: str
    short_name: str | None = None
    subtitle: str | None = None
    sport: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None


class FollowOut(BaseModel):
    id: str
    target_type: TargetType
    target_id: str
    is_primary: bool
    notify: dict[str, bool]
    created_at: datetime
    target: FollowTarget | None = None


class NotifyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_start: bool | None = None
    goal: bool | None = None
    result: bool | None = None
    scenario_change: bool | None = None
    relevance: bool | None = None
    schedule_change: bool | None = None
    next_opponent: bool | None = None
    news: bool | None = None


class NotificationOut(BaseModel):
    id: str
    kind: str
    text: str
    team_id: str | None
    match_id: str | None = None
    tournament_id: str | None = None
    created_at: datetime
    read: bool


class NotificationsPage(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None
    unread_count: int


class MarkRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] | None = None


# ---- scoring ---------------------------------------------------------------------------------


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_seq: int = Field(ge=1)
    type: str
    payload: dict[str, Any] = {}
    team_id: str | None = None
    player_id: str | None = None
    clock: str | None = Field(default=None, max_length=10)


class UndoIn(BaseModel):
    client_seq: int = Field(ge=1)


class LiveScore(BaseModel):
    home_goals: int
    away_goals: int
    period: int
    finished: bool
    home_shootout: int = 0
    away_shootout: int = 0


class EventAccepted(BaseModel):
    seq: int
    duplicate: bool
    live: LiveScore
    moments: list[str]


class FinishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_goals: int = Field(ge=0)
    away_goals: int = Field(ge=0)


class ResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_goals: int = Field(ge=0)
    away_goals: int = Field(ge=0)
    decided_by: Literal["regulation", "extra_time", "penalties"] = "regulation"
    home_penalties: int | None = Field(default=None, ge=0)
    away_penalties: int | None = Field(default=None, ge=0)


class MatchStatus(BaseModel):
    match_id: str
    status: str
    result: dict[str, Any] | None = None


class ScorerTeam(BaseModel):
    id: str
    name: str
    short_name: str | None = None


class ScorerMatch(BaseModel):
    match_id: str
    code: str
    starts_at: datetime
    status: str
    home_team_id: str | None
    away_team_id: str | None
    tournament_id: str
    tournament_name: str
    sport: str
    stage: str
    pitch: str | None
    home: ScorerTeam | None
    away: ScorerTeam | None
    data_level: str
    events_recorded: int
    last_event_at: datetime | None


class EventPadButton(BaseModel):
    id: str
    type: str
    label: str
    group: Literal["score", "play", "discipline", "control"]
    team: bool
    player: Literal["required", "optional", "none"] = "none"
    player_prompt: str | None = None
    points: int = 0
    follow_up: str | None = None
    payload: dict[str, Any] = {}
    knockout_only: bool = False


class EventPad(BaseModel):
    sport: str
    clock: bool
    periods: list[str]
    score_label: str
    event_types: list[str]
    buttons: list[EventPadButton]


class ScoredEvent(BaseModel):
    seq: int
    client_seq: int
    type: str
    team_id: str | None
    player_id: str | None
    period: int | None
    clock: str | None
    payload: dict[str, Any]
    undone: bool
    undoes_seq: int | None
    created_at: datetime


class ScorerRosterPlayer(BaseModel):
    id: str
    display_name: str
    shirt_number: int | None


class ScoringState(BaseModel):
    match_id: str
    tournament_id: str
    sport: str
    code: str
    stage: str
    status: str
    data_level: str
    starts_at: datetime
    pitch: str | None
    home: ScorerTeam
    away: ScorerTeam
    score: LiveScore
    period: int
    periods: int
    period_minutes: int | None
    between_periods: bool
    home_roster: list[ScorerRosterPlayer]
    away_roster: list[ScorerRosterPlayer]
    events: list[ScoredEvent]
    last_client_seq: int
    role: Literal["scorer", "organiser"]
    server_time: datetime
