"""The draft builder settles what it can instead of asking (docs/12-tournament-setup.md §4)."""

from app.modules.setup.extraction import _advancing


def test_teams_through_as_written_when_they_fill_a_bracket() -> None:
    assert _advancing(groups=4, size=5, per_group=2, best_of_rest=0) == (2, 0)
    assert _advancing(groups=6, size=4, per_group=2, best_of_rest=4) == (2, 4)


def test_group_size_read_as_teams_through_falls_back_to_top_two() -> None:
    # "4 groups of 5, top 2 to the quarter-finals" misread as 5 through from each group.
    assert _advancing(groups=4, size=5, per_group=5, best_of_rest=0) == (2, 0)


def test_no_bracket_fits_leaves_the_format_to_format_auto() -> None:
    assert _advancing(groups=3, size=4, per_group=2, best_of_rest=0) is None
