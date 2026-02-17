# app/api/enhanced_code.py
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import List, Optional, Dict, Any
from uuid import UUID

from app.core.auth import get_current_user
from app.models.user import User
from app.schemas.code import (
    CodeGenerationRequest, CodeExecutionRequest,
    CronJobRequest, CodeResponse, CronJobResponse
)
from app.services.code_service import CodeService
from app.services.ai_code_service import AICodeGenerationService
from app.core.cron_manager import CronManager
from app.dependencies import get_code_service, get_db, get_redis

router = APIRouter(prefix="/api/v2/code", tags=["code-v2"])

@router.post("/generate")
async def generate_code(
    request: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    code_service: CodeService = Depends(get_code_service),
    db = Depends(get_db),
    redis = Depends(get_redis)
):
    """智能生成代码"""
    # 创建 AI 代码生成服务
    ai_code_service = AICodeGenerationService(
        ai_service=None,  # 这里需要注入实际的 AI 服务
        code_service=code_service
    )
    
    # 提取参数
    prompt = request.get("prompt", "")
    model = request.get("model", "gpt-4")
    auto_detect_type = request.get("auto_detect_type", True)
    script_type = request.get("script_type", "auto")
    
    # 检测代码生成意图
    if auto_detect_type:
        is_code_request, detected_type = ai_code_service.detect_code_generation_intent(prompt)
        if not is_code_request:
            return {
                "success": False,
                "message": "未检测到代码生成请求",
                "suggestion": "请描述您需要的脚本功能，例如：'创建一个监控系统资源的Python脚本'"
            }
        script_type = detected_type or script_type
    
    # 生成代码
    try:
        result = await ai_code_service.generate_code_with_ai(
            user_request=prompt,
            script_type=script_type,
            model=model,
            user_id=str(current_user.id),
            conversation_id=request.get("conversation_id", ""),
            **request.get("options", {})
        )
        
        return {
            "success": True,
            "result": result,
            "script_type": script_type,
            "model_used": model
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"代码生成失败: {str(e)}"
        )

@router.post("/execute/{code_id}/test")
async def test_execute_code(
    code_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    code_service: CodeService = Depends(get_code_service)
):
    """测试执行代码（异步）"""
    try:
        # 先验证代码存在
        codes = await code_service.get_user_codes(
            user_id=current_user.id,
            limit=1
        )
        
        # 在后台执行
        background_tasks.add_task(
            code_service.execute_code,
            code_id=code_id,
            user_id=current_user.id,
            env_vars={"TEST_MODE": "true"}
        )
        
        return {
            "success": True,
            "message": "代码已提交执行，请稍后查看结果",
            "execution_id": str(code_id),
            "status_url": f"/api/v2/code/execution/{code_id}/status"
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/execution/{code_id}/status")
async def get_execution_status(
    code_id: UUID,
    current_user: User = Depends(get_current_user),
    code_service: CodeService = Depends(get_code_service)
):
    """获取代码执行状态"""
    # 这里需要实现执行状态追踪
    # 简化示例，实际应该从数据库或缓存获取
    return {
        "code_id": str(code_id),
        "status": "completed",
        "result": {
            "success": True,
            "execution_time": 1.23,
            "output": "Script executed successfully"
        }
    }

@router.post("/cron/create")
async def create_cron_job_v2(
    request: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    code_service: CodeService = Depends(get_code_service)
):
    """创建定时任务（增强版）"""
    cron_manager = CronManager()
    
    code_id = request.get("code_id")
    cron_expression = request.get("cron_expression")
    job_name = request.get("job_name")
    env_vars = request.get("env_vars", {})
    description = request.get("description")
    
    # 获取代码信息
    code = await code_service.db.query(GeneratedCode).filter(
        GeneratedCode.id == code_id,
        GeneratedCode.user_id == current_user.id
    ).first()
    
    if not code:
        raise HTTPException(status_code=404, detail="代码未找到")
    
    # 创建定时任务
    result = cron_manager.create_cron_job(
        script_path=code.file_path,
        cron_expression=cron_expression,
        user_id=str(current_user.id),
        job_name=job_name,
        env_vars=env_vars,
        description=description
    )
    
    if result["success"]:
        # 保存到数据库
        await code_service.create_cron_job(
            code_id=code_id,
            user_id=current_user.id,
            cron_expression=cron_expression,
            job_name=result["job_info"]["job_name"]
        )
        
        return {
            "success": True,
            "job": result["job_info"],
            "next_run": result["next_run"]
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "创建定时任务失败")
        )

@router.get("/cron/jobs")
async def list_cron_jobs(
    active_only: bool = True,
    current_user: User = Depends(get_current_user)
):
    """列出用户的定时任务"""
    cron_manager = CronManager()
    
    jobs = cron_manager.list_jobs(
        user_id=str(current_user.id),
        active_only=active_only
    )
    
    return {
        "success": True,
        "jobs": jobs,
        "total": len(jobs)
    }

@router.get("/cron/jobs/{job_id}")
async def get_cron_job_details(
    job_id: str,
    current_user: User = Depends(get_current_user)
):
    """获取定时任务详情"""
    cron_manager = CronManager()
    
    jobs = cron_manager.list_jobs(user_id=str(current_user.id))
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    
    if not job:
        raise HTTPException(status_code=404, detail="任务未找到")
    
    # 获取日志
    logs = cron_manager.get_job_logs(job_id, lines=50)
    
    return {
        "success": True,
        "job": job,
        "logs": logs
    }

@router.delete("/cron/jobs/{job_id}")
async def delete_cron_job(
    job_id: str,
    current_user: User = Depends(get_current_user)
):
    """删除定时任务"""
    cron_manager = CronManager()
    
    # 验证任务属于当前用户
    jobs = cron_manager.list_jobs(user_id=str(current_user.id))
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    
    if not job:
        raise HTTPException(status_code=404, detail="任务未找到")
    
    success = cron_manager.remove_cron_job(job_id)
    
    if success:
        return {
            "success": True,
            "message": "定时任务已删除"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="删除任务失败"
        )

@router.put("/cron/jobs/{job_id}")
async def update_cron_job(
    job_id: str,
    updates: Dict[str, Any],
    current_user: User = Depends(get_current_user)
):
    """更新定时任务"""
    cron_manager = CronManager()
    
    # 验证任务属于当前用户
    jobs = cron_manager.list_jobs(user_id=str(current_user.id))
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    
    if not job:
        raise HTTPException(status_code=404, detail="任务未找到")
    
    # 只允许更新特定字段
    allowed_updates = {}
    for field in ["description", "cron_expression", "env_vars"]:
        if field in updates:
            allowed_updates[field] = updates[field]
    
    if not allowed_updates:
        raise HTTPException(
            status_code=400,
            detail="没有有效的更新字段"
        )
    
    success = cron_manager.update_job(job_id, allowed_updates)
    
    if success:
        return {
            "success": True,
            "message": "定时任务已更新",
            "updated_fields": list(allowed_updates.keys())
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="更新任务失败"
        )

@router.post("/cron/validate")
async def validate_cron_expression(
    request: Dict[str, str],
    current_user: User = Depends(get_current_user)
):
    """验证 cron 表达式"""
    from croniter import croniter
    
    expression = request.get("expression", "")
    
    try:
        # 验证表达式
        croniter(expression)
        
        # 计算接下来的5次执行时间
        cron = croniter(expression, datetime.now())
        next_runs = []
        for _ in range(5):
            next_runs.append(cron.get_next(datetime).isoformat())
        
        # 转换为人类可读格式
        ai_code_service = AICodeGenerationService(None, None)
        human_readable = ai_code_service.parse_cron_to_human_readable(expression)
        
        return {
            "success": True,
            "valid": True,
            "expression": expression,
            "human_readable": human_readable,
            "next_runs": next_runs
        }
        
    except Exception as e:
        return {
            "success": False,
            "valid": False,
            "error": str(e),
            "message": "无效的 cron 表达式"
        }

@router.get("/templates")
async def get_code_templates(
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """获取代码模板"""
    templates = [
        {
            "id": "monitor_system",
            "name": "系统监控脚本",
            "category": "monitoring",
            "language": "python",
            "description": "监控CPU、内存、磁盘使用率",
            "prompt": "创建一个Python脚本，监控系统CPU、内存和磁盘使用率，当使用率超过80%时发送警告",
            "suggested_cron": "*/5 * * * *"
        },
        {
            "id": "backup_database",
            "name": "数据库备份脚本",
            "category": "backup",
            "language": "bash",
            "description": "自动备份MySQL数据库",
            "prompt": "编写一个bash脚本，备份MySQL数据库，保留最近7天的备份，并压缩存储",
            "suggested_cron": "0 2 * * *"
        },
        {
            "id": "log_cleanup",
            "name": "日志清理脚本",
            "category": "maintenance",
            "language": "bash",
            "description": "清理超过30天的日志文件",
            "prompt": "创建一个bash脚本，查找并删除/var/log目录下超过30天的日志文件",
            "suggested_cron": "0 3 * * 0"
        },
        {
            "id": "api_health_check",
            "name": "API健康检查",
            "category": "monitoring",
            "language": "python",
            "description": "检查多个API端点的健康状态",
            "prompt": "写一个Python脚本，检查多个API端点的健康状态，记录响应时间，失败时发送通知",
            "suggested_cron": "*/10 * * * *"
        }
    ]
    
    if category:
        templates = [t for t in templates if t["category"] == category]
    
    return {
        "success": True,
        "templates": templates,
        "categories": ["monitoring", "backup", "maintenance"]
    }

@router.post("/templates/{template_id}/use")
async def use_code_template(
    template_id: str,
    request: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    code_service: CodeService = Depends(get_code_service),
    db = Depends(get_db),
    redis = Depends(get_redis)
):
    """使用代码模板生成代码"""
    # 获取模板
    templates = await get_code_templates(current_user=current_user)
    template = next((t for t in templates["templates"] if t["id"] == template_id), None)
    
    if not template:
        raise HTTPException(status_code=404, detail="模板未找到")
    
    # 自定义参数
    custom_params = request.get("parameters", {})
    custom_prompt = template["prompt"]
    
    # 替换模板中的参数
    for key, value in custom_params.items():
        custom_prompt = custom_prompt.replace(f"{{{key}}}", value)
    
    # 生成代码
    ai_code_service = AICodeGenerationService(
        ai_service=None,  # 需要注入实际的 AI 服务
        code_service=code_service
    )
    
    try:
        result = await ai_code_service.generate_code_with_ai(
            user_request=custom_prompt,
            script_type=template["language"],
            model=request.get("model", "gpt-4"),
            user_id=str(current_user.id),
            conversation_id=request.get("conversation_id", ""),
            **request.get("options", {})
        )
        
        # 添加模板信息
        result["template_used"] = template
        result["suggested_cron"] = template.get("suggested_cron")
        
        return {
            "success": True,
            "result": result
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"使用模板生成代码失败: {str(e)}"
        )