#!/usr/bin/env python3
"""
CheapBuy Agentic Loop 核心引擎 (v3 — Claude Code 全功能版)
==========================================================
v3 新增: file_search, batch_read, multi_edit, task_complete 工具
         description 字段, 结构化 result_meta, file_change 事件, detail_items
"""

import os
import re
import json
import asyncio
import logging
import uuid
import difflib
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# 工具定义
# =============================================================================

TOOL_DEFINITIONS = [
    {
        "name": "bash",
        "description": "Execute a bash command in the project workspace. Always provide a 'description' field summarizing what this command does.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute"},
                "description": {"type": "string", "description": "Short human-readable title, e.g. 'Install dependencies'"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120, max: 600)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read file contents with line numbers. Large files auto-truncated. Use start_line/end_line for sections.",
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
        "description": "Read multiple files in one call. More efficient than multiple read_file calls.",
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
        "description": "Replace a unique string in a file. old_str must appear exactly once. Returns diff stats (+N -M).",
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
        "description": "Apply multiple edits to one file atomically. Each edit is {old_str, new_str} applied sequentially.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "edits": {"type": "array", "items": {"type": "object", "properties": {"old_str": {"type": "string"}, "new_str": {"type": "string"}}, "required": ["old_str", "new_str"]}, "description": "List of edits"},
                "description": {"type": "string", "description": "What you're changing"}
            },
            "required": ["path", "edits"]
        }
    },
    {
        "name": "list_dir",
        "description": "List files and directories with sizes. Skips hidden dirs, __pycache__, node_modules.",
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
        "description": "Search for regex pattern in files. Returns matching lines with paths and line numbers.",
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
        "description": "Search for files by name pattern (glob). Find files when you know part of the name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.py', 'config*', 'README*'"},
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
        "description": "Fetch web page as cleaned text. Returns title and content.",
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
]

AGENTIC_SYSTEM_PROMPT = """You are an expert software engineer working in a Linux environment with root access.
You have tools to read/write/edit files, run bash commands, search code, search the web, and fetch web pages.

IMPORTANT: For every tool call, include a 'description' field with a short human-readable title.
This description appears in the UI so the user can understand what you're doing at a glance.

Examples of good descriptions:
- bash: "Install Flask and dependencies", "Run the test suite"
- read_file: "View the main entry point", "Read the config file"
- edit_file: "Replace scalar XOR with VALU XOR", "Fix import statement"
- write_file: "Create Flask app entry point", "Add requirements.txt"

Rules:
1. Always use tools to verify your work - don't assume, check.
2. When creating projects, write ALL files before running them.
3. If a command fails, read the error, fix it, retry.
4. Use edit_file for small changes, multi_edit for multiple changes in one file, write_file for new files.
5. Install dependencies before running code.
6. After creating a project, run it to verify it works.
7. Debug systematically: read file, understand error, fix, verify.
8. Keep responses concise - focus on actions.
9. When complete, call task_complete with a summary.
10. Use web_search for current info, web_fetch for full page content.
11. Use batch_read for multiple files, file_search to find files by name.
12. Use multi_edit for multiple changes in a single file."""


# =============================================================================
# 工具执行器 (v3)
# =============================================================================

SKIP_DIRS = {
    '__pycache__', '.git', 'node_modules', '.venv', 'venv',
    '.cache', '.mypy_cache', '.pytest_cache', '.tox',
    'dist', 'build', '.egg-info', '.eggs', 'htmlcov',
    '.next', '.nuxt', 'coverage'
}

class ToolExecutor:
    MAX_DISPLAY_LINES = 200
    MAX_HEAD_LINES = 100
    MAX_TAIL_LINES = 100

    def __init__(self, work_dir: str):
        self.work_dir = os.path.abspath(work_dir)
        os.makedirs(self.work_dir, exist_ok=True)
        self.file_changes: List[Dict[str, Any]] = []
        logger.info(f"ToolExecutor initialized, work_dir: {self.work_dir}")

    async def execute(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        handlers = {
            "bash": self._bash, "read_file": self._read_file,
            "batch_read": self._batch_read, "write_file": self._write_file,
            "edit_file": self._edit_file, "multi_edit": self._multi_edit,
            "list_dir": self._list_dir, "grep_search": self._grep_search,
            "file_search": self._file_search, "web_search": self._web_search,
            "web_fetch": self._web_fetch, "task_complete": self._task_complete,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            return await handler(tool_input)
        except Exception as e:
            logger.error(f"Tool {tool_name} error: {e}", exc_info=True)
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})

    async def _bash(self, params: Dict) -> str:
        command = params["command"]
        timeout = min(params.get("timeout", 120), 600)
        logger.info(f"[bash] $ {command}")
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
            return json.dumps({"exit_code": proc.returncode, "stdout": out, "stderr": err})
        except asyncio.TimeoutError:
            return json.dumps({"error": f"Command timed out after {timeout}s"})

    async def _read_file(self, params: Dict) -> str:
        path = self._resolve(params["path"])
        if not os.path.exists(path):
            return json.dumps({"error": f"File not found: {path}"})
        if not os.path.isfile(path):
            return json.dumps({"error": f"Not a file: {path}"})
        try:
            sz = os.path.getsize(path)
            if sz > 500000:
                return json.dumps({"error": f"File too large ({sz} bytes). Use start_line/end_line.", "file_size": sz})
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            total = len(lines)
            fname = os.path.basename(path)
            has_range = "start_line" in params or "end_line" in params
            if not has_range and total > self.MAX_DISPLAY_LINES:
                head = "".join(f"{i:4d} | {lines[i-1]}" for i in range(1, self.MAX_HEAD_LINES+1))
                tail = "".join(f"{i:4d} | {lines[i-1]}" for i in range(total-self.MAX_TAIL_LINES+1, total+1))
                omit = total - self.MAX_HEAD_LINES - self.MAX_TAIL_LINES
                ts, te = self.MAX_HEAD_LINES+1, total-self.MAX_TAIL_LINES
                content = head + f"\n... [{omit} lines truncated — use start_line/end_line to view {ts}-{te}] ...\n\n" + tail
                return json.dumps({"path":path,"filename":fname,"total_lines":total,
                    "lines":f"1-{self.MAX_HEAD_LINES}+{total-self.MAX_TAIL_LINES+1}-{total}/{total}",
                    "content":content,"truncated":True,
                    "truncated_start":ts,"truncated_end":te,
                    "truncated_range":f"{ts}-{te}",
                    "hint":f"View truncated section of {fname}"})
            start = max(1, params.get("start_line", 1))
            end = min(total, params.get("end_line", total))
            content = "".join(f"{i:4d} | {lines[i-1]}" for i in range(start, end+1))
            return json.dumps({"path":path,"filename":fname,"total_lines":total,
                "lines":f"{start}-{end}/{total}","content":content,"truncated":False})
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
                    entry = {"filename":d.get("filename",""),"lines":d.get("lines",""),
                        "total_lines":d.get("total_lines",0),"truncated":d.get("truncated",False),
                        "content":d.get("content","")}
                    if d.get("truncated"):
                        entry["truncated_range"] = d.get("truncated_range","")
                        entry["hint"] = d.get("hint","")
                    results[p] = entry
            except: errors[p] = "parse error"
        return json.dumps({"files_read":len(results),"files_errored":len(errors),
            "results":results,"errors":errors or None}, ensure_ascii=False)

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
            self.file_changes.append({"action":act,"path":path,"filename":fn,"lines":lc})
            return json.dumps({"success":True,"path":path,"filename":fn,"size":len(content),"lines":lc,"action":act})
        except Exception as e:
            return json.dumps({"error": f"Write failed: {str(e)}"})

    async def _edit_file(self, params: Dict) -> str:
        path = self._resolve(params["path"])
        old_s, new_s = params["old_str"], params["new_str"]
        if not os.path.exists(path):
            return json.dumps({"error": f"File not found: {path}"})
        try:
            with open(path,'r',encoding='utf-8') as f: content = f.read()
            cnt = content.count(old_s)
            if cnt == 0:
                sim = self._find_similar(content, old_s)
                return json.dumps({"error":"old_str not found","path":path,
                    "file_lines":content.count('\n')+1,"hint":f"Similar: {sim[:200]}" if sim else "None"})
            if cnt > 1:
                return json.dumps({"error":f"old_str found {cnt} times, must be unique"})
            new_content = content.replace(old_s, new_s, 1)
            with open(path,'w',encoding='utf-8') as f: f.write(new_content)
            added, removed = self._diff_stats(old_s, new_s)
            fn = os.path.basename(path)
            self.file_changes.append({"action":"edited","path":path,"filename":fn,"added":added,"removed":removed})
            return json.dumps({"success":True,"path":path,"filename":fn,
                "diff":f"{fn} +{added} -{removed}","added_lines":added,"removed_lines":removed,
                "description":params.get("description",f"Edit {fn}")})
        except Exception as e:
            return json.dumps({"error": f"Edit failed: {str(e)}"})

    async def _multi_edit(self, params: Dict) -> str:
        path = self._resolve(params["path"])
        edits = params.get("edits", [])
        if not edits: return json.dumps({"error": "No edits"})
        if not os.path.exists(path): return json.dumps({"error": f"File not found: {path}"})
        try:
            with open(path,'r',encoding='utf-8') as f: content = f.read()
            ta, tr, applied, errs = 0, 0, 0, []
            for i, e in enumerate(edits):
                os_s, ns_s = e["old_str"], e["new_str"]
                c = content.count(os_s)
                if c == 0: errs.append(f"Edit {i+1}: not found"); continue
                if c > 1: errs.append(f"Edit {i+1}: found {c} times"); continue
                content = content.replace(os_s, ns_s, 1)
                applied += 1
                a, r = self._diff_stats(os_s, ns_s)
                ta += a; tr += r
            if applied == 0: return json.dumps({"error":"No edits applied","errors":errs})
            with open(path,'w',encoding='utf-8') as f: f.write(content)
            fn = os.path.basename(path)
            self.file_changes.append({"action":"multi_edited","path":path,"filename":fn,"edits_applied":applied,"added":ta,"removed":tr})
            res = {"success":True,"path":path,"filename":fn,"edits_applied":applied,"edits_total":len(edits),
                "diff":f"{fn} +{ta} -{tr}","added_lines":ta,"removed_lines":tr}
            if errs: res["errors"] = errs
            return json.dumps(res)
        except Exception as e:
            return json.dumps({"error": f"Multi-edit failed: {str(e)}"})

    async def _list_dir(self, params: Dict) -> str:
        path = self._resolve(params.get("path", "."))
        depth = min(params.get("depth", 2), 5)
        if not os.path.isdir(path): return json.dumps({"error": f"Not a directory: {path}"})
        lines = []
        self._walk(path, lines, 0, depth)
        return f"📁 {path}\n" + "\n".join(lines) if lines else f"📁 {path}\n  (empty)"

    def _walk(self, p, lines, d, mx):
        if d >= mx: return
        try: items = sorted(os.listdir(p))
        except: return
        ind = "  "*(d+1)
        for item in items:
            if item in SKIP_DIRS or item.startswith('.'): continue
            fp = os.path.join(p, item)
            if os.path.isdir(fp):
                try: c = len([f for f in os.listdir(fp) if not f.startswith('.')])
                except: c = '?'
                lines.append(f"{ind}📁 {item}/ ({c} items)")
                self._walk(fp, lines, d+1, mx)
            else:
                lines.append(f"{ind}📄 {item} ({self._hsz(os.path.getsize(fp))})")

    async def _grep_search(self, params: Dict) -> str:
        pattern = params["pattern"]
        path = self._resolve(params.get("path", "."))
        cmd = ["grep","-rn","--max-count=50","--color=never"]
        if params.get("include"): cmd += ["--include", params["include"]]
        for s in SKIP_DIRS: cmd += [f"--exclude-dir={s}"]
        cmd += [pattern, path]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            r = out.decode('utf-8', errors='replace')
            if not r: return "(no matches)"
            mc = len(r.strip().split('\n'))
            if len(r) > 8000: r = r[:8000] + f"\n...[truncated, {mc} matches]"
            return json.dumps({"pattern":pattern,"matches":mc,"content":r})
        except asyncio.TimeoutError: return json.dumps({"error":"Search timed out"})
        except Exception as e: return json.dumps({"error":str(e)})

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
                    matches.append({"path":os.path.relpath(fp,self.work_dir),"abs_path":fp,"size":sz,"size_human":self._hsz(sz)})
                except: pass
                if len(matches) >= mx: break
            return json.dumps({"pattern":pattern,"matches":len(matches),"results":matches}, ensure_ascii=False)
        except asyncio.TimeoutError: return json.dumps({"error":"Search timed out"})
        except Exception as e: return json.dumps({"error":str(e)})

    async def _web_search(self, params: Dict) -> str:
        query = params["query"]
        logger.info(f"[web_search] {query}")
        try:
            from app.core.web_search import SerperSearchEngine
            engine = SerperSearchEngine()
            results = await engine.search(query, max_results=10)
            if not results: return json.dumps({"query":query,"results_count":0,"results":[]})
            if isinstance(results[0], dict) and "error" in results[0]:
                return json.dumps({"query":query,"error":results[0]["error"]})
            structured = [{"title":r.get("title",""),"url":r.get("link",r.get("url","")),"snippet":r.get("snippet",r.get("description","")),"domain":r.get("domain","")} for r in results]
            return json.dumps({"query":query,"results_count":len(structured),"results":structured}, ensure_ascii=False)
        except ImportError: return json.dumps({"query":query,"error":"Web search not available. Set SERPER_API_KEY."})
        except Exception as e: return json.dumps({"query":query,"error":str(e)})

    async def _web_fetch(self, params: Dict) -> str:
        url = params["url"]
        logger.info(f"[web_fetch] {url}")
        try:
            from app.core.web_search import WebBrowser
            browser = WebBrowser(max_content_length=15000)
            content = await browser.browse(url, clean=True)
            title = self._extract_title(content, url)
            return json.dumps({"url":url,"title":title,"content_length":len(content),"content":content}, ensure_ascii=False)
        except ImportError:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                    resp = await c.get(url, headers={"User-Agent":"Mozilla/5.0"})
                    text = resp.text
                    tm = re.search(r'<title[^>]*>(.*?)</title>', text, re.I|re.DOTALL)
                    title = tm.group(1).strip() if tm else url
                    for pat in [r'<script[^>]*>.*?</script>', r'<style[^>]*>.*?</style>', r'<[^>]+>']:
                        text = re.sub(pat, ' ', text, flags=re.DOTALL)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if len(text) > 15000: text = text[:15000] + "\n...[truncated]"
                    return json.dumps({"url":url,"title":title,"status":resp.status_code,"content_length":len(text),"content":text}, ensure_ascii=False)
            except Exception as e2: return json.dumps({"url":url,"error":str(e2)})
        except Exception as e: return json.dumps({"url":url,"error":str(e)})

    async def _task_complete(self, params: Dict) -> str:
        return json.dumps({"completed":True,"summary":params.get("summary","Done"),
            "files_changed":params.get("files_changed",[]),
            "total_file_changes":len(self.file_changes),
            "file_change_log":self.file_changes[-20:]}, ensure_ascii=False)

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
        if idx >= 0: return content[max(0,idx-20):idx+window]
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


# =============================================================================
# Turn 汇总 (v3) + AgenticLoop 核心 + 工厂函数
# =============================================================================

def build_turn_summary(tool_uses: List[Dict]) -> Dict[str, Any]:
    """生成 turn 汇总，含 detail_items 供前端折叠子项"""
    counts = {"bash":0,"read_file":0,"batch_read":0,"write_file":0,"edit_file":0,
              "multi_edit":0,"list_dir":0,"grep_search":0,"file_search":0,
              "web_search":0,"web_fetch":0,"task_complete":0}
    detail_items = []
    for tu in tool_uses:
        name = tu.get("name","")
        inp = tu.get("input", {})
        desc = inp.get("description","")
        if name in counts: counts[name] += 1
        icon_map = {"bash":"terminal","read_file":"file-text","batch_read":"files",
            "write_file":"file-plus","edit_file":"pencil","multi_edit":"pencil-ruler",
            "list_dir":"folder-open","grep_search":"search","file_search":"file-search",
            "web_search":"globe","web_fetch":"download","task_complete":"check-circle"}
        item = {"tool": name, "icon": icon_map.get(name, "zap")}
        if desc:
            item["title"] = desc
        else:
            item["title"] = _auto_title(name, inp)
        detail_items.append(item)

    vc = counts["read_file"]+counts["batch_read"]
    ec = counts["edit_file"]+counts["multi_edit"]
    sc = counts["list_dir"]+counts["grep_search"]+counts["file_search"]

    parts = []
    if counts["bash"]:
        n=counts["bash"]; parts.append(f"Ran {n} command{'s' if n>1 else ''}")
    if vc:
        n=vc; parts.append(f"viewed {n} file{'s' if n>1 else ''}")
    if counts["write_file"]:
        n=counts["write_file"]; parts.append(f"created {n} file{'s' if n>1 else ''}")
    if ec:
        n=ec; parts.append(f"edited {'a file' if n==1 else f'{n} files'}")
    if sc:
        n=sc; parts.append(f"searched {n} path{'s' if n>1 else ''}")
    if counts["web_search"]: parts.append("searched the web")
    if counts["web_fetch"]:
        n=counts["web_fetch"]; parts.append(f"fetched {n} page{'s' if n>1 else ''}")
    if counts["task_complete"]: parts.append("completed task")

    display = ", ".join(parts) if parts else "Done"
    if display: display = display[0].upper() + display[1:]

    return {"commands_run":counts["bash"],"files_viewed":vc,"files_edited":ec,
        "files_created":counts["write_file"],"searches_code":sc,
        "searches_web":counts["web_search"],"pages_fetched":counts["web_fetch"],
        "task_completed":counts["task_complete"]>0,"display":display,
        "detail_items":detail_items,"tool_count":len(tool_uses)}


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
        u=inp.get("url",""); return f"Fetch: {u[:60]}{'...' if len(u)>60 else ''}"
    elif name == "task_complete": return "Task completed"
    return name


class AgenticLoop:
    """Agentic Loop v3 - 事件: start, text, tool_start, tool_result, file_change, turn, progress, done, error"""
    DEFAULT_MODEL = "claude-opus-4-6"

    def __init__(self, ai_engine, work_dir: str, model: str=None, max_turns: int=30, system_prompt: str=None):
        self.ai_engine = ai_engine
        self.work_dir = os.path.abspath(work_dir)
        self.model = model or self.DEFAULT_MODEL
        self.max_turns = max_turns
        self.system_prompt = system_prompt or AGENTIC_SYSTEM_PROMPT
        self.executor = ToolExecutor(self.work_dir)
        self.turn_count = 0
        self.total_tool_calls = 0
        self.events: List[Dict] = []
        os.makedirs(self.work_dir, exist_ok=True)

    async def run(self, task: str) -> AsyncGenerator[Dict[str, Any], None]:
        start_time = datetime.now()
        messages = [{"role": "user", "content": task}]

        yield {"type":"start","task":task[:500],"model":self.model,
            "work_dir":self.work_dir,"max_turns":self.max_turns,
            "timestamp":datetime.now().isoformat()}

        for turn in range(1, self.max_turns+1):
            self.turn_count = turn
            logger.info(f"[AgenticLoop] Turn {turn}/{self.max_turns}")

            yield {"type":"progress","turn":turn,"max_turns":self.max_turns,
                "total_tool_calls":self.total_tool_calls,
                "elapsed":(datetime.now()-start_time).total_seconds()}

            # -- 调用 AI --
            try:
                result = await self.ai_engine.get_completion(
                    messages=messages, model=self.model, system_prompt=self.system_prompt,
                    tools=TOOL_DEFINITIONS, temperature=0.3, max_tokens=8192)
            except Exception as e:
                logger.error(f"[AgenticLoop] AI call failed: {e}")
                yield {"type":"error","message":f"AI call failed: {str(e)}","turn":turn}
                return

            content_blocks = result.get("content_blocks", [])
            tool_uses = result.get("tool_uses", [])
            stop_reason = result.get("stop_reason", "end_turn")

            if not content_blocks and result.get("content"):
                content_blocks = [{"type":"text","text":result["content"]}]

            # yield text + tool_start 事件
            for block in content_blocks:
                if block.get("type") == "text" and block.get("text"):
                    yield {"type":"text","content":block["text"],"turn":turn}
                elif block.get("type") == "tool_use":
                    tinp = block.get("input", {})
                    desc = tinp.get("description", _auto_title(block["name"], tinp))
                    yield {"type":"tool_start","tool":block["name"],"args":tinp,
                        "tool_use_id":block["id"],"description":desc,"turn":turn}

            messages.append({"role":"assistant","content":content_blocks})

            # -- 判断结束 --
            if not tool_uses:
                dur = (datetime.now()-start_time).total_seconds()
                yield {"type":"done","turns":turn,"total_tool_calls":self.total_tool_calls,
                    "duration":dur,"stop_reason":stop_reason,"work_dir":self.work_dir,
                    "file_changes":self.executor.file_changes[-20:]}
                return

            # -- 执行工具 --
            tool_results = []
            fc_before = len(self.executor.file_changes)

            for tu in tool_uses:
                tn, ti, tid = tu["name"], tu["input"], tu["id"]
                self.total_tool_calls += 1
                logger.info(f"[AgenticLoop] Exec: {tn} (id={tid})")

                rs = await self.executor.execute(tn, ti)
                if len(rs) > 15000: rs = rs[:15000] + "\n...[truncated]"

                meta = self._extract_meta(tn, rs)

                yield {"type":"tool_result","tool":tn,"tool_use_id":tid,
                    "result":rs[:3000],"result_meta":meta,
                    "success":"error" not in rs.lower()[:50],"turn":turn}

                tool_results.append({"type":"tool_result","tool_use_id":tid,"content":rs})

            # file_change 事件
            for ch in self.executor.file_changes[fc_before:]:
                yield {"type":"file_change","action":ch.get("action",""),
                    "path":ch.get("path",""),"filename":ch.get("filename",""),
                    "added":ch.get("added",0),"removed":ch.get("removed",0),"turn":turn}

            messages.append({"role":"user","content":tool_results})

            # turn 汇总
            summary = build_turn_summary(tool_uses)
            yield {"type":"turn","turn":turn,"tool_calls_this_turn":len(tool_uses),
                "total_tool_calls":self.total_tool_calls,"summary":summary,
                "display":summary["display"],"detail_items":summary["detail_items"]}

        # max turns
        dur = (datetime.now()-start_time).total_seconds()
        yield {"type":"error","message":f"Reached max turns ({self.max_turns}).",
            "turns":self.max_turns,"total_tool_calls":self.total_tool_calls,
            "duration":dur,"file_changes":self.executor.file_changes[-20:]}

    def _extract_meta(self, tool_name: str, result_str: str) -> Dict[str, Any]:
        """提取结构化元数据供前端渲染"""
        meta = {}
        try:
            d = json.loads(result_str)
            if tool_name == "read_file":
                meta["truncated"] = d.get("truncated",False)
                meta["filename"] = d.get("filename","")
                meta["total_lines"] = d.get("total_lines",0)
                if d.get("truncated"):
                    meta["truncated_range"] = d.get("truncated_range","")
                    meta["hint"] = d.get("hint","")
            elif tool_name == "batch_read":
                meta["files_read"] = d.get("files_read",0)
                meta["files_errored"] = d.get("files_errored",0)
            elif tool_name in ("edit_file","multi_edit"):
                meta["diff"] = d.get("diff","")
                meta["filename"] = d.get("filename","")
                meta["added_lines"] = d.get("added_lines",0)
                meta["removed_lines"] = d.get("removed_lines",0)
            elif tool_name == "write_file":
                meta["filename"] = d.get("filename","")
                meta["lines"] = d.get("lines",0)
                meta["action"] = d.get("action","created")
            elif tool_name == "web_search":
                meta["results_count"] = d.get("results_count",0)
                meta["query"] = d.get("query","")
                meta["result_titles"] = [{"title":r.get("title",""),"url":r.get("url",""),"domain":r.get("domain","")} for r in d.get("results",[])[:10]]
            elif tool_name == "web_fetch":
                meta["title"] = d.get("title","")
                meta["url"] = d.get("url","")
                meta["content_length"] = d.get("content_length",0)
            elif tool_name == "file_search":
                meta["matches"] = d.get("matches",0)
                meta["pattern"] = d.get("pattern","")
            elif tool_name == "grep_search":
                meta["matches"] = d.get("matches",0)
            elif tool_name == "bash":
                meta["exit_code"] = d.get("exit_code",-1)
            elif tool_name == "task_complete":
                meta["completed"] = True
                meta["summary"] = d.get("summary","")
        except: pass
        return meta

    async def run_sync(self, task: str) -> Dict[str, Any]:
        """同步模式：收集所有事件返回最终结果"""
        events = []
        texts = []
        async for ev in self.run(task):
            events.append(ev)
            if ev["type"] == "text": texts.append(ev["content"])
        last = events[-1] if events else {"type":"error","message":"No events"}
        return {"success":last.get("type")=="done","turns":last.get("turns",0),
            "total_tool_calls":last.get("total_tool_calls",0),
            "duration":last.get("duration",0),"final_text":"\n".join(texts),
            "events":events,"work_dir":self.work_dir,
            "file_changes":self.executor.file_changes}


def create_agentic_loop(ai_engine, user_id: str, project_id: str=None,
    base_workspace: str=None, model: str=None, max_turns: int=30, system_prompt: str=None
) -> AgenticLoop:
    """工厂函数：创建 AgenticLoop"""
    from app.config import settings
    base = base_workspace or getattr(settings, 'WORKSPACE_PATH', './workspace')
    project_id = project_id or f"task_{uuid.uuid4().hex[:12]}"
    work_dir = os.path.join(base, str(user_id), str(project_id))
    return AgenticLoop(ai_engine=ai_engine, work_dir=work_dir,
        model=model or AgenticLoop.DEFAULT_MODEL, max_turns=max_turns, system_prompt=system_prompt)