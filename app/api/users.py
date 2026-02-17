from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_active_superuser
from app.models.user import User
from app.schemas.user import (
    UserResponse, UserUpdate, UserPreferences,
    UserPlugins, UserAPIKeys, UserSettingsUpdate
)
from app.db.session import get_db
from app.services.user_service import UserService
from app.dependencies import get_user_service

router = APIRouter(prefix="/api/users", tags=["users"])

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """获取当前用户信息"""
    return UserResponse.from_orm(current_user)

@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """更新当前用户信息"""
    updated_user = await user_service.update_user(
        user_id=current_user.id,
        update_data=user_update.dict(exclude_unset=True)
    )
    return UserResponse.from_orm(updated_user)

@router.get("/settings")
async def get_user_settings(
    current_user: User = Depends(get_current_user)
):
    """获取用户设置"""
    return {
        "language": current_user.language,
        "preferred_model": current_user.preferred_model,
        "system_prompt": current_user.system_prompt,
        "claude_system_prompt": current_user.claude_system_prompt,
        "preferences": current_user.preferences,
        "plugins": current_user.plugins
    }

@router.put("/settings")
async def update_user_settings(
    settings: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """更新用户设置"""
    # 更新语言
    if settings.language:
        await user_service.update_user_language(current_user.id, settings.language)
    
    # 更新模型
    if settings.preferred_model:
        await user_service.update_preferred_model(current_user.id, settings.preferred_model)
    
    # 更新系统提示词
    if settings.system_prompt is not None:
        await user_service.update_system_prompt(
            current_user.id,
            settings.system_prompt,
            is_claude=False
        )
    
    if settings.claude_system_prompt is not None:
        await user_service.update_system_prompt(
            current_user.id,
            settings.claude_system_prompt,
            is_claude=True
        )
    
    return {"status": "success", "message": "设置已更新"}

@router.put("/preferences")
async def update_user_preferences(
    preferences: UserPreferences,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """更新用户偏好设置"""
    await user_service.update_user_preferences(
        user_id=current_user.id,
        preferences=preferences.dict()
    )
    return {"status": "success", "message": "偏好设置已更新"}

@router.put("/plugins")
async def update_user_plugins(
    plugins: UserPlugins,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """更新用户插件设置"""
    await user_service.update_user_plugins(
        user_id=current_user.id,
        plugins=plugins.dict()
    )
    return {"status": "success", "message": "插件设置已更新"}

@router.post("/api-keys")
async def add_api_key(
    provider: str,
    api_key: str,
    api_url: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """添加API密钥"""
    if not api_key.startswith(("sk-", "anthropic-")):
        raise HTTPException(
            status_code=400,
            detail="无效的API密钥格式"
        )
    
    await user_service.add_api_key(
        user_id=current_user.id,
        provider=provider,
        api_key=api_key,
        api_url=api_url
    )
    
    return {"status": "success", "message": "API密钥已添加"}

@router.delete("/api-keys/{provider}")
async def remove_api_key(
    provider: str,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """删除API密钥"""
    await user_service.remove_api_key(
        user_id=current_user.id,
        provider=provider
    )
    return {"status": "success", "message": "API密钥已删除"}

@router.get("/statistics")
async def get_user_statistics(
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """获取用户统计信息"""
    stats = await user_service.get_user_statistics(current_user.id)
    return stats

@router.delete("/me")
async def delete_current_user(
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """删除当前用户账户"""
    await user_service.delete_user(current_user.id)
    return {"status": "success", "message": "账户已删除"}

# 管理员端点
@router.get("/list", response_model=Dict[str, Any])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_active_superuser),
    db: Session = Depends(get_db)
):
    """列出所有用户（仅管理员）"""
    users = db.query(User).offset(skip).limit(limit).all()
    total = db.query(User).count()
    
    return {
        "users": [UserResponse.from_orm(user) for user in users],
        "total": total,
        "skip": skip,
        "limit": limit
    }

@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    user_id: str,
    current_user: User = Depends(get_current_active_superuser),
    user_service: UserService = Depends(get_user_service)
):
    """根据ID获取用户（仅管理员）"""
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="用户不存在"
        )
    return UserResponse.from_orm(user)

@router.put("/{user_id}/activate")
async def activate_user(
    user_id: str,
    is_active: bool,
    current_user: User = Depends(get_current_active_superuser),
    user_service: UserService = Depends(get_user_service)
):
    """激活或停用用户（仅管理员）"""
    await user_service.set_user_active_status(user_id, is_active)
    status = "激活" if is_active else "停用"
    return {"status": "success", "message": f"用户已{status}"}