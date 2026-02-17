#!/usr/bin/env python3
"""
CheapBuy Agentic Loop 核心引擎 (v2 — 增强版)
=============================================

相比 v1 新增:
- web_search 工具 (对接 SerperSearchEngine)
- web_fetch 工具 (对接 WebBrowser / Jina Reader)
- edit_file 返回行级 diff 统计 (+N -M)
- read_file 超长文件自动截断 + truncated 标记
- turn 汇总事件: "Ran 3 commands, viewed 2 files, edited a file"

使用方式:
    from app.core.agents.agentic_loop import AgenticLoop

    loop = AgenticLoop(ai_engine=ai_engine, work_dir="/workspace/user1/project1")
    async for event in loop.run("创建一个 Flask REST API"):
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
            "For large files (>200 lines), content is auto-truncated showing head and tail. "
            "Use start_line/end_line to view specific sections."
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
    },
    {
        "name": "web_search",
        "description": (
            "Search the web using Google. Returns a list of results with title, URL and snippet. "
            "Use this when you need current information, documentation, or answers from the internet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (keep it short and specific, 1-6 words)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch the content of a web page and return it as cleaned plain text. "
            "Use this after web_search to read a specific page in detail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to fetch (must start with http:// or https://)"}
            },
            "required": ["url"]
        }
    },
]

# 默认 system prompt
AGENTIC_SYSTEM_PROMPT = """You are an expert software engineer working in a Linux environment with root access.
You have tools to read/write/edit files, run bash commands, search code, search the web, and fetch web pages.

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
10. When the task is complete and verified, stop calling tools.
11. Use web_search when you need current information, API docs, or unknown topics.
12. Use web_fetch to read full page content after finding relevant URLs via web_search."""


# =============================================================================
# 工具执行器
# =============================================================================

class ToolExecutor:
    """
    工具执行器 - 在项目 workspace 中执行工具调用
    
    所有文件操作的相对路径都以 work_dir 为根目录，
    绝对路径直接使用（root 权限下安全）。
    """
    
    # 文件查看截断阈值
    MAX_DISPLAY_LINES = 200
    MAX_HEAD_LINES = 100
    MAX_TAIL_LINES = 100
    
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
            "web_search": self._web_search,
            "web_fetch": self._web_fetch,
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
    
    # -------------------------------------------------------------------------
    # bash
    # -------------------------------------------------------------------------
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
                timeout=120
            )
            
            stdout_str = stdout.decode('utf-8', errors='replace')
            stderr_str = stderr.decode('utf-8', errors='replace')
            
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
    
    # -------------------------------------------------------------------------
    # read_file — 增强：自动截断 + truncated 标记
    # -------------------------------------------------------------------------
    async def _read_file(self, params: Dict) -> str:
        """读取文件内容，超长自动截断"""
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
            has_range = "start_line" in params or "end_line" in params
            
            if not has_range and total > self.MAX_DISPLAY_LINES:
                # 自动截断：显示头 + 尾
                head = "".join(
                    f"{i:4d} | {lines[i-1]}" for i in range(1, self.MAX_HEAD_LINES + 1)
                )
                tail = "".join(
                    f"{i:4d} | {lines[i-1]}" for i in range(total - self.MAX_TAIL_LINES + 1, total + 1)
                )
                omitted = total - self.MAX_HEAD_LINES - self.MAX_TAIL_LINES
                content = (
                    head
                    + f"\n... [{omitted} lines truncated — use start_line/end_line to view lines "
                    + f"{self.MAX_HEAD_LINES + 1}-{total - self.MAX_TAIL_LINES}] ...\n\n"
                    + tail
                )
                return json.dumps({
                    "path": path,
                    "lines": f"1-{self.MAX_HEAD_LINES}+{total - self.MAX_TAIL_LINES + 1}-{total}/{total}",
                    "content": content,
                    "truncated": True,
                    "truncated_range": f"{self.MAX_HEAD_LINES + 1}-{total - self.MAX_TAIL_LINES}"
                })
            
            # 正常模式（含 start_line/end_line）
            start = max(1, params.get("start_line", 1))
            end = min(total, params.get("end_line", total))
            
            content = ""
            for i in range(start, end + 1):
                content += f"{i:4d} | {lines[i-1]}"
            
            return json.dumps({
                "path": path,
                "lines": f"{start}-{end}/{total}",
                "content": content,
                "truncated": False
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to read file: {str(e)}"})
    
    # -------------------------------------------------------------------------
    # write_file
    # -------------------------------------------------------------------------
    async def _write_file(self, params: Dict) -> str:
        """写入文件"""
        path = self._resolve_path(params["path"])
        content = params["content"]
        
        try:
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
    
    # -------------------------------------------------------------------------
    # edit_file — 增强：行级 diff 统计 (+N -M)
    # -------------------------------------------------------------------------
    async def _edit_file(self, params: Dict) -> str:
        """编辑文件（精确替换），返回行级 diff"""
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
            
            # 行级 diff 统计
            old_line_count = old_str.count('\n') + (1 if old_str and not old_str.endswith('\n') else 0)
            new_line_count = new_str.count('\n') + (1 if new_str and not new_str.endswith('\n') else 0)
            added = max(0, new_line_count - old_line_count)
            removed = max(0, old_line_count - new_line_count)
            # 即使行数没变也至少算 1 行修改
            if added == 0 and removed == 0:
                # 有内容变化但行数不变：标记为修改的行数
                changed_lines = old_str.count('\n') + 1
                added = changed_lines
                removed = changed_lines
            
            filename = os.path.basename(path)
            
            return json.dumps({
                "success": True,
                "path": path,
                "diff": f"{filename} +{added} -{removed}",
                "added_lines": added,
                "removed_lines": removed
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to edit file: {str(e)}"})
    
    # -------------------------------------------------------------------------
    # list_dir
    # -------------------------------------------------------------------------
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
    
    # -------------------------------------------------------------------------
    # grep_search
    # -------------------------------------------------------------------------
    async def _grep_search(self, params: Dict) -> str:
        """搜索代码"""
        pattern = params["pattern"]
        path = self._resolve_path(params.get("path", "."))
        
        cmd = ["grep", "-rn", "--max-count=50", "--color=never"]
        
        if params.get("include"):
            cmd += ["--include", params["include"]]
        
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
            
            if len(result) > 8000:
                result = result[:8000] + "\n...[truncated, showing first 8000 chars]"
            
            return result
            
        except asyncio.TimeoutError:
            return json.dumps({"error": "Search timed out"})
        except Exception as e:
            return json.dumps({"error": f"Search failed: {str(e)}"})
    
    # -------------------------------------------------------------------------
    # web_search — 新增：对接 SerperSearchEngine
    # -------------------------------------------------------------------------
    async def _web_search(self, params: Dict) -> str:
        """搜索网络"""
        query = params["query"]
        logger.info(f"[web_search] query: {query}")
        
        try:
            from app.core.web_search import SerperSearchEngine
            engine = SerperSearchEngine()
            results = await engine.search(query, max_results=10)
            
            if not results:
                return json.dumps({"query": query, "results_count": 0, "results": []})
            
            # 检查是否有错误
            if results and isinstance(results[0], dict) and "error" in results[0]:
                return json.dumps({
                    "query": query,
                    "error": results[0]["error"]
                })
            
            return json.dumps({
                "query": query,
                "results_count": len(results),
                "results": results
            }, ensure_ascii=False)
            
        except ImportError:
            # 降级：用 bash curl 调搜索
            logger.warning("web_search: SerperSearchEngine not available, falling back to stub")
            return json.dumps({
                "query": query,
                "error": "Web search module not available. Install: SERPER_API_KEY in .env"
            })
        except Exception as e:
            logger.error(f"web_search error: {e}", exc_info=True)
            return json.dumps({"query": query, "error": str(e)})
    
    # -------------------------------------------------------------------------
    # web_fetch — 新增：对接 WebBrowser (Jina Reader)
    # -------------------------------------------------------------------------
    async def _web_fetch(self, params: Dict) -> str:
        """获取网页内容"""
        url = params["url"]
        logger.info(f"[web_fetch] url: {url}")
        
        try:
            from app.core.web_search import WebBrowser
            browser = WebBrowser(max_content_length=15000)
            content = await browser.browse(url, clean=True)
            
            return json.dumps({
                "url": url,
                "content_length": len(content),
                "content": content
            }, ensure_ascii=False)
            
        except ImportError:
            # 降级：用 httpx 直接获取
            logger.warning("web_fetch: WebBrowser not available, using httpx fallback")
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    text = resp.text
                    # 简单去 HTML 标签
                    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if len(text) > 15000:
                        text = text[:15000] + "\n...[truncated]"
                    return json.dumps({
                        "url": url,
                        "status": resp.status_code,
                        "content_length": len(text),
                        "content": text
                    }, ensure_ascii=False)
            except Exception as e2:
                return json.dumps({"url": url, "error": str(e2)})
        except Exception as e:
            logger.error(f"web_fetch error: {e}", exc_info=True)
            return json.dumps({"url": url, "error": str(e)})
    
    # -------------------------------------------------------------------------
    # 路径解析
    # -------------------------------------------------------------------------
    def _resolve_path(self, path: str) -> str:
        """解析路径 - 相对路径基于 work_dir，绝对路径直接使用"""
        if os.path.isabs(path):
            return path
        return os.path.join(self.work_dir, path)


# =============================================================================
# Turn 汇总工具
# =============================================================================

def build_turn_summary(tool_uses: List[Dict]) -> Dict[str, Any]:
    """
    根据本轮的 tool_use 列表，生成汇总统计和展示文本。
    
    返回:
        {
            "commands_run": 3,
            "files_viewed": 2,
            "files_edited": 1,
            "files_created": 0,
            "searches": 1,
            "pages_fetched": 0,
            "display": "Ran 3 commands, viewed 2 files, edited a file, searched the web"
        }
    """
    counts = {
        "bash": 0, "read_file": 0, "write_file": 0,
        "edit_file": 0, "list_dir": 0, "grep_search": 0,
        "web_search": 0, "web_fetch": 0,
    }
    for tu in tool_uses:
        name = tu.get("name", "")
        if name in counts:
            counts[name] += 1
    
    parts = []
    if counts["bash"]:
        n = counts["bash"]
        parts.append(f"Ran {n} command{'s' if n > 1 else ''}")
    if counts["read_file"]:
        n = counts["read_file"]
        parts.append(f"viewed {n} file{'s' if n > 1 else ''}")
    if counts["write_file"]:
        n = counts["write_file"]
        parts.append(f"created {n} file{'s' if n > 1 else ''}")
    if counts["edit_file"]:
        n = counts["edit_file"]
        parts.append(f"edited {n} file{'s' if n > 1 else ''}")
    if counts["list_dir"] or counts["grep_search"]:
        n = counts["list_dir"] + counts["grep_search"]
        parts.append(f"searched {n} path{'s' if n > 1 else ''}")
    if counts["web_search"]:
        parts.append("searched the web")
    if counts["web_fetch"]:
        n = counts["web_fetch"]
        parts.append(f"fetched {n} page{'s' if n > 1 else ''}")
    
    display = ", ".join(parts) if parts else "Done"
    # 首字母大写
    display = display[0].upper() + display[1:] if display else "Done"
    
    return {
        "commands_run": counts["bash"],
        "files_viewed": counts["read_file"],
        "files_edited": counts["edit_file"],
        "files_created": counts["write_file"],
        "searches": counts["web_search"],
        "pages_fetched": counts["web_fetch"],
        "display": display
    }


# =============================================================================
# Agentic Loop 核心
# =============================================================================

class AgenticLoop:
    """
    Agentic Loop 核心引擎
    
    通过 AsyncGenerator 模式运行，每个事件 yield 给调用者。
    调用者（API 层）将事件转为 SSE 推送给前端。
    
    事件类型：
    - start:        任务开始
    - text:         AI 的文本输出
    - tool_start:   开始执行工具（附带工具名称和参数）
    - tool_result:  工具执行结果
    - turn:         一轮结束（含汇总: "Ran 3 commands, viewed 2 files"）
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
            
            if not content_blocks and result.get("content"):
                content_blocks = [{"type": "text", "text": result["content"]}]
            
            # yield 文本和工具调用事件
            for block in content_blocks:
                if block.get("type") == "text" and block.get("text"):
                    yield {
                        "type": "text",
                        "content": block["text"],
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
            
            # 将 assistant 消息追加到 history
            messages.append({"role": "assistant", "content": content_blocks})
            
            # ====== 判断是否结束 ======
            if not tool_uses:
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
                
                result_str = await self.executor.execute(tool_name, tool_input)
                
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
                
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_str
                })
            
            # 将工具结果追加到 messages
            messages.append({"role": "user", "content": tool_results})
            
            # ====== yield turn 汇总事件 ======
            summary = build_turn_summary(tool_uses)
            yield {
                "type": "turn",
                "turn": turn,
                "tool_calls_this_turn": len(tool_uses),
                "total_tool_calls": self.total_tool_calls,
                "summary": summary,
                "display": summary["display"]
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