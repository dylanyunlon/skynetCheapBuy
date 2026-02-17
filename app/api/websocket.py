from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from typing import Dict, Set
import json
import asyncio
from datetime import datetime

from app.core.auth import AuthService
from app.dependencies import get_websocket_chat_service
from app.services.chat_service import WebSocketChatService

router = APIRouter(prefix="/api/ws", tags=["websocket"])

class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        # 存储活动连接 {user_id: {connection_id: websocket}}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        # 存储用户的会话订阅 {user_id: {conversation_id: set(connection_ids)}}
        self.conversation_subscriptions: Dict[str, Dict[str, Set[str]]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str, connection_id: str):
        """接受WebSocket连接"""
        await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = {}
        
        self.active_connections[user_id][connection_id] = websocket
        
        # 发送连接成功消息
        await self.send_personal_message(
            websocket,
            {
                "type": "connection",
                "data": {
                    "status": "connected",
                    "connection_id": connection_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
        )
    
    def disconnect(self, user_id: str, connection_id: str):
        """断开WebSocket连接"""
        if user_id in self.active_connections:
            self.active_connections[user_id].pop(connection_id, None)
            
            # 如果用户没有其他连接，清理用户数据
            if not self.active_connections[user_id]:
                self.active_connections.pop(user_id)
                self.conversation_subscriptions.pop(user_id, None)
    
    async def subscribe_to_conversation(
        self,
        user_id: str,
        connection_id: str,
        conversation_id: str
    ):
        """订阅会话更新"""
        if user_id not in self.conversation_subscriptions:
            self.conversation_subscriptions[user_id] = {}
        
        if conversation_id not in self.conversation_subscriptions[user_id]:
            self.conversation_subscriptions[user_id][conversation_id] = set()
        
        self.conversation_subscriptions[user_id][conversation_id].add(connection_id)
    
    async def unsubscribe_from_conversation(
        self,
        user_id: str,
        connection_id: str,
        conversation_id: str
    ):
        """取消订阅会话"""
        if (user_id in self.conversation_subscriptions and
            conversation_id in self.conversation_subscriptions[user_id]):
            self.conversation_subscriptions[user_id][conversation_id].discard(connection_id)
    
    async def send_personal_message(self, websocket: WebSocket, message: dict):
        """发送个人消息"""
        await websocket.send_json(message)
    
    async def broadcast_to_user(self, user_id: str, message: dict):
        """向用户的所有连接广播消息"""
        if user_id in self.active_connections:
            for websocket in self.active_connections[user_id].values():
                await websocket.send_json(message)
    
    async def broadcast_to_conversation(
        self,
        user_id: str,
        conversation_id: str,
        message: dict,
        exclude_connection: str = None
    ):
        """向订阅了特定会话的连接广播消息"""
        if (user_id in self.conversation_subscriptions and
            conversation_id in self.conversation_subscriptions[user_id]):
            
            for connection_id in self.conversation_subscriptions[user_id][conversation_id]:
                if connection_id != exclude_connection:
                    websocket = self.active_connections[user_id].get(connection_id)
                    if websocket:
                        await websocket.send_json(message)

# 创建全局连接管理器
manager = ConnectionManager()

@router.websocket("/chat")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    chat_service: WebSocketChatService = Depends(get_websocket_chat_service)
):
    """
    WebSocket聊天端点
    
    客户端连接示例:
    ```javascript
    const ws = new WebSocket('ws://localhost:8000/api/ws/chat?token=YOUR_JWT_TOKEN');
    
    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        console.log('Received:', message);
    };
    
    // 发送消息
    ws.send(JSON.stringify({
        action: 'send_message',
        conversation_id: 'conv_id',
        content: 'Hello AI!',
        model: 'gpt-3.5-turbo'
    }));
    ```
    """
    # 验证token
    try:
        token_data = AuthService.decode_token(token)
        user = await chat_service.get_user_by_username(token_data.username)
        if not user:
            await websocket.close(code=4001, reason="Unauthorized")
            return
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    # 生成连接ID
    import uuid
    connection_id = str(uuid.uuid4())
    
    # 连接管理
    await manager.connect(websocket, str(user.id), connection_id)
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_json()
            
            # 处理不同类型的消息
            action = data.get("action")
            
            if action == "ping":
                # 心跳检测
                await websocket.send_json({
                    "type": "pong",
                    "data": {"timestamp": datetime.utcnow().isoformat()}
                })
            
            elif action == "subscribe":
                # 订阅会话
                conversation_id = data.get("conversation_id")
                if conversation_id:
                    await manager.subscribe_to_conversation(
                        str(user.id),
                        connection_id,
                        conversation_id
                    )
                    await websocket.send_json({
                        "type": "subscribed",
                        "data": {"conversation_id": conversation_id}
                    })
            
            elif action == "unsubscribe":
                # 取消订阅
                conversation_id = data.get("conversation_id")
                if conversation_id:
                    await manager.unsubscribe_from_conversation(
                        str(user.id),
                        connection_id,
                        conversation_id
                    )
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "data": {"conversation_id": conversation_id}
                    })
            
            elif action in ["send_message", "edit_message", "delete_message", "typing"]:
                # 处理聊天相关操作
                await chat_service.handle_websocket_message(
                    websocket=websocket,
                    user_id=user.id,
                    message=data
                )
            
            else:
                # 未知操作
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"Unknown action: {action}"}
                })
    
    except WebSocketDisconnect:
        manager.disconnect(str(user.id), connection_id)
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "data": {"message": str(e)}
        })
        await websocket.close()
        manager.disconnect(str(user.id), connection_id)

@router.websocket("/notifications")
async def websocket_notifications(
    websocket: WebSocket,
    token: str = Query(...)
):
    """
    通知WebSocket端点
    用于推送系统通知、消息更新等
    """
    # 验证token
    try:
        token_data = AuthService.decode_token(token)
        # 这里应该从数据库获取用户
        user_id = token_data.username  # 简化示例
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    await websocket.accept()
    
    try:
        # 发送初始连接消息
        await websocket.send_json({
            "type": "connected",
            "data": {"user_id": user_id}
        })
        
        # 保持连接并定期发送通知
        while True:
            # 这里可以监听Redis发布/订阅或其他消息队列
            # 示例：发送模拟通知
            await asyncio.sleep(30)  # 每30秒检查一次
            
            # 检查是否有新通知
            # notifications = await get_pending_notifications(user_id)
            # for notification in notifications:
            #     await websocket.send_json({
            #         "type": "notification",
            #         "data": notification
            #     })
    
    except WebSocketDisconnect:
        print(f"User {user_id} disconnected from notifications")