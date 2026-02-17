# app/api/v2/benchmark.py - Benchmark API端点
# v3.2: 修复硬编码评估，集成真实SWE-bench评估器

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, List
import logging
import uuid
import asyncio
import os
import json
from datetime import datetime

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.core.ai_engine import AIEngine
from app.core.code_extractor import CodeExtractor, CodeBlock, CodeType
from app.core.repo.analyzer import RepoAnalyzer
from app.core.repo.tree_builder import CodeTreeBuilder

# 导入真实评估器
try:
    from app.core.benchmark.swe_bench_evaluator import (
        SWEBenchEvaluator, GitTaskBenchEvaluator, MLEBenchEvaluator,
        EvaluationMode, SWEBenchInstance, EvaluationResult, create_evaluator
    )
    EVALUATOR_AVAILABLE = True
except ImportError:
    EVALUATOR_AVAILABLE = False
    logger_temp = logging.getLogger(__name__)
    logger_temp.warning("SWE-bench evaluator not available, using fallback")

# 导入任务定义
from .benchmark_tasks import (
    BenchmarkType, DifficultyLevel, BenchmarkTask,
    get_all_tasks, get_tasks_by_type, get_tasks_by_domain, get_task_by_id,
    BENCHMARK_INFO, GITTASKBENCH_TASKS, SWE_BENCH_TASKS, MLE_BENCH_TASKS
)

from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/benchmark", tags=["benchmark"])

# 活跃会话存储
active_sessions: Dict[str, 'BenchmarkSessionWrapper'] = {}


# ==================== 请求模型 ====================

class BenchmarkRunRequest(BaseModel):
    task_id: str
    benchmark_type: BenchmarkType
    config: Optional[Dict[str, Any]] = None
    repository_url: Optional[str] = None
    custom_task: Optional[Dict[str, Any]] = None


class RepoAnalysisRequest(BaseModel):
    repo_url: str
    force_refresh: bool = False
    max_depth: int = 4


class BatchBenchmarkRequest(BaseModel):
    benchmark_types: List[BenchmarkType]
    tasks_per_benchmark: int = 5
    config: Optional[Dict[str, Any]] = None


# ==================== 会话包装器 ====================

class BenchmarkSessionWrapper:
    def __init__(self, session_id: str, task: BenchmarkTask, user_id: str):
        self.session_id = session_id
        self.task = task
        self.task_id = task.id
        self.task_description = task.description
        self.repository_url = task.repository_url
        self.user_id = user_id
        
        self.status = "idle"
        self.current_stage = "idle"
        self.stages: Dict[str, Dict[str, Any]] = {}
        self.metrics = {
            "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "total_api_calls": 0, "total_duration_ms": 0, "estimated_cost_usd": 0.0,
            "execution_completion_rate": 0.0, "task_pass_rate": 0.0, "alpha_score": 0.0
        }
        
        self.repo_analysis = {}
        self.tree_structure = {}
        self.generated_code = []
        self.execution_results = []
        self.validation_result = None
        self.logs = []
        
        self.created_at = datetime.utcnow().isoformat()
        self.updated_at = self.created_at
        self.completed_at = None
        self.work_dir = None
    
    def add_log(self, level: str, message: str, data: Any = None):
        self.logs.append({
            "level": level, "message": message, "data": data,
            "timestamp": datetime.utcnow().isoformat()
        })
        self.updated_at = datetime.utcnow().isoformat()
    
    def start_stage(self, stage_id: str, description: str = ""):
        self.stages[stage_id] = {
            "status": "running", "started_at": datetime.utcnow().isoformat(),
            "description": description, "output": "", "token_usage": 0
        }
        self.current_stage = stage_id
        self.status = "running"
        self.updated_at = datetime.utcnow().isoformat()
    
    def complete_stage(self, stage_id: str, output: str = "", token_usage: int = 0):
        if stage_id in self.stages:
            self.stages[stage_id].update({
                "status": "completed", "completed_at": datetime.utcnow().isoformat(),
                "output": output, "token_usage": token_usage,
                "duration_ms": int((datetime.utcnow() - datetime.fromisoformat(
                    self.stages[stage_id]["started_at"])).total_seconds() * 1000)
            })
        self.metrics["total_tokens"] += token_usage
        self.updated_at = datetime.utcnow().isoformat()
    
    def fail_stage(self, stage_id: str, error: str):
        if stage_id in self.stages:
            self.stages[stage_id].update({
                "status": "failed", "completed_at": datetime.utcnow().isoformat(),
                "error": error
            })
        self.status = "failed"
        self.updated_at = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id, "task_id": self.task_id,
            "task": self.task.dict(), "status": self.status,
            "current_stage": self.current_stage, "stages": self.stages,
            "metrics": self.metrics, "repo_analysis": self.repo_analysis,
            "generated_code": self.generated_code,
            "execution_results": self.execution_results,
            "validation_result": self.validation_result,
            "logs": self.logs, "created_at": self.created_at,
            "updated_at": self.updated_at, "completed_at": self.completed_at
        }


# ==================== Benchmark Runner ====================

class SkynetBenchmarkRunner:
    """RepoMaster风格的Benchmark运行器"""
    
    STAGES = [
        ("repo_clone", "仓库克隆"),
        ("tree_analysis", "Tree结构分析"),
        ("hierarchical_analysis", "层级结构分析"),
        ("solution_generation", "解决方案生成"),
        ("code_execution", "代码执行"),
        ("validation", "结果验证")
    ]
    
    def __init__(self, session: BenchmarkSessionWrapper, ai_engine: AIEngine):
        self.session = session
        self.ai_engine = ai_engine
        self.repo_analyzer = RepoAnalyzer()
    
    async def run(self):
        """运行完整的Benchmark流程"""
        start_time = datetime.utcnow()
        self.session.status = "running"
        
        try:
            for stage_id, stage_name in self.STAGES:
                self.session.add_log("info", f"开始阶段: {stage_name}")
                self.session.start_stage(stage_id, stage_name)
                
                try:
                    if stage_id == "repo_clone":
                        await self._stage_repo_clone()
                    elif stage_id == "tree_analysis":
                        await self._stage_tree_analysis()
                    elif stage_id == "hierarchical_analysis":
                        await self._stage_hierarchical_analysis()
                    elif stage_id == "solution_generation":
                        await self._stage_solution_generation()
                    elif stage_id == "code_execution":
                        await self._stage_code_execution()
                    elif stage_id == "validation":
                        await self._stage_validation()
                    
                    self.session.add_log("info", f"阶段完成: {stage_name}")
                    
                except Exception as e:
                    self.session.fail_stage(stage_id, str(e))
                    self.session.add_log("error", f"阶段失败: {stage_name} - {e}")
                    raise
            
            # 计算最终指标
            self._calculate_metrics(start_time)
            self.session.status = "completed"
            self.session.completed_at = datetime.utcnow().isoformat()
            
        except Exception as e:
            self.session.status = "failed"
            self.session.add_log("error", f"Benchmark失败: {e}")
            raise
    
    async def _stage_repo_clone(self):
        """阶段1: 克隆仓库"""
        repo_url = self.session.repository_url
        if not repo_url:
            self.session.complete_stage("repo_clone", "无需克隆仓库（本地任务）")
            return
        
        result = await self.repo_analyzer.analyze_repository(repo_url, force_refresh=False)
        
        if result.get('success'):
            self.session.repo_analysis = {
                "repo_name": result.get("repo_name"),
                "stats": result.get("stats"),
                "key_modules": result.get("key_modules", [])[:10]
            }
            output = f"✓ 仓库分析成功\n├── 名称: {result.get('repo_name')}\n"
            output += f"├── 模块数: {result.get('stats', {}).get('total_modules', 0)}\n"
            output += f"└── 函数数: {result.get('stats', {}).get('total_functions', 0)}"
            self.session.complete_stage("repo_clone", output)
        else:
            raise Exception(f"仓库分析失败: {result.get('error')}")
    
    async def _stage_tree_analysis(self):
        """阶段2: Tree结构分析"""
        repo_url = self.session.repository_url
        
        if not repo_url:
            self.session.tree_structure = {"flat_paths_count": 0, "tree_preview": "无仓库"}
            self.session.complete_stage("tree_analysis", "✓ Tree分析完成（无仓库）")
            return
        
        # 从repo_analysis中获取tree信息（analyze_repository已经构建）
        repo_analysis = self.session.repo_analysis
        tree_abstraction = repo_analysis.get("tree_abstraction", {})
        
        if tree_abstraction:
            self.session.tree_structure = {
                "flat_paths_count": tree_abstraction.get("flat_paths_count", 0),
                "tree_preview": tree_abstraction.get("tree_content_preview", "")[:500]
            }
            output = f"✓ Tree分析完成\n├── 文件数: {tree_abstraction.get('flat_paths_count', 0)}"
        else:
            # 如果没有tree_abstraction，使用结构信息
            structure = repo_analysis.get("structure", "")
            self.session.tree_structure = {
                "flat_paths_count": repo_analysis.get("stats", {}).get("total_modules", 0),
                "tree_preview": structure[:500] if structure else ""
            }
            output = "✓ Tree分析完成（使用结构信息）"
        
        self.session.complete_stage("tree_analysis", output)
    
    async def _stage_hierarchical_analysis(self):
        """阶段3: 层级结构分析"""
        task = self.session.task
        repo_analysis = self.session.repo_analysis
        
        # 构建分析提示
        prompt = f"""基于以下仓库结构和任务描述，分析关键模块：

任务: {task.description}
领域: {task.domain}
模态: {task.modality}

仓库统计:
- 总模块数: {repo_analysis.get('stats', {}).get('total_modules', 0)}
- 总函数数: {repo_analysis.get('stats', {}).get('total_functions', 0)}

关键模块:
{json.dumps(repo_analysis.get('key_modules', [])[:5], indent=2, ensure_ascii=False)}

请分析:
1. 主要模块列表及其用途
2. 数据流和依赖关系
3. 推荐的入口点和关键函数"""
        
        # 使用AIEngine.generate方法
        response = await self.ai_engine.generate(prompt, max_tokens=2000)
        token_usage = response.get("usage", {}).get("total_tokens", 0)
        
        # 更新API调用统计
        self.session.metrics["total_api_calls"] += 1
        
        self.session.complete_stage("hierarchical_analysis", 
                                   response.get("content", "分析完成"), token_usage)
    
    async def _stage_solution_generation(self):
        """阶段4: 解决方案生成"""
        task = self.session.task
        
        prompt = f"""根据以下任务生成Python解决方案代码:

任务: {task.name}
描述: {task.description}
仓库: {task.repository_url or '无'}
成功标准: {json.dumps(task.success_criteria, ensure_ascii=False) if task.success_criteria else '无'}

要求:
1. 生成完整可执行的Python代码
2. 包含必要的依赖导入
3. 处理输入输出
4. 添加错误处理
5. 输出结果到指定位置

请生成解决方案代码:"""
        
        # 使用AIEngine.generate方法
        response = await self.ai_engine.generate(prompt, max_tokens=4000)
        token_usage = response.get("usage", {}).get("total_tokens", 0)
        
        # 更新API调用统计
        self.session.metrics["total_api_calls"] += 1
        
        content = response.get("content", "")
        
        # 提取代码
        extractor = CodeExtractor()
        code_blocks = extractor.extract_code_blocks(content)
        
        # CodeBlock属性: code, language, description
        self.session.generated_code = [
            {"language": b.language, "content": b.code}  # 使用 b.code 而不是 b.content
            for b in code_blocks
        ]
        
        output = f"✓ 解决方案生成完成\n├── 代码块数: {len(code_blocks)}\n"
        output += f"└── Token使用: {token_usage}"
        
        self.session.complete_stage("solution_generation", output, token_usage)
    
    async def _stage_code_execution(self):
        """阶段5: 代码执行"""
        if not self.session.generated_code:
            self.session.complete_stage("code_execution", "无代码需要执行")
            return
        
        # 执行生成的代码
        execution_results = []
        for i, code_block in enumerate(self.session.generated_code):
            if code_block["language"] in ["python", "py"]:
                try:
                    # 实际执行逻辑（简化版）
                    result = await self._execute_python_code(code_block["content"], i)
                    execution_results.append(result)
                except Exception as e:
                    execution_results.append({
                        "index": i, "status": "failed", "error": str(e)
                    })
        
        self.session.execution_results = execution_results
        
        success_count = sum(1 for r in execution_results if r.get("status") == "success")
        output = f"✓ 代码执行完成\n├── 总代码块: {len(execution_results)}\n"
        output += f"└── 成功执行: {success_count}"
        
        self.session.complete_stage("code_execution", output)
    
    async def _execute_python_code(self, code: str, index: int) -> Dict[str, Any]:
        """执行Python代码"""
        import tempfile
        import subprocess
        
        # 创建临时文件
        work_dir = self.session.work_dir or tempfile.mkdtemp()
        code_file = os.path.join(work_dir, f"solution_{index}.py")
        
        try:
            # 写入代码
            with open(code_file, 'w', encoding='utf-8') as f:
                f.write(code)
            
            # 执行代码（设置超时）
            result = subprocess.run(
                ['python', code_file],
                capture_output=True,
                text=True,
                timeout=60,  # 60秒超时
                cwd=work_dir
            )
            
            return {
                "index": index,
                "status": "success" if result.returncode == 0 else "failed",
                "exit_code": result.returncode,
                "stdout": result.stdout[:1000],  # 限制输出长度
                "stderr": result.stderr[:500] if result.returncode != 0 else ""
            }
            
        except subprocess.TimeoutExpired:
            return {
                "index": index,
                "status": "timeout",
                "error": "Execution timed out (60s)"
            }
        except Exception as e:
            return {
                "index": index,
                "status": "error",
                "error": str(e)
            }
    
    async def _stage_validation(self):
        """阶段6: 结果验证 - 使用真实评估器"""
        task = self.session.task
        success_criteria = task.success_criteria or {}
        benchmark_type = task.benchmark_type
        
        # 确定评估模式 - 默认使用FULL模式（最准确）
        eval_mode = os.environ.get("BENCHMARK_EVAL_MODE", "full")
        
        if EVALUATOR_AVAILABLE:
            try:
                # 使用真实评估器
                if benchmark_type in [BenchmarkType.SWE_BENCH_VERIFIED, BenchmarkType.SWE_BENCH_LITE]:
                    evaluator = SWEBenchEvaluator(mode=EvaluationMode(eval_mode))
                    
                    # 构建SWE-bench实例
                    instance = SWEBenchInstance(
                        instance_id=task.id,
                        repo=task.repository_url or "",
                        base_commit="",
                        problem_statement=task.description,
                        fail_to_pass=success_criteria.get("fail_to_pass", []),
                        pass_to_pass=success_criteria.get("pass_to_pass", [])
                    )
                    
                    # 获取生成的patch (从generated_code中提取)
                    generated_patch = self._extract_patch_from_code()
                    
                    # 执行评估
                    result = await evaluator.evaluate(instance, generated_patch)
                    
                    self.session.validation_result = {
                        "passed": result.resolved,
                        "tests_run": result.tests_passed + result.tests_failed,
                        "tests_passed": result.tests_passed,
                        "tests_failed": result.tests_failed,
                        "evaluation_mode": result.evaluation_mode,
                        "patch_applied": result.patch_applied,
                        "details": result.details,
                        "error": result.error_message
                    }
                    
                elif benchmark_type == BenchmarkType.GITTASKBENCH:
                    evaluator = GitTaskBenchEvaluator()
                    
                    # 获取生成的输出
                    generated_output = "\n".join(
                        block.get("content", "") for block in self.session.generated_code
                    )
                    
                    result = await evaluator.evaluate(task.id, generated_output, success_criteria)
                    
                    self.session.validation_result = {
                        "passed": result.resolved,
                        "tests_run": 1,
                        "tests_passed": result.tests_passed,
                        "tests_failed": result.tests_failed,
                        "evaluation_mode": "gittaskbench",
                        "details": result.details
                    }
                    
                elif benchmark_type == BenchmarkType.MLE_BENCH:
                    evaluator = MLEBenchEvaluator()
                    
                    # MLE-bench需要提交文件
                    submission_file = os.path.join(
                        self.session.work_dir or "/tmp",
                        "submission.csv"
                    )
                    
                    result = await evaluator.evaluate(
                        task.id, 
                        submission_file,
                        success_criteria.get("metric", "accuracy")
                    )
                    
                    self.session.validation_result = {
                        "passed": result.resolved,
                        "tests_run": 1,
                        "tests_passed": result.tests_passed,
                        "tests_failed": result.tests_failed,
                        "evaluation_mode": "mle_bench",
                        "details": result.details
                    }
                    
                else:
                    # 其他类型使用简化评估
                    await self._fallback_validation()
                    
            except Exception as e:
                logger.error(f"Evaluator error: {e}", exc_info=True)
                await self._fallback_validation()
        else:
            # 评估器不可用时使用回退方案
            await self._fallback_validation()
        
        # 生成输出
        validation = self.session.validation_result
        passed = validation.get("passed", False)
        tests_passed = validation.get("tests_passed", 0)
        tests_run = validation.get("tests_run", 0)
        eval_mode_str = validation.get("evaluation_mode", "unknown")
        
        output = f"{'✓' if passed else '✗'} 验证{'通过' if passed else '失败'}\n"
        output += f"├── 评估模式: {eval_mode_str}\n"
        output += f"├── 测试用例: {tests_passed}/{tests_run} 通过\n"
        
        if validation.get("error"):
            output += f"└── 错误: {validation['error'][:100]}"
        elif validation.get("details"):
            details = validation["details"]
            if "evaluation_note" in details:
                output += f"└── 注意: {details['evaluation_note'][:100]}"
            else:
                output += f"└── Patch已应用: {validation.get('patch_applied', 'N/A')}"
        
        self.session.complete_stage("validation", output)
    
    async def _fallback_validation(self):
        """回退验证方案 - 当真实评估器不可用时"""
        execution_results = self.session.execution_results
        
        tests_run = len(execution_results)
        tests_passed = sum(1 for r in execution_results if r.get("status") == "success")
        
        # 简化的通过判断：有代码生成且执行成功
        passed = tests_passed > 0
        
        self.session.validation_result = {
            "passed": passed,
            "tests_run": tests_run,
            "tests_passed": tests_passed,
            "tests_failed": tests_run - tests_passed,
            "evaluation_mode": "fallback",
            "details": {
                "evaluation_note": "Fallback mode - based on code execution only, NOT real SWE-bench tests",
                "warning": "This is NOT accurate SWE-bench evaluation. Install swebench and Docker for real evaluation."
            }
        }
    
    def _extract_patch_from_code(self) -> str:
        """从生成的代码中提取patch"""
        # 查找diff格式的内容
        for code_block in self.session.generated_code:
            content = code_block.get("content", "")
            if "diff --git" in content or content.startswith("---"):
                return content
        
        # 如果没有找到diff格式，尝试将代码转换为简单的patch格式
        # 这只是一个占位符，真正的patch应该由AI生成
        all_code = "\n".join(
            block.get("content", "") for block in self.session.generated_code
        )
        
        if all_code:
            # 返回一个简化的patch表示
            return f"""# Generated code (not a proper git diff)
# Real SWE-bench evaluation requires a proper git diff format

{all_code}
"""
        
        return ""
    
    def _calculate_metrics(self, start_time: datetime):
        """计算最终指标"""
        duration = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        # ECR: 执行完成率
        total_stages = len(self.STAGES)
        completed_stages = sum(1 for s in self.session.stages.values() 
                              if s.get("status") == "completed")
        ecr = completed_stages / total_stages if total_stages > 0 else 0
        
        # TPR: 任务通过率
        validation = self.session.validation_result or {}
        tpr = 1.0 if validation.get("passed", False) else 0.0
        
        # Alpha Score: 经济效益评分
        market_value = self.session.task.market_value_usd or 10.0
        
        # 估算成本 (基于token使用量)
        total_tokens = self.session.metrics.get("total_tokens", 0)
        # GPT-4o 定价: ~$0.005/1K input, ~$0.015/1K output (取平均)
        estimated_cost = (total_tokens / 1000) * 0.01
        
        alpha = (tpr * market_value) - estimated_cost
        
        self.session.metrics.update({
            "total_duration_ms": int(duration),
            "execution_completion_rate": ecr,
            "task_pass_rate": tpr,
            "alpha_score": alpha,
            "estimated_cost_usd": estimated_cost
        })


# ==================== API端点 ====================

@router.get("/tasks")
async def get_benchmark_tasks(
    type: Optional[BenchmarkType] = None,
    domain: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100)
):
    """获取Benchmark任务列表"""
    if type:
        tasks = get_tasks_by_type(type, limit)
    elif domain:
        tasks = get_tasks_by_domain(domain, limit)
    else:
        tasks = get_all_tasks()[:limit]
    
    return {"tasks": [t.dict() for t in tasks], "total": len(tasks)}


@router.get("/tasks/{task_id}")
async def get_benchmark_task(task_id: str):
    """获取单个任务详情"""
    task = get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": task.dict()}


@router.get("/info/{benchmark_type}")
async def get_benchmark_info(benchmark_type: BenchmarkType):
    """获取Benchmark类型信息"""
    info = BENCHMARK_INFO.get(benchmark_type)
    if not info:
        return {"name": benchmark_type.value, "description": "", "task_count": 0}
    return info


@router.post("/run")
async def start_benchmark_run(
    request: BenchmarkRunRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """启动Benchmark运行"""
    logger.info(f"[Benchmark] Starting run for task: {request.task_id}")
    
    # 查找任务
    task = get_task_by_id(request.task_id)
    if not task and request.custom_task:
        task = BenchmarkTask(
            id=f"custom_{uuid.uuid4().hex[:8]}",
            benchmark_type=BenchmarkType.CUSTOM,
            name=request.custom_task.get("name", "Custom Task"),
            description=request.custom_task.get("description", ""),
            difficulty=DifficultyLevel.MEDIUM,
            domain=request.custom_task.get("domain", "general"),
            modality=request.custom_task.get("modality", "code"),
            repository_url=request.repository_url
        )
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 创建会话
    session_id = f"bench_{uuid.uuid4().hex[:12]}"
    session = BenchmarkSessionWrapper(session_id, task, str(current_user.id))
    active_sessions[session_id] = session
    
    # 后台运行
    async def run_benchmark():
        try:
            ai_engine = AIEngine()
            runner = SkynetBenchmarkRunner(session, ai_engine)
            await runner.run()
        except Exception as e:
            logger.error(f"[Benchmark] Run failed: {e}", exc_info=True)
            session.status = "failed"
    
    asyncio.create_task(run_benchmark())
    
    return {"success": True, "session_id": session_id, "task": task.dict()}


@router.post("/batch")
async def start_batch_benchmark(
    request: BatchBenchmarkRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """批量启动Benchmark运行"""
    logger.info(f"[Benchmark] Starting batch run for types: {request.benchmark_types}")
    
    sessions = []
    for btype in request.benchmark_types:
        tasks = get_tasks_by_type(btype, request.tasks_per_benchmark)
        for task in tasks:
            session_id = f"bench_{uuid.uuid4().hex[:12]}"
            session = BenchmarkSessionWrapper(session_id, task, str(current_user.id))
            active_sessions[session_id] = session
            sessions.append({
                "session_id": session_id,
                "task_id": task.id,
                "benchmark_type": btype.value
            })
            
            # 后台运行
            async def run_single_benchmark(s=session):
                try:
                    ai_engine = AIEngine()
                    runner = SkynetBenchmarkRunner(s, ai_engine)
                    await runner.run()
                except Exception as e:
                    logger.error(f"[Benchmark] Run failed: {e}", exc_info=True)
                    s.status = "failed"
            
            asyncio.create_task(run_single_benchmark())
    
    return {
        "success": True,
        "sessions": sessions,
        "total": len(sessions)
    }


@router.get("/session/{session_id}")
async def get_session_status(session_id: str, current_user: User = Depends(get_current_user)):
    """获取会话状态"""
    session = active_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return {"session": session.to_dict()}


@router.post("/cancel/{session_id}")
async def cancel_benchmark(session_id: str, current_user: User = Depends(get_current_user)):
    """取消Benchmark运行"""
    session = active_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = "cancelled"
    return {"success": True}


@router.post("/analyze-repo")
async def analyze_repository(request: RepoAnalysisRequest, current_user: User = Depends(get_current_user)):
    """分析仓库"""
    analyzer = RepoAnalyzer()
    result = await analyzer.analyze_repository(
        request.repo_url, force_refresh=request.force_refresh, max_depth=request.max_depth
    )
    if not result.get('success'):
        raise HTTPException(status_code=400, detail=result.get('error'))
    return {
        "repo_name": result.get("repo_name"),
        "stats": result.get("stats"),
        "key_modules": result.get("key_modules", [])[:10],
        "tree_abstraction": result.get("tree_abstraction"),
        "parse_stats": result.get("parse_stats")
    }


@router.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "version": "3.1.0-skynet",
        "active_sessions": len(active_sessions),
        "supported_benchmarks": [t.value for t in BenchmarkType],
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/stats")
async def get_stats():
    """获取统计信息"""
    sessions_by_status = {}
    sessions_by_type = {}
    total_tokens = 0
    total_api_calls = 0
    
    for session in active_sessions.values():
        sessions_by_status[session.status] = sessions_by_status.get(session.status, 0) + 1
        btype = session.task.benchmark_type.value
        sessions_by_type[btype] = sessions_by_type.get(btype, 0) + 1
        total_tokens += session.metrics.get("total_tokens", 0)
        total_api_calls += session.metrics.get("total_api_calls", 0)
    
    # 计算平均指标
    completed_sessions = [s for s in active_sessions.values() if s.status == "completed"]
    avg_ecr = sum(s.metrics.get("execution_completion_rate", 0) for s in completed_sessions) / len(completed_sessions) if completed_sessions else 0
    avg_tpr = sum(s.metrics.get("task_pass_rate", 0) for s in completed_sessions) / len(completed_sessions) if completed_sessions else 0
    
    return {
        "active_sessions": len(active_sessions),
        "sessions_by_status": sessions_by_status,
        "sessions_by_type": sessions_by_type,
        "aggregate_metrics": {
            "total_tokens": total_tokens,
            "total_api_calls": total_api_calls,
            "avg_execution_completion_rate": round(avg_ecr, 4),
            "avg_task_pass_rate": round(avg_tpr, 4)
        },
        "available_tasks": {
            "gittaskbench": len(GITTASKBENCH_TASKS),
            "swe_bench": len(SWE_BENCH_TASKS),
            "mle_bench": len(MLE_BENCH_TASKS)
        }
    }


@router.delete("/sessions")
async def clear_sessions(current_user: User = Depends(get_current_user)):
    """清除已完成的会话"""
    cleared = 0
    for session_id in list(active_sessions.keys()):
        session = active_sessions[session_id]
        if session.user_id == str(current_user.id) and session.status in ["completed", "failed", "cancelled"]:
            del active_sessions[session_id]
            cleared += 1
    
    return {"success": True, "cleared": cleared}