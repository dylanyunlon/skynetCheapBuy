#!/usr/bin/env python3
"""
CheapBuy Agentic Loop 核心引擎
===============================

将 test_agentic_loop.py 的原型改造为生产级后端组件。

核心思路：
- 复用现有 AIEngine + ClaudeCompatibleProvider（已改造支持 tools）
- ToolExecutor 在用户的 workspace 目录下执行，与项目文件系统融合
- 通过 AsyncGenerator yield 事件，供 API 层 SSE 推送给前端
- 每个 tool_use 都有对应的 tool_result 回传，形成完整的 agentic loop

使用方式：
    from app.core.agents.agentic_loop import AgenticLoop

    loop = AgenticLoop(ai_engine=ai_engine, work_dir="/workspace/user1/project1")
    async for event in loop.run("创建一个 Flask REST API"):
        # event: {"type": "text|tool_start|tool_result|turn|done|error", ...}
        await sse_send(event)
"""

import os
import re
import json
import asyncio
import logging
import uuid
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# =============================================================================
# 工具定义（Claude /v1/messages 原生格式）
# =============================================================================

TOOL_DEFINITIONS = [
    {
        "name": "bash",
        "description": (
            "Execute a bash command in the project workspace. "
            "Use for: running scripts, installing packages (pip/npm), "
            "checking system status, running tests, starting servers. "
            "Commands run with root privileges. Working directory is the project root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": (
            "Read the contents of a file. Returns content with line numbers. "
            "Use start_line/end_line for large files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (relative to project root or absolute)"},
                "start_line": {"type": "integer", "description": "Start line number (1-indexed, optional)"},
                "end_line": {"type": "integer", "description": "End line number (inclusive, optional)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": (
            "Create or overwrite a file with the given content. "
            "Parent directories are created automatically. "
            "Use this for creating new files or completely replacing file content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (relative to project root or absolute)"},
                "content": {"type": "string", "description": "Complete file content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": (
            "Edit a file by replacing a unique string with another. "
            "old_str must appear exactly once in the file. "
            "Use this for surgical edits instead of rewriting the whole file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_str": {"type": "string", "description": "Exact string to replace (must appear exactly once)"},
                "new_str": {"type": "string", "description": "Replacement string"}
            },
            "required": ["path", "old_str", "new_str"]
        }
    },
    {
        "name": "list_dir",
        "description": "List files and directories. Shows file sizes. Skips hidden dirs, __pycache__, node_modules.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (default: project root)"}
            },
            "required": []
        }
    },
    {
        "name": "grep_search",
        "description": (
            "Search for a regex pattern in files. Returns matching lines with file paths and line numbers. "
            "Use 'include' to filter by file extension (e.g. '*.py')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex)"},
                "path": {"type": "string", "description": "Directory to search in (default: project root)"},
                "include": {"type": "string", "description": "File glob pattern, e.g. '*.py', '*.js'"}
            },
            "required": ["pattern"]
        }
    }
]

# 默认 system prompt
AGENTIC_SYSTEM_PROMPT = """You are an expert software engineer working in a Linux environment with root access.
You have tools to read/write/edit files, run bash commands, and search code.

Rules:
1. Always use tools to verify your work - don't assume, check.
2. When creating projects, write ALL files before running them.
3. If a command fails, read the error carefully, fix the issue, and retry.
4. Use edit_file for small changes, write_file for new files or complete rewrites.
5. Install dependencies before running code (pip install, npm install, etc).
6. For web projects, use proper project structure with separate files.
7. After creating a project, always run it to verify it works.
8. If you encounter errors, debug systematically: read the file, understand the error, fix it, verify.
9. Keep responses concise - focus on actions, not explanations.
10. When the task is complete and verified, stop calling tools."""


# =============================================================================
# 工具执行器
# =============================================================================

class ToolExecutor:
    """
    工具执行器 - 在项目 workspace 中执行工具调用
    
    所有文件操作的相对路径都以 work_dir 为根目录，
    绝对路径直接使用（root 权限下安全）。
    """
    
    def __init__(self, work_dir: str):
        self.work_dir = os.path.abspath(work_dir)
        os.makedirs(self.work_dir, exist_ok=True)
        logger.info(f"ToolExecutor initialized, work_dir: {self.work_dir}")
    
    async def execute(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """执行工具调用，返回结果字符串"""
        handlers = {
            "bash": self._bash,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "list_dir": self._list_dir,
            "grep_search": self._grep_search,
        }
        
        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        
        try:
            result = await handler(tool_input)
            return result
        except Exception as e:
            logger.error(f"Tool {tool_name} execution error: {e}", exc_info=True)
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})
    
    async def _bash(self, params: Dict) -> str:
        """执行 bash 命令"""
        command = params["command"]
        logger.info(f"[bash] $ {command}")
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir,
                env={**os.environ, "HOME": self.work_dir, "PWD": self.work_dir}
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120  # 2 分钟超时
            )
            
            stdout_str = stdout.decode('utf-8', errors='replace')
            stderr_str = stderr.decode('utf-8', errors='replace')
            
            # 截断过长输出
            if len(stdout_str) > 10000:
                stdout_str = stdout_str[:10000] + "\n...[truncated, showing first 10000 chars]"
            if len(stderr_str) > 5000:
                stderr_str = stderr_str[:5000] + "\n...[truncated]"
            
            return json.dumps({
                "exit_code": process.returncode,
                "stdout": stdout_str,
                "stderr": stderr_str
            })
            
        except asyncio.TimeoutError:
            return json.dumps({"error": "Command timed out after 120 seconds"})
    
    async def _read_file(self, params: Dict) -> str:
        """读取文件内容"""
        path = self._resolve_path(params["path"])
        
        if not os.path.exists(path):
            return json.dumps({"error": f"File not found: {path}"})
        
        if not os.path.isfile(path):
            return json.dumps({"error": f"Not a file: {path}"})
        
        try:
            file_size = os.path.getsize(path)
            if file_size > 500000:  # 500KB
                return json.dumps({"error": f"File too large ({file_size} bytes). Use start_line/end_line."})
            
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            
            total = len(lines)
            start = max(1, params.get("start_line", 1))
            end = min(total, params.get("end_line", total))
            
            content = ""
            for i in range(start, end + 1):
                content += f"{i:4d} | {lines[i-1]}"
            
            return json.dumps({
                "path": path,
                "lines": f"{start}-{end}/{total}",
                "content": content
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to read file: {str(e)}"})
    
    async def _write_file(self, params: Dict) -> str:
        """写入文件"""
        path = self._resolve_path(params["path"])
        content = params["content"]
        
        try:
            # 自动创建父目录
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            line_count = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
            
            return json.dumps({
                "success": True,
                "path": path,
                "size": len(content),
                "lines": line_count
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to write file: {str(e)}"})
    
    async def _edit_file(self, params: Dict) -> str:
        """编辑文件（精确替换）"""
        path = self._resolve_path(params["path"])
        old_str = params["old_str"]
        new_str = params["new_str"]
        
        if not os.path.exists(path):
            return json.dumps({"error": f"File not found: {path}"})
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            count = content.count(old_str)
            if count == 0:
                # 提供上下文帮助 AI 理解
                return json.dumps({
                    "error": "old_str not found in file",
                    "hint": f"File has {len(content)} chars, {content.count(chr(10))} lines. "
                            f"First 200 chars: {content[:200]}"
                })
            if count > 1:
                return json.dumps({
                    "error": f"old_str found {count} times, must be unique. Make your old_str more specific."
                })
            
            new_content = content.replace(old_str, new_str, 1)
            
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            return json.dumps({
                "success": True,
                "path": path,
                "chars_removed": len(old_str),
                "chars_added": len(new_str)
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to edit file: {str(e)}"})
    
    async def _list_dir(self, params: Dict) -> str:
        """列出目录内容"""
        path = self._resolve_path(params.get("path", "."))
        
        if not os.path.exists(path):
            return json.dumps({"error": f"Directory not found: {path}"})
        
        if not os.path.isdir(path):
            return json.dumps({"error": f"Not a directory: {path}"})
        
        skip = {'__pycache__', '.git', 'node_modules', '.venv', 'venv', '.cache', '.mypy_cache'}
        
        try:
            items = sorted(os.listdir(path))
            lines = []
            for item in items:
                if item in skip or item.startswith('.'):
                    continue
                full_path = os.path.join(path, item)
                if os.path.isdir(full_path):
                    # 统计子目录中的文件数
                    try:
                        count = len([f for f in os.listdir(full_path) if not f.startswith('.')])
                    except PermissionError:
                        count = '?'
                    lines.append(f"  📁 {item}/ ({count} items)")
                else:
                    size = os.path.getsize(full_path)
                    if size > 1024 * 1024:
                        size_str = f"{size / 1024 / 1024:.1f}MB"
                    elif size > 1024:
                        size_str = f"{size / 1024:.1f}KB"
                    else:
                        size_str = f"{size}B"
                    lines.append(f"  📄 {item} ({size_str})")
            
            return f"📁 {path}\n" + "\n".join(lines) if lines else f"📁 {path}\n  (empty directory)"
        except Exception as e:
            return json.dumps({"error": f"Failed to list directory: {str(e)}"})
    
    async def _grep_search(self, params: Dict) -> str:
        """搜索代码"""
        pattern = params["pattern"]
        path = self._resolve_path(params.get("path", "."))
        
        cmd = ["grep", "-rn", "--max-count=50", "--color=never"]
        
        if params.get("include"):
            cmd += ["--include", params["include"]]
        
        # 排除常见的无关目录
        cmd += [
            "--exclude-dir=__pycache__",
            "--exclude-dir=.git",
            "--exclude-dir=node_modules",
            "--exclude-dir=.venv",
            "--exclude-dir=venv",
        ]
        
        cmd += [pattern, path]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
            result = stdout.decode('utf-8', errors='replace')
            
            if not result:
                return "(no matches found)"
            
            # 截断过长结果
            if len(result) > 8000:
                result = result[:8000] + "\n...[truncated, showing first 8000 chars]"
            
            return result
            
        except asyncio.TimeoutError:
            return json.dumps({"error": "Search timed out"})
        except Exception as e:
            return json.dumps({"error": f"Search failed: {str(e)}"})
    
    def _resolve_path(self, path: str) -> str:
        """解析路径 - 相对路径基于 work_dir，绝对路径直接使用"""
        if os.path.isabs(path):
            return path
        return os.path.join(self.work_dir, path)


# =============================================================================
# Agentic Loop 核心
# =============================================================================

class AgenticLoop:
    """
    Agentic Loop 核心引擎
    
    通过 AsyncGenerator 模式运行，每个事件 yield 给调用者。
    调用者（API 层）将事件转为 SSE 推送给前端。
    
    事件类型：
    - text:         AI 的文本输出
    - tool_start:   开始执行工具（附带工具名称和参数）
    - tool_result:  工具执行结果
    - turn:         一轮结束
    - done:         任务完成
    - error:        出错
    """
    
    DEFAULT_MODEL = "claude-opus-4-6"
    
    def __init__(
        self,
        ai_engine,
        work_dir: str,
        model: str = None,
        max_turns: int = 30,
        system_prompt: str = None
    ):
        self.ai_engine = ai_engine
        self.work_dir = os.path.abspath(work_dir)
        self.model = model or self.DEFAULT_MODEL
        self.max_turns = max_turns
        self.system_prompt = system_prompt or AGENTIC_SYSTEM_PROMPT
        self.executor = ToolExecutor(self.work_dir)
        
        # 运行状态
        self.turn_count = 0
        self.total_tool_calls = 0
        self.events: List[Dict] = []
        
        os.makedirs(self.work_dir, exist_ok=True)
    
    async def run(self, task: str) -> AsyncGenerator[Dict[str, Any], None]:
        """
        运行 Agentic Loop
        
        每个 yield 的 dict 是一个事件，前端可以直接渲染。
        循环条件：AI 返回 tool_use blocks → 执行 → 回传结果 → 再调 AI
        终止条件：AI 不再调用工具（stop_reason == "end_turn"）或达到 max_turns
        """
        start_time = datetime.now()
        
        # 初始化消息
        messages = [{"role": "user", "content": task}]
        
        yield {
            "type": "start",
            "task": task[:500],
            "model": self.model,
            "work_dir": self.work_dir,
            "max_turns": self.max_turns,
            "timestamp": datetime.now().isoformat()
        }
        
        for turn in range(1, self.max_turns + 1):
            self.turn_count = turn
            
            logger.info(f"[AgenticLoop] Turn {turn}/{self.max_turns}")
            
            # ====== 调用 AI ======
            try:
                result = await self.ai_engine.get_completion(
                    messages=messages,
                    model=self.model,
                    system_prompt=self.system_prompt,
                    tools=TOOL_DEFINITIONS,
                    temperature=0.3,
                    max_tokens=8192
                )
            except Exception as e:
                logger.error(f"[AgenticLoop] AI call failed: {e}")
                yield {"type": "error", "message": f"AI call failed: {str(e)}", "turn": turn}
                return
            
            # ====== 解析响应 ======
            content_blocks = result.get("content_blocks", [])
            tool_uses = result.get("tool_uses", [])
            stop_reason = result.get("stop_reason", "end_turn")
            
            # 如果 content_blocks 为空，尝试从旧格式获取
            if not content_blocks and result.get("content"):
                content_blocks = [{"type": "text", "text": result["content"]}]
            
            # yield 文本和工具调用事件
            for block in content_blocks:
                if block.get("type") == "text" and block.get("text"):
                    text = block["text"]
                    yield {
                        "type": "text",
                        "content": text,
                        "turn": turn
                    }
                elif block.get("type") == "tool_use":
                    yield {
                        "type": "tool_start",
                        "tool": block["name"],
                        "args": block["input"],
                        "tool_use_id": block["id"],
                        "turn": turn
                    }
            
            # 将 assistant 消息追加到 history（包含完整 blocks）
            messages.append({"role": "assistant", "content": content_blocks})
            
            # ====== 判断是否结束 ======
            if not tool_uses:
                # AI 没有调用任何工具，任务完成
                duration = (datetime.now() - start_time).total_seconds()
                yield {
                    "type": "done",
                    "turns": turn,
                    "total_tool_calls": self.total_tool_calls,
                    "duration": duration,
                    "stop_reason": stop_reason,
                    "work_dir": self.work_dir
                }
                return
            
            if stop_reason == "end_turn" and not tool_uses:
                duration = (datetime.now() - start_time).total_seconds()
                yield {
                    "type": "done",
                    "turns": turn,
                    "total_tool_calls": self.total_tool_calls,
                    "duration": duration,
                    "stop_reason": stop_reason,
                    "work_dir": self.work_dir
                }
                return
            
            # ====== 执行工具 ======
            tool_results = []
            
            for tu in tool_uses:
                tool_name = tu["name"]
                tool_input = tu["input"]
                tool_id = tu["id"]
                self.total_tool_calls += 1
                
                logger.info(f"[AgenticLoop] Executing tool: {tool_name} (id={tool_id})")
                
                # 执行
                result_str = await self.executor.execute(tool_name, tool_input)
                
                # 截断过长的结果
                if len(result_str) > 15000:
                    result_str = result_str[:15000] + "\n...[truncated to 15000 chars]"
                
                # yield 工具结果事件
                yield {
                    "type": "tool_result",
                    "tool": tool_name,
                    "tool_use_id": tool_id,
                    "result": result_str[:2000],  # 给前端的摘要
                    "success": "error" not in result_str.lower()[:50],
                    "turn": turn
                }
                
                # 构造 Claude 格式的 tool_result
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_str
                })
            
            # 将工具结果追加到 messages（Claude 格式：user message with tool_result blocks）
            messages.append({"role": "user", "content": tool_results})
            
            # yield turn 完成事件
            yield {
                "type": "turn",
                "turn": turn,
                "tool_calls_this_turn": len(tool_uses),
                "total_tool_calls": self.total_tool_calls
            }
        
        # 达到最大轮次
        duration = (datetime.now() - start_time).total_seconds()
        yield {
            "type": "error",
            "message": f"Reached maximum turns ({self.max_turns}). Task may be incomplete.",
            "turns": self.max_turns,
            "total_tool_calls": self.total_tool_calls,
            "duration": duration
        }
    
    async def run_sync(self, task: str) -> Dict[str, Any]:
        """
        同步模式运行（收集所有事件，返回最终结果）
        用于非 SSE 场景（如 create-project 内部调用）
        """
        events = []
        final_text_parts = []
        
        async for event in self.run(task):
            events.append(event)
            if event["type"] == "text":
                final_text_parts.append(event["content"])
        
        last_event = events[-1] if events else {"type": "error", "message": "No events"}
        
        return {
            "success": last_event.get("type") == "done",
            "turns": last_event.get("turns", 0),
            "total_tool_calls": last_event.get("total_tool_calls", 0),
            "duration": last_event.get("duration", 0),
            "final_text": "\n".join(final_text_parts),
            "events": events,
            "work_dir": self.work_dir
        }


# =============================================================================
# 便捷工厂函数
# =============================================================================

def create_agentic_loop(
    ai_engine,
    user_id: str,
    project_id: str = None,
    base_workspace: str = None,
    model: str = None,
    max_turns: int = 30,
    system_prompt: str = None
) -> AgenticLoop:
    """
    创建 AgenticLoop 实例的工厂函数
    
    自动构建 workspace 路径：{base_workspace}/{user_id}/{project_id}/
    """
    from app.config import settings
    
    base = base_workspace or getattr(settings, 'WORKSPACE_PATH', './workspace')
    project_id = project_id or f"task_{uuid.uuid4().hex[:12]}"
    work_dir = os.path.join(base, str(user_id), str(project_id))
    
    return AgenticLoop(
        ai_engine=ai_engine,
        work_dir=work_dir,
        model=model or AgenticLoop.DEFAULT_MODEL,
        max_turns=max_turns,
        system_prompt=system_prompt
    )