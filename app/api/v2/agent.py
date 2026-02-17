from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, List
from sqlalchemy.orm import Session
import uuid

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.services.enhanced_code_service import EnhancedCodeService
from app.models.workspace import Project

from app.core.ai_engine import AIEngine
from app.schemas.v2.agent import (
    ProjectCreateRequest,
    ProjectExecuteRequest,
    FileEditRequest,
    ProjectResponse
)

router = APIRouter(prefix="/api/v2/agent", tags=["agent"])

@router.post("/create-project", response_model=ProjectResponse)
async def create_project(
    request: ProjectCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建新项目"""
    ai_engine = AIEngine()
    service = EnhancedCodeService(db, ai_engine)
    
    try:
        # 确保 user_id 是字符串格式的 UUID
        user_id = str(current_user.id) if isinstance(current_user.id, uuid.UUID) else current_user.id
        
        result = await service.create_project_from_request(
            user_id=user_id,
            request=request.prompt,
            model=request.model,
            auto_execute=request.auto_execute,
            max_debug_attempts=request.max_debug_attempts
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Project creation failed"))
        
        return ProjectResponse(**result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/execute-project/{project_id}")
async def execute_project(
    project_id: str,
    request: ProjectExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """执行项目"""
    ai_engine = AIEngine()
    service = EnhancedCodeService(db, ai_engine)
    
    try:
        # 确保 user_id 是字符串格式的 UUID
        user_id = str(current_user.id) if isinstance(current_user.id, uuid.UUID) else current_user.id
        
        result = await service.execute_project_with_debug(
            user_id=user_id,
            project_id=project_id,
            max_attempts=request.max_debug_attempts
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/edit-file/{project_id}")
async def edit_file(
    project_id: str,
    request: FileEditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """编辑项目文件"""
    ai_engine = AIEngine()
    service = EnhancedCodeService(db, ai_engine)
    
    try:
        # 确保 user_id 是字符串格式的 UUID
        user_id = str(current_user.id) if isinstance(current_user.id, uuid.UUID) else current_user.id
        
        # 获取项目
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.user_id == current_user.id
        ).first()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # TODO: 实现文件编辑逻辑
        # 1. 获取当前文件内容
        # 2. 使用AI生成修改
        # 3. 保存新内容
        # 4. 可选：重新执行项目
        
        return {"success": True, "message": "File edited successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/projects")
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """列出用户的所有项目"""
    projects = db.query(Project).filter(
        Project.user_id == current_user.id
    ).order_by(Project.created_at.desc()).all()
    
    return [
        {
            "id": str(project.id),
            "name": project.name,
            "type": project.project_type,
            "created_at": project.created_at.isoformat(),
            "last_executed_at": project.last_executed_at.isoformat() if project.last_executed_at else None
        }
        for project in projects
    ]