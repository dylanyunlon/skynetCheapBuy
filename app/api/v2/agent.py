from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, List
from sqlalchemy.orm import Session
import uuid
import os
import json
import logging

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.services.enhanced_code_service import EnhancedCodeService
from app.models.workspace import Project

from app.core.ai_engine import AIEngine
from app.schemas.v2.agent import (
    ProjectCreateRequest,
    ProjectExecuteRequest,
    FileEditRequest,
    ProjectResponse,
    AgenticTaskRequest,
)

from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

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


# ============================================================================
# Agentic Loop 端点
# ============================================================================

@router.post("/agentic-task")
async def agentic_task(
    request: AgenticTaskRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🔧 Agentic Loop 核心端点（SSE 流式推送）
    
    AI 多轮自主调用工具直到完成任务。前端通过 SSE 实时接收事件：
    
    事件类型：
    - start:       任务开始（包含工作目录等信息）
    - text:        AI 的文本输出
    - tool_start:  AI 请求执行工具（附带工具名称和参数）
    - tool_result: 工具执行结果
    - turn:        一轮循环结束
    - done:        任务完成
    - error:       出错
    
    前端用法：
        const evtSource = new EventSource('/api/v2/agent/agentic-task');
        evtSource.addEventListener('text', (e) => { ... });
        evtSource.addEventListener('tool_start', (e) => { ... });
    """
    from app.core.agents.agentic_loop import create_agentic_loop
    
    ai_engine = AIEngine()
    user_id = str(current_user.id) if isinstance(current_user.id, uuid.UUID) else current_user.id
    
    loop = create_agentic_loop(
        ai_engine=ai_engine,
        user_id=user_id,
        project_id=request.project_id,
        model=request.model,
        max_turns=request.max_turns,
        system_prompt=request.system_prompt
    )
    
    # 如果指定了自定义工作目录（高级用法，比如操作现有项目）
    if request.work_dir:
        loop.work_dir = os.path.abspath(request.work_dir)
        loop.executor.work_dir = loop.work_dir
        os.makedirs(loop.work_dir, exist_ok=True)
    
    logger.info(
        f"[Agentic] User {user_id} starting task, model={request.model}, "
        f"work_dir={loop.work_dir}, max_turns={request.max_turns}"
    )
    
    async def event_generator():
        try:
            async for event in loop.run(request.task):
                yield {
                    "event": event.get("type", "message"),
                    "data": json.dumps(event, ensure_ascii=False, default=str)
                }
        except Exception as e:
            logger.error(f"[Agentic] Stream error: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({
                    "type": "error",
                    "message": f"Stream error: {str(e)}"
                }, ensure_ascii=False)
            }
    
    return EventSourceResponse(
        event_generator(),
        sep="\n",           # 使用 \n 而非 \r\n，确保前端 split('\n\n') 能正确解析
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/agentic-create-project")
async def agentic_create_project(
    request: AgenticTaskRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🔧 使用 Agentic Loop 创建项目（同步模式，等待完成后返回）
    
    与旧的 create-project 不同：
    - 旧版：AI 生成代码文本 → 正则提取 → 保存 → 执行 → 失败重试
    - 新版：AI 自主调用 write_file/bash/edit_file 工具循环，直到项目跑通
    
    返回值包含项目路径和所有执行事件。
    """
    from app.core.agents.agentic_loop import create_agentic_loop
    
    ai_engine = AIEngine()
    user_id = str(current_user.id) if isinstance(current_user.id, uuid.UUID) else current_user.id
    
    # 生成项目 ID
    project_id = request.project_id or str(uuid.uuid4())
    
    loop = create_agentic_loop(
        ai_engine=ai_engine,
        user_id=user_id,
        project_id=project_id,
        model=request.model,
        max_turns=request.max_turns,
        system_prompt=request.system_prompt
    )
    
    logger.info(f"[Agentic] User {user_id} creating project via agentic loop, project_id={project_id}")
    
    try:
        # 同步运行（收集所有事件）
        result = await loop.run_sync(request.task)
        
        # 列出创建的文件
        created_files = []
        for event in result.get("events", []):
            if event.get("type") == "tool_result" and event.get("tool") == "write_file":
                try:
                    r = json.loads(event.get("result", "{}"))
                    if r.get("path"):
                        created_files.append(r["path"])
                except:
                    pass
        
        return {
            "success": result["success"],
            "project_id": project_id,
            "project_path": loop.work_dir,
            "turns": result["turns"],
            "total_tool_calls": result["total_tool_calls"],
            "duration": result["duration"],
            "files": created_files,
            "final_text": result["final_text"][:3000],
            "events_summary": [
                {
                    "type": e["type"],
                    "tool": e.get("tool"),
                    "turn": e.get("turn"),
                    "success": e.get("success"),
                }
                for e in result.get("events", [])
                if e["type"] in ("tool_start", "tool_result", "done", "error")
            ]
        }
        
    except Exception as e:
        logger.error(f"[Agentic] Project creation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))