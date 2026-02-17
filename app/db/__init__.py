# app/db/__init__.py
"""
数据库初始化模块
在这里导入所有模型，确保它们被正确注册
"""

# 首先导入基础配置
from app.db.base import Base
from app.db.session import SessionLocal, engine, get_db

# 然后导入所有模型
# 这确保了所有模型都被 SQLAlchemy 发现
from app.models.user import User, Conversation, Message
from app.models.file import File
from app.models.chat import ChatSession, ChatMessage, ChatTemplate, ChatShare

# 导出常用的对象
__all__ = [
    "Base",
    "SessionLocal", 
    "engine",
    "get_db",
    "User",
    "Conversation",
    "Message",
    "File",
    "ChatSession",
    "ChatMessage",
    "ChatTemplate",
    "ChatShare"
]