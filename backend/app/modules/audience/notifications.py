"""Personal notifications (docs/14-personal-experience.md, Personal notifications).

Followers of a team get a notification per kind they have on (defaults in
`NOTIFY_DEFAULTS`), in their language. At most one per team per 5 minutes except
match start, result and schedule change. In quiet hours (22-08, the follower's time
zone) nothing is pushed — the notification still waits in the app — except a schedule
change for a match in the next 2 hours. Without a push subscription, schedule changes go
by email.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import transaction
from app.core.email import EmailSender, OutgoingEmail
from app.core.ids import new_id
from app.core.time import Clock
from app.modules.accounts import service as accounts
from app.modules.audience import repository
from app.modules.audience.models import NOTIFY_DEFAULTS, Notification, PushSubscription
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut

log = structlog.get_logger("notifications")

UNTHROTTLED = frozenset({"match_start", "result", "schedule_change"})
THROTTLE = timedelta(minutes=5)
QUIET_START, QUIET_END = 22, 8
URGENT_WINDOW = timedelta(hours=2)
TOGGLE = {"reminder": "match_start"}  # reminders follow the match-start switch

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "match_start": "{team} kick off now on {pitch}",
        "reminder": "{team} play {opponent} at {time} on {pitch}",
        "result": "Full time: {home} {home_goals}–{away_goals} {away}",
        "scenario_change": "{team}: {summary}",
        "relevance": "A match now matters for {team}. {reason}",
        "schedule_change": "{team}: the schedule changed. Check your next match time and pitch.",
        "next_opponent": "{team} play {opponent} next ({code}, {time}, {pitch})",
        "goal": "GOAL {team}! {home_goals}–{away_goals}",
        "news": "{team}: {title}",
    },
    "fi": {
        "match_start": "{team} aloittaa nyt kentällä {pitch}",
        "reminder": "{team} – {opponent} klo {time}, {pitch}",
        "result": "Lopputulos: {home} {home_goals}–{away_goals} {away}",
        "scenario_change": "{team}: {summary}",
        "relevance": "Tämä ottelu vaikuttaa nyt joukkueeseen {team}. {reason}",
        "schedule_change": "{team}: aikataulu muuttui. Tarkista seuraavan ottelun aika ja kenttä.",
        "next_opponent": "{team} kohtaa seuraavaksi joukkueen {opponent} ({code}, {time}, {pitch})",
        "goal": "MAALI {team}! {home_goals}–{away_goals}",
        "news": "{team}: {title}",
    },
    "bn": {
        "match_start": "{team} এখন {pitch} মাঠে খেলা শুরু করছে",
        "reminder": "{team} বনাম {opponent}, {time}, {pitch}",
        "result": "খেলা শেষ: {home} {home_goals}–{away_goals} {away}",
        "scenario_change": "{team}: {summary}",
        "relevance": "একটি ম্যাচ এখন {team}-এর জন্য গুরুত্বপূর্ণ। {reason}",
        "schedule_change": "{team}: সময়সূচি বদলেছে। পরের ম্যাচের সময় ও মাঠ দেখে নিন।",
        "next_opponent": "{team}-এর পরের প্রতিপক্ষ {opponent} ({code}, {time}, {pitch})",
        "goal": "গোল {team}! {home_goals}–{away_goals}",
        "news": "{team}: {title}",
    },
}


class PushSender(Protocol):
    async def send(self, endpoint: str, keys: dict[str, str], payload: dict[str, Any]) -> bool: ...


class WebPushSender:
    """Web push with VAPID (pywebpush), run off the event loop."""

    def __init__(self, settings: Settings) -> None:
        assert settings.vapid_private_key is not None
        self._key = settings.vapid_private_key.get_secret_value()
        self._subject = settings.vapid_subject

    async def send(self, endpoint: str, keys: dict[str, str], payload: dict[str, Any]) -> bool:
        from pywebpush import WebPushException, webpush

        def deliver() -> bool:
            try:
                webpush(
                    {"endpoint": endpoint, "keys": keys},
                    json.dumps(payload),
                    vapid_private_key=self._key,
                    vapid_claims={"sub": self._subject},
                )
            except WebPushException:
                log.warning("push_failed", endpoint=endpoint[:40])
                return False
            return True

        return await asyncio.to_thread(deliver)


@dataclass(frozen=True)
class Delivery:
    push: PushSender | None = None
    email: EmailSender | None = None


def delivery_for(settings: Settings, email: EmailSender | None) -> Delivery:
    push = WebPushSender(settings) if settings.vapid_private_key else None
    return Delivery(push=push, email=email)


def _quiet(now: datetime, time_zone: str) -> bool:
    hour = now.astimezone(ZoneInfo(time_zone)).hour
    return hour >= QUIET_START or hour < QUIET_END


class _Blank(dict[str, Any]):
    """Missing values render as empty text rather than failing the whole notification."""

    def __missing__(self, key: str) -> str:
        return ""


def render(language: str, kind: str, values: dict[str, Any]) -> str:
    template = TEXTS.get(language, TEXTS["en"]).get(kind) or TEXTS["en"][kind]
    return template.format_map(_Blank(values))


async def notify(
    db: AsyncSession,
    clock: Clock,
    delivery: Delivery,
    *,
    kind: str,
    per_team: dict[UUID, dict[str, Any]],
    match_starts_at: datetime | None = None,
) -> int:
    """Notify the followers of each team in `per_team` (values for its text); returns how
    many notifications were created."""
    now = clock.now()
    follows = await repository.followers_of(db, "team", list(per_team))
    toggle = TOGGLE.get(kind, kind)
    follows = [f for f in follows if {**NOTIFY_DEFAULTS, **f.notify}.get(toggle, False)]
    if not follows:
        return 0
    people = await accounts.profiles(db, sorted({f.user_id for f in follows}))
    urgent = (
        kind == "schedule_change"
        and match_starts_at is not None
        and match_starts_at - now <= URGENT_WINDOW
    )
    created = 0
    async with transaction(db):
        for follow in follows:
            person = people.get(follow.user_id)
            if person is None:
                continue
            team_id = follow.target_id
            if kind not in UNTHROTTLED and await repository.notified_since(
                db, follow.user_id, team_id, now - THROTTLE
            ):
                continue
            text = render(person.language, kind, per_team[team_id])
            quiet = _quiet(now, person.time_zone) and not urgent
            pushed = False
            if not quiet:
                pushed = await _deliver(db, delivery, follow.user_id, person.email, kind, text)
            db.add(
                Notification(
                    id=new_id(),
                    user_id=follow.user_id,
                    kind=kind,
                    team_id=team_id,
                    payload={"text": text, **{k: str(v) for k, v in per_team[team_id].items()}},
                    pushed=pushed,
                    created_at=now,
                )
            )
            created += 1
    return created


async def _deliver(
    db: AsyncSession, delivery: Delivery, user_id: UUID, email: str, kind: str, text: str
) -> bool:
    subscriptions = (
        (await db.execute(select(PushSubscription).where(PushSubscription.user_id == user_id)))
        .scalars()
        .all()
    )
    sent = False
    if delivery.push is not None:
        for sub in subscriptions:
            sent |= await delivery.push.send(sub.endpoint, sub.keys, {"kind": kind, "text": text})
    if not subscriptions and kind == "schedule_change" and delivery.email is not None:
        await delivery.email.send(OutgoingEmail(to=email, subject="OurSport", text=text))
        sent = True
    return sent


# --- turning jobs into notifications ---------------------------------------------------------


async def _match_values(
    db: AsyncSession, match: MatchOut
) -> tuple[dict[UUID, dict[str, Any]], str, str]:
    entries = {e.team_id: e.name for e in await competitions.entries_of(db, match.tournament_id)}
    pitches = {p.id: p.name for p in await competitions.pitches_of(db, match.tournament_id)}
    tournament = await competitions.tournament_window(db, match.tournament_id)
    local = match.starts_at.astimezone(ZoneInfo(tournament.time_zone)).strftime("%H:%M")
    pitch = pitches.get(match.pitch_id, "") if match.pitch_id else ""
    home, away = entries.get(match.home_team_id, ""), entries.get(match.away_team_id, "")  # type: ignore[arg-type]  # None maps to ""
    result = match.result or {}
    values: dict[UUID, dict[str, Any]] = {}
    for team_id, opponent in ((match.home_team_id, away), (match.away_team_id, home)):
        if team_id is None:
            continue
        values[team_id] = {
            "team": entries.get(team_id, ""),
            "opponent": opponent,
            "home": home,
            "away": away,
            "pitch": pitch,
            "time": local,
            "code": match.code,
            "home_goals": result.get("home_goals", ""),
            "away_goals": result.get("away_goals", ""),
        }
    return values, pitch, local


async def handle_job(
    db: AsyncSession, clock: Clock, delivery: Delivery, args: dict[str, Any]
) -> int:
    """The `notify_followers` job: work out who and what, then notify."""
    kind = str(args["kind"])
    if "match_id" in args:
        match = await competitions.get_match(db, UUID(str(args["match_id"])))
        values, _, _ = await _match_values(db, match)
        link = {"match_id": str(match.id), "tournament_id": str(match.tournament_id)}
        values = {team: {**v, **link} for team, v in values.items()}  # the notification's link
        return await notify(
            db, clock, delivery, kind=kind, per_team=values, match_starts_at=match.starts_at
        )
    team_ids = [UUID(t) for t in str(args.get("team_ids", "")).split(",") if t]
    names: dict[UUID, str] = {}
    if "tournament_id" in args:
        tid = UUID(str(args["tournament_id"]))
        names = {e.team_id: e.name for e in await competitions.entries_of(db, tid)}
    extra = {k: v for k, v in args.items() if k not in ("kind", "team_ids", "tournament_id")}
    link = {"tournament_id": str(args["tournament_id"])} if "tournament_id" in args else {}
    per_team = {t: {"team": names.get(t, ""), **extra, **link} for t in team_ids}
    starts = args.get("starts_at")
    return await notify(
        db,
        clock,
        delivery,
        kind=kind,
        per_team=per_team,
        match_starts_at=datetime.fromisoformat(str(starts)) if starts else None,
    )


async def reminders(db: AsyncSession, clock: Clock, delivery: Delivery) -> int:
    """Every 5 minutes: "starts in 1 hour" and "in 15 minutes" to followers."""
    now = clock.now()
    windows = [
        (timedelta(minutes=55), timedelta(minutes=60)),
        (timedelta(minutes=10), timedelta(minutes=15)),
    ]
    sent = 0
    for match in await competitions.matches_starting(
        db, now + timedelta(minutes=10), now + timedelta(minutes=60)
    ):
        if any(now + a <= match.starts_at < now + b for a, b in windows):
            values, _, _ = await _match_values(db, match)
            sent += await notify(db, clock, delivery, kind="reminder", per_team=values)
    return sent
