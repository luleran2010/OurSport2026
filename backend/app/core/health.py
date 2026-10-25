import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])
log = structlog.get_logger(__name__)

# A readiness check raises (or times out) when its dependency is unusable.
ReadinessCheck = Callable[[], Awaitable[None]]
CheckResult = Literal["ok", "error"]


class LiveStatus(BaseModel):
    status: Literal["ok"]


class ReadyStatus(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, CheckResult]


@router.get(
    "/live",
    response_model=LiveStatus,
    operation_id="get_health_live",
    summary="Process liveness check",
)
async def live() -> LiveStatus:
    """Return 200 while the process can serve requests; checks no dependencies."""
    return LiveStatus(status="ok")


@router.get(
    "/ready",
    response_model=ReadyStatus,
    operation_id="get_health_ready",
    summary="Readiness check: database and Redis reachable, migrations at head",
    responses={503: {"model": ReadyStatus, "description": "A dependency is unavailable"}},
)
async def ready(request: Request, response: Response) -> ReadyStatus:
    """Return 200 only when every dependency the API needs is reachable, else 503."""
    checks: Mapping[str, ReadinessCheck] = request.app.state.readiness_checks
    timeout_s: float = request.app.state.settings.health_check_timeout_s
    names = list(checks)
    outcomes = await asyncio.gather(*(_run(name, checks[name], timeout_s) for name in names))
    results = dict(zip(names, outcomes, strict=True))
    healthy = all(result == "ok" for result in results.values())
    if not healthy:
        response.status_code = 503
    return ReadyStatus(status="ok" if healthy else "unavailable", checks=results)


async def _run(name: str, check: ReadinessCheck, timeout_s: float) -> CheckResult:
    try:
        await asyncio.wait_for(check(), timeout=timeout_s)
    except Exception as exc:
        log.warning("readiness_check_failed", check=name, error=type(exc).__name__)
        return "error"
    return "ok"
