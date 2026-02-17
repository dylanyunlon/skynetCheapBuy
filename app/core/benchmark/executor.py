# app/core/benchmark/executor.py
# Benchmark代码执行器 - 支持Docker和本地执行

import os
import re
import json
import asyncio
import tempfile
import subprocess
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    output_files: List[str] = field(default_factory=list)
    error_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionStep:
    """执行步骤"""
    step_id: str
    name: str
    code: str
    language: str
    filename: Optional[str] = None
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[ExecutionResult] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class BenchmarkExecutor:
    """
    Benchmark代码执行器
    
    功能：
    1. 支持本地执行和Docker执行
    2. 管理执行环境和依赖
    3. 捕获输出和错误
    4. 支持超时控制
    """
    
    def __init__(
        self,
        work_dir: str,
        use_docker: bool = False,
        docker_image: str = "python:3.10-slim",
        timeout: int = 300,
        keep_same_path: bool = True
    ):
        """
        初始化执行器
        
        Args:
            work_dir: 工作目录
            use_docker: 是否使用Docker
            docker_image: Docker镜像名称
            timeout: 执行超时时间（秒）
            keep_same_path: Docker中是否保持相同路径
        """
        self.work_dir = os.path.abspath(work_dir)
        self.use_docker = use_docker
        self.docker_image = docker_image
        self.timeout = timeout
        self.keep_same_path = keep_same_path
        
        # 确保工作目录存在
        os.makedirs(self.work_dir, exist_ok=True)
        
        # 执行历史
        self.execution_history: List[ExecutionStep] = []
        
        # Docker容器ID（如果使用Docker）
        self._container_id: Optional[str] = None
        
        logger.info(f"BenchmarkExecutor initialized: work_dir={work_dir}, docker={use_docker}")
    
    async def execute_code(
        self,
        code: str,
        language: str = "python",
        filename: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        input_data: Optional[str] = None
    ) -> ExecutionResult:
        """
        执行代码
        
        Args:
            code: 要执行的代码
            language: 编程语言
            filename: 保存的文件名（如果为None则自动生成）
            env_vars: 环境变量
            input_data: 标准输入数据
            
        Returns:
            ExecutionResult
        """
        step_id = f"step_{uuid.uuid4().hex[:8]}"
        
        # 生成文件名
        if not filename:
            ext = self._get_extension(language)
            filename = f"code_{uuid.uuid4().hex[:8]}{ext}"
        
        step = ExecutionStep(
            step_id=step_id,
            name=f"Execute {filename}",
            code=code,
            language=language,
            filename=filename,
            status="running",
            started_at=datetime.utcnow().isoformat()
        )
        self.execution_history.append(step)
        
        start_time = datetime.utcnow()
        
        try:
            # 保存代码文件
            file_path = os.path.join(self.work_dir, filename)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code)
            
            logger.info(f"Code saved to {file_path}")
            
            # 执行代码
            if self.use_docker:
                result = await self._execute_in_docker(file_path, language, env_vars, input_data)
            else:
                result = await self._execute_local(file_path, language, env_vars, input_data)
            
            # 计算执行时间
            result.duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # 更新步骤状态
            step.status = "completed" if result.success else "failed"
            step.result = result
            step.completed_at = datetime.utcnow().isoformat()
            
            return result
            
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            result = ExecutionResult(
                success=False,
                exit_code=-1,
                stderr=str(e),
                error_type=type(e).__name__,
                duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
            )
            step.status = "failed"
            step.result = result
            step.completed_at = datetime.utcnow().isoformat()
            return result
    
    async def execute_batch(
        self,
        code_blocks: List[Dict[str, Any]],
        stop_on_error: bool = True
    ) -> List[ExecutionResult]:
        """
        批量执行代码块
        
        Args:
            code_blocks: 代码块列表 [{"code": "...", "language": "python", "filename": "xxx.py"}, ...]
            stop_on_error: 遇到错误时是否停止
            
        Returns:
            执行结果列表
        """
        results = []
        
        for block in code_blocks:
            result = await self.execute_code(
                code=block.get("code", ""),
                language=block.get("language", "python"),
                filename=block.get("filename"),
                env_vars=block.get("env_vars")
            )
            results.append(result)
            
            if not result.success and stop_on_error:
                logger.warning(f"Stopping batch execution due to error")
                break
        
        return results
    
    async def install_dependencies(self, packages: List[str]) -> ExecutionResult:
        """
        安装依赖包
        
        Args:
            packages: 包名列表
            
        Returns:
            ExecutionResult
        """
        if not packages:
            return ExecutionResult(success=True, stdout="No packages to install")
        
        # 构建pip install命令
        pip_cmd = f"pip install --quiet {' '.join(packages)}"
        
        return await self.execute_code(
            code=pip_cmd,
            language="bash",
            filename="install_deps.sh"
        )
    
    async def _execute_local(
        self,
        file_path: str,
        language: str,
        env_vars: Optional[Dict[str, str]] = None,
        input_data: Optional[str] = None
    ) -> ExecutionResult:
        """本地执行代码"""
        
        cmd = self._get_command(language, file_path)
        
        # 准备环境变量
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
        
        # 添加PYTHONPATH
        if language == "python":
            pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{self.work_dir}:{pythonpath}"
        
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if input_data else None,
                cwd=self.work_dir,
                env=env
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=input_data.encode() if input_data else None),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return ExecutionResult(
                    success=False,
                    exit_code=-1,
                    stderr=f"Execution timed out after {self.timeout}s",
                    error_type="TimeoutError"
                )
            
            stdout_text = stdout.decode('utf-8', errors='replace')
            stderr_text = stderr.decode('utf-8', errors='replace')
            
            # 检测输出文件
            output_files = self._detect_output_files(stdout_text + stderr_text)
            
            return ExecutionResult(
                success=process.returncode == 0,
                exit_code=process.returncode,
                stdout=self._truncate_output(stdout_text),
                stderr=self._truncate_output(stderr_text),
                output_files=output_files,
                error_type=self._detect_error_type(stderr_text) if process.returncode != 0 else None
            )
            
        except Exception as e:
            logger.error(f"Local execution error: {e}")
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stderr=str(e),
                error_type=type(e).__name__
            )
    
    async def _execute_in_docker(
        self,
        file_path: str,
        language: str,
        env_vars: Optional[Dict[str, str]] = None,
        input_data: Optional[str] = None
    ) -> ExecutionResult:
        """在Docker中执行代码"""
        
        # 确保容器运行
        if not self._container_id:
            await self._start_container()
        
        # 构建执行命令
        if self.keep_same_path:
            container_file_path = file_path
        else:
            container_file_path = f"/workspace/{os.path.basename(file_path)}"
        
        cmd = self._get_command(language, container_file_path)
        
        # 构建docker exec命令
        docker_cmd = ["docker", "exec"]
        
        # 添加环境变量
        if env_vars:
            for key, value in env_vars.items():
                docker_cmd.extend(["-e", f"{key}={value}"])
        
        # 添加工作目录
        docker_cmd.extend(["-w", self.work_dir if self.keep_same_path else "/workspace"])
        
        docker_cmd.extend([self._container_id, "sh", "-c", cmd])
        
        try:
            process = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if input_data else None
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=input_data.encode() if input_data else None),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                # 杀死容器中的进程
                await asyncio.create_subprocess_exec(
                    "docker", "exec", self._container_id, "pkill", "-f", os.path.basename(file_path)
                )
                return ExecutionResult(
                    success=False,
                    exit_code=-1,
                    stderr=f"Execution timed out after {self.timeout}s",
                    error_type="TimeoutError"
                )
            
            stdout_text = stdout.decode('utf-8', errors='replace')
            stderr_text = stderr.decode('utf-8', errors='replace')
            
            return ExecutionResult(
                success=process.returncode == 0,
                exit_code=process.returncode,
                stdout=self._truncate_output(stdout_text),
                stderr=self._truncate_output(stderr_text),
                output_files=self._detect_output_files(stdout_text + stderr_text),
                error_type=self._detect_error_type(stderr_text) if process.returncode != 0 else None
            )
            
        except Exception as e:
            logger.error(f"Docker execution error: {e}")
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stderr=str(e),
                error_type=type(e).__name__
            )
    
    async def _start_container(self):
        """启动Docker容器"""
        container_name = f"benchmark-{uuid.uuid4().hex[:8]}"
        
        # 构建volume挂载
        if self.keep_same_path:
            volume_mount = f"{self.work_dir}:{self.work_dir}"
        else:
            volume_mount = f"{self.work_dir}:/workspace"
        
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "-v", volume_mount,
            "--network", "host",
            self.docker_image,
            "tail", "-f", "/dev/null"  # 保持容器运行
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"Failed to start Docker container: {stderr.decode()}")
        
        self._container_id = stdout.decode().strip()
        logger.info(f"Started Docker container: {self._container_id[:12]}")
    
    async def stop_container(self):
        """停止Docker容器"""
        if self._container_id:
            try:
                await asyncio.create_subprocess_exec(
                    "docker", "stop", self._container_id
                )
                await asyncio.create_subprocess_exec(
                    "docker", "rm", self._container_id
                )
                logger.info(f"Stopped Docker container: {self._container_id[:12]}")
            except Exception as e:
                logger.error(f"Failed to stop container: {e}")
            finally:
                self._container_id = None
    
    def _get_command(self, language: str, file_path: str) -> str:
        """根据语言获取执行命令"""
        commands = {
            "python": f"python3 {file_path}",
            "bash": f"bash {file_path}",
            "sh": f"sh {file_path}",
            "javascript": f"node {file_path}",
            "typescript": f"npx ts-node {file_path}",
        }
        return commands.get(language, f"python3 {file_path}")
    
    def _get_extension(self, language: str) -> str:
        """根据语言获取文件扩展名"""
        extensions = {
            "python": ".py",
            "bash": ".sh",
            "sh": ".sh",
            "javascript": ".js",
            "typescript": ".ts",
        }
        return extensions.get(language, ".py")
    
    def _truncate_output(self, text: str, max_chars: int = 10000) -> str:
        """截断输出文本"""
        if len(text) <= max_chars:
            return text
        
        half = max_chars // 2
        return f"{text[:half]}\n\n... [truncated {len(text) - max_chars} chars] ...\n\n{text[-half:]}"
    
    def _detect_output_files(self, text: str) -> List[str]:
        """从输出中检测生成的文件"""
        files = []
        
        # 常见的输出文件模式
        patterns = [
            r"saved to ['\"]?([^'\"]+)['\"]?",
            r"output: ['\"]?([^'\"]+)['\"]?",
            r"written to ['\"]?([^'\"]+)['\"]?",
            r"created ['\"]?([^'\"]+)['\"]?",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            files.extend(matches)
        
        # 验证文件是否存在
        existing = []
        for f in files:
            full_path = os.path.join(self.work_dir, f) if not os.path.isabs(f) else f
            if os.path.exists(full_path):
                existing.append(f)
        
        return existing
    
    def _detect_error_type(self, stderr: str) -> Optional[str]:
        """检测错误类型"""
        error_patterns = {
            "ModuleNotFoundError": r"ModuleNotFoundError",
            "ImportError": r"ImportError",
            "SyntaxError": r"SyntaxError",
            "IndentationError": r"IndentationError",
            "NameError": r"NameError",
            "TypeError": r"TypeError",
            "ValueError": r"ValueError",
            "KeyError": r"KeyError",
            "IndexError": r"IndexError",
            "FileNotFoundError": r"FileNotFoundError",
            "PermissionError": r"PermissionError",
            "RuntimeError": r"RuntimeError",
            "MemoryError": r"MemoryError",
            "TimeoutError": r"TimeoutError",
        }
        
        for error_type, pattern in error_patterns.items():
            if re.search(pattern, stderr):
                return error_type
        
        return "UnknownError" if stderr else None
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """获取执行摘要"""
        total = len(self.execution_history)
        successful = sum(1 for s in self.execution_history if s.status == "completed" and s.result and s.result.success)
        failed = sum(1 for s in self.execution_history if s.status == "failed")
        
        total_duration = sum(
            s.result.duration_ms for s in self.execution_history 
            if s.result and s.result.duration_ms
        )
        
        return {
            "total_steps": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0,
            "total_duration_ms": total_duration,
            "steps": [
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "status": s.status,
                    "duration_ms": s.result.duration_ms if s.result else 0,
                    "error_type": s.result.error_type if s.result else None
                }
                for s in self.execution_history
            ]
        }
    
    async def cleanup(self):
        """清理资源"""
        if self.use_docker:
            await self.stop_container()
        
        logger.info("Executor cleanup completed")
    
    def __del__(self):
        """析构时清理"""
        if self._container_id:
            # 同步清理
            import subprocess
            try:
                subprocess.run(["docker", "stop", self._container_id], capture_output=True)
                subprocess.run(["docker", "rm", self._container_id], capture_output=True)
            except Exception:
                pass
