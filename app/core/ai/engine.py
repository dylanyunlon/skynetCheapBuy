from typing import Dict, Any, List, Optional, AsyncGenerator
import asyncio
from app.core.config_manager import config_manager
from app.core.ai.plugin_system import plugin_manager
from app.core.cache.cache_manager import cache_manager
from app.schemas.chat import StreamChunk
import logging

logger = logging.getLogger(__name__)

class AIEngine:
    """重构后的 AI 引擎"""
    
    def __init__(self):
        self._initialized = False
        self._provider_cache = {}
    
    async def initialize(self):
        """初始化引擎"""
        if self._initialized:
            return
        
        # 发现并加载插件
        await plugin_manager.discover_plugins()
        
        # 加载配置的提供商
        for provider_name, provider_config in config_manager._cache.get("providers", {}).items():
            if provider_config.enabled:
                try:
                    await plugin_manager.load_plugin(
                        provider_name,
                        provider_config.dict()
                    )
                    logger.info(f"Loaded provider plugin: {provider_name}")
                except Exception as e:
                    logger.error(f"Failed to load provider {provider_name}: {e}")
        
        self._initialized = True
    
    async def get_provider_for_model(self, model: str) -> Optional[Any]:
        """获取模型对应的提供商"""
        # 从缓存获取
        if model in self._provider_cache:
            return self._provider_cache[model]
        
        # 获取模型配置
        model_config = config_manager.get_model_config(model)
        if not model_config:
            raise ValueError(f"Model {model} not found in registry")
        
        # 获取提供商插件
        provider = plugin_manager.get_plugin(model_config.provider)
        if not provider:
            raise ValueError(f"Provider {model_config.provider} not available")
        
        # 缓存
        self._provider_cache[model] = provider
        return provider
    
    @cache_manager.cached(ttl=300, key_prefix="ai_completion")
    async def get_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> Dict[str, Any]:
        """获取 AI 完成响应"""
        # 确保初始化
        await self.initialize()
        
        # 获取提供商
        provider = await self.get_provider_for_model(model)
        
        # 获取模型配置
        model_config = config_manager.get_model_config(model)
        
        # 应用模型限制
        if model_config:
            if "max_tokens" not in kwargs and model_config.limits.get("max_tokens"):
                kwargs["max_tokens"] = model_config.limits["max_tokens"]
        
        # 调用提供商
        try:
            result = await provider.get_completion(messages, model, **kwargs)
            
            # 记录使用情况
            await self._record_usage(model, result.get("usage", {}))
            
            return result
        except Exception as e:
            logger.error(f"Completion error for model {model}: {e}")
            raise
    
    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式获取 AI 响应"""
        await self.initialize()
        
        provider = await self.get_provider_for_model(model)
        model_config = config_manager.get_model_config(model)
        
        # 应用配置
        if model_config and "max_tokens" not in kwargs:
            kwargs["max_tokens"] = model_config.limits.get("max_tokens")
        
        try:
            async for chunk in provider.stream_completion(messages, model, **kwargs):
                yield StreamChunk(**chunk)
        except Exception as e:
            logger.error(f"Stream error for model {model}: {e}")
            yield StreamChunk(
                content=f"Error: {str(e)}",
                type="error",
                metadata={"error": True}
            )
    
    async def _record_usage(self, model: str, usage: Dict[str, Any]):
        """记录使用情况"""
        # 这里可以实现使用统计记录
        pass
    
    async def validate_model_availability(self, model: str, user_id: str) -> Dict[str, Any]:
        """验证模型可用性"""
        await self.initialize()
        
        # 检查模型配置
        model_config = config_manager.get_model_config(model)
        if not model_config or not model_config.enabled:
            return {
                "available": False,
                "reason": "Model not enabled or not found"
            }
        
        # 检查提供商
        provider = plugin_manager.get_plugin(model_config.provider)
        if not provider:
            return {
                "available": False,
                "reason": f"Provider {model_config.provider} not available"
            }
        
        # 验证模型
        try:
            is_valid = await provider.validate_model(model)
            return {
                "available": is_valid,
                "reason": None if is_valid else "Model validation failed"
            }
        except Exception as e:
            return {
                "available": False,
                "reason": str(e)
            }

# 全局 AI 引擎实例
ai_engine = AIEngine()