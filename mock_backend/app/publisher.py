"""Publisher portal (P-series): event organisers' events and the AI texts waiting for their review.

Events a publisher runs live in store.publisher_events: published tournaments (fans see them) and events still
being set up (draft, rules pending). AI-written texts are reviewed by editors (E-series); a publisher can also
review the ones for their events when "publisher review" is on for that event.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from .mock_data import DEMO_PUBLISHER, TEAMS
from .models import PublisherEvent, PublisherEvents, ReviewItem, ReviewQueue, ReviewStory, Story

if TYPE_CHECKING:
    from .store import FeedStore, Session

DAY = 86_400_000
HOUR = 3_600_000


def seed(store: FeedStore) -> None:
    now = store.now
    owner = DEMO_PUBLISHER["email"]
    store.publisher_events = {
        "njc-u17": {"tournament_id": "njc-u17", "owners": [owner], "review_enabled": True},
        "oulu-sixes": {"tournament_id": "oulu-sixes", "owners": [owner], "review_enabled": False},
        "winter-futsal-26": {
            "owners": [owner], "review_enabled": False, "status": "draft", "name": "Oulu Winter Futsal Cup 2026",
            "sport": "football", "starts_at": now + 42 * DAY, "ends_at": now + 43 * DAY, "venue": "Ouluhalli", "teams": 5,
            "matches_total": 0, "next_step": "Add the teams and upload the rulebook.",
        },
        "finbangla-26": {
            "owners": [owner], "review_enabled": True, "status": "rules_pending", "name": "FinBangla Cricket Cup 2026",
            "sport": "cricket", "starts_at": now + 21 * DAY, "ends_at": now + 22 * DAY, "venue": "Kuivasjärvi cricket ground",
            "teams": 8, "matches_total": 15, "next_step": "Check the rules read from the rulebook and confirm them.",
            "step": 4, "groups": [{"id": "A", "name": "Group A"}, {"id": "B", "name": "Group B"}],
            "rulebook": {"kind": "file", "name": "FinBangla-Cup-2026-rules.pdf", "size": 184_220, "received_at": now - 2 * DAY},
            "rules_job": {"status": "done", "progress": 100, "step": "Rules found", "started_at": now - 2 * DAY},
            "rules_text": "FinBangla Cricket Cup 2026 playing conditions. Matches are 20 overs a side and should finish within "
                          "180 minutes. A win gives 2 points and a tie or no result 1 point. Teams in each group are ranked by "
                          "points, then by net run rate. The top 2 teams of each group play the semi-finals. "
                          "Umpires' decisions are final.",
        },
        "autumn-floorball-26": {
            "owners": [owner], "review_enabled": False, "status": "finished", "name": "Oulu Autumn Floorball Cup",
            "sport": "floorball", "starts_at": now - 20 * DAY, "ends_at": now - 19 * DAY, "venue": "Ouluhalli", "teams": 6,
            "matches_total": 9, "matches_played": 9, "next_step": "All done. The results stay on OurSport.",
        },
    }
    # AI texts written for the publisher's events, not published until reviewed
    cup = store.tournaments.get("njc-u17")
    drafts = [
        Story(id="draft-njc-sf-preview", tournament_id="njc-u17", tag="Preview", author="OurSport AI", author_type="ai",
              published_at=now - 50 * 60_000, team_ids=["olsu17", "tarmou17"],
              title="Semi-final race: three teams chasing two places in Group A",
              summary="OLS U17 lead the group, but Tarmo U17 and AC Oulu U17 can still go through.",
              body=["OLS U17 top Group A with one round to play.", "A draw is enough for OLS; Tarmo need to win."]),
        Story(id="draft-njc-day2", tournament_id="njc-u17", tag="Day 2 report", author="OurSport AI", author_type="ai",
              published_at=now - 20 * 60_000,
              title="Group B decided on goal difference",
              summary="Tornio U17 and Raahe U17 finish level on points; goal difference sends Tornio through first.",
              body=["Tornio U17 won their last game 2–0.", "Raahe U17 also finished on six points."]),
        Story(id="draft-sixes-final", tournament_id="oulu-sixes", tag="Preview", author="OurSport AI", author_type="ai",
              published_at=now - 30 * 60_000, title="Strikers and Oulu CC set for Sunday’s final",
              summary="Net run rate separated the top three after the last league round.", body=["The final starts at 14:00."]),
    ]
    store.drafts = {d.id: d for d in drafts}
    store.review_items = [
        {"id": "rv-1", "story_id": "draft-njc-sf-preview", "event_id": "njc-u17", "reason": "New preview before the last group round",
         "created_at": now - 50 * 60_000, "status": "pending", "claimed_by": None},
        {"id": "rv-2", "story_id": "draft-njc-day2", "event_id": "njc-u17", "reason": "New day report", "created_at": now - 20 * 60_000,
         "status": "in_review", "claimed_by": "Editor desk"},
        {"id": "rv-3", "story_id": "draft-sixes-final", "event_id": "oulu-sixes", "reason": "New preview for the final",
         "created_at": now - 30 * 60_000, "status": "pending", "claimed_by": None},
    ]
    if cup is None:
        store.review_items = [r for r in store.review_items if r["event_id"] != "njc-u17"]


def require_publisher(session: Session) -> None:
    if not session.signed_in:
        raise HTTPException(401, "Log in with your publisher account.")
    if not session.is_publisher():
        raise HTTPException(403, {"code": "not_publisher", "message": "Only publishers can open the publisher portal."})


def my_event_ids(store: FeedStore, session: Session) -> list[str]:
    email = (session.email or "").lower()
    return [eid for eid, e in store.publisher_events.items() if email in {o.lower() for o in e["owners"]}]


def _event(store: FeedStore, eid: str) -> PublisherEvent:
    e = store.publisher_events[eid]
    t = store.tournaments.get(e.get("tournament_id") or "")
    if t is None:  # still being set up (or an old event without match data)
        from .event_setup import normalise, tick_job

        normalise(e)
        tick_job(store, e)
        teams = len(e["teams"]) or e.get("planned_teams", 0)
        return PublisherEvent(id=eid, name=e["name"], sport=e["sport"], status=e["status"], starts_at=e["starts_at"],
                              ends_at=e["ends_at"], venue=e["venue"], teams=teams, matches_total=e.get("matches_total", 0),
                              matches_played=e.get("matches_played", 0), live_now=0, review_enabled=e["review_enabled"],
                              next_step=e["next_step"])
    games = [m for m in store.matches if m.tournament_id == t.id]
    played = sum(1 for m in games if m.status == "finished")
    live = sum(1 for m in games if m.status == "live")
    if games and played == len(games) or store.now > t.ends_at:
        status, step = "finished", "All matches played. Check the final report."
    elif live or t.starts_at <= store.now:
        status = "live"
        step = f"{live} match{'es' if live != 1 else ''} live now · {len(games) - played} still to play." if live \
            else f"{len(games) - played} matches still to play."
    else:
        status, step = "scheduled", "Published. Matches start on the first day."
    return PublisherEvent(id=eid, name=t.name, sport=t.sport, status=status, starts_at=t.starts_at, ends_at=t.ends_at,
                          venue=t.venue, teams=len(t.teams), matches_total=len(games), matches_played=played, live_now=live,
                          review_enabled=store.publisher_events[eid]["review_enabled"], tournament_id=t.id, next_step=step)


ORDER = {"live": 0, "rules_pending": 1, "draft": 2, "scheduled": 3, "finished": 4}


def events(store: FeedStore, session: Session) -> PublisherEvents:
    require_publisher(session)
    items = sorted((_event(store, eid) for eid in my_event_ids(store, session)),
                   key=lambda e: (ORDER[e.status], e.starts_at or 0))
    org = DEMO_PUBLISHER["organisation"] if (session.email or "").lower() == DEMO_PUBLISHER["email"] else session.name
    return PublisherEvents(organisation=org, events=items, updated_at=store.now)


def _item(store: FeedStore, r: dict) -> ReviewItem | None:
    st = store.drafts.get(r["story_id"])
    if st is None:
        return None
    name = store.tournaments[r["event_id"]].name if r["event_id"] in store.tournaments else store.publisher_events[r["event_id"]].get("name", r["event_id"])
    return ReviewItem(id=r["id"], reason=r["reason"], event_id=r["event_id"], event_name=name, created_at=r["created_at"],
                      status=r["status"], claimed_by=r["claimed_by"],
                      story=ReviewStory(id=st.id, title=st.title, summary=st.summary, tag=st.tag, language=st.language,
                                        author_type=st.author_type))


def review_queue(store: FeedStore, session: Session, scope: str) -> ReviewQueue:
    if not session.signed_in:
        raise HTTPException(401, "Log in first.")
    require_publisher(session)
    enabled = [eid for eid in my_event_ids(store, session) if store.publisher_events[eid]["review_enabled"]]
    rows = [r for r in store.review_items if r["event_id"] in enabled]
    items = [i for i in (_item(store, r) for r in sorted(rows, key=lambda r: r["created_at"])) if i and i.status != "done"]
    return ReviewQueue(scope=scope, items=items, review_enabled_events=enabled, updated_at=store.now)
