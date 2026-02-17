import asyncio
import json
from typing import AsyncGenerator, Dict, Any, List, Optional, Union
from abc import ABC, abstractmethod
import httpx
import openai
from anthropic import AsyncAnthropic
import google.generativeai as genai
import logging

from app.config import settings
from app.schemas.chat import StreamChunk

logger = logging.getLogger(__name__)

class AIProvider(ABC):
    """AI提供商基类"""
    
    @abstractmethod
    async def get_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        pass

class OpenAIProvider(AIProvider):
    """OpenAI提供商"""
    
    def __init__(self, api_key: str, api_base: Optional[str] = None):
        self.api_key = api_key
        self.api_base = api_base or "https://api.openai.com/v1"
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=60.0,  # 增加超时时间
            max_retries=3   # 设置重试次数
        )
    
    async def get_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        try:
            # 添加系统提示词
            if system_prompt:
                messages = [{"role": "system", "content": system_prompt}] + messages
            
            # 处理函数调用
            tools = None
            if kwargs.get("plugins"):
                tools = self._build_tools(kwargs["plugins"])
            
            # 创建请求参数
            request_params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": False
            }
            
            # 只有当 max_tokens 有值时才添加
            if max_tokens:
                request_params["max_tokens"] = max_tokens
            
            # 只有当有工具时才添加
            if tools:
                request_params["tools"] = tools
            
            logger.info(f"Calling OpenAI API with model: {model}, base_url: {self.api_base}")
            
            response = await self.client.chat.completions.create(**request_params)
            
            return {
                "content": response.choices[0].message.content or "",
                "usage": response.usage.dict() if response.usage else {},
                "finish_reason": response.choices[0].finish_reason,
                "tool_calls": getattr(response.choices[0].message, 'tool_calls', None)
            }
            
        except openai.APIStatusError as e:
            logger.error(f"OpenAI API status error: {e.status_code} - {e.message}")
            if e.status_code == 503:
                raise Exception("AI service is temporarily unavailable. Please try again later.")
            elif e.status_code == 401:
                raise Exception("Invalid API key or authentication failed.")
            elif e.status_code == 429:
                raise Exception("Rate limit exceeded. Please try again later.")
            else:
                raise Exception(f"API error: {e.message}")
                
        except openai.APIConnectionError as e:
            logger.error(f"OpenAI API connection error: {e}")
            raise Exception("Failed to connect to AI service. Please check your network connection.")
            
        except openai.APITimeoutError as e:
            logger.error(f"OpenAI API timeout error: {e}")
            raise Exception("Request timed out. Please try again.")
            
        except Exception as e:
            logger.error(f"Unexpected error in OpenAI provider: {e}")
            raise Exception(f"An unexpected error occurred: {str(e)}")
    
    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        try:
            if system_prompt:
                messages = [{"role": "system", "content": system_prompt}] + messages
            
            tools = None
            if kwargs.get("plugins"):
                tools = self._build_tools(kwargs["plugins"])
            
            request_params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": True
            }
            
            if tools:
                request_params["tools"] = tools
            
            stream = await self.client.chat.completions.create(**request_params)
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield StreamChunk(
                        content=chunk.choices[0].delta.content,
                        type="text"
                    )
                
                # 处理工具调用
                if hasattr(chunk.choices[0].delta, 'tool_calls') and chunk.choices[0].delta.tool_calls:
                    for tool_call in chunk.choices[0].delta.tool_calls:
                        yield StreamChunk(
                            content="",
                            type="tool_call",
                            metadata={
                                "tool_name": tool_call.function.name,
                                "arguments": tool_call.function.arguments
                            }
                        )
                        
        except openai.APIStatusError as e:
            logger.error(f"OpenAI API stream status error: {e.status_code} - {e.message}")
            yield StreamChunk(
                content=f"Error: {e.message}",
                type="error",
                metadata={"error": True, "status_code": e.status_code}
            )
            
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield StreamChunk(
                content=f"Stream error: {str(e)}",
                type="error",
                metadata={"error": True}
            )
    
    def _build_tools(self, plugins: Dict[str, bool]) -> List[Dict[str, Any]]:
        """构建工具列表"""
        tools = []
        
        if plugins.get("search"):
            tools.append({
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web for information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query"
                            }
                        },
                        "required": ["query"]
                    }
                }
            })
        
        if plugins.get("generate_image"):
            tools.append({
                "type": "function",
                "function": {
                    "name": "generate_image",
                    "description": "Generate an image based on a description",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "description": "The image description"
                            }
                        },
                        "required": ["prompt"]
                    }
                }
            })
        
        return tools

class AnthropicProvider(AIProvider):
    """Anthropic Claude提供商"""
    
    def __init__(self, api_key: str):
        self.client = AsyncAnthropic(api_key=api_key)
    
    async def get_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        try:
            # Claude格式转换
            claude_messages = self._convert_messages(messages)
            
            response = await self.client.messages.create(
                model=model,
                messages=claude_messages,
                system=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens or 4096
            )
            
            return {
                "content": response.content[0].text,
                "usage": {
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens
                },
                "finish_reason": response.stop_reason
            }
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise Exception(f"Claude API error: {str(e)}")
    
    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        try:
            claude_messages = self._convert_messages(messages)
            
            async with self.client.messages.stream(
                model=model,
                messages=claude_messages,
                system=system_prompt,
                temperature=temperature,
                max_tokens=4096
            ) as stream:
                async for text in stream.text_stream:
                    yield StreamChunk(content=text, type="text")
        except Exception as e:
            logger.error(f"Anthropic stream error: {e}")
            yield StreamChunk(
                content=f"Claude stream error: {str(e)}",
                type="error",
                metadata={"error": True}
            )
    
    def _convert_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """转换消息格式以适应Claude API"""
        # Claude不支持system角色在messages中
        return [
            msg for msg in messages
            if msg["role"] != "system"
        ]

class GoogleProvider(AIProvider):
    """Google Gemini提供商"""
    
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
    
    async def get_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        try:
            # 创建模型实例
            gemini_model = genai.GenerativeModel(
                model_name=model,
                system_instruction=system_prompt
            )
            
            # 转换消息格式
            chat = gemini_model.start_chat(history=self._convert_to_gemini_format(messages[:-1]))
            
            # 发送最后一条消息
            response = await chat.send_message_async(
                messages[-1]["content"],
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": kwargs.get("max_tokens")
                }
            )
            
            return {
                "content": response.text,
                "usage": {
                    "prompt_tokens": response.usage_metadata.prompt_token_count,
                    "completion_tokens": response.usage_metadata.candidates_token_count,
                    "total_tokens": response.usage_metadata.total_token_count
                },
                "finish_reason": response.candidates[0].finish_reason.name
            }
        except Exception as e:
            logger.error(f"Google AI error: {e}")
            raise Exception(f"Gemini API error: {str(e)}")
    
    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        try:
            gemini_model = genai.GenerativeModel(
                model_name=model,
                system_instruction=system_prompt
            )
            
            chat = gemini_model.start_chat(history=self._convert_to_gemini_format(messages[:-1]))
            
            response = await chat.send_message_async(
                messages[-1]["content"],
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": kwargs.get("max_tokens")
                },
                stream=True
            )
            
            async for chunk in response:
                if chunk.text:
                    yield StreamChunk(content=chunk.text, type="text")
        except Exception as e:
            logger.error(f"Google stream error: {e}")
            yield StreamChunk(
                content=f"Gemini stream error: {str(e)}",
                type="error",
                metadata={"error": True}
            )
    
    def _convert_to_gemini_format(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """转换为Gemini格式"""
        history = []
        for msg in messages:
            if msg["role"] == "user":
                history.append({"role": "user", "parts": [msg["content"]]})
            elif msg["role"] == "assistant":
                history.append({"role": "model", "parts": [msg["content"]]})
        return history

class AIEngine:
    """AI引擎主类"""
    
    def __init__(self):
        self.providers: Dict[str, AIProvider] = {}
        self._init_providers()
    
    def _init_providers(self):
        """初始化提供商"""
        if settings.OPENAI_API_KEY:
            self.providers["openai"] = OpenAIProvider(
                settings.OPENAI_API_KEY,
                settings.OPENAI_API_BASE
            )
        
        if settings.ANTHROPIC_API_KEY:
            self.providers["anthropic"] = AnthropicProvider(
                settings.ANTHROPIC_API_KEY
            )
        
        if settings.GOOGLE_AI_API_KEY:
            self.providers["google"] = GoogleProvider(
                settings.GOOGLE_AI_API_KEY
            )
    
    def _get_provider(self, model: str, api_key: Optional[str] = None, api_url: Optional[str] = None) -> AIProvider:
        """根据模型获取提供商"""
        # 自定义API密钥
        if api_key:
            # 检查是否是已知的模型前缀
            if model.startswith("gpt") or model.startswith("o1"):
                return OpenAIProvider(api_key, api_url)
            elif model.startswith("claude"):
                return AnthropicProvider(api_key)
            elif model.startswith("gemini"):
                return GoogleProvider(api_key)
            else:
                # 对于未知模型（如 Doubao），默认使用 OpenAI 兼容接口
                logger.info(f"Using OpenAI-compatible provider for model: {model}")
                return OpenAIProvider(api_key, api_url)
        
        # 使用默认提供商
        if model.startswith("gpt") or model.startswith("o1"):
            provider = self.providers.get("openai")
        elif model.startswith("claude"):
            provider = self.providers.get("anthropic")
        elif model.startswith("gemini"):
            provider = self.providers.get("google")
        else:
            # 对于未知模型，尝试使用 OpenAI 提供商（兼容接口）
            provider = self.providers.get("openai")
        
        if not provider:
            raise ValueError(f"No provider available for model: {model}. Please check your API configuration.")
        
        return provider
    
    async def get_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> Dict[str, Any]:
        """获取AI完成响应"""
        try:
            provider = self._get_provider(
                model,
                kwargs.get("api_key"),
                kwargs.get("api_url")
            )
            
            # 处理图像消息
            messages = await self._process_image_messages(messages, model)
            
            return await provider.get_completion(messages, model, **kwargs)
            
        except Exception as e:
            logger.error(f"AI Engine error for model {model}: {e}")
            raise
    
    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式获取AI响应"""
        try:
            provider = self._get_provider(
                model,
                kwargs.get("api_key"),
                kwargs.get("api_url")
            )
            
            # 处理图像消息
            messages = await self._process_image_messages(messages, model)
            
            # 如果启用了插件，先进行搜索等操作
            if kwargs.get("plugins", {}).get("search"):
                # 提取搜索查询
                search_query = self._extract_search_query(messages[-1]["content"])
                if search_query:
                    yield StreamChunk(
                        content="",
                        type="search_stage",
                        metadata={"stage": "searching", "query": search_query}
                    )
                    
                    # 执行搜索
                    search_results = await self._perform_search(search_query)
                    
                    # 将搜索结果添加到上下文
                    messages[-1]["content"] += f"\n\nSearch results:\n{search_results}"
            
            # 流式生成响应
            async for chunk in provider.stream_completion(messages, model, **kwargs):
                yield chunk
                
        except Exception as e:
            logger.error(f"Stream error for model {model}: {e}")
            yield StreamChunk(
                content=f"Error: {str(e)}",
                type="error",
                metadata={"error": True}
            )
    
    async def _process_image_messages(
        self,
        messages: List[Dict[str, str]],
        model: str
    ) -> List[Dict[str, str]]:
        """处理包含图像的消息"""
        # 如果模型支持图像，转换消息格式
        if "vision" in model or "gemini-pro-vision" in model:
            processed_messages = []
            for msg in messages:
                if isinstance(msg.get("content"), list):
                    # 已经是多模态格式
                    processed_messages.append(msg)
                else:
                    # 检查是否包含图像URL
                    content = msg["content"]
                    if "http" in content and any(ext in content for ext in [".jpg", ".png", ".webp"]):
                        # 提取图像URL并构建多模态消息
                        # 这里简化处理，实际应该更复杂
                        processed_messages.append(msg)
                    else:
                        processed_messages.append(msg)
            return processed_messages
        
        return messages
    
    def _extract_search_query(self, content: str) -> Optional[str]:
        """从用户消息中提取搜索查询"""
        # 简单的关键词匹配，实际应该更智能
        search_keywords = ["search for", "look up", "find information about", "搜索", "查找"]
        content_lower = content.lower()
        
        for keyword in search_keywords:
            if keyword in content_lower:
                # 提取关键词后的内容作为查询
                start = content_lower.find(keyword) + len(keyword)
                query = content[start:].strip()
                # 移除标点符号
                query = query.rstrip(".,!?")
                return query
        
        return None
    
    async def _perform_search(self, query: str) -> str:
        """执行网络搜索"""
        # 这里应该实现实际的搜索功能
        # 可以使用搜索API如Google Search API、Bing API等
        # 简化示例
        return f"Search results for '{query}':\n1. Result 1\n2. Result 2\n3. Result 3"