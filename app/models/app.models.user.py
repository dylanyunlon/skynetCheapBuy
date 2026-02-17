from sqlalchemy import Column, String, Boolean, DateTime, JSON, Integer, ForeignKey, Text, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.db.base import Base

class UserRole(enum.Enum):
    """用户角色枚举"""
    USER = "user"
    ADMIN = "admin"
    MODERATOR = "moderator"

class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)  # 添加 full_name 字段
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    # 修改 role 列定义
    role = Column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]), 
        default=UserRole.USER.value,
        nullable=False
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 用户配置
    language = Column(String(50), default="en")
    preferred_model = Column(String(100), default="o3-gz")
    system_prompt = Column(Text, nullable=True)
    claude_system_prompt = Column(Text, nullable=True)
    
    # 用户偏好设置
    preferences = Column(JSON, default={
        "PASS_HISTORY": 3,
        "LONG_TEXT": False,
        "LONG_TEXT_SPLIT": True,
        "FOLLOW_UP": True,
        "TITLE": True,
        "REPLY": True,
        "TYPING": True,
        "IMAGEQA": True,
        "FILE_UPLOAD_MESS": True
    })
    
    # 插件配置
    plugins = Column(JSON, default={
        "search": False,
        "url_reader": False,
        "generate_image": False
    })
    
    # API配置
    api_keys = Column(JSON, default={})  # 存储加密的API密钥
    api_urls = Column(JSON, default={})
    
    # 关系
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    files = relationship("File", back_populates="user", cascade="all, delete-orphan")

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=True)
    model = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # 会话配置
    system_prompt = Column(Text, nullable=True)
    temperature = Column(Integer, default=0.7)
    max_tokens = Column(Integer, nullable=True)
    
    # 关系
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    role = Column(String(50), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False)
    
    # 额外数据 - 重命名 metadata 为 message_metadata
    message_metadata = Column(JSON, default={})  # 存储token数、模型信息等
    attachments = Column(JSON, default=[])  # 存储文件引用
    
    # 关系
    conversation = relationship("Conversation", back_populates="messages")