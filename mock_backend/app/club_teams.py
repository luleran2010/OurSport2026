"""Club portal C3: teams and players, with junior protection.

Rules (enforced here, the page only mirrors them):
- A player born in or after ``minor_cutoff()`` counts as under 18 (birthdays aren't stored, so a player who
  turns 18 this year is still treated as a minor).
- Under-18s default to *hidden*. *family* (only linked family members see the profile) needs a consent record.
  *public* for an under-18 needs a guardian's consent with scope "public". Adults can be public without one.
- Withdrawing consent drops the profile back to the most private setting that is still allowed (hidden).

Fan pages read the result through ``fan_visibility`` / ``guardian_access`` (players.py, main.py).

The team and player registries live in mock_data (TEAMS, CLUBS, PLAYERS) and are shared with the fan side;
``reset_registry`` restores them for every store reset so tests and restarts start from the same data.
"""

from __future__ import annotations

import random
import secrets
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException

from .mock_data import AGE_GROUPS, CLUBS, DEMO_EMAIL, DEMO_USER_NAME, PLAYERS, SPORTS, TEAMS, FIRST_NAMES, LAST_NAMES
from .models import (
    ClubTeams, Consent, FamilyMember, Player, RosterPlayer, Team, TeamRoster, TeamSummary,
)

if TYPE_CHECKING:
    from .store import FeedStore, Session

# Snapshots of the shared registries as shipped (restored on every reset).
_SEED_TEAMS = {k: v.model_copy() for k, v in TEAMS.items()}
_SEED_CLUBS = {k: c.model_copy(deep=True) for k, c in CLUBS.items()}  # whole club profiles (C5 edits them too)
_SEED_PLAYERS = [(p.id, p.name, p.number, p.position, p.team.id) for p in PLAYERS]
_SEED_PLAYERS_NAMES = [(p.name,) for p in PLAYERS]

# player id -> {birth_year, visibility, consent (dict | None), family: [dict(id, name, email)]}
RECORDS: dict[str, dict] = {}

# An adult player's own narrower setting for the fan side (F8 demo data).
OWN_SETTING = {"pl7": "members", "pl12": "private"}

POSITIONS = {
    "football": ["Goalkeeper", "Defender", "Defender", "Midfielder", "Midfielder", "Winger", "Forward"],
    "floorball": ["Goalkeeper", "Defender", "Defender", "Centre", "Forward", "Forward"],
    "ice-hockey": ["Goaltender", "Defence", "Defence", "Centre", "Winger", "Winger"],
}
EXTRA_SQUAD = {"tarmo": 14, "tarmou17": 15, "olsu17": 14, "olsfb": 12}  # demo squads for the portal clubs


def this_year() -> int:
    return datetime.now().year


def minor_cutoff() -> int:
    return this_year() - 18


def is_minor(birth_year: int) -> bool:
    return birth_year >= minor_cutoff()


# ---- seeding -----------------------------------------------------------------------------

def reset_registry(store: FeedStore) -> None:
    """Restore teams/clubs/players to the shipped data, then add demo squads and roster records."""
    TEAMS.clear()
    TEAMS.update({k: v.model_copy() for k, v in _SEED_TEAMS.items()})
    for k, c in CLUBS.items():  # same objects (other modules hold them), shipped values
        seed = _SEED_CLUBS[k].model_copy(deep=True)
        for field in type(c).model_fields:
            setattr(c, field, getattr(seed, field))
    PLAYERS[:] = [Player(id=i, name=n, number=no, position=pos, team=TEAMS[t]) for i, n, no, pos, t in _SEED_PLAYERS]
    RECORDS.clear()

    now = store.now
    for p in list(PLAYERS):
        rng = random.Random(p.id)
        RECORDS[p.id] = {"birth_year": _birth_year(p.team, rng), "visibility": "public", "consent": None, "family": []}
    for team_id, n in EXTRA_SQUAD.items():
        team = TEAMS[team_id]
        rng = random.Random(f"squad:{team_id}")
        taken = {p.number for p in PLAYERS if p.team.id == team_id}
        names = {p.name for p in PLAYERS}
        # fresh first names only, so a search for an existing player's first name still finds just them
        firsts = [f for f in FIRST_NAMES if f not in {x.split()[0] for x, *_ in _SEED_PLAYERS_NAMES}]
        for k in range(n):
            while (name := f"{rng.choice(firsts)} {rng.choice(LAST_NAMES)}") in names:
                pass
            names.add(name)
            number = next(x for x in [1, *range(2, 40)] if x not in taken) if k else 1
            if number in taken:
                number = next(x for x in range(2, 99) if x not in taken)
            taken.add(number)
            pos = POSITIONS[team.sport][0] if number == 1 else rng.choice(POSITIONS[team.sport][1:])
            pid = f"pl-{team_id}-{k + 1}"
            PLAYERS.append(Player(id=pid, name=name, number=number, position=pos, team=team))
            RECORDS[pid] = {"birth_year": _birth_year(team, rng), "visibility": "public", "consent": None, "family": []}

    # Junior protection for the seed: under-18s hidden, a few with family consent on record.
    for pid, rec in RECORDS.items():
        if is_minor(rec["birth_year"]):
            rec["visibility"] = "hidden"
    _seed_consent("pl4", DEMO_USER_NAME, DEMO_EMAIL, "family", now)  # the demo account is Veeti's guardian
    for pid, scope in (("pl-olsu17-2", "family"), ("pl-olsu17-5", "family"), ("pl-tarmou17-3", "family"),
                       ("pl-tarmou17-7", "public")):
        if pid in RECORDS:
            first = next(p for p in PLAYERS if p.id == pid).name.split()[-1]
            parent = f"{random.Random(pid).choice(FIRST_NAMES)} {first}"
            _seed_consent(pid, parent, f"{parent.lower().replace(' ', '.').replace('ä', 'a').replace('ö', 'o')}@example.com",
                          scope, now)
    for p in PLAYERS:  # older teams' birth years for the fan-side age groups stay plausible
        p.team = TEAMS[p.team.id]


def _birth_year(team: Team, rng: random.Random) -> int:
    y = this_year()
    if team.age_group == "u17":
        return rng.choice([y - 17, y - 16, y - 16, y - 15])
    if team.age_group == "u20":
        return rng.choice([y - 20, y - 19, y - 19, y - 18])
    return rng.randint(y - 34, y - 19)


def _seed_consent(pid: str, name: str, email: str, scope: str, now: int) -> None:
    rec = RECORDS[pid]
    rec["consent"] = {"given_by": name, "email": email, "relation": "guardian", "scope": scope,
                      "recorded_at": now - 40 * 86_400_000, "recorded_by": "Club admin"}
    rec["family"].append({"id": f"fam-{pid}", "name": name, "email": email})
    rec["visibility"] = scope


# ---- fan side ----------------------------------------------------------------------------

def record(player_id: str) -> dict | None:
    return RECORDS.get(player_id)


def fan_visibility(p: Player) -> str:
    """public / members / private, as the fan pages know it. Unknown players (no record) stay private if junior."""
    rec = RECORDS.get(p.id)
    if rec is None:
        return "private" if p.team.age_group != "senior" else "public"
    if rec["visibility"] != "public":
        return "private"
    return OWN_SETTING.get(p.id, "public")


def guardian_access(p: Player) -> bool:
    """Linked family members see the profile unless the club hid it completely."""
    rec = RECORDS.get(p.id)
    return rec is None or rec["visibility"] != "hidden"


def apply_family_links(store: FeedStore, profile: Session) -> None:
    """After sign-up / log-in: links the club made to this email start working."""
    if not profile.email:
        return
    for pid, rec in RECORDS.items():
        if any(f["email"].lower() == profile.email.lower() for f in rec["family"]) and pid not in profile.family:
            profile.family.append(pid)


# ---- reads -------------------------------------------------------------------------------

def competitions(store: FeedStore, team: Team) -> list[str]:
    names = {team.league} if team.league else set()
    for m in store.matches:
        if team.id in (m.home.id, m.away.id):
            t = store.tournaments.get(m.tournament_id or "")
            names.add(t.name if t else m.league)
    names = {n for n in names if n}
    # "Kakkonen" and "Kakkonen · Group C" are the same competition: keep the more specific name
    return sorted(n for n in names if not any(o != n and o.startswith(f"{n} ·") for o in names))


def _club_teams(club_id: str) -> list[Team]:
    return [TEAMS[t] for t in CLUBS[club_id].team_ids if t in TEAMS]


def _squad(team_id: str) -> list[Player]:
    return [p for p in PLAYERS if p.team.id == team_id]


def club_teams(store: FeedStore, club_id: str) -> ClubTeams:
    teams = []
    for t in _club_teams(club_id):
        squad = _squad(t.id)
        recs = [RECORDS.get(p.id) or {} for p in squad]
        teams.append(TeamSummary(team=t, competitions=competitions(store, t), players=len(squad),
                                 minors=sum(1 for r in recs if is_minor(r.get("birth_year", 0))),
                                 hidden=sum(1 for r in recs if r.get("visibility") == "hidden")))
    return ClubTeams(club=CLUBS[club_id], teams=teams, sports=[s for s in SPORTS if s.id != "all"], age_groups=AGE_GROUPS)


def allowed(rec: dict) -> list[str]:
    out = ["hidden"]
    consent = rec["consent"]
    if consent:
        out.insert(0, "family")
    if not is_minor(rec["birth_year"]) or (consent and consent["scope"] == "public"):
        out.insert(0, "public")
    return out


def _accounts_with(store: FeedStore, email: str) -> list[Session]:
    from .club_portal import _profiles

    return [p for p in _profiles(store) if p.email and p.email.lower() == email.lower()]


def to_roster_player(store: FeedStore, p: Player) -> RosterPlayer:
    rec = RECORDS[p.id]
    minor = is_minor(rec["birth_year"])
    return RosterPlayer(
        id=p.id, name=p.name, number=p.number, position=p.position, birth_year=rec["birth_year"], minor=minor,
        visibility=rec["visibility"], allowed=allowed(rec),
        own_setting=OWN_SETTING.get(p.id) if not minor and rec["visibility"] == "public" else None,
        consent=Consent(**rec["consent"]) if rec["consent"] else None,
        family=[FamilyMember(id=f["id"], name=f["name"], email=f["email"], has_account=bool(_accounts_with(store, f["email"])))
                for f in rec["family"]],
    )


def team_roster(store: FeedStore, team: Team) -> TeamRoster:
    squad = sorted(_squad(team.id), key=lambda p: (p.number, p.name))
    for p in squad:
        RECORDS.setdefault(p.id, {"birth_year": this_year() - 25, "visibility": "public", "consent": None, "family": []})
    return TeamRoster(team=team, club=CLUBS[team.club_id], competitions=competitions(store, team),
                      minor_cutoff_year=minor_cutoff(), players=[to_roster_player(store, p) for p in squad])


# ---- access ------------------------------------------------------------------------------

def require_admin(session: Session, club_id: str) -> None:
    if not session.signed_in:
        raise HTTPException(401, "Log in with your club admin account.")
    if not session.is_admin(club_id):
        raise HTTPException(403, {"code": "not_club_admin", "message": "You’re not an admin of this club."})


def team_for_admin(team_id: str, session: Session) -> Team:
    team = TEAMS.get(team_id)
    if team is None:
        raise HTTPException(404, "Team not found")
    require_admin(session, team.club_id)
    return team


def player_for_admin(player_id: str, session: Session) -> Player:
    p = next((x for x in PLAYERS if x.id == player_id), None)
    if p is None:
        raise HTTPException(404, "Player not found")
    require_admin(session, p.team.club_id)
    RECORDS.setdefault(p.id, {"birth_year": this_year() - 25, "visibility": "public", "consent": None, "family": []})
    return p


# ---- writes: teams -----------------------------------------------------------------------

def _check_team_fields(club_id: str, name: str | None, sport: str | None, age_group: str | None, skip: str | None = None):
    if name and any(t.name.lower() == name.strip().lower() and t.id != skip for t in _club_teams(club_id)):
        raise HTTPException(409, {"code": "team_exists", "message": "The club already has a team with this name."})
    if sport is not None and sport not in {s.id for s in SPORTS if s.id != "all"}:
        raise HTTPException(422, {"code": "sport", "message": "Unknown sport."})
    if age_group is not None and age_group not in {a.id for a in AGE_GROUPS}:
        raise HTTPException(422, {"code": "age_group", "message": "Unknown age group."})


def create_team(store: FeedStore, club_id: str, body) -> TeamSummary:
    _check_team_fields(club_id, body.name, body.sport, body.age_group)
    club = CLUBS[club_id]
    base = "".join(ch for ch in body.name.lower() if ch.isalnum())[:12] or "team"
    tid = base if base not in TEAMS else f"{base}-{secrets.token_hex(2)}"
    team = Team(id=tid, name=body.name.strip(), short=(body.short or club.short).upper()[:4], color=club.color,
                sport=body.sport, league=body.league.strip(), club_id=club_id, region=club.region, age_group=body.age_group)
    TEAMS[tid] = team
    club.team_ids.append(tid)
    if body.sport not in club.sports:
        club.sports = sorted({*club.sports, body.sport})
    return TeamSummary(team=team, competitions=competitions(store, team), players=0, minors=0, hidden=0)


def update_team(store: FeedStore, team: Team, body) -> Team:
    _check_team_fields(team.club_id, body.name, None, body.age_group, skip=team.id)
    for field in ("name", "short", "age_group", "league"):
        value = getattr(body, field)
        if value is not None:
            setattr(team, field, value.strip().upper() if field == "short" else value.strip() if isinstance(value, str) else value)
    return team


# ---- writes: players ---------------------------------------------------------------------

def _not_allowed(visibility: str, rec: dict) -> HTTPException:
    minor = is_minor(rec["birth_year"])
    if visibility == "family":
        msg = "“Family only” needs a consent record. Record consent first."
    elif minor and rec["consent"]:
        msg = "A public profile for a player under 18 needs a guardian’s consent to a public profile."
    else:
        msg = "A player under 18 can’t be public without a guardian’s consent to a public profile."
    return HTTPException(409, {"code": "consent_required", "message": msg, "allowed": allowed(rec)})


def _check_number(team: Team, number: int, skip: str | None = None) -> None:
    if any(p.number == number and p.id != skip for p in _squad(team.id)):
        raise HTTPException(409, {"code": "number_taken", "message": f"Number {number} is already taken in {team.name}."})


def _check_birth_year(year: int) -> None:
    if year > this_year() - 4:
        raise HTTPException(422, {"code": "birth_year", "message": "Check the birth year."})


def add_player(store: FeedStore, team: Team, body) -> RosterPlayer:
    _check_number(team, body.number)
    _check_birth_year(body.birth_year)
    rec = {"birth_year": body.birth_year, "visibility": "hidden", "consent": None, "family": []}
    want = body.visibility or ("hidden" if is_minor(body.birth_year) else "public")
    if want not in allowed(rec):
        raise _not_allowed(want, rec)
    rec["visibility"] = want
    pid = f"pl-{secrets.token_hex(4)}"
    p = Player(id=pid, name=body.name.strip(), number=body.number,
               position=body.position.strip() or POSITIONS.get(team.sport, ["Player"])[-1], team=team)
    PLAYERS.append(p)
    RECORDS[pid] = rec
    return to_roster_player(store, p)


def update_player(store: FeedStore, p: Player, body) -> RosterPlayer:
    rec = RECORDS[p.id]
    if body.number is not None:
        _check_number(p.team, body.number, skip=p.id)
    if body.birth_year is not None:
        _check_birth_year(body.birth_year)
    after = {**rec, "birth_year": body.birth_year if body.birth_year is not None else rec["birth_year"]}
    want = body.visibility or rec["visibility"]
    if want not in allowed(after):
        if body.visibility is None:  # e.g. the new birth year makes a public adult an under-18
            raise HTTPException(409, {"code": "consent_required", "allowed": allowed(after),
                                      "message": "With this birth year the player is under 18: set the profile to hidden first."})
        raise _not_allowed(want, after)
    rec.update(birth_year=after["birth_year"], visibility=want)
    if body.name is not None:
        p.name = body.name.strip()
    if body.number is not None:
        p.number = body.number
    if body.position is not None:
        p.position = body.position.strip()
    return to_roster_player(store, p)


def record_consent(store: FeedStore, p: Player, body, session: Session) -> RosterPlayer:
    rec = RECORDS[p.id]
    if is_minor(rec["birth_year"]) and body.relation != "guardian":
        raise HTTPException(422, {"code": "guardian_required", "message": "For a player under 18 the consent must come from a guardian."})
    if body.link_family and body.relation == "guardian" and not body.email:
        raise HTTPException(422, {"code": "email_required", "message": "Add the guardian’s email to link their account."})
    rec["consent"] = {"given_by": body.given_by.strip(), "email": body.email, "relation": body.relation, "scope": body.scope,
                      "recorded_at": store.now, "recorded_by": session.name}
    if rec["visibility"] not in allowed(rec):  # e.g. replaced a public consent with a family-only one
        rec["visibility"] = "family"
    if body.link_family and body.relation == "guardian" and body.email:
        _link(store, p, rec, body.given_by.strip(), body.email)
    return to_roster_player(store, p)


def withdraw_consent(store: FeedStore, p: Player) -> RosterPlayer:
    rec = RECORDS[p.id]
    rec["consent"] = None
    if rec["visibility"] not in allowed(rec):
        rec["visibility"] = "hidden"
    return to_roster_player(store, p)


def _link(store: FeedStore, p: Player, rec: dict, name: str, email: str) -> None:
    if not any(f["email"].lower() == email.lower() for f in rec["family"]):
        rec["family"].append({"id": f"fam-{secrets.token_hex(4)}", "name": name, "email": email})
    for prof in _accounts_with(store, email):
        if p.id not in prof.family:
            prof.family.append(p.id)


def link_family(store: FeedStore, p: Player, body) -> RosterPlayer:
    rec = RECORDS[p.id]
    if not is_minor(rec["birth_year"]):
        raise HTTPException(409, {"code": "not_junior", "message": "Family members are linked to players under 18."})
    _link(store, p, rec, body.name.strip(), body.email)
    return to_roster_player(store, p)


def unlink_family(store: FeedStore, p: Player, link_id: str) -> RosterPlayer:
    rec = RECORDS[p.id]
    link = next((f for f in rec["family"] if f["id"] == link_id), None)
    if link is None:
        raise HTTPException(404, "Family link not found")
    rec["family"].remove(link)
    for prof in _accounts_with(store, link["email"]):
        if p.id in prof.family:
            prof.family.remove(p.id)
    return to_roster_player(store, p)
