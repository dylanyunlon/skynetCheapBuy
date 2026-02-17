# app/db/session.py - 修复版本
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from sqlalchemy.ext.declarative import declarative_base
from typing import Generator
import redis.asyncio as aioredis
from typing import Optional

from app.config import settings

# 创建数据库引擎
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=0,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=settings.DEBUG
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 声明式基类
Base = declarative_base()

# 数据库会话依赖项
def get_db() -> Generator[Session, None, None]:
    """
    数据库会话依赖项
    创建一个新的数据库会话，在请求完成后关闭它
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Redis相关
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