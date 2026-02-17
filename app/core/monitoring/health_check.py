from typing import Dict, Any, List
from datetime import datetime
import asyncio
from app.core.db.connection_pool import ConnectionPoolManager
from app.core.ai.engine import AIEngine

class HealthChecker:
    """健康检查器"""
    
    def __init__(
        self,
        pool_manager: ConnectionPoolManager,
        ai_engine: AIEngine
    ):
        self.pool_manager = pool_manager
        self.ai_engine = ai_engine
        self._checks = {
            "database": self._check_database,
            "redis": self._check_redis,
            "ai_engine": self._check_ai_engine,
            "disk_space": self._check_disk_space,
            "memory": self._check_memory
        }
    
    async def check_health(self) -> Dict[str, Any]:
        """基础健康检查"""
        checks = await asyncio.gather(
            self._check_database(),
            self._check_redis(),
            return_exceptions=True
        )
        
        database_health = checks[0] if not isinstance(checks[0], Exception) else False
        redis_health = checks[1] if not isinstance(checks[1], Exception) else False
        
        is_healthy = database_health and redis_health
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {
                "database": "ok" if database_health else "failed",
                "redis": "ok" if redis_health else "failed"
            }
        }
    
    async def detailed_check(self) -> Dict[str, Any]:
        """详细健康检查"""
        results = {}
        
        for check_name, check_func in self._checks.items():
            try:
                result = await check_func()
                results[check_name] = {
                    "status": "ok" if result else "failed",
                    "details": result,
                    "timestamp": datetime.utcnow().isoformat()
                }
            except Exception as e:
                results[check_name] = {
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
        
        # 整体状态
        all_ok = all(
            check["status"] == "ok"
            for check in results.values()
        )
        
        return {
            "status": "healthy" if all_ok else "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "checks": results
        }
    
    async def _check_database(self) -> bool:
        """检查数据库连接"""
        try:
            async with self.pool_manager.get_db_session() as session:
                result = await session.execute("SELECT 1")
                return result.scalar() == 1
        except:
            return False
    
    async def _check_redis(self) -> bool:
        """检查 Redis 连接"""
        try:
            redis = await self.pool_manager.get_redis()
            return await redis.ping()
        except:
            return False
    
    async def _check_ai_engine(self) -> Dict[str, Any]:
        """检查 AI 引擎"""
        results = {}
        
        # 检查每个配置的模型
        from app.core.config_manager import config_manager
        models = config_manager.get_all_models(enabled_only=True)
        
        for model in models[:3]:  # 只检查前3个模型
            try:
                validation = await self.ai_engine.validate_model_availability(
                    model.name,
                    "health_check"
                )
                results[model.name] = validation["available"]
            except:
                results[model.name] = False
        
        return results
    
    async def _check_disk_space(self) -> Dict[str, Any]:
        """检查磁盘空间"""
        import psutil
        disk = psutil.disk_usage('/')
        
        return {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": disk.percent,
            "healthy": disk.percent < 90  # 90% 阈值
        }
    
    async def _check_memory(self) -> Dict[str, Any]:
        """检查内存使用"""
        import psutil
        memory = psutil.virtual_memory()
        
        return {
            "total_gb": round(memory.total / (1024**3), 2),
            "available_gb": round(memory.available / (1024**3), 2),
            "percent": memory.percent,
            "healthy": memory.percent < 85  # 85% 阈值
        }