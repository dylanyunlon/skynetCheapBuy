from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from app.schemas.chat import ConversationInfo, ConversationList
from app.models.chat import ChatSession, ChatMessage
from app.models.user import User
from app.core.auth import get_current_user
from app.dependencies import get_db, get_chat_service
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

@router.get("", response_model=List[ConversationInfo])
async def get_conversations(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = None,
    model: Optional[str] = None,
    is_pinned: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取用户的会话列表
    """
    query = db.query(ChatSession).filter(
        and_(
            ChatSession.user_id == current_user.id,
            ChatSession.is_active == True
        )
    )
    
    # 搜索过滤
    if search:
        query = query.filter(
            or_(
                ChatSession.title.ilike(f"%{search}%"),
                ChatSession.description.ilike(f"%{search}%")
            )
        )
    
    # 模型过滤
    if model:
        query = query.filter(
            ChatSession.config["model"].astext == model
        )
    
    # 置顶过滤
    if is_pinned is not None:
        query = query.filter(ChatSession.is_pinned == is_pinned)
    
    # 排序：置顶的在前，然后按更新时间降序
    query = query.order_by(
        ChatSession.is_pinned.desc(),
        ChatSession.updated_at.desc()
    )
    
    # 分页
    total = query.count()
    conversations = query.offset(offset).limit(limit).all()
    
    # 转换为响应格式
    result = []
    for conv in conversations:
        # 获取模型信息
        model_name = conv.config.get("model", "unknown") if conv.config else "unknown"
        
        result.append(ConversationInfo(
            id=str(conv.id),
            title=conv.title,
            model=model_name,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=conv.message_count or 0,
            is_active=conv.is_active
        ))
    
    return result

@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取会话详情
    """
    conversation = db.query(ChatSession).filter(
        and_(
            ChatSession.id == conversation_id,
            ChatSession.user_id == current_user.id
        )
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )
    
    # 获取最近的几条消息
    recent_messages = db.query(ChatMessage).filter(
        and_(
            ChatMessage.session_id == conversation.id,
            ChatMessage.is_deleted == False
        )
    ).order_by(ChatMessage.created_at.desc()).limit(5).all()
    
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "description": conversation.description,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "is_pinned": conversation.is_pinned,
        "config": conversation.config,
        "tags": conversation.tags,
        "message_count": conversation.message_count,
        "total_tokens": conversation.total_tokens,
        "recent_messages": [
            {
                "id": str(msg.id),
                "role": msg.role,
                "content": msg.content[:100] + "..." if len(msg.content) > 100 else msg.content,
                "created_at": msg.created_at
            }
            for msg in reversed(recent_messages)
        ]
    }

@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    获取会话的消息历史
    """
    try:
        messages = await chat_service.get_conversation_history(
            user_id=current_user.id,
            conversation_id=str(conversation_id),
            limit=limit,
            offset=offset
        )
        
        return messages
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取消息历史失败: {str(e)}"
        )

@router.post("/{conversation_id}/title")
async def update_conversation_title(
    conversation_id: UUID,
    title: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    更新会话标题
    """
    conversation = db.query(ChatSession).filter(
        and_(
            ChatSession.id == conversation_id,
            ChatSession.user_id == current_user.id
        )
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )
    
    conversation.title = title
    conversation.updated_at = datetime.utcnow()
    db.commit()
    
    return {"status": "success", "title": title}

@router.post("/{conversation_id}/pin")
async def pin_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    置顶/取消置顶会话
    """
    conversation = db.query(ChatSession).filter(
        and_(
            ChatSession.id == conversation_id,
            ChatSession.user_id == current_user.id
        )
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )
    
    conversation.is_pinned = not conversation.is_pinned
    conversation.updated_at = datetime.utcnow()
    db.commit()
    
    return {
        "status": "success",
        "is_pinned": conversation.is_pinned
    }

@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除会话
    """
    conversation = db.query(ChatSession).filter(
        and_(
            ChatSession.id == conversation_id,
            ChatSession.user_id == current_user.id
        )
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )
    
    # 软删除
    conversation.is_active = False
    conversation.updated_at = datetime.utcnow()
    db.commit()
    
    return {"status": "success", "message": "会话已删除"}

@router.post("/{conversation_id}/clear")
async def clear_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    清空会话消息但保留会话
    """
    conversation = db.query(ChatSession).filter(
        and_(
            ChatSession.id == conversation_id,
            ChatSession.user_id == current_user.id
        )
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )
    
    # 软删除所有消息
    db.query(ChatMessage).filter(
        ChatMessage.session_id == conversation.id
    ).update({
        "is_deleted": True,
        "deleted_at": datetime.utcnow()
    })
    
    # 重置会话统计
    conversation.message_count = 0
    conversation.total_tokens = 0
    conversation.updated_at = datetime.utcnow()
    
    db.commit()
    
    return {"status": "success", "message": "会话已清空"}

@router.get("/stats/summary")
async def get_conversations_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取会话统计摘要
    """
    # 总会话数
    total_conversations = db.query(func.count(ChatSession.id)).filter(
        and_(
            ChatSession.user_id == current_user.id,
            ChatSession.is_active == True
        )
    ).scalar()
    
    # 总消息数
    total_messages = db.query(func.count(ChatMessage.id)).join(
        ChatSession
    ).filter(
        and_(
            ChatSession.user_id == current_user.id,
            ChatMessage.is_deleted == False
        )
    ).scalar()
    
    # 模型使用统计
    model_stats = db.query(
        ChatSession.config["model"].astext.label("model"),
        func.count(ChatSession.id).label("count")
    ).filter(
        and_(
            ChatSession.user_id == current_user.id,
            ChatSession.is_active == True
        )
    ).group_by(
        ChatSession.config["model"].astext
    ).all()
    
    return {
        "total_conversations": total_conversations or 0,
        "total_messages": total_messages or 0,
        "model_usage": {
            stat.model: stat.count 
            for stat in model_stats if stat.model
        }
    }

@router.post("/{conversation_id}/export")
async def export_conversation(
    conversation_id: UUID,
    format: str = Query("json", regex="^(json|markdown|txt)$"),
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    导出会话内容
    """
    try:
        # 获取完整历史
        messages = await chat_service.get_conversation_history(
            user_id=current_user.id,
            conversation_id=str(conversation_id),
            limit=10000  # 获取所有消息
        )
        
        if format == "json":
            return {
                "conversation_id": str(conversation_id),
                "exported_at": datetime.utcnow().isoformat(),
                "messages": messages
            }
        
        elif format == "markdown":
            content = f"# 会话导出\n\n"
            content += f"**会话ID**: {conversation_id}\n"
            content += f"**导出时间**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            content += "---\n\n"
            
            for msg in messages:
                role = "👤 用户" if msg["role"] == "user" else "🤖 AI"
                content += f"### {role}\n"
                content += f"*{msg['created_at']}*\n\n"
                content += f"{msg['content']}\n\n"
                content += "---\n\n"
            
            return {"content": content, "format": "markdown"}
        
        elif format == "txt":
            content = ""
            for msg in messages:
                role = "User" if msg["role"] == "user" else "AI"
                content += f"[{msg['created_at']}] {role}: {msg['content']}\n\n"
            
            return {"content": content, "format": "txt"}
            
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出失败: {str(e)}"
        )