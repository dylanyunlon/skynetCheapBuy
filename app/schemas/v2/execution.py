from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class ExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    DEBUGGING = "debugging"
    CANCELLED = "cancelled"

class ExecutionRequest(BaseModel):
    """执行请求"""
    project_id: str
    entry_point: Optional[str] = None
    args: List[str] = []
    env_vars: Dict[str, str] = {}
    timeout: int = Field(default=300, ge=1, le=3600)
    auto_debug: bool = True
    max_debug_attempts: int = Field(default=3, ge=0, le=5)

class ExecutionResponse(BaseModel):
    """执行响应"""
    execution_id: str
    project_id: str
    status: ExecutionStatus
    start_time: datetime
    end_time: Optional[datetime]
    duration: Optional[float]
    exit_code: Optional[int]
    
class ExecutionLog(BaseModel):
    """执行日志"""
    execution_id: str
    timestamp: datetime
    level: str = Field(..., pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    message: str
    source: str = Field(..., pattern="^(stdout|stderr|system)$")
    
class DebugInfo(BaseModel):
    """调试信息"""
    error_type: str
    error_message: str
    file_path: Optional[str]
    line_number: Optional[int]
    suggested_fix: Optional[str]
    confidence: float = Field(ge=0.0, le=1.0)