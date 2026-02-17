# app/core/intent/engine.py - 修复版本
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import re
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class IntentType(Enum):
    """意图类型"""
    GENERAL_CHAT = "general_chat"
    PROJECT_CREATE = "project_create"
    PROJECT_MODIFY = "project_modify"
    CODE_GENERATION = "code_generation"
    FILE_OPERATION = "file_operation"
    WORKSPACE_COMMAND = "workspace_command"
    PROJECT_EXECUTION = "project_execution"
    PROJECT_DEPLOY = "project_deploy"
    CODE_EXECUTION = "code_execution"
    CRON_SETUP = "cron_setup"
    # 添加 Vibe Coding 相关意图类型
    VIBE_CODING_META = "vibe_coding_meta"         # Vibe Coding Meta 阶段
    VIBE_CODING_GENERATE = "vibe_coding_generate"  # Vibe Coding Generate 阶段

@dataclass
class Intent:
    type: IntentType
    confidence: float
    entities: Dict[str, Any]
    metadata: Dict[str, Any]
    suggested_actions: List[str] = None

    def __post_init__(self):
        if self.suggested_actions is None:
            self.suggested_actions = []

class IntentEngine:
    """智能意图识别引擎"""
    
    def __init__(self):
        self.patterns = self._load_patterns()
        self.project_keywords = self._load_project_keywords()
        self.code_keywords = self._load_code_keywords()
        self.file_operation_keywords = self._load_file_operation_keywords()
    
    async def analyze_intent(
        self,
        message: str,
        context: Dict[str, Any],
        user_history: Optional[List] = None
    ) -> Intent:
        """分析用户意图"""
        
        message_lower = message.lower().strip()
        
        # 1. 检查是否为 Vibe Coding 相关意图
        vibe_intent = self._detect_vibe_coding_intent(message, context)
        if vibe_intent:
            logger.info(f"Detected Vibe Coding intent: {vibe_intent.type.value}")
            return vibe_intent
        
        # 2. 基于规则的快速识别
        rule_intent = self._rule_based_classification(message, context)
        if rule_intent.confidence > 0.8:
            logger.info(f"High confidence rule-based intent: {rule_intent.type.value}")
            return rule_intent
        
        # 3. 上下文增强识别
        context_intent = self._context_enhanced_classification(
            message, context, user_history
        )
        
        # 4. 结合项目状态识别
        if context.get("project_id"):
            project_intent = self._project_aware_classification(
                message, context
            )
            # 选择置信度最高的意图
            best_intent = max([rule_intent, context_intent, project_intent], 
                            key=lambda x: x.confidence)
        else:
            best_intent = max([rule_intent, context_intent], 
                            key=lambda x: x.confidence)
        
        logger.info(f"Final intent: {best_intent.type.value} (confidence: {best_intent.confidence})")
        return best_intent
    
    def _detect_vibe_coding_intent(self, message: str, context: Dict[str, Any]) -> Optional[Intent]:
        """检测 Vibe Coding 相关意图"""
        
        # 检查是否为 Generate 阶段（确认生成项目）
        if context.get("stage") == "meta_complete" or context.get("meta_result"):
            confirm_patterns = [
                r"确认生成", r"确认创建", r"生成项目", r"创建项目",
                r"confirm", r"generate", r"create project", r"yes", r"好的", r"确定"
            ]
            
            if any(re.search(pattern, message, re.IGNORECASE) for pattern in confirm_patterns):
                return Intent(
                    type=IntentType.VIBE_CODING_GENERATE,
                    confidence=0.95,
                    entities={
                        "stage": "generate",
                        "meta_result": context.get("meta_result"),
                        "optimized_prompt": context.get("optimized_prompt"),
                        "original_user_input": context.get("original_user_input")
                    },
                    metadata={
                        "stage": "generate",
                        "meta_result": context.get("meta_result"),
                        "trigger": "vibe_coding_generate"
                    },
                    suggested_actions=["生成项目", "创建工作空间", "部署预览"]
                )
        
        # 检查是否为需求修改请求
        if context.get("stage") == "meta_complete":
            modify_patterns = [
                r"修改", r"调整", r"改成", r"换成", r"优化",
                r"modify", r"change", r"adjust", r"update", r"improve"
            ]
            
            if any(re.search(pattern, message, re.IGNORECASE) for pattern in modify_patterns):
                return Intent(
                    type=IntentType.VIBE_CODING_META,
                    confidence=0.9,
                    entities={
                        "stage": "meta_modify",
                        "is_modification": True,
                        "previous_meta_result": context.get("meta_result")
                    },
                    metadata={
                        "stage": "meta_modify",
                        "is_modification": True,
                        "trigger": "vibe_coding_meta_modify"
                    },
                    suggested_actions=["重新优化需求", "确认修改", "生成项目"]
                )
        
        # 检查是否为初始的项目创建请求（需要 Meta 阶段）
        vibe_features = self._detect_vibe_coding_features(message)
        if vibe_features.get("requires_meta_prompt"):
            return Intent(
                type=IntentType.VIBE_CODING_META,
                confidence=0.9,
                entities={
                    "stage": "meta_initial",
                    "vibe_features": vibe_features,
                    "project_type": vibe_features.get("project_type", "web")
                },
                metadata={
                    "stage": "meta_initial",
                    "vibe_features": vibe_features,
                    "trigger": "vibe_coding_meta_initial"
                },
                suggested_actions=["优化需求", "设计架构", "生成项目"]
            )
        
        return None
    
    def _rule_based_classification(
        self, 
        message: str, 
        context: Dict[str, Any]
    ) -> Intent:
        """基于规则的分类"""
        message_lower = message.lower()
        
        # 项目创建模式 - 优先级最高
        if self._matches_project_creation(message_lower):
            entities = self._extract_project_entities(message)
            return Intent(
                type=IntentType.PROJECT_CREATE,
                confidence=0.95,
                entities=entities,
                metadata={"trigger": "create_keywords"},
                suggested_actions=["创建项目", "选择模板", "配置技术栈"]
            )
        
        # 代码执行模式 - 检查是否要执行现有代码
        if self._matches_code_execution(message_lower, context):
            return Intent(
                type=IntentType.CODE_EXECUTION,
                confidence=0.9,
                entities={"action": "execute"},
                metadata={"trigger": "execution_keywords"},
                suggested_actions=["运行代码", "查看结果", "调试错误"]
            )
        
        # 定时任务设置
        if self._matches_cron_setup(message_lower):
            entities = self._extract_cron_entities(message)
            return Intent(
                type=IntentType.CRON_SETUP,
                confidence=0.85,
                entities=entities,
                metadata={"trigger": "cron_keywords"},
                suggested_actions=["设置定时任务", "查看任务列表", "修改执行时间"]
            )
        
        # 代码生成模式
        if self._matches_code_generation(message_lower):
            entities = self._extract_code_entities(message)
            return Intent(
                type=IntentType.CODE_GENERATION,
                confidence=0.85,
                entities=entities,
                metadata={"trigger": "code_keywords"},
                suggested_actions=["生成代码", "保存到项目", "立即执行"]
            )
        
        # 文件操作模式
        if self._matches_file_operation(message_lower):
            entities = self._extract_file_entities(message)
            return Intent(
                type=IntentType.FILE_OPERATION,
                confidence=0.8,
                entities=entities,
                metadata={"trigger": "file_keywords"},
                suggested_actions=["查看文件", "编辑内容", "删除文件"]
            )
        
        # 项目修改模式
        if context.get("project_id") and self._matches_project_modification(message_lower):
            return Intent(
                type=IntentType.PROJECT_MODIFY,
                confidence=0.75,
                entities={"project_id": context["project_id"]},
                metadata={"trigger": "modify_keywords"},
                suggested_actions=["修改项目", "添加功能", "查看结构"]
            )
        
        return Intent(
            type=IntentType.GENERAL_CHAT,
            confidence=0.5,
            entities={},
            metadata={"trigger": "default"},
            suggested_actions=["继续对话", "创建项目", "生成代码"]
        )
    
    def _context_enhanced_classification(
        self, 
        message: str, 
        context: Dict[str, Any],
        user_history: Optional[List] = None
    ) -> Intent:
        """上下文增强分类"""
        
        # 如果用户最近在讨论项目相关内容
        if user_history:
            recent_messages = user_history[-3:] if len(user_history) >= 3 else user_history
            recent_text = " ".join([msg.get("content", "") for msg in recent_messages])
            
            if any(keyword in recent_text.lower() for keyword in ["project", "项目", "app", "应用"]):
                if any(keyword in message.lower() for keyword in ["add", "create", "make", "添加", "创建", "做"]):
                    return Intent(
                        type=IntentType.PROJECT_MODIFY,
                        confidence=0.7,
                        entities={"context": "recent_project_discussion"},
                        metadata={"trigger": "context_history"},
                        suggested_actions=["修改项目", "添加功能"]
                    )
        
        # 检查是否在项目上下文中
        if context.get("project_id"):
            return Intent(
                type=IntentType.PROJECT_MODIFY,
                confidence=0.6,
                entities={"project_id": context["project_id"]},
                metadata={"trigger": "project_context"},
                suggested_actions=["修改项目", "查看文件", "运行项目"]
            )
        
        return Intent(
            type=IntentType.GENERAL_CHAT,
            confidence=0.4,
            entities={},
            metadata={"trigger": "context_default"}
        )
    
    def _project_aware_classification(
        self, 
        message: str, 
        context: Dict[str, Any]
    ) -> Intent:
        """项目感知分类"""
        project_files = context.get("project_files", [])
        project_type = context.get("project_type", "")
        
        # 如果消息提到了项目中的文件
        mentioned_files = []
        for file_path in project_files:
            if file_path.lower() in message.lower():
                mentioned_files.append(file_path)
        
        if mentioned_files:
            return Intent(
                type=IntentType.FILE_OPERATION,
                confidence=0.9,
                entities={"files": mentioned_files, "project_id": context["project_id"]},
                metadata={"trigger": "project_file_mention"},
                suggested_actions=["编辑文件", "查看内容", "删除文件"]
            )
        
        # 如果是技术栈相关的问题
        if project_type and project_type.lower() in message.lower():
            return Intent(
                type=IntentType.PROJECT_MODIFY,
                confidence=0.7,
                entities={"project_type": project_type, "project_id": context["project_id"]},
                metadata={"trigger": "tech_stack_mention"},
                suggested_actions=["修改配置", "添加依赖", "更新代码"]
            )
        
        # 检查是否想要运行项目
        if any(keyword in message.lower() for keyword in ["run", "start", "launch", "运行", "启动", "执行"]):
            return Intent(
                type=IntentType.PROJECT_EXECUTION,
                confidence=0.8,
                entities={"project_id": context["project_id"], "action": "run"},
                metadata={"trigger": "project_run_keywords"},
                suggested_actions=["运行项目", "查看输出", "调试错误"]
            )
        
        return Intent(
            type=IntentType.GENERAL_CHAT,
            confidence=0.4,
            entities={},
            metadata={"trigger": "project_context"}
        )
    
    # 意图匹配方法
    def _matches_project_creation(self, message: str) -> bool:
        """检查是否匹配项目创建意图"""
        creation_patterns = [
            r"创建.*?项目", r"新建.*?项目", r"做.*?项目", r"开发.*?项目",
            r"create.*?project", r"new.*?project", r"build.*?app", r"make.*?app",
            r"start.*?project", r"initialize.*?project",
            r"我想做", r"我要做", r"帮我做", r"做一个",
            r"build a", r"create a", r"make a", r"develop a"
        ]
        
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in creation_patterns)
    
    def _matches_code_generation(self, message: str) -> bool:
        """检查是否匹配代码生成意图"""
        code_patterns = [
            r"写.*?代码", r"生成.*?代码", r"创建.*?函数", r"实现.*?功能",
            r"write.*?code", r"generate.*?code", r"create.*?function", r"implement.*?function",
            r"脚本", r"script", r"程序", r"program",
            r"写一个", r"做一个.*?脚本", r"创建一个.*?程序"
        ]
        
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in code_patterns)
    
    def _matches_code_execution(self, message: str, context: Dict[str, Any]) -> bool:
        """检查是否匹配代码执行意图"""
        # 如果有项目或代码上下文，并且包含执行关键词
        has_code_context = context.get("project_id") or context.get("recent_code_generation")
        
        execution_patterns = [
            r"运行", r"执行", r"启动", r"测试",
            r"run", r"execute", r"start", r"test", r"launch"
        ]
        
        return has_code_context and any(re.search(pattern, message, re.IGNORECASE) for pattern in execution_patterns)
    
    def _matches_cron_setup(self, message: str) -> bool:
        """检查是否匹配定时任务设置意图"""
        cron_patterns = [
            r"定时.*?任务", r"定时.*?执行", r"每.*?执行", r"定时.*?运行",
            r"cron", r"schedule", r"timer", r"periodic",
            r"每天", r"每小时", r"每分钟", r"每周", r"每月",
            r"every.*?day", r"every.*?hour", r"every.*?minute", r"daily", r"hourly"
        ]
        
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in cron_patterns)
    
    def _matches_file_operation(self, message: str) -> bool:
        """检查是否匹配文件操作意图"""
        file_patterns = [
            r"添加.*?文件", r"创建.*?文件", r"删除.*?文件", r"修改.*?文件",
            r"add.*?file", r"create.*?file", r"delete.*?file", r"modify.*?file",
            r"edit.*?file", r"update.*?file", r"查看.*?文件", r"打开.*?文件"
        ]
        
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in file_patterns)
    
    def _matches_project_modification(self, message: str) -> bool:
        """检查是否匹配项目修改意图"""
        modify_patterns = [
            r"修改", r"更新", r"添加.*?功能", r"增加.*?功能",
            r"modify", r"update", r"add.*?feature", r"enhance", r"improve"
        ]
        
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in modify_patterns)
    
    # 实体提取方法
    def _extract_project_entities(self, message: str) -> Dict[str, Any]:
        """提取项目相关实体"""
        entities = {}
        
        # 提取项目类型
        type_patterns = {
            "web": [r"网站", r"网页", r"web.*?app", r"website", r"web.*?site"],
            "api": [r"api", r"接口", r"后端", r"backend", r"server"],
            "mobile": [r"手机.*?应用", r"移动.*?应用", r"mobile.*?app", r"app"],
            "desktop": [r"桌面.*?应用", r"desktop.*?app", r"gui"],
            "data": [r"数据.*?分析", r"机器.*?学习", r"data.*?analysis", r"ml", r"ai"],
            "game": [r"游戏", r"game"],
            "tool": [r"工具", r"tool", r"utility", r"脚本", r"script"]
        }
        
        for ptype, patterns in type_patterns.items():
            if any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns):
                entities["project_type"] = ptype
                break
        
        # 提取技术栈
        tech_patterns = {
            "python": [r"python", r"django", r"flask", r"fastapi", r"py"],
            "javascript": [r"javascript", r"js", r"react", r"vue", r"node", r"express"],
            "typescript": [r"typescript", r"ts", r"next\.?js", r"nuxt"],
            "java": [r"java", r"spring", r"springboot"],
            "go": [r"golang", r"go"],
            "rust": [r"rust"],
            "cpp": [r"c\+\+", r"cpp"],
            "html": [r"html", r"css", r"前端"],
        }
        
        techs = []
        for tech, patterns in tech_patterns.items():
            if any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns):
                techs.append(tech)
        
        if techs:
            entities["technologies"] = techs
        
        # 提取项目名称（简单实现）
        name_match = re.search(r"叫做?[\"']?([^\"'，。！？\s]+)[\"']?", message)
        if name_match:
            entities["project_name"] = name_match.group(1)
        
        return entities
    
    def _extract_code_entities(self, message: str) -> Dict[str, Any]:
        """提取代码相关实体"""
        entities = {}
        
        # 提取编程语言
        language_patterns = {
            "python": [r"python", r"py"],
            "javascript": [r"javascript", r"js"],
            "typescript": [r"typescript", r"ts"],
            "bash": [r"bash", r"shell", r"脚本"],
            "sql": [r"sql", r"数据库"],
            "html": [r"html"],
            "css": [r"css"],
            "java": [r"java"],
            "go": [r"go", r"golang"],
            "rust": [r"rust"],
            "cpp": [r"c\+\+", r"cpp"]
        }
        
        for lang, patterns in language_patterns.items():
            if any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns):
                entities["language"] = lang
                break
        
        # 提取功能描述
        func_patterns = [
            r"实现.*?功能", r"写.*?函数", r"创建.*?类",
            r"implement.*?function", r"create.*?class", r"write.*?function"
        ]
        
        for pattern in func_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                entities["functionality"] = match.group(0)
                break
        
        return entities
    
    def _extract_file_entities(self, message: str) -> Dict[str, Any]:
        """提取文件相关实体"""
        entities = {}
        
        # 提取文件路径或名称
        file_patterns = [
            r"([^\s]+\.(?:py|js|ts|html|css|java|go|rs|cpp|h|json|yaml|yml|md|txt))",
            r"文件[\"']?([^\"'，。！？\s]+)[\"']?",
            r"file[\"']?([^\"'，。！？\s]+)[\"']?"
        ]
        
        for pattern in file_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                entities["file_path"] = match.group(1)
                break
        
        # 提取操作类型
        if any(word in message.lower() for word in ["create", "add", "新建", "创建", "添加"]):
            entities["operation"] = "create"
        elif any(word in message.lower() for word in ["delete", "remove", "删除"]):
            entities["operation"] = "delete"
        elif any(word in message.lower() for word in ["edit", "modify", "update", "编辑", "修改"]):
            entities["operation"] = "edit"
        elif any(word in message.lower() for word in ["view", "show", "查看", "显示"]):
            entities["operation"] = "view"
        
        return entities
    
    def _extract_cron_entities(self, message: str) -> Dict[str, Any]:
        """提取定时任务相关实体"""
        entities = {}
        
        # 提取时间表达式
        time_patterns = {
            "daily": [r"每天", r"daily", r"每日"],
            "hourly": [r"每小时", r"hourly", r"每个小时"],
            "weekly": [r"每周", r"weekly", r"每星期"],
            "monthly": [r"每月", r"monthly", r"每个月"],
            "minutely": [r"每分钟", r"every.*?minute"]
        }
        
        for freq, patterns in time_patterns.items():
            if any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns):
                entities["frequency"] = freq
                break
        
        # 提取具体时间
        time_match = re.search(r"(\d{1,2}):(\d{2})", message)
        if time_match:
            entities["time"] = f"{time_match.group(1)}:{time_match.group(2)}"
        
        return entities
    
    # 数据加载方法（可以后续从配置文件加载）
    def _load_patterns(self) -> Dict[str, List[str]]:
        """加载意图识别模式"""
        return {}
    
    def _load_project_keywords(self) -> List[str]:
        """加载项目关键词"""
        return [
            "project", "项目", "app", "应用", "website", "网站",
            "system", "系统", "platform", "平台", "service", "服务"
        ]
    
    def _load_code_keywords(self) -> List[str]:
        """加载代码关键词"""
        return [
            "code", "代码", "script", "脚本", "function", "函数",
            "class", "类", "method", "方法", "algorithm", "算法"
        ]
    
    def _load_file_operation_keywords(self) -> List[str]:
        """加载文件操作关键词"""
        return [
            "file", "文件", "folder", "文件夹", "directory", "目录",
            "create", "创建", "delete", "删除", "edit", "编辑"
        ]
    
    async def analyze_intent_with_project_context(
        self,
        message: str,
        context: Dict[str, Any],
        user_history: Optional[List] = None
    ) -> Intent:
        """增强的项目感知意图识别"""
        
        # 基础意图识别（使用现有逻辑）
        base_intent = await self.analyze_intent(message, context, user_history)
        
        # 项目感知增强
        if context.get("current_project_id"):
            base_intent = self._enhance_with_project_context(base_intent, message, context)
        
        # 添加 vibe coding 特征识别
        vibe_features = self._detect_vibe_coding_features(message)
        base_intent.metadata.update({"vibe_features": vibe_features})
        
        return base_intent
    
    def _enhance_with_project_context(self, intent: Intent, message: str, context: Dict[str, Any]) -> Intent:
        """用项目上下文增强意图"""
        # 如果在项目上下文中，可以调整意图类型和置信度
        if context.get("current_project_id"):
            intent.entities["project_id"] = context["current_project_id"]
            intent.metadata["project_context"] = True
        
        return intent
    
    def _detect_vibe_coding_features(self, message: str) -> Dict[str, Any]:
        """检测 vibe coding 特征"""
        features = {
            "requires_meta_prompt": False,
            "complexity_level": "simple",  # simple, medium, complex
            "expected_output": "text",  # text, project, modification, execution
            "user_expertise": "beginner",  # beginner, intermediate, expert
            "project_type": "web"  # 默认类型
        }
        
        # 检测是否需要 meta-prompt（项目创建类请求）
        if any(keyword in message.lower() for keyword in 
               ["创建", "新建", "搭建", "做一个", "build", "create", "make", "开发"]):
            features["requires_meta_prompt"] = True
            features["expected_output"] = "project"
        
        # 检测复杂度
        if len(message.split()) > 20 or any(keyword in message.lower() for keyword in 
                ["数据库", "用户系统", "登录", "支付", "api", "后端", "database", "auth", "payment"]):
            features["complexity_level"] = "complex"
        elif len(message.split()) > 10 or any(keyword in message.lower() for keyword in 
                ["前端", "后端", "react", "vue", "express", "flask"]):
            features["complexity_level"] = "medium"
        
        # 检测项目类型
        if any(keyword in message.lower() for keyword in ["网站", "website", "web", "前端"]):
            features["project_type"] = "web"
        elif any(keyword in message.lower() for keyword in ["api", "后端", "backend", "server"]):
            features["project_type"] = "api"
        elif any(keyword in message.lower() for keyword in ["app", "应用", "mobile"]):
            features["project_type"] = "mobile"
        elif any(keyword in message.lower() for keyword in ["数据", "分析", "ml", "ai"]):
            features["project_type"] = "data"
        
        return features