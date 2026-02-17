# app/db/redis.py
import redis.asyncio as aioredis
from typing import Optional

from app.config import settings

redis_pool: Optional[aioredis.Redis] = None

async def init_redis():
    """初始化Redis连接池"""
    global redis_pool
    redis_pool = await aioredis.from_url(
        settings.REDIS_URL,
        encoding='utf-8',
        decode_responses=True
    )

async def close_redis():
    """关闭Redis连接池"""
    global redis_pool
    if redis_pool:
        await redis_pool.close()

async def get_redis() -> aioredis.Redis:
    """获取Redis连接"""
    if not redis_pool:
        await init_redis()
    return redis_pool