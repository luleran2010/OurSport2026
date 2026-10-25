"""Club portal C5: club profile (name, logo, colours, town, sports, description) and sponsors.

Images (club logo, sponsor logos) are uploaded with POST /uploads as the raw file body and kept in memory
(mock storage: they are gone after a restart). The profile then refers to them by their /uploads/{id} URL.
"""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING

from fastapi import HTTPException

from .mock_data import CLUBS, SPORTS, TEAMS
from .models import Club, ClubProfile, Sponsor, Upload

if TYPE_CHECKING:
    from .store import FeedStore, Session

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}  # no SVG: it can carry scripts
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_UPLOADS = 200  # mock storage keeps the latest ones
_MAGIC = {"image/png": b"\x89PNG", "image/jpeg": b"\xff\xd8", "image/gif": b"GIF8", "image/webp": b"RIFF"}
URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.I)


def sports_in_use(club_id: str) -> list[str]:
    return sorted({TEAMS[t].sport for t in CLUBS[club_id].team_ids if t in TEAMS})


def profile(store: FeedStore, club_id: str) -> ClubProfile:
    return ClubProfile(club=CLUBS[club_id], sports=[s for s in SPORTS if s.id != "all"],
                       sports_in_use=sports_in_use(club_id), updated_at=store.now)


# ---- uploads -----------------------------------------------------------------------------

def save_upload(store: FeedStore, content_type: str, data: bytes) -> Upload:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype not in IMAGE_TYPES:
        raise HTTPException(415, {"code": "image_type", "message": "Upload a PNG, JPEG, WebP or GIF image."})
    if not data:
        raise HTTPException(422, {"code": "empty", "message": "The file is empty."})
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, {"code": "too_large", "message": "Images can be at most 2 MB."})
    if not data.startswith(_MAGIC[ctype]):
        raise HTTPException(415, {"code": "image_type", "message": "That file isn’t a valid image."})
    uid = secrets.token_urlsafe(12)
    store.uploads[uid] = (ctype, data)
    while len(store.uploads) > MAX_UPLOADS:
        store.uploads.pop(next(iter(store.uploads)))
    return Upload(id=uid, url=f"/uploads/{uid}", content_type=ctype, size=len(data))


def _check_image_url(store: FeedStore, url: str | None) -> None:
    if url is None:
        return
    m = re.fullmatch(r"/uploads/([\w-]+)", url)
    if not m or m.group(1) not in store.uploads:
        raise HTTPException(422, {"code": "image", "message": "Upload the image first (POST /uploads)."})


# ---- profile -----------------------------------------------------------------------------

def update(store: FeedStore, club_id: str, body, fields: set[str]) -> Club:
    club = CLUBS[club_id]
    data = {f: getattr(body, f) for f in fields}
    if "logo_url" in data:
        _check_image_url(store, data["logo_url"])
    if "sports" in data:
        sports = list(dict.fromkeys(data["sports"]))
        known = {s.id for s in SPORTS if s.id != "all"}
        if not set(sports) <= known:
            raise HTTPException(422, {"code": "sport", "message": "Unknown sport."})
        missing = set(sports_in_use(club_id)) - set(sports)
        if missing:
            names = ", ".join(s.label for s in SPORTS if s.id in missing)
            raise HTTPException(409, {"code": "sport_in_use", "message": f"The club’s teams play {names}. Remove the team first."})
        data["sports"] = sorted(sports)
    for key in ("name", "city", "description", "short"):
        if key in data and isinstance(data[key], str):
            data[key] = data[key].strip()
    if data.get("short"):
        data["short"] = data["short"].upper()
    for key in ("color", "secondary_color"):
        if data.get(key):
            data[key] = data[key].lower()
    for key in ("name", "short", "color", "city", "sports"):  # required fields can't be cleared
        if key in data and data[key] is None:
            data.pop(key)
    for key, value in data.items():
        setattr(club, key, value)
    return club


# ---- sponsors ----------------------------------------------------------------------------

def _clean_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = f"https://{url}"
    if not URL_RE.match(url):
        raise HTTPException(422, {"code": "url", "message": "Check the link (e.g. https://example.com)."})
    return url


def _sponsor(club: Club, sponsor_id: str) -> Sponsor:
    sp = next((s for s in club.sponsors if s.id == sponsor_id), None)
    if sp is None:
        raise HTTPException(404, "Sponsor not found")
    return sp


def add_sponsor(store: FeedStore, club_id: str, body) -> Sponsor:
    club = CLUBS[club_id]
    if len(club.sponsors) >= 20:
        raise HTTPException(409, {"code": "too_many", "message": "A club can list up to 20 sponsors."})
    if any(s.name.lower() == body.name.strip().lower() for s in club.sponsors):
        raise HTTPException(409, {"code": "sponsor_exists", "message": "This sponsor is already on the list."})
    _check_image_url(store, body.logo_url)
    sp = Sponsor(id=f"sp-{secrets.token_hex(4)}", name=body.name.strip(), url=_clean_url(body.url),
                 logo_url=body.logo_url, show_on=list(dict.fromkeys(body.show_on)))
    club.sponsors = [*club.sponsors, sp]
    return sp


def update_sponsor(store: FeedStore, club_id: str, sponsor_id: str, body, fields: set[str]) -> Sponsor:
    sp = _sponsor(CLUBS[club_id], sponsor_id)
    if "logo_url" in fields:
        _check_image_url(store, body.logo_url)
        sp.logo_url = body.logo_url
    if "url" in fields:
        sp.url = _clean_url(body.url)
    if "name" in fields and body.name:
        sp.name = body.name.strip()
    if "show_on" in fields and body.show_on is not None:
        sp.show_on = list(dict.fromkeys(body.show_on))
    return sp


def remove_sponsor(club_id: str, sponsor_id: str) -> None:
    club = CLUBS[club_id]
    sp = _sponsor(club, sponsor_id)
    club.sponsors = [s for s in club.sponsors if s is not sp]


def report_sponsors(store: FeedStore, match_id: str | None) -> list[Sponsor]:
    """Sponsors shown under a match report: both clubs' sponsors that chose "reports"."""
    m = store.get_match(match_id or "")
    if m is None:
        return []
    out = []
    for club_id in dict.fromkeys([m.home.club_id, m.away.club_id]):
        club = CLUBS.get(club_id)
        out += [s for s in (club.sponsors if club else []) if "reports" in s.show_on]
    return out
