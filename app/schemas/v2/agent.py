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


# ============================================================================
# Agentic Loop Schemas
# ============================================================================

class AgenticTaskRequest(BaseModel):
    """Agentic Loop 任务请求"""
    task: str = Field(..., description="任务描述（自然语言）")
    model: Optional[str] = Field(default="claude-opus-4-6", description="AI 模型")
    project_id: Optional[str] = Field(default=None, description="关联项目 ID（可选，不传则自动创建）")
    max_turns: int = Field(default=30, ge=1, le=100, description="最大循环轮次")
    system_prompt: Optional[str] = Field(default=None, description="自定义系统提示词（可选）")
    work_dir: Optional[str] = Field(default=None, description="自定义工作目录（可选，高级用法）")


class AgenticEventResponse(BaseModel):
    """Agentic Loop 事件（SSE 推送）— v3 增强"""
    type: str = Field(..., description="事件类型: start|text|tool_start|tool_result|file_change|turn|progress|done|error")
    content: Optional[str] = None
    tool: Optional[str] = None
    tool_use_id: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    result: Optional[str] = None
    result_meta: Optional[Dict[str, Any]] = None  # v3: 结构化元数据
    description: Optional[str] = None  # v3: 工具操作描述
    turn: Optional[int] = None
    turns: Optional[int] = None
    total_tool_calls: Optional[int] = None
    duration: Optional[float] = None
    message: Optional[str] = None
    success: Optional[bool] = None
    # v3: file_change 事件字段
    action: Optional[str] = None
    path: Optional[str] = None
    filename: Optional[str] = None
    added: Optional[int] = None
    removed: Optional[int] = None
    # v3: turn 事件增强字段
    display: Optional[str] = None
    detail_items: Optional[List[Dict[str, Any]]] = None
    summary: Optional[Dict[str, Any]] = None
    # v3: progress 事件字段
    max_turns: Optional[int] = None
    elapsed: Optional[float] = None
    # v3: done 事件增强
    file_changes: Optional[List[Dict[str, Any]]] = None


class AgenticTaskResult(BaseModel):
    """Agentic Loop 同步执行结果 — v3"""
    success: bool
    turns: int
    total_tool_calls: int
    duration: float
    final_text: str
    work_dir: str
    events: List[Dict[str, Any]] = []
    file_changes: List[Dict[str, Any]] = []  # v3: 文件变更日志