from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from uuid import UUID

from app.core.auth import get_current_user
from app.models.user import User
from app.schemas.code import (
    CodeGenerationRequest, CodeExecutionRequest,
    CronJobRequest, CodeResponse, CronJobResponse
)
from app.services.code_service import CodeService
from app.dependencies import get_code_service

router = APIRouter(prefix="/api/code", tags=["code"])

@router.post("/extract")
async def extract_code_from_response(
    request: CodeGenerationRequest,
    current_user: User = Depends(get_current_user),
    code_service: CodeService = Depends(get_code_service)
):
    """从AI响应中提取代码"""
    result = await code_service.process_ai_response_for_code(
        ai_response=request.ai_response,
        user_id=current_user.id,
        conversation_id=request.conversation_id,
        auto_save=request.auto_save
    )
    return result

@router.post("/execute/{code_id}")
async def execute_code(
    code_id: UUID,
    request: CodeExecutionRequest,
    current_user: User = Depends(get_current_user),
    code_service: CodeService = Depends(get_code_service)
):
    """执行保存的代码"""
    try:
        result = await code_service.execute_code(
            code_id=code_id,
            user_id=current_user.id,
            env_vars=request.env_vars
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/cron/{code_id}")
async def create_cron_job(
    code_id: UUID,
    request: CronJobRequest,
    current_user: User = Depends(get_current_user),
    code_service: CodeService = Depends(get_code_service)
):
    """为代码创建定时任务"""
    try:
        result = await code_service.create_cron_job(
            code_id=code_id,
            user_id=current_user.id,
            cron_expression=request.cron_expression,
            job_name=request.job_name
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/list", response_model=List[CodeResponse])
async def list_user_codes(
    language: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    code_service: CodeService = Depends(get_code_service)
):
    """获取用户的代码列表"""
    codes = await code_service.get_user_codes(
        user_id=current_user.id,
        language=language,
        limit=limit,
        offset=offset
    )
    return codes