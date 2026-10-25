"""Load test (docs/10-operations.md, Performance targets).

    uv run python -m app.scripts.loadtest                       # API started in-process
    uv run python -m app.scripts.loadtest --base http://host:8000
    uv run python -m app.scripts.loadtest --viewers 200 --live 10 --cups 1 --pitches 4

Provisions its own cups through the real setup pipeline (fake LLM, recorded answers, the
first one on 8 pitches), starts the live matches (all pitches of the first cup, the rest
from the others), then measures with real clients:

- 1,000 WebSocket viewers on one match: time from posting a goal to each viewer receiving
  it (target p95 < 2 s, at least 99% delivered);
- a goal posted to every live match each round, spread over `--spread_ms` (default 1 s;
  0 posts them all in the same instant) (`POST /matches/{id}/events`, target p95 < 200 ms);
- public reads under concurrency (target p95 < 150 ms) and personal pages (p95 < 300 ms).

Prints a JSON report; with `--check` exits 1 when a target is missed. Load generator and
server share one machine in the in-process mode, so treat those numbers as a lower bound.
Uses the dev dependencies (httpx2, websockets).
"""

import argparse
import asyncio
import contextlib
import datetime as dt
import json
import resource
import socket
import statistics
import sys
import time
from collections.abc import Awaitable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2 as httpx
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from websockets.asyncio.client import connect

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.llm import FakeProvider, LLMGateway
from app.core.logging import configure_logging
from app.core.redis_client import create_redis
from app.core.security import AccessClaims, encode_access_token
from app.core.time import SystemClock
from app.core.viewer import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, Viewer
from app.modules.accounts import service as accounts
from app.modules.competitions import service as competitions
from app.modules.competitions.schemas import OrganisationCreate
from app.modules.scoring import service as scoring
from app.modules.setup import service as setup
from app.modules.setup.schemas import SetupStart

CUP = Path(__file__).parent / "seed_data" / "cup"
MIME = {".csv": "text/csv", ".txt": "text/plain"}
TARGETS = {
    "event_p95_ms": 2000,
    "delivered": 0.99,
    "post_p95_ms": 200,
    "read_p95_ms": 150,
    "personal_p95_ms": 300,
}
CSRF = "loadtest-csrf"


@dataclass
class Plan:
    viewers: int = 1000
    live: int = 50
    cups: int = 3
    pitches: int = 8
    rounds: int = 5
    reads: int = 600
    concurrency: int = 50
    spread_ms: int = 1000  # each round's goals arrive over this window (0: all at once)


@dataclass
class Report:
    viewers_connected: int = 0
    live_matches: int = 0
    pitches_live_in_main_cup: int = 0
    delivered: float = 0.0
    event_ms: dict[str, float] = field(default_factory=dict)
    post_ms: dict[str, float] = field(default_factory=dict)
    read_ms: dict[str, float] = field(default_factory=dict)
    personal_ms: dict[str, float] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


def summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {
        "n": len(values),
        "p50": round(statistics.median(ordered), 1),
        "p95": round(p95, 1),
        "max": round(ordered[-1], 1),
    }


async def provision(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, plan: Plan
) -> list[tuple[UUID, UUID]]:
    """Publish `cups` copies of the demo cup (the first on `pitches` pitches); returns
    (tournament id, owner id) of each."""
    clock = SystemClock()
    case = json.loads((CUP / "case.json").read_text())
    redis = create_redis(settings)
    run = uuid4().hex[:6]
    out = []
    try:
        async with sessions() as db:
            owner = await accounts.ensure_user(
                db, clock, f"loadtest-{run}@example.com", "Load Test"
            )
            viewer = Viewer(user_id=owner)
            org = await competitions.create_organisation(
                db,
                clock,
                viewer,
                OrganisationCreate(
                    kind="community",
                    name=f"Load Test {run}",
                    sports=["football"],
                    accept_processing_terms=True,
                ),
            )
            for n in range(plan.cups):
                answers = json.loads(json.dumps(case["llm"]))
                if n == 0:
                    answers["schedule_extract.v1"]["pitches"]["value"] = plan.pitches
                await redis.flushdb()
                llm = LLMGateway(FakeProvider(responses=answers), settings, redis, clock)
                session = await setup.start(
                    db,
                    clock,
                    viewer,
                    SetupStart(
                        organisation_id=org.id,
                        name=f"Load Test Cup {run} {n + 1}",
                        starts_on=dt.date(2026, 6, 12),
                        ends_on=dt.date(2026, 6, 14),
                    ),
                )
                for f in case["files"]:
                    path = CUP / f["file"]
                    await setup.add_file(
                        db,
                        clock,
                        viewer,
                        session.id,
                        kind=f["kind"],
                        filename=path.name,
                        mime=MIME.get(path.suffix, "text/plain"),
                        data=path.read_bytes(),
                    )
                await setup.run_extraction(db, clock, llm, viewer, session.id)
                published = await setup.publish(db, clock, viewer, session.id, None, "notice")
                out.append((published.tournament_id, owner))
    finally:
        await redis.aclose()
    return out


async def start_matches(
    sessions: async_sessionmaker[AsyncSession], cups: list[tuple[UUID, UUID]], plan: Plan
) -> tuple[list[tuple[UUID, UUID]], int]:
    """Kick off one match on every pitch of the first cup, then fill up to `live` from the
    other cups (and the first cup's later matches); returns (match id, home team id)."""
    clock = SystemClock()
    async with sessions() as db:
        startable: list[list[Any]] = []
        for tid, _ in cups:
            matches = [
                m
                for m in await competitions.list_matches(db, tid)
                if m.status == "scheduled" and m.home_team_id and m.away_team_id
            ]
            startable.append(sorted(matches, key=lambda m: m.starts_at))
        first: dict[UUID | None, Any] = {}
        for m in startable[0]:
            first.setdefault(m.pitch_id, m)
        order = [(0, m) for m in first.values()]
        order += [(i, m) for i, ms in enumerate(startable) if i > 0 for m in ms]
        order += [(0, m) for m in startable[0] if m not in first.values()]
        live: list[tuple[UUID, UUID]] = []
        for index, m in order[: plan.live]:
            await scoring.start(db, clock, Viewer(user_id=cups[index][1]), m.id)
            live.append((m.id, m.home_team_id))
        pitches = await db.scalar(
            text(
                "SELECT count(DISTINCT pitch_id) FROM matches WHERE tournament_id = :t "
                "AND status = 'live'"
            ),
            {"t": cups[0][0]},
        )
    return live, int(pitches or 0)


def owner_client(base: str, settings: Settings, owner: UUID) -> httpx.AsyncClient:
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    claims = AccessClaims(owner, uuid4(), frozenset(), expires)
    token = encode_access_token(claims, settings.jwt_secret.get_secret_value())
    cookies = {ACCESS_COOKIE: token, CSRF_COOKIE: CSRF}
    return httpx.AsyncClient(
        base_url=base,
        cookies=cookies,
        headers={CSRF_HEADER: CSRF},
        timeout=30,
        limits=httpx.Limits(max_connections=200),
    )


class Viewers:
    """WebSocket viewers of one match, recording when each sees each event seq."""

    def __init__(self) -> None:
        self.seen: dict[int, list[float]] = {}
        self.connected = 0
        self.expected = 0
        self.tasks: list[asyncio.Task[None]] = []

    async def watch(self, url: str, ready: asyncio.Event) -> None:
        try:
            async with connect(url, max_queue=None, open_timeout=60) as ws:
                self.connected += 1
                if self.connected >= self.expected:
                    ready.set()
                async for raw in ws:
                    message = json.loads(raw)
                    if message.get("type") == "event" and isinstance(message.get("seq"), int):
                        self.seen.setdefault(message["seq"], []).append(time.perf_counter())
        except Exception:  # a dropped viewer is counted as not delivered
            return

    async def open(self, http: httpx.AsyncClient, ws_base: str, match_id: UUID, count: int) -> None:
        self.expected = count
        ready = asyncio.Event()
        for start in range(0, count, 100):
            token = (await http.get(f"/api/v1/live/token?match_id={match_id}")).json()["token"]
            url = f"{ws_base}/api/v1/live/matches/{match_id}?token={token}"
            for _ in range(min(100, count - start)):
                self.tasks.append(asyncio.create_task(self.watch(url, ready)))
            await asyncio.sleep(0.2)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(ready.wait(), timeout=60)

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


async def post_goal(
    http: httpx.AsyncClient, match_id: UUID, team_id: UUID, n: int
) -> tuple[float, int]:
    started = time.perf_counter()
    response = await http.post(
        f"/api/v1/matches/{match_id}/events",
        json={"client_seq": n, "type": "goal", "team_id": str(team_id)},
    )
    elapsed = (time.perf_counter() - started) * 1000
    if response.status_code != 201:
        raise RuntimeError(f"event rejected: {response.status_code} {response.text[:200]}")
    return elapsed, int(response.json()["seq"])


async def after[T](delay: float, work: Awaitable[T]) -> T:
    await asyncio.sleep(delay)
    return await work


async def timed_gets(
    http: httpx.AsyncClient, urls: list[str], total: int, concurrency: int
) -> list[float]:
    times: list[float] = []
    gate = asyncio.Semaphore(concurrency)

    async def one(url: str) -> None:
        async with gate:
            started = time.perf_counter()
            response = await http.get(url)
            if response.status_code < 400:
                times.append((time.perf_counter() - started) * 1000)

    await asyncio.gather(*(one(urls[i % len(urls)]) for i in range(total)))
    return times


async def measure(
    base: str, settings: Settings, plan: Plan, sessions: async_sessionmaker[AsyncSession]
) -> Report:
    report = Report()
    cups = await provision(sessions, settings, plan)
    live, report.pitches_live_in_main_cup = await start_matches(sessions, cups, plan)
    report.live_matches = len(live)
    target = live[0][0]
    owner = cups[0][1]
    ws_base = base.replace("http", "ws", 1)
    viewers = Viewers()
    async with (
        owner_client(base, settings, owner) as http,
        httpx.AsyncClient(
            base_url=base, timeout=30, limits=httpx.Limits(max_connections=200)
        ) as anonymous,
    ):
        await viewers.open(anonymous, ws_base, target, plan.viewers)
        report.viewers_connected = viewers.connected
        latencies: list[float] = []
        posts: list[float] = []
        delivered: list[float] = []
        for n in range(1, plan.rounds + 1):
            sent = time.perf_counter()
            gap = plan.spread_ms / 1000 / max(len(live), 1)
            results = await asyncio.gather(
                *(after(i * gap, post_goal(http, m, team, n)) for i, (m, team) in enumerate(live))
            )
            posts.extend(ms for ms, _ in results)
            seq = results[0][1]
            deadline = time.perf_counter() + 10
            while (
                len(viewers.seen.get(seq, [])) < viewers.connected
                and time.perf_counter() < deadline
            ):
                await asyncio.sleep(0.05)
            arrivals = viewers.seen.get(seq, [])
            latencies.extend((t - sent) * 1000 for t in arrivals)
            delivered.append(len(arrivals) / max(viewers.connected, 1))
        report.event_ms = summary(latencies)
        report.post_ms = summary(posts)
        report.delivered = round(min(delivered) if delivered else 0.0, 4)
        tid = cups[0][0]
        public = [
            f"/api/v1/tournaments/{tid}",
            f"/api/v1/tournaments/{tid}/live",
            f"/api/v1/tournaments/{tid}/standings",
            f"/api/v1/matches/{target}",
            f"/api/v1/matches/{target}/timeline",
            f"/api/v1/tournaments/{tid}/schedule",
        ]
        report.read_ms = summary(await timed_gets(anonymous, public, plan.reads, plan.concurrency))
        personal = ["/api/v1/me/home", "/api/v1/me/feed", "/api/v1/me"]
        report.personal_ms = summary(
            await timed_gets(http, personal, plan.reads // 3, plan.concurrency)
        )
    await viewers.close()
    report.failures = check(report, plan)
    return report


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def check(report: Report, plan: Plan) -> list[str]:
    failures = []
    if report.viewers_connected < plan.viewers:
        failures.append(f"only {report.viewers_connected} of {plan.viewers} viewers connected")
    if report.delivered < TARGETS["delivered"]:
        failures.append(f"delivered {report.delivered:.2%} of events")
    for name, values, key in (
        ("event", report.event_ms, "event_p95_ms"),
        ("post", report.post_ms, "post_p95_ms"),
        ("read", report.read_ms, "read_p95_ms"),
        ("personal", report.personal_ms, "personal_p95_ms"),
    ):
        if values and values["p95"] > TARGETS[key]:
            failures.append(f"{name} p95 {values['p95']} ms > {TARGETS[key]} ms")
    return failures


async def run(plan: Plan, base: str | None, settings: Settings | None = None) -> Report:
    settings = settings or get_settings()
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(max(soft, plan.viewers * 3), hard), hard))
    engine = create_engine(settings)
    sessions = create_sessionmaker(engine)
    server: uvicorn.Server | None = None
    serving: asyncio.Task[None] | None = None
    try:
        if base is None:
            from app.main import create_app

            api = create_app(settings)
            quiet()  # create_app configures INFO logging
            port = free_port()
            config = uvicorn.Config(
                api,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                ws="auto",
            )
            server = uvicorn.Server(config)
            serving = asyncio.create_task(server.serve())
            while not server.started:
                await asyncio.sleep(0.05)
            base = f"http://127.0.0.1:{port}"
        return await measure(base, settings, plan, sessions)
    finally:
        if server is not None and serving is not None:
            server.should_exit = True
            await serving
        await engine.dispose()


def quiet() -> None:
    """Request and client logs would drown the report."""
    configure_logging("WARNING")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", help="a running API (default: start one in-process)")
    parser.add_argument("--check", action="store_true", help="exit 1 when a target is missed")
    for name, default in asdict(Plan()).items():
        parser.add_argument(f"--{name}", type=int, default=default)
    args = parser.parse_args()
    plan = Plan(**{k: getattr(args, k) for k in asdict(Plan())})
    quiet()
    report = asyncio.run(run(plan, args.base))
    print(json.dumps(asdict(report), indent=2))  # the report is the output
    if args.check and report.failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
