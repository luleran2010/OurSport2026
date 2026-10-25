"""Project the mock's in-memory data onto the v1 contract (backend/docs/05-api.md).

Mapping rules: clubs are organisations; league games without an event belong to a pseudo
tournament per league (`league:<name>`); slugs become stable UUIDs (`ids.uid`); epoch ms
become UTC datetimes; scores `[home, away]` become `{home_goals, away_goals}`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from .. import club_teams
from .. import players as player_service
from .. import tournaments as TN
from ..mock_data import CLUBS, PLAYERS, SPORTS, TEAMS, is_junior
from ..models import Match, Player, Story, Team, Tournament
from . import schemas as S
from .ids import uid

if TYPE_CHECKING:
    from ..store import FeedStore, Session

HOUR = 3_600_000
AI_LABEL = {"en": "Written by AI from match data", "fi": "Tekoälyn kirjoittama otteluaineistosta",
            "bn": "ম্যাচের তথ্য থেকে এআই লিখেছে"}
_SPORT_CODES = {"ice-hockey": "ice_hockey"}
_AGE = {"senior": "adult"}


def ts(ms: int | None) -> datetime | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, UTC)


def day(ms: int | None) -> date | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, UTC).date()


def sport_code(sport: str) -> str:
    return _SPORT_CODES.get(sport, sport)


def mock_sport(code: str) -> str:
    return next((k for k, v in _SPORT_CODES.items() if v == code), code)


def age_group(team: Team) -> str:
    return _AGE.get(team.age_group, team.age_group)


def sports() -> list[S.SportOut]:
    return [S.SportOut(code=sport_code(s.id), name=s.label) for s in SPORTS if s.id != "all"]


# ---- organisations and teams ---------------------------------------------------------------


def org_summary(club_id: str) -> S.OrganisationSummary:
    c = CLUBS[club_id]
    return S.OrganisationSummary(
        id=uid("org", c.id), name=c.name, slug=c.id, kind="club", town=c.city,
        sports=[sport_code(s) for s in c.sports], logo_url=c.logo_url,
        colors=S.OrganisationColors(primary=c.color, secondary=c.secondary_color),
    )


def team_name(team: Team) -> S.TeamName:
    return S.TeamName(id=uid("team", team.id), name=team.name, short_name=team.short)


def team_out(team: Team) -> S.TeamOut:
    return S.TeamOut(id=uid("team", team.id), name=team.name, short_name=team.short, age_group=age_group(team),
                     organisation_id=uid("org", team.club_id) if team.club_id in CLUBS else None)


# ---- tournaments (events, plus one pseudo tournament per league) ---------------------------


@dataclass
class TView:
    key: str  # tournament slug, or "league:<name>"
    name: str
    sport: str
    club_id: str | None
    starts_ms: int
    ends_ms: int
    junior: bool
    groups: list[tuple[str, str, list[str]]] = field(default_factory=list)  # (id, name, team slugs)
    event: Tournament | None = None
    team_ids: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return uid("tournament", self.key)


def _league_key(league: str) -> str:
    return "league:" + re.sub(r"[^a-z0-9]+", "-", league.lower()).strip("-")


def tournament_key(m: Match) -> str:
    return m.tournament_id or _league_key(m.league)


def tournaments(store: FeedStore) -> dict[str, TView]:
    out: dict[str, TView] = {}
    for t in store.tournaments.values():
        out[t.id] = TView(
            key=t.id, name=t.name, sport=t.sport, club_id=t.organiser.club_id, starts_ms=t.starts_at,
            ends_ms=t.ends_at, junior=t.junior, groups=[(g.id, g.name, list(g.team_ids)) for g in t.groups],
            event=t, team_ids=[x.id for x in t.teams],
        )
    for m in store.matches:
        if m.tournament_id:
            continue
        key = _league_key(m.league)
        times = [x for x in (m.starts_at, m.ended_at) if x is not None] or [store.now]
        view = out.get(key)
        if view is None:
            view = out[key] = TView(key=key, name=m.league, sport=m.sport, club_id=m.home.club_id,
                                    starts_ms=min(times), ends_ms=max(times), junior=False)
        view.starts_ms, view.ends_ms = min(view.starts_ms, *times), max(view.ends_ms, *times)
        for team in (m.home, m.away):
            if team.id not in view.team_ids:
                view.team_ids.append(team.id)
                view.junior = view.junior or is_junior(team)
    return out


def tournament_status(view: TView, now: int) -> str:
    if now < view.starts_ms:
        return "upcoming"
    return "active" if now <= view.ends_ms + 2 * HOUR else "finished"


# live access per tournament (the organiser's setting; the backend's default is "public")
LIVE_ACCESS: dict[str, str] = {}


def _settings(view: TView) -> S.TournamentSettings:
    return S.TournamentSettings(
        languages=["fi", "en", "bn"], show_probabilities=not view.junior,
        live_access=LIVE_ACCESS.get(view.key, "public"),
        filming_policy="consent_required" if view.junior else "notice", filming_confirmed=True,
    )


def tournament_out(view: TView, now: int) -> S.TournamentOut:
    return S.TournamentOut(
        id=view.id, organisation_id=uid("org", view.club_id or "independent"), name=view.name, slug=view.key,
        sport=sport_code(view.sport), status=tournament_status(view, now), age_group="u17" if view.junior else "adult",
        is_junior=view.junior, time_zone="Europe/Helsinki", starts_on=day(view.starts_ms), ends_on=day(view.ends_ms),
        settings=_settings(view),
    )


def list_item(view: TView, now: int) -> S.TournamentListItem:
    club = CLUBS.get(view.club_id or "")
    return S.TournamentListItem(**tournament_out(view, now).model_dump(), organisation_name=club.name if club else "",
                                team_count=len(view.team_ids))


def can_watch_live(profile: Session | None, tournament: str) -> bool:
    """The live access policy as the backend applies it: public: everyone; members: any
    signed-in viewer; premium: staff only (until subscriptions)."""
    policy = LIVE_ACCESS.get(tournament, "public")
    if policy == "public":
        return True
    signed_in = bool(profile and profile.signed_in)
    return signed_in if policy == "members" else bool(signed_in and getattr(profile, "v1_staff", False))


def tournament_page(store: FeedStore, view: TView, profile: Session | None) -> S.TournamentPage:
    out = tournament_out(view, store.now)
    club = CLUBS.get(view.club_id or "")
    return S.TournamentPage(
        id=out.id, name=out.name, slug=out.slug, sport=out.sport, status=out.status, age_group=out.age_group,
        starts_on=out.starts_on, ends_on=out.ends_on, time_zone=out.time_zone, languages=out.settings.languages,
        live_access=out.settings.live_access, show_probabilities=out.settings.show_probabilities,
        groups=[S.GroupPage(id=uid("group", f"{view.key}:{gid}"), name=name,
                            teams=[team_name(TEAMS[t]) for t in teams if t in TEAMS])
                for gid, name, teams in view.groups],
        live_now=sum(1 for m in store.matches if tournament_key(m) == view.key and m.status == "live"),
        organisation_id=out.organisation_id, organisation_name=club.name if club else "", is_junior=view.junior,
    )


# ---- matches ---------------------------------------------------------------------------------

_STATUS = {"upcoming": "scheduled", "live": "live", "finished": "finished"}


def _period_number(period: str | None) -> int | None:
    found = re.match(r"(\d)", period or "")
    return int(found.group(1)) if found else None


def score_of(m: Match) -> S.Score | None:
    if m.score is None:
        return None
    return S.Score(home_goals=m.score[0], away_goals=m.score[1], period=_period_number(m.period),
                   finished=m.status == "finished")


def starts_of(m: Match) -> int:
    return m.starts_at or (m.ended_at - 2 * HOUR if m.ended_at else 0)


def card(m: Match, profile: Session | None) -> S.MatchCard:
    group = m.stage if (m.stage or "").startswith(("Group", "League")) else None
    stage = "group" if group or not m.stage else re.sub(r"[^a-z]+", "_", m.stage.lower()).strip("_")
    hidden = m.status == "live" and not can_watch_live(profile, tournament_key(m))  # live access policy
    return S.MatchCard(
        id=uid("match", m.id), tournament_id=uid("tournament", tournament_key(m)), sport=sport_code(m.sport),
        code=m.id.upper(), stage=stage, group=group, pitch=m.venue, starts_at=ts(starts_of(m)), status=_STATUS[m.status],
        home=team_name(m.home), away=team_name(m.away), home_source=None, away_source=None,
        score=None if hidden else score_of(m), data_level="results" if m.data_level == "results_only" else "events",
    )


def match_list(matches: list[Match], profile: Session | None, when: str | None, now: int) -> list[S.MatchCard]:
    if when == "live":
        matches = [m for m in matches if m.status == "live"]
    elif when == "today":
        today = day(now)
        matches = [m for m in matches if day(starts_of(m)) == today]
    elif when == "upcoming":
        matches = [m for m in matches if m.status == "upcoming" and starts_of(m) >= now][:50]
    elif when == "recent":
        done = sorted((m for m in matches if m.status == "finished"), key=lambda m: -(m.ended_at or 0))[:50]
        return [card(m, profile) for m in done]
    return [card(m, profile) for m in sorted(matches, key=starts_of)]


_TIMELINE_TYPES = {"kickoff": "period_start", "goal": "goal", "fulltime": "period_end", "correction": "undo"}


def timeline(store: FeedStore, m: Match, since_seq: int = 0) -> list[dict]:
    """Scorer-entered and simulated events (AI insights are commentary, not events)."""
    out = []
    for seq, e in enumerate((e for e in store.timelines.get(m.id, []) if not e.ai), start=1):
        if seq <= since_seq:
            continue
        kind = _TIMELINE_TYPES.get(e.kind, "period_end" if e.text.startswith("End") else "period_start"
                                   if e.kind == "period" else "event")
        out.append({"seq": seq, "type": kind, "team_id": uid("team", e.team_id) if e.team_id else None,
                    "period": _period_number(m.period), "clock": f"{e.minute}:00", "undone": False,
                    "payload": {"text": e.text}})
    return out


def commentary(store: FeedStore, m: Match) -> list[S.CommentaryOut]:
    items = [e for e in store.timelines.get(m.id, []) if e.ai]
    return [
        S.CommentaryOut(id=uid("commentary", e.id), match_id=uid("match", m.id), seq=n, kind="moment", moments=[],
                        items=[S.CommentaryLine(language="en", text=e.text, fact_ids=[])], author_type="ai",
                        ai_labels={"en": AI_LABEL["en"]}, created_at=ts(e.at))
        for n, e in reversed(list(enumerate(items, start=1)))
    ]


# ---- standings, scenarios, rules -------------------------------------------------------------

_SCENARIO_STATUS = {"through": "clinched", "out": "eliminated", "alive": "alive"}


def standings(store: FeedStore, view: TView) -> S.StandingsPage:
    if view.event is None:
        return S.StandingsPage(version=0, groups=[])
    page = TN.standings(view.event, store.matches, store.now)
    return S.StandingsPage(version=store.now // 1000, groups=[
        S.GroupTable(group=g.name, group_id=uid("group", f"{view.key}:{g.id}"), rows=[
            S.StandingsRow(position=r.position, team=team_name(r.team), played=r.played, won=r.won, drawn=r.drawn,
                           lost=r.lost, goals_for=r.scored, goals_against=r.conceded,
                           goal_difference=r.scored - r.conceded, points=r.points, form=list(r.form),
                           tied_unresolved=False, status=r.status)
            for r in g.rows
        ]) for g in page.groups
    ])


def scenarios(store: FeedStore, view: TView, team_slug: str | None) -> list[S.ScenarioPage]:
    if view.event is None:
        return []
    cards = TN.scenarios(view.event, store.matches, store.now).cards
    out = []
    for c in cards:
        if team_slug and c.team.id != team_slug:
            continue
        paths = [{"outcome": "any", "result": c.headline, "summary": c.detail, "share": None}]
        out.append(S.ScenarioPage(team=team_name(c.team), scenario={
            "status": _SCENARIO_STATUS[c.status], "exact": True, "qualify_share": None, "paths": paths,
            "knockout": None,
        }))
    return sorted(out, key=lambda p: p.team.name)


def rules(view: TView, lang: str | None) -> S.RulesSummary:
    lines = []
    if view.event is not None:
        lines = [f"{s.heading}: {s.text}" for s in TN.rules_summary(view.event).sections]
    return S.RulesSummary(tournament_id=view.id, version=1, language=lang or "en", lines=lines)


# ---- players -----------------------------------------------------------------------------------


def visible(p: Player, profile: Session | None) -> bool:
    """public: everyone; members: signed-in viewers; private: only linked family (docs/09)."""
    seen = player_service.visibility(p)
    signed_in = bool(profile and profile.signed_in)
    family = bool(profile and profile.is_guardian_of(p.id)) and club_teams.guardian_access(p)  # hidden: nobody
    return seen == "public" or (seen == "members" and signed_in) or family


def hub_player(p: Player) -> S.HubPlayer:
    return S.HubPlayer(id=uid("player", p.id), display_name=p.name, shirt_number=p.number)


def team_players(team: Team, profile: Session | None) -> list[S.HubPlayer]:
    return [hub_player(p) for p in PLAYERS if p.team.id == team.id and visible(p, profile)]


def player_goals(store: FeedStore, p: Player) -> int:
    stats = player_service.profile(store, p).stats
    return next((int(s.value) for s in stats if s.key == "goals" and s.value.isdigit()), 0)


# ---- stories -----------------------------------------------------------------------------------


def story_rows(store: FeedStore, story: Story) -> list[S.StoryOut]:
    """One row per language (the backend stores each language as its own story)."""
    from .. import match_detail as MD

    if story.match_id:
        subject_type, subject = "match", uid("match", story.match_id)
    elif story.tournament_id:
        subject_type, subject = "tournament", uid("tournament", story.tournament_id)
    elif story.club_id:
        subject_type, subject = "organisation", uid("org", story.club_id)
    else:
        subject_type, subject = "team", uid("team", story.team_ids[0] if story.team_ids else "none")
    m = store.get_match(story.match_id) if story.match_id else None
    tournament = story.tournament_id or (tournament_key(m) if m else None)
    tag = story.tag.lower()
    kind = "preview" if "preview" in tag else "report" if "report" in tag else "news"
    out = []
    for lang in dict.fromkeys([story.language, *story.available_languages]):
        text = MD.localized(story, lang)
        ai = story.author_type == "ai"
        out.append(S.StoryOut(
            id=uid("story", f"{story.id}:{lang}"), tournament_id=uid("tournament", tournament) if tournament else None,
            kind=kind, subject_type=subject_type, subject_id=subject, language=lang if lang in AI_LABEL else "en",
            headline=text.title, body="\n\n".join([text.summary, *text.body]),
            author_type="ai" if ai else "human", ai_label=AI_LABEL.get(lang, AI_LABEL["en"]) if ai else None,
            published_at=ts(story.published_at), corrected_at=ts(story.corrected_at), version=1,
        ))
    return out


def stories_newest(store: FeedStore, keep) -> list[S.StoryOut]:
    rows = []
    for st in sorted(store.stories, key=lambda s: -s.published_at):
        if st.published_at <= store.now and keep(st):
            rows += story_rows(store, st)
    return rows
