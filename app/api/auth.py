from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
import uuid
import logging

from app.core.auth import AuthService, get_current_user
from app.schemas.auth import Token, UserCreate, UserLogin, TokenRefresh
from app.models.user import User
from app.db.session import get_db
from app.config import settings
from app.services.user_service import UserService
from app.dependencies import get_user_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/register", response_model=Token)
async def register(
    user_create: UserCreate,
    db: Session = Depends(get_db),
    user_service: UserService = Depends(get_user_service)
):
    """
    用户注册
    
    创建新用户账户并返回访问令牌
    """
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(
        (User.username == user_create.username) | 
        (User.email == user_create.email)
    ).first()
    
    if existing_user:
        if existing_user.username == user_create.username:
            raise HTTPException(
                status_code=400,
                detail="用户名已被注册"
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="邮箱已被注册"
            )
    
    # 创建新用户
    hashed_password = AuthService.get_password_hash(user_create.password)
    new_user = User(
        username=user_create.username,
        email=user_create.email,
        hashed_password=hashed_password,
        language=user_create.language or settings.DEFAULT_LANGUAGE
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # 创建访问令牌 - 使用用户ID而不是用户名
    access_token = AuthService.create_access_token(
        data={
            "sub": str(new_user.id),  # 使用用户ID
            "username": new_user.username,  # 也包含用户名作为额外信息
            "email": new_user.email
        }
    )
    refresh_token = AuthService.create_refresh_token(
        data={
            "sub": str(new_user.id),
            "username": new_user.username
        }
    )
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user_id": str(new_user.id),  # 返回用户ID
        "username": new_user.username  # 返回用户名
    }

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    用户登录
    
    使用用户名和密码登录，返回访问令牌
    """
    # 查找用户
    user = db.query(User).filter(User.username == form_data.username).first()
    
    if not user or not AuthService.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户账户已被禁用"
        )
    
    # 创建访问令牌 - 使用用户ID
    access_token = AuthService.create_access_token(
        data={
            "sub": str(user.id),  # 使用用户ID
            "username": user.username,  # 也包含用户名
            "email": user.email
        }
    )
    refresh_token = AuthService.create_refresh_token(
        data={
            "sub": str(user.id),
            "username": user.username
        }
    )
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user_id": str(user.id),  # 返回用户ID
        "username": user.username  # 返回用户名
    }

@router.post("/refresh", response_model=Token)
async def refresh_token(
    token_refresh: TokenRefresh,
    db: Session = Depends(get_db)
):
    """
    刷新访问令牌
    
    使用刷新令牌获取新的访问令牌
    """
    try:
        logger.info("[Refresh] Starting token refresh process")
        
        # 使用 AuthService 解码刷新令牌
        payload = AuthService.decode_refresh_token(token_refresh.refresh_token)
        
        if not payload:
            logger.warning("[Refresh] Invalid refresh token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的刷新令牌"
            )
        
        # 从 payload 中获取用户标识符
        user_identifier = payload.get("sub")
        username = payload.get("username")
        
        if not user_identifier:
            logger.warning("[Refresh] Missing user identifier in token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的令牌格式"
            )
        
        logger.info(f"[Refresh] Looking for user: {user_identifier}")
        
        user = None
        
        # 尝试作为 UUID 查找
        try:
            user_uuid = uuid.UUID(user_identifier)
            user = db.query(User).filter(User.id == user_uuid).first()
            if user:
                logger.info(f"[Refresh] User found by UUID: {user.username}")
        except ValueError:
            # 不是有效的 UUID，尝试作为用户名查找
            logger.info(f"[Refresh] Searching by username: {user_identifier}")
            user = db.query(User).filter(User.username == user_identifier).first()
            if user:
                logger.info(f"[Refresh] User found by username: {user.username}")
        
        # 如果还是找不到，尝试使用 username 字段
        if not user and username:
            logger.info(f"[Refresh] Searching by payload username: {username}")
            user = db.query(User).filter(User.username == username).first()
            if user:
                logger.info(f"[Refresh] User found by payload username: {user.username}")
            
        if not user:
            logger.error(f"[Refresh] User not found: {user_identifier}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在"
            )
            
        if not user.is_active:
            logger.warning(f"[Refresh] User {user.username} is not active")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户账户已被禁用"
            )
        
        # 创建新的访问令牌
        access_token = AuthService.create_access_token(
            data={
                "sub": str(user.id),
                "username": user.username,
                "email": user.email
            }
        )
        
        # 创建新的刷新令牌
        new_refresh_token = AuthService.create_refresh_token(
            data={
                "sub": str(user.id),
                "username": user.username
            }
        )
        
        logger.info(f"[Refresh] Successfully refreshed tokens for user: {user.username}")
        
        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user_id": str(user.id),
            "username": user.username
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Refresh] Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"令牌验证失败: {str(e)}"
        )

@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user)
):
    """
    用户登出
    
    在实际应用中，这里可以将令牌加入黑名单
    """
    # TODO: 实现令牌黑名单机制
    # 可以使用Redis存储已失效的令牌
    
    return {"message": "登出成功"}

@router.post("/change-password")
async def change_password(
    current_password: str,
    new_password: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    修改密码
    """
    # 验证当前密码
    if not AuthService.verify_password(current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="当前密码错误"
        )
    
    # 更新密码
    current_user.hashed_password = AuthService.get_password_hash(new_password)
    db.commit()
    
    return {"message": "密码修改成功"}

@router.post("/reset-password-request")
async def request_password_reset(
    email: str,
    db: Session = Depends(get_db)
):
    """
    请求重置密码
    
    发送重置密码邮件（需要配置邮件服务）
    """
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        # 为了安全，即使用户不存在也返回成功
        return {"message": "如果该邮箱已注册，您将收到重置密码的邮件"}
    
    # TODO: 实现发送重置密码邮件的逻辑
    # 1. 生成重置令牌
    # 2. 发送包含重置链接的邮件
    # 3. 存储重置令牌（可以使用Redis，设置过期时间）
    
    return {"message": "如果该邮箱已注册，您将收到重置密码的邮件"}

@router.post("/reset-password")
async def reset_password(
    token: str,
    new_password: str,
    db: Session = Depends(get_db)
):
    """
    重置密码
    
    使用重置令牌设置新密码
    """
    # TODO: 验证重置令牌
    # 1. 从Redis或数据库中验证令牌
    # 2. 获取关联的用户
    # 3. 更新密码
    # 4. 删除使用过的令牌
    
    raise HTTPException(
        status_code=501,
        detail="密码重置功能尚未实现"
    )

@router.get("/verify")
async def verify_token(
    current_user: User = Depends(get_current_user)
):
    """
    验证令牌
    
    检查当前令牌是否有效
    """
    return {
        "valid": True,
        "user_id": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "is_active": current_user.is_active
    }

@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    获取当前用户信息
    """
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "is_active": current_user.is_active,
        "is_superuser": current_user.is_superuser,
        "role": current_user.role,
        "language": current_user.language,
        "preferred_model": current_user.preferred_model,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "updated_at": current_user.updated_at.isoformat() if current_user.updated_at else None
    }