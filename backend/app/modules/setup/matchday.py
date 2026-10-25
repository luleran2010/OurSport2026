"""Match day for organisers: the console and engine rescheduling (docs/06, docs/12 §6).

A change is previewed first (the engine moves the fewest unstarted matches), then
confirmed: matches move, walkovers are recorded, followers of affected teams are notified.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.db import transaction
from app.core.errors import NotFound, ScheduleInfeasible, ValidationFailed
from app.core.ids import new_id
from app.core.live import LiveHub, envelope, tournament_channel
from app.core.time import Clock, isoformat_z
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import MatchMove, MatchOut, ScheduleUpdate
from app.modules.rules import service as rules
from app.modules.setup import repository, review
from app.modules.setup.models import SchedulePlanRecord
from app.modules.setup.schemas import (
    ChangeConfirmed,
    ChangePreview,
    ConsoleMatch,
    ConsoleOut,
    ConsolePitch,
    MovedMatch,
    ScheduleChangeIn,
)
from engine.rules.config import RuleConfig
from engine.rules.schedule_policy import SchedulePolicy
from engine.schedule import (
    MatchPostponed,
    PitchClosed,
    PitchDelay,
    ScheduleChange,
    TeamWithdrawn,
    reschedule,
)
from engine.schedule import ScheduleInfeasible as EngineInfeasible
from engine.sports.football import FootballResult
from engine.sports.registry import get_sport

UNSCORED_GRACE = timedelta(minutes=10)
_REASONS = {
    "delay": "delay",
    "pitch_closed": "manual",
    "postponed": "manual",
    "withdrawn": "withdrawal",
}


async def _manager(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> None:
    if not await competitions.manages(db, viewer, tournament_id):
        raise NotFound()


async def _published(db: AsyncSession, tournament_id: UUID) -> SchedulePlanRecord:
    plan = await repository.published_plan(db, tournament_id)
    if plan is None or "engine" not in plan.plan:
        raise NotFound("no published schedule")
    return plan


def _engine_change(change: ScheduleChangeIn, keys: dict[str, str]) -> ScheduleChange:
    if change.kind == "delay" and change.pitch and change.minutes:
        return PitchDelay(change.pitch, change.minutes)
    if change.kind == "pitch_closed" and change.pitch:
        return PitchClosed(change.pitch)
    if change.kind == "postponed" and change.match_code:
        return MatchPostponed(change.match_code, change.not_before)
    if change.kind == "withdrawn" and change.team_id:
        key = next((k for k, v in keys.items() if v == str(change.team_id)), None)
        if key is None:
            raise ValidationFailed("that team does not play in this tournament")
        return TeamWithdrawn(key)
    raise ValidationFailed(f"incomplete '{change.kind}' change")


async def preview_change(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID, change: ScheduleChangeIn
) -> ChangePreview:
    """What the engine would move; nothing changes until it is confirmed."""
    await _manager(db, viewer, tournament_id)
    current = await _published(db, tournament_id)
    policy = SchedulePolicy.model_validate(current.policy)
    plan = review.engine_plan_from(current.plan["engine"], policy)
    keys: dict[str, str] = current.plan.get("team_ids", {})
    try:
        new_plan = reschedule(
            plan,
            frozen_until=isoformat_z(clock.now()),
            changes=[_engine_change(change, keys)],
            policy=policy,
        )
    except EngineInfeasible as exc:
        raise ScheduleInfeasible(str(exc)) from exc
    before = {m.code: m for m in plan.matches}
    after = {m.code: m for m in new_plan.matches}
    moved = [
        MovedMatch(
            code=code,
            starts_at_before=before[code].starts_at,
            starts_at_after=after[code].starts_at,
            pitch_before=before[code].pitch,
            pitch_after=after[code].pitch,
        )
        for code in new_plan.moved
    ]
    new_walkovers = [c for c in new_plan.walkovers if c not in plan.walkovers]
    affected: set[str] = set()
    for code in [*new_plan.moved, *new_walkovers]:
        m = before[code]
        affected |= {keys[k] for k in (m.home, m.away) if k and k in keys}
    plan_id = new_id()
    async with transaction(db):
        db.add(
            SchedulePlanRecord(
                id=plan_id,
                tournament_id=tournament_id,
                version=await repository.next_plan_version(db, tournament_id),
                based_on_draw_id=current.based_on_draw_id,
                plan={
                    **current.plan,
                    "engine": review.engine_plan_json(new_plan),
                    "change": change.model_dump(mode="json"),
                    "moved": list(new_plan.moved),
                    "new_walkovers": new_walkovers,
                    "affected": sorted(affected),
                },
                policy=current.policy,
                quality={"hard_violations": new_plan.quality.hard_violations},
                reason=_REASONS[change.kind],
                status="proposed",
                created_at=clock.now(),
            )
        )
    return ChangePreview(
        plan_id=plan_id,
        moved=moved,
        walkovers=new_walkovers,
        affected_team_ids=sorted(UUID(t) for t in affected),
    )


async def confirm_change(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    tournament_id: UUID,
    plan_id: UUID,
    live: LiveHub | None = None,
) -> ChangeConfirmed:
    """Publish a previewed reschedule and tell the followers of every affected team."""
    await _manager(db, viewer, tournament_id)
    proposal = await db.get(SchedulePlanRecord, plan_id)
    if proposal is None or proposal.tournament_id != tournament_id or proposal.status != "proposed":
        raise NotFound()
    current = await _published(db, tournament_id)
    policy = SchedulePolicy.model_validate(proposal.policy)
    new_plan = review.engine_plan_from(proposal.plan["engine"], policy)
    by_code = {m.code: m for m in new_plan.matches}
    keys: dict[str, str] = proposal.plan.get("team_ids", {})
    config = RuleConfig.model_validate((await rules.confirmed_config(db, tournament_id)).config)
    old = {m.code: m for m in review.engine_plan_from(current.plan["engine"], policy).matches}
    walkovers: dict[str, dict[str, object]] = {}
    withdrawn: list[UUID] = []
    change = proposal.plan.get("change", {})
    if change.get("kind") == "withdrawn" and change.get("team_id"):
        withdrawn.append(UUID(change["team_id"]))
        gone = next(k for k, v in keys.items() if v == change["team_id"])
        for code in proposal.plan.get("new_walkovers", []):
            m = old[code]
            result = get_sport(config.sport).walkover_result(
                config, "away" if m.home == gone else "home"
            )
            assert isinstance(result, FootballResult)  # goal-based sports
            walkovers[code] = {
                "home_goals": result.home_goals,
                "away_goals": result.away_goals,
                "decided_by": "regulation",
                "walkover": True,
            }
    update_ = ScheduleUpdate(
        moves=[
            MatchMove(
                code=c,
                starts_at=datetime.fromisoformat(by_code[c].starts_at),
                pitch=by_code[c].pitch,
            )
            for c in proposal.plan.get("moved", [])
        ],
        walkovers=walkovers,
        withdrawn_team_ids=withdrawn,
    )
    async with transaction(db):
        version = await competitions.apply_schedule(db, clock, tournament_id, update_)
        current.status = "superseded"
        proposal.status = "published"
        affected = proposal.plan.get("affected", [])
        if affected:
            await jobs.defer(
                db,
                "notify_followers",
                kind="schedule_change",
                tournament_id=tournament_id,
                team_ids=",".join(affected),
            )
        await jobs.defer(db, "recalc_tournament", tournament_id=tournament_id)
    if live is not None:
        changed = [
            {"code": m.code, "starts_at": m.starts_at.isoformat(), "pitch": m.pitch}
            for m in update_.moves
        ]
        message = envelope(
            "schedule", clock.now(), {"matches": changed, "walkovers": list(walkovers)}
        )
        await live.publish(tournament_channel(tournament_id), message)
    return ChangeConfirmed(
        schedule_version=version, moved=len(update_.moves), walkovers=len(walkovers)
    )


def _console_match(m: MatchOut) -> ConsoleMatch:
    return ConsoleMatch(
        code=m.code,
        status=m.status,
        starts_at=isoformat_z(m.starts_at),
        home_team_id=m.home_team_id,
        away_team_id=m.away_team_id,
    )


async def console(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID, live: LiveHub | None = None
) -> ConsoleOut:
    """All pitches now and next, how late each pitch is, and finished matches nobody scored."""
    await _manager(db, viewer, tournament_id)
    now = clock.now()
    plan = await repository.published_plan(db, tournament_id)
    match_minutes = int(plan.policy.get("match_minutes", 50)) if plan else 50
    matches = await competitions.list_matches(db, tournament_id)
    pitches = await competitions.pitches_of(db, tournament_id)
    out = []
    for pitch in pitches:
        on_pitch = [m for m in matches if m.pitch_id == pitch.id]
        live_match = next((m for m in on_pitch if m.status == "live"), None)
        upcoming = next((m for m in on_pitch if m.status == "scheduled"), None)
        late = 0
        if upcoming is not None and upcoming.starts_at < now and live_match is None:
            late = int((now - upcoming.starts_at).total_seconds() // 60)
        out.append(
            ConsolePitch(
                pitch=pitch.name,
                now=_console_match(live_match) if live_match else None,
                next=_console_match(upcoming) if upcoming else None,
                delay_minutes=late,
                viewers=await live.viewers(live_match.id) if live and live_match else 0,
            )
        )
    unscored = [
        m.code
        for m in matches
        if m.status in ("scheduled", "live")
        and m.starts_at.astimezone(UTC) + timedelta(minutes=match_minutes) + UNSCORED_GRACE < now
    ]
    return ConsoleOut(pitches=out, unscored=unscored)


async def announce(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID, text: str, live: LiveHub
) -> None:
    """Send an organiser announcement to everyone following the tournament live."""
    await _manager(db, viewer, tournament_id)
    await live.publish(
        tournament_channel(tournament_id), envelope("announcement", clock.now(), {"text": text})
    )
