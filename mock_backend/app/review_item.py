"""Editor desk E2: one review item — the text with the checker's marks, the evidence, and the editor's decision.

Every item has a review record (a dict):
- `text`: the working copy {title, summary, body: [paragraphs]} — edits go here, the live story changes only on approve,
- `version`: bumped by every edit; `check`: the checker's last run {version, at, flags},
- `facts`: the fact sheet the writer had (frozen when the text was generated), `rule_version`, `history`.
AI drafts and club news keep their record in `store.review_items`; corrections (fan / club error reports on published
stories) get one in `store.correction_reviews` the first time an editor opens them.

The checker is deterministic: it splits the text into sentences, ties each to the facts whose names or numbers it uses,
and flags (a) numbers not in the fact sheet, (b) junior players named or their age given, (c) claims the data can't back
("unbeaten", "sold out", injuries, top scorers), (d) sensitive topics (incidents, fights, police…).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from . import tournaments as TN
from .mock_data import CLUBS, PLAYERS, is_junior
from .models import Story

if TYPE_CHECKING:
    from .store import FeedStore, Session

MIN = 60_000
DAY = 24 * 60 * MIN
try:  # Windows has no system time zone database (needs the tzdata package): fall back to the computer's local time,
    HEL = ZoneInfo("Europe/Helsinki")  # like the rest of the backend does
except ZoneInfoNotFoundError:
    HEL = None
REGEN_MS = 8_000  # the mock AI writer sends a new version this long after "send back"

NUM = re.compile(r"(?<![\w.])[+-]?\d+(?:[.,:–-]\d+)*")
AGE = re.compile(r"\b\d{1,2}[- ]?(?:year-old|years old|-vuotias|vuotias)", re.I)
CLAIMS = [
    (re.compile(r"unbeaten|tappioton", re.I), "Claim not in the fact sheet: “{m}”"),
    (re.compile(r"sold out|loppuunmyy\w*|বিক্রি হয়ে গেছে", re.I), "Sold out: ticket data isn’t in the fact sheet"),
    (re.compile(r"injur\w*|loukkaant\w*", re.I), "Injury news isn’t in the fact sheet"),
    (re.compile(r"(?:top|leading) scorer|maalikuningas", re.I), "Top-scorer claim isn’t in the fact sheet"),
    (re.compile(r"\b(?:club|league|season|all-time|new|unbeaten) record\b|ennätys\w*", re.I), "Record claim isn’t in the fact sheet"),
]
SENSITIVE = re.compile(r"incident\w*|fight\w*|racis\w*|police|ambulance|abuse\w*|välikohtau\w*|tappelu\w*", re.I)
GENERIC = {"Oulu", "Oulun", "City", "Juniors", "U17", "U20", "FC", "CC", "Kemi", "Women"}
SENT = re.compile(r"(?<=[.!?।])\s+")


# ---- fact sheets ---------------------------------------------------------------------------

def _team_terms(team) -> list[str]:
    words = [w for w in team.name.split() if len(w) >= 4 and w not in GENERIC]
    return [team.name, *words]


def _when(ts: int) -> str:
    d = datetime.fromtimestamp(ts / 1000, HEL) if HEL else datetime.fromtimestamp(ts / 1000).astimezone()
    return f"{d:%a} {d.day} {d:%b}, {d:%H:%M}"  # no %-d: Windows strftime doesn't support it


def _fact(claim: str, value: str, source: str, terms: list[str] | None = None, junior: bool = False) -> dict:
    return {"claim": claim, "value": value, "source": source, "terms": terms or [], "junior": junior}


def _match_facts(store: FeedStore, m) -> list[dict]:
    out = [_fact("Teams", f"{m.home.name} v {m.away.name}", "Fixture list", _team_terms(m.home) + _team_terms(m.away)),
           _fact("Competition", m.league + (f" · {m.stage}" if m.stage else ""), "Fixture list", [m.league])]
    if m.status == "finished" and m.score:
        a, b = m.score
        out.append(_fact("Final score", f"{m.home.name} {a}–{b} {m.away.name}", "Scorer app · final whistle",
                         [f"{a}–{b}", f"{b}–{a}", f"{a}-{b}", f"{b}-{a}"]))
    elif m.status == "live" and m.score:
        out.append(_fact("Live score", f"{m.home.name} {m.score[0]}–{m.score[1]} {m.away.name}", "Scorer app · live"))
    if m.starts_at:
        out.append(_fact("Start", _when(m.starts_at), "Fixture list", [_when(m.starts_at)[-5:]]))
    out.append(_fact("Venue", m.venue, "Fixture list", [m.venue]))
    return out


def _event_facts(store: FeedStore, event_id: str, text: str) -> list[dict]:
    t = store.tournaments.get(event_id)
    if t is None:
        return []
    st = TN.standings(t, store.matches, store.now)
    out = []
    for g in st.groups:
        if len(st.groups) > 1 and not any(term in text for r in g.rows for term in _team_terms(r.team)):
            continue
        for r in g.rows:
            out.append(_fact(f"{g.name} · {r.position}.", f"{r.team.name} — {r.points} pts, P{r.played}, W{r.won} D{r.drawn} "
                             f"L{r.lost}, {st.tiebreak.label} {r.tiebreak_display}", "Standings", _team_terms(r.team)))
        names = {r.team.id for r in g.rows}
        for m in store.matches:
            if m.tournament_id == event_id and m.status == "finished" and m.home.id in names and m.score:
                a, b = m.score
                out.append(_fact(f"Result · {m.stage or t.name}", f"{m.home.name} {a}–{b} {m.away.name}", "Scorer app",
                                 [f"{a}–{b}", f"{b}–{a}"]))
    return out


def _player_facts(text: str) -> list[dict]:
    return [_fact("Player", f"{p.name}, #{p.number} {p.position}, {p.team.name}" + (" (junior team)" if is_junior(p.team) else ""),
                  "Team sheet", [p.name], junior=is_junior(p.team)) for p in PLAYERS if p.name in text]


FACT_KEYS = {"final_score": "Final score", "competition": "Competition", "venue": "Venue", "ended_at": "Full time",
             "kickoff_at": "Start", "goal": "Goal", "table_move": "Table position", "head_to_head": "Head-to-head"}


def story_facts(st: Story | None) -> list[dict]:
    """The fact sheet a published AI story was written from (Story.facts), as checker facts."""
    out = []
    for f in (st.facts if st else []):
        value = f.value or (_when(f.at) if f.at else "")
        if value:
            out.append(_fact(FACT_KEYS.get(f.key, f.key.replace("_", " ").capitalize()), value, "Story fact sheet",
                             [t for t in NUM.findall(value)] + ([value[-5:]] if f.at else [])))
    return out


def story_match(store: FeedStore, st: Story, text: str):
    """The story's match; for club news, the finished game between the two teams it names."""
    m = store.get_match(st.match_id or "")
    if m is None and text:
        m = next((x for x in store.matches if x.status == "finished" and x.home.name in text and x.away.name in text), None)
    return m


def build_facts(store: FeedStore, *, match_id: str | None, event_id: str | None, club_id: str | None, text: str,
                extra: list[dict] = ()) -> list[dict]:
    facts: list[dict] = []
    m = store.get_match(match_id or "")
    if m:
        facts += _match_facts(store, m)
    if event_id:
        facts += _event_facts(store, event_id, text)
    if club_id and club_id in CLUBS:
        c = CLUBS[club_id]
        facts += [_fact("Club", f"{c.name} ({c.short}), {c.city}", "Club profile", [c.name, c.short]),
                  _fact("Home ground", c.venue, "Club profile", [c.venue])]
    facts += _player_facts(text) + list(extra)
    for i, f in enumerate(facts, 1):
        f["id"] = f"F{i}"
    return facts


# ---- the checker ---------------------------------------------------------------------------

def _numbers(s: str) -> set[str]:
    return {n.lstrip("+") for n in NUM.findall(s)}


def check_sentence(text: str, facts: list[dict]) -> tuple[list[str], list[dict]]:
    """-> (fact ids the sentence uses, flags)."""
    known = set()
    for f in facts:
        known |= _numbers(f["value"]) | {t for t in f["terms"] if NUM.fullmatch(t)}
    used = [f["id"] for f in facts if any(t and t in text for t in f["terms"])]
    flags = []
    ages = " ".join(a.group(0) for a in AGE.finditer(text))
    for n in NUM.findall(text):
        if n in ages:
            continue  # reported as an age below
        if n.lstrip("+") not in known and n.replace("-", "–").lstrip("+") not in known:
            fid = next((f["id"] for f in facts if n.lstrip("+") in _numbers(f["value"])), None)
            if fid:
                used.append(fid)
            else:
                flags.append({"code": "number", "reason": f"Number not in the fact sheet: {n}", "quote": n})
        else:
            used += [f["id"] for f in facts if n.lstrip("+") in _numbers(f["value"]) and f["id"] not in used][:1]
    juniors = [f for f in facts if f["junior"] and any(t in text for t in f["terms"])]
    if juniors:
        names = ", ".join(f["value"].split(",")[0] for f in juniors)
        flags.append({"code": "junior", "reason": f"Names a junior player ({names})", "quote": juniors[0]["terms"][0]})
    for a in AGE.finditer(text):
        flags.append({"code": "junior", "reason": "Gives a young player’s age", "quote": a.group(0)})
    for rx, label in CLAIMS:
        for c in rx.finditer(text):
            if not any(c.group(0).lower() in f["value"].lower() for f in facts):
                flags.append({"code": "claim", "reason": label.format(m=c.group(0)), "quote": c.group(0)})
    for s in SENSITIVE.finditer(text):
        flags.append({"code": "sensitive", "reason": f"Sensitive topic: “{s.group(0)}” — needs an editor’s judgement", "quote": s.group(0)})
    return sorted(set(used), key=lambda x: int(x[1:])), flags


def annotate(text: dict, facts: list[dict], with_flags: bool) -> dict:
    def sent(sid: str, s: str) -> dict:
        used, flags = check_sentence(s, facts)
        return {"id": sid, "text": s, "fact_ids": used, "flags": flags if with_flags else []}

    return {
        "title": sent("t", text["title"]),
        "summary": [sent(f"s{i}", s) for i, s in enumerate(SENT.split(text["summary"] or "")) if s],
        "body": [[sent(f"b{p}-{i}", s) for i, s in enumerate(SENT.split(par)) if s] for p, par in enumerate(text["body"])],
    }


def flag_count(text: dict, facts: list[dict]) -> int:
    a = annotate(text, facts, True)
    sents = [a["title"], *a["summary"], *(s for par in a["body"] for s in par)]
    return sum(len(s["flags"]) for s in sents)


def run_check(store: FeedStore, rec: dict, by: str | None = None) -> dict:
    n = flag_count(rec["text"], rec["facts"])
    rec["check"] = {"version": rec["version"], "at": store.now, "flags": n}
    if by:
        rec["history"].append({"at": store.now, "by": "Checker", "action": "checked",
                               "note": "Passed: no red flags." if not n else f"{n} red flag{'s' if n != 1 else ''}."})
    return rec["check"]


# ---- seeding the demo texts -----------------------------------------------------------------

TEXTS = {
    "rv-1": dict(
        title="Semi-final race: three teams chasing two places in Group A",
        summary="OLS U17 lead the group, but AC Oulu U17 and Tarmo U17 can still go through.",
        body=["OLS U17 top Group A with 4 points from 2 games. AC Oulu U17 are second on 3 points and have the best goal "
              "difference in the group, +2.",
              "Veeti Laine and Onni Korhonen have been the standout players so far.",
              "A draw is enough for OLS; Tarmo U17 need to win."]),
    "rv-2": dict(
        title="Group B decided on goal difference",
        summary="Tornio U17 and Raahe U17 are level on 4 points; goal difference puts Tornio first.",
        body=["Tornio U17 drew 1–1 away at Raahe U17.", "Goalkeeper Miro Kangas kept Tornio in the game with a late save.",
              "Haukipudas U17 can still catch both teams in the last round."],
        extra=[_fact("Player", "Miro Kangas, #1 Goalkeeper, Tornio U17 (junior team)", "Team sheet", ["Miro Kangas"], True)]),
    "rv-3": dict(
        title="Strikers and Oulu CC set for Sunday’s final",
        summary="Net run rate separated the top two after the league round.",
        body=["Kemi Strikers lead the league on net run rate, +1.167. The Strikers have been unbeaten all season.",
              "The final starts at 14:00."],
        extra=[_fact("Final", "Sunday 14:00, Kuivasjärvi cricket ground", "Event schedule", ["final"])]),
    "rv-4": dict(
        title="Kärpät U20 kaatoi Hokin maalein 4–2",
        summary="Kärpät U20 ratkaisi ottelun kolmannessa erässä.",
        body=["Oulun Kärpät voitti Kajaanin Hokin kotonaan Raksila Arenalla 4–2.",
              "Ratkaisun teki 17-vuotias hyökkääjä Aaro Hämäläinen."]),
    "rv-5": dict(
        title="RoKi host Kiekko-Oulu without their top scorer",
        summary="RoKi are said to miss their leading scorer with an injury.",
        body=["RoKi Juniors host Kiekko-Oulu at Lappi Areena.", "Kiekko-Oulu won the last meeting 3–2.",
              "Elias Kallio is expected to miss the game with an injury."],
        extra=[_fact("Last meeting", "Kiekko-Oulu 3–2 RoKi Juniors", "Results archive", ["last meeting"])]),
    "rv-6": dict(
        title="OLS avaa uuden tekonurmen Heinäpäässä",
        summary="Uusi tekonurmi otetaan käyttöön marraskuussa.",
        body=["OLS:n uusi tekonurmi Heinäpään kentälle valmistuu marraskuussa.",
              "Kenttä on juniorijoukkueiden käytössä arki-iltaisin."]),
    "rv-7": dict(
        title="Oulu Hoops name new head coach",
        summary="A familiar face returns to lead the team.",
        body=["Oulu Hoops have a new head coach.", "Former captain Mikko Aho takes over from the start of November."]),
    "rv-8": dict(
        title="Hoops edge Raahe after a tense finish",
        summary="The game was stopped for 10 minutes after an incident in the stands.",
        body=["Oulu Hoops won 78–71 away at Raahe Areena.",
              "Play was stopped for 10 minutes in the third quarter after an incident in the stands.",
              "Hoops pulled away in the last minutes."]),
    "rv-9": dict(
        title="ওউলু সিক্সেসের ফাইনালে স্ট্রাইকার্স",
        summary="কেমি স্ট্রাইকার্স রবিবারের ফাইনালে খেলবে।",
        body=["ফাইনাল রবিবার দুপুরে।", "সব টিকিট বিক্রি হয়ে গেছে।"]),
}


def _rule_version(store: FeedStore, event_id: str | None) -> dict | None:
    if not event_id:
        return None
    e = store.publisher_events.get(event_id, {})
    if e.get("rule_versions"):
        v = e["rule_versions"][-1]
        return {"version": v["version"], "confirmed_at": v["confirmed_at"], "confirmed_by": v["confirmed_by"],
                "name": e.get("name") or event_id, "summary": None}
    t = store.tournaments.get(event_id)
    if t is None:
        return None
    st = TN.standings(t, store.matches, store.now)
    return {"version": 2, "confirmed_at": store.now - 9 * DAY, "confirmed_by": "Kaisa Ranta", "name": t.name,
            "summary": f"Win {t.points_win} pts, draw {t.points_draw} pt" + ("" if t.sport == "cricket" else "")
                       + f". Level on points: {st.tiebreak.description.lower()} decides. Top {t.qualify_count} go to {t.qualify_label}."}


def seed(store: FeedStore) -> None:
    """Texts, fact sheets and history for the seeded queue (editor_desk.seed made the items)."""
    store.correction_reviews: dict[str, dict] = {}
    store.fix_reviews: dict[str, dict] = {}  # E3 "Correct" on a live story: item id fix-{storyId}
    store.editor_log: list[dict] = []  # approvals with red flags ("verified manually"), for audits
    for r in store.review_items:
        st = store.drafts[r["story_id"]]
        spec = TEXTS.get(r["id"], {})
        text = {"title": spec.get("title", st.title), "summary": spec.get("summary", st.summary),
                "body": list(spec.get("body", st.body))}
        store.drafts[st.id] = st.model_copy(update={"title": text["title"], "summary": text["summary"], "body": text["body"]})
        joined = " ".join([text["title"], text["summary"] or "", *text["body"]])
        event_id = r.get("event_id") or st.tournament_id
        r.update(text=text, version=1, facts=build_facts(store, match_id=st.match_id, event_id=event_id, club_id=st.club_id,
                                                          text=joined, extra=spec.get("extra", [])),
                 rule_version=_rule_version(store, event_id), decision=None)
        manual = st.author_type == "editor"
        r["history"] = [{"at": r["created_at"], "by": st.author if manual else "OurSport AI",
                         "action": "submitted" if manual else "generated",
                         "note": "Club news sent for checking." if manual else "Written from the fact sheet."}]
        run_check(store, r)
        r["history"].append({"at": r["created_at"], "by": "Checker", "action": "checked",
                             "note": f"{r['check']['flags']} red flag(s)." if r["check"]["flags"] else "Passed: no red flags."})
        if r["claimed_by"]:
            r["history"].append({"at": r.get("claimed_at") or r["created_at"], "by": r["claimed_by"], "action": "claimed", "note": None})
    # the fan report on s4 ("says 4–0 in one place"): the club story really has the slip
    s4 = store.get_story("s4")
    if s4 and not any("4–0" in b for b in s4.body):
        store.stories = [x.model_copy(update={"body": ["OLS U17 beat AC Oulu U17 4–0 at Heinäpää.", *x.body]}) if x.id == "s4" else x
                         for x in store.stories]
    # an earlier round on the RoKi preview: rejected once, regenerated
    rv5 = next((r for r in store.review_items if r["id"] == "rv-5"), None)
    if rv5:
        t0 = rv5["created_at"]
        rv5["history"][:0] = [
            {"at": t0 - 40 * MIN, "by": "OurSport AI", "action": "generated", "note": "Written from the fact sheet."},
            {"at": t0 - 25 * MIN, "by": "Sanna Virta", "action": "sent_back",
             "note": "Don’t speculate about the line-up. Stick to the fixture and the last meeting."},
        ]
        rv5["history"][2]["action"] = "regenerated"
        rv5["history"][2]["note"] = "Version 2 after the editor’s note."
        rv5["version"] = 2
        rv5["check"]["version"] = 2


def submit_manual(store: FeedStore, st: Story, event_id: str, publish_at: int | None, by: str) -> dict:
    """P5: a publisher's post without publish rights goes to the editor desk as manual news."""
    store.drafts[st.id] = st
    m = store.get_match(st.match_id or "")
    text = {"title": st.title, "summary": st.summary, "body": list(st.body)}
    joined = " ".join([text["title"], text["summary"] or "", *text["body"]])
    rec = {
        "id": f"rv-{store._next_id()}", "story_id": st.id, "event_id": event_id, "reason": "Publisher news waiting for a check before publishing",
        "reason_code": "manual_news", "priority": "normal", "kind": "manual_news", "sport": m.sport if m else store.tournaments[event_id].sport,
        "created_at": store.now, "status": "pending", "claimed_by": None, "claimed_at": None, "text": text, "version": 1,
        "facts": build_facts(store, match_id=m.id if m else None, event_id=event_id, club_id=None, text=joined),
        "rule_version": _rule_version(store, event_id), "decision": None, "publish_at": publish_at,
        "history": [{"at": store.now, "by": by, "action": "submitted", "note": "Publisher news sent for checking."}],
    }
    run_check(store, rec)
    rec["history"].append({"at": store.now, "by": "Checker", "action": "checked",
                           "note": f"{rec['check']['flags']} red flag(s)." if rec["check"]["flags"] else "Passed: no red flags."})
    store.review_items.append(rec)
    store._notify()
    return rec


# ---- records ------------------------------------------------------------------------------

def _correction_record(store: FeedStore, cid: str) -> dict | None:
    item_id = f"corr-{cid}"
    if item_id in store.correction_reviews:
        return store.correction_reviews[item_id]
    c = next((x for x in store.error_reports if x["id"] == cid), None)
    if c is None:
        return None
    st = store.get_story(c["story_id"]) if c["story_id"] else None
    m = store.get_match(c["match_id"] or "") or (store.get_match(st.match_id or "") if st else None)
    text = {"title": st.title, "summary": st.summary, "body": list(st.body)} if st else None
    joined = " ".join([text["title"], text["summary"] or "", *text["body"]]) if text else ""
    if m is None and joined:  # a club story about a match: the finished game between the two teams it names
        m = next((x for x in store.matches if x.status == "finished" and x.home.name in joined and x.away.name in joined), None)
    rec = {
        "id": item_id, "kind": "correction", "story_id": st.id if st else None, "correction_id": cid, "text": text,
        "version": 1, "facts": build_facts(store, match_id=m.id if m else None, event_id=m.tournament_id if m else None,
                                           club_id=st.club_id if st else None, text=joined, extra=story_facts(st)),
        "rule_version": _rule_version(store, m.tournament_id if m else None), "decision": None, "status": "pending",
        "history": ([{"at": st.published_at, "by": st.author, "action": "published", "note": None}] if st else []) + [
            {"at": c["created_at"], "by": "Fan report" if c["source"] == "fan" else (c["reporter"] or "Club"), "action": "reported",
             "note": c["message"]}],
    }
    if text:
        run_check(store, rec)
    store.correction_reviews[item_id] = rec
    return rec


def _fix_record(store: FeedStore, story_id: str) -> dict | None:
    """E3 "Correct": an editor's correction of a live story (no report). A decided one makes way for a fresh one."""
    item_id = f"fix-{story_id}"
    rec = store.fix_reviews.get(item_id)
    if rec and not rec.get("decision"):
        return rec
    st = store.get_story(story_id)
    if st is None:
        return None
    text = {"title": st.title, "summary": st.summary, "body": list(st.body)}
    joined = " ".join([text["title"], text["summary"] or "", *text["body"]])
    m = story_match(store, st, joined)
    event_id = st.tournament_id or (m.tournament_id if m else None)
    rec = {
        "id": item_id, "kind": "fix", "story_id": st.id, "text": text, "version": 1, "claimed_by": None, "status": "pending",
        "facts": build_facts(store, match_id=m.id if m else None, event_id=event_id, club_id=st.club_id, text=joined,
                             extra=story_facts(st)),
        "rule_version": _rule_version(store, event_id), "decision": None,
        "history": [{"at": st.published_at, "by": st.author, "action": "published", "note": None}]
                   + ([{"at": st.corrected_at, "by": "Editor desk", "action": "corrected", "note": st.correction_note}]
                      if st.corrected_at else []),
    }
    run_check(store, rec)
    store.fix_reviews[item_id] = rec
    return rec


def record(store: FeedStore, item_id: str) -> dict:
    if item_id.startswith("fix-"):
        rec = _fix_record(store, item_id[4:])
    elif item_id.startswith("corr-"):
        rec = _correction_record(store, item_id[5:])
    else:
        rec = next((r for r in store.review_items if r["id"] == item_id), None)
    if rec is None:
        raise HTTPException(404, "Not in the queue")
    _maybe_regenerated(store, rec)
    return rec


def by_story(store: FeedStore, story_or_item_id: str, item_id: str | None) -> dict:
    """The /stories/{id}/… endpoints: the open review of that story (or `itemId` from the body, or a queue item id)."""
    if item_id:
        rec = record(store, item_id)
        if rec.get("story_id") not in (story_or_item_id, None) and rec["id"] != story_or_item_id:
            raise HTTPException(400, "That item is about another story")
        return rec
    if story_or_item_id.startswith(("rv-", "corr-")):
        return record(store, story_or_item_id)
    for r in store.review_items:
        if r["story_id"] == story_or_item_id and r.get("decision") is None:
            return record(store, r["id"])
    for c in store.error_reports:
        if c["story_id"] == story_or_item_id and c["status"] == "open":
            return record(store, f"corr-{c['id']}")
    raise HTTPException(404, "This story has nothing waiting for review")


def _claimed_by(store: FeedStore, rec: dict) -> str | None:
    if rec["kind"] == "correction":
        c = store.correction_claims.get(rec["correction_id"])
        return c["by"] if c else None
    return rec["claimed_by"]


def _claim(store: FeedStore, rec: dict, me: str) -> None:
    who = _claimed_by(store, rec)
    if who and who != me:
        raise HTTPException(409, {"code": "claimed", "message": f"{who} is reviewing this. Take it over first.", "by": who})
    if who != me:
        if rec["kind"] == "correction":
            store.correction_claims[rec["correction_id"]] = {"by": me, "at": store.now}
        else:
            rec.update(claimed_by=me, claimed_at=store.now, status="in_review")
        rec["history"].append({"at": store.now, "by": me, "action": "claimed", "note": None})


def _open(rec: dict) -> None:
    if rec.get("decision"):
        raise HTTPException(409, {"code": "decided", "message": "This item has already been decided."})
    if rec.get("regenerate_at"):
        raise HTTPException(409, {"code": "regenerating", "message": "The AI writer is working on a new version."})


def _maybe_regenerated(store: FeedStore, rec: dict) -> None:
    """Mock AI writer: a few seconds after "send back", a new version without the flagged sentences arrives."""
    at = rec.get("regenerate_at")
    if not at or store.now < at:
        return
    a = annotate(rec["text"], rec["facts"], True)
    body = []
    for par in a["body"]:
        kept = " ".join(s["text"] for s in par if not s["flags"])
        if kept:
            body.append(kept)
    summary = " ".join(s["text"] for s in a["summary"] if not s["flags"]) or rec["text"]["summary"]
    if a["summary"] and all(s["flags"] for s in a["summary"]) and a["body"]:
        summary = body[0] if body else summary
    title = a["title"]["text"]
    if a["title"]["flags"]:
        title = re.sub(r"\s+without their top scorer|\s+after an incident.*$", "", title).strip() or title
    rec["text"] = {"title": title, "summary": summary, "body": body or rec["text"]["body"]}
    rec["version"] += 1
    rec["regenerate_at"] = None
    if rec["kind"] != "correction":
        rec.update(claimed_by=None, claimed_at=None, status="pending")
    else:
        store.correction_claims.pop(rec["correction_id"], None)
    run_check(store, rec)
    rec["history"].append({"at": at, "by": "OurSport AI", "action": "regenerated",
                           "note": f"Version {rec['version']}. {rec['check']['flags'] or 'No'} red flag(s) left."})


# ---- reading -----------------------------------------------------------------------------

def detail(store: FeedStore, session: Session, item_id: str) -> dict:
    from . import editor_desk as ED

    ED.require_editor(session)
    rec = record(store, item_id)
    me = session.name
    order = [i.id for i in ED.all_items(store, me)]
    item = next((i for i in ED.all_items(store, me) if i.id == item_id), None)
    pos = order.index(item_id) if item_id in order else None
    text = rec["text"]
    stale = bool(text) and rec["check"]["version"] != rec["version"]
    corr = None
    if rec["kind"] == "correction":
        c = next(x for x in store.error_reports if x["id"] == rec["correction_id"])
        from .corrections import FIELDS
        corr = {"id": c["id"], "source": c["source"], "field": FIELDS.get(c["field"], c["field"]), "message": c["message"],
                "correct_value": c["correct_value"], "reporter": c["reporter"], "created_at": c["created_at"], "status": c["status"]}
    st = store.drafts.get(rec.get("story_id") or "") or store.get_story(rec.get("story_id") or "")
    m = store.get_match((st.match_id if st else None) or "") or (item.match if item else None)
    if m is None and corr and rec["correction_id"]:
        c = next(x for x in store.error_reports if x["id"] == rec["correction_id"])
        m = store.get_match(c["match_id"] or "")
    status = ("decided" if rec.get("decision") else "regenerating" if rec.get("regenerate_at")
              else "in_review" if _claimed_by(store, rec) else "pending")
    return {
        "id": rec["id"], "kind": rec["kind"], "story_id": rec.get("story_id"), "item": item, "status": status,
        "decision": rec.get("decision"), "version": rec["version"], "text": text,
        "annotated": annotate(text, rec["facts"], not stale) if text else None,
        "check": {**rec["check"], "status": "stale" if stale else "flagged" if rec["check"]["flags"] else "passed"} if text else None,
        "facts": [{k: f[k] for k in ("id", "claim", "value", "source", "junior")} for f in rec["facts"]],
        "match": m, "event_name": item.event_name if item else None, "rule_version": rec.get("rule_version"),
        "history": sorted(rec["history"], key=lambda h: h["at"]), "correction": corr,
        "tag": st.tag if st else None, "author": st.author if st else None, "language": st.language if st else "en",
        "assigned_to": _claimed_by(store, rec), "assigned_to_me": _claimed_by(store, rec) == me,
        "regenerate_at": rec.get("regenerate_at"),
        "nav": {"position": pos + 1 if pos is not None else None, "total": len(order),
                "prev_id": order[pos - 1] if pos else None if pos is not None else (order[-1] if order else None),
                "next_id": (order[pos + 1] if pos + 1 < len(order) else None) if pos is not None else (order[0] if order else None)},
        "updated_at": store.now,
    }


# ---- editing, checking, deciding -------------------------------------------------------------

def patch(store: FeedStore, session: Session, story_id: str, body) -> dict:
    from . import editor_desk as ED

    ED.require_editor(session)
    rec = by_story(store, story_id, body.item_id)
    _open(rec)
    if not rec["text"]:
        raise HTTPException(409, {"code": "no_text", "message": "This item has no text to edit."})
    _claim(store, rec, session.name)
    if body.version is not None and body.version != rec["version"]:
        raise HTTPException(409, {"code": "stale_version", "message": "Someone changed this text meanwhile. Reload it first."})
    new = {"title": body.title.strip(), "summary": (body.summary or "").strip() or None,
           "body": [p.strip() for p in body.body if p.strip()]}
    if not new["title"] or not new["body"]:
        raise HTTPException(422, "The headline and the text can’t be empty.")
    if new == rec["text"]:
        return detail(store, session, rec["id"])
    changed = [k for k in ("title", "summary", "body") if new[k] != rec["text"][k]]
    rec["text"] = new
    rec["version"] += 1
    rec["history"].append({"at": store.now, "by": session.name, "action": "edited",
                           "note": "Changed " + ", ".join({"title": "headline", "summary": "summary", "body": "text"}[k] for k in changed) + "."})
    store._notify()
    return detail(store, session, rec["id"])


def check(store: FeedStore, session: Session, story_id: str, item_id: str | None) -> dict:
    from . import editor_desk as ED

    ED.require_editor(session)
    rec = by_story(store, story_id, item_id)
    if not rec["text"]:
        raise HTTPException(409, {"code": "no_text", "message": "This item has no text to check."})
    run_check(store, rec, by=session.name)
    return detail(store, session, rec["id"])


def _finish(store: FeedStore, session: Session, rec: dict, action: str, note: str | None, **extra) -> dict:
    rec["decision"] = {"action": action, "by": session.name, "at": store.now, "note": note, **extra}
    rec["status"] = "done"
    rec["history"].append({"at": store.now, "by": session.name, "action": action, "note": note})
    store._notify()
    nxt = detail(store, session, rec["id"])["nav"]
    return {"id": rec["id"], "decision": rec["decision"], "next_id": nxt["next_id"]}


def approve(store: FeedStore, session: Session, story_id: str, body) -> dict:
    from . import corrections
    from . import editor_desk as ED

    ED.require_editor(session)
    rec = by_story(store, story_id, body.item_id)
    _open(rec)
    _claim(store, rec, session.name)
    flags = 0
    if rec["text"]:
        if rec["check"]["version"] != rec["version"]:
            raise HTTPException(409, {"code": "check_stale", "message": "The text changed since the last check. Run the checker first."})
        flags = rec["check"]["flags"]
    note = (body.note or "").strip()
    if flags and not (body.verified and len(note) >= 10):
        raise HTTPException(409, {"code": "red_flags", "message": f"{flags} red flag{'s' if flags != 1 else ''} left. Fix the text, or tick "
                                  "“I verified this manually” and say what you checked (at least 10 characters).", "flags": flags})
    if flags:
        store.editor_log.append({"at": store.now, "by": session.name, "item_id": rec["id"], "story_id": rec.get("story_id"),
                                 "flags": flags, "note": note, "version": rec["version"]})
    t = rec["text"]
    public = (body.public_note or "").strip()
    if rec["kind"] == "fix" and len(public) < 5:
        raise HTTPException(422, {"code": "public_note", "message": "Say what was corrected (shown to readers, at least 5 characters)."})
    if rec["kind"] in ("correction", "fix"):
        if t and rec["story_id"]:
            if store.get_story(rec["story_id"]) is None:
                raise HTTPException(409, {"code": "unpublished", "message": "The story is unpublished, so it can’t be corrected."})
            changed = {"title": t["title"], "summary": t["summary"], "body": t["body"], "corrected_at": store.now,
                       "correction_note": public or "Corrected after a reader’s report.", "translations": {}}
            store.stories = [s.model_copy(update={**changed, "available_languages": [s.language]}) if s.id == rec["story_id"] else s
                             for s in store.stories]
        if rec["kind"] == "correction":
            corrections.resolve(store, rec["correction_id"], "fixed", note or public or "Checked by the editor desk and corrected.")
    else:
        draft = store.drafts.pop(rec["story_id"], None)
        if draft:
            story = Story(**{**draft.model_dump(), "title": t["title"], "summary": t["summary"], "body": t["body"],
                             "published_at": max(store.now, rec.get("publish_at") or 0)})  # P5 posts may be scheduled
            store.stories.append(story)
            store._log_story(story)
    label = (f"Correction published: {public}" if rec["kind"] == "fix" else f"Approved and published (version {rec['version']})")
    return _finish(store, session, rec, "approved", f"{label}. Verified manually with {flags} red flag(s): {note}" if flags else note or label,
                   flags_overridden=flags)


def reject(store: FeedStore, session: Session, story_id: str, body) -> dict:
    from . import corrections
    from . import editor_desk as ED

    ED.require_editor(session)
    rec = by_story(store, story_id, body.item_id)
    _open(rec)
    _claim(store, rec, session.name)
    reason = body.reason.strip()
    if len(reason) < 5:
        raise HTTPException(422, "Say why you reject it (at least 5 characters).")
    if rec["kind"] == "correction":
        corrections.resolve(store, rec["correction_id"], "rejected", reason)
    else:
        draft = store.drafts.pop(rec["story_id"], None)
        if draft and rec["kind"] != "fix":  # kept for the publisher's content list (P5: "blocked")
            t = rec["text"] or {}
            store.blocked[draft.id] = {"story": draft.model_copy(update={k: v for k, v in t.items() if v is not None}),
                                       "reason": reason, "by": session.name, "at": store.now, "event_id": rec.get("event_id")}
    return _finish(store, session, rec, "rejected", reason)


def regenerate(store: FeedStore, session: Session, story_id: str, body) -> dict:
    from . import editor_desk as ED

    ED.require_editor(session)
    rec = by_story(store, story_id, body.item_id)
    _open(rec)
    if not rec["text"]:
        raise HTTPException(409, {"code": "no_text", "message": "There is no text to regenerate."})
    _claim(store, rec, session.name)
    note = body.note.strip()
    if len(note) < 5:
        raise HTTPException(422, "Tell the writer what to change (at least 5 characters).")
    rec["regenerate_at"] = store.now + REGEN_MS
    rec["history"].append({"at": store.now, "by": session.name, "action": "sent_back", "note": note})
    store._notify()
    order = [i.id for i in ED.all_items(store, session.name)]
    return {"id": rec["id"], "decision": None, "next_id": order[0] if order else None, "ready_at": rec["regenerate_at"]}
