"""Personal data redaction before anything reaches an LLM (docs/09, Data minimisation).

Removes phone numbers, emails, Finnish personal identity codes, dates (birth dates in team
lists) and street addresses. The report keeps counts per kind, never the values.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# Order matters: identity codes and emails before phone numbers and dates.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("identity_code", re.compile(r"\b\d{6}[-+A-FUVWXY]\d{3}[0-9A-Y]\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    (
        "date",
        re.compile(
            r"\b(?:\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}|(?:19|20)\d{2}-\d{1,2}-\d{1,2})\b"
        ),
    ),
    ("phone", re.compile(r"(?<![\w])(?:\+\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?){2,4}\d{2,4}\b")),
    (
        "address",
        re.compile(
            r"\b[A-ZÅÄÖ][\wåäöÅÄÖ-]*(?:katu|tie|kuja|polku|väylä|kaari|rinne)\s+\d+[A-Za-z]?"
            r"(?:\s+[A-Z]\s*\d*)?\b"
            r"|\b\d+\s+(?:[A-Z][\w-]*\s+){1,3}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Way)\b",
        ),
    ),
)
_PHONE_MIN_DIGITS = 7


@dataclass(frozen=True)
class Redaction:
    text: str
    counts: dict[str, int] = field(default_factory=dict)  # kind -> how many were removed


def _replace(kind: str, counts: dict[str, int]) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        if kind == "phone" and sum(c.isdigit() for c in match.group()) < _PHONE_MIN_DIGITS:
            return match.group()  # scores, years and shirt numbers are not phone numbers
        counts[kind] = counts.get(kind, 0) + 1
        return f"[{kind}]"

    return replace


def redact(text: str) -> Redaction:
    counts: dict[str, int] = {}
    for kind, pattern in _PATTERNS:
        text = pattern.sub(_replace(kind, counts), text)
    return Redaction(text, counts)


def find_pii(text: str) -> list[str]:
    """Kinds of personal data still present (the gateway's last line of defence)."""
    return sorted(redact(text).counts)
