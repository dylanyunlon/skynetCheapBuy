"""
Event Stream — SSE Event Types and Formatting for Agentic Loop v7
==================================================================
Defines all event types emitted by the Agentic Loop, matching
Claude Code's frontend event contract:

Event types:
  start            — Session started
  progress         — Turn progress update
  thinking         — Model is thinking
  text             — Text response from model
  tool_start       — Tool execution beginning
  tool_result      — Tool execution completed
  file_change      — File was created/modified/deleted
  turn             — Turn completed with summary
  todo_update      — TODO list changed
  subagent_start   — Sub-agent spawned
  subagent_result  — Sub-agent completed
  usage            — Token usage stats
  context_compact  — Context window compacted
  approval_needed  — User approval required for risky op
  error            — Error occurred
  done             — Session completed
  heartbeat        — Keep-alive ping

Drop-in at: app/core/agents/event_stream.py
"""

import json
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    """All event types emitted by the Agentic Loop"""
    START = "start"
    PROGRESS = "progress"
    THINKING = "thinking"
    TEXT = "text"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    FILE_CHANGE = "file_change"
    TURN = "turn"
    TODO_UPDATE = "todo_update"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_RESULT = "subagent_result"
    USAGE = "usage"
    CONTEXT_COMPACT = "context_compact"
    APPROVAL_NEEDED = "approval_needed"
    ERROR = "error"
    DONE = "done"
    HEARTBEAT = "heartbeat"


@dataclass
class AgenticEvent:
    """A single event emitted by the loop"""
    type: EventType
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    session_id: Optional[str] = None
    turn: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a flat dict suitable for JSON serialization"""
        result = {"type": self.type.value, **self.data}
        if self.turn is not None:
            result["turn"] = self.turn
        if self.session_id:
            result["session_id"] = self.session_id
        result["timestamp"] = self.timestamp
        return result

    def to_sse(self) -> str:
        """Format as Server-Sent Event string"""
        data = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"data: {data}\n\n"


class EventBuilder:
    """
    Helper to build standardized events for the Agentic Loop.
    Ensures consistent event structure across the codebase.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id

    def _event(self, event_type: EventType, data: Dict, turn: int = None) -> Dict:
        """Build a standard event dict (legacy format for yield)"""
        ev = {"type": event_type.value, **data}
        if turn is not None:
            ev["turn"] = turn
        ev["timestamp"] = time.time()
        return ev

    # === Session lifecycle events ===

    def start(self, task: str, model: str, work_dir: str,
              max_turns: int, version: str = "v7") -> Dict:
        return self._event(EventType.START, {
            "task": task[:500],
            "model": model,
            "work_dir": work_dir,
            "max_turns": max_turns,
            "version": version,
        })

    def progress(self, turn: int, max_turns: int,
                 total_tool_calls: int, elapsed: float) -> Dict:
        return self._event(EventType.PROGRESS, {
            "total_tool_calls": total_tool_calls,
            "elapsed": round(elapsed, 2),
            "max_turns": max_turns,
        }, turn=turn)

    def done(self, turns: int, total_tool_calls: int, duration: float,
             stop_reason: str, work_dir: str, file_changes: List,
             input_tokens: int, output_tokens: int, cost: float,
             todo_status: Dict = None) -> Dict:
        return self._event(EventType.DONE, {
            "turns": turns,
            "total_tool_calls": total_tool_calls,
            "duration": round(duration, 2),
            "stop_reason": stop_reason,
            "work_dir": work_dir,
            "file_changes": file_changes[-20:],
            "total_input_tokens": input_tokens,
            "total_output_tokens": output_tokens,
            "total_cost": round(cost, 6),
            "todo_status": todo_status or {},
        })

    def error(self, message: str, turn: int = None, **extra) -> Dict:
        return self._event(EventType.ERROR, {
            "message": message, **extra
        }, turn=turn)

    # === Content events ===

    def text(self, content: str, turn: int) -> Dict:
        return self._event(EventType.TEXT, {"content": content}, turn=turn)

    def thinking(self, content: str, turn: int) -> Dict:
        return self._event(EventType.THINKING, {"content": content}, turn=turn)

    # === Tool events ===

    def tool_start(self, tool: str, args: Dict, tool_use_id: str,
                   description: str, turn: int) -> Dict:
        return self._event(EventType.TOOL_START, {
            "tool": tool,
            "args": args,
            "tool_use_id": tool_use_id,
            "description": description,
        }, turn=turn)

    def tool_result(self, tool: str, tool_use_id: str, result: str,
                    result_meta: Dict, success: bool, turn: int,
                    duration_ms: float = 0) -> Dict:
        return self._event(EventType.TOOL_RESULT, {
            "tool": tool,
            "tool_use_id": tool_use_id,
            "result": result,
            "result_meta": result_meta,
            "success": success,
            "duration_ms": round(duration_ms, 1),
        }, turn=turn)

    def file_change(self, action: str, path: str, filename: str,
                    added: int = 0, removed: int = 0, turn: int = None) -> Dict:
        return self._event(EventType.FILE_CHANGE, {
            "action": action,
            "path": path,
            "filename": filename,
            "added": added,
            "removed": removed,
        }, turn=turn)

    # === Turn summary ===

    def turn_summary(self, turn: int, tool_calls_count: int,
                     total_tool_calls: int, summary: Dict,
                     display: str, detail_items: List) -> Dict:
        return self._event(EventType.TURN, {
            "tool_calls_this_turn": tool_calls_count,
            "total_tool_calls": total_tool_calls,
            "summary": summary,
            "display": display,
            "detail_items": detail_items,
        }, turn=turn)

    # === Token usage ===

    def usage(self, turn: int, input_tokens: int, output_tokens: int,
              total_input: int, total_output: int,
              turn_cost: float, total_cost: float,
              context_tokens: int) -> Dict:
        return self._event(EventType.USAGE, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "turn_cost": round(turn_cost, 6),
            "total_cost": round(total_cost, 6),
            "context_tokens_est": context_tokens,
        }, turn=turn)

    # === Planning / TODO ===

    def todo_update(self, turn: int, todo_status: Dict) -> Dict:
        return self._event(EventType.TODO_UPDATE, {
            "todo_status": todo_status,
        }, turn=turn)

    # === Sub-agent ===

    def subagent_start(self, tool_use_id: str, subagent_type: str,
                       prompt: str, turn: int) -> Dict:
        return self._event(EventType.SUBAGENT_START, {
            "tool_use_id": tool_use_id,
            "subagent_type": subagent_type,
            "prompt": prompt[:200],
        }, turn=turn)

    def subagent_result(self, tool_use_id: str, result: str,
                        result_meta: Dict, subagent_type: str, turn: int) -> Dict:
        return self._event(EventType.SUBAGENT_RESULT, {
            "tool_use_id": tool_use_id,
            "result": result,
            "result_meta": result_meta,
            "subagent_type": subagent_type,
        }, turn=turn)

    # === Context management ===

    def context_compact(self, before_tokens: int, after_tokens: int,
                        before_messages: int, after_messages: int,
                        turn: int) -> Dict:
        return self._event(EventType.CONTEXT_COMPACT, {
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "before_messages": before_messages,
            "after_messages": after_messages,
            "savings_pct": round((1 - after_tokens / max(before_tokens, 1)) * 100, 1),
        }, turn=turn)

    # === Permission / Approval ===

    def approval_needed(self, tool: str, command: str,
                        risk_level: str, tool_use_id: str, turn: int) -> Dict:
        return self._event(EventType.APPROVAL_NEEDED, {
            "tool": tool,
            "command": command,
            "risk_level": risk_level,
            "tool_use_id": tool_use_id,
        }, turn=turn)

    # === Heartbeat ===

    def heartbeat(self, elapsed: float) -> Dict:
        return self._event(EventType.HEARTBEAT, {
            "elapsed": round(elapsed, 1),
        })


def format_sse(event: Dict) -> str:
    """Format an event dict as an SSE string"""
    data = json.dumps(event, ensure_ascii=False)
    return f"data: {data}\n\n"


def format_sse_heartbeat() -> str:
    """Format a heartbeat SSE"""
    return f"data: {json.dumps({'type': 'heartbeat', 'timestamp': time.time()})}\n\n"
