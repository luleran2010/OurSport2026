"""Fixed-window rate limits in Redis (docs/09-security-privacy.md, Rate limits)."""

from redis.asyncio import Redis

from app.core.errors import RateLimited


async def enforce(redis: Redis, key: str, *, limit: int, window_s: int) -> None:
    """Count one hit on `key`; raise `RateLimited` once `limit` hits fall in the window."""
    full_key = f"rl:{key}"
    count = await redis.incr(full_key)
    if count == 1:
        await redis.expire(full_key, window_s)
    if count > limit:
        ttl = await redis.ttl(full_key)
        raise RateLimited(max(int(ttl), 1))
