"""Automatic setup: intake → extraction → review → draw and schedule → publish
(docs/12-tournament-setup.md). AI proposes, the engine decides, the organiser publishes.
"""

import secrets
from datetime import timedelta
from uuid import UUID

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.db import transaction
from app.core.documents import UnsupportedDocument, extract
from app.core.errors import (
    Conflict,
    NotFound,
    OpenQuestionsRemaining,
    SetupNotReady,
    StaleVersion,
    ValidationFailed,
)
from app.core.errors import ScheduleInfeasible as ScheduleInfeasibleError
from app.core.ids import new_id
from app.core.live import LiveHub, envelope, tournament_channel
from app.core.llm import LLMGateway
from app.core.redaction import redact
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import (
    FilmingPolicy,
    MatchEntry,
    TeamEntry,
    TournamentCreate,
    TournamentOut,
    TournamentStructure,
)
from app.modules.rules import service as rules_service
from app.modules.setup import repository, review
from app.modules.setup.extraction import IntakeText, TournamentFacts, build_draft
from app.modules.setup.models import (
    DrawRecord,
    IntakeFile,
    SchedulePlanRecord,
    SetupDraft,
    SetupSession,
)
from app.modules.setup.schemas import (
    Answer,
    Assumption,
    DraftOut,
    DrawOut,
    DrawReveal,
    FileKind,
    IntakeFileOut,
    MoveMatch,
    OpenQuestion,
    Published,
    RevealStep,
    ScheduleOut,
    SetupDraftData,
    SetupOut,
    SetupStart,
    SetupSummary,
    SetupTournament,
)
from engine.rules.presets import CATALOGUE_VERSION

log = structlog.get_logger("setup")


async def _owned(db: AsyncSession, viewer: Viewer, session_id: UUID) -> SetupSession:
    session = await repository.session_by_id(db, session_id)
    if session is None or not await competitions.manages(db, viewer, session.tournament_id):
        raise NotFound()
    return session


def _file_out(f: IntakeFile) -> IntakeFileOut:
    return IntakeFileOut(
        id=f.id,
        kind=f.kind,  # type: ignore[arg-type]  # CHECK constraint keeps it valid
        mime=f.mime,
        characters=len(f.text_extracted),
        redaction_report=f.redaction_report,
    )


def _tournament(t: TournamentOut) -> SetupTournament:
    return SetupTournament(
        name=t.name,
        organisation_id=t.organisation_id,
        sport=t.sport,
        age_group=t.age_group,
        is_junior=t.is_junior,
        time_zone=t.time_zone,
        starts_on=t.starts_on,
        ends_on=t.ends_on,
    )


async def list_setups(db: AsyncSession, viewer: Viewer) -> list[SetupSummary]:
    """The setups of the tournaments I own or organise (drafts and published), newest first."""
    tournaments = {t.id: t for t in await competitions.managed_tournaments(db, viewer)}
    sessions = await repository.sessions_of_tournaments(db, list(tournaments))
    return [
        SetupSummary(
            id=s.id,
            tournament_id=s.tournament_id,
            status=s.status,
            tournament=_tournament(tournaments[s.tournament_id]),
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


async def _out(db: AsyncSession, session: SetupSession) -> SetupOut:
    draft = await repository.latest_draft(db, session.id)
    managed = await competitions.tournament_window(db, session.tournament_id)
    draw = await repository.latest_draw(db, session.tournament_id)
    plan = await repository.latest_plan(db, session.tournament_id)
    return SetupOut(
        draw=DrawOut.model_validate(draw.explanation) if draw else None,
        schedule=ScheduleOut(matches=plan.plan["matches"], quality=plan.quality) if plan else None,
        id=session.id,
        tournament_id=session.tournament_id,
        tournament=_tournament(managed),
        status=session.status,
        failure_reason=session.failure_reason,
        files=[_file_out(f) for f in await repository.files_of(db, session.id)],
        draft=None
        if draft is None
        else DraftOut(
            version=draft.version,
            draft=SetupDraftData.model_validate(draft.draft),
            assumptions=[Assumption.model_validate(a) for a in draft.assumptions],
            open_questions=[OpenQuestion.model_validate(q) for q in draft.open_questions],
        ),
    )


async def start(db: AsyncSession, clock: Clock, viewer: Viewer, data: SetupStart) -> SetupOut:
    """Create the draft tournament and its setup session."""
    assert viewer.user_id is not None
    tournament = await competitions.create_tournament(
        db,
        clock,
        viewer.user_id,
        TournamentCreate(
            organisation_id=data.organisation_id,
            name=data.name,
            sport=data.sport,
            age_group=data.age_group,  # type: ignore[arg-type]  # validated by TournamentCreate
            time_zone=data.time_zone,
            starts_on=data.starts_on,
            ends_on=data.ends_on,
            series_id=data.series_id,
        ),
    )
    now = clock.now()
    async with transaction(db):
        session = SetupSession(
            id=new_id(),
            tournament_id=tournament.id,
            status="intake",
            organiser_language=data.organiser_language,
            created_by=viewer.user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(session)
    return await _out(db, session)


async def add_file(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    session_id: UUID,
    *,
    kind: FileKind,
    filename: str,
    mime: str,
    data: bytes,
) -> IntakeFileOut:
    """Read and redact an upload; only redacted text (and photos) is kept for extraction.
    The organisation must have accepted the processing terms (docs/13 §7)."""
    session = await _owned(db, viewer, session_id)
    await competitions.require_processing_agreement(db, session.tournament_id)
    try:
        document = extract(data, filename, mime)
    except UnsupportedDocument as exc:
        raise ValidationFailed(str(exc)) from exc
    redacted = redact(document.text)
    counts = dict(redacted.counts)
    rows = None
    if document.rows is not None:
        rows = []
        for row in document.rows:
            cells = []
            for cell in row:
                r = redact(cell)
                for k, v in r.counts.items():
                    counts[k] = counts.get(k, 0) + v
                cells.append(r.text)
            rows.append(cells)
    async with transaction(db):
        record = IntakeFile(
            id=new_id(),
            setup_session_id=session.id,
            kind=kind,
            filename=filename[:200],
            mime=mime or document.kind,
            text_extracted=redacted.text,
            rows=rows,
            image=data if document.kind == "image" else None,
            redaction_report=counts,
            created_at=clock.now(),
        )
        db.add(record)
    return _file_out(record)


async def run_extraction(
    db: AsyncSession, clock: Clock, llm: LLMGateway, viewer: Viewer, session_id: UUID
) -> SetupOut:
    """Extract, fill gaps from the catalogue, validate; store the draft as a new version."""
    session = await _owned(db, viewer, session_id)
    await competitions.require_processing_agreement(db, session.tournament_id)
    tournament = await competitions.get_tournament(db, viewer, session.tournament_id)
    files = await repository.files_of(db, session.id)
    if not any(f.kind == "team_list" for f in files):
        raise ValidationFailed("add the team list first")
    async with transaction(db):
        session.status = "extracting"
        session.updated_at = clock.now()
    facts = TournamentFacts(
        tournament_id=str(tournament.id),
        sport=tournament.sport,
        age_group=tournament.age_group,
        time_zone=tournament.time_zone,
        starts_on=tournament.starts_on,
        ends_on=tournament.ends_on,
        language=session.organiser_language,
    )
    intake = [
        IntakeText(f.kind, f.text_extracted, f.rows, (f.mime, f.image) if f.image else None)
        for f in files
    ]
    try:
        draft = await build_draft(facts, intake, llm)
    except Exception as exc:
        # Never leave the session "extracting": mark it failed so the organiser can retry.
        log.exception("setup_extraction_failed", setup_session_id=str(session.id))
        async with transaction(db):
            session.status = "failed"
            session.failure_reason = f"the documents could not be read ({type(exc).__name__})"
            session.updated_at = clock.now()
        return await _out(db, session)
    async with transaction(db):
        await db.execute(
            update(SetupDraft)
            .where(SetupDraft.setup_session_id == session.id, SetupDraft.status == "draft")
            .values(status="superseded")
        )
        db.add(
            SetupDraft(
                id=new_id(),
                setup_session_id=session.id,
                version=await repository.next_draft_version(db, session.id),
                draft=draft.data.model_dump(mode="json"),
                assumptions=[a.model_dump(mode="json") for a in draft.assumptions],
                open_questions=[q.model_dump(mode="json") for q in draft.questions],
                decisions=[],
                status="draft",
                created_at=clock.now(),
            )
        )
        session.status = "needs_answers" if draft.questions else "drawing"
        session.failure_reason = None
        session.updated_at = clock.now()
    if not draft.questions:
        stored = await repository.latest_draft(db, session.id)
        assert stored is not None
        await _draw_and_schedule(db, clock, session, stored, reason="initial")
    return await _out(db, session)


async def delete_setup(db: AsyncSession, viewer: Viewer, session_id: UUID) -> None:
    """Remove an event that was set up but never published: the draft tournament, its
    uploads, drafts, draws and schedules. Published events stay (409)."""
    session = await _owned(db, viewer, session_id)
    if session.status == "published":
        raise Conflict("a published event cannot be removed")
    await competitions.delete_draft_tournament(db, session.tournament_id)


async def get(db: AsyncSession, viewer: Viewer, session_id: UUID) -> SetupOut:
    """Status, files, the latest draft, its assumptions and open questions."""
    return await _out(db, await _owned(db, viewer, session_id))


# --- review, draw, schedule, publish (T-025) --------------------------------------------------


def _check_version(draft: SetupDraft, if_match: str | None) -> None:
    if if_match is None:
        return
    wanted = "".join(c for c in if_match if c.isdigit())
    if wanted != str(draft.version):
        raise StaleVersion(f"the draft is at version {draft.version}")


async def _current(db: AsyncSession, session: SetupSession) -> SetupDraft:
    draft = await repository.latest_draft(db, session.id)
    if draft is None:
        raise SetupNotReady("run the extraction first")
    return draft


async def _store(
    db: AsyncSession,
    clock: Clock,
    session: SetupSession,
    previous: SetupDraft,
    data: SetupDraftData,
    questions: list[OpenQuestion],
    decisions: list[dict[str, str]],
) -> SetupDraft:
    """Save a new draft version, then draw and schedule it once nothing is left to ask."""
    now = clock.now()
    async with transaction(db):
        previous.status = "superseded"
        draft = SetupDraft(
            id=new_id(),
            setup_session_id=session.id,
            version=previous.version + 1,
            draft=data.model_dump(mode="json"),
            assumptions=previous.assumptions,
            open_questions=[q.model_dump(mode="json") for q in questions],
            decisions=[*previous.decisions, *decisions],
            status="draft",
            created_at=now,
        )
        db.add(draft)
        session.status = "needs_answers" if questions else "drawing"
        session.updated_at = now
    if not questions:
        await _draw_and_schedule(db, clock, session, draft, reason="initial")
    return draft


async def _draw_and_schedule(
    db: AsyncSession,
    clock: Clock,
    session: SetupSession,
    draft: SetupDraft,
    *,
    reason: str,
    seed: bytes | None = None,
) -> None:
    """The engine draws (new CSPRNG seed unless given) and schedules; results are stored."""
    data = SetupDraftData.model_validate(draft.draft)
    seed = seed or secrets.token_bytes(16)
    generated = review.generate(data, seed)
    now = clock.now()
    async with transaction(db):
        await db.execute(
            update(DrawRecord)
            .where(
                DrawRecord.tournament_id == session.tournament_id, DrawRecord.status == "proposed"
            )
            .values(status="discarded")
        )
        await db.execute(
            update(SchedulePlanRecord)
            .where(
                SchedulePlanRecord.tournament_id == session.tournament_id,
                SchedulePlanRecord.status == "proposed",
            )
            .values(status="superseded")
        )
        draw_id = None
        if generated.draw is not None:
            draw = generated.draw
            record = DrawRecord(
                id=new_id(),
                tournament_id=session.tournament_id,
                setup_draft_id=draft.id,
                seed=draw.seed,
                pots=[list(p) for p in draw.pots],
                constraints=data.seeding.get("separations", []),
                result={"groups": [list(g) for g in draw.groups], "method": draw.method},
                explanation=review.draw_out(draw, data.teams).model_dump(mode="json"),
                engine_version=draw.algorithm,
                status="proposed",
                created_at=now,
            )
            db.add(record)
            draw_id = record.id
        if generated.plan is not None:
            out = review.schedule_out(generated.plan)
            db.add(
                SchedulePlanRecord(
                    id=new_id(),
                    tournament_id=session.tournament_id,
                    version=await repository.next_plan_version(db, session.tournament_id),
                    based_on_draw_id=draw_id,
                    plan={
                        "seed": seed.hex(),
                        "matches": [m.model_dump(mode="json") for m in out.matches],
                        "engine": review.engine_plan_json(generated.plan),
                    },
                    policy=data.schedule or {},
                    quality=out.quality,
                    reason=reason,
                    status="proposed",
                    created_at=now,
                )
            )
        if generated.questions:
            draft.open_questions = [q.model_dump(mode="json") for q in generated.questions]
            session.status = "needs_answers"
        else:
            draft.status = "ready"
            session.status = "ready"
        session.updated_at = now


async def answer(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    session_id: UUID,
    answers: list[Answer],
    if_match: str | None,
) -> SetupOut:
    """Answer open questions; the engine re-validates, then draws and schedules."""
    session = await _owned(db, viewer, session_id)
    current = await _current(db, session)
    _check_version(current, if_match)
    data = SetupDraftData.model_validate(current.draft)
    questions = {q["id"]: OpenQuestion.model_validate(q) for q in current.open_questions}
    decisions = []
    for a in answers:
        question = questions.pop(a.question_id, None)
        if question is None:
            raise ValidationFailed(f"no open question '{a.question_id}'")
        value = a.value
        if question.field == "schedule" and question.options:
            value = await _relaxation_policy(data, a.value)
        try:
            data = review.apply_change(data, question.field, value, question)
        except review.UnknownAnswer as exc:
            raise ValidationFailed(str(exc)) from exc
        decisions.append({"question": question.id, "field": question.field, "value": a.value})
    remaining = review.refresh_questions(data, list(questions.values()))
    await _store(db, clock, session, current, data, remaining, decisions)
    return await _out(db, session)


async def _relaxation_policy(data: SetupDraftData, summary: str) -> str:
    generated = review.generate(data, b"relaxation")
    for relaxation in generated.relaxations:
        if relaxation.summary == summary:
            return relaxation.policy.model_dump_json()
    raise ValidationFailed(f"'{summary}' is not one of the suggested changes")


async def change(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    session_id: UUID,
    field: str,
    value: str,
    if_match: str | None,
) -> SetupOut:
    """Change one value of the draft (an assumption the organiser disagrees with)."""
    session = await _owned(db, viewer, session_id)
    current = await _current(db, session)
    _check_version(current, if_match)
    try:
        data = review.apply_change(SetupDraftData.model_validate(current.draft), field, value)
    except review.UnknownAnswer as exc:
        raise ValidationFailed(str(exc)) from exc
    open_ = [OpenQuestion.model_validate(q) for q in current.open_questions]
    await _store(
        db,
        clock,
        session,
        current,
        data,
        review.refresh_questions(data, open_, changed=field),
        [{"field": field, "value": value}],
    )
    return await _out(db, session)


async def redraw(db: AsyncSession, clock: Clock, viewer: Viewer, session_id: UUID) -> SetupOut:
    """A new draw with a new seed (previous draws are kept for audit)."""
    session = await _owned(db, viewer, session_id)
    if session.status not in ("ready", "drawing"):
        raise SetupNotReady("answer the open questions first")
    await _draw_and_schedule(db, clock, session, await _current(db, session), reason="regenerate")
    return await _out(db, session)


async def regenerate_schedule(
    db: AsyncSession, clock: Clock, viewer: Viewer, session_id: UUID, relaxation: str | None
) -> SetupOut:
    """Rebuild the schedule for the same draw, optionally applying an engine suggestion."""
    session = await _owned(db, viewer, session_id)
    current = await _current(db, session)
    data = SetupDraftData.model_validate(current.draft)
    if relaxation:
        data = review.apply_change(data, "schedule", await _relaxation_policy(data, relaxation))
        async with transaction(db):
            current.draft = data.model_dump(mode="json")
    draw = await repository.proposed_draw(db, session.tournament_id)
    await _draw_and_schedule(
        db, clock, session, current, reason="regenerate", seed=draw.seed if draw else None
    )
    return await _out(db, session)


async def move_match(
    db: AsyncSession, clock: Clock, viewer: Viewer, session_id: UUID, code: str, move: MoveMatch
) -> SetupOut:
    """Pin one match to a day, time and pitch; the engine rebuilds the rest around it."""
    session = await _owned(db, viewer, session_id)
    current = await _current(db, session)
    try:
        data = review.move_match(
            SetupDraftData.model_validate(current.draft), code, move.date, move.start, move.pitch
        )
    except (review.UnknownAnswer, ValueError) as exc:
        raise ValidationFailed(str(exc)) from exc
    draw = await repository.proposed_draw(db, session.tournament_id)
    generated = review.generate(data, draw.seed if draw else secrets.token_bytes(16))
    if generated.plan is None:
        raise ScheduleInfeasibleError(generated.questions[0].text if generated.questions else None)
    async with transaction(db):
        current.draft = data.model_dump(mode="json")
    await _draw_and_schedule(
        db, clock, session, current, reason="manual", seed=draw.seed if draw else None
    )
    return await _out(db, session)


_JUNIOR_FILMING = ("consent_required", "not_allowed")


async def _filming_chosen(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, policy: FilmingPolicy | None
) -> None:
    """Publishing needs an explicit filming policy; junior tournaments film only with
    consent, or not at all (docs/13 §7)."""
    tournament = await competitions.get_tournament(db, viewer, tournament_id)
    if policy is None:
        if not tournament.settings.filming_confirmed:
            raise SetupNotReady("choose a filming policy (filming_policy) before publishing")
        policy = tournament.settings.filming_policy
    if tournament.is_junior and policy not in _JUNIOR_FILMING:
        raise ValidationFailed(
            "junior tournaments need the filming policy consent_required or not_allowed"
        )
    await competitions.update_settings(
        db, tournament_id, {"filming_policy": policy, "filming_confirmed": True}
    )


async def publish(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    session_id: UUID,
    if_match: str | None,
    filming_policy: FilmingPolicy | None = None,
) -> Published:
    """Write groups, teams, matches and confirmed rules in one transaction; go public."""
    session = await _owned(db, viewer, session_id)
    current = await _current(db, session)
    _check_version(current, if_match)
    if current.open_questions:
        raise OpenQuestionsRemaining(f"{len(current.open_questions)} questions are still open")
    if session.status != "ready":
        raise SetupNotReady(f"the setup is '{session.status}'")
    await _filming_chosen(db, viewer, session.tournament_id, filming_policy)
    draw = await repository.proposed_draw(db, session.tournament_id)
    plan = await repository.proposed_plan(db, session.tournament_id)
    if plan is None:
        raise SetupNotReady("there is no schedule yet")
    data = SetupDraftData.model_validate(current.draft)
    rules, fmt, _, schedule = review.engine_inputs(data)
    tournament = await competitions.get_tournament(db, viewer, session.tournament_id)
    group_of: dict[str, str] = {}
    pot_of: dict[str, int | None] = {}
    if draw is not None:
        for index, members in enumerate(draw.result["groups"]):
            for key in members:
                group_of[key] = chr(ord("A") + index)
        for pot_index, members in enumerate(draw.pots):
            for key in members:
                pot_of[key] = pot_index + 1
    seeds = {f"seed:{i}": t.key for i, t in enumerate(data.teams, start=1)}
    structure = TournamentStructure(
        venue_name=tournament.name,
        pitches=list(schedule.pitches) if schedule else [],
        groups=sorted(set(group_of.values())),
        teams=[
            TeamEntry(
                key=t.key,
                name=t.name,
                short_name=t.short_name,
                organisation_name=t.organisation,
                group=group_of.get(t.key),
                pot=pot_of.get(t.key),
                seed=i,
                seeding_reason={"previous_placement": t.previous_placement},
            )
            for i, t in enumerate(data.teams, start=1)
        ],
        matches=[
            MatchEntry(
                code=m["code"],
                stage=m["stage"],
                group=m["group"],
                round=m["round"],
                home_key=m["home"] or seeds.get(m["home_source"] or ""),
                away_key=m["away"] or seeds.get(m["away_source"] or ""),
                home_source=m["home_source"],
                away_source=m["away_source"],
                pitch=m["pitch"],
                starts_at=m["starts_at"],
            )
            for m in plan.plan["matches"]
        ],
        format_spec=fmt.model_dump(mode="json"),
        policy_catalogue_version=CATALOGUE_VERSION,
    )
    async with transaction(db):
        team_ids = await competitions.create_structure(db, clock, session.tournament_id, structure)
        plan.plan = {**plan.plan, "team_ids": {k: str(v) for k, v in team_ids.items()}}
        await rules_service.save_draft(
            db, clock, session.tournament_id, rules, {"setup_draft": str(current.id)}
        )
        await rules_service.confirm(db, clock, viewer, session.tournament_id)
        current.status = "published"
        if draw is not None:
            draw.status = "published"
        plan.status = "published"
        session.status = "published"
        session.updated_at = clock.now()
        # recalc_tournament builds the standings and fixtures read models fans see first
        for job in ("recalc_tournament", "prematch_build", "notify_teams"):
            await jobs.defer(db, job, tournament_id=session.tournament_id)
    counts = await competitions.tournament_counts(db, session.tournament_id)
    return Published(tournament_id=session.tournament_id, status="upcoming", **counts)


async def published_draw(db: AsyncSession, tournament_id: UUID) -> DrawOut:
    """The draw that was published (404 before publish)."""
    draw = await repository.published_draw(db, tournament_id)
    if draw is None:
        raise NotFound()
    return DrawOut.model_validate(draw.explanation)


INTAKE_RETENTION = timedelta(days=365)


async def purge_intake(db: AsyncSession, clock: Clock) -> int:
    """Retention (docs/09): uploaded rulebooks, team lists and photos are deleted one year
    after the tournament ends (the extracted rules and teams stay)."""
    removed = 0
    today = clock.now().date()
    async with transaction(db):
        for tournament_id in await repository.intake_tournaments(db):
            window = await competitions.tournament_window(db, tournament_id)
            if window.ends_on is not None and window.ends_on + INTAKE_RETENTION < today:
                removed += await repository.delete_intake(db, tournament_id)
    return removed


# --- live draw (docs/12 §5: live draw mode) -------------------------------------------------


async def _ceremony_draw(db: AsyncSession, tournament_id: UUID) -> DrawRecord:
    draw = await repository.published_draw(db, tournament_id)
    draw = draw or await repository.proposed_draw(db, tournament_id)
    if draw is None:
        raise NotFound()
    return draw


def _steps(draw: DrawRecord) -> list[RevealStep]:
    """Pot 1 first, group by group, then pot 2, …; teams without a pot last."""
    out = DrawOut.model_validate(draw.explanation)
    picks = [
        (t.pot if t.pot is not None else 10_000, g_index, t_index, g.group, t)
        for g_index, g in enumerate(out.groups)
        for t_index, t in enumerate(g.teams)
    ]
    return [
        RevealStep(step=n, pot=t.pot, group=group, team=t.name)
        for n, (_, _, _, group, t) in enumerate(sorted(picks, key=lambda p: p[:3]), start=1)
    ]


def _reveal_out(tournament_id: UUID, draw: DrawRecord) -> DrawReveal:
    steps = _steps(draw)
    done = draw.revealed >= len(steps)
    return DrawReveal(
        tournament_id=tournament_id,
        total=len(steps),
        revealed=draw.revealed,
        steps=steps[: draw.revealed],
        seed=draw.seed.hex() if done else None,
    )


async def draw_reveal(db: AsyncSession, tournament_id: UUID) -> DrawReveal:
    """What the venue screen shows of the live draw so far."""
    return _reveal_out(tournament_id, await _ceremony_draw(db, tournament_id))


async def reveal_next(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID, live: LiveHub | None
) -> DrawReveal:
    """Reveal the next team (organisers); sends a `draw_step` live message."""
    if not await competitions.manages(db, viewer, tournament_id):
        raise NotFound()
    async with transaction(db):
        draw = await _ceremony_draw(db, tournament_id)
        steps = _steps(draw)
        if draw.revealed >= len(steps):
            raise Conflict("every team has been drawn")
        draw.revealed += 1
    out = _reveal_out(tournament_id, draw)
    if live is not None:
        data = {**steps[draw.revealed - 1].model_dump(), "total": out.total, "seed": out.seed}
        await live.publish(
            tournament_channel(tournament_id), envelope("draw_step", clock.now(), data)
        )
    return out


async def reset_reveal(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> DrawReveal:
    """Start the ceremony again (organisers)."""
    if not await competitions.manages(db, viewer, tournament_id):
        raise NotFound()
    async with transaction(db):
        draw = await _ceremony_draw(db, tournament_id)
        draw.revealed = 0
    return _reveal_out(tournament_id, draw)
