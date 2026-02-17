from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, QueuePool
import aioredis
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class PoolConfig:
    """连接池配置"""
    pool_size: int = 20
    max_overflow: int = 10
    pool_timeout: int = 3000
    pool_recycle: int = 3600
    echo_pool: bool = False

class ConnectionPoolManager:
    """连接池管理器"""
    
    def __init__(self):
        self._engines: Dict[str, AsyncEngine] = {}
        self._redis_pools: Dict[str, aioredis.Redis] = {}
        self._session_makers: Dict[str, sessionmaker] = {}
        self._metrics = {
            "connections_created": 0,
            "connections_recycled": 0,
            "pool_overflows": 0
        }
    
    async def create_database_pool(
        self,
        name: str,
        database_url: str,
        config: Optional[PoolConfig] = None
    ) -> AsyncEngine:
        """创建数据库连接池"""
        if name in self._engines:
            return self._engines[name]
        
        config = config or PoolConfig()
        
        engine = create_async_engine(
            database_url,
            pool_size=config.pool_size,
            max_overflow=config.max_overflow,
            pool_timeout=config.pool_timeout,
            pool_recycle=config.pool_recycle,
            echo_pool=config.echo_pool,
            pool_pre_ping=True,  # 检查连接健康
            connect_args={
                "server_settings": {
                    "application_name": f"chatbot_api_{name}",
                    "jit": "off"
                },
                "command_timeout": 6000,
                "options": "-c default_transaction_isolation='read committed'"
            }
        )
        
        self._engines[name] = engine
        
        # 创建 session maker
        self._session_makers[name] = sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # 监听池事件
        @engine.pool.events.connect
        def receive_connect(dbapi_conn, connection_record):
            self._metrics["connections_created"] += 1
        
        @engine.pool.events.checkin
        def receive_checkin(dbapi_conn, connection_record):
            if connection_record.age > config.pool_recycle:
                self._metrics["connections_recycled"] += 1
        
        logger.info(f"Created database pool '{name}' with size {config.pool_size}")
        return engine
    
    async def create_redis_pool(
        self,
        name: str,
        redis_url: str,
        pool_size: int = 10,
        max_connections: int = 50
    ) -> aioredis.Redis:
        """创建 Redis 连接池"""
        if name in self._redis_pools:
            return self._redis_pools[name]
        
        pool = aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=max_connections,
            health_check_interval=30,
            socket_keepalive=True,
            socket_keepalive_options={
                1: 1,  # TCP_KEEPIDLE
                2: 1,  # TCP_KEEPINTVL
                3: 5,  # TCP_KEEPCNT
            }
        )
        
        self._redis_pools[name] = pool
        logger.info(f"Created Redis pool '{name}' with max connections {max_connections}")
        return pool
    
    @asynccontextmanager
    async def get_db_session(self, pool_name: str = "default"):
        """获取数据库会话"""
        if pool_name not in self._session_makers:
            raise ValueError(f"Database pool '{pool_name}' not found")
        
        async with self._session_makers[pool_name]() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    async def get_redis(self, pool_name: str = "default") -> aioredis.Redis:
        """获取 Redis 连接"""
        if pool_name not in self._redis_pools:
            raise ValueError(f"Redis pool '{pool_name}' not found")
        return self._redis_pools[pool_name]
    
    async def close_all(self):
        """关闭所有连接池"""
        # 关闭数据库连接
        for name, engine in self._engines.items():
            await engine.dispose()
            logger.info(f"Closed database pool '{name}'")
        
        # 关闭 Redis 连接
        for name, pool in self._redis_pools.items():
            await pool.close()
            logger.info(f"Closed Redis pool '{name}'")
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取连接池指标"""
        metrics = self._metrics.copy()
        
        # 添加当前池状态
        for name, engine in self._engines.items():
            pool = engine.pool
            metrics[f"db_{name}_size"] = pool.size()
            metrics[f"db_{name}_checked_out"] = pool.checked_out()
            metrics[f"db_{name}_overflow"] = pool.overflow()
        
        return metrics
    
    async def health_check(self) -> Dict[str, bool]:
        """健康检查"""
        health = {}
        
        # 检查数据库连接
        for name, engine in self._engines.items():
            try:
                async with engine.connect() as conn:
                    await conn.execute("SELECT 1")
                health[f"db_{name}"] = True
            except Exception as e:
                logger.error(f"Database pool '{name}' health check failed: {e}")
                health[f"db_{name}"] = False
        
        # 检查 Redis 连接
        for name, pool in self._redis_pools.items():
            try:
                await pool.ping()
                health[f"redis_{name}"] = True
            except Exception as e:
                logger.error(f"Redis pool '{name}' health check failed: {e}")
                health[f"redis_{name}"] = False
        
        return health

# 全局连接池管理器
pool_manager = ConnectionPoolManager()