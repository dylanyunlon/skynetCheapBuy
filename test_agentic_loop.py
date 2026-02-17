#!/usr/bin/env python3
"""
CheapBuy Agentic Loop 原型 (已验证可用)
========================================

已确认的可用模型（tryallai.com 透传 tools）：
  ✅ claude-sonnet-4-5-20250929  (推荐，性价比最高)
  ✅ claude-haiku-4-5-20251001   (最快最便宜)
  ✅ claude-opus-4-6             (最强)
  ❌ claude-sonnet-4-20250514    (tools 被代理吞掉)
  ❌ claude-3-5-haiku-20241022   (tools 被代理吞掉)

使用：
    cd /root/dylan/CheapBuy
    python3 test_agentic_loop.py                      # 基础测试
    python3 test_agentic_loop.py --test multi          # 多步骤
    python3 test_agentic_loop.py --test debug          # 自动调试
    python3 test_agentic_loop.py --test interactive    # 交互模式
    python3 test_agentic_loop.py --model claude-opus-4-6 --test basic  # 指定模型
"""

import os, sys, json, asyncio, argparse, tempfile, logging
from typing import Dict, Any, List

sys.path.insert(0, '/root/dylan/CheapBuy')
try:
    from app.config import settings
    DEFAULT_API_KEY = settings.OPENAI_API_KEY
    DEFAULT_BASE_URL = settings.OPENAI_API_BASE
    print(f"✅ CheapBuy config loaded, base_url: {DEFAULT_BASE_URL}")
except Exception:
    DEFAULT_API_KEY = os.environ.get("API_KEY", "")
    DEFAULT_BASE_URL = os.environ.get("API_BASE_URL", "https://api.tryallai.com/v1")
    print("⚠️  Using env vars")

# 默认用已验证支持 tool_use 的模型
DEFAULT_MODEL = "claude-opus-4-6"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
import httpx


# =============================================================================
# 工具定义（Claude /v1/messages 原生格式）
# =============================================================================

TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command on the server. Use for running scripts, installing packages, file operations, checking system status, running tests, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read the content of a file. Supports optional line range for large files. Returns content with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (absolute or relative to work dir)"},
                "start_line": {"type": "integer", "description": "Start line (1-indexed, optional)"},
                "end_line": {"type": "integer", "description": "End line (inclusive, optional)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file with the given content. Automatically creates parent directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "Edit a file by replacing a specific unique string with another. The old_str must appear exactly once in the file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_str": {"type": "string", "description": "Exact string to replace (must be unique in file)"},
                "new_str": {"type": "string", "description": "Replacement string"}
            },
            "required": ["path", "old_str", "new_str"]
        }
    },
    {
        "name": "list_dir",
        "description": "List files and directories at the given path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (default: working dir)"}
            },
            "required": []
        }
    },
    {
        "name": "grep_search",
        "description": "Search for a pattern in files using grep. Returns matching lines with file paths and line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex supported)"},
                "path": {"type": "string", "description": "Directory or file to search in"},
                "include": {"type": "string", "description": "File pattern to include (e.g. '*.py')"}
            },
            "required": ["pattern"]
        }
    }
]


# =============================================================================
# 工具执行器
# =============================================================================

class ToolExecutor:
    def __init__(self, work_dir=None):
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="agentic_")
        os.makedirs(self.work_dir, exist_ok=True)
        print(f"📂 Work dir: {self.work_dir}")

    async def execute(self, name: str, inp: Dict) -> str:
        h = {"bash": self._bash, "read_file": self._read, "write_file": self._write,
             "edit_file": self._edit, "list_dir": self._ls, "grep_search": self._grep}
        try:
            return await h[name](inp)
        except KeyError:
            return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _bash(self, p):
        cmd = p["command"]
        logger.info(f"    $ {cmd}")
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=self.work_dir)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
            o = out.decode('utf-8', errors='replace')
            e = err.decode('utf-8', errors='replace')
            if len(o) > 8000: o = o[:8000] + "\n...[truncated]"
            if len(e) > 3000: e = e[:3000] + "\n...[truncated]"
            return json.dumps({"exit_code": proc.returncode, "stdout": o, "stderr": e})
        except asyncio.TimeoutError:
            return json.dumps({"error": "Command timed out (60s)"})

    async def _read(self, p):
        path = self._r(p["path"])
        if not os.path.exists(path): return json.dumps({"error": f"Not found: {path}"})
        with open(path, 'r', encoding='utf-8', errors='replace') as f: lines = f.readlines()
        t = len(lines); s = max(1, p.get("start_line", 1)); e = min(t, p.get("end_line", t))
        c = "".join(f"{i:4d} | {lines[i-1]}" for i in range(s, e + 1))
        return json.dumps({"path": path, "lines": f"{s}-{e}/{t}", "content": c})

    async def _write(self, p):
        path = self._r(p["path"])
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f: f.write(p["content"])
        return json.dumps({"success": True, "path": path, "bytes": len(p["content"])})

    async def _edit(self, p):
        path = self._r(p["path"])
        if not os.path.exists(path): return json.dumps({"error": f"Not found: {path}"})
        with open(path, 'r') as f: content = f.read()
        n = content.count(p["old_str"])
        if n == 0: return json.dumps({"error": "old_str not found in file"})
        if n > 1: return json.dumps({"error": f"old_str found {n} times, must be unique"})
        with open(path, 'w') as f: f.write(content.replace(p["old_str"], p["new_str"], 1))
        return json.dumps({"success": True, "path": path})

    async def _ls(self, p):
        path = self._r(p.get("path", "."))
        if not os.path.exists(path): return json.dumps({"error": f"Not found: {path}"})
        skip = {'__pycache__', '.git', 'node_modules', '.venv', 'venv'}
        lines = []
        for i in sorted(os.listdir(path)):
            if i in skip or i.startswith('.'): continue
            full = os.path.join(path, i)
            lines.append(f"  {i}/" if os.path.isdir(full) else f"  {i} ({os.path.getsize(full)}B)")
        return "\n".join(lines) or "(empty)"

    async def _grep(self, p):
        path = self._r(p.get("path", "."))
        cmd = ["grep", "-rn", "--max-count=30"]
        if p.get("include"): cmd += ["--include", p["include"]]
        cmd += [p["pattern"], path]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            r = out.decode('utf-8', errors='replace')
            return r[:5000] if r else "(no matches)"
        except:
            return "(search error)"

    def _r(self, path):
        return path if os.path.isabs(path) else os.path.join(self.work_dir, path)


# =============================================================================
# Agentic Loop（httpx → tryallai.com/v1/messages + tools）
# =============================================================================

class AgenticLoop:
    """
    核心 Agentic Loop
    
    调用链路：httpx POST → tryallai.com/v1/messages (Claude 原生格式 + tools)
    与你的 ClaudeCompatibleProvider 完全一致，只多了 tools 参数。
    """

    def __init__(self, api_key, base_url="https://api.tryallai.com/v1",
                 model="claude-opus-4-6", max_turns=30, work_dir=None):
        self.api_key = api_key
        base = base_url.rstrip('/')
        if base.endswith("/v1"): base = base[:-3]
        self.endpoint = f"{base}/v1/messages"
        self.model = model
        self.max_turns = max_turns
        self.executor = ToolExecutor(work_dir)
        self.system = (
            "You are an expert software engineer assistant with access to tools.\n"
            "You can execute bash commands, read/write/edit files, list directories, and search code.\n\n"
            "When given a task:\n"
            "1. Understand what needs to be done\n"
            "2. Use tools to explore and implement step by step\n"
            "3. Verify your work by running tests or checking output\n"
            "4. Report the final results\n\n"
            "IMPORTANT: Always use tools to take action. Never just describe what you would do - actually do it using the tools."
        )

    async def _call_api(self, messages: List[Dict]) -> Dict:
        """调用 Claude /v1/messages（与 ClaudeCompatibleProvider 完全一致，多了 tools）"""
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "system": self.system,
            "tools": TOOLS,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "anthropic-version": "2023-06-01"
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(self.endpoint, json=body, headers=headers)
            if resp.status_code != 200:
                raise Exception(f"API {resp.status_code}: {resp.text[:300]}")
            return resp.json()

    async def run(self, task: str) -> Dict[str, Any]:
        """运行 Agentic Loop"""
        messages = [{"role": "user", "content": task}]
        events = []

        for turn in range(1, self.max_turns + 1):
            print(f"\n{'='*60}")
            print(f"🔄 Turn {turn}/{self.max_turns}")
            print(f"{'='*60}")

            # 1. 调用 API
            try:
                data = await self._call_api(messages)
            except Exception as e:
                print(f"❌ API error: {e}")
                events.append({"type": "error", "content": str(e)})
                break

            stop = data.get("stop_reason", "")
            blocks = data.get("content", [])
            usage = data.get("usage", {})
            tool_uses = []

            print(f"  stop_reason={stop}  tokens_in={usage.get('input_tokens',0)} tokens_out={usage.get('output_tokens',0)}")

            # 2. 解析 content blocks
            for b in blocks:
                if b["type"] == "text":
                    txt = b.get("text", "")
                    if txt:
                        display = txt[:200] + ('...' if len(txt) > 200 else '')
                        print(f"  📝 {display}")
                        events.append({"type": "text", "content": txt})
                elif b["type"] == "tool_use":
                    print(f"  🔧 {b['name']}({json.dumps(b['input'], ensure_ascii=False)[:80]})")
                    events.append({"type": "tool_start", "tool": b["name"], "args": b["input"], "id": b["id"]})
                    tool_uses.append(b)

            # 3. assistant message
            messages.append({"role": "assistant", "content": blocks})

            # 4. 没有工具调用 → 完成
            if not tool_uses:
                print(f"\n✅ 完成 (stop={stop})")
                break

            # 5. 执行所有工具
            results = []
            for tu in tool_uses:
                print(f"\n  ⚡ 执行 {tu['name']}...")
                r = await self.executor.execute(tu["name"], tu["input"])
                if len(r) > 12000: r = r[:12000] + "\n...[truncated]"
                display = r[:150] + ('...' if len(r) > 150 else '')
                print(f"  ✔ {display}")
                events.append({"type": "tool_result", "tool": tu["name"], "id": tu["id"], "result": r[:500]})
                results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": r})

            # 6. 工具结果回传
            messages.append({"role": "user", "content": results})

        final = "\n".join(e["content"] for e in events if e["type"] == "text")
        total_tools = sum(1 for e in events if e["type"] == "tool_start")
        return {"success": True, "turns": turn, "total_tool_calls": total_tools,
                "final_text": final, "events": events, "work_dir": self.executor.work_dir}


# =============================================================================
# 测试
# =============================================================================

async def test_basic(loop):
    print("\n🧪 TEST 1: 创建 Python 文件并执行")
    r = await loop.run(
        "Create a Python file called hello.py that prints 'Hello from CheapBuy Agentic Loop!', "
        "then run it and show me the output."
    )
    _show(r); return r

async def test_multi(loop):
    print("\n🧪 TEST 2: 创建计算器项目 + 单元测试")
    r = await loop.run(
        "Create a Python calculator project:\n"
        "1. calculator.py with add, subtract, multiply, divide functions\n"
        "2. test_calculator.py with unittest tests for each function\n"
        "3. Run the tests and show results\n"
        "4. List all files you created"
    )
    _show(r); return r

async def test_debug(loop):
    print("\n🧪 TEST 3: 自动调试循环")
    r = await loop.run(
        "Write a Python fibonacci function in fib.py that has an intentional off-by-one bug. "
        "Run it to see the wrong output, then fix the bug using edit_file, "
        "and verify that fib(10) returns 55."
    )
    _show(r); return r

def _show(r):
    print(f"\n{'─'*60}")
    print(f"📊 结果: {r['turns']} turns, {r['total_tool_calls']} tool calls")
    for e in r['events']:
        if e['type'] == 'tool_start':
            print(f"   🔧 {e['tool']}: {json.dumps(e.get('args', {}), ensure_ascii=False)[:60]}")
    print(f"\n📝 最终 AI 回复:\n{r['final_text'][:800]}")
    print(f"\n📂 工作目录: {r['work_dir']}")
    print(f"{'─'*60}")


async def main():
    pa = argparse.ArgumentParser(description="CheapBuy Agentic Loop 测试")
    pa.add_argument("--api-key", default=DEFAULT_API_KEY)
    pa.add_argument("--base-url", default=DEFAULT_BASE_URL)
    pa.add_argument("--model", default=DEFAULT_MODEL,
                    help="推荐: claude-opus-4-6, claude-haiku-4-5-20251001, claude-opus-4-6")
    pa.add_argument("--test", choices=["basic", "multi", "debug", "all", "interactive"], default="basic")
    pa.add_argument("--work-dir", default=None)
    a = pa.parse_args()

    if not a.api_key:
        print("❌ 需要 API key")
        sys.exit(1)

    print(f"\n🚀 CheapBuy Agentic Loop")
    print(f"   Endpoint: {a.base_url}")
    print(f"   Model: {a.model}")
    print(f"   Test: {a.test}")

    loop = AgenticLoop(a.api_key, a.base_url, a.model, work_dir=a.work_dir)

    if a.test == "basic":
        await test_basic(loop)
    elif a.test == "multi":
        await test_multi(loop)
    elif a.test == "debug":
        await test_debug(loop)
    elif a.test == "all":
        await test_basic(loop)
        await test_multi(loop)
        await test_debug(loop)
    elif a.test == "interactive":
        print("\n💬 交互模式 - 输入任务让 AI 用工具执行，'q' 退出")
        while True:
            try:
                t = input("\n👤 Task: ").strip()
                if t.lower() in ('q', 'quit', 'exit'): break
                if t: _show(await loop.run(t))
            except KeyboardInterrupt:
                break

    print("\n✅ Done")

if __name__ == "__main__":
    asyncio.run(main())