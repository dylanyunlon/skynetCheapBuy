# app/core/cron_manager.py
import subprocess
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid
import json
import logging

logger = logging.getLogger(__name__)

class CronManager:
    """Cron 任务管理器"""
    
    def __init__(self, base_path: str = "/app/cron"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.jobs_db_path = self.base_path / "jobs.json"
        self._load_jobs_db()
    
    def _load_jobs_db(self):
        """加载任务数据库"""
        if self.jobs_db_path.exists():
            with open(self.jobs_db_path, 'r') as f:
                self.jobs_db = json.load(f)
        else:
            self.jobs_db = {}
    
    def _save_jobs_db(self):
        """保存任务数据库"""
        with open(self.jobs_db_path, 'w') as f:
            json.dump(self.jobs_db, f, indent=2)
    
    def create_cron_job(
        self,
        script_path: str,
        cron_expression: str,
        user_id: str,
        job_name: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """创建 cron 任务"""
        script_path = Path(script_path)
        
        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")
        
        # 生成任务ID和名称
        job_id = str(uuid.uuid4())
        job_name = job_name or f"chatbot_job_{job_id[:8]}"
        
        # 创建日志目录
        log_dir = self.base_path / "logs" / user_id
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建环境变量文件
        env_file = None
        if env_vars:
            env_file = self.base_path / "env" / f"{job_id}.env"
            env_file.parent.mkdir(parents=True, exist_ok=True)
            with open(env_file, 'w') as f:
                for key, value in env_vars.items():
                    f.write(f'export {key}="{value}"\n')
        
        # 创建包装脚本
        wrapper_script = self._create_wrapper_script(
            job_id=job_id,
            job_name=job_name,
            script_path=script_path,
            env_file=env_file,
            log_dir=log_dir
        )
        
        # 构建 cron 命令
        cron_command = f"{cron_expression} {wrapper_script} >> {log_dir}/{job_name}.log 2>&1"
        
        # 添加到 crontab
        success = self._add_to_crontab(job_id, job_name, cron_command)
        
        if success:
            # 保存任务信息
            job_info = {
                "job_id": job_id,
                "job_name": job_name,
                "user_id": user_id,
                "script_path": str(script_path),
                "cron_expression": cron_expression,
                "wrapper_script": str(wrapper_script),
                "log_dir": str(log_dir),
                "env_file": str(env_file) if env_file else None,
                "description": description,
                "created_at": datetime.now().isoformat(),
                "is_active": True,
                "last_run": None,
                "run_count": 0
            }
            
            self.jobs_db[job_id] = job_info
            self._save_jobs_db()
            
            return {
                "success": True,
                "job_info": job_info,
                "next_run": self._calculate_next_run(cron_expression)
            }
        else:
            return {
                "success": False,
                "error": "Failed to add job to crontab"
            }
    
    def _create_wrapper_script(
        self,
        job_id: str,
        job_name: str,
        script_path: Path,
        env_file: Optional[Path],
        log_dir: Path
    ) -> Path:
        """创建任务包装脚本"""
        wrapper_dir = self.base_path / "wrappers"
        wrapper_dir.mkdir(exist_ok=True)
        
        wrapper_path = wrapper_dir / f"{job_id}.sh"
        
        wrapper_content = f"""#!/bin/bash
# Wrapper script for cron job: {job_name}
# Job ID: {job_id}
# Generated at: {datetime.now().isoformat()}

# 设置错误处理
set -euo pipefail

# 记录开始时间
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Job {job_name} started"

# 加载环境变量
"""
        
        if env_file:
            wrapper_content += f"source {env_file}\n"
        
        wrapper_content += f"""
# 设置工作目录
cd $(dirname {script_path})

# 执行脚本
if [[ "{script_path}" == *.py ]]; then
    /usr/bin/env python3 {script_path}
elif [[ "{script_path}" == *.sh ]]; then
    /bin/bash {script_path}
else
    {script_path}
fi

# 记录结束时间
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Job {job_name} completed with exit code $?"

# 更新任务信息
echo "{{
    \\"job_id\\": \\"{job_id}\\",
    \\"last_run\\": \\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\\",
    \\"exit_code\\": $?
}}" > {log_dir}/.last_run_{job_id}.json
"""
        
        with open(wrapper_path, 'w') as f:
            f.write(wrapper_content)
        
        # 设置执行权限
        os.chmod(wrapper_path, 0o755)
        
        return wrapper_path
    
    def _add_to_crontab(self, job_id: str, job_name: str, cron_command: str) -> bool:
        """添加任务到 crontab"""
        try:
            # 获取当前 crontab
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                check=False
            )
            
            current_crontab = result.stdout if result.returncode == 0 else ""
            
            # 添加新任务
            new_crontab = current_crontab
            if new_crontab and not new_crontab.endswith('\n'):
                new_crontab += '\n'
            
            new_crontab += f"# ChatBot Job: {job_name} (ID: {job_id})\n"
            new_crontab += f"{cron_command}\n"
            
            # 写入临时文件
            temp_file = f"/tmp/crontab_{uuid.uuid4().hex}"
            with open(temp_file, 'w') as f:
                f.write(new_crontab)
            
            # 安装新的 crontab
            result = subprocess.run(
                ["crontab", temp_file],
                capture_output=True,
                text=True
            )
            
            # 清理临时文件
            os.remove(temp_file)
            
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"Failed to add cron job: {e}")
            return False
    
    def remove_cron_job(self, job_id: str) -> bool:
        """删除 cron 任务"""
        try:
            # 获取任务信息
            job_info = self.jobs_db.get(job_id)
            if not job_info:
                return False
            
            # 获取当前 crontab
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                return False
            
            current_crontab = result.stdout
            
            # 过滤掉要删除的任务
            new_lines = []
            skip_next = False
            
            for line in current_crontab.splitlines():
                if f"ID: {job_id}" in line:
                    skip_next = True
                    continue
                if skip_next:
                    skip_next = False
                    continue
                new_lines.append(line)
            
            # 写入新的 crontab
            temp_file = f"/tmp/crontab_{uuid.uuid4().hex}"
            with open(temp_file, 'w') as f:
                f.write('\n'.join(new_lines))
                if new_lines:
                    f.write('\n')
            
            # 安装新的 crontab
            result = subprocess.run(
                ["crontab", temp_file],
                capture_output=True,
                text=True
            )
            
            os.remove(temp_file)
            
            if result.returncode == 0:
                # 更新数据库
                job_info["is_active"] = False
                job_info["removed_at"] = datetime.now().isoformat()
                self.jobs_db[job_id] = job_info
                self._save_jobs_db()
                
                # 清理相关文件
                self._cleanup_job_files(job_info)
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove cron job: {e}")
            return False
    
    def _cleanup_job_files(self, job_info: Dict[str, Any]):
        """清理任务相关文件"""
        try:
            # 删除包装脚本
            if job_info.get("wrapper_script"):
                wrapper_path = Path(job_info["wrapper_script"])
                if wrapper_path.exists():
                    wrapper_path.unlink()
            
            # 删除环境变量文件
            if job_info.get("env_file"):
                env_path = Path(job_info["env_file"])
                if env_path.exists():
                    env_path.unlink()
        except Exception as e:
            logger.error(f"Failed to cleanup job files: {e}")
    
    def list_jobs(self, user_id: Optional[str] = None, active_only: bool = True) -> List[Dict[str, Any]]:
        """列出任务"""
        jobs = []
        
        for job_id, job_info in self.jobs_db.items():
            # 过滤用户
            if user_id and job_info.get("user_id") != user_id:
                continue
            
            # 过滤活动状态
            if active_only and not job_info.get("is_active", True):
                continue
            
            # 添加运行状态
            job_info = self._get_job_status(job_info)
            jobs.append(job_info)
        
        return sorted(jobs, key=lambda x: x.get("created_at", ""), reverse=True)
    
    def _get_job_status(self, job_info: Dict[str, Any]) -> Dict[str, Any]:
        """获取任务状态"""
        job_info = job_info.copy()
        
        # 检查最后运行状态
        log_dir = Path(job_info.get("log_dir", ""))
        if log_dir.exists():
            last_run_file = log_dir / f".last_run_{job_info['job_id']}.json"
            if last_run_file.exists():
                try:
                    with open(last_run_file, 'r') as f:
                        last_run_data = json.load(f)
                        job_info["last_run"] = last_run_data.get("last_run")
                        job_info["last_exit_code"] = last_run_data.get("exit_code")
                except:
                    pass
        
        # 计算下次运行时间
        if job_info.get("is_active") and job_info.get("cron_expression"):
            job_info["next_run"] = self._calculate_next_run(job_info["cron_expression"])
        
        return job_info
    
    def _calculate_next_run(self, cron_expression: str) -> Optional[str]:
        """计算下次运行时间"""
        try:
            from croniter import croniter
            cron = croniter(cron_expression, datetime.now())
            next_run = cron.get_next(datetime)
            return next_run.isoformat()
        except:
            return None
    
    def get_job_logs(self, job_id: str, lines: int = 100) -> Optional[str]:
        """获取任务日志"""
        job_info = self.jobs_db.get(job_id)
        if not job_info:
            return None
        
        log_file = Path(job_info["log_dir"]) / f"{job_info['job_name']}.log"
        if not log_file.exists():
            return None
        
        try:
            # 读取最后 N 行
            with open(log_file, 'r') as f:
                lines_list = f.readlines()
                return ''.join(lines_list[-lines:])
        except Exception as e:
            logger.error(f"Failed to read log file: {e}")
            return None
    
    def update_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """更新任务信息"""
        job_info = self.jobs_db.get(job_id)
        if not job_info:
            return False
        
        # 允许更新的字段
        allowed_fields = ["description", "env_vars", "cron_expression"]
        
        for field, value in updates.items():
            if field in allowed_fields:
                if field == "cron_expression":
                    # 需要更新 crontab
                    self.remove_cron_job(job_id)
                    job_info[field] = value
                    self._add_to_crontab(
                        job_info["job_id"],
                        job_info["job_name"],
                        f"{value} {job_info['wrapper_script']} >> {job_info['log_dir']}/{job_info['job_name']}.log 2>&1"
                    )
                else:
                    job_info[field] = value
        
        job_info["updated_at"] = datetime.now().isoformat()
        self.jobs_db[job_id] = job_info
        self._save_jobs_db()
        
        return True