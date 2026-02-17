import asyncio
import json
import re
from typing import AsyncGenerator, Dict, Any, Optional, List, Tuple
from uuid import UUID, uuid4
from datetime import datetime, timedelta
import redis.asyncio as aioredis
from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import WebSocket
import logging

# 修正导入路径
from app.models.chat import ChatSession, ChatMessage
from app.models.user import User
from app.core.ai_engine import AIEngine
from app.db.redis import get_redis
from app.schemas.chat import StreamChunk
from app.config import settings
from app.utils.markdown import escape_markdown, split_code, replace_all
from app.utils.file_handler import extract_file_content
from app.services.code_service import CodeService
from app.services.ai_code_service import AICodeGenerationService
from app.core.code_extractor import CodeExtractor


logger = logging.getLogger(__name__)

class ChatService:
    def __init__(self, db: Session, redis: aioredis.Redis):
        self.db = db
        self.redis = redis
        self.ai_engine = AIEngine()
        self.message_cache = {}  # 消息缓存
        self.typing_tasks = {}   # 输入状态任务
        self.code_service = CodeService(db)  # 传递 db 参数
        self.ai_code_service = AICodeGenerationService(self.ai_engine, self.code_service)
        
    async def process_message(
        self,
        user_id: UUID,
        message: str,
        model: Optional[str] = None,
        conversation_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        attachments: Optional[List[str]] = None,
        pass_history: Optional[int] = None
    ) -> Dict[str, Any]:
        """处理用户消息并返回AI响应"""
        
        # 获取用户配置
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("用户不存在")
        
        # 使用用户偏好的模型或传入的模型
        model = model or user.preferred_model or settings.DEFAULT_MODEL
        user_preferences = user.preferences or {}
        
        # 检测是否是代码生成请求
        is_code_generation, script_type = self.ai_code_service.detect_code_generation_intent(message)
        
        if is_code_generation:
            # 使用智能代码生成服务
            result = await self.ai_code_service.generate_code_with_ai(
                user_request=message,
                script_type=script_type,
                model=model,
                user_id=str(user_id),
                conversation_id=conversation_id,
                system_prompt=system_prompt
            )
            
            # 如果有 cron 表达式并且有可执行代码，自动设置定时任务
            if result.get("cron_ready") and user_preferences.get("auto_setup_cron", True):
                cron_result = await self.ai_code_service.setup_cron_job_from_code(
                    code_id=result["cron_ready"]["code_id"],
                    cron_expression=result["cron_ready"]["cron_expression"],
                    user_id=str(user_id),
                    job_name=result["cron_ready"]["suggested_job_name"]
                )
                
                # 添加 cron 设置结果到响应
                if cron_result["success"]:
                    cron_readable = self.ai_code_service.parse_cron_to_human_readable(
                        result["cron_ready"]["cron_expression"]
                    )
                    result["ai_response"] += f"\n\n✅ 定时任务已自动设置：{cron_readable}"
                    result["cron_setup"] = cron_result
            
            # 构建响应
            response = {
                "id": str(uuid4()),
                "conversation_id": conversation_id or str(uuid4()),
                "content": result["ai_response"],
                "model": model,
                "created_at": datetime.utcnow().isoformat(),
                "metadata": result.get("metadata", {}),
                "code_extraction": result.get("code_extraction"),
                "cron_setup": result.get("cron_setup")
            }
            
            return response
        
        # 如果不是代码生成请求，使用原有逻辑
        if self._is_code_generation_request(message):
            code_generation_prompt = self._get_code_generation_prompt()
            if system_prompt:
                system_prompt = f"{system_prompt}\n\n{code_generation_prompt}"
            else:
                system_prompt = code_generation_prompt

        # 获取历史记录传递数量
        if pass_history is None:
            pass_history = user.preferences.get("PASS_HISTORY", 3) if user.preferences else 3
        
        # 获取或创建会话
        if conversation_id:
            # 尝试将字符串转换为UUID
            try:
                conv_uuid = UUID(conversation_id)
                conversation = self._get_conversation(user_id, conv_uuid)
            except ValueError:
                # 如果不是有效的UUID，创建新会话
                conversation = None
                
            if not conversation:
                # 创建新会话
                conversation = self._create_conversation(user_id, model, system_prompt)
        else:
            conversation = self._create_conversation(user_id, model, system_prompt)
        
        # 处理附件
        if attachments:
            message = await self._process_attachments(attachments, message)
        
        # 保存用户消息
        user_message = ChatMessage(
            session_id=conversation.id,
            role="user",
            content=message,
            attachments=attachments or []
        )
        self.db.add(user_message)
        self.db.commit()
        
        # 获取历史消息
        history = self._get_conversation_history(
            conversation.id, 
            limit=pass_history if pass_history > 0 else 0
        )
        
        # 准备系统提示词
        if model and "claude" in model.lower():
            final_system_prompt = system_prompt or user.claude_system_prompt or ""
        else:
            final_system_prompt = system_prompt or user.system_prompt or ""
        
        # 获取启用的插件
        enabled_plugins = self._get_enabled_plugins(user)
        
        # 调用AI引擎
        ai_response = await self.ai_engine.get_completion(
            messages=history,
            model=model,
            system_prompt=final_system_prompt,
            temperature=0.7,  # 默认温度
            max_tokens=None,  # 使用模型默认值
            plugins=enabled_plugins,
            user_id=str(user_id),
            api_key=self._get_api_key(user, model),
            api_url=self._get_api_url(user, model)
        )
        
        # 保存AI响应
        assistant_message = ChatMessage(
            session_id=conversation.id,
            role="assistant",
            content=ai_response["content"],
            model=model,
            message_data={
                "tokens": ai_response.get("usage", {}),
                "finish_reason": ai_response.get("finish_reason")
            }
        )
        self.db.add(assistant_message)
        
        if user_preferences.get("auto_extract_code", True):
            try:
                code_result = await self.code_service.process_ai_response_for_code(
                    ai_response=ai_response["content"],
                    user_id=str(user_id),
                    conversation_id=str(conversation.id),
                    auto_save=user_preferences.get("auto_save_code", True)
                )
                # 如果有代码，添加到响应元数据
                if code_result["has_code"]:
                    if "metadata" not in ai_response:
                        ai_response["metadata"] = {}
                    ai_response["metadata"]["extracted_codes"] = code_result["code_blocks"]
                    
                    # 在响应内容后添加代码提取通知
                    if code_result["code_blocks"]:
                        saved_count = len([c for c in code_result["code_blocks"] if c.get("saved")])
                        if saved_count > 0:
                            ai_response["content"] += f"\n\n💾 已自动保存 {saved_count} 个可执行代码块。" 
            except Exception as e:
                logger.error(f"Code extraction failed: {e}")

        # 更新会话信息
        conversation.updated_at = datetime.utcnow()
        conversation.message_count = (conversation.message_count or 0) + 2
        if ai_response.get("usage", {}).get("total_tokens"):
            conversation.total_tokens = (conversation.total_tokens or 0) + ai_response["usage"]["total_tokens"]
        
        self.db.commit()
        
        # 生成响应
        response = {
            "id": str(assistant_message.id),
            "conversation_id": str(conversation.id),
            "content": ai_response["content"],
            "model": model,
            "created_at": assistant_message.created_at.isoformat(),
            "metadata": assistant_message.message_data or {},
            "usage": ai_response.get("usage", {})
        }

        # 如果启用了后续问题生成
        if user.preferences and user.preferences.get("FOLLOW_UP", True):
            follow_up_questions = await self._generate_follow_up_questions(
                ai_response["content"], 
                user.language or "en",
                model
            )
            if follow_up_questions:
                response["follow_up_questions"] = follow_up_questions

        logger.info(f"Returning response: {response}")
        return response

    
    async def stream_message(
        self,
        user_id: UUID,
        message: str,
        model: Optional[str] = None,
        conversation_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        attachments: Optional[List[str]] = None
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式处理消息"""
        
        # 获取用户和会话
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("用户不存在")
        
        model = model or user.preferred_model or settings.DEFAULT_MODEL
        
        # 检测是否是代码生成请求
        is_code_generation, script_type = self.ai_code_service.detect_code_generation_intent(message)
        
        if is_code_generation:
            # 对于代码生成请求，使用非流式处理（因为需要完整分析）
            result = await self.process_message(
                user_id=user_id,
                message=message,
                model=model,
                conversation_id=conversation_id,
                system_prompt=system_prompt,
                attachments=attachments
            )
            
            # 模拟流式输出
            yield StreamChunk(
                content=result["content"],
                type="text",
                metadata=result.get("metadata", {})
            )
            
            yield StreamChunk(
                content="",
                type="complete",
                metadata={
                    "final_content": result["content"],
                    "code_extraction": result.get("code_extraction"),
                    "cron_setup": result.get("cron_setup")
                }
            )
            return
        
        # 原有的流式处理逻辑
        if conversation_id:
            try:
                conv_uuid = UUID(conversation_id)
                conversation = self._get_conversation(user_id, conv_uuid)
            except ValueError:
                conversation = None
                
            if not conversation:
                conversation = self._create_conversation(user_id, model, system_prompt)
        else:
            conversation = self._create_conversation(user_id, model, system_prompt)
        
        # 处理附件
        if attachments:
            message = await self._process_attachments(attachments, message)
        
        # 保存用户消息
        user_message = ChatMessage(
            session_id=conversation.id,
            role="user",
            content=message,
            attachments=attachments or []
        )
        self.db.add(user_message)
        self.db.commit()
        
        # 获取历史和配置
        pass_history = user.preferences.get("PASS_HISTORY", 3) if user.preferences else 3
        history = self._get_conversation_history(
            conversation.id,
            limit=pass_history if pass_history > 0 else 0
        )
        
        # 系统提示词
        if model and "claude" in model.lower():
            final_system_prompt = system_prompt or user.claude_system_prompt or ""
        else:
            final_system_prompt = system_prompt or user.system_prompt or ""
        
        # 创建助手消息占位符
        assistant_message = ChatMessage(
            session_id=conversation.id,
            role="assistant",
            content="",
            model=model
        )
        self.db.add(assistant_message)
        self.db.commit()
        
        # 流式响应变量
        full_response = ""
        frequency_modification = self._get_frequency_modification(model, str(conversation.id))
        modify_time = 0
        
        try:
            # 发送开始输入状态
            yield StreamChunk(
                content="",
                type="typing_start",
                metadata={"message_id": str(assistant_message.id)}
            )
            
            # 流式获取AI响应
            async for chunk in self.ai_engine.stream_completion(
                messages=history,
                model=model,
                system_prompt=final_system_prompt,
                temperature=0.7,
                plugins=self._get_enabled_plugins(user),
                user_id=str(user_id),
                api_key=self._get_api_key(user, model),
                api_url=self._get_api_url(user, model)
            ):
                # 处理搜索阶段消息
                if chunk.type == "search_stage":
                    yield StreamChunk(
                        content=chunk.content,
                        type="stage",
                        metadata=chunk.metadata
                    )
                    continue
                
                full_response += chunk.content
                
                # 处理Markdown格式
                formatted_response = self._format_response(full_response, model)
                
                # 更新缓存
                await self._update_streaming_cache(
                    str(conversation.id),
                    str(assistant_message.id),
                    formatted_response
                )
                
                # 定期发送更新
                modify_time += 1
                if modify_time % frequency_modification == 0:
                    yield StreamChunk(
                        content=chunk.content,
                        type="text",
                        metadata={
                            "message_id": str(assistant_message.id),
                            "conversation_id": str(conversation.id),
                            "formatted": formatted_response
                        }
                    )
                else:
                    # 仅发送增量内容
                    yield StreamChunk(
                        content=chunk.content,
                        type="text_delta",
                        metadata={"message_id": str(assistant_message.id)}
                    )
            
            # 保存完整响应
            assistant_message.content = full_response
            assistant_message.message_data = {
                "model": model,
                "stream_completed": True
            }
            
            # 自动提取代码
            user_preferences = user.preferences or {}
            if user_preferences.get("auto_extract_code", True):
                try:
                    code_result = await self.code_service.process_ai_response_for_code(
                        ai_response=full_response,
                        user_id=str(user_id),
                        conversation_id=str(conversation.id),
                        auto_save=user_preferences.get("auto_save_code", True)
                    )
                    
                    if code_result["has_code"] and code_result["saved_blocks"] > 0:
                        notification = f"\n\n💾 已自动保存 {code_result['saved_blocks']} 个可执行代码块。"
                        assistant_message.content += notification
                        full_response += notification
                        
                        yield StreamChunk(
                            content=notification,
                            type="text",
                            metadata={"code_extraction": code_result}
                        )
                except Exception as e:
                    logger.error(f"Code extraction failed: {e}")
            
            conversation.updated_at = datetime.utcnow()
            conversation.message_count = (conversation.message_count or 0) + 2
            self.db.commit()
            
            # 发送完成信号
            yield StreamChunk(
                content="",
                type="complete",
                metadata={
                    "message_id": str(assistant_message.id),
                    "final_content": full_response
                }
            )
            
            # 清理缓存
            await self._clear_streaming_cache(str(conversation.id), str(assistant_message.id))
            
        except Exception as e:
            # 错误处理
            self.db.delete(assistant_message)
            self.db.commit()
            
            yield StreamChunk(
                content=str(e),
                type="error",
                metadata={"error": True, "message": str(e)}
            )
    
    # ... 其余方法保持不变 ...
    
    def _is_code_generation_request(self, message: str) -> bool:
        """检测是否是代码生成请求（旧方法，保留兼容性）"""
        keywords = ["写一个", "创建一个", "生成一个", "write a", "create a", "generate a", 
                   "脚本", "script", "代码", "code", "程序", "program"]
        return any(keyword in message.lower() for keyword in keywords)
    
    def _get_code_generation_prompt(self) -> str:
        """获取代码生成提示词"""
        return """When generating code, please:
1. Provide complete, executable code
2. Include proper error handling
3. Add helpful comments
4. Use safe coding practices
5. Include usage instructions

For Python scripts, use proper shebang and if __name__ == "__main__" structure.
For Bash scripts, use proper shebang and set -euo pipefail for safety."""
    
    # ... 其余辅助方法保持不变 ...
    
    async def reset_conversation(
        self,
        user_id: UUID,
        conversation_id: str,
        system_prompt: Optional[str] = None
    ):
        """重置会话"""
        try:
            conv_uuid = UUID(conversation_id)
        except ValueError:
            raise ValueError("无效的会话ID")
            
        conversation = self._get_conversation(user_id, conv_uuid)
        if not conversation:
            raise ValueError("会话不存在")
        
        # 删除所有消息
        self.db.query(ChatMessage).filter(
            ChatMessage.session_id == conversation.id
        ).delete()
        
        # 更新会话信息
        conversation.message_count = 0
        conversation.total_tokens = 0
        conversation.updated_at = datetime.utcnow()
        
        # 更新系统提示词
        if system_prompt:
            if not conversation.config:
                conversation.config = {}
            conversation.config["system_prompt"] = system_prompt
        
        self.db.commit()
        
    async def get_conversation_history(
        self,
        user_id: UUID,
        conversation_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """获取会话历史"""
        try:
            conv_uuid = UUID(conversation_id)
        except ValueError:
            raise ValueError("无效的会话ID")
            
        conversation = self._get_conversation(user_id, conv_uuid)
        if not conversation:
            raise ValueError("会话不存在")
        
        messages = self.db.query(ChatMessage).filter(
            and_(
                ChatMessage.session_id == conversation.id,
                ChatMessage.is_deleted == False
            )
        ).order_by(ChatMessage.created_at.desc()).offset(offset).limit(limit).all()
        
        return [
            {
                "id": str(msg.id),
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
                "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
                "attachments": msg.attachments,
                "metadata": msg.message_data,
                "model": msg.model
            }
            for msg in reversed(messages)
        ]
    
    async def delete_message(self, user_id: UUID, message_id: str):
        """删除消息"""
        try:
            msg_uuid = UUID(message_id)
        except ValueError:
            raise ValueError("无效的消息ID")
            
        message = self.db.query(ChatMessage).join(ChatSession).filter(
            and_(
                ChatMessage.id == msg_uuid,
                ChatSession.user_id == user_id
            )
        ).first()
        
        if not message:
            raise ValueError("消息不存在或无权删除")
        
        message.is_deleted = True
        message.deleted_at = datetime.utcnow()
        self.db.commit()
    
    async def edit_message(
        self,
        user_id: UUID,
        message_id: str,
        new_content: str
    ) -> Dict[str, Any]:
        """编辑消息"""
        try:
            msg_uuid = UUID(message_id)
        except ValueError:
            raise ValueError("无效的消息ID")
            
        message = self.db.query(ChatMessage).join(ChatSession).filter(
            and_(
                ChatMessage.id == msg_uuid,
                ChatSession.user_id == user_id
            )
        ).first()
        
        if not message:
            raise ValueError("消息不存在或无权编辑")
        
        message.content = new_content
        message.edited_at = datetime.utcnow()
        message.is_edited = True
        self.db.commit()
        
        return {
            "id": str(message.id),
            "content": message.content,
            "edited_at": message.edited_at.isoformat()
        }
    
    # 辅助方法
    def _get_conversation(self, user_id: UUID, conversation_id: UUID) -> Optional[ChatSession]:
        """获取会话"""
        return self.db.query(ChatSession).filter(
            and_(
                ChatSession.id == conversation_id,
                ChatSession.user_id == user_id,
                ChatSession.is_active == True
            )
        ).first()
    
    def _create_conversation(
        self,
        user_id: UUID,
        model: str,
        system_prompt: Optional[str] = None
    ) -> ChatSession:
        """创建新会话"""
        conversation = ChatSession(
            user_id=user_id,
            title=f"New Chat - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            config={
                "model": model,
                "system_prompt": system_prompt
            } if system_prompt else {"model": model}
        )
        self.db.add(conversation)
        self.db.commit()
        return conversation
    
    def _get_conversation_history(
        self,
        conversation_id: UUID,
        limit: int = 50
    ) -> List[Dict[str, str]]:
        """获取会话历史用于AI"""
        if limit == 0:
            return []
        
        messages = self.db.query(ChatMessage).filter(
            and_(
                ChatMessage.session_id == conversation_id,
                ChatMessage.is_deleted == False
            )
        ).order_by(ChatMessage.created_at.desc()).limit(limit).all()
        
        return [
            {"role": msg.role, "content": msg.content}
            for msg in reversed(messages)
        ]
    
    def _get_enabled_plugins(self, user: User) -> Dict[str, bool]:
        """获取用户启用的插件"""
        if not user.plugins:
            return {}
            
        # 检查系统是否支持该插件
        available_plugins = getattr(settings, 'AVAILABLE_PLUGINS', {})
        
        return {
            plugin: enabled
            for plugin, enabled in user.plugins.items()
            if enabled and available_plugins.get(plugin, False)
        }
    
    def _get_api_key(self, user: User, model: str) -> Optional[str]:
        """获取API密钥"""
        if not model:
            return None
            
        # 首先尝试用户自定义密钥
        provider = self._get_model_provider(model)
        if provider and user.api_keys and user.api_keys.get(provider):
            return user.api_keys[provider]
        
        # 使用系统默认密钥
        try:
            from app.config import get_api_key_for_model
            return get_api_key_for_model(model)
        except:
            return None
    
    def _get_api_url(self, user: User, model: str) -> Optional[str]:
        """获取API URL"""
        if not model:
            return None
            
        provider = self._get_model_provider(model)
        if provider and user.api_urls and user.api_urls.get(provider):
            return user.api_urls[provider]
        
        try:
            from app.config import get_api_base_for_model
            return get_api_base_for_model(model)
        except:
            return None
    
    def _get_model_provider(self, model: str) -> Optional[str]:
        """获取模型提供商"""
        if not model:
            return None
            
        model_lower = model.lower()
        if "gpt" in model_lower:
            return "openai"
        elif "claude" in model_lower:
            return "anthropic"
        elif "gemini" in model_lower:
            return "google"
        elif "doubao" in model_lower:
            return "doubao"
        else:
            return "custom"
    
    async def _process_attachments(
        self,
        attachment_ids: List[str],
        message: str
    ) -> str:
        """处理附件并将内容添加到消息中"""
        from app.models.file import File
        
        for file_id in attachment_ids:
            try:
                file_uuid = UUID(file_id)
                file = self.db.query(File).filter(File.id == file_uuid).first()
                if file and file.extracted_text:
                    message = f"{file.extracted_text}\n\n{message}"
            except ValueError:
                continue
        
        return message
    
    def _format_response(self, response: str, model: str) -> str:
        """格式化响应（处理Markdown等）"""
        # 处理未闭合的代码块
        if response.count("```") % 2 != 0:
            response += "\n```"
        
        # Claude特殊处理
        if model and "claude" in model.lower():
            response = self._claude_format(response)
        
        return response
    
    def _claude_format(self, text: str) -> str:
        """Claude响应格式化"""
        # 实现Claude特定的格式化逻辑
        return text
    
    def _get_frequency_modification(self, model: str, conversation_id: str) -> int:
        """获取更新频率"""
        if "gpt-4" in model.lower():
            return 25
        elif "gemini" in model.lower():
            return 1
        elif conversation_id.startswith("group_"):
            return 35
        else:
            return 20
    
    async def _generate_follow_up_questions(
        self,
        response: str,
        language: str,
        model: str
    ) -> List[str]:
        """生成后续问题"""
        prompt = (
            f"Based on the following response, generate 3 relevant follow-up questions "
            f"in {language}. Only output the questions, one per line.\n\n"
            f"Response: {response[:1000]}"
        )
        
        try:
            result = await self.ai_engine.get_completion(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                temperature=0.7,
                max_tokens=200
            )
            
            questions = result["content"].strip().split('\n')
            return [q.strip() for q in questions if q.strip()][:3]
        except:
            return []
    
    async def _update_streaming_cache(
        self,
        conversation_id: str,
        message_id: str,
        content: str
    ):
        """更新流式响应缓存"""
        key = f"stream:{conversation_id}:{message_id}"
        await self.redis.setex(key, 300, content)
    
    async def _clear_streaming_cache(
        self,
        conversation_id: str,
        message_id: str
    ):
        """清理流式响应缓存"""
        key = f"stream:{conversation_id}:{message_id}"
        await self.redis.delete(key)
    
    async def _clear_conversation_cache(self, conversation_id: str):
        """清理会话相关的所有缓存"""
        pattern = f"stream:{conversation_id}:*"
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern)
            if keys:
                await self.redis.delete(*keys)
            if cursor == 0:
                break


class WebSocketChatService(ChatService):
    """WebSocket聊天服务"""
    
    async def handle_websocket_message(
        self,
        websocket: WebSocket,
        user_id: UUID,
        message: Dict[str, Any]
    ):
        """处理WebSocket消息"""
        action = message.get("action")
        
        if action == "send_message":
            await self._handle_send_message(websocket, user_id, message)
        elif action == "edit_message":
            await self._handle_edit_message(websocket, user_id, message)
        elif action == "delete_message":
            await self._handle_delete_message(websocket, user_id, message)
        elif action == "typing":
            await self._handle_typing_indicator(websocket, user_id, message)
    
    async def _handle_send_message(
        self,
        websocket: WebSocket,
        user_id: UUID,
        message: Dict[str, Any]
    ):
        """处理发送消息"""
        conversation_id = message.get("conversation_id")
        content = message.get("content")
        model = message.get("model")
        
        # 发送"正在输入"状态
        await websocket.send_json({
            "type": "typing",
            "data": {"status": "start"}
        })
        
        try:
            # 流式处理消息
            async for chunk in self.stream_message(
                user_id=user_id,
                message=content,
                model=model,
                conversation_id=conversation_id
            ):
                await websocket.send_json({
                    "type": "stream",
                    "data": {
                        "content": chunk.content,
                        "chunk_type": chunk.type,
                        "metadata": chunk.metadata
                    }
                })
            
            # 发送完成信号
            await websocket.send_json({
                "type": "complete",
                "data": {"status": "success"}
            })
            
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "data": {"error": str(e)}
            })
        finally:
            # 停止"正在输入"状态
            await websocket.send_json({
                "type": "typing",
                "data": {"status": "stop"}
            })
    
    async def _handle_edit_message(
        self,
        websocket: WebSocket,
        user_id: UUID,
        message: Dict[str, Any]
    ):
        """处理编辑消息"""
        message_id = message.get("message_id")
        new_content = message.get("content")
        
        try:
            updated_message = await self.edit_message(
                user_id=user_id,
                message_id=message_id,
                new_content=new_content
            )
            
            await websocket.send_json({
                "type": "message_edited",
                "data": updated_message
            })
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "data": {"error": str(e)}
            })
    
    async def _handle_delete_message(
        self,
        websocket: WebSocket,
        user_id: UUID,
        message: Dict[str, Any]
    ):
        """处理删除消息"""
        message_id = message.get("message_id")
        
        try:
            await self.delete_message(user_id, message_id)
            
            await websocket.send_json({
                "type": "message_deleted",
                "data": {"message_id": message_id}
            })
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "data": {"error": str(e)}
            })
    
    async def _handle_typing_indicator(
        self,
        websocket: WebSocket,
        user_id: UUID,
        message: Dict[str, Any]
    ):
        """处理输入指示器"""
        conversation_id = message.get("conversation_id")
        is_typing = message.get("is_typing", False)
        
        # 广播给会话中的其他用户（如果是群聊）
        # 这里简化处理，只回显给发送者
        await websocket.send_json({
            "type": "typing_indicator",
            "data": {
                "user_id": str(user_id),
                "conversation_id": conversation_id,
                "is_typing": is_typing
            }
        })
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        return self.db.query(User).filter(User.username == username).first()