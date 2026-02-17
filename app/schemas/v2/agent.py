from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class ProjectCreateRequest(BaseModel):
    """项目创建请求"""
    prompt: str = Field(..., description="项目需求描述")
    model: str = Field(default="claude-opus-4-5-20251101", description="AI模型")
    auto_execute: bool = Field(default=True, description="是否自动执行")
    max_debug_attempts: int = Field(default=3, ge=0, le=5, description="最大调试次数")
    project_type: Optional[str] = Field(default=None, description="项目类型")
    
class ProjectExecuteRequest(BaseModel):
    """项目执行请求"""
    max_debug_attempts: int = Field(default=3, ge=0, le=5)
    env_vars: Optional[Dict[str, str]] = Field(default=None, description="环境变量")
    entry_point: Optional[str] = Field(default=None, description="入口文件")
    timeout: int = Field(default=300, ge=1, le=3600, description="超时时间（秒）")

class FileEditRequest(BaseModel):
    """文件编辑请求"""
    file_path: str = Field(..., description="文件路径")
    prompt: str = Field(..., description="编辑指令")
    auto_format: bool = Field(default=True, description="是否自动格式化")
    validate: bool = Field(default=True, description="是否验证语法")

class ProjectResponse(BaseModel):
    """项目响应"""
    success: bool
    project_id: str
    project_path: str
    files: List[str]
    structure: Dict[str, Any]
    execution_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class FileContent(BaseModel):
    """文件内容"""
    path: str
    content: str
    language: str
    size: int
    checksum: Optional[str] = None

class ExecutionResult(BaseModel):
    """执行结果"""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    debug_attempts: int = 0
    debug_history: List[Dict[str, Any]] = []