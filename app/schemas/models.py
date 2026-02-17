from pydantic import BaseModel, Field, ConfigDict  # 添加 ConfigDict 导入
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime

class ModelInfo(BaseModel):
    """模型信息"""
    name: str
    provider: str
    available: bool
    capabilities: Dict[str, Any]
    context_window: Optional[int] = None
    max_tokens: Optional[int] = None
    supports_vision: bool = False
    supports_functions: bool = False
    supports_streaming: bool = True
    description: Optional[str] = None
    recommended_for: List[str] = []

class ModelUsageStats(BaseModel):
    """模型使用统计"""
    model: str
    total_messages: int
    total_tokens: int
    total_cost: Optional[float] = None
    last_used: Optional[datetime] = None

class ModelCapabilities(BaseModel):
    """模型能力"""
    chat: bool = True
    image_input: bool = False
    image_generation: bool = False
    function_calling: bool = False
    streaming: bool = True
    max_tokens: int
    context_window: int
    cost_per_1k_input: Optional[float] = None
    cost_per_1k_output: Optional[float] = None

class ModelGroup(BaseModel):
    """模型组"""
    name: str
    models: List[str]
    description: Optional[str] = None

class ModelTestRequest(BaseModel):
    """模型测试请求"""
    model: str
    test_message: str = "Hello, please respond with 'OK' if you can read this."

class ModelTestResponse(BaseModel):
    """模型测试响应"""
    success: bool
    model: str
    response: Optional[str] = None
    error: Optional[str] = None
    latency: Optional[int] = None  # 毫秒

class CustomModelRequest(BaseModel):
    """自定义模型请求"""
    name: str = Field(..., min_length=1, max_length=100)
    provider: str
    api_url: str
    api_key: Optional[str] = None
    model_type: str = "chat"
    capabilities: Optional[Dict[str, bool]] = None
    model_config = ConfigDict(
        protected_namespaces=(),  # 禁用保护命名空间
        from_attributes=True  # 如果需要 ORM 模式
    )