# app/api/websocket/terminal_ws.py
import asyncio
import json
import logging
import os
import pty
import select
import subprocess
import struct
import fcntl
import termios
from typing import Optional, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime

from app.dependencies import get_current_user_ws
from app.models.user import User
from app.models.workspace import Project
from app.db.session import SessionLocal
from app.core.workspace.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)

class TerminalSession:
    """终端会话管理器"""
    
    def __init__(self, project_id: str, user_id: str, project_path: str):
        self.project_id = project_id
        self.user_id = user_id
        self.project_path = project_path
        self.process = None
        self.master_fd = None
        self.slave_fd = None
        
    async def start(self) -> bool:
        """启动终端会话"""
        try:
            # 创建伪终端
            self.master_fd, self.slave_fd = pty.openpty()
            
            # 设置为非阻塞模式
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            
            # 启动 bash 进程
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["PYTHONPATH"] = self.project_path + ":" + env.get("PYTHONPATH", "")
            
            self.process = subprocess.Popen(
                ["/bin/bash"],
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                cwd=self.project_path,
                env=env,
                preexec_fn=os.setsid
            )
            
            # 发送初始化命令
            welcome_msg = f"# Project Terminal: {self.project_id}\n"
            welcome_msg += f"# Working Directory: {self.project_path}\n"
            welcome_msg += f"# Type 'exit' to close the terminal\n\n"
            os.write(self.master_fd, welcome_msg.encode())
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start terminal session: {e}")
            return False
    
    async def write(self, data: str):
        """写入数据到终端"""
        if self.master_fd:
            try:
                os.write(self.master_fd, data.encode())
            except Exception as e:
                logger.error(f"Failed to write to terminal: {e}")
    
    async def read(self) -> Optional[str]:
        """从终端读取数据"""
        if self.master_fd:
            try:
                # 使用 select 检查是否有数据可读
                r, _, _ = select.select([self.master_fd], [], [], 0)
                if r:
                    data = os.read(self.master_fd, 1024)
                    return data.decode('utf-8', errors='replace')
            except Exception as e:
                logger.error(f"Failed to read from terminal: {e}")
        return None
    
    async def resize(self, rows: int, cols: int):
        """调整终端大小"""
        if self.master_fd:
            try:
                # 设置终端窗口大小
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except Exception as e:
                logger.error(f"Failed to resize terminal: {e}")
    
    async def close(self):
        """关闭终端会话"""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.sleep(0.1)
                if self.process.poll() is None:
                    self.process.kill()
            except Exception as e:
                logger.error(f"Failed to terminate process: {e}")
        
        if self.master_fd:
            try:
                os.close(self.master_fd)
            except:
                pass
        
        if self.slave_fd:
            try:
                os.close(self.slave_fd)
            except:
                pass

async def terminal_endpoint(
    websocket: WebSocket,
    project_id: str,
    token: Optional[str]
):
    """WebSocket 终端端点"""
    await websocket.accept()
    
    db = SessionLocal()
    session = None
    
    try:
        # 认证用户
        user = await get_current_user_ws(websocket, token, db)
        if not user:
            await websocket.send_json({
                "type": "error",
                "message": "Authentication failed"
            })
            return
        
        # 验证项目权限
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.user_id == user.id
        ).first()
        
        if not project:
            await websocket.send_json({
                "type": "error",
                "message": "Project not found or access denied"
            })
            await websocket.close()
            return
        
        # 获取项目路径
        workspace_manager = WorkspaceManager()
        project_path = workspace_manager.base_path / str(user.id) / project_id
        
        if not project_path.exists():
            await websocket.send_json({
                "type": "error",
                "message": "Project workspace not found"
            })
            await websocket.close()
            return
        
        # 创建终端会话
        session = TerminalSession(project_id, str(user.id), str(project_path))
        
        if not await session.start():
            await websocket.send_json({
                "type": "error",
                "message": "Failed to start terminal session"
            })
            await websocket.close()
            return
        
        # 发送连接成功消息
        await websocket.send_json({
            "type": "connected",
            "project_id": project_id,
            "path": str(project_path)
        })
        
        # 创建读取任务
        async def read_terminal():
            """持续读取终端输出"""
            while True:
                try:
                    output = await session.read()
                    if output:
                        await websocket.send_json({
                            "type": "output",
                            "data": output
                        })
                    else:
                        await asyncio.sleep(0.01)
                except Exception as e:
                    logger.error(f"Error reading terminal: {e}")
                    break
        
        # 启动读取任务
        read_task = asyncio.create_task(read_terminal())
        
        # 处理 WebSocket 消息
        try:
            while True:
                message = await websocket.receive_json()
                msg_type = message.get("type")
                
                if msg_type == "input":
                    # 处理用户输入
                    data = message.get("data", "")
                    await session.write(data)
                    
                elif msg_type == "resize":
                    # 处理终端大小调整
                    rows = message.get("rows", 24)
                    cols = message.get("cols", 80)
                    await session.resize(rows, cols)
                    
                elif msg_type == "ping":
                    # 处理心跳
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    
                elif msg_type == "command":
                    # 处理特殊命令
                    command = message.get("command")
                    if command == "clear":
                        await session.write("\033[2J\033[H")
                    elif command == "interrupt":
                        await session.write("\x03")  # Ctrl+C
                    elif command == "eof":
                        await session.write("\x04")  # Ctrl+D
                        
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for project {project_id}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        finally:
            # 清理
            read_task.cancel()
            if session:
                await session.close()
                
    finally:
        db.close()
        try:
            await websocket.close()
        except:
            pass

# 全局会话管理器（可选）
class TerminalManager:
    """全局终端会话管理器"""
    
    def __init__(self):
        self.sessions: Dict[str, TerminalSession] = {}
    
    def add_session(self, session_id: str, session: TerminalSession):
        """添加会话"""
        self.sessions[session_id] = session
    
    def remove_session(self, session_id: str):
        """移除会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def get_session(self, session_id: str) -> Optional[TerminalSession]:
        """获取会话"""
        return self.sessions.get(session_id)
    
    async def cleanup_inactive_sessions(self):
        """清理不活跃的会话"""
        # 实现会话超时清理逻辑
        pass

# 创建全局管理器实例
terminal_manager = TerminalManager()