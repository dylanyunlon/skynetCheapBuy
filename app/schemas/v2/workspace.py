from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class ProjectType(str, Enum):
    """项目类型枚举"""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    MIXED = "mixed"
    OTHER = "other"

class ProjectStatus(str, Enum):
    """项目状态枚举"""
    ACTIVE = "active"
    ARCHIVED = "archived"
    TEMPLATE = "template"

class WorkspaceInfo(BaseModel):
    """工作空间信息"""
    user_id: str
    total_projects: int
    total_size: int
    storage_used_percentage: float

class ProjectInfo(BaseModel):
    """项目信息"""
    id: str
    name: str
    description: Optional[str]
    type: ProjectType
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    last_executed_at: Optional[datetime]
    execution_count: int
    file_count: int
    size: int

class FileContent(BaseModel):
    """文件内容"""
    path: str
    content: str
    language: str
    size: int

class ProjectDetail(BaseModel):
    """项目详情"""
    id: str
    name: str
    description: Optional[str]
    type: ProjectType
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    last_executed_at: Optional[datetime]
    execution_count: int
    file_count: int
    size: int
    files: List[FileContent]
    structure: Dict[str, Any]
    dependencies: List[str]
    entry_point: Optional[str]
    git_repo: Optional[str]
    settings: Dict[str, Any]

class FileOperation(BaseModel):
    """文件操作"""
    operation: str = Field(..., pattern="^(create|update|delete)$")
    file_path: str
    content: Optional[str] = None

class BatchFileOperation(BaseModel):
    """批量文件操作"""
    operations: List[FileOperation]
    commit_message: Optional[str] = None