# app/models/__init__.py

# 导入所有模型
from app.models.user import User, UserRole
from app.models.chat import ChatSession, ChatMessage, ChatTemplate, ChatShare
from app.models.file import File, FileShare, FileConversion, FileChunk
from app.models.workspace import Project, ProjectFile, ProjectExecution

# 为了向后兼容，创建别名
Conversation = ChatSession  # 别名：Conversation -> ChatSession
Message = ChatMessage       # 别名：Message -> ChatMessage

# 导出所有模型
__all__ = [
    # 用户相关
    'User',
    'UserRole',
    
    # 聊天相关
    'ChatSession',
    'ChatMessage', 
    'ChatTemplate',
    'ChatShare',
    
    # 文件相关
    'File',
    'FileShare',
    'FileConversion',
    'FileChunk',
    
    'Project',
    'ProjectFile',
    'ProjectExecution',
    
    # 兼容性别名
    'Conversation',
    'Message'
]