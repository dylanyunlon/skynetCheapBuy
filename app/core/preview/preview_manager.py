import asyncio
import logging
import socket
from pathlib import Path
from typing import Dict, Optional, Any, List
from app.config import settings

logger = logging.getLogger(__name__)

class PreviewManager:
    """预览管理器 - 提供类似 Lovable.ai 的实时预览"""
    
    def __init__(self):
        self.preview_servers = {}
        
    async def start_preview(self, project_path: Path, project_id: str) -> str:
        """启动项目预览服务"""
        
        # 检测项目类型
        if self._is_web_project(project_path):
            return await self._start_web_preview(project_path, project_id)
        elif self._is_static_project(project_path):
            return await self._start_static_preview(project_path, project_id)
        else:
            return await self._start_output_preview(project_path, project_id)
    
    def _is_web_project(self, project_path: Path) -> bool:
        """检测是否为 web 项目"""
        indicators = [
            "package.json",
            "index.html",
            "app.py",
            "server.js"
        ]
        return any((project_path / indicator).exists() for indicator in indicators)
    
    def _is_static_project(self, project_path: Path) -> bool:
        """检测是否为静态项目"""
        html_files = list(project_path.glob("*.html"))
        return len(html_files) > 0
    
    def _get_available_port(self) -> int:
        """获取可用端口 - 使用配置中的端口范围"""
        return settings.get_available_preview_port()
    
    async def _start_static_preview(self, project_path: Path, project_id: str) -> str:
        """启动静态文件预览"""
        port = self._get_available_port()
        
        try:
            # 启动简单的静态文件服务器
            server_process = await asyncio.create_subprocess_exec(
                "python3", "-m", "http.server", str(port),
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.preview_servers[project_id] = {
                "process": server_process,
                "port": port,
                "type": "static",
                "project_path": str(project_path)
            }
            
            # 生成预览URL - 使用配置中的外网IP
            preview_url = settings.get_preview_url(port)
            
            logger.info(f"Started static preview for project {project_id} on {preview_url}")
            return preview_url
            
        except Exception as e:
            logger.error(f"Failed to start static preview for project {project_id}: {e}")
            raise
    
    async def _start_web_preview(self, project_path: Path, project_id: str) -> str:
        """启动Web项目预览"""
        port = self._get_available_port()
        
        try:
            # 检查是否有package.json（Node.js项目）
            if (project_path / "package.json").exists():
                return await self._start_node_preview(project_path, project_id, port)
            
            # 检查是否有app.py（Python Flask/FastAPI项目）
            elif (project_path / "app.py").exists():
                return await self._start_python_preview(project_path, project_id, port)
            
            # 默认作为静态项目处理
            else:
                return await self._start_static_preview(project_path, project_id)
                
        except Exception as e:
            logger.error(f"Failed to start web preview for project {project_id}: {e}")
            # 降级到静态预览
            return await self._start_static_preview(project_path, project_id)
    
    async def _start_node_preview(self, project_path: Path, project_id: str, port: int) -> str:
        """启动Node.js项目预览"""
        try:
            # 尝试启动开发服务器
            server_process = await asyncio.create_subprocess_exec(
                "npm", "run", "dev", "--", "--port", str(port),
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**dict(os.environ), "PORT": str(port)}
            )
            
            self.preview_servers[project_id] = {
                "process": server_process,
                "port": port,
                "type": "node",
                "project_path": str(project_path)
            }
            
            preview_url = settings.get_preview_url(port)
            logger.info(f"Started Node.js preview for project {project_id} on {preview_url}")
            return preview_url
            
        except Exception as e:
            logger.warning(f"Failed to start Node.js dev server, falling back to static: {e}")
            return await self._start_static_preview(project_path, project_id)
    
    async def _start_python_preview(self, project_path: Path, project_id: str, port: int) -> str:
        """启动Python项目预览"""
        try:
            # 尝试启动Python服务器
            server_process = await asyncio.create_subprocess_exec(
                "python3", "app.py", "--host", "0.0.0.0", "--port", str(port),
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**dict(os.environ), "PORT": str(port)}
            )
            
            self.preview_servers[project_id] = {
                "process": server_process,
                "port": port,
                "type": "python",
                "project_path": str(project_path)
            }
            
            preview_url = settings.get_preview_url(port)
            logger.info(f"Started Python preview for project {project_id} on {preview_url}")
            return preview_url
            
        except Exception as e:
            logger.warning(f"Failed to start Python server, falling back to static: {e}")
            return await self._start_static_preview(project_path, project_id)
    
    async def _start_output_preview(self, project_path: Path, project_id: str) -> str:
        """为输出结果创建预览"""
        port = self._get_available_port()
        
        try:
            # 创建简单的输出预览页面
            output_file = project_path / "output.html"
            if not output_file.exists():
                # 创建基本的输出展示页面
                html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>项目输出 - {project_id}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.6;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #eee;
        }}
        .output-section {{
            margin: 20px 0;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 5px;
            border-left: 4px solid #007bff;
        }}
        pre {{
            background: #2d3748;
            color: #e2e8f0;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        .file-list {{
            list-style: none;
            padding: 0;
        }}
        .file-list li {{
            padding: 8px 0;
            border-bottom: 1px solid #eee;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>项目输出预览</h1>
            <p>项目ID: {project_id}</p>
        </div>
        
        <div class="output-section">
            <h3>项目文件</h3>
            <ul class="file-list">
"""
                
                # 列出项目文件
                for file_path in project_path.rglob("*"):
                    if file_path.is_file() and file_path.name != "output.html":
                        relative_path = file_path.relative_to(project_path)
                        html_content += f"                <li>{relative_path}</li>\n"
                
                html_content += """
            </ul>
        </div>
        
        <div class="output-section">
            <h3>说明</h3>
            <p>这是一个自动生成的项目输出预览页面。如果项目包含可执行的Web应用，请检查项目目录中的具体文件。</p>
        </div>
    </div>
</body>
</html>
"""
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
            
            # 启动静态服务器
            return await self._start_static_preview(project_path, project_id)
            
        except Exception as e:
            logger.error(f"Failed to create output preview for project {project_id}: {e}")
            raise
    
    async def stop_preview(self, project_id: str) -> bool:
        """停止项目预览"""
        if project_id not in self.preview_servers:
            return False
        
        try:
            server_info = self.preview_servers[project_id]
            process = server_info["process"]
            
            # 终止进程
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            
            # 清理记录
            del self.preview_servers[project_id]
            
            logger.info(f"Stopped preview for project {project_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop preview for project {project_id}: {e}")
            return False
    
    def get_preview_info(self, project_id: str) -> Optional[Dict[str, Any]]:
        """获取预览信息"""
        if project_id not in self.preview_servers:
            return None
        
        server_info = self.preview_servers[project_id]
        
        return {
            "project_id": project_id,
            "port": server_info["port"],
            "type": server_info["type"],
            "url": settings.get_preview_url(server_info["port"]),
            "status": "running" if server_info["process"].returncode is None else "stopped",
            "project_path": server_info["project_path"]
        }
    
    def list_active_previews(self) -> List[Dict[str, Any]]:
        """列出所有活跃的预览"""
        return [
            self.get_preview_info(project_id)
            for project_id in self.preview_servers.keys()
        ]
    
    async def cleanup_stopped_previews(self):
        """清理已停止的预览服务"""
        stopped_projects = []
        
        for project_id, server_info in self.preview_servers.items():
            if server_info["process"].returncode is not None:
                stopped_projects.append(project_id)
        
        for project_id in stopped_projects:
            del self.preview_servers[project_id]
            logger.info(f"Cleaned up stopped preview for project {project_id}")
    
    def __del__(self):
        """析构函数，清理所有预览服务"""
        for project_id in list(self.preview_servers.keys()):
            try:
                server_info = self.preview_servers[project_id]
                if server_info["process"].returncode is None:
                    server_info["process"].terminate()
            except Exception:
                pass