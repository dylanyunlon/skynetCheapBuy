from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import uuid

from app.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import TokenData

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

class AuthService:
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def get_password_hash(password: str) -> str:
        """生成密码哈希"""
        return pwd_context.hash(password)
    
    @staticmethod
    def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """创建访问令牌"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire, "type": "access"})
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def create_refresh_token(data: Dict[str, Any]) -> str:
        """创建刷新令牌"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire, "type": "refresh"})
        encoded_jwt = jwt.encode(to_encode, settings.REFRESH_SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def decode_token(token: str, token_type: str = "access") -> TokenData:
        """解码令牌"""
        try:
            secret_key = settings.SECRET_KEY if token_type == "access" else settings.REFRESH_SECRET_KEY
            payload = jwt.decode(token, secret_key, algorithms=[settings.ALGORITHM])
            
            if payload.get("type") != token_type:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="无效的令牌类型"
                )
            
            # 从 payload 中获取用户信息
            user_id: str = payload.get("sub")  # sub 是用户 ID
            username: str = payload.get("username")  # 用户名在额外字段中
            
            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="无效的令牌"
                )
            
            # TokenData 需要包含 user_id 和 username
            return TokenData(username=username or user_id, user_id=user_id)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无法验证凭据",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    @staticmethod
    def decode_refresh_token(token: str) -> Optional[Dict[str, Any]]:
        """解码刷新令牌，返回原始 payload"""
        try:
            payload = jwt.decode(
                token, 
                settings.REFRESH_SECRET_KEY, 
                algorithms=[settings.ALGORITHM]
            )
            
            if payload.get("type") != "refresh":
                return None
            
            return payload
        except JWTError:
            return None

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """获取当前用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token_data = AuthService.decode_token(token)
    
    user = None
    
    # 使用 user_id 查询（如果有的话）
    if hasattr(token_data, 'user_id') and token_data.user_id:
        # 首先尝试通过 ID 查询
        try:
            user_uuid = uuid.UUID(token_data.user_id)
            user = db.query(User).filter(User.id == user_uuid).first()
        except ValueError:
            # 不是有效的 UUID，尝试用户名
            pass
    
    # 如果通过 ID 没找到，尝试用户名
    if not user and hasattr(token_data, 'username') and token_data.username:
        user = db.query(User).filter(User.username == token_data.username).first()
    
    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户账户已被禁用"
        )
    
    return user

async def get_current_active_superuser(
    current_user: User = Depends(get_current_user)
) -> User:
    """获取当前管理员用户"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足"
        )
    return current_user

# API密钥认证（可选）
from fastapi.security import APIKeyHeader
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key: Optional[str] = Depends(api_key_header)) -> Optional[str]:
    """获取API密钥"""
    if api_key and api_key.startswith("sk-"):
        return api_key
    return None

# 依赖注入装饰器（替代原Telegram机器人的装饰器）
def require_auth(func):
    """需要认证的装饰器"""
    async def wrapper(*args, current_user: User = Depends(get_current_user), **kwargs):
        return await func(*args, current_user=current_user, **kwargs)
    return wrapper

def require_admin(func):
    """需要管理员权限的装饰器"""
    async def wrapper(*args, current_user: User = Depends(get_current_active_superuser), **kwargs):
        return await func(*args, current_user=current_user, **kwargs)
    return wrapper