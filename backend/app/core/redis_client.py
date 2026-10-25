from redis.asyncio import BlockingConnectionPool, Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    """Create the process-wide Redis client; connections are opened lazily. Under load a
    request waits for a free connection (up to `REDIS_POOL_TIMEOUT_S`) instead of failing."""
    pool = BlockingConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        timeout=settings.redis_pool_timeout_s,
        socket_connect_timeout=settings.health_check_timeout_s,
        socket_timeout=settings.health_check_timeout_s,
        decode_responses=True,
    )
    return Redis(connection_pool=pool)


async def check_redis(redis: Redis) -> None:
    """Raise if Redis does not answer PING."""
    if not await redis.ping():
        raise ConnectionError("redis did not answer PING")
