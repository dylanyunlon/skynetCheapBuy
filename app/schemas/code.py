# app/schemas/code.py

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID

class CodeGenerationRequest(BaseModel):
    """代码生成请求"""
    prompt: str = Field(..., description="用户的代码生成请求")
    language: Optional[str] = Field(None, description="指定编程语言")
    conversation_id: Optional[str] = Field(None, description="会话ID")
    model: Optional[str] = Field(None, description="AI模型")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    force_generation: bool = Field(False, description="强制生成代码")
    auto_setup_cron: bool = Field(False, description="自动设置定时任务")
    auto_save: bool = Field(True, description="是否自动保存提取的代码")

# 为了兼容性，添加别名
CodeGenerateRequest = CodeGenerationRequest

class CodeExecutionRequest(BaseModel):
    """代码执行请求"""
    parameters: Optional[Dict[str, Any]] = Field(None, description="执行参数")
    env_vars: Optional[Dict[str, str]] = Field(None, description="环境变量")
    timeout: Optional[int] = Field(300, description="执行超时时间（秒）")

# 为了兼容性，添加别名
CodeExecuteRequest = CodeExecutionRequest

class CronJobRequest(BaseModel):
    """定时任务请求"""
    code_id: str = Field(..., description="代码ID")
    cron_expression: str = Field(..., description="Cron表达式", example="0 */6 * * *")
    job_name: Optional[str] = Field(None, description="任务名称")
    env_vars: Optional[Dict[str, str]] = Field(None, description="环境变量")
    description: Optional[str] = Field(None, description="任务描述")

class CodeResponse(BaseModel):
    """代码响应"""
    id: str
    language: str
    description: Optional[str] = None
    created_at: str
    last_executed_at: Optional[str] = None
    execution_count: int = 0
    has_cron_job: bool = False
    file_size: int = 0

class CodeExecutionResponse(BaseModel):
    """代码执行响应"""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    execution_time: float
    executed_at: str

# 为了兼容性，添加别名
CodeExecuteResponse = CodeExecutionResponse

class CronJobResponse(BaseModel):
    """定时任务响应"""
    success: bool
    job_id: Optional[str] = None
    job_name: str
    cron_expression: str
    next_run: Optional[str] = None
    error: Optional[str] = None

class CodeBlockInfo(BaseModel):
    """代码块信息"""
    language: str
    valid: bool
    saved: bool = False
    error: Optional[str] = None
    code_preview: str
    description: Optional[str] = None
    id: Optional[str] = None
    file_path: Optional[str] = None

class CodeExtractionResponse(BaseModel):
    """代码提取响应"""
    has_code: bool
    code_blocks: List[CodeBlockInfo]
    total_blocks: int = 0
    executable_blocks: int = 0
    message: Optional[str] = None

# 新增缺失的响应类
class CodeGenerateResponse(BaseModel):
    """代码生成响应"""
    success: bool
    ai_response: str
    code_extraction: Optional[CodeExtractionResponse] = None
    script_type: str
    cron_expression: Optional[str] = None
    cron_setup: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

# 为了兼容性，添加别名
CodeGenerateResponse = CodeGenerateResponse

class CodeSnippetResponse(BaseModel):
    """代码片段响应"""
    id: str
    user_id: str
    language: str
    content: str
    wrapped_content: Optional[str] = None
    description: Optional[str] = None
    file_path: str
    created_at: str
    updated_at: Optional[str] = None
    last_executed_at: Optional[str] = None
    execution_count: int = 0
    has_cron_job: bool = False
    cron_expression: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class CodeListResponse(BaseModel):
    """代码列表响应"""
    snippets: List[CodeSnippetResponse]
    total: int
    limit: int
    offset: int

class CodeCreate(BaseModel):
    """创建代码片段"""
    language: str = Field(..., description="编程语言")
    code: str = Field(..., description="代码内容")
    title: Optional[str] = Field(None, description="标题")
    description: Optional[str] = Field(None, description="描述")
    conversation_id: Optional[str] = Field(None, description="会话ID")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class CodeUpdate(BaseModel):
    """更新代码片段"""
    title: Optional[str] = Field(None, description="标题")
    description: Optional[str] = Field(None, description="描述")
    code: Optional[str] = Field(None, description="代码内容")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据")