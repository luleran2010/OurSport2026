from collections.abc import Callable

from app.core.config import Settings
from app.scripts.seed import seed


async def test_seed_builds_the_demo_and_is_idempotent(
    database_url: str, make_settings: Callable[..., Settings]
) -> None:
    settings = make_settings(database_url=database_url)

    first = await seed(settings)
    second = await seed(settings)

    assert any("16 teams, 32 matches" in line for line in first) or all(
        "already there" in line for line in first
    )
    assert any("8 teams, 28 matches, 14 played" in line for line in first) or all(
        "already there" in line for line in first
    )
    assert any("futsal" in line and "8 teams, 16 matches" in line for line in first) or all(
        "already there" in line for line in first
    )
    assert all("already there" in line for line in second)
