"""Explore & search (F2): text search with filters, and "near you" lookups."""

import math
import re
import unicodedata
from collections.abc import Iterable

from .players import featurable
from .mock_data import AGE_GROUPS, CLUBS, PLAYERS, REGIONS, SPORTS, TEAMS, VENUES, is_junior
from .models import (
    Club, Match, NearbyClub, NearbyEvent, NearbyResults, Player, SearchFilters,
    SearchOption, SearchResults, SearchType, Team,
)

TYPE_OPTIONS = [
    SearchOption(id="all", label="All"),
    SearchOption(id="clubs", label="Clubs"),
    SearchOption(id="teams", label="Teams"),
    SearchOption(id="events", label="Events"),
    SearchOption(id="players", label="Players"),
]

_SPLIT = re.compile(r"[\s\-·/,.()]+")
_STATUS_ORDER = {"live": 0, "upcoming": 1, "finished": 2}


def norm(text: str) -> str:
    """Lowercase and strip accents so 'karpat' finds 'Kärpät'."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


def _token_score(token: str, field: str) -> int:
    if field == token:
        return 100
    if field.startswith(token):
        return 80
    if any(w.startswith(token) for w in _SPLIT.split(field)):
        return 60
    return 40 if token in field else 0


def text_score(tokens: list[str], fields: Iterable[str | None]) -> int:
    """Every query token must match some field; 1 when there is no query (browse)."""
    if not tokens:
        return 1
    nfields = [norm(f) for f in fields if f]
    total = 0
    for t in tokens:
        best = max((_token_score(t, f) for f in nfields), default=0)
        if best == 0:
            return 0
        total += best
    return total


def _match_region(m: Match) -> str:
    venue = VENUES.get(m.venue)
    return venue[2] if venue else m.home.region


def _keep(value: str | None, *candidates: str) -> bool:
    return value in (None, "", "all") or value in candidates


def search(
    matches: list[Match],
    q: str = "",
    type_: SearchType = "all",
    sport: str | None = None,
    region: str | None = None,
    age: str | None = None,
    limit: int = 20,
) -> SearchResults:
    tokens = [t for t in _SPLIT.split(norm(q)) if t]

    def club_ok(c: Club) -> bool:
        ages = {TEAMS[t].age_group for t in c.team_ids}
        return _keep(sport, *c.sports) and _keep(region, c.region) and _keep(age, *ages)

    def team_ok(t: Team) -> bool:
        return _keep(sport, t.sport) and _keep(region, t.region) and _keep(age, t.age_group)

    clubs = [
        (s, c) for c in CLUBS.values() if club_ok(c)
        and (s := text_score(tokens, [c.name, c.short, c.city, *[TEAMS[t].name for t in c.team_ids]]))
    ]
    teams = [
        (s, t) for t in TEAMS.values() if team_ok(t)
        and (s := text_score(tokens, [t.name, t.short, t.league, CLUBS[t.club_id].name, CLUBS[t.club_id].city]))
    ]
    events = [
        (s, m) for m in matches
        if _keep(sport, m.sport) and _keep(region, _match_region(m)) and _keep(age, m.home.age_group)
        and (s := text_score(tokens, [m.home.name, m.away.name, m.home.short, m.away.short, m.league, m.venue]))
    ]
    players = [
        (s, p) for p in PLAYERS if team_ok(p.team) and not is_junior(p.team)  # junior protection
        and featurable(p)  # private profiles are never listed by name
        and (s := text_score(tokens, [p.name, p.position, str(p.number), p.team.name]))
    ]

    clubs.sort(key=lambda x: (-x[0], x[1].name))
    teams.sort(key=lambda x: (-x[0], x[1].name))
    players.sort(key=lambda x: (-x[0], x[1].name))
    events.sort(key=lambda x: (
        -x[0],
        _STATUS_ORDER[x[1].status],
        (x[1].starts_at or 0) if x[1].status == "upcoming" else -(x[1].ended_at or 0),
    ))

    groups = {"clubs": clubs, "teams": teams, "events": events, "players": players}
    if type_ != "all":
        groups = {k: (v if k == type_ else []) for k, v in groups.items()}
    counts = {k: len(v) for k, v in groups.items()}
    return SearchResults(
        query=q,
        total=sum(counts.values()),
        counts=counts,
        **{k: [item for _, item in v[:limit]] for k, v in groups.items()},
    )


def filters() -> SearchFilters:
    return SearchFilters(types=TYPE_OPTIONS, sports=SPORTS, regions=REGIONS, age_groups=AGE_GROUPS)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearby(matches: list[Match], lat: float, lon: float, radius_km: float = 50, limit: int = 6) -> NearbyResults:
    clubs = sorted(
        (NearbyClub(**c.model_dump(), distance_km=round(distance_km(lat, lon, c.lat, c.lon), 1)) for c in CLUBS.values()),
        key=lambda c: c.distance_km,
    )
    events = []
    for m in matches:
        venue = VENUES.get(m.venue)
        if m.status == "finished" or venue is None:
            continue
        d = round(distance_km(lat, lon, venue[0], venue[1]), 1)
        events.append(NearbyEvent(**m.model_dump(), distance_km=d))
    events.sort(key=lambda e: (_STATUS_ORDER[e.status], e.distance_km))
    return NearbyResults(
        clubs=[c for c in clubs if c.distance_km <= radius_km][:limit],
        events=[e for e in events if e.distance_km <= radius_km][:limit],
    )
