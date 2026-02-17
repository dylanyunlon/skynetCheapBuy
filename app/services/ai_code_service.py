# app/services/ai_code_service.py

import re
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

# 添加缺失的导入
from app.services.ai_service import AIService
from app.services.code_service import CodeService
from app.core.code_extractor import CodeExtractor


class AICodeGenerationService:
    """AI 代码生成服务"""
    
    # 代码生成意图关键词
    CODE_GENERATION_KEYWORDS = [
        # 中文
        "写一个", "创建一个", "生成一个", "编写", "实现", "开发",
        "脚本", "程序", "代码", "自动化", "定时任务", "监控",
        # English
        "write a", "create a", "generate a", "implement", "develop",
        "script", "program", "code", "automate", "schedule", "monitor"
    ]
    
    # 脚本类型识别模式
    SCRIPT_TYPE_PATTERNS = {
        "python": [
            r"python\s*(脚本|script|程序|program)",
            r"\.py\s*文件",
            r"使用\s*python",
            r"用\s*python\s*实现"
        ],
        "bash": [
            r"bash\s*(脚本|script)",
            r"shell\s*(脚本|script)",
            r"\.sh\s*文件",
            r"linux\s*命令",
            r"系统命令"
        ]
    }
    
    # 定时任务模式
    CRON_PATTERNS = [
        r"每(\d+)分钟",
        r"每(\d+)小时",
        r"每天(\d+)点",
        r"every\s+(\d+)\s*minutes?",
        r"every\s+(\d+)\s*hours?",
        r"daily\s+at\s+(\d+)"
    ]
    
    def __init__(self, ai_service: AIService, code_service: CodeService):
        self.ai_service = ai_service
        self.code_service = code_service
        self.extractor = CodeExtractor()
    
    def detect_code_generation_intent(self, message: str) -> Tuple[bool, Optional[str]]:
        """检测是否是代码生成请求"""
        message_lower = message.lower()
        
        # 检查关键词
        for keyword in self.CODE_GENERATION_KEYWORDS:
            if keyword in message_lower:
                # 尝试识别脚本类型
                script_type = self.detect_script_type(message)
                return True, script_type
        
        return False, None
    
    def detect_script_type(self, message: str) -> str:
        """检测脚本类型"""
        message_lower = message.lower()
        
        # 检查 Python 模式
        for pattern in self.SCRIPT_TYPE_PATTERNS["python"]:
            if re.search(pattern, message_lower):
                return "python"
        
        # 检查 Bash 模式
        for pattern in self.SCRIPT_TYPE_PATTERNS["bash"]:
            if re.search(pattern, message_lower):
                return "bash"
        
        # 默认根据任务类型判断
        if any(keyword in message_lower for keyword in ["api", "数据处理", "机器学习", "analysis"]):
            return "python"
        elif any(keyword in message_lower for keyword in ["系统", "文件", "备份", "日志", "system", "backup"]):
            return "bash"
        
        # 默认使用 Python
        return "python"
    
    def extract_cron_expression(self, message: str) -> Optional[str]:
        """从消息中提取 cron 表达式"""
        message_lower = message.lower()
        
        # 标准 cron 表达式
        cron_match = re.search(r'["\']?(\*|[\d,\-\/]+)\s+(\*|[\d,\-\/]+)\s+(\*|[\d,\-\/]+)\s+(\*|[\d,\-\/]+)\s+(\*|[\d,\-\/]+)["\']?', message)
        if cron_match:
            return cron_match.group(0).strip('"\'')
        
        # 自然语言转换
        # 每X分钟
        match = re.search(r'每(\d+)分钟|every\s+(\d+)\s*minutes?', message_lower)
        if match:
            minutes = match.group(1) or match.group(2)
            return f"*/{minutes} * * * *"
        
        # 每X小时
        match = re.search(r'每(\d+)小时|every\s+(\d+)\s*hours?', message_lower)
        if match:
            hours = match.group(1) or match.group(2)
            return f"0 */{hours} * * *"
        
        # 每天X点
        match = re.search(r'每天(\d+)点|daily\s+at\s+(\d+)', message_lower)
        if match:
            hour = match.group(1) or match.group(2)
            return f"0 {hour} * * *"
        
        # 每天凌晨
        if "每天凌晨" in message_lower or "daily at midnight" in message_lower:
            return "0 0 * * *"
        
        return None
    
    def build_code_generation_prompt(
        self,
        user_request: str,
        script_type: str,
        include_cron: bool = False
    ) -> str:
        """构建代码生成提示词"""
        template = f"""请根据以下需求生成一个完整的、可直接执行的 {script_type} 脚本。

            用户需求：{user_request}

            要求：
            1. 代码必须是完整的、可直接执行的脚本
            2. 包含适当的错误处理和日志记录
            3. 添加必要的注释说明
            4. 使用安全的编码实践
            5. 包含脚本用途和参数说明

            脚本类型：{script_type}
            """
                    
        if script_type == "python":
            template += """
            Python 脚本要求：
            - 使用 Python 3.6+ 语法
            - 包含 shebang 行 (#!/usr/bin/env python3)
            - 使用 if __name__ == "__main__": 结构
            - 适当的异常处理
            - 使用 logging 模块记录日志
            """
        elif script_type == "bash":
            template += """
            Bash 脚本要求：
            - 使用 #!/bin/bash shebang
            - 设置 set -euo pipefail 严格模式
            - 包含错误处理函数
            - 使用有意义的变量名
            - 添加执行日志
            """
        
        if include_cron:
            template += """
            定时任务说明：
            - 脚本将通过 crontab 定时执行
            - 确保使用绝对路径
            - 输出重定向到日志文件
            - 处理环境变量问题
            """
        
        return template
    

    async def generate_code_with_ai(
        self,
        user_request: str,
        script_type: str,
        model: str,
        user_id: str,
        conversation_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """使用 AI 生成代码"""
        # 检测是否需要定时任务
        cron_expression = self.extract_cron_expression(user_request)
        
        # 构建提示词
        prompt = self.build_code_generation_prompt(
            user_request,
            script_type,
            include_cron=bool(cron_expression)
        )
        
        # 创建系统提示词
        system_prompt = """你是一个专业的代码生成助手。你的任务是根据用户需求生成高质量、安全、可维护的代码。
            生成的代码必须：
            1. 完整可执行，不是代码片段
            2. 包含错误处理和日志记录
            3. 遵循最佳实践和安全规范
            4. 有清晰的注释和文档

            请将生成的代码放在 markdown 代码块中，并指定正确的语言标识。"""
        
        # 从 kwargs 中提取 system_prompt（如果存在）
        if "system_prompt" in kwargs:
            system_prompt = kwargs.pop("system_prompt")  # 使用 pop 移除并获取值
        
        # 调用 AI 生成代码
        messages = [
            {"role": "user", "content": prompt}
        ]
        
        # 获取 AI 响应
        response = await self.ai_service.get_completion(
            messages=messages,
            model=model,
            system_prompt=system_prompt,
            temperature=0.3,  # 降低温度以获得更稳定的代码
            **kwargs  # 现在 kwargs 中不再包含 system_prompt
        )
        
        # 处理响应，提取代码
        code_result = await self.code_service.process_ai_response_for_code(
            ai_response=response["content"],
            user_id=user_id,
            conversation_id=conversation_id,
            auto_save=True
        )
        
        # 添加额外信息
        result = {
            "ai_response": response["content"],
            "code_extraction": code_result,
            "script_type": script_type,
            "cron_expression": cron_expression,
            "metadata": {
                "detected_intent": "code_generation",
                "script_type": script_type,
                "has_cron": bool(cron_expression),
                "model_used": model
            }
        }
        
        # 如果有可执行代码并且有 cron 表达式，准备定时任务信息
        if code_result.get("has_code") and cron_expression:
            executable_codes = [
                code for code in code_result["code_blocks"]
                if code.get("valid") and code.get("saved")
            ]
            
            if executable_codes:
                result["cron_ready"] = {
                    "code_id": executable_codes[0]["id"],
                    "cron_expression": cron_expression,
                    "suggested_job_name": self._generate_job_name(user_request)
                }
        
        return result


    def _generate_job_name(self, request: str) -> str:
        """生成任务名称"""
        # 提取关键词作为任务名
        keywords = []
        
        # 常见任务类型
        task_types = {
            "监控": "monitor",
            "备份": "backup",
            "清理": "cleanup",
            "同步": "sync",
            "检查": "check",
            "报告": "report"
        }
        
        for cn, en in task_types.items():
            if cn in request:
                keywords.append(en)
                break
        
        # 如果没有找到，使用通用名称
        if not keywords:
            keywords.append("task")
        
        # 添加时间戳确保唯一性
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"chatbot_{'_'.join(keywords)}_{timestamp}"
    
    async def setup_cron_job_from_code(
        self,
        code_id: str,
        cron_expression: str,
        user_id: str,
        job_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """从生成的代码设置定时任务"""
        try:
            result = await self.code_service.create_cron_job(
                code_id=code_id,
                user_id=user_id,
                cron_expression=cron_expression,
                job_name=job_name
            )
            
            return {
                "success": True,
                "cron_job": result,
                "message": f"定时任务 '{result['job_name']}' 创建成功"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "定时任务创建失败"
            }
    
    def parse_cron_to_human_readable(self, cron_expression: str) -> str:
        """将 cron 表达式转换为人类可读格式"""
        parts = cron_expression.split()
        if len(parts) != 5:
            return "无效的 cron 表达式"
        
        minute, hour, day, month, weekday = parts
        
        # 简单的解析逻辑
        if minute == "0" and hour == "*" and day == "*" and month == "*" and weekday == "*":
            return "每小时执行一次"
        elif minute == "0" and hour == "0" and day == "*" and month == "*" and weekday == "*":
            return "每天凌晨执行"
        elif minute.startswith("*/"):
            interval = minute[2:]
            return f"每 {interval} 分钟执行一次"
        elif hour.startswith("*/"):
            interval = hour[2:]
            return f"每 {interval} 小时执行一次"
        elif minute != "*" and hour != "*":
            return f"每天 {hour}:{minute} 执行"
        
        return cron_expression  # 返回原始表达式