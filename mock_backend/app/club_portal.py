"""Club portal (C-series): data for club admins."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from . import club_members as CM
from . import corrections
from . import club_matches as CMatch
from .mock_data import CLUB_SUBSCRIPTIONS, CLUBS, DEFAULT_SUBSCRIPTION, TEAMS
from .models import ClubDashboard, ClubKpis, Match, NextMatch, Story

if TYPE_CHECKING:
    from .store import FeedStore


def subscription(store: FeedStore, club_id: str) -> dict:
    """The club's subscription (plan, seats, price); billing (C6) changes it, so it lives in the store."""
    if club_id not in store.billing:
        store.billing[club_id] = {**CLUB_SUBSCRIPTIONS.get(club_id, DEFAULT_SUBSCRIPTION), "invoices": None}
    return store.billing[club_id]


def _profiles(store: FeedStore) -> list:
    """Distinct fan profiles (several browsers can share one account's profile)."""
    seen, out = set(), []
    for p in store.sessions.values():
        if id(p) not in seen:
            seen.add(id(p))
            out.append(p)
    return out


def _club_matches(store: FeedStore, club_id: str) -> list[Match]:
    teams = set(CLUBS[club_id].team_ids)
    return [m for m in store.matches if m.home.id in teams or m.away.id in teams]


def club_stories(store: FeedStore, club_id: str) -> list[Story]:
    teams = set(CLUBS[club_id].team_ids)
    out = [s for s in store.stories if s.published_at <= store.now and (s.club_id == club_id or teams & set(s.team_ids))]
    return sorted(out, key=lambda s: -s.published_at)


def story_club_ids(store: FeedStore, story_id: str) -> set[str]:
    s = store.get_story(story_id)
    if s is None:
        return set()
    return ({s.club_id} if s.club_id else set()) | {TEAMS[t].club_id for t in s.team_ids if t in TEAMS}


def _week_bounds(now_ms: int) -> tuple[int, int]:
    d = datetime.fromtimestamp(now_ms / 1000).astimezone()
    start = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000), int((start + timedelta(days=7)).timestamp() * 1000)


def dashboard(store: FeedStore, club_id: str) -> ClubDashboard:
    club = CLUBS[club_id]
    sub = subscription(store, club_id)
    teams = set(club.team_ids)
    profiles = _profiles(store)
    followers = sub["followers_base"] + sum(
        1 for p in profiles if p.signed_in and (club_id in p.clubs or teams & set(p.teams))
    )
    seats = CM.seats(store, club_id)

    week_start, week_end = _week_bounds(store.now)
    games = _club_matches(store, club_id)

    def when(m: Match) -> int:
        return m.starts_at or m.ended_at or store.now

    this_week = [m for m in games if week_start <= when(m) < week_end]
    upcoming = sorted((m for m in games if m.status == "upcoming" and (m.starts_at or 0) > store.now),
                      key=lambda m: m.starts_at or 0)[:6]

    return ClubDashboard(
        club=club,
        plan=sub["plan"],
        kpis=ClubKpis(
            followers=followers,
            premium_seats_used=seats.used,
            premium_seats_total=seats.total,
            matches_this_week=len(this_week),
            open_corrections=corrections.open_count(store, club_id),
        ),
        next_matches=[NextMatch(match=m, scorer=CMatch.scorer_name(store, m.id)) for m in upcoming],
        stories=club_stories(store, club_id)[:5],
        updated_at=store.now,
    )
