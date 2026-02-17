# app/schemas/user.py
from pydantic import BaseModel, Field, EmailStr, field_validator, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID


class UserBase(BaseModel):
    """用户基础信息"""
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    email: EmailStr


class UserCreate(UserBase):
    """用户创建"""
    password: str = Field(..., min_length=6, max_length=100)
    full_name: Optional[str] = None
    language: Optional[str] = None
    preferred_model: Optional[str] = None


class UserLogin(BaseModel):
    """用户登录"""
    username: str
    password: str


class UserResponse(UserBase):
    """用户响应"""
    id: UUID
    full_name: Optional[str] = None
    is_active: bool
    is_superuser: bool
    created_at: datetime
    language: str
    preferred_model: str

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    """用户更新"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    language: Optional[str] = None
    username: Optional[str] = Field(None, min_length=3, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    password: Optional[str] = Field(None, min_length=6, max_length=100)


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


class UserPlugins(BaseModel):
    """用户插件设置"""
    search: Optional[bool] = None
    url_reader: Optional[bool] = None
    generate_image: Optional[bool] = None
    code_interpreter: Optional[bool] = None


class UserAPIKeys(BaseModel):
    """用户API密钥"""
    provider: str = Field(..., pattern="^(openai|anthropic|google|custom)$")
    api_key: str = Field(..., min_length=10)
    api_url: Optional[str] = None

    @field_validator('api_key')
    def validate_api_key(cls, v: str, info) -> str:
        provider = info.data.get('provider')
        if provider == 'openai' and not v.startswith('sk-'):
            raise ValueError('OpenAI API密钥必须以sk-开头')
        elif provider == 'anthropic' and not v.startswith('sk-ant-'):
            raise ValueError('Anthropic API密钥必须以sk-ant-开头')
        return v


class UserSettingsUpdate(BaseModel):
    """用户设置更新"""
    language: Optional[str] = None
    preferred_model: Optional[str] = None
    system_prompt: Optional[str] = None
    claude_system_prompt: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=32000)


class UserProfile(BaseModel):
    """用户详细资料"""
    id: UUID
    username: str
    email: str
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = Field(None, max_length=500)

    # 设置
    language: str
    preferred_model: str
    preferences: Dict[str, Any]
    plugins: Dict[str, bool]

    # 统计
    total_conversations: int = 0
    total_messages: int = 0
    member_since: datetime
    last_active: Optional[datetime] = None

    # 配额
    quota: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class UserStatistics(BaseModel):
    """用户统计信息"""
    total_conversations: int
    total_messages: int
    total_tokens_used: int
    favorite_model: Optional[str] = None
    active_days: int
    last_active: Optional[datetime] = None

    # 详细统计
    messages_by_day: Optional[Dict[str, int]] = None
    usage_by_model: Optional[Dict[str, Dict[str, Any]]] = None
    average_conversation_length: Optional[float] = None


class UserQuota(BaseModel):
    """用户配额"""
    user_id: UUID

    # 消息配额
    daily_message_limit: int = 1000
    daily_messages_used: int = 0

    # Token配额
    monthly_token_limit: int = 1000000
    monthly_tokens_used: int = 0

    # 文件配额
    storage_limit_mb: int = 1000
    storage_used_mb: float = 0

    # 重置时间
    daily_reset_at: datetime
    monthly_reset_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserNotificationSettings(BaseModel):
    """用户通知设置"""
    email_notifications: bool = True
    push_notifications: bool = False

    # 通知类型
    notify_on_reply: bool = True
    notify_on_mention: bool = True
    notify_on_share: bool = True
    notify_on_system_updates: bool = True

    # 通知频率
    digest_frequency: str = Field(default="daily", pattern="^(realtime|hourly|daily|weekly|never)$")


class UserPrivacySettings(BaseModel):
    """用户隐私设置"""
    profile_visibility: str = Field(default="public", pattern="^(public|friends|private)$")
    show_online_status: bool = True
    allow_message_requests: bool = True
    share_usage_analytics: bool = True