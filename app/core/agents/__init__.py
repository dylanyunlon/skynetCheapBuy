"""
Skynet Agentic Loop v8 — Claude Code 全功能对标 (v8 完整升级)
==============================================================
v8 新增:
  - DebugAgent: 自动调试循环 (Feature #10-#14)
  - RevertManager: 文件编辑历史 + 安全回退
  - TestRunner: 结构化测试执行
  - CorrectnessChecker: 输出正确性验证
  - DiffTracker: 详细 +N/-M 变更追踪
  - ChunkScheduler: 工具调用交错调度 (Feature #15)
  - PipelineOptimizer: 批量读取/命令优化
  - ExecutionTracker: Claude Code 风格的 turn 摘要生成

模块导出
"""

from .agentic_loop import (
    AgenticLoop,
    ToolExecutor,
    TodoManager,
    create_agentic_loop,
    build_turn_summary,
    TOOL_DEFINITIONS,
    AGENTIC_SYSTEM_PROMPT,
    estimate_tokens,
    estimate_messages_tokens,
    estimate_cost,
)

from .tool_registry import (
    ToolRegistry,
    ToolCategory,
    PermissionLevel,
    ToolDefinition,
)

from .context_manager import (
    ContextManager,
)

from .event_stream import (
    EventBuilder,
    EventType,
    AgenticEvent,
    format_sse,
    format_sse_heartbeat,
)

from .permission_gate import (
    PermissionGate,
    RiskLevel,
)

from .debug_agent import (
    DebugAgent,
    RevertManager,
    TestRunner,
    TestResult,
    CorrectnessChecker,
    DiffTracker,
    EditRecord,
)

from .loop_scheduler import (
    ChunkScheduler,
    PipelineOptimizer,
    ExecutionTracker,
    ScheduledCall,
)

__all__ = [
    # Core loop
    "AgenticLoop",
    "ToolExecutor",
    "TodoManager",
    "create_agentic_loop",
    "build_turn_summary",
    "TOOL_DEFINITIONS",
    "AGENTIC_SYSTEM_PROMPT",
    # Tool registry
    "ToolRegistry",
    "ToolCategory",
    "PermissionLevel",
    "ToolDefinition",
    # Context management
    "ContextManager",
    # Event stream
    "EventBuilder",
    "EventType",
    "AgenticEvent",
    "format_sse",
    "format_sse_heartbeat",
    # Permission gate
    "PermissionGate",
    "RiskLevel",
    # v8: Debug agent
    "DebugAgent",
    "RevertManager",
    "TestRunner",
    "TestResult",
    "CorrectnessChecker",
    "DiffTracker",
    "EditRecord",
    # v8: Loop scheduler
    "ChunkScheduler",
    "PipelineOptimizer",
    "ExecutionTracker",
    "ScheduledCall",
    # Utilities
    "estimate_tokens",
    "estimate_messages_tokens",
    "estimate_cost",
]
