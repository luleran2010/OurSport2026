"""Deterministic team-list parsing: tables, pasted lists and WhatsApp messages.

Only when this fails does the setup ask the LLM (`teams_extract.v1`), and then only with
redacted text.
"""

import re
from collections.abc import Sequence

_NAME_HEADERS = {
    "team",
    "teams",
    "team name",
    "name",
    "joukkue",
    "joukkueet",
    "nimi",
    "দল",
    "দলের নাম",
}
_ORG_HEADERS = {
    "club", "organisation", "organization", "association", "seura", "yhdistys", "ক্লাব", "সংগঠন",
}  # fmt: skip
_WHATSAPP_PREFIX = re.compile(
    r"^\[?\d{1,2}[./]\d{1,2}[./]\d{2,4},?\s+\d{1,2}[:.]\d{2}(?::\d{2})?(?:\s?[AaPp][Mm])?\]?"
    r"\s*(?:-\s*)?[^:]{1,40}:\s*"
)
_BULLET = re.compile(r"^\s*(?:[-*•▪︎·]+|\d{1,3}[.)]|[a-z][.)])\s*")
_IN_BRACKETS = re.compile(r"^(?P<name>.+?)\s*[(\[](?P<org>[^)\]]+)[)\]]\s*$")
_MAX_NAME = 60
_MIN_TEAMS = 2

type Team = tuple[str, str | None]  # (name, organisation)


def _clean(cell: str) -> str:
    return " ".join(cell.split()).strip(" ,;")


def _plausible(name: str) -> bool:
    return (
        bool(name)
        and len(name) <= _MAX_NAME
        and not name.startswith("[")  # a redacted phone or email left on its own
        and not name.endswith("?")
        and any(c.isalpha() for c in name)
    )


def teams_from_rows(rows: Sequence[Sequence[str]]) -> list[Team] | None:
    """Teams from a spreadsheet or CSV; the header row (if any) says which column is which."""
    rows = [[_clean(c) for c in row] for row in rows if any(c.strip() for c in row)]
    if not rows:
        return None
    header = [c.casefold() for c in rows[0]]
    name_col = next((i for i, h in enumerate(header) if h in _NAME_HEADERS), None)
    org_col = next((i for i, h in enumerate(header) if h in _ORG_HEADERS), None)
    body = rows[1:] if name_col is not None or org_col is not None else rows
    name_col = 0 if name_col is None else name_col
    teams: list[Team] = []
    for row in body:
        name = row[name_col] if name_col < len(row) else ""
        org = row[org_col] if org_col is not None and org_col < len(row) else None
        if _plausible(name):
            teams.append((name, org or None))
    return teams if len(teams) >= _MIN_TEAMS else None


def teams_from_text(text: str) -> list[Team] | None:
    """Teams from a pasted list or a WhatsApp message, one team per line."""
    lines = [line for line in text.splitlines() if line.strip()]
    teams: list[Team] = []
    for line in lines:
        line = _BULLET.sub("", _WHATSAPP_PREFIX.sub("", line)).strip()
        org = None
        match = _IN_BRACKETS.match(line)
        if match:
            line, org = match["name"], _clean(match["org"])
        name = _clean(line)
        if _plausible(name) and ":" not in name and len(name.split()) <= 6:
            teams.append((name, org))
    if len(teams) < _MIN_TEAMS or len(teams) < 0.6 * len(lines):
        return None
    return teams
