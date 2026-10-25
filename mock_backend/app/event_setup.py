"""Publisher P2: the create-event wizard (basics, teams, fixtures, rulebook) and the rules reading job.

A new event is a draft in store.publisher_events until the publisher confirms its rules (P3). Every step saves
straight away, so the wizard can be left and continued (/publisher/events/{id}/setup).

The rulebook "AI" here is a mock: it reads plain text out of the upload (TXT, DOCX, simple PDFs, pasted text),
looks for points, match length, tiebreakers and how many teams go through, and fills the rest from the sport's usual
rules, marking those as "check this" for P3. A web link isn't fetched in the demo.
"""

from __future__ import annotations

import csv
import io
import re
import secrets
import zipfile
import zlib
from datetime import date, datetime, timedelta
from itertools import combinations
from typing import TYPE_CHECKING

from fastapi import HTTPException

from .mock_data import AGE_GROUPS, SPORTS, TEAMS
from .models import EventSetup, Fixture, FixtureImportResult, FixtureProblem, Rulebook, RulesJob, RulesStatus, SetupGroup, SetupTeam

if TYPE_CHECKING:
    from .store import FeedStore, Session

SPORT_IDS = {s.id for s in SPORTS if s.id != "all"}
AGE_IDS = {a.id for a in AGE_GROUPS}
COLORS = ["#e4572e", "#2e86ab", "#3bb273", "#7768ae", "#e0a100", "#d7263d", "#1b998b", "#f46036", "#255f85", "#6d597a"]
READ_SECONDS = 6  # how long the mock AI takes to read a rulebook
MAX_RULEBOOK = 10 * 1024 * 1024
STEPS = ["Reading the document", "Finding points and tiebreakers", "Checking the format and match length", "Writing the summary"]
SPORT_DEFAULTS = {
    "football": {"points_win": 3, "points_draw": 1, "match_minutes": 90, "tiebreakers": ["Goal difference", "Goals scored", "Head-to-head"]},
    "floorball": {"points_win": 3, "points_draw": 1, "match_minutes": 60, "tiebreakers": ["Goal difference", "Goals scored"]},
    "ice-hockey": {"points_win": 3, "points_draw": 1, "match_minutes": 60, "tiebreakers": ["Goal difference", "Goals scored"]},
    "basketball": {"points_win": 2, "points_draw": 0, "match_minutes": 40, "tiebreakers": ["Head-to-head", "Point difference"]},
    "volleyball": {"points_win": 3, "points_draw": 0, "match_minutes": 90, "tiebreakers": ["Set ratio", "Point ratio"]},
    "cricket": {"points_win": 2, "points_draw": 1, "match_minutes": 90, "tiebreakers": ["Net run rate", "Head-to-head"]},
}


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000).astimezone().date().isoformat()


def _ms(day: str, end: bool = False) -> int:
    d = datetime.fromisoformat(day).astimezone() if "T" in day else datetime.combine(date.fromisoformat(day), datetime.min.time()).astimezone()
    return int((d + (timedelta(hours=23, minutes=59) if end else timedelta())).timestamp() * 1000)


def normalise(e: dict) -> dict:
    """Wizard fields for any publisher event (older seeded drafts didn't have them)."""
    e.setdefault("step", 4 if e.get("status") == "rules_pending" else 0)
    e.setdefault("venues", [e["venue"]] if e.get("venue") else [])
    e.setdefault("age_group", "senior")
    e.setdefault("languages", ["fi", "en"])
    e.setdefault("logo_url", None)
    e.setdefault("groups", [{"id": "A", "name": "Group A"}])
    if not isinstance(e.get("teams"), list):
        e["planned_teams"] = e.get("teams") or 0
        e["teams"] = []
    e.setdefault("fixtures", [])
    e.setdefault("rulebook", None)
    e.setdefault("rules_job", None)
    e.setdefault("rules", None)
    return e


# ---- access ------------------------------------------------------------------------------

def owned(store: FeedStore, event_id: str, session: Session) -> dict:
    from .publisher import require_publisher

    require_publisher(session)
    e = store.publisher_events.get(event_id)
    if e is None:
        raise HTTPException(404, "Event not found")
    if (session.email or "").lower() not in {o.lower() for o in e["owners"]}:
        raise HTTPException(403, {"code": "not_your_event", "message": "This event belongs to another publisher."})
    if e.get("tournament_id"):
        raise HTTPException(409, {"code": "published", "message": "The event is published; its setup can’t be changed here."})
    return normalise(e)


# ---- read --------------------------------------------------------------------------------

def setup(store: FeedStore, event_id: str) -> EventSetup:
    e = normalise(store.publisher_events[event_id])
    tick_job(store, e)
    job = e["rules_job"]
    return EventSetup(
        id=event_id, status=e["status"], step=e["step"], name=e["name"], sport=e["sport"],
        start_date=_iso(e["starts_at"]) if e.get("starts_at") else None, end_date=_iso(e["ends_at"]) if e.get("ends_at") else None,
        venues=e["venues"], age_group=e["age_group"], languages=e["languages"], logo_url=e["logo_url"],
        groups=[SetupGroup(**g) for g in e["groups"]], teams=[SetupTeam(**t) for t in e["teams"]],
        fixtures=[Fixture(**f) for f in e["fixtures"]],
        rulebook=Rulebook(**e["rulebook"]) if e["rulebook"] else None,
        rules_job=RulesJob(**{k: job[k] for k in ("status", "progress", "step", "started_at")}) if job else None,
        updated_at=store.now,
    )


# ---- step 1: basics ----------------------------------------------------------------------

def _check_basics(store: FeedStore, d: dict) -> None:
    if d["sport"] not in SPORT_IDS:
        raise HTTPException(422, {"code": "sport", "field": "sport", "message": "Pick a sport."})
    if d["age_group"] not in AGE_IDS:
        raise HTTPException(422, {"code": "age_group", "field": "ageGroup", "message": "Pick an age group."})
    start, end = date.fromisoformat(d["start_date"]), date.fromisoformat(d["end_date"])
    if end < start:
        raise HTTPException(422, {"code": "dates", "field": "endDate", "message": "The event can’t end before it starts."})
    if start < date.fromisoformat(_iso(store.now)):
        raise HTTPException(422, {"code": "dates", "field": "startDate", "message": "The start date is in the past."})
    if (end - start).days > 60:
        raise HTTPException(422, {"code": "dates", "field": "endDate", "message": "An event can last at most 60 days."})
    if not all(v.strip() for v in d["venues"]):
        raise HTTPException(422, {"code": "venues", "field": "venues", "message": "Give every venue a name."})
    if d.get("logo_url"):
        from .club_profile import _check_image_url
        _check_image_url(store, d["logo_url"])


def create(store: FeedStore, body, session: Session) -> EventSetup:
    from .publisher import require_publisher

    require_publisher(session)
    d = body.model_dump()
    d["venues"] = [v.strip() for v in d["venues"] if v.strip()] or [""]
    _check_basics(store, d)
    base = re.sub(r"[^a-z0-9]+", "-", d["name"].lower()).strip("-")[:30] or "event"
    eid = base if base not in store.publisher_events and base not in store.tournaments else f"{base}-{secrets.token_hex(2)}"
    store.publisher_events[eid] = normalise({
        "owners": [session.email], "review_enabled": False, "status": "draft", "step": 1, "name": d["name"].strip(),
        "sport": d["sport"], "starts_at": _ms(d["start_date"]), "ends_at": _ms(d["end_date"], end=True), "venue": d["venues"][0],
        "venues": d["venues"], "age_group": d["age_group"], "languages": list(dict.fromkeys(d["languages"])),
        "logo_url": d["logo_url"], "groups": [{"id": "A", "name": "Group A"}], "teams": [], "fixtures": [],
        "matches_total": 0, "next_step": "Add the teams.",
    })
    return setup(store, eid)


def update(store: FeedStore, event_id: str, e: dict, body, fields: set[str]) -> EventSetup:
    basics = {"name", "sport", "start_date", "end_date", "venues", "age_group", "languages", "logo_url"}
    if fields & basics:
        cur = {"name": e["name"], "sport": e["sport"], "start_date": _iso(e["starts_at"]), "end_date": _iso(e["ends_at"]),
               "venues": e["venues"], "age_group": e["age_group"], "languages": e["languages"], "logo_url": e["logo_url"]}
        for f in fields & basics:
            cur[f] = getattr(body, f)
        cur["venues"] = [v.strip() for v in cur["venues"] if v and v.strip()]
        if not cur["venues"]:
            raise HTTPException(422, {"code": "venues", "field": "venues", "message": "Add at least one venue."})
        if cur["sport"] != e["sport"] and any(not t["new"] for t in e["teams"]):
            raise HTTPException(409, {"code": "sport_has_teams", "field": "sport",
                                      "message": "Remove the OurSport teams first: they play another sport."})
        _check_basics(store, cur)
        e.update(name=cur["name"].strip(), sport=cur["sport"], starts_at=_ms(cur["start_date"]), ends_at=_ms(cur["end_date"], end=True),
                 venues=cur["venues"], venue=cur["venues"][0], age_group=cur["age_group"],
                 languages=list(dict.fromkeys(cur["languages"])), logo_url=cur["logo_url"])
    if "groups" in fields and body.groups is not None:
        if not body.groups:
            raise HTTPException(422, {"code": "groups", "message": "Keep at least one group."})
        ids = [g.id for g in body.groups]
        if len(set(ids)) != len(ids) or any(not g.name.strip() for g in body.groups):
            raise HTTPException(422, {"code": "groups", "message": "Every group needs its own name."})
        e["groups"] = [{"id": g.id, "name": g.name.strip()} for g in body.groups]
        for t in e["teams"]:
            if t["group"] not in ids:
                t["group"] = ids[0] if len(ids) == 1 else None
    if "team_groups" in fields and body.team_groups:
        ids = {g["id"] for g in e["groups"]}
        for tid, gid in body.team_groups.items():
            t = next((x for x in e["teams"] if x["id"] == tid), None)
            if t is None or (gid is not None and gid not in ids):
                raise HTTPException(422, {"code": "team_group", "message": "Unknown team or group."})
            t["group"] = gid
    if "fixtures" in fields and body.fixtures is not None:
        rows = [f.model_dump() for f in body.fixtures]
        problems = check_fixtures(e, rows)
        if problems:
            raise HTTPException(422, {"code": "fixtures", "message": f"{len(problems)} problem(s) in the fixtures.",
                                      "problems": [p.model_dump(by_alias=True) for p in problems]})
        e["fixtures"] = rows
    if "step" in fields and body.step is not None:
        validate_step(e, body.step)
        e["step"] = max(e["step"], body.step)
    e["matches_total"] = len(e["fixtures"])
    e["next_step"] = _next_step(e)
    return setup(store, event_id)


def validate_step(e: dict, step: int) -> None:
    """A step can be marked done only when its required fields are valid (the wizard's Next button)."""
    if step >= 2:
        if len(e["teams"]) < 2:
            raise HTTPException(422, {"code": "teams", "message": "Add at least two teams."})
        if len(e["groups"]) > 1 and any(t["group"] is None for t in e["teams"]):
            raise HTTPException(422, {"code": "teams", "message": "Put every team in a group."})
        for g in e["groups"]:
            if len(e["groups"]) > 1 and sum(1 for t in e["teams"] if t["group"] == g["id"]) < 2:
                raise HTTPException(422, {"code": "teams", "message": f"{g['name']} needs at least two teams."})
    if step >= 3:
        if not e["fixtures"]:
            raise HTTPException(422, {"code": "fixtures", "message": "Add the fixtures (import a CSV or generate them)."})
        problems = check_fixtures(e, e["fixtures"])
        if problems:
            raise HTTPException(422, {"code": "fixtures", "message": "Fix the fixtures first."})
    if step >= 4 and not e["rulebook"]:
        raise HTTPException(422, {"code": "rulebook", "message": "Add the rulebook."})


def _next_step(e: dict) -> str:
    if e["status"] == "rules_pending":
        return "Check the rules read from the rulebook and confirm them."
    return {0: "Fill in the basics.", 1: "Add the teams.", 2: "Add the fixtures.", 3: "Upload the rulebook."}.get(
        e["step"], "Waiting for the rules to be read.")


# ---- step 2: teams -----------------------------------------------------------------------

def add_team(store: FeedStore, event_id: str, e: dict, body) -> EventSetup:
    if len(e["teams"]) >= 64:
        raise HTTPException(409, {"code": "too_many", "message": "An event can have up to 64 teams."})
    group = body.group if body.group in {g["id"] for g in e["groups"]} else (e["groups"][0]["id"] if len(e["groups"]) == 1 else None)
    if body.team_id:
        t = TEAMS.get(body.team_id)
        if t is None:
            raise HTTPException(404, "Team not found")
        if t.sport != e["sport"]:
            raise HTTPException(422, {"code": "sport", "message": f"{t.name} plays another sport."})
        if any(x["id"] == t.id for x in e["teams"]):
            raise HTTPException(409, {"code": "team_added", "message": f"{t.name} is already in the event."})
        e["teams"].append({"id": t.id, "name": t.name, "short": t.short, "color": t.color, "club_id": t.club_id, "new": False, "group": group})
    else:
        if not body.name:
            raise HTTPException(422, {"code": "name", "message": "Give the new team a name."})
        name = body.name.strip()
        if any(x["name"].lower() == name.lower() for x in e["teams"]):
            raise HTTPException(409, {"code": "team_added", "message": f"{name} is already in the event."})
        short = (body.short or re.sub(r"[^A-Za-zÅÄÖåäö]", "", name)[:3] or "TM").upper()[:4]
        e["teams"].append({"id": f"new-{secrets.token_hex(3)}", "name": name, "short": short,
                           "color": COLORS[len(e["teams"]) % len(COLORS)], "club_id": None, "new": True, "group": group})
    return setup(store, event_id)


def remove_team(store: FeedStore, event_id: str, e: dict, team_id: str) -> EventSetup:
    if not any(t["id"] == team_id for t in e["teams"]):
        raise HTTPException(404, "Team not in the event")
    e["teams"] = [t for t in e["teams"] if t["id"] != team_id]
    e["fixtures"] = [f for f in e["fixtures"] if team_id not in (f["home"], f["away"])]
    e["step"] = min(e["step"], 1)
    return setup(store, event_id)


# ---- step 3: fixtures --------------------------------------------------------------------

TIME_RE = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")


def check_fixtures(e: dict, rows: list[dict]) -> list[FixtureProblem]:
    teams = {t["id"] for t in e["teams"]}
    groups = {g["id"] for g in e["groups"]}
    start, end = _iso(e["starts_at"]), _iso(e["ends_at"])
    out: list[FixtureProblem] = []
    seen = set()
    for i, f in enumerate(rows, 1):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.get("date") or ""):
            out.append(FixtureProblem(row=i, field="date", message="Date must be YYYY-MM-DD."))
        elif not (start <= f["date"] <= end):
            out.append(FixtureProblem(row=i, field="date", message=f"Date isn’t within the event ({start} – {end})."))
        if not TIME_RE.match(f.get("time") or ""):
            out.append(FixtureProblem(row=i, field="time", message="Time must be HH:MM."))
        for side in ("home", "away"):
            if f.get(side) not in teams:
                out.append(FixtureProblem(row=i, field=side, message=f"{side.title()} team isn’t in the event."))
        if f.get("home") and f.get("home") == f.get("away"):
            out.append(FixtureProblem(row=i, field="away", message="A team can’t play itself."))
        if f.get("venue") not in e["venues"]:
            out.append(FixtureProblem(row=i, field="venue", message="Pick one of the event’s venues."))
        if f.get("group") and f["group"] not in groups:
            out.append(FixtureProblem(row=i, field="group", message="Unknown group."))
        key = (f.get("date"), f.get("time"), f.get("venue"))
        if key in seen and all(key):
            out.append(FixtureProblem(row=i, field="time", message="Another match is at the same venue at the same time."))
        seen.add(key)
    return out


def _team_by_label(e: dict, label: str) -> str | None:
    label = (label or "").strip().lower()
    for t in e["teams"]:
        if label in (t["name"].lower(), t["short"].lower(), t["id"].lower()):
            return t["id"]
    return None


def _group_by_label(e: dict, label: str) -> str | None:
    label = (label or "").strip().lower()
    if not label:
        return None
    for g in e["groups"]:
        if label in (g["id"].lower(), g["name"].lower(), g["name"].lower().replace("group ", "")):
            return g["id"]
    return label  # unknown: reported by check_fixtures


def parse_csv(e: dict, text: str) -> tuple[list[dict], list[FixtureProblem]]:
    lines = text.lstrip("\ufeff")
    first = lines.splitlines()[0] if lines.strip() else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(lines), delimiter=delim)
    cols = [c.strip().lower() for c in (reader.fieldnames or [])]
    need = ["date", "time", "home", "away"]
    if not all(c in cols for c in need):
        return [], [FixtureProblem(row=0, message="The first row must name the columns: date, time, home, away, venue, group.")]
    rows, problems = [], []
    for i, raw in enumerate(reader, 1):
        r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        d = r.get("date", "")
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", d)  # Finnish 23.10.2026
        if m:
            d = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        t = r.get("time", "").replace(".", ":")
        if re.fullmatch(r"\d:\d\d", t):
            t = "0" + t
        home, away = _team_by_label(e, r.get("home", "")), _team_by_label(e, r.get("away", ""))
        if home is None:
            problems.append(FixtureProblem(row=i, field="home", message=f"“{r.get('home', '')}” isn’t one of the event’s teams."))
        if away is None:
            problems.append(FixtureProblem(row=i, field="away", message=f"“{r.get('away', '')}” isn’t one of the event’s teams."))
        venue = r.get("venue") or (e["venues"][0] if len(e["venues"]) == 1 else "")
        match_venue = next((v for v in e["venues"] if v.lower() == venue.lower()), venue)
        rows.append({"id": f"fx-{secrets.token_hex(3)}", "date": d, "time": t, "home": home or "", "away": away or "",
                     "venue": match_venue, "group": _group_by_label(e, r.get("group", ""))})
    reported = {(p.row, p.field) for p in problems}
    problems += [p for p in check_fixtures(e, rows) if (p.row, p.field) not in reported]
    return rows, sorted(problems, key=lambda p: p.row)


def round_robin(e: dict, first_time: str, minutes: int) -> list[dict]:
    """Everyone plays everyone once inside their group; matches spread over the event days and venues."""
    groups = e["groups"] if any(t["group"] for t in e["teams"]) else [{"id": None, "name": ""}]
    pairs = []
    for g in groups:
        members = [t["id"] for t in e["teams"] if t["group"] == g["id"] or g["id"] is None]
        pairs += [(a, b, g["id"]) for a, b in combinations(members, 2)]
    days = (date.fromisoformat(_iso(e["ends_at"])) - date.fromisoformat(_iso(e["starts_at"]))).days + 1
    per_day = -(-len(pairs) // days) if pairs else 0
    h, m = map(int, first_time.split(":"))
    out = []
    for i, (a, b, gid) in enumerate(pairs):
        day, slot = divmod(i, per_day)
        venue = e["venues"][slot % len(e["venues"])]
        start = datetime.combine(date.fromisoformat(_iso(e["starts_at"])) + timedelta(days=day), datetime.min.time()) \
            + timedelta(hours=h, minutes=m + (slot // len(e["venues"])) * minutes)
        out.append({"id": f"fx-{secrets.token_hex(3)}", "date": start.date().isoformat(), "time": start.strftime("%H:%M"),
                    "home": a, "away": b, "venue": venue, "group": gid})
    return out


def import_fixtures(store: FeedStore, event_id: str, e: dict, body) -> FixtureImportResult:
    if len(e["teams"]) < 2:
        raise HTTPException(409, {"code": "teams", "message": "Add the teams first."})
    if body.kind == "csv":
        if not body.csv or not body.csv.strip():
            raise HTTPException(422, {"code": "csv", "message": "The CSV is empty."})
        rows, problems = parse_csv(e, body.csv)
    else:
        rows = round_robin(e, body.first_time, body.minutes_between)
        problems = check_fixtures(e, rows)
    if body.dry_run or problems:
        if problems and not body.dry_run:
            raise HTTPException(422, {"code": "fixtures", "message": f"{len(problems)} problem(s): nothing was imported.",
                                      "problems": [p.model_dump(by_alias=True) for p in problems]})
        return FixtureImportResult(fixtures=[Fixture(**r) for r in rows], problems=problems)
    e["fixtures"] = rows
    e["matches_total"] = len(rows)
    e["next_step"] = _next_step(e)
    return FixtureImportResult(fixtures=[Fixture(**r) for r in rows], problems=[], setup=setup(store, event_id))


# ---- step 4: rulebook and the rules reading job ------------------------------------------

def _pdf_text(data: bytes) -> str:
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        chunks += [s.decode("latin-1") for s in re.findall(rb"\(((?:\\.|[^\\)])*)\)\s*Tj", raw)]
        for arr in re.findall(rb"\[(.*?)\]\s*TJ", raw, re.S):
            chunks.append("".join(s.decode("latin-1") for s in re.findall(rb"\(((?:\\.|[^\\)])*)\)", arr)))
    return "\n".join(chunks)


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    return re.sub(r"<[^>]+>", " ", xml.replace("</w:p>", "\n"))


def rulebook_text(content_type: str, name: str, data: bytes) -> str:
    ctype = (content_type or "").split(";")[0].lower()
    if ctype == "application/pdf" or name.lower().endswith(".pdf"):
        if not data.startswith(b"%PDF"):
            raise HTTPException(415, {"code": "file", "message": "That file isn’t a PDF."})
        return _pdf_text(data)
    if "wordprocessingml" in ctype or name.lower().endswith(".docx"):
        try:
            return _docx_text(data)
        except (zipfile.BadZipFile, KeyError):
            raise HTTPException(415, {"code": "file", "message": "That file isn’t a Word (.docx) document."}) from None
    if ctype.startswith("text/") or name.lower().endswith(".txt"):
        return data.decode("utf-8", "ignore")
    raise HTTPException(415, {"code": "file", "message": "Upload a PDF or Word (.docx) file, paste a link or paste the text."})


def extract_rules(sport: str, text: str, teams: int, groups: int) -> dict:
    """Mock AI: find what the text says, fill the rest from the sport's usual rules and flag it for checking."""
    d = SPORT_DEFAULTS.get(sport, SPORT_DEFAULTS["football"])
    t = (text or "").lower()
    found, uncertain = {}, []

    def num(patterns):
        for p in patterns:
            m = re.search(p, t)
            if m:
                return int(m.group(1))
        return None

    found["pointsWin"] = num([r"win\w*[^.\n]{0,20}?(\d)\s*point", r"(\d)\s*points? for a win", r"voitosta\s*(\d)"])
    found["pointsDraw"] = num([r"draw\w*[^.\n]{0,20}?(\d)\s*point", r"(\d)\s*points? for a draw", r"tasapelistä\s*(\d)"])
    found["matchMinutes"] = num([r"(\d{2,3})\s*min", r"2\s*x\s*(\d{2})"])
    if found["matchMinutes"] and re.search(r"2\s*x\s*\d{2}", t):
        found["matchMinutes"] *= 2
    found["qualifyCount"] = num([r"top\s*(\d)", r"(\d)\s*best", r"first\s*(\d)"])
    tb = []
    for key, label in [("goal difference", "Goal difference"), ("net run rate", "Net run rate"), ("head-to-head", "Head-to-head"),
                       ("head to head", "Head-to-head"), ("goals scored", "Goals scored"), ("fair play", "Fair play"),
                       ("drawing of lots", "Drawing lots"), ("penalt", "Penalty shoot-out")]:
        if key in t and label not in tb:
            tb.append(label)
    rules = {
        "pointsWin": found["pointsWin"] if found["pointsWin"] is not None else d["points_win"],
        "pointsDraw": found["pointsDraw"] if found["pointsDraw"] is not None else d["points_draw"],
        "pointsLoss": 0,
        "matchMinutes": found["matchMinutes"] or d["match_minutes"],
        "qualifyCount": found["qualifyCount"] or min(2, max(1, teams // max(groups, 1))),
        "tiebreakers": tb or d["tiebreakers"],
        "format": f"{groups} group{'s' if groups != 1 else ''}, everyone plays everyone once in their group."
                  if groups > 1 else "One group, everyone plays everyone once.",
    }
    for k, v in found.items():
        if v is None:
            uncertain.append(k)
    if not tb:
        uncertain.append("tiebreakers")
    rules["uncertain"] = uncertain  # P3 asks the publisher to check these
    rules["sourceChars"] = len(text or "")
    return rules


def start_rules(store: FeedStore, event_id: str, e: dict, kind: str, name: str, size: int | None, text: str) -> EventSetup:
    validate_step(e, 3)
    e["rulebook"] = {"kind": kind, "name": name, "size": size, "received_at": store.now}
    e["rules_text"] = text
    e["rules_job"] = {"status": "reading", "progress": 0, "step": STEPS[0], "started_at": store.now}
    e["rules"] = None
    e["step"] = 4
    e["next_step"] = "Waiting for the rules to be read."
    return setup(store, event_id)


def tick_job(store: FeedStore, e: dict) -> None:
    """The mock AI job advances with time: READ_SECONDS from upload to done."""
    job = e.get("rules_job")
    if not job or job["status"] != "reading":
        return
    import time

    now = time.time_ns() // 1_000_000
    frac = min(1.0, (now - job["started_at"]) / (READ_SECONDS * 1000))
    job["progress"] = int(frac * 100)
    job["step"] = STEPS[min(int(frac * len(STEPS)), len(STEPS) - 1)]
    if frac >= 1 and (e.get("rulebook") or {}).get("kind") == "file" and not (e.get("rules_text") or "").strip():
        job.update(status="failed", progress=100, step="No text could be read from the file (a scanned PDF?)")
        return
    if frac >= 1:
        e["rules"] = extract_rules(e["sport"], e.get("rules_text", ""), len(e["teams"]), len(e["groups"]))
        job.update(status="done", progress=100, step="Rules found")
        e["status"] = "rules_pending"
        e["next_step"] = _next_step(e)


def rules_status(store: FeedStore, e: dict) -> RulesStatus:
    tick_job(store, e)
    job = e.get("rules_job")
    if not job:
        return RulesStatus(status="none", progress=0, step="No rulebook yet")
    return RulesStatus(status=job["status"], progress=job["progress"], step=job["step"],
                       rules=e["rules"] if job["status"] == "done" else None)
