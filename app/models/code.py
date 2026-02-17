# app/models/code.py
from sqlalchemy import Column, String, Text, JSON, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid
from datetime import datetime

class CodeSnippet(Base):
    """代码片段模型"""
    __tablename__ = "code_snippets"
    
    # 使用 UUID 作为主键
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # user_id 也应该是 UUID 类型，以匹配 users 表
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    language = Column(String, nullable=False)
    code = Column(Text, nullable=False)
    wrapped_code = Column(Text)
    title = Column(String)
    description = Column(Text)
    conversation_id = Column(String)
    file_path = Column(String)
    
    # 将 metadata 改名为 snippet_metadata
    snippet_metadata = Column(JSON, default=dict)
    
    execution_history = Column(JSON, default=list)
    cron_jobs = Column(JSON, default=list)
    last_executed = Column(DateTime)
    execution_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    
    # 关系
    user = relationship("User", back_populates="code_snippets")
    
    def to_dict(self):
        """转换为字典"""
        return {
            "id": str(self.id),  # 转换 UUID 为字符串
            "user_id": str(self.user_id),  # 转换 UUID 为字符串
            "language": self.language,
            "code": self.code,
            "wrapped_code": self.wrapped_code,
            "title": self.title,
            "description": self.description,
            "conversation_id": self.conversation_id,
            "file_path": self.file_path,
            "metadata": self.snippet_metadata,  # 对外仍然使用 metadata
            "execution_history": self.execution_history or [],
            "cron_jobs": self.cron_jobs or [],
            "last_executed": self.last_executed.isoformat() if self.last_executed else None,
            "execution_count": self.execution_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class GeneratedCode(Base):
    """生成的代码记录"""
    __tablename__ = "generated_codes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    conversation_id = Column(String, nullable=False)
    
    language = Column(String, nullable=False)  # python, bash, etc.
    code = Column(Text, nullable=False)  # 原始代码
    wrapped_code = Column(Text)  # 包装后的代码
    
    file_path = Column(String)  # 保存路径
    description = Column(Text)  # 代码描述
    
    extra_metadata = Column(JSON)  # 额外元数据
    execution_history = Column(JSON)  # 执行历史
    
    last_executed_at = Column(DateTime)
    execution_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    user = relationship("User", back_populates="generated_codes")
    cron_jobs = relationship("CronJob", back_populates="code", cascade="all, delete-orphan")

class CronJob(Base):
    """定时任务记录"""
    __tablename__ = "cron_jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    code_id = Column(UUID(as_uuid=True), ForeignKey("generated_codes.id"), nullable=False)
    
    job_name = Column(String, unique=True, nullable=False)
    cron_expression = Column(String, nullable=False)
    
    log_file = Column(String)
    is_active = Column(Boolean, default=True)
    
    last_run_at = Column(DateTime)
    next_run_at = Column(DateTime)
    run_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    user = relationship("User", back_populates="cron_jobs")
    code = relationship("GeneratedCode", back_populates="cron_jobs")