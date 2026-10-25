"""Team page (F4): header, the current competition's scenario and table, and players to watch.

Fixtures and results come from the live feed on the client. Player rules match the rest of the fan side:
- adult teams: players whose profile the viewer may open (public, or members-only when signed in);
- junior teams (any non-senior age group): no players to watch, except a player the viewer is linked to
  as family (shown with the family_only badge);
- results-only events have no player data, so nobody is featured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import club_teams
from . import event_manage
from . import players as player_service
from . import tournaments as tournament_service
from .mock_data import AGE_GROUPS, CLUBS, PLAYERS, is_junior
from .models import PlayerSpotlight, Team, TeamCompetition, TeamPage, TeamStandings, Tournament

if TYPE_CHECKING:
    from .store import FeedStore, Session

MAX_PLAYERS = 3
# Stats that read as negative for a player; never shown on a spotlight card.
_NEGATIVE_STATS = {"gaa"}


def current_competition(store: FeedStore, team: Team) -> Tournament | None:
    """The fan-visible event the team plays in: an ongoing or upcoming one first, else the latest finished."""
    events = [t for t in store.tournaments.values()
              if any(x.id == team.id for x in t.teams) and event_manage.visible_to_fans(store, t.id, listed=False)]
    if not events:
        return None
    running = sorted((t for t in events if t.ends_at >= store.now), key=lambda t: t.starts_at)
    return running[0] if running else max(events, key=lambda t: t.ends_at)


def _spotlight(store: FeedStore, p, visibility: str) -> PlayerSpotlight:
    prof = player_service.profile(store, p)
    stats = [s for s in prof.stats if s.key not in _NEGATIVE_STATS][:3]
    open_ms = [m for m in prof.milestones if not m.achieved and m.target]
    done = [m for m in prof.milestones if m.achieved]
    milestone = open_ms[0] if open_ms else (done[-1] if done else None)
    return PlayerSpotlight(player=p, visibility=visibility, stats=stats, form=prof.form, milestone=milestone)


def _players(store: FeedStore, team: Team, session: Session, results_only: bool) -> list[PlayerSpotlight]:
    if results_only:
        return []
    out = []
    for p in (p for p in PLAYERS if p.team.id == team.id):
        if session.is_guardian_of(p.id) and club_teams.guardian_access(p):
            vis = player_service.visibility(p)
            out.append(_spotlight(store, p, vis if vis != "private" and not is_junior(team) else "family_only"))
        elif not is_junior(team):
            vis = player_service.visibility(p)
            if vis == "public" or (vis == "members" and session.signed_in):
                out.append(_spotlight(store, p, vis))
    # Family links first, then the roster order.
    out.sort(key=lambda s: s.visibility != "family_only")
    return out[:MAX_PLAYERS]


def build(store: FeedStore, team: Team, session: Session) -> TeamPage:
    club = CLUBS.get(team.club_id)
    age = next((a.label for a in AGE_GROUPS if a.id == team.age_group), team.age_group)
    t = current_competition(store, team)
    competition = scenario = standings = None
    if t:
        table = tournament_service.standings(t, store.matches, store.now)
        group = next((g for g in table.groups if any(r.team.id == team.id for r in g.rows)), None)
        if group:
            competition = TeamCompetition(id=t.id, name=t.name, group_name=group.name)
            standings = TeamStandings(updated_at=table.updated_at, tiebreak=table.tiebreak, for_label=table.for_label,
                                      against_label=table.against_label, qualify_count=table.qualify_count, group=group)
            scenario = next((c for c in tournament_service.scenarios(t, store.matches, store.now).cards
                             if c.team.id == team.id), None)
    return TeamPage(
        team=team, club_name=club.name if club else None, age_group_label=age, junior=is_junior(team),
        competition=competition, scenario=scenario, standings=standings,
        players_to_watch=_players(store, team, session, bool(t and t.results_only)),
        updated_at=store.now,
    )
