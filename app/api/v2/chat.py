# app/api/v2/chat.py - 完整修复版本 + Bash脚本生成支持
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from typing import Optional, List, Dict, Any, AsyncGenerator
import json
import time
from uuid import uuid4
from sse_starlette.sse import EventSourceResponse
import logging

from app.core.intent.engine import Intent, IntentType, IntentEngine
from app.schemas.v2.chat import (
    ChatMessageRequest, ChatMessageResponse, ProjectContext,
    StreamResponse, StreamChunkData, ConversationListResponse,
    BatchRequest, BatchResponse, ChatConfig, ChatStatistics,
    LegacyChatMessage, LegacyChatResponse
)
from app.dependencies import get_current_user, get_chat_service, get_project_service, get_intent_engine, get_chat_router
from app.models.user import User
from app.services.chat_service import ChatService
from app.core.chat.router import ChatRouter
from app.core.ai_engine import AIEngine
from app.core.workspace.workspace_manager import WorkspaceManager
from app.services.project_service import ProjectService
# 新增：Bash脚本生成服务
from app.services.bash_script_vibe_service import BashScriptVibeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["chat-v2-unified"])

# 依赖注入
async def get_intent_engine_dep() -> IntentEngine:
    """获取意图识别引擎实例"""
    return IntentEngine()

async def get_chat_router_dep(
    chat_service: ChatService = Depends(get_chat_service)
) -> ChatRouter:
    """获取聊天路由器实例"""
    ai_engine = AIEngine()
    return ChatRouter(chat_service, ai_engine)

# 新增：Bash脚本生成服务依赖
async def get_bash_script_vibe_service(
    current_user: User = Depends(get_current_user)
) -> BashScriptVibeService:
    """获取Bash脚本生成Vibe服务实例"""
    from app.db.session import get_db_session
    from app.core.workspace.workspace_manager import WorkspaceManager
    from app.core.ai_engine import AIEngine
    
    db_session = next(get_db_session())
    workspace_manager = WorkspaceManager()
    ai_engine = AIEngine()
    
    return BashScriptVibeService(
        db_session=db_session,
        workspace_manager=workspace_manager,
        ai_engine=ai_engine
    )

# 新增：Bash脚本生成的Vibe Coding端点
@router.post("/bash-vibe-create-project")
async def create_bash_vibe_project(
    request: ChatMessageRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    bash_vibe_service: BashScriptVibeService = Depends(get_bash_script_vibe_service)
):
    """
    创建bash脚本生成的vibe coding项目
    """
    start_time = time.time()
    
    try:
        logger.info(f"Starting bash script vibe coding for user {current_user.id}")
        
        # 调用bash脚本生成服务
        result = await bash_vibe_service.create_project_from_vibe_chat(
            user_id=str(current_user.id),
            user_input=request.message,
            chat_session_id=request.conversation_id or "default"
        )
        
        if result.get("success"):
            processing_time = int((time.time() - start_time) * 1000)
            
            # 构建成功响应
            response_content = f"""🔧 **Bash脚本自动化项目创建成功！**

📁 **项目名称**: {result['project']['name']}
🆔 **项目ID**: {result['project']['id']}
📄 **生成方法**: Bash脚本自动化
🌐 **预览链接**: {result.get('preview_url', '正在生成中...')}

✨ **特色功能**:
- ✅ 完整的bash脚本自动化
- ✅ Heredoc语法文件生成
- ✅ 智能端口冲突处理
- ✅ 跨平台部署兼容
- ✅ 全面的错误处理

🔧 **可用操作**:
- "查看生成的bash脚本"
- "修改项目内容"
- "添加新功能"
- "重新部署"
"""
            
            return {
                "success": True,
                "project": result["project"],
                "workspace_result": result["workspace_result"],
                "files_result": result["files_result"],
                "deployment_result": result["deployment_result"],
                "preview_url": result["preview_url"],
                "generation_method": "bash_script_automation",
                "system_type": "bash_vibe_coding",
                "bash_script_generated": True,
                "response_content": response_content,
                "processing_time_ms": processing_time,
                "meta_data": result["meta_data"]
            }
        else:
            raise Exception(result.get("error", "Unknown bash script generation error"))
            
    except Exception as e:
        logger.error(f"Bash vibe project creation failed: {e}", exc_info=True)
        processing_time = int((time.time() - start_time) * 1000)
        
        return {
            "success": False,
            "error": "Bash脚本项目生成失败",
            "details": str(e),
            "generation_method": "bash_script_automation",
            "processing_time_ms": processing_time
        }

# 新增：兼容旧版接口的bash脚本生成
@router.post("/bash-message")
async def bash_legacy_chat_message(
    message: LegacyChatMessage,
    current_user: User = Depends(get_current_user),
    bash_vibe_service: BashScriptVibeService = Depends(get_bash_script_vibe_service)
):
    """兼容旧版本的bash脚本生成接口"""
    start_time = time.time()
    
    try:
        # 调用bash脚本生成服务
        result = await bash_vibe_service.create_project_from_vibe_chat(
            user_id=str(current_user.id),
            user_input=message.content,
            chat_session_id=message.conversation_id or "default"
        )
        
        if result.get("success"):
            return {
                "success": True,
                "data": {
                    "conversation_id": message.conversation_id,
                    "content": f"🔧 Bash脚本项目创建成功！项目：{result['project']['name']}",
                    "intent_detected": "bash_script_generation",
                    "project_created": result["project"],
                    "preview_url": result.get("preview_url"),
                    "metadata": {
                        "generation_method": "bash_script_automation",
                        "bash_script_generated": True,
                        "meta_data": result["meta_data"]
                    }
                }
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Bash脚本生成失败"),
                "data": {
                    "conversation_id": message.conversation_id,
                    "content": f"❌ Bash脚本项目创建失败: {result.get('error', '未知错误')}",
                    "intent_detected": "bash_script_generation_failed"
                }
            }
            
    except Exception as e:
        logger.error(f"Bash legacy chat error: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "data": {
                "conversation_id": message.conversation_id,
                "content": f"❌ Bash脚本项目创建失败: {str(e)}",
                "intent_detected": "bash_script_generation_error"
            }
        }

# 主要的统一聊天接口
@router.post("/chat", response_model=ChatMessageResponse)
async def unified_chat(
    request: ChatMessageRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    intent_engine: IntentEngine = Depends(get_intent_engine_dep),
    chat_router: ChatRouter = Depends(get_chat_router_dep),
    project_service: ProjectService = Depends(get_project_service)
):
    """
    统一聊天接口 - 支持两阶段 Vibe Coding
    """
    start_time = time.time()
    
    try:
        # 1. 构建项目感知上下文
        context = await _build_enhanced_context(request, current_user, project_service)
        
        # 2. 增强的意图识别
        intent = await intent_engine.analyze_intent_with_project_context(
            message=request.message,
            context=context,
            user_history=await _get_user_history(current_user.id)
        )
        
        # 3. Vibe Coding 两阶段处理
        if intent.type == IntentType.VIBE_CODING_META:
            return await _handle_vibe_coding_meta_stage(
                request, intent, context, current_user, project_service
            )
        elif intent.type == IntentType.VIBE_CODING_GENERATE:
            return await _handle_vibe_coding_generate_stage(
                request, intent, context, current_user, project_service
            )
        
        # 4. 传统项目创建处理
        elif intent.metadata.get("vibe_features", {}).get("requires_meta_prompt"):
            return await _handle_vibe_coding_meta_stage(
                request, intent, context, current_user, project_service
            )
        
        # 5. 常规路由处理
        result = await chat_router.route_and_process(
            request=request,
            intent=intent,
            context=context,
            user=current_user
        )
        
        # 6. 处理后台任务
        if hasattr(result, 'background_tasks') and result.background_tasks:
            for task in result.background_tasks:
                background_tasks.add_task(task['func'], **task['args'])
        
        # 7. 更新响应时间
        processing_time = int((time.time() - start_time) * 1000)
        if hasattr(result, 'response'):
            result.response.processing_time_ms = processing_time
            return result.response
        else:
            return ChatMessageResponse(
                message_id=str(uuid4()),
                conversation_id=request.conversation_id,
                content=str(result),
                intent_detected=intent.type.value,
                processing_time_ms=processing_time
            )
        
    except Exception as e:
        logger.error(f"Unified chat error: {e}", exc_info=True)
        
        # 降级到基础聊天服务
        try:
            fallback_response = await _fallback_chat(request, current_user, chat_router)
            return fallback_response
        except Exception as fallback_error:
            logger.error(f"Fallback chat also failed: {fallback_error}")
            raise HTTPException(
                status_code=500,
                detail=f"聊天服务暂时不可用: {str(e)}"
            )

# Vibe Coding 处理函数
async def _handle_vibe_coding_meta_stage(
    request: ChatMessageRequest,
    intent: Intent,
    context: Dict[str, Any],
    user: User,
    project_service: ProjectService
) -> ChatMessageResponse:
    """处理 Vibe Coding Meta 阶段 - 第一次 AI 调用"""
    
    # 🔧 修复：添加 start_time 定义
    start_time = time.time()
    
    try:
        logger.info(f"Starting Vibe Coding Meta stage for user {user.id}")
        
        # 检查是否是修改需求
        if intent.entities.get("is_modification"):
            previous_meta_result = context.get("meta_result") or intent.entities.get("previous_meta_result")
            if not previous_meta_result:
                return ChatMessageResponse(
                    message_id=str(uuid4()),
                    conversation_id=request.conversation_id,
                    content="❌ 无法找到之前的需求信息，请重新开始",
                    intent_detected=intent.type.value,
                    suggestions=["重新创建项目", "详细描述需求"],
                    processing_time_ms=int((time.time() - start_time) * 1000)
                )
            
            meta_result = await project_service.modify_vibe_coding_requirement(
                user_id=str(user.id),
                modification_request=request.message,
                previous_meta_result=previous_meta_result,
                chat_session_id=request.conversation_id or "default"
            )
        else:
            # 执行 Meta 阶段
            meta_result = await project_service.handle_vibe_coding_meta_stage(
                user_id=str(user.id),
                user_input=request.message,
                chat_session_id=request.conversation_id or "default"
            )
        
        if not meta_result.get("success"):
            return ChatMessageResponse(
                message_id=str(uuid4()),
                conversation_id=request.conversation_id,
                content=f"❌ 需求分析失败: {meta_result.get('error', '未知错误')}",
                intent_detected=intent.type.value,
                suggestions=["重试", "简化需求", "联系支持"],
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
        
        # 构建 Meta 阶段完成响应
        response_content = meta_result["optimized_description"]
        
        return ChatMessageResponse(
            message_id=str(uuid4()),
            conversation_id=request.conversation_id or str(uuid4()),
            content=response_content,
            intent_detected=intent.type.value,
            metadata={
                "stage": "meta_complete",
                "vibe_data": {
                    "optimized_description": meta_result["optimized_description"],
                    "project_info": meta_result.get("project_info", {}),
                    "meta_result": meta_result,
                    "original_user_input": request.message
                }
            },
            suggestions=["确认生成项目", "修改需求", "重新优化"],
            processing_time_ms=int((time.time() - start_time) * 1000)
        )
        
    except Exception as e:
        logger.error(f"Vibe Coding Meta stage failed: {e}", exc_info=True)
        return ChatMessageResponse(
            message_id=str(uuid4()),
            conversation_id=request.conversation_id or str(uuid4()),
            content=f"❌ 需求优化失败: {str(e)}",
            intent_detected=intent.type.value,
            suggestions=["重试", "简化需求", "联系支持"],
            processing_time_ms=int((time.time() - start_time) * 1000)
        )

async def _handle_vibe_coding_generate_stage(
    request: ChatMessageRequest,
    intent: Intent,
    context: Dict[str, Any],
    user: User,
    project_service: ProjectService
) -> ChatMessageResponse:
    """处理 Vibe Coding Generate 阶段 - 第二次 AI 调用 + 项目创建"""
    
    # 🔧 修复：添加 start_time 定义
    start_time = time.time()
    
    try:
        logger.info(f"Starting Vibe Coding Generate stage for user {user.id}")
        
        # 从意图元数据中获取 meta_result
        meta_result = intent.metadata.get("meta_result")
        if not meta_result:
            # 尝试从请求元数据中获取
            meta_result = request.metadata.get("meta_result") if hasattr(request, 'metadata') and request.metadata else None
        
        # 尝试从上下文中获取
        if not meta_result:
            meta_result = context.get("meta_result")
        
        if not meta_result:
            logger.error("No meta_result found for generate stage")
            return ChatMessageResponse(
                message_id=str(uuid4()),
                conversation_id=request.conversation_id,
                content="❌ 缺少项目优化信息，请重新开始",
                intent_detected=intent.type.value,
                suggestions=["重新创建项目", "返回上一步"],
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
        
        # 执行 Generate 阶段
        generate_result = await project_service.handle_vibe_coding_generate_stage(
            user_id=str(user.id),
            meta_result=meta_result,
            chat_session_id=request.conversation_id or "default"
        )
        
        if not generate_result.get("success"):
            return ChatMessageResponse(
                message_id=str(uuid4()),
                conversation_id=request.conversation_id,
                content=f"❌ 项目生成失败: {generate_result.get('error', '未知错误')}",
                intent_detected=intent.type.value,
                suggestions=["重试", "修改需求", "联系支持"],
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
        
        # 构建项目创建成功响应
        response_content = _build_project_creation_response(generate_result)
        
        # 构建项目创建信息
        project_info = {
            "success": True,
            "project_id": str(generate_result["project"].id),
            "project_name": generate_result["project"].name,
            "project_type": generate_result["project"].project_type,
            "files_created": generate_result.get("workspace_result", {}).get("file_count", 0),
            "workspace_path": generate_result["project"].workspace_path
        }
        
        # 添加预览URL
        if generate_result.get("preview_url"):
            project_info["preview_url"] = generate_result["preview_url"]
        
        # 添加执行状态
        execution_result = generate_result.get("execution_result", {})
        project_info["execution_success"] = execution_result.get("success", False)
        if not execution_result.get("success") and execution_result.get("error"):
            project_info["execution_error"] = execution_result["error"]
        
        return ChatMessageResponse(
            message_id=str(uuid4()),
            conversation_id=request.conversation_id or str(uuid4()),
            content=response_content,
            intent_detected=intent.type.value,
            project_created=project_info,
            metadata={
                "stage": "generate_complete",
                "project_created": project_info,
                "suggestions": ["修改项目", "添加功能", "部署项目", "查看代码"]
            },
            suggestions=["修改项目", "添加功能", "部署项目", "查看代码"],
            processing_time_ms=int((time.time() - start_time) * 1000)
        )
        
    except Exception as e:
        logger.error(f"Vibe Coding Generate stage failed: {e}", exc_info=True)
        return ChatMessageResponse(
            message_id=str(uuid4()),
            conversation_id=request.conversation_id or str(uuid4()),
            content=f"❌ 项目创建失败: {str(e)}",
            intent_detected=intent.type.value,
            project_created={
                "success": False,
                "error": str(e)
            },
            suggestions=["重试", "简化需求", "联系支持"],
            processing_time_ms=int((time.time() - start_time) * 1000)
        )

# 兼容性接口 - 支持前端直接调用
@router.post("/message")
async def legacy_chat_message(
    message: LegacyChatMessage,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
    intent_engine: IntentEngine = Depends(get_intent_engine_dep)
):
    """兼容旧版本的聊天接口 - 增强支持 Vibe Coding"""
    start_time = time.time()
    
    try:
        # 构建请求对象
        request = ChatMessageRequest(
            message=message.content,
            conversation_id=message.conversation_id,
            model=message.model,
            system_prompt=message.system_prompt,
            attachments=message.attachments
        )
        
        # 从请求中获取元数据（如果有的话）
        request_metadata = getattr(message, 'metadata', {})
        
        # 构建上下文
        context = await _build_enhanced_context(request, current_user, project_service)
        
        # 添加请求元数据到上下文
        if request_metadata:
            context.update(request_metadata)
        
        # 意图识别
        intent = await intent_engine.analyze_intent_with_project_context(
            message=message.content,
            context=context
        )
        
        # Vibe Coding Meta 阶段处理
        if (intent.type == IntentType.VIBE_CODING_META or 
            intent.metadata.get("vibe_features", {}).get("requires_meta_prompt") or
            request_metadata.get("stage") == "meta_modify"):
            
            chat_response = await _handle_vibe_coding_meta_stage(
                request, intent, context, current_user, project_service
            )
            
            # 🔧 修复：确保 vibe_data 格式正确
            vibe_data = chat_response.metadata.get("vibe_data") if chat_response.metadata else None
            if not vibe_data:
                vibe_data = {
                    "optimized_description": chat_response.content,
                    "project_info": {
                        "type": "web",
                        "technologies": ["html", "css", "javascript"],
                        "target_person": "sky-net",
                        "port": 17430
                    },
                    "meta_result": {
                        "success": True,
                        "stage": "meta_complete",
                        "optimized_description": chat_response.content,
                        "project_info": {
                            "type": "web",
                            "technologies": ["html", "css", "javascript"],
                            "target_person": "sky-net",
                            "port": 17430
                        },
                        "id": chat_response.message_id,
                        "content": chat_response.content,
                        "conversation_id": chat_response.conversation_id,
                        "created_at": str(int(time.time()))
                    },
                    "original_user_input": message.content
                }
            
            # 🔧 修复：返回前端期望的包装格式
            return {
                "success": True,
                "data": {
                    "conversation_id": chat_response.conversation_id,
                    "content": chat_response.content,
                    "intent_detected": chat_response.intent_detected,
                    "metadata": {
                        "stage": "meta_complete",
                        "vibe_data": vibe_data,
                        "suggestions": chat_response.suggestions or ["确认生成项目", "修改需求", "重新优化"]
                    }
                }
            }
        
        # Vibe Coding Generate 阶段处理
        elif (intent.type == IntentType.VIBE_CODING_GENERATE or 
              request_metadata.get("stage") == "generate"):
            
            chat_response = await _handle_vibe_coding_generate_stage(
                request, intent, context, current_user, project_service
            )
            
            # 🔧 修复：返回前端期望的包装格式
            return {
                "success": True,
                "data": {
                    "conversation_id": chat_response.conversation_id,
                    "content": chat_response.content,
                    "intent_detected": chat_response.intent_detected,
                    "project_created": chat_response.project_created,
                    "metadata": {
                        "stage": "generate_complete",
                        "suggestions": chat_response.suggestions or ["修改项目", "添加功能", "部署项目", "查看代码"]
                    }
                }
            }
        
        # 常规聊天处理
        else:
            chat_service = await get_chat_service()
            response = await chat_service.process_message(
                user_id=current_user.id,
                message=message.content,
                model=message.model,
                conversation_id=message.conversation_id,
                system_prompt=message.system_prompt,
                attachments=message.attachments
            )
            
            # 🔧 修复：常规聊天也返回包装格式
            return {
                "success": True,
                "data": {
                    "conversation_id": response.get("conversation_id"),
                    "content": response.get("content"),
                    "intent_detected": "general_chat",
                    "metadata": response.get("metadata", {})
                }
            }
        
    except Exception as e:
        logger.error(f"Legacy chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# 核心辅助函数
async def _build_enhanced_context(
    request: ChatMessageRequest, 
    user: User,
    project_service: ProjectService
) -> Dict[str, Any]:
    """构建增强的项目感知上下文"""
    context = {
        "user_id": str(user.id),
        "conversation_id": request.conversation_id,
        "project_id": request.project_id,
        "user_preferences": user.preferences or {},
        "api_keys": user.api_keys or {},
        "timestamp": time.time()
    }
    
    # 添加阶段信息（从请求元数据中获取）
    if hasattr(request, 'metadata') and request.metadata:
        context["stage"] = request.metadata.get("stage")
        context["optimized_prompt"] = request.metadata.get("optimized_prompt")
        context["original_user_input"] = request.metadata.get("original_user_input")
        context["meta_result"] = request.metadata.get("meta_result")
    
    # 加载项目上下文
    if request.project_id:
        try:
            project_context = await project_service.get_project_context(request.project_id)
            context.update({
                "current_project_id": request.project_id,
                "project_info": project_context.get("project_info"),
                "project_files": project_context.get("project_files", []),
                "project_type": project_context.get("project_type", "python"),
                "recent_executions": project_context.get("recent_executions", []),
                "tech_stack": project_context.get("tech_stack", [])
            })
            logger.info(f"Loaded project context for project {request.project_id}")
        except Exception as e:
            logger.warning(f"Failed to load project context: {e}")
    
    return context

def _build_project_creation_response(result: Dict[str, Any]) -> str:
    """构建项目创建成功响应"""
    project = result["project"]
    
    response = f"""✅ **项目创建成功！**

📁 **项目名称**: {project.name}
🆔 **项目ID**: {project.id}
📄 **文件数量**: {result.get("workspace_result", {}).get("file_count", 0)}
🌐 **预览链接**: [点击查看]({result.get("preview_url", "正在生成中...")})

💡 **提示**: 你可以继续与我对话来修改和优化这个项目。

🔧 **可用操作**:
- "修改首页样式"
- "添加新功能"  
- "优化性能"
- "部署到生产环境"
"""
    
    if result.get("execution_result", {}).get("success"):
        response += f"\n✅ **执行状态**: 项目已成功运行"
    else:
        response += f"\n⚠️ **执行状态**: 需要调试，正在自动修复..."
    
    return response

async def _get_user_history(user_id: str) -> List[Dict[str, Any]]:
    """获取用户历史（简化实现）"""
    return []

async def _fallback_chat(
    request: ChatMessageRequest,
    user: User,
    chat_router: ChatRouter
) -> ChatMessageResponse:
    """降级聊天处理"""
    
    response = await chat_router.chat_service.process_message(
        user_id=user.id,
        message=request.message,
        model=request.model,
        conversation_id=request.conversation_id,
        system_prompt=request.system_prompt,
        attachments=request.attachments
    )
    
    return ChatMessageResponse(
        message_id=response.get("id", str(uuid4())),
        conversation_id=response.get("conversation_id", request.conversation_id),
        content=response.get("content", ""),
        intent_detected="general_chat",
        suggestions=["继续对话", "创建项目", "生成代码"],
        processing_time_ms=100
    )

# 其他端点保持不变...
@router.get("/chat/stream")
async def unified_chat_stream(
    message: str = Query(..., description="消息内容"),
    project_id: Optional[str] = Query(None, description="项目ID"),
    conversation_id: Optional[str] = Query(None, description="会话ID"),
    model: Optional[str] = Query(None, description="AI模型"),
    intent_hint: Optional[str] = Query(None, description="意图提示"),
    current_user: User = Depends(get_current_user),
    chat_router: ChatRouter = Depends(get_chat_router_dep)
):
    """统一流式聊天接口"""
    
    async def generate():
        try:
            request = ChatMessageRequest(
                message=message,
                project_id=project_id,
                conversation_id=conversation_id,
                model=model,
                intent_hint=intent_hint
            )
            
            async for chunk in chat_router.stream_process(request, current_user):
                yield {
                    "event": chunk.event_type,
                    "data": json.dumps(chunk.data, ensure_ascii=False)
                }
                
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({
                    "error": str(e),
                    "code": "STREAM_ERROR"
                }, ensure_ascii=False)
            }
        finally:
            yield {
                "event": "done",
                "data": json.dumps({"status": "completed"}, ensure_ascii=False)
            }
    
    return EventSourceResponse(
        generate(),
        sep="\n",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """获取用户会话列表"""
    try:
        offset = (page - 1) * page_size
        conversations = await chat_service.list_conversations(
            user_id=current_user.id,
            limit=page_size,
            offset=offset
        )
        
        from app.schemas.v2.chat import ConversationInfo
        conversation_list = []
        
        for conv in conversations:
            conversation_list.append(ConversationInfo(
                id=conv.get("id", ""),
                title=conv.get("title"),
                project_id=None,
                conversation_type="general",
                message_count=conv.get("message_count", 0),
                last_message=conv.get("last_message"),
                created_at=conv.get("created_at"),
                updated_at=conv.get("updated_at"),
                is_active=conv.get("is_active", True)
            ))
        
        return ConversationListResponse(
            conversations=conversation_list,
            total=len(conversation_list),
            page=page,
            page_size=page_size,
            has_more=len(conversation_list) >= page_size
        )
        
    except Exception as e:
        logger.error(f"List conversations error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/config", response_model=ChatConfig)
async def get_chat_config(current_user: User = Depends(get_current_user)):
    """获取用户聊天配置"""
    return ChatConfig(
        model=current_user.preferred_model,
        temperature=0.7,
        system_prompt=current_user.system_prompt,
        enable_project_context=current_user.preferences.get("enable_project_context", True),
        enable_code_generation=current_user.preferences.get("auto_extract_code", True),
        enable_file_operations=True,
        auto_save_code=current_user.preferences.get("auto_save_code", True),
        auto_execute_safe_code=current_user.preferences.get("auto_execute_safe_code", False)
    )