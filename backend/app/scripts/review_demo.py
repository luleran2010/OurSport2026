"""Demo work for the editor desk: AI stories the claim checker holds for review.

    uv run python -m app.scripts.review_demo [--count 3]

Rewrites a few published AI stories (reports, previews, summaries) with the offline writer
plus one wrong sentence each (a score that never happened, a claim no fact backs, betting
talk). The checker flags it, the retry keeps it, so each story waits in the review queue as
`blocked_claim` and is hidden from fans until an editor approves, fixes or rejects it.
Local and test environments only; needs no API key. Run `seed` first.
"""

import argparse
import asyncio
from collections.abc import Callable
from typing import Any, cast

import structlog
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.llm import FakeProvider, LLMGateway
from app.core.logging import configure_logging
from app.core.pagination import PageParams
from app.core.time import SystemClock
from app.modules.content import fake_writer
from app.modules.content import service as content

log = structlog.get_logger("review_demo")

# One wrong sentence per story, citing the first fact so it reads as part of the report.
WRONG = [
    "It finished 9-9 in the end, the highest score of the tournament.",
    "The winners are now certain to lift the trophy on the final day.",
    "Anyone who bet on the underdogs today won big at the bookmakers.",
]


class _RunCache:
    """Stands in for Redis for this run only, so the wrong drafts never reach the shared
    LLM cache (later rewrites of these stories must not get them back)."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self._data.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self._data[key] = value

    async def incrby(self, key: str, amount: int) -> int:
        self._data[key] = int(self._data.get(key, 0)) + amount
        return int(self._data[key])

    async def expire(self, key: str, seconds: int) -> bool:
        return True


def _writer(sentence: str) -> Callable[[str, str], dict[str, Any]]:
    def write(task: str, prompt: str) -> dict[str, Any]:
        good = fake_writer.write(task, prompt)
        for text in good.values():
            cited: list[str] = next((s["facts"] for s in text["sentences"] if s["facts"]), [])
            text["sentences"].insert(1, {"text": sentence, "facts": cited[:1]})
        return good

    return write


async def make_review_work(settings: Settings, count: int) -> list[str]:
    if settings.env not in ("local", "test"):
        raise SystemExit("review_demo writes demo data: local and test environments only")
    engine = create_engine(settings)
    clock = SystemClock()
    held: list[str] = []
    try:
        async with create_sessionmaker(engine)() as db:
            feed = await content.list_stories(db, PageParams(limit=100), language="en")
            subjects = list(
                dict.fromkeys(
                    (s.subject_type, s.subject_id, s.kind, s.tournament_id)
                    for s in feed.items
                    if s.author_type == "ai"
                )
            )
            if not subjects:
                raise SystemExit("no published AI stories yet: run the seed first")
            for i, (subject_type, subject_id, kind, tournament_id) in enumerate(subjects[:count]):
                writer = _writer(WRONG[i % len(WRONG)])
                provider = FakeProvider(responses={f"{kind}.v1": writer})
                llm = LLMGateway(provider, settings, cast(Redis, _RunCache()), clock)
                await content.write_story(
                    db,
                    clock,
                    llm,
                    subject_type,
                    subject_id,
                    kind,
                    tournament_id=tournament_id,
                    force=True,
                )
            queue = await content.stories_in_review(db)
            held = [f"{s.language} · {s.review_reason} · {s.headline}" for s in queue]
    finally:
        await engine.dispose()
    return held


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--count", type=int, default=3, help="how many stories (each in every language)"
    )
    args = parser.parse_args()
    for line in asyncio.run(make_review_work(get_settings(), args.count)):
        log.info("in_review", story=line)


if __name__ == "__main__":
    main()
