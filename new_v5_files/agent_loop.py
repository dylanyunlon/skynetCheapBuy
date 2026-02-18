"""
Skynet Agentic Loop - Master Agent Loop Engine
================================================
Based on Claude Code's architecture:
- Single-threaded master loop (Think → Act → Observe → Repeat)
- Tool-driven autonomy with model-controlled flow
- Context window management with auto-compaction
- Sub-agent support for parallel tasks

Core Pattern: while(tool_call) → execute tool → feed results → repeat
The loop continues as long as the model's response includes tool usage;
when the model produces plain text without tool calls, the loop terminates.
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum

from .tool_registry import ToolRegistry
from .context_manager import ContextManager
from .event_queue import EventQueue


class LoopStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    ERROR = "error"


class StepType(str, Enum):
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    TEXT_RESPONSE = "text_response"
    ERROR = "error"
    SUMMARY = "summary"


@dataclass
class ToolCall:
    """Represents a single tool invocation"""
    id: str
    tool_name: str
    arguments: Dict[str, Any]
    description: str = ""
    status: str = "pending"  # pending, running, completed, failed
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    @property
    def duration_ms(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at) * 1000
        return None


@dataclass
class AgentStep:
    """A single step in the agentic loop"""
    id: str
    step_type: StepType
    content: Any
    tool_calls: List[ToolCall] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    
    # UI display fields (mimicking Claude Code's UI)
    display_title: str = ""
    display_detail: str = ""
    is_collapsed: bool = False
    files_changed: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class LoopSession:
    """Tracks an entire agentic loop session"""
    session_id: str
    status: LoopStatus = LoopStatus.IDLE
    steps: List[AgentStep] = field(default_factory=list)
    total_tool_calls: int = 0
    total_files_viewed: int = 0
    total_files_edited: int = 0
    total_commands_run: int = 0
    total_searches: int = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    
    # Context management
    messages: List[Dict[str, Any]] = field(default_factory=list)
    context_usage_pct: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "steps": [self._step_to_dict(s) for s in self.steps],
            "stats": {
                "total_tool_calls": self.total_tool_calls,
                "total_files_viewed": self.total_files_viewed,
                "total_files_edited": self.total_files_edited,
                "total_commands_run": self.total_commands_run,
                "total_searches": self.total_searches,
            },
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "context_usage_pct": self.context_usage_pct,
        }
    
    def _step_to_dict(self, step: AgentStep) -> Dict:
        return {
            "id": step.id,
            "step_type": step.step_type.value,
            "display_title": step.display_title,
            "display_detail": step.display_detail,
            "is_collapsed": step.is_collapsed,
            "files_changed": step.files_changed,
            "tool_calls": [
                {
                    "id": tc.id,
                    "tool_name": tc.tool_name,
                    "description": tc.description,
                    "status": tc.status,
                    "duration_ms": tc.duration_ms,
                }
                for tc in step.tool_calls
            ],
            "timestamp": step.timestamp,
        }


class AgentLoop:
    """
    The Master Agent Loop - core of the Skynet agentic system.
    
    Implements the TAOR pattern:
    Think → Act → Observe → Repeat
    
    Mirrors Claude Code's single-threaded master loop with:
    - Tool registry for extensible capabilities
    - Context window management
    - Real-time event streaming (SSE)
    - Sub-agent spawning for parallel tasks
    - Interrupt/resume support
    """
    
    MAX_ITERATIONS = 100  # Safety rail: max loop iterations
    CONTEXT_COMPACT_THRESHOLD = 0.92  # Compact at 92% usage (like Claude Code)
    
    def __init__(
        self,
        tool_registry: ToolRegistry,
        context_manager: ContextManager,
        event_queue: EventQueue,
        llm_client: Any = None,
        max_iterations: int = MAX_ITERATIONS,
    ):
        self.tool_registry = tool_registry
        self.context_manager = context_manager
        self.event_queue = event_queue
        self.llm_client = llm_client
        self.max_iterations = max_iterations
        self._current_session: Optional[LoopSession] = None
        self._interrupt_flag = False
        self._pause_flag = False
    
    async def run(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict, None]:
        """
        Execute the agentic loop.
        
        Yields events as they happen for real-time SSE streaming.
        The loop continues until the model stops requesting tools
        or max_iterations is reached.
        """
        session = LoopSession(
            session_id=session_id or str(uuid.uuid4()),
            status=LoopStatus.RUNNING,
            started_at=time.time(),
        )
        self._current_session = session
        self._interrupt_flag = False
        
        # Initialize context
        messages = self.context_manager.build_messages(
            user_message=user_message,
            system_prompt=system_prompt,
        )
        session.messages = messages
        
        yield self._emit_event("session_start", session.to_dict())
        
        iteration = 0
        while iteration < self.max_iterations:
            # Check for interrupts
            if self._interrupt_flag:
                session.status = LoopStatus.PAUSED
                yield self._emit_event("session_paused", {"reason": "user_interrupt"})
                break
            
            if self._pause_flag:
                session.status = LoopStatus.WAITING_APPROVAL
                yield self._emit_event("waiting_approval", {})
                # Wait for resume signal
                while self._pause_flag and not self._interrupt_flag:
                    await asyncio.sleep(0.1)
                if self._interrupt_flag:
                    break
                session.status = LoopStatus.RUNNING
            
            iteration += 1
            
            # === THINK: Get model response ===
            yield self._emit_event("thinking", {"iteration": iteration})
            
            try:
                response = await self._call_llm(messages)
            except Exception as e:
                session.status = LoopStatus.ERROR
                session.error = str(e)
                yield self._emit_event("error", {"message": str(e)})
                break
            
            # Parse response for tool calls
            tool_calls = self._extract_tool_calls(response)
            text_content = self._extract_text(response)
            
            # If no tool calls, the model is done - loop terminates
            if not tool_calls:
                step = AgentStep(
                    id=str(uuid.uuid4()),
                    step_type=StepType.TEXT_RESPONSE,
                    content=text_content,
                    display_title="Response",
                    display_detail=text_content[:200] if text_content else "",
                )
                session.steps.append(step)
                yield self._emit_event("text_response", {
                    "content": text_content,
                    "step": session._step_to_dict(step),
                })
                session.status = LoopStatus.COMPLETED
                break
            
            # === ACT: Execute tool calls ===
            step = AgentStep(
                id=str(uuid.uuid4()),
                step_type=StepType.TOOL_CALL,
                content=None,
                tool_calls=tool_calls,
            )
            
            # Generate display title (like Claude Code's UI)
            step.display_title = self._generate_step_title(tool_calls)
            step.display_detail = self._generate_step_detail(tool_calls)
            
            yield self._emit_event("tool_calls_start", {
                "step_id": step.id,
                "display_title": step.display_title,
                "tool_count": len(tool_calls),
                "tools": [{"name": tc.tool_name, "description": tc.description} for tc in tool_calls],
            })
            
            # Execute each tool call
            tool_results = []
            for tc in tool_calls:
                tc.status = "running"
                tc.started_at = time.time()
                
                yield self._emit_event("tool_executing", {
                    "tool_call_id": tc.id,
                    "tool_name": tc.tool_name,
                    "description": tc.description,
                })
                
                try:
                    result = await self.tool_registry.execute(
                        tc.tool_name, tc.arguments
                    )
                    tc.result = result
                    tc.status = "completed"
                    tc.completed_at = time.time()
                    
                    # Track stats
                    session.total_tool_calls += 1
                    self._update_stats(session, tc)
                    
                    yield self._emit_event("tool_completed", {
                        "tool_call_id": tc.id,
                        "tool_name": tc.tool_name,
                        "duration_ms": tc.duration_ms,
                        "result_preview": self._preview_result(result),
                    })
                    
                    tool_results.append({
                        "tool_use_id": tc.id,
                        "content": json.dumps(result) if isinstance(result, dict) else str(result),
                    })
                    
                except Exception as e:
                    tc.status = "failed"
                    tc.error = str(e)
                    tc.completed_at = time.time()
                    
                    yield self._emit_event("tool_error", {
                        "tool_call_id": tc.id,
                        "tool_name": tc.tool_name,
                        "error": str(e),
                    })
                    
                    tool_results.append({
                        "tool_use_id": tc.id,
                        "content": f"Error: {e}",
                        "is_error": True,
                    })
            
            # Collect file changes from edit tools
            step.files_changed = self._collect_file_changes(tool_calls)
            session.steps.append(step)
            
            yield self._emit_event("step_completed", {
                "step": session._step_to_dict(step),
                "stats": session.to_dict()["stats"],
            })
            
            # === OBSERVE: Feed results back to model ===
            # Add assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": response.get("content", []),
            })
            
            # Add tool results
            for tr in tool_results:
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tr["tool_use_id"],
                        "content": tr["content"],
                    }],
                })
            
            # Context management: check if compaction needed
            session.context_usage_pct = self.context_manager.get_usage_pct(messages)
            if session.context_usage_pct > self.CONTEXT_COMPACT_THRESHOLD:
                yield self._emit_event("context_compacting", {
                    "usage_pct": session.context_usage_pct,
                })
                messages = await self.context_manager.compact(messages)
                yield self._emit_event("context_compacted", {
                    "new_usage_pct": self.context_manager.get_usage_pct(messages),
                })
            
            session.messages = messages
            # === REPEAT: Continue the loop ===
        
        # Loop ended
        if session.status == LoopStatus.RUNNING:
            if iteration >= self.max_iterations:
                session.status = LoopStatus.ERROR
                session.error = f"Max iterations ({self.max_iterations}) reached"
                yield self._emit_event("max_iterations", {"max": self.max_iterations})
            else:
                session.status = LoopStatus.COMPLETED
        
        session.completed_at = time.time()
        yield self._emit_event("session_complete", session.to_dict())
    
    def interrupt(self):
        """Interrupt the current loop (like Ctrl+C in Claude Code)"""
        self._interrupt_flag = True
    
    def pause(self):
        """Pause the loop and wait for approval"""
        self._pause_flag = True
    
    def resume(self):
        """Resume a paused loop"""
        self._pause_flag = False
    
    # === Private helpers ===
    
    async def _call_llm(self, messages: List[Dict]) -> Dict:
        """Call the LLM with tool definitions"""
        if self.llm_client:
            return await self.llm_client.chat(
                messages=messages,
                tools=self.tool_registry.get_tool_definitions(),
            )
        # Fallback: mock response for testing
        return {"content": [{"type": "text", "text": "Task completed."}]}
    
    def _extract_tool_calls(self, response: Dict) -> List[ToolCall]:
        """Extract tool calls from LLM response"""
        tool_calls = []
        for block in response.get("content", []):
            if block.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", str(uuid.uuid4())),
                    tool_name=block["name"],
                    arguments=block.get("input", {}),
                    description=block.get("input", {}).get("description", ""),
                ))
        return tool_calls
    
    def _extract_text(self, response: Dict) -> str:
        """Extract text content from LLM response"""
        texts = []
        for block in response.get("content", []):
            if block.get("type") == "text":
                texts.append(block["text"])
        return "\n".join(texts)
    
    def _generate_step_title(self, tool_calls: List[ToolCall]) -> str:
        """
        Generate Claude Code-style step titles:
        - "Ran 7 commands" 
        - "Viewed 3 files"
        - "Ran a command, edited a file"
        - "Searched the web"
        """
        actions = {}
        for tc in tool_calls:
            category = self._categorize_tool(tc.tool_name)
            actions[category] = actions.get(category, 0) + 1
        
        parts = []
        for category, count in actions.items():
            if category == "command":
                parts.append(f"Ran {count} command{'s' if count > 1 else ''}")
            elif category == "view":
                parts.append(f"Viewed {count} file{'s' if count > 1 else ''}")
            elif category == "edit":
                parts.append(f"edited {count} file{'s' if count > 1 else ''}")
            elif category == "search":
                parts.append("Searched the web")
            elif category == "fetch":
                parts.append(f"Fetched {count} page{'s' if count > 1 else ''}")
        
        return ", ".join(parts) if parts else "Processing"
    
    def _generate_step_detail(self, tool_calls: List[ToolCall]) -> str:
        """Generate detail text for each tool call"""
        details = []
        for tc in tool_calls:
            if tc.description:
                details.append(tc.description)
            else:
                details.append(f"{tc.tool_name}: {json.dumps(tc.arguments)[:100]}")
        return "\n".join(details)
    
    def _categorize_tool(self, tool_name: str) -> str:
        """Categorize tools for display grouping"""
        categories = {
            "bash": "command",
            "run_command": "command",
            "execute_script": "command",
            "view_file": "view",
            "read_file": "view",
            "view_truncated": "view",
            "glob": "view",
            "grep": "view",
            "ls": "view",
            "edit_file": "edit",
            "write_file": "edit",
            "multi_edit": "edit",
            "str_replace": "edit",
            "web_search": "search",
            "web_fetch": "fetch",
            "todo_read": "todo",
            "todo_write": "todo",
        }
        return categories.get(tool_name, "other")
    
    def _update_stats(self, session: LoopSession, tc: ToolCall):
        """Update session statistics based on tool call"""
        category = self._categorize_tool(tc.tool_name)
        if category == "command":
            session.total_commands_run += 1
        elif category == "view":
            session.total_files_viewed += 1
        elif category == "edit":
            session.total_files_edited += 1
        elif category == "search":
            session.total_searches += 1
    
    def _collect_file_changes(self, tool_calls: List[ToolCall]) -> List[Dict]:
        """Collect file change info for display (like +3, -4 in Claude Code)"""
        changes = []
        for tc in tool_calls:
            if tc.tool_name in ("edit_file", "str_replace", "multi_edit", "write_file"):
                result = tc.result or {}
                if isinstance(result, dict):
                    changes.append({
                        "file": result.get("file", tc.arguments.get("path", "unknown")),
                        "additions": result.get("additions", 0),
                        "deletions": result.get("deletions", 0),
                    })
        return changes
    
    def _preview_result(self, result: Any, max_len: int = 500) -> str:
        """Create a preview of tool result for streaming"""
        if isinstance(result, dict):
            text = json.dumps(result, ensure_ascii=False)
        else:
            text = str(result)
        return text[:max_len] + ("..." if len(text) > max_len else "")
    
    def _emit_event(self, event_type: str, data: Dict) -> Dict:
        """Create a standardized event for SSE streaming"""
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
            "session_id": self._current_session.session_id if self._current_session else None,
        }
        # Also push to event queue for other listeners
        self.event_queue.push(event)
        return event
