import os
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
import uuid
from datetime import datetime
import shlex
import json
import sys

class ScriptExecutor:
    """安全执行脚本的类"""
    
    def __init__(self, scripts_dir: str = "/app/generated_scripts"):
        self.scripts_dir = Path(scripts_dir)
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        
    async def save_script(
        self, 
        code: str, 
        language: str, 
        user_id: str,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """保存脚本到文件系统"""
        # 生成唯一文件名
        script_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 确定文件扩展名
        extensions = {
            "python": ".py",
            "bash": ".sh",
            "shell": ".sh",
            "javascript": ".js"
        }
        ext = extensions.get(language, ".txt")
        
        # 创建用户目录
        user_dir = self.scripts_dir / user_id
        user_dir.mkdir(exist_ok=True)
        
        # 保存脚本
        filename = f"{timestamp}_{script_id}{ext}"
        filepath = user_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(code)
        
        # 设置执行权限（仅限bash/shell脚本）
        if language in ["bash", "shell"]:
            os.chmod(filepath, 0o755)
        
        # 保存元数据
        metadata = {
            "script_id": script_id,
            "filename": filename,
            "filepath": str(filepath),
            "language": language,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "size": len(code),
            "line_count": len(code.splitlines())
        }
        
        metadata_file = filepath.with_suffix('.json')
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        return metadata
    
    async def execute_script(
        self, 
        filepath: str, 
        timeout: int = 30000,
        env: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """安全执行脚本"""
        filepath = Path(filepath)
        
        if not filepath.exists():
            raise FileNotFoundError(f"Script not found: {filepath}")
        
        # 确定执行命令
        if filepath.suffix == '.py':
            cmd = [sys.executable, str(filepath)]
        elif filepath.suffix in ['.sh', '.bash']:
            cmd = ['/bin/bash', str(filepath)]
        elif filepath.suffix == '.js':
            # 检查是否有 node
            node_path = shutil.which('node')
            if node_path:
                cmd = [node_path, str(filepath)]
            else:
                return {
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "Node.js is not installed",
                    "execution_time": 0,
                    "executed_at": datetime.now().isoformat()
                }
        else:
            raise ValueError(f"Unsupported script type: {filepath.suffix}")
        
        # 准备环境变量
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)
        
        # 执行脚本
        start_time = datetime.now()
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=exec_env
            )
            
            # 等待执行完成（带超时）
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            
            return {
                "success": process.returncode == 0,
                "exit_code": process.returncode,
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "execution_time": execution_time,
                "executed_at": start_time.isoformat()
            }
            
        except asyncio.TimeoutError:
            # 终止超时的进程
            process.terminate()
            await process.wait()
            
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Script execution timed out after {timeout} seconds",
                "execution_time": timeout,
                "executed_at": start_time.isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "execution_time": 0,
                "executed_at": start_time.isoformat()
            }
    
    async def schedule_cron_job(
        self,
        script_path: str,
        cron_expression: str,
        user_id: str,
        job_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """添加crontab定时任务"""
        script_path = Path(script_path)
        
        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")
        
        # 生成任务名称
        job_name = job_name or f"chatbot_job_{uuid.uuid4().hex[:8]}"
        
        # 创建cron命令
        # 将输出重定向到日志文件
        log_dir = self.scripts_dir / user_id / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"{job_name}.log"
        
        cron_command = f"{cron_expression} {script_path} >> {log_file} 2>&1"
        
        # 创建临时crontab文件
        temp_cron = f"/tmp/cron_{user_id}_{uuid.uuid4().hex}"
        
        try:
            # 获取当前crontab
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True
            )
            
            current_cron = result.stdout if result.returncode == 0 else ""
            
            # 添加新任务（带注释标识）
            with open(temp_cron, 'w') as f:
                f.write(current_cron)
                if current_cron and not current_cron.endswith('\n'):
                    f.write('\n')
                f.write(f"# ChatBot Job: {job_name}\n")
                f.write(f"{cron_command}\n")
            
            # 安装新的crontab
            result = subprocess.run(
                ["crontab", temp_cron],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "job_name": job_name,
                    "cron_expression": cron_expression,
                    "script_path": str(script_path),
                    "log_file": str(log_file),
                    "created_at": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr,
                    "job_name": job_name
                }
                
        finally:
            # 清理临时文件
            if os.path.exists(temp_cron):
                os.remove(temp_cron)
    
    async def remove_cron_job(self, job_name: str, user_id: str) -> bool:
        """删除crontab任务"""
        temp_cron = f"/tmp/cron_{user_id}_{uuid.uuid4().hex}"
        
        try:
            # 获取当前crontab
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return False
            
            current_cron = result.stdout
            
            # 过滤掉要删除的任务
            new_lines = []
            skip_next = False
            
            for line in current_cron.splitlines():
                if f"# ChatBot Job: {job_name}" in line:
                    skip_next = True
                    continue
                if skip_next:
                    skip_next = False
                    continue
                new_lines.append(line)
            
            # 写入新的crontab
            with open(temp_cron, 'w') as f:
                f.write('\n'.join(new_lines))
                if new_lines:
                    f.write('\n')
            
            # 安装新的crontab
            result = subprocess.run(
                ["crontab", temp_cron],
                capture_output=True,
                text=True
            )
            
            return result.returncode == 0
            
        finally:
            if os.path.exists(temp_cron):
                os.remove(temp_cron)

# 添加缺失的导入
import shutil