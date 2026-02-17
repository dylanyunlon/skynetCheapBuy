# app/core/rate_limit.py
# v3: 大幅放宽CCPO验证API的限流配置

import time
from typing import Dict, Optional, Callable
from functools import wraps
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
import aioredis

from app.config import settings
from app.db.redis import get_redis

class RateLimiter:
    """速率限制器"""
    
    def __init__(self, redis: Optional[aioredis.Redis] = None):
        self.redis = redis
        # 内存缓存作为后备
        self.memory_store: Dict[str, Dict[str, any]] = defaultdict(dict)
    
    async def check_rate_limit(
        self,
        key: str,
        max_calls: int,
        period: int  # 秒
    ) -> tuple[bool, Optional[int]]:
        """
        检查速率限制
        返回: (是否允许, 剩余等待时间)
        """
        if self.redis:
            return await self._check_redis(key, max_calls, period)
        else:
            return self._check_memory(key, max_calls, period)
    
    async def _check_redis(
        self,
        key: str,
        max_calls: int,
        period: int
    ) -> tuple[bool, Optional[int]]:
        """使用Redis检查速率限制"""
        current_time = int(time.time())
        window_start = current_time - period
        
        # 使用Redis的有序集合实现滑动窗口
        pipe = self.redis.pipeline()
        
        # 移除过期的记录
        pipe.zremrangebyscore(key, 0, window_start)
        
        # 获取当前窗口内的请求数
        pipe.zcard(key)
        
        # 添加当前请求
        pipe.zadd(key, {str(current_time): current_time})
        
        # 设置过期时间
        pipe.expire(key, period + 1)
        
        results = await pipe.execute()
        current_calls = results[1]
        
        if current_calls >= max_calls:
            # 获取最早的请求时间
            earliest = await self.redis.zrange(key, 0, 0, withscores=True)
            if earliest:
                wait_time = int(earliest[0][1]) + period - current_time
                return False, wait_time
            return False, period
        
        return True, None
    
    def _check_memory(
        self,
        key: str,
        max_calls: int,
        period: int
    ) -> tuple[bool, Optional[int]]:
        """使用内存检查速率限制"""
        current_time = time.time()
        window_start = current_time - period
        
        # 获取或创建请求记录
        if key not in self.memory_store:
            self.memory_store[key] = {
                "calls": [],
                "last_cleanup": current_time
            }
        
        record = self.memory_store[key]
        
        # 定期清理过期记录
        if current_time - record["last_cleanup"] > period:
            record["calls"] = [
                call_time for call_time in record["calls"]
                if call_time > window_start
            ]
            record["last_cleanup"] = current_time
        
        # 检查当前窗口内的请求数
        valid_calls = [
            call_time for call_time in record["calls"]
            if call_time > window_start
        ]
        
        if len(valid_calls) >= max_calls:
            wait_time = int(valid_calls[0] + period - current_time)
            return False, wait_time
        
        # 添加当前请求
        record["calls"].append(current_time)
        
        return True, None

# 全局速率限制器实例
rate_limiter = RateLimiter()

# ==================== 限流配置 ====================
# v3: 大幅放宽限制，支持CCPO训练的高频验证请求

# Benchmark API限流配置
BENCHMARK_RATE_LIMITS = {
    # 路径前缀 -> (max_calls, period_seconds)
    "/api/v2/benchmark/session/": (120, 60),     # 轮询：每分钟120次（每0.5秒1次）
    "/api/v2/benchmark/run": (30, 60),           # 创建会话：每分钟30次
    "/api/v2/benchmark/tasks": (60, 60),         # 获取任务列表：每分钟60次
    "/api/v2/benchmark/": (300, 60),             # 其他benchmark API：每分钟300次
}

# ==================== CCPO验证API限流配置 (新增) ====================
# CCPO验证需要高频请求，因为：
# 1. 每个样本可能需要多次验证
# 2. 批量处理时会并发请求
# 3. 重试机制需要额外请求

CCPO_RATE_LIMITS = {
    # CCPO代码验证相关路径
    "/api/v2/code/verify": (600, 60),            # 代码验证：每分钟600次（每秒10次）
    "/api/v2/code/execute": (600, 60),           # 代码执行：每分钟600次
    "/api/v2/verify": (600, 60),                 # 通用验证：每分钟600次
    "/api/v2/execute": (600, 60),                # 通用执行：每分钟600次
    "/api/code": (600, 60),                      # 旧版代码API：每分钟600次
    "/verify": (600, 60),                        # 简化验证路径：每分钟600次
    "/execute": (600, 60),                       # 简化执行路径：每分钟600次
}

# 通用API限流配置
GENERAL_RATE_LIMITS = {
    "/api/chat": (30, 60),                       # 聊天API：每分钟30次
    "/api/": (120, 60),                          # 其他API：每分钟120次
}

def get_rate_limit_config(path: str) -> tuple[int, int, str]:
    """
    获取API的限流配置
    返回: (max_calls, period, limit_type)
    """
    # 1. 优先检查CCPO验证API（最宽松）
    for prefix, (max_calls, period) in CCPO_RATE_LIMITS.items():
        if prefix in path.lower():
            return max_calls, period, "ccpo"
    
    # 2. 检查Benchmark API
    for prefix, (max_calls, period) in BENCHMARK_RATE_LIMITS.items():
        if path.startswith(prefix):
            return max_calls, period, "benchmark"
    
    # 3. 检查通用API
    for prefix, (max_calls, period) in GENERAL_RATE_LIMITS.items():
        if path.startswith(prefix):
            return max_calls, period, "general"
    
    # 4. 默认配置
    return 60, 60, "default"

def get_benchmark_rate_limit(path: str) -> tuple[int, int]:
    """获取Benchmark API的限流配置（向后兼容）"""
    for prefix, (max_calls, period) in BENCHMARK_RATE_LIMITS.items():
        if path.startswith(prefix):
            return max_calls, period
    return None, None

async def rate_limit_middleware(request: Request, call_next):
    """速率限制中间件 - v3优化版"""
    # 跳过不需要限制的路径
    skip_paths = ["/docs", "/redoc", "/openapi.json", "/health", "/", "/favicon.ico"]
    if request.url.path in skip_paths:
        return await call_next(request)
    
    # 获取用户标识
    user_key = None
    
    # 尝试从JWT获取用户ID
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            from app.core.auth import AuthService
            token = auth_header.split(" ")[1]
            token_data = AuthService.decode_token(token)
            user_key = f"rate_limit:user:{token_data.username}"
        except:
            pass
    
    # 如果没有用户认证，使用IP地址
    if not user_key:
        client_ip = request.client.host
        user_key = f"rate_limit:ip:{client_ip}"
    
    # 检查速率限制
    redis = await get_redis()
    limiter = RateLimiter(redis)
    
    # 获取限流配置
    path = request.url.path
    max_calls, period, limit_type = get_rate_limit_config(path)
    
    # 构建rate key
    if limit_type == "ccpo":
        # CCPO验证使用独立的限流key，避免与其他API冲突
        rate_key = f"{user_key}:ccpo"
    elif limit_type == "benchmark":
        # Benchmark API使用独立的限流key
        path_suffix = path.split('/')[4] if len(path.split('/')) > 4 else 'general'
        rate_key = f"{user_key}:benchmark:{path_suffix}"
    else:
        rate_key = user_key
    
    allowed, wait_time = await limiter.check_rate_limit(
        rate_key,
        max_calls,
        period
    )
    
    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "请求过于频繁，请稍后再试",
                "retry_after": wait_time,
                "limit_type": limit_type,
                "max_calls": max_calls,
                "period": period
            },
            headers={
                "Retry-After": str(wait_time),
                "X-RateLimit-Limit": str(max_calls),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + wait_time),
                "X-RateLimit-Type": limit_type
            }
        )
    
    # 继续处理请求
    response = await call_next(request)
    
    # 添加速率限制头部信息
    response.headers["X-RateLimit-Limit"] = str(max_calls)
    response.headers["X-RateLimit-Remaining"] = str(max_calls - 1)
    response.headers["X-RateLimit-Type"] = limit_type
    
    return response

def rate_limit(calls: int = 10, period: int = 60):
    """
    速率限制装饰器
    
    使用方法:
    @rate_limit(calls=5, period=60)
    async def my_endpoint():
        pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 从kwargs中获取当前用户
            current_user = kwargs.get("current_user")
            if current_user:
                key = f"rate_limit:endpoint:{func.__name__}:user:{current_user.id}"
            else:
                # 尝试从request获取IP
                request = None
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
                
                if request:
                    key = f"rate_limit:endpoint:{func.__name__}:ip:{request.client.host}"
                else:
                    key = f"rate_limit:endpoint:{func.__name__}:unknown"
            
            redis = await get_redis()
            limiter = RateLimiter(redis)
            
            allowed, wait_time = await limiter.check_rate_limit(key, calls, period)
            
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"速率限制：请在 {wait_time} 秒后重试",
                    headers={"Retry-After": str(wait_time)}
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

class UserActionLimiter:
    """用户操作限制器（防止滥用）"""
    
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
    
    async def check_message_frequency(
        self,
        user_id: str,
        conversation_id: str,
        min_interval: float = 0.5  # 最小发送间隔（秒）
    ) -> bool:
        """检查消息发送频率"""
        key = f"msg_freq:{user_id}:{conversation_id}"
        
        last_time = await self.redis.get(key)
        current_time = time.time()
        
        if last_time:
            last_time = float(last_time)
            if current_time - last_time < min_interval:
                return False
        
        # 更新最后发送时间
        await self.redis.setex(key, 60, str(current_time))
        return True
    
    async def check_file_upload_limit(
        self,
        user_id: str,
        max_files: int = 10,
        period: int = 3600  # 1小时
    ) -> tuple[bool, int]:
        """检查文件上传限制"""
        key = f"file_upload:{user_id}"
        current_count = await self.redis.incr(key)
        
        if current_count == 1:
            await self.redis.expire(key, period)
        
        if current_count > max_files:
            ttl = await self.redis.ttl(key)
            return False, ttl
        
        return True, 0
    
    async def check_api_key_changes(
        self,
        user_id: str,
        max_changes: int = 5,
        period: int = 86400  # 24小时
    ) -> bool:
        """检查API密钥更改频率"""
        key = f"api_key_changes:{user_id}"
        
        # 使用有序集合记录更改时间
        current_time = time.time()
        window_start = current_time - period
        
        # 清理过期记录
        await self.redis.zremrangebyscore(key, 0, window_start)
        
        # 获取当前计数
        count = await self.redis.zcard(key)
        
        if count >= max_changes:
            return False
        
        # 添加新记录
        await self.redis.zadd(key, {str(current_time): current_time})
        await self.redis.expire(key, period)
        
        return True

# 会话级别的限制
class ConversationLimiter:
    """会话限制器"""
    
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
    
    async def check_conversation_length(
        self,
        conversation_id: str,
        max_messages: int = 100
    ) -> bool:
        """检查会话长度"""
        key = f"conv_len:{conversation_id}"
        current_length = await self.redis.incr(key)
        
        if current_length == 1:
            await self.redis.expire(key, 86400)  # 24小时过期
        
        return current_length <= max_messages
    
    async def reset_conversation_counter(self, conversation_id: str):
        """重置会话计数器"""
        key = f"conv_len:{conversation_id}"
        await self.redis.delete(key)