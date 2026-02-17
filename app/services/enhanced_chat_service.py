# app/services/enhanced_chat_service.py
from typing import Dict, Any, Optional, List, AsyncGenerator
from uuid import UUID
from sqlalchemy.orm import Session
import aioredis

from app.services.chat_service import ChatService
from app.services.ai_code_service import AICodeGenerationService
from app.models.chat import ChatMessage
from app.schemas.chat import ChatMessage, StreamChunk

class EnhancedChatService(ChatService):
    """增强的聊天服务，支持代码生成"""
    
    def __init__(self, db: Session, redis: aioredis.Redis, code_generation_service: AICodeGenerationService):
        super().__init__(db, redis)
        self.code_gen_service = code_generation_service
    
    async def process_message(
        self,
        user_id: UUID,
        message: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """处理消息，包含代码生成检测"""
        # 检测是否是代码生成请求
        is_code_request, script_type = self.code_gen_service.detect_code_generation_intent(message)  # 修复：使用 message 而不是 content
        
        code_generation_metadata = None
        if is_code_request:
            # 创建代码生成元数据
            code_generation_metadata = {
                "detected": True,
                "script_type": script_type
            }
            
            # 使用代码生成优化的系统提示词
            if not kwargs.get("system_prompt"):
                kwargs["system_prompt"] = self._get_code_generation_system_prompt(script_type)
        
        # 从 kwargs 中移除 metadata（如果存在）
        metadata = kwargs.pop("metadata", None)
        
        # 调用父类方法处理消息
        result = await super().process_message(
            user_id=user_id,
            message=message,  # 修复：使用 message 而不是 content
            conversation_id=conversation_id,
            model=model,
            **kwargs
        )
        if code_generation_metadata:
            result["metadata"] = result.get("metadata", {})
            result["metadata"]["code_generation"] = code_generation_metadata
        
        # 如果是代码生成请求，进行后处理
        if is_code_request and result.get("content"):
            # 提取和保存代码
            code_result = await self.code_gen_service.code_service.process_ai_response_for_code(
                ai_response=result["content"],
                user_id=user_id,
                conversation_id=result["conversation_id"],
                auto_save=True
            )
            
            # 添加代码提取结果到响应
            result["code_extraction"] = code_result
            
            # 检查是否需要创建定时任务
            cron_expression = self.code_gen_service.extract_cron_expression(message)  # 修复：使用 message 而不是 content
            if cron_expression and code_result.get("has_code"):
                executable_codes = [
                    code for code in code_result["code_blocks"]
                    if code.get("valid") and code.get("saved")
                ]
                
                if executable_codes:
                    result["cron_suggestion"] = {
                        "code_id": executable_codes[0]["id"],
                        "cron_expression": cron_expression,
                        "human_readable": self.code_gen_service.parse_cron_to_human_readable(cron_expression),
                        "suggested_job_name": self.code_gen_service._generate_job_name(message)  # 修复：使用 message 而不是 content
                    }
            
            # 添加执行建议
            if code_result.get("has_code"):
                result["execution_suggestion"] = self._generate_execution_suggestion(code_result)
        
        return result
    
    async def process_message_with_code(
        self,
        user_id: str,
        content: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        extract_code: bool = True,
        auto_execute: bool = False,
        setup_cron: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """处理消息并自动处理代码相关功能"""
        
        # 首先处理消息
        result = await self.process_message(
            user_id=UUID(user_id),
            message=content,
            conversation_id=conversation_id,
            model=model,
            system_prompt=system_prompt,
            **kwargs
        )
        
        # 添加元数据
        result["metadata"] = result.get("metadata", {})
        
        # 如果启用了代码提取
        if extract_code and result.get("code_extraction"):
            code_extraction = result["code_extraction"]
            result["metadata"]["extracted_codes"] = code_extraction.get("code_blocks", [])
            
            # 如果启用了自动执行
            if auto_execute and code_extraction.get("has_code"):
                executions = []
                for code_block in code_extraction.get("code_blocks", []):
                    if code_block.get("saved") and code_block.get("valid"):
                        try:
                            # 执行代码
                            exec_result = await self.execute_saved_code(
                                user_id=user_id,
                                code_id=code_block["id"]
                            )
                            executions.append({
                                "code_id": code_block["id"],
                                "success": exec_result.get("success", False),
                                "output": exec_result.get("result", {}).get("output", ""),
                                "error": exec_result.get("error")
                            })
                        except Exception as e:
                            executions.append({
                                "code_id": code_block["id"],
                                "success": False,
                                "error": str(e)
                            })
                
                result["metadata"]["executions"] = executions
            
            # 如果启用了定时任务设置
            if setup_cron and result.get("cron_suggestion"):
                cron_suggestion = result["cron_suggestion"]
                try:
                    cron_result = await self.code_gen_service.setup_cron_job_from_code(
                        code_id=cron_suggestion["code_id"],
                        cron_expression=cron_suggestion["cron_expression"],
                        user_id=user_id,
                        job_name=cron_suggestion.get("suggested_job_name")
                    )
                    
                    result["metadata"]["cron_jobs"] = [{
                        "success": cron_result["success"],
                        "job_info": cron_result.get("cron_job", {}),
                        "error": cron_result.get("error")
                    }]
                except Exception as e:
                    result["metadata"]["cron_jobs"] = [{
                        "success": False,
                        "error": str(e)
                    }]
        
        # 添加后续建议
        result["follow_up_questions"] = self._generate_follow_up_questions(result)
        
        return result
    
    async def execute_saved_code(
            self,
            user_id: str,
            code_id: str,
            parameters: Optional[Dict[str, str]] = None,
            timeout: int = 30000
        ) -> Dict[str, Any]:
            """执行已保存的代码"""
            try:
                # 调用代码服务执行代码
                execution_result = await self.code_gen_service.code_service.execute_code(
                    code_id=code_id,  # 不需要转换为 UUID，让 code_service 处理
                    user_id=user_id,  # 不需要转换为 UUID，让 code_service 处理
                    env_vars=parameters or {},
                    timeout=timeout
                )
                
                # 格式化执行报告
                report = self._format_execution_report(execution_result)
                
                return {
                    "success": True,
                    "result": execution_result,
                    "report": report
                }
                
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "report": f"执行失败: {str(e)}"
                }


    async def stream_message(
        self,
        user_id: UUID,
        content: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式处理消息，支持代码生成"""
        # 检测代码生成意图
        is_code_request, script_type = self.code_gen_service.detect_code_generation_intent(content)
        
        if is_code_request:
            # 发送检测结果
            yield StreamChunk(
                content="",
                type="metadata",
                metadata={
                    "code_generation_detected": True,
                    "script_type": script_type
                }
            )
            
            # 更新系统提示词
            if not kwargs.get("system_prompt"):
                kwargs["system_prompt"] = self._get_code_generation_system_prompt(script_type)
        
        # 收集完整响应用于代码提取
        full_response = ""
        
        metadata = kwargs.pop("metadata", None)
        
        # 流式生成响应
        async for chunk in super().stream_message(
            user_id=user_id,
            message=content,
            conversation_id=conversation_id,
            model=model,
            **kwargs
        ):
            yield chunk
            
            # 收集文本内容
            if chunk.type == "text":
                full_response += chunk.content
            
            # 记录会话ID
            if chunk.type == "metadata" and chunk.metadata.get("conversation_id"):
                conversation_id = chunk.metadata["conversation_id"]
        
        # 处理代码提取（在流结束后）
        if is_code_request and full_response:
            # 提取代码
            code_result = await self.code_gen_service.code_service.process_ai_response_for_code(
                ai_response=full_response,
                user_id=user_id,
                conversation_id=conversation_id,
                auto_save=True
            )
            
            # 发送代码提取结果
            if code_result.get("has_code"):
                yield StreamChunk(
                    content="",
                    type="code_extraction",
                    metadata=code_result
                )
                
                # 检查定时任务建议
                cron_expression = self.code_gen_service.extract_cron_expression(content)
                if cron_expression:
                    executable_codes = [
                        code for code in code_result["code_blocks"]
                        if code.get("valid") and code.get("saved")
                    ]
                    
                    if executable_codes:
                        yield StreamChunk(
                            content="",
                            type="cron_suggestion",
                            metadata={
                                "code_id": executable_codes[0]["id"],
                                "cron_expression": cron_expression,
                                "human_readable": self.code_gen_service.parse_cron_to_human_readable(cron_expression),
                                "suggested_job_name": self.code_gen_service._generate_job_name(content)
                            }
                        )
    
    def _get_code_generation_system_prompt(self, script_type: str) -> str:
        """获取代码生成专用的系统提示词"""
        return f"""你是一个专业的 {script_type} 代码生成助手。你的任务是根据用户需求生成高质量、安全、可维护的代码。

生成代码时请遵循以下原则：
1. 代码必须完整可执行，包含所有必要的导入和依赖
2. 包含适当的错误处理和异常捕获
3. 添加清晰的注释说明代码功能
4. 使用安全的编码实践，避免潜在的安全风险
5. 包含使用说明和参数说明

请将生成的代码放在 ```{script_type} 代码块中。

对于 Python 脚本：
- 使用 #!/usr/bin/env python3 作为 shebang
- 包含 if __name__ == "__main__": 结构
- 使用 logging 模块记录日志
- 遵循 PEP 8 编码规范

对于 Bash 脚本：
- 使用 #!/bin/bash 作为 shebang
- 设置 set -euo pipefail 确保脚本安全
- 使用函数组织代码
- 包含错误处理和日志记录"""
    
    def _generate_execution_suggestion(self, code_result: Dict[str, Any]) -> Dict[str, Any]:
        """生成执行建议"""
        suggestions = []
        
        if code_result.get("executable_blocks", 0) > 0:
            suggestions.append("代码已保存，可以立即执行测试")
            
            # 获取第一个可执行代码
            for code in code_result.get("code_blocks", []):
                if code.get("valid") and code.get("saved"):
                    return {
                        "can_execute": True,
                        "code_id": code["id"],
                        "language": code["language"],
                        "suggestions": suggestions,
                        "test_command": f"执行代码: /exec {code['id']}"
                    }
        
        return {
            "can_execute": False,
            "suggestions": ["没有找到可执行的代码块"]
        }
    
    def _format_execution_report(self, execution_result: Dict[str, Any]) -> str:
        """格式化执行报告"""
        report_lines = []
        
        # 执行状态
        if execution_result.get("success"):
            report_lines.append("✅ 代码执行成功")
        else:
            report_lines.append("❌ 代码执行失败")
        
        # 执行时间
        if execution_result.get("execution_time"):
            report_lines.append(f"⏱️ 执行时间: {execution_result['execution_time']:.2f} 秒")
        
        # 输出
        if execution_result.get("output"):
            report_lines.append("\n📤 输出:")
            report_lines.append("```")
            # report_lines.append(execution_result["output"][:1000])  # 限制输出长度
            # if len(execution_result["output"]) > 1000:
            #     report_lines.append("... (输出已截断)")
            # report_lines.append("```")
            report_lines.append(execution_result["output"])
        
        if execution_result.get("error"):
            report_lines.append("\n❌ 错误信息:")
            report_lines.append("```")
            report_lines.append(execution_result["error"])
            report_lines.append("```")
        
        # 日志
        if execution_result.get("logs"):
            report_lines.append("\n📝 执行日志:")
            report_lines.append("```")
            report_lines.append(execution_result["logs"][:500])
            if len(execution_result["logs" ]) > 500:
                report_lines.append("... (日志已截断)")
            report_lines.append("```")
        
        return "\n".join(report_lines)
    
    def _generate_follow_up_questions(self, result: Dict[str, Any], *args, **kwargs) -> List[str]:
        """生成后续建议问题"""
        questions = []
        
        # 如果有代码提取
        if result.get("code_extraction", {}).get("has_code"):
            questions.append("需要我执行这段代码来测试吗？")
            
            # 如果没有定时任务但可能需要
            if not result.get("metadata", {}).get("cron_jobs"):
                questions.append("需要设置定时任务来定期运行这个脚本吗？")
            
            # 根据代码类型提供建议
            code_blocks = result.get("code_extraction", {}).get("code_blocks", [])
            if code_blocks:
                first_block = code_blocks[0]
                if first_block.get("language") == "python":
                    questions.append("需要添加更多的错误处理或日志记录吗？")
                elif first_block.get("language") == "bash":
                    questions.append("需要添加更多的系统兼容性检查吗？")
        
        # 如果没有代码但看起来像代码请求
        elif "脚本" in result.get("content", "") or "代码" in result.get("content", ""):
            questions.append("需要我帮您编写具体的代码实现吗？")
            questions.append("可以详细描述一下您的具体需求吗？")
        
        # 通用建议
        questions.extend([
            "还有其他功能需要添加吗？",
            "需要查看相关的代码模板吗？"
        ])
        
        return questions[:3]  # 只返回前3个建议


# 创建定时任务的辅助函数
async def create_cron_job_interactive(
    chat_service: EnhancedChatService,
    user_id: UUID,
    code_id: str,
    cron_expression: str,
    job_name: Optional[str] = None
) -> Dict[str, Any]:
    """交互式创建定时任务"""
    try:
        # 验证 cron 表达式
        human_readable = chat_service.code_gen_service.parse_cron_to_human_readable(cron_expression)
        
        # 创建定时任务
        result = await chat_service.code_gen_service.setup_cron_job_from_code(
            code_id=code_id,
            cron_expression=cron_expression,
            user_id=str(user_id),
            job_name=job_name
        )
        
        if result["success"]:
            return {
                "success": True,
                "message": f"定时任务已创建成功！\n任务名称: {result['cron_job']['job_name']}\n执行频率: {human_readable}\n下次执行: {result['cron_job']['next_run']}",
                "job_details": result["cron_job"]
            }
        else:
            return {
                "success": False,
                "message": f"创建定时任务失败: {result['error']}",
                "error": result["error"]
            }
            
    except Exception as e:
        return {
            "success": False,
            "message": f"创建定时任务时发生错误: {str(e)}",
            "error": str(e)
        }