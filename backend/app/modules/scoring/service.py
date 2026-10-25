"""Scoring: scorer passes, idempotent append-only events, live state, finish and results.

Ingestion rules (docs/06-live.md): only a pass for the pitch/match or tournament staff may
score, only while the match is live; `(match_id, client_seq)` makes retries idempotent;
events are validated by the sport module against the replayed live state; `seq` comes from
the locked match row; undo is a new event.
"""

import base64
import hashlib
import hmac
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events, jobs
from app.core.config import Settings
from app.core.db import transaction
from app.core.errors import (
    Conflict,
    MatchNotLive,
    NotAuthenticated,
    PassNotYetValid,
    PassRevoked,
    ScorerNotAssigned,
    ValidationFailed,
)
from app.core.ids import new_id
from app.core.live import LiveHub, envelope, match_channel, tournament_channel
from app.core.security import hash_token, new_token
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchOut, TournamentOut
from app.modules.rules import service as rules
from app.modules.scoring import repository
from app.modules.scoring.models import LiveState, MatchEvent, ScorerPass
from app.modules.scoring.schemas import (
    EventAccepted,
    EventIn,
    EventPad,
    EventPadButton,
    LiveScore,
    MatchStatus,
    PassCreate,
    PassOut,
    ResultIn,
    ScoredEvent,
    ScorerMatch,
    ScorerRosterPlayer,
    ScorerTeam,
    ScoringState,
)
from engine.model import EventLite, LiveStateLite
from engine.rules.config import RuleConfig
from engine.sports.base import InvalidEvent, SportModule
from engine.sports.football import FootballResult
from engine.sports.registry import UnknownSport, get_sport

PASS_HANDLER_KEY = "scoring.pitch_passes"


# --- scorer passes ---------------------------------------------------------------------------


def pass_token(settings: Settings, pass_id: UUID) -> str:
    """The QR token of a pass: derived from the server secret, stored only as a hash, so the
    organiser can reprint a pitch sheet without the token ever being kept."""
    digest = hmac.new(
        settings.jwt_secret.get_secret_value().encode(), f"pass:{pass_id}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _pass_out(settings: Settings, row: ScorerPass) -> PassOut:
    token = pass_token(settings, row.id)
    return PassOut(
        id=row.id,
        label=row.label,
        pitch_id=row.pitch_id,
        match_id=row.match_id,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        revoked=row.revoked_at is not None,
        token=token,
        scan_url=f"{settings.web_base_url}/score?pass={token}",
    )


async def _window(db: AsyncSession, tournament_id: UUID) -> tuple[datetime, datetime]:
    """The tournament days in its time zone, as a UTC validity window."""
    tournament = await competitions.tournament_window(db, tournament_id)
    zone = ZoneInfo(tournament.time_zone)
    if tournament.starts_on is None:
        raise ValidationFailed("the tournament has no dates")
    first = datetime.combine(tournament.starts_on, time(0, 0), zone)
    last = datetime.combine(tournament.ends_on or tournament.starts_on, time(0, 0), zone)
    return first, last + timedelta(days=1)


async def _new_pass(
    db: AsyncSession,
    clock: Clock,
    settings: Settings,
    tournament_id: UUID,
    label: str,
    *,
    pitch_id: UUID | None = None,
    match_id: UUID | None = None,
    valid_until: datetime | None = None,
    created_by: UUID | None = None,
) -> ScorerPass:
    valid_from, until = await _window(db, tournament_id)
    pass_id = new_id()
    row = ScorerPass(
        id=pass_id,
        tournament_id=tournament_id,
        pitch_id=pitch_id,
        match_id=match_id,
        label=label,
        token_hash=hash_token(pass_token(settings, pass_id)),
        valid_from=valid_from,
        valid_until=valid_until or until,
        created_by=created_by,
        created_at=clock.now(),
    )
    db.add(row)
    return row


def register(settings: Settings, clock: Clock) -> None:
    """Subscribe to domain events (called once per app at startup)."""

    async def on_published(db: AsyncSession, event: events.TournamentPublished) -> None:
        for number, pitch_id in enumerate(event.pitch_ids, start=1):
            await _new_pass(
                db, clock, settings, event.tournament_id, f"Pitch {number}", pitch_id=pitch_id
            )

    events.subscribe(events.TournamentPublished, on_published, key=PASS_HANDLER_KEY)


async def _require_manager(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> None:
    if not await competitions.manages(db, viewer, tournament_id):
        raise NotAuthenticated() if not viewer.is_member else ScorerNotAssigned()


async def list_passes(
    db: AsyncSession, settings: Settings, viewer: Viewer, tournament_id: UUID
) -> list[PassOut]:
    """The tournament's scorer passes with their QR tokens (organisers only)."""
    await _require_manager(db, viewer, tournament_id)
    return [_pass_out(settings, p) for p in await repository.passes_of(db, tournament_id)]


async def create_pass(
    db: AsyncSession,
    clock: Clock,
    settings: Settings,
    viewer: Viewer,
    tournament_id: UUID,
    data: PassCreate,
) -> PassOut:
    """A pass for one pitch or one match (a lost phone gets a new one)."""
    await _require_manager(db, viewer, tournament_id)
    if (data.pitch_id is None) == (data.match_id is None):
        raise ValidationFailed("a pass is for one pitch or one match")
    async with transaction(db):
        row = await _new_pass(
            db,
            clock,
            settings,
            tournament_id,
            data.label,
            pitch_id=data.pitch_id,
            match_id=data.match_id,
            valid_until=data.valid_until,
            created_by=viewer.user_id,
        )
    return _pass_out(settings, row)


async def revoke_pass(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID, pass_id: UUID
) -> None:
    await _require_manager(db, viewer, tournament_id)
    async with transaction(db):
        row = await db.get(ScorerPass, pass_id)
        if row is None or row.tournament_id != tournament_id:
            raise ScorerNotAssigned()
        row.revoked_at = row.revoked_at or clock.now()


async def _resolve_pass(db: AsyncSession, token: str, now: datetime) -> ScorerPass:
    row = await repository.pass_by_hash(db, hash_token(token))
    if row is None:
        raise NotAuthenticated("unknown scorer pass")
    if row.revoked_at is None and now < row.valid_from:
        # Passes work on the tournament days only (docs/09-security-privacy.md).
        raise PassNotYetValid(f"the pass works from {row.valid_from.isoformat()}")
    if row.revoked_at is not None or now >= row.valid_until:
        raise PassRevoked()
    return row


async def _authorise(
    db: AsyncSession, clock: Clock, viewer: Viewer, match: MatchOut
) -> tuple[UUID | None, UUID | None]:
    """(user id, pass id) of whoever may score this match; raises otherwise."""
    if viewer.pass_token:
        scorer = await _resolve_pass(db, viewer.pass_token, clock.now())
        in_scope = scorer.match_id == match.id or (
            scorer.pitch_id is not None and scorer.pitch_id == match.pitch_id
        )
        if scorer.tournament_id != match.tournament_id or not in_scope:
            raise ScorerNotAssigned()
        return None, scorer.id
    if await competitions.manages(db, viewer, match.tournament_id):
        return viewer.user_id, None
    if not viewer.is_member:
        raise NotAuthenticated()
    raise ScorerNotAssigned()


# --- live state ------------------------------------------------------------------------------


def _lite(row: MatchEvent) -> EventLite:
    payload = dict(row.payload)
    if row.undoes_seq is not None:
        payload["undoes_seq"] = row.undoes_seq
    return EventLite(
        seq=row.seq,
        type=row.type,
        team=str(row.team_id) if row.team_id else None,
        player=str(row.player_id) if row.player_id else None,
        payload=payload,
    )


async def _context(db: AsyncSession, match: MatchOut) -> tuple[RuleConfig, str, str]:
    if match.home_team_id is None or match.away_team_id is None:
        raise MatchNotLive("the teams of this match are not known yet")
    confirmed = await rules.confirmed_config(db, match.tournament_id)
    return (
        RuleConfig.model_validate(confirmed.config),
        str(match.home_team_id),
        str(match.away_team_id),
    )


def _score(state: LiveStateLite) -> LiveScore:
    return LiveScore(
        home_goals=state.home_goals,
        away_goals=state.away_goals,
        period=state.period,
        finished=state.finished,
        home_shootout=state.home_shootout,
        away_shootout=state.away_shootout,
    )


async def _save_state(
    db: AsyncSession,
    clock: Clock,
    match_id: UUID,
    seq: int,
    state: LiveStateLite,
    moments: list[str],
) -> None:
    data: dict[str, Any] = {
        **_score(state).model_dump(),
        "sent_off": sorted(state.sent_off),
        "moments": moments,
    }
    row = await repository.live_state(db, match_id)
    if row is None:
        db.add(LiveState(match_id=match_id, seq=seq, state=data, updated_at=clock.now()))
    else:
        row.seq, row.state, row.updated_at = seq, data, clock.now()


# --- match flow ------------------------------------------------------------------------------


async def start(db: AsyncSession, clock: Clock, viewer: Viewer, match_id: UUID) -> MatchStatus:
    """Kick-off: the match goes live (scorer pass for the pitch, or staff)."""
    match = await competitions.get_match(db, match_id)
    await _authorise(db, clock, viewer, match)
    await _context(db, match)
    if match.status not in ("scheduled", "postponed", "live"):
        raise MatchNotLive(f"the match is {match.status}")
    async with transaction(db):
        await competitions.set_match_status(db, match_id, "live")
        if await repository.live_state(db, match_id) is None:
            empty = LiveStateLite(str(match.home_team_id), str(match.away_team_id), 0, 0, 0)
            await _save_state(db, clock, match_id, 0, empty, ["match_start"])
        await jobs.defer(db, "notify_followers", match_id=match_id, kind="match_start")
    return MatchStatus(match_id=match_id, status="live")


async def _publish(
    live: LiveHub | None,
    clock: Clock,
    match: MatchOut,
    type_: str,
    seq: int | None,
    data: dict[str, Any],
) -> None:
    """Fan the message out after commit: full detail to the match, the score to the tournament."""
    if live is None:
        return
    message = envelope(type_, clock.now(), data, match_id=match.id, seq=seq)
    await live.publish(match_channel(match.id), message)
    score = {k: v for k, v in data.items() if k in ("score", "result")}
    await live.publish(tournament_channel(match.tournament_id), {**message, "data": score})


async def post_event(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    match_id: UUID,
    data: EventIn,
    live: LiveHub | None = None,
) -> EventAccepted:
    """Append one event; a retry with the same `client_seq` returns the original."""
    match = await competitions.get_match(db, match_id)
    user_id, pass_id = await _authorise(db, clock, viewer, match)
    config, home, away = await _context(db, match)
    async with transaction(db):
        match = await competitions.lock_match(db, match_id)  # one writer per match at a time
        existing = await repository.event_by_client_seq(db, match_id, data.client_seq)
        rows = await repository.events_of(db, match_id)
        knockout = match.stage != "group"
        if existing is not None:
            state = _sport(config).replay(
                home, away, [_lite(r) for r in rows], config, knockout=knockout
            )
            return EventAccepted(seq=existing.seq, duplicate=True, live=_score(state), moments=[])
        # Organisers correct a finished match with new events (an undo, a missed goal);
        # scorer passes only score live matches.
        correcting = match.status == "finished" and user_id is not None
        if match.status != "live" and not (correcting and match.data_level == "events"):
            raise MatchNotLive(f"the match is {match.status}")
        latest = await repository.max_client_seq(db, match_id)
        if data.client_seq < latest:
            raise Conflict(f"events must arrive in order; expected client_seq {latest + 1}")
        before = _sport(config).replay(
            home, away, [_lite(r) for r in rows], config, knockout=knockout
        )
        undoes = data.payload.get("undoes_seq") if data.type == "undo" else None
        candidate = EventLite(
            seq=match.last_seq + 1,
            type=data.type,
            team=str(data.team_id) if data.team_id else None,
            player=str(data.player_id) if data.player_id else None,
            payload=data.payload,
        )
        try:
            _sport(config).validate_event(before, candidate, config)
        except InvalidEvent as exc:
            raise ValidationFailed(f"{exc.code}: {exc}") from exc
        seq = await competitions.next_event_seq(db, match_id)
        row = MatchEvent(
            id=new_id(),
            match_id=match_id,
            seq=seq,
            client_seq=data.client_seq,
            type=data.type,
            payload={k: v for k, v in data.payload.items() if k != "undoes_seq"},
            team_id=data.team_id,
            player_id=data.player_id,
            period=before.period or None,
            clock=data.clock,
            entered_by_user_id=user_id,
            entered_by_pass_id=pass_id,
            created_at=clock.now(),
            undoes_seq=undoes if isinstance(undoes, int) else None,
        )
        db.add(row)
        after = _sport(config).replay(
            home, away, [*(_lite(r) for r in rows), _lite(row)], config, knockout=knockout
        )
        moments: list[str] = []
        if correcting:
            await _save_state(db, clock, match_id, seq, after, moments)
            corrected = _result_json(_sport(config).result_of(after, config))
            await competitions.record_result(db, match_id, corrected)
            await jobs.defer(db, "recalc_tournament", tournament_id=match.tournament_id)
        else:
            moments = (
                []
                if data.type == "undo"
                else _sport(config).detect_moments(before, after, candidate, config)
            )
            await _save_state(db, clock, match_id, seq, after, moments)
            await jobs.defer(db, "recalc_live", match_id=match_id, seq=seq)
            if moments:
                await jobs.defer(
                    db, "write_commentary", match_id=match_id, seq=seq, moments=",".join(moments)
                )
    message: dict[str, Any] = {
        "event": data.type,
        "team_id": str(data.team_id) if data.team_id else None,
        "score": _score(after).model_dump(),
        "moments": moments,
    }
    if correcting:
        message["result"] = corrected
    if data.type == "undo" or correcting:
        await _publish(live, clock, match, "correction", seq, {**message, "undone_seq": undoes})
    else:
        await _publish(live, clock, match, "event", seq, message)
    return EventAccepted(seq=seq, duplicate=False, live=_score(after), moments=moments)


async def undo(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    match_id: UUID,
    seq: int,
    client_seq: int,
    live: LiveHub | None = None,
) -> EventAccepted:
    """Undo an earlier event by appending an undo event."""
    return await post_event(
        db,
        clock,
        viewer,
        match_id,
        EventIn(client_seq=client_seq, type="undo", payload={"undoes_seq": seq}),
        live,
    )


def _sport(config: RuleConfig) -> SportModule:
    """The sport module of the tournament's confirmed rules (football, futsal)."""
    return get_sport(config.sport)


def _result_json(result: object) -> dict[str, object]:
    if not isinstance(result, FootballResult):  # every sport of this release scores goals
        raise TypeError(f"no stored form for {type(result).__name__}")
    return {
        "home_goals": result.home_goals,
        "away_goals": result.away_goals,
        "decided_by": result.decided_by,
        "home_penalties": result.home_penalties,
        "away_penalties": result.away_penalties,
    }


async def finish(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    match_id: UUID,
    home_goals: int,
    away_goals: int,
    live: LiveHub | None = None,
) -> MatchStatus:
    """Confirm the final score shown on the pad; the match is finished."""
    match = await competitions.get_match(db, match_id)
    await _authorise(db, clock, viewer, match)
    config, home, away = await _context(db, match)
    if match.status != "live":
        raise MatchNotLive(f"the match is {match.status}")
    rows = await repository.events_of(db, match_id)
    state = _sport(config).replay(
        home, away, [_lite(r) for r in rows], config, knockout=match.stage != "group"
    )
    if (state.home_goals, state.away_goals) != (home_goals, away_goals):
        raise Conflict(f"the live score is {state.home_goals}-{state.away_goals}")
    try:
        result = _sport(config).result_of(state, config)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    async with transaction(db):
        await competitions.record_result(db, match_id, _result_json(result))
        await jobs.defer(db, "recalc_tournament", tournament_id=match.tournament_id)
        await jobs.defer(db, "notify_followers", kind="result", match_id=match_id)
        last = rows[-1].seq if rows else 0
        await jobs.defer(db, "write_commentary", match_id=match_id, seq=last, moments="full_time")
    await _publish(live, clock, match, "match_finished", None, {"result": _result_json(result)})
    return MatchStatus(match_id=match_id, status="finished", result=_result_json(result))


async def enter_result(
    db: AsyncSession, clock: Clock, viewer: Viewer, match_id: UUID, data: ResultIn
) -> MatchStatus:
    """Results-only entry for pitches without a volunteer (organiser, two taps)."""
    match = await competitions.get_match(db, match_id)
    await _authorise(db, clock, viewer, match)
    await _context(db, match)
    try:
        result = FootballResult(
            data.home_goals,
            data.away_goals,
            data.decided_by,
            data.home_penalties,
            data.away_penalties,
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    async with transaction(db):
        await competitions.record_result(db, match_id, _result_json(result), data_level="results")
        await jobs.defer(db, "recalc_tournament", tournament_id=match.tournament_id)
        await jobs.defer(db, "notify_followers", kind="result", match_id=match_id)
    return MatchStatus(match_id=match_id, status="finished", result=_result_json(result))


def event_types(sport: str) -> list[str]:
    """The events a scorer pad may send for this sport."""
    try:
        return sorted(get_sport(sport).event_types)
    except UnknownSport:
        raise ValidationFailed(f"no event pad for '{sport}' yet") from None


async def live_snapshot(db: AsyncSession, match_id: UUID) -> tuple[int, LiveScore] | None:
    """(last seq, score) of a match that has started; None before kick-off."""
    row = await repository.live_state(db, match_id)
    if row is None:
        return None
    return row.seq, LiveScore.model_validate(row.state)


async def timeline(db: AsyncSession, match_id: UUID, since_seq: int = 0) -> list[dict[str, Any]]:
    """Public match events after `since_seq`: undone events marked, never player ids
    (names are added only for players a viewer may see, by the reading module)."""
    rows = await repository.events_of(db, match_id)
    undone = {r.undoes_seq for r in rows if r.undoes_seq is not None}
    return [
        {
            "seq": r.seq,
            "type": r.type,
            "team_id": str(r.team_id) if r.team_id else None,
            "period": r.period,
            "clock": r.clock,
            "undone": r.seq in undone,
            "payload": {k: v for k, v in r.payload.items() if k != "player"},
        }
        for r in rows
        if r.seq > since_seq
    ]


async def scorers(db: AsyncSession, match_id: UUID) -> dict[int, UUID]:
    """Player id of each event that names one (seq -> player). For the fact builder only,
    which keeps a name only when the visibility filter allows it; never serve these ids."""
    return {r.seq: r.player_id for r in await repository.events_of(db, match_id) if r.player_id}


PASS_RETENTION = timedelta(days=30)


async def purge_passes(db: AsyncSession, clock: Clock) -> int:
    """Retention (docs/09): scorer passes are deleted 30 days after the tournament ends."""
    removed = 0
    today = clock.now().date()
    async with transaction(db):
        for tournament_id in await repository.pass_tournaments(db):
            window = await competitions.tournament_window(db, tournament_id)
            if window.ends_on is not None and window.ends_on + PASS_RETENTION < today:
                removed += await repository.delete_passes(
                    db, tournament_id, lambda: hash_token(new_token()), clock.now()
                )
    return removed


# --- the scoring console (pad, my matches, state) --------------------------------------------

_B = EventPadButton
_FOOTBALL_PAD = [
    _B(id="period_start", type="period_start", label="Start period", group="control", team=False),
    _B(id="period_end", type="period_end", label="End period", group="control", team=False),
    _B(
        id="goal",
        type="goal",
        label="Goal",
        group="score",
        team=True,
        player="optional",
        player_prompt="Who scored?",
        points=1,
    ),
    _B(
        id="penalty_goal",
        type="goal",
        label="Penalty goal",
        group="score",
        team=True,
        player="optional",
        player_prompt="Who scored?",
        points=1,
        payload={"kind": "penalty"},
    ),
    _B(
        id="own_goal",
        type="goal",
        label="Own goal",
        group="score",
        team=True,
        player="optional",
        player_prompt="Who put it in their own net?",
        points=1,
        payload={"kind": "own_goal"},
    ),
    _B(
        id="penalty_missed",
        type="penalty_missed",
        label="Penalty missed",
        group="play",
        team=True,
        player="optional",
        player_prompt="Who took it?",
    ),
    _B(
        id="yellow_card",
        type="yellow_card",
        label="Yellow card",
        group="discipline",
        team=True,
        player="optional",
        player_prompt="Who was booked?",
    ),
    _B(
        id="second_yellow",
        type="second_yellow",
        label="Second yellow",
        group="discipline",
        team=True,
        player="optional",
        player_prompt="Who was sent off?",
    ),
    _B(
        id="red_card",
        type="red_card",
        label="Red card",
        group="discipline",
        team=True,
        player="optional",
        player_prompt="Who was sent off?",
    ),
    _B(
        id="substitution",
        type="substitution",
        label="Substitution",
        group="play",
        team=True,
        player="optional",
        player_prompt="Who came on?",
    ),
    _B(
        id="shootout_scored",
        type="shootout_kick",
        label="Shootout: scored",
        group="score",
        team=True,
        player="optional",
        payload={"scored": True},
        knockout_only=True,
    ),
    _B(
        id="shootout_missed",
        type="shootout_kick",
        label="Shootout: missed",
        group="score",
        team=True,
        player="optional",
        payload={"scored": False},
        knockout_only=True,
    ),
]
_FUTSAL_EXTRA = [
    _B(
        id="foul",
        type="foul",
        label="Foul",
        group="discipline",
        team=True,
        player="optional",
        player_prompt="Who fouled?",
    ),
    _B(id="timeout", type="timeout", label="Timeout", group="control", team=True),
]


def event_pad(sport: str) -> EventPad:
    """The scorer pad for this sport: buttons, labels and what each one posts."""
    types = event_types(sport)
    buttons = _FOOTBALL_PAD + (_FUTSAL_EXTRA if sport == "futsal" else [])
    return EventPad(
        sport=sport,
        clock=True,
        periods=["1st half", "2nd half"],
        score_label="Goals",
        event_types=types,
        buttons=[b for b in buttons if b.type in types],
    )


async def _names(db: AsyncSession, tournament_id: UUID) -> dict[UUID, ScorerTeam]:
    return {
        e.team_id: ScorerTeam(id=e.team_id, name=e.name, short_name=e.short_name)
        for e in await competitions.entries_of(db, tournament_id)
    }


async def _matches_for(
    db: AsyncSession, tournament: TournamentOut, keep: Callable[[MatchOut], bool]
) -> list[ScorerMatch]:
    teams = await _names(db, tournament.id)
    pitches = {p.id: p.name for p in await competitions.pitches_of(db, tournament.id)}
    out = []
    for m in await competitions.list_matches(db, tournament.id):
        if not keep(m):
            continue
        rows = await repository.events_of(db, m.id)
        out.append(
            ScorerMatch(
                match_id=m.id,
                code=m.code,
                starts_at=m.starts_at,
                status=m.status,
                home_team_id=m.home_team_id,
                away_team_id=m.away_team_id,
                tournament_id=tournament.id,
                tournament_name=tournament.name,
                sport=tournament.sport,
                stage=m.stage,
                pitch=pitches.get(m.pitch_id) if m.pitch_id else None,
                home=teams.get(m.home_team_id) if m.home_team_id else None,
                away=teams.get(m.away_team_id) if m.away_team_id else None,
                data_level=m.data_level,
                events_recorded=len(rows),
                last_event_at=rows[-1].created_at if rows else None,
            )
        )
    return out


async def my_matches(db: AsyncSession, clock: Clock, viewer: Viewer) -> list[ScorerMatch]:
    """A scorer pass: today's matches of its pitch or match. An organiser's account: every
    match of the tournaments they run that are not over yet. Kick-off order."""
    if not viewer.pass_token:
        if not viewer.is_member:
            raise NotAuthenticated("open the pitch QR code")
        out: list[ScorerMatch] = []
        for t in await competitions.managed_tournaments(db, viewer):
            if t.status in ("upcoming", "active"):
                out += await _matches_for(db, t, lambda m: True)
        return sorted(out, key=lambda s: s.starts_at)
    scorer = await _resolve_pass(db, viewer.pass_token, clock.now())
    tournament = await competitions.tournament_window(db, scorer.tournament_id)
    zone = ZoneInfo(tournament.time_zone)
    today = clock.now().astimezone(zone).date()

    def mine(m: MatchOut) -> bool:
        in_scope = m.id == scorer.match_id or (
            scorer.pitch_id is not None and m.pitch_id == scorer.pitch_id
        )
        return in_scope and m.starts_at.astimezone(zone).date() == today

    return await _matches_for(db, tournament, mine)


async def scoring_state(
    db: AsyncSession, clock: Clock, viewer: Viewer, match_id: UUID
) -> ScoringState:
    """The console's view of a match: score, period, rosters and every event with its
    server `seq` (for undo) and `client_seq`."""
    match = await competitions.get_match(db, match_id)
    user_id, _ = await _authorise(db, clock, viewer, match)
    config, home, away = await _context(db, match)
    assert match.home_team_id is not None and match.away_team_id is not None  # _context
    tournament = await competitions.tournament_window(db, match.tournament_id)
    rows = await repository.events_of(db, match_id)
    sport = _sport(config)
    state = sport.replay(
        home, away, [_lite(r) for r in rows], config, knockout=match.stage != "group"
    )
    undone = {r.undoes_seq for r in rows if r.undoes_seq is not None}
    period_marks = [
        r for r in rows if r.type in ("period_start", "period_end") and r.seq not in undone
    ]
    # Every sport module parses its own match rules (periods, minutes); not in the protocol.
    match_rules = getattr(sport, "match_rules")(config.match)  # noqa: B009
    teams = await _names(db, match.tournament_id)
    pitches = {p.id: p.name for p in await competitions.pitches_of(db, match.tournament_id)}
    # Organisers see their whole roster; a pass sees public players only (docs/09).
    reader = Viewer(user_id=user_id) if user_id else Viewer()
    rosters = {
        side: [
            ScorerRosterPlayer(id=p.id, display_name=p.display_name, shirt_number=p.shirt_number)
            for p in await competitions.list_players(db, reader, team_id)
        ]
        for side, team_id in (("home", match.home_team_id), ("away", match.away_team_id))
    }
    return ScoringState(
        match_id=match.id,
        tournament_id=match.tournament_id,
        sport=tournament.sport,
        code=match.code,
        stage=match.stage,
        status=match.status,
        data_level=match.data_level,
        starts_at=match.starts_at,
        pitch=pitches.get(match.pitch_id) if match.pitch_id else None,
        home=teams[match.home_team_id],
        away=teams[match.away_team_id],
        score=_score(state),
        period=state.period,
        periods=match_rules.periods,
        period_minutes=getattr(match_rules, "period_minutes", None),
        between_periods=bool(period_marks)
        and period_marks[-1].type == "period_end"
        and not state.finished,
        home_roster=rosters["home"],
        away_roster=rosters["away"],
        events=[
            ScoredEvent(
                seq=r.seq,
                client_seq=r.client_seq,
                type=r.type,
                team_id=r.team_id,
                player_id=r.player_id,
                period=r.period,
                clock=r.clock,
                payload=r.payload,
                undone=r.seq in undone,
                undoes_seq=r.undoes_seq,
                created_at=r.created_at,
            )
            for r in reversed(rows)
        ],
        last_client_seq=await repository.max_client_seq(db, match_id),
        role="organiser" if user_id else "scorer",
        server_time=clock.now(),
    )
