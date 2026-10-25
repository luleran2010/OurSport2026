"""Publisher portal P5: news and content of one event.

Every story about the event — AI previews / reports and the publisher's own posts — with its status:
draft (saved, not sent), scheduled (goes out at `publish_at`), in_review (in the editor desk queue),
published, blocked (rejected by an editor) or unpublished (taken down by an editor).

Manual posts: published (or scheduled) directly when the event has publish rights (`can_publish`), otherwise they go
to the editor desk as "manual news" (E1) and come out when an editor approves them.
Body: paragraphs split by blank lines, with **bold**, *italic* and "- " list lines.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi import HTTPException

from .event_manage import owned_event
from .models import EventStories, EventStory, Story

if TYPE_CHECKING:
    from .store import FeedStore, Session

MIN = 60_000
ORDER = ["draft", "scheduled", "in_review", "published", "blocked", "unpublished"]


def _org(session: Session) -> str:
    from .mock_data import DEMO_PUBLISHER

    return DEMO_PUBLISHER["organisation"] if (session.email or "").lower() == DEMO_PUBLISHER["email"] else session.name


def _event_of(store: FeedStore, st: Story) -> str | None:
    if st.tournament_id:
        return st.tournament_id
    m = store.get_match(st.match_id or "")
    return m.tournament_id if m else None


def _row(store: FeedStore, st: Story, status: str, at: int, *, note: str | None = None, editable: bool = False,
         publish_at: int | None = None) -> EventStory:
    return EventStory(
        id=st.id, title=st.title, summary=st.summary, body=st.body, tag=st.tag, author=st.author,
        author_type="ai" if st.author_type == "ai" else "manual", language=st.language, status=status, at=at,
        publish_at=publish_at, note=note, corrected_at=st.corrected_at, image_url=st.image_url, team_ids=st.team_ids,
        match_ids=[x for x in [st.match_id, *st.related_match_ids] if x], editable=editable,
    )


def _rows(store: FeedStore, tid: str, owner: str) -> list[EventStory]:
    mine = lambda st: store.post_owner.get(st.id, "").lower() == owner  # noqa: E731
    out = []
    for st in store.stories:
        if _event_of(store, st) == tid:
            future = st.published_at > store.now
            out.append(_row(store, st, "scheduled" if future else "published", st.published_at, editable=mine(st),
                            publish_at=st.published_at if future else None))
    for r in store.review_items:
        st = store.drafts.get(r["story_id"])
        if st is None or r.get("decision") or (r.get("event_id") or _event_of(store, st)) != tid:
            continue
        text = r.get("text") or {}
        st = st.model_copy(update={k: v for k, v in text.items() if v is not None})
        out.append(_row(store, st, "in_review", r["created_at"], note=r["reason"], publish_at=r.get("publish_at"),
                        editable=mine(st) and not r.get("claimed_by") and not r.get("regenerate_at")))
    for p in store.pub_posts.values():
        if p["event_id"] == tid and mine(p["story"]):
            out.append(_row(store, p["story"], "draft", p["saved_at"], publish_at=p["publish_at"], editable=True))
    for b in store.blocked.values():
        if (b.get("event_id") or _event_of(store, b["story"])) == tid:
            out.append(_row(store, b["story"], "blocked", b["at"], note=f"{b['by']}: {b['reason']}"))
    for u in store.unpublished.values():
        if _event_of(store, u["story"]) == tid:
            out.append(_row(store, u["story"], "unpublished", u["at"], note=f"{u['by']}: {u['reason']}"))
    return sorted(out, key=lambda r: -r.at)


def stories(store: FeedStore, session: Session, event_id: str, *, status: str | None, author: str | None,
            language: str | None, q: str | None) -> EventStories:
    e = owned_event(store, event_id, session)
    t = store.tournaments.get(e.get("tournament_id") or "")
    if t is None:
        raise HTTPException(409, {"code": "not_published", "message": "Publish the event first: news needs its teams and matches."})
    every = _rows(store, t.id, (session.email or "").lower())
    needle = (q or "").strip().lower()
    items = [r for r in every if (not status or r.status == status) and (not author or r.author_type == author)
             and (not language or r.language == language) and (not needle or needle in f"{r.title} {r.summary}".lower())]
    return EventStories(
        event_id=event_id, event_name=t.name, items=items, counts={s: sum(r.status == s for r in every) for s in ORDER},
        languages=e.get("languages", ["fi", "en"]), can_publish=e.get("can_publish", False), teams=t.teams,
        matches=sorted((m for m in store.matches if m.tournament_id == t.id), key=lambda m: m.starts_at or 0), updated_at=store.now,
    )


# ---- writing ---------------------------------------------------------------------------------

def _paragraphs(body: str) -> list[str]:
    paras = [re.sub(r"[ \t]+\n", "\n", p).strip() for p in re.split(r"\n\s*\n", body.replace("\r\n", "\n"))]
    return [p for p in paras if p]


def _plain(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*|\*(.+?)\*", lambda m: m.group(1) or m.group(2), re.sub(r"^- ", "", text, flags=re.M))


def _check_links(store: FeedStore, t, team_ids: list[str], match_ids: list[str]) -> None:
    ids = {tm.id for tm in t.teams}
    if any(x not in ids for x in team_ids):
        raise HTTPException(422, {"code": "teams", "message": "Link teams of this event only."})
    games = {m.id for m in store.matches if m.tournament_id == t.id}
    if any(x not in games for x in match_ids):
        raise HTTPException(422, {"code": "matches", "message": "Link matches of this event only."})


def _validate(store: FeedStore, e: dict, t, d: dict) -> None:
    from .club_profile import _check_image_url

    if d["language"] not in e.get("languages", ["fi", "en"]):
        raise HTTPException(422, {"code": "language", "message": "Pick one of the event’s content languages (Settings)."})
    _check_links(store, t, d["team_ids"], d["match_ids"])
    _check_image_url(store, d["image_url"])
    if d["publish_at"] is not None and d["publish_at"] < store.now - MIN:
        raise HTTPException(422, {"code": "publish_at", "message": "The publish time is in the past. Leave it empty to publish now."})
    if not _paragraphs(d["body"]):
        raise HTTPException(422, {"code": "body", "message": "Write the text."})


def _story(d: dict, story_id: str, tid: str, org: str, at: int) -> Story:
    paras = _paragraphs(d["body"])
    summary = (d.get("summary") or "").strip() or _plain(paras[0]).split("\n")[0][:240]
    return Story(id=story_id, tournament_id=tid, match_id=d["match_ids"][0] if d["match_ids"] else None,
                 related_match_ids=d["match_ids"][1:], team_ids=d["team_ids"], title=d["title"].strip(), summary=summary,
                 body=paras, tag="News", author=org, author_type="editor", published_at=at, language=d["language"],
                 available_languages=[d["language"]], image_url=d["image_url"])


def _send(store: FeedStore, session: Session, e: dict, t, st: Story, publish_at: int | None) -> str:
    """Publish / schedule (with publish rights) or hand to the editors. -> the new status."""
    if e.get("can_publish"):
        st = st.model_copy(update={"published_at": max(publish_at or store.now, store.now)})
        store.stories.append(st)
        if st.published_at <= store.now:
            store._log_story(st)
        store._notify()
        return "scheduled" if st.published_at > store.now else "published"
    from .review_item import submit_manual

    submit_manual(store, st, t.id, publish_at, by=st.author)
    return "in_review"


def create(store: FeedStore, session: Session, body) -> EventStory:
    e = owned_event(store, body.event_id, session)
    t = store.tournaments.get(e.get("tournament_id") or "")
    if t is None:
        raise HTTPException(409, {"code": "not_published", "message": "Publish the event first."})
    d = body.model_dump()
    _validate(store, e, t, d)
    sid = f"news-{t.id}-{store._next_id()}"
    st = _story(d, sid, t.id, _org(session), store.now)
    store.post_owner[sid] = (session.email or "").lower()
    if not body.submit:
        store.pub_posts[sid] = {"story": st, "event_id": t.id, "publish_at": body.publish_at, "saved_at": store.now}
        return _row(store, st, "draft", store.now, publish_at=body.publish_at, editable=True)
    status = _send(store, session, e, t, st, body.publish_at)
    return next(r for r in _rows(store, t.id, (session.email or "").lower()) if r.id == sid and r.status == status)


def update(store: FeedStore, session: Session, story_id: str, body, fields: set[str]) -> EventStory:
    owner = (session.email or "").lower()
    if store.post_owner.get(story_id, "").lower() != owner:
        raise HTTPException(403, {"code": "not_your_post", "message": "You can change only your own posts. Ask the editor desk to correct other stories."})
    draft = store.pub_posts.get(story_id)
    live = store.get_story(story_id)
    rec = next((r for r in store.review_items if r["story_id"] == story_id and not r.get("decision")), None)
    cur = draft["story"] if draft else live or (store.drafts.get(story_id) if rec else None)
    if cur is None:
        raise HTTPException(409, {"code": "locked", "message": "This post can’t be changed any more (rejected or unpublished)."})
    tid = _event_of(store, cur)
    eid = next(k for k, v in store.publisher_events.items() if v.get("tournament_id") == tid)
    e = owned_event(store, eid, session)
    t = store.tournaments[tid]
    if rec:
        if rec.get("claimed_by") or rec.get("regenerate_at"):
            raise HTTPException(409, {"code": "in_review", "message": f"{rec.get('claimed_by') or 'An editor'} is reviewing it now."})
        text = rec["text"]
        cur = cur.model_copy(update={"title": text["title"], "summary": text["summary"], "body": text["body"]})
    if live and not draft and not e.get("can_publish"):
        raise HTTPException(409, {"code": "no_rights", "message": "It’s published: ask the editor desk for a correction."})
    d = {"title": cur.title, "summary": None if "summary" not in fields else body.summary, "body": "\n\n".join(cur.body),
         "image_url": cur.image_url, "team_ids": cur.team_ids, "match_ids": [x for x in [cur.match_id, *cur.related_match_ids] if x],
         "language": cur.language, "publish_at": (draft or {}).get("publish_at") or (rec or {}).get("publish_at")
         or (cur.published_at if live and cur.published_at > store.now else None)}
    for f in fields - {"submit"}:
        d[f] = getattr(body, f)
    if "summary" not in fields:
        d["summary"] = cur.summary if not ({"body"} & fields) else None
    _validate(store, e, t, d)
    new = _story(d, story_id, tid, cur.author, cur.published_at)
    if draft:
        if body.submit:
            store.pub_posts.pop(story_id)
            status = _send(store, session, e, t, new, d["publish_at"])
            return next(r for r in _rows(store, tid, owner) if r.id == story_id and r.status == status)
        draft.update(story=new, publish_at=d["publish_at"], saved_at=store.now)
        return _row(store, new, "draft", store.now, publish_at=d["publish_at"], editable=True)
    if rec:
        from .review_item import run_check

        store.drafts[story_id] = new
        rec["text"] = {"title": new.title, "summary": new.summary, "body": new.body}
        rec["version"] += 1
        rec["publish_at"] = d["publish_at"]
        rec["history"].append({"at": store.now, "by": cur.author, "action": "edited", "note": "Changed by the publisher."})
        run_check(store, rec)
        store._notify()
        return next(r for r in _rows(store, tid, owner) if r.id == story_id)
    # published / scheduled with publish rights: change it in place
    at = max(d["publish_at"], store.now) if d["publish_at"] and cur.published_at > store.now else cur.published_at
    store.stories = [new.model_copy(update={"published_at": at, "corrected_at": cur.corrected_at, "correction_note": cur.correction_note})
                     if s.id == story_id else s for s in store.stories]
    store._notify()
    return next(r for r in _rows(store, tid, owner) if r.id == story_id)
