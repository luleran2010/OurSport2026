"""Fan read models as served (docs/05-api.md, Fan: browse)."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class TeamName(BaseModel):
    id: UUID
    name: str
    short_name: str | None = None


class GroupPage(BaseModel):
    id: UUID
    name: str
    teams: list[TeamName]


class TournamentFormat(BaseModel):
    """How the tournament is played, from its confirmed rules (docs/04-engine.md)."""

    kind: Literal["round_robin", "double_round_robin", "groups_then_knockout", "knockout"]
    qualify_per_group: int  # top N of each group reach the knockout; 0 when the table decides
    best_of_rest: int  # e.g. the best 4 third-placed teams also go through
    points: dict[str, int]  # outcome -> points, e.g. {"win": 3, "draw": 1, "loss": 0}
    match_minutes: int | None  # playing time, without breaks
    tiebreakers: list[str]  # applied in order, engine codes
    standings_visible: bool


class TournamentPage(BaseModel):
    id: UUID
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
    organisation_id: UUID
    organisation_name: str
    is_junior: bool
    format: TournamentFormat | None = None  # None until the rules are confirmed


class Score(BaseModel):
    home_goals: int
    away_goals: int
    period: int | None = None
    finished: bool = False


class MatchCard(BaseModel):
    id: UUID
    tournament_id: UUID
    sport: str  # "football", "futsal"
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
    score: Score | None  # None when the live access policy hides it
    data_level: str = "events"  # "results": only the final score is entered, no live events


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
    status: Literal["through", "out", "alive"] = "alive"  # from the scenarios read model


class GroupTable(BaseModel):
    group: str
    group_id: UUID | None = None
    rows: list[StandingsRow]


class StandingsPage(BaseModel):
    version: int
    groups: list[GroupTable]


class BracketPage(BaseModel):
    version: int
    matches: list[dict[str, Any]]


class ScenarioPage(BaseModel):
    team: TeamName
    scenario: dict[str, Any]


class SchedulePage(BaseModel):
    matches: list[MatchCard]


class LivePage(BaseModel):
    matches: list[MatchCard]


class MatchList(BaseModel):
    """Matches across tournaments: the fan app's live feed, an organisation's matches."""

    matches: list[MatchCard]
    server_time: datetime


class ScreenPage(BaseModel):
    now_playing: list[MatchCard]
    next_up: list[MatchCard]
    standings: list[GroupTable]


class WidgetPage(BaseModel):
    live: list[MatchCard]
    next: list[MatchCard]
    leaders: list[StandingsRow]


class MatchPage(BaseModel):
    match: MatchCard
    tournament_id: UUID
    live_access: bool


class TimelinePage(BaseModel):
    events: list[dict[str, Any]]


class TeamPage(BaseModel):
    id: UUID
    name: str
    short_name: str | None
    tournaments: list[dict[str, Any]]
    matches: list[MatchCard]
    organisation_id: UUID | None = None
    age_group: str = "adult"
    players: list["HubPlayer"] = []  # only players this viewer may see (docs/09)


class HubTournament(BaseModel):
    id: UUID
    name: str
    status: str


class HubPlayer(BaseModel):
    id: UUID
    display_name: str
    shirt_number: int | None


class MattersItem(BaseModel):
    match: MatchCard | None
    impact: float
    reason: str


class TeamHub(BaseModel):
    """My Team hub (docs/14-personal-experience.md): read models only."""

    team: TeamName
    tournament: HubTournament | None
    status_chip: str | None  # "2nd in Group A · alive"
    now_or_next: MatchCard | None
    what_we_need: list[str]
    knockout: dict[str, Any] | None
    matters: list[MattersItem]
    journey: dict[str, Any] | None
    league: GroupTable | None
    players: list[HubPlayer]  # only players this viewer may see
    chances: dict[str, Any] | None = None  # predictions (T-042)
    stories: list[dict[str, Any]] = []  # stories (T-052)


class MatchPrediction(BaseModel):
    """Chances with ranges; without percentages (junior or no data) only the reasons."""

    match_id: UUID
    confidence: str
    home_win: tuple[float, float] | None
    draw: tuple[float, float] | None
    away_win: tuple[float, float] | None
    factors: list[dict[str, Any]]
    model_version: str


class ComparisonPage(BaseModel):
    a: dict[str, Any]
    b: dict[str, Any]
    head_to_head: list[dict[str, Any]]
    rating_gap: str


class AnalysisPage(BaseModel):
    facts: list[dict[str, Any]]


class Fact(BaseModel):
    """One verified statement (docs/07, Fact sheets). `source` names the read model."""

    id: str
    kind: str
    claim: str
    value: int | float | str | None = None
    unit: str | None = None
    source: str
    team_id: str | None = None


class FactContext(BaseModel):
    tournament_id: UUID | None = None
    is_junior: bool
    show_probabilities: bool
    languages: list[str]
    tone_profile: str  # "adult" or "junior"
    audience: str = "public"  # "public" or "team_followers"


class FactSheetOut(BaseModel):
    """What a writing task receives; nothing else about the subject reaches the LLM."""

    id: UUID
    subject_type: str  # "match", "team", "tournament"
    subject_id: UUID
    kind: str  # "preview", "report", "team_recap", "summary"
    facts: list[Fact]
    context: FactContext
    inputs_hash: str
    created_at: datetime


class MatchInfo(BaseModel):
    """What content needs to know about a match for live commentary."""

    id: UUID
    tournament_id: UUID
    stage: str
    status: str
    home_team_id: UUID | None
    away_team_id: UUID | None


class PlayerPage(BaseModel):
    """A player a viewer may see (public, their family, or staff), with their goals."""

    id: UUID
    display_name: str
    shirt_number: int | None
    team: TeamName
    goals: int
    tournaments: list[dict[str, Any]]


TeamPage.model_rebuild()
