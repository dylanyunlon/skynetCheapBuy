#!/usr/bin/env python3
"""
CheapBuy Agentic Loop v6 — Claude Code 全功能对标版
====================================================
v6 新增 (对标 Claude Code 2025/2026 内部实现):
  ★ TodoWrite / TodoRead      — 任务规划 + 进度追踪 (Claude Code 核心)
  ★ SubAgent / Task            — 子代理: Explore / Plan / General-purpose
  ★ Context Compaction (wU2)   — 92% 窗口自动压缩 + 长期记忆
  ★ Glob tool                  — 文件全局匹配 (Claude Code 原生工具)
  ★ Permission System          — 危险命令分级确认
  ★ Memory / CLAUDE.md         — 项目级记忆文件
  ★ Reminder Injection         — 工具调用后注入 TODO 状态提醒

  v5 全部 15 项保留; v4 全部保留

部署方式:
  替换 app/core/agents/agentic_loop.py (先备份旧版)
"""

import os
import re
import json
import asyncio
import logging
import uuid
import difflib
import time
import tempfile
from typing import Dict, Any, List, Optional, AsyncGenerator, Tuple
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# 常量
# =============================================================================

MAX_CONTEXT_TOKENS = 180_000        # Claude 200k 窗口, 留 20k 余量
SUMMARIZE_THRESHOLD = 165_000       # 92% of 180k — 对标 Claude Code wU2 压缩器
MAX_TOOL_OUTPUT_LEN = 15_000        # 单工具输出最大长度
MAX_DISPLAY_RESULT = 3_000          # 推送给前端的 result 最大长度
HEARTBEAT_INTERVAL = 15.0           # 心跳间隔 (秒)
API_MAX_RETRIES = 3                 # API 调用最大重试次数
API_BASE_DELAY = 1.0                # 重试基础延迟 (秒)
MAX_SUBAGENT_DEPTH = 2              # v6: SubAgent 最大递归深度
MAX_TODO_ITEMS = 50                 # v6: 最大 TODO 项数

# 模型价格 ($ per 1M tokens)
MODEL_PRICING = {
    "claude-opus-4-6":           {"input": 15.0,  "output": 75.0},
    "claude-opus-4-5-20251101":  {"input": 15.0,  "output": 75.0},
    "claude-sonnet-4-5-20250929":{"input": 3.0,   "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.0},
    "_default":                  {"input": 3.0,   "output": 15.0},
}

SKIP_DIRS = {
    '__pycache__', '.git', 'node_modules', '.venv', 'venv',
    '.cache', '.mypy_cache', '.pytest_cache', '.tox',
    'dist', 'build', '.egg-info', '.eggs', 'htmlcov',
    '.next', '.nuxt', 'coverage'
}

# v6: 危险命令模式 (对标 Claude Code Permission System)
RISKY_CMD_RE = [
    r'\brm\s+(-rf?|--recursive)', r'\bsudo\b', r'\bchmod\b.*777',
    r'\bgit\s+push\b', r'\bgit\s+reset\s+--hard',
    r'\breboot\b', r'\bshutdown\b',
    r'\bdrop\s+table\b', r'\btruncate\b',
]

# =============================================================================
# 工具定义
# =============================================================================

TOOL_DEFINITIONS = [
    {
        "name": "bash",
        "description": (
            "Execute a bash command in the project workspace. "
            "Always provide a 'description' field summarizing what this command does. "
            "Commands run with bash -c. Use && to chain. Avoid interactive commands."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute"},
                "description": {"type": "string", "description": "Short human-readable title"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120, max: 600)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": (
            "Read file contents with line numbers. Large files auto-truncated to head+tail. "
            "Use start_line/end_line to view specific sections."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
                "end_line": {"type": "integer", "description": "End line (inclusive)"},
                "description": {"type": "string", "description": "Why you're reading this file"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "batch_read",
        "description": "Read multiple files in one call. More efficient than multiple read_file calls. Max 10 files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "List of file paths"},
                "description": {"type": "string", "description": "Why you're reading these files"}
            },
            "required": ["paths"]
        }
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file. Parent dirs created automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Complete file content"},
                "description": {"type": "string", "description": "What file you're creating"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": (
            "Replace a unique string in a file. old_str must appear exactly once. "
            "Returns unified diff and stats (+N -M)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_str": {"type": "string", "description": "Exact string to replace (must be unique)"},
                "new_str": {"type": "string", "description": "Replacement string"},
                "description": {"type": "string", "description": "What you're changing"}
            },
            "required": ["path", "old_str", "new_str"]
        }
    },
    {
        "name": "multi_edit",
        "description": "Apply multiple edits to one file atomically. Each edit is {old_str, new_str}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"old_str": {"type": "string"}, "new_str": {"type": "string"}},
                        "required": ["old_str", "new_str"]
                    },
                    "description": "List of edits"
                },
                "description": {"type": "string", "description": "What you're changing"}
            },
            "required": ["path", "edits"]
        }
    },
    {
        "name": "list_dir",
        "description": "List files and directories with sizes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (default: project root)"},
                "depth": {"type": "integer", "description": "Max depth (default: 2, max: 5)"}
            },
            "required": []
        }
    },
    {
        "name": "grep_search",
        "description": "Search for regex pattern in files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex)"},
                "path": {"type": "string", "description": "Directory to search"},
                "include": {"type": "string", "description": "File glob, e.g. '*.py'"}
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "file_search",
        "description": "Search for files by name pattern (glob).",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern"},
                "path": {"type": "string", "description": "Root directory (default: project root)"},
                "max_results": {"type": "integer", "description": "Max results (default: 20)"}
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the web. Returns results with title, URL and snippet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (1-6 words)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "web_fetch",
        "description": "Fetch web page as cleaned text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to fetch"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "task_complete",
        "description": "Signal task completion with a structured summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Summary of what was accomplished"},
                "files_changed": {"type": "array", "items": {"type": "string"}, "description": "Files created/modified"}
            },
            "required": ["summary"]
        }
    },
    # === v5 新增工具 ===
    {
        "name": "view_truncated",
        "description": (
            "View the truncated (hidden) section of a file that was previously cut off. "
            "Use after read_file reports truncation. Provide start_line and end_line from the truncated range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "start_line": {"type": "integer", "description": "Start of truncated range"},
                "end_line": {"type": "integer", "description": "End of truncated range"},
                "description": {"type": "string", "description": "Why viewing this section"}
            },
            "required": ["path", "start_line", "end_line"]
        }
    },
    {
        "name": "batch_commands",
        "description": (
            "Run multiple bash commands in sequence. Each command has a description shown in UI. "
            "Stops on first failure unless continue_on_error is set. "
            "UI displays as 'Ran N commands' with expandable details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "Bash command"},
                            "description": {"type": "string", "description": "What this command does"}
                        },
                        "required": ["command"]
                    },
                    "description": "List of commands with descriptions"
                },
                "continue_on_error": {"type": "boolean", "description": "Continue after failures (default: false)"},
                "description": {"type": "string", "description": "Overall batch description"}
            },
            "required": ["commands"]
        }
    },
    {
        "name": "run_script",
        "description": (
            "Run a multi-line script. Creates temp file, executes, cleans up. "
            "UI shows 'Script' label that can be expanded to see full script content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "Script content (multi-line)"},
                "interpreter": {"type": "string", "description": "bash, python3, or node (default: bash)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 300)"},
                "description": {"type": "string", "description": "What this script does"}
            },
            "required": ["script"]
        }
    },
    {
        "name": "revert_edit",
        "description": (
            "Revert a previous edit by swapping old_str and new_str. "
            "Use when a change needs to be undone. Shows as 'Revert {description}' in UI."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_str": {"type": "string", "description": "Current string (was new_str in original edit)"},
                "new_str": {"type": "string", "description": "Revert to this (was old_str in original edit)"},
                "description": {"type": "string", "description": "What you're reverting"}
            },
            "required": ["path", "old_str", "new_str"]
        }
    },
    # === v6 新增工具 (对标 Claude Code) ===
    {
        "name": "glob",
        "description": "Find files matching glob pattern recursively. Fast. Examples: '**/*.py', 'src/**/*.ts'",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern"},
                "path": {"type": "string", "description": "Root directory"},
                "max_results": {"type": "integer", "description": "Max results (default: 50)"}
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "todo_write",
        "description": (
            "Create/update structured task list. Use VERY frequently for planning and tracking. "
            "Each todo: {content, status(pending/in_progress/completed), priority(high/medium/low)}. "
            "Replaces entire list. Mark completed IMMEDIATELY after finishing each item."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "content": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                            "priority": {"type": "string", "enum": ["high", "medium", "low"]}
                        },
                        "required": ["content", "status"]
                    }
                },
                "description": {"type": "string"}
            },
            "required": ["todos"]
        }
    },
    {
        "name": "todo_read",
        "description": "Read current todo list to check progress.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "task",
        "description": (
            "Launch sub-agent for complex tasks. Types: 'explore' (read-only codebase analysis), "
            "'plan' (detailed plan), 'general' (autonomous subtask). Returns summary when done."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subagent_type": {"type": "string", "enum": ["explore", "plan", "general"]},
                "prompt": {"type": "string", "description": "Task for the sub-agent"},
                "description": {"type": "string"},
                "max_turns": {"type": "integer", "description": "Max turns (default: 10)"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "memory_read",
        "description": "Read project memory file (.cheapbuy_memory.md / CLAUDE.md).",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "memory_write",
        "description": "Append/update project memory. Record architecture decisions, conventions, commands.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "section": {"type": "string", "description": "Section name"},
                "mode": {"type": "string", "enum": ["append", "replace_section"]}
            },
            "required": ["content"]
        }
    },
]


# =============================================================================
# System Prompt (v5)
# =============================================================================

AGENTIC_SYSTEM_PROMPT = """You are an expert software engineer working in a Linux environment.
You have tools to read/write/edit files, run bash commands, search code, browse the web,
plan tasks with todo_write, and delegate complex work to sub-agents via task.

## Core Workflow (Claude Code Style)
1. **Plan first**: Use todo_write to create a structured task list for any non-trivial task.
2. **Explore**: Use read_file, grep_search, glob to understand the codebase.
3. **Implement**: Use edit_file, write_file, multi_edit to make changes.
4. **Verify**: Run tests/builds with bash. Check results.
5. **Track progress**: Update todo_write as you complete each step.
6. **Record knowledge**: Use memory_write to save important project info.

## Tool Usage Guidelines

1. **description field**: ALWAYS include a 'description' field in every tool call.

2. **TodoWrite** (CRITICAL):
   - Create todos BEFORE starting multi-step tasks
   - Mark each todo in_progress when starting, completed when done
   - Do NOT batch — update immediately after completing each item

3. **Sub-agents** (via task tool):
   - 'explore' for codebase analysis (read-only, fast)
   - 'plan' for detailed implementation plans
   - 'general' for autonomous subtasks

4. **File operations**:
   - write_file for new files, edit_file for precise changes
   - multi_edit for multiple changes, batch_read for multiple files
   - glob for fast file pattern matching

5. **Debugging**: Read error -> Read file -> Fix -> Verify. Use batch_commands for diagnostics.

6. **Completion**: Call task_complete with a clear summary when done.

7. **Be concise**: Focus on actions. Use absolute file paths. No emojis."""


# =============================================================================
# Token 估算
# =============================================================================

def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1

def estimate_messages_tokens(messages: List[Dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        total += estimate_tokens(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        total += estimate_tokens(json.dumps(block.get("input", {})))
                    elif block.get("type") == "tool_result":
                        total += estimate_tokens(str(block.get("content", "")))
    return total

def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["_default"])
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


# =============================================================================
# v6: TODO Manager (对标 Claude Code TodoWrite/TodoRead)
# =============================================================================

class TodoManager:
    def __init__(self):
        self.todos: List[Dict[str, Any]] = []
        self._counter = 0

    def write(self, todos: List[Dict[str, Any]]) -> Dict[str, Any]:
        new_todos = []
        for t in todos[:MAX_TODO_ITEMS]:
            self._counter += 1
            new_todos.append({
                "id": t.get("id", f"todo_{self._counter}"),
                "content": t.get("content", ""),
                "status": t.get("status", "pending"),
                "priority": t.get("priority", "medium"),
            })
        self.todos = new_todos
        return self._summary()

    def read(self) -> Dict[str, Any]:
        return self._summary()

    def _summary(self) -> Dict[str, Any]:
        c = sum(1 for t in self.todos if t["status"] == "completed")
        ip = sum(1 for t in self.todos if t["status"] == "in_progress")
        p = sum(1 for t in self.todos if t["status"] == "pending")
        return {"total": len(self.todos), "completed": c, "in_progress": ip, "pending": p,
                "todos": self.todos,
                "progress_display": f"{c}/{len(self.todos)} completed" if self.todos else "No tasks"}

    def render_reminder(self) -> str:
        if not self.todos: return ""
        lines = ["[TODO Status]"]
        for t in self.todos:
            icon = {"completed": "done", "in_progress": ">>", "pending": ".."}[t["status"]]
            lines.append(f"  [{icon}] {t['content']}")
        c = sum(1 for t in self.todos if t["status"] == "completed")
        lines.append(f"Progress: {c}/{len(self.todos)}")
        return "\n".join(lines)


# v6: Permission Checker
class PermissionChecker:
    @staticmethod
    def classify_risk(command: str) -> str:
        for pat in RISKY_CMD_RE:
            if re.search(pat, command, re.IGNORECASE):
                return "risky"
        return "safe"


# =============================================================================
# 工具执行器 (v4 + v5 + v6)
# =============================================================================

class ToolExecutor:
    MAX_DISPLAY_LINES = 200
    MAX_HEAD_LINES = 100
    MAX_TAIL_LINES = 100

    def __init__(self, work_dir: str):
        self.work_dir = os.path.abspath(work_dir)
        os.makedirs(self.work_dir, exist_ok=True)
        self.file_changes: List[Dict[str, Any]] = []
        self.todo_manager = TodoManager()          # v6
        self.permission_checker = PermissionChecker()  # v6
        self.memory_file = os.path.join(self.work_dir, ".cheapbuy_memory.md")  # v6

    async def execute(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        handlers = {
            "bash": self._bash, "read_file": self._read_file,
            "batch_read": self._batch_read, "write_file": self._write_file,
            "edit_file": self._edit_file, "multi_edit": self._multi_edit,
            "list_dir": self._list_dir, "grep_search": self._grep_search,
            "file_search": self._file_search, "web_search": self._web_search,
            "web_fetch": self._web_fetch, "task_complete": self._task_complete,
            # v5 新增
            "view_truncated": self._view_truncated,
            "batch_commands": self._batch_commands,
            "run_script": self._run_script,
            "revert_edit": self._revert_edit,
            # v6 新增
            "glob": self._glob,
            "todo_write": self._todo_write,
            "todo_read": self._todo_read,
            "task": self._task_stub,
            "memory_read": self._memory_read,
            "memory_write": self._memory_write,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            return await handler(tool_input)
        except Exception as e:
            logger.error(f"Tool {tool_name} error: {e}", exc_info=True)
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})

    async def execute_parallel(self, tool_calls: List[Tuple[str, Dict, str]]) -> List[Tuple[str, str, str]]:
        """并行执行多个工具, 返回 [(tool_id, result_str, tool_name), ...]"""
        async def _run_one(name, inp, tid):
            result = await self.execute(name, inp)
            return (tid, result, name)
        tasks = [_run_one(n, i, t) for n, i, t in tool_calls]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def _bash(self, params: Dict) -> str:
        command = params["command"]
        timeout = min(params.get("timeout", 120), 600)
        risk = self.permission_checker.classify_risk(command)  # v6
        try:
            proc = await asyncio.create_subprocess_shell(
                command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir, env={**os.environ, "HOME": self.work_dir, "PWD": self.work_dir}
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode('utf-8', errors='replace')
            err = stderr.decode('utf-8', errors='replace')
            if len(out) > 10000:
                out = out[:5000] + f"\n...[{len(out)-10000} chars truncated]...\n" + out[-5000:]
            if len(err) > 5000:
                err = err[:5000] + "\n...[truncated]"
            return json.dumps({"exit_code": proc.returncode, "stdout": out, "stderr": err, "risk_level": risk})
        except asyncio.TimeoutError:
            return json.dumps({"error": f"Command timed out after {timeout}s", "exit_code": -1})

    async def _read_file(self, params: Dict) -> str:
        path = self._resolve(params["path"])
        if not os.path.exists(path):
            return json.dumps({"error": f"File not found: {path}"})
        if not os.path.isfile(path):
            return json.dumps({"error": f"Not a file: {path}"})
        try:
            sz = os.path.getsize(path)
            if sz > 500_000:
                return json.dumps({"error": f"File too large ({sz} bytes). Use start_line/end_line.", "file_size": sz})
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            total = len(lines)
            fname = os.path.basename(path)
            has_range = "start_line" in params or "end_line" in params
            if not has_range and total > self.MAX_DISPLAY_LINES:
                head = "".join(f"{i:4d} | {lines[i-1]}" for i in range(1, self.MAX_HEAD_LINES + 1))
                tail = "".join(f"{i:4d} | {lines[i-1]}" for i in range(total - self.MAX_TAIL_LINES + 1, total + 1))
                omit = total - self.MAX_HEAD_LINES - self.MAX_TAIL_LINES
                ts, te = self.MAX_HEAD_LINES + 1, total - self.MAX_TAIL_LINES
                content = head + f"\n... [{omit} lines truncated — use start_line/end_line to view {ts}-{te}] ...\n\n" + tail
                return json.dumps({
                    "path": path, "filename": fname, "total_lines": total,
                    "lines": f"1-{self.MAX_HEAD_LINES}+{total-self.MAX_TAIL_LINES+1}-{total}/{total}",
                    "content": content, "truncated": True,
                    "truncated_start": ts, "truncated_end": te,
                    "truncated_range": f"{ts}-{te}",
                    "hint": f"View truncated section of {fname}"
                })
            start = max(1, params.get("start_line", 1))
            end = min(total, params.get("end_line", total))
            content = "".join(f"{i:4d} | {lines[i-1]}" for i in range(start, end + 1))
            return json.dumps({
                "path": path, "filename": fname, "total_lines": total,
                "lines": f"{start}-{end}/{total}", "content": content, "truncated": False
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to read: {str(e)}"})

    async def _batch_read(self, params: Dict) -> str:
        paths = params.get("paths", [])
        if not paths: return json.dumps({"error": "No paths"})
        if len(paths) > 10: return json.dumps({"error": "Max 10 files per batch_read"})
        results, errors = {}, {}
        for p in paths:
            r = await self._read_file({"path": p})
            try:
                d = json.loads(r)
                if "error" in d: errors[p] = d["error"]
                else:
                    entry = {"filename": d.get("filename",""), "lines": d.get("lines",""),
                        "total_lines": d.get("total_lines",0), "truncated": d.get("truncated",False),
                        "content": d.get("content","")}
                    if d.get("truncated"):
                        entry["truncated_range"] = d.get("truncated_range","")
                        entry["hint"] = d.get("hint","")
                    results[p] = entry
            except: errors[p] = "parse error"
        return json.dumps({"files_read": len(results), "files_errored": len(errors),
            "results": results, "errors": errors or None}, ensure_ascii=False)

    async def _write_file(self, params: Dict) -> str:
        path = self._resolve(params["path"])
        content = params["content"]
        try:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            is_new = not os.path.exists(path)
            with open(path, 'w', encoding='utf-8') as f: f.write(content)
            lc = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
            fn = os.path.basename(path)
            act = "created" if is_new else "overwritten"
            self.file_changes.append({"action": act, "path": path, "filename": fn, "lines": lc})
            return json.dumps({"success": True, "path": path, "filename": fn, "size": len(content), "lines": lc, "action": act})
        except Exception as e:
            return json.dumps({"error": f"Write failed: {str(e)}"})

    async def _edit_file(self, params: Dict) -> str:
        path = self._resolve(params["path"])
        old_s, new_s = params["old_str"], params["new_str"]
        if not os.path.exists(path):
            return json.dumps({"error": f"File not found: {path}"})
        try:
            with open(path, 'r', encoding='utf-8') as f: content = f.read()
            cnt = content.count(old_s)
            if cnt == 0:
                sim = self._find_similar(content, old_s)
                return json.dumps({"error": "old_str not found", "path": path,
                    "file_lines": content.count('\n')+1, "hint": f"Similar: {sim[:200]}" if sim else "None"})
            if cnt > 1:
                return json.dumps({"error": f"old_str found {cnt} times, must be unique"})
            new_content = content.replace(old_s, new_s, 1)
            with open(path, 'w', encoding='utf-8') as f: f.write(new_content)
            added, removed = self._diff_stats(old_s, new_s)
            fn = os.path.basename(path)
            udiff = self._unified_diff(content, new_content, fn)
            self.file_changes.append({"action": "edited", "path": path, "filename": fn, "added": added, "removed": removed})
            return json.dumps({"success": True, "path": path, "filename": fn,
                "diff": f"{fn} +{added} -{removed}", "unified_diff": udiff[:2000],
                "added_lines": added, "removed_lines": removed,
                "description": params.get("description", f"Edit {fn}")})
        except Exception as e:
            return json.dumps({"error": f"Edit failed: {str(e)}"})

    async def _multi_edit(self, params: Dict) -> str:
        path = self._resolve(params["path"])
        edits = params.get("edits", [])
        if not edits: return json.dumps({"error": "No edits"})
        if not os.path.exists(path): return json.dumps({"error": f"File not found: {path}"})
        try:
            with open(path, 'r', encoding='utf-8') as f: original = f.read()
            content = original
            ta, tr, applied, errs = 0, 0, 0, []
            for i, e in enumerate(edits):
                os_s, ns_s = e["old_str"], e["new_str"]
                c = content.count(os_s)
                if c == 0: errs.append(f"Edit {i+1}: not found"); continue
                if c > 1: errs.append(f"Edit {i+1}: found {c} times"); continue
                content = content.replace(os_s, ns_s, 1)
                applied += 1; a, r = self._diff_stats(os_s, ns_s); ta += a; tr += r
            if applied == 0: return json.dumps({"error": "No edits applied", "errors": errs})
            with open(path, 'w', encoding='utf-8') as f: f.write(content)
            fn = os.path.basename(path)
            udiff = self._unified_diff(original, content, fn)
            self.file_changes.append({"action": "multi_edited", "path": path, "filename": fn,
                "edits_applied": applied, "added": ta, "removed": tr})
            res = {"success": True, "path": path, "filename": fn,
                "edits_applied": applied, "edits_total": len(edits),
                "diff": f"{fn} +{ta} -{tr}", "unified_diff": udiff[:2000],
                "added_lines": ta, "removed_lines": tr}
            if errs: res["errors"] = errs
            return json.dumps(res)
        except Exception as e:
            return json.dumps({"error": f"Multi-edit failed: {str(e)}"})

    async def _list_dir(self, params: Dict) -> str:
        path = self._resolve(params.get("path", "."))
        depth = min(params.get("depth", 2), 5)
        if not os.path.isdir(path): return json.dumps({"error": f"Not a directory: {path}"})
        lines = []; self._walk(path, lines, 0, depth)
        return f"📁 {path}\n" + "\n".join(lines) if lines else f"📁 {path}\n  (empty)"

    def _walk(self, p, lines, d, mx):
        if d >= mx: return
        try: items = sorted(os.listdir(p))
        except: return
        ind = "  " * (d + 1)
        for item in items:
            if item in SKIP_DIRS or item.startswith('.'): continue
            fp = os.path.join(p, item)
            if os.path.isdir(fp):
                try: c = len([f for f in os.listdir(fp) if not f.startswith('.')])
                except: c = '?'
                lines.append(f"{ind}📁 {item}/ ({c} items)")
                self._walk(fp, lines, d + 1, mx)
            else:
                lines.append(f"{ind}📄 {item} ({self._hsz(os.path.getsize(fp))})")

    async def _grep_search(self, params: Dict) -> str:
        pattern = params["pattern"]
        path = self._resolve(params.get("path", "."))
        cmd = ["grep", "-rn", "--max-count=50", "--color=never"]
        if params.get("include"): cmd += ["--include", params["include"]]
        for s in SKIP_DIRS: cmd += [f"--exclude-dir={s}"]
        cmd += [pattern, path]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            r = out.decode('utf-8', errors='replace')
            if not r: return json.dumps({"pattern": pattern, "matches": 0, "content": "(no matches)"})
            mc = len(r.strip().split('\n'))
            if len(r) > 8000: r = r[:8000] + f"\n...[truncated, {mc} matches]"
            return json.dumps({"pattern": pattern, "matches": mc, "content": r})
        except asyncio.TimeoutError: return json.dumps({"error": "Search timed out"})
        except Exception as e: return json.dumps({"error": str(e)})

    async def _file_search(self, params: Dict) -> str:
        pattern = params["pattern"]
        root = self._resolve(params.get("path", "."))
        mx = min(params.get("max_results", 20), 100)
        if not os.path.exists(root): return json.dumps({"error": f"Dir not found: {root}"})
        try:
            cmd = ["find", root, "-type", "f", "-name", pattern, "-maxdepth", "10"]
            for s in SKIP_DIRS: cmd += ["-not", "-path", f"*/{s}/*"]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            matches = []
            for fp in out.decode('utf-8', errors='replace').strip().split('\n'):
                fp = fp.strip()
                if not fp or not os.path.exists(fp): continue
                try:
                    sz = os.path.getsize(fp)
                    matches.append({"path": os.path.relpath(fp, self.work_dir), "abs_path": fp,
                        "size": sz, "size_human": self._hsz(sz)})
                except: pass
                if len(matches) >= mx: break
            return json.dumps({"pattern": pattern, "matches": len(matches), "results": matches}, ensure_ascii=False)
        except asyncio.TimeoutError: return json.dumps({"error": "Search timed out"})
        except Exception as e: return json.dumps({"error": str(e)})

    async def _web_search(self, params: Dict) -> str:
        query = params["query"]
        try:
            from app.core.web_search import SerperSearchEngine
            engine = SerperSearchEngine()
            results = await engine.search(query, max_results=10)
            if not results: return json.dumps({"query": query, "results_count": 0, "results": []})
            if isinstance(results[0], dict) and "error" in results[0]:
                return json.dumps({"query": query, "error": results[0]["error"]})
            structured = [{"title": r.get("title",""), "url": r.get("link", r.get("url","")),
                "snippet": r.get("snippet", r.get("description","")), "domain": r.get("domain","")} for r in results]
            return json.dumps({"query": query, "results_count": len(structured), "results": structured}, ensure_ascii=False)
        except ImportError: return json.dumps({"query": query, "error": "Web search not available."})
        except Exception as e: return json.dumps({"query": query, "error": str(e)})

    async def _web_fetch(self, params: Dict) -> str:
        url = params["url"]
        try:
            from app.core.web_search import WebBrowser
            browser = WebBrowser(max_content_length=15000)
            content = await browser.browse(url, clean=True)
            title = self._extract_title(content, url)
            return json.dumps({"url": url, "title": title, "content_length": len(content), "content": content}, ensure_ascii=False)
        except ImportError:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                    resp = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    text = resp.text
                    tm = re.search(r'<title[^>]*>(.*?)</title>', text, re.I|re.DOTALL)
                    title = tm.group(1).strip() if tm else url
                    for pat in [r'<script[^>]*>.*?</script>', r'<style[^>]*>.*?</style>', r'<[^>]+>']:
                        text = re.sub(pat, ' ', text, flags=re.DOTALL)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if len(text) > 15000: text = text[:15000] + "\n...[truncated]"
                    return json.dumps({"url": url, "title": title, "status": resp.status_code,
                        "content_length": len(text), "content": text}, ensure_ascii=False)
            except Exception as e2: return json.dumps({"url": url, "error": str(e2)})
        except Exception as e: return json.dumps({"url": url, "error": str(e)})

    async def _task_complete(self, params: Dict) -> str:
        return json.dumps({"completed": True, "summary": params.get("summary","Done"),
            "files_changed": params.get("files_changed",[]),
            "total_file_changes": len(self.file_changes),
            "file_change_log": self.file_changes[-20:]}, ensure_ascii=False)

    # === v5 新增工具实现 ===

    async def _view_truncated(self, params: Dict) -> str:
        """Feature #2: View truncated section of a file"""
        path = self._resolve(params["path"])
        start = params.get("start_line", 1)
        end = params.get("end_line")
        # 复用 _read_file 的 start_line/end_line 逻辑
        return await self._read_file({"path": params["path"], "start_line": start, "end_line": end,
            "description": params.get("description", f"View truncated section of {os.path.basename(path)}")})

    async def _batch_commands(self, params: Dict) -> str:
        """Feature #6-7: Run multiple commands — 'Ran N commands'"""
        commands = params.get("commands", [])
        if not commands:
            return json.dumps({"error": "No commands provided"})
        continue_on_error = params.get("continue_on_error", False)
        results = []
        succeeded, failed = 0, 0
        for i, cmd_info in enumerate(commands):
            command = cmd_info.get("command", "")
            desc = cmd_info.get("description", f"Command {i+1}")
            r_str = await self._bash({"command": command, "timeout": cmd_info.get("timeout", 120)})
            try:
                r = json.loads(r_str)
            except:
                r = {"exit_code": -1, "stdout": "", "stderr": r_str}
            ok = r.get("exit_code", -1) == 0
            if ok:
                succeeded += 1
            else:
                failed += 1
            results.append({
                "index": i + 1,
                "command": command[:200],
                "description": desc,
                "exit_code": r.get("exit_code", -1),
                "success": ok,
                "stdout_preview": r.get("stdout", "")[:500],
                "stderr_preview": r.get("stderr", "")[:300],
            })
            if not ok and not continue_on_error:
                break
        n = len(results)
        return json.dumps({
            "total_commands": len(commands),
            "executed": n,
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
            "display_title": f"Ran {n} command{'s' if n != 1 else ''}",
        }, ensure_ascii=False)

    async def _run_script(self, params: Dict) -> str:
        """Feature #6/10: Run multi-line script with expandable 'Script' display"""
        script = params.get("script", "")
        interpreter = params.get("interpreter", "bash")
        timeout = min(params.get("timeout", 300), 600)
        desc = params.get("description", "Script")
        if not script:
            return json.dumps({"error": "Empty script"})
        import tempfile
        ext_map = {"bash": ".sh", "python3": ".py", "python": ".py", "node": ".js"}
        ext = ext_map.get(interpreter, ".sh")
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix=ext, delete=False,
                                              dir=self.work_dir, prefix="script_") as f:
                if interpreter in ("bash", "sh"):
                    f.write("#!/bin/bash\nset -e\n" + script)
                else:
                    f.write(script)
                script_path = f.name
            os.chmod(script_path, 0o755)
            r_str = await self._bash({"command": f"{interpreter} {script_path}", "timeout": timeout})
            try:
                r = json.loads(r_str)
            except:
                r = {"exit_code": -1, "stdout": "", "stderr": r_str}
            r["script"] = script
            r["interpreter"] = interpreter
            r["description"] = desc
            r["display_title"] = desc
            r["script_path"] = script_path
            return json.dumps(r, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e), "script": script[:500]})
        finally:
            try:
                os.unlink(script_path)
            except:
                pass

    async def _revert_edit(self, params: Dict) -> str:
        """Feature #14: Revert a previous edit"""
        desc = params.get("description", "Revert edit")
        # revert_edit is just edit_file with a "Revert" prefix in description
        result_str = await self._edit_file({
            "path": params["path"],
            "old_str": params["old_str"],
            "new_str": params["new_str"],
            "description": f"Revert: {desc}"
        })
        try:
            r = json.loads(result_str)
            r["reverted"] = True
            r["display_title"] = f"Revert: {desc}"
            return json.dumps(r, ensure_ascii=False)
        except:
            return result_str

    # === v6 新增工具实现 ===

    async def _glob(self, params: Dict) -> str:
        """v6: Claude Code 原生 Glob 工具"""
        pattern = params["pattern"]
        root = self._resolve(params.get("path", "."))
        max_results = min(params.get("max_results", 50), 200)
        if not os.path.exists(root):
            return json.dumps({"error": f"Root not found: {root}"})
        matches = []
        try:
            for fp in Path(root).glob(pattern):
                if any(skip in fp.parts for skip in SKIP_DIRS): continue
                if fp.is_file():
                    try:
                        sz = fp.stat().st_size
                        matches.append({"path": str(fp), "relative": str(fp.relative_to(root)), "size": sz, "size_human": self._hsz(sz)})
                    except: pass
                if len(matches) >= max_results: break
        except Exception as e:
            return json.dumps({"error": f"Glob failed: {str(e)}"})
        return json.dumps({"pattern": pattern, "root": root, "matches": len(matches), "results": matches}, ensure_ascii=False)

    async def _todo_write(self, params: Dict) -> str:
        """v6: 对标 Claude Code TodoWrite"""
        todos = params.get("todos", [])
        if not todos: return json.dumps({"error": "No todos provided"})
        result = self.todo_manager.write(todos)
        result["display_title"] = f"Updated todo list ({result['total']} items)"
        return json.dumps(result, ensure_ascii=False)

    async def _todo_read(self, params: Dict) -> str:
        """v6: 对标 Claude Code TodoRead"""
        return json.dumps(self.todo_manager.read(), ensure_ascii=False)

    async def _task_stub(self, params: Dict) -> str:
        """v6: Stub — real SubAgent execution handled at AgenticLoop level"""
        return json.dumps({"error": "Task tool must be handled by AgenticLoop"})

    async def _memory_read(self, params: Dict) -> str:
        """v6: 读取项目记忆文件"""
        candidates = [self.memory_file, os.path.join(self.work_dir, "CLAUDE.md"),
                      os.path.join(self.work_dir, ".claude", "CLAUDE.md")]
        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f: content = f.read()
                    return json.dumps({"path": path, "content": content, "size": len(content)}, ensure_ascii=False)
                except Exception as e:
                    return json.dumps({"error": str(e)})
        return json.dumps({"content": "", "message": "No memory file found. Use memory_write to create one."})

    async def _memory_write(self, params: Dict) -> str:
        """v6: 写入项目记忆文件"""
        content = params.get("content", "")
        section = params.get("section")
        mode = params.get("mode", "append")
        try:
            existing = ""
            if os.path.exists(self.memory_file):
                with open(self.memory_file, 'r', encoding='utf-8') as f: existing = f.read()
            if mode == "replace_section" and section:
                header = f"## {section}"
                if header in existing:
                    existing = re.sub(rf"(## {re.escape(section)}\n)(.*?)(?=\n## |\Z)",
                                      f"## {section}\n{content}\n", existing, flags=re.DOTALL)
                else:
                    existing += f"\n\n## {section}\n{content}\n"
            else:
                existing += f"\n\n## {section}\n{content}\n" if section else f"\n{content}\n"
            if not existing.startswith("# "):
                existing = "# Project Memory\n\n" + existing
            with open(self.memory_file, 'w', encoding='utf-8') as f: f.write(existing)
            return json.dumps({"success": True, "path": self.memory_file, "size": len(existing), "mode": mode})
        except Exception as e:
            return json.dumps({"error": f"Memory write failed: {str(e)}"})

    def _resolve(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(self.work_dir, path)

    @staticmethod
    def _hsz(sz):
        if sz > 1048576: return f"{sz/1048576:.1f}MB"
        if sz > 1024: return f"{sz/1024:.1f}KB"
        return f"{sz}B"

    @staticmethod
    def _extract_title(content, fallback):
        lines = content.strip().split('\n')
        if lines:
            f = lines[0].strip()
            if len(f) < 200 and f and not f.startswith(('http','<','{','[')):
                t = re.sub(r'^#+\s*', '', f).strip()
                if t: return t
        return fallback

    @staticmethod
    def _find_similar(content, target, window=200):
        if len(target) < 10: return ""
        idx = content.find(target[:15])
        if idx >= 0: return content[max(0, idx-20):idx+window]
        return ""

    @staticmethod
    def _diff_stats(old_s, new_s):
        added = removed = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_s.split('\n'), new_s.split('\n')).get_opcodes():
            if tag == 'insert': added += j2-j1
            elif tag == 'delete': removed += i2-i1
            elif tag == 'replace': added += j2-j1; removed += i2-i1
        if added == 0 and removed == 0 and old_s != new_s: added = removed = 1
        return added, removed

    @staticmethod
    def _unified_diff(old_content: str, new_content: str, filename: str) -> str:
        """v4: 生成 unified diff"""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        return "".join(difflib.unified_diff(old_lines, new_lines,
            fromfile=f"a/{filename}", tofile=f"b/{filename}", n=3))


# =============================================================================
# Turn 汇总 + 自动标题
# =============================================================================

def build_turn_summary(tool_uses: List[Dict]) -> Dict[str, Any]:
    counts = {"bash": 0, "read_file": 0, "batch_read": 0, "write_file": 0,
              "edit_file": 0, "multi_edit": 0, "list_dir": 0, "grep_search": 0,
              "file_search": 0, "glob": 0, "web_search": 0, "web_fetch": 0, "task_complete": 0,
              "view_truncated": 0, "batch_commands": 0, "run_script": 0, "revert_edit": 0,
              "todo_write": 0, "todo_read": 0, "task": 0, "memory_read": 0, "memory_write": 0}
    detail_items = []
    icon_map = {"bash": "terminal", "read_file": "file-text", "batch_read": "files",
        "write_file": "file-plus", "edit_file": "pencil", "multi_edit": "pencil-ruler",
        "list_dir": "folder-open", "grep_search": "search", "file_search": "file-search",
        "glob": "file-search", "web_search": "globe", "web_fetch": "download",
        "task_complete": "check-circle", "view_truncated": "eye",
        "batch_commands": "terminal", "run_script": "code", "revert_edit": "rotate-ccw",
        "todo_write": "list-todo", "todo_read": "list-checks",
        "task": "git-branch", "memory_read": "brain", "memory_write": "brain"}
    for tu in tool_uses:
        name = tu.get("name", ""); inp = tu.get("input", {})
        if name in counts: counts[name] += 1
        desc = inp.get("description", "")
        detail_items.append({"tool": name, "icon": icon_map.get(name, "zap"),
            "title": desc if desc else _auto_title(name, inp)})

    vc = counts["read_file"] + counts["batch_read"] + counts["view_truncated"]
    ec = counts["edit_file"] + counts["multi_edit"] + counts["revert_edit"]
    sc = counts["list_dir"] + counts["grep_search"] + counts["file_search"] + counts["glob"]
    cc = counts["bash"] + counts["batch_commands"] + counts["run_script"]
    tc = counts["todo_write"] + counts["todo_read"]
    parts = []
    if cc: n = cc; parts.append(f"Ran {n} command{'s' if n>1 else ''}")
    if vc: n = vc; parts.append(f"viewed {n} file{'s' if n>1 else ''}")
    if counts["write_file"]: n = counts["write_file"]; parts.append(f"created {n} file{'s' if n>1 else ''}")
    if ec: n = ec; parts.append(f"edited {'a file' if n==1 else f'{n} files'}")
    if sc: n = sc; parts.append(f"searched {n} path{'s' if n>1 else ''}")
    if counts["web_search"]: parts.append("searched the web")
    if counts["web_fetch"]: n = counts["web_fetch"]; parts.append(f"fetched {n} page{'s' if n>1 else ''}")
    if counts["revert_edit"]: n = counts["revert_edit"]; parts.append(f"reverted {n} edit{'s' if n>1 else ''}")
    if tc: parts.append("updated tasks")
    if counts["task"]: n = counts["task"]; parts.append(f"launched {n} sub-agent{'s' if n>1 else ''}")
    if counts["memory_write"]: parts.append("updated memory")
    if counts["task_complete"]: parts.append("completed task")
    display = ", ".join(parts) if parts else "Done"
    if display: display = display[0].upper() + display[1:]
    return {"commands_run": cc, "files_viewed": vc, "files_edited": ec,
        "files_created": counts["write_file"], "searches_code": sc,
        "searches_web": counts["web_search"], "pages_fetched": counts["web_fetch"],
        "reverts": counts["revert_edit"], "todos_updated": tc,
        "subagents_launched": counts["task"],
        "task_completed": counts["task_complete"] > 0, "display": display,
        "detail_items": detail_items, "tool_count": len(tool_uses)}


def _auto_title(name, inp):
    if name == "bash":
        cmd = inp.get("command",""); return f"$ {cmd[:80]}{'...' if len(cmd)>80 else ''}"
    elif name == "read_file": return f"Read {inp.get('path','file')}"
    elif name == "batch_read": return f"Read {len(inp.get('paths',[]))} files"
    elif name == "write_file": return f"Create {inp.get('path','file')}"
    elif name == "edit_file": return f"Edit {inp.get('path','file')}"
    elif name == "multi_edit": return f"Apply {len(inp.get('edits',[]))} edits to {inp.get('path','file')}"
    elif name == "list_dir": return f"List {inp.get('path','.')}"
    elif name == "grep_search": return f"Search: {inp.get('pattern','')}"
    elif name == "file_search": return f"Find: {inp.get('pattern','')}"
    elif name == "web_search": return f"Search: {inp.get('query','')}"
    elif name == "web_fetch":
        u = inp.get("url",""); return f"Fetch: {u[:60]}{'...' if len(u)>60 else ''}"
    elif name == "task_complete": return "Task completed"
    # v5 新增
    elif name == "view_truncated":
        fn = os.path.basename(inp.get("path",""))
        return f"View truncated section of {fn}"
    elif name == "batch_commands":
        n = len(inp.get("commands",[])); return f"Run {n} command{'s' if n>1 else ''}"
    elif name == "run_script":
        return inp.get("description", "Script")
    elif name == "revert_edit":
        return f"Revert: {inp.get('description', 'edit')}"
    elif name == "glob":
        return f"Glob: {inp.get('pattern','')}"
    elif name == "todo_write":
        return f"Plan: {len(inp.get('todos',[]))} tasks"
    elif name == "todo_read":
        return "Check task progress"
    elif name == "task":
        return f"SubAgent ({inp.get('subagent_type','general')}): {inp.get('description',inp.get('prompt','')[:60])}"
    elif name == "memory_read":
        return "Read project memory"
    elif name == "memory_write":
        return f"Update memory: {inp.get('section', 'notes')}"
    return name


# =============================================================================
# v6: SubAgent (对标 Claude Code Task Tool)
# =============================================================================

SUBAGENT_PROMPTS = {
    "explore": "You are an Explore sub-agent. READ-ONLY access. Search and analyze the codebase, then provide a clear summary. Use absolute paths.",
    "plan": "You are a Plan sub-agent. READ-ONLY access. Create a detailed step-by-step implementation plan with specific files and functions.",
    "general": "You are a general-purpose sub-agent. Complete your assigned task, then call task_complete with a summary. Use absolute paths.",
}
SUBAGENT_TOOLS = {
    "explore": ["read_file","batch_read","glob","grep_search","file_search","list_dir","task_complete"],
    "plan": ["read_file","batch_read","glob","grep_search","file_search","list_dir","todo_write","task_complete"],
    "general": None,
}

async def run_subagent(ai_engine, work_dir, prompt, subagent_type="general",
                       model=None, max_turns=10, depth=0):
    if depth >= MAX_SUBAGENT_DEPTH:
        return {"success": False, "error": "Max subagent depth", "summary": "Cannot spawn more sub-agents"}
    sys_prompt = SUBAGENT_PROMPTS.get(subagent_type, SUBAGENT_PROMPTS["general"])
    allowed = SUBAGENT_TOOLS.get(subagent_type)
    tools = [t for t in TOOL_DEFINITIONS if t["name"] in allowed] if allowed else [t for t in TOOL_DEFINITIONS if t["name"] != "task"]
    executor = ToolExecutor(work_dir)
    messages = [{"role": "user", "content": prompt}]
    all_text = []
    for turn in range(1, max_turns + 1):
        try:
            result = await ai_engine.get_completion(messages=messages, model=model or "claude-sonnet-4-5-20250929",
                system_prompt=sys_prompt, tools=tools, temperature=0.2, max_tokens=8192)
        except Exception as e:
            return {"success": False, "error": str(e), "summary": f"SubAgent failed: {e}"}
        content_blocks = result.get("content_blocks", [])
        tool_uses = result.get("tool_uses", [])
        if not content_blocks and result.get("content"):
            content_blocks = [{"type": "text", "text": result["content"]}]
        for b in content_blocks:
            if b.get("type") == "text" and b.get("text"): all_text.append(b["text"])
        messages.append({"role": "assistant", "content": content_blocks})
        if not tool_uses: break
        tool_results = []
        for tu in tool_uses:
            tn, ti, tid = tu["name"], tu["input"], tu["id"]
            if tn == "task_complete":
                return {"success": True, "summary": ti.get("summary", "\n".join(all_text)),
                        "turns": turn, "files_changed": executor.file_changes}
            rs = await executor.execute(tn, ti)
            if len(rs) > MAX_TOOL_OUTPUT_LEN: rs = rs[:MAX_TOOL_OUTPUT_LEN] + "\n...[truncated]"
            tool_results.append({"type": "tool_result", "tool_use_id": tid, "content": rs})
        messages.append({"role": "user", "content": tool_results})
    return {"success": True, "summary": "\n".join(all_text) or "SubAgent completed.",
            "turns": max_turns, "files_changed": executor.file_changes}


# =============================================================================
# Agentic Loop v6 — 核心
# =============================================================================

class AgenticLoop:
    """
    Agentic Loop v6 — Claude Code 全功能对标

    事件: start, text, thinking, tool_start, tool_result, file_change,
          turn, progress, usage, todo_update, subagent_start, subagent_result, done, error
    """
    DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

    def __init__(self, ai_engine, work_dir: str, model: str = None,
                 max_turns: int = 30, system_prompt: str = None,
                 enable_parallel: bool = True):
        self.ai_engine = ai_engine
        self.work_dir = os.path.abspath(work_dir)
        self.model = model or self.DEFAULT_MODEL
        self.max_turns = max_turns
        self.system_prompt = system_prompt or AGENTIC_SYSTEM_PROMPT
        self.executor = ToolExecutor(self.work_dir)
        self.enable_parallel = enable_parallel
        self.subagent_depth = 0  # v6
        self.turn_count = 0
        self.total_tool_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self._cancelled = False  # v6: 中断支持
        os.makedirs(self.work_dir, exist_ok=True)

    def cancel(self):
        """v6: 中断执行"""
        self._cancelled = True

    async def run(self, task: str) -> AsyncGenerator[Dict[str, Any], None]:
        start_time = datetime.now()
        messages = [{"role": "user", "content": task}]

        # v6: 加载项目记忆
        memory = await self._load_memory()
        if memory:
            messages[0]["content"] = f"[PROJECT MEMORY]\n{memory}\n\n[TASK]\n{task}"

        yield {"type": "start", "task": task[:500], "model": self.model,
            "work_dir": self.work_dir, "max_turns": self.max_turns,
            "timestamp": datetime.now().isoformat(), "version": "v6"}

        for turn in range(1, self.max_turns + 1):
            if self._cancelled:
                yield {"type": "error", "message": "Task cancelled by user", "turn": turn}
                return

            self.turn_count = turn
            logger.info(f"[AgenticLoop v6] Turn {turn}/{self.max_turns}")

            yield {"type": "progress", "turn": turn, "max_turns": self.max_turns,
                "total_tool_calls": self.total_tool_calls,
                "elapsed": (datetime.now() - start_time).total_seconds()}

            # ---- 上下文窗口管理 (v6: Context Compaction) ----
            est_tokens = estimate_messages_tokens(messages)
            if est_tokens > SUMMARIZE_THRESHOLD:
                logger.info(f"[v6] Context at {est_tokens} tokens, compacting...")
                messages = await self._summarize_context(messages)

            # ---- v6: Reminder Injection (TODO 状态) ----
            todo_reminder = self.executor.todo_manager.render_reminder()
            effective_system = self.system_prompt
            if todo_reminder:
                effective_system += f"\n\n{todo_reminder}"

            # ---- AI 调用 (带重试) ----
            result = None; last_error = None
            for attempt in range(1, API_MAX_RETRIES + 1):
                try:
                    result = await self.ai_engine.get_completion(
                        messages=messages, model=self.model,
                        system_prompt=effective_system,
                        tools=TOOL_DEFINITIONS, temperature=0.3, max_tokens=16384)
                    break
                except Exception as e:
                    last_error = e
                    delay = API_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(f"[v6] AI call failed (attempt {attempt}): {e}, retry in {delay}s")
                    if attempt < API_MAX_RETRIES:
                        await asyncio.sleep(delay)

            if result is None:
                yield {"type": "error", "message": f"AI call failed after {API_MAX_RETRIES} retries: {last_error}", "turn": turn}
                return

            content_blocks = result.get("content_blocks", [])
            tool_uses = result.get("tool_uses", [])
            stop_reason = result.get("stop_reason", "end_turn")

            # Token 用量
            usage = result.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            turn_cost = estimate_cost(self.model, input_tokens, output_tokens)
            self.total_cost += turn_cost

            if not content_blocks and result.get("content"):
                content_blocks = [{"type": "text", "text": result["content"]}]

            # yield text + thinking + tool_start
            for block in content_blocks:
                if block.get("type") == "text" and block.get("text"):
                    yield {"type": "text", "content": block["text"], "turn": turn}
                elif block.get("type") == "thinking" and block.get("thinking"):
                    yield {"type": "thinking", "content": block["thinking"], "turn": turn}
                elif block.get("type") == "tool_use":
                    tinp = block.get("input", {})
                    desc = tinp.get("description", _auto_title(block["name"], tinp))
                    yield {"type": "tool_start", "tool": block["name"], "args": tinp,
                        "tool_use_id": block["id"], "description": desc, "turn": turn}

            messages.append({"role": "assistant", "content": content_blocks})

            # usage 事件
            yield {"type": "usage", "turn": turn,
                "input_tokens": input_tokens, "output_tokens": output_tokens,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "turn_cost": round(turn_cost, 6), "total_cost": round(self.total_cost, 6),
                "context_tokens_est": estimate_messages_tokens(messages)}

            # 判断结束
            if not tool_uses:
                dur = (datetime.now() - start_time).total_seconds()
                yield {"type": "done", "turns": turn,
                    "total_tool_calls": self.total_tool_calls, "duration": dur,
                    "stop_reason": stop_reason, "work_dir": self.work_dir,
                    "file_changes": self.executor.file_changes[-20:],
                    "total_input_tokens": self.total_input_tokens,
                    "total_output_tokens": self.total_output_tokens,
                    "total_cost": round(self.total_cost, 6),
                    "todo_status": self.executor.todo_manager.read()}
                return

            # 执行工具 (v6: 分离 SubAgent 和普通工具)
            fc_before = len(self.executor.file_changes)
            tool_results = []

            subagent_calls = [tu for tu in tool_uses if tu["name"] == "task"]
            normal_calls = [tu for tu in tool_uses if tu["name"] != "task"]

            # 普通工具 (支持并行)
            if self.enable_parallel and len(normal_calls) > 1:
                calls = [(tu["name"], tu["input"], tu["id"]) for tu in normal_calls]
                par_results = await self.executor.execute_parallel(calls)
                result_map = {tid: (rs, tn) for tid, rs, tn in par_results}
                for tu in normal_calls:
                    tid = tu["id"]; tn = tu["name"]
                    self.total_tool_calls += 1
                    rs, _ = result_map.get(tid, ("", tn))
                    if len(rs) > MAX_TOOL_OUTPUT_LEN: rs = rs[:MAX_TOOL_OUTPUT_LEN] + "\n...[truncated]"
                    meta = self._extract_meta(tn, rs)
                    yield {"type": "tool_result", "tool": tn, "tool_use_id": tid,
                        "result": rs[:MAX_DISPLAY_RESULT], "result_meta": meta,
                        "success": "error" not in rs.lower()[:50], "turn": turn}
                    tool_results.append({"type": "tool_result", "tool_use_id": tid, "content": rs})
                    if tn in ("todo_write", "todo_read"):
                        yield {"type": "todo_update", "turn": turn, "todo_status": self.executor.todo_manager.read()}
            else:
                for tu in normal_calls:
                    tn, ti, tid = tu["name"], tu["input"], tu["id"]
                    self.total_tool_calls += 1
                    rs = await self.executor.execute(tn, ti)
                    if len(rs) > MAX_TOOL_OUTPUT_LEN: rs = rs[:MAX_TOOL_OUTPUT_LEN] + "\n...[truncated]"
                    meta = self._extract_meta(tn, rs)
                    yield {"type": "tool_result", "tool": tn, "tool_use_id": tid,
                        "result": rs[:MAX_DISPLAY_RESULT], "result_meta": meta,
                        "success": "error" not in rs.lower()[:50], "turn": turn}
                    tool_results.append({"type": "tool_result", "tool_use_id": tid, "content": rs})
                    if tn in ("todo_write", "todo_read"):
                        yield {"type": "todo_update", "turn": turn, "todo_status": self.executor.todo_manager.read()}

            # v6: SubAgent 调用
            for tu in subagent_calls:
                tid = tu["id"]; ti = tu["input"]
                self.total_tool_calls += 1
                subagent_type = ti.get("subagent_type", "general")
                yield {"type": "subagent_start", "tool_use_id": tid,
                       "subagent_type": subagent_type, "prompt": ti.get("prompt","")[:200], "turn": turn}
                try:
                    sub_result = await run_subagent(
                        ai_engine=self.ai_engine, work_dir=self.work_dir,
                        prompt=ti.get("prompt",""), subagent_type=subagent_type,
                        model=ti.get("model") or "claude-sonnet-4-5-20250929",
                        max_turns=min(ti.get("max_turns", 10), 15),
                        depth=self.subagent_depth + 1)
                    rs = json.dumps({"success": sub_result.get("success",False),
                        "summary": sub_result.get("summary",""), "turns": sub_result.get("turns",0),
                        "subagent_type": subagent_type}, ensure_ascii=False)
                    for fc in sub_result.get("files_changed", []):
                        self.executor.file_changes.append(fc)
                except Exception as e:
                    rs = json.dumps({"error": f"SubAgent failed: {str(e)}", "success": False})
                if len(rs) > MAX_TOOL_OUTPUT_LEN: rs = rs[:MAX_TOOL_OUTPUT_LEN]
                meta = self._extract_meta("task", rs)
                yield {"type": "subagent_result", "tool_use_id": tid,
                       "result": rs[:MAX_DISPLAY_RESULT], "result_meta": meta,
                       "subagent_type": subagent_type, "turn": turn}
                yield {"type": "tool_result", "tool": "task", "tool_use_id": tid,
                       "result": rs[:MAX_DISPLAY_RESULT], "result_meta": meta,
                       "success": "error" not in rs.lower()[:50], "turn": turn}
                tool_results.append({"type": "tool_result", "tool_use_id": tid, "content": rs})

            for ch in self.executor.file_changes[fc_before:]:
                yield {"type": "file_change", "action": ch.get("action",""),
                    "path": ch.get("path",""), "filename": ch.get("filename",""),
                    "added": ch.get("added",0), "removed": ch.get("removed",0), "turn": turn}

            messages.append({"role": "user", "content": tool_results})

            summary = build_turn_summary(tool_uses)
            yield {"type": "turn", "turn": turn,
                "tool_calls_this_turn": len(tool_uses),
                "total_tool_calls": self.total_tool_calls,
                "summary": summary, "display": summary["display"],
                "detail_items": summary["detail_items"]}

        dur = (datetime.now() - start_time).total_seconds()
        yield {"type": "error", "message": f"Reached max turns ({self.max_turns}).",
            "turns": self.max_turns, "total_tool_calls": self.total_tool_calls,
            "duration": dur, "file_changes": self.executor.file_changes[-20:],
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost": round(self.total_cost, 6)}

    async def _load_memory(self) -> str:
        """v6: 加载项目记忆"""
        candidates = [
            os.path.join(self.work_dir, ".cheapbuy_memory.md"),
            os.path.join(self.work_dir, "CLAUDE.md"),
            os.path.join(self.work_dir, ".claude", "CLAUDE.md"),
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f: content = f.read()
                    return content[:5000] if len(content) > 5000 else content
                except: pass
        return ""

    async def _summarize_context(self, messages: List[Dict]) -> List[Dict]:
        if len(messages) <= 4: return messages
        keep_first = messages[:1]; keep_last = messages[-4:]
        to_summarize = messages[1:-4]
        if not to_summarize: return messages
        summary_text = []
        for msg in to_summarize:
            role = msg.get("role",""); content = msg.get("content","")
            if isinstance(content, str):
                summary_text.append(f"[{role}]: {content[:500]}")
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict):
                        if b.get("type") == "text":
                            summary_text.append(f"[{role}]: {b.get('text','')[:300]}")
                        elif b.get("type") == "tool_use":
                            summary_text.append(f"[{role}]: Called {b.get('name')}")
                        elif b.get("type") == "tool_result":
                            summary_text.append(f"[tool_result]: {str(b.get('content',''))[:200]}")
        try:
            sr = await self.ai_engine.get_completion(
                messages=[{"role": "user", "content":
                    "Summarize this conversation concisely. Focus on tools called, files modified, what was done.\n\n"
                    + "\n".join(summary_text[:50])}],
                model=self.model, temperature=0.1, max_tokens=1024)
            sc = sr.get("content", "Previous context.")
        except: sc = "Previous conversation involved tool calls and modifications."
        compressed = keep_first + [
            {"role": "user", "content": f"[CONTEXT SUMMARY]\n{sc}"},
            {"role": "assistant", "content": "Understood. Continuing."},
        ] + keep_last
        return compressed

    def _extract_meta(self, tool_name: str, result_str: str) -> Dict[str, Any]:
        meta = {}
        try:
            d = json.loads(result_str)
            if tool_name == "read_file":
                meta["truncated"] = d.get("truncated", False)
                meta["filename"] = d.get("filename", "")
                meta["total_lines"] = d.get("total_lines", 0)
                if d.get("truncated"):
                    meta["truncated_range"] = d.get("truncated_range", "")
                    meta["hint"] = d.get("hint", "")
            elif tool_name == "batch_read":
                meta["files_read"] = d.get("files_read", 0)
                meta["files_errored"] = d.get("files_errored", 0)
            elif tool_name in ("edit_file", "multi_edit"):
                meta["diff"] = d.get("diff", "")
                meta["filename"] = d.get("filename", "")
                meta["added_lines"] = d.get("added_lines", 0)
                meta["removed_lines"] = d.get("removed_lines", 0)
                meta["unified_diff"] = d.get("unified_diff", "")
            elif tool_name == "write_file":
                meta["filename"] = d.get("filename", "")
                meta["lines"] = d.get("lines", 0)
                meta["action"] = d.get("action", "created")
            elif tool_name == "web_search":
                meta["results_count"] = d.get("results_count", 0)
                meta["query"] = d.get("query", "")
                meta["result_titles"] = [{"title": r.get("title",""), "url": r.get("url",""),
                    "domain": r.get("domain","")} for r in d.get("results",[])[:10]]
            elif tool_name == "web_fetch":
                meta["title"] = d.get("title", "")
                meta["url"] = d.get("url", "")
                meta["content_length"] = d.get("content_length", 0)
            elif tool_name == "file_search":
                meta["matches"] = d.get("matches", 0)
                meta["pattern"] = d.get("pattern", "")
            elif tool_name == "grep_search":
                meta["matches"] = d.get("matches", 0)
            elif tool_name == "bash":
                meta["exit_code"] = d.get("exit_code", -1)
            elif tool_name == "task_complete":
                meta["completed"] = True
                meta["summary"] = d.get("summary", "")
            # v5 新增
            elif tool_name == "view_truncated":
                meta["filename"] = d.get("filename", "")
                meta["total_lines"] = d.get("total_lines", 0)
                meta["lines"] = d.get("lines", "")
                meta["display_title"] = f"View truncated section of {d.get('filename', '')}"
            elif tool_name == "batch_commands":
                meta["total_commands"] = d.get("total_commands", 0)
                meta["executed"] = d.get("executed", 0)
                meta["succeeded"] = d.get("succeeded", 0)
                meta["failed"] = d.get("failed", 0)
                meta["display_title"] = d.get("display_title", "")
                meta["results"] = [
                    {"description": r.get("description",""), "success": r.get("success",False)}
                    for r in d.get("results",[])
                ]
            elif tool_name == "run_script":
                meta["exit_code"] = d.get("exit_code", -1)
                meta["script_preview"] = d.get("script", "")[:500]
                meta["description"] = d.get("description", "Script")
                meta["display_type"] = "script"
            elif tool_name == "revert_edit":
                meta["reverted"] = d.get("reverted", False)
                meta["filename"] = d.get("filename", "")
                meta["diff"] = d.get("diff", "")
                meta["display_title"] = d.get("display_title", "Revert edit")
            # v6 新增
            elif tool_name == "glob":
                meta["matches"] = d.get("matches", 0)
                meta["pattern"] = d.get("pattern", "")
            elif tool_name == "todo_write":
                meta["total"] = d.get("total", 0)
                meta["completed"] = d.get("completed", 0)
                meta["in_progress"] = d.get("in_progress", 0)
                meta["pending"] = d.get("pending", 0)
                meta["progress_display"] = d.get("progress_display", "")
                meta["display_title"] = d.get("display_title", "Updated tasks")
            elif tool_name == "todo_read":
                meta["total"] = d.get("total", 0)
                meta["completed"] = d.get("completed", 0)
                meta["progress_display"] = d.get("progress_display", "")
            elif tool_name == "task":
                meta["success"] = d.get("success", False)
                meta["summary"] = d.get("summary", "")[:500]
                meta["subagent_type"] = d.get("subagent_type", "general")
                meta["turns"] = d.get("turns", 0)
            elif tool_name == "memory_read":
                meta["size"] = d.get("size", 0)
                meta["has_content"] = bool(d.get("content"))
            elif tool_name == "memory_write":
                meta["success"] = d.get("success", False)
                meta["mode"] = d.get("mode", "append")
        except: pass
        return meta

    async def run_sync(self, task: str) -> Dict[str, Any]:
        events, texts = [], []
        async for ev in self.run(task):
            events.append(ev)
            if ev["type"] == "text": texts.append(ev["content"])
        last = events[-1] if events else {"type": "error", "message": "No events"}
        return {"success": last.get("type") == "done", "turns": last.get("turns", 0),
            "total_tool_calls": last.get("total_tool_calls", 0),
            "duration": last.get("duration", 0), "final_text": "\n".join(texts),
            "events": events, "work_dir": self.work_dir,
            "file_changes": self.executor.file_changes,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost": round(self.total_cost, 6),
            "todo_status": self.executor.todo_manager.read()}


def create_agentic_loop(ai_engine, user_id: str, project_id: str = None,
    base_workspace: str = None, model: str = None, max_turns: int = 30,
    system_prompt: str = None, enable_parallel: bool = True
) -> AgenticLoop:
    from app.config import settings
    base = base_workspace or getattr(settings, 'WORKSPACE_PATH', './workspace')
    project_id = project_id or f"task_{uuid.uuid4().hex[:12]}"
    work_dir = os.path.join(base, str(user_id), str(project_id))
    return AgenticLoop(ai_engine=ai_engine, work_dir=work_dir,
        model=model or AgenticLoop.DEFAULT_MODEL, max_turns=max_turns,
        system_prompt=system_prompt, enable_parallel=enable_parallel)