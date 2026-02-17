from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import List, Optional
from sqlalchemy.orm import Session
import shutil
from pathlib import Path
import uuid
from datetime import datetime

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.workspace import Project, ProjectFile
from app.core.workspace.workspace_manager import WorkspaceManager
from app.schemas.v2.workspace import (
    WorkspaceInfo, ProjectInfo, ProjectDetail,
    FileContent, FileOperation, BatchFileOperation,
    ProjectType, ProjectStatus
)

router = APIRouter(prefix="/api/v2/workspace", tags=["workspace"])

@router.get("/info", response_model=WorkspaceInfo)
async def get_workspace_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取工作空间信息"""
    workspace_manager = WorkspaceManager()
    
    # 统计项目数量
    project_count = db.query(Project).filter(
        Project.user_id == current_user.id
    ).count()
    
    # 确保 user_id 是字符串格式
    user_id_str = str(current_user.id) if isinstance(current_user.id, uuid.UUID) else current_user.id
    
    # 计算存储使用
    total_size = workspace_manager.calculate_user_storage(user_id_str)
    max_storage = 1024 * 1024 * 1024  # 1GB 限制
    
    return WorkspaceInfo(
        user_id=user_id_str,
        total_projects=project_count,
        total_size=total_size,
        storage_used_percentage=(total_size / max_storage) * 100
    )

@router.get("/projects", response_model=List[ProjectInfo])
async def list_projects(
    status: Optional[str] = None,
    project_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """列出用户项目"""
    query = db.query(Project).filter(Project.user_id == current_user.id)
    
    if status:
        query = query.filter(Project.status == status)
    if project_type:
        query = query.filter(Project.project_type == project_type)
    
    projects = query.order_by(
        Project.updated_at.desc()
    ).offset(offset).limit(limit).all()
    
    result = []
    for project in projects:
        file_count = db.query(ProjectFile).filter(
            ProjectFile.project_id == project.id
        ).count()
        
        # 处理项目类型，确保符合 schema 要求
        project_type_normalized = project.project_type
        if project_type_normalized not in ['python', 'javascript', 'typescript', 'mixed', 'other']:
            # 如果是 bash 或其他未知类型，归类为 'other'
            project_type_normalized = 'other'
        
        # 处理状态
        status_normalized = project.status or "active"
        if status_normalized not in ['active', 'archived', 'template']:
            status_normalized = 'active'
        
        result.append(ProjectInfo(
            id=str(project.id),
            name=project.name,
            description=project.description,
            type=ProjectType(project_type_normalized),
            status=ProjectStatus(status_normalized),
            created_at=project.created_at,
            updated_at=project.updated_at or project.created_at,  # 使用 created_at 作为默认值
            last_executed_at=project.last_executed_at,
            execution_count=project.execution_count or 0,  # 默认值 0
            file_count=file_count,
            size=project.message_data.get("size", 0) if project.message_data else 0
        ))
    
    return result

@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project_detail(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取项目详情"""
    # 尝试将 project_id 转换为 UUID
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    
    project = db.query(Project).filter(
        Project.id == project_uuid,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # 获取文件列表
    files = db.query(ProjectFile).filter(
        ProjectFile.project_id == project.id
    ).all()
    
    file_contents = [
        FileContent(
            path=file.file_path,
            content=file.content,
            language=file.language or "text",
            size=len(file.content)
        )
        for file in files
    ]
    
    # 处理项目类型
    project_type_normalized = project.project_type
    if project_type_normalized not in ['python', 'javascript', 'typescript', 'mixed', 'other']:
        project_type_normalized = 'other'
    
    # 处理状态
    status_normalized = project.status or "active"
    if status_normalized not in ['active', 'archived', 'template']:
        status_normalized = 'active'
    
    return ProjectDetail(
        id=str(project.id),
        name=project.name,
        description=project.description,
        type=ProjectType(project_type_normalized),
        status=ProjectStatus(status_normalized),
        created_at=project.created_at,
        updated_at=project.updated_at or project.created_at,
        last_executed_at=project.last_executed_at,
        execution_count=project.execution_count or 0,
        file_count=len(files),
        size=sum(len(f.content) for f in files),
        files=file_contents,
        structure=project.message_data.get("structure", {}) if project.message_data else {},
        dependencies=project.dependencies or [],
        entry_point=project.entry_point,
        git_repo=project.git_repo,
        settings=project.settings or {}
    )

@router.get("/projects/{project_id}/files/{file_path:path}")
async def get_file_content(
    project_id: str,
    file_path: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取文件内容"""
    # 尝试将 project_id 转换为 UUID
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    
    # 验证项目权限
    project = db.query(Project).filter(
        Project.id == project_uuid,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # 获取文件
    file = db.query(ProjectFile).filter(
        ProjectFile.project_id == project_uuid,
        ProjectFile.file_path == file_path
    ).first()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    return {
        "content": file.content,
        "language": file.language,
        "size": len(file.content)
    }

@router.post("/projects/{project_id}/files")
async def update_files(
    project_id: str,
    operations: BatchFileOperation,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """批量更新项目文件"""
    # 尝试将 project_id 转换为 UUID
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    
    # 验证项目权限
    project = db.query(Project).filter(
        Project.id == project_uuid,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    workspace_manager = WorkspaceManager()
    results = []
    
    # 确保 user_id 是字符串格式
    user_id_str = str(current_user.id) if isinstance(current_user.id, uuid.UUID) else current_user.id
    
    for op in operations.operations:
        try:
            if op.operation == "create" or op.operation == "update":
                # 添加或更新文件
                result = await workspace_manager.add_file(
                    user_id=user_id_str,
                    project_id=project_id,
                    file_path=op.file_path,
                    content=op.content or "",
                    auto_commit=bool(operations.commit_message)
                )
                
                # 更新数据库
                existing_file = db.query(ProjectFile).filter(
                    ProjectFile.project_id == project_uuid,
                    ProjectFile.file_path == op.file_path
                ).first()
                
                if existing_file:
                    existing_file.content = op.content or ""
                else:
                    new_file = ProjectFile(
                        project_id=project_uuid,
                        file_path=op.file_path,
                        content=op.content or "",
                        file_type="code",
                        language=workspace_manager._detect_language(op.file_path)
                    )
                    db.add(new_file)
                
                results.append({"operation": op.operation, "file": op.file_path, "success": True})
                
            elif op.operation == "delete":
                # 删除文件
                await workspace_manager.delete_file(
                    user_id=user_id_str,
                    project_id=project_id,
                    file_path=op.file_path
                )
                
                # 从数据库删除
                db.query(ProjectFile).filter(
                    ProjectFile.project_id == project_uuid,
                    ProjectFile.file_path == op.file_path
                ).delete()
                
                results.append({"operation": op.operation, "file": op.file_path, "success": True})
                
        except Exception as e:
            results.append({
                "operation": op.operation,
                "file": op.file_path,
                "success": False,
                "error": str(e)
            })
    
    # 更新项目的 updated_at 时间戳
    project.updated_at = datetime.utcnow()
    
    db.commit()
    
    return {"results": results}

@router.post("/projects/{project_id}/upload")
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    path: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """上传文件到项目"""
    # 尝试将 project_id 转换为 UUID
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    
    # 验证项目权限
    project = db.query(Project).filter(
        Project.id == project_uuid,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # 确定文件路径
    file_path = path or file.filename
    
    # 读取文件内容
    content = await file.read()
    content_str = content.decode('utf-8', errors='replace')
    
    # 确保 user_id 是字符串格式
    user_id_str = str(current_user.id) if isinstance(current_user.id, uuid.UUID) else current_user.id
    
    # 保存文件
    workspace_manager = WorkspaceManager()
    result = await workspace_manager.add_file(
        user_id=user_id_str,
        project_id=project_id,
        file_path=file_path,
        content=content_str
    )
    
    # 更新数据库
    existing_file = db.query(ProjectFile).filter(
        ProjectFile.project_id == project_uuid,
        ProjectFile.file_path == file_path
    ).first()
    
    if existing_file:
        existing_file.content = content_str
    else:
        new_file = ProjectFile(
            project_id=project_uuid,
            file_path=file_path,
            content=content_str,
            file_type="code",
            language=workspace_manager._detect_language(file_path),
            size=len(content)
        )
        db.add(new_file)
    
    db.commit()
    
    return {
        "success": True,
        "file_path": file_path,
        "size": len(content)
    }

@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除项目"""
    # 尝试将 project_id 转换为 UUID
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    
    # 验证项目权限
    project = db.query(Project).filter(
        Project.id == project_uuid,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # 确保 user_id 是字符串格式
    user_id_str = str(current_user.id) if isinstance(current_user.id, uuid.UUID) else current_user.id
    
    # 删除工作空间文件
    workspace_manager = WorkspaceManager()
    await workspace_manager.delete_project(
        user_id=user_id_str,
        project_id=project_id
    )
    
    # 删除数据库记录
    db.delete(project)
    db.commit()
    
    return {"success": True, "message": "Project deleted successfully"}