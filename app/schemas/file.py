from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID


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


class FileCreate(BaseModel):
    """文件创建请求"""
    filename: str
    file_type: str = Field(..., pattern="^(image|document|code|audio)$")
    file_size: int = Field(..., gt=0)
    mime_type: str
    process_immediately: bool = True
    conversation_id: Optional[str] = None


class FileUpdate(BaseModel):
    """文件更新请求"""
    filename: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(uploaded|processing|processed|failed)$")
    extracted_text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class FileProcessRequest(BaseModel):
    """文件处理请求"""
    extract_text: bool = True
    detect_language: bool = False
    generate_summary: bool = False
    extract_metadata: bool = True


class FileProcessResponse(BaseModel):
    """文件处理响应"""
    file_id: UUID
    status: str
    extracted_content: Optional[str] = None
    detected_language: Optional[str] = None
    summary: Optional[str] = None
    metadata: Dict[str, Any] = {}
    processing_time_ms: int


class FileBatchUploadRequest(BaseModel):
    """批量上传请求"""
    files: List[FileCreate]
    process_immediately: bool = True
    conversation_id: Optional[str] = None


class FileBatchUploadResponse(BaseModel):
    """批量上传响应"""
    total_files: int
    successful: int
    failed: int
    results: List[Dict[str, Any]]


class FileSearchRequest(BaseModel):
    """文件搜索请求"""
    query: Optional[str] = None
    file_type: Optional[str] = None
    uploaded_after: Optional[datetime] = None
    uploaded_before: Optional[datetime] = None
    status: Optional[str] = None
    limit: int = Field(default=50, le=100)
    offset: int = Field(default=0, ge=0)


class FileSearchResponse(BaseModel):
    """文件搜索响应"""
    total: int
    files: List[FileResponse]
    query: Optional[str] = None


class FileShareRequest(BaseModel):
    """文件分享请求"""
    file_id: UUID
    expires_in_hours: Optional[int] = Field(None, gt=0, le=168)  # 最多7天
    password: Optional[str] = None
    allow_download: bool = True


class FileShareResponse(BaseModel):
    """文件分享响应"""
    share_url: str
    share_token: str
    expires_at: Optional[datetime] = None
    password_protected: bool = False


class FileMetadata(BaseModel):
    """文件元数据"""
    size: int
    created: float
    modified: float
    mime_type: Optional[str] = None
    extension: str
    hash: str

    # 图片特定
    dimensions: Optional[tuple[int, int]] = None
    mode: Optional[str] = None
    format: Optional[str] = None

    # 文档特定
    page_count: Optional[int] = None
    word_count: Optional[int] = None

    # 音频特定
    duration_seconds: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None


class FileQuota(BaseModel):
    """文件配额信息"""
    total_storage_mb: int
    used_storage_mb: float
    available_storage_mb: float
    file_count: int
    max_file_size_mb: int

    @validator('available_storage_mb')
    def calculate_available(cls, v, values):
        if 'total_storage_mb' in values and 'used_storage_mb' in values:
            return values['total_storage_mb'] - values['used_storage_mb']
        return v