from typing import Optional, Any, Dict, List, Callable
import json
import hashlib
from datetime import datetime, timedelta
import asyncio
from functools import wraps
import aioredis
from sqlalchemy.orm import Session

class CacheLayer:
    """缓存层基类"""
    
    async def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        raise NotImplementedError
    
    async def delete(self, key: str):
        raise NotImplementedError
    
    async def exists(self, key: str) -> bool:
        raise NotImplementedError

class MemoryCache(CacheLayer):
    """内存缓存层"""
    
    def __init__(self, max_size: int = 1000):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._max_size = max_size
        self._access_times: Dict[str, datetime] = {}
    
    async def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            entry = self._cache[key]
            if entry["expires_at"] is None or entry["expires_at"] > datetime.utcnow():
                self._access_times[key] = datetime.utcnow()
                return entry["value"]
            else:
                del self._cache[key]
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        # LRU 淘汰策略
        if len(self._cache) >= self._max_size:
            oldest_key = min(self._access_times.items(), key=lambda x: x[1])[0]
            del self._cache[oldest_key]
            del self._access_times[oldest_key]
        
        expires_at = None
        if ttl:
            expires_at = datetime.utcnow() + timedelta(seconds=ttl)
        
        self._cache[key] = {
            "value": value,
            "expires_at": expires_at
        }
        self._access_times[key] = datetime.utcnow()

class RedisCache(CacheLayer):
    """Redis 缓存层"""
    
    def __init__(self, redis: aioredis.Redis, prefix: str = "cache:"):
        self.redis = redis
        self.prefix = prefix
    
    def _make_key(self, key: str) -> str:
        return f"{self.prefix}{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        value = await self.redis.get(self._make_key(key))
        if value:
            return json.loads(value)
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        await self.redis.set(
            self._make_key(key),
            json.dumps(value),
            ex=ttl
        )

class CacheManager:
    """多级缓存管理器"""
    
    def __init__(self):
        self.layers: List[CacheLayer] = []
        self._warming_tasks = {}
    
    def add_layer(self, layer: CacheLayer):
        """添加缓存层"""
        self.layers.append(layer)
    
    async def get(self, key: str) -> Optional[Any]:
        """从缓存获取数据"""
        for i, layer in enumerate(self.layers):
            value = await layer.get(key)
            if value is not None:
                # 回填上层缓存
                for j in range(i):
                    await self.layers[j].set(key, value, ttl=300)
                return value
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None, layers: Optional[List[int]] = None):
        """设置缓存"""
        target_layers = self.layers if layers is None else [self.layers[i] for i in layers]
        await asyncio.gather(*[
            layer.set(key, value, ttl) for layer in target_layers
        ])
    
    async def delete(self, key: str):
        """删除缓存"""
        await asyncio.gather(*[
            layer.delete(key) for layer in self.layers
        ])
    
    def cache_key(self, prefix: str, *args, **kwargs) -> str:
        """生成缓存键"""
        key_data = {
            "prefix": prefix,
            "args": args,
            "kwargs": kwargs
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def cached(self, ttl: int = 300, key_prefix: str = None, layers: Optional[List[int]] = None):
        """缓存装饰器"""
        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # 生成缓存键
                prefix = key_prefix or f"{func.__module__}.{func.__name__}"
                cache_key = self.cache_key(prefix, *args, **kwargs)
                
                # 尝试从缓存获取
                cached_value = await self.get(cache_key)
                if cached_value is not None:
                    return cached_value
                
                # 执行函数
                result = await func(*args, **kwargs)
                
                # 设置缓存
                await self.set(cache_key, result, ttl=ttl, layers=layers)
                
                return result
            return wrapper
        return decorator
    
    async def warm_cache(self, key: str, loader: Callable, ttl: int = 3600):
        """缓存预热"""
        value = await loader()
        await self.set(key, value, ttl=ttl)
    
    def schedule_warming(self, key: str, loader: Callable, interval: int = 3600):
        """定期缓存预热"""
        async def warming_task():
            while True:
                try:
                    await self.warm_cache(key, loader, ttl=interval)
                    await asyncio.sleep(interval * 0.9)  # 在过期前刷新
                except Exception as e:
                    print(f"Cache warming error for {key}: {e}")
                    await asyncio.sleep(60)  # 错误后等待重试
        
        task = asyncio.create_task(warming_task())
        self._warming_tasks[key] = task

# 全局缓存管理器
cache_manager = CacheManager()