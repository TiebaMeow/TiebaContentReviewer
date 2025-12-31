from __future__ import annotations

from redis.asyncio import Redis

from src.config import settings


async def get_redis_client() -> Redis:
    """获取 Redis 客户端实例。

    Returns:
        Redis: 配置好的 Redis 异步客户端。
    """
    return Redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-any-return]
