from sqlalchemy import Column, String, Text, JSON, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List
from sqlalchemy import Integer

from sqlalchemy import Column, String, Enum
import enum

class ProjectStatus(str, enum.Enum):
    """项目状态枚举"""
    ACTIVE = "active"
    ARCHIVED = "archived"
    TEMPLATE = "template"
    DELETED = "deleted"
    CREATING = "creating"  # 新增：创建中状态
    ERROR = "error"        # 新增：错误状态

class Project(Base):
    """项目模型 - 合并了workspace和vibe coding功能"""
    __tablename__ = "projects"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # 基本信息
    name = Column(String, nullable=False)
    description = Column(Text)
    project_type = Column(String, default="python")  # python, javascript, web, mixed
    
    # 状态管理
    status = Column(
        String(50), 
        default=ProjectStatus.ACTIVE,
        nullable=False,
        server_default="active",
        comment="项目状态"
    )
    
    # 工作空间信息
    workspace_path = Column(String)  # 工作空间路径
    git_repo = Column(String)  # Git仓库URL
    
    # 项目配置
    entry_point = Column(String)  # 入口文件
    dependencies = Column(JSON, default=list)  # 项目依赖
    tech_stack = Column(JSON, default=lambda: [])  # 技术栈列表
    
    # 预览和部署
    preview_url = Column(String)  # 预览链接
    deployment_url = Column(String)  # 部署链接
    
    # 统计信息
    file_count = Column(Integer, default=0)
    size = Column(Integer, default=0)  # 文件总大小（字节）
    
    # 执行相关
    last_executed_at = Column(DateTime)
    execution_count = Column(Integer, default=0)
    
    # Vibe Coding 特有字段
    creation_prompt = Column(Text, nullable=True)      # 用户原始输入
    enhanced_prompt = Column(Text, nullable=True)       # 优化后的 prompt
    ai_response = Column(Text, nullable=True)           # AI 的完整响应
    meta_prompt_data = Column(JSON, nullable=True)     # 完整的双重调用数据
    
    # 项目设置和元数据
    message_data = Column(JSON, default=dict)  # 项目元数据
    settings = Column(JSON, default=dict)  # 项目设置
    
    # 权限和可见性
    is_public = Column(Boolean, default=False)
    is_template = Column(Boolean, default=False)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deployed_at = Column(DateTime, nullable=True)  # 部署时间
    
    # 关系定义
    user = relationship("User", back_populates="projects")
    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
    executions = relationship("ProjectExecution", back_populates="project", cascade="all, delete-orphan")
    
    # 兼容性：支持对话关系（如果存在）
    # conversations = relationship("Conversation", back_populates="current_project")

class ProjectFile(Base):
    """项目文件模型 - 合并了两个版本的功能"""
    __tablename__ = "project_files"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    
    # 文件基本信息
    file_path = Column(String, nullable=False)  # 相对路径
    content = Column(Text, nullable=False)
    file_type = Column(String)  # code, config, data, etc.
    language = Column(String)  # 编程语言
    
    # 文件属性
    size = Column(Integer)  # 文件大小（字节）
    checksum = Column(String)  # 文件校验和
    is_entry_point = Column(Boolean, default=False)  # 是否是入口文件
    is_generated = Column(Boolean, default=True)     # 是否是生成的文件
    
    # 元数据
    message_data = Column(JSON, default=dict)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    project = relationship("Project", back_populates="files")

class ProjectExecution(Base):
    """项目执行记录"""
    __tablename__ = "project_executions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # 执行状态
    status = Column(String)  # running, success, failed, debugging
    exit_code = Column(Integer)
    
    # 输出信息
    stdout = Column(Text)
    stderr = Column(Text)
    
    # 时间信息
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime)
    duration = Column(Integer)  # 执行时长（秒）
    
    # 调试信息
    debug_attempts = Column(Integer, default=0)
    debug_history = Column(JSON, default=list)
    
    # 环境信息
    environment = Column(JSON, default=dict)  # 环境变量
    parameters = Column(JSON, default=dict)  # 执行参数
    
    # 关系
    project = relationship("Project", back_populates="executions")
    user = relationship("User")