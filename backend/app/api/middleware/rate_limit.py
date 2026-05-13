"""
Rate Limiting Middleware - Token Bucket Algorithm (Redis-backed)
"""

from fastapi import Request, HTTPException, status
from redis.exceptions import RedisError
from app.dependencies import get_redis


async def rate_limit_check(request: Request, user_id: str, limit: int = 30, window: int = 60):
    """
    Token-bucket rate limiter.
    Args:
        user_id: Unique user identifier
        limit: Max requests per window
        window: Time window in seconds
    """
    redis = get_redis()
    if redis is None:
        return
    key = f"rate_limit:{user_id}"
    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, window)
    except (RedisError, OSError, RuntimeError, ValueError):
        return
    if current > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
        )
