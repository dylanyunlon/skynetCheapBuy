from typing import Dict, Any, List, AsyncGenerator
import httpx
from app.core.ai.plugin_system import AIProviderPlugin

class DoubaoProvider(AIProviderPlugin):
    """Doubao AI 提供商插件"""
    
    async def initialize(self):
        """初始化插件"""
        self.api_base = self.config.get("api_base", "https://api.doubao.com/v1")
        self.api_key = self.config.get("api_key")
        self.timeout = self.config.get("timeout", 60)
        
        self.client = httpx.AsyncClient(
            base_url=self.api_base,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            timeout=self.timeout
        )
    
    async def get_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> Dict[str, Any]:
        """获取完成响应"""
        request_data = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens"),
            "stream": False
        }
        
        response = await self.client.post("/chat/completions", json=request_data)
        response.raise_for_status()
        
        data = response.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {}),
            "finish_reason": data["choices"][0].get("finish_reason")
        }
    
    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式获取响应"""
        request_data = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens"),
            "stream": True
        }
        
        async with self.client.stream("POST", "/chat/completions", json=request_data) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    yield {"content": line[6:], "type": "text"}
    
    async def validate_model(self, model: str) -> bool:
        """验证模型是否可用"""
        try:
            response = await self.client.get(f"/models/{model}")
            return response.status_code == 200
        except:
            return False
    
    def get_capabilities(self) -> Dict[str, Any]:
        """获取插件能力"""
        return {
            "streaming": True,
            "function_calling": True,
            "image_input": False,
            "batch_processing": True,
            "context_window": 262144,
            "max_tokens": 4096
        }