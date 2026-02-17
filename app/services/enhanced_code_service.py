from typing import Dict, List, Any, Optional
import asyncio
from sqlalchemy.orm import Session
import uuid
import logging
from pathlib import Path

from app.services.code_service import CodeService
from app.core.workspace.workspace_manager import WorkspaceManager
from app.core.agents.code_agent import CodeGenerationAgent, DebugAgent
from app.models.code import CodeSnippet, GeneratedCode
from app.models.workspace import Project, ProjectFile
from app.config import settings

logger = logging.getLogger(__name__)

class EnhancedCodeService(CodeService):
    """增强的代码服务 - 支持多文件项目和智能调试"""
    
    def __init__(self, db: Session, ai_engine):
        super().__init__(db)
        # 使用配置中的工作空间路径，如果没有则使用默认值
        workspace_path = getattr(settings, 'WORKSPACE_PATH', './workspace')
        self.workspace_manager = WorkspaceManager(base_path=workspace_path)
        self.generation_agent = CodeGenerationAgent(ai_engine)
        self.debug_agent = DebugAgent(ai_engine)
        self.ai_engine = ai_engine
    
    async def create_project_from_request(
        self,
        user_id: str,
        request: str,
        model: str = "claude-opus-4-20250514-all",
        auto_execute: bool = False,
        max_debug_attempts: int = 3
    ) -> Dict[str, Any]:
        """从用户请求创建完整项目"""
        
        try:
            # 确保 user_id 是有效的 UUID 字符串
            if not user_id:
                return {
                    "success": False,
                    "error": "User ID is required"
                }
            
            # 验证 UUID 格式
            try:
                user_uuid = uuid.UUID(user_id)
            except ValueError:
                return {
                    "success": False,
                    "error": f"Invalid user ID format: {user_id}"
                }
            
            # 1. 分析需求，确定项目结构
            logger.info(f"Analyzing project request for user {user_id}")
            analysis_result = await self.generation_agent.analyze({
                "request": request,
                "model": model
            })
            
            if not analysis_result["success"]:
                return {
                    "success": False,
                    "error": "Failed to analyze request",
                    "details": analysis_result
                }
            
            project_structure = analysis_result["project_structure"]
            
            # 2. 创建项目
            logger.info("Creating project in workspace")
            project_info = await self.workspace_manager.create_project(
                user_id=user_id,
                project_name=project_structure.get("name", "untitled"),
                project_type=project_structure.get("project_type", "python"),
                description=request
            )
            
            # 3. 生成代码文件
            logger.info("Generating code files")
            generation_result = await self.generation_agent.generate({
                "request": request,
                "project_structure": project_structure,
                "model": model
            })
            
            if not generation_result["success"]:
                return {
                    "success": False,
                    "error": "Failed to generate code",
                    "project_id": project_info["project_id"],
                    "details": generation_result
                }
            
            # 4. 保存文件到项目
            logger.info(f"Saving {len(generation_result['files'])} files to project")
            entry_point = None
            python_files = []
            
            for file_path, file_info in generation_result["files"].items():
                await self.workspace_manager.add_file(
                    user_id=user_id,
                    project_id=project_info["project_id"],
                    file_path=file_path,
                    content=file_info["content"],
                    file_type="code"
                )
                
                # 收集Python文件作为潜在的入口点
                if file_path.endswith(".py"):
                    python_files.append(file_path)
                    # 优先选择常见的入口文件名
                    if file_path in ["main.py", "app.py", "run.py", "__main__.py"]:
                        entry_point = file_path
            
            # 如果没有找到标准入口文件，使用第一个Python文件
            if not entry_point and python_files:
                entry_point = python_files[0]
            
            # 如果还是没有入口点，使用第一个文件
            if not entry_point and generation_result["files"]:
                entry_point = list(generation_result["files"].keys())[0]
            
            # 5. 保存到数据库
            logger.info("Saving project to database")
            
            # 创建项目记录，使用 UUID 对象
            project = Project(
                id=uuid.UUID(project_info["project_id"]),
                user_id=user_uuid,  # 使用 UUID 对象而不是字符串
                name=project_structure.get("name", "untitled"),
                description=request,
                project_type=project_structure.get("project_type", "python"),
                entry_point=entry_point or "main.py",  # 使用检测到的入口点
                metadata={
                    "structure": project_structure,
                    "analysis": analysis_result.get("analysis", {})
                }
            )
            self.db.add(project)
            
            # 保存文件记录
            for file_path, file_info in generation_result["files"].items():
                project_file = ProjectFile(
                    project_id=uuid.UUID(project_info["project_id"]),
                    file_path=file_path,
                    content=file_info["content"],
                    file_type="code",
                    language=self._detect_language(file_path)
                )
                self.db.add(project_file)
            
            self.db.commit()
            
            # 6. 如果需要自动执行
            execution_result = None
            preview_url = None
            
            if auto_execute:
                logger.info("Auto-executing project")
                execution_result = await self.execute_project_with_debug(
                    user_id=user_id,
                    project_id=project_info["project_id"],
                    max_attempts=max_debug_attempts
                )
                
                # 提取预览URL
                if execution_result and execution_result.get("preview_url"):
                    preview_url = execution_result["preview_url"]
                    logger.info(f"Extracted preview URL from execution: {preview_url}")

            return {
                "success": True,
                "project_id": project_info["project_id"],
                "project_path": project_info["path"],
                "files": list(generation_result["files"].keys()),
                "structure": project_structure,
                "execution_result": execution_result,
                "preview_url": preview_url,  # 添加这行
                "project_detail": {  # 添加项目详情
                    "id": project_info["project_id"],
                    "name": project_structure.get("name", "untitled"),
                    "type": project_structure.get("project_type", "python"),
                    "file_count": len(generation_result["files"]),
                    "preview_url": preview_url
                }
            }
            
        except Exception as e:
            logger.error(f"Error creating project: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    async def execute_project_with_debug(
        self,
        user_id: str,
        project_id: str,
        max_attempts: int = 3,
        entry_point: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行项目，如果失败则尝试调试和修复"""
        
        debug_history = []
        
        # 如果没有指定入口点，从数据库获取
        if not entry_point:
            try:
                project_uuid = uuid.UUID(project_id)
                project = self.db.query(Project).filter(Project.id == project_uuid).first()
                if project:
                    entry_point = project.entry_point
            except Exception as e:
                logger.warning(f"Failed to get entry point from database: {e}")
        
        for attempt in range(max_attempts):
            # 执行项目
            logger.info(f"Executing project (attempt {attempt + 1}/{max_attempts})")
            execution_result = await self.workspace_manager.execute_project(
                user_id=user_id,
                project_id=project_id,
                entry_point=entry_point  # 传递入口点
            )
            
            if execution_result["success"]:
                return {
                    "success": True,
                    "exit_code": execution_result["exit_code"],
                    "stdout": execution_result["stdout"],
                    "stderr": execution_result["stderr"],
                    "debug_attempts": attempt,
                    "debug_history": debug_history
                }
            
            # 记录调试历史
            debug_history.append({
                "attempt": attempt + 1,
                "error": execution_result["stderr"],
                "exit_code": execution_result["exit_code"]
            })
            
            # 如果失败，尝试调试
            if attempt < max_attempts - 1:
                logger.info(f"Debugging project error (attempt {attempt + 1})")
                debug_result = await self._debug_and_fix_project(
                    user_id=user_id,
                    project_id=project_id,
                    error_info=execution_result
                )
                
                if not debug_result["success"]:
                    logger.warning("Debug failed, stopping attempts")
                    break
                
                debug_history[-1]["fixes"] = debug_result["fixed_files"]
        
        return {
            "success": False,
            "exit_code": execution_result["exit_code"],
            "stdout": execution_result["stdout"],
            "stderr": execution_result["stderr"],
            "debug_attempts": max_attempts,
            "debug_history": debug_history
        }
    
    async def _debug_and_fix_project(
        self,
        user_id: str,
        project_id: str,
        error_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调试并修复项目错误"""
        
        try:
            # 将 project_id 转换为 UUID
            project_uuid = uuid.UUID(project_id)
            
            # 获取项目文件
            project_files = self.db.query(ProjectFile).filter(
                ProjectFile.project_id == project_uuid
            ).all()
            
            fixed_files = []
            
            # 分析错误，确定需要修复的文件
            for file in project_files:
                if file.file_type == "code":
                    # 分析错误
                    analysis_result = await self.debug_agent.analyze({
                        "error_info": error_info,
                        "code": file.content,
                        "file_path": file.file_path
                    })
                    
                    if not analysis_result.get("needs_fix", False):
                        continue
                    
                    # 生成修复
                    fix_result = await self.debug_agent.generate({
                        "analysis": analysis_result["analysis"],
                        "code": file.content,
                        "file_path": file.file_path
                    })
                    
                    if fix_result["success"]:
                        # 更新文件内容
                        file.content = fix_result["fixed_code"]
                        
                        # 更新工作空间中的文件
                        await self.workspace_manager.add_file(
                            user_id=user_id,
                            project_id=project_id,
                            file_path=file.file_path,
                            content=fix_result["fixed_code"],
                            auto_commit=True
                        )
                        
                        fixed_files.append({
                            "file_path": file.file_path,
                            "changes": fix_result.get("changes", [])
                        })
            
            self.db.commit()
            
            return {
                "success": len(fixed_files) > 0,
                "fixed_files": fixed_files
            }
            
        except Exception as e:
            logger.error(f"Error debugging project: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    def _detect_language(self, file_path: str) -> str:
        """检测文件语言"""
        ext = Path(file_path).suffix.lower()
        
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".sh": "bash",
            ".bash": "bash",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".md": "markdown",
            ".txt": "text",
            ".html": "html",
            ".css": "css",
            ".sql": "sql",
            ".cpp": "cpp",
            ".c": "c",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".php": "php",
            ".rb": "ruby"
        }
        
        return ext_map.get(ext, "text")