"""Printables (docs/06, docs/12 §7): pitch sheets with the scorer QR code and the day's
matches, and the venue filming notice with a QR to the privacy notice and opt-out.

Served as print-ready HTML (A4, one sheet per page); the organiser prints or saves it as
PDF from the browser. QR codes are inline SVG (`segno`), so nothing is fetched.
"""

from datetime import datetime
from html import escape
from uuid import UUID
from zoneinfo import ZoneInfo

import segno
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFound
from app.core.viewer import Viewer
from app.modules.competitions import service as competitions
from app.modules.media import service
from app.modules.scoring import service as scoring

TITLES = {
    "pitch": {"en": "Scorer pass", "fi": "Kirjurin passi", "bn": "স্কোরার পাস"},
    "how": {
        "en": "Scan with your phone, tap Start at kick-off, then tap each goal and card.",
        "fi": "Skannaa puhelimella, paina Aloita avauspotkussa ja sitten jokainen maali ja kortti.",
        "bn": "ফোন দিয়ে স্ক্যান করুন, খেলা শুরুতে Start চাপুন, তারপর প্রতিটি গোল ও কার্ড চাপুন।",
    },
    "notice": {"en": "Filming notice", "fi": "Kuvausilmoitus", "bn": "ভিডিও করার বিজ্ঞপ্তি"},
    "privacy": {
        "en": "Privacy notice and opt-out",
        "fi": "Tietosuojaseloste ja kieltäytyminen",
        "bn": "গোপনীয়তা বিজ্ঞপ্তি ও না চাওয়ার উপায়",
    },
}
_STYLE = """
@page { size: A4; margin: 16mm; }
body { font-family: "Noto Sans", "Noto Sans Bengali", Arial, sans-serif; color: #111; }
.sheet { page-break-after: always; }
.sheet:last-child { page-break-after: auto; }
h1 { font-size: 28pt; margin: 0 0 4mm; } h2 { font-size: 16pt; margin: 6mm 0 2mm; }
.qr svg { width: 70mm; height: 70mm; }
table { border-collapse: collapse; width: 100%; font-size: 12pt; }
td, th { border-bottom: 1px solid #ccc; padding: 2mm; text-align: left; }
.small { font-size: 10pt; color: #444; }
"""


def qr_svg(url: str) -> str:
    return str(segno.make(url, error="m").svg_inline(scale=4, border=2))


def _page(title: str, sheets: list[str], language: str) -> str:
    body = "\n".join(f'<section class="sheet">{s}</section>' for s in sheets)
    return (
        f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head><body>{body}</body></html>"
    )


def _local(value: datetime, zone: str) -> str:
    return value.astimezone(ZoneInfo(zone)).strftime("%a %d.%m. %H:%M")


async def pitch_sheets(
    db: AsyncSession, settings: Settings, viewer: Viewer, tournament_id: UUID
) -> str:
    """One sheet per pitch: its scorer QR code, how to score, and its matches."""
    passes = await scoring.list_passes(db, settings, viewer, tournament_id)  # organisers only
    tournament = await competitions.get_tournament(db, viewer, tournament_id)
    languages = tournament.settings.languages
    pitches = {p.id: p.name for p in await competitions.pitches_of(db, tournament_id)}
    names = {str(e.team_id): e.name for e in await competitions.entries_of(db, tournament_id)}
    matches = await competitions.list_matches(db, tournament_id)
    sheets = []
    for scorer_pass in passes:
        if scorer_pass.revoked or scorer_pass.pitch_id is None:
            continue
        rows = []
        for m in sorted(matches, key=lambda m: m.starts_at):
            if m.pitch_id != scorer_pass.pitch_id:
                continue
            home = names.get(str(m.home_team_id), m.home_source or "?")
            away = names.get(str(m.away_team_id), m.away_source or "?")
            rows.append(
                f"<tr><td>{escape(_local(m.starts_at, tournament.time_zone))}</td>"
                f"<td>{escape(m.code)}</td><td>{escape(home)} - {escape(away)}</td></tr>"
            )
        titles = " · ".join(TITLES["pitch"][lang] for lang in languages)
        how = "".join(f"<p>{escape(TITLES['how'][lang])}</p>" for lang in languages)
        sheets.append(
            f"<h1>{escape(pitches.get(scorer_pass.pitch_id, scorer_pass.label))}</h1>"
            f"<p class='small'>{escape(tournament.name)} · {escape(titles)}</p>"
            f"<div class='qr'>{qr_svg(scorer_pass.scan_url)}</div>{how}"
            f"<table><tr><th>⏱</th><th>#</th><th></th></tr>{''.join(rows)}</table>"
            f"<p class='small'>{escape(scorer_pass.label)} · "
            f"{escape(_local(scorer_pass.valid_until, tournament.time_zone))}</p>"
        )
    if not sheets:
        raise NotFound("no pitch passes yet")
    return _page(f"{tournament.name} - pitch sheets", sheets, languages[0])


async def filming_notice_sheet(
    db: AsyncSession, settings: Settings, viewer: Viewer, tournament_id: UUID
) -> str:
    """The venue filming notice in every tournament language, with the privacy QR."""
    if not await competitions.manages(db, viewer, tournament_id):
        raise NotFound()
    notice = await service.notice(db, viewer, tournament_id)
    tournament = await competitions.get_tournament(db, viewer, tournament_id)
    url = f"{settings.web_base_url}/tournaments/{tournament_id}/filming"
    texts = "".join(
        f"<h2>{escape(TITLES['notice'][lang])}</h2><p>{escape(text)}</p>"
        for lang, text in notice.texts.items()
    )
    privacy = " · ".join(TITLES["privacy"][lang] for lang in notice.texts)
    sheet = (
        f"<h1>📹 {escape(tournament.name)}</h1>{texts}"
        f"<div class='qr'>{qr_svg(url)}</div><p class='small'>{escape(privacy)}: {escape(url)}</p>"
    )
    return _page(f"{tournament.name} - filming notice", [sheet], next(iter(notice.texts), "en"))
