"""Publisher portal P4: managing a published event (one with match data in store.tournaments).

Overview (status, next matches, live now), fixtures and results (add / edit / remove fixtures, enter or correct
results, assign scorers, data level), teams, scorers (invited by email; an invite turns active when someone signs in
with that email and opens the scorer area) and settings (content languages, publisher review, visibility).
"""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING

from fastapi import HTTPException

from . import club_matches as CMX
from . import tournaments as TN
from .mock_data import CLUBS, TEAMS
from .models import (Correction, EventManage, EventScorer, EventSettings, ManagedMatch, ManagedTeam, Match,
                     ScorerInviteResult)

if TYPE_CHECKING:
    from .store import FeedStore, Session

MIN = 60_000
DAY = 24 * 60 * MIN
INVITE_DAYS = 14
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def seed(store: FeedStore) -> None:
    from .mock_data import DEMO_SCORER

    store.event_scorers: dict[str, list[dict]] = {}
    for eid, e in store.publisher_events.items():
        e.setdefault("visibility", "public")
        e.setdefault("languages", ["fi", "en"])
        # publish rights for manual posts: OurSport grants them per event; junior events always go via the editors
        t = store.tournaments.get(e.get("tournament_id") or "")
        e.setdefault("can_publish", bool(t) and not t.junior)
    if "njc-u17" in store.publisher_events:
        now = store.now
        store.event_scorers["njc-u17"] = [
            {"id": "es-1", "name": DEMO_SCORER["name"], "email": DEMO_SCORER["email"], "invited_at": now - 6 * DAY,
             "accepted_at": now - 5 * DAY, "expires_at": now + 8 * DAY, "token": secrets.token_urlsafe(8)},
            {"id": "es-2", "name": "Maria Lehto", "email": "maria.lehto@example.org", "invited_at": now - 1 * DAY,
             "accepted_at": None, "expires_at": now + 13 * DAY, "token": secrets.token_urlsafe(8)},
        ]
        for mid in ("njc11", "njc12"):
            if store.get_match(mid):
                store.scorers[mid] = {"member_id": "es-1", "club_id": "event:njc-u17", "event_id": "njc-u17"}


# ---- access --------------------------------------------------------------------------------

def owned_event(store: FeedStore, event_id: str, session: Session) -> dict:
    """The publisher's own event, published or not. 401 / 403 / 404."""
    from .publisher import require_publisher

    if not session.signed_in:
        raise HTTPException(401, "Log in with your publisher account.")
    require_publisher(session)
    e = store.publisher_events.get(event_id)
    if e is None:
        raise HTTPException(404, "Event not found")
    if (session.email or "").lower() not in {o.lower() for o in e["owners"]}:
        raise HTTPException(403, {"code": "not_your_event", "message": "This event belongs to another publisher."})
    return e


def _tournament(store: FeedStore, e: dict):
    t = store.tournaments.get(e.get("tournament_id") or "")
    if t is None:
        raise HTTPException(409, {"code": "not_published", "message": "The event isn’t published yet. Finish the setup first."})
    return t


def event_of_match(store: FeedStore, m: Match, session: Session) -> tuple[str, dict] | None:
    """(event id, event) when the match belongs to one of this publisher's published events."""
    if not session.signed_in or not session.is_publisher() or not m.tournament_id:
        return None
    email = (session.email or "").lower()
    for eid, e in store.publisher_events.items():
        if e.get("tournament_id") == m.tournament_id and email in {o.lower() for o in e["owners"]}:
            return eid, e
    return None


# ---- scorers ---------------------------------------------------------------------------------

def scorer_status(store: FeedStore, r: dict) -> str:
    if r["accepted_at"]:
        return "active"
    return "expired" if (r["expires_at"] or 0) < store.now else "invited"


def _scorer(store: FeedStore, eid: str, r: dict) -> EventScorer:
    n = sum(1 for a in store.scorers.values() if a.get("event_id") == eid and a["member_id"] == r["id"])
    return EventScorer(id=r["id"], name=r["name"], email=r["email"], status=scorer_status(store, r), invited_at=r["invited_at"],
                       accepted_at=r["accepted_at"], expires_at=r["expires_at"], matches=n)


def my_event_rows(store: FeedStore, session: Session) -> list[tuple[str, dict]]:
    """S1/S2: (f"event:{id}", row) for every event this account scores for. Signing in with the invited email
    activates the invite."""
    if not session.email:
        return []
    out = []
    for eid, rows in getattr(store, "event_scorers", {}).items():
        for r in rows:
            if r["email"].lower() != session.email.lower():
                continue
            if not r["accepted_at"] and scorer_status(store, r) == "invited":
                r["accepted_at"] = store.now
                r["name"] = r["name"] or session.name
            if r["accepted_at"]:
                out.append((f"event:{eid}", r))
    if out and ("*", "scorer") not in session.roles:
        session.roles.append(("*", "scorer"))  # not tied to a club: shown as a OurSport role
    return out


def invite_scorers(store: FeedStore, session: Session, event_id: str, body) -> ScorerInviteResult:
    e = owned_event(store, event_id, session)
    _tournament(store, e)
    rows = store.event_scorers.setdefault(event_id, [])
    invited, skipped = [], []
    for raw in body.emails:
        email = raw.strip().lower()
        if not EMAIL.match(email):
            skipped.append({"email": raw, "reason": "Not an email address."})
            continue
        cur = next((r for r in rows if r["email"].lower() == email), None)
        if cur and scorer_status(store, cur) == "active":
            skipped.append({"email": raw, "reason": "Already a scorer for this event."})
            continue
        if cur:  # invited or expired: send again
            cur.update(invited_at=store.now, expires_at=store.now + INVITE_DAYS * DAY)
            invited.append(_scorer(store, event_id, cur))
            continue
        r = {"id": f"es-{store._next_id()}", "name": (body.name or "").strip() or None if len(body.emails) == 1 else None,
             "email": email, "invited_at": store.now, "accepted_at": None, "expires_at": store.now + INVITE_DAYS * DAY,
             "token": secrets.token_urlsafe(8), "message": body.message}
        rows.append(r)
        invited.append(_scorer(store, event_id, r))
    return ScorerInviteResult(invited=invited, skipped=skipped)


def remove_scorer(store: FeedStore, session: Session, event_id: str, scorer_id: str) -> EventManage:
    e = owned_event(store, event_id, session)
    rows = store.event_scorers.get(event_id, [])
    if not any(r["id"] == scorer_id for r in rows):
        raise HTTPException(404, "Scorer not found")
    store.event_scorers[event_id] = [r for r in rows if r["id"] != scorer_id]
    for mid, a in list(store.scorers.items()):
        m = store.get_match(mid)
        if a.get("event_id") == event_id and a["member_id"] == scorer_id and m and m.status != "finished":
            store.scorers.pop(mid)
    return manage(store, event_id, e)


def assigned(store: FeedStore, a: dict):
    """club_matches.assigned for an event scorer."""
    from .models import AssignedScorer

    eid = a["event_id"]
    r = next((x for x in store.event_scorers.get(eid, []) if x["id"] == a["member_id"]), None)
    if r is None:
        return None
    e = store.publisher_events.get(eid, {})
    t = store.tournaments.get(e.get("tournament_id") or "")
    return AssignedScorer(member_id=r["id"], name=r["name"] or r["email"], club_id=a["club_id"],
                          club_name=f"{t.name if t else eid} scorer")


# ---- read ------------------------------------------------------------------------------------

def _managed(store: FeedStore, t, m: Match) -> ManagedMatch:
    group = next((g.name for g in t.groups if m.home.id in g.team_ids and m.away.id in g.team_ids), m.stage)
    entered = [x for x in store.timelines.get(m.id, []) if not x.ai]
    return ManagedMatch(match=m, group=group, status=CMX.status(store, m), scorer=CMX.assigned(store, m.id),
                        can_finish=CMX.can_finish(store, m) or (m.status == "upcoming" and (m.starts_at or 0) <= store.now),
                        editable=m.status == "upcoming", events_recorded=len(entered))


def manage(store: FeedStore, event_id: str, e: dict) -> EventManage:
    t = _tournament(store, e)
    games = sorted((m for m in store.matches if m.tournament_id == t.id), key=lambda m: (m.starts_at or m.ended_at or 0, m.id))
    rows = [_managed(store, t, m) for m in games]
    st = TN.standings(t, store.matches, store.now)
    table = {r.team.id: (r.played, r.points, r.position) for g in st.groups for r in g.rows}
    group_of = {tid: g.name for g in t.groups for tid in g.team_ids}
    played = sum(1 for m in games if m.status == "finished")
    live = sum(1 for m in games if m.status == "live")
    status = "finished" if games and played == len(games) or store.now > t.ends_at else \
        "live" if live or t.starts_at <= store.now else "scheduled"
    venues = list(dict.fromkeys([t.venue, *(m.venue for m in games)]))
    return EventManage(
        id=event_id, tournament_id=t.id, name=t.name, sport=t.sport, status=status, starts_at=t.starts_at, ends_at=t.ends_at,
        venue=t.venue, venues=venues, format=t.format, junior=t.junior, results_only=t.results_only,
        settings=EventSettings(languages=e.get("languages", ["fi", "en"]), review_enabled=e["review_enabled"],
                               visibility=e.get("visibility", "public"), can_publish=e.get("can_publish", False)),
        counts={"total": len(games), "played": played, "live": live,
                "upcoming": sum(1 for r in rows if r.status == "upcoming"),
                "awaiting_result": sum(1 for r in rows if r.status == "awaiting_result"),
                "no_scorer": sum(1 for r in rows if r.status in ("upcoming", "live") and r.match.data_level == "live" and not r.scorer)},
        groups=t.groups,
        teams=[ManagedTeam(team=tm, group=group_of.get(tm.id), club_name=CLUBS[tm.club_id].name if tm.club_id in CLUBS else None,
                           played=table.get(tm.id, (0, 0, None))[0], points=table.get(tm.id, (0, 0, None))[1],
                           position=table.get(tm.id, (0, 0, None))[2]) for tm in t.teams],
        matches=rows, scorers=[_scorer(store, event_id, r) for r in store.event_scorers.get(event_id, [])], updated_at=store.now,
    )


# ---- settings --------------------------------------------------------------------------------

def patch(store: FeedStore, event_id: str, e: dict, body, fields: set[str]) -> EventManage:
    _tournament(store, e)
    locked = fields - {"languages", "review_enabled", "visibility"}
    if locked:
        raise HTTPException(409, {"code": "published", "message": "The event is published: only its settings can change here."})
    if "languages" in fields and body.languages:
        e["languages"] = list(dict.fromkeys(body.languages))
    if "review_enabled" in fields and body.review_enabled is not None:
        e["review_enabled"] = body.review_enabled
    if "visibility" in fields and body.visibility:
        e["visibility"] = body.visibility
    store._notify()
    return manage(store, event_id, e)


def visible_to_fans(store: FeedStore, tournament_id: str, listed: bool) -> bool:
    """`listed`: shown in event lists (public only); otherwise reachable by link (public / unlisted)."""
    e = next((x for x in store.publisher_events.values() if x.get("tournament_id") == tournament_id), None)
    v = (e or {}).get("visibility", "public")
    return v == "public" if listed else v != "hidden"


# ---- fixtures and results --------------------------------------------------------------------

def _team(t, team_id: str):
    tm = next((x for x in t.teams if x.id == team_id), None)
    if tm is None:
        raise HTTPException(422, {"code": "team", "message": "Pick teams of this event."})
    return tm


def add_match(store: FeedStore, session: Session, event_id: str, body) -> ManagedMatch:
    e = owned_event(store, event_id, session)
    t = _tournament(store, e)
    home, away = _team(t, body.home), _team(t, body.away)
    if home.id == away.id:
        raise HTTPException(422, {"code": "teams", "message": "A team can’t play itself."})
    if body.starts_at < store.now:
        raise HTTPException(422, {"code": "time", "message": "The start time is in the past."})
    if body.starts_at > t.ends_at + 30 * DAY:
        raise HTTPException(422, {"code": "time", "message": "That’s long after the event ends."})
    clash = next((m for m in store.matches if m.tournament_id == t.id and m.status != "finished" and abs((m.starts_at or 0) - body.starts_at) < 30 * MIN
                  and ({m.home.id, m.away.id} & {home.id, away.id} or m.venue == body.venue.strip())), None)
    if clash:
        raise HTTPException(409, {"code": "clash", "message": f"Clashes with {clash.home.name} v {clash.away.name} at that time."})
    group = next((g for g in t.groups if home.id in g.team_ids and away.id in g.team_ids), None)
    m = Match(id=f"{t.id}-{store._next_id()}", sport=t.sport, league=t.name, status="upcoming", home=home, away=away,
              venue=body.venue.strip(), starts_at=body.starts_at, tournament_id=t.id,
              stage=group.name if group else (body.group or "Play-offs"), data_level="results_only" if t.results_only else "live")
    store.matches.append(m)
    store._notify()
    return _managed(store, t, m)


def update_match(store: FeedStore, session: Session, event_id: str, e: dict, m: Match, body, fields: set[str]) -> ManagedMatch:
    t = _tournament(store, e)
    if "score" in fields and body.score is not None:
        if any(s < 0 or s > 999 for s in body.score):
            raise HTTPException(422, {"code": "score", "message": "Check the score."})
        if m.status == "finished":  # correct a result
            if body.score != m.score:
                old = f"{m.score[0]}–{m.score[1]}" if m.score else "?"
                fixed = m.model_copy(update={"score": list(body.score), "correction": Correction(
                    message=f"Result corrected by the organiser: {old} → {body.score[0]}–{body.score[1]}", at=store.now)})
                store.matches = [fixed if x.id == m.id else x for x in store.matches]
                store._log_result(fixed, at=store.now)
                store._notify()
                m = fixed
        elif m.status == "live" or (m.starts_at or 0) <= store.now:
            m = store.finish_match(m.id, body.score)
        else:
            raise HTTPException(409, {"code": "not_started", "message": "Results can be entered once the match has started."})
        return _managed(store, t, store.get_match(m.id))
    if m.status != "upcoming" and fields & {"starts_at", "venue", "data_level"}:
        raise HTTPException(409, {"code": "started", "message": "The match has started: time, venue and data level are fixed."})
    if "starts_at" in fields and body.starts_at:
        if body.starts_at < store.now:
            raise HTTPException(422, {"code": "time", "message": "The start time is in the past."})
        m.starts_at = body.starts_at
    if "venue" in fields and body.venue:
        m.venue = body.venue.strip()
    if "data_level" in fields and body.data_level:
        m.data_level = body.data_level
    if "scorer_id" in fields:
        if m.status == "finished":
            raise HTTPException(409, {"code": "finished", "message": "The match has finished."})
        if body.scorer_id is None:
            store.scorers.pop(m.id, None)
        else:
            r = next((x for x in store.event_scorers.get(event_id, []) if x["id"] == body.scorer_id), None)
            if r is None or scorer_status(store, r) == "expired":
                raise HTTPException(422, {"code": "not_a_scorer", "message": "Pick one of the event’s scorers (invite them first)."})
            store.scorers[m.id] = {"member_id": r["id"], "club_id": f"event:{event_id}", "event_id": event_id}
    store._notify()
    return _managed(store, t, m)


def delete_match(store: FeedStore, session: Session, m: Match) -> None:
    hit = event_of_match(store, m, session)
    if hit is None:
        raise HTTPException(403, {"code": "not_your_event", "message": "Only the event’s publisher can remove its fixtures."})
    if m.status != "upcoming" or store.timelines.get(m.id):
        raise HTTPException(409, {"code": "started", "message": "Only fixtures that haven’t started can be removed."})
    store.matches = [x for x in store.matches if x.id != m.id]
    store.scorers.pop(m.id, None)
    store.stories = [s for s in store.stories if not (s.match_id == m.id and s.tag.lower().startswith("preview"))]
    store._notify()


# ---- rules of a published event (P3 page for events that are already running) ------------------

def ensure_rules(store: FeedStore, e: dict) -> dict:
    """A published event came with its rules already confirmed: give it the same rules record the P3 page reads
    (text, extracted draft, answered questions, examples marked correct, versions 1–2), once."""
    from copy import deepcopy

    from . import rules_review as RR
    from .event_setup import extract_rules

    if e.get("rules_draft") is not None:
        return e
    t = _tournament(store, e)
    rs = TN.rules_summary(t)
    text = " ".join(f"{s.heading}. {s.text}" for s in rs.sections)
    e.update(name=t.name, sport=t.sport, rules_text=text,
             teams=[{"id": tm.id, "name": tm.name, "group": next((g.id for g in t.groups if tm.id in g.team_ids), None)}
                    for tm in t.teams], groups=[{"id": g.id, "name": g.name} for g in t.groups],
             rulebook={"kind": "text", "name": f"{t.name} rules", "size": len(text), "received_at": t.starts_at - 21 * DAY},
             rules_job={"status": "done", "progress": 100, "step": "Rules found", "started_at": t.starts_at - 21 * DAY})
    e["rules"] = extract_rules(t.sport, text, len(t.teams), len(t.groups))
    e["rules_answers"], e["rules_marks"] = {}, {}
    d = RR.draft(store, e)
    d["points"].update(win=t.points_win, draw=t.points_draw, loss=0)
    d["advancement"]["per_group"] = t.qualify_count
    d["match"]["minutes"] = d["match"]["minutes"] or t.match_minutes
    want = "net_run_rate" if t.tiebreak.key == "nrr" else "goal_difference"
    for q in RR.questions(e, d):  # the organiser's answers: the option that matches how the event is run
        opt = next((o for o in q["options"] if (q["id"] == "tiebreakers" and o["value"][0] == want)
                    or (q["id"] == "advancement" and o["value"] == t.qualify_count)), q["options"][0])
        e["rules_answers"][q["id"]] = opt["id"]
        RR.apply_answer(d, q["id"], opt["value"])
    if "lots" not in d["tiebreakers"]:  # the event's regulations end with drawing lots
        d["tiebreakers"].append("lots")
    for ex in RR.examples(e, d):
        e["rules_marks"][ex["id"]] = {"status": "correct", "note": "", "fingerprint": ex["fingerprint"]}
    e["rule_versions"] = [
        {"version": 1, "confirmed_at": t.starts_at - 20 * DAY, "confirmed_by": "Kaisa Ranta", "rules": deepcopy(d), "notes": {}},
        {"version": 2, "confirmed_at": store.now - 9 * DAY, "confirmed_by": "Kaisa Ranta", "rules": deepcopy(d), "notes": {}},
    ]
    return e


def apply_confirmed_rules(store: FeedStore, e: dict) -> None:
    """After a new rules version on a running event: the points and places count from now on."""
    t = store.tournaments.get(e.get("tournament_id") or "")
    d = e.get("rules_draft")
    if t is None or not d:
        return
    t.points_win = d["points"]["win"] if d["points"]["win"] is not None else t.points_win
    t.points_draw = d["points"]["draw"] if d["points"]["draw"] is not None else t.points_draw
    t.qualify_count = d["advancement"]["per_group"] or t.qualify_count
    e["status"] = "scheduled"
