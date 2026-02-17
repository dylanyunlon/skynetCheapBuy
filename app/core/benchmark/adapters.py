#!/usr/bin/env python
"""
CheapBuy Benchmark Adapters
支持主流Code Agent Benchmark任务

支持的Benchmark:
1. SWE-bench Verified - GitHub Issue修复任务
2. MLE-bench - Kaggle机器学习任务
3. GitTaskBench - 仓库级任务
"""

import os
import re
import json
import asyncio
import subprocess
import shutil
import fnmatch
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from pathlib import Path
import logging
import uuid

logger = logging.getLogger(__name__)


class BenchmarkTask:
    """Benchmark任务基类"""
    
    def __init__(
        self,
        task_id: str,
        task_type: str,
        description: str,
        repo_url: Optional[str] = None,
        input_data: Optional[Dict] = None,
        expected_output: Optional[Dict] = None
    ):
        self.task_id = task_id
        self.task_type = task_type
        self.description = description
        self.repo_url = repo_url
        self.input_data = input_data or {}
        self.expected_output = expected_output or {}
        
        self.status = "pending"
        self.result = None
        self.metrics = {}
        self.start_time = None
        self.end_time = None
    
    def to_dict(self) -> Dict:
        return {
            'task_id': self.task_id,
            'task_type': self.task_type,
            'description': self.description,
            'repo_url': self.repo_url,
            'status': self.status,
            'result': self.result,
            'metrics': self.metrics,
            'duration': (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else None
        }


class BenchmarkAdapter(ABC):
    """Benchmark适配器基类"""
    
    def __init__(self, work_dir: str):
        self.work_dir = os.path.abspath(work_dir)
        os.makedirs(self.work_dir, exist_ok=True)
        self.name = "base"
    
    @abstractmethod
    async def prepare_task(self, task_config: Dict) -> BenchmarkTask:
        """准备任务环境"""
        pass
    
    @abstractmethod
    async def execute_task(self, task: BenchmarkTask, agent_func) -> Dict:
        """执行任务"""
        pass
    
    @abstractmethod
    async def evaluate_result(self, task: BenchmarkTask, result: Dict) -> Dict:
        """评估结果"""
        pass
    
    async def run_task(self, task_config: Dict, agent_func) -> Dict:
        """运行完整的任务流程"""
        task = await self.prepare_task(task_config)
        task.start_time = datetime.utcnow()
        task.status = "running"
        
        try:
            result = await self.execute_task(task, agent_func)
            task.result = result
            
            evaluation = await self.evaluate_result(task, result)
            task.metrics = evaluation
            
            task.status = "completed"
            
        except Exception as e:
            logger.error(f"任务执行失败: {e}")
            task.status = "failed"
            task.result = {"error": str(e)}
            task.metrics = {"success": False, "error": str(e)}
        
        task.end_time = datetime.utcnow()
        return task.to_dict()


class SWEBenchAdapter(BenchmarkAdapter):
    """SWE-bench Verified 适配器"""
    
    def __init__(self, work_dir: str):
        super().__init__(work_dir)
        self.name = "swe-bench"
    
    async def prepare_task(self, task_config: Dict) -> BenchmarkTask:
        task = BenchmarkTask(
            task_id=task_config.get('task_id', str(uuid.uuid4())),
            task_type='swe-bench',
            description=task_config.get('issue_description', ''),
            repo_url=task_config.get('repo_url'),
            input_data={
                'base_commit': task_config.get('base_commit'),
                'test_patch': task_config.get('test_patch'),
                'hints': task_config.get('hints', [])
            }
        )
        
        task_dir = os.path.join(self.work_dir, task.task_id)
        os.makedirs(task_dir, exist_ok=True)
        
        if task.repo_url:
            repo_path = os.path.join(task_dir, 'repo')
            await self._clone_to_commit(
                task.repo_url,
                repo_path,
                task.input_data.get('base_commit')
            )
            task.input_data['repo_path'] = repo_path
        
        return task
    
    async def _clone_to_commit(self, url: str, path: str, commit: Optional[str]) -> None:
        if os.path.exists(path):
            shutil.rmtree(path)
        
        cmd = ['git', 'clone', url, path]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if commit:
            cmd = ['git', '-C', path, 'checkout', commit]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
    
    async def execute_task(self, task: BenchmarkTask, agent_func) -> Dict:
        prompt = f"""
## SWE-bench Task: {task.task_id}

### Issue Description
{task.description}

### Repository Path
{task.input_data.get('repo_path', 'N/A')}

### Your Task
1. Analyze the issue and locate the relevant code
2. Understand the root cause
3. Generate a patch in unified diff format

Return JSON:
{{"analysis": "...", "files_modified": [...], "patch": "--- a/file.py\\n+++ b/file.py\\n..."}}
"""
        result = await agent_func(prompt, task.input_data.get('repo_path'))
        
        try:
            if isinstance(result, str):
                json_match = re.search(r'\{[\s\S]*\}', result)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    result = {"patch": result, "analysis": "Direct response"}
        except:
            result = {"patch": str(result), "analysis": "Parse failed"}
        
        return result
    
    async def evaluate_result(self, task: BenchmarkTask, result: Dict) -> Dict:
        metrics = {
            'has_patch': bool(result.get('patch')),
            'patch_valid': False,
            'tests_passed': False
        }
        
        patch = result.get('patch', '')
        if not patch:
            return metrics
        
        repo_path = task.input_data.get('repo_path')
        if not repo_path or not os.path.exists(repo_path):
            return metrics
        
        try:
            patch_file = os.path.join(repo_path, 'agent.patch')
            with open(patch_file, 'w') as f:
                f.write(patch)
            
            cmd = ['git', '-C', repo_path, 'apply', '--check', patch_file]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            
            metrics['patch_valid'] = (process.returncode == 0)
        except Exception as e:
            logger.error(f"评估失败: {e}")
        
        return metrics


class MLEBenchAdapter(BenchmarkAdapter):
    """MLE-bench 适配器"""
    
    def __init__(self, work_dir: str):
        super().__init__(work_dir)
        self.name = "mle-bench"
    
    async def prepare_task(self, task_config: Dict) -> BenchmarkTask:
        task = BenchmarkTask(
            task_id=task_config.get('task_id', str(uuid.uuid4())),
            task_type='mle-bench',
            description=task_config.get('description', ''),
            input_data={
                'competition_name': task_config.get('competition_name'),
                'data_path': task_config.get('data_path'),
                'metric': task_config.get('metric', 'accuracy'),
                'submission_format': task_config.get('submission_format'),
                'complexity': task_config.get('complexity', 'medium')
            }
        )
        
        task_dir = os.path.join(self.work_dir, task.task_id)
        os.makedirs(task_dir, exist_ok=True)
        task.input_data['work_dir'] = task_dir
        
        data_path = task_config.get('data_path')
        if data_path and os.path.exists(data_path):
            target_data = os.path.join(task_dir, 'data')
            if os.path.isdir(data_path):
                shutil.copytree(data_path, target_data, dirs_exist_ok=True)
            else:
                os.makedirs(target_data, exist_ok=True)
                shutil.copy(data_path, target_data)
            task.input_data['data_path'] = target_data
        
        return task
    
    async def execute_task(self, task: BenchmarkTask, agent_func) -> Dict:
        prompt = f"""
## MLE-bench Task: {task.task_id}
### Competition: {task.input_data.get('competition_name', 'Unknown')}

### Description
{task.description}

### Data: {task.input_data.get('data_path', 'N/A')}
### Metric: {task.input_data.get('metric', 'accuracy')}
### Working Directory: {task.input_data.get('work_dir')}

Build a model, generate predictions, save to submission.csv
"""
        result = await agent_func(prompt, task.input_data.get('work_dir'))
        
        submission_path = os.path.join(task.input_data.get('work_dir', ''), 'submission.csv')
        
        return {
            'agent_response': result,
            'submission_exists': os.path.exists(submission_path),
            'submission_path': submission_path if os.path.exists(submission_path) else None
        }
    
    async def evaluate_result(self, task: BenchmarkTask, result: Dict) -> Dict:
        return {
            'submission_valid': result.get('submission_exists', False),
            'score': None,
            'medal': None
        }


class GitTaskBenchAdapter(BenchmarkAdapter):
    """GitTaskBench 适配器"""
    
    def __init__(self, work_dir: str):
        super().__init__(work_dir)
        self.name = "git-task-bench"
    
    async def prepare_task(self, task_config: Dict) -> BenchmarkTask:
        task = BenchmarkTask(
            task_id=task_config.get('task_id', str(uuid.uuid4())),
            task_type='git-task-bench',
            description=task_config.get('task_description', ''),
            repo_url=task_config.get('repo', {}).get('url'),
            input_data={
                'repo': task_config.get('repo', {}),
                'input_data': task_config.get('input_data', []),
                'output_requirements': task_config.get('output_requirements', {})
            }
        )
        
        task_dir = os.path.join(self.work_dir, task.task_id)
        input_dir = os.path.join(task_dir, 'input')
        output_dir = os.path.join(task_dir, 'output')
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        
        for input_item in task.input_data.get('input_data', []):
            src_path = input_item.get('path')
            if src_path and os.path.exists(src_path):
                dst_path = os.path.join(input_dir, os.path.basename(src_path))
                if os.path.isfile(src_path):
                    shutil.copy(src_path, dst_path)
                else:
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                input_item['local_path'] = dst_path
        
        task.input_data['work_dir'] = task_dir
        task.input_data['input_dir'] = input_dir
        task.input_data['output_dir'] = output_dir
        
        return task
    
    async def execute_task(self, task: BenchmarkTask, agent_func) -> Dict:
        input_desc = "\n".join(
            f"- {item.get('local_path', item.get('path'))}: {item.get('description', '')}"
            for item in task.input_data.get('input_data', [])
        )
        
        prompt = f"""
## GitTaskBench: {task.task_id}

### Task
{task.description}

### Repository: {task.repo_url or 'N/A'}

### Input
{input_desc or 'No input'}

### Output Directory
{task.input_data.get('output_dir')}

Clone repo, setup env, process input, save output to the output directory.
"""
        result = await agent_func(prompt, task.input_data.get('work_dir'))
        
        output_dir = task.input_data.get('output_dir', '')
        output_files = []
        if os.path.exists(output_dir):
            output_files = [f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]
        
        return {
            'agent_response': result,
            'output_files': output_files,
            'output_dir': output_dir,
            'has_output': len(output_files) > 0
        }
    
    async def evaluate_result(self, task: BenchmarkTask, result: Dict) -> Dict:
        output_files = result.get('output_files', [])
        metrics = {
            'task_completed': len(output_files) > 0,
            'output_files_count': len(output_files),
            'output_valid': False
        }
        
        expected_pattern = task.input_data.get('output_requirements', {}).get('pattern', 'output*')
        metrics['output_valid'] = any(fnmatch.fnmatch(f, expected_pattern) for f in output_files)
        
        return metrics


class BenchmarkRunner:
    """Benchmark运行器"""
    
    def __init__(self, work_dir: str = "./workspace/benchmarks"):
        self.work_dir = os.path.abspath(work_dir)
        os.makedirs(self.work_dir, exist_ok=True)
        
        self.adapters: Dict[str, BenchmarkAdapter] = {
            'swe-bench': SWEBenchAdapter(os.path.join(self.work_dir, 'swe-bench')),
            'mle-bench': MLEBenchAdapter(os.path.join(self.work_dir, 'mle-bench')),
            'git-task-bench': GitTaskBenchAdapter(os.path.join(self.work_dir, 'git-task-bench'))
        }
        
        self.task_history: List[Dict] = []
    
    async def run_task(self, benchmark_type: str, task_config: Dict, agent_func) -> Dict:
        adapter = self.adapters.get(benchmark_type)
        if not adapter:
            return {'success': False, 'error': f"Unknown: {benchmark_type}"}
        
        result = await adapter.run_task(task_config, agent_func)
        self.task_history.append({
            'benchmark_type': benchmark_type,
            'task_id': result.get('task_id'),
            'timestamp': datetime.utcnow().isoformat(),
            'result': result
        })
        
        return result
    
    def get_statistics(self) -> Dict:
        stats = {'total_tasks': len(self.task_history), 'by_benchmark': {}}
        for record in self.task_history:
            benchmark = record.get('benchmark_type', 'unknown')
            if benchmark not in stats['by_benchmark']:
                stats['by_benchmark'][benchmark] = {'total': 0, 'completed': 0}
            stats['by_benchmark'][benchmark]['total'] += 1
            if record.get('result', {}).get('status') == 'completed':
                stats['by_benchmark'][benchmark]['completed'] += 1
        return stats


if __name__ == "__main__":
    async def mock_agent(prompt: str, work_dir: str = None) -> str:
        return f"Mock response for: {prompt[:100]}..."
    
    async def test():
        runner = BenchmarkRunner()
        result = await runner.run_task('git-task-bench', {
            "task_id": "test_001",
            "task_description": "Test task",
            "repo": {"type": "github", "url": "https://github.com/test/repo"}
        }, mock_agent)
        print(json.dumps(result, indent=2, default=str))
    
    asyncio.run(test())
