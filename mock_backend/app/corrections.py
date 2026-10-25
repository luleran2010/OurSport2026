"""Club portal C7: corrections.

One list for error reports about a club's matches and stories:
- fans report from a story page (F7: "Report an error"), source "fan", no name kept;
- clubs report from the portal: match, what is wrong, the correct value, source "club".
Editors resolve them (E3: fixed / rejected, with a note); clubs only report and follow the status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from .mock_data import CLUBS, TEAMS
from .models import Correction as MatchCorrection
from .models import CorrectionItem, CorrectionList, Match, Story

if TYPE_CHECKING:
    from .store import FeedStore, Session

FIELDS = {"score": "Score", "scorer": "Goal or point scorer", "event": "Match event", "time": "Date or time",
          "teams": "Teams or line-up", "story": "Story text", "other": "Something else"}
DAY = 86_400_000


def _clubs_for(store: FeedStore, match: Match | None, story: Story | None) -> list[str]:
    ids: list[str] = []
    if match:
        ids += [match.home.club_id, match.away.club_id]
    if story:
        ids += ([story.club_id] if story.club_id else []) + [TEAMS[t].club_id for t in story.team_ids if t in TEAMS]
        m = store.get_match(story.match_id or "")
        if m:
            ids += [m.home.club_id, m.away.club_id]
    return list(dict.fromkeys(i for i in ids if i in CLUBS))


def add(store: FeedStore, *, source: str, message: str, story_id: str | None = None, match_id: str | None = None,
        field: str = "other", correct_value: str | None = None, reporter: str | None = None,
        status: str = "open", at: int | None = None, resolution: str | None = None, resolved_at: int | None = None) -> dict:
    story = store.get_story(story_id) if story_id else None
    match = store.get_match(match_id or (story.match_id if story else "") or "")
    item = {
        "id": f"cr-{store._next_id()}", "source": source, "story_id": story_id, "match_id": match.id if match else None,
        "club_ids": _clubs_for(store, match, story), "field": field, "message": message, "correct_value": correct_value,
        "reporter": reporter, "status": status, "created_at": at or store.now, "resolution": resolution,
        "resolved_at": resolved_at,
    }
    store.error_reports.append(item)
    return item


def seed(store: FeedStore) -> None:
    """Demo history: one fixed and one rejected club report next to the open fan reports."""
    now = store.now
    for k, r in enumerate(x for x in store.error_reports if x["source"] == "fan"):  # fan reports came in earlier today
        r["created_at"] = now - (k + 1) * 3 * 3_600_000
    r4 = store.get_match("r4")
    if r4:
        add(store, source="club", match_id="r4", field="score", reporter="Sanna Heikkilä, Oulun Tarmo",
            message="Our 88th-minute winner is missing: the game ended 1–0, not 0–0.", correct_value="Kemi City 0–1 Oulun Tarmo",
            status="fixed", at=(r4.ended_at or now) + 20 * 60_000, resolved_at=(r4.ended_at or now) + 40 * 60_000,
            resolution="Checked against the referee’s report. Score corrected and the match report updated.")
    if store.get_match("r5"):
        add(store, source="club", match_id="r5", field="scorer", reporter="Jari Niemi, Oulun Tarmo",
            message="The first goal was scored by #7, not #9.", correct_value="#7",
            status="rejected", at=now - 12 * DAY, resolved_at=now - 11 * DAY,
            resolution="The match video shows #9 scoring. No change.")


def open_count(store: FeedStore, club_id: str) -> int:
    return sum(1 for r in store.error_reports if r["status"] == "open" and club_id in r["club_ids"])


def _item(store: FeedStore, r: dict) -> CorrectionItem:
    story = store.get_story(r["story_id"]) if r["story_id"] else None
    return CorrectionItem(
        id=r["id"], source=r["source"], status=r["status"], field=r["field"], field_label=FIELDS.get(r["field"], r["field"]),
        message=r["message"], correct_value=r["correct_value"], reporter=r["reporter"] if r["source"] == "club" else None,
        created_at=r["created_at"], resolved_at=r["resolved_at"], resolution=r["resolution"],
        match=store.get_match(r["match_id"] or ""), story_id=r["story_id"], story_title=story.title if story else None,
    )


def list_for(store: FeedStore, club_id: str) -> CorrectionList:
    rows = sorted((r for r in store.error_reports if club_id in r["club_ids"]), key=lambda r: -r["created_at"])
    items = [_item(store, r) for r in rows]
    counts = {s: sum(1 for i in items if i.status == s) for s in ("open", "fixed", "rejected")}
    return CorrectionList(club=CLUBS[club_id], items=items, counts=counts, fields=FIELDS, updated_at=store.now)


def report(store: FeedStore, body, session: Session) -> CorrectionItem:
    club_id = body.club_id
    if club_id not in CLUBS:
        raise HTTPException(404, "Club not found")
    if not session.is_admin(club_id):
        raise HTTPException(403, {"code": "not_club_admin", "message": "You’re not an admin of this club."})
    m = store.get_match(body.match_id)
    if m is None or club_id not in (m.home.club_id, m.away.club_id):
        raise HTTPException(422, {"code": "match", "message": "Pick one of the club’s matches."})
    if body.field not in FIELDS:
        raise HTTPException(422, {"code": "field", "message": "Pick what is wrong."})
    dup = next((r for r in store.error_reports if r["status"] == "open" and r["match_id"] == m.id and r["field"] == body.field
                and (r["correct_value"] or "").strip().lower() == (body.correct_value or "").strip().lower()), None)
    if dup:
        raise HTTPException(409, {"code": "duplicate", "message": "The same correction is already waiting for an editor."})
    item = add(store, source="club", match_id=m.id, field=body.field, message=body.message.strip(),
               correct_value=(body.correct_value or "").strip() or None, reporter=f"{session.name}, {CLUBS[club_id].name}")
    return _item(store, item)


def resolve(store: FeedStore, correction_id: str, status: str, note: str | None) -> CorrectionItem:
    """Editor desk (E3) sets fixed / rejected. A fixed match correction shows the "Corrected" tag to fans."""
    r = next((x for x in store.error_reports if x["id"] == correction_id), None)
    if r is None:
        raise HTTPException(404, "Correction not found")
    r.update(status=status, resolution=note, resolved_at=store.now)
    if status == "fixed" and r["match_id"]:
        text = f"Corrected: {FIELDS.get(r['field'], 'details')}" + (f" — {r['correct_value']}" if r["correct_value"] else "")
        store.matches = [m.model_copy(update={"correction": MatchCorrection(message=text, at=store.now)}) if m.id == r["match_id"] else m
                         for m in store.matches]
    return _item(store, r)
