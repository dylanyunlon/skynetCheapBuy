import aiohttp
import asyncio
import json
from typing import Dict, Any, Optional, AsyncGenerator
from pathlib import Path
import websockets
import sys

class ClaudeCodeClient:
    """Claude Code API 客户端"""
    
    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.session = None
        self.ws = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
        if self.ws:
            await self.ws.close()
    
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    async def create_project(
        self,
        request: str,
        model: str = "claude-opus-4-5-20251101",
        auto_execute: bool = True,
        max_debug_attempts: int = 3
    ) -> Dict[str, Any]:
        """创建新项目"""
        async with self.session.post(
            f"{self.base_url}/api/v2/agent/create-project",
            json={
                "prompt": request,
                "model": model,
                "auto_execute": auto_execute,
                "max_debug_attempts": max_debug_attempts
            },
            headers=self._headers()
        ) as response:
            if response.status != 200:
                error = await response.text()
                raise Exception(f"Failed to create project: {error}")
            return await response.json()
    
    async def execute_project(
        self,
        project_id: str,
        max_debug_attempts: int = 3,
        env_vars: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """执行项目"""
        async with self.session.post(
            f"{self.base_url}/api/v2/agent/execute-project/{project_id}",
            json={
                "max_debug_attempts": max_debug_attempts,
                "env_vars": env_vars or {}
            },
            headers=self._headers()
        ) as response:
            if response.status != 200:
                error = await response.text()
                raise Exception(f"Failed to execute project: {error}")
            return await response.json()
    
    async def get_file_content(
        self,
        project_id: str,
        file_path: str
    ) -> str:
        """获取文件内容"""
        async with self.session.get(
            f"{self.base_url}/api/v2/workspace/{project_id}/files/{file_path}",
            headers=self._headers()
        ) as response:
            if response.status != 200:
                error = await response.text()
                raise Exception(f"Failed to get file: {error}")
            data = await response.json()
            return data["content"]
    
    async def edit_file(
        self,
        project_id: str,
        file_path: str,
        edit_prompt: str
    ) -> Dict[str, Any]:
        """编辑文件"""
        async with self.session.post(
            f"{self.base_url}/api/v2/agent/edit-file/{project_id}",
            json={
                "file_path": file_path,
                "prompt": edit_prompt
            },
            headers=self._headers()
        ) as response:
            if response.status != 200:
                error = await response.text()
                raise Exception(f"Failed to edit file: {error}")
            return await response.json()
    
    async def list_projects(self) -> List[Dict[str, Any]]:
        """列出项目"""
        async with self.session.get(
            f"{self.base_url}/api/v2/agent/projects",
            headers=self._headers()
        ) as response:
            if response.status != 200:
                error = await response.text()
                raise Exception(f"Failed to list projects: {error}")
            return await response.json()
    
    async def export_project(
        self,
        project_id: str,
        output_dir: str
    ) -> None:
        """导出项目到本地"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 获取项目文件列表
        async with self.session.get(
            f"{self.base_url}/api/v2/workspace/{project_id}/files",
            headers=self._headers()
        ) as response:
            if response.status != 200:
                raise Exception("Failed to get project files")
            files = await response.json()
        
        # 下载每个文件
        for file_info in files:
            file_path = file_info["path"]
            content = await self.get_file_content(project_id, file_path)
            
            local_path = output_path / file_path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(content)
    
    async def connect_terminal(
        self,
        project_id: str
    ) -> 'TerminalSession':
        """连接到项目终端"""
        ws_url = self.base_url.replace("http", "ws")
        ws_url = f"{ws_url}/api/v2/terminal/{project_id}"
        
        return TerminalSession(ws_url, self.token)


class TerminalSession:
    """终端会话"""
    
    def __init__(self, ws_url: str, token: Optional[str] = None):
        self.ws_url = ws_url
        self.token = token
        self.ws = None
    
    async def __aenter__(self):
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        
        self.ws = await websockets.connect(
            self.ws_url,
            extra_headers=headers
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.ws:
            await self.ws.close()
    
    async def send_command(self, command: str):
        """发送命令"""
        await self.ws.send(json.dumps({
            "type": "command",
            "data": command
        }))
    
    async def receive_output(self) -> AsyncGenerator[Dict[str, Any], None]:
        """接收输出"""
        async for message in self.ws:
            data = json.loads(message)
            yield data