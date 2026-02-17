# app/services/project_service.py - 最终版本，修复所有依赖问题
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models.workspace import Project, ProjectFile
from app.core.workspace.workspace_manager import WorkspaceManager
from app.core.ai.prompt_engine import PromptEngine
from app.core.ai_engine import AIEngine
import json
import asyncio
import logging
from uuid import uuid4
from datetime import datetime

logger = logging.getLogger(__name__)

class ProjectService:
    """统一的项目服务 - 支持完整的 Vibe Coding 流程"""
    
    def __init__(self, db: Session, workspace_manager: WorkspaceManager, ai_engine: AIEngine):
        self.db = db
        self.workspace_manager = workspace_manager
        self.ai_engine = ai_engine
        self.prompt_engine = PromptEngine(ai_engine)
    
    # ==================== Vibe Coding 两阶段流程 ====================
    
    async def handle_vibe_coding_meta_stage(
        self,
        user_id: str,
        user_input: str,
        chat_session_id: str
    ) -> Dict[str, Any]:
        """处理 Vibe Coding Meta 阶段 - 第一次 AI 调用"""
        
        logger.info(f"Starting Vibe Coding Meta stage for user {user_id}")
        
        try:
            # 使用 PromptEngine 处理 Meta 阶段
            meta_result = await self.prompt_engine.handle_vibe_coding_meta_stage(user_input)
            
            # 添加用户和会话信息
            meta_result.update({
                "user_id": user_id,
                "chat_session_id": chat_session_id,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            logger.info(f"Meta stage completed successfully for user {user_id}")
            return meta_result
            
        except Exception as e:
            logger.error(f"Vibe Coding Meta stage failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "stage": "meta_failed",
                "user_id": user_id,
                "chat_session_id": chat_session_id
            }
    
    async def handle_vibe_coding_generate_stage(
        self,
        user_id: str,
        meta_result: Dict[str, Any],
        chat_session_id: str
    ) -> Dict[str, Any]:
        """处理 Vibe Coding Generate 阶段 - 第二次 AI 调用 + 实际项目创建"""
        
        logger.info(f"Starting Vibe Coding Generate stage for user {user_id}")
        
        try:
            # 第一步：使用 PromptEngine 生成项目数据
            generate_result = await self.prompt_engine.handle_vibe_coding_generate_stage(meta_result)
            
            if not generate_result.get("success"):
                return generate_result
            
            # 第二步：解析项目数据
            project_data = generate_result["project_data"]
            
            # 第三步：创建数据库记录
            project = await self._create_project_record(
                user_id=user_id,
                project_data=project_data,
                meta_result=meta_result,
                generate_result=generate_result,
                chat_session_id=chat_session_id
            )
            
            # 第四步：在工作空间中创建实际文件
            workspace_result = await self._setup_project_workspace(project, project_data)
            
            # 第五步：执行项目并生成预览
            execution_result = await self._execute_and_preview_project(project, workspace_result)
            
            # 第六步：更新项目状态
            await self._finalize_project_creation(project, workspace_result, execution_result)
            
            return {
                "success": True,
                "stage": "generate_complete",
                "project": project,
                "project_data": project_data,
                "workspace_result": workspace_result,
                "execution_result": execution_result,
                "preview_url": execution_result.get("preview_url"),
                "meta_result": meta_result,
                "generate_result": generate_result
            }
            
        except Exception as e:
            logger.error(f"Vibe Coding Generate stage failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "stage": "generate_failed",
                "user_id": user_id,
                "chat_session_id": chat_session_id
            }
    
    # ==================== 修改需求处理 ====================
    
    async def modify_vibe_coding_requirement(
        self,
        user_id: str,
        modification_request: str,
        previous_meta_result: Dict[str, Any],
        chat_session_id: str
    ) -> Dict[str, Any]:
        """处理 Vibe Coding 需求修改"""
        
        logger.info(f"Modifying Vibe Coding requirement for user {user_id}")
        
        try:
            # 构建修改需求的 prompt
            modify_prompt = f"""基于之前的项目需求和用户的修改要求，请重新优化项目描述。

之前的项目需求：
{previous_meta_result.get('optimized_description', '')}

用户的修改要求：
{modification_request}

请按照之前的格式重新返回优化后的项目描述，确保：
1. 保持项目的基本架构
2. 整合用户的新要求
3. 确保技术方案的一致性
4. 提供完整的项目规划

优化后的项目描述："""

            # 调用 AI 重新优化
            messages = [{"role": "user", "content": modify_prompt}]
            response = await self.ai_engine.get_completion(
                messages=messages,
                model="claude-opus-4-5-20251101",
                temperature=0.7,
                max_tokens=2000
            )
            
            optimized_description = response.get("content", "")
            
            # 解析新的项目信息
            project_info = self.prompt_engine._extract_project_info_from_optimization(optimized_description)
            
            # 创建新的 meta_result
            new_meta_result = {
                "success": True,
                "stage": "meta_complete",
                "original_input": modification_request,
                "optimized_description": optimized_description,
                "project_info": project_info,
                "next_stage": "generate",
                "modified": True,
                "previous_meta_result": previous_meta_result,
                "user_id": user_id,
                "chat_session_id": chat_session_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            logger.info(f"Requirement modification completed for user {user_id}")
            return new_meta_result
            
        except Exception as e:
            logger.error(f"Requirement modification failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "stage": "modify_failed",
                "user_id": user_id,
                "chat_session_id": chat_session_id
            }
    
    # ==================== 项目创建实现 ====================
    
    async def _create_project_record(
        self,
        user_id: str,
        project_data: Dict[str, Any],
        meta_result: Dict[str, Any],
        generate_result: Dict[str, Any],
        chat_session_id: str
    ) -> Project:
        """创建项目数据库记录"""
        
        project_meta = project_data.get("project_meta", {})
        
        project = Project(
            id=uuid4(),
            user_id=user_id,
            name=project_meta.get("name", "未命名项目"),
            description=project_meta.get("description", ""),
            project_type=project_meta.get("type", "web"),
            tech_stack=project_meta.get("tech_stack", []),
            status="creating",
            creation_prompt=meta_result.get("original_input", ""),
            enhanced_prompt=meta_result.get("optimized_description", ""),
            ai_response=generate_result.get("ai_response", ""),
            meta_prompt_data={
                "meta_result": meta_result,
                "generate_result": generate_result,
                "chat_session_id": chat_session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "vibe_coding": True
            }
        )
        
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        
        logger.info(f"Created project record: {project.id}")
        return project
    
    async def _setup_project_workspace(
        self,
        project: Project,
        project_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """在工作空间中创建实际文件"""
        
        try:
            # 创建工作空间
            workspace_result = await self.workspace_manager.create_project(
                user_id=str(project.user_id),
                project_name=project.name,
                project_type=project.project_type,
                description=project.description
            )
            
            logger.info(f"Created workspace: {workspace_result}")
            
            # 更新项目工作空间路径
            project.workspace_path = workspace_result["path"]
            
            # 创建所有文件
            files = project_data.get("files", {})
            created_files = []
            
            for file_path, file_info in files.items():
                content = file_info.get("content", "")
                if content:
                    # 在工作空间中创建文件
                    file_result = await self.workspace_manager.add_file(
                        user_id=str(project.user_id),
                        project_id=workspace_result["project_id"],
                        file_path=file_path,
                        content=content,
                        file_type=self._detect_file_type(file_path, file_info)
                    )
                    
                    logger.info(f"Created file in workspace: {file_result}")
                    
                    # 创建数据库记录
                    project_file = ProjectFile(
                        id=uuid4(),
                        project_id=project.id,
                        file_path=file_path,
                        content=content,
                        file_type=self._detect_file_type(file_path, file_info),
                        language=self._detect_language(file_path),
                        size=len(content)
                    )
                    
                    # 检查是否是入口文件
                    deployment = project_data.get("deployment", {})
                    entry_point = deployment.get("entry_point", "")
                    if (file_path == entry_point or 
                        file_path in ["main.py", "app.py", "index.html", "index.js", "start_server.sh", "run.sh"]):
                        project_file.is_entry_point = True
                        logger.info(f"Marked {file_path} as entry point")
                        
                        # 如果是shell脚本，设置可执行权限
                        if file_path.endswith('.sh'):
                            import os
                            import stat
                            script_path = f"{workspace_result['path']}/{file_path}"
                            try:
                                os.chmod(script_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IROTH)
                                logger.info(f"Set executable permission for {file_path}")
                            except Exception as e:
                                logger.warning(f"Failed to set executable permission: {e}")
                    
                    self.db.add(project_file)
                    created_files.append(file_path)
            
            # 更新项目统计
            project.file_count = len(created_files)
            project.size = sum(len(files[f].get("content", "")) for f in created_files)
            
            self.db.commit()
            
            logger.info(f"Created {len(created_files)} files for project {project.id}")
            
            return {
                "workspace_path": workspace_result["path"],
                "workspace_project_id": workspace_result["project_id"],
                "created_files": created_files,
                "file_count": len(created_files)
            }
            
        except Exception as e:
            logger.error(f"Failed to setup workspace: {e}", exc_info=True)
            raise
    
    async def _execute_and_preview_project(self, project: Project, workspace_result: Dict[str, Any]) -> Dict[str, Any]:
        """执行项目并生成预览"""
        
        try:
            logger.info(f"Starting project execution for project {project.id}")
            
            # 获取项目文件信息
            project_files = self.db.query(ProjectFile).filter(
                ProjectFile.project_id == project.id
            ).all()
            
            if not project_files:
                logger.warning(f"No files found for project {project.id}")
                return {
                    "success": False,
                    "error": "No files found in project",
                    "preview_url": None
                }
            
            logger.info(f"Found {len(project_files)} files for project {project.id}")
            
            # 查找入口文件
            entry_file = None
            for file in project_files:
                if file.is_entry_point:
                    entry_file = file.file_path
                    break
            
            # 如果没有明确的入口文件，尝试常见的入口文件
            if not entry_file:
                common_entries = ["start_server.sh", "deploy.sh", "index.html", "main.py", "app.py", "index.js"]
                for file in project_files:
                    if file.file_path in common_entries:
                        entry_file = file.file_path
                        break
            
            # 如果还是没有找到，使用第一个文件
            if not entry_file and project_files:
                entry_file = project_files[0].file_path
            
            logger.info(f"Using entry file: {entry_file} for project {project.id}")
            
            # 检查工作空间路径
            if not project.workspace_path:
                logger.error(f"No workspace path found for project {project.id}")
                return {
                    "success": False,
                    "error": "No workspace path found",
                    "preview_url": None
                }
            
            # 使用工作空间中的项目ID执行
            workspace_project_id = workspace_result.get("workspace_project_id", str(project.id))
            
            try:
                execution_result = await self.workspace_manager.execute_project(
                    user_id=str(project.user_id),
                    project_id=workspace_project_id,
                    entry_point=entry_file,
                    timeout=60000
                )
                logger.info(f"Project execution result: {execution_result}")
            except Exception as exec_error:
                logger.error(f"Workspace execution failed: {exec_error}")
                
                # 尝试创建一个基础预览（特别是对于HTML文件）
                if entry_file and entry_file.endswith('.html'):
                    logger.info("Creating basic preview for HTML file")
                    preview_url = f"/preview/{project.id}/{entry_file}"
                    
                    # 更新项目预览URL
                    project.preview_url = preview_url
                    self.db.commit()
                    
                    return {
                        "success": True,
                        "preview_url": preview_url,
                        "stdout": "HTML file created successfully",
                        "stderr": "",
                        "note": "Basic preview created for HTML file"
                    }
                else:
                    # 对于其他类型的文件，返回部分成功
                    return {
                        "success": False,
                        "error": f"Execution failed: {str(exec_error)}",
                        "preview_url": None,
                        "stdout": "",
                        "stderr": str(exec_error),
                        "note": "Files created but execution failed"
                    }
            
            # 如果有预览URL，保存到项目
            if execution_result.get("preview_url"):
                project.preview_url = execution_result["preview_url"]
                self.db.commit()
                logger.info(f"Updated project preview URL: {execution_result['preview_url']}")
            
            return execution_result
            
        except Exception as e:
            logger.error(f"Project execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "preview_url": None,
                "stdout": "",
                "stderr": str(e)
            }
    
    async def _finalize_project_creation(
        self,
        project: Project,
        workspace_result: Dict[str, Any],
        execution_result: Dict[str, Any]
    ):
        """完成项目创建"""
        
        # 判断项目最终状态
        if execution_result.get("success", False):
            project.status = "active"
            if execution_result.get("preview_url"):
                project.preview_url = execution_result["preview_url"]
            logger.info(f"Project {project.id} completed successfully")
            
        elif execution_result.get("preview_url"):
            project.status = "active"
            project.preview_url = execution_result["preview_url"]
            logger.info(f"Project {project.id} completed with preview (partial success)")
            
        elif workspace_result.get("file_count", 0) > 0:
            project.status = "active"
            logger.info(f"Project {project.id} completed with files created (execution failed)")
            
        else:
            project.status = "error"
            logger.error(f"Project {project.id} creation failed completely")
        
        self.db.commit()
        logger.info(f"Finalized project {project.id} with status: {project.status}")
    
    # ==================== 项目上下文和查询 ====================
    
    async def get_project_context(self, project_id: str) -> Dict[str, Any]:
        """获取项目上下文信息"""
        
        try:
            # 查询项目基本信息
            project = self.db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return {}
            
            # 查询项目文件
            project_files = self.db.query(ProjectFile).filter(
                ProjectFile.project_id == project_id
            ).all()
            
            # 构建文件列表
            file_list = []
            for file in project_files:
                file_list.append({
                    "path": file.file_path,
                    "type": file.file_type,
                    "language": file.language,
                    "size": file.size,
                    "is_entry_point": file.is_entry_point,
                    "created_at": file.created_at.isoformat()
                })
            
            return {
                "project_info": {
                    "id": str(project.id),
                    "name": project.name,
                    "description": project.description,
                    "type": project.project_type,
                    "status": project.status,
                    "created_at": project.created_at.isoformat(),
                    "preview_url": project.preview_url
                },
                "project_files": [f["path"] for f in file_list],
                "project_type": project.project_type,
                "tech_stack": project.tech_stack or [],
                "recent_executions": [],
                "file_details": file_list
            }
            
        except Exception as e:
            logger.error(f"Failed to get project context: {e}")
            return {}
    
    async def get_project_detail(self, project_id: str) -> Optional[Project]:
        """获取项目详情"""
        
        try:
            project = self.db.query(Project).filter(Project.id == project_id).first()
            return project
        except Exception as e:
            logger.error(f"Failed to get project detail: {e}")
            return None
    
    async def get_project_preview_status(self, project_id: str) -> Dict[str, Any]:
        """获取项目预览状态"""
        
        try:
            project = self.db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return {"success": False, "error": "Project not found"}
            
            return {
                "success": True,
                "project_id": str(project.id),
                "preview_url": project.preview_url,
                "status": project.status,
                "workspace_path": project.workspace_path
            }
        except Exception as e:
            logger.error(f"Failed to get project preview status: {e}")
            return {"success": False, "error": str(e)}
    
    async def list_projects(self, user_id: str, status: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """获取用户项目列表"""
        
        try:
            query = self.db.query(Project).filter(Project.user_id == user_id)
            
            if status:
                query = query.filter(Project.status == status)
            
            projects = query.order_by(Project.created_at.desc()).limit(limit).all()
            
            return [
                {
                    "id": str(project.id),
                    "name": project.name,
                    "description": project.description,
                    "type": project.project_type,
                    "status": project.status,
                    "created_at": project.created_at.isoformat(),
                    "updated_at": project.updated_at.isoformat(),
                    "preview_url": project.preview_url,
                    "file_count": project.file_count,
                    "size": project.size or 0
                }
                for project in projects
            ]
        except Exception as e:
            logger.error(f"Failed to list projects: {e}")
            return []
    
    # ==================== 工具方法 ====================
    
    def _detect_file_type(self, file_path: str, file_info: Dict[str, Any]) -> str:
        """检测文件类型"""
        import os
        
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".html": "html",
            ".htm": "html",
            ".css": "css",
            ".json": "json",
            ".md": "markdown",
            ".txt": "text",
            ".sh": "shell",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".xml": "xml",
            ".sql": "sql"
        }
        
        ext = os.path.splitext(file_path)[1].lower()
        return ext_map.get(ext, "text")
    
    def _detect_language(self, file_path: str) -> str:
        """检测编程语言"""
        import os
        
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".html": "html",
            ".htm": "html",
            ".css": "css",
            ".json": "json",
            ".md": "markdown",
            ".sh": "bash",
            ".bash": "bash",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".xml": "xml",
            ".sql": "sql"
        }
        
        ext = os.path.splitext(file_path)[1].lower()
        return ext_map.get(ext, "text")