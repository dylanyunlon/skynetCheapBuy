"""
Event Stream — SSE Event Types and Formatting for Agentic Loop v9
==================================================================
v9 新增事件类型:
  debug_start      — Debug cycle started
  debug_result     — Debug cycle completed
  test_result      — Test execution result
  revert           — File revert operation
  diff_summary     — Cumulative diff summary
  approval_wait    — Waiting for user approval (with timeout)
  chunk_schedule   — Tool call scheduling info

v7 全部保留:
  start, progress, thinking, text, tool_start, tool_result,
  file_change, turn, todo_update, subagent_start, subagent_result,
  usage, context_compact, approval_needed, error, done, heartbeat

位置: app/core/agents/event_stream.py
"""

import json
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    """All event types emitted by the Agentic Loop"""
    # v7 events
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
    # v9 new events
    DEBUG_START = "debug_start"
    DEBUG_RESULT = "debug_result"
    TEST_RESULT = "test_result"
    REVERT = "revert"
    DIFF_SUMMARY = "diff_summary"
    APPROVAL_WAIT = "approval_wait"
    CHUNK_SCHEDULE = "chunk_schedule"


@dataclass
class AgenticEvent:
    type: EventType
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    session_id: Optional[str] = None
    turn: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {"type": self.type.value, **self.data}
        if self.turn is not None:
            result["turn"] = self.turn
        if self.session_id:
            result["session_id"] = self.session_id
        result["timestamp"] = self.timestamp
        return result

    def to_sse(self) -> str:
        data = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"data: {data}\n\n"


class EventBuilder:
    """Build standardized events for the Agentic Loop v9."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id

    def _event(self, event_type: EventType, data: Dict, turn: int = None) -> Dict:
        ev = {"type": event_type.value, **data}
        if turn is not None:
            ev["turn"] = turn
        ev["timestamp"] = time.time()
        return ev

    # === Session lifecycle ===
    def start(self, task, model, work_dir, max_turns, version="v9"):
        return self._event(EventType.START, {
            "task": task[:500], "model": model, "work_dir": work_dir,
            "max_turns": max_turns, "version": version,
        })

    def progress(self, turn, max_turns, total_tool_calls, elapsed):
        return self._event(EventType.PROGRESS, {
            "total_tool_calls": total_tool_calls, "elapsed": round(elapsed, 2),
            "max_turns": max_turns,
        }, turn=turn)

    def done(self, turns, total_tool_calls, duration, stop_reason, work_dir,
             file_changes, input_tokens, output_tokens, cost,
             todo_status=None, diff_summary=None):
        return self._event(EventType.DONE, {
            "turns": turns, "total_tool_calls": total_tool_calls,
            "duration": round(duration, 2), "stop_reason": stop_reason,
            "work_dir": work_dir, "file_changes": file_changes[-20:],
            "total_input_tokens": input_tokens, "total_output_tokens": output_tokens,
            "total_cost": round(cost, 6),
            "todo_status": todo_status or {}, "diff_summary": diff_summary or {},
        })

    def error(self, message, turn=None, **extra):
        return self._event(EventType.ERROR, {"message": message, **extra}, turn=turn)

    # === Content ===
    def text(self, content, turn):
        return self._event(EventType.TEXT, {"content": content}, turn=turn)

    def thinking(self, content, turn):
        return self._event(EventType.THINKING, {"content": content}, turn=turn)

    # === Tool ===
    def tool_start(self, tool, args, tool_use_id, description, turn):
        return self._event(EventType.TOOL_START, {
            "tool": tool, "args": args, "tool_use_id": tool_use_id,
            "description": description,
        }, turn=turn)

    def tool_result(self, tool, tool_use_id, result, result_meta, success, turn,
                    duration_ms=0):
        return self._event(EventType.TOOL_RESULT, {
            "tool": tool, "tool_use_id": tool_use_id, "result": result,
            "result_meta": result_meta, "success": success,
            "duration_ms": round(duration_ms, 1),
        }, turn=turn)

    def file_change(self, action, path, filename, added=0, removed=0, turn=None):
        return self._event(EventType.FILE_CHANGE, {
            "action": action, "path": path, "filename": filename,
            "added": added, "removed": removed,
        }, turn=turn)

    # === Turn ===
    def turn_summary(self, turn, tool_calls_count, total_tool_calls, summary,
                     display, detail_items):
        return self._event(EventType.TURN, {
            "tool_calls_this_turn": tool_calls_count,
            "total_tool_calls": total_tool_calls,
            "summary": summary, "display": display,
            "detail_items": detail_items,
        }, turn=turn)

    # === Usage ===
    def usage(self, turn, input_tokens, output_tokens, total_input, total_output,
              turn_cost, total_cost, context_tokens):
        return self._event(EventType.USAGE, {
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_input_tokens": total_input, "total_output_tokens": total_output,
            "turn_cost": round(turn_cost, 6), "total_cost": round(total_cost, 6),
            "context_tokens_est": context_tokens,
        }, turn=turn)

    # === TODO ===
    def todo_update(self, turn, todo_status):
        return self._event(EventType.TODO_UPDATE, {"todo_status": todo_status}, turn=turn)

    # === SubAgent ===
    def subagent_start(self, tool_use_id, subagent_type, prompt, turn):
        return self._event(EventType.SUBAGENT_START, {
            "tool_use_id": tool_use_id, "subagent_type": subagent_type,
            "prompt": prompt[:200],
        }, turn=turn)

    def subagent_result(self, tool_use_id, result, result_meta, subagent_type, turn):
        return self._event(EventType.SUBAGENT_RESULT, {
            "tool_use_id": tool_use_id, "result": result,
            "result_meta": result_meta, "subagent_type": subagent_type,
        }, turn=turn)

    # === Context ===
    def context_compact(self, before_tokens, after_tokens, before_messages,
                        after_messages, turn):
        return self._event(EventType.CONTEXT_COMPACT, {
            "before_tokens": before_tokens, "after_tokens": after_tokens,
            "before_messages": before_messages, "after_messages": after_messages,
            "savings_pct": round((1 - after_tokens / max(before_tokens, 1)) * 100, 1),
        }, turn=turn)

    # === Permission ===
    def approval_needed(self, tool, command, risk_level, tool_use_id, turn):
        return self._event(EventType.APPROVAL_NEEDED, {
            "tool": tool, "command": command, "risk_level": risk_level,
            "tool_use_id": tool_use_id,
        }, turn=turn)

    def approval_wait(self, tool, command, risk_level, tool_use_id, timeout_s, turn):
        return self._event(EventType.APPROVAL_WAIT, {
            "tool": tool, "command": command[:200], "risk_level": risk_level,
            "tool_use_id": tool_use_id, "timeout_s": timeout_s,
            "message": f"Waiting for approval: {command[:100]}",
        }, turn=turn)

    # === Heartbeat ===
    def heartbeat(self, elapsed):
        return self._event(EventType.HEARTBEAT, {"elapsed": round(elapsed, 1)})

    # =================================================================
    # v9 新增
    # =================================================================
    def debug_start(self, test_command, iteration, max_iterations, turn):
        return self._event(EventType.DEBUG_START, {
            "test_command": test_command[:200],
            "iteration": iteration, "max_iterations": max_iterations,
        }, turn=turn)

    def debug_result(self, success, iterations, display, turn, **extra):
        return self._event(EventType.DEBUG_RESULT, {
            "success": success, "iterations": iterations, "display": display,
            **extra,
        }, turn=turn)

    def test_result(self, command, passed, exit_code, total_tests, passed_tests,
                    failed_tests, duration_s, turn, failure_details=None):
        return self._event(EventType.TEST_RESULT, {
            "command": command[:200], "passed": passed, "exit_code": exit_code,
            "total_tests": total_tests, "passed_tests": passed_tests,
            "failed_tests": failed_tests, "duration_s": round(duration_s, 2),
            "failure_details": (failure_details or [])[:5],
        }, turn=turn)

    def revert_event(self, path, edit_id, description, diff_display, turn):
        return self._event(EventType.REVERT, {
            "path": path, "edit_id": edit_id,
            "description": description, "diff_display": diff_display,
        }, turn=turn)

    def diff_summary(self, files_changed, total_added, total_removed,
                     file_details, turn):
        return self._event(EventType.DIFF_SUMMARY, {
            "files_changed": files_changed, "total_added": total_added,
            "total_removed": total_removed, "file_details": file_details[:20],
        }, turn=turn)

    def chunk_schedule(self, total_calls, chunks, parallel_calls, turn):
        return self._event(EventType.CHUNK_SCHEDULE, {
            "total_calls": total_calls, "chunks": chunks,
            "parallel_calls": parallel_calls,
        }, turn=turn)


def format_sse(event: Dict) -> str:
    data = json.dumps(event, ensure_ascii=False)
    return f"data: {data}\n\n"

def format_sse_heartbeat() -> str:
    return f"data: {json.dumps({'type': 'heartbeat', 'timestamp': time.time()})}\n\n"