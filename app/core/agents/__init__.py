"""
Skynet Agentic Loop v9 — Claude Code 全功能深度集成版
======================================================
v9 新增:
  - ChunkScheduler 实际接入: 工具调用依赖分析 + 并行调度
  - ExecutionTracker 实际接入: 精确 turn 统计
  - DebugAgent 工具化: debug_test / revert_to_checkpoint 工具
  - DiffSummary 事件: 每 turn 发出累积变更摘要
  - task_complete 自动退出
  - 增强 System Prompt

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
    # Debug agent
    "DebugAgent",
    "RevertManager",
    "TestRunner",
    "TestResult",
    "CorrectnessChecker",
    "DiffTracker",
    "EditRecord",
    # Loop scheduler
    "ChunkScheduler",
    "PipelineOptimizer",
    "ExecutionTracker",
    "ScheduledCall",
    # Utilities
    "estimate_tokens",
    "estimate_messages_tokens",
    "estimate_cost",
]