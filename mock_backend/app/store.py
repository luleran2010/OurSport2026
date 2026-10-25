"""In-memory store with a simulated live ticker. Swap for a DB + real data feed later."""

import asyncio
import random
import time
from datetime import datetime
from dataclasses import dataclass, field
from itertools import count

from .tournaments import seed_tournaments
from . import match_detail as MD
from . import tournaments as TN
from .notifications import EventLog
from .auth import Accounts
from . import club_members as CM
from . import club_teams as CT
from .mock_data import TEAMS as TEAMS_BY_ID
from .mock_data import ROLE_LABELS, DEMO_INVITES, DEMO_ADMIN_CLUBS, DEMO_ERROR_REPORTS, DEMO_SCORERS, DEMO_RESULTS_ONLY
from .mock_data import DEMO_EDITOR, DEMO_PUBLISHER, DEMO_SCORER
from .mock_data import CLUBS, DEFAULT_FOLLOWS, DEMO_FOLLOWS, DEMO_PREMIUM_CLUB, DEMO_USER_NAME, DEMO_EMAIL, DEMO_FAMILY, PLAYERS, seed, seed_club_content
from .models import (
    Correction, TimelineEvent, NotificationPrefs, FamilyLink, ClubRole,
    ClubEvent, ClubMatches, ClubSuggestion, Comment, FeedSnapshot, Follows, Match, Me, Post, Premium, Story,
    SuggestionReceipt,
)

VISITOR_UPCOMING_LIMIT = 3
_STATUS_ORDER = {"live": 0, "upcoming": 1, "finished": 2}


def end_of_year(ms: int) -> int:
    d = datetime.fromtimestamp(ms / 1000).astimezone()
    return int(d.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=0).timestamp() * 1000)


@dataclass
class Session:
    """One browser (cookie). Visitors can follow; signing in makes them a member."""

    id: str
    signed_in: bool = False
    teams: list[str] = field(default_factory=lambda: list(DEFAULT_FOLLOWS["teams"]))
    clubs: list[str] = field(default_factory=lambda: list(DEFAULT_FOLLOWS["clubs"]))
    tournaments: list[str] = field(default_factory=list)
    notifications: dict[str, NotificationPrefs] = field(default_factory=dict)  # follow id -> prefs
    # account (F10)
    name: str = DEMO_USER_NAME
    email: str | None = None
    language: str = "en"
    premium_club: str | None = None
    premium_until: int | None = None
    family: list[str] = field(default_factory=list)  # player ids this member is guardian of
    # notifications (F11): everything up to read_upto is read, plus individually read items
    read_upto: int = -1
    read_seqs: set[int] = field(default_factory=set)
    account_email: str | None = None  # set for real accounts (F12); None for visitors and demo sign-ins
    roles: list[tuple[str, str]] = field(default_factory=list)  # (club id, role) from accepted invites (F13)

    def follows_of(self, kind: str) -> list[str]:
        return {"club": self.clubs, "team": self.teams, "tournament": self.tournaments}[kind]

    def prefs(self, follow_id: str) -> NotificationPrefs:
        return self.notifications.setdefault(follow_id, NotificationPrefs())

    def sign_in_demo(self, plan: str) -> None:
        self.signed_in = True
        if plan == "scorer":  # a different person: the club's volunteer scorer (S1/S2)
            self.name, self.email = DEMO_SCORER["name"], DEMO_SCORER["email"]
            self.roles = [(DEMO_SCORER["club"], "scorer")]
            self.premium_club = self.premium_until = None
            self.family = []
            self.clubs = [DEMO_SCORER["club"]]
            return
        if plan == "publisher":  # an event organiser (P-series)
            self.name, self.email = DEMO_PUBLISHER["name"], DEMO_PUBLISHER["email"]
            self.roles = [("*", "publisher")]
            self.premium_club = self.premium_until = None
            self.family = []
            return
        if plan == "editor":  # an editor at a sports desk (E-series)
            self.name, self.email = DEMO_EDITOR["name"], DEMO_EDITOR["email"]
            self.roles = [("*", "editor")]
            self.premium_club = self.premium_until = None
            self.family = []
            return
        if self.email in (DEMO_SCORER["email"], DEMO_PUBLISHER["email"], DEMO_EDITOR["email"]):  # same browser switching back to the fan demo
            self.name, self.email, self.roles, self.clubs = DEMO_USER_NAME, DEMO_EMAIL, [], []
        if not (self.teams or self.clubs or self.tournaments):  # demo account comes with a couple of follows
            self.teams = list(DEMO_FOLLOWS["teams"])
            self.clubs = list(DEMO_FOLLOWS["clubs"])
        self.email = self.email or DEMO_EMAIL
        if plan == "premium":
            self.premium_club = DEMO_PREMIUM_CLUB
            self.premium_until = end_of_year(now_ms())
            self.family = list(DEMO_FAMILY)
            for club in DEMO_ADMIN_CLUBS:
                if (club, "admin") not in self.roles:
                    self.roles.append((club, "admin"))
        else:
            self.premium_club = self.premium_until = None
            self.family = []

    def is_admin(self, club_id: str) -> bool:
        return self.signed_in and (club_id, "admin") in self.roles

    def is_publisher(self) -> bool:
        """Publisher portal role (P-series): not tied to a club, stored as ("*", "publisher")."""
        return self.signed_in and ("*", "publisher") in self.roles

    def is_editor(self) -> bool:
        """Editor desk (E-series) role: not tied to a club, stored as ("*", "editor")."""
        return self.signed_in and ("*", "editor") in self.roles

    def grant_premium(self, club_id: str) -> None:
        self.premium_club = club_id
        self.premium_until = end_of_year(now_ms())

    def is_guardian_of(self, player_id: str) -> bool:
        return self.signed_in and player_id in self.family

    def me(self) -> Me:
        premium = None
        if self.signed_in and self.premium_club and (self.premium_until or 0) > now_ms():
            club = CLUBS[self.premium_club]
            premium = Premium(plan="Premium", via_club_id=club.id, via_club_name=club.name,
                              valid_until=self.premium_until)
        family = [FamilyLink(player=p) for p in PLAYERS if self.signed_in and p.id in self.family]
        roles = [
            ClubRole(club_id=c, club_name=CLUBS[c].name if c in CLUBS else "OurSport", role=r, label=ROLE_LABELS[r][0])
            for c, r in self.roles if self.signed_in and (c in CLUBS or c == "*") and r in ROLE_LABELS
        ]
        return Me(
            signed_in=self.signed_in,
            name=self.name if self.signed_in else "Guest fan",
            email=self.email if self.signed_in else None,
            language=self.language,
            premium=premium,
            follows=Follows(clubs=list(self.clubs), teams=list(self.teams), tournaments=list(self.tournaments)),
            family=family,
            roles=roles,
        )


SCORE_CHANCE = 0.12
INSIGHT_CHANCE = 0.08
LIVE_TOKEN_TTL_MS = 60 * 60 * 1000


def now_ms() -> int:
    return int(time.time() * 1000)


class FeedStore:
    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self._ids = count(1)
        self._changed = asyncio.Event()
        self.reset()

    def reset(self) -> None:
        self.now = now_ms()
        CT.reset_registry(self)  # teams / players / roster records back to the shipped data (C3)
        self.matches, self.posts = seed(self.now)
        self.suggestions: list[tuple[str, ClubSuggestion]] = []
        self.events, self.stories = seed_club_content(self.now)
        tournaments, cup_matches, cup_stories = seed_tournaments(self.now)
        self.tournaments = {t.id: t for t in tournaments}
        self.matches += cup_matches
        self.stories += cup_stories
        self.sessions: dict[str, Session] = {}  # cookie id -> profile (several cookies may share an account's)
        self.v1 = None  # v1 contract sessions and tokens (v1/auth.py), created on first use
        self.accounts = Accounts()
        # invites (F13): token -> dict(club, kind, role, invited_by, message, expires_at, used_by)
        day = 24 * 60 * 60 * 1000
        self.invites: dict[str, dict] = {
            tok: {"club": club, "kind": kind, "role": role, "invited_by": by, "message": msg,
                  "expires_at": self.now + days * day, "used_by": object() if used else None}
            for tok, club, kind, role, by, msg, days, used in DEMO_INVITES
        }
        self.club_members: dict[str, list[dict]] = {}  # club portal rosters (C2), see club_members.py
        self.billing: dict[str, dict] = {}  # club subscriptions (C6), filled on first use: club_portal.subscription
        self.portal_sessions: dict[str, dict] = {}  # mock payment-provider page sessions (C6)
        self.manual: dict[str, dict] = {}  # matches a scorer is scoring (S2): the simulation leaves them alone
        from . import publisher as PUB

        PUB.seed(self)  # publisher events and the AI drafts waiting for review (P1)
        from . import editor_desk as ED

        self.correction_claims: dict[str, dict] = {}  # correction id -> {"by", "at"}: an editor is on it (E1)
        ED.seed(self)  # more flagged texts and club news for the editors' queue (E1)
        from . import review_item as RI

        RI.seed(self)  # texts, fact sheets, checker results and history for each item (E2)
        self.unpublished: dict[str, dict] = {}  # E3: story id -> {"story", "at", "by", "reason"}
        self.blocked: dict[str, dict] = {}  # P5: drafts the editors rejected: story id -> {"story", "reason", "by", "at", "event_id"}
        self.pub_posts: dict[str, dict] = {}  # P5: publisher posts not sent yet (drafts): story id -> {"story", "event_id", "publish_at"}
        self.post_owner: dict[str, str] = {}  # P5: story id -> publisher email (their manual posts)
        self.uploads: dict[str, tuple[str, bytes]] = {}  # uploaded images (C5): id -> (content type, bytes)
        CM.seed_rosters(self)
        self.live_tokens: dict[str, tuple[Session, int]] = {}  # token -> (profile, expires at)
        # Match page content: timelines for live games, previews/reports as stories.
        self.timelines: dict[str, list[TimelineEvent]] = {
            m.id: MD.seed_timeline(m, self.now, self._next_id) for m in self.matches if m.status == "live"
        }
        for m in self.matches:
            if m.status == "upcoming":
                self.stories.append(MD.preview_story(m, self.now, MD.head_to_head(self, m)))
            elif m.status == "finished":
                self.stories.append(MD.report_story(m, self.now, impact=MD.table_impact(self, m)))
        # fan error reports (F7) -> club corrections queue (C7)
        self.error_reports: list[dict] = []
        for story_id, message in DEMO_ERROR_REPORTS:
            self.add_error_report(story_id, message)
        from . import corrections

        corrections.seed(self)
        # match id -> {"member_id", "club_id"}: the scorer a club assigned (C4); see club_matches.py
        self.scorers: dict[str, dict] = {}
        for m in self.matches:  # results-only games: no live events, the club enters the final score
            t = self.tournaments.get(m.tournament_id or "")
            if m.id in DEMO_RESULTS_ONLY or (t and t.results_only and m.status == "upcoming"):
                m.data_level = "results_only"
        for mid, (club_id, name) in DEMO_SCORERS.items():
            row = next((r for r in self.club_members.get(club_id, []) if r["name"] == name), None)
            if row:
                self.scorers[mid] = {"member_id": row["id"], "club_id": club_id}
        from . import event_manage as EM

        EM.seed(self)  # event settings, the events' own scorers (P4)
        self._seed_log()
        # Demo: one result was corrected after the match report was checked.
        self.matches = [
            m.model_copy(update={"correction": Correction(
                message="Result corrected: the 88th-minute goal was confirmed for Oulun Tarmo after the referee’s "
                        "report was checked. The score was briefly shown as 0–0.",
                at=(m.ended_at or self.now) + 40 * 60_000,
            )}) if m.id == "r4" else m
            for m in self.matches
        ]

    # ---- notifications log (F11) -------------------------------------------
    def _seed_log(self) -> None:
        """Recent history so members see notifications straight away."""
        self.log = EventLog()
        since = self.now - 8 * 24 * 60 * 60 * 1000  # the past week or so
        for m in self.matches:
            if m.status == "finished" and (m.ended_at or 0) >= since:
                self._log_result(m, at=m.ended_at)
            elif m.status == "live":
                self._log_kickoff(m, at=self.now - (m.clock or 0) * 60_000)
                for e in self.timelines.get(m.id, []):
                    if e.kind == "goal":
                        team = TEAMS_BY_ID.get(e.team_id)
                        self.log.add("live_update", e.at, f"Goal! {team.name if team else ''}".strip(),
                                     f"{e.minute}′ · {m.home.name} v {m.away.name}", ("match", m.id),
                                     teams=[m.home.id, m.away.id], tournament=m.tournament_id)
        for st in self.stories:
            if since <= st.published_at <= self.now:
                self._log_story(st)
        self.log.sort_seeded()

    def _log_kickoff(self, m: Match, at: int) -> None:
        self.log.add("match_start", at, f"Kick-off: {m.home.name} v {m.away.name}", f"{m.league} · {m.venue}",
                     ("match", m.id), teams=[m.home.id, m.away.id], tournament=m.tournament_id)

    def _log_result(self, m: Match, at: int) -> None:
        self.log.add("result", at, f"Full time: {m.home.name} {m.score[0]}–{m.score[1]} {m.away.name}",
                     m.league, ("match", m.id), teams=[m.home.id, m.away.id], tournament=m.tournament_id)

    def _log_story(self, st: Story) -> None:
        self.log.add("news", st.published_at, st.title, st.summary, ("story", st.id), teams=st.team_ids,
                     clubs=[st.club_id] if st.club_id else [], tournament=st.tournament_id)

    def _log_scenario_changes(self, m: Match) -> None:
        """After a tournament game ends: tell followers whose team is now through or out."""
        t = self.tournaments.get(m.tournament_id or "")
        group = t and next((g for g in t.groups if m.home.id in g.team_ids and m.away.id in g.team_ids), None)
        if not group:
            return
        after_matches = TN._group_matches(t, group, self.matches)
        before_matches = [x.model_copy(update={"status": "live"}) if x.id == m.id else x for x in after_matches]
        before, after = TN._statuses(t, group, before_matches), TN._statuses(t, group, after_matches)
        for tid in group.team_ids:
            old, new = before[tid]["status"], after[tid]["status"]
            if old != new and new in ("through", "out"):
                name = TEAMS_BY_ID[tid].name
                title = f"{name} are through to {t.qualify_label}" if new == "through" else f"{name} are out of {t.name}"
                self.log.add("scenario_change", self.now, title, f"{group.name} · after {m.home.short} {m.score[0]}–"
                             f"{m.score[1]} {m.away.short}", ("event", t.id), teams=[tid], tournament=t.id)

    def _next_id(self) -> int:
        return next(self._ids)

    # ---- match page (F6) ---------------------------------------------------
    def match_stories(self, match_id: str) -> list[Story]:
        return sorted((s for s in self.stories if s.match_id == match_id), key=lambda s: -s.published_at)

    def _timeline(self, m: Match, kind: str, text: str, team_id: str | None = None, ai: bool = False) -> None:
        self.timelines.setdefault(m.id, []).append(TimelineEvent(
            id=f"tl-{self._next_id()}", minute=m.clock or 0, kind=kind, text=text, team_id=team_id, ai=ai, at=self.now,
        ))

    def add_error_report(self, story_id: str, message: str) -> str:
        """A fan's report from a story page (F7); it lands in the clubs' corrections list (C7)."""
        from . import corrections

        return corrections.add(self, source="fan", story_id=story_id, message=message, field="story")["id"]

    def issue_live_token(self, profile: Session) -> tuple[str, int]:
        import secrets

        token = secrets.token_urlsafe(24)
        expires = now_ms() + LIVE_TOKEN_TTL_MS
        self.live_tokens[token] = (profile, expires)
        return token, expires

    def session_for_token(self, token: str | None) -> "Session | None":
        profile, expires = self.live_tokens.get(token or "", (None, 0))
        if profile is None or expires < now_ms():
            return None
        # still valid only while some browser is signed in to this profile
        return profile if any(p is profile for p in self.sessions.values()) else None

    # ---- sessions ----------------------------------------------------------
    def session(self, sid: str | None) -> Session | None:
        return self.sessions.get(sid) if sid else None

    def bind(self, sid: str, profile: Session) -> None:
        """Point a browser cookie at a profile (log-in) — replaces whatever it pointed at."""
        self.sessions[sid] = profile

    def delete_profile(self, profile: Session) -> None:
        """Remove a profile everywhere: all browsers signed in to it, its live tokens and its account."""
        self.sessions = {sid: p for sid, p in self.sessions.items() if p is not profile}
        self.live_tokens = {t: v for t, v in self.live_tokens.items() if v[0] is not profile}
        self.accounts.delete(profile.account_email)

    def new_session(self, sid: str) -> Session:
        self.sessions[sid] = Session(id=sid)
        return self.sessions[sid]

    # ---- clubs (F3) --------------------------------------------------------
    def club_matches(self, club_id: str, when: str, member: bool, limit: int = 50) -> ClubMatches:
        team_ids = set(CLUBS[club_id].team_ids)
        mine = [m for m in self.matches if m.home.id in team_ids or m.away.id in team_ids]
        if when == "past":
            items = sorted((m for m in mine if m.status == "finished"), key=lambda m: -(m.ended_at or 0))
            return ClubMatches(when="past", matches=items[:limit], events=[], total=len(items), limited=False)

        def when_of(x: Match | ClubEvent) -> tuple[int, int]:
            if isinstance(x, ClubEvent):
                return (1, x.starts_at)
            return (_STATUS_ORDER[x.status], x.starts_at or 0)

        upcoming: list[Match | ClubEvent] = [m for m in mine if m.status in ("live", "upcoming")]
        upcoming += [e for e in self.events if e.club_id == club_id and e.starts_at >= self.now]
        upcoming.sort(key=when_of)
        cap = limit if member else min(limit, VISITOR_UPCOMING_LIMIT)
        shown = upcoming[:cap]
        return ClubMatches(
            when="upcoming",
            matches=[x for x in shown if isinstance(x, Match)],
            events=[x for x in shown if isinstance(x, ClubEvent)],
            total=len(upcoming),
            limited=not member and len(upcoming) > cap,
        )

    def club_stories(self, club_id: str) -> list[Story]:
        return sorted((s for s in self.stories if s.club_id == club_id), key=lambda s: -s.published_at)

    def get_story(self, story_id: str) -> Story | None:
        return next((s for s in self.stories if s.id == story_id), None)

    def get_match(self, match_id: str) -> Match | None:
        return next((m for m in self.matches if m.id == match_id), None)

    # ---- reads -------------------------------------------------------------
    def snapshot(self) -> FeedSnapshot:
        return FeedSnapshot(now=self.now, matches=self.matches, posts=self.posts)

    def get_post(self, post_id: str) -> Post | None:
        return next((p for p in self.posts if p.id == post_id), None)

    # ---- writes ------------------------------------------------------------
    def add_comment(self, post_id: str, author: str, text: str) -> Comment | None:
        post = self.get_post(post_id)
        if post is None:
            return None
        comment = Comment(id=f"c-{next(self._ids)}", author=author, text=text, created_at=now_ms())
        post.comments.append(comment)
        self._notify()
        return comment

    def add_suggestion(self, suggestion: ClubSuggestion) -> SuggestionReceipt:
        receipt = SuggestionReceipt(id=f"sg-{next(self._ids)}")
        self.suggestions.append((receipt.id, suggestion))
        return receipt

    def tick(self) -> None:
        """Advance the simulation one step: kick off due games, run clocks, maybe score."""
        self.now = now_ms()
        scored = False
        just_finished: list[str] = []
        updated: list[Match] = []
        for m in self.matches:
            if m.id in self.manual:  # scored by a person (S2): only the clock moves
                st = self.manual[m.id]
                if m.status == "live" and st["running"]:
                    m = m.model_copy(update={"clock": st["base_minute"] + max(0, (self.now - st["base_at"]) // 60_000),
                                             "flash": None})
            elif m.status == "upcoming" and m.data_level == "results_only":
                pass  # no live play-by-play: stays scheduled until the club enters the result (C4)
            elif m.status == "upcoming" and m.starts_at is not None and m.starts_at <= self.now:
                m = m.model_copy(update={
                    "status": "live", "clock": 1, "period": "1st", "score": [0, 0],
                    "viewers": 12, "last_event": "Game under way!",
                })
                self._timeline(m, "kickoff", f"Kick-off at {m.venue}.")
                self._log_kickoff(m, at=self.now)
            elif m.status == "live" and self._at_full_time(m):
                m = m.model_copy(update={
                    "status": "finished", "ended_at": self.now, "period": "Full time", "flash": None,
                    "last_event": f"Full time: {m.home.short} {m.score[0]}–{m.score[1]} {m.away.short}",
                })
                self._timeline(m, "fulltime", f"Full time: {m.home.name} {m.score[0]}–{m.score[1]} {m.away.name}.")
                just_finished.append(m.id)
            elif m.status == "live":
                m = m.model_copy(update={
                    "clock": (m.clock or 0) + 1,
                    "flash": None,
                    "viewers": (m.viewers or 0) + self.rng.randint(0, 3),
                })
                if not scored and self.rng.random() < SCORE_CHANCE:
                    scored = True
                    m = self._score(m, self.rng.randint(0, 1))
                elif self.rng.random() < INSIGHT_CHANCE:
                    self._timeline(m, "insight", MD.insight_text(m, self.timelines.get(m.id, [])), ai=True)
            updated.append(m)
        self.matches = updated
        for mid in just_finished:  # write the AI report once the table includes the result
            m = self.get_match(mid)
            self._log_result(m, at=self.now)
            self._log_scenario_changes(m)
            report = MD.report_story(m, self.now, self.timelines.get(mid), MD.table_impact(self, m))
            self.stories.append(report)
            self._log_story(report)
        self._notify()

    def finish_match(self, match_id: str, score: list[int]) -> Match:
        """End a game with this final score (club result entry or the scorer's "finish"): the same
        follow-ups as a game the simulation ends: result notification, scenario changes, AI report."""
        self.now = now_ms()
        old = self.get_match(match_id)
        m = old.model_copy(update={
            "status": "finished", "score": list(score), "ended_at": self.now, "period": "Full time", "flash": None,
            "clock": old.clock, "last_event": f"Full time: {old.home.short} {score[0]}–{score[1]} {old.away.short}",
        })
        self.matches = [m if x.id == match_id else x for x in self.matches]
        if old.status == "live":
            self._timeline(m, "fulltime", f"Full time: {m.home.name} {score[0]}–{score[1]} {m.away.name}.")
        self._log_result(m, at=self.now)
        self._log_scenario_changes(m)
        report = MD.report_story(m, self.now, self.timelines.get(match_id), MD.table_impact(self, m))
        self.stories.append(report)
        self._log_story(report)
        self._notify()
        return m

    def _at_full_time(self, m: Match) -> bool:
        """Tournament games end at their set length; league demo games keep running."""
        t = self.tournaments.get(m.tournament_id or "")
        return t is not None and (m.clock or 0) >= t.match_minutes

    def _score(self, m: Match, side: int) -> Match:
        score = list(m.score or [0, 0])
        score[side] += 1
        team = m.home if side == 0 else m.away
        line = f"{m.home.short} {score[0]}–{score[1]} {m.away.short}"
        self._timeline(m, "goal", f"Goal! {team.name} — {line}", team_id=team.id)
        self.log.add("live_update", self.now, f"Goal! {team.name} — {line}", f"{m.clock}′ · {m.league}",
                     ("match", m.id), teams=[m.home.id, m.away.id], tournament=m.tournament_id)
        self.posts.insert(0, Post(
            id=f"auto-{next(self._ids)}", type="score", sport=m.sport, match_id=m.id,
            team_ids=[m.home.id, m.away.id], author="OurSport Live", created_at=self.now,
            text=f"Score! {team.name} — {line} ({m.clock}′)",
        ))
        return m.model_copy(update={
            "score": score, "flash": side, "last_event": f"{m.clock}′ {team.name} score! {line}",
        })

    # ---- change notification (for the SSE stream) --------------------------
    def _notify(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()

    async def wait_for_change(self, timeout: float) -> bool:
        event = self._changed
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def run_ticker(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            self.tick()
