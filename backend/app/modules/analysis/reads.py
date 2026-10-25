"""Fan reads: only stored data (snapshots, published matches, live state), never the
engine or the LLM (CLAUDE.md rule 6). Live scores follow the live access policy."""

from datetime import date
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, RulesNotConfirmed
from app.core.viewer import Viewer
from app.modules.analysis.models import (
    AnalysisVersion,
    BracketSnapshot,
    MatchAnalysis,
    PredictionRecord,
    RelevanceSnapshot,
    ScenarioSnapshot,
    StandingsSnapshot,
    TeamComparison,
    TeamJourney,
)
from app.modules.analysis.schemas import (
    BracketPage,
    GroupPage,
    GroupTable,
    HubPlayer,
    HubTournament,
    LivePage,
    MatchCard,
    MatchPage,
    MatchPrediction,
    MattersItem,
    ScenarioPage,
    SchedulePage,
    Score,
    ScreenPage,
    StandingsPage,
    StandingsRow,
    TeamHub,
    TeamName,
    TeamPage,
    TimelinePage,
    TournamentFormat,
    TournamentPage,
    WidgetPage,
)
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut, TournamentOut
from app.modules.rules import service as rules
from app.modules.scoring import service as scoring
from engine.rules.config import RuleConfig


async def can_watch_live(db: AsyncSession, viewer: Viewer, tournament: TournamentOut) -> bool:
    """The live access policy (ADR 0011): staff always; then public / members / premium."""
    if await competitions.manages(db, viewer, tournament.id):
        return True
    policy = tournament.settings.live_access
    if policy == "public":
        return True
    if policy == "members":
        return viewer.is_member  # narrowed to followers and organisation members in T-040
    return False  # premium: entitlements arrive with subscriptions


class _Context:
    """Names and places a page needs, loaded once."""

    def __init__(
        self,
        tournament: TournamentOut,
        names: dict[UUID, str],
        groups: dict[UUID, str],
        pitches: dict[UUID, str],
        live: bool,
        shorts: dict[UUID, str | None] | None = None,
    ) -> None:
        self.tournament, self.names, self.groups, self.pitches, self.live = (
            tournament,
            names,
            groups,
            pitches,
            live,
        )
        self.shorts = shorts or {}

    def team(self, team_id: UUID | None) -> TeamName | None:
        if team_id is None:
            return None
        return TeamName(
            id=team_id, name=self.names.get(team_id, ""), short_name=self.shorts.get(team_id)
        )


async def _context(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> _Context:
    tournament = await competitions.get_tournament(db, viewer, tournament_id)  # drafts: 404
    entries = await competitions.entries_of(db, tournament_id)
    return _Context(
        tournament,
        {e.team_id: e.name for e in entries},
        {g.id: g.name for g in await competitions.groups_of(db, tournament_id)},
        {p.id: p.name for p in await competitions.pitches_of(db, tournament_id)},
        await can_watch_live(db, viewer, tournament),
        {e.team_id: e.short_name for e in entries},
    )


async def _card(db: AsyncSession, ctx: _Context, m: MatchOut) -> MatchCard:
    score = None
    if m.status == "finished" and m.result:
        score = Score.model_validate({**m.result, "finished": True})
    elif m.status == "live" and ctx.live:
        snapshot = await scoring.live_snapshot(db, m.id)
        if snapshot:
            live = snapshot[1]
            score = Score(
                home_goals=live.home_goals, away_goals=live.away_goals, period=live.period
            )
    return MatchCard(
        id=m.id,
        tournament_id=m.tournament_id,
        sport=ctx.tournament.sport,
        code=m.code,
        stage=m.stage,
        group=ctx.groups.get(m.group_id) if m.group_id else None,
        pitch=ctx.pitches.get(m.pitch_id) if m.pitch_id else None,
        starts_at=m.starts_at,
        status=m.status,
        home=ctx.team(m.home_team_id),
        away=ctx.team(m.away_team_id),
        home_source=m.home_source,
        away_source=m.away_source,
        score=score,
        data_level=m.data_level,
    )


async def tournament_page(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> TournamentPage:
    ctx = await _context(db, viewer, tournament_id)
    t = ctx.tournament
    entries = await competitions.entries_of(db, tournament_id)
    matches = await competitions.list_matches(db, tournament_id)
    groups = [
        GroupPage(
            id=gid,
            name=name,
            teams=[n for e in entries if e.group_id == gid and (n := ctx.team(e.team_id))],
        )
        for gid, name in ctx.groups.items()
    ]
    organisations = await competitions.organisation_names(db, [t.organisation_id])
    return TournamentPage(
        id=t.id,
        name=t.name,
        slug=t.slug,
        sport=t.sport,
        status=t.status,
        age_group=t.age_group,
        starts_on=t.starts_on,
        ends_on=t.ends_on,
        time_zone=t.time_zone,
        languages=list(t.settings.languages),
        live_access=t.settings.live_access,
        show_probabilities=t.settings.show_probabilities,
        groups=groups,
        live_now=sum(1 for m in matches if m.status == "live"),
        organisation_id=t.organisation_id,
        organisation_name=organisations.get(t.organisation_id, ""),
        is_junior=t.is_junior,
        format=await _format(db, tournament_id),
    )


async def _format(db: AsyncSession, tournament_id: UUID) -> TournamentFormat | None:
    try:
        stored = await rules.confirmed_config(db, tournament_id)
    except RulesNotConfirmed:
        return None
    config = RuleConfig.model_validate(stored.config)
    match = config.match
    minutes = (
        int(match["periods"]) * int(match["period_minutes"])
        if "periods" in match and "period_minutes" in match
        else None
    )
    knockout = config.format == "groups_then_knockout"
    return TournamentFormat(
        kind=config.format,
        qualify_per_group=config.advancement.per_group if knockout else 0,
        best_of_rest=config.advancement.best_of_rest if knockout else 0,
        points=config.points.table,
        match_minutes=minutes,
        tiebreakers=[t.value for t in config.tiebreakers],
        standings_visible=config.standings_visible,
    )


async def live_page(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> LivePage:
    ctx = await _context(db, viewer, tournament_id)
    matches = await competitions.list_matches(db, tournament_id)
    return LivePage(matches=[await _card(db, ctx, m) for m in matches if m.status == "live"])


async def _tables(
    db: AsyncSession, ctx: _Context, tournament_id: UUID
) -> tuple[int, list[GroupTable]]:
    current = await db.get(AnalysisVersion, tournament_id)
    if current is None:
        return 0, []
    rows = (
        await db.execute(
            select(StandingsSnapshot).where(
                StandingsSnapshot.tournament_id == tournament_id,
                StandingsSnapshot.version == current.version,
                StandingsSnapshot.provisional.is_(False),
            )
        )
    ).scalars()
    statuses = {
        s.team_id: _TABLE_STATUS.get(str(s.scenario.get("status")), "alive")
        for s in (
            await db.execute(
                select(ScenarioSnapshot).where(
                    ScenarioSnapshot.tournament_id == tournament_id,
                    ScenarioSnapshot.version == current.version,
                )
            )
        ).scalars()
    }
    tables = []
    for snapshot in sorted(
        rows, key=lambda s: ctx.groups.get(s.group_id, "") if s.group_id else ""
    ):
        tables.append(
            GroupTable(
                group=ctx.groups.get(snapshot.group_id, "") if snapshot.group_id else "",
                group_id=snapshot.group_id,
                rows=[_table_row(ctx, r, statuses) for r in snapshot.rows],
            )
        )
    return current.version, tables


_TABLE_STATUS: dict[str, Literal["through", "out", "alive"]] = {
    "clinched": "through",
    "eliminated": "out",
}


def _table_row(
    ctx: _Context,
    r: dict[str, Any],
    statuses: dict[UUID, Literal["through", "out", "alive"]] | None = None,
) -> StandingsRow:
    team_id = UUID(r["team_id"])
    team = ctx.team(team_id)
    assert team is not None
    return StandingsRow(
        position=r["position"],
        team=team,
        status=(statuses or {}).get(team_id, "alive"),
        played=r["played"],
        won=r["won"],
        drawn=r["drawn"],
        lost=r["lost"],
        goals_for=r["goals_for"],
        goals_against=r["goals_against"],
        goal_difference=r["goal_difference"],
        points=r["points"],
        form=r["form"],
        tied_unresolved=r["tied_unresolved"],
    )


async def standings_page(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> StandingsPage:
    ctx = await _context(db, viewer, tournament_id)
    version, tables = await _tables(db, ctx, tournament_id)
    return StandingsPage(version=version, groups=tables)


async def bracket_page(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> BracketPage:
    await _context(db, viewer, tournament_id)
    snapshot = (
        await db.execute(
            select(BracketSnapshot)
            .where(BracketSnapshot.tournament_id == tournament_id)
            .order_by(BracketSnapshot.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if snapshot is None:
        return BracketPage(version=0, matches=[])
    return BracketPage(version=snapshot.version, matches=snapshot.bracket["matches"])


async def schedule_page(
    db: AsyncSession,
    viewer: Viewer,
    tournament_id: UUID,
    *,
    day: date | None = None,
    pitch_id: UUID | None = None,
    team_id: UUID | None = None,
) -> SchedulePage:
    ctx = await _context(db, viewer, tournament_id)
    zone = ZoneInfo(ctx.tournament.time_zone)
    cards = []
    for m in await competitions.list_matches(db, tournament_id):
        if day and m.starts_at.astimezone(zone).date() != day:
            continue
        if pitch_id and m.pitch_id != pitch_id:
            continue
        if team_id and team_id not in (m.home_team_id, m.away_team_id):
            continue
        cards.append(await _card(db, ctx, m))
    return SchedulePage(matches=cards)


async def scenarios_page(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, team_id: UUID | None
) -> list[ScenarioPage]:
    ctx = await _context(db, viewer, tournament_id)
    current = await db.get(AnalysisVersion, tournament_id)
    if current is None:
        return []
    query = select(ScenarioSnapshot).where(
        ScenarioSnapshot.tournament_id == tournament_id, ScenarioSnapshot.version == current.version
    )
    if team_id:
        query = query.where(ScenarioSnapshot.team_id == team_id)
    rows = (await db.execute(query)).scalars()
    scenarios = [
        ScenarioPage(
            team=ctx.team(s.team_id) or TeamName(id=s.team_id, name=""), scenario=s.scenario
        )
        for s in rows
    ]
    if not ctx.tournament.settings.show_probabilities:
        for page in scenarios:  # junior: factors and words only, no percentages (docs/09)
            page.scenario = {
                k: v for k, v in page.scenario.items() if k not in ("qualify_share", "chances")
            }
            page.scenario["paths"] = [
                {k: v for k, v in p.items() if k != "share"} for p in page.scenario.get("paths", [])
            ]
    return sorted(scenarios, key=lambda p: p.team.name)


async def screen_page(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> ScreenPage:
    ctx = await _context(db, viewer, tournament_id)
    matches = await competitions.list_matches(db, tournament_id)
    now = [m for m in matches if m.status == "live"]
    upcoming: dict[UUID | None, MatchOut] = {}
    for m in matches:
        if m.status == "scheduled" and m.pitch_id not in upcoming:
            upcoming[m.pitch_id] = m
    _, tables = await _tables(db, ctx, tournament_id)
    return ScreenPage(
        now_playing=[await _card(db, ctx, m) for m in now],
        next_up=[await _card(db, ctx, m) for m in upcoming.values()],
        standings=tables,
    )


async def widget_page(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> WidgetPage:
    screen = await screen_page(db, viewer, tournament_id)
    leaders = [t.rows[0] for t in screen.standings if t.rows]
    return WidgetPage(live=screen.now_playing, next=screen.next_up[:5], leaders=leaders)


async def match_page(db: AsyncSession, viewer: Viewer, match_id: UUID) -> MatchPage:
    match = await competitions.get_match(db, match_id)
    ctx = await _context(db, viewer, match.tournament_id)
    return MatchPage(
        match=await _card(db, ctx, match), tournament_id=match.tournament_id, live_access=ctx.live
    )


async def timeline_page(
    db: AsyncSession, viewer: Viewer, match_id: UUID, since_seq: int
) -> TimelinePage:
    match = await competitions.get_match(db, match_id)
    ctx = await _context(db, viewer, match.tournament_id)
    if match.status == "live" and not ctx.live:
        return TimelinePage(events=[])  # the policy hides it while live; everyone after finish
    return TimelinePage(events=await scoring.timeline(db, match_id, since_seq))


async def team_page(db: AsyncSession, viewer: Viewer, team_id: UUID) -> TeamPage:
    team = await competitions.get_team(db, Viewer(), team_id)  # public view: never contacts
    tournaments = await competitions.public_tournaments(db, team_id=team_id)
    if not tournaments:
        raise NotFound()  # teams of draft tournaments are not public yet
    cards = []
    for t in tournaments:
        ctx = await _context(db, viewer, t.id)
        cards += [
            await _card(db, ctx, m)
            for m in await competitions.team_matches(db, team_id)
            if m.tournament_id == t.id
        ]
    journeys = {
        j.tournament_id: j.journey
        for j in (
            await db.execute(select(TeamJourney).where(TeamJourney.team_id == team_id))
        ).scalars()
    }
    return TeamPage(
        id=team.id,
        name=team.name,
        short_name=team.short_name,
        tournaments=[
            {"id": str(t.id), "name": t.name, "status": t.status, "journey": journeys.get(t.id)}
            for t in tournaments
        ],
        matches=cards,
        organisation_id=team.organisation_id,
        age_group=team.age_group,
        players=[
            HubPlayer(id=p.id, display_name=p.display_name, shirt_number=p.shirt_number)
            for p in await competitions.list_players(db, viewer, team_id)
        ],
    )


_STATUS_WORDS = {
    "clinched": "through",
    "eliminated": "out",
    "in_control": "in control",
    "must_win": "must win",
    "alive": "alive",
}


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


async def current_tournament(db: AsyncSession, team_id: UUID) -> TournamentOut | None:
    """The team's live or next tournament, else its latest one."""
    tournaments = await competitions.public_tournaments(db, team_id=team_id)
    for status in ("active", "upcoming"):
        for t in tournaments:
            if t.status == status:
                return t
    return tournaments[0] if tournaments else None


async def team_hub(
    db: AsyncSession, viewer: Viewer, team_id: UUID, tournament_id: UUID | None = None
) -> TeamHub:
    """Everything about one team in one tournament, from read models only."""
    team = await competitions.get_team(db, Viewer(), team_id)
    players = [
        HubPlayer(id=p.id, display_name=p.display_name, shirt_number=p.shirt_number)
        for p in await competitions.list_players(db, viewer, team_id)  # visibility filtered
    ]
    name = TeamName(id=team.id, name=team.name)
    tournament = (
        await competitions.get_tournament(db, viewer, tournament_id)
        if tournament_id
        else await current_tournament(db, team_id)
    )
    if tournament is None:
        return TeamHub(
            team=name,
            tournament=None,
            status_chip=None,
            now_or_next=None,
            what_we_need=[],
            knockout=None,
            matters=[],
            journey=None,
            league=None,
            players=players,
        )
    ctx = await _context(db, viewer, tournament.id)
    matches = [
        m
        for m in await competitions.list_matches(db, tournament.id)
        if team_id in (m.home_team_id, m.away_team_id)
    ]
    current = next((m for m in matches if m.status == "live"), None) or next(
        (m for m in matches if m.status in ("scheduled", "postponed")), None
    )
    _, tables = await _tables(db, ctx, tournament.id)
    league = next((t for t in tables if any(r.team.id == team_id for r in t.rows)), None)
    version = await db.get(AnalysisVersion, tournament.id)
    scenario: dict[str, Any] | None = None
    matters: list[MattersItem] = []
    journey = None
    if version is not None:
        row = (
            await db.execute(
                select(ScenarioSnapshot).where(
                    ScenarioSnapshot.tournament_id == tournament.id,
                    ScenarioSnapshot.team_id == team_id,
                    ScenarioSnapshot.version == version.version,
                )
            )
        ).scalar_one_or_none()
        scenario = row.scenario if row else None
        rel = (
            await db.execute(
                select(RelevanceSnapshot).where(
                    RelevanceSnapshot.tournament_id == tournament.id,
                    RelevanceSnapshot.team_id == team_id,
                    RelevanceSnapshot.version == version.version,
                )
            )
        ).scalar_one_or_none()
        by_id = {str(m.id): m for m in await competitions.list_matches(db, tournament.id)}
        for item in (rel.items if rel else [])[:5]:
            if item["impact"] <= 0:
                continue
            m = by_id.get(item["match_id"])
            matters.append(
                MattersItem(
                    match=await _card(db, ctx, m) if m else None,
                    impact=item["impact"],
                    reason=item["reason"],
                )
            )
        j = await db.get(TeamJourney, (tournament.id, team_id))
        journey = j.journey if j else None
    chip = None
    if league is not None:
        position = next(r.position for r in league.rows if r.team.id == team_id)
        words = _STATUS_WORDS.get(scenario["status"], "") if scenario else ""
        chip = f"{_ordinal(position)} in Group {league.group}" + (f" · {words}" if words else "")
    return TeamHub(
        team=name,
        tournament=HubTournament(id=tournament.id, name=tournament.name, status=tournament.status),
        status_chip=chip,
        now_or_next=await _card(db, ctx, current) if current else None,
        what_we_need=[p["summary"] for p in scenario["paths"]] if scenario else [],
        knockout=scenario.get("knockout") if scenario else None,
        matters=matters,
        journey=journey,
        league=league,
        players=players,
        chances=await _chances(db, viewer, current.id) if current else None,
    )


async def prediction_page(db: AsyncSession, viewer: Viewer, match_id: UUID) -> MatchPrediction:
    """The stored prediction; percentages only when the tournament shows them and the model
    has enough games (`confidence != "none"`)."""
    match = await competitions.get_match(db, match_id)
    ctx = await _context(db, viewer, match.tournament_id)
    row = await db.get(PredictionRecord, match_id)
    if row is None:
        raise NotFound()
    show = ctx.tournament.settings.show_probabilities and row.confidence != "none"
    return MatchPrediction(
        match_id=match_id,
        confidence=row.confidence,
        home_win=(row.home_win_low, row.home_win_high) if show else None,
        draw=(row.draw_low, row.draw_high)
        if show and row.draw_low is not None and row.draw_high is not None
        else None,
        away_win=(row.away_win_low, row.away_win_high) if show else None,
        factors=row.factors,
        model_version=row.model_version,
    )


async def _chances(db: AsyncSession, viewer: Viewer, match_id: UUID) -> dict[str, Any] | None:
    try:
        return (await prediction_page(db, viewer, match_id)).model_dump(mode="json")
    except NotFound:
        return None


async def comparison_page(db: AsyncSession, viewer: Viewer, match_id: UUID) -> dict[str, Any]:
    match = await competitions.get_match(db, match_id)
    await _context(db, viewer, match.tournament_id)
    row = await db.get(TeamComparison, match_id)
    if row is None:
        raise NotFound()
    return row.comparison


async def analysis_page(db: AsyncSession, viewer: Viewer, match_id: UUID) -> dict[str, Any]:
    match = await competitions.get_match(db, match_id)
    ctx = await _context(db, viewer, match.tournament_id)
    row = await db.get(MatchAnalysis, match_id)
    if row is None:
        raise NotFound()
    facts = row.analysis["facts"]
    if not ctx.tournament.settings.show_probabilities:  # juniors: no "pre-match chance" figures
        facts = [f for f in facts if f["kind"] != "upset"]
    return {"facts": facts}
