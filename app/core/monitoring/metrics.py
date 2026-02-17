from typing import Dict, Any
from fastapi import APIRouter, Depends
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from functools import wraps
import time
import psutil
import asyncio

# Prometheus 指标
request_count = Counter(
    'chatbot_requests_total',
    'Total number of requests',
    ['method', 'endpoint', 'status']
)

request_duration = Histogram(
    'chatbot_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint']
)

active_connections = Gauge(
    'chatbot_active_connections',
    'Number of active connections',
    ['type']
)

model_usage = Counter(
    'chatbot_model_usage_total',
    'Model usage count',
    ['model', 'provider']
)

cache_operations = Counter(
    'chatbot_cache_operations_total',
    'Cache operations',
    ['operation', 'layer', 'status']
)

class MetricsCollector:
    """指标收集器"""
    
    def __init__(self):
        self.start_time = time.time()
        self._custom_metrics = {}
    
    def record_request(self, method: str, endpoint: str, status: int, duration: float):
        """记录请求指标"""
        request_count.labels(method=method, endpoint=endpoint, status=status).inc()
        request_duration.labels(method=method, endpoint=endpoint).observe(duration)
    
    def record_model_usage(self, model: str, provider: str):
        """记录模型使用"""
        model_usage.labels(model=model, provider=provider).inc()
    
    def record_cache_operation(self, operation: str, layer: str, hit: bool):
        """记录缓存操作"""
        status = "hit" if hit else "miss"
        cache_operations.labels(operation=operation, layer=layer, status=status).inc()
    
    def update_active_connections(self, conn_type: str, count: int):
        """更新活跃连接数"""
        active_connections.labels(type=conn_type).set(count)
    
    async def collect_system_metrics(self) -> Dict[str, Any]:
        """收集系统指标"""
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # 网络 I/O
        net_io = psutil.net_io_counters()
        
        # 进程信息
        process = psutil.Process()
        
        return {
            "system": {
                "cpu_percent": cpu_percent,
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                    "used": memory.used
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent
                },
                "network": {
                    "bytes_sent": net_io.bytes_sent,
                    "bytes_recv": net_io.bytes_recv,
                    "packets_sent": net_io.packets_sent,
                    "packets_recv": net_io.packets_recv
                }
            },
            "process": {
                "cpu_percent": process.cpu_percent(),
                "memory_info": process.memory_info()._asdict(),
                "num_threads": process.num_threads(),
                "uptime": time.time() - self.start_time
            }
        }
    
    def add_custom_metric(self, name: str, value: Any, labels: Dict[str, str] = None):
        """添加自定义指标"""
        key = f"{name}:{str(labels)}" if labels else name
        self._custom_metrics[key] = {
            "name": name,
            "value": value,
            "labels": labels,
            "timestamp": time.time()
        }

# 全局指标收集器
metrics_collector = MetricsCollector()

def track_metrics(endpoint: str = None):
    """请求指标跟踪装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            method = kwargs.get('request', args[0] if args else None).method if args or kwargs else 'UNKNOWN'
            
            try:
                result = await func(*args, **kwargs)
                status = 200
                return result
            except Exception as e:
                status = 500
                raise
            finally:
                duration = time.time() - start_time
                metrics_collector.record_request(
                    method=method,
                    endpoint=endpoint or func.__name__,
                    status=status,
                    duration=duration
                )
        return wrapper
    return decorator

# 路由
metrics_router = APIRouter()

@metrics_router.get("/prometheus")
async def prometheus_metrics():
    """Prometheus 格式的指标"""
    return generate_latest()

@metrics_router.get("/system")
async def system_metrics():
    """系统指标"""
    return await metrics_collector.collect_system_metrics()

@metrics_router.get("/custom")
async def custom_metrics():
    """自定义指标"""
    return metrics_collector._custom_metrics