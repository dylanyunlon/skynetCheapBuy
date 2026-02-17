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

# ============== 辅助函数：判断模型类型 ==============
def is_claude_model(model: str) -> bool:
    """判断是否为 Claude 模型"""
    claude_prefixes = ["claude-", "claude_"]
    model_lower = model.lower()
    return any(model_lower.startswith(prefix) for prefix in claude_prefixes)

def is_openai_model(model: str) -> bool:
    """判断是否为 OpenAI 模型"""
    openai_prefixes = ["gpt-", "gpt_", "o1-", "o1_", "o3-", "o3_"]
    model_lower = model.lower()
    return any(model_lower.startswith(prefix) for prefix in openai_prefixes)

def is_gemini_model(model: str) -> bool:
    """判断是否为 Gemini 模型"""
    return model.lower().startswith("gemini")


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
    """OpenAI提供商 - 用于 /v1/chat/completions 端点"""
    
    def __init__(self, api_key: str, api_base: Optional[str] = None):
        self.api_key = api_key
        self.api_base = api_base or "https://api.openai.com/v1"
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=60000.0,
            max_retries=0
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
            
            if max_tokens:
                request_params["max_tokens"] = max_tokens
            
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


class ClaudeCompatibleProvider(AIProvider):
    """
    Claude 兼容提供商 - 用于 /v1/messages 端点（原生 Claude 格式）
    通过 httpx 直接调用 tryallai.com 的 /v1/messages 端点
    """
    
    def __init__(self, api_key: str, api_base: Optional[str] = None):
        self.api_key = api_key
        # 将 base_url 从 /v1 改为根路径，然后我们手动添加 /v1/messages
        self.api_base = api_base or "https://api.tryallai.com"
        # 移除末尾的 /v1 如果存在
        if self.api_base.endswith("/v1"):
            self.api_base = self.api_base[:-3]
        elif self.api_base.endswith("/v1/"):
            self.api_base = self.api_base[:-4]
        
        self.messages_endpoint = f"{self.api_base}/v1/messages"
        
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
            # 从 messages 中提取 system 消息
            # 注意：agentic loop 传入的 messages 可能包含 content 为 list 的 block 格式
            # （tool_result / assistant tool_use），这些不需要拆分 system
            system_content = system_prompt
            claude_messages = []
            
            for msg in messages:
                if msg["role"] == "system":
                    # 合并所有 system 消息
                    if system_content:
                        system_content = system_content + "\n\n" + msg["content"]
                    else:
                        system_content = msg["content"]
                elif isinstance(msg.get("content"), list):
                    # Agentic loop 格式：content 是 block 数组
                    # （assistant 的 tool_use blocks 或 user 的 tool_result blocks）
                    claude_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
                else:
                    claude_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
            
            # 构建请求体（原生 Claude 格式）
            request_body = {
                "model": model,
                "messages": claude_messages,
                "max_tokens": max_tokens or 4096,
                "temperature": temperature
            }
            
            # 只有当 system 存在时才添加
            if system_content:
                request_body["system"] = system_content
            
            # ★ Agentic Loop 支持：传入 tools 定义
            if kwargs.get("tools"):
                request_body["tools"] = kwargs["tools"]
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "anthropic-version": "2023-06-01"
            }
            
            # Agentic loop 需要更长的超时（工具调用描述可能很长）
            timeout = 120.0 if kwargs.get("tools") else 60.0
            
            logger.info(f"Calling Claude Messages API with model: {model}, endpoint: {self.messages_endpoint}, tools: {bool(kwargs.get('tools'))}")
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self.messages_endpoint,
                    json=request_body,
                    headers=headers
                )
                
                if response.status_code != 200:
                    error_text = response.text
                    logger.error(f"Claude API error: {response.status_code} - {error_text}")
                    raise Exception(f"Claude API error: {response.status_code} - {error_text}")
                
                data = response.json()
                
                # ★ 增强解析：同时提取 text 和 tool_use blocks
                content_text = ""
                content_blocks = data.get("content", [])
                tool_uses = []
                
                for block in content_blocks:
                    if block.get("type") == "text":
                        content_text += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_uses.append(block)
                
                usage = {}
                if data.get("usage"):
                    usage = {
                        "prompt_tokens": data["usage"].get("input_tokens", 0),
                        "completion_tokens": data["usage"].get("output_tokens", 0),
                        "total_tokens": data["usage"].get("input_tokens", 0) + data["usage"].get("output_tokens", 0)
                    }
                
                return {
                    # 向后兼容：所有旧代码只读这个字段，不受影响
                    "content": content_text,
                    "usage": usage,
                    "finish_reason": data.get("stop_reason", "end_turn"),
                    "tool_calls": None,
                    # ★ Agentic Loop 新增字段
                    "content_blocks": content_blocks,   # 原始 content block 数组
                    "tool_uses": tool_uses,             # tool_use block 列表
                    "stop_reason": data.get("stop_reason", "end_turn"),
                }
                
        except httpx.TimeoutException:
            logger.error("Claude API timeout")
            raise Exception("Request timed out. Please try again.")
        except httpx.HTTPError as e:
            logger.error(f"Claude API HTTP error: {e}")
            raise Exception(f"HTTP error: {str(e)}")
        except Exception as e:
            logger.error(f"Claude API error: {e}")
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
            # 从 messages 中提取 system 消息
            system_content = system_prompt
            claude_messages = []
            
            for msg in messages:
                if msg["role"] == "system":
                    if system_content:
                        system_content = system_content + "\n\n" + msg["content"]
                    else:
                        system_content = msg["content"]
                else:
                    claude_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
            
            request_body = {
                "model": model,
                "messages": claude_messages,
                "max_tokens": kwargs.get("max_tokens", 4096),
                "temperature": temperature,
                "stream": True
            }
            
            if system_content:
                request_body["system"] = system_content
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "anthropic-version": "2023-06-01"
            }
            
            logger.info(f"Calling Claude Messages API (stream) with model: {model}")
            
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    self.messages_endpoint,
                    json=request_body,
                    headers=headers
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        logger.error(f"Claude stream error: {response.status_code} - {error_text}")
                        yield StreamChunk(
                            content=f"Error: {error_text.decode()}",
                            type="error",
                            metadata={"error": True, "status_code": response.status_code}
                        )
                        return
                    
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                event_type = data.get("type", "")
                                
                                if event_type == "content_block_delta":
                                    delta = data.get("delta", {})
                                    if delta.get("type") == "text_delta":
                                        text = delta.get("text", "")
                                        if text:
                                            yield StreamChunk(content=text, type="text")
                                            
                            except json.JSONDecodeError:
                                continue
                                
        except Exception as e:
            logger.error(f"Claude stream error: {e}")
            yield StreamChunk(
                content=f"Stream error: {str(e)}",
                type="error",
                metadata={"error": True}
            )


class AnthropicProvider(AIProvider):
    """Anthropic Claude提供商（原生 SDK）"""
    
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
    
    # 默认模型配置
    DEFAULT_MODEL = "claude-opus-4-5-20251101"
    BENCHMARK_MODEL = "claude-opus-4-5-20251101"  # 用于benchmark的默认模型
    
    def __init__(self, default_model: Optional[str] = None):
        self.providers: Dict[str, AIProvider] = {}
        self.default_model = default_model or self.DEFAULT_MODEL
        self._init_providers()
    
    def _init_providers(self):
        """初始化提供商"""
        if settings.OPENAI_API_KEY:
            self.providers["openai"] = OpenAIProvider(
                settings.OPENAI_API_KEY,
                settings.OPENAI_API_BASE
            )
        
        if settings.ANTHROPIC_API_KEY:
            # 使用 ClaudeCompatibleProvider 来处理 Claude 模型
            self.providers["anthropic"] = ClaudeCompatibleProvider(
                settings.OPENAI_API_KEY,  # 使用同一个 API key
                settings.OPENAI_API_BASE
            )
        
        if settings.GOOGLE_AI_API_KEY:
            self.providers["google"] = GoogleProvider(
                settings.GOOGLE_AI_API_KEY
            )
    
    def _get_provider(self, model: str, api_key: Optional[str] = None, api_url: Optional[str] = None) -> AIProvider:
        """根据模型获取提供商"""
        # 自定义API密钥
        if api_key:
            # 使用辅助函数判断模型类型
            if is_claude_model(model):
                # Claude 模型使用 /v1/messages 端点
                logger.info(f"Using ClaudeCompatibleProvider for model: {model}")
                return ClaudeCompatibleProvider(api_key, api_url)
            elif is_openai_model(model):
                # OpenAI 模型使用 /v1/chat/completions 端点
                logger.info(f"Using OpenAIProvider for model: {model}")
                return OpenAIProvider(api_key, api_url)
            elif is_gemini_model(model):
                return GoogleProvider(api_key)
            else:
                # 对于未知模型（如 Doubao），默认使用 OpenAI 兼容接口
                logger.info(f"Using OpenAI-compatible provider for unknown model: {model}")
                return OpenAIProvider(api_key, api_url)
        
        # 使用默认提供商
        if is_openai_model(model):
            provider = self.providers.get("openai")
        elif is_claude_model(model):
            provider = self.providers.get("anthropic")
        elif is_gemini_model(model):
            provider = self.providers.get("google")
        else:
            # 对于未知模型，尝试使用 OpenAI 提供商（兼容接口）
            provider = self.providers.get("openai")
        
        if not provider:
            raise ValueError(f"No provider available for model: {model}. Please check your API configuration.")
        
        return provider
    
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        简化的生成接口 - 用于Benchmark等场景
        
        Args:
            prompt: 用户提示词
            max_tokens: 最大生成token数
            temperature: 温度参数
            model: 使用的模型，默认使用BENCHMARK_MODEL
            system_prompt: 系统提示词
            **kwargs: 其他参数传递给get_completion
            
        Returns:
            包含content、usage等的字典
        """
        model = model or self.BENCHMARK_MODEL
        
        messages = [{"role": "user", "content": prompt}]
        
        try:
            result = await self.get_completion(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt,
                **kwargs
            )
            return result
        except Exception as e:
            logger.error(f"Generate error: {e}")
            # 返回错误但保持接口一致性
            return {
                "content": f"Error: {str(e)}",
                "usage": {"total_tokens": 0},
                "finish_reason": "error",
                "error": str(e)
            }
    
    async def generate_with_context(
        self,
        prompt: str,
        context: str,
        max_tokens: int = 4000,
        model: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        带上下文的生成接口 - 用于代码分析等场景
        
        Args:
            prompt: 用户提示词
            context: 上下文信息（如仓库结构、代码片段等）
            max_tokens: 最大生成token数
            model: 使用的模型
            **kwargs: 其他参数
            
        Returns:
            包含content、usage等的字典
        """
        full_prompt = f"""Context:
{context}

Task:
{prompt}"""
        
        return await self.generate(
            prompt=full_prompt,
            max_tokens=max_tokens,
            model=model,
            **kwargs
        )
    
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
                search_query = self._extract_search_query(messages[-1]["content"])
                if search_query:
                    yield StreamChunk(
                        content="",
                        type="search_stage",
                        metadata={"stage": "searching", "query": search_query}
                    )
                    
                    search_results = await self._perform_search(search_query)
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
        if "vision" in model or "gemini-pro-vision" in model:
            processed_messages = []
            for msg in messages:
                if isinstance(msg.get("content"), list):
                    processed_messages.append(msg)
                else:
                    content = msg["content"]
                    if "http" in content and any(ext in content for ext in [".jpg", ".png", ".webp"]):
                        processed_messages.append(msg)
                    else:
                        processed_messages.append(msg)
            return processed_messages
        
        return messages
    
    def _extract_search_query(self, content: str) -> Optional[str]:
        """从用户消息中提取搜索查询"""
        search_keywords = ["search for", "look up", "find information about", "搜索", "查找"]
        content_lower = content.lower()
        
        for keyword in search_keywords:
            if keyword in content_lower:
                start = content_lower.find(keyword) + len(keyword)
                query = content[start:].strip()
                query = query.rstrip(".,!?")
                return query
        
        return None
    
    async def _perform_search(self, query: str) -> str:
        """执行网络搜索"""
        return f"Search results for '{query}':\n1. Result 1\n2. Result 2\n3. Result 3"