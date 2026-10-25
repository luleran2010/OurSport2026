"""Content: AI stories and announcements written from fact sheets (docs/07).

`write_story` gets the fact sheet from analysis, asks the gateway for every tournament
language at once, runs the claim checker per language, regenerates once with the issues,
and publishes what passes with the AI label. A draft that still fails waits in review
(`in_review`, editorial T-054); an LLM failure means silence (the result card is enough).
Announcement drafts fall back to a template, since the organiser always sees them first.
"""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import transaction
from app.core.errors import NotFound, StaleVersion, ValidationFailed
from app.core.live import LiveHub, envelope, match_channel, tournament_channel
from app.core.llm import LLMError, LLMGateway, ProviderError
from app.core.pagination import Page, PageParams, decode_cursor, encode_cursor
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.analysis import service as analysis
from app.modules.analysis.schemas import FactSheetOut
from app.modules.content import checker
from app.modules.content.models import Announcement, CommentaryItem, Story, StoryVersion
from app.modules.content.schemas import (
    AnnouncementOut,
    CheckResult,
    FictionalFlavor,
    NameBook,
    ReviewItem,
    ReviewSummary,
    StoryAction,
    StoryDetail,
    StoryDraft,
    StoryEdit,
    StoryFact,
    StoryOut,
    StoryVersionOut,
    WritingInputs,
    WrittenSentence,
    WrittenText,
)
from app.modules.content.team_backgrounds import (
    find_team_backgrounds,
    source_claims,
    with_fact_ids,
)

log = structlog.get_logger("content")

TEMPLATE_VERSION = "v1"
AI_LABELS = {
    "en": "Written by AI from match data",
    "fi": "Tekoälyn kirjoittama otteludatan pohjalta",
    "bn": "ম্যাচের তথ্য থেকে এআই-এর লেখা",
}
REVIEWED = {
    "en": ", reviewed by an editor",
    "fi": ", toimittajan tarkistama",
    "bn": ", সম্পাদকের যাচাই করা",
}
_BIG_MATCH = ("final", "semi_final", "third_place")
_PLAIN_FACTS = ("fixture", "kickoff", "pitch", "result")
_RESULT_PREFIX = {"en": "Full time", "fi": "Lopputulos", "bn": "খেলা শেষ"}
_BENGALI = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


async def _sheet(
    db: AsyncSession,
    clock: Clock,
    subject_type: str,
    subject_id: UUID,
    kind: str,
    tournament_id: UUID | None,
) -> FactSheetOut | None:
    if subject_type == "match":
        return await analysis.match_fact_sheet(db, clock, subject_id, kind)
    if subject_type == "team" and tournament_id is not None:
        return await analysis.team_fact_sheet(db, clock, tournament_id, subject_id)
    if subject_type == "tournament":
        return await analysis.tournament_fact_sheet(db, clock, subject_id)
    return None


def _length(sheet: FactSheetOut, kind: str) -> str | None:
    """Finals, decisive matches and upsets get a standard report; the rest a short one."""
    if kind != "report":
        return None
    kinds = {f.kind for f in sheet.facts}
    big = any(
        f.kind == "fixture" and any(s in f.claim.lower().replace(" ", "_") for s in _BIG_MATCH)
        for f in sheet.facts
    )
    return "standard" if big or kinds & {"upset", "qualified", "eliminated"} else "short"


def _inputs(
    sheet: FactSheetOut,
    task: str,
    length: str | None,
    issues: list[str],
    names: NameBook,
) -> WritingInputs:
    unit, low, high = checker.LIMITS[f"{task}:{length}" if task == "report" else task]
    claims = " ".join(fact.claim for fact in sheet.facts)
    team_context = (
        with_fact_ids(find_team_backgrounds(
            [
                name
                for name in names.teams
                if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", claims, re.IGNORECASE)
            ]
        ))
        if task == "report"
        else {}
    )
    return WritingInputs(
        task=task,
        length=length,
        word_range=(low, high) if unit == "words" else None,
        sentence_range=(low, high) if unit == "sentences" else None,
        tone_profile=sheet.context.tone_profile,
        show_probabilities=sheet.context.show_probabilities,
        facts=analysis.fact_payload(sheet)["facts"],
        fictional_team_backgrounds=team_context,
        retry_issues=issues,
    )


async def _names(db: AsyncSession, tournament_id: UUID) -> NameBook:
    return NameBook.model_validate(await analysis.names_for_checking(db, tournament_id))


async def _draft(
    llm: LLMGateway, sheet: FactSheetOut, names: NameBook, task: str, length: str | None
) -> tuple[dict[str, WrittenText], CheckResult, str]:
    """Write and check; one regeneration with the checker's issues if the first fails."""
    issues: list[str] = []
    languages = sheet.context.languages
    tournament = str(sheet.context.tournament_id) if sheet.context.tournament_id else None
    for _ in range(2):
        inputs = _inputs(sheet, task, length, issues, names)
        result = await llm.generate(
            f"{task}.{TEMPLATE_VERSION}",
            inputs,
            output=StoryDraft,
            languages=languages,
            tournament_id=tournament,
        )
        texts = result.output.texts()
        for language, text in texts.items():
            if text.fictional_flavor is None:
                continue
            allowed_lore = source_claims(inputs.fictional_team_backgrounds, language)
            if not allowed_lore:
                text.fictional_flavor = None
            elif not text.fictional_flavor.facts:
                text.fictional_flavor.facts = list(allowed_lore)
        check = checker.check(
            texts,
            sheet,
            names,
            task=task,
            length=length,
            additional_facts={
                fact_id: claim
                for language in languages
                for fact_id, claim in source_claims(
                    inputs.fictional_team_backgrounds, language
                ).items()
            },
        )
        if check.passed:
            return texts, check, result.model
        issues = [f"{i.language}: {i.kind}: {i.detail}: {i.sentence}" for i in check.issues]
    return texts, check, result.model


def _meaningful(sheet: FactSheetOut) -> bool:
    """Silence is allowed: a report needs more than the result itself (docs/07)."""
    return any(f.kind not in _PLAIN_FACTS for f in sheet.facts)


_FICTION_LABELS = {
    "en": "Fictional team flavor (not a match fact):",
    "fi": "Kuvitteellinen joukkuekuvaus (ei ottelufakta):",
    "bn": "কাল্পনিক দলের পরিচিতি (ম্যাচের তথ্য নয়):",
}
_LORE_FACT_LABELS = {
    "en": "Fictional team background (not a match fact): ",
    "fi": "Kuvitteellinen joukkuekuvaus (ei ottelufakta): ",
    "bn": "কাল্পনিক দলের পরিচিতি (ম্যাচের তথ্য নয়): ",
}


def _story_body(text: WrittenText, language: str) -> str:
    """Keep optional fictional flavor visibly distinct from fact-checked match prose."""
    body = " ".join(sentence.text for sentence in text.sentences)
    flavor = text.fictional_flavor.text if text.fictional_flavor else None
    if flavor:
        label = _FICTION_LABELS.get(language, _FICTION_LABELS["en"])
        body = f"{body}\n\n**{label}** {flavor}"
    return body


def _story_sentences(
    text: WrittenText,
    language: str,
    backgrounds: dict[str, dict[str, dict[str, str]]],
) -> list[dict[str, Any]]:
    sentences = [sentence.model_dump() for sentence in text.sentences]
    flavor = text.fictional_flavor
    if flavor:
        lore = source_claims(backgrounds, language)
        sentences.append(
            {
                **flavor.model_dump(),
                "fictional": True,
                "sources": [
                    {"id": fact_id, "claim": claim}
                    for fact_id, claim in lore.items()
                    if fact_id in flavor.facts
                ],
            }
        )
    return sentences


def _fictional_flavor_text(body: str, language: str) -> str | None:
    label = _FICTION_LABELS.get(language, _FICTION_LABELS["en"])
    marker = f"\n\n**{label}**"
    if marker not in body:
        return None
    return body.split(marker, maxsplit=1)[1].strip()


def _fact_body(body: str) -> str:
    """Exclude only the explicitly labeled fiction section from editorial fact checks."""
    for label in _FICTION_LABELS.values():
        marker = f"\n\n**{label}**"
        if marker in body:
            return body.split(marker, maxsplit=1)[0]
    return body


async def write_story(
    db: AsyncSession,
    clock: Clock,
    llm: LLMGateway,
    subject_type: str,
    subject_id: UUID,
    kind: str,
    *,
    tournament_id: UUID | None = None,
    correction: bool = False,
    force: bool = False,
    live: LiveHub | None = None,
) -> list[StoryOut]:
    """Write (or rewrite) one story in every tournament language; returns what was
    published. Unchanged facts are not rewritten unless `force` (an editor's regenerate).
    A `correction` rewrite of a published story marks it "Corrected" and tells live
    viewers."""
    sheet = await _sheet(db, clock, subject_type, subject_id, kind, tournament_id)
    if sheet is None or sheet.context.tournament_id is None:
        return []
    if kind == "report" and not _meaningful(sheet):
        return []
    existing = {
        s.language: s
        for s in await db.scalars(
            select(Story).where(
                Story.subject_type == subject_type,
                Story.subject_id == subject_id,
                Story.kind == kind,
            )
        )
    }
    if not force and existing and all(s.fact_sheet_id == sheet.id for s in existing.values()):
        return [_out(s) for s in existing.values() if s.status == "published"]
    length = _length(sheet, kind)
    names = await _names(db, sheet.context.tournament_id)
    backgrounds = _inputs(sheet, kind, length, [], names).fictional_team_backgrounds
    try:
        texts, check, model = await _draft(llm, sheet, names, kind, length)
    except ProviderError as exc:
        if exc.retryable:
            raise  # the job retries with backoff
        log.warning("story_not_written", kind=kind, subject_id=str(subject_id), error=str(exc))
        return []
    except LLMError as exc:
        log.warning("story_not_written", kind=kind, subject_id=str(subject_id), error=str(exc))
        return []
    now = clock.now()
    sensitive = sheet.context.is_junior and any(
        f.kind in ("red_card", "second_yellow") for f in sheet.facts
    )
    status = "published" if check.passed and not sensitive else "in_review"
    reason = None if status == "published" else "sensitive" if sensitive else "blocked_claim"
    stored: list[Story] = []
    corrected: list[Story] = []
    async with transaction(db):
        for language, text in texts.items():
            if language not in sheet.context.languages:
                continue
            own = [i for i in check.issues if i.language == language]
            row = existing.get(language)
            if row is None:
                row = Story(
                    tournament_id=sheet.context.tournament_id,
                    kind=kind,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    language=language,
                    author_type="ai",
                    version=0,
                    created_at=now,
                )
                db.add(row)
            elif row.version:
                db.add(
                    StoryVersion(
                        story_id=row.id,
                        version=row.version,
                        headline=row.headline,
                        body=row.body,
                        created_at=now,
                    )
                )
                if correction and row.status == "published" and status == "published":
                    row.corrected_at = now
                    corrected.append(row)
            row.headline = (text.headline.text if text.headline else text.sentences[0].text)[:200]
            row.body = _story_body(text, language)
            row.sentences = _story_sentences(text, language, backgrounds)
            row.fact_sheet_id = sheet.id
            row.status = status
            row.check_result = CheckResult(passed=not own, issues=own).model_dump()
            row.model = model
            row.template = f"{kind}.{TEMPLATE_VERSION}"
            row.version = (row.version or 0) + 1
            row.published_at = now if status == "published" else row.published_at
            row.review_reason = reason
            row.reviewed_by = row.reviewed_at = None
            row.updated_at = now
            stored.append(row)
    log.info("story_written", kind=kind, status=status, languages=sorted(texts))
    if corrected and live is not None:
        await _announce_correction(live, clock, sheet, corrected)
    return [_out(s) for s in stored if s.status == "published"]


async def _announce_correction(
    live: LiveHub, clock: Clock, sheet: FactSheetOut, stories: list[Story]
) -> None:
    """A `correction` live message: the story was rewritten from corrected facts."""
    data = {
        "story_corrected": [_out(s).model_dump(mode="json") for s in stories],
        "subject_type": sheet.subject_type,
        "subject_id": str(sheet.subject_id),
    }
    match_id = sheet.subject_id if sheet.subject_type == "match" else None
    message = envelope("correction", clock.now(), data, match_id=match_id)
    if match_id is not None:
        await live.publish(match_channel(match_id), message)
    if sheet.context.tournament_id is not None:
        await live.publish(tournament_channel(sheet.context.tournament_id), message)


def story_label(s: Story) -> str | None:
    if s.author_type != "ai":
        return None
    label = AI_LABELS.get(s.language)
    return f"{label}{REVIEWED[s.language]}" if label and s.reviewed_by else label


def _out(s: Story) -> StoryOut:
    return StoryOut(
        id=s.id,
        tournament_id=s.tournament_id,
        kind=s.kind,
        subject_type=s.subject_type,
        subject_id=s.subject_id,
        language=s.language,
        headline=s.headline,
        body=s.body,
        author_type=s.author_type,
        ai_label=story_label(s),
        published_at=s.published_at,
        corrected_at=s.corrected_at,
        version=s.version,
    )


async def _published(db: AsyncSession, *where: Any, language: str | None) -> list[StoryOut]:
    query = select(Story).where(Story.status == "published", *where)
    if language:
        query = query.where(Story.language == language)
    rows = await db.scalars(query.order_by(Story.published_at.desc(), Story.language))
    return [_out(s) for s in rows]


async def tournament_stories(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID, language: str | None = None
) -> list[StoryOut]:
    """Published stories of a tournament, newest first."""
    await analysis.visible_tournament(db, viewer, tournament_id)
    return await _published(db, Story.tournament_id == tournament_id, language=language)


async def match_stories(
    db: AsyncSession, viewer: Viewer, match_id: UUID, kind: str | None, language: str | None
) -> list[StoryOut]:
    """Published stories of a match (preview, report)."""
    await analysis.visible_tournament(db, viewer, await analysis.match_tournament_id(db, match_id))
    where = [Story.subject_type == "match", Story.subject_id == match_id]
    if kind:
        where.append(Story.kind == kind)
    return await _published(db, *where, language=language)


async def team_stories(
    db: AsyncSession, team_id: UUID, tournament_id: UUID | None, match_ids: list[UUID]
) -> list[StoryOut]:
    """A team's recaps and the stories of its matches (My Team hub)."""
    subjects: ColumnElement[bool] = (Story.subject_type == "team") & (Story.subject_id == team_id)
    if match_ids:
        subjects = subjects | ((Story.subject_type == "match") & Story.subject_id.in_(match_ids))
    where = [subjects]
    if tournament_id is not None:
        where.append(Story.tournament_id == tournament_id)
    return await _published(db, *where, language=None)


async def match_reports(db: AsyncSession, match_ids: list[UUID]) -> dict[UUID, list[StoryOut]]:
    """Published reports by match (feeds attach them to results)."""
    if not match_ids:
        return {}
    stories = await _published(
        db,
        Story.subject_type == "match",
        Story.subject_id.in_(match_ids),
        Story.kind == "report",
        language=None,
    )
    out: dict[UUID, list[StoryOut]] = {}
    for s in stories:
        out.setdefault(s.subject_id, []).append(s)
    return out


async def story(db: AsyncSession, viewer: Viewer, story_id: UUID) -> StoryDetail:
    """One published story with the facts behind each sentence ("Why?")."""
    row = await db.get(Story, story_id)
    if row is None or row.status != "published":
        raise NotFound()
    await analysis.visible_tournament(db, viewer, row.tournament_id)
    facts = await analysis.fact_sheet(db, row.fact_sheet_id) if row.fact_sheet_id else None
    used = {i for s in row.sentences for i in s.get("facts", [])}
    lore_facts = {
        source["id"]: source["claim"]
        for sentence in row.sentences
        for source in sentence.get("sources", [])
    }
    return StoryDetail(
        **_out(row).model_dump(),
        sentences=row.sentences,
        facts=[
            StoryFact(id=f.id, claim=f.claim)
            for f in (facts.facts if facts else [])
            if f.id in used
        ]
        + [
            StoryFact(
                id=fact_id,
                claim=f"{_LORE_FACT_LABELS.get(row.language, _LORE_FACT_LABELS['en'])}{claim}",
            )
            for fact_id, claim in lore_facts.items()
        ],
    )


def _template_announcement(sheet: FactSheetOut) -> dict[str, str]:
    result = next((f for f in sheet.facts if f.kind == "result"), None)
    if result is None:
        return {}
    texts = {}
    for language in sheet.context.languages:
        claim = result.claim.translate(_BENGALI) if language == "bn" else result.claim
        end = "।" if language == "bn" else "."
        texts[language] = f"{_RESULT_PREFIX[language]}: {claim}{end}"
    return texts


async def draft_announcement(
    db: AsyncSession, clock: Clock, llm: LLMGateway, tournament_id: UUID, kind: str, ref: str
) -> AnnouncementOut | None:
    """Draft a result announcement in every language; the organiser taps to send it."""
    if kind != "result":
        return None
    existing = await db.scalar(
        select(Announcement).where(
            Announcement.tournament_id == tournament_id,
            Announcement.kind == kind,
            Announcement.ref == ref,
        )
    )
    sheet = await analysis.match_fact_sheet(db, clock, UUID(ref), "report")
    if sheet is None:
        return None
    if existing is not None and existing.source.get("fact_sheet_id") == str(sheet.id):
        return _announcement_out(existing)
    author = "template"
    texts = _template_announcement(sheet)
    check: dict[str, Any] = {}
    try:
        written, result, _ = await _draft(
            llm, sheet, await _names(db, tournament_id), "announcement", None
        )
        if result.passed:
            texts = {lang: " ".join(s.text for s in t.sentences) for lang, t in written.items()}
            author = "ai"
        check = result.model_dump()
    except LLMError as exc:
        log.info("announcement_template", ref=ref, reason=str(exc))
    if not texts:
        return None
    async with transaction(db):
        row = existing or Announcement(
            tournament_id=tournament_id, kind=kind, ref=ref, created_at=clock.now()
        )
        row.texts = texts
        row.author_type = author
        row.status = "draft"
        row.source = {"fact_sheet_id": str(sheet.id), "check_result": check}
        if existing is None:
            db.add(row)
    return _announcement_out(row)


def _announcement_out(row: Announcement) -> AnnouncementOut:
    return AnnouncementOut(
        id=row.id,
        kind=row.kind,
        ref=row.ref,
        texts=row.texts,
        author_type=row.author_type,
        status=row.status,
        created_at=row.created_at,
        sent_at=row.sent_at,
    )


async def _require_manager(db: AsyncSession, viewer: Viewer, tournament_id: UUID) -> None:
    if not await analysis.manages(db, viewer, tournament_id):
        raise NotFound()


async def list_announcements(
    db: AsyncSession, viewer: Viewer, tournament_id: UUID
) -> list[AnnouncementOut]:
    """Announcement drafts and sent ones, newest first (organisers)."""
    await _require_manager(db, viewer, tournament_id)
    rows = await db.scalars(
        select(Announcement)
        .where(Announcement.tournament_id == tournament_id)
        .order_by(Announcement.created_at.desc())
    )
    return [_announcement_out(r) for r in rows]


async def send_announcement(
    db: AsyncSession,
    clock: Clock,
    viewer: Viewer,
    tournament_id: UUID,
    announcement_id: UUID,
    live: LiveHub,
) -> AnnouncementOut:
    """One tap: send a draft to everyone following the tournament live."""
    await _require_manager(db, viewer, tournament_id)
    async with transaction(db):
        row = await db.get(Announcement, announcement_id)
        if row is None or row.tournament_id != tournament_id:
            raise NotFound()
        row.status = "sent"
        row.sent_at = clock.now()
    first = next(iter(row.texts.values()))
    data = {"text": first, "texts": row.texts, "author_type": row.author_type}
    if row.author_type == "ai":
        data["ai_labels"] = {lang: AI_LABELS[lang] for lang in row.texts if lang in AI_LABELS}
    await live.publish(
        tournament_channel(tournament_id), envelope("announcement", clock.now(), data)
    )
    return _announcement_out(row)


# --- editorial (called by the editorial module) ------------------------------------------


def _summary(s: Story) -> ReviewSummary:
    return ReviewSummary(
        **_out(s).model_dump(),
        status=s.status,
        review_reason=s.review_reason,
        updated_at=s.updated_at,
        reviewed_by_editor=s.reviewed_by is not None,
        removal_reason=s.removal_reason,
    )


async def _story_row(db: AsyncSession, story_id: UUID) -> Story:
    row = await db.get(Story, story_id)
    if row is None:
        raise NotFound()
    return row


async def stories_in_review(
    db: AsyncSession, reason: str | None = None, limit: int = 50
) -> list[ReviewSummary]:
    """Stories waiting for an editor, oldest first."""
    query = select(Story).where(Story.status == "in_review")
    if reason:
        query = query.where(Story.review_reason == reason)
    rows = await db.scalars(query.order_by(Story.updated_at, Story.id).limit(limit))
    return [_summary(s) for s in rows]


async def editor_stories(db: AsyncSession, status: str, limit: int = 200) -> list[ReviewSummary]:
    """Published or unpublished stories for the editor desk, latest change first."""
    rows = await db.scalars(
        select(Story)
        .where(Story.status == status)
        .order_by(Story.updated_at.desc(), Story.id)
        .limit(limit)
    )
    return [_summary(s) for s in rows]


async def story_summaries(db: AsyncSession, story_ids: list[UUID]) -> dict[UUID, ReviewSummary]:
    """Stories by id, any status (the editor desk names the story of each report)."""
    if not story_ids:
        return {}
    rows = await db.scalars(select(Story).where(Story.id.in_(story_ids)))
    return {s.id: _summary(s) for s in rows}


async def review_item(db: AsyncSession, story_id: UUID) -> ReviewItem:
    """A story with its check result, the whole fact sheet and its earlier versions."""
    row = await _story_row(db, story_id)
    sheet = await analysis.fact_sheet(db, row.fact_sheet_id) if row.fact_sheet_id else None
    versions = await db.scalars(
        select(StoryVersion).where(StoryVersion.story_id == story_id).order_by(StoryVersion.version)
    )
    lore_facts = {
        source["id"]: source["claim"]
        for sentence in row.sentences
        for source in sentence.get("sources", [])
    }
    return ReviewItem(
        **_summary(row).model_dump(),
        sentences=row.sentences,
        check_result=row.check_result,
        facts=[StoryFact(id=f.id, claim=f.claim) for f in (sheet.facts if sheet else [])]
        + [
            StoryFact(
                id=fact_id,
                claim=f"{_LORE_FACT_LABELS.get(row.language, _LORE_FACT_LABELS['en'])}{claim}",
            )
            for fact_id, claim in lore_facts.items()
        ],
        versions=[
            StoryVersionOut(
                version=v.version,
                headline=v.headline,
                body=v.body,
                edited_by=v.edited_by,
                created_at=v.created_at,
            )
            for v in versions
        ],
    )


_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


async def edit_story(
    db: AsyncSession, clock: Clock, editor_id: UUID, story_id: UUID, edit: StoryEdit, version: int
) -> ReviewItem:
    """An editor's new text (If-Match `version`); the old text is kept as a version."""
    async with transaction(db):
        row = await _story_row(db, story_id)
        if row.version != version:
            raise StaleVersion(f"the story is at version {row.version}")
        db.add(
            StoryVersion(
                story_id=row.id,
                version=row.version,
                headline=row.headline,
                body=row.body,
                edited_by=editor_id,
                created_at=clock.now(),
            )
        )
        previous_flavor = next((s for s in row.sentences if s.get("fictional")), None)
        row.headline, row.body = edit.headline, edit.body
        fact_body = _fact_body(edit.body)
        row.sentences = [{"text": s, "facts": []} for s in _SENTENCE_END.split(fact_body) if s]
        flavor_text = _fictional_flavor_text(edit.body, row.language)
        if flavor_text:
            row.sentences.append(
                {
                    "text": flavor_text,
                    "facts": (
                        previous_flavor.get("facts", [])
                        if previous_flavor and previous_flavor["text"] == flavor_text
                        else []
                    ),
                    "fictional": True,
                    "sources": (
                        previous_flavor.get("sources", [])
                        if previous_flavor and previous_flavor["text"] == flavor_text
                        else []
                    ),
                }
            )
        row.check_result = {}
        row.version += 1
        row.updated_at = clock.now()
    return await review_item(db, story_id)


async def check_story(db: AsyncSession, story_id: UUID) -> CheckResult:
    """Run the claim checker on the story's current text (an edited sentence may use any
    fact of the sheet) and store the result."""
    row = await _story_row(db, story_id)
    sheet = await analysis.fact_sheet(db, row.fact_sheet_id) if row.fact_sheet_id else None
    if sheet is None:
        raise ValidationFailed("the story has no fact sheet to check against")
    every = [f.id for f in sheet.facts]
    factual_sentences = [s for s in row.sentences if not s.get("fictional")]
    fiction = next((s for s in row.sentences if s.get("fictional")), None)
    sentences = [
        WrittenSentence(text=s["text"], facts=s.get("facts") or every)
        for s in factual_sentences
    ]
    additional_facts = {
        source["id"]: source["claim"]
        for sentence in row.sentences
        for source in sentence.get("sources", [])
    }
    text = {
        row.language: WrittenText(
            headline=WrittenSentence(text=row.headline, facts=every),
            sentences=sentences,
            fictional_flavor=(
                FictionalFlavor(text=fiction["text"], facts=fiction.get("facts", []))
                if fiction
                else None
            ),
        )
    }
    one = sheet.model_copy(
        update={"context": sheet.context.model_copy(update={"languages": [row.language]})}
    )
    names = await _names(db, row.tournament_id)
    result = checker.check(
        text,
        one,
        names,
        task=row.kind,
        length=_length(sheet, row.kind),
        additional_facts=additional_facts,
    )
    async with transaction(db):
        row.check_result = result.model_dump()
    return result


async def decide_story(
    db: AsyncSession,
    clock: Clock,
    editor_id: UUID,
    story_id: UUID,
    action: StoryAction,
    reason: str | None = None,
) -> ReviewSummary:
    """Approve (publish, labelled "reviewed by an editor"), reject or unpublish a story."""
    async with transaction(db):
        row = await _story_row(db, story_id)
        if action == "approve":
            row.status = "published"
            row.published_at = row.published_at or clock.now()
            row.reviewed_by, row.reviewed_at = editor_id, clock.now()
        elif action == "reject":
            row.status = "blocked"
        else:
            row.status = "unpublished"
            row.removal_reason = reason
        row.updated_at = clock.now()
    return _summary(row)


async def regenerate_story(
    db: AsyncSession, clock: Clock, llm: LLMGateway, story_id: UUID
) -> list[StoryOut]:
    """Write the story again from the current facts (an editor's regenerate)."""
    row = await _story_row(db, story_id)
    return await write_story(
        db,
        clock,
        llm,
        row.subject_type,
        row.subject_id,
        row.kind,
        tournament_id=row.tournament_id,
        force=True,
    )


async def story_tournament(db: AsyncSession, story_id: UUID) -> UUID:
    """The tournament of a published story (correction reports)."""
    row = await _story_row(db, story_id)
    if row.status != "published":
        raise NotFound()
    return row.tournament_id


# --- privacy refresh (docs/09: consent withdrawn, visibility lowered) ----------------------

A_PLAYER = {"en": "a player", "fi": "pelaaja", "bn": "একজন খেলোয়াড়"}


def _redact(text: str, names: list[str], language: str) -> str:
    for name in sorted(names, key=len, reverse=True):
        text = text.replace(name, A_PLAYER.get(language, A_PLAYER["en"]))
    return text


async def refresh_team_content(
    db: AsyncSession, clock: Clock, llm: LLMGateway, tournament_id: UUID, team_id: UUID
) -> int:
    """A player of this team may no longer be named: rewrite the team's stories from the
    new facts, then take every name that is now private out of stories, commentary and
    announcements of the tournament. Returns how many items changed."""
    changed = 0
    for card in await analysis.team_cards(db, Viewer(), team_id):
        changed += len(await write_story(db, clock, llm, "match", card.id, "report"))
    changed += len(
        await write_story(
            db, clock, llm, "team", team_id, "team_recap", tournament_id=tournament_id
        )
    )
    private = (await analysis.names_for_checking(db, tournament_id))["private_players"]
    if not private:
        return changed
    async with transaction(db):
        for story in await db.scalars(select(Story).where(Story.tournament_id == tournament_id)):
            body = _redact(story.body, private, story.language)
            headline = _redact(story.headline, private, story.language)
            if (body, headline) != (story.body, story.headline):
                story.body, story.headline = body, headline
                story.sentences = [
                    {**s, "text": _redact(s["text"], private, story.language)}
                    for s in story.sentences
                ]
                changed += 1
        lines = await db.scalars(
            select(CommentaryItem).where(CommentaryItem.tournament_id == tournament_id)
        )
        for line in lines:
            texts = {
                lang: {**v, "text": _redact(v["text"], private, lang)}
                for lang, v in line.texts.items()
            }
            if texts != line.texts:
                line.texts = texts
                changed += 1
        drafts = await db.scalars(
            select(Announcement).where(Announcement.tournament_id == tournament_id)
        )
        for draft in drafts:
            redacted = {lang: _redact(v, private, lang) for lang, v in draft.texts.items()}
            if redacted != draft.texts:
                draft.texts = redacted
                changed += 1
    log.info("privacy_refresh", team_id=str(team_id), changed=changed)
    return changed


async def list_stories(
    db: AsyncSession,
    params: PageParams,
    *,
    tournament_ids: list[UUID] | None = None,
    language: str | None = None,
) -> Page[StoryOut]:
    """Published stories, newest first (of these tournaments, when given): the news feed."""
    if tournament_ids is not None and not tournament_ids:
        return Page(items=[], next_cursor=None)
    query = select(Story).where(Story.status == "published", Story.published_at.is_not(None))
    if tournament_ids is not None:
        query = query.where(Story.tournament_id.in_(tournament_ids))
    if language:
        query = query.where(Story.language == language)
    if params.cursor:
        position = decode_cursor(params.cursor)
        try:
            at, last = datetime.fromisoformat(str(position["at"])), UUID(str(position["id"]))
        except (KeyError, ValueError):
            raise ValidationFailed("Invalid pagination cursor") from None
        query = query.where(
            or_(Story.published_at < at, and_(Story.published_at == at, Story.id > last))
        )
    rows = list(
        await db.scalars(
            query.order_by(Story.published_at.desc(), Story.id).limit(params.limit + 1)
        )
    )
    items = rows[: params.limit]
    cursor = None
    if len(rows) > params.limit and items[-1].published_at is not None:
        cursor = encode_cursor({"at": items[-1].published_at.isoformat(), "id": str(items[-1].id)})
    return Page(items=[_out(s) for s in items], next_cursor=cursor)


async def organisation_stories(
    db: AsyncSession, organisation_id: UUID, params: PageParams, language: str | None
) -> Page[StoryOut]:
    """Published stories of an organisation's tournaments, newest first."""
    ids = await analysis.organisation_tournament_ids(db, organisation_id)
    return await list_stories(db, params, tournament_ids=ids, language=language)
