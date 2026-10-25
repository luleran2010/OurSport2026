import time
from collections import Counter
from collections.abc import Sequence
from typing import Literal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.draw import Draw, DrawInfeasible, SeedEntry, make_draw
from engine.rng import DeterministicRng
from engine.rules.format import FormatSpec
from engine.rules.seeding import FixedPlacement, SeedingPolicy, SeedingSource, Separation

PLACEMENT_FIRST = [SeedingSource.PREVIOUS_PLACEMENT, SeedingSource.RATING, SeedingSource.NONE]


def fmt(*sizes: int) -> FormatSpec:
    return FormatSpec(team_count=sum(sizes), group_sizes=list(sizes))


def entries(n: int, *, placed: int = 0) -> list[SeedEntry]:
    """Teams t00…; the first `placed` have last edition's placements 1…placed."""
    return [
        SeedEntry(team=f"t{i:02d}", previous_placement=i + 1 if i < placed else None)
        for i in range(n)
    ]


def policy(**overrides: object) -> SeedingPolicy:
    values: dict[str, object] = {"source": PLACEMENT_FIRST}
    values.update(overrides)
    return SeedingPolicy.model_validate(values)


def seed(n: int) -> bytes:
    return n.to_bytes(8, "big")


def group_of(draw: Draw) -> dict[str, int]:
    return {team: g for g, members in enumerate(draw.groups) for team in members}


def assert_valid(
    draw: Draw, teams: Sequence[SeedEntry], spec: FormatSpec, pol: SeedingPolicy
) -> None:
    where = group_of(draw)
    assert sorted(where) == sorted(e.team for e in teams)
    assert [len(members) for members in draw.groups] == spec.group_sizes
    if pol.pots == "by_group_position":
        for pot in draw.pots:
            assert len({where[t] for t in pot}) == len(pot)  # one team per pot per group
    for separation in pol.separations:
        limit = 1 if separation.kind == "distinct_groups" else separation.max_per_group
        counts = Counter(where[t] for t in separation.teams)
        assert max(counts.values()) <= limit
    for fixed in pol.fixed:
        assert where[fixed.team] == fixed.group_index
        if fixed.position_in_group is not None:
            members = draw.groups[fixed.group_index]
            assert members[fixed.position_in_group - 1] == fixed.team


# --- deterministic random numbers ------------------------------------------------------------


def test_rng_is_reproducible_and_unbiased_in_range() -> None:
    a, b = DeterministicRng(b"seed"), DeterministicRng(b"seed")

    first = [a.randbelow(6) for _ in range(600)]

    assert first == [b.randbelow(6) for _ in range(600)]
    assert set(first) == set(range(6))
    assert first != [DeterministicRng(b"other").randbelow(6) for _ in range(600)]


def test_rng_shuffle_is_a_permutation() -> None:
    items = list(range(20))

    shuffled = DeterministicRng(b"x").shuffled(items)

    assert sorted(shuffled) == items
    assert shuffled != items


# --- pots and seeding ------------------------------------------------------------------------


def test_previous_placement_puts_last_years_top_four_in_pot_one() -> None:
    teams = entries(16, placed=8)

    draw = make_draw(teams, fmt(4, 4, 4, 4), policy(), seed=seed(1))

    assert sorted(draw.pots[0]) == ["t00", "t01", "t02", "t03"]
    assert sorted(draw.pots[1]) == ["t04", "t05", "t06", "t07"]
    by_team = {p.team: p for p in draw.placements}
    assert by_team["t01"].pot == 1
    assert by_team["t01"].seeded_by is SeedingSource.PREVIOUS_PLACEMENT
    assert by_team["t01"].seed_value == 2
    assert by_team["t12"].seeded_by is SeedingSource.NONE
    # Position in the group follows the pot: pot 1 teams are A1, B1, …
    assert all(draw.groups[g][0] in draw.pots[0] for g in range(4))


def test_rating_ranks_teams_without_a_previous_placement() -> None:
    teams = [
        SeedEntry("champ", previous_placement=1),
        SeedEntry("strong", rating=1700.0),
        SeedEntry("weak", rating=1400.0),
        SeedEntry("new"),
    ]

    draw = make_draw(teams, fmt(2, 2), policy(), seed=seed(3))

    assert draw.pots == (("champ", "strong"), ("weak", "new"))


def test_organiser_order_is_a_seeding_source() -> None:
    teams = [SeedEntry(f"t{i}", organiser_rank=i) for i in (3, 1, 4, 2)]
    pol = policy(source=[SeedingSource.ORGANISER_ORDER])

    draw = make_draw(teams, fmt(2, 2), pol, seed=seed(3))

    assert draw.pots == (("t1", "t2"), ("t3", "t4"))


def test_unequal_groups_put_the_last_pot_in_the_bigger_groups() -> None:
    draw = make_draw(entries(11, placed=11), fmt(4, 4, 3), policy(), seed=seed(5))

    assert [len(p) for p in draw.pots] == [3, 3, 3, 2]
    where = group_of(draw)
    assert {where[t] for t in draw.pots[3]} <= {0, 1}


# --- constraints -----------------------------------------------------------------------------


def test_previous_semi_finalists_are_kept_apart_in_every_draw() -> None:
    teams = entries(16, placed=4)
    semis = Separation(teams=["t00", "t01", "t02", "t03"], reason="2025 semi-finalists")
    clubs = Separation(teams=["t04", "t09", "t14"], reason="same organisation")
    pol = policy(
        source=[SeedingSource.PREVIOUS_PLACEMENT, SeedingSource.NONE], separations=[semis, clubs]
    )

    for n in range(50):
        assert_valid(
            make_draw(teams, fmt(4, 4, 4, 4), pol, seed=seed(n)), teams, fmt(4, 4, 4, 4), pol
        )


def test_host_fixed_in_group_a_position_one() -> None:
    teams = entries(16, placed=16)
    pol = policy(fixed=[FixedPlacement(team="t10", group_index=0, position_in_group=1)])

    for n in range(20):
        draw = make_draw(teams, fmt(4, 4, 4, 4), pol, seed=seed(n))
        assert draw.groups[0][0] == "t10"
        assert_valid(draw, teams, fmt(4, 4, 4, 4), pol)
    host = next(p for p in draw.placements if p.team == "t10")
    assert host.fixed


def test_placements_explain_separations() -> None:
    teams = entries(8, placed=2)
    pol = policy(separations=[Separation(teams=["t00", "t01"], reason="2025 finalists")])

    draw = make_draw(teams, fmt(4, 4), pol, seed=seed(9))

    finalist = next(p for p in draw.placements if p.team == "t00")
    assert finalist.kept_apart == ("2025 finalists",)
    assert finalist.group in ("A", "B")


# --- reproducibility -------------------------------------------------------------------------


def test_same_seed_same_draw_and_input_order_does_not_matter() -> None:
    teams = entries(16, placed=6)
    pol = policy(separations=[Separation(teams=["t00", "t01", "t02", "t03"], reason="semis")])

    first = make_draw(teams, fmt(4, 4, 4, 4), pol, seed=seed(42))
    again = make_draw(list(reversed(teams)), fmt(4, 4, 4, 4), pol, seed=seed(42))

    assert first == again
    assert first.seed == seed(42)
    others = {make_draw(teams, fmt(4, 4, 4, 4), pol, seed=seed(n)).groups for n in range(10)}
    assert len(others) > 1


# --- fairness: every valid draw equally likely -----------------------------------------------

# 6 unseeded teams into 2 groups of 3, with a and b kept apart: 12 valid draws.
SMALL_TEAMS = [SeedEntry(t) for t in "abcdef"]
SMALL_POLICY = SeedingPolicy(
    source=[SeedingSource.NONE],
    pots="none",
    separations=[Separation(teams=["a", "b"], reason="rivals")],
)
CHI_SQUARE_11_DOF_P001 = 31.26


def _chi_square(draws: list[Draw]) -> tuple[int, float]:
    counts = Counter(tuple(frozenset(g) for g in d.groups) for d in draws)
    expected = len(draws) / len(counts)
    return len(counts), sum((c - expected) ** 2 / expected for c in counts.values())


def test_enumeration_is_uniform_over_valid_draws() -> None:
    draws = [make_draw(SMALL_TEAMS, fmt(3, 3), SMALL_POLICY, seed=seed(n)) for n in range(3000)]

    assert draws[0].method == "enumeration"
    assert draws[0].uniform
    assert draws[0].valid_draws == 12
    distinct, chi_square = _chi_square(draws)
    assert distinct == 12
    assert chi_square < CHI_SQUARE_11_DOF_P001


def test_rejection_sampling_is_uniform_over_valid_draws() -> None:
    draws = [
        make_draw(SMALL_TEAMS, fmt(3, 3), SMALL_POLICY, seed=seed(n), enumeration_limit=0)
        for n in range(3000)
    ]

    assert draws[0].method == "rejection"
    assert draws[0].uniform
    distinct, chi_square = _chi_square(draws)
    assert distinct == 12
    assert chi_square < CHI_SQUARE_11_DOF_P001


def test_randomized_search_fallback_is_valid_but_not_claimed_uniform() -> None:
    draw = make_draw(
        SMALL_TEAMS, fmt(3, 3), SMALL_POLICY, seed=seed(1), enumeration_limit=0, max_rejections=0
    )

    assert draw.method == "randomized_search"
    assert not draw.uniform
    assert_valid(draw, SMALL_TEAMS, fmt(3, 3), SMALL_POLICY)


# --- infeasible constraints ------------------------------------------------------------------


def test_six_separated_teams_into_four_groups_is_a_minimal_conflict() -> None:
    teams = entries(16, placed=8)
    quarter_finalists = Separation(
        teams=[f"t{i:02d}" for i in range(6)], reason="2025 quarter-finalists"
    )
    harmless = Separation(teams=["t10", "t11"], reason="same organisation")

    with pytest.raises(DrawInfeasible) as caught:
        make_draw(
            teams, fmt(4, 4, 4, 4), policy(separations=[harmless, quarter_finalists]), seed=seed(1)
        )

    assert caught.value.conflict == (quarter_finalists,)
    assert str(caught.value) == (
        "6 teams (2025 quarter-finalists) must be in different groups, but there are only 4 groups"
    )


def test_minimal_conflict_drops_rules_that_are_not_part_of_it() -> None:
    teams = [SeedEntry(t) for t in "abcdef"]
    ab = Separation(teams=["a", "b"], reason="ab")
    de = Separation(teams=["d", "e"], reason="de")
    ac = Separation(teams=["a", "c"], reason="ac")
    bc = Separation(teams=["b", "c"], reason="bc")
    pol = SeedingPolicy(source=[SeedingSource.NONE], pots="none", separations=[ab, de, ac, bc])

    with pytest.raises(DrawInfeasible) as caught:
        make_draw(teams, fmt(3, 3), pol, seed=seed(1))

    # a, b, c pairwise apart cannot fit 2 groups; d-e apart is not part of the conflict,
    # and dropping any of the three pairs makes the rest possible (the conflict is unique).
    assert caught.value.conflict == (ab, ac, bc)  # in the policy's order


def test_fixed_placements_can_be_part_of_a_conflict() -> None:
    teams = entries(8, placed=8)
    apart = Separation(teams=["t00", "t07"], reason="finalists")
    pol = policy(
        separations=[apart],
        fixed=[
            FixedPlacement(team="t00", group_index=0),
            FixedPlacement(team="t07", group_index=0),
        ],
    )

    with pytest.raises(DrawInfeasible) as caught:
        make_draw(teams, fmt(4, 4), pol, seed=seed(1))

    assert apart in caught.value.conflict
    assert len(caught.value.conflict) == 3


def test_bad_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="16 teams"):
        make_draw(entries(15), fmt(4, 4, 4, 4), policy(), seed=seed(1))
    with pytest.raises(ValueError, match="twice"):
        make_draw([*entries(7), SeedEntry("t00")], fmt(4, 4), policy(), seed=seed(1))
    with pytest.raises(ValueError, match="groups"):
        make_draw(entries(8), FormatSpec(team_count=8), policy(), seed=seed(1))


# --- properties and performance --------------------------------------------------------------


@st.composite
def draw_cases(draw_fn: st.DrawFn) -> tuple[list[SeedEntry], FormatSpec, SeedingPolicy, bytes]:
    group_count = draw_fn(st.integers(min_value=2, max_value=6))
    sizes = [draw_fn(st.integers(min_value=3, max_value=4)) for _ in range(group_count)]
    n = sum(sizes)
    teams = entries(n, placed=draw_fn(st.integers(min_value=0, max_value=n)))
    ids = [e.team for e in teams]
    separations = [
        Separation(teams=chosen, reason=f"rule {i}")
        for i, chosen in enumerate(
            draw_fn(
                st.lists(
                    st.lists(st.sampled_from(ids), min_size=2, max_size=group_count, unique=True),
                    max_size=3,
                )
            )
        )
    ]
    pots: Literal["by_group_position", "none"] = draw_fn(
        st.sampled_from(["by_group_position", "none"])
    )
    pol = SeedingPolicy(source=PLACEMENT_FIRST, pots=pots, separations=separations)
    return teams, fmt(*sizes), pol, draw_fn(st.binary(min_size=1, max_size=16))


@settings(max_examples=150, deadline=None)
@given(draw_cases())
def test_every_draw_satisfies_every_constraint(
    case: tuple[list[SeedEntry], FormatSpec, SeedingPolicy, bytes],
) -> None:
    teams, spec, pol, seed_bytes = case
    try:
        draw = make_draw(teams, spec, pol, seed=seed_bytes)
    except DrawInfeasible as infeasible:
        assert infeasible.conflict  # always names the rules that clash
        return
    assert_valid(draw, teams, spec, pol)


def test_thirty_two_teams_with_eight_separations_is_fast() -> None:
    teams = entries(32, placed=8)
    quarter_finalists = Separation(
        teams=[f"t{i:02d}" for i in range(8)], reason="quarter-finalists"
    )
    clubs = [
        Separation(teams=[f"t{8 + i:02d}", f"t{20 + i:02d}"], reason=f"club {i}") for i in range(7)
    ]
    pol = policy(separations=[quarter_finalists, *clubs])

    started = time.perf_counter()
    draw = make_draw(teams, fmt(*[4] * 8), pol, seed=seed(7))
    elapsed = time.perf_counter() - started

    assert_valid(draw, teams, fmt(*[4] * 8), pol)
    assert draw.method == "rejection"
    assert elapsed < 1.0
