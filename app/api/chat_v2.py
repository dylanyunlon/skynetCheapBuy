# app/api/chat_v2.py
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from typing import Optional, List
import json
from sse_starlette.sse import EventSourceResponse

from app.schemas.chat import (
    ChatMessage, ChatResponse, ChatStreamResponse,
    ResetChatRequest, ChatHistoryResponse
)
from app.dependencies import get_current_user, get_chat_service
from app.models.user import User
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/chat/v2", tags=["chat-v2"])

# 添加 OPTIONS 处理器
@router.options("/message")
async def options_message():
    """处理 OPTIONS 请求"""
    return Response(status_code=200)

@router.post("/message", response_model=ChatResponse)
async def send_message_v2(
    message: ChatMessage,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    发送消息到AI并获取响应 (V2版本)
    """
    try:
        response = await chat_service.process_message(
            user_id=current_user.id,
            message=message.content,
            model=message.model,
            conversation_id=message.conversation_id,
            system_prompt=message.system_prompt,
            attachments=message.attachments
        )
        
        return ChatResponse(**response)
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"处理消息时出错: {str(e)}"
        )

@router.get("/stream")
async def stream_chat_v2(
    message: str = Query(..., description="消息内容"),
    model: Optional[str] = Query(None, description="AI模型"),
    conversation_id: Optional[str] = Query(None, description="会话ID"),
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    SSE流式响应接口 (V2版本)
    """
    async def generate():
        try:
            full_response = ""
            message_id = None
            
            async for chunk in chat_service.stream_message(
                user_id=current_user.id,
                message=message,
                model=model,
                conversation_id=conversation_id
            ):
                if chunk.metadata and "message_id" in chunk.metadata:
                    message_id = chunk.metadata["message_id"]
                
                if chunk.type in ["text", "text_delta"]:
                    full_response += chunk.content
                
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "content": chunk.content,
                        "type": chunk.type,
                        "metadata": chunk.metadata
                    }, ensure_ascii=False)
                }
                
                if chunk.type == "error":
                    break
                
                if chunk.type == "complete":
                    if conversation_id:
                        yield {
                            "event": "done",
                            "data": json.dumps({
                                "status": "completed",
                                "conversation_id": conversation_id,
                                "message_id": message_id,
                                "total_length": len(full_response)
                            }, ensure_ascii=False)
                        }
                    break
                    
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}, ensure_ascii=False)
            }
        finally:
            yield {
                "event": "done",
                "data": json.dumps({"status": "completed"}, ensure_ascii=False)
            }
    
    return EventSourceResponse(
        generate(),
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        },
        ping=30
    )

@router.get("/conversations")
async def list_conversations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    列出用户的所有会话
    """
    try:
        conversations = await chat_service.list_conversations(
            user_id=current_user.id,
            limit=limit,
            offset=offset
        )
        return {
            "conversations": conversations,
            "total": len(conversations),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取会话列表失败: {str(e)}"
        )

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    删除整个会话
    """
    try:
        await chat_service.delete_conversation(
            user_id=current_user.id,
            conversation_id=conversation_id
        )
        return {"status": "success", "message": "会话已删除"}
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"会话不存在或无权删除"
        )

# 添加执行代码的路由
@router.post("/execute-code")
async def execute_code(
    request: dict,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    执行代码
    """
    try:
        code_id = request.get("code_id")
        parameters = request.get("parameters", {})
        timeout = request.get("timeout", 30000)
        
        if not code_id:
            raise HTTPException(status_code=400, detail="code_id is required")
        
        # 这里调用代码执行服务
        # result = await code_service.execute_code(...)
        
        return {
            "success": True,
            "data": {
                "result": {
                    "success": True,
                    "output": "Code execution result",
                    "execution_time": 0.1
                },
                "report": "Execution completed successfully"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 添加设置定时任务的路由
@router.post("/setup-cron")
async def setup_cron(
    request: dict,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    设置定时任务
    """
    try:
        code_id = request.get("code_id")
        cron_expression = request.get("cron_expression")
        job_name = request.get("job_name")
        
        if not code_id or not cron_expression:
            raise HTTPException(
                status_code=400, 
                detail="code_id and cron_expression are required"
            )
        
        # 这里调用定时任务服务
        # result = await cron_service.setup_cron(...)
        
        return {
            "success": True,
            "data": {
                "job_name": job_name or f"job_{code_id}",
                "cron_expression": cron_expression,
                "next_run": "2024-01-01 00:00:00"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 添加获取代码模板的路由
@router.get("/code-templates")
async def get_code_templates(
    language: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user)
):
    """
    获取代码模板
    """
    try:
        # 这里返回示例模板
        templates = {
            "python": {
                "hello_world": "print('Hello, World!')",
                "http_request": "import requests\n\nresponse = requests.get('https://api.example.com')\nprint(response.json())"
            },
            "javascript": {
                "hello_world": "console.log('Hello, World!');",
                "http_request": "fetch('https://api.example.com')\n  .then(response => response.json())\n  .then(data => console.log(data));"
            }
        }
        
        return {
            "success": True,
            "templates": templates
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))