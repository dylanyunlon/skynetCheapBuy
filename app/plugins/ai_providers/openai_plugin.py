from typing import Dict, Any, List, AsyncGenerator, Optional
import openai
from openai import AsyncOpenAI
from app.core.ai.plugin_system import AIProviderPlugin
from app.core.monitoring.metrics import metrics_collector
import logging

logger = logging.getLogger(__name__)

class OpenAIPlugin(AIProviderPlugin):
    """OpenAI 提供商插件"""
    
    async def initialize(self):
        """初始化插件"""
        self.api_key = self.config.get("api_key")
        self.api_base = self.config.get("api_base", "https://api.openai.com/v1")
        self.timeout = self.config.get("timeout", 6000)
        self.max_retries = self.config.get("max_retries", 3)
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            timeout=self.timeout,
            max_retries=self.max_retries
        )
        
        logger.info(f"OpenAI plugin initialized with base URL: {self.api_base}")
    
    async def get_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> Dict[str, Any]:
        """获取完成响应"""
        try:
            # 记录指标
            metrics_collector.record_model_usage(model, "openai")
            
            # 构建请求
            request_params = {
                "model": model,
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens"),
                "top_p": kwargs.get("top_p", 1.0),
                "frequency_penalty": kwargs.get("frequency_penalty", 0),
                "presence_penalty": kwargs.get("presence_penalty", 0),
                "stream": False
            }
            
            # 移除 None 值
            request_params = {k: v for k, v in request_params.items() if v is not None}
            
            # 处理函数调用
            if kwargs.get("functions"):
                request_params["functions"] = kwargs["functions"]
                if kwargs.get("function_call"):
                    request_params["function_call"] = kwargs["function_call"]
            
            # 调用 API
            response = await self.client.chat.completions.create(**request_params)
            
            # 处理响应
            choice = response.choices[0]
            result = {
                "content": choice.message.content or "",
                "role": choice.message.role,
                "finish_reason": choice.finish_reason,
                "usage": response.usage.model_dump() if response.usage else {}
            }
            
            # 处理函数调用
            if hasattr(choice.message, 'function_call') and choice.message.function_call:
                result["function_call"] = {
                    "name": choice.message.function_call.name,
                    "arguments": choice.message.function_call.arguments
                }
            
            return result
            
        except openai.APIStatusError as e:
            logger.error(f"OpenAI API error: {e.status_code} - {e.message}")
            raise Exception(f"API error: {e.message}")
        except openai.APIConnectionError as e:
            logger.error(f"OpenAI connection error: {e}")
            raise Exception("Failed to connect to OpenAI service")
        except Exception as e:
            logger.error(f"Unexpected error in OpenAI plugin: {e}")
            raise
    
    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式获取响应"""
        try:
            metrics_collector.record_model_usage(model, "openai")
            
            request_params = {
                "model": model,
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens"),
                "stream": True
            }
            
            request_params = {k: v for k, v in request_params.items() if v is not None}
            
            stream = await self.client.chat.completions.create(**request_params)
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield {
                        "content": chunk.choices[0].delta.content,
                        "type": "text",
                        "metadata": {}
                    }
                
                if chunk.choices[0].finish_reason:
                    yield {
                        "content": "",
                        "type": "finish",
                        "metadata": {
                            "finish_reason": chunk.choices[0].finish_reason
                        }
                    }
                    
        except Exception as e:
            logger.error(f"Stream error in OpenAI plugin: {e}")
            yield {
                "content": f"Error: {str(e)}",
                "type": "error",
                "metadata": {"error": True}
            }
    
    async def validate_model(self, model: str) -> bool:
        """验证模型是否可用"""
        try:
            # 尝试列出模型
            models = await self.client.models.list()
            model_ids = [m.id for m in models.data]
            return model in model_ids
        except:
            # 如果列出失败，尝试直接调用
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "test"}],
                    max_tokens=1
                )
                return True
            except:
                return False
    
    def get_capabilities(self) -> Dict[str, Any]:
        """获取插件能力"""
        return {
            "streaming": True,
            "function_calling": True,
            "image_input": True,  # GPT-4V
            "batch_processing": False,
            "embeddings": True,
            "fine_tuning": True
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            # 尝试获取模型列表
            models = await self.client.models.list()
            return {
                "status": "healthy",
                "name": self.name,
                "available_models": len(models.data),
                "base_url": self.api_base
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "name": self.name,
                "error": str(e)
            }