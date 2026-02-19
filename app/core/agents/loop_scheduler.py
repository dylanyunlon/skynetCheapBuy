"""
Loop Scheduler — Optimized Tool Execution Interleaving for Agentic Loop v8
=============================================================================
Based on Claude Code's per-chunk scheduling (Feature #15):

  ★ ChunkScheduler   — Group tool calls into interleaved chunks
  ★ PipelineOptimizer — Reorder independent ops for max parallelism
  ★ BatchCollector    — Aggregate multiple reads/commands into batches

The key insight: instead of executing all tool calls sequentially per turn,
we can identify independent operations and interleave them for better
throughput. This matches Claude Code's "Restructure main loop to emit
per-chunk (all rounds for each chunk) for better scheduler interleaving."

Drop-in at: app/core/agents/loop_scheduler.py
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class DependencyType(str, Enum):
    """Types of dependencies between tool calls"""
    NONE = "none"           # Fully independent
    FILE_READ = "file_read"  # Reads a file that might be written
    FILE_WRITE = "file_write"  # Writes a file that might be read
    SEQUENTIAL = "sequential"  # Must run in order
    SAME_FILE = "same_file"    # Operates on same file


@dataclass
class ScheduledCall:
    """A tool call with scheduling metadata"""
    tool_name: str
    tool_input: Dict[str, Any]
    tool_use_id: str
    # Scheduling
    chunk_id: int = 0
    can_parallel: bool = False
    depends_on: List[str] = field(default_factory=list)
    # Execution
    result: Optional[str] = None
    duration_ms: float = 0
    executed: bool = False
    
    @property
    def target_path(self) -> Optional[str]:
        """Get the file path this call operates on"""
        return (
            self.tool_input.get("path") or
            self.tool_input.get("paths", [None])[0] if self.tool_input.get("paths") else
            None
        )
    
    @property
    def is_read_only(self) -> bool:
        """Check if this call only reads data"""
        return self.tool_name in (
            "read_file", "batch_read", "view_truncated", "list_dir",
            "grep_search", "file_search", "glob", "todo_read",
            "memory_read", "web_search", "web_fetch",
        )
    
    @property
    def is_write(self) -> bool:
        """Check if this call modifies files"""
        return self.tool_name in (
            "write_file", "edit_file", "multi_edit", "revert_edit",
        )


class ChunkScheduler:
    """
    Organize tool calls into optimally ordered chunks.
    
    Strategy:
    1. Analyze dependencies between tool calls
    2. Group independent reads together (can run in parallel)
    3. Serialize writes to the same file
    4. Batch consecutive reads into batch_read when possible
    5. Interleave command execution with file operations
    
    Example:
        Input:  [read_file(a.py), read_file(b.py), edit_file(a.py), bash(test)]
        Output: Chunk 0: [read_file(a.py), read_file(b.py)]  # parallel reads
                Chunk 1: [edit_file(a.py)]                      # depends on read
                Chunk 2: [bash(test)]                            # depends on edit
    """
    
    def schedule(self, tool_calls: List[ScheduledCall]) -> List[List[ScheduledCall]]:
        """
        Schedule tool calls into execution chunks.
        Returns list of chunks, each chunk contains calls that can run in parallel.
        """
        if not tool_calls:
            return []
        
        if len(tool_calls) == 1:
            tool_calls[0].chunk_id = 0
            return [tool_calls]
        
        # Build dependency graph
        deps = self._analyze_dependencies(tool_calls)
        
        # Topological sort into chunks
        chunks = self._build_chunks(tool_calls, deps)
        
        return chunks
    
    def _analyze_dependencies(
        self, calls: List[ScheduledCall]
    ) -> Dict[str, Set[str]]:
        """
        Analyze dependencies between tool calls.
        Returns: {tool_use_id: set of tool_use_ids it depends on}
        """
        deps: Dict[str, Set[str]] = {c.tool_use_id: set() for c in calls}
        
        # Track which files are read/written by which calls
        file_writers: Dict[str, str] = {}  # path -> tool_use_id of writer
        file_readers: Dict[str, List[str]] = {}  # path -> list of reader tool_use_ids
        
        for i, call in enumerate(calls):
            path = call.target_path
            
            if path:
                # If this call writes a file that was previously read
                if call.is_write:
                    # Depends on all previous reads of this file
                    for reader_id in file_readers.get(path, []):
                        if reader_id != call.tool_use_id:
                            deps[call.tool_use_id].add(reader_id)
                    
                    # Depends on previous writer of this file (serialize writes)
                    if path in file_writers:
                        deps[call.tool_use_id].add(file_writers[path])
                    
                    file_writers[path] = call.tool_use_id
                
                elif call.is_read_only:
                    # If reading a file that was previously written
                    if path in file_writers:
                        deps[call.tool_use_id].add(file_writers[path])
                    
                    if path not in file_readers:
                        file_readers[path] = []
                    file_readers[path].append(call.tool_use_id)
            
            # bash commands and task_complete are sequential by default
            if call.tool_name in ("bash", "batch_commands", "run_script", "task_complete"):
                # Depends on all previous writes
                for prev_call in calls[:i]:
                    if prev_call.is_write or prev_call.tool_name in ("bash", "batch_commands"):
                        deps[call.tool_use_id].add(prev_call.tool_use_id)
            
            # Sub-agent tasks depend on everything before them
            if call.tool_name == "task":
                for prev_call in calls[:i]:
                    deps[call.tool_use_id].add(prev_call.tool_use_id)
        
        return deps
    
    def _build_chunks(
        self, 
        calls: List[ScheduledCall], 
        deps: Dict[str, Set[str]]
    ) -> List[List[ScheduledCall]]:
        """Build execution chunks using topological sorting"""
        chunks: List[List[ScheduledCall]] = []
        scheduled: Set[str] = set()
        call_map = {c.tool_use_id: c for c in calls}
        remaining = set(c.tool_use_id for c in calls)
        
        chunk_id = 0
        while remaining:
            # Find all calls whose dependencies are satisfied
            ready = []
            for tid in remaining:
                unmet = deps[tid] - scheduled
                if not unmet:
                    ready.append(tid)
            
            if not ready:
                # Circular dependency fallback: just take the first remaining
                logger.warning("Circular dependency detected in tool scheduling")
                ready = [next(iter(remaining))]
            
            chunk = []
            for tid in ready:
                call = call_map[tid]
                call.chunk_id = chunk_id
                call.can_parallel = len(ready) > 1
                chunk.append(call)
                scheduled.add(tid)
                remaining.discard(tid)
            
            chunks.append(chunk)
            chunk_id += 1
        
        return chunks


class PipelineOptimizer:
    """
    Optimize the execution pipeline by batching similar operations.
    
    Optimizations:
    1. Merge consecutive read_file calls into batch_read
    2. Merge consecutive bash commands into batch_commands 
    3. Identify safe parallel execution opportunities
    """
    
    @staticmethod
    def optimize_reads(calls: List[ScheduledCall]) -> List[ScheduledCall]:
        """
        Merge multiple consecutive read_file calls into a single batch_read.
        Only merges reads that are in the same chunk.
        """
        if not calls:
            return calls
        
        result = []
        read_buffer: List[ScheduledCall] = []
        
        for call in calls:
            if call.tool_name == "read_file" and not call.tool_input.get("start_line"):
                read_buffer.append(call)
            else:
                # Flush read buffer
                if len(read_buffer) > 1:
                    # Create batch_read
                    paths = [c.tool_input["path"] for c in read_buffer]
                    batch = ScheduledCall(
                        tool_name="batch_read",
                        tool_input={
                            "paths": paths,
                            "description": f"Read {len(paths)} files",
                        },
                        tool_use_id=read_buffer[0].tool_use_id,
                        chunk_id=read_buffer[0].chunk_id,
                    )
                    result.append(batch)
                elif read_buffer:
                    result.extend(read_buffer)
                read_buffer = []
                result.append(call)
        
        # Flush remaining
        if len(read_buffer) > 1:
            paths = [c.tool_input["path"] for c in read_buffer]
            batch = ScheduledCall(
                tool_name="batch_read",
                tool_input={"paths": paths, "description": f"Read {len(paths)} files"},
                tool_use_id=read_buffer[0].tool_use_id,
                chunk_id=read_buffer[0].chunk_id,
            )
            result.append(batch)
        elif read_buffer:
            result.extend(read_buffer)
        
        return result
    
    @staticmethod
    def can_parallelize(chunk: List[ScheduledCall]) -> bool:
        """Check if a chunk of calls can safely run in parallel"""
        if len(chunk) <= 1:
            return False
        
        # All reads are safe to parallelize
        if all(c.is_read_only for c in chunk):
            return True
        
        # Check for conflicting file writes
        write_paths = set()
        for c in chunk:
            if c.is_write:
                path = c.target_path
                if path in write_paths:
                    return False  # Two writes to same file
                write_paths.add(path)
        
        # Check that no read targets overlap with write targets
        for c in chunk:
            if c.is_read_only and c.target_path in write_paths:
                return False
        
        return True


class ExecutionTracker:
    """
    Track execution statistics for turn summary generation.
    Generates Claude Code-style summaries like:
    - "Ran 7 commands"
    - "Viewed 3 files"
    - "Ran a command, edited a file"
    - "Searched the web"
    """
    
    def __init__(self):
        self.tool_calls: List[Dict[str, Any]] = []
    
    def record(self, tool_name: str, tool_input: Dict, duration_ms: float,
               success: bool, result_meta: Dict = None):
        """Record a tool execution"""
        self.tool_calls.append({
            "tool": tool_name,
            "input": tool_input,
            "duration_ms": duration_ms,
            "success": success,
            "meta": result_meta or {},
            "timestamp": time.time(),
        })
    
    def build_turn_display(self) -> str:
        """
        Build Claude Code-style turn display string.
        Examples:
            "Ran 7 commands"
            "Viewed 3 files"
            "Ran a command, edited a file"
            "Ran 14 commands, viewed a file, edited a file"
        """
        categories = {}
        for tc in self.tool_calls:
            cat = self._categorize(tc["tool"])
            categories[cat] = categories.get(cat, 0) + 1
        
        parts = []
        category_order = ["command", "view", "edit", "search", "web", "agent"]
        
        for cat in category_order:
            count = categories.get(cat, 0)
            if count == 0:
                continue
            
            if cat == "command":
                if count == 1:
                    parts.append("Ran a command")
                else:
                    parts.append(f"Ran {count} commands")
            elif cat == "view":
                if count == 1:
                    parts.append("viewed a file")
                else:
                    parts.append(f"viewed {count} files")
            elif cat == "edit":
                if count == 1:
                    parts.append("edited a file")
                else:
                    parts.append(f"edited {count} files")
            elif cat == "search":
                parts.append("Searched the web")
            elif cat == "web":
                if count == 1:
                    parts.append("fetched a page")
                else:
                    parts.append(f"fetched {count} pages")
            elif cat == "agent":
                parts.append(f"ran {count} sub-agent(s)")
        
        if not parts:
            return "Processing"
        
        # Capitalize first part
        result = parts[0]
        if len(parts) > 1:
            result += ", " + ", ".join(parts[1:])
        
        return result
    
    def build_detail_items(self) -> List[Dict[str, str]]:
        """Build detail items for each tool call (expandable in UI)"""
        items = []
        for tc in self.tool_calls:
            desc = tc["input"].get("description", "")
            if not desc:
                desc = self._auto_description(tc["tool"], tc["input"])
            
            items.append({
                "tool": tc["tool"],
                "description": desc,
                "duration_ms": tc["duration_ms"],
                "success": tc["success"],
                "meta": tc["meta"],
            })
        return items
    
    def _categorize(self, tool_name: str) -> str:
        """Categorize tool for display"""
        cats = {
            "bash": "command", "batch_commands": "command", "run_script": "command",
            "read_file": "view", "batch_read": "view", "view_truncated": "view",
            "list_dir": "view", "grep_search": "view", "file_search": "view", "glob": "view",
            "write_file": "edit", "edit_file": "edit", "multi_edit": "edit", "revert_edit": "edit",
            "web_search": "search", "web_fetch": "web",
            "task": "agent",
        }
        return cats.get(tool_name, "other")
    
    def _auto_description(self, tool_name: str, args: Dict) -> str:
        """Generate auto description for tools without explicit description"""
        if tool_name == "bash":
            cmd = args.get("command", "")
            return cmd[:80] + ("..." if len(cmd) > 80 else "")
        elif tool_name in ("read_file", "view_truncated"):
            return f"View {args.get('path', 'file')}"
        elif tool_name == "edit_file":
            return f"Edit {args.get('path', 'file')}"
        elif tool_name == "write_file":
            return f"Create {args.get('path', 'file')}"
        elif tool_name == "web_search":
            return args.get("query", "Search")
        elif tool_name == "web_fetch":
            return f"Fetch {args.get('url', 'page')}"
        elif tool_name == "grep_search":
            return f"Search for '{args.get('pattern', '')}'"
        return tool_name
    
    def reset(self):
        """Reset for new turn"""
        self.tool_calls = []
