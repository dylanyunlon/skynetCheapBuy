# app/services/code_service.py
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from uuid import uuid4
import logging

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.code import CodeSnippet
from app.models.user import User
from uuid import UUID
from app.core.code_extractor import CodeExtractor, CodeBlock, CodeType
from app.core.script_executor import ScriptExecutor
from app.core.cron_manager import CronManager
from app.schemas.code import CodeCreate, CodeUpdate

logger = logging.getLogger(__name__)

class CodeService:
    """代码管理服务"""
    
    def __init__(self, db: Session):
        self.db = db
        self.extractor = CodeExtractor()
        self.executor = ScriptExecutor()
        self.cron_manager = CronManager()
    
    async def process_ai_response_for_code(
        self,
        ai_response: str,
        user_id: str,
        conversation_id: Optional[str] = None,
        auto_save: bool = True
    ) -> Dict[str, Any]:
        """处理 AI 响应中的代码"""
        # 提取代码块
        code_blocks = self.extractor.extract_code_blocks(ai_response)
        
        result = {
            "has_code": len(code_blocks) > 0,
            "code_blocks": [],
            "total_blocks": len(code_blocks),
            "saved_blocks": 0
        }
        
        for block in code_blocks:
            # 验证代码
            is_valid = False
            error_msg = None
            
            if block.language == CodeType.PYTHON.value:
                is_valid, error_msg = self.extractor.validate_python_code(block.code)
            elif block.language in [CodeType.BASH.value, CodeType.SHELL.value]:
                is_valid, error_msg = self.extractor.validate_bash_code(block.code)
            else:
                # 其他语言暂时标记为有效
                is_valid = True
            
            block_info = {
                "language": block.language,
                "description": block.description,
                "is_executable": block.is_executable,
                "valid": is_valid,
                "error": error_msg,
                "line_count": len(block.code.splitlines()),
                "size": len(block.code)
            }
            
            # 如果是可执行代码且有效，保存它
            if auto_save and block.is_executable and is_valid:
                try:
                    # 添加安全包装
                    wrapped_code = self.extractor.add_safety_wrapper(block.code, block.language)
                    
                    # 保存到文件系统
                    script_info = await self.executor.save_script(
                        code=wrapped_code,
                        language=block.language,
                        user_id=str(user_id),  # 确保是字符串
                        description=block.description
                    )
                    
                    # 保存到数据库
                    code_snippet = CodeSnippet(
                        user_id=user_id,  # user_id 已经是 UUID
                        language=block.language,
                        code=block.code,  # 保存原始代码
                        wrapped_code=wrapped_code,  # 保存包装后的代码
                        title=block.description or f"{block.language} script",
                        description=block.description,
                        conversation_id=conversation_id,
                        file_path=script_info["filepath"],
                        snippet_metadata=script_info  # 使用新的列名
                    )
                    
                    self.db.add(code_snippet)
                    self.db.commit()
                    
                    block_info["saved"] = True
                    block_info["id"] = str(code_snippet.id)
                    block_info["filepath"] = script_info["filepath"]
                    result["saved_blocks"] += 1
                    
                except Exception as e:
                    logger.error(f"Failed to save code block: {e}")
                    block_info["saved"] = False
                    block_info["save_error"] = str(e)
            else:
                block_info["saved"] = False
                if not is_valid:
                    block_info["save_reason"] = "Invalid code syntax"
                elif not block.is_executable:
                    block_info["save_reason"] = "Not executable code"
                else:
                    block_info["save_reason"] = "Auto-save disabled"
            
            result["code_blocks"].append(block_info)
        
        return result
    

    async def execute_code(
            self,
            code_id: str,
            user_id: str,
            env_vars: Optional[Dict[str, str]] = None,
            timeout: int = 3000
        ) -> Dict[str, Any]:
            """执行保存的代码"""
            # 获取代码记录
            code_snippet = self.db.query(CodeSnippet).filter(
                and_(
                    CodeSnippet.id == code_id,
                    CodeSnippet.user_id == user_id
                )
            ).first()
            
            if not code_snippet:
                raise ValueError("Code snippet not found or access denied")
            
            # 执行脚本
            result = await self.executor.execute_script(
                filepath=code_snippet.file_path,
                timeout=timeout,
                env=env_vars
            )
            
            # 更新执行记录
            if not code_snippet.execution_history:
                code_snippet.execution_history = []
            
            code_snippet.execution_history.append({
                "executed_at": result["executed_at"],
                "success": result["success"],
                "exit_code": result["exit_code"],
                "execution_time": result["execution_time"]
            })
            
            code_snippet.last_executed = datetime.utcnow()
            code_snippet.execution_count = (code_snippet.execution_count or 0) + 1
            
            self.db.commit()
            
            # 为了兼容性，添加 output 和 error 字段
            result["output"] = result.get("stdout", "")
            result["error"] = result.get("stderr", "")
            
            # 如果没有输出但有错误，将错误作为输出
            if not result["output"] and result["error"]:
                result["output"] = f"Error: {result['error']}"
            
            # 添加日志字段（合并 stdout 和 stderr）
            logs = []
            if result.get("stdout"):
                logs.append("=== STDOUT ===")
                logs.append(result["stdout"])
            if result.get("stderr"):
                logs.append("\n=== STDERR ===")
                logs.append(result["stderr"])
            result["logs"] = "\n".join(logs) if logs else ""
            
            # 为了兼容性，添加 output 和 error 字段
            result["output"] = result.get("stdout", "")
            result["error"] = result.get("stderr", "")

            # 如果没有输出但有错误，将错误作为输出
            if not result["output"] and result["error"]:
                result["output"] = f"Error: {result['error']}"

            # 添加日志字段（合并 stdout 和 stderr）
            logs = []
            if result.get("stdout"):
                logs.append("=== STDOUT ===")
                logs.append(result["stdout"])
            if result.get("stderr"):
                logs.append("\n=== STDERR ===")
                logs.append(result["stderr"])
            result["logs"] = "\n".join(logs) if logs else ""

            return result
            return result


    async def create_cron_job(
        self,
        code_id: str,
        user_id: str,
        cron_expression: str,
        job_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """为代码创建定时任务"""
        # 获取代码记录
        code_snippet = self.db.query(CodeSnippet).filter(
            and_(
                CodeSnippet.id == code_id,
                CodeSnippet.user_id == user_id
            )
        ).first()
        
        if not code_snippet:
            raise ValueError("Code snippet not found or access denied")
        
        if not code_snippet.file_path or not Path(code_snippet.file_path).exists():
            raise ValueError("Script file not found")
        
        # 创建 cron 任务
        result = self.cron_manager.create_cron_job(
            script_path=code_snippet.file_path,
            cron_expression=cron_expression,
            user_id=str(user_id),
            job_name=job_name,
            description=code_snippet.description
        )
        
        if result["success"]:
            # 更新代码记录
            if not code_snippet.cron_jobs:
                code_snippet.cron_jobs = []
            
            code_snippet.cron_jobs.append(result["job_info"])
            self.db.commit()
        
        return result
    
    async def get_user_codes(
        self,
        user_id: str,
        language: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """获取用户的代码列表"""
        query = self.db.query(CodeSnippet).filter(
            CodeSnippet.user_id == user_id
        )
        
        if language:
            query = query.filter(CodeSnippet.language == language)
        
        snippets = query.order_by(
            CodeSnippet.created_at.desc()
        ).offset(offset).limit(limit).all()
        
        return [
            {
                "id": str(snippet.id),
                "language": snippet.language,
                "title": snippet.title,
                "description": snippet.description,
                "created_at": snippet.created_at.isoformat() if snippet.created_at else None,
                "last_executed_at": snippet.last_executed.isoformat() if snippet.last_executed else None,
                "execution_count": snippet.execution_count or 0,
                "has_cron_job": bool(snippet.cron_jobs),
                "file_size": len(snippet.code) if snippet.code else 0
            }
            for snippet in snippets
        ]
    
    async def get_code_snippet(
        self,
        code_id: str,
        user_id: str,
        include_wrapped: bool = False
    ) -> Dict[str, Any]:
        """获取代码片段详情"""
        snippet = self.db.query(CodeSnippet).filter(
            and_(
                CodeSnippet.id == code_id,
                CodeSnippet.user_id == user_id
            )
        ).first()
        
        if not snippet:
            raise ValueError("Code snippet not found or access denied")
        
        result = {
            "id": str(snippet.id),
            "language": snippet.language,
            "code": snippet.code,
            "title": snippet.title,
            "description": snippet.description,
            "created_at": snippet.created_at.isoformat() if snippet.created_at else None,
            "updated_at": snippet.updated_at.isoformat() if snippet.updated_at else None,
            "last_executed": snippet.last_executed.isoformat() if snippet.last_executed else None,
            "execution_count": snippet.execution_count or 0,
            "file_path": snippet.file_path,
            "conversation_id": snippet.conversation_id,
            "metadata": snippet.snippet_metadata,
            "execution_history": snippet.execution_history or [],
            "cron_jobs": snippet.cron_jobs or []
        }
        
        if include_wrapped and snippet.wrapped_code:
            result["wrapped_code"] = snippet.wrapped_code
        
        return result