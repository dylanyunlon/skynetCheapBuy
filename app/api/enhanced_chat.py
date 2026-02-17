# app/api/enhanced_chat.py
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import aioredis
from uuid import UUID

from app.core.auth import get_current_user
from app.models.user import User
from app.services.enhanced_chat_service import EnhancedChatService
from app.services.ai_code_service import AICodeGenerationService
from app.services.ai_service import AIService
from app.services.code_service import CodeService
from app.dependencies import get_db, get_redis_client
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/chat/v2", tags=["enhanced-chat"])

class EnhancedChatRequest(BaseModel):
    """增强的聊天请求"""
    content: str = Field(..., description="用户消息内容")
    conversation_id: Optional[str] = Field(None, description="会话ID")
    model: Optional[str] = Field("o3-gz", description="AI模型")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    
    # 代码相关选项
    extract_code: bool = Field(True, description="是否自动提取代码")
    auto_execute: bool = Field(False, description="是否自动执行提取的代码")
    setup_cron: bool = Field(False, description="是否自动设置定时任务")
    
    # 代码生成提示
    code_language: Optional[str] = Field(None, description="指定代码语言")
    code_requirements: Optional[str] = Field(None, description="代码特殊要求")

class CodeExecutionRequest(BaseModel):
    """代码执行请求"""
    code_id: str = Field(..., description="代码ID")
    parameters: Optional[Dict[str, str]] = Field(None, description="环境变量参数")
    timeout: int = Field(300, description="执行超时时间（秒）")

class CronSetupRequest(BaseModel):
    """定时任务设置请求"""
    code_id: str = Field(..., description="代码ID")
    cron_expression: str = Field(..., description="Cron表达式")
    job_name: Optional[str] = Field(None, description="任务名称")
    description: Optional[str] = Field(None, description="任务描述")


def get_enhanced_chat_service(
    db: Session = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis_client)
) -> EnhancedChatService:
    """获取增强聊天服务的依赖"""
    # 创建 AI 服务
    ai_service = AIService(db, redis)
    
    # 创建代码服务
    code_service = CodeService(db)
    
    # 创建 AI 代码生成服务
    code_generation_service = AICodeGenerationService(ai_service, code_service)
    
    # 创建增强聊天服务
    return EnhancedChatService(db, redis, code_generation_service)


@router.post("/message")
async def send_enhanced_message(
    request: EnhancedChatRequest,
    current_user: User = Depends(get_current_user),
    service: EnhancedChatService = Depends(get_enhanced_chat_service)
):
    """发送消息并自动处理代码"""
    try:
        # 如果指定了代码语言或要求，增强消息内容
        enhanced_content = request.content
        if request.code_language:
            enhanced_content = f"请用{request.code_language}编写代码：{request.content}"
        if request.code_requirements:
            enhanced_content += f"\n\n特殊要求：{request.code_requirements}"
        
        # 处理消息
        result = await service.process_message_with_code(
            user_id=str(current_user.id),
            content=enhanced_content,
            conversation_id=request.conversation_id,
            model=request.model,
            system_prompt=request.system_prompt,
            extract_code=request.extract_code,
            auto_execute=request.auto_execute,
            setup_cron=request.setup_cron
        )
        
        return {
            "success": True,
            "data": result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute-code")
async def execute_code(
    request: CodeExecutionRequest,
    current_user: User = Depends(get_current_user),
    service: EnhancedChatService = Depends(get_enhanced_chat_service)
):
    """执行已保存的代码"""
    try:
        result = await service.execute_saved_code(
            user_id=str(current_user.id),
            code_id=request.code_id,
            parameters=request.parameters
        )
        
        return {
            "success": True,
            "data": result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/setup-cron")
async def setup_cron_job(
    request: CronSetupRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """为代码设置定时任务"""
    from app.services.code_service import CodeService
    code_service = CodeService(db)
    
    try:
        result = await code_service.create_cron_job(
            code_id=request.code_id,
            user_id=str(current_user.id),
            cron_expression=request.cron_expression,
            job_name=request.job_name
        )
        
        return {
            "success": result["success"],
            "data": result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/code-templates")
async def get_code_templates(
    language: Optional[str] = Query(None, description="编程语言"),
    task_type: Optional[str] = Query(None, description="任务类型"),
    current_user: User = Depends(get_current_user)
):
    """获取代码生成模板"""
    templates = {
        "python": {
            "monitor": """创建一个Python脚本用于系统监控：
- 监控CPU、内存、磁盘使用率
- 阈值：CPU 80%、内存 90%、磁盘 85%
- 超过阈值时记录到日志
- 每5分钟运行一次
- 生成JSON格式的日志""",
            
            "backup": """创建一个Python备份脚本：
- 备份指定目录到压缩文件
- 支持增量备份
- 保留最近7个备份
- 验证备份完整性
- 发送备份报告""",
            
            "etl": """创建一个Python ETL脚本：
- 从CSV文件读取数据
- 清洗和转换数据
- 验证数据质量
- 加载到SQLite数据库
- 生成处理报告"""
        },
        "bash": {
            "monitor": """创建一个Bash监控脚本：
- 检查系统资源使用情况
- 监控关键服务状态
- 生成告警日志
- 支持邮件通知
- 适合cron定时执行""",
            
            "backup": """创建一个Bash备份脚本：
- 使用tar进行文件备份
- 支持远程备份（rsync）
- 自动清理旧备份
- 备份前后验证
- 详细的日志记录""",
            
            "deploy": """创建一个Bash部署脚本：
- Git拉取最新代码
- 安装依赖
- 运行测试
- 零停机部署
- 失败自动回滚"""
        }
    }
    
    # 根据参数过滤
    if language and language in templates:
        templates = {language: templates[language]}
    
    if task_type:
        filtered = {}
        for lang, tasks in templates.items():
            if task_type in tasks:
                filtered[lang] = {task_type: tasks[task_type]}
        templates = filtered if filtered else templates
    
    return {
        "success": True,
        "templates": templates,
        "languages": list(templates.keys()),
        "task_types": list(set(
            task for tasks in templates.values() 
            for task in tasks.keys()
        ))
    }


@router.get("/conversations/{conversation_id}/codes")
async def get_conversation_codes(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取会话中生成的所有代码"""
    from app.services.code_service import CodeService
    code_service = CodeService(db)
    
    try:
        codes = await code_service.get_conversation_codes(
            conversation_id=conversation_id,
            user_id=str(current_user.id)
        )
        
        return {
            "success": True,
            "data": {
                "conversation_id": conversation_id,
                "codes": codes,
                "total": len(codes)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-code-intent")
async def analyze_code_intent(
    request: Dict[str, str],
    current_user: User = Depends(get_current_user),
    service: EnhancedChatService = Depends(get_enhanced_chat_service)
):
    """分析用户消息中的代码生成意图"""
    content = request.get("content", "")
    
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")
    
    # 使用 AI 代码生成服务分析意图
    is_code_request, script_type = service.code_gen_service.detect_code_generation_intent(content)
    
    # 提取可能的 cron 表达式
    cron_expression = None
    human_readable_cron = None
    if is_code_request:
        cron_expression = service.code_gen_service.extract_cron_expression(content)
        if cron_expression:
            human_readable_cron = service.code_gen_service.parse_cron_to_human_readable(cron_expression)
    
    return {
        "success": True,
        "data": {
            "is_code_request": is_code_request,
            "script_type": script_type,
            "cron_expression": cron_expression,
            "human_readable_cron": human_readable_cron,
            "suggestions": {
                "enhance_prompt": is_code_request and not script_type,
                "add_cron": is_code_request and not cron_expression,
                "recommended_model": "gpt-4" if is_code_request else "gpt-3.5-turbo"
            }
        }
    }