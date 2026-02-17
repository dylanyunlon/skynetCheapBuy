# app/schemas/v2/chat.py - 完整版本，添加 metadata 支持
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from uuid import UUID
import re

class ChatMessageRequest(BaseModel):
    """统一聊天请求模型"""
    message: str = Field(..., min_length=1, max_length=100000, description="用户消息内容")
    conversation_id: Optional[str] = Field(None, description="会话ID")
    project_id: Optional[str] = Field(None, description="关联项目ID")
    model: Optional[str] = Field(None, description="AI模型")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    attachments: Optional[List[str]] = Field(default_factory=list, description="附件列表")
    
    # 修复：使用 pattern 替代 regex
    intent_hint: Optional[str] = Field(None, description="意图提示", pattern="^(create_project|generate_code|execute_code|file_operation|general_chat)$")
    
    # 新增：上下文控制
    include_project_context: bool = Field(True, description="是否包含项目上下文")
    include_file_contents: bool = Field(False, description="是否包含文件内容")
    
    # 兼容性：支持旧版本参数
    pass_history: Optional[int] = Field(None, description="历史消息数量", ge=0, le=100)
    
    # 添加 metadata 支持
    metadata: Optional[Dict[str, Any]] = Field(None, description="请求元数据")

class ProjectOperation(BaseModel):
    """项目操作模型"""
    operation: str = Field(..., description="操作类型", pattern="^(create|modify|delete|execute)$")
    project_id: Optional[str] = Field(None, description="项目ID")
    description: str = Field(..., description="操作描述")
    status: str = Field("pending", description="操作状态", pattern="^(pending|completed|failed)$")
    result: Optional[Dict[str, Any]] = Field(None, description="操作结果")

class CodeGeneration(BaseModel):
    """代码生成模型"""
    language: str = Field(..., description="编程语言")
    code: str = Field(..., description="生成的代码")
    file_path: Optional[str] = Field(None, description="文件路径")
    description: Optional[str] = Field(None, description="代码描述")
    executable: bool = Field(False, description="是否可执行")
    saved: bool = Field(False, description="是否已保存")

class FileOperation(BaseModel):
    """文件操作模型"""
    operation: str = Field(..., description="操作类型", pattern="^(create|read|update|delete|move|copy)$")
    file_path: str = Field(..., description="文件路径")
    content: Optional[str] = Field(None, description="文件内容")
    status: str = Field("pending", description="操作状态")
    result: Optional[Dict[str, Any]] = Field(None, description="操作结果")

class ExecutionResult(BaseModel):
    """执行结果模型"""
    success: bool = Field(..., description="是否成功")
    exit_code: Optional[int] = Field(None, description="退出代码")
    stdout: Optional[str] = Field(None, description="标准输出")
    stderr: Optional[str] = Field(None, description="错误输出")
    duration_ms: Optional[int] = Field(None, description="执行时长(毫秒)")
    resource_usage: Optional[Dict[str, Any]] = Field(None, description="资源使用情况")

class ChatMessageResponse(BaseModel):
    """统一聊天响应模型"""
    message_id: str = Field(..., description="消息ID")
    conversation_id: str = Field(..., description="会话ID")
    content: str = Field(..., description="响应内容")
    
    # 意图识别结果
    intent_detected: Optional[str] = Field(None, description="检测到的意图")
    intent_confidence: Optional[float] = Field(None, description="意图置信度", ge=0, le=1)
    
    # 项目相关响应
    project_created: Optional[Dict[str, Any]] = Field(None, description="创建的项目信息")
    project_modified: Optional[Dict[str, Any]] = Field(None, description="修改的项目信息")
    project_suggestion: Optional[Dict[str, Any]] = Field(None, description="项目建议")
    project_operations: Optional[List[ProjectOperation]] = Field(default_factory=list, description="项目操作列表")
    
    # 代码生成响应
    code_generations: Optional[List[CodeGeneration]] = Field(default_factory=list, description="代码生成列表")
    
    # 文件操作响应
    file_operations: Optional[List[FileOperation]] = Field(default_factory=list, description="文件操作列表")
    
    # 执行结果
    execution_result: Optional[ExecutionResult] = Field(None, description="执行结果")
    
    # 建议操作
    suggestions: Optional[List[str]] = Field(default_factory=list, description="建议操作列表")
    
    # 兼容性：支持旧版本字段
    follow_up_questions: Optional[List[str]] = Field(None, description="后续问题建议")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据")
    usage: Optional[Dict[str, Any]] = Field(None, description="使用统计")
    
    # 性能指标
    processing_time_ms: Optional[int] = Field(None, description="处理时间(毫秒)")
    
    # 时间戳
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="响应时间戳")

class ProjectContext(BaseModel):
    """项目上下文模型"""
    project_id: str = Field(..., description="项目ID")
    project_name: str = Field(..., description="项目名称")
    project_type: str = Field(..., description="项目类型")
    project_files: List[str] = Field(default_factory=list, description="项目文件列表")
    file_structure: Dict[str, Any] = Field(default_factory=dict, description="文件结构")
    dependencies: List[str] = Field(default_factory=list, description="依赖列表")
    recent_executions: List[Dict[str, Any]] = Field(default_factory=list, description="最近执行记录")
    workspace_path: Optional[str] = Field(None, description="工作空间路径")
    git_status: Optional[Dict[str, Any]] = Field(None, description="Git状态")

class ProjectSpec(BaseModel):
    """项目规格模型"""
    name: str = Field(..., description="项目名称", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="项目描述", max_length=1000)
    type: str = Field("general", description="项目类型")
    technologies: List[str] = Field(default_factory=list, description="技术栈")
    template: Optional[str] = Field(None, description="项目模板")
    dependencies: List[str] = Field(default_factory=list, description="依赖列表")
    settings: Dict[str, Any] = Field(default_factory=dict, description="项目设置")
    auto_create: bool = Field(False, description="是否自动创建")

# 流式响应模型
class StreamChunkData(BaseModel):
    """流式响应数据块"""
    content: str = Field("", description="内容片段")
    chunk_type: str = Field("text", description="数据块类型")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据")

class StreamResponse(BaseModel):
    """流式响应模型"""
    event_type: str = Field(..., description="事件类型")
    data: StreamChunkData = Field(..., description="数据内容")
    message_id: Optional[str] = Field(None, description="消息ID")
    conversation_id: Optional[str] = Field(None, description="会话ID")

# 批量操作模型
class BatchRequest(BaseModel):
    """批量请求模型"""
    requests: List[ChatMessageRequest] = Field(..., description="请求列表", min_length=1, max_length=10)
    parallel: bool = Field(False, description="是否并行处理")

class BatchResponse(BaseModel):
    """批量响应模型"""
    responses: List[ChatMessageResponse] = Field(..., description="响应列表")
    success_count: int = Field(..., description="成功数量")
    error_count: int = Field(..., description="错误数量")
    total_processing_time_ms: int = Field(..., description="总处理时间")

# 会话管理模型
class ConversationInfo(BaseModel):
    """会话信息模型"""
    id: str = Field(..., description="会话ID")
    title: Optional[str] = Field(None, description="会话标题")
    project_id: Optional[str] = Field(None, description="关联项目ID")
    conversation_type: str = Field("general", description="会话类型")
    message_count: int = Field(0, description="消息数量")
    last_message: Optional[str] = Field(None, description="最后一条消息")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    is_active: bool = Field(True, description="是否活跃")

class ConversationListResponse(BaseModel):
    """会话列表响应"""
    conversations: List[ConversationInfo] = Field(..., description="会话列表")
    total: int = Field(..., description="总数量")
    page: int = Field(1, description="当前页")
    page_size: int = Field(20, description="页大小")
    has_more: bool = Field(False, description="是否有更多")

# 错误响应模型
class ErrorDetail(BaseModel):
    """错误详情模型"""
    code: str = Field(..., description="错误代码")
    message: str = Field(..., description="错误消息")
    field: Optional[str] = Field(None, description="错误字段")
    details: Optional[Dict[str, Any]] = Field(None, description="详细信息")

class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: ErrorDetail = Field(..., description="错误详情")
    request_id: Optional[str] = Field(None, description="请求ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="时间戳")

# 统计模型
class ChatStatistics(BaseModel):
    """聊天统计模型"""
    total_messages: int = Field(..., description="总消息数")
    total_conversations: int = Field(..., description="总会话数")
    project_related_chats: int = Field(..., description="项目相关聊天数")
    code_generations: int = Field(..., description="代码生成次数")
    successful_executions: int = Field(..., description="成功执行次数")
    average_response_time_ms: float = Field(..., description="平均响应时间")
    popular_intents: List[Dict[str, Any]] = Field(..., description="热门意图统计")

# 配置模型
class ChatConfig(BaseModel):
    """聊天配置模型"""
    model: str = Field(..., description="默认模型")
    temperature: float = Field(0.7, description="温度参数", ge=0, le=2)
    max_tokens: Optional[int] = Field(None, description="最大token数", gt=0)
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    enable_project_context: bool = Field(True, description="启用项目上下文")
    enable_code_generation: bool = Field(True, description="启用代码生成")
    enable_file_operations: bool = Field(True, description="启用文件操作")
    auto_save_code: bool = Field(True, description="自动保存代码")
    auto_execute_safe_code: bool = Field(False, description="自动执行安全代码")

# 兼容性模型 - 确保与现有 schemas/chat.py 兼容
class LegacyChatMessage(BaseModel):
    """兼容旧版聊天消息模型"""
    content: str = Field(..., min_length=1, max_length=100000)
    model: Optional[str] = None
    conversation_id: Optional[str] = None
    system_prompt: Optional[str] = None
    attachments: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None  # 添加 metadata 支持

class LegacyChatResponse(BaseModel):
    """兼容旧版聊天响应模型"""
    id: str
    conversation_id: str
    content: str
    model: str
    created_at: str
    metadata: Optional[Dict[str, Any]] = None
    follow_up_questions: Optional[List[str]] = None