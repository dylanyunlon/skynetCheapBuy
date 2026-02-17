from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional
from datetime import datetime


class Token(BaseModel):
    """令牌响应"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="令牌过期时间（秒）")


class TokenData(BaseModel):
    """令牌数据"""
    username: Optional[str] = None
    user_id: Optional[str] = None
    scopes: list[str] = []


class TokenRefresh(BaseModel):
    """刷新令牌请求"""
    refresh_token: str


class UserCreate(BaseModel):
    """用户注册"""
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    language: Optional[str] = Field(default="en", pattern="^[a-z]{2}(-[a-z]{2,4})?$")

    @validator('password')
    def validate_password(cls, v):
        if not any(char.isdigit() for char in v):
            raise ValueError('密码必须包含至少一个数字')
        if not any(char.isalpha() for char in v):
            raise ValueError('密码必须包含至少一个字母')
        if not any(char.isupper() for char in v):
            raise ValueError('密码必须包含至少一个大写字母')
        if not any(char.islower() for char in v):
            raise ValueError('密码必须包含至少一个小写字母')
        return v


class UserLogin(BaseModel):
    """用户登录"""
    username: str
    password: str


class PasswordChange(BaseModel):
    """修改密码"""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=100)

    @validator('new_password')
    def validate_new_password(cls, v, values):
        if 'current_password' in values and v == values['current_password']:
            raise ValueError('新密码不能与当前密码相同')

        # 应用相同的密码强度验证
        if not any(char.isdigit() for char in v):
            raise ValueError('密码必须包含至少一个数字')
        if not any(char.isalpha() for char in v):
            raise ValueError('密码必须包含至少一个字母')
        return v


class PasswordReset(BaseModel):
    """重置密码"""
    token: str
    new_password: str = Field(..., min_length=8, max_length=100)


class PasswordResetRequest(BaseModel):
    """请求重置密码"""
    email: EmailStr


class OAuth2Login(BaseModel):
    """OAuth2登录"""
    provider: str = Field(..., pattern="^(google|github|microsoft)$")
    code: str
    state: Optional[str] = None


class APIKeyCreate(BaseModel):
    """创建API密钥"""
    name: str = Field(..., min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None


class APIKeyResponse(BaseModel):
    """API密钥响应"""
    id: str
    name: str
    key: str  # 只在创建时返回完整密钥
    key_preview: str  # 部分显示的密钥
    scopes: list[str]
    created_at: datetime
    expires_at: Optional[datetime]
    last_used: Optional[datetime]


class LoginHistory(BaseModel):
    """登录历史"""
    id: str
    user_id: str
    ip_address: str
    user_agent: str
    location: Optional[str] = None
    status: str  # success, failed
    created_at: datetime