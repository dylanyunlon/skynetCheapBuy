from pydantic import BaseModel, ConfigDict

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from uuid import UUID


# 聊天相关模式
class ChatMessage(BaseModel):
    """聊天消息"""
    content: str = Field(..., min_length=1, max_length=100000)
    model: Optional[str] = None
    conversation_id: Optional[str] = None
    system_prompt: Optional[str] = None
    attachments: Optional[List[str]] = None

    @validator('content')
    def validate_content(cls, v):
        if not v.strip():
            raise ValueError('消息内容不能为空')
        return v


class ChatResponse(BaseModel):
    """聊天响应"""
    id: str
    conversation_id: str
    content: str
    model: str
    created_at: str
    metadata: Optional[Dict[str, Any]] = None
    follow_up_questions: Optional[List[str]] = None


class ChatStreamResponse(BaseModel):
    """聊天流式响应"""
    id: str
    conversation_id: str
    chunk: str
    chunk_type: str = "text"  # text, error, done
    metadata: Optional[Dict[str, Any]] = None


class StreamChunk(BaseModel):
    """流式响应块"""
    content: str
    type: str = "text"  # text, text_delta, error, stage, complete, typing_start
    metadata: Optional[Dict[str, Any]] = None


class ResetChatRequest(BaseModel):
    """重置聊天请求"""
    system_prompt: Optional[str] = None


class ChatHistoryResponse(BaseModel):
    """聊天历史响应"""
    conversation_id: str
    messages: List[Dict[str, Any]]
    total_count: int


class ConversationInfo(BaseModel):
    """会话信息"""
    id: str
    title: Optional[str] = None
    model: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    is_active: bool = True


class ConversationList(BaseModel):
    """会话列表"""
    conversations: List[ConversationInfo]
    total: int
    page: int
    page_size: int


# WebSocket消息模式
class WebSocketMessage(BaseModel):
    """WebSocket消息"""
    action: str = Field(..., pattern="^(send_message|edit_message|delete_message|typing|ping|subscribe|unsubscribe)$")
    conversation_id: Optional[str] = None
    content: Optional[str] = None
    message_id: Optional[str] = None
    model: Optional[str] = None
    attachments: Optional[List[str]] = None


class WebSocketResponse(BaseModel):
    """WebSocket响应"""
    type: str  # stream, typing, error, connection, subscribed, unsubscribed, pong, complete
    data: Dict[str, Any]


# 用户相关模式
class UserBase(BaseModel):
    """用户基础信息"""
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    email: str = Field(..., pattern="^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$")


class UserCreate(UserBase):
    """用户创建"""
    password: str = Field(..., min_length=8, max_length=100)
    language: Optional[str] = "en"

    @validator('password')
    def validate_password(cls, v):
        if not any(char.isdigit() for char in v):
            raise ValueError('密码必须包含至少一个数字')
        if not any(char.isalpha() for char in v):
            raise ValueError('密码必须包含至少一个字母')
        return v


class UserLogin(BaseModel):
    """用户登录"""
    username: str
    password: str


class UserUpdate(BaseModel):
    """用户更新"""
    email: Optional[str] = None
    language: Optional[str] = None


class UserResponse(UserBase):
    """用户响应"""
    id: UUID
    is_active: bool
    is_superuser: bool
    created_at: datetime
    language: str
    preferred_model: str

    class Config:
        orm_mode = True


class UserPreferences(BaseModel):
    """用户偏好设置"""
    PASS_HISTORY: Optional[int] = Field(None, ge=0, le=100)
    LONG_TEXT: Optional[bool] = None
    LONG_TEXT_SPLIT: Optional[bool] = None
    FOLLOW_UP: Optional[bool] = None
    TITLE: Optional[bool] = None
    REPLY: Optional[bool] = None
    TYPING: Optional[bool] = None
    IMAGEQA: Optional[bool] = None
    FILE_UPLOAD_MESS: Optional[bool] = None

    # 新增代码相关偏好
    auto_extract_code: Optional[bool] = Field(True, description="自动提取代码")
    auto_save_code: Optional[bool] = Field(True, description="自动保存提取的代码")
    code_safety_check: Optional[bool] = Field(True, description="执行前进行安全检查")
    code_execution_timeout: Optional[int] = Field(300, description="代码执行超时时间(秒)")

    
class UserPlugins(BaseModel):
    """用户插件设置"""
    search: Optional[bool] = None
    url_reader: Optional[bool] = None
    generate_image: Optional[bool] = None


class UserAPIKeys(BaseModel):
    """用户API密钥"""
    provider: str = Field(..., pattern="^(openai|anthropic|google|custom)$")
    api_key: str = Field(..., min_length=10)
    api_url: Optional[str] = None


class UserSettingsUpdate(BaseModel):
    """用户设置更新"""
    language: Optional[str] = None
    preferred_model: Optional[str] = None
    system_prompt: Optional[str] = None
    claude_system_prompt: Optional[str] = None


# 认证相关模式
class Token(BaseModel):
    """令牌"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    """令牌数据"""
    username: Optional[str] = None


class TokenRefresh(BaseModel):
    """刷新令牌"""
    refresh_token: str


# 文件相关模式
class FileUploadResponse(BaseModel):
    """文件上传响应"""
    id: str
    filename: str
    file_type: str
    file_size: int
    uploaded_at: datetime
    status: str
    extracted_content: Optional[str] = None
    conversation_id: Optional[str] = None


class FileResponse(BaseModel):
    """文件信息响应"""
    id: UUID
    filename: str
    file_type: str
    file_size: int
    mime_type: str
    uploaded_at: datetime
    status: str
    extracted_text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        orm_mode = True


# 模型相关模式
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


class CustomModelConfig(BaseModel):
    """自定义模型配置"""
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


class ModelUsageStats(BaseModel):
    """模型使用统计"""
    model: str
    total_messages: int
    total_tokens: int
    total_cost: Optional[float] = None
    last_used: Optional[datetime] = None


# 错误响应模式
class ErrorResponse(BaseModel):
    """错误响应"""
    detail: str
    code: Optional[str] = None
    field: Optional[str] = None


class ValidationErrorResponse(BaseModel):
    """验证错误响应"""
    detail: List[Dict[str, Any]]


# 统计相关模式
class UserStatistics(BaseModel):
    """用户统计"""
    total_conversations: int
    total_messages: int
    total_tokens_used: int
    favorite_model: Optional[str] = None
    active_days: int
    last_active: Optional[datetime] = None


class SystemStatistics(BaseModel):
    """系统统计"""
    total_users: int
    active_users_today: int
    total_messages_today: int
    popular_models: List[Dict[str, int]]
    system_health: str = "healthy"

class ConversationResponse(BaseModel):
    """会话响应模型"""
    id: str
    title: Optional[str]
    created_at: str
    updated_at: str
    message_count: Optional[int] = 0
    last_message: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None

class ConversationListResponse(BaseModel):
    """会话列表响应"""
    conversations: List[ConversationResponse]
    total: int
    has_more: bool