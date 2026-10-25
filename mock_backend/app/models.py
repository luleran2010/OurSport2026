from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Base model: snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Sport(ApiModel):
    id: str
    label: str
    icon: str = ""


class Team(ApiModel):
    id: str
    name: str
    short: str
    color: str
    sport: str
    league: str
    club_id: str
    region: str
    age_group: str


class Region(ApiModel):
    id: str
    label: str


class AgeGroup(ApiModel):
    id: str
    label: str


SponsorPlacement = Literal["cards", "club_page", "reports"]


class Sponsor(ApiModel):
    id: str = ""
    name: str
    logo_url: str | None = None
    url: str | None = None
    show_on: list[SponsorPlacement] = ["cards", "club_page", "reports"]  # share cards / club page / match reports


class Club(ApiModel):
    id: str
    name: str
    short: str
    color: str
    city: str
    region: str
    sports: list[str]
    team_ids: list[str]
    venue: str
    lat: float
    lon: float
    logo_url: str | None = None  # None -> the app draws a crest from short + color
    sponsors: list[Sponsor] = []
    contact_email: str | None = None
    secondary_color: str = "#ffffff"  # second colour on share cards
    description: str = ""


class Player(ApiModel):
    id: str
    name: str
    number: int
    position: str
    team: Team


MatchStatus = Literal["live", "upcoming", "finished"]


class Correction(ApiModel):
    message: str
    at: int  # epoch ms


class Match(ApiModel):
    id: str
    sport: str
    league: str
    status: MatchStatus
    home: Team
    away: Team
    venue: str
    score: list[int] | None = None
    clock: int | None = None
    period: str | None = None
    viewers: int | None = None
    last_event: str | None = None
    flash: int | None = None  # 0 = home, 1 = away just scored (cleared next tick)
    starts_at: int | None = None  # epoch ms
    ended_at: int | None = None  # epoch ms
    tournament_id: str | None = None
    stage: str | None = None  # e.g. "Group A"
    correction: "Correction | None" = None  # set when the result/data was corrected
    data_level: Literal["live", "results_only"] = "live"  # results_only: no live events, only the final score


class Comment(ApiModel):
    id: str
    author: str
    text: str
    created_at: int


class PostResult(ApiModel):
    home: str
    away: str
    score: list[int]


class PostMedia(ApiModel):
    duration: str


PostType = Literal["highlight", "update", "result", "score"]


class Post(ApiModel):
    id: str
    type: PostType
    sport: str
    team_ids: list[str]
    match_id: str | None = None  # set when the post is about one match
    author: str
    created_at: int
    text: str
    likes: int = 0
    comments: list[Comment] = []
    media: PostMedia | None = None
    result: PostResult | None = None


class FeedSnapshot(ApiModel):
    now: int
    matches: list[Match]
    posts: list[Post]


class NewComment(ApiModel):
    text: str
    author: str = "You"


# ---- Explore & search (F2) -------------------------------------------------

SearchType = Literal["all", "clubs", "teams", "events", "players"]


class SearchResults(ApiModel):
    query: str
    total: int
    counts: dict[str, int]  # matches per type before the per-group limit
    clubs: list[Club]
    teams: list[Team]
    events: list[Match]
    players: list[Player]


class SearchOption(ApiModel):
    id: str
    label: str


class SearchFilters(ApiModel):
    types: list[SearchOption]
    sports: list[Sport]
    regions: list[Region]
    age_groups: list[AgeGroup]


class NearbyClub(Club):
    distance_km: float


class NearbyEvent(Match):
    distance_km: float


class NearbyResults(ApiModel):
    clubs: list[NearbyClub]
    events: list[NearbyEvent]


class ClubSuggestion(ApiModel):
    name: str = Field(min_length=2, max_length=120)
    city: str = Field("", max_length=80)
    sport: str = Field("", max_length=40)
    contact: str = Field("", max_length=120)
    message: str = Field("", max_length=1000)


class SuggestionReceipt(ApiModel):
    id: str
    status: Literal["received"] = "received"


# ---- Club page (F3) --------------------------------------------------------

class ClubEvent(ApiModel):
    """A non-match club happening: open training, camp, fan evening…"""

    id: str
    club_id: str
    title: str
    starts_at: int  # epoch ms
    venue: str
    description: str = ""


class ClubMatches(ApiModel):
    when: Literal["upcoming", "past"]
    matches: list[Match]
    events: list[ClubEvent]
    total: int  # matches + events available to a member
    limited: bool  # True when a visitor only sees the first few


class StoryText(ApiModel):
    title: str
    summary: str
    body: list[str]


class StoryFact(ApiModel):
    """One line of the fact sheet a story was written from (shown under "Why?")."""

    key: str  # final_score | competition | venue | ended_at | kickoff_at | goal | table_move | head_to_head
    value: str  # language-neutral value (names, numbers)
    at: int | None = None  # epoch ms, for date facts


class Story(ApiModel):
    id: str
    club_id: str | None = None
    tournament_id: str | None = None
    match_id: str | None = None
    team_ids: list[str] = []
    title: str
    summary: str
    body: list[str]  # paragraphs
    tag: str
    author: str
    author_type: Literal["ai", "editor"] = "editor"
    published_at: int  # epoch ms
    language: str = "en"  # language of title/summary/body in this response
    available_languages: list[str] = ["en"]
    # other languages; kept server-side (GET /stories/{id}?lang= picks one), never serialised
    translations: dict[str, StoryText] = Field(default_factory=dict, exclude=True)
    facts: list[StoryFact] = []  # AI stories: the fact sheet they were written from
    image_url: str | None = None  # P5: manual posts can have one image (from POST /uploads)
    related_match_ids: list[str] = []  # P5: more linked matches besides match_id
    corrected_at: int | None = None  # E3: set when an editor published a correction ("Corrected on {date}")
    correction_note: str | None = None  # what was corrected, shown to readers


# ---- Me / follows / demo auth -----------------------------------------------

class Premium(ApiModel):
    plan: str
    via_club_id: str | None = None  # "Granted by {club}"
    via_club_name: str | None = None
    valid_until: int | None = None  # epoch ms


class Follows(ApiModel):
    clubs: list[str]
    teams: list[str]
    tournaments: list[str] = []


class FamilyLink(ApiModel):
    """A junior player this member is the guardian of (they can see the private profile)."""

    player: "Player"
    relation: Literal["guardian"] = "guardian"


Language = Literal["en", "fi", "bn"]


class ClubRole(ApiModel):
    """A role a club gave this member through an invite (F13)."""

    club_id: str
    club_name: str
    role: str  # e.g. "scorer"
    label: str  # e.g. "Scorer"


class Me(ApiModel):
    signed_in: bool
    name: str
    email: str | None = None
    language: Language = "en"
    premium: Premium | None = None
    follows: Follows
    family: list[FamilyLink] = []
    roles: list[ClubRole] = []


class MePatch(ApiModel):
    """Only the fields you send are changed."""

    name: str | None = Field(None, min_length=1, max_length=60)
    email: str | None = Field(None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    language: Language | None = None


class RedeemCode(ApiModel):
    code: str = Field(min_length=3, max_length=40)


class FollowRequest(ApiModel):
    kind: Literal["club", "team", "tournament"]
    id: str


# ---- Events / tournaments (F5) ---------------------------------------------

class Organiser(ApiModel):
    name: str
    club_id: str | None = None


class Tiebreak(ApiModel):
    key: str  # "gd" | "nrr"
    label: str  # column header, e.g. "GD" or "NRR"
    description: str


class TournamentGroup(ApiModel):
    id: str
    name: str
    team_ids: list[str]


class Tournament(ApiModel):
    id: str
    name: str
    sport: str
    starts_at: int
    ends_at: int
    organiser: Organiser
    venue: str
    region: str
    format: str  # plain-language format line
    results_only: bool  # no player data: hide player sections
    junior: bool = False  # junior event: player sections hidden (junior protection)
    qualify_count: int  # top N of each group go through
    qualify_label: str  # what they go through to, e.g. "the semi-finals"
    points_win: int
    points_draw: int
    match_minutes: int
    tiebreak: Tiebreak
    for_label: str
    against_label: str
    groups: list[TournamentGroup]
    teams: list[Team]
    updated_at: int = 0  # epoch ms of the latest data


class StandingRow(ApiModel):
    position: int
    team: Team
    played: int
    won: int
    drawn: int
    lost: int
    scored: int
    conceded: int
    tiebreak_value: float
    tiebreak_display: str
    points: int
    form: list[Literal["W", "D", "L"]]  # oldest -> newest
    status: Literal["through", "out", "alive"]


class GroupStandings(ApiModel):
    id: str
    name: str
    rows: list[StandingRow]


class TopScorer(ApiModel):
    player_name: str
    team: Team
    goals: int


class StandingsResponse(ApiModel):
    tournament_id: str
    updated_at: int
    tiebreak: Tiebreak
    for_label: str
    against_label: str
    qualify_count: int
    groups: list[GroupStandings]
    top_scorers: list[TopScorer] | None  # None for results-only events


class ScenarioFixture(ApiModel):
    match_id: str
    opponent: Team
    status: Literal["live", "upcoming"]
    starts_at: int | None = None


class ScenarioCard(ApiModel):
    team: Team
    group_id: str
    group_name: str
    position: int
    points: int
    max_points: int
    status: Literal["through", "out", "alive"]
    headline: str
    detail: str
    remaining: list[ScenarioFixture]


class ScenariosResponse(ApiModel):
    tournament_id: str
    updated_at: int
    qualify_count: int
    cards: list[ScenarioCard]


class RuleSection(ApiModel):
    heading: str
    text: str


class RulesSummary(ApiModel):
    tournament_id: str
    title: str
    sections: list[RuleSection]


# ---- Match page (F6) ---------------------------------------------------------

TimelineKind = Literal["kickoff", "goal", "insight", "fulltime", "info", "event", "period", "correction"]


class TimelineEvent(ApiModel):
    id: str
    minute: int
    kind: TimelineKind
    text: str
    team_id: str | None = None
    ai: bool = False  # generated insight, labelled as such in the app
    at: int  # epoch ms
    icon: str | None = None  # from the sport's event list (scorer-entered events)


class PlayerNote(ApiModel):
    player: Player
    note: str


class HeadToHead(ApiModel):
    played: int
    home_wins: int
    draws: int
    away_wins: int
    matches: list[Match]  # most recent first


class TableImpact(ApiModel):
    team: Team
    group_name: str
    before: int | None  # position before this game (None = no games yet)
    after: int
    text: str  # e.g. "moved from 3rd to 2nd"


class LiveAccess(ApiModel):
    live_allowed: bool  # premium: live score, timeline and stakes
    reason: str | None = None


class MatchDetail(ApiModel):
    match: Match  # score/clock removed for live games without premium
    access: LiveAccess
    junior: bool = False  # a junior team plays: player sections are not provided
    tournament_name: str | None = None
    stakes: list[ScenarioCard] | None = None  # scheduled tournament games
    players_to_watch: list[PlayerNote] | None = None  # scheduled; None for results-only events
    head_to_head: HeadToHead | None = None  # scheduled
    live_stakes: str | None = None  # live + premium: "If it ends like this…"
    timeline: list[TimelineEvent] | None = None  # live + premium
    table_impact: list[TableImpact] | None = None  # finished tournament games
    player_of_match: PlayerNote | None = None  # finished; None for results-only events
    updated_at: int


class LiveToken(ApiModel):
    token: str
    expires_at: int


class LiveMessage(ApiModel):
    type: Literal["snapshot", "update"]
    match: Match
    timeline: list[TimelineEvent]
    live_stakes: str | None
    updated_at: int


Match.model_rebuild()
FamilyLink.model_rebuild()


# ---- Story page (F7) ---------------------------------------------------------

class TournamentRef(ApiModel):
    id: str
    name: str


class StoryRelated(ApiModel):
    matches: list[Match]
    teams: list[Team]
    club: Club | None = None
    tournament: TournamentRef | None = None


class StoryDetail(ApiModel):
    story: Story
    related: StoryRelated
    sponsors: list[Sponsor] = []  # match reports: sponsors of the clubs playing that chose "reports"


class ErrorReport(ApiModel):
    message: str = Field(min_length=5, max_length=1000)


class ErrorReportReceipt(ApiModel):
    id: str
    status: Literal["received"] = "received"


# ---- Player page (F8) ----------------------------------------------------------

Visibility = Literal["public", "members", "private"]


class StatItem(ApiModel):
    key: str
    label: str
    value: str


class FormItem(ApiModel):
    match_id: str
    result: Literal["W", "D", "L"]  # team result
    contribution: str  # the player's line, e.g. "1 goal · 90′"


class Milestone(ApiModel):
    title: str
    achieved: bool
    date: int | None = None  # epoch ms when achieved
    progress: int | None = None
    target: int | None = None


class PlayerMatchLine(ApiModel):
    match: Match
    line: str


class PlayerProfile(ApiModel):
    player: Player
    visibility: Visibility
    season: str
    stats: list[StatItem]
    form: list[FormItem]  # oldest -> newest
    milestones: list[Milestone]
    recent_matches: list[PlayerMatchLine]  # newest first


# ---- Following (F9) ----------------------------------------------------------------

FollowKind = Literal["club", "team", "tournament"]


class NotificationPrefs(ApiModel):
    match_start: bool = True
    live_updates: bool = True  # goals and other live events
    results: bool = True
    scenario_changes: bool = True
    news: bool = True


class NotificationPatch(ApiModel):
    """Only the fields you send are changed."""

    match_start: bool | None = None
    live_updates: bool | None = None
    results: bool | None = None
    scenario_changes: bool | None = None
    news: bool | None = None


class FollowItem(ApiModel):
    id: str  # "<kind>:<target id>", e.g. "club:ols"
    kind: FollowKind
    target_id: str
    name: str
    subtitle: str
    short: str
    color: str
    sport: str | None = None
    starts_at: int | None = None  # events
    ends_at: int | None = None
    notifications: NotificationPrefs


class FollowList(ApiModel):
    clubs: list[FollowItem]
    teams: list[FollowItem]
    events: list[FollowItem]


# ---- Notifications (F11) and the news feed -------------------------------------------

NotificationKind = Literal["match_start", "live_update", "result", "scenario_change", "news"]


class NotificationLink(ApiModel):
    type: Literal["match", "story", "event", "team", "club"]
    id: str


class AppNotification(ApiModel):
    id: str
    kind: NotificationKind
    title: str
    body: str
    at: int  # epoch ms
    read: bool
    link: NotificationLink | None = None


class NotificationsPage(ApiModel):
    items: list[AppNotification]  # newest first
    unread_count: int
    next_cursor: str | None = None


class MarkRead(ApiModel):
    ids: list[str] = []
    all: bool = False


class NewsPage(ApiModel):
    items: list[Story]  # newest first
    next_cursor: str | None = None


# ---- Sign up / log in / reset password (F12) ------------------------------------------

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SignupBody(ApiModel):
    email: str = Field(max_length=120, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=200)
    language: Language = "en"
    accept_terms: bool  # consent to the terms of use and privacy policy


class LoginBody(ApiModel):
    email: str = Field(max_length=120)
    password: str = Field(max_length=200)


class ResetRequest(ApiModel):
    email: str = Field(max_length=120)


class ResetConfirm(ApiModel):
    token: str = Field(min_length=10, max_length=100)
    password: str = Field(min_length=8, max_length=200)


class ResetRequested(ApiModel):
    status: Literal["sent"] = "sent"
    dev_reset_link: str | None = None  # only when OURSPORT_DEV_EMAIL=1 (no email service yet)


# ---- Accept invite (F13) ---------------------------------------------------------------

class InviteOffer(ApiModel):
    kind: Literal["premium_seat", "role"]
    role: str | None = None  # for kind == "role"
    label: str  # "Premium seat" / "Scorer"
    description: str


class InviteInfo(ApiModel):
    token: str
    club: Club
    offer: InviteOffer
    invited_by: str
    message: str | None = None
    expires_at: int
    status: Literal["valid", "expired", "used", "accepted_by_you"]


class InviteAccepted(ApiModel):
    me: Me
    invite: InviteInfo


# ---- Club dashboard (C1) ---------------------------------------------------------------------

class ClubKpis(ApiModel):
    followers: int
    premium_seats_used: int
    premium_seats_total: int
    matches_this_week: int
    open_corrections: int


class NextMatch(ApiModel):
    match: Match
    scorer: str | None = None  # None -> "No scorer"


class ClubDashboard(ApiModel):
    club: Club
    plan: str
    kpis: ClubKpis
    next_matches: list[NextMatch]
    stories: list[Story]  # latest published stories about the club
    updated_at: int


# ---- Club portal: members and Premium seats (C2) ------------------------------------------

MemberRole = Literal["member", "scorer", "admin"]


class SeatCount(ApiModel):
    used: int
    total: int


class ClubMember(ApiModel):
    id: str
    name: str | None = None  # unknown until the person joins, if the invite had no name
    email: str
    role: MemberRole
    premium: bool
    status: Literal["invited", "active", "expired"]
    invited_at: int
    activated_at: int | None = None
    expires_at: int | None = None  # of a pending (or expired) invite
    is_you: bool = False
    invite_link: str | None = None  # only with OURSPORT_DEV_EMAIL=1 (no email service yet)


class ClubMembers(ApiModel):
    club: Club
    plan: str
    seats: SeatCount
    members: list[ClubMember]
    updated_at: int


class InviteRowIn(ApiModel):
    """One row of a bulk invite; checked row by row so mistakes come back as row errors, not a 422."""

    email: str = Field(max_length=200)
    name: str | None = Field(None, max_length=120)
    role: str = Field("member", max_length=20)
    premium: bool = False


class BulkInviteIn(ApiModel):
    rows: list[InviteRowIn] = Field(min_length=1, max_length=500)
    dry_run: bool = False  # true: only validate (the dialog's preview)


class RowError(ApiModel):
    code: Literal["email", "duplicate", "duplicate_in_list", "role", "seat_limit"]
    message: str


class InviteRowResult(ApiModel):
    index: int
    email: str
    name: str | None = None
    role: str
    premium: bool
    error: RowError | None = None


class BulkInviteResult(ApiModel):
    rows: list[InviteRowResult]
    created: list[ClubMember]
    seats: SeatCount


class MemberPatch(ApiModel):
    """Only the fields you send are changed."""

    premium: bool | None = None
    role: MemberRole | None = None


class MemberChange(ApiModel):
    member: ClubMember | None = None  # None after a delete
    seats: SeatCount


# ---- Club portal: teams and players (C3) --------------------------------------------------

RosterVisibility = Literal["public", "family", "hidden"]


class TeamSummary(ApiModel):
    team: Team
    competitions: list[str]  # leagues and tournaments the team plays in
    players: int
    minors: int  # players under 18 (by birth year)
    hidden: int


class ClubTeams(ApiModel):
    club: Club
    teams: list[TeamSummary]
    sports: list[Sport]
    age_groups: list[AgeGroup]


class TeamIn(ApiModel):
    name: str = Field(min_length=2, max_length=60)
    short: str | None = Field(None, min_length=2, max_length=4)
    sport: str
    age_group: str
    league: str = Field("", max_length=60)


class TeamPatch(ApiModel):
    """Only the fields you send are changed. The sport can't be changed (create a new team)."""

    name: str | None = Field(None, min_length=2, max_length=60)
    short: str | None = Field(None, min_length=2, max_length=4)
    age_group: str | None = None
    league: str | None = Field(None, max_length=60)


class Consent(ApiModel):
    given_by: str
    email: str | None = None
    relation: Literal["guardian", "player"]
    scope: Literal["family", "public"]  # what was agreed: family-only profile, or a public profile
    recorded_at: int
    recorded_by: str


class FamilyMember(ApiModel):
    id: str
    name: str
    email: str
    has_account: bool  # False: the link starts working when they sign up with this email


class RosterPlayer(ApiModel):
    id: str
    name: str
    number: int
    position: str
    birth_year: int
    minor: bool  # under 18 (born in or after the cutoff year)
    visibility: RosterVisibility
    allowed: list[RosterVisibility]  # what the API accepts for this player right now
    own_setting: Literal["members", "private"] | None = None  # an adult player's own narrower choice
    consent: Consent | None = None
    family: list[FamilyMember] = []


class TeamRoster(ApiModel):
    team: Team
    club: Club
    competitions: list[str]
    minor_cutoff_year: int  # born in or after this year counts as under 18
    players: list[RosterPlayer]


class PlayerIn(ApiModel):
    name: str = Field(min_length=2, max_length=60)
    number: int = Field(ge=0, le=99)
    birth_year: int = Field(ge=1940, le=2030)
    position: str = Field("", max_length=30)
    visibility: RosterVisibility | None = None  # default: hidden for under-18s, public for adults


class PlayerPatch(ApiModel):
    name: str | None = Field(None, min_length=2, max_length=60)
    number: int | None = Field(None, ge=0, le=99)
    birth_year: int | None = Field(None, ge=1940, le=2030)
    position: str | None = Field(None, max_length=30)
    visibility: RosterVisibility | None = None


class ConsentIn(ApiModel):
    given_by: str = Field(min_length=2, max_length=80)
    email: str | None = Field(None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    relation: Literal["guardian", "player"] = "guardian"
    scope: Literal["family", "public"] = "family"
    link_family: bool = True  # also link the guardian's account so they can see the profile


class FamilyIn(ApiModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---- Club portal: matches and scorers (C4) -------------------------------------------------

class ScorerOption(ApiModel):
    id: str  # member id in the club roster
    name: str
    email: str


class AssignedScorer(ApiModel):
    member_id: str
    name: str
    club_id: str
    club_name: str


class PortalMatch(ApiModel):
    match: Match
    competition: str  # tournament name or league
    data_level: Literal["live", "results_only"]
    status: Literal["upcoming", "awaiting_result", "live", "finished"]  # awaiting_result: results-only game has started
    scorer: AssignedScorer | None = None
    can_finish: bool  # the "Enter result" / finish action is allowed now
    editable: bool  # scorer and data level can still be changed (not finished)


class PortalMatches(ApiModel):
    club: Club
    teams: list[Team]  # the club's teams (filter)
    scorers: list[ScorerOption]  # active members with the scorer role
    upcoming: list[PortalMatch]  # live, awaiting result and scheduled, soonest first
    past: list[PortalMatch]  # finished, latest first
    updated_at: int


class MatchPatch(ApiModel):
    """Only the fields you send are changed. `scorerId: null` removes the scorer."""

    scorer_id: str | None = None
    data_level: Literal["live", "results_only"] | None = None
    # publishers (P4) on their event's matches also:
    starts_at: int | None = None  # epoch ms (before kick-off)
    venue: str | None = Field(None, min_length=2, max_length=80)
    score: list[int] | None = Field(None, min_length=2, max_length=2)  # enter (or correct) the result


class FinishMatch(ApiModel):
    score: list[int] = Field(min_length=2, max_length=2)  # [home, away]


# ---- Club portal: profile and sponsors (C5) ------------------------------------------------

class ClubPatch(ApiModel):
    """Only the fields you send are changed. `logoUrl` must come from POST /uploads (or null to remove)."""

    name: str | None = Field(None, min_length=2, max_length=80)
    short: str | None = Field(None, min_length=2, max_length=4)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    secondary_color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    city: str | None = Field(None, min_length=2, max_length=60)
    sports: list[str] | None = Field(None, min_length=1)
    description: str | None = Field(None, max_length=800)
    logo_url: str | None = None
    contact_email: str | None = Field(None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SponsorIn(ApiModel):
    name: str = Field(min_length=2, max_length=80)
    url: str | None = Field(None, max_length=200)
    logo_url: str | None = None
    show_on: list[SponsorPlacement] = ["cards", "club_page", "reports"]


class SponsorPatch(ApiModel):
    name: str | None = Field(None, min_length=2, max_length=80)
    url: str | None = Field(None, max_length=200)
    logo_url: str | None = None
    show_on: list[SponsorPlacement] | None = None


class ClubProfile(ApiModel):
    club: Club
    sports: list[Sport]  # options
    sports_in_use: list[str]  # sports the club's teams play (can't be removed)
    updated_at: int


class Upload(ApiModel):
    id: str
    url: str  # /uploads/{id}
    content_type: str
    size: int


# ---- Club portal: billing (C6) ----------------------------------------------------------------

class PaymentMethod(ApiModel):
    """Summary from the payment provider. Card details are entered and stored only on the provider's page."""

    brand: str
    last4: str
    expires: str  # MM/YY


class Invoice(ApiModel):
    id: str
    number: str
    period_start: str  # dates (YYYY-MM-DD, Finnish calendar)
    period_end: str
    issued_on: str
    seats: int
    net_cents: int
    vat_cents: int
    total_cents: int
    status: Literal["paid", "open"]
    pdf_url: str


class BillingSummary(ApiModel):
    club: Club
    plan: str
    currency: Literal["EUR"] = "EUR"
    price_per_seat_cents: int  # per month, VAT 0 %
    vat_rate: float
    seats_total: int
    seats_used: int
    min_seats: int  # can't go below the seats in use
    max_seats: int
    monthly_net_cents: int
    next_invoice_date: str  # YYYY-MM-DD
    next_invoice_estimate_cents: int  # incl. VAT and any change this month
    pending_charge_cents: int  # prorated seats added this month, on the next invoice (net)
    payment_method: PaymentMethod | None = None
    invoices: list[Invoice]
    updated_at: int


class SeatChange(ApiModel):
    seats: int = Field(ge=0, le=1000)
    preview: bool = False  # true: only work out the cost


class SeatChangeResult(ApiModel):
    seats_from: int
    seats_to: int
    prorated_net_cents: int  # added seats for the rest of this month (0 when reducing)
    new_monthly_net_cents: int
    effective: Literal["now"] = "now"
    message: str
    applied: bool
    billing: BillingSummary | None = None  # after the change (not on a preview)


class PortalRequest(ApiModel):
    return_path: str = Field("/club", max_length=200)  # where the provider sends the admin back to (our app)


class PortalSession(ApiModel):
    url: str  # the provider's hosted page: open it with a full-page redirect
    expires_at: int


# ---- Club portal: corrections (C7) ----------------------------------------------------------

CorrectionStatus = Literal["open", "fixed", "rejected"]


class CorrectionItem(ApiModel):
    id: str
    source: Literal["fan", "club"]
    status: CorrectionStatus
    field: str
    field_label: str
    message: str  # what is wrong
    correct_value: str | None = None
    reporter: str | None = None  # club reports only; fans stay anonymous
    created_at: int
    resolved_at: int | None = None
    resolution: str | None = None  # the editor's note
    match: "Match | None" = None
    story_id: str | None = None
    story_title: str | None = None


class CorrectionList(ApiModel):
    club: Club
    items: list[CorrectionItem]  # newest first
    counts: dict[str, int]  # open / fixed / rejected
    fields: dict[str, str]  # what can be wrong: id -> label (for the form)
    updated_at: int


class CorrectionIn(ApiModel):
    club_id: str
    match_id: str
    field: str
    message: str = Field(min_length=5, max_length=1000)
    correct_value: str | None = Field(None, max_length=200)


class CorrectionResolve(ApiModel):
    status: Literal["fixed", "rejected"]
    note: str | None = Field(None, max_length=1000)


# ---- Scorer area: my matches (S1) -----------------------------------------------------------

class ScoringAssignment(ApiModel):
    match: Match
    club_id: str  # the club that assigned me
    club_name: str
    competition: str
    data_level: Literal["live", "results_only"]
    status: Literal["upcoming", "live", "finished"]
    day: Literal["today", "later", "past"]
    can_start: bool  # live or kicks off today
    events_recorded: int  # events the server has for this match (local unsent ones are counted by the app)
    last_event_at: int | None = None


class ScoringAssignments(ApiModel):
    scorer_name: str
    clubs: list[Club]
    active: list[ScoringAssignment]  # live first, then today, then later
    past: list[ScoringAssignment]  # finished, latest first
    updated_at: int


# ---- Scorer console (S2) --------------------------------------------------------------------

class EventType(ApiModel):
    id: str
    label: str  # button text
    icon: str
    group: Literal["score", "play", "discipline", "control"]
    team: bool = True  # belongs to one team
    player: Literal["required", "optional", "none"] = "none"
    player_prompt: str | None = None  # picker title, e.g. "Who scored?"
    points: int = 0  # added to the team's score
    follow_up: str | None = None  # event type offered right after (goal -> assist), skippable
    ball: bool = False  # cricket: a legal delivery (counts towards the over)
    wicket: bool = False
    feed: bool = True  # shown on the fans' live timeline (cricket: only boundaries and wickets)


class SportEvents(ApiModel):
    sport: str
    pad: Literal["split", "batting"]  # split: a column per team; batting: pick the batting team, then tap
    clock: bool  # running match clock (minutes)
    period_minutes: int | None = None
    periods: list[str]  # "1st half", "2nd half" / "1st innings", …
    score_label: str  # "Goals", "Runs", "Points"
    event_types: list[EventType]


class RosterEntry(ApiModel):
    id: str
    number: int
    name: str | None = None  # None: the profile isn't public (junior protection): show the number only


class ScoredEvent(ApiModel):
    seq: int  # server order
    client_seq: int
    device_id: str
    type: str
    team: Literal["home", "away"] | None = None
    player_id: str | None = None
    player_label: str | None = None
    minute: int | None = None
    period: int
    at: int
    undone: bool = False


class ScoringClock(ApiModel):
    running: bool
    base_minute: int  # minute shown at base_at
    base_at: int  # epoch ms


class ScoringState(ApiModel):
    match: Match
    sport: str
    started: bool
    period_index: int
    period_label: str
    between_periods: bool  # a period has ended and the next one hasn't started
    clock: ScoringClock | None = None
    wickets: list[int] = [0, 0]  # cricket
    balls: list[int] = [0, 0]  # cricket: legal deliveries per batting team
    home_roster: list[RosterEntry]
    away_roster: list[RosterEntry]
    events: list[ScoredEvent]  # newest first, including undone ones
    device_last_seq: int = 0  # highest client_seq received from the asking device
    role: Literal["scorer", "admin"]
    updated_at: int


class EventIn(ApiModel):
    device_id: str = Field(min_length=4, max_length=64)
    client_seq: int = Field(ge=1)
    type: str
    team: Literal["home", "away"] | None = None
    player_id: str | None = None
    at: int | None = None  # when it was tapped (client clock), for the record


class UndoIn(ApiModel):
    device_id: str = Field(min_length=4, max_length=64)


# ---- Publisher portal (P1) ----------------------------------------------------------------------

EventStatus = Literal["draft", "rules_pending", "scheduled", "live", "finished"]


class PublisherEvent(ApiModel):
    id: str
    name: str
    sport: str
    status: EventStatus
    starts_at: int | None = None
    ends_at: int | None = None
    venue: str | None = None
    teams: int
    matches_total: int
    matches_played: int
    live_now: int  # matches being played right now
    review_enabled: bool  # the publisher reviews AI texts for this event (besides the editors)
    tournament_id: str | None = None  # published: the fans' event page
    next_step: str  # plain-language next thing to do


class PublisherEvents(ApiModel):
    organisation: str
    events: list[PublisherEvent]
    updated_at: int


class ReviewStory(ApiModel):
    id: str
    title: str
    summary: str
    tag: str
    language: str
    author_type: Literal["ai", "editor"]


class ReviewItem(ApiModel):
    id: str
    kind: Literal["ai_story"] = "ai_story"
    reason: str  # why it needs a look, e.g. "New match report"
    story: ReviewStory
    event_id: str
    event_name: str
    created_at: int
    status: Literal["pending", "in_review"]
    claimed_by: str | None = None


class ReviewQueue(ApiModel):
    scope: Literal["mine", "all"]
    items: list[ReviewItem]  # oldest first: the longest-waiting on top
    review_enabled_events: list[str]  # my events with publisher review on (scope=mine)
    updated_at: int


# ---- Publisher: create event wizard (P2) ---------------------------------------------------------

class SetupTeam(ApiModel):
    id: str
    name: str
    short: str
    color: str
    club_id: str | None = None
    new: bool = False  # created in the wizard (not yet a OurSport team)
    group: str | None = None  # group id


class SetupGroup(ApiModel):
    id: str
    name: str


class Fixture(ApiModel):
    id: str
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    home: str  # team id
    away: str
    venue: str
    group: str | None = None


class FixtureProblem(ApiModel):
    row: int  # 1-based row of the table or CSV (header not counted)
    field: str | None = None
    message: str


class Rulebook(ApiModel):
    kind: Literal["file", "url", "text"]
    name: str  # file name, the link or "Pasted text"
    size: int | None = None
    received_at: int


class RulesJob(ApiModel):
    status: Literal["reading", "done", "failed"]
    progress: int  # 0–100
    step: str  # what the AI is doing now
    started_at: int


class EventSetup(ApiModel):
    id: str
    status: Literal["draft", "rules_pending", "scheduled", "live", "finished"]
    step: int  # highest completed step (0–4)
    name: str
    sport: str
    start_date: str | None = None
    end_date: str | None = None
    venues: list[str] = []
    age_group: str = "senior"
    languages: list[Language] = ["fi", "en"]
    logo_url: str | None = None
    groups: list[SetupGroup] = []
    teams: list[SetupTeam] = []
    fixtures: list[Fixture] = []
    rulebook: Rulebook | None = None
    rules_job: RulesJob | None = None
    updated_at: int


class EventBasics(ApiModel):
    name: str = Field(min_length=3, max_length=80)
    sport: str
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    venues: list[str] = Field(min_length=1, max_length=10)
    age_group: str = "senior"
    languages: list[Language] = Field(min_length=1)
    logo_url: str | None = None


class EventPatch(ApiModel):
    """Only the fields you send are changed. `groups` and `fixtures` replace the whole list."""

    name: str | None = Field(None, min_length=3, max_length=80)
    sport: str | None = None
    start_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    venues: list[str] | None = Field(None, min_length=1, max_length=10)
    age_group: str | None = None
    languages: list[Language] | None = Field(None, min_length=1)
    logo_url: str | None = None
    groups: list[SetupGroup] | None = None
    team_groups: dict[str, str | None] | None = None  # team id -> group id
    fixtures: list[Fixture] | None = None
    step: int | None = Field(None, ge=0, le=4)  # mark a step done (validated)
    review_enabled: bool | None = None  # P4 settings: the publisher reviews AI texts before they go out
    visibility: Literal["public", "unlisted", "hidden"] | None = None  # P4 settings: listed / link only / hidden from fans


class TeamAdd(ApiModel):
    team_id: str | None = None  # an existing OurSport team
    name: str | None = Field(None, min_length=2, max_length=60)  # or a new one
    short: str | None = Field(None, min_length=2, max_length=4)
    group: str | None = None


class FixtureImport(ApiModel):
    kind: Literal["csv", "round_robin"]
    csv: str | None = Field(None, max_length=200_000)
    first_time: str = Field("10:00", pattern=r"^\d{2}:\d{2}$")  # round robin: first kick-off each day
    minutes_between: int = Field(60, ge=10, le=600)
    dry_run: bool = False


class FixtureImportResult(ApiModel):
    fixtures: list[Fixture]
    problems: list[FixtureProblem]
    setup: EventSetup | None = None  # after a real import


class RulesStatus(ApiModel):
    status: Literal["none", "reading", "done", "failed"]
    progress: int
    step: str
    rules: dict | None = None  # extracted rules for P3 (points, tiebreakers, format, uncertain fields)


# ---- Publisher: rules review (P3) ----------------------------------------------------------

class ExampleMark(ApiModel):
    status: Literal["correct", "incorrect", "pending"]
    note: str | None = Field(None, max_length=1000)


class RulesDraftPatch(ApiModel):
    """`values`: rule key -> value (keys as in the cards' fields, e.g. "points.win", "tiebreakers");
    `answers`: question id -> option id; `marks`: example id -> mark; `manual`: start an empty draft."""

    values: dict[str, Any] | None = None
    answers: dict[str, str] | None = None
    marks: dict[str, ExampleMark] | None = None
    manual: bool = False


# ---- Editor desk: review queue (E1) ----------------------------------------------------------

ReviewReason = Literal["sensitive_topic", "blocked_claim", "junior_mention", "manual_news", "correction"]


class QueueItem(ApiModel):
    id: str
    kind: Literal["ai_story", "manual_news", "correction"]
    reason: ReviewReason
    reason_text: str  # what the checker flagged, in plain words
    priority: Literal["high", "normal"]
    headline: str
    summary: str | None = None
    language: str
    sport: str | None = None
    event_id: str | None = None
    event_name: str | None = None
    match: "Match | None" = None
    source: str  # "OurSport AI", a club, or "Fan report"
    created_at: int
    status: Literal["pending", "in_review"]
    assigned_to: str | None = None
    assigned_to_me: bool = False
    claimed_at: int | None = None


class QueueFilterOption(ApiModel):
    id: str
    label: str
    count: int


class EditorQueue(ApiModel):
    scope: Literal["all"] = "all"
    items: list[QueueItem]  # high priority first, then the longest-waiting
    total: int  # matching the filters
    next_cursor: str | None = None
    counts: dict[str, int]  # all / high / unassigned / mine / over_30 / over_120 (whole queue, unfiltered)
    filters: dict[str, list[QueueFilterOption]]  # reasons / sports / events / languages present in the queue
    updated_at: int


# ---- Editor desk: review item (E2) ------------------------------------------------------------

class StoryEdit(ApiModel):
    item_id: str | None = Field(None, max_length=40)
    version: int | None = None  # the version the editor started from (409 if it changed meanwhile)
    title: str = Field(..., max_length=160)
    summary: str | None = Field(None, max_length=400)
    body: list[str] = Field(..., max_length=20)


class ReviewTarget(ApiModel):
    item_id: str | None = Field(None, max_length=40)


class ApproveRequest(ReviewTarget):
    verified: bool = False  # "I verified this manually" (needed while red flags remain)
    note: str | None = Field(None, max_length=600)
    public_note: str | None = Field(None, max_length=300)  # corrections: what was corrected, shown to readers


class RejectRequest(ReviewTarget):
    reason: str = Field(..., max_length=600)


class RegenerateRequest(ReviewTarget):
    note: str = Field(..., max_length=600)


# ---- Editor desk: published content and corrections (E3) ------------------------------------

class PublishedStory(ApiModel):
    id: str
    title: str
    summary: str
    tag: str
    author: str
    author_type: Literal["ai", "editor"]
    language: str
    published_at: int
    status: Literal["published", "unpublished"]
    event_id: str | None = None
    event_name: str | None = None
    match: "Match | None" = None
    club_name: str | None = None
    corrected_at: int | None = None
    correction_note: str | None = None
    open_corrections: int = 0
    correct_item_id: str  # E2 item to open for "Correct": the open report's item, else a fresh correction
    unpublished_at: int | None = None
    unpublished_by: str | None = None
    unpublish_reason: str | None = None


class PublishedPage(ApiModel):
    items: list[PublishedStory]  # newest first
    total: int
    next_cursor: str | None = None
    counts: dict[str, int]  # published / corrected / reported / unpublished
    events: list[QueueFilterOption]
    updated_at: int


class EditorCorrection(ApiModel):
    id: str
    item_id: str  # open it in E2
    source: Literal["fan", "club"]
    status: Literal["open", "fixed", "rejected"]
    field_label: str
    message: str
    correct_value: str | None = None
    reporter: str | None = None
    created_at: int
    resolved_at: int | None = None
    resolution: str | None = None
    story_id: str | None = None
    story_title: str | None = None
    story_status: Literal["published", "unpublished"] | None = None
    match: "Match | None" = None
    assigned_to: str | None = None


class EditorCorrections(ApiModel):
    items: list[EditorCorrection]  # open: oldest first; resolved: newest first
    counts: dict[str, int]  # open / fixed / rejected
    updated_at: int


class UnpublishRequest(ApiModel):
    reason: str = Field(..., max_length=600)


# ---- Publisher: event management (P4) ----------------------------------------------------------

class EventScorer(ApiModel):
    id: str
    name: str | None = None
    email: str
    status: Literal["invited", "active", "expired"]
    invited_at: int
    accepted_at: int | None = None
    expires_at: int | None = None
    matches: int = 0  # matches assigned


class ManagedMatch(ApiModel):
    match: Match
    group: str | None = None
    status: Literal["upcoming", "awaiting_result", "live", "finished"]
    scorer: AssignedScorer | None = None
    can_finish: bool
    editable: bool  # time, venue, data level and scorer can change (not started)
    events_recorded: int = 0


class ManagedTeam(ApiModel):
    team: Team
    group: str | None = None
    club_name: str | None = None
    played: int = 0
    points: int = 0
    position: int | None = None


class EventSettings(ApiModel):
    languages: list[Language]
    review_enabled: bool
    visibility: Literal["public", "unlisted", "hidden"]
    can_publish: bool  # manual posts go out directly; without it they go to the editor desk first


class EventManage(ApiModel):
    kind: Literal["managed"] = "managed"
    id: str
    tournament_id: str
    name: str
    sport: str
    status: Literal["scheduled", "live", "finished"]
    starts_at: int
    ends_at: int
    venue: str
    venues: list[str]
    format: str
    junior: bool
    results_only: bool
    settings: EventSettings
    counts: dict[str, int]  # total / played / live / upcoming / awaiting_result / no_scorer
    groups: list[TournamentGroup]
    teams: list[ManagedTeam]
    matches: list[ManagedMatch]  # by start time
    scorers: list[EventScorer]
    updated_at: int


class FixtureIn(ApiModel):
    home: str
    away: str
    starts_at: int  # epoch ms
    venue: str = Field(min_length=2, max_length=80)
    group: str | None = None


class ScorerInvite(ApiModel):
    emails: list[str] = Field(min_length=1, max_length=20)
    name: str | None = Field(None, max_length=80)  # for a single invite
    message: str | None = Field(None, max_length=500)


class ScorerInviteResult(ApiModel):
    invited: list[EventScorer]
    skipped: list[dict]  # {email, reason}


# ---- Publisher: news and content (P5) ----------------------------------------------------------

class EventStory(ApiModel):
    id: str
    title: str
    summary: str
    body: list[str]
    tag: str
    author: str
    author_type: Literal["ai", "manual"]
    language: str
    status: Literal["draft", "scheduled", "in_review", "published", "blocked", "unpublished"]
    at: int  # published / scheduled / submitted / saved
    publish_at: int | None = None
    note: str | None = None  # why blocked / unpublished, or the review reason
    corrected_at: int | None = None
    image_url: str | None = None
    team_ids: list[str] = []
    match_ids: list[str] = []
    editable: bool = False  # the publisher can still change it


class EventStories(ApiModel):
    event_id: str
    event_name: str
    items: list[EventStory]  # newest first
    counts: dict[str, int]
    languages: list[Language]
    can_publish: bool
    teams: list[Team]
    matches: list[Match]
    updated_at: int


class PostIn(ApiModel):
    event_id: str
    title: str = Field(min_length=3, max_length=140)
    summary: str | None = Field(None, max_length=300)
    body: str = Field(min_length=1, max_length=8000)  # paragraphs split by blank lines; **bold**, *italic*, "- " lists
    image_url: str | None = None
    team_ids: list[str] = Field(default_factory=list, max_length=10)
    match_ids: list[str] = Field(default_factory=list, max_length=10)
    language: Language = "en"
    publish_at: int | None = None  # epoch ms; empty = now
    submit: bool = True  # false: save as a draft


class PostPatch(ApiModel):
    title: str | None = Field(None, min_length=3, max_length=140)
    summary: str | None = Field(None, max_length=300)
    body: str | None = Field(None, min_length=1, max_length=8000)
    image_url: str | None = None
    team_ids: list[str] | None = Field(None, max_length=10)
    match_ids: list[str] | None = Field(None, max_length=10)
    language: Language | None = None
    publish_at: int | None = None
    submit: bool | None = None  # true: send a draft (publish, schedule or to the editors)


# ---- Team page (F4) ------------------------------------------------------------------

class TeamCompetition(ApiModel):
    id: str  # tournament id (the fans' event page)
    name: str
    group_name: str


class TeamStandings(ApiModel):
    """The team's group table; the page highlights the team's own row."""
    updated_at: int
    tiebreak: Tiebreak
    for_label: str
    against_label: str
    qualify_count: int
    group: GroupStandings


class PlayerSpotlight(ApiModel):
    player: Player
    visibility: Literal["public", "members", "family_only"]  # family_only: shown only to linked family
    stats: list[StatItem]  # a few season numbers
    form: list[FormItem]  # oldest -> newest
    milestone: Milestone | None = None


class TeamPage(ApiModel):
    team: Team
    club_name: str | None
    age_group_label: str
    junior: bool
    competition: TeamCompetition | None  # None: the team isn't in a current competition
    scenario: ScenarioCard | None
    standings: TeamStandings | None
    # Only the players this viewer may see. Empty for junior teams unless the viewer is linked family.
    players_to_watch: list[PlayerSpotlight]
    updated_at: int
