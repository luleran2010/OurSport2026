"""Fictional team flavor stored outside the application database."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

CORPUS_PATH = Path(__file__).with_name("team_backgrounds.json")


class TeamBackground(BaseModel):
    model_config = ConfigDict(extra="forbid")

    en: str
    fi: str
    bn: str


class TeamBackgroundRequest(BaseModel):
    team_names: list[str]


class TeamBackgroundResponse(BaseModel):
    teams: dict[str, TeamBackground]


def background_fact_id(team_name: str, language: str) -> str:
    digest = hashlib.sha256(team_name.casefold().encode("utf-8")).hexdigest()[:12]
    return f"lore_{digest}_{language}"


def with_fact_ids(
    backgrounds: dict[str, dict[str, str]],
) -> dict[str, dict[str, dict[str, str]]]:
    """Give each localized external lore entry a stable citeable ID."""
    return {
        team_name: {
            language: {
                "id": background_fact_id(team_name, language),
                "text": text,
            }
            for language, text in localized.items()
        }
        for team_name, localized in backgrounds.items()
    }


def source_claims(
    backgrounds: dict[str, dict[str, dict[str, str]]], language: str
) -> dict[str, str]:
    """Return the localized synthetic evidence claims supplied to the writer."""
    return {
        entry["id"]: entry["text"]
        for localized in backgrounds.values()
        if (entry := localized.get(language)) is not None
    }


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


def find_team_backgrounds(names: list[str]) -> dict[str, dict[str, str]]:
    """Exact normalized team-name lookup; player names are never searched or stored."""
    if not CORPUS_PATH.exists():
        return {}
    raw: Any = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError(f"unsupported team background corpus format: {CORPUS_PATH}")
    entries = raw.get("teams")
    if not isinstance(entries, dict):
        raise ValueError(f"team background corpus has no teams mapping: {CORPUS_PATH}")
    indexed: dict[str, tuple[str, TeamBackground]] = {}
    for team_name, value in entries.items():
        if not isinstance(team_name, str):
            raise ValueError(f"invalid team name in {CORPUS_PATH}")
        normalised_name = _normalise(team_name)
        if normalised_name in indexed:
            raise ValueError(f"duplicate normalized team name {team_name!r} in {CORPUS_PATH}")
        try:
            indexed[normalised_name] = (
                team_name,
                TeamBackground.model_validate(value),
            )
        except ValidationError as exc:
            raise ValueError(f"invalid background for team {team_name!r}: {exc}") from exc
    found: dict[str, dict[str, str]] = {}
    for name in names:
        match = indexed.get(_normalise(name))
        if match is not None:
            _, background = match
            found[name] = background.model_dump()
    return found
