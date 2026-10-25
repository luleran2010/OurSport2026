from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    """One problem found in a configuration.

    `code` is stable and machine-readable; `path` points at the offending field
    (`points.table.tie`, `seeding.separations[0].teams[1]`); `message` is plain language
    for the organiser.
    """

    code: str
    path: str
    message: str


class InvalidConfig(ValueError):
    """Raised by `ensure_valid` with every issue found, not just the first."""

    def __init__(self, issues: Sequence[Issue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(f"{issue.path}: {issue.message}" for issue in self.issues))
