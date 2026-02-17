# app/services/user_service.py
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_
from cryptography.fernet import Fernet
import json
import logging
import base64
import hashlib

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import SecurityUtils

from app.config import settings

logger = logging.getLogger(__name__)

def ensure_fernet_key(key: str) -> bytes:
    """确保密钥是有效的 Fernet 密钥"""
    # 尝试不同的处理方式
    attempts = [
        # 1. 直接作为字符串（如果已经是 base64）
        lambda: key if isinstance(key, str) and len(key) == 44 else None,
        # 2. 编码为 bytes
        lambda: key.encode() if isinstance(key, str) else key,
        # 3. 从密钥生成确定性的 Fernet 密钥
        lambda: base64.urlsafe_b64encode(hashlib.sha256(key.encode() if isinstance(key, str) else key).digest())
    ]
    
    for attempt in attempts:
        try:
            result = attempt()
            if result:
                # 验证是否是有效的 Fernet 密钥
                Fernet(result)
                return result
        except Exception:
            continue
    
    # 如果都失败了，生成新的密钥
    logger.error(f"Failed to process SECRET_KEY, generating new Fernet key")
    return Fernet.generate_key()

class UserService:
    """用户服务类"""
    
    def __init__(self, db: Session, redis_client=None):
        self.db = db
        self.redis = redis_client
        
        # 初始化加密器
        self._init_cipher()
    
    def _init_cipher(self):
        """初始化 Fernet 加密器"""
        try:
            fernet_key = ensure_fernet_key(settings.SECRET_KEY)
            self.cipher = Fernet(fernet_key)
            logger.info("Fernet cipher initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Fernet cipher: {e}")
            # 生成临时密钥以确保服务可以启动
            self.cipher = Fernet(Fernet.generate_key())
            logger.warning("Using temporary Fernet key")
    
    async def get_user(self, user_id: str) -> Optional[User]:
        """获取用户信息"""
        # 先从缓存查找
        if self.redis:
            try:
                cached = await self.redis.get(f"user:{user_id}")
                if cached:
                    user_data = json.loads(cached)
                    # 从缓存数据重建用户对象
                    return self.db.query(User).filter(User.id == user_data['id']).first()
            except Exception as e:
                logger.error(f"Error getting user from cache: {e}")
        
        # 从数据库查找
        user = self.db.query(User).filter(User.id == user_id).first()
        
        # 缓存用户信息
        if user and self.redis:
            try:
                # 只缓存基本信息，避免序列化问题
                cache_data = {
                    'id': str(user.id),
                    'username': user.username,
                    'email': user.email
                }
                await self.redis.setex(
                    f"user:{user_id}", 
                    3600,  # 1小时过期
                    json.dumps(cache_data)
                )
            except Exception as e:
                logger.error(f"Error caching user: {e}")
        
        return user
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        return self.db.query(User).filter(User.username == username).first()
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        return self.db.query(User).filter(User.email == email).first()
    
    async def create_user(self, user_create: UserCreate) -> User:
        """创建新用户"""
        # 检查用户名和邮箱是否已存在
        existing = self.db.query(User).filter(
            or_(
                User.username == user_create.username,
                User.email == user_create.email
            )
        ).first()
        
        if existing:
            if existing.username == user_create.username:
                raise ValueError("Username already exists")
            else:
                raise ValueError("Email already exists")
        
        # 创建用户
        db_user = User(
            username=user_create.username,
            email=user_create.email,
            full_name=user_create.full_name if hasattr(user_create, 'full_name') else '',
            hashed_password=SecurityUtils.get_password_hash(user_create.password),
            language=getattr(user_create, 'language', None) or settings.DEFAULT_LANGUAGE,
            preferred_model=getattr(user_create, 'preferred_model', None) or settings.DEFAULT_MODEL
        )
        
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)
        
        logger.info(f"Created new user: {db_user.username}")
        return db_user
    
    async def update_user(self, user_id: str, user_update: UserUpdate) -> Optional[User]:
        """更新用户信息"""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        
        update_data = user_update.dict(exclude_unset=True)
        
        # 处理密码更新
        if "password" in update_data:
            update_data["hashed_password"] = get_password_hash(update_data.pop("password"))
        
        # 更新用户信息
        for field, value in update_data.items():
            setattr(user, field, value)
        
        self.db.commit()
        self.db.refresh(user)
        
        # 清除缓存
        if self.redis:
            try:
                await self.redis.delete(f"user:{user_id}")
            except Exception as e:
                logger.error(f"Error clearing user cache: {e}")
        
        return user
    
    async def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        
        self.db.delete(user)
        self.db.commit()
        
        # 清除缓存
        if self.redis:
            try:
                await self.redis.delete(f"user:{user_id}")
            except Exception as e:
                logger.error(f"Error clearing user cache: {e}")
        
        return True
    
    async def encrypt_api_key(self, api_key: str) -> str:
        """加密API密钥"""
        try:
            return self.cipher.encrypt(api_key.encode()).decode()
        except Exception as e:
            logger.error(f"Error encrypting API key: {e}")
            raise
    
    async def decrypt_api_key(self, encrypted_key: str) -> str:
        """解密API密钥"""
        try:
            return self.cipher.decrypt(encrypted_key.encode()).decode()
        except Exception as e:
            logger.error(f"Failed to decrypt API key: {e}")
            return ""
    
    async def update_api_keys(self, user_id: str, api_keys: Dict[str, str]) -> bool:
        """更新用户的API密钥"""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        
        # 加密所有API密钥
        encrypted_keys = {}
        for provider, key in api_keys.items():
            if key:  # 只加密非空密钥
                try:
                    encrypted_keys[provider] = await self.encrypt_api_key(key)
                except Exception as e:
                    logger.error(f"Failed to encrypt {provider} API key: {e}")
                    return False
        
        user.api_keys = encrypted_keys
        self.db.commit()
        
        # 清除缓存
        if self.redis:
            try:
                await self.redis.delete(f"user:{user_id}")
            except Exception as e:
                logger.error(f"Error clearing user cache: {e}")
        
        return True
    
    async def get_decrypted_api_keys(self, user_id: str) -> Dict[str, str]:
        """获取用户的解密API密钥"""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user or not user.api_keys:
            return {}
        
        decrypted_keys = {}
        for provider, encrypted_key in user.api_keys.items():
            if encrypted_key:
                try:
                    decrypted_keys[provider] = await self.decrypt_api_key(encrypted_key)
                except Exception as e:
                    logger.error(f"Failed to decrypt {provider} API key: {e}")
                    decrypted_keys[provider] = ""
        
        return decrypted_keys
    
    async def list_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """列出所有用户"""
        return self.db.query(User).offset(skip).limit(limit).all()
    
    async def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """验证用户身份"""
        user = await self.get_user_by_username(username)
        if not user:
            logger.debug(f"User not found: {username}")
            return None
        if not SecurityUtils.verify_password(password, user.hashed_password):
            logger.debug(f"Invalid password for user: {username}")
            return None
        if not user.is_active:
            logger.debug(f"User is inactive: {username}")
            return None
        return user