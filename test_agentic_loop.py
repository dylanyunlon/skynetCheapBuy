#!/usr/bin/env python3
"""
Agentic Loop 集成测试（修复版）
================================
自动加载 CheapBuy 的 .env 配置，无论从哪个目录运行都可以。

使用方式:
    python3 test_agentic_integration.py
"""

import os
import sys
import json
import asyncio
import logging

# ============================================================================
# 关键：加载 CheapBuy 的环境配置
# ============================================================================
CHEAPBUY_DIR = "/root/dylan/CheapBuy"
SKYNET_DIR = "/root/dylan/skynetCheapBuy/skynetCheapBuy"

# 加载 .env 文件
env_file = os.path.join(CHEAPBUY_DIR, ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    print(f"✅ 加载 .env: {env_file}")
else:
    print(f"⚠️  未找到 .env: {env_file}")

# 添加模块路径（优先 skynetCheapBuy，回退 CheapBuy）
sys.path.insert(0, SKYNET_DIR)
sys.path.insert(1, CHEAPBUY_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


async def test_1_tool_executor():
    """测试 1: ToolExecutor 能正确执行工具"""
    print("\n" + "="*60)
    print("🧪 测试 1: ToolExecutor")
    print("="*60)

    from app.core.agents.agentic_loop import ToolExecutor
    import tempfile

    work_dir = tempfile.mkdtemp(prefix="agentic_test_")
    executor = ToolExecutor(work_dir)

    # write_file
    r = json.loads(await executor.execute("write_file", {
        "path": "hello.py",
        "content": "print('Hello from Agentic Loop!')\n"
    }))
    assert r["success"], f"write_file failed: {r}"
    print(f"  ✅ write_file: {r['path']} ({r['size']}B)")

    # read_file
    r = json.loads(await executor.execute("read_file", {"path": "hello.py"}))
    assert "Hello from Agentic Loop" in r["content"]
    print(f"  ✅ read_file: {r['lines']}")

    # bash
    r = json.loads(await executor.execute("bash", {"command": "python3 hello.py"}))
    assert r["exit_code"] == 0 and "Hello from Agentic Loop" in r["stdout"]
    print(f"  ✅ bash: {r['stdout'].strip()}")

    # edit_file
    r = json.loads(await executor.execute("edit_file", {
        "path": "hello.py",
        "old_str": "Hello from Agentic Loop!",
        "new_str": "Hello from EDITED Agentic Loop!"
    }))
    assert r["success"]
    r = json.loads(await executor.execute("bash", {"command": "python3 hello.py"}))
    assert "EDITED" in r["stdout"]
    print(f"  ✅ edit_file + verify: {r['stdout'].strip()}")

    # list_dir
    result = await executor.execute("list_dir", {"path": "."})
    assert "hello.py" in result
    print(f"  ✅ list_dir: found hello.py")

    # grep_search
    result = await executor.execute("grep_search", {"pattern": "EDITED", "path": "."})
    assert "EDITED" in result
    print(f"  ✅ grep_search: found pattern")

    print(f"\n  ✅ ToolExecutor 全部通过!")

    import shutil
    shutil.rmtree(work_dir, ignore_errors=True)


async def test_2_claude_provider_tools():
    """测试 2: ClaudeCompatibleProvider 支持 tools"""
    print("\n" + "="*60)
    print("🧪 测试 2: ClaudeCompatibleProvider with tools")
    print("="*60)

    from app.core.ai_engine import AIEngine

    ai_engine = AIEngine()

    tools = [{
        "name": "get_weather",
        "description": "Get current weather for a city",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"}
            },
            "required": ["city"]
        }
    }]

    messages = [{"role": "user", "content": "What's the weather in Beijing? Use the get_weather tool."}]

    print(f"  📡 Calling claude-opus-4-6 with tools...")

    result = await ai_engine.get_completion(
        messages=messages,
        model="claude-opus-4-6",
        tools=tools,
        temperature=0.1,
        max_tokens=1024
    )

    # 验证新增字段
    assert "content_blocks" in result, "Missing content_blocks"
    assert "tool_uses" in result, "Missing tool_uses"
    assert "stop_reason" in result, "Missing stop_reason"

    print(f"  ✅ content_blocks: {len(result['content_blocks'])} blocks")
    print(f"  ✅ tool_uses: {len(result['tool_uses'])} calls")
    print(f"  ✅ stop_reason: {result['stop_reason']}")

    if result['tool_uses']:
        tu = result['tool_uses'][0]
        print(f"  ✅ tool_use: name={tu['name']}, id={tu['id']}, input={tu['input']}")
    else:
        print(f"  ⚠️  AI didn't call tool (may happen), content: {result['content'][:200]}")

    # 向后兼容
    assert isinstance(result["content"], str)
    print(f"  ✅ backward compat: content is str, tool_calls is {result.get('tool_calls')}")

    print(f"\n  ✅ Provider 改造通过!")


async def test_3_agentic_loop():
    """测试 3: 完整 Agentic Loop"""
    print("\n" + "="*60)
    print("🧪 测试 3: 完整 Agentic Loop (AI 自主创建+执行代码)")
    print("="*60)

    from app.core.ai_engine import AIEngine
    from app.core.agents.agentic_loop import AgenticLoop
    import tempfile

    ai_engine = AIEngine()
    work_dir = tempfile.mkdtemp(prefix="agentic_loop_test_")

    loop = AgenticLoop(
        ai_engine=ai_engine,
        work_dir=work_dir,
        model="claude-opus-4-6",
        max_turns=15
    )

    task = (
        "Create a Python file called calc.py with functions add(a,b) and multiply(a,b). "
        "Then create test_calc.py that tests both functions using assert statements. "
        "Run the tests with python3 and verify they pass."
    )

    print(f"  📝 Task: {task[:80]}...")
    print(f"  📁 Work dir: {work_dir}")
    print()

    event_counts = {}

    async for event in loop.run(task):
        t = event["type"]
        event_counts[t] = event_counts.get(t, 0) + 1

        if t == "start":
            print(f"  🚀 Started (model={event['model']})")
        elif t == "text":
            text = event["content"][:150].replace('\n', ' ')
            print(f"  📝 [Turn {event.get('turn')}] {text}")
        elif t == "tool_start":
            args_str = json.dumps(event["args"], ensure_ascii=False)
            if len(args_str) > 100:
                args_str = args_str[:100] + "..."
            print(f"  🔧 [Turn {event.get('turn')}] {event['tool']}({args_str})")
        elif t == "tool_result":
            icon = "✅" if event.get("success") else "❌"
            preview = event.get("result", "")[:120].replace('\n', ' ')
            print(f"  {icon} [Turn {event.get('turn')}] → {preview}")
        elif t == "turn":
            print(f"  🔄 Turn {event['turn']} done ({event['tool_calls_this_turn']} tools, total: {event['total_tool_calls']})")
        elif t == "done":
            print(f"\n  ✅ DONE! {event['turns']} turns, {event['total_tool_calls']} tool calls, {event['duration']:.1f}s")
        elif t == "error":
            print(f"\n  ❌ Error: {event.get('message')}")

    print(f"\n  📊 Events: {event_counts}")

    # 验证文件创建
    calc_exists = os.path.exists(os.path.join(work_dir, "calc.py"))
    test_exists = os.path.exists(os.path.join(work_dir, "test_calc.py"))
    print(f"  📁 calc.py: {'✅' if calc_exists else '❌'}")
    print(f"  📁 test_calc.py: {'✅' if test_exists else '❌'}")

    if calc_exists:
        with open(os.path.join(work_dir, "calc.py")) as f:
            print(f"  📄 calc.py content:\n{f.read()}")

    assert calc_exists, "calc.py should exist"
    assert test_exists, "test_calc.py should exist"

    import shutil
    shutil.rmtree(work_dir, ignore_errors=True)


async def main():
    print("="*60)
    print("🔧 CheapBuy Agentic Loop 集成测试")
    print("="*60)

    # 测试 1: ToolExecutor（纯本地）
    await test_1_tool_executor()

    # 检查 API 配置
    try:
        from app.config import settings
        api_key = settings.OPENAI_API_KEY
        api_base = settings.OPENAI_API_BASE
        if not api_key:
            print("\n⚠️  OPENAI_API_KEY 为空，跳过测试 2-3")
            return
        print(f"\n📡 API: {api_base}")
        print(f"🔑 Key: {api_key[:8]}...{api_key[-4:]}")
    except Exception as e:
        print(f"\n❌ 配置加载失败: {e}")
        print("   检查 .env 文件是否存在且包含必要字段")
        return

    # 测试 2: Provider 改造
    await test_2_claude_provider_tools()

    # 测试 3: 完整 agentic loop
    await test_3_agentic_loop()

    print("\n" + "="*60)
    print("✅ 全部测试通过! Agentic Loop 改造成功!")
    print("="*60)
    print()
    print("下一步:")
    print("  1. 重启 CheapBuy: systemctl restart cheapbuy")
    print("  2. 测试 SSE 端点: curl -N POST /api/v2/agent/agentic-task")
    print("  3. 前端对接: useAgenticLoop hook")


if __name__ == "__main__":
    asyncio.run(main())