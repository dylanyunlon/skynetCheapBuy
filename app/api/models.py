from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any, Optional

from app.core.auth import get_current_user
from app.models.user import User
from app.config import settings, get_all_available_models, get_model_groups, get_model_provider
from app.services.ai_service import AIService
from app.dependencies import get_ai_service

router = APIRouter(prefix="/api/models", tags=["models"])

@router.get("/available")
async def get_available_models(
    current_user: User = Depends(get_current_user),
    ai_service: AIService = Depends(get_ai_service)
):
    """
    获取可用的AI模型列表
    
    返回用户可以使用的所有AI模型，包括：
    - 系统配置的模型
    - 用户自定义API的模型
    """
    # 获取系统模型
    system_models = get_all_available_models()
    
    # 获取用户自定义模型
    user_models = await ai_service.get_user_custom_models(current_user.id)
    
    # 获取模型分组
    model_groups = get_model_groups()
    
    # 检查每个模型的可用性
    available_models = []
    for model in system_models:
        model_info = await ai_service.check_model_availability(model, current_user.id)
        if model_info["available"]:
            available_models.append(model_info)
    
    return {
        "models": available_models,
        "groups": model_groups,
        "custom_models": user_models,
        "default_model": current_user.preferred_model or settings.DEFAULT_MODEL
    }

@router.get("/groups")
async def get_model_groups(
    current_user: User = Depends(get_current_user)
):
    """获取模型分组"""
    return {
        "groups": get_model_groups(),
        "ungrouped_models": await _get_ungrouped_models()
    }

@router.get("/{model_name}/info")
async def get_model_info(
    model_name: str,
    current_user: User = Depends(get_current_user),
    ai_service: AIService = Depends(get_ai_service)
):
    """
    获取特定模型的详细信息
    
    包括：
    - 模型能力（是否支持图像、工具调用等）
    - 上下文窗口大小
    - 定价信息
    - 提供商信息
    """
    model_info = await ai_service.get_model_details(model_name, current_user.id)
    
    if not model_info:
        raise HTTPException(
            status_code=404,
            detail=f"模型 {model_name} 不存在或不可用"
        )
    
    return model_info

@router.post("/test")
async def test_model(
    model_name: str,
    test_message: str = "Hello, please respond with 'OK' if you can read this.",
    current_user: User = Depends(get_current_user),
    ai_service: AIService = Depends(get_ai_service)
):
    """
    测试模型连接
    
    发送测试消息并验证模型是否正常工作
    """
    try:
        response = await ai_service.test_model_connection(
            model_name=model_name,
            user_id=current_user.id,
            test_message=test_message
        )
        
        return {
            "status": "success",
            "model": model_name,
            "response": response,
            "latency": response.get("latency", 0)
        }
    except Exception as e:
        return {
            "status": "failed",
            "model": model_name,
            "error": str(e)
        }

@router.post("/custom")
async def add_custom_model(
    model_config: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    ai_service: AIService = Depends(get_ai_service)
):
    """
    添加自定义模型
    
    允许用户添加自定义的模型配置，如：
    - 自托管的模型
    - 第三方API兼容的模型
    """
    required_fields = ["name", "provider", "api_url"]
    for field in required_fields:
        if field not in model_config:
            raise HTTPException(
                status_code=400,
                detail=f"缺少必要字段: {field}"
            )
    
    # 验证模型配置
    is_valid = await ai_service.validate_custom_model(model_config, current_user.id)
    
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail="无效的模型配置或无法连接到模型"
        )
    
    # 保存自定义模型
    await ai_service.save_custom_model(current_user.id, model_config)
    
    return {
        "status": "success",
        "message": "自定义模型已添加",
        "model": model_config["name"]
    }

@router.delete("/custom/{model_name}")
async def remove_custom_model(
    model_name: str,
    current_user: User = Depends(get_current_user),
    ai_service: AIService = Depends(get_ai_service)
):
    """删除自定义模型"""
    success = await ai_service.remove_custom_model(current_user.id, model_name)
    
    if not success:
        raise HTTPException(
            status_code=404,
            detail="模型不存在或无权删除"
        )
    
    return {"status": "success", "message": "自定义模型已删除"}

@router.get("/usage/statistics")
async def get_model_usage_statistics(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    ai_service: AIService = Depends(get_ai_service)
):
    """
    获取模型使用统计
    
    返回用户在指定时间段内的模型使用情况
    """
    stats = await ai_service.get_user_model_usage(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date
    )
    
    return stats

@router.get("/capabilities")
async def get_model_capabilities():
    """
    获取所有模型的能力矩阵
    
    返回每个模型支持的功能列表
    """
    return {
        "capabilities": {
            "o3-gz": {
                "chat": True,
                "image_input": False,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 4096,
                "context_window": 16384
            },
            "gpt-4": {
                "chat": True,
                "image_input": False,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 8192,
                "context_window": 8192
            },
            "gpt-4-vision-preview": {
                "chat": True,
                "image_input": True,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 4096,
                "context_window": 128000
            },
            "claude-3-opus": {
                "chat": True,
                "image_input": True,
                "image_generation": False,
                "function_calling": False,
                "streaming": True,
                "max_tokens": 4096,
                "context_window": 200000
            },
            "gemini-pro": {
                "chat": True,
                "image_input": False,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 8192,
                "context_window": 32768
            },
            "gemini-pro-vision": {
                "chat": True,
                "image_input": True,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 8192,
                "context_window": 32768
            }
        }
    }

async def _get_ungrouped_models() -> List[str]:
    """获取未分组的模型"""
    all_models = get_all_available_models()
    grouped_models = set()
    
    for models in get_model_groups().values():
        grouped_models.update(models)
    
    return [model for model in all_models if model not in grouped_models]