from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from uuid import UUID
import json
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
import aioredis

from app.models.user import User, Conversation, Message
from app.config import settings, get_all_available_models, get_model_provider
from app.schemas.models import ModelInfo, ModelUsageStats


class AIService:
    """AI模型管理服务"""

    def __init__(self, db: Session, redis: aioredis.Redis):
        self.db = db
        self.redis = redis
        self._model_capabilities = self._load_model_capabilities()

    def _load_model_capabilities(self) -> Dict[str, Dict[str, Any]]:
        """加载模型能力配置"""
        return {
            "o3-gz": {
                "chat": True,
                "image_input": False,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 4096,
                "context_window": 16384,
                "cost_per_1k_input": 0.0005,
                "cost_per_1k_output": 0.0015
            },
            "gpt-3.5-turbo-16k": {
                "chat": True,
                "image_input": False,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 4096,
                "context_window": 16384,
                "cost_per_1k_input": 0.003,
                "cost_per_1k_output": 0.004
            },
            "gpt-4": {
                "chat": True,
                "image_input": False,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 8192,
                "context_window": 8192,
                "cost_per_1k_input": 0.03,
                "cost_per_1k_output": 0.06
            },
            "gpt-4-turbo-preview": {
                "chat": True,
                "image_input": False,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 4096,
                "context_window": 128000,
                "cost_per_1k_input": 0.01,
                "cost_per_1k_output": 0.03
            },
            "gpt-4-vision-preview": {
                "chat": True,
                "image_input": True,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 4096,
                "context_window": 128000,
                "cost_per_1k_input": 0.01,
                "cost_per_1k_output": 0.03
            },
            "claude-3-opus": {
                "chat": True,
                "image_input": True,
                "image_generation": False,
                "function_calling": False,
                "streaming": True,
                "max_tokens": 4096,
                "context_window": 200000,
                "cost_per_1k_input": 0.015,
                "cost_per_1k_output": 0.075
            },
            "claude-3-sonnet": {
                "chat": True,
                "image_input": True,
                "image_generation": False,
                "function_calling": False,
                "streaming": True,
                "max_tokens": 4096,
                "context_window": 200000,
                "cost_per_1k_input": 0.003,
                "cost_per_1k_output": 0.015
            },
            "claude-3-haiku": {
                "chat": True,
                "image_input": True,
                "image_generation": False,
                "function_calling": False,
                "streaming": True,
                "max_tokens": 4096,
                "context_window": 200000,
                "cost_per_1k_input": 0.00025,
                "cost_per_1k_output": 0.00125
            },
            "gemini-pro": {
                "chat": True,
                "image_input": False,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 8192,
                "context_window": 32768,
                "cost_per_1k_input": 0.0005,
                "cost_per_1k_output": 0.0015
            },
            "gemini-pro-vision": {
                "chat": True,
                "image_input": True,
                "image_generation": False,
                "function_calling": True,
                "streaming": True,
                "max_tokens": 8192,
                "context_window": 32768,
                "cost_per_1k_input": 0.0005,
                "cost_per_1k_output": 0.0015
            }
        }

    async def check_model_availability(
            self,
            model: str,
            user_id: UUID
    ) -> Dict[str, Any]:
        """检查模型可用性"""
        # 检查系统配置
        provider = get_model_provider(model)
        if not provider:
            return {
                "available": False,
                "model": model,
                "reason": "Unknown model"
            }

        # 检查API密钥
        from app.services.user_service import UserService
        user_service = UserService(self.db, self.redis)
        user = await user_service.get_user_by_id(user_id)

        # 检查用户自定义API密钥
        has_user_key = False
        if user and user.api_keys:
            has_user_key = provider in user.api_keys

        # 检查系统API密钥
        has_system_key = False
        if provider == "openai" and settings.OPENAI_API_KEY:
            has_system_key = True
        elif provider == "anthropic" and settings.ANTHROPIC_API_KEY:
            has_system_key = True
        elif provider == "google" and settings.GOOGLE_AI_API_KEY:
            has_system_key = True

        available = has_user_key or has_system_key

        # 获取模型能力
        capabilities = self._model_capabilities.get(model, {})

        return {
            "available": available,
            "model": model,
            "provider": provider,
            "has_user_key": has_user_key,
            "has_system_key": has_system_key,
            "capabilities": capabilities,
            "reason": None if available else "No API key configured"
        }

    async def get_user_custom_models(self, user_id: UUID) -> List[Dict[str, Any]]:
        """获取用户自定义模型"""
        # 从Redis缓存获取
        cache_key = f"user_custom_models:{user_id}"
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)

        # 从数据库获取用户
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return []

        # 获取用户配置的自定义模型
        custom_models = []
        if user.api_urls:
            for provider, url in user.api_urls.items():
                if provider == "custom" and user.api_keys.get("custom"):
                    # 这里可以扩展支持更多自定义模型
                    custom_models.append({
                        "name": "custom-model",
                        "provider": "custom",
                        "api_url": url,
                        "available": True
                    })

        # 缓存结果
        await self.redis.setex(cache_key, 3600, json.dumps(custom_models))

        return custom_models

    async def get_model_details(
            self,
            model: str,
            user_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """获取模型详细信息"""
        # 检查可用性
        availability = await self.check_model_availability(model, user_id)
        if not availability["available"]:
            return None

        # 获取基本信息
        provider = get_model_provider(model)
        capabilities = self._model_capabilities.get(model, {})

        # 获取使用统计
        usage_stats = await self.get_model_usage_for_user(user_id, model)

        return {
            "name": model,
            "provider": provider,
            "available": True,
            "capabilities": capabilities,
            "usage": usage_stats,
            "description": self._get_model_description(model),
            "recommended_for": self._get_model_recommendations(model)
        }

    def _get_model_description(self, model: str) -> str:
        """获取模型描述"""
        descriptions = {
            "o3-gz": "Fast and efficient model for most tasks",
            "gpt-4": "Most capable GPT model for complex reasoning",
            "gpt-4-turbo-preview": "Latest GPT-4 with 128k context window",
            "gpt-4-vision-preview": "GPT-4 with image understanding capabilities",
            "claude-3-opus": "Most powerful Claude model for complex tasks",
            "claude-3-sonnet": "Balanced Claude model for general use",
            "claude-3-haiku": "Fast and affordable Claude model",
            "gemini-pro": "Google's advanced language model",
            "gemini-pro-vision": "Gemini with multimodal capabilities"
        }
        return descriptions.get(model, "Advanced AI language model")

    def _get_model_recommendations(self, model: str) -> List[str]:
        """获取模型推荐用途"""
        recommendations = {
            "o3-gz": ["General chat", "Code generation", "Quick responses"],
            "gpt-4": ["Complex reasoning", "Advanced coding", "Creative writing"],
            "gpt-4-turbo-preview": ["Long documents", "Detailed analysis", "Research"],
            "gpt-4-vision-preview": ["Image analysis", "Visual questions", "OCR tasks"],
            "claude-3-opus": ["Deep analysis", "Complex coding", "Academic writing"],
            "claude-3-sonnet": ["General purpose", "Balanced performance", "Daily tasks"],
            "claude-3-haiku": ["Quick queries", "High volume tasks", "Cost-effective"],
            "gemini-pro": ["Factual queries", "Technical content", "Reasoning"],
            "gemini-pro-vision": ["Image understanding", "Visual content", "Multimodal tasks"]
        }
        return recommendations.get(model, ["General AI assistance"])

    async def test_model_connection(
            self,
            model_name: str,
            user_id: UUID,
            test_message: str = "Hello, please respond with 'OK' if you can read this."
    ) -> Dict[str, Any]:
        """测试模型连接"""
        import time
        from app.core.ai_engine import AIEngine

        start_time = time.time()

        try:
            # 获取用户配置
            from app.services.user_service import UserService
            user_service = UserService(self.db, self.redis)
            user = await user_service.get_user_by_id(user_id)

            # 获取API密钥
            provider = get_model_provider(model_name)
            api_key = None
            api_url = None

            if user and user.api_keys and provider in user.api_keys:
                api_key = await user_service.get_decrypted_api_key(user_id, provider)
                api_url = user.api_urls.get(provider)

            # 创建AI引擎实例
            ai_engine = AIEngine()

            # 发送测试消息
            response = await ai_engine.get_completion(
                messages=[{"role": "user", "content": test_message}],
                model=model_name,
                api_key=api_key,
                api_url=api_url,
                max_tokens=50
            )

            end_time = time.time()
            latency = round((end_time - start_time) * 1000)  # 毫秒

            return {
                "success": True,
                "response": response["content"],
                "latency": latency,
                "model": model_name
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "model": model_name
            }

    async def validate_custom_model(
            self,
            model_config: Dict[str, Any],
            user_id: UUID
    ) -> bool:
        """验证自定义模型配置"""
        required_fields = ["name", "provider", "api_url"]

        # 检查必需字段
        for field in required_fields:
            if field not in model_config:
                return False

        # 如果提供了API密钥，尝试测试连接
        if model_config.get("api_key"):
            result = await self.test_model_connection(
                model_name=model_config["name"],
                user_id=user_id,
                test_message="Test connection"
            )
            return result["success"]

        return True

    async def save_custom_model(
            self,
            user_id: UUID,
            model_config: Dict[str, Any]
    ):
        """保存自定义模型配置"""
        # 这里可以扩展实现自定义模型的存储
        # 目前简化处理，存储在用户的api_urls中
        from app.services.user_service import UserService
        user_service = UserService(self.db, self.redis)

        # 添加自定义API配置
        await user_service.add_api_key(
            user_id=user_id,
            provider="custom",
            api_key=model_config.get("api_key", ""),
            api_url=model_config["api_url"]
        )

        # 清除缓存
        cache_key = f"user_custom_models:{user_id}"
        await self.redis.delete(cache_key)

    async def remove_custom_model(
            self,
            user_id: UUID,
            model_name: str
    ) -> bool:
        """删除自定义模型"""
        # 简化实现
        from app.services.user_service import UserService
        user_service = UserService(self.db, self.redis)

        if model_name == "custom-model":
            await user_service.remove_api_key(user_id, "custom")

            # 清除缓存
            cache_key = f"user_custom_models:{user_id}"
            await self.redis.delete(cache_key)

            return True

        return False

    async def get_user_model_usage(
            self,
            user_id: UUID,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取用户模型使用统计"""
        # 构建查询
        query = self.db.query(
            Conversation.model,
            func.count(Message.id).label('message_count'),
            func.sum(
                func.coalesce(
                    func.json_extract(Message.metadata, '$.tokens.total_tokens'),
                    0
                )
            ).label('total_tokens')
        ).join(
            Message, Message.conversation_id == Conversation.id
        ).filter(
            Conversation.user_id == user_id
        )

        # 添加时间过滤
        if start_date:
            query = query.filter(Message.created_at >= datetime.fromisoformat(start_date))
        if end_date:
            query = query.filter(Message.created_at <= datetime.fromisoformat(end_date))

        # 按模型分组
        results = query.group_by(Conversation.model).all()

        # 计算统计
        usage_by_model = {}
        total_cost = 0.0

        for model, message_count, total_tokens in results:
            # 获取模型成本
            capabilities = self._model_capabilities.get(model, {})
            cost_per_1k = capabilities.get('cost_per_1k_input', 0) + capabilities.get('cost_per_1k_output', 0)
            model_cost = (total_tokens or 0) / 1000 * cost_per_1k

            usage_by_model[model] = {
                "message_count": message_count,
                "total_tokens": total_tokens or 0,
                "estimated_cost": round(model_cost, 4)
            }

            total_cost += model_cost

        # 获取最后使用时间
        last_message = self.db.query(Message).join(Conversation).filter(
            Conversation.user_id == user_id
        ).order_by(Message.created_at.desc()).first()

        return {
            "usage_by_model": usage_by_model,
            "total_cost": round(total_cost, 4),
            "period": {
                "start": start_date,
                "end": end_date
            },
            "last_used": last_message.created_at.isoformat() if last_message else None
        }

    async def get_model_usage_for_user(
            self,
            user_id: UUID,
            model: str
    ) -> ModelUsageStats:
        """获取特定模型的使用统计"""
        # 查询该模型的使用情况
        result = self.db.query(
            func.count(Message.id).label('message_count'),
            func.sum(
                func.coalesce(
                    func.json_extract(Message.metadata, '$.tokens.total_tokens'),
                    0
                )
            ).label('total_tokens'),
            func.max(Message.created_at).label('last_used')
        ).join(
            Conversation, Message.conversation_id == Conversation.id
        ).filter(
            and_(
                Conversation.user_id == user_id,
                Conversation.model == model
            )
        ).first()

        message_count, total_tokens, last_used = result

        # 计算成本
        capabilities = self._model_capabilities.get(model, {})
        cost_per_1k = capabilities.get('cost_per_1k_input', 0) + capabilities.get('cost_per_1k_output', 0)
        total_cost = (total_tokens or 0) / 1000 * cost_per_1k

        return ModelUsageStats(
            model=model,
            total_messages=message_count or 0,
            total_tokens=total_tokens or 0,
            total_cost=round(total_cost, 4),
            last_used=last_used
        )