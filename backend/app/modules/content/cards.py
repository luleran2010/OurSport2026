"""Share cards and the venue screen rotation (docs/06, Livecast).

Cards are 1200×630 SVG images (the size link previews use) drawn from read models: a
match card (teams, score or kick-off, tournament) and a story card (headline and the AI
label). The screen rotation turns the venue screen read model, the latest commentary,
sent announcements and the newest story into timed panels.
"""

from datetime import timedelta
from html import escape
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.time import Clock
from app.core.viewer import Viewer
from app.modules.analysis import service as analysis
from app.modules.content import commentary
from app.modules.content.models import Announcement, CommentaryItem, Story
from app.modules.content.schemas import ScreenPanel, ScreenRotation
from app.modules.content.service import AI_LABELS, story_label

WIDTH, HEIGHT = 1200, 630
SHORT_AI = {"en": "AI-written", "fi": "Tekoälyn kirjoittama", "bn": "এআই-এর লেখা"}
_FONT = "Noto Sans, Noto Sans Bengali, Arial, sans-serif"
ANNOUNCEMENT_WINDOW = timedelta(minutes=30)


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines[:4]


def _svg(body: str, footer: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="{_FONT}">'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#0b3d2e"/><stop offset="1" stop-color="#14532d"/>'
        "</linearGradient></defs>"
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#bg)"/>{body}'
        f'<text x="60" y="{HEIGHT - 40}" font-size="26" fill="#a7f3d0">{escape(footer)}</text>'
        "</svg>"
    )


def _text(
    x: int,
    y: int,
    size: int,
    text: str,
    *,
    weight: int = 400,
    anchor: str = "start",
    fill: str = "#ffffff",
) -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
        f'text-anchor="{anchor}" fill="{fill}">{escape(text)}</text>'
    )


async def match_card(db: AsyncSession, viewer: Viewer, match_id: UUID) -> str:
    """The match as a share image: teams, the score (or kick-off), the tournament."""
    card = await analysis.match_card(db, viewer, match_id)
    tournament = await analysis.visible_tournament(
        db, viewer, await analysis.match_tournament_id(db, match_id)
    )
    home = card.home.name if card.home else card.home_source or "?"
    away = card.away.name if card.away else card.away_source or "?"
    if card.score is not None and card.status in ("live", "finished"):
        middle = f"{card.score.home_goals} - {card.score.away_goals}"
    else:
        middle = card.starts_at.strftime("%d.%m. %H:%M UTC")
    stage = f"Group {card.group}" if card.group else card.stage.replace("_", " ")
    body = (
        _text(60, 110, 34, tournament.name, weight=600, fill="#a7f3d0")
        + _text(60, 160, 28, stage, fill="#d1fae5")
        + _text(WIDTH // 2, 300, 56, home, weight=700, anchor="middle")
        + _text(WIDTH // 2, 400, 88, middle, weight=800, anchor="middle")
        + _text(WIDTH // 2, 490, 56, away, weight=700, anchor="middle")
        + (
            _text(WIDTH - 60, 110, 30, "LIVE", weight=800, anchor="end", fill="#f87171")
            if card.status == "live"
            else ""
        )
    )
    return _svg(body, "OurSport")


async def story_card(db: AsyncSession, viewer: Viewer, story_id: UUID) -> str:
    """A published story as a share image, with its AI label."""
    row = await db.get(Story, story_id)
    if row is None or row.status != "published":
        raise NotFound()
    tournament = await analysis.visible_tournament(db, viewer, row.tournament_id)
    lines = _wrap(row.headline, 34)
    body = _text(60, 110, 34, tournament.name, weight=600, fill="#a7f3d0") + "".join(
        _text(60, 220 + 80 * n, 60, line, weight=700) for n, line in enumerate(lines)
    )
    footer = "OurSport"
    if row.author_type == "ai":
        footer += f" · {SHORT_AI.get(row.language, SHORT_AI['en'])}"
    return _svg(body, footer)


async def screen_rotation(
    db: AsyncSession, clock: Clock, viewer: Viewer, tournament_id: UUID
) -> ScreenRotation:
    """Timed panels for the venue big screen: live matches, the latest commentary line of
    each, next up, every group table, announcements of the last half hour, newest story."""
    screen = await analysis.screen(db, viewer, tournament_id)
    panels: list[ScreenPanel] = []
    if screen.now_playing:
        panels.append(
            ScreenPanel(
                kind="now_playing",
                seconds=15,
                data={"matches": [m.model_dump(mode="json") for m in screen.now_playing]},
            )
        )
        lines = []
        for m in screen.now_playing:
            if not await analysis.can_watch_live(db, viewer, m.id):
                continue
            latest = await db.scalar(
                select(CommentaryItem)
                .where(CommentaryItem.match_id == m.id)
                .order_by(CommentaryItem.created_at.desc())
                .limit(1)
            )
            if latest is not None:
                lines.append(commentary.commentary_out(latest).model_dump(mode="json"))
        if lines:
            panels.append(ScreenPanel(kind="commentary", seconds=10, data={"lines": lines}))
    if screen.next_up:
        panels.append(
            ScreenPanel(
                kind="next_up",
                seconds=10,
                data={"matches": [m.model_dump(mode="json") for m in screen.next_up]},
            )
        )
    for table in screen.standings:
        panels.append(ScreenPanel(kind="standings", seconds=12, data=table.model_dump(mode="json")))
    since = clock.now() - ANNOUNCEMENT_WINDOW
    sent = await db.scalars(
        select(Announcement)
        .where(
            Announcement.tournament_id == tournament_id,
            Announcement.status == "sent",
            Announcement.sent_at >= since,
        )
        .order_by(Announcement.sent_at.desc())
    )
    for a in sent:
        data: dict[str, Any] = {"texts": a.texts, "author_type": a.author_type}
        if a.author_type == "ai":
            data["ai_labels"] = {lang: AI_LABELS[lang] for lang in a.texts if lang in AI_LABELS}
        panels.append(ScreenPanel(kind="announcement", seconds=10, data=data))
    newest = await db.scalars(
        select(Story)
        .where(Story.tournament_id == tournament_id, Story.status == "published")
        .order_by(Story.published_at.desc())
        .limit(3)
    )
    stories = [
        {
            "id": str(s.id),
            "language": s.language,
            "headline": s.headline,
            "ai_label": story_label(s),
        }
        for s in newest
    ]
    if stories:
        panels.append(ScreenPanel(kind="story", seconds=10, data={"stories": stories}))
    return ScreenRotation(tournament_id=tournament_id, generated_at=clock.now(), panels=panels)
