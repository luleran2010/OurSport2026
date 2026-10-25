"""Demo data: a 3-day community cup and a junior league, built by the real setup pipeline.

    uv run python -m app.scripts.seed

Uses the fake LLM provider with recorded extraction answers, so it needs no API key.
Idempotent: tournaments that already exist (by slug) are left alone. All names are
invented.
"""

import asyncio
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.llm import FakeProvider, LLMGateway
from app.core.logging import configure_logging
from app.core.redis_client import create_redis
from app.core.time import Clock, SystemClock
from app.core.viewer import Viewer
from app.modules.accounts import service as accounts
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import FilmingPolicy, OrganisationCreate
from app.modules.scoring import service as scoring
from app.modules.setup import service as setup
from app.modules.setup.schemas import SetupStart

log = structlog.get_logger("seed")
DATA = Path(__file__).parent / "seed_data"
ORGANISER_EMAIL = "demo.organiser@example.com"
MIME = {".csv": "text/csv", ".txt": "text/plain"}


@dataclass(frozen=True)
class DemoTournament:
    folder: str
    name: str
    age_group: str
    starts_on: dt.date
    ends_on: dt.date
    league: bool = False
    played_share: float = 0.0
    sport: Literal["football", "futsal"] = "football"


CUP = DemoTournament(
    "cup", "Demo Community Cup 2026", "adult", dt.date(2026, 6, 12), dt.date(2026, 6, 14)
)
FUTSAL = DemoTournament(
    "futsal",
    "Demo Futsal Cup 2026",
    "adult",
    dt.date(2026, 11, 14),
    dt.date(2026, 11, 14),
    sport="futsal",
)
JUNIOR = DemoTournament(
    "junior",
    "Demo Junior League U12",
    "u12",
    dt.date(2026, 9, 5),
    dt.date(2026, 9, 26),
    league=True,
    played_share=0.5,
)


async def _build(
    db: AsyncSession,
    clock: Clock,
    llm: LLMGateway,
    viewer: Viewer,
    org_id: Any,
    demo: DemoTournament,
) -> str:
    slug = competitions.slugify(demo.name)
    for candidate in [slug, *(f"{slug}-{n}" for n in range(2, 10))]:
        existing = await competitions.find_tournament(db, candidate)
        if existing and existing.status != "draft":  # a failed earlier run may leave a draft
            return f"{candidate}: already there"
    case = json.loads((DATA / demo.folder / "case.json").read_text())
    llm._provider = FakeProvider(responses=case["llm"])  # recorded answers for this tournament
    session = await setup.start(
        db,
        clock,
        viewer,
        SetupStart(
            organisation_id=org_id,
            name=demo.name,
            sport=demo.sport,
            age_group=demo.age_group,
            starts_on=demo.starts_on,
            ends_on=demo.ends_on,
        ),
    )
    for f in case["files"]:
        path = DATA / demo.folder / f["file"]
        await setup.add_file(
            db,
            clock,
            viewer,
            session.id,
            kind=f["kind"],
            filename=path.name,
            mime=MIME.get(path.suffix, ""),
            data=path.read_bytes(),
        )
    out = await setup.run_extraction(db, clock, llm, viewer, session.id)
    if demo.league:
        out = await setup.change(db, clock, viewer, session.id, "format", "league", None)
    if out.status != "ready":
        questions = [q.text for q in out.draft.open_questions] if out.draft else []
        raise RuntimeError(f"{demo.name} is not ready: {out.status} {questions}")
    filming: FilmingPolicy = "notice" if demo.age_group == "adult" else "consent_required"
    published = await setup.publish(db, clock, viewer, session.id, None, filming)
    matches = await competitions.list_matches(db, published.tournament_id)
    played = matches[: int(len(matches) * demo.played_share)]
    for i, match in enumerate(played):
        if match.home_team_id and match.away_team_id:
            score: dict[str, object] = {
                "home_goals": (i * 7) % 4,
                "away_goals": (i * 3) % 3,
                "decided_by": "regulation",
            }
            await competitions.record_result(db, match.id, score)
    return f"{slug}: {published.teams} teams, {published.matches} matches, {len(played)} played"


async def seed(settings: Settings, clock: Clock | None = None) -> list[str]:
    """Create the demo organiser, organisation and tournaments (skipping existing ones)."""
    clock = clock or SystemClock()
    scoring.register(settings, clock)  # pitch scorer passes at publish
    engine = create_engine(settings)
    redis = create_redis(settings)
    llm = LLMGateway(FakeProvider(), settings, redis, clock)
    try:
        async with create_sessionmaker(engine)() as db:
            user = await accounts.ensure_user(db, clock, ORGANISER_EMAIL, "Demo Organiser")
            viewer = Viewer(user_id=user)
            org_slug = "demo-community-sports"
            existing = await competitions.find_organisation(db, org_slug)
            org_id = (
                existing
                or (
                    await competitions.create_organisation(
                        db,
                        clock,
                        viewer,
                        OrganisationCreate(
                            kind="community",
                            name="Demo Community Sports",
                            sports=["football", "futsal"],
                            accept_processing_terms=True,
                        ),
                    )
                ).id
            )
            return [await _build(db, clock, llm, viewer, org_id, t) for t in (CUP, FUTSAL, JUNIOR)]
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    configure_logging()
    for line in asyncio.run(seed(get_settings())):
        log.info("seeded", result=line)


if __name__ == "__main__":
    main()
