from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.workspace import Project, ProjectExecution
from app.core.agents.code_agent import DebugAgent
from app.core.ai_engine import AIEngine
from app.schemas.v2.execution import DebugInfo

router = APIRouter(prefix="/api/v2/debug", tags=["debug"])

@router.post("/analyze/{execution_id}", response_model=DebugInfo)
async def analyze_execution_error(
    execution_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """分析执行错误"""
    # 获取执行记录
    execution = db.query(ProjectExecution).filter(
        ProjectExecution.id == execution_id,
        ProjectExecution.user_id == current_user.id
    ).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    if execution.status != "failed":
        raise HTTPException(status_code=400, detail="Execution did not fail")
    
    # 使用调试代理分析错误
    ai_engine = AIEngine()
    debug_agent = DebugAgent(ai_engine)
    
    # 获取相关文件内容
    project = db.query(Project).filter(
        Project.id == execution.project_id
    ).first()
    
    # 简化分析（实际应该更复杂）
    analysis = await debug_agent.analyze({
        "error_info": {
            "stderr": execution.stderr,
            "exit_code": execution.exit_code
        },
        "code": "# Project code would be here",
        "file_path": project.entry_point
    })
    
    # 解析错误类型和位置
    error_type = "runtime_error"
    error_message = execution.stderr.split('\n')[0] if execution.stderr else "Unknown error"
    
    return DebugInfo(
        error_type=error_type,
        error_message=error_message,
        file_path=project.entry_point,
        line_number=None,
        suggested_fix=analysis.get("analysis", ""),
        confidence=0.8
    )

@router.post("/suggest-fix/{project_id}")
async def suggest_fix(
    project_id: str,
    error_info: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """建议错误修复"""
    # 验证项目权限
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # 使用调试代理生成修复建议
    ai_engine = AIEngine()
    debug_agent = DebugAgent(ai_engine)
    
    # 这里应该获取实际的代码内容
    suggestions = []
    
    return {
        "success": True,
        "suggestions": suggestions
    }