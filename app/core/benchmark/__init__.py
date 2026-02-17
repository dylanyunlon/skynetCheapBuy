# app/core/benchmark/__init__.py
# Benchmark模块 - 非端到端的代码测试框架

from .loaders import *
from .evaluators import *

from .code_extractor import (
    BenchmarkCodeExtractor,
    TreeStructureExtractor,
    ExtractedCodeBlock,
    CodeIntent
)

from .executor import (
    BenchmarkExecutor,
    ExecutionResult,
    ExecutionStep
)

from .session import (
    BenchmarkSessionManager,
    BenchmarkSession,
    BenchmarkStage,
    BenchmarkMetrics,
    StageResult
)

from .loaders import *
from .evaluators import *
from .swe_bench_evaluator import *

__all__ = [
    # 代码提取
    "BenchmarkCodeExtractor",
    "TreeStructureExtractor", 
    "ExtractedCodeBlock",
    "CodeIntent",
    
    # 执行器
    "BenchmarkExecutor",
    "ExecutionResult",
    "ExecutionStep",
    
    # 会话管理
    "BenchmarkSessionManager",
    "BenchmarkSession",
    "BenchmarkStage",
    "BenchmarkMetrics",
    "StageResult"
]
