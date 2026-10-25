"""The OurSport API v1 (backend/docs/05-api.md) served from the mock's in-memory data.

Paths, operation ids, parameters and schemas are the backend's; `tests/test_contract.py`
checks them against backend/docs/frontend-handoff/openapi.json.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from pydantic import RootModel

from .. import scoring as legacy_scoring
from .. import sport_events
from ..main_store import store
from ..mock_data import CLUBS, PLAYERS, TEAMS
from ..models import EventIn as LegacyEventIn
from ..models import Match
from . import auth as A
from . import project as P
from . import schemas as S
from .errors import problem
from .ids import slug, uid

# As in the backend: signing in needs no CSRF token (there is no session to protect yet).
_NO_CSRF = {"/api/v1/auth/signup", "/api/v1/auth/magic-link", "/api/v1/auth/magic-link/verify",
            "/api/v1/auth/demo-login"}


def _csrf(request: Request) -> None:
    if request.url.path not in _NO_CSRF:
        A.check_csrf(request)


router = APIRouter(prefix="/api/v1", dependencies=[Depends(_csrf)])
_DEVICE = "v1-api"  # the mock's scorer state keeps a device id per event


def viewer(request: Request) -> A.Viewer:
    return A.viewer_of(store, request)


Who = Annotated[A.Viewer, Depends(viewer)]


def member(who: Who) -> A.Viewer:
    if not who.is_member:
        raise problem(401, "not_authenticated")
    return who


Member = Annotated[A.Viewer, Depends(member)]


def _origin(request: Request) -> str:
    return request.headers.get("origin") or "http://localhost:5173"


# ---- paging: an opaque offset cursor (the backend's are keyset; both are opaque) ------------


def _page(rows: list, cursor: str | None, limit: int) -> tuple[list, str | None]:
    start = 0
    if cursor:
        try:
            start = int(json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))["o"])
        except (ValueError, KeyError, TypeError):
            raise problem(422, "validation_error", "Invalid pagination cursor",
                          [{"field": "query.cursor", "message": "invalid cursor"}]) from None
    chunk = rows[start:start + limit]
    more = start + limit < len(rows)
    token = base64.urlsafe_b64encode(json.dumps({"o": start + limit}).encode()).decode().rstrip("=")
    return chunk, token if more else None


Cursor = Annotated[str | None, Query(max_length=1024)]
Limit = Annotated[int, Query(ge=1, le=100)]


# ---- lookups -------------------------------------------------------------------------------


def _views() -> dict[str, P.TView]:
    return P.tournaments(store)


def _view(tournament_id: str) -> P.TView:
    view = _views().get(slug("tournament", tournament_id))
    if view is None or not _reachable(view):
        raise problem(404, "not_found")
    return view


def _reachable(view: P.TView, listed: bool = False) -> bool:
    """An organiser can make an event unlisted (link only) or hidden (P4 settings)."""
    from .. import event_manage

    return view.event is None or event_manage.visible_to_fans(store, view.key, listed)


def _match(match_id: str) -> Match:
    m = store.get_match(slug("match", match_id))
    if m is None:
        raise problem(404, "not_found")
    return m


def _team(team_id: str):
    team = TEAMS.get(slug("team", team_id))
    if team is None:
        raise problem(404, "not_found")
    return team


def _club(organisation_id: str):
    club = CLUBS.get(slug("org", organisation_id))
    if club is None:
        raise problem(404, "not_found")
    return club


# ---- auth ----------------------------------------------------------------------------------


@router.post("/auth/signup", status_code=202, response_model=S.Accepted, operation_id="signUp", tags=["auth"])
def sign_up(body: S.SignupRequest, request: Request) -> S.Accepted:
    """Start a sign-up: emails a magic link that creates the account. Always 202."""
    email = body.email.strip().lower()
    A.send_link(store, email, body.model_dump(), _origin(request))
    return S.Accepted()


@router.post("/auth/magic-link", status_code=202, response_model=S.Accepted, operation_id="requestMagicLink",
             tags=["auth"])
def request_magic_link(body: S.MagicLinkRequest, request: Request) -> S.Accepted:
    """Email a sign-in link. Always 202, whether or not the email has an account."""
    email = body.email.strip().lower()
    if email in A.state(store).accounts:
        A.send_link(store, email, None, _origin(request))
    return S.Accepted()


@router.post("/auth/magic-link/verify", response_model=S.SessionInfo, operation_id="verifyMagicLink",
             tags=["auth"])
def verify_magic_link(body: S.VerifyRequest, response: Response) -> S.SessionInfo:
    """Open a magic link: sets the session cookies (and creates a pending account)."""
    from ..store import Session

    s = A.state(store)
    link = s.links.pop(body.token, None)
    if link is None or link["expires"] < A._now():
        raise problem(401, "not_authenticated", "This link has expired or was already used")
    created = False
    profile = s.accounts.get(link["email"])
    if profile is None:
        signup = link["signup"] or {}
        profile = Session(id=uid("user", link["email"]), signed_in=True, email=link["email"],
                          name=signup.get("display_name") or link["email"].split("@")[0],
                          language=signup.get("language", "en"), account_email=link["email"])
        profile.teams, profile.clubs, profile.tournaments = [], [], []
        follow_target = signup.get("follow")
        if follow_target:
            _follow(profile, follow_target["target_type"], follow_target["target_id"], primary=True)
        s.accounts[link["email"]] = profile
        created = True
    csrf = A.issue(store, response, profile)
    return S.SessionInfo(user_id=_me(profile).id, csrf_token=csrf, account_created=created)


@router.post("/auth/demo-login", response_model=S.SessionInfo, operation_id="demoLogin", tags=["auth"])
def demo_login(body: S.DemoLoginRequest, response: Response) -> S.SessionInfo:
    """Development only (404 elsewhere): sign in as a demo fan, organiser or editor."""
    from ..store import Session

    s = A.state(store)
    key = f"demo:{body.persona}"
    profile = s.accounts.get(key)
    if profile is None:
        profile = Session(id=uid("user", key))
        # fan: the mock's Premium demo fan (also a club admin for the portal pages);
        # organiser: runs every event (the publisher pages); editor: the sports desk.
        profile.sign_in_demo({"fan": "premium", "organiser": "publisher", "editor": "editor"}[body.persona])
        profile.v1_staff = body.persona == "organiser"
        s.accounts[key] = profile
    csrf = A.issue(store, response, profile)
    return S.SessionInfo(user_id=_me(profile).id, csrf_token=csrf)


@router.post("/auth/refresh", response_model=S.SessionInfo, operation_id="refreshSession", tags=["auth"])
def refresh_session(request: Request, response: Response,
                    oursport_refresh: Annotated[str | None, Cookie()] = None) -> S.SessionInfo:
    """Rotate the refresh token and issue a new access token."""
    profile, csrf = A.rotate(store, request, response)
    return S.SessionInfo(user_id=_me(profile).id, csrf_token=csrf)


@router.post("/auth/logout", status_code=204, operation_id="logout", tags=["auth"])
def logout(request: Request, who: Member, oursport_refresh: Annotated[str | None, Cookie()] = None) -> Response:
    """End this device's session."""
    response = Response(status_code=204)
    A.end(store, request, response)
    return response


@router.post("/auth/logout-all", status_code=204, operation_id="logoutAll", tags=["auth"])
def logout_all(request: Request, who: Member) -> Response:
    """End every session of this account."""
    response = Response(status_code=204)
    A.end(store, request, response, everywhere=True)
    return response


# ---- me --------------------------------------------------------------------------------------

_FOLLOW_KINDS = {"organisation": "club", "team": "team", "tournament": "tournament"}
_TARGET_TYPES = {v: k for k, v in _FOLLOW_KINDS.items()}
_ID_KIND = {"club": "org", "team": "team", "tournament": "tournament"}


def _follow_id(kind: str, target: str) -> str:
    return uid("follow", f"{kind}:{target}")


def _refs(profile) -> list[S.FollowRef]:
    primary = getattr(profile, "v1_primary", None)
    return [
        S.FollowRef(id=_follow_id(kind, t), target_type=_TARGET_TYPES[kind], target_id=uid(_ID_KIND[kind], t),
                    is_primary=kind == "team" and t == primary)
        for kind in ("team", "club", "tournament") for t in profile.follows_of(kind)
    ]


def _me(profile) -> S.Me:
    from .. import event_manage

    event_manage.my_event_rows(store, profile)  # signing in activates an event's scorer invite (P4)
    legacy = profile.me()
    plan = None
    if legacy.premium:
        plan = S.PlanInfo(tier="premium", granted_by_organisation_id=uid("org", legacy.premium.via_club_id or ""),
                          valid_until=P.ts(legacy.premium.valid_until).isoformat().replace("+00:00", "Z")
                          if legacy.premium.valid_until else None)
    staff = []
    if getattr(profile, "v1_staff", False):
        staff = [S.StaffTournament(tournament_id=v.id, tournament_name=v.name,
                                   organisation_id=uid("org", v.club_id or "independent"), role="owner")
                 for v in _views().values() if v.event is not None]
    primary = getattr(profile, "v1_primary", None)
    return S.Me(
        id=uid("user", profile.email or profile.id), display_name=profile.name, email=profile.email or "",
        language=profile.language, time_zone=getattr(profile, "time_zone", "Europe/Helsinki"), plan=plan,
        memberships=[S.Membership(organisation_id=uid("org", c), organisation_name=CLUBS[c].name, role=r)
                     for c, r in profile.roles if c in CLUBS and r == "admin"],
        staff_tournaments=staff,
        global_roles=["editor"] if profile.is_editor() else [],
        primary_team_id=uid("team", primary) if primary else None,
        family_player_ids=[uid("player", p) for p in profile.family],
        follows=_refs(profile),
        unread_notifications=store.log.page(profile, 1, None).unread_count,
    )


@router.get("/me", response_model=S.Me, operation_id="getMe", tags=["me"])
def get_me(who: Member) -> S.Me:
    """The signed-in user's profile."""
    return _me(who.profile)


@router.patch("/me", response_model=S.Me, operation_id="updateMe", tags=["me"])
def update_me(body: S.MePatch, who: Member) -> S.Me:
    """Change display name, language or time zone."""
    p = who.profile
    if body.display_name is not None:
        p.name = body.display_name.strip()
    if body.language is not None:
        p.language = body.language
    if body.time_zone is not None:
        p.time_zone = body.time_zone
    return _me(p)


@router.delete("/me", status_code=204, operation_id="deleteMe", tags=["me"])
def delete_me(request: Request, who: Member) -> Response:
    """Delete your account and sign out everywhere."""
    s = A.state(store)
    s.accounts = {k: v for k, v in s.accounts.items() if v is not who.profile}
    store.delete_profile(who.profile)
    response = Response(status_code=204)
    A.end(store, request, response, everywhere=True)
    return response


# ---- catalogue -------------------------------------------------------------------------------

SportList = RootModel[list[S.SportOut]]


@router.get("/sports", response_model=list[S.SportOut], operation_id="listSports", tags=["fan"])
def list_sports() -> list[S.SportOut]:
    """The sports OurSport runs."""
    return P.sports()


@router.get("/organisations", response_model=S.PageOrganisations, operation_id="listOrganisations", tags=["fan"])
def list_organisations(cursor: Cursor = None, limit: Limit = 20,
                       sport: Annotated[str | None, Query(max_length=20)] = None) -> S.PageOrganisations:
    """Every organisation (clubs, associations, communities), by name."""
    rows = [P.org_summary(c) for c in sorted(CLUBS, key=lambda c: CLUBS[c].name)]
    if sport:
        rows = [o for o in rows if sport in o.sports]
    items, nxt = _page(rows, cursor, limit)
    return S.PageOrganisations(items=items, next_cursor=nxt)


@router.get("/tournaments", response_model=S.PageTournaments, operation_id="listTournaments", tags=["fan"])
def list_tournaments(cursor: Cursor = None, limit: Limit = 20, organisation_id: str | None = None,
                     sport: Annotated[str | None, Query(max_length=20)] = None,
                     status: Literal["upcoming", "active", "finished"] | None = None) -> S.PageTournaments:
    """Published tournaments, newest first."""
    views = [v for v in _views().values() if _reachable(v, listed=True)]
    rows = [P.list_item(v, store.now) for v in sorted(views, key=lambda v: -v.starts_ms)]
    if organisation_id:
        rows = [t for t in rows if t.organisation_id == uid("org", slug("org", organisation_id))]
    if sport:
        rows = [t for t in rows if t.sport == sport]
    if status:
        rows = [t for t in rows if t.status == status]
    items, nxt = _page(rows, cursor, limit)
    return S.PageTournaments(items=items, next_cursor=nxt)


def _team_item(team, views: dict[str, P.TView]) -> S.TeamListItem:
    where = [v for v in sorted(views.values(), key=lambda v: -v.starts_ms) if team.id in v.team_ids]
    return S.TeamListItem(**P.team_out(team).model_dump(), sports=[P.sport_code(team.sport)],
                          tournament_ids=[v.id for v in where])


@router.get("/teams", response_model=S.PageTeams, operation_id="listTeams", tags=["fan"])
def list_teams(cursor: Cursor = None, limit: Limit = 20, tournament_id: str | None = None,
               organisation_id: str | None = None) -> S.PageTeams:
    """Teams of published tournaments, by name."""
    views = _views()
    teams = sorted(TEAMS.values(), key=lambda t: (t.name, t.id))
    if tournament_id:
        view = _view(tournament_id)
        teams = [t for t in teams if t.id in view.team_ids]
    if organisation_id:
        teams = [t for t in teams if t.club_id == slug("org", organisation_id)]
    items, nxt = _page([_team_item(t, views) for t in teams], cursor, limit)
    return S.PageTeams(items=items, next_cursor=nxt)


TeamList = RootModel[list[S.TeamOut]]


@router.get("/organisations/{organisation_id}/teams", response_model=list[S.TeamOut],
            operation_id="listOrganisationTeams", tags=["fan"])
def organisation_teams(organisation_id: str) -> list[S.TeamOut]:
    """An organisation's teams (no contact details)."""
    club = _club(organisation_id)
    return [P.team_out(TEAMS[t]) for t in club.team_ids if t in TEAMS]


@router.get("/search", response_model=S.SearchResult, operation_id="search", tags=["fan"])
def search(q: Annotated[str, Query(min_length=2, max_length=80)],
           type: Literal["organisation", "tournament", "team", "player"] | None = None,
           sport: Annotated[str | None, Query(max_length=20)] = None,
           region: Annotated[str | None, Query(max_length=80)] = None,
           limit: Annotated[int, Query(ge=1, le=50)] = 10) -> S.SearchResult:
    """Organisations, published tournaments, their teams and public players by name."""
    needle = q.strip().lower()
    hits: list[S.SearchHit] = []
    if type in (None, "organisation"):
        clubs = [c for c in CLUBS.values() if needle in c.name.lower()
                 and (not region or region.lower() in c.city.lower()) and (not sport or P.mock_sport(sport) in c.sports)]
        hits += [S.SearchHit(type="organisation", id=uid("org", c.id), name=c.name, detail=c.city) for c in clubs[:limit]]
    if type in (None, "tournament"):
        views = [v for v in _views().values() if v.event and needle in v.name.lower()
                 and (not sport or P.sport_code(v.sport) == sport)]
        hits += [S.SearchHit(type="tournament", id=v.id, name=v.name, detail=P.sport_code(v.sport)) for v in views[:limit]]
    if type in (None, "team"):
        teams = [t for t in TEAMS.values() if needle in t.name.lower()]
        hits += [S.SearchHit(type="team", id=uid("team", t.id), name=t.name) for t in teams[:limit]]
    if type in (None, "player"):
        players = [p for p in PLAYERS if needle in p.name.lower() and P.visible(p, None)]
        hits += [S.SearchHit(type="player", id=uid("player", p.id), name=p.name, detail=p.team.name)
                 for p in players[:limit]]
    return S.SearchResult(query=q, hits=hits)


@router.get("/organisations/{organisation_id}", response_model=S.OrganisationPage, operation_id="getOrganisation",
            tags=["fan"])
def get_organisation(organisation_id: str) -> S.OrganisationPage:
    """An organisation and its published tournaments."""
    club = _club(organisation_id)
    views = [v for v in _views().values() if v.club_id == club.id and v.event is not None]
    return S.OrganisationPage(**P.org_summary(club.id).model_dump(),
                              sponsors=[s.model_dump(mode="json") for s in club.sponsors],
                              tournaments=[P.tournament_out(v, store.now) for v in views])


# ---- fan reads -------------------------------------------------------------------------------

When = Literal["live", "today", "upcoming", "recent"]


def _now() -> datetime:
    return datetime.now(UTC)


@router.get("/matches", response_model=S.MatchList, operation_id="listMatches", tags=["fan"])
def list_matches(who: Who, when: When | None = None) -> S.MatchList:
    """Matches of every published tournament (scores per live access): the app's feed."""
    return S.MatchList(matches=P.match_list(store.matches, who.profile, when, store.now),
                       server_time=_now())


@router.get("/organisations/{organisation_id}/matches", response_model=S.MatchList,
            operation_id="listOrganisationMatches", tags=["fan"])
def organisation_matches(organisation_id: str, who: Who, when: When | None = None) -> S.MatchList:
    """Matches of an organisation's published tournaments."""
    club = _club(organisation_id)
    team_ids = set(club.team_ids)
    mine = [m for m in store.matches if m.home.id in team_ids or m.away.id in team_ids]
    return S.MatchList(matches=P.match_list(mine, who.profile, when, store.now),
                       server_time=_now())


@router.get("/tournaments/{tournament_id}", response_model=S.TournamentPage, operation_id="getTournament",
            tags=["fan"])
def get_tournament(tournament_id: str, who: Who) -> S.TournamentPage:
    """Tournament, groups, status, fan-visible settings, live-now count."""
    return P.tournament_page(store, _view(tournament_id), who.profile)


def _matches_of(view: P.TView) -> list[Match]:
    return [m for m in store.matches if P.tournament_key(m) == view.key]


@router.get("/tournaments/{tournament_id}/live", response_model=S.LivePage, operation_id="getLive", tags=["fan"])
def get_live(tournament_id: str, who: Who) -> S.LivePage:
    """All live matches now (scores per the live access policy): the livecast page."""
    view = _view(tournament_id)
    return S.LivePage(matches=P.match_list(_matches_of(view), who.profile, "live", store.now))


@router.get("/tournaments/{tournament_id}/standings", response_model=S.StandingsPage, operation_id="getStandings",
            tags=["fan"])
def get_standings(tournament_id: str) -> S.StandingsPage:
    """Standings per group."""
    return P.standings(store, _view(tournament_id))


@router.get("/tournaments/{tournament_id}/schedule", response_model=S.SchedulePage, operation_id="getSchedule",
            tags=["fan"])
def get_schedule(tournament_id: str, who: Who, day: str | None = None, pitch_id: str | None = None,
                 team_id: str | None = None) -> S.SchedulePage:
    """The schedule, filtered by day, pitch or team."""
    cards = P.match_list(_matches_of(_view(tournament_id)), who.profile, None, store.now)
    if day:
        cards = [c for c in cards if c.starts_at.date().isoformat() == day]
    if team_id:
        cards = [c for c in cards if team_id in (c.home and c.home.id, c.away and c.away.id)]
    return S.SchedulePage(matches=cards)


ScenarioList = RootModel[list[S.ScenarioPage]]


@router.get("/tournaments/{tournament_id}/scenarios", response_model=list[S.ScenarioPage],
            operation_id="getScenarios", tags=["fan"])
def get_scenarios(tournament_id: str, team_id: str | None = None) -> list[S.ScenarioPage]:
    """What each team needs."""
    return P.scenarios(store, _view(tournament_id), slug("team", team_id) if team_id else None)


@router.get("/tournaments/{tournament_id}/rules/summary", response_model=S.RulesSummary,
            operation_id="getRulesSummary", tags=["rules"])
def get_rules(tournament_id: str, lang: Literal["fi", "en", "bn"] | None = None) -> S.RulesSummary:
    """The plain-language rules summary."""
    return P.rules(_view(tournament_id), lang)


@router.get("/matches/{match_id}", response_model=S.MatchPage, operation_id="getMatch", tags=["fan"])
def get_match(match_id: str, who: Who) -> S.MatchPage:
    """A match with teams, pitch, result and live score (per live access)."""
    m = _match(match_id)
    live = P.can_watch_live(who.profile, P.tournament_key(m))
    return S.MatchPage(match=P.card(m, who.profile), tournament_id=uid("tournament", P.tournament_key(m)), live_access=live)


@router.get("/matches/{match_id}/timeline", response_model=S.TimelinePage, operation_id="getTimeline",
            tags=["fan"])
def get_timeline(match_id: str, who: Who, since_seq: Annotated[int, Query(ge=0)] = 0) -> S.TimelinePage:
    """Events after `since_seq` (per live access while live; everyone after the finish)."""
    m = _match(match_id)
    if m.status == "live" and not P.can_watch_live(who.profile, P.tournament_key(m)):
        return S.TimelinePage(events=[])
    return S.TimelinePage(events=P.timeline(store, m, since_seq))


@router.get("/matches/{match_id}/commentary", response_model=list[S.CommentaryOut],
            operation_id="getMatchCommentary", tags=["fan"])
def get_commentary(match_id: str, who: Who) -> list[S.CommentaryOut]:
    """Live commentary lines, newest first (AI-labelled)."""
    m = _match(match_id)
    if m.status == "live" and not P.can_watch_live(who.profile, P.tournament_key(m)):
        return []
    return P.commentary(store, m)


@router.get("/teams/{team_id}", response_model=S.TeamPage, operation_id="getTeam", tags=["fan"])
def get_team(team_id: str, who: Who) -> S.TeamPage:
    """Team, its tournaments, fixtures, results and the players this viewer may see."""
    team = _team(team_id)
    views = [v for v in _views().values() if team.id in v.team_ids]
    mine = [m for m in store.matches if team.id in (m.home.id, m.away.id)]
    return S.TeamPage(
        id=uid("team", team.id), name=team.name, short_name=team.short,
        tournaments=[{"id": v.id, "name": v.name, "status": P.tournament_status(v, store.now), "journey": None}
                     for v in views],
        matches=P.match_list(mine, who.profile, None, store.now),
        organisation_id=uid("org", team.club_id) if team.club_id in CLUBS else None,
        age_group=P.age_group(team), players=P.team_players(team, who.profile),
    )


@router.get("/players/{player_id}", response_model=S.PlayerPage, operation_id="getPlayer", tags=["fan"])
def get_player(player_id: str, who: Who) -> S.PlayerPage:
    """A player page; 404 for anyone the visibility rules hide the player from."""
    p = next((x for x in PLAYERS if x.id == slug("player", player_id)), None)
    if p is None or not P.visible(p, who.profile):
        raise problem(404, "not_found")
    views = [v for v in _views().values() if p.team.id in v.team_ids]
    return S.PlayerPage(id=uid("player", p.id), display_name=p.name, shirt_number=p.number,
                        team=P.team_name(p.team), goals=P.player_goals(store, p),
                        tournaments=[{"id": v.id, "name": v.name} for v in views])


# ---- stories ---------------------------------------------------------------------------------

Lang = Annotated[Literal["fi", "en", "bn"] | None, Query()]
StoryList = RootModel[list[S.StoryOut]]


def _lang(rows: list[S.StoryOut], lang: str | None) -> list[S.StoryOut]:
    return [r for r in rows if not lang or r.language == lang]


@router.get("/tournaments/{tournament_id}/stories", response_model=list[S.StoryOut],
            operation_id="getTournamentStories", tags=["fan"])
def tournament_stories(tournament_id: str, lang: Lang = None) -> list[S.StoryOut]:
    """Published stories of a tournament, newest first (every language unless `lang`)."""
    view = _view(tournament_id)
    match_ids = {m.id for m in _matches_of(view)}
    rows = P.stories_newest(store, lambda s: s.tournament_id == view.key or s.match_id in match_ids)
    return _lang(rows, lang)


@router.get("/matches/{match_id}/stories", response_model=list[S.StoryOut], operation_id="getMatchStories",
            tags=["fan"])
def match_stories(match_id: str, kind: Literal["preview", "report"] | None = None,
                  lang: Lang = None) -> list[S.StoryOut]:
    """Preview and report of a match."""
    m = _match(match_id)
    rows = _lang(P.stories_newest(store, lambda s: s.match_id == m.id), lang)
    return [r for r in rows if not kind or r.kind == kind]


def _story(story_id: str):
    key = slug("story", story_id)
    base, _, lang = key.partition(":")
    st = store.get_story(base)
    if st is None or st.published_at > store.now:
        raise problem(404, "not_found")
    return st, lang or st.language


@router.get("/stories/{story_id}", response_model=S.StoryDetail, operation_id="getStory", tags=["fan"])
def get_story(story_id: str) -> S.StoryDetail:
    """One published story with the facts behind it ("Why?")."""
    st, lang = _story(story_id)
    row = next((r for r in P.story_rows(store, st) if r.language == lang), P.story_rows(store, st)[0])
    facts = [S.StoryFact(id=f"f{n}", claim=f"{f.key}: {f.value}") for n, f in enumerate(st.facts, start=1)]
    sentences = [{"text": t, "facts": []} for t in row.body.split("\n\n")]
    return S.StoryDetail(**row.model_dump(), sentences=sentences, facts=facts)


@router.post("/stories/{story_id}/corrections", status_code=201, response_model=S.CorrectionOut,
             operation_id="reportCorrection", tags=["editorial"])
def report_correction(story_id: str, body: S.CorrectionIn, who: Member) -> S.CorrectionOut:
    """Report a mistake in a story (members)."""
    st, _ = _story(story_id)
    rid = store.add_error_report(st.id, body.text)
    tournament = st.tournament_id or (P.tournament_key(store.get_match(st.match_id)) if st.match_id else "")
    return S.CorrectionOut(id=uid("correction", rid), tournament_id=uid("tournament", tournament or "none"),
                           story_id=story_id, kind=body.kind, text=body.text, status="open", note=None,
                           created_at=_now(), resolved_at=None)


@router.get("/stories", response_model=S.PageStories, operation_id="listStories", tags=["fan"])
def list_stories(cursor: Cursor = None, limit: Limit = 20, tournament_id: str | None = None,
                 lang: Lang = None) -> S.PageStories:
    """Published stories of every tournament (or one), newest first: the public news feed."""
    if tournament_id:
        rows = tournament_stories(tournament_id, lang)
    else:
        rows = _lang(P.stories_newest(store, lambda s: True), lang)
    items, nxt = _page(rows, cursor, limit)
    return S.PageStories(items=items, next_cursor=nxt)


@router.get("/organisations/{organisation_id}/stories", response_model=S.PageStories,
            operation_id="listOrganisationStories", tags=["fan"])
def organisation_stories(organisation_id: str, cursor: Cursor = None, limit: Limit = 20,
                         lang: Lang = None) -> S.PageStories:
    """Published stories of an organisation's tournaments, newest first."""
    club = _club(organisation_id)
    rows = _lang(P.stories_newest(store, lambda s: s.club_id == club.id or bool(set(s.team_ids) & set(club.team_ids))),
                 lang)
    items, nxt = _page(rows, cursor, limit)
    return S.PageStories(items=items, next_cursor=nxt)


@router.get("/me/stories", response_model=S.PageStories, operation_id="listMyStories", tags=["me"])
def my_stories(who: Member, cursor: Cursor = None, limit: Limit = 20, lang: Lang = None) -> S.PageStories:
    """Stories of everything I follow, newest first: my news feed."""
    p = who.profile
    teams = set(p.teams) | {t for c in p.clubs if c in CLUBS for t in CLUBS[c].team_ids}

    def mine(s) -> bool:
        return bool(set(s.team_ids) & teams) or s.club_id in p.clubs or (s.tournament_id in p.tournaments)

    items, nxt = _page(_lang(P.stories_newest(store, mine), lang), cursor, limit)
    return S.PageStories(items=items, next_cursor=nxt)


# ---- follows and notifications ---------------------------------------------------------------

_NOTIFY_FIELDS = {"match_start": "match_start", "goal": "live_updates", "result": "results",
                  "scenario_change": "scenario_changes", "news": "news"}


def _follow(profile, target_type: str, target_id: str, primary: bool = False) -> tuple[str, str]:
    kind = _FOLLOW_KINDS.get(target_type)
    if kind is None:
        raise problem(404, "not_found")
    target = slug(_ID_KIND[kind], target_id)
    known = {"club": CLUBS, "team": TEAMS, "tournament": store.tournaments}[kind]
    if target not in known:
        raise problem(404, "not_found")
    items = profile.follows_of(kind)
    if target not in items:
        items.append(target)
        A.state(store).follow_created[(kind, target)] = A._now()
    if primary and kind == "team":
        profile.v1_primary = target
    return kind, target


def _follow_out(profile, kind: str, target: str) -> S.FollowOut:
    prefs = profile.prefs(f"{kind}:{target}")
    notify = {k: getattr(prefs, v) for k, v in _NOTIFY_FIELDS.items()}
    notify |= {"relevance": True, "schedule_change": True, "next_opponent": True}
    created = A.state(store).follow_created.get((kind, target), A._now())
    if kind == "team":
        t = TEAMS[target]
        summary = S.FollowTarget(name=t.name, short_name=t.short, subtitle=t.league, sport=P.sport_code(t.sport))
    elif kind == "club":
        c = CLUBS[target]
        summary = S.FollowTarget(name=c.name, short_name=c.short, subtitle=c.city,
                                 sport=P.sport_code(c.sports[0]) if c.sports else None)
    else:
        ev = store.tournaments[target]
        summary = S.FollowTarget(name=ev.name, subtitle=ev.organiser.name, sport=P.sport_code(ev.sport),
                                 starts_on=P.day(ev.starts_at), ends_on=P.day(ev.ends_at))
    return S.FollowOut(id=_follow_id(kind, target), target_type=_TARGET_TYPES[kind],
                       target_id=uid(_ID_KIND[kind], target),
                       is_primary=kind == "team" and getattr(profile, "v1_primary", None) == target,
                       notify=notify, created_at=datetime.fromtimestamp(created, UTC), target=summary)


def _by_follow_id(profile, follow_id: str) -> tuple[str, str]:
    for kind in ("team", "club", "tournament"):
        for t in profile.follows_of(kind):
            if _follow_id(kind, t) == follow_id:
                return kind, t
    raise problem(404, "not_found")


FollowList = RootModel[list[S.FollowOut]]


@router.get("/me/follows", response_model=list[S.FollowOut], operation_id="listFollows", tags=["me"])
def list_follows(who: Member) -> list[S.FollowOut]:
    p = who.profile
    return [_follow_out(p, kind, t) for kind in ("team", "club", "tournament") for t in p.follows_of(kind)
            if t in {"club": CLUBS, "team": TEAMS, "tournament": store.tournaments}[kind]]


@router.post("/me/follows", status_code=201, response_model=S.FollowOut, operation_id="follow", tags=["me"])
def follow(body: S.FollowIn, who: Member) -> S.FollowOut:
    """Follow a team, tournament, organisation or series (`is_primary`: my team)."""
    kind, target = _follow(who.profile, body.target_type, body.target_id, primary=body.is_primary)
    return _follow_out(who.profile, kind, target)


@router.delete("/me/follows/{follow_id}", status_code=204, operation_id="unfollow", tags=["me"])
def unfollow(follow_id: str, who: Member) -> Response:
    kind, target = _by_follow_id(who.profile, follow_id)
    who.profile.follows_of(kind).remove(target)
    who.profile.notifications.pop(f"{kind}:{target}", None)
    if getattr(who.profile, "v1_primary", None) == target:
        who.profile.v1_primary = None
    return Response(status_code=204)


@router.patch("/me/follows/{follow_id}/notifications", response_model=S.FollowOut,
              operation_id="setFollowNotifications", tags=["me"])
def set_notifications(follow_id: str, body: S.NotifyPatch, who: Member) -> S.FollowOut:
    """Turn notification kinds on or off for one follow."""
    kind, target = _by_follow_id(who.profile, follow_id)
    prefs = who.profile.prefs(f"{kind}:{target}")
    for field, value in body.model_dump(exclude_none=True).items():
        if field in _NOTIFY_FIELDS:
            setattr(prefs, _NOTIFY_FIELDS[field], value)
    return _follow_out(who.profile, kind, target)


_KINDS = {"live_update": "goal"}


@router.get("/me/notifications", response_model=S.NotificationsPage, operation_id="listNotifications",
            tags=["me"])
def notifications(who: Member, cursor: Cursor = None, limit: Limit = 20) -> S.NotificationsPage:
    """My newest notifications, a page at a time, with the unread count."""
    before = None
    if cursor:
        try:
            before = int(json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))["before"])
        except (ValueError, KeyError, TypeError):
            raise problem(422, "validation_error", "Invalid pagination cursor") from None
    page = store.log.page(who.profile, limit, before)
    events = {f"n-{e.seq}": e for e in store.log.events}
    items = []
    for n in page.items:
        e = events[n.id]
        items.append(S.NotificationOut(
            id=uid("notification", n.id), kind=_KINDS.get(n.kind, n.kind), text=f"{n.title} — {n.body}",
            team_id=uid("team", e.team_ids[0]) if e.team_ids else None,
            match_id=uid("match", e.link_id) if e.link_type == "match" else None,
            tournament_id=uid("tournament", e.tournament_id) if e.tournament_id else None,
            created_at=P.ts(n.at), read=n.read,
        ))
    nxt = None
    if page.next_cursor is not None:
        nxt = base64.urlsafe_b64encode(json.dumps({"before": int(page.next_cursor)}).encode()).decode().rstrip("=")
    return S.NotificationsPage(items=items, next_cursor=nxt, unread_count=page.unread_count)


@router.post("/me/notifications/read", status_code=204, operation_id="markNotificationsRead", tags=["me"])
def mark_read(body: S.MarkRead, who: Member) -> Response:
    if body.ids is None:
        store.log.mark_read(who.profile, [], True)
    else:
        store.log.mark_read(who.profile, [slug("notification", i) for i in body.ids], False)
    return Response(status_code=204)


# ---- live token ----------------------------------------------------------------------------


@router.get("/live/token", response_model=S.LiveToken, operation_id="getLiveToken", tags=["fan"])
def live_token(who: Who, match_id: str | None = None, tournament_id: str | None = None) -> S.LiveToken:
    """A short-lived token for the live WebSocket (live access policy checked)."""
    if (match_id is None) == (tournament_id is None):
        raise problem(422, "validation_error", "give exactly one of match_id and tournament_id")
    key = P.tournament_key(_match(match_id)) if match_id else _view(tournament_id).key
    scope = f"match:{_match(match_id).id}" if match_id else f"tournament:{key}"
    if not P.can_watch_live(who.profile, key):
        raise problem(401, "not_authenticated", "sign in to follow live")
    import secrets

    token = secrets.token_urlsafe(24)
    expires = A._now() + A.LIVE_TOKEN_TTL
    A.state(store).live_tokens[token] = (scope, expires)
    return S.LiveToken(token=token, expires_at=datetime.fromtimestamp(expires, UTC), scope=scope)


# ---- scoring -------------------------------------------------------------------------------


def _scorer_role(who: A.Viewer, m: Match) -> Literal["scorer", "organiser"]:
    """A pass for the match's tournament, or an organiser account. 401 / 403 otherwise."""
    if who.pass_tournament:
        if who.pass_tournament != m.tournament_id:
            raise problem(403, "scorer_not_assigned")
        return "scorer"
    if who.is_member and getattr(who.profile, "v1_staff", False) and m.tournament_id:
        return "organiser"
    if not who.is_member:
        raise problem(401, "not_authenticated")
    raise problem(403, "scorer_not_assigned")


def _scored(m: Match) -> list[dict]:
    st = legacy_scoring.manual(store, m) or {"events": []}
    return st["events"]


def _scorer_match(m: Match) -> S.ScorerMatch:
    view = _views()[P.tournament_key(m)]
    events = _scored(m)
    return S.ScorerMatch(
        match_id=uid("match", m.id), code=m.id.upper(), starts_at=P.ts(P.starts_of(m)), status=P._STATUS[m.status],
        home_team_id=uid("team", m.home.id), away_team_id=uid("team", m.away.id), tournament_id=view.id,
        tournament_name=view.name, sport=P.sport_code(m.sport), stage=P.card(m, None).stage, pitch=m.venue,
        home=S.ScorerTeam(**P.team_name(m.home).model_dump()), away=S.ScorerTeam(**P.team_name(m.away).model_dump()),
        data_level="results" if m.data_level == "results_only" else "events", events_recorded=len(events),
        last_event_at=P.ts(events[-1]["at"]) if events else None,
    )


ScorerList = RootModel[list[S.ScorerMatch]]


@router.get("/scoring/me", response_model=list[S.ScorerMatch], operation_id="getScorerMatches", tags=["scoring"])
def scorer_matches(who: Who) -> list[S.ScorerMatch]:
    """My matches to score: today's for a scorer pass; every open one for an organiser."""
    if who.pass_tournament:
        today = P.day(store.now)
        mine = [m for m in store.matches if m.tournament_id == who.pass_tournament
                and (m.status == "live" or P.day(P.starts_of(m)) == today)]
    elif who.is_member:
        mine = [m for m in store.matches if m.tournament_id and getattr(who.profile, "v1_staff", False)]
    else:
        raise problem(401, "not_authenticated", "open the pitch QR code")
    return [_scorer_match(m) for m in sorted(mine, key=P.starts_of)]


# Backend event types -> the mock pad's ids (football and futsal); other sports use their own ids.
_TO_MOCK = {"penalty_missed": "penalty_miss", "second_yellow": "red_card"}
_FROM_MOCK = {"penalty_miss": "penalty_missed", "penalty_goal": "goal", "start": "period_start"}
_FOOTBALL_PAD = [
    S.EventPadButton(id="period_start", type="period_start", label="Start period", group="control", team=False),
    S.EventPadButton(id="period_end", type="period_end", label="End period", group="control", team=False),
    S.EventPadButton(id="goal", type="goal", label="Goal", group="score", team=True, player="optional",
                     player_prompt="Who scored?", points=1),
    S.EventPadButton(id="penalty_goal", type="goal", label="Penalty goal", group="score", team=True,
                     player="optional", player_prompt="Who scored?", points=1, payload={"kind": "penalty"}),
    S.EventPadButton(id="own_goal", type="goal", label="Own goal", group="score", team=True, player="optional",
                     player_prompt="Who put it in their own net?", points=1, payload={"kind": "own_goal"}),
    S.EventPadButton(id="penalty_missed", type="penalty_missed", label="Penalty missed", group="play", team=True,
                     player="optional", player_prompt="Who took it?"),
    S.EventPadButton(id="yellow_card", type="yellow_card", label="Yellow card", group="discipline", team=True,
                     player="optional", player_prompt="Who was booked?"),
    S.EventPadButton(id="second_yellow", type="second_yellow", label="Second yellow", group="discipline", team=True,
                     player="optional", player_prompt="Who was sent off?"),
    S.EventPadButton(id="red_card", type="red_card", label="Red card", group="discipline", team=True,
                     player="optional", player_prompt="Who was sent off?"),
    S.EventPadButton(id="substitution", type="substitution", label="Substitution", group="play", team=True,
                     player="optional", player_prompt="Who came on?"),
]
_FOOTBALL_TYPES = ["goal", "penalty_missed", "period_end", "period_start", "red_card", "second_yellow",
                   "shootout_kick", "substitution", "undo", "yellow_card"]


@router.get("/sports/{code}/event-types", response_model=S.EventPad, operation_id="getEventTypes",
            tags=["scoring"])
def event_types(code: str) -> S.EventPad:
    """The event pad definition for a sport: buttons, labels, and what each one posts."""
    if code in ("football", "futsal"):
        types = _FOOTBALL_TYPES + (["foul", "timeout"] if code == "futsal" else [])
        buttons = list(_FOOTBALL_PAD)
        if code == "futsal":
            buttons += [S.EventPadButton(id="foul", type="foul", label="Foul", group="discipline", team=True,
                                         player="optional", player_prompt="Who fouled?"),
                        S.EventPadButton(id="timeout", type="timeout", label="Timeout", group="control", team=True)]
        return S.EventPad(sport=code, clock=True, periods=["1st half", "2nd half"], score_label="Goals",
                          event_types=sorted(types), buttons=buttons)
    sp = sport_events.for_sport(P.mock_sport(code))
    if sp is None:
        raise problem(422, "validation_error", f"no event pad for '{code}' yet")
    buttons = [S.EventPadButton(id=e.id, type=_FROM_MOCK.get(e.id, e.id), label=e.label, group=e.group, team=e.team,
                                player=e.player, player_prompt=e.player_prompt, points=e.points, follow_up=e.follow_up)
               for e in sp.event_types if e.id != "start"]
    return S.EventPad(sport=code, clock=sp.clock, periods=sp.periods, score_label=sp.score_label,
                      event_types=sorted({b.type for b in buttons} | {"undo"}), buttons=buttons)


def _live_score(m: Match) -> S.LiveScore:
    score = m.score or [0, 0]
    st = legacy_scoring.manual(store, m)
    period = 0 if not (st and st["started"]) and m.status != "live" else (st["period_index"] + 1 if st else 1)
    return S.LiveScore(home_goals=score[0], away_goals=score[1], period=period, finished=m.status == "finished")


@router.get("/matches/{match_id}/scoring", response_model=S.ScoringState, operation_id="getScoringState",
            tags=["scoring"])
def scoring_state(match_id: str, who: Who) -> S.ScoringState:
    """The scoring console's view of a match (scorer pass for its pitch, or organisers)."""
    m = _match(match_id)
    role = _scorer_role(who, m)
    sp = legacy_scoring.sport_of(m)
    legacy = legacy_scoring.state(store, m, "admin" if role == "organiser" else "scorer")
    events = []
    undone_by = {}
    for e in reversed(_scored(m)):  # newest first
        events.append(S.ScoredEvent(
            seq=e["seq"], client_seq=e["client_seq"], type=_FROM_MOCK.get(e["type"], e["type"]),
            team_id=uid("team", (m.home if e["team"] == "home" else m.away).id) if e["team"] else None,
            player_id=uid("player", e["player_id"]) if e["player_id"] else None, period=e["period"] + 1,
            clock=f"{e['minute']}:00" if e["minute"] is not None else None,
            payload={"kind": "penalty"} if e["type"] == "penalty_goal" else {}, undone=e["undone"],
            undoes_seq=undone_by.get(e["seq"]), created_at=P.ts(e["at"]),
        ))

    def roster(entries) -> list[S.ScorerRosterPlayer]:
        return [S.ScorerRosterPlayer(id=uid("player", r.id), display_name=r.name, shirt_number=r.number)
                for r in entries if r.name]  # hidden juniors never appear (docs/09)

    view = _views()[P.tournament_key(m)]
    return S.ScoringState(
        match_id=uid("match", m.id), tournament_id=view.id, sport=P.sport_code(m.sport), code=m.id.upper(),
        stage=P.card(m, None).stage, status=P._STATUS[m.status],
        data_level="results" if m.data_level == "results_only" else "events", starts_at=P.ts(P.starts_of(m)),
        pitch=m.venue, home=S.ScorerTeam(**P.team_name(m.home).model_dump()),
        away=S.ScorerTeam(**P.team_name(m.away).model_dump()), score=_live_score(m),
        period=(legacy.period_index + 1) if legacy.started else 0, periods=len(sp.periods),
        period_minutes=sp.period_minutes, between_periods=legacy.between_periods,
        home_roster=roster(legacy.home_roster), away_roster=roster(legacy.away_roster), events=events,
        last_client_seq=max((e["client_seq"] for e in _scored(m)), default=0), role=role, server_time=_now(),
    )


def _legacy_event(m: Match, client_seq: int, type_: str, team: str | None = None, player: str | None = None):
    accepted = legacy_scoring.add_event(store, m, LegacyEventIn(device_id=_DEVICE, client_seq=client_seq, type=type_,
                                                                team=team, player_id=player), None)
    return accepted


@router.post("/matches/{match_id}/start", response_model=S.MatchStatus, operation_id="startMatch",
             tags=["scoring"])
def start_match(match_id: str, who: Who) -> S.MatchStatus:
    """Kick-off: the match goes live."""
    m = _match(match_id)
    _scorer_role(who, m)
    st = legacy_scoring.manual(store, m, create=True)
    if not st["started"]:
        seq = max((e["client_seq"] for e in st["events"]), default=0) + 1
        _legacy_event(m, seq, "start")
    return S.MatchStatus(match_id=match_id, status="live")


@router.post("/matches/{match_id}/events", status_code=201, response_model=S.EventAccepted,
             operation_id="postMatchEvent", tags=["scoring"])
def post_event(match_id: str, body: S.EventIn, response: Response, who: Who) -> S.EventAccepted:
    """Append an event; a retry with the same client_seq returns 200 and the original seq."""
    m = _match(match_id)
    _scorer_role(who, m)
    st = legacy_scoring.manual(store, m, create=True)
    existing = next((e for e in st["events"] if e["client_seq"] == body.client_seq), None)
    if existing is not None:
        response.status_code = 200
        return S.EventAccepted(seq=existing["seq"], duplicate=True, live=_live_score(m), moments=[])
    latest = max((e["client_seq"] for e in st["events"]), default=0)
    if body.client_seq < latest:
        raise problem(409, "conflict", f"events must arrive in order; expected client_seq {latest + 1}")
    if m.status != "live":
        raise problem(409, "match_not_live", f"the match is {P._STATUS[m.status]}")
    if body.type == "undo":
        return undo_event(match_id, int(body.payload.get("undoes_seq", 0)), S.UndoIn(client_seq=body.client_seq), who)
    side = None
    if body.team_id:
        team = slug("team", body.team_id)
        if team not in (m.home.id, m.away.id):
            raise problem(422, "validation_error", "team_not_in_match: the event's team is not playing this match")
        side = "home" if team == m.home.id else "away"
    kind = body.payload.get("kind")
    type_ = _TO_MOCK.get(body.type, body.type)
    if body.type == "goal" and kind == "penalty":
        type_ = "penalty_goal"
    elif body.type == "goal" and kind == "own_goal" and side:
        side = "away" if side == "home" else "home"  # credited to the other team, as the backend does
    if body.type == "period_start" and not st["started"]:
        type_ = "start"
    player = slug("player", body.player_id) if body.player_id else None
    _legacy_event(m, body.client_seq, type_, side, player)
    m = _match(match_id)
    seq = next(e["seq"] for e in st["events"] if e["client_seq"] == body.client_seq)
    moments = ["goal"] if body.type == "goal" else []
    return S.EventAccepted(seq=seq, duplicate=False, live=_live_score(m), moments=moments)


@router.post("/matches/{match_id}/events/{seq}/undo", status_code=201, response_model=S.EventAccepted,
             operation_id="undoMatchEvent", tags=["scoring"])
def undo_event(match_id: str, seq: int, body: S.UndoIn, who: Who) -> S.EventAccepted:
    """Undo an event (appends an undo event)."""
    m = _match(match_id)
    _scorer_role(who, m)
    st = legacy_scoring.manual(store, m) or {"events": []}
    target = next((e for e in st["events"] if e["seq"] == seq), None)
    if target is None:
        raise problem(422, "validation_error", "invalid_undo: an undo must point at an earlier event")
    legacy_scoring.undo(store, m, target["client_seq"], target["device_id"])
    return S.EventAccepted(seq=seq, duplicate=False, live=_live_score(_match(match_id)), moments=[])


@router.post("/matches/{match_id}/finish", response_model=S.MatchStatus, operation_id="finishMatch",
             tags=["scoring"])
def finish_match(match_id: str, body: S.FinishIn, who: Who) -> S.MatchStatus:
    """Confirm the final score."""
    m = _match(match_id)
    _scorer_role(who, m)
    if m.status != "live":
        raise problem(409, "match_not_live", f"the match is {P._STATUS[m.status]}")
    store.finish_match(m.id, [body.home_goals, body.away_goals])
    result = {"home_goals": body.home_goals, "away_goals": body.away_goals, "decided_by": "regulation"}
    return S.MatchStatus(match_id=match_id, status="finished", result=result)


@router.post("/matches/{match_id}/result", response_model=S.MatchStatus, operation_id="enterResult",
             tags=["scoring"])
def enter_result(match_id: str, body: S.ResultIn, who: Who) -> S.MatchStatus:
    """Results-only entry."""
    m = _match(match_id)
    _scorer_role(who, m)
    if m.status == "finished":
        raise problem(409, "match_not_live", "the match is finished")
    store.finish_match(m.id, [body.home_goals, body.away_goals])
    result = body.model_dump()
    return S.MatchStatus(match_id=match_id, status="finished", result=result)


# ---- mock only -------------------------------------------------------------------------------

mock_router = APIRouter(prefix="/mock", tags=["mock only"])


@mock_router.get("/outbox")
def outbox() -> list[dict]:
    """Magic-link emails the mock 'sent' (the backend's Mailpit), newest first."""
    return A.state(store).outbox


@mock_router.get("/scorer-passes")
def scorer_passes() -> list[dict]:
    """The demo scorer pass of each tournament (the real one is in the pitch QR code)."""
    return [{"tournament_id": uid("tournament", t), "name": ev.name, "token": A.pass_token(t)}
            for t, ev in store.tournaments.items()]

