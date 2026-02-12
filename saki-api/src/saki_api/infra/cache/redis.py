"""
Redis client helper for Working Area cache.
"""

from redis.asyncio import Redis

from saki_api.core.config import settings

_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    """
    Get a singleton Redis client.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis_client


def build_working_key(
        project_id: str,
        user_id: str,
        sample_id: str,
        branch_name: str,
) -> str:
    """
    Build a Redis key for Working Area payloads.
    """
    prefix = settings.REDIS_KEY_PREFIX
    return f"{prefix}:working:{project_id}:{branch_name}:{user_id}:{sample_id}"
