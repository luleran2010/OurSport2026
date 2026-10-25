"""Scorer area (S1–S2): matches assigned to the signed-in scorer.

A scorer is a club member with the scorer role (C2). Their account is matched to the roster row by email.
Clubs assign scorers per match in the club portal (C4, store.scorers).
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException

from . import club_members as CM
from .mock_data import CLUBS
from .models import Match, ScoringAssignment, ScoringAssignments

if TYPE_CHECKING:
    from .store import FeedStore, Session


def my_rows(store: FeedStore, session: Session) -> list[tuple[str, dict]]:
    """(club id, roster row) for every club where this account is an active scorer."""
    if not session.email:
        return []
    out = []
    for club_id, rows in store.club_members.items():
        for r in rows:
            emails = {r["email"].lower(), (r["account_email"] or "").lower()}
            if session.email.lower() in emails and r["role"] == "scorer" and CM.status_of(store, r) == "active":
                out.append((club_id, r))
    from .event_manage import my_event_rows

    return out + my_event_rows(store, session)  # scorers invited by an event's publisher (P4)


def require_scorer(store: FeedStore, session: Session) -> list[tuple[str, dict]]:
    if not session.signed_in:
        raise HTTPException(401, "Log in with your scorer account.")
    rows = my_rows(store, session)
    if not rows and not any(r == "scorer" for _, r in session.roles):
        raise HTTPException(403, {"code": "not_scorer", "message": "Only scorers have scoring assignments."})
    return rows


def _day(ts: int | None) -> str:
    return datetime.fromtimestamp((ts or 0) / 1000).astimezone().date().isoformat()


def _item(store: FeedStore, m: Match, club_id: str) -> ScoringAssignment:
    t = store.tournaments.get(m.tournament_id or "")
    events = [e for e in store.timelines.get(m.id, []) if not e.ai]  # entered events, not AI insights
    today = _day(store.now)
    if m.status == "finished":
        day = "past"
    elif m.status == "live" or _day(m.starts_at) <= today:
        day = "today"
    else:
        day = "later"
    return ScoringAssignment(
        match=m, club_id=club_id, club_name=CLUBS[club_id].name if club_id in CLUBS else (t.name if t else "Event"), competition=t.name if t else m.league,
        data_level=m.data_level, status=m.status, day=day, can_start=m.status == "live" or (m.status == "upcoming" and day == "today"),
        events_recorded=len(events), last_event_at=max((e.at for e in events), default=None),
    )


def assignments(store: FeedStore, session: Session) -> ScoringAssignments:
    rows = require_scorer(store, session)
    mine = {r["id"]: club_id for club_id, r in rows}
    items = []
    for match_id, a in store.scorers.items():
        if a["member_id"] in mine:
            m = store.get_match(match_id)
            if m:
                items.append(_item(store, m, a["club_id"]))
    rank = {"live": 0, "upcoming": 1}
    active = sorted((i for i in items if i.status != "finished"),
                    key=lambda i: (rank[i.status], 0 if i.day == "today" else 1, i.match.starts_at or 0))
    past = sorted((i for i in items if i.status == "finished"), key=lambda i: -(i.match.ended_at or 0))
    name = next((r["name"] for _, r in rows if r["name"]), session.name)
    return ScoringAssignments(scorer_name=name, clubs=[CLUBS[c] for c in dict.fromkeys(mine.values()) if c in CLUBS],
                              active=active, past=past, updated_at=store.now)


# ---- scorer console (S2) -----------------------------------------------------------------
# Manual scoring state per match (store.manual[match_id]); once a scorer sends the first event the live
# simulation leaves the match alone (store.tick checks store.manual).

from . import players as player_service  # noqa: E402
from . import sport_events  # noqa: E402
from .mock_data import PLAYERS  # noqa: E402
from .models import EventIn, Post, RosterEntry, ScoredEvent, ScoringClock, ScoringState, SportEvents  # noqa: E402

MIN = 60_000


def _now() -> int:
    return time.time_ns() // 1_000_000


def match_access(store: FeedStore, match_id: str, session: Session) -> tuple[Match, str]:
    """The assigned scorer, or an admin of either club playing. 401 / 404 / 403."""
    if not session.signed_in:
        raise HTTPException(401, "Log in with your scorer account.")
    m = store.get_match(match_id)
    if m is None:
        raise HTTPException(404, "Match not found")
    if any(session.is_admin(c) for c in (m.home.club_id, m.away.club_id)):
        return m, "admin"
    a = store.scorers.get(match_id)
    if a and a["member_id"] in {r["id"] for _, r in my_rows(store, session)}:
        return m, "scorer"
    raise HTTPException(403, {"code": "not_assigned", "message": "You’re not the scorer of this match."})


def sport_of(m: Match) -> SportEvents:
    sp = sport_events.for_sport(m.sport)
    if sp is None:
        raise HTTPException(409, {"code": "sport", "message": "This sport can’t be scored in the app yet."})
    return sp


def _period_index(sp: SportEvents, period: str | None) -> int:
    p = (period or "").lower()
    for i, label in enumerate(sp.periods):
        if label.lower() == p:
            return i
    for i, prefix in enumerate(("1st", "2nd", "3rd", "4th")):
        if p.startswith(prefix):
            return min(i, len(sp.periods) - 1)
    return 0


def manual(store: FeedStore, m: Match, create: bool = False) -> dict | None:
    st = store.manual.get(m.id)
    if st is None and create:
        sp = sport_of(m)
        started = m.status == "live"
        st = {"started": started, "period_index": _period_index(sp, m.period) if started else 0, "between": False,
              "running": started and sp.clock, "base_minute": m.clock or 0, "base_at": store.now,
              "wickets": [0, 0], "balls": [0, 0], "events": [], "seq": 0}
        store.manual[m.id] = st
    return st


def minute_now(store: FeedStore, st: dict) -> int:
    if not st["running"]:
        return st["base_minute"]
    return st["base_minute"] + max(0, (store.now - st["base_at"]) // MIN)


def roster(team_id: str) -> list[RosterEntry]:
    squad = sorted((p for p in PLAYERS if p.team.id == team_id), key=lambda p: (p.number, p.id))
    # junior protection: only public profiles come with a name
    return [RosterEntry(id=p.id, number=p.number, name=p.name if player_service.visibility(p) == "public" else None) for p in squad]


def _player_label(player_id: str | None, team_id: str) -> str | None:
    if not player_id:
        return None
    entry = next((r for r in roster(team_id) if r.id == player_id), None)
    if entry is None:
        return None
    return f"#{entry.number} {entry.name}" if entry.name else f"#{entry.number}"


def state(store: FeedStore, m: Match, role: str, device: str | None = None) -> ScoringState:
    sp = sport_of(m)
    st = manual(store, m) or {"started": m.status == "live", "period_index": _period_index(sp, m.period), "between": False,
                              "running": m.status == "live" and sp.clock, "base_minute": m.clock or 0, "base_at": store.now,
                              "wickets": [0, 0], "balls": [0, 0], "events": []}
    idx = st["period_index"]
    if m.status == "finished":
        label = "Full time"
    elif not st["started"]:
        label = "Not started"
    elif st["between"]:
        label = f"End of {sp.periods[idx]}"
    else:
        label = sp.periods[min(idx, len(sp.periods) - 1)]
    events = [ScoredEvent(**e) for e in reversed(st["events"])]
    return ScoringState(
        match=m, sport=m.sport, started=st["started"], period_index=idx, period_label=label, between_periods=st["between"],
        clock=ScoringClock(running=st["running"] and m.status == "live", base_minute=st["base_minute"], base_at=st["base_at"])
        if sp.clock else None,
        wickets=st["wickets"], balls=st["balls"], home_roster=roster(m.home.id), away_roster=roster(m.away.id), events=events,
        device_last_seq=max((e["client_seq"] for e in st["events"] if e["device_id"] == device), default=0) if device else 0,
        role=role, updated_at=store.now,
    )


def _replace(store: FeedStore, m: Match) -> Match:
    store.matches = [m if x.id == m.id else x for x in store.matches]
    return m


def add_event(store: FeedStore, m: Match, body: EventIn, session: Session) -> bool:
    """Apply one scorer event. Returns False if this (device, client_seq) was already received (idempotent)."""
    sp = sport_of(m)
    st = manual(store, m, create=True)
    if any(e["device_id"] == body.device_id and e["client_seq"] == body.client_seq for e in st["events"]):
        return False
    et = next((t for t in sp.event_types if t.id == body.type), None)
    if et is None:
        raise HTTPException(422, {"code": "event_type", "message": f"Unknown event for {m.sport}."})
    if m.status == "finished":
        raise HTTPException(409, {"code": "finished", "message": "The match has finished."})
    if m.data_level == "results_only":
        raise HTTPException(409, {"code": "results_only", "message": "This match is results only: enter the final score."})
    store.now = _now()
    side = None
    if et.team:
        if body.team is None:
            raise HTTPException(422, {"code": "team", "message": "Pick the team."})
        side = 0 if body.team == "home" else 1
    team = (m.home, m.away)[side] if side is not None else None
    if et.player == "required" and not body.player_id:
        raise HTTPException(422, {"code": "player", "message": f"Pick the player: {et.player_prompt or et.label}"})
    if body.player_id:
        if team is None or body.player_id not in {r.id for r in roster(team.id)}:
            raise HTTPException(422, {"code": "player", "message": "That player isn’t in the team."})

    if et.id == "start":
        if st["started"]:
            raise HTTPException(409, {"code": "started", "message": "The match has already started."})
        st.update(started=True, period_index=0, between=False, running=sp.clock, base_minute=0, base_at=store.now)
        m = _replace(store, m.model_copy(update={"status": "live", "score": m.score or [0, 0], "clock": 0 if sp.clock else None,
                                                  "period": sp.periods[0], "last_event": "Game under way!", "viewers": m.viewers or 1}))
        store._timeline(m, "kickoff", f"Kick-off at {m.venue}." if sp.clock else f"{sp.periods[0]} under way at {m.venue}.")
        store._log_kickoff(m, at=store.now)
    elif not st["started"]:
        raise HTTPException(409, {"code": "not_started", "message": "Start the match first."})
    elif et.id == "period_end":
        if st["between"]:
            raise HTTPException(409, {"code": "between_periods", "message": "The period has already ended."})
        minute = minute_now(store, st)
        st.update(between=True, running=False, base_minute=minute, base_at=store.now)
        m = _replace(store, m.model_copy(update={"clock": minute if sp.clock else m.clock,
                                                  "period": f"End of {sp.periods[st['period_index']]}"}))
        store._timeline(m, "period", f"End of the {sp.periods[st['period_index']]}: {m.home.short} {m.score[0]}–{m.score[1]} {m.away.short}.")
    elif et.id == "period_start":
        if not st["between"] or st["period_index"] + 1 >= len(sp.periods):
            raise HTTPException(409, {"code": "no_next_period", "message": "There is no next period to start."})
        idx = st["period_index"] + 1
        base = idx * (sp.period_minutes or 0)
        st.update(between=False, period_index=idx, running=sp.clock, base_minute=base, base_at=store.now)
        m = _replace(store, m.model_copy(update={"clock": base if sp.clock else m.clock, "period": sp.periods[idx]}))
        store._timeline(m, "period", f"{sp.periods[idx]} under way.")
    else:
        if st["between"]:
            raise HTTPException(409, {"code": "between_periods", "message": "Start the next period first."})
        minute = minute_now(store, st) if sp.clock else None
        score = list(m.score or [0, 0])
        if et.points:
            score[side] += et.points
        if et.wicket:
            st["wickets"][side] += 1
        if et.ball:
            st["balls"][side] += 1
        who = _player_label(body.player_id, team.id) if team else None
        line = f"{m.home.short} {score[0]}–{score[1]} {m.away.short}"
        text = f"{et.label}{' — ' + team.name if team else ''}{' (' + who + ')' if who else ''}"
        if et.points and sp.pad == "split":
            text = f"{et.label}! {team.name} — {line}{' · ' + who if who else ''}"
        update = {"score": score, "clock": minute if sp.clock else m.clock, "flash": side if et.points else None,
                  "last_event": f"{str(minute) + '′ ' if minute is not None else ''}{text}"}
        m = _replace(store, m.model_copy(update=update))
        if et.feed:
            store.timelines.setdefault(m.id, []).append(_tl(store, m, "goal" if et.points and sp.pad == "split" else "event",
                                                             text, team.id if team else None, et.icon, minute))
        if et.points and sp.pad == "split":
            store.log.add("live_update", store.now, f"{et.label}! {team.name} — {line}", f"{minute or 0}′ · {m.league}",
                          ("match", m.id), teams=[m.home.id, m.away.id], tournament=m.tournament_id)
            store.posts.insert(0, Post(id=f"auto-{store._next_id()}", type="score", sport=m.sport, match_id=m.id,
                                       team_ids=[m.home.id, m.away.id], author="OurSport Live", created_at=store.now,
                                       text=f"Score! {team.name} — {line}{f' ({minute}′)' if minute is not None else ''}"))
    st["seq"] = st.get("seq", 0) + 1
    st["events"].append({
        "seq": st["seq"], "client_seq": body.client_seq, "device_id": body.device_id, "type": et.id, "team": body.team if et.team else None,
        "player_id": body.player_id, "player_label": _player_label(body.player_id, team.id) if team else None,
        "minute": minute_now(store, st) if sp.clock else None, "period": st["period_index"], "at": store.now, "undone": False,
        "timeline_id": store.timelines.get(m.id, [None])[-1].id if store.timelines.get(m.id) else None,
    })
    store._notify()
    return True


def _tl(store: FeedStore, m: Match, kind: str, text: str, team_id: str | None, icon: str, minute: int | None):
    from .models import TimelineEvent

    return TimelineEvent(id=f"tl-{store._next_id()}", minute=minute or 0, kind=kind, text=text, team_id=team_id,
                         at=store.now, icon=icon)


def undo(store: FeedStore, m: Match, client_seq: int, device_id: str) -> None:
    """Take back one event (idempotent). Scores, wickets and balls are reversed; fans see a correction row."""
    sp = sport_of(m)
    st = manual(store, m)
    ev = next((e for e in (st or {}).get("events", []) if e["device_id"] == device_id and e["client_seq"] == client_seq), None)
    if ev is None:
        raise HTTPException(404, {"code": "not_found", "message": "That event hasn’t reached the server."})
    if ev["undone"]:
        return
    if m.status == "finished":
        raise HTTPException(409, {"code": "finished", "message": "The match has finished. Report a correction instead."})
    if ev["type"] in ("start", "period_end", "period_start"):
        raise HTTPException(409, {"code": "control", "message": "Starting or ending a period can’t be undone here."})
    et = next(t for t in sp.event_types if t.id == ev["type"])
    side = None if ev["team"] is None else (0 if ev["team"] == "home" else 1)
    score = list(m.score or [0, 0])
    if et.points and side is not None:
        score[side] = max(0, score[side] - et.points)
    if et.wicket and side is not None:
        st["wickets"][side] = max(0, st["wickets"][side] - 1)
    if et.ball and side is not None:
        st["balls"][side] = max(0, st["balls"][side] - 1)
    ev["undone"] = True
    store.now = _now()
    m = _replace(store, m.model_copy(update={"score": score, "flash": None,
                                              "last_event": f"Correction: {et.label.lower()} taken back"}))
    tl = store.timelines.get(m.id, [])
    if ev.get("timeline_id"):
        store.timelines[m.id] = [e for e in tl if e.id != ev["timeline_id"]]
    team = (m.home, m.away)[side].name if side is not None else ""
    store.timelines.setdefault(m.id, []).append(_tl(store, m, "correction", f"Correction: {et.label.lower()} {('for ' + team) if team else ''} "
                                                    f"taken back. {m.home.short} {score[0]}–{score[1]} {m.away.short}", None, "↩",
                                                    minute_now(store, st) if sp.clock else None))
    store._notify()
