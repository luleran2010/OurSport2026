"""Tournament structure: groups, knockout bracket, match counts and placeholder sources.

Placeholder grammar (used wherever a knockout slot is not yet a team):
`group:A:1` (1st in group A), `best_rest:2` (2nd-best team among those ranked across
groups, e.g. best thirds), `winner:QF1`, `loser:SF1`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from string import ascii_uppercase
from typing import Literal

from pydantic import Field

from engine.rules.base import RuleModel
from engine.rules.config import AdvancementRule

KnockoutRound = Literal["round_of_16", "quarter_final", "semi_final", "final"]
DrawDecider = Literal["penalties", "extra_time_then_penalties"]

ROUND_ORDER: tuple[KnockoutRound, ...] = ("round_of_16", "quarter_final", "semi_final", "final")
ROUND_SIZE: dict[KnockoutRound, int] = {
    "round_of_16": 16,
    "quarter_final": 8,
    "semi_final": 4,
    "final": 2,
}
_ROUND_CODE: dict[KnockoutRound, str] = {
    "round_of_16": "R16_",
    "quarter_final": "QF",
    "semi_final": "SF",
    "final": "F",
}
THIRD_PLACE_CODE = "3P"
MAX_GROUPS = len(ascii_uppercase)


class KnockoutSpec(RuleModel):
    rounds: list[KnockoutRound] = Field(min_length=1)
    third_place_match: bool = False
    crossover: Literal["standard", "custom"] = "standard"  # standard: A1-B2, B1-A2, …
    # First-round pairs as placeholder sources, used when crossover is "custom".
    custom_pairs: list[tuple[str, str]] = Field(default_factory=list)
    draws_decided_by: DrawDecider = "penalties"
    final_draws_decided_by: DrawDecider | None = None  # None: same as the other rounds


class FormatSpec(RuleModel):
    team_count: int = Field(ge=2)
    # [4, 4, 4, 4] or [4, 4, 3]; empty for a pure knockout.
    group_sizes: list[int] = Field(default_factory=list)
    group_rounds: Literal[1, 2] = 1  # single or double round robin
    knockout: KnockoutSpec | None = None

    @property
    def group_count(self) -> int:
        return len(self.group_sizes)

    @property
    def group_letters(self) -> list[str]:
        return [group_letter(i) for i in range(self.group_count)]


@dataclass(frozen=True)
class FormatChoice:
    """A format together with the advancement rule it was built for."""

    format: FormatSpec
    advancement: AdvancementRule


def group_letter(index: int) -> str:
    return ascii_uppercase[index]


def group_source(letter: str, position: int) -> str:
    return f"group:{letter}:{position}"


def best_rest_source(rank: int) -> str:
    return f"best_rest:{rank}"


def winner_source(match_code: str) -> str:
    return f"winner:{match_code}"


def loser_source(match_code: str) -> str:
    return f"loser:{match_code}"


def round_label(round_: KnockoutRound) -> str:
    return round_.replace("_", " ")


def round_match_codes(round_: KnockoutRound) -> list[str]:
    if round_ == "final":
        return ["F"]
    return [f"{_ROUND_CODE[round_]}{i}" for i in range(1, ROUND_SIZE[round_] // 2 + 1)]


def group_match_count(fmt: FormatSpec) -> int:
    return sum(size * (size - 1) // 2 for size in fmt.group_sizes) * fmt.group_rounds


def group_match_codes(fmt: FormatSpec) -> list[str]:
    """Codes `A1`… per group; which pairing each code is gets fixed by the schedule."""
    per_group = [size * (size - 1) // 2 * fmt.group_rounds for size in fmt.group_sizes]
    return [
        f"{group_letter(g)}{n}" for g, count in enumerate(per_group) for n in range(1, count + 1)
    ]


def knockout_match_codes(fmt: FormatSpec) -> list[str]:
    """Knockout codes in playing order; the third-place match precedes the final."""
    if fmt.knockout is None:
        return []
    codes: list[str] = []
    for round_ in fmt.knockout.rounds:
        if round_ == "final" and fmt.knockout.third_place_match:
            codes.append(THIRD_PLACE_CODE)
        codes.extend(round_match_codes(round_))
    return codes


def knockout_match_count(fmt: FormatSpec) -> int:
    return len(knockout_match_codes(fmt))


def total_match_count(fmt: FormatSpec) -> int:
    return group_match_count(fmt) + knockout_match_count(fmt)


def all_match_codes(fmt: FormatSpec) -> list[str]:
    return group_match_codes(fmt) + knockout_match_codes(fmt)


def max_matches_per_team(fmt: FormatSpec) -> int:
    """Most matches any one team can play: largest group, then every knockout round."""
    group = (max(fmt.group_sizes) - 1) * fmt.group_rounds if fmt.group_sizes else 0
    return group + (len(fmt.knockout.rounds) if fmt.knockout else 0)


def qualifier_sources(fmt: FormatSpec, advancement: AdvancementRule) -> list[str]:
    """Placeholder sources of every team entering the knockout, in seeding order."""
    if not fmt.group_sizes:
        return [f"seed:{i}" for i in range(1, fmt.team_count + 1)]
    sources = [
        group_source(letter, position)
        for letter in fmt.group_letters
        for position in range(1, advancement.per_group + 1)
    ]
    sources += [best_rest_source(rank) for rank in range(1, advancement.best_of_rest + 1)]
    return sources


def first_round_for(qualifiers: int) -> KnockoutRound | None:
    for round_ in ROUND_ORDER:
        if ROUND_SIZE[round_] == qualifiers:
            return round_
    return None


def rounds_from(first: KnockoutRound) -> list[KnockoutRound]:
    return list(ROUND_ORDER[ROUND_ORDER.index(first) :])


def _bracket_sizes() -> str:
    return ", ".join(str(ROUND_SIZE[r]) for r in reversed(ROUND_ORDER))


def groups_then_knockout(
    group_sizes: Sequence[int],
    *,
    per_group: int,
    best_of_rest: int = 0,
    third_place_match: bool = False,
    draws_decided_by: DrawDecider = "penalties",
    final_draws_decided_by: DrawDecider | None = None,
) -> FormatChoice:
    """Build a group stage feeding a knockout bracket that the qualifiers fill exactly."""
    qualifiers = len(group_sizes) * per_group + best_of_rest
    if best_of_rest > len(group_sizes):
        raise ValueError(f"best_of_rest={best_of_rest} exceeds {len(group_sizes)} groups")
    first = first_round_for(qualifiers)
    if first is None:
        raise ValueError(
            f"{qualifiers} qualifiers cannot fill a knockout bracket "
            f"(supported sizes: {_bracket_sizes()})"
        )
    knockout = KnockoutSpec(
        rounds=rounds_from(first),
        third_place_match=third_place_match,
        draws_decided_by=draws_decided_by,
        final_draws_decided_by=final_draws_decided_by,
    )
    fmt = FormatSpec(team_count=sum(group_sizes), group_sizes=list(group_sizes), knockout=knockout)
    return FormatChoice(fmt, AdvancementRule(per_group=per_group, best_of_rest=best_of_rest))


def league(team_count: int, *, double: bool = False) -> FormatChoice:
    """Everyone plays everyone (once, or home and away); the table decides."""
    fmt = FormatSpec(
        team_count=team_count, group_sizes=[team_count], group_rounds=2 if double else 1
    )
    return FormatChoice(fmt, AdvancementRule(per_group=1))


def knockout_only(team_count: int, *, third_place_match: bool = False) -> FormatChoice:
    first = first_round_for(team_count)
    if first is None:
        raise ValueError(
            f"a knockout of {team_count} teams needs a bracket of {_bracket_sizes()} teams; "
            "byes are not supported yet"
        )
    knockout = KnockoutSpec(rounds=rounds_from(first), third_place_match=third_place_match)
    return FormatChoice(
        FormatSpec(team_count=team_count, knockout=knockout), AdvancementRule(per_group=0)
    )
