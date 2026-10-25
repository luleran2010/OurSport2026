"""Editor desk (E-series): the review queue for human editors.

Everything that must be checked by a person before (or after) it goes out lands here:
- AI texts the checker flagged (sensitive topic, a claim it couldn't back with data, a junior mentioned),
- news written by clubs ("manual news"),
- error reports from fans and clubs about published results and stories (C7, "correction").
The queue is ordered by priority, then by waiting time. Editors claim items; "Take next" claims the oldest
high-priority item nobody has.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from .mock_data import SPORTS
from .models import EditorQueue, QueueFilterOption, QueueItem, Story

if TYPE_CHECKING:
    from .store import FeedStore, Session

MIN = 60_000
REASONS = {
    "sensitive_topic": "Sensitive topic",
    "blocked_claim": "Blocked claim",
    "junior_mention": "Junior mention",
    "manual_news": "Manual news",
    "correction": "Correction",
}
LANGS = {"fi": "Finnish", "en": "English", "bn": "Bangla"}
PAGE = 25


def seed(store: FeedStore) -> None:
    """More flagged texts besides the publisher's (publisher.seed): match reports, previews, club news."""
    now = store.now
    for r in store.review_items:  # the publisher drafts: what the checker flagged
        r.setdefault("kind", "ai_story")
    extra = {
        "rv-1": ("junior_mention", "high", "Names two U17 players in the text"),
        "rv-2": ("junior_mention", "high", "Mentions a U17 goalkeeper by name"),
        "rv-3": ("blocked_claim", "normal", "Calls Kemi Strikers “unbeaten all season”: not in the data"),
    }
    for r in store.review_items:
        code, prio, why = extra.get(r["id"], ("blocked_claim", "normal", r["reason"]))
        r.update(reason_code=code, priority=prio, reason=why)
    other = "Sanna Virta"
    drafts = [
        ("rv-4", Story(id="draft-r1-report", tag="Match report", author="OurSport AI", author_type="ai", match_id="r1",
                       team_ids=["karpat", "hokki"], language="fi", published_at=now - 70 * MIN,
                       title="Kärpät U20 kaatoi Hokin maalein 4–2", summary="Kärpät U20 ratkaisi ottelun kolmannessa erässä.",
                       body=["Kärpät U20 voitti Hokki U20:n 4–2.", "Ratkaisun teki 17-vuotias hyökkääjä."]),
         "junior_mention", "high", "Names a 17-year-old player", "ice-hockey", None, None, None),
        ("rv-5", Story(id="draft-m7-preview", tag="Preview", author="OurSport AI", author_type="ai", match_id="m7",
                       team_ids=["roki", "kko"], published_at=now - 35 * MIN,
                       title="RoKi host Kiekko-Oulu without their top scorer",
                       summary="RoKi are said to miss their leading scorer with an injury.", body=["RoKi host Kiekko-Oulu at Lappi Areena."]),
         "blocked_claim", "normal", "Mentions an injury that isn’t in the club’s data", "ice-hockey", None, None, None),
        ("rv-6", Story(id="draft-ols-turf", tag="Club news", author="OLS", author_type="editor", club_id="ols", language="fi",
                       published_at=now - 12 * MIN, title="OLS avaa uuden tekonurmen Heinäpäässä",
                       summary="Uusi tekonurmi otetaan käyttöön marraskuussa.", body=["OLS:n uusi tekonurmi valmistuu marraskuussa."]),
         "manual_news", "normal", "Club news waiting for a check before publishing", "football", None, None, None),
        ("rv-7", Story(id="draft-hoops-coach", tag="Club news", author="Oulu Hoops", author_type="editor", club_id="hoops",
                       published_at=now - 4 * 60 * MIN, title="Oulu Hoops name new head coach",
                       summary="A familiar face returns to lead the team.", body=["Oulu Hoops have a new head coach."]),
         "manual_news", "normal", "Club news waiting for a check before publishing", "basketball", None, other, now - 3 * 60 * MIN),
        ("rv-8", Story(id="draft-r2-report", tag="Match report", author="OurSport AI", author_type="ai", match_id="r2",
                       team_ids=["hoops", "raahe"], published_at=now - 150 * MIN,
                       title="Hoops edge Raahe after a tense finish",
                       summary="The game was stopped for ten minutes after an incident in the stands.", body=["Oulu Hoops beat Raahe Rays."]),
         "sensitive_topic", "high", "Mentions an incident in the stands", "basketball", None, None, None),
        ("rv-9", Story(id="draft-finbangla-bn", tag="Preview", author="OurSport AI", author_type="ai", tournament_id="oulu-sixes",
                       language="bn", published_at=now - 8 * MIN, title="ওউলু সিক্সেসের ফাইনালে স্ট্রাইকার্স",
                       summary="কেমি স্ট্রাইকার্স রবিবারের ফাইনালে খেলবে।", body=["ফাইনাল রবিবার দুপুরে।"]),
         "blocked_claim", "normal", "Says the final is “sold out”: not in the data", "cricket", "oulu-sixes", None, None),
    ]
    for rid, story, code, prio, why, sport, event_id, assigned, claimed_at in drafts:
        store.drafts[story.id] = story
        store.review_items.append({
            "id": rid, "story_id": story.id, "event_id": event_id or story.tournament_id, "reason": why, "reason_code": code,
            "priority": prio, "kind": "manual_news" if code == "manual_news" else "ai_story", "sport": sport,
            "created_at": story.published_at, "status": "in_review" if assigned else "pending", "claimed_by": assigned,
            "claimed_at": claimed_at,
        })
    for r in store.review_items:
        if r["id"] == "rv-2":
            r.update(claimed_by=other, claimed_at=now - 10 * MIN)


def require_editor(session: Session) -> None:
    if not session.signed_in:
        raise HTTPException(401, "Log in with your editor account.")
    if not session.is_editor():
        raise HTTPException(403, {"code": "not_editor", "message": "Only editors can open the editor desk."})


# ---- building queue items ----------------------------------------------------------------

def _event_name(store: FeedStore, event_id: str | None) -> str | None:
    if not event_id:
        return None
    t = store.tournaments.get(event_id)
    if t:
        return t.name
    e = store.publisher_events.get(event_id)
    return e.get("name") if e else None


def _from_review(store: FeedStore, r: dict, me: str) -> QueueItem | None:
    from .review_item import _maybe_regenerated

    _maybe_regenerated(store, r)
    st = store.drafts.get(r["story_id"])
    if st is None or r["status"] == "done" or r.get("decision") or r.get("regenerate_at"):
        return None
    text = r.get("text") or {"title": st.title, "summary": st.summary}
    m = store.get_match(st.match_id or "")
    event_id = r.get("event_id") or (m.tournament_id if m else None)
    sport = r.get("sport") or (m.sport if m else None) or (store.tournaments[event_id].sport if event_id in store.tournaments else None)
    source = st.author if st.author_type == "editor" else "OurSport AI"
    return QueueItem(
        id=r["id"], kind=r.get("kind", "ai_story"), reason=r["reason_code"], reason_text=r["reason"], priority=r["priority"],
        headline=text["title"], summary=text["summary"], language=st.language, sport=sport, event_id=event_id,
        event_name=_event_name(store, event_id), match=m, source=source, created_at=r["created_at"],
        status="in_review" if r["claimed_by"] else "pending", assigned_to=r["claimed_by"], assigned_to_me=r["claimed_by"] == me,
        claimed_at=r.get("claimed_at"),
    )


def _from_correction(store: FeedStore, c: dict, me: str) -> QueueItem | None:
    if c["status"] != "open":
        return None
    rec = store.correction_reviews.get(f"corr-{c['id']}") if hasattr(store, "correction_reviews") else None
    if rec:
        from .review_item import _maybe_regenerated

        _maybe_regenerated(store, rec)
        if rec.get("regenerate_at") or rec.get("decision"):
            return None
    m = store.get_match(c["match_id"] or "")
    st = store.get_story(c["story_id"]) if c["story_id"] else None
    claim = store.correction_claims.get(c["id"])
    who = "Fan report" if c["source"] == "fan" else (c["reporter"] or "Club")
    return QueueItem(
        id=f"corr-{c['id']}", kind="correction", reason="correction", reason_text=c["message"],
        priority="high" if c["field"] in ("score", "scorer") else "normal",
        headline=(rec["text"]["title"] if rec and rec["text"] else st.title if st else f"{m.home.name} v {m.away.name}" if m else "Correction"),
        summary=c["correct_value"] and f"Correct value: {c['correct_value']}", language=st.language if st else "en",
        sport=m.sport if m else None, event_id=m.tournament_id if m else None,
        event_name=_event_name(store, m.tournament_id) if m else None, match=m, source=who, created_at=c["created_at"],
        status="in_review" if claim else "pending", assigned_to=claim["by"] if claim else None,
        assigned_to_me=bool(claim and claim["by"] == me), claimed_at=claim["at"] if claim else None,
    )


def all_items(store: FeedStore, me: str) -> list[QueueItem]:
    items = [i for i in (_from_review(store, r, me) for r in store.review_items) if i]
    items += [i for i in (_from_correction(store, c, me) for c in store.error_reports) if i]
    return sorted(items, key=lambda i: (i.priority != "high", i.created_at))


def queue(store: FeedStore, session: Session, *, reason: str | None, sport: str | None, event: str | None,
          language: str | None, age: str | None, assigned: str | None, cursor: str | None, limit: int) -> EditorQueue:
    require_editor(session)
    me = session.name
    every = all_items(store, me)
    waited = lambda i: (store.now - i.created_at) // MIN  # noqa: E731

    def keep(i: QueueItem) -> bool:
        if reason and i.reason != reason:
            return False
        if sport and i.sport != sport:
            return False
        if event and i.event_id != event:
            return False
        if language and i.language != language:
            return False
        if age == "under_30" and waited(i) >= 30 or age == "over_30" and waited(i) < 30 or age == "over_120" and waited(i) < 120:
            return False
        if assigned == "me" and not i.assigned_to_me or assigned == "none" and i.assigned_to:
            return False
        return True

    matching = [i for i in every if keep(i)]
    start = int(cursor) if cursor and cursor.isdigit() else 0
    page = matching[start:start + limit]
    sport_label = {s.id: f"{s.icon} {s.label}" for s in SPORTS}

    def options(key, label) -> list[QueueFilterOption]:
        seen: dict[str, int] = {}
        for i in every:
            k = getattr(i, key)
            if k:
                seen[k] = seen.get(k, 0) + 1
        return [QueueFilterOption(id=k, label=label(k), count=n) for k, n in sorted(seen.items(), key=lambda kv: label(kv[0]))]

    names = {i.event_id: i.event_name for i in every if i.event_id}
    return EditorQueue(
        items=page, total=len(matching), next_cursor=str(start + limit) if start + limit < len(matching) else None,
        counts={"all": len(every), "high": sum(i.priority == "high" for i in every), "unassigned": sum(not i.assigned_to for i in every),
                "mine": sum(i.assigned_to_me for i in every), "over_30": sum(waited(i) >= 30 for i in every),
                "over_120": sum(waited(i) >= 120 for i in every)},
        filters={"reasons": [QueueFilterOption(id=k, label=v, count=sum(i.reason == k for i in every)) for k, v in REASONS.items()],
                 "sports": options("sport", lambda k: sport_label.get(k, k)),
                 "events": options("event_id", lambda k: names.get(k) or k),
                 "languages": options("language", lambda k: LANGS.get(k, k))},
        updated_at=store.now,
    )


# ---- claiming ----------------------------------------------------------------------------

def claim(store: FeedStore, session: Session, item_id: str, force: bool = False) -> QueueItem:
    require_editor(session)
    me = session.name
    if item_id == "next":  # "Take next": the oldest high-priority item nobody has, else the oldest unassigned one
        free = [i for i in all_items(store, me) if not i.assigned_to]
        if not free:
            raise HTTPException(404, {"code": "empty", "message": "Nothing left to take: every item has an editor."})
        item_id = free[0].id
    if item_id.startswith("corr-"):
        cid = item_id[5:]
        c = next((x for x in store.error_reports if x["id"] == cid and x["status"] == "open"), None)
        if c is None:
            raise HTTPException(404, "Not in the queue any more")
        cur = store.correction_claims.get(cid)
        if cur and cur["by"] != me and not force:
            raise HTTPException(409, {"code": "claimed", "message": f"{cur['by']} is already reviewing this.", "by": cur["by"]})
        store.correction_claims[cid] = {"by": me, "at": store.now}
        return _from_correction(store, c, me)
    r = next((x for x in store.review_items if x["id"] == item_id and x["status"] != "done"), None)
    if r is None:
        raise HTTPException(404, "Not in the queue any more")
    if r["claimed_by"] and r["claimed_by"] != me and not force:
        raise HTTPException(409, {"code": "claimed", "message": f"{r['claimed_by']} is already reviewing this.", "by": r["claimed_by"]})
    r.update(claimed_by=me, claimed_at=store.now, status="in_review")
    store._notify()
    return _from_review(store, r, me)
