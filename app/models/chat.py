from sqlalchemy import Column, String, Boolean, DateTime, JSON, Integer, ForeignKey, Text, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.db.base import Base


class ChatSession(Base):
    """聊天会话模型"""
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    is_pinned = Column(Boolean, default=False)

    # 会话配置
    config = Column(JSON, default={})
    tags = Column(JSON, default=[])

    # 统计信息
    message_count = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    # 关系
    user = relationship("User", backref="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    # 新增项目关联字段
    current_project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    session_type = Column(String(50), default="general")  # general, project_focused, vibe_coding
    
    # 项目上下文信息
    project_context = Column(JSON, default={})  # 存储项目相关的对话上下文
    
    # 关系
    current_project = relationship("Project", backref="chat_sessions")


class ChatMessage(Base):
    """聊天消息模型"""
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("chat_messages.id"), nullable=True)

    # 消息内容
    role = Column(String(50), nullable=False)  # user, assistant, system, tool
    content = Column(Text, nullable=False)
    content_type = Column(String(50), default="text")  # text, image, file, code

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)

    # 状态
    is_deleted = Column(Boolean, default=False)
    is_edited = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)

    # 元数据 - 重命名 metadata 为 message_data
    message_data = Column(JSON, default={})
    attachments = Column(JSON, default=[])

    # AI相关
    model = Column(String(100), nullable=True)
    tokens = Column(JSON, nullable=True)  # {prompt_tokens, completion_tokens, total_tokens}
    latency_ms = Column(Integer, nullable=True)

    # 评分和反馈
    rating = Column(Integer, nullable=True)  # 1-5
    feedback = Column(Text, nullable=True)

    # 关系
    session = relationship("ChatSession", back_populates="messages")
    replies = relationship("ChatMessage", backref="parent", remote_side=[id])
    
    # 新增 AI 处理相关字段
    intent_detected = Column(String(100), nullable=True)
    prompt_enhancement = Column(JSON, nullable=True)  # 存储 meta-prompt 数据
    project_action = Column(String(100), nullable=True)  # create, modify, execute, preview
    
    # AI 调用记录
    ai_calls = Column(JSON, default=[])  # 记录双重调用过程

class ChatTemplate(Base):
    """聊天模板"""
    __tablename__ = "chat_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # null表示系统模板
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)

    # 模板内容
    system_prompt = Column(Text, nullable=True)
    initial_messages = Column(JSON, default=[])
    variables = Column(JSON, default={})  # 模板变量定义

    # 配置
    model = Column(String(100), nullable=True)
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)

    # 使用统计
    usage_count = Column(Integer, default=0)
    last_used = Column(DateTime, nullable=True)

    # 状态
    is_public = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatShare(Base):
    """聊天分享"""
    __tablename__ = "chat_shares"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False)
    shared_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # 分享设置
    share_token = Column(String(100), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    view_count = Column(Integer, default=0)
    max_views = Column(Integer, nullable=True)

    # 权限
    allow_copy = Column(Boolean, default=True)
    allow_continue = Column(Boolean, default=False)
    password = Column(String(255), nullable=True)  # 加密存储

    # 状态
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_viewed = Column(DateTime, nullable=True)

    # 关系
    session = relationship("ChatSession")
    sharer = relationship("User")