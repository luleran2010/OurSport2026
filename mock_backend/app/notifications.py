"""Notifications (F11): a shared event log, filtered per member by follows and alert settings.

Events are recorded once (kick-off, goal, full time, qualification change, new story). Each member sees
the events that concern what they follow, if the matching alert switch (F9) is on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .mock_data import CLUBS, TEAMS
from .models import AppNotification, NotificationLink, NotificationsPage

if TYPE_CHECKING:
    from .store import Session

# notification kind -> alert switch (NotificationPrefs field)
PREF_FOR_KIND = {
    "match_start": "match_start",
    "live_update": "live_updates",
    "result": "results",
    "scenario_change": "scenario_changes",
    "news": "news",
}


@dataclass
class LogEvent:
    seq: int  # position in the log (also the cursor)
    kind: str
    at: int
    title: str
    body: str
    link_type: str
    link_id: str
    team_ids: list[str] = field(default_factory=list)
    club_ids: list[str] = field(default_factory=list)
    tournament_id: str | None = None


class EventLog:
    def __init__(self) -> None:
        self.events: list[LogEvent] = []

    def add(self, kind: str, at: int, title: str, body: str, link: tuple[str, str], *,
            teams: list[str] = (), clubs: list[str] = (), tournament: str | None = None) -> None:
        self.events.append(LogEvent(
            seq=len(self.events), kind=kind, at=at, title=title, body=body, link_type=link[0], link_id=link[1],
            team_ids=list(teams), club_ids=list(clubs), tournament_id=tournament,
        ))

    def sort_seeded(self) -> None:
        """Seeded history arrives out of order: sort by time once, then renumber."""
        self.events.sort(key=lambda e: e.at)
        for i, e in enumerate(self.events):
            e.seq = i

    # ---- per member ------------------------------------------------------------
    @staticmethod
    def _follow_ids(s: Session, e: LogEvent) -> list[str]:
        ids = [f"team:{t}" for t in e.team_ids if t in s.teams]
        event_clubs = set(e.club_ids) | {TEAMS[t].club_id for t in e.team_ids if t in TEAMS}
        ids += [f"club:{c}" for c in s.clubs if c in event_clubs]
        if e.tournament_id and e.tournament_id in s.tournaments:
            ids.append(f"tournament:{e.tournament_id}")
        return ids

    def relevant(self, s: Session, e: LogEvent) -> bool:
        pref = PREF_FOR_KIND[e.kind]
        return any(getattr(s.prefs(fid), pref) for fid in self._follow_ids(s, e))

    def is_read(self, s: Session, e: LogEvent) -> bool:
        return e.seq <= s.read_upto or e.seq in s.read_seqs

    def page(self, s: Session, limit: int, before: int | None) -> NotificationsPage:
        mine = [e for e in reversed(self.events) if self.relevant(s, e)]
        unread = sum(1 for e in mine if not self.is_read(s, e))
        if before is not None:
            mine = [e for e in mine if e.seq < before]
        chunk = mine[:limit]
        return NotificationsPage(
            items=[AppNotification(
                id=f"n-{e.seq}", kind=e.kind, title=e.title, body=e.body, at=e.at, read=self.is_read(s, e),
                link=NotificationLink(type=e.link_type, id=e.link_id),
            ) for e in chunk],
            unread_count=unread,
            next_cursor=str(chunk[-1].seq) if len(mine) > limit else None,
        )

    def mark_read(self, s: Session, ids: list[str], all_: bool) -> None:
        if all_:
            s.read_upto = len(self.events) - 1
            s.read_seqs.clear()
            return
        for nid in ids:
            if nid.startswith("n-") and nid[2:].isdigit():
                s.read_seqs.add(int(nid[2:]))


def club_name(club_id: str | None) -> str:
    return CLUBS[club_id].name if club_id in CLUBS else ""
