"""Editor desk E3: published content and corrections.

- Every published story, searchable (title / summary), with filters: date, event, AI or manual, corrected.
- Error reports from fans and clubs (C7) — open first — with "Resolve" (fixed / rejected + note).
- Unpublish (with a reason, kept for the record) and Correct: opens the E2 editor on the live story
  (item `fix-{storyId}`, or the open report's item); publishing it adds a visible "Corrected on {date}" note.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from .corrections import FIELDS
from .mock_data import CLUBS
from .models import EditorCorrection, EditorCorrections, PublishedPage, PublishedStory, QueueFilterOption, Story

if TYPE_CHECKING:
    from .store import FeedStore, Session

DAY = 24 * 3_600_000
PERIODS = {"24h": DAY, "7d": 7 * DAY, "30d": 30 * DAY}


def _require(session: Session) -> None:
    from .editor_desk import require_editor

    require_editor(session)


def _open_reports(store: FeedStore, story_id: str) -> list[dict]:
    return [c for c in store.error_reports if c["story_id"] == story_id and c["status"] == "open"]


def _row(store: FeedStore, st: Story, unpub: dict | None = None) -> PublishedStory:
    t = store.tournaments.get(st.tournament_id or "")
    m = store.get_match(st.match_id or "")
    if t is None and m and m.tournament_id:
        t = store.tournaments.get(m.tournament_id)
    reports = _open_reports(store, st.id)
    return PublishedStory(
        id=st.id, title=st.title, summary=st.summary, tag=st.tag, author=st.author, author_type=st.author_type,
        language=st.language, published_at=st.published_at, status="unpublished" if unpub else "published",
        event_id=t.id if t else None, event_name=t.name if t else None, match=m,
        club_name=CLUBS[st.club_id].name if st.club_id in CLUBS else None, corrected_at=st.corrected_at,
        correction_note=st.correction_note, open_corrections=len(reports),
        correct_item_id=f"corr-{reports[0]['id']}" if reports else f"fix-{st.id}",
        unpublished_at=unpub["at"] if unpub else None, unpublished_by=unpub["by"] if unpub else None,
        unpublish_reason=unpub["reason"] if unpub else None,
    )


def stories(store: FeedStore, session: Session, *, status: str, q: str | None, date: str | None, event: str | None,
            author: str | None, corrected: str | None, cursor: str | None, limit: int) -> PublishedPage:
    _require(session)
    live = [s for s in store.stories if s.published_at <= store.now]
    rows = [_row(store, s) for s in live] + [_row(store, u["story"], u) for u in store.unpublished.values()]
    rows.sort(key=lambda r: (-r.published_at, r.id))
    counts = {"published": sum(r.status == "published" for r in rows),
              "corrected": sum(bool(r.corrected_at) for r in rows if r.status == "published"),
              "reported": sum(r.open_corrections > 0 for r in rows if r.status == "published"),
              "unpublished": sum(r.status == "unpublished" for r in rows)}
    events: dict[str, list] = {}
    for r in rows:
        if r.event_id:
            events.setdefault(r.event_id, [r.event_name, 0])[1] += 1

    needle = (q or "").strip().lower()

    def keep(r: PublishedStory) -> bool:
        if status != "all" and r.status != status:
            return False
        if needle and needle not in f"{r.title} {r.summary} {r.tag} {r.author}".lower():
            return False
        if date in PERIODS and r.published_at < store.now - PERIODS[date]:
            return False
        if event and r.event_id != event:
            return False
        if author == "ai" and r.author_type != "ai" or author == "manual" and r.author_type != "editor":
            return False
        if corrected == "yes" and not r.corrected_at or corrected == "no" and r.corrected_at:
            return False
        if corrected == "reported" and not r.open_corrections:
            return False
        return True

    matching = [r for r in rows if keep(r)]
    start = int(cursor) if cursor and cursor.isdigit() else 0
    return PublishedPage(
        items=matching[start:start + limit], total=len(matching),
        next_cursor=str(start + limit) if start + limit < len(matching) else None, counts=counts,
        events=[QueueFilterOption(id=k, label=v[0], count=v[1]) for k, v in sorted(events.items(), key=lambda kv: kv[1][0])],
        updated_at=store.now,
    )


def correction_list(store: FeedStore, session: Session, status: str) -> EditorCorrections:
    _require(session)
    out = []
    for c in store.error_reports:
        if status != "all" and c["status"] != status:
            continue
        st = store.get_story(c["story_id"] or "")
        unpub = store.unpublished.get(c["story_id"] or "")
        if st is None and unpub:
            st = unpub["story"]
        m = store.get_match(c["match_id"] or "") or (store.get_match(st.match_id or "") if st else None)
        claim = store.correction_claims.get(c["id"])
        out.append(EditorCorrection(
            id=c["id"], item_id=f"corr-{c['id']}", source=c["source"], status=c["status"], field_label=FIELDS.get(c["field"], c["field"]),
            message=c["message"], correct_value=c["correct_value"], reporter=c["reporter"], created_at=c["created_at"],
            resolved_at=c["resolved_at"], resolution=c["resolution"], story_id=st.id if st else None,
            story_title=st.title if st else None, story_status=("unpublished" if unpub else "published") if st else None,
            match=m, assigned_to=claim["by"] if claim else None,
        ))
    out.sort(key=lambda i: (i.status != "open", i.created_at if i.status == "open" else -(i.resolved_at or i.created_at)))
    counts = {s: sum(c["status"] == s for c in store.error_reports) for s in ("open", "fixed", "rejected")}
    return EditorCorrections(items=out, counts=counts, updated_at=store.now)


def resolve(store: FeedStore, session: Session, correction_id: str, status: str, note: str | None):
    """PATCH /corrections/{id}: fixed / rejected with a note, without opening the editor."""
    from . import corrections

    _require(session)
    c = next((x for x in store.error_reports if x["id"] == correction_id), None)
    if c is None:
        raise HTTPException(404, "Correction not found")
    if c["status"] != "open":
        raise HTTPException(409, {"code": "resolved", "message": f"Already {c['status']}."})
    if status == "rejected" and len((note or "").strip()) < 5:
        raise HTTPException(422, "Say why the report is rejected (at least 5 characters) — the club sees this note.")
    item = corrections.resolve(store, correction_id, status, (note or "").strip() or None)
    rec = store.correction_reviews.get(f"corr-{correction_id}")
    if rec and not rec.get("decision"):
        rec["decision"] = {"action": "approved" if status == "fixed" else "rejected", "by": session.name, "at": store.now,
                           "note": note}
        rec["status"] = "done"
        rec["history"].append({"at": store.now, "by": session.name, "action": "approved" if status == "fixed" else "rejected",
                               "note": f"Resolved as {status} from the corrections list" + (f": {note}" if note else ".")})
    store.correction_claims.pop(correction_id, None)
    store._notify()
    return item


def unpublish(store: FeedStore, session: Session, story_id: str, reason: str) -> PublishedStory:
    _require(session)
    st = store.get_story(story_id)
    if st is None:
        if story_id in store.unpublished:
            raise HTTPException(409, {"code": "unpublished", "message": "Already unpublished."})
        raise HTTPException(404, "Story not found")
    reason = reason.strip()
    if len(reason) < 5:
        raise HTTPException(422, "Say why it is unpublished (at least 5 characters).")
    store.stories = [s for s in store.stories if s.id != story_id]
    store.unpublished[story_id] = {"story": st, "at": store.now, "by": session.name, "reason": reason}
    store._notify()
    return _row(store, st, store.unpublished[story_id])
