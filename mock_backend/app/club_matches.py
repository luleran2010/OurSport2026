"""Club portal C4: the club's matches, scorer assignment, data level and result entry.

- A club admin manages the games its teams play (home or away).
- Scorers are picked from the club's active members with the scorer role (C2 roster).
- Data level: "live" (a scorer enters events during the game) or "results_only" (only the final score,
  entered here with "Enter result"). It can be changed until the game starts.
- Finishing: a results-only game once it has started; a live game while it is live.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from . import club_members as CM
from .mock_data import CLUBS, TEAMS
from .models import AssignedScorer, PortalMatch, PortalMatches, Match, ScorerOption

if TYPE_CHECKING:
    from .store import FeedStore, Session


def _team_ids(club_id: str) -> set[str]:
    return set(CLUBS[club_id].team_ids)


def clubs_of(m: Match) -> set[str]:
    return {t.club_id for t in (m.home, m.away)}


def scorer_options(store: FeedStore, club_id: str) -> list[ScorerOption]:
    rows = [r for r in CM.roster(store, club_id) if r["role"] == "scorer" and CM.status_of(store, r) == "active"]
    return [ScorerOption(id=r["id"], name=r["name"] or r["email"], email=r["email"]) for r in sorted(rows, key=lambda r: r["name"] or "")]


def assigned(store: FeedStore, match_id: str) -> AssignedScorer | None:
    a = store.scorers.get(match_id)
    if not a:
        return None
    if a.get("event_id"):  # an event's own scorer (P4)
        from .event_manage import assigned as event_assigned

        return event_assigned(store, a)
    row = next((r for r in CM.roster(store, a["club_id"]) if r["id"] == a["member_id"]), None)
    if row is None:  # the member was removed from the club
        return None
    return AssignedScorer(member_id=row["id"], name=row["name"] or row["email"], club_id=a["club_id"],
                          club_name=CLUBS[a["club_id"]].name)


def scorer_name(store: FeedStore, match_id: str) -> str | None:
    a = assigned(store, match_id)
    return a.name if a else None


def status(store: FeedStore, m: Match) -> str:
    if m.status == "upcoming" and m.data_level == "results_only" and (m.starts_at or 0) <= store.now:
        return "awaiting_result"
    return m.status


def can_finish(store: FeedStore, m: Match) -> bool:
    s = status(store, m)
    return s == "awaiting_result" or s == "live"


def to_club_match(store: FeedStore, m: Match) -> PortalMatch:
    t = store.tournaments.get(m.tournament_id or "")
    return PortalMatch(match=m, competition=t.name if t else m.league, data_level=m.data_level, status=status(store, m),
                     scorer=assigned(store, m.id), can_finish=can_finish(store, m), editable=m.status != "finished")


def club_matches(store: FeedStore, club_id: str) -> PortalMatches:
    teams = _team_ids(club_id)
    games = [m for m in store.matches if m.home.id in teams or m.away.id in teams]
    upcoming = sorted((m for m in games if m.status != "finished"),
                      key=lambda m: ({"live": 0, "upcoming": 1}[m.status], m.starts_at or 0))
    upcoming.sort(key=lambda m: 0 if status(store, m) in ("live", "awaiting_result") else 1)
    past = sorted((m for m in games if m.status == "finished"), key=lambda m: -(m.ended_at or 0))
    return PortalMatches(club=CLUBS[club_id], teams=[TEAMS[t] for t in CLUBS[club_id].team_ids if t in TEAMS],
                       scorers=scorer_options(store, club_id), upcoming=[to_club_match(store, m) for m in upcoming],
                       past=[to_club_match(store, m) for m in past], updated_at=store.now)


# ---- access + writes ---------------------------------------------------------------------

def match_for_admin(store: FeedStore, match_id: str, session: Session) -> tuple[Match, str]:
    """The match and the club (of the two playing) that this admin manages. 401 / 404 / 403."""
    if not session.signed_in:
        raise HTTPException(401, "Log in with your club admin account.")
    m = store.get_match(match_id)
    if m is None:
        raise HTTPException(404, "Match not found")
    mine = [c for c in clubs_of(m) if session.is_admin(c)]
    if not mine:
        raise HTTPException(403, {"code": "not_club_admin", "message": "Only admins of the clubs playing can manage this match."})
    return m, sorted(mine)[0]


def update(store: FeedStore, m: Match, club_id: str, body, fields: set[str]) -> PortalMatch:
    if m.status == "finished":
        raise HTTPException(409, {"code": "finished", "message": "The match has finished. Use Corrections to change it."})
    if "data_level" in fields and body.data_level and body.data_level != m.data_level:
        if m.status != "upcoming":
            raise HTTPException(409, {"code": "started", "message": "The data level can’t change once the match has started."})
        m.data_level = body.data_level
    if "scorer_id" in fields:
        if body.scorer_id is None:
            store.scorers.pop(m.id, None)
        else:
            if body.scorer_id not in {o.id for o in scorer_options(store, club_id)}:
                raise HTTPException(422, {"code": "not_a_scorer", "message": "Pick an active member with the scorer role."})
            store.scorers[m.id] = {"member_id": body.scorer_id, "club_id": club_id}
    return to_club_match(store, m)


def finish(store: FeedStore, m: Match, score: list[int]) -> PortalMatch:
    if m.status == "finished":
        raise HTTPException(409, {"code": "finished", "message": "The match has already finished."})
    if not can_finish(store, m):
        raise HTTPException(409, {"code": "not_started", "message": "The result can be entered once the match has started."})
    if any(s < 0 or s > 999 for s in score):
        raise HTTPException(422, {"code": "score", "message": "Check the score."})
    return to_club_match(store, store.finish_match(m.id, score))
