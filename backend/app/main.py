from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI

from app.core import health, jobs, legal
from app.core.config import API_PREFIX, Settings, get_settings
from app.core.db import check_database, create_engine, create_sessionmaker
from app.core.email import EmailSender, SmtpEmailSender
from app.core.errors import install_error_handlers
from app.core.http_cache import SharedCacheMiddleware
from app.core.live import LiveHub
from app.core.llm import LLMProvider, build_gateway
from app.core.logging import RequestIdMiddleware, configure_logging
from app.core.migrations import check_migrations, expected_heads
from app.core.redis_client import check_redis, create_redis
from app.core.time import Clock, SystemClock
from app.modules.accounts import privacy as accounts_privacy
from app.modules.accounts.router import auth_router, me_router
from app.modules.analysis.live import router as live_router
from app.modules.analysis.router import router as fan_router
from app.modules.audience import privacy as audience_privacy
from app.modules.audience import service as audience
from app.modules.audience.router import public_router as audience_public_router
from app.modules.audience.router import router as audience_router
from app.modules.competitions import privacy as competitions_privacy
from app.modules.competitions import service as competitions
from app.modules.competitions.router import organiser_router as competitions_organiser_router
from app.modules.competitions.router import router as competitions_router
from app.modules.content import fake_writer
from app.modules.content import privacy as content_privacy
from app.modules.content.router import organiser_router as content_organiser_router
from app.modules.content.router import router as content_router
from app.modules.editorial import privacy as editorial_privacy
from app.modules.editorial.router import reader_router as editorial_reader_router
from app.modules.editorial.router import router as editorial_router
from app.modules.media import privacy as media_privacy
from app.modules.media.router import router as media_router
from app.modules.rules import privacy as rules_privacy
from app.modules.rules.router import router as rules_router
from app.modules.scoring import privacy as scoring_privacy
from app.modules.scoring import service as scoring
from app.modules.scoring.router import router as scoring_router
from app.modules.setup.router import draw_router, matchday_router
from app.modules.setup.router import router as setup_router


def register_privacy(clock: Clock) -> None:
    """Every module's GDPR export and erasure handlers (docs/09, GDPR)."""
    accounts_privacy.register(clock)
    for module in (
        audience_privacy,
        competitions_privacy,
        content_privacy,
        editorial_privacy,
        media_privacy,
        rules_privacy,
        scoring_privacy,
    ):
        module.register()


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    email_sender: EmailSender | None = None,
    llm_provider: LLMProvider | None = None,
) -> FastAPI:
    """Build the FastAPI application with all routers mounted."""
    settings = settings or get_settings()
    configure_logging()
    migration_heads = expected_heads()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        redis = create_redis(settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.redis = redis
        provider = llm_provider or fake_writer.provider_for(settings)
        app.state.llm = build_gateway(settings, redis, app.state.clock, provider)
        app.state.live = LiveHub(redis)
        app.state.readiness_checks = {
            "database": partial(check_database, engine),
            "migrations": partial(check_migrations, engine, migration_heads),
            "redis": partial(check_redis, redis),
        }
        try:
            yield
        finally:
            await app.state.live.close()
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title="OurSport API",
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/docs",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    app.state.email_sender = email_sender or SmtpEmailSender(settings)

    scoring.register(settings, app.state.clock)
    audience.register(app.state.clock)
    competitions.register()
    register_privacy(app.state.clock)
    install_error_handlers(app)
    app.add_middleware(SharedCacheMiddleware)
    app.add_middleware(RequestIdMiddleware)
    # Health checks live outside the versioned API so load balancers never depend on it.
    app.include_router(health.router)
    for router in (
        auth_router,
        me_router,
        competitions_router,
        competitions_organiser_router,
        rules_router,
        setup_router,
        draw_router,
        matchday_router,
        scoring_router,
        fan_router,
        live_router,
        audience_router,
        audience_public_router,
        content_router,
        media_router,
        content_organiser_router,
        editorial_router,
        editorial_reader_router,
        jobs.router,
        legal.router,
    ):
        app.include_router(router, prefix=API_PREFIX)
    return app


app = create_app()
