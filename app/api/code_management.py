# app/api/code_management.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from uuid import UUID

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.services.code_service import CodeService
from app.services.ai_code_service import AICodeGenerationService
from app.core.ai_engine import AIEngine
from app.schemas.code import (
    CodeGenerateRequest,
    CodeGenerateResponse,
    CodeExecuteRequest,
    CodeExecuteResponse,
    CodeSnippetResponse,
    CronJobRequest,
    CronJobResponse,
    CodeListResponse
)

router = APIRouter(prefix="/api/v1/code", tags=["code_management"])

@router.post("/generate", response_model=CodeGenerateResponse)
async def generate_code(
    request: CodeGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    智能生成代码
    
    - 自动识别需求类型（Python/Bash脚本）
    - 生成完整可执行的代码
    - 自动提取并设置定时任务（如果需要）
    """
    code_service = CodeService(db)
    ai_engine = AIEngine()
    ai_code_service = AICodeGenerationService(ai_engine, code_service)
    
    # 检测代码生成意图
    is_code_gen, script_type = ai_code_service.detect_code_generation_intent(request.prompt)
    
    if not is_code_gen and not request.force_generation:
        raise HTTPException(
            status_code=400,
            detail="Request does not appear to be asking for code generation. Use force_generation=true to override."
        )
    
    # 如果用户指定了语言，使用用户的选择
    if request.language:
        script_type = request.language
    elif not script_type:
        script_type = "python"  # 默认Python
    
    try:
        # 生成代码
        result = await ai_code_service.generate_code_with_ai(
            user_request=request.prompt,
            script_type=script_type,
            model=request.model or current_user.preferred_model,
            user_id=str(current_user.id),
            conversation_id=request.conversation_id,
            system_prompt=request.system_prompt
        )
        
        # 如果有定时任务需求并且用户允许，自动设置
        if result.get("cron_ready") and request.auto_setup_cron:
            cron_result = await ai_code_service.setup_cron_job_from_code(
                code_id=result["cron_ready"]["code_id"],
                cron_expression=result["cron_ready"]["cron_expression"],
                user_id=str(current_user.id),
                job_name=result["cron_ready"]["suggested_job_name"]
            )
            result["cron_setup"] = cron_result
        
        return CodeGenerateResponse(
            success=True,
            ai_response=result["ai_response"],
            code_extraction=result.get("code_extraction"),
            script_type=script_type,
            cron_expression=result.get("cron_expression"),
            cron_setup=result.get("cron_setup"),
            metadata=result.get("metadata", {})
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/execute/{code_id}", response_model=CodeExecuteResponse)
async def execute_code(
    code_id: str,
    request: CodeExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """执行保存的代码"""
    code_service = CodeService(db)
    
    try:
        result = await code_service.execute_code(
            code_id=code_id,
            user_id=str(current_user.id),
            parameters=request.parameters,
            timeout=request.timeout
        )
        
        return CodeExecuteResponse(
            success=result["success"],
            exit_code=result["exit_code"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            execution_time=result["execution_time"],
            executed_at=result["executed_at"]
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/snippets", response_model=CodeListResponse)
async def list_code_snippets(
    language: Optional[str] = Query(None, description="Filter by language"),
    conversation_id: Optional[str] = Query(None, description="Filter by conversation"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """列出用户的代码片段"""
    code_service = CodeService(db)
    
    snippets = await code_service.list_code_snippets(
        user_id=str(current_user.id),
        language=language,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset
    )
    
    return CodeListResponse(
        snippets=snippets,
        total=len(snippets),
        limit=limit,
        offset=offset
    )

@router.get("/snippets/{code_id}", response_model=CodeSnippetResponse)
async def get_code_snippet(
    code_id: str,
    include_wrapped: bool = Query(False, description="Include wrapped code"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取代码片段详情"""
    code_service = CodeService(db)
    
    try:
        snippet = await code_service.get_code_snippet(
            code_id=code_id,
            user_id=str(current_user.id),
            include_wrapped=include_wrapped
        )
        return CodeSnippetResponse(**snippet)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/snippets/{code_id}")
async def update_code_snippet(
    code_id: str,
    updates: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新代码片段"""
    code_service = CodeService(db)
    
    try:
        updated = await code_service.update_code_snippet(
            code_id=code_id,
            user_id=str(current_user.id),
            updates=updates
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/snippets/{code_id}")
async def delete_code_snippet(
    code_id: str,
    remove_file: bool = Query(True, description="Remove file from filesystem"),
    remove_cron: bool = Query(True, description="Remove associated cron jobs"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除代码片段"""
    code_service = CodeService(db)
    
    try:
        success = await code_service.delete_code_snippet(
            code_id=code_id,
            user_id=str(current_user.id),
            remove_file=remove_file,
            remove_cron=remove_cron
        )
        return {"success": success}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# Cron 任务管理端点

@router.post("/cron/tasks", response_model=CronJobResponse)
async def create_cron_job(
    request: CronJobRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建定时任务"""
    code_service = CodeService(db)
    
    try:
        result = await code_service.create_cron_job(
            code_id=request.code_id,
            user_id=str(current_user.id),
            cron_expression=request.cron_expression,
            job_name=request.job_name,
            env_vars=request.env_vars,
            description=request.description
        )
        
        if result["success"]:
            return CronJobResponse(**result["job_info"])
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to create cron job"))
            
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/cron/tasks")
async def list_cron_jobs(
    active_only: bool = Query(True, description="Show only active jobs"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """列出定时任务"""
    from app.core.cron_manager import CronManager
    
    cron_manager = CronManager()
    jobs = cron_manager.list_jobs(
        user_id=str(current_user.id),
        active_only=active_only
    )
    
    return {
        "jobs": jobs,
        "total": len(jobs)
    }

@router.get("/cron/tasks/{job_id}")
async def get_cron_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取定时任务详情"""
    from app.core.cron_manager import CronManager
    
    cron_manager = CronManager()
    jobs = cron_manager.list_jobs(user_id=str(current_user.id))
    
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job

@router.get("/cron/tasks/{job_id}/logs")
async def get_cron_job_logs(
    job_id: str,
    lines: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取定时任务日志"""
    from app.core.cron_manager import CronManager
    
    cron_manager = CronManager()
    
    # 验证任务所有权
    jobs = cron_manager.list_jobs(user_id=str(current_user.id))
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    logs = cron_manager.get_job_logs(job_id, lines)
    if logs is None:
        raise HTTPException(status_code=404, detail="No logs found")
    
    return {
        "job_id": job_id,
        "logs": logs,
        "lines": lines
    }

@router.put("/cron/tasks/{job_id}")
async def update_cron_job(
    job_id: str,
    updates: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新定时任务"""
    from app.core.cron_manager import CronManager
    
    cron_manager = CronManager()
    
    # 验证任务所有权
    jobs = cron_manager.list_jobs(user_id=str(current_user.id))
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    success = cron_manager.update_job(job_id, updates)
    
    if success:
        return {"success": True, "message": "Job updated successfully"}
    else:
        raise HTTPException(status_code=400, detail="Failed to update job")

@router.delete("/cron/tasks/{job_id}")
async def delete_cron_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除定时任务"""
    from app.core.cron_manager import CronManager
    
    cron_manager = CronManager()
    
    # 验证任务所有权
    jobs = cron_manager.list_jobs(user_id=str(current_user.id))
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    success = cron_manager.remove_cron_job(job_id)
    
    if success:
        return {"success": True, "message": "Job deleted successfully"}
    else:
        raise HTTPException(status_code=400, detail="Failed to delete job")

# 实用工具端点

@router.post("/parse-cron")
async def parse_cron_expression(
    expression: str,
    current_user: User = Depends(get_current_user)
):
    """解析 cron 表达式为人类可读格式"""
    code_service = CodeService(None)
    ai_engine = AIEngine()
    ai_code_service = AICodeGenerationService(ai_engine, code_service)
    
    readable = ai_code_service.parse_cron_to_human_readable(expression)
    
    # 计算下次运行时间
    try:
        from croniter import croniter
        from datetime import datetime
        
        cron = croniter(expression, datetime.now())
        next_runs = []
        for _ in range(5):
            next_runs.append(cron.get_next(datetime).isoformat())
    except:
        next_runs = []
    
    return {
        "expression": expression,
        "readable": readable,
        "next_runs": next_runs
    }

@router.post("/validate-code")
async def validate_code(
    code: str,
    language: str,
    current_user: User = Depends(get_current_user)
):
    """验证代码语法"""
    from app.core.code_extractor import CodeExtractor
    
    extractor = CodeExtractor()
    
    if language == "python":
        is_valid, error = extractor.validate_python_code(code)
    elif language in ["bash", "shell"]:
        is_valid, error = extractor.validate_bash_code(code)
    elif language == "javascript":
        is_valid, error = extractor.validate_javascript_code(code)
    else:
        return {
            "valid": True,
            "message": f"Validation not implemented for {language}"
        }
    
    return {
        "valid": is_valid,
        "error": error,
        "language": language
    }