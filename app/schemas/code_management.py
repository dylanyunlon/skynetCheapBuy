# app/schemas/code_management.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class ScriptLanguage(str, Enum):
    PYTHON = "python"
    BASH = "bash"
    SHELL = "shell"
    JAVASCRIPT = "javascript"
    SQL = "sql"

class CodeGenerateRequest(BaseModel):
    prompt: str = Field(..., description="用户的代码生成请求")
    language: Optional[ScriptLanguage] = Field(None, description="指定脚本语言")
    model: Optional[str] = Field(None, description="使用的AI模型")
    conversation_id: Optional[str] = Field(None, description="会话ID")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    execution_type: Optional[str] = Field("immediate", description="执行类型: immediate 或 scheduled")
    schedule: Optional[str] = Field(None, description="Cron表达式（用于定时任务）")
    auto_setup_cron: bool = Field(True, description="自动设置定时任务")
    force_generation: bool = Field(False, description="强制生成代码（即使未检测到代码生成意图）")

class CodeBlock(BaseModel):
    language: str
    description: Optional[str]
    is_executable: bool
    valid: bool
    error: Optional[str]
    line_count: int
    size: int
    saved: bool
    id: Optional[str]
    filepath: Optional[str]
    save_error: Optional[str]
    save_reason: Optional[str]

class CodeExtractionResult(BaseModel):
    has_code: bool
    code_blocks: List[CodeBlock]
    total_blocks: int
    saved_blocks: int

class CronSetupResult(BaseModel):
    success: bool
    cron_job: Optional[Dict[str, Any]]
    message: str
    error: Optional[str]

class CodeGenerateResponse(BaseModel):
    success: bool
    ai_response: str
    code_extraction: Optional[CodeExtractionResult]
    script_type: str
    cron_expression: Optional[str]
    cron_setup: Optional[CronSetupResult]
    metadata: Dict[str, Any]

class CodeExecuteRequest(BaseModel):
    parameters: Optional[Dict[str, str]] = Field(None, description="环境变量参数")
    timeout: int = Field(300, ge=1, le=3600, description="执行超时时间（秒）")

class CodeExecuteResponse(BaseModel):
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    execution_time: float
    executed_at: str

class CodeSnippetSummary(BaseModel):
    id: str
    language: str
    title: str
    description: Optional[str]
    created_at: str
    last_executed: Optional[str]
    execution_count: int
    has_cron_jobs: bool
    file_path: str
    conversation_id: Optional[str]

class CodeListResponse(BaseModel):
    snippets: List[CodeSnippetSummary]
    total: int
    limit: int
    offset: int

class CodeSnippetResponse(BaseModel):
    id: str
    language: str
    code: str
    wrapped_code: Optional[str]
    title: str
    description: Optional[str]
    created_at: str
    updated_at: Optional[str]
    last_executed: Optional[str]
    execution_count: int
    file_path: str
    conversation_id: Optional[str]
    metadata: Dict[str, Any]
    execution_history: List[Dict[str, Any]]
    cron_jobs: List[Dict[str, Any]]

class CronJobRequest(BaseModel):
    code_id: str = Field(..., description="代码片段ID")
    cron_expression: str = Field(..., description="Cron表达式")
    job_name: Optional[str] = Field(None, description="任务名称")
    env_vars: Optional[Dict[str, str]] = Field(None, description="环境变量")
    description: Optional[str] = Field(None, description="任务描述")

class CronJobResponse(BaseModel):
    job_id: str
    job_name: str
    user_id: str
    script_path: str
    cron_expression: str
    wrapper_script: str
    log_dir: str
    env_file: Optional[str]
    description: Optional[str]
    created_at: str
    is_active: bool
    last_run: Optional[str]
    run_count: int
    next_run: Optional[str]