from sqlalchemy import Column, String, Boolean, DateTime, JSON, Integer, ForeignKey, Text, Float, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.db.base import Base


class File(Base):
    """文件模型"""
    __tablename__ = "files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # 文件基本信息
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)  # 原始文件名
    file_type = Column(String(50), nullable=False, index=True)  # image, document, code, audio
    file_size = Column(Integer, nullable=False)  # 字节
    file_path = Column(String(500), nullable=False, unique=True)  # 存储路径
    file_hash = Column(String(64), nullable=False, index=True)  # SHA256哈希
    mime_type = Column(String(100), nullable=False)

    # 时间戳
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)
    accessed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)  # 文件过期时间

    # 处理状态
    status = Column(String(50), default="uploaded", nullable=False, index=True)
    # uploaded, processing, processed, failed, deleted
    processing_error = Column(Text, nullable=True)

    # 提取的内容
    extracted_text = Column(Text, nullable=True)
    text_language = Column(String(10), nullable=True)  # 检测到的语言
    summary = Column(Text, nullable=True)  # AI生成的摘要

    # 元数据
    metadata_data = Column(JSON, default={})
    # 对于图片: dimensions, format, mode, exif
    # 对于文档: page_count, word_count, author
    # 对于音频: duration, bitrate, sample_rate

    # 标签和分类
    tags = Column(JSON, default=[])
    category = Column(String(50), nullable=True, index=True)

    # 访问控制
    is_public = Column(Boolean, default=False)
    access_count = Column(Integer, default=0)

    # 关系
    user = relationship("User", back_populates="files")
    file_shares = relationship("FileShare", back_populates="file", cascade="all, delete-orphan")
    
    # 修复：明确指定外键关系
    file_conversions = relationship(
        "FileConversion",
        foreign_keys="FileConversion.original_file_id",
        back_populates="original_file",
        cascade="all, delete-orphan"
    )
    
    # 添加：作为转换结果的文件关系
    conversions_as_result = relationship(
        "FileConversion",
        foreign_keys="FileConversion.converted_file_id",
        back_populates="converted_file"
    )

    # 复合索引
    __table_args__ = (
        Index('idx_user_type_status', 'user_id', 'file_type', 'status'),
        Index('idx_user_uploaded', 'user_id', 'uploaded_at'),
    )


class FileShare(Base):
    """文件分享模型"""
    __tablename__ = "file_shares"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=False, index=True)
    shared_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # 分享设置
    share_token = Column(String(100), unique=True, nullable=False, index=True)
    share_type = Column(String(50), default="link")  # link, email, embed

    # 访问控制
    password_hash = Column(String(255), nullable=True)  # 密码保护
    expires_at = Column(DateTime, nullable=True, index=True)
    max_downloads = Column(Integer, nullable=True)
    download_count = Column(Integer, default=0)

    # 权限
    allow_download = Column(Boolean, default=True)
    allow_preview = Column(Boolean, default=True)
    require_login = Column(Boolean, default=False)

    # 接收者信息（如果是定向分享）
    recipient_email = Column(String(255), nullable=True)
    recipient_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    accessed_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    # 状态
    is_active = Column(Boolean, default=True)

    # 关系
    file = relationship("File", back_populates="file_shares")
    sharer = relationship("User", foreign_keys=[shared_by])
    recipient = relationship("User", foreign_keys=[recipient_id])


class FileConversion(Base):
    """文件转换记录"""
    __tablename__ = "file_conversions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_file_id = Column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=False)
    converted_file_id = Column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=True)

    # 转换信息
    target_format = Column(String(50), nullable=False)
    conversion_type = Column(String(50), nullable=False)  # format, compress, resize, extract

    # 转换参数
    parameters = Column(JSON, default={})
    # 例如: {"quality": 80, "width": 1920, "height": 1080}

    # 状态
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    error_message = Column(Text, nullable=True)

    # 时间和性能
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)

    # 关系 - 修复：明确指定 back_populates
    original_file = relationship(
        "File",
        foreign_keys=[original_file_id],
        back_populates="file_conversions"
    )
    converted_file = relationship(
        "File",
        foreign_keys=[converted_file_id],
        back_populates="conversions_as_result"
    )


class FileChunk(Base):
    """文件分块（用于大文件上传）"""
    __tablename__ = "file_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_id = Column(String(100), nullable=False, index=True)  # 上传会话ID

    # 分块信息
    chunk_number = Column(Integer, nullable=False)
    total_chunks = Column(Integer, nullable=False)
    chunk_size = Column(Integer, nullable=False)
    chunk_hash = Column(String(64), nullable=False)

    # 存储
    chunk_path = Column(String(500), nullable=False)

    # 状态
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    is_verified = Column(Boolean, default=False)

    # 复合唯一约束
    __table_args__ = (
        Index('idx_upload_chunk', 'upload_id', 'chunk_number', unique=True),
    )


class FileAccess(Base):
    """文件访问日志"""
    __tablename__ = "file_access_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # 访问信息
    action = Column(String(50), nullable=False)  # view, download, share, delete
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    referer = Column(String(500), nullable=True)

    # 分享访问
    share_id = Column(UUID(as_uuid=True), ForeignKey("file_shares.id"), nullable=True)

    # 时间戳
    accessed_at = Column(DateTime, default=datetime.utcnow, index=True)

    # 性能指标
    response_time_ms = Column(Integer, nullable=True)
    bytes_sent = Column(Integer, nullable=True)

    # 关系
    file = relationship("File")
    user = relationship("User")
    share = relationship("FileShare")