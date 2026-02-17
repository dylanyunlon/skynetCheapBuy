# app/dependencies.py - 增强版
from typing import Generator, Optional
from fastapi import Depends, HTTPException, status, Header, WebSocket, Query
from sqlalchemy.orm import Session
import aioredis
from jose import JWTError, jwt
import logging
import uuid

from app.db.session import SessionLocal
from app.db.redis import get_redis
from app.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

# 数据库会话依赖
def get_db() -> Generator[Session, None, None]:
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
        db.commit()  # 添加显式提交
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Redis依赖
async def get_redis_client() -> aioredis.Redis:
    """获取Redis客户端"""
    return await get_redis()

# 修复：添加 verify_token 函数
def verify_token(token: str) -> dict:
    """验证JWT token并返回用户信息"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        
        # 从 payload 中获取用户信息
        user_id = payload.get("sub")
        username = payload.get("username")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user_id"
            )
        
        return {
            "user_id": user_id,
            "username": username,
            "payload": payload
        }
        
    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )

# 认证依赖
async def get_current_user(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
) -> User:
    """获取当前登录用户"""
    logger.info(f"[Auth Debug] Authorization header: {authorization[:50] if authorization else 'None'}...")
    
    if not authorization:
        logger.warning("[Auth Debug] No authorization header provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证信息",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 检查 Bearer token
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            logger.warning(f"[Auth Debug] Invalid auth scheme: {scheme}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的认证方案",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except ValueError:
        logger.warning("[Auth Debug] Invalid auth format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证格式",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        # 解码 JWT token
        logger.info("[Auth Debug] Decoding JWT token...")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        sub_value: str = payload.get("sub")
        
        logger.info(f"[Auth Debug] Token payload - sub: {sub_value}, username: {payload.get('username')}")
        
        if sub_value is None:
            logger.warning("[Auth Debug] No 'sub' in token payload")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的认证凭据",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # 智能判断 sub 是用户ID还是用户名
        user = None
        
        # 尝试作为UUID处理
        try:
            user_uuid = uuid.UUID(sub_value)
            logger.info(f"[Auth Debug] Searching user by UUID: {user_uuid}")
            user = db.query(User).filter(User.id == user_uuid).first()
            if user:
                logger.info(f"[Auth Debug] User found by UUID: {user.username}")
        except ValueError:
            # 不是有效的UUID，尝试作为用户名处理
            logger.info(f"[Auth Debug] Not a valid UUID, searching by username: {sub_value}")
            user = db.query(User).filter(User.username == sub_value).first()
            if user:
                logger.info(f"[Auth Debug] User found by username: {user.username}")
        
        if user is None:
            # 如果都找不到，再尝试从payload中获取username字段
            username = payload.get("username")
            if username:
                logger.info(f"[Auth Debug] Searching by payload username: {username}")
                user = db.query(User).filter(User.username == username).first()
                if user:
                    logger.info(f"[Auth Debug] User found by payload username: {user.username}")
        
        if user is None:
            logger.error("[Auth Debug] User not found in database")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
            
    except JWTError as e:
        logger.error(f"[Auth Debug] JWT decode error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        logger.warning(f"[Auth Debug] User {user.username} is not active")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户已被禁用"
        )
    
    logger.info(f"[Auth Debug] Authentication successful for user: {user.username}")
    return user

# WebSocket 认证依赖
async def get_current_user_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    db: Session = None
) -> Optional[User]:
    """
    WebSocket 连接的用户认证
    由于 WebSocket 不支持标准的 Authorization header，
    所以通过查询参数传递 token
    """
    if not token:
        logger.warning("WebSocket connection attempted without token")
        await websocket.close(code=1008)  # Policy Violation
        return None
    
    try:
        # 解码 JWT token
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        sub_value: str = payload.get("sub")
        
        if sub_value is None:
            logger.warning("Invalid token payload - missing sub")
            await websocket.close(code=1008)
            return None
        
        # 获取数据库会话
        if db is None:
            db = SessionLocal()
            should_close_db = True
        else:
            should_close_db = False
        
        try:
            # 智能查找用户
            user = None
            
            # 尝试作为UUID处理
            try:
                user_uuid = uuid.UUID(sub_value)
                user = db.query(User).filter(User.id == user_uuid).first()
            except ValueError:
                # 不是有效的UUID，尝试作为用户名处理
                user = db.query(User).filter(User.username == sub_value).first()
            
            if user is None:
                # 尝试从payload中获取username
                username = payload.get("username")
                if username:
                    user = db.query(User).filter(User.username == username).first()
            
            if user is None:
                logger.warning(f"User not found: {sub_value}")
                await websocket.close(code=1008)
                return None
            
            if not user.is_active:
                logger.warning(f"Inactive user attempted WebSocket connection: {user.username}")
                await websocket.close(code=1008)
                return None
            
            logger.info(f"WebSocket authenticated for user: {user.username} (ID: {user.id})")
            return user
            
        finally:
            if should_close_db:
                db.close()
                
    except JWTError as e:
        logger.error(f"JWT decode error in WebSocket auth: {e}")
        await websocket.close(code=1008)
        return None
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket auth: {e}")
        await websocket.close(code=1008)
        return None

# 可选：不需要数据库查询的简化版本
async def get_current_user_ws_simple(
    token: Optional[str] = Query(None)
) -> Optional[dict]:
    """
    简化的 WebSocket 认证（只验证 token，不查询数据库）
    返回 token payload 而不是 User 对象
    """
    if not token:
        return None
    
    try:
        # 解码 JWT token
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        sub_value: str = payload.get("sub")
        
        if sub_value is None:
            return None
            
        return {
            "user_id": sub_value,  # 可能是ID或用户名
            "username": payload.get("username"),  # 尝试获取用户名
            "payload": payload
        }
        
    except JWTError:
        return None

# 可选：添加获取当前活跃用户的依赖
async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """获取当前活跃用户"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="用户未激活")
    return current_user

# 可选：添加获取当前超级用户的依赖
async def get_current_superuser(
    current_user: User = Depends(get_current_user)
) -> User:
    """获取当前超级用户"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="没有足够的权限"
        )
    return current_user

# 服务依赖 - 延迟导入以避免循环依赖
def get_chat_service(
    db: Session = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis_client)
):
    """获取聊天服务实例"""
    from app.services.chat_service import ChatService
    return ChatService(db, redis)

def get_websocket_chat_service(
    db: Session = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis_client)
):
    """获取WebSocket聊天服务实例"""
    from app.services.chat_service import WebSocketChatService
    return WebSocketChatService(db, redis)

def get_user_service(
    db: Session = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis_client)
):
    """获取用户服务实例"""
    from app.services.user_service import UserService
    return UserService(db, redis)

def get_file_service(
    db: Session = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis_client)
):
    """获取文件服务实例"""
    from app.services.file_service import FileService
    return FileService(db, redis)

def get_ai_service(
    db: Session = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis_client)
):
    """获取AI服务实例"""
    from app.services.ai_service import AIService
    return AIService(db, redis)

def get_code_service(
    db: Session = Depends(get_db)
):
    """获取代码服务实例"""
    from app.services.code_service import CodeService
    return CodeService(db)  # 只传入 db，不传入 redis

def get_terminal_service(
    db: Session = Depends(get_db)
):
    """获取终端服务实例"""
    from app.core.terminal.pty_manager import PTYManager
    return PTYManager(db)

# 新增：V2架构相关依赖
def get_intent_engine():
    """获取意图识别引擎实例"""
    from app.core.intent.engine import IntentEngine
    return IntentEngine()

def get_chat_router(
    chat_service = Depends(get_chat_service)
):
    """获取聊天路由器实例"""
    from app.core.chat.router import ChatRouter
    from app.core.ai_engine import AIEngine
    ai_engine = AIEngine()
    return ChatRouter(chat_service, ai_engine)

# 修复：增强的项目服务依赖
def get_project_service(
    db: Session = Depends(get_db)
):
    """获取项目服务实例"""
    from app.services.project_service import ProjectService
    from app.core.workspace.workspace_manager import WorkspaceManager
    from app.core.ai.prompt_engine import PromptEngine
    from app.core.ai_engine import AIEngine
    
    # 初始化依赖组件
    workspace_manager = WorkspaceManager()
    ai_engine = AIEngine()  # 使用 AIEngine 而不是 AIService
    prompt_engine = PromptEngine(ai_engine)
    
    return ProjectService(db, workspace_manager, prompt_engine)

def get_workspace_service(
    db: Session = Depends(get_db)
):
    """获取工作空间服务实例"""
    from app.core.workspace.workspace_manager import WorkspaceManager
    return WorkspaceManager()

# 分页参数
class PaginationParams:
    """分页参数"""
    
    def __init__(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by: Optional[str] = None,
        order_desc: bool = False
    ):
        self.skip = skip
        self.limit = min(limit, 1000)  # 最大限制1000
        self.order_by = order_by
        self.order_desc = order_desc

def get_pagination(
    skip: int = 0,
    limit: int = 100,
    order_by: Optional[str] = None,
    order_desc: bool = False
) -> PaginationParams:
    """获取分页参数"""
    return PaginationParams(skip, limit, order_by, order_desc)

# 查询参数
class SearchParams:
    """搜索参数"""
    
    def __init__(
        self,
        q: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[str] = None
    ):
        self.q = q
        self.start_date = start_date
        self.end_date = end_date
        self.model = model
        self.status = status

def get_search_params(
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None
) -> SearchParams:
    """获取搜索参数"""
    return SearchParams(q, start_date, end_date, model, status)