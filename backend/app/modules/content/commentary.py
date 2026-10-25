"""Live commentary (docs/06-live.md, Commentary cadence; docs/07, commentary.v1).

Written from the scorer's events: every moment (goal, equaliser, red card, half and full
time, …) defers `write_commentary`. At most one line per match every 45 seconds: a moment
inside the window moves the job to the window's end, where one line covers everything
since the last one. Full time always gets its line. With many pitches live, the AI writes
for the matches with the most live viewers (knockouts first); the others, and every line
the model cannot write in time or the checker rejects, get a template line.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.db import transaction
from app.core.errors import Forbidden
from app.core.live import LiveHub, envelope, match_channel, tournament_channel
from app.core.llm import LLMError, LLMGateway
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.analysis import service as analysis
from app.modules.analysis.schemas import FactSheetOut, MatchInfo
from app.modules.content import checker
from app.modules.content.models import CommentaryItem
from app.modules.content.schemas import (
    CheckResult,
    CommentaryLine,
    CommentaryOut,
    NameBook,
    StoryDraft,
    WritingInputs,
)
from app.modules.content.service import AI_LABELS

log = structlog.get_logger("commentary")

WINDOW = timedelta(seconds=45)
AI_SLOTS = 4  # live matches per tournament that get AI lines at the same time
_BENGALI = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
_TEAM_EVENTS = ("goal", "red_card", "second_yellow", "penalty_missed", "foul", "timeout")
# Most important first: the line is about this moment.
PRIORITY = (
    "full_time",
    "red_card",
    "lead_change",
    "equaliser",
    "penalty_scored",
    "goal",
    "sixth_foul",
    "penalty_missed",
    "timeout",
    "half_time",
    "kick_off",
)
TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "full_time": "Full time: {score}.",
        "red_card": "Red card for {team}. It is {score}.",
        "lead_change": "{team} take the lead! {score}.",
        "equaliser": "{team} equalise! {score}.",
        "penalty_scored": "Penalty scored by {team}! {score}.",
        "goal": "GOAL for {team}! {score}.",
        "penalty_missed": "{team} miss a penalty. Still {score}.",
        "half_time": "Half time: {score}.",
        "kick_off": "Kick-off: {home} against {away}.",
        "sixth_foul": "{team} commit their sixth foul: a direct free kick from now on. {score}.",
        "timeout": "Timeout for {team}. {score}.",
    },
    "fi": {
        "full_time": "Loppuvihellys: {score}.",
        "red_card": "Punainen kortti joukkueelle {team}. Tilanne {score}.",
        "lead_change": "{team} siirtyy johtoon! {score}.",
        "equaliser": "{team} tasoittaa! {score}.",
        "penalty_scored": "Rangaistuspotkumaali, {team}! {score}.",
        "goal": "MAALI, {team}! {score}.",
        "penalty_missed": "{team} epäonnistuu rangaistuspotkussa. Yhä {score}.",
        "half_time": "Puoliaika: {score}.",
        "kick_off": "Ottelu alkaa: {home} vastaan {away}.",
        "sixth_foul": "{team}: kuudes virhe, nyt jokaisesta virheestä suora vapaapotku. {score}.",
        "timeout": "Aikalisä joukkueelle {team}. {score}.",
    },
    "bn": {
        "full_time": "খেলা শেষ: {score}।",
        "red_card": "{team} লাল কার্ড পেয়েছে। স্কোর {score}।",
        "lead_change": "{team} এগিয়ে গেল! {score}।",
        "equaliser": "{team} সমতা ফেরাল! {score}।",
        "penalty_scored": "পেনাল্টি থেকে গোল, {team}! {score}।",
        "goal": "গোল! {team}! {score}।",
        "penalty_missed": "{team} পেনাল্টি মিস করেছে। স্কোর এখনো {score}।",
        "half_time": "বিরতি: {score}।",
        "kick_off": "খেলা শুরু: {home} বনাম {away}।",
        "sixth_foul": "{team} ষষ্ঠ ফাউল করেছে: এখন থেকে সরাসরি ফ্রি কিক। {score}।",
        "timeout": "{team} টাইম-আউট নিয়েছে। {score}।",
    },
}


def _main_moment(moments: list[str], sheet: FactSheetOut) -> str:
    present = set(moments) | ({"goal"} if any(f.kind == "goal" for f in sheet.facts) else set())
    return next((m for m in PRIORITY if m in present), "goal")


def template_lines(
    sheet: FactSheetOut, match: MatchInfo, names: dict[str, str], moment: str
) -> dict[str, dict[str, Any]]:
    """A line per language built only from the score and the team of the moment."""
    score_fact = next(f for f in sheet.facts if f.kind == "score")
    home, away = names[str(match.home_team_id)], names[str(match.away_team_id)]
    team_fact = next(
        (f for f in reversed(sheet.facts) if f.team_id and f.kind in _TEAM_EVENTS), None
    )
    team = names.get(team_fact.team_id or "", home) if team_fact else home
    used = [score_fact.id] + ([team_fact.id] if team_fact else [])
    lines = {}
    for language in sheet.context.languages:
        score = f"{home} {score_fact.value} {away}"
        if language == "bn":
            score = score.replace(str(score_fact.value), str(score_fact.value).translate(_BENGALI))
        text = TEMPLATES[language][moment].format(score=score, team=team, home=home, away=away)
        lines[language] = {"text": text, "facts": used}
    return lines


async def _prioritised(db: AsyncSession, live: LiveHub | None, match: MatchInfo) -> bool:
    """Whether this match is among the AI_SLOTS live matches with the largest audience."""
    matches = await analysis.live_matches(db, match.tournament_id)
    if len(matches) <= AI_SLOTS:
        return True

    async def rank(m: MatchInfo) -> tuple[bool, int]:
        viewers = await live.viewers(m.id) if live else 0
        return (m.stage != "group", viewers)

    ranked = sorted([(await rank(m), str(m.id)) for m in matches], reverse=True)
    return str(match.id) in {mid for _, mid in ranked[:AI_SLOTS]}


async def _ai_lines(
    db: AsyncSession, llm: LLMGateway, sheet: FactSheetOut
) -> tuple[dict[str, dict[str, Any]] | None, CheckResult | None, str | None]:
    """AI lines that passed the checker, or None with the reason."""
    assert sheet.context.tournament_id is not None
    names = NameBook.model_validate(
        await analysis.names_for_checking(db, sheet.context.tournament_id)
    )
    _, low, high = checker.LIMITS["commentary"]
    inputs = WritingInputs(
        task="commentary",
        sentence_range=(low, high),
        tone_profile=sheet.context.tone_profile,
        show_probabilities=sheet.context.show_probabilities,
        facts=analysis.fact_payload(sheet)["facts"],
    )
    try:
        result = await llm.generate(
            "commentary.v1",
            inputs,
            output=StoryDraft,
            languages=sheet.context.languages,
            tournament_id=str(sheet.context.tournament_id),
        )
    except LLMError as exc:
        log.info("commentary_template", reason="llm", error=str(exc))
        return None, None, "llm_error"
    texts = result.output.texts()
    check = checker.check(texts, sheet, names, task="commentary")
    if not check.passed:
        log.info("commentary_dropped", issues=[i.detail for i in check.issues])
        return None, check, "checker"
    lines = {
        lang: {
            "text": " ".join(s.text for s in t.sentences),
            "facts": sorted({i for s in t.sentences for i in s.facts}),
        }
        for lang, t in texts.items()
    }
    return lines, check, None


def commentary_out(row: CommentaryItem) -> CommentaryOut:
    return CommentaryOut(
        id=row.id,
        match_id=row.match_id,
        seq=row.seq,
        kind=row.kind,
        moments=row.moments,
        items=[
            CommentaryLine(language=lang, text=v["text"], fact_ids=v["facts"])
            for lang, v in row.texts.items()
        ],
        author_type=row.author_type,
        ai_labels={lang: AI_LABELS[lang] for lang in row.texts}
        if row.author_type == "ai"
        else None,
        created_at=row.created_at,
    )


async def write_commentary(
    db: AsyncSession,
    clock: Clock,
    llm: LLMGateway,
    live: LiveHub | None,
    match_id: UUID,
    seq: int,
    moments: list[str],
) -> CommentaryOut | None:
    """One commentary line for the match's latest moments (or None: covered or deferred)."""
    final = "full_time" in moments
    last = await db.scalar(
        select(CommentaryItem)
        .where(CommentaryItem.match_id == match_id)
        .order_by(CommentaryItem.created_at.desc(), CommentaryItem.seq.desc())
        .limit(1)
    )
    if final:
        done = await db.scalar(
            select(CommentaryItem.id).where(
                CommentaryItem.match_id == match_id,
                CommentaryItem.moments.contains(["full_time"]),
            )
        )
        if done is not None:
            return None
    elif last is not None:
        if last.seq >= seq:
            return None  # an earlier line already covers this event
        due = last.created_at + WINDOW
        if clock.now() < due:
            async with transaction(db):
                await jobs.defer(
                    db,
                    "write_commentary",
                    run_at=due,
                    match_id=match_id,
                    seq=seq,
                    moments=",".join(moments),
                )
            return None
    since = last.seq if last is not None else 0
    sheet = await analysis.live_fact_sheet(db, clock, match_id, since, moments)
    if sheet is None or sheet.context.tournament_id is None:
        return None
    match = await analysis.match_info(db, match_id)
    names = await analysis.team_names(db, sheet.context.tournament_id)
    moment = _main_moment(moments, sheet)
    lines: dict[str, dict[str, Any]] | None = None
    check: CheckResult | None = None
    reason: str | None = "priority"
    if await _prioritised(db, live, match):
        lines, check, reason = await _ai_lines(db, llm, sheet)
    author = "ai" if lines else "template"
    lines = lines or template_lines(sheet, match, names, moment)
    covered = max(seq, await analysis.live_seq(db, match_id))
    async with transaction(db):
        row = CommentaryItem(
            match_id=match_id,
            tournament_id=sheet.context.tournament_id,
            seq=covered,
            kind="moment",
            moments=sorted(set(moments) | {moment}),
            texts=lines,
            fact_sheet_id=sheet.id,
            check_result=check.model_dump() if check else {},
            author_type=author,
            reason=None if author == "ai" else reason,
            created_at=clock.now(),
        )
        db.add(row)
    out = commentary_out(row)
    if live is not None:
        message = envelope(
            "commentary", clock.now(), out.model_dump(mode="json"), match_id=match_id
        )
        await live.publish(match_channel(match_id), message)
        await live.publish(tournament_channel(sheet.context.tournament_id), message)
    return out


async def match_commentary(db: AsyncSession, viewer: Viewer, match_id: UUID) -> list[CommentaryOut]:
    """A match's commentary, newest first (live access policy while the match is live)."""
    if not await analysis.can_watch_live(db, viewer, match_id):
        raise Forbidden("live coverage is for members")
    rows = await db.scalars(
        select(CommentaryItem)
        .where(CommentaryItem.match_id == match_id)
        .order_by(CommentaryItem.created_at.desc(), CommentaryItem.seq.desc())
    )
    return [commentary_out(r) for r in rows]
