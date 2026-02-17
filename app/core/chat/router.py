# app/core/chat/router.py
from typing import Dict, Any, AsyncGenerator, List, Optional
from dataclasses import dataclass
import logging
from uuid import UUID
import json

from app.core.intent.engine import Intent, IntentType
from app.schemas.v2.chat import ChatMessageRequest, ChatMessageResponse, ProjectOperation, CodeGeneration
from app.models.user import User
from app.services.chat_service import ChatService
from app.core.ai_engine import AIEngine

logger = logging.getLogger(__name__)

@dataclass
class ChatResult:
    response: ChatMessageResponse
    background_tasks: List[Dict[str, Any]]

@dataclass
class StreamChunk:
    event_type: str
    data: Dict[str, Any]

class ChatRouter:
    """智能对话路由器 - 核心统一处理逻辑"""
    
    def __init__(
        self,
        chat_service: ChatService,
        ai_engine: AIEngine
    ):
        self.chat_service = chat_service
        self.ai_engine = ai_engine
        
        # 注册处理器
        self.handlers = {
            IntentType.PROJECT_CREATE: self._handle_project_creation,
            IntentType.PROJECT_MODIFY: self._handle_project_modification,
            IntentType.CODE_GENERATION: self._handle_code_generation,
            IntentType.FILE_OPERATION: self._handle_file_operation,
            IntentType.PROJECT_EXECUTION: self._handle_project_execution,
            IntentType.CODE_EXECUTION: self._handle_code_execution,
            IntentType.CRON_SETUP: self._handle_cron_setup,
            IntentType.GENERAL_CHAT: self._handle_general_chat,
        }
    
    async def route_and_process(
        self,
        request: ChatMessageRequest,
        intent: Intent,
        context: Dict[str, Any],
        user: User
    ) -> ChatResult:
        """路由并处理请求"""
        
        logger.info(f"Processing intent: {intent.type.value} for user: {user.username}")
        
        handler = self.handlers.get(intent.type, self._handle_general_chat)
        
        try:
            result = await handler(request, intent, context, user)
            logger.info(f"Successfully processed intent: {intent.type.value}")
            return result
        except Exception as e:
            logger.error(f"Error processing intent {intent.type.value}: {e}", exc_info=True)
            # 降级到普通聊天
            return await self._handle_general_chat(request, intent, context, user)
    
    async def stream_process(
        self,
        request: ChatMessageRequest,
        user: User
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式处理 - 复用现有的流式逻辑"""
        
        # 使用现有的流式聊天服务
        async for chunk in self.chat_service.stream_message(
            user_id=user.id,
            message=request.message,
            model=request.model,
            conversation_id=request.conversation_id,
            system_prompt=request.system_prompt,
            attachments=request.attachments
        ):
            yield StreamChunk(
                event_type=chunk.type,
                data={
                    "content": chunk.content,
                    "metadata": chunk.metadata or {}
                }
            )
    
    # 意图处理器实现
    async def _handle_project_creation(
        self,
        request: ChatMessageRequest,
        intent: Intent,
        context: Dict[str, Any],
        user: User
    ) -> ChatResult:
        """处理项目创建"""
        
        # 1. 分析项目需求
        project_spec = await self._analyze_project_requirements(
            request.message, intent.entities
        )
        
        # 2. 生成项目建议和计划
        ai_prompt = f"""
        用户想要创建一个项目：{request.message}
        
        项目需求分析：
        - 项目类型：{project_spec.get('project_type', '未指定')}
        - 技术栈：{project_spec.get('technologies', [])}
        - 项目名称：{project_spec.get('project_name', '未指定')}
        
        请为用户生成：
        1. 详细的项目结构建议
        2. 技术栈选择说明
        3. 实现步骤规划
        4. 预计的文件列表
        
        请用友好的语调回应，并询问用户是否要立即创建这个项目。
        """
        
        ai_response = await self.ai_engine.get_completion(
            messages=[{"role": "user", "content": ai_prompt}],
            model=request.model or user.preferred_model,
            system_prompt=request.system_prompt,
            user_id=str(user.id),
            api_key=self._get_api_key(user, request.model),
            api_url=self._get_api_url(user, request.model)
        )
        
        # 3. 构建响应
        response_content = ai_response["content"]
        
        # 添加项目创建建议
        if project_spec:
            response_content += f"\n\n📋 **项目创建建议**\n"
            response_content += f"- 项目类型：{project_spec.get('project_type', '通用项目')}\n"
            response_content += f"- 推荐技术栈：{', '.join(project_spec.get('technologies', ['Python']))}\n"
            if project_spec.get('project_name'):
                response_content += f"- 建议名称：{project_spec['project_name']}\n"
        
        suggestions = ["立即创建项目", "修改项目配置", "选择其他模板", "继续讨论需求"]
        
        return ChatResult(
            response=ChatMessageResponse(
                message_id=str(UUID.uuid4()),
                conversation_id=request.conversation_id or str(UUID.uuid4()),
                content=response_content,
                intent_detected=intent.type.value,
                suggestions=suggestions,
                project_suggestion=project_spec,
                processing_time_ms=100  # 示例值
            ),
            background_tasks=[]
        )
    
    async def _handle_code_generation(
        self,
        request: ChatMessageRequest,
        intent: Intent,
        context: Dict[str, Any],
        user: User
    ) -> ChatResult:
        """处理代码生成 - 复用现有逻辑"""
        
        # 使用现有的代码生成服务
        response = await self.chat_service.process_message(
            user_id=user.id,
            message=request.message,
            model=request.model,
            conversation_id=request.conversation_id,
            system_prompt=request.system_prompt,
            attachments=request.attachments
        )
        
        # 转换为新的响应格式
        suggestions = ["运行代码", "修改代码", "保存到项目"]
        if context.get("project_id"):
            suggestions.extend(["添加到项目", "查看项目结构"])
        
        code_generations = []
        if response.get("code_extraction"):
            for code_block in response["code_extraction"].get("code_blocks", []):
                code_generations.append(CodeGeneration(
                    language=code_block.get("language", "text"),
                    code=code_block.get("code", ""),
                    file_path=code_block.get("file_path"),
                    description=code_block.get("description")
                ))
        
        return ChatResult(
            response=ChatMessageResponse(
                message_id=response["id"],
                conversation_id=response["conversation_id"],
                content=response["content"],
                intent_detected=intent.type.value,
                suggestions=suggestions,
                code_generations=code_generations,
                processing_time_ms=response.get("processing_time_ms", 100)
            ),
            background_tasks=[]
        )
    
    async def _handle_code_execution(
        self,
        request: ChatMessageRequest,
        intent: Intent,
        context: Dict[str, Any],
        user: User
    ) -> ChatResult:
        """处理代码执行"""
        
        # 检查是否有项目上下文
        if context.get("project_id"):
            # 执行项目
            return await self._handle_project_execution(request, intent, context, user)
        
        # 如果没有具体的代码要执行，询问用户
        response_content = """
        🤔 我注意到您想要执行代码，但需要更多信息：
        
        **请告诉我：**
        1. 您要执行什么代码？
        2. 是执行现有项目还是单独的脚本？
        3. 需要什么参数或输入？
        
        **我可以帮您：**
        - 运行Python脚本
        - 执行项目代码
        - 设置定时任务
        - 调试错误
        """
        
        return ChatResult(
            response=ChatMessageResponse(
                message_id=str(UUID.uuid4()),
                conversation_id=request.conversation_id or str(UUID.uuid4()),
                content=response_content,
                intent_detected=intent.type.value,
                suggestions=["查看最近的代码", "选择执行项目", "上传代码文件", "生成测试代码"],
                processing_time_ms=50
            ),
            background_tasks=[]
        )
    
    async def _handle_project_execution(
        self,
        request: ChatMessageRequest,
        intent: Intent,
        context: Dict[str, Any],
        user: User
    ) -> ChatResult:
        """处理项目执行"""
        
        project_id = context.get("project_id")
        if not project_id:
            return await self._handle_code_execution(request, intent, context, user)
        
        # 模拟项目执行逻辑（需要集成工作空间管理器）
        response_content = f"""
        🚀 **正在执行项目** (ID: {project_id})
        
        **执行状态：** 准备中...
        
        **注意：** 实际的项目执行功能需要工作空间管理器的支持。
        当前这是一个模拟响应。
        
        **下一步：**
        1. 检查项目文件
        2. 安装依赖
        3. 运行入口文件
        4. 显示输出结果
        """
        
        suggestions = ["查看输出", "停止执行", "查看日志", "调试错误", "重新运行"]
        
        # 这里应该调用实际的工作空间管理器
        execution_result = {
            "status": "simulated",
            "project_id": project_id,
            "message": "This is a simulated execution result"
        }
        
        return ChatResult(
            response=ChatMessageResponse(
                message_id=str(UUID.uuid4()),
                conversation_id=request.conversation_id or str(UUID.uuid4()),
                content=response_content,
                intent_detected=intent.type.value,
                suggestions=suggestions,
                execution_result=execution_result,
                processing_time_ms=200
            ),
            background_tasks=[]
        )
    
    async def _handle_cron_setup(
        self,
        request: ChatMessageRequest,
        intent: Intent,
        context: Dict[str, Any],
        user: User
    ) -> ChatResult:
        """处理定时任务设置"""
        
        entities = intent.entities
        frequency = entities.get("frequency", "未指定")
        time_spec = entities.get("time", "未指定")
        
        response_content = f"""
        ⏰ **定时任务设置**
        
        根据您的需求分析：
        - 执行频率：{frequency}
        - 执行时间：{time_spec}
        
        **设置步骤：**
        1. 确认要执行的代码或项目
        2. 设置执行时间
        3. 配置执行环境
        4. 启动定时任务
        
        **示例设置：**
        - 每天上午9点执行：`0 9 * * *`
        - 每小时执行一次：`0 * * * *`
        - 每5分钟执行：`*/5 * * * *`
        
        请告诉我具体要执行什么代码，我来帮您设置定时任务。
        """
        
        suggestions = ["选择现有代码", "设置执行时间", "测试运行", "查看任务列表"]
        
        return ChatResult(
            response=ChatMessageResponse(
                message_id=str(UUID.uuid4()),
                conversation_id=request.conversation_id or str(UUID.uuid4()),
                content=response_content,
                intent_detected=intent.type.value,
                suggestions=suggestions,
                processing_time_ms=100
            ),
            background_tasks=[]
        )
    
    async def _handle_file_operation(
        self,
        request: ChatMessageRequest,
        intent: Intent,
        context: Dict[str, Any],
        user: User
    ) -> ChatResult:
        """处理文件操作"""
        
        entities = intent.entities
        file_path = entities.get("file_path", "未指定")
        operation = entities.get("operation", "未知")
        
        response_content = f"""
        📁 **文件操作**
        
        **检测到的操作：**
        - 文件：{file_path}
        - 操作：{operation}
        
        **我可以帮您：**
        - 创建新文件
        - 编辑现有文件
        - 查看文件内容
        - 删除文件
        - 重命名文件
        
        请告诉我具体要对哪个文件进行什么操作。
        """
        
        if context.get("project_id"):
            response_content += f"\n**当前项目：** {context['project_id']}"
            suggestions = ["查看项目文件", "创建新文件", "编辑配置", "删除文件"]
        else:
            suggestions = ["创建文件", "上传文件", "查看文件", "创建项目"]
        
        file_operations = []
        if file_path != "未指定":
            file_operations.append({
                "operation": operation,
                "file_path": file_path,
                "status": "pending"
            })
        
        return ChatResult(
            response=ChatMessageResponse(
                message_id=str(UUID.uuid4()),
                conversation_id=request.conversation_id or str(UUID.uuid4()),
                content=response_content,
                intent_detected=intent.type.value,
                suggestions=suggestions,
                file_operations=file_operations,
                processing_time_ms=80
            ),
            background_tasks=[]
        )
    
    async def _handle_project_modification(
        self,
        request: ChatMessageRequest,
        intent: Intent,
        context: Dict[str, Any],
        user: User
    ) -> ChatResult:
        """处理项目修改"""
        
        project_id = context.get("project_id")
        
        if not project_id:
            # 没有项目上下文，建议创建项目
            response_content = """
            🤔 **需要项目上下文**
            
            您想要修改项目，但当前没有选中的项目。
            
            **您可以：**
            1. 选择现有项目
            2. 创建新项目
            3. 告诉我项目名称
            
            **我可以帮您：**
            - 修改项目代码
            - 添加新功能
            - 更新配置
            - 重构代码
            """
            suggestions = ["查看项目列表", "创建新项目", "指定项目名称"]
        else:
            response_content = f"""
            🔧 **项目修改**
            
            **当前项目：** {project_id}
            
            **我可以帮您：**
            - 添加新功能
            - 修改现有代码
            - 更新配置文件
            - 重构代码结构
            - 修复问题
            
            请告诉我具体要修改什么，我来帮您实现。
            """
            suggestions = ["添加功能", "修改代码", "更新配置", "查看项目结构", "运行项目"]
        
        project_operations = []
        if project_id:
            project_operations.append(ProjectOperation(
                operation="modify",
                project_id=project_id,
                description=request.message,
                status="pending"
            ))
        
        return ChatResult(
            response=ChatMessageResponse(
                message_id=str(UUID.uuid4()),
                conversation_id=request.conversation_id or str(UUID.uuid4()),
                content=response_content,
                intent_detected=intent.type.value,
                suggestions=suggestions,
                project_operations=project_operations,
                processing_time_ms=120
            ),
            background_tasks=[]
        )
    
    async def _handle_general_chat(
        self,
        request: ChatMessageRequest,
        intent: Intent,
        context: Dict[str, Any],
        user: User
    ) -> ChatResult:
        """处理普通聊天 - 使用现有逻辑"""
        
        # 使用现有的聊天服务
        response = await self.chat_service.process_message(
            user_id=user.id,
            message=request.message,
            model=request.model,
            conversation_id=request.conversation_id,
            system_prompt=request.system_prompt,
            attachments=request.attachments
        )
        
        # 基于上下文添加智能建议
        suggestions = response.get("follow_up_questions", [])
        if not suggestions:
            if context.get("project_id"):
                suggestions = ["修改项目", "运行项目", "添加功能", "查看文件"]
            else:
                suggestions = ["创建项目", "生成代码", "上传文件", "继续聊天"]
        
        return ChatResult(
            response=ChatMessageResponse(
                message_id=response["id"],
                conversation_id=response["conversation_id"],
                content=response["content"],
                intent_detected=intent.type.value,
                suggestions=suggestions[:4],  # 限制建议数量
                processing_time_ms=response.get("processing_time_ms", 100)
            ),
            background_tasks=[]
        )
    
    # 辅助方法
    async def _analyze_project_requirements(
        self, 
        message: str, 
        entities: Dict[str, Any]
    ) -> Dict[str, Any]:
        """分析项目需求"""
        
        project_spec = {
            "message": message,
            "project_type": entities.get("project_type", "general"),
            "technologies": entities.get("technologies", []),
            "project_name": entities.get("project_name"),
            "auto_create": False  # 默认不自动创建
        }
        
        # 如果用户明确表示要立即创建
        if any(word in message.lower() for word in ["立即", "马上", "现在就", "immediately", "now"]):
            project_spec["auto_create"] = True
        
        return project_spec
    
    def _get_api_key(self, user: User, model: Optional[str]) -> Optional[str]:
        """获取API密钥"""
        return self.chat_service._get_api_key(user, model or user.preferred_model)
    
    def _get_api_url(self, user: User, model: Optional[str]) -> Optional[str]:
        """获取API URL"""
        return self.chat_service._get_api_url(user, model or user.preferred_model)