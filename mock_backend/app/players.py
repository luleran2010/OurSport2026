"""Player page (F8): visibility rules and a mock season profile built from the team's games."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from . import club_teams
from .mock_data import PLAYERS
from .models import FormItem, Match, Milestone, Player, PlayerMatchLine, PlayerProfile, StatItem

if TYPE_CHECKING:
    from .store import FeedStore

SEASON = "2026"
YEAR_MS = 365 * 24 * 60 * 60 * 1000

def visibility(p: Player) -> str:
    """public / members / private for the fan pages. The club sets it in the portal (C3, club_teams.py):
    under-18s are hidden unless a guardian's consent is on record; an adult may narrow it further."""
    return club_teams.fan_visibility(p)


def get_player(player_id: str) -> Player | None:
    return next((p for p in PLAYERS if p.id == player_id), None)


def featurable(p: Player) -> bool:
    """May appear by name in search, players to watch, player of the match."""
    return visibility(p) != "private"


def _rng(p: Player) -> random.Random:
    return random.Random(f"{p.id}:{SEASON}")


def _is_keeper(p: Player) -> bool:
    return p.position.lower() in ("goalkeeper", "goaltender", "libero")


def _season_stats(p: Player, r: random.Random, min_goals: int = 0, min_assists: int = 0,
                  min_apps: int = 0) -> tuple[list[StatItem], dict]:
    sport = p.team.sport
    gp = max(r.randint(12, 22), min_apps)
    if sport == "football":
        if _is_keeper(p):
            cs = r.randint(3, 8)
            return [StatItem(key="apps", label="Appearances", value=str(gp)),
                    StatItem(key="clean_sheets", label="Clean sheets", value=str(cs)),
                    StatItem(key="saves", label="Saves", value=str(r.randint(30, 70))),
                    StatItem(key="minutes", label="Minutes", value=str(gp * 90))], {"apps": gp, "clean_sheets": cs}
        goals = max(r.randint(2, 11) if p.position in ("Forward", "Winger") else r.randint(0, 5), min_goals)
        return [StatItem(key="apps", label="Appearances", value=str(gp)),
                StatItem(key="goals", label="Goals", value=str(goals)),
                StatItem(key="assists", label="Assists", value=str(max(r.randint(1, 7), min_assists))),
                StatItem(key="minutes", label="Minutes", value=str(gp * r.randint(60, 88)))], {"apps": gp, "goals": goals}
    if sport == "ice-hockey":
        if _is_keeper(p):
            return [StatItem(key="gp", label="Games", value=str(gp)),
                    StatItem(key="sv", label="Save %", value=f"{r.uniform(89.5, 93.5):.1f}"),
                    StatItem(key="gaa", label="Goals against avg", value=f"{r.uniform(2.1, 3.4):.2f}"),
                    StatItem(key="so", label="Shutouts", value=str(r.randint(0, 3)))], {"apps": gp}
        g, a = max(r.randint(3, 14), min_goals), max(r.randint(4, 16), min_assists)
        return [StatItem(key="gp", label="Games", value=str(gp)), StatItem(key="goals", label="Goals", value=str(g)),
                StatItem(key="assists", label="Assists", value=str(a)), StatItem(key="points", label="Points", value=str(g + a))], \
            {"apps": gp, "goals": g, "points": g + a}
    if sport == "floorball":
        g, a = max(r.randint(4, 18), min_goals), max(r.randint(3, 14), min_assists)
        return [StatItem(key="gp", label="Games", value=str(gp)), StatItem(key="goals", label="Goals", value=str(g)),
                StatItem(key="assists", label="Assists", value=str(a)), StatItem(key="points", label="Points", value=str(g + a))], \
            {"apps": gp, "goals": g, "points": g + a}
    if sport == "basketball":
        ppg = r.uniform(8, 21)
        return [StatItem(key="gp", label="Games", value=str(gp)), StatItem(key="ppg", label="Points / game", value=f"{ppg:.1f}"),
                StatItem(key="rpg", label="Rebounds / game", value=f"{r.uniform(2, 9):.1f}"),
                StatItem(key="apg", label="Assists / game", value=f"{r.uniform(1, 7):.1f}")], {"apps": gp, "points": round(ppg * gp)}
    # volleyball
    pts = r.randint(60, 210)
    return [StatItem(key="matches", label="Matches", value=str(gp)), StatItem(key="sets", label="Sets", value=str(gp * 3 + r.randint(0, 9))),
            StatItem(key="points", label="Points", value=str(pts)), StatItem(key="aces", label="Aces", value=str(r.randint(4, 25)))], \
        {"apps": gp, "points": pts}


def _line(p: Player, m: Match, side: int, r: random.Random) -> tuple[str, int, int]:
    """The player's line for one game, plus the goals (or points) and assists in it."""
    mine, theirs = m.score[side], m.score[1 - side]
    sport = p.team.sport
    if sport == "football":
        if _is_keeper(p):
            return ("Clean sheet · 90′" if theirs == 0 else f"{theirs} conceded · 90′"), 0, 0
        g = r.randint(0, min(2, mine))
        text = f"{g} goal{'s' if g != 1 else ''} · {r.choice([72, 85, 90])}′" if g else f"{r.choice([64, 78, 90])}′"
        return text, g, 0
    if sport in ("ice-hockey", "floorball"):
        if _is_keeper(p):
            return f"{theirs} against", 0, 0
        g, a = r.randint(0, min(2, mine)), r.randint(0, 2)
        return f"{g}+{a} ({g + a} pts)", g, a
    if sport == "basketball":
        pts = r.randint(6, 26)
        return f"{pts} pts · {r.randint(1, 10)} reb", pts, 0
    pts = r.randint(4, 18)
    return f"{pts} points", pts, 0


def profile(store: FeedStore, p: Player) -> PlayerProfile:
    r = _rng(p)
    games = sorted(
        (m for m in store.matches if m.status == "finished" and p.team.id in (m.home.id, m.away.id)),
        key=lambda m: -(m.ended_at or 0),
    )[:5]
    recent, form = [], []
    seen_goals = seen_assists = 0
    for m in games:
        side = 0 if m.home.id == p.team.id else 1
        mine, theirs = m.score[side], m.score[1 - side]
        result = "W" if mine > theirs else "L" if mine < theirs else "D"
        line, g, a = _line(p, m, side, r)
        seen_goals += g
        seen_assists += a
        recent.append(PlayerMatchLine(match=m, line=line))
        form.append(FormItem(match_id=m.id, result=result, contribution=line))
    form.reverse()  # oldest -> newest
    # Season totals must at least cover what the recent games show.
    stats, totals = _season_stats(p, _rng(p), min_goals=seen_goals, min_assists=seen_assists, min_apps=len(games))

    now = store.now
    career = totals["apps"] + r.randint(25, 140)
    debut = datetime.fromtimestamp((now - r.randint(2, 7) * YEAR_MS) / 1000)
    milestones = [
        Milestone(title=f"Debut for {p.team.name}", achieved=True, date=int(debut.timestamp() * 1000)),
        Milestone(title="100 appearances for the club", achieved=career >= 100,
                  date=int((datetime.fromtimestamp(now / 1000) - timedelta(days=r.randint(20, 300))).timestamp() * 1000)
                  if career >= 100 else None,
                  progress=min(career, 100), target=100),
    ]
    if "goals" in totals:
        target = 10 if totals["goals"] < 10 else 20
        milestones.append(Milestone(title=f"{target} goals this season", achieved=totals["goals"] >= target,
                                    progress=min(totals["goals"], target), target=target))
    elif "points" in totals:
        target = 250 if totals["points"] < 250 else 500
        milestones.append(Milestone(title=f"{target} points this season", achieved=totals["points"] >= target,
                                    progress=min(totals["points"], target), target=target))
    return PlayerProfile(
        player=p, visibility=visibility(p), season=SEASON, stats=stats, form=form,
        milestones=milestones, recent_matches=recent,
    )
