import asyncio
import os
import pty
import select
import struct
import fcntl
import termios
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class PTYProcess:
    """PTY 进程封装"""
    
    def __init__(self, master_fd: int, slave_fd: int, pid: int):
        self.master_fd = master_fd
        self.slave_fd = slave_fd
        self.pid = pid
        self.running = True
    
    async def write(self, data: str):
        """写入数据到 PTY"""
        try:
            os.write(self.master_fd, data.encode())
        except OSError as e:
            logger.error(f"Error writing to PTY: {e}")
            self.running = False
    
    async def read(self) -> Optional[str]:
        """从 PTY 读取数据"""
        try:
            # 使用 select 检查是否有数据可读
            readable, _, _ = select.select([self.master_fd], [], [], 0.1)
            if readable:
                data = os.read(self.master_fd, 4096)
                return data.decode('utf-8', errors='replace')
            return None
        except OSError as e:
            logger.error(f"Error reading from PTY: {e}")
            self.running = False
            return None
    
    async def send_signal(self, signal_name: str):
        """发送信号到进程"""
        import signal
        
        signal_map = {
            "SIGINT": signal.SIGINT,
            "SIGTERM": signal.SIGTERM,
            "SIGKILL": signal.SIGKILL,
        }
        
        if signal_name in signal_map:
            os.kill(self.pid, signal_map[signal_name])


class PTYManager:
    """PTY 管理器"""
    
    async def create_pty(
        self,
        command: str = "/bin/bash",
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ) -> PTYProcess:
        """创建新的 PTY"""
        # 创建 PTY
        master_fd, slave_fd = pty.openpty()
        
        # Fork 进程
        pid = os.fork()
        
        if pid == 0:  # 子进程
            # 设置为会话领导
            os.setsid()
            
            # 使 slave 成为控制终端
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY)
            
            # 复制文件描述符
            os.dup2(slave_fd, 0)  # stdin
            os.dup2(slave_fd, 1)  # stdout
            os.dup2(slave_fd, 2)  # stderr
            
            # 关闭不需要的文件描述符
            os.close(master_fd)
            os.close(slave_fd)
            
            # 设置工作目录
            if cwd:
                os.chdir(cwd)
            
            # 设置环境变量
            if env:
                os.environ.update(env)
            
            # 执行命令
            os.execv("/bin/bash", ["bash", "-l"])
            
        else:  # 父进程
            # 关闭 slave_fd
            os.close(slave_fd)
            
            # 设置为非阻塞模式
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            
            return PTYProcess(master_fd, slave_fd, pid)
    
    async def resize_pty(
        self,
        process: PTYProcess,
        rows: int,
        cols: int
    ):
        """调整 PTY 大小"""
        try:
            # 构建 winsize 结构
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(process.master_fd, termios.TIOCSWINSZ, winsize)
        except Exception as e:
            logger.error(f"Error resizing PTY: {e}")
    
    async def close_pty(self, process: PTYProcess):
        """关闭 PTY"""
        try:
            os.close(process.master_fd)
            # 等待子进程结束
            os.waitpid(process.pid, 0)
        except Exception as e:
            logger.error(f"Error closing PTY: {e}")