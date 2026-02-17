# from fastapi import APIRouter, Depends, HTTPException, status
# from fastapi.responses import StreamingResponse
# from typing import Optional, List
# import asyncio
# import json
# from sse_starlette.sse import EventSourceResponse

# from app.schemas.chat import (
#     ChatMessage, ChatResponse, ChatStreamResponse,
#     ResetChatRequest, ChatHistoryResponse
# )
# from app.core.auth import get_current_user
# from app.core.rate_limit import rate_limit
# from app.models.user import User
# from app.services.chat_service import ChatService
# from app.dependencies import get_chat_service

# router = APIRouter(prefix="/api/chat", tags=["chat"])

# @router.post("/message", response_model=ChatResponse)
# @rate_limit(calls=10, period=60)
# async def send_message(
#     message: ChatMessage,
#     current_user: User = Depends(get_current_user),
#     chat_service: ChatService = Depends(get_chat_service)
# ):
#     """
#     发送消息到AI并获取响应
#     """
#     try:
#         response = await chat_service.process_message(
#             user_id=current_user.id,
#             message=message.content,
#             model=message.model,
#             conversation_id=message.conversation_id,
#             system_prompt=message.system_prompt,
#             attachments=message.attachments
#         )
        
#         # 确保响应格式正确
#         return ChatResponse(**response)
        
#     except ValueError as e:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=str(e)
#         )
#     except Exception as e:
#         import traceback
#         traceback.print_exc()  # 打印详细错误
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"处理消息时出错: {str(e)}"
#         )

# @router.get("/stream")
# async def stream_chat(
#     message: str,
#     model: Optional[str] = None,
#     conversation_id: Optional[str] = None,
#     current_user: User = Depends(get_current_user),
#     chat_service: ChatService = Depends(get_chat_service)
# ):
#     """
#     SSE流式响应接口
#     """
#     async def generate():
#         try:
#             async for chunk in chat_service.stream_message(
#                 user_id=current_user.id,
#                 message=message,
#                 model=model,
#                 conversation_id=conversation_id
#             ):
#                 yield {
#                     "event": "message",
#                     "data": json.dumps({
#                         "content": chunk.content,
#                         "type": chunk.type,
#                         "metadata": chunk.metadata
#                     })
#                 }
#         except Exception as e:
#             yield {
#                 "event": "error",
#                 "data": json.dumps({"error": str(e)})
#             }
#         finally:
#             yield {
#                 "event": "done",
#                 "data": json.dumps({"status": "completed"})
#             }
    
#     return EventSourceResponse(generate())

# @router.post("/reset/{conversation_id}")
# async def reset_conversation(
#     conversation_id: str,
#     reset_request: Optional[ResetChatRequest] = None,
#     current_user: User = Depends(get_current_user),
#     chat_service: ChatService = Depends(get_chat_service)
# ):
#     """
#     重置指定会话
#     """
#     try:
#         await chat_service.reset_conversation(
#             user_id=current_user.id,
#             conversation_id=conversation_id,
#             system_prompt=reset_request.system_prompt if reset_request else None
#         )
#         return {"status": "success", "message": "会话已重置"}
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"重置会话时出错: {str(e)}"
#         )

# @router.get("/history/{conversation_id}", response_model=ChatHistoryResponse)
# async def get_chat_history(
#     conversation_id: str,
#     limit: int = 50,
#     offset: int = 0,
#     current_user: User = Depends(get_current_user),
#     chat_service: ChatService = Depends(get_chat_service)
# ):
#     """
#     获取会话历史
#     """
#     history = await chat_service.get_conversation_history(
#         user_id=current_user.id,
#         conversation_id=conversation_id,
#         limit=limit,
#         offset=offset
#     )
#     return ChatHistoryResponse(
#         conversation_id=conversation_id,
#         messages=history,
#         total_count=len(history)
#     )

# @router.delete("/message/{message_id}")
# async def delete_message(
#     message_id: str,
#     current_user: User = Depends(get_current_user),
#     chat_service: ChatService = Depends(get_chat_service)
# ):
#     """
#     删除指定消息
#     """
#     try:
#         await chat_service.delete_message(
#             user_id=current_user.id,
#             message_id=message_id
#         )
#         return {"status": "success", "message": "消息已删除"}
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"消息不存在或无权删除"
#         )

# @router.put("/message/{message_id}")
# async def edit_message(
#     message_id: str,
#     new_content: str,
#     current_user: User = Depends(get_current_user),
#     chat_service: ChatService = Depends(get_chat_service)
# ):
#     """
#     编辑消息（类似Telegram的消息编辑功能）
#     """
#     try:
#         updated_message = await chat_service.edit_message(
#             user_id=current_user.id,
#             message_id=message_id,
#             new_content=new_content
#         )
#         return updated_message
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"消息不存在或无权编辑"
#         )


from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from typing import Optional, List
import asyncio
import json
from sse_starlette.sse import EventSourceResponse

from app.schemas.chat import (
    ChatMessage, ChatResponse, ChatStreamResponse,
    ResetChatRequest, ChatHistoryResponse
)
from app.core.auth import get_current_user
from app.core.rate_limit import rate_limit
from app.models.user import User
from app.services.chat_service import ChatService
from app.dependencies import get_chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])

@router.post("/message", response_model=ChatResponse)
@rate_limit(calls=10, period=60)
async def send_message(
    message: ChatMessage,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    发送消息到AI并获取响应
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
        
        # 确保响应格式正确
        return ChatResponse(**response)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        import traceback
        traceback.print_exc()  # 打印详细错误
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"处理消息时出错: {str(e)}"
        )

@router.get("/stream")
async def stream_chat(
    message: str = Query(..., description="消息内容"),
    model: Optional[str] = Query(None, description="AI模型"),
    conversation_id: Optional[str] = Query(None, description="会话ID"),
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    SSE流式响应接口
    """
    async def generate():
        try:
            # 记录完整的响应内容
            full_response = ""
            message_id = None
            
            async for chunk in chat_service.stream_message(
                user_id=current_user.id,
                message=message,
                model=model,
                conversation_id=conversation_id
            ):
                # 记录消息ID
                if chunk.metadata and "message_id" in chunk.metadata:
                    message_id = chunk.metadata["message_id"]
                
                # 累积响应内容
                if chunk.type == "text" or chunk.type == "text_delta":
                    full_response += chunk.content
                
                # 发送SSE事件
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "content": chunk.content,
                        "type": chunk.type,
                        "metadata": chunk.metadata
                    }, ensure_ascii=False)
                }
                
                # 对于错误类型，立即结束
                if chunk.type == "error":
                    break
                
                # 完成信号
                if chunk.type == "complete":
                    # 发送最终的会话ID
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
                    
        except asyncio.CancelledError:
            # 客户端断开连接
            yield {
                "event": "error",
                "data": json.dumps({"error": "Client disconnected"}, ensure_ascii=False)
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}, ensure_ascii=False)
            }
        finally:
            # 确保发送完成事件
            yield {
                "event": "done",
                "data": json.dumps({"status": "completed"}, ensure_ascii=False)
            }
    
    # 设置适当的超时和保持连接
    return EventSourceResponse(
        generate(),
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用Nginx缓冲
        },
        ping=30  # 每30秒发送ping保持连接
    )

@router.post("/reset/{conversation_id}")
async def reset_conversation(
    conversation_id: str,
    reset_request: Optional[ResetChatRequest] = None,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    重置指定会话
    """
    try:
        await chat_service.reset_conversation(
            user_id=current_user.id,
            conversation_id=conversation_id,
            system_prompt=reset_request.system_prompt if reset_request else None
        )
        return {"status": "success", "message": "会话已重置"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"重置会话时出错: {str(e)}"
        )

@router.get("/history/{conversation_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    conversation_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    获取会话历史
    """
    history = await chat_service.get_conversation_history(
        user_id=current_user.id,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset
    )
    return ChatHistoryResponse(
        conversation_id=conversation_id,
        messages=history,
        total_count=len(history)
    )

@router.delete("/message/{message_id}")
async def delete_message(
    message_id: str,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    删除指定消息
    """
    try:
        await chat_service.delete_message(
            user_id=current_user.id,
            message_id=message_id
        )
        return {"status": "success", "message": "消息已删除"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"消息不存在或无权删除"
        )

@router.put("/message/{message_id}")
async def edit_message(
    message_id: str,
    new_content: str,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    编辑消息（类似Telegram的消息编辑功能）
    """
    try:
        updated_message = await chat_service.edit_message(
            user_id=current_user.id,
            message_id=message_id,
            new_content=new_content
        )
        return updated_message
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"消息不存在或无权编辑"
        )