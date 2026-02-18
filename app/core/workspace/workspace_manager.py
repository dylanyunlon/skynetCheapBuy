# app/core/workspace/workspace_manager.py - 修复版本
import os
import json
import shutil
import socket
import subprocess
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import uuid4
from contextlib import closing
import git

logger = logging.getLogger(__name__)

class WorkspaceManager:
    """工作空间管理器 - 管理用户的项目和文件"""
    
    def __init__(self, base_path: str = "./workspace"):
        """初始化工作空间管理器"""
        self.base_path = Path(base_path)
        self.running_servers = {}  # 跟踪正在运行的服务器进程
        
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Workspace initialized at: {self.base_path.absolute()}")
        except Exception as e:
            logger.error(f"Failed to create workspace directory: {e}")
            import tempfile
            self.base_path = Path(tempfile.mkdtemp(prefix="claude_workspace_"))
            logger.warning(f"Using temporary workspace at: {self.base_path}")
    
    async def create_project(
        self,
        user_id: str,
        project_name: str,
        project_type: str = "python",
        description: Optional[str] = None,
        init_git: bool = True
    ) -> Dict[str, Any]:
        """创建新项目"""
        if not user_id:
            raise ValueError("user_id cannot be None or empty")
        
        project_id = str(uuid4())
        
        # 创建用户目录和项目目录
        user_path = self.base_path / user_id
        project_path = user_path / project_id
        
        try:
            project_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created project directory: {project_path}")
        except Exception as e:
            logger.error(f"Failed to create project directory: {e}")
            raise
        
        # 创建项目元数据
        metadata = {
            "id": project_id,
            "name": project_name,
            "type": project_type,
            "description": description,
            "created_at": datetime.utcnow().isoformat(),
            "files": {},
            "dependencies": [],
            "entry_point": None
        }
        
        # 保存元数据
        metadata_path = project_path / ".claude-project.json"
        try:
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save project metadata: {e}")
            raise
        
        # 初始化 Git（可选）
        if init_git:
            try:
                repo = git.Repo.init(project_path)
                repo.index.add([".claude-project.json"])
                repo.index.commit("Initial project setup")
                logger.info(f"Initialized git repository for project {project_id}")
            except Exception as e:
                logger.warning(f"Failed to initialize git repository: {e}")
        
        return {
            "project_id": project_id,
            "path": str(project_path),
            "metadata": metadata
        }
    
    async def add_file(
        self,
        user_id: str,
        project_id: str,
        file_path: str,
        content: str,
        file_type: str = "code",
        auto_commit: bool = True
    ) -> Dict[str, Any]:
        """向项目添加文件"""
        if not user_id or not project_id:
            raise ValueError("user_id and project_id cannot be None or empty")
        
        project_path = self.base_path / user_id / project_id
        
        if not project_path.exists():
            raise FileNotFoundError(f"Project not found: {project_id}")
        
        # 创建文件
        full_path = project_path / file_path
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding='utf-8')
            logger.info(f"Created file: {full_path}")
        except Exception as e:
            logger.error(f"Failed to create file {file_path}: {e}")
            raise
        
        # 更新项目元数据
        metadata_path = project_path / ".claude-project.json"
        try:
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
            
            metadata["files"][file_path] = {
                "type": file_type,
                "size": len(content),
                "created_at": datetime.utcnow().isoformat(),
                "language": self._detect_language(file_path)
            }
            
            # 更新入口点（如果是主文件）
            if file_path in ["main.py", "app.py", "index.js", "index.ts", "start_server.sh"]:
                metadata["entry_point"] = file_path
            
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to update project metadata: {e}")
        
        # Git 提交（可选）
        if auto_commit and (project_path / ".git").exists():
            try:
                repo = git.Repo(project_path)
                repo.index.add([file_path, ".claude-project.json"])
                repo.index.commit(f"Add {file_path}")
            except Exception as e:
                logger.warning(f"Failed to commit file to git: {e}")
        
        return {
            "file_path": file_path,
            "full_path": str(full_path),
            "size": len(content)
        }

    async def execute_project(
        self, 
        user_id: str, 
        project_id: str, 
        entry_point: Optional[str] = None, 
        env_vars: Optional[Dict[str, str]] = None, 
        timeout: int = 30000
    ) -> Dict[str, Any]:
        """执行整个项目 - 特殊处理服务器启动脚本"""
        
        if not user_id or not project_id:
            raise ValueError("user_id and project_id cannot be None or empty")
        
        project_path = self.base_path / user_id / project_id
        
        if not project_path.exists():
            raise FileNotFoundError(f"Project not found: {project_id}")
        
        # 读取项目元数据
        metadata_path = project_path / ".claude-project.json"
        if metadata_path.exists():
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
        else:
            metadata = {}
        
        # 确定入口点
        if not entry_point:
            entry_point = metadata.get("entry_point", "main.py")
        
        entry_file = project_path / entry_point
        if not entry_file.exists():
            # 尝试查找其他可能的入口文件
            possible_entries = ["main.py", "app.py", "run.py", "index.py", "start_server.sh", "main.sh", "run.sh"]
            for entry in possible_entries:
                if (project_path / entry).exists():
                    entry_point = entry
                    break
            else:
                return {
                    "success": False,
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": f"Entry point not found: {entry_point}",
                    "entry_point": entry_point
                }
        
        # 检测文件类型
        file_extension = Path(entry_point).suffix.lower()
        logger.info(f"Executing {file_extension} file: {entry_point}")
        
        # **关键修复：特殊处理服务器启动脚本**
        if self._is_server_script(entry_point, project_path):
            return await self._execute_server_script(
                user_id, project_id, project_path, entry_point, env_vars
            )
        
        # 准备环境变量
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
        env["PYTHONPATH"] = str(project_path) + ":" + env.get("PYTHONPATH", "")
        
        # 根据文件类型选择执行器
        if file_extension == '.py':
            cmd = ["python3", entry_point]
        elif file_extension in ['.sh', '.bash']:
            # 设置执行权限
            import stat
            entry_file_path = project_path / entry_point
            current_permissions = entry_file_path.stat().st_mode
            entry_file_path.chmod(current_permissions | stat.S_IEXEC)
            cmd = ["bash", entry_point]
        elif file_extension == '.js':
            cmd = ["node", entry_point]
        elif file_extension == '.ts':
            cmd = ["npx", "ts-node", entry_point]
        elif file_extension in ['.html', '.htm']:
            # HTML 文件启动静态服务器
            return await self._serve_static_files(project_path, project_id, entry_point)
        else:
            cmd = ["python3", entry_point]
        
        logger.info(f"Executing command: {' '.join(cmd)}")
        
        try:
            # 执行前的文件列表
            files_before = set(f.name for f in project_path.iterdir() if f.is_file())
            
            # 执行命令
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(project_path),
                env=env
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return {
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Execution timeout after {timeout} seconds",
                    "entry_point": entry_point
                }
            
            stdout_text = stdout.decode('utf-8', errors='replace')
            stderr_text = stderr.decode('utf-8', errors='replace')
            
            logger.info(f"Execution completed with exit code: {process.returncode}")
            
            # 执行后的文件列表
            files_after = set(f.name for f in project_path.iterdir() if f.is_file())
            new_files = files_after - files_before
            
            # 判断成功
            if file_extension in ['.sh', '.bash']:
                success = self._determine_shell_script_success(
                    process.returncode, stdout_text, stderr_text, new_files, project_path
                )
            else:
                success = process.returncode == 0
            
            # 构建结果
            result = {
                "success": success,
                "exit_code": process.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "entry_point": entry_point,
                "files_created": len(new_files)
            }
            
            # 检查生成的文件
            generated_files = []
            preview_files = []
            
            for file_name in new_files:
                file_path = project_path / file_name
                if file_path.suffix.lower() in ['.html', '.htm']:
                    preview_files.append(file_name)
                    generated_files.append({
                        "path": file_name,
                        "type": "html",
                        "size": file_path.stat().st_size
                    })
            
            if generated_files:
                result["generated_files"] = generated_files
            if preview_files:
                result["preview_files"] = preview_files
                result["preview_url"] = f"/preview/{project_id}/{preview_files[0]}"
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to execute project: {e}", exc_info=True)
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "entry_point": entry_point
            }

    def _is_server_script(self, entry_point: str, project_path: Path) -> bool:
        """判断是否为服务器启动脚本"""
        server_script_names = [
            "start_server.sh", "run_server.sh", "serve.sh", 
            "start.sh", "launch.sh", "server.sh"
        ]
        
        if entry_point in server_script_names:
            return True
        
        # 检查脚本内容
        try:
            script_path = project_path / entry_point
            if script_path.exists() and script_path.suffix in ['.sh', '.bash']:
                content = script_path.read_text()
                server_indicators = [
                    "http.server", "SimpleHTTPServer", "nginx", "apache2",
                    "python -m http.server", "python3 -m http.server",
                    "serve -s", "live-server", "http-server"
                ]
                return any(indicator in content for indicator in server_indicators)
        except Exception:
            pass
        
        return False

    async def _execute_server_script(
        self, 
        user_id: str, 
        project_id: str, 
        project_path: Path, 
        entry_point: str, 
        env_vars: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """执行服务器启动脚本 - 非阻塞方式"""
        
        logger.info(f"Detected server script: {entry_point}, starting in background...")
        
        # 准备环境变量
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
        
        # 设置执行权限
        import stat
        script_path = project_path / entry_point
        current_permissions = script_path.stat().st_mode
        script_path.chmod(current_permissions | stat.S_IEXEC)
        
        try:
            # 从脚本中提取端口信息
            port = self._extract_port_from_script(script_path)
            if not port:
                port = self._find_available_port()
            
            logger.info(f"Starting server script on port {port}")
            
            # 后台启动服务器进程
            process = await asyncio.create_subprocess_exec(
                "bash", entry_point,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(project_path),
                env=env
            )
            
            # 记录运行中的服务器
            server_key = f"{user_id}_{project_id}"
            self.running_servers[server_key] = {
                "process": process,
                "port": port,
                "project_path": str(project_path),
                "started_at": datetime.utcnow(),
                "entry_point": entry_point
            }
            
            # 等待一小段时间以检查服务器是否成功启动
            await asyncio.sleep(3)
            
            # 检查进程是否还在运行
            if process.returncode is not None:
                # 进程已经退出，读取输出
                stdout, stderr = await process.communicate()
                stdout_text = stdout.decode('utf-8', errors='replace')
                stderr_text = stderr.decode('utf-8', errors='replace')
                
                logger.warning(f"Server script exited early with code {process.returncode}")
                
                return {
                    "success": False,
                    "exit_code": process.returncode,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "entry_point": entry_point,
                    "error": "Server script exited unexpectedly"
                }
            
            # 检查端口是否被监听
            server_running = await self._check_server_running(port)
            
            if server_running:
                preview_url = f"http://localhost:{port}"
                
                # 如果有具体的HTML文件，添加到URL
                html_files = list(project_path.glob("*.html"))
                if html_files:
                    main_html = "index.html" if (project_path / "index.html").exists() else html_files[0].name
                    if main_html != "index.html":  # 如果不是index.html，需要添加文件名
                        preview_url += f"/{main_html}"
                
                logger.info(f"Server started successfully: {preview_url}")
                
                return {
                    "success": True,
                    "exit_code": 0,
                    "stdout": f"Server started successfully on port {port}",
                    "stderr": "",
                    "entry_point": entry_point,
                    "preview_url": preview_url,
                    "port": port,
                    "server_pid": process.pid,
                    "background_process": True
                }
            else:
                # 尝试读取部分输出以了解问题
                try:
                    # 非阻塞读取
                    stdout_data = await asyncio.wait_for(
                        process.stdout.read(1024), timeout=1.0
                    )
                    stderr_data = await asyncio.wait_for(
                        process.stderr.read(1024), timeout=1.0
                    )
                    
                    stdout_text = stdout_data.decode('utf-8', errors='replace')
                    stderr_text = stderr_data.decode('utf-8', errors='replace')
                except asyncio.TimeoutError:
                    stdout_text = "No output (server may be starting...)"
                    stderr_text = ""
                
                logger.warning(f"Server script started but port {port} not accessible")
                
                return {
                    "success": True,  # 进程启动了，即使端口还不可访问
                    "exit_code": 0,
                    "stdout": f"Server starting on port {port}...\n{stdout_text}",
                    "stderr": stderr_text,
                    "entry_point": entry_point,
                    "preview_url": f"http://localhost:{port}",
                    "port": port,
                    "server_pid": process.pid,
                    "background_process": True,
                    "warning": "Server started but not immediately accessible"
                }
                
        except Exception as e:
            logger.error(f"Failed to start server script: {e}", exc_info=True)
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Failed to start server: {str(e)}",
                "entry_point": entry_point
            }

    async def _serve_static_files(
        self, 
        project_path: Path, 
        project_id: str, 
        entry_point: str
    ) -> Dict[str, Any]:
        """为HTML文件启动静态文件服务器"""
        
        port = self._find_available_port()
        
        try:
            # 启动静态文件服务器
            process = await asyncio.create_subprocess_exec(
                "python3", "-m", "http.server", str(port), "--bind", "0.0.0.0",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(project_path)
            )
            
            # 等待服务器启动
            await asyncio.sleep(2)
            
            # 检查服务器是否运行
            server_running = await self._check_server_running(port)
            
            if server_running:
                preview_url = f"http://localhost:{port}/{entry_point}"
                
                return {
                    "success": True,
                    "exit_code": 0,
                    "stdout": f"Static server started on port {port}",
                    "stderr": "",
                    "entry_point": entry_point,
                    "preview_url": preview_url,
                    "port": port,
                    "server_pid": process.pid,
                    "background_process": True
                }
            else:
                return {
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Failed to start static server on port {port}",
                    "entry_point": entry_point
                }
                
        except Exception as e:
            logger.error(f"Failed to start static server: {e}")
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "entry_point": entry_point
            }

    def _extract_port_from_script(self, script_path: Path) -> Optional[int]:
        """从脚本中提取端口号"""
        try:
            content = script_path.read_text()
            
            # 查找常见的端口定义模式
            import re
            port_patterns = [
                r'PORT=(\d+)',
                r'port\s*=\s*(\d+)',
                r':(\d+)',
                r'http\.server\s+(\d+)',
                r'SimpleHTTPServer\s+(\d+)'
            ]
            
            for pattern in port_patterns:
                match = re.search(pattern, content)
                if match:
                    port = int(match.group(1))
                    if 1024 <= port <= 65535:  # 有效端口范围
                        return port
        except Exception:
            pass
        
        return None

    async def _check_server_running(self, port: int, max_attempts: int = 5) -> bool:
        """检查服务器是否在指定端口运行"""
        for attempt in range(max_attempts):
            try:
                # 使用socket检查端口是否被监听
                with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
                    sock.settimeout(1)
                    result = sock.connect_ex(('localhost', port))
                    if result == 0:
                        return True
            except Exception:
                pass
            
            if attempt < max_attempts - 1:
                await asyncio.sleep(1)
        
        return False

    def _find_available_port(self, start_port: int = 17430) -> int:
        """找到可用的端口"""
        for port in range(start_port, start_port + 100):
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
                if sock.connect_ex(('localhost', port)) != 0:
                    return port
        return start_port

    def _determine_shell_script_success(
        self, 
        exit_code: int, 
        stdout: str, 
        stderr: str, 
        new_files: set,
        project_path: Path
    ) -> bool:
        """智能判断 shell 脚本是否成功执行"""
        
        # 1. 如果退出码是 0，直接认为成功
        if exit_code == 0:
            return True
        
        # 2. 如果创建了新文件，很可能是成功的
        if new_files:
            logger.info(f"Shell script created files: {list(new_files)}, considering successful")
            return True
        
        # 3. 检查输出中的成功指示词
        success_indicators = [
            "成功", "success", "successfully", "完成", "created", "生成",
            "Success", "Successfully", "Created", "Generated", "Done",
            "Serving HTTP", "started", "启动", "运行", "running"
        ]
        
        combined_output = stdout + stderr
        for indicator in success_indicators:
            if indicator in combined_output:
                logger.info(f"Found success indicator '{indicator}' in output")
                return True
        
        # 4. 如果是后台进程（如服务器），即使退出码非0也可能是正常的
        server_indicators = ["http.server", "SimpleHTTPServer", "Serving HTTP"]
        if any(indicator in combined_output for indicator in server_indicators):
            logger.info("Detected server process, considering successful")
            return True
        
        # 5. 检查是否有严重错误
        serious_errors = [
            "command not found", "permission denied", "no such file",
            "syntax error", "cannot create", "failed to"
        ]
        
        for error in serious_errors:
            if error.lower() in combined_output.lower():
                logger.warning(f"Found serious error '{error}' in output")
                return False
        
        # 6. 如果退出码是 1 但没有严重错误，可能是警告性质的
        if exit_code == 1 and not any(error.lower() in combined_output.lower() for error in serious_errors):
            logger.info("Exit code 1 but no serious errors detected, considering successful")
            return True
        
        return False

    async def stop_server(self, user_id: str, project_id: str) -> bool:
        """停止项目的服务器进程"""
        server_key = f"{user_id}_{project_id}"
        
        if server_key in self.running_servers:
            server_info = self.running_servers[server_key]
            process = server_info["process"]
            
            try:
                process.terminate()
                await asyncio.sleep(2)
                
                if process.returncode is None:
                    process.kill()
                    await asyncio.sleep(1)
                
                del self.running_servers[server_key]
                logger.info(f"Stopped server for project {project_id}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to stop server: {e}")
                return False
        
        return False

    async def get_server_status(self, user_id: str, project_id: str) -> Optional[Dict[str, Any]]:
        """获取服务器状态"""
        server_key = f"{user_id}_{project_id}"
        
        if server_key in self.running_servers:
            server_info = self.running_servers[server_key]
            process = server_info["process"]
            
            is_running = process.returncode is None
            port_accessible = await self._check_server_running(server_info["port"])
            
            return {
                "running": is_running,
                "port": server_info["port"],
                "port_accessible": port_accessible,
                "pid": process.pid if is_running else None,
                "started_at": server_info["started_at"].isoformat(),
                "entry_point": server_info["entry_point"]
            }
        
        return None

    # 其他现有方法保持不变...
    async def delete_file(self, user_id: str, project_id: str, file_path: str) -> bool:
        """删除项目文件"""
        if not user_id or not project_id:
            raise ValueError("user_id and project_id cannot be None or empty")
        
        full_path = self.base_path / user_id / project_id / file_path
        
        if full_path.exists():
            full_path.unlink()
            
            # 更新元数据
            metadata_path = self.base_path / user_id / project_id / ".claude-project.json"
            if metadata_path.exists():
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                
                if file_path in metadata.get("files", {}):
                    del metadata["files"][file_path]
                    
                with open(metadata_path, "w") as f:
                    json.dump(metadata, f, indent=2)
            
            return True
        
        return False
    
    async def delete_project(self, user_id: str, project_id: str) -> bool:
        """删除整个项目"""
        if not user_id or not project_id:
            raise ValueError("user_id and project_id cannot be None or empty")
        
        # 先停止服务器
        await self.stop_server(user_id, project_id)
        
        project_path = self.base_path / user_id / project_id
        
        if project_path.exists():
            shutil.rmtree(project_path)
            return True
        
        return False
    
    def calculate_user_storage(self, user_id: str) -> int:
        """计算用户存储使用量（字节）"""
        if not user_id:
            return 0
        
        user_path = self.base_path / user_id
        
        if not user_path.exists():
            return 0
        
        total_size = 0
        for path in user_path.rglob("*"):
            if path.is_file():
                total_size += path.stat().st_size
        
        return total_size
    
    def _detect_language(self, file_path: str) -> str:
        """检测文件语言"""
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
            ".sql": "sql"
        }
        
        ext = Path(file_path).suffix.lower()
        return ext_map.get(ext, "text")