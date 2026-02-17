from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import json
import uuid
import aioredis

from app.config import settings


class SessionManager:
    """会话管理器"""

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.default_ttl = settings.SESSION_TIMEOUT  # 默认会话超时时间

    async def create_session(
            self,
            user_id: str,
            data: Dict[str, Any],
            ttl: Optional[int] = None
    ) -> str:
        """
        创建新会话

        Args:
            user_id: 用户ID
            data: 会话数据
            ttl: 会话生存时间（秒）

        Returns:
            会话ID
        """
        session_id = str(uuid.uuid4())
        session_key = f"session:{session_id}"

        session_data = {
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "last_accessed": datetime.utcnow().isoformat(),
            "data": data
        }

        ttl = ttl or self.default_ttl
        await self.redis.setex(
            session_key,
            ttl,
            json.dumps(session_data)
        )

        # 添加到用户的会话列表
        user_sessions_key = f"user_sessions:{user_id}"
        await self.redis.sadd(user_sessions_key, session_id)
        await self.redis.expire(user_sessions_key, ttl)

        return session_id

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话数据

        Args:
            session_id: 会话ID

        Returns:
            会话数据或None
        """
        session_key = f"session:{session_id}"
        session_data = await self.redis.get(session_key)

        if not session_data:
            return None

        data = json.loads(session_data)

        # 更新最后访问时间
        data["last_accessed"] = datetime.utcnow().isoformat()
        await self.redis.setex(
            session_key,
            self.default_ttl,
            json.dumps(data)
        )

        return data

    async def update_session(
            self,
            session_id: str,
            data: Dict[str, Any],
            merge: bool = True
    ) -> bool:
        """
        更新会话数据

        Args:
            session_id: 会话ID
            data: 新数据
            merge: 是否合并数据（True）或替换（False）

        Returns:
            是否成功
        """
        session_data = await self.get_session(session_id)
        if not session_data:
            return False

        if merge:
            session_data["data"].update(data)
        else:
            session_data["data"] = data

        session_key = f"session:{session_id}"
        await self.redis.setex(
            session_key,
            self.default_ttl,
            json.dumps(session_data)
        )

        return True

    async def delete_session(self, session_id: str) -> bool:
        """
        删除会话

        Args:
            session_id: 会话ID

        Returns:
            是否成功
        """
        session_key = f"session:{session_id}"
        session_data = await self.get_session(session_id)

        if session_data:
            # 从用户会话列表中移除
            user_id = session_data["user_id"]
            user_sessions_key = f"user_sessions:{user_id}"
            await self.redis.srem(user_sessions_key, session_id)

        # 删除会话数据
        result = await self.redis.delete(session_key)
        return result > 0

    async def get_user_sessions(self, user_id: str) -> list[str]:
        """
        获取用户的所有会话ID

        Args:
            user_id: 用户ID

        Returns:
            会话ID列表
        """
        user_sessions_key = f"user_sessions:{user_id}"
        session_ids = await self.redis.smembers(user_sessions_key)
        return list(session_ids) if session_ids else []

    async def delete_user_sessions(self, user_id: str) -> int:
        """
        删除用户的所有会话

        Args:
            user_id: 用户ID

        Returns:
            删除的会话数
        """
        session_ids = await self.get_user_sessions(user_id)
        deleted = 0

        for session_id in session_ids:
            if await self.delete_session(session_id):
                deleted += 1

        # 删除用户会话列表
        user_sessions_key = f"user_sessions:{user_id}"
        await self.redis.delete(user_sessions_key)

        return deleted

    async def extend_session(self, session_id: str, ttl: Optional[int] = None) -> bool:
        """
        延长会话时间

        Args:
            session_id: 会话ID
            ttl: 新的生存时间（秒）

        Returns:
            是否成功
        """
        session_key = f"session:{session_id}"
        ttl = ttl or self.default_ttl

        result = await self.redis.expire(session_key, ttl)
        return bool(result)

    async def cleanup_expired_sessions(self):
        """清理过期会话（通常由Redis自动处理）"""
        # Redis会自动删除过期键，这个方法主要用于清理孤立的引用
        pass


class ConversationSessionManager(SessionManager):
    """对话会话管理器"""

    async def create_conversation_session(
            self,
            user_id: str,
            conversation_id: str,
            model: str,
            system_prompt: Optional[str] = None
    ) -> str:
        """创建对话会话"""
        data = {
            "conversation_id": conversation_id,
            "model": model,
            "system_prompt": system_prompt,
            "message_count": 0,
            "context": []
        }

        return await self.create_session(user_id, data)

    async def add_message_to_context(
            self,
            session_id: str,
            role: str,
            content: str,
            max_context_length: int = 10
    ) -> bool:
        """添加消息到上下文"""
        session_data = await self.get_session(session_id)
        if not session_data:
            return False

        # 添加消息
        context = session_data["data"].get("context", [])
        context.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })

        # 限制上下文长度
        if len(context) > max_context_length:
            context = context[-max_context_length:]

        # 更新会话
        session_data["data"]["context"] = context
        session_data["data"]["message_count"] += 1

        return await self.update_session(session_id, session_data["data"], merge=False)

    async def get_conversation_context(self, session_id: str) -> list[Dict[str, str]]:
        """获取对话上下文"""
        session_data = await self.get_session(session_id)
        if not session_data:
            return []

        return session_data["data"].get("context", [])

    async def clear_conversation_context(self, session_id: str) -> bool:
        """清空对话上下文"""
        return await self.update_session(
            session_id,
            {"context": [], "message_count": 0},
            merge=True
        )