"""Claim checker (docs/07-content-pipeline.md, Claim checker). Deterministic, per language.

A draft passes only if, in every requested language:

1. every number (digits, Bengali digits ০-৯, number and ordinal words in fi/en/bn) appears
   in a fact the sentence cites;
2. every recognised team or player name appears in the fact sheet, and no hidden or
   family-only player is named;
3. status words ("qualified", "champions", "eliminated", …) are backed by a cited fact;
4. no betting vocabulary, and no harsh words in junior content;
5. every claim sentence cites at least one fact, and every cited id exists;
6. the length fits the task and the text is in the right script.

Names are removed before numbers are read, so a team called "FC 1907" is not a number.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.modules.analysis.schemas import Fact, FactSheetOut
from app.modules.content.schemas import (
    CheckIssue,
    CheckResult,
    FictionalFlavor,
    IssueKind,
    NameBook,
    WrittenSentence,
    WrittenText,
)

BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_BENGALI_LETTER = re.compile(r"[ঀ-৿]")
_LATIN_LETTER = re.compile(r"[A-Za-zÅÄÖåäö]")
_DIGITS = re.compile(r"\d+")
_TOKEN = re.compile(r"[\wঀ-৿]+", re.UNICODE)

# Number and ordinal words a sentence may use for a value. Left out because they are mostly
# not numbers: English "one" ("a great one") and "first" ("first half"), Finnish
# "ensimmäinen", Bengali "প্রথম" and "নয়" (also "is not"). Bengali "এক" counts only on its
# own (not "একটি").
NUMBER_WORDS: dict[str, dict[str, int]] = {
    "en": {
        "zero": 0, "nil": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "twenty": 20,
        "twice": 2, "double": 2, "brace": 2,
    },
    "fi": {
        "nolla": 0, "yksi": 1, "kaksi": 2, "kolme": 3, "neljä": 4, "viisi": 5, "kuusi": 6,
        "seitsemän": 7, "kahdeksan": 8, "yhdeksän": 9, "kymmenen": 10,
        "kahdesti": 2, "kolmesti": 3, "hattrick": 3,
    },
    "bn": {
        "শূন্য": 0, "এক": 1, "দুই": 2, "তিন": 3, "চার": 4, "পাঁচ": 5, "ছয়": 6, "সাত": 7,
        "আট": 8, "দশ": 10, "হ্যাটট্রিক": 3,
    },
}  # fmt: skip
# Ordinals must match a position or placement, not any number in the cited facts.
ORDINAL_WORDS: dict[str, dict[str, int]] = {
    "en": {"second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
           "eighth": 8, "runner-up": 2},
    "fi": {"toinen": 2, "toisena": 2, "toiseksi": 2, "kolmas": 3, "kolmantena": 3,
           "kolmanneksi": 3, "neljäs": 4, "neljäntenä": 4, "viides": 5},
    "bn": {"দ্বিতীয়": 2, "তৃতীয়": 3, "চতুর্থ": 4, "পঞ্চম": 5},
}  # fmt: skip
_EN_ORDINAL = re.compile(r"(\d+)(?:st|nd|rd|th)\b", re.I)
_RANKED = ("position", "placement", "table")

# Status concepts: words per language, and the facts that can back them.
STATUS_WORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "qualified": {
        "en": ("qualified", "qualify", "qualifies", "through to", "advance", "advanced"),
        "fi": ("jatkoon", "jatkopaikka", "selviytyi", "pudotuspeleihin", "varmisti paikkansa"),
        "bn": ("পরের পর্বে", "কোয়ালিফাই", "উত্তীর্ণ"),
    },
    "eliminated": {
        "en": ("eliminated", "knocked out", "out of the tournament", "exit"),
        "fi": ("putosi turnauksesta", "putosi jatkosta", "karsiutui", "jatko päättyi"),
        "bn": ("বাদ পড়", "ছিটকে"),
    },
    "champions": {
        "en": ("champions", "champion", "won the tournament", "won the cup", "lifted the"),
        "fi": ("mestari", "voitti turnauksen", "voitti cupin"),
        "bn": ("চ্যাম্পিয়ন", "শিরোপা"),
    },
    "top": {
        "en": ("top of", "tops", "leaders", "lead the group", "won group"),
        "fi": ("kärjessä", "kärkipaikalla", "lohkovoitto", "voitti lohkon"),
        "bn": ("শীর্ষে", "গ্রুপ সেরা"),
    },
    "unbeaten": {
        "en": ("unbeaten", "undefeated", "perfect record"),
        "fi": ("tappioton", "tappiottomana", "voittamaton"),
        "bn": ("অপরাজিত",),
    },
}

BETTING_TERMS: dict[str, tuple[str, ...]] = {
    "en": ("odds", "bet", "bets", "betting", "bookmaker", "bookie", "wager", "punter",
           "accumulator", "favourite to win at"),
    "fi": ("veto", "vedot", "vedonlyönti", "kerroin", "kertoimet", "vedonvälittäjä",
           "pelikohde"),
    "bn": ("বাজি", "জুয়া", "বেটিং"),
}  # fmt: skip
JUNIOR_TERMS: dict[str, tuple[str, ...]] = {
    "en": ("humiliated", "humiliation", "disaster", "collapse", "collapsed", "thrashed",
           "embarrassing", "embarrassed", "useless", "pathetic", "terrible", "mistake by"),
    "fi": ("nöyryytys", "nöyryytti", "katastrofi", "romahdus", "romahti", "surkea",
           "noloa", "virhe"),
    "bn": ("অপমান", "বিপর্যয়", "লজ্জাজনক", "ভরাডুবি"),
}  # fmt: skip

# Words in the body (headline excluded), or sentences: (unit, min, max).
LIMITS: dict[str, tuple[str, int, int]] = {
    "preview": ("words", 60, 120),
    "report:short": ("words", 60, 100),
    "report:standard": ("words", 150, 250),
    "summary": ("words", 200, 350),
    "team_recap": ("words", 80, 150),
    "scenario_explain": ("sentences", 1, 3),
    "prediction_explain": ("sentences", 1, 2),
    "relevance_explain": ("sentences", 1, 1),
    "commentary": ("sentences", 1, 2),
    "announcement": ("sentences", 1, 2),
}
WORD_MARGIN = 0.2  # word targets are for English; fi and bn use fewer, longer words

_STATUS_FACTS: dict[str, tuple[str, ...]] = {
    "qualified": ("qualified",),
    "eliminated": ("eliminated",),
    "champions": (),
    "top": ("group_winner",),
    "unbeaten": ("unbeaten",),
}


@dataclass(frozen=True)
class _Book:
    teams: tuple[str, ...]
    allowed: frozenset[str]  # names the fact sheet itself states
    private: tuple[str, ...]
    public_players: tuple[str, ...]


def _pattern(phrase: str) -> re.Pattern[str]:
    # \b does not work around Bengali vowel signs; look for non-letters instead.
    return re.compile(rf"(?<![\wঀ-৿]){re.escape(phrase)}(?![\wঀ-৿])", re.I)


def _contains(text: str, phrase: str) -> bool:
    return _pattern(phrase).search(text) is not None


def _contains_prefix(text: str, phrase: str) -> bool:
    """Bengali verbs inflect at the end (বাদ পড়েছে); match the stem."""
    return re.search(rf"(?<![\wঀ-৿]){re.escape(phrase)}", text, re.I) is not None


def numbers_in(text: str, language: str) -> list[int]:
    """Every cardinal number a reader would see: digits (Bengali digits too) and words."""
    plain = text.translate(BENGALI_DIGITS)
    if language == "en":
        plain = _EN_ORDINAL.sub(" ", plain)  # "2nd" is a position, read by ordinals_in
    found = [int(d) for d in _DIGITS.findall(plain)]
    words = NUMBER_WORDS.get(language, {})
    found += [words[t] for t in _TOKEN.findall(plain.lower()) if t in words]
    if language == "en":
        found += [3] * len(re.findall(r"hat-trick", plain, re.I))
    return found


def ordinals_in(text: str, language: str) -> list[int]:
    """Positions a reader would see: "2nd", "second", "toisena", "দ্বিতীয়"."""
    plain = text.translate(BENGALI_DIGITS)
    found = [int(d) for d in _EN_ORDINAL.findall(plain)] if language == "en" else []
    words = ORDINAL_WORDS.get(language, {})
    found += [words[t] for t in _TOKEN.findall(plain.lower()) if t in words]
    if language == "en":
        found += [2] * len(re.findall(r"runner-up", plain, re.I))
    return found


def _fact_ordinals(facts: Sequence[Fact]) -> set[int]:
    ranks: set[int] = set()
    for f in facts:
        if f.kind in _RANKED and isinstance(f.value, int) and not isinstance(f.value, bool):
            ranks.add(f.value)
        ranks.update(int(d) for d in _EN_ORDINAL.findall(f.claim))
        if f.kind == "placement" and "runner-up" in f.claim:
            ranks.add(2)
    return ranks


def _strip_names(text: str, names: Iterable[str]) -> str:
    """Remove names (and any case ending after them) so their digits are not read."""
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(
            rf"(?<![\w\u0980-\u09FF]){re.escape(name)}[\w\u0980-\u09FF]*", " ", text, flags=re.I
        )
    return text


def _fact_numbers(facts: Sequence[Fact], names: Iterable[str]) -> set[int]:
    values: set[int] = set()
    for f in facts:
        values.update(numbers_in(_strip_names(f.claim, names), "en"))
        if isinstance(f.value, bool):
            continue
        if isinstance(f.value, int):
            values.add(f.value)
        elif isinstance(f.value, float):
            values.update({round(f.value), round(f.value * 100)})
        elif isinstance(f.value, str):
            values.update(int(d) for d in _DIGITS.findall(f.value))
    return values


def _status_backed(concept: str, cited: Sequence[Fact]) -> bool:
    for f in cited:
        if f.kind in _STATUS_FACTS[concept]:
            return True
        if concept == "qualified" and f.kind == "status" and f.value == "clinched":
            return True
        if concept == "eliminated" and f.kind == "status" and f.value == "eliminated":
            return True
        if concept == "champions" and f.kind == "placement" and f.value == 1:
            return True
        if concept == "top" and f.kind == "position" and f.value == 1:
            return True
        if any(_contains(f.claim, w) for w in STATUS_WORDS[concept]["en"]):
            return True
    return False


class _Checker:
    def __init__(self, sheet: FactSheetOut, book: _Book) -> None:
        self.sheet = sheet
        self.facts = {f.id: f for f in sheet.facts}
        self.book = book
        self.junior = sheet.context.tone_profile == "junior"
        self.issues: list[CheckIssue] = []

    def issue(self, language: str, sentence: str, kind: IssueKind, detail: str) -> None:
        self.issues.append(
            CheckIssue(language=language, sentence=sentence, kind=kind, detail=detail)
        )

    def sentence(self, language: str, s: WrittenSentence) -> None:
        text = s.text
        unknown = [i for i in s.facts if i not in self.facts]
        if unknown:
            self.issue(language, text, "fact_ref", f"cites unknown facts {unknown}")
        cited = [self.facts[i] for i in s.facts if i in self.facts]
        names = self._names(language, text)
        stripped = _strip_names(text, self.book.teams + self.book.public_players)
        numbers = numbers_in(stripped, language)
        allowed = _fact_numbers(cited, self.book.teams + self.book.public_players)
        for n in numbers:
            if n not in allowed:
                self.issue(language, text, "number", f"{n} is not in the cited facts")
        ranks = ordinals_in(stripped, language)
        for n in ranks:
            if n not in _fact_ordinals(cited):
                self.issue(language, text, "number", f"position {n} is not in the cited facts")
        statuses = [
            concept
            for concept, words in STATUS_WORDS.items()
            if any(
                (_contains_prefix if language == "bn" else _contains)(text, w)
                for w in words.get(language, ())
            )
        ]
        for concept in statuses:
            if not _status_backed(concept, cited):
                self.issue(language, text, "status", f"'{concept}' is not backed by a cited fact")
        banned = BETTING_TERMS.get(language, ()) + (
            JUNIOR_TERMS.get(language, ()) if self.junior else ()
        )
        for term in banned:
            if (_contains_prefix if language == "bn" else _contains)(text, term):
                self.issue(language, text, "banned", f"'{term}' is not allowed")
        if (numbers or ranks or names or statuses) and not s.facts:
            self.issue(language, text, "fact_ref", "a claim sentence cites no fact")

    def _names(self, language: str, text: str) -> list[str]:
        # Finnish and Bengali add case endings to names (Roversia, FC-কে).
        match = _contains if language == "en" else _contains_prefix
        found = []
        for name in self.book.private:
            if match(text, name):
                self.issue(language, text, "hidden_name", "names a player who is not public")
        for name in self.book.teams + self.book.public_players:
            if match(text, name):
                found.append(name)
                if name not in self.book.allowed:
                    self.issue(language, text, "name", f"'{name}' is not in the fact sheet")
        return found

    def length(self, language: str, draft: WrittenText, task: str) -> None:
        if task not in LIMITS:
            return
        unit, low, high = LIMITS[task]
        if unit == "sentences":
            count = len(draft.sentences)
            ok = low <= count <= high
        else:
            count = sum(len(_TOKEN.findall(s.text)) for s in draft.sentences)
            ok = low * (1 - WORD_MARGIN) <= count <= high * (1 + WORD_MARGIN)
        if not ok:
            self.issue(language, "", "length", f"{count} {unit}; {task} needs {low}-{high}")

    def script(self, language: str, draft: WrittenText) -> None:
        text = " ".join(s.text for s in draft.sentences)
        text = _strip_names(text, self.book.teams + self.book.public_players + self.book.private)
        bengali = len(_BENGALI_LETTER.findall(text))
        latin = len(_LATIN_LETTER.findall(text))
        wrong = latin > bengali if language == "bn" else bengali > 0
        if wrong:
            self.issue(language, "", "language", f"text is not written in '{language}'")


def check(
    drafts: dict[str, WrittenText],
    sheet: FactSheetOut,
    names: NameBook,
    *,
    task: str,
    length: str | None = None,
    additional_facts: dict[str, str] | None = None,
) -> CheckResult:
    """Check a draft in every language of the fact sheet's context.

    `task` is the writing task (`report`, `commentary`, …); `length` picks `short` or
    `standard` for reports.
    """
    extra = [
        Fact(
            id=fact_id,
            kind="fictional_background",
            claim=claim,
            source="team_backgrounds.json",
        )
        for fact_id, claim in (additional_facts or {}).items()
    ]
    claims = " ".join(f.claim for f in [*sheet.facts, *extra])
    book = _Book(
        teams=tuple(names.teams),
        allowed=frozenset(n for n in names.teams + names.players if _contains(claims, n)),
        private=tuple(names.private_players),
        public_players=tuple(names.players),
    )
    checker = _Checker(sheet, book)
    checker.facts.update({fact.id: fact for fact in extra})
    limit_key = f"{task}:{length}" if task == "report" else task
    for language in sheet.context.languages:
        draft = drafts.get(language)
        if draft is None or not draft.sentences:
            checker.issue(language, "", "language", f"no text in '{language}'")
            continue
        for s in ([draft.headline] if draft.headline else []) + draft.sentences:
            checker.sentence(language, s)
        checker.length(language, draft, limit_key)
        checker.script(language, draft)
        if draft.fictional_flavor:
            _check_fictional_flavor(
                checker,
                language,
                draft.fictional_flavor,
                {
                    fact_id
                    for fact_id in (additional_facts or {})
                    if fact_id.endswith(f"_{language}")
                },
            )
    return CheckResult(passed=not checker.issues, issues=checker.issues)


def _check_fictional_flavor(
    checker: _Checker,
    language: str,
    flavor: FictionalFlavor,
    allowed_sources: set[str],
) -> None:
    """Check lore citations separately from match facts; do not require match-fact IDs."""
    if not flavor.facts or any(fact_id not in allowed_sources for fact_id in flavor.facts):
        checker.issue(
            language,
            flavor.text,
            "fiction",
            "fictional flavor must cite only supplied team-background facts",
        )
        return
    checker.sentence(language, WrittenSentence(text=flavor.text, facts=flavor.facts))
    stripped = _strip_names(
        flavor.text,
        checker.book.teams + checker.book.public_players + checker.book.private,
    )
    bengali = len(_BENGALI_LETTER.findall(stripped))
    latin = len(_LATIN_LETTER.findall(stripped))
    wrong_script = latin > bengali if language == "bn" else bengali > 0
    if wrong_script:
        checker.issue(language, flavor.text, "language", f"text is not written in '{language}'")
    parts = re.split(r"(?<=[.!?।])\s+", flavor.text.strip())
    if len(parts) > len(flavor.facts):
        checker.issue(
            language,
            flavor.text,
            "fiction",
            "fictional flavor may contain at most one sentence per cited team background",
        )
    if len(_TOKEN.findall(flavor.text)) > 40:
        checker.issue(
            language, flavor.text, "fiction", "fictional flavor must be no longer than 40 words"
        )
