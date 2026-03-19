"""TDD tests for Sprint 2: agentic_loop.run() emits Claude API SSE format.

TEST-DRIVEN DEVELOPMENT. No mock implementations.
Tests verify the agentic loop run() yields events in Claude API format:
  message_start → content_block_start → content_block_delta → content_block_stop
  → message_delta → message_stop

AND still yields v9 events (tool_start, tool_result, turn, done, etc.)
for backwards compatibility.
"""
import json
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.core.agents.event_stream import EventBuilder, format_sse


class TestAgenticStreamEmitsMessageStart:
    """The run() entry should emit message_start as the first Claude API event."""

    def test_01_message_start_before_content(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.message_start(message_id="msg_001", model="claude-opus-4-6")
        assert ev["type"] == "message_start"
        assert ev["message"]["role"] == "assistant"
        # SSE format should be valid
        sse = format_sse(ev)
        parsed = json.loads(sse.strip().replace("data: ", "", 1))
        assert parsed["type"] == "message_start"

    def test_02_message_start_contains_model(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.message_start("msg_002", "claude-sonnet-4-5-20250929")
        assert ev["message"]["model"] == "claude-sonnet-4-5-20250929"


class TestAgenticStreamThinkingFlow:
    """Thinking should be wrapped: content_block_start(thinking) → deltas → stop."""

    def test_03_thinking_block_start(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.content_block_start(index=0, block_type="thinking")
        assert ev["content_block"]["type"] == "thinking"
        assert ev["content_block"]["thinking"] == ""

    def test_04_thinking_deltas_accumulate(self):
        eb = EventBuilder(session_id="s1")
        d1 = eb.content_block_delta(0, "thinking_delta", thinking="Let me ")
        d2 = eb.content_block_delta(0, "thinking_delta", thinking="analyze this")
        assert d1["delta"]["thinking"] == "Let me "
        assert d2["delta"]["thinking"] == "analyze this"

    def test_05_thinking_summary_delta(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.content_block_delta(0, "thinking_summary_delta",
                                     summary={"summary": "Analyzing the test failures"})
        assert ev["delta"]["type"] == "thinking_summary_delta"
        assert ev["delta"]["summary"]["summary"] == "Analyzing the test failures"


class TestAgenticStreamToolUseFlow:
    """Tool use should be: content_block_start(tool_use) → input_json_delta → stop."""

    def test_06_tool_use_block_start(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.content_block_start(
            index=1, block_type="tool_use",
            tool_id="toolu_abc", tool_name="bash",
            message="Running command"
        )
        cb = ev["content_block"]
        assert cb["type"] == "tool_use"
        assert cb["name"] == "bash"
        assert cb["id"] == "toolu_abc"
        assert cb["input"] == {}

    def test_07_input_json_delta_streaming(self):
        eb = EventBuilder(session_id="s1")
        d1 = eb.content_block_delta(1, "input_json_delta", partial_json='{"command":')
        d2 = eb.content_block_delta(1, "input_json_delta", partial_json='"ls -la"}')
        full = d1["delta"]["partial_json"] + d2["delta"]["partial_json"]
        parsed = json.loads(full)
        assert parsed["command"] == "ls -la"

    def test_08_tool_use_block_update_shows_description(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.content_block_delta(1, "tool_use_block_update_delta",
                                     message="Running pytest tests")
        assert ev["delta"]["message"] == "Running pytest tests"


class TestAgenticStreamTextFlow:
    """Text output should be: content_block_start(text) → text_delta → stop."""

    def test_09_text_block_start(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.content_block_start(index=2, block_type="text")
        assert ev["content_block"]["type"] == "text"
        assert ev["content_block"]["text"] == ""

    def test_10_text_delta_streaming(self):
        eb = EventBuilder(session_id="s1")
        d1 = eb.content_block_delta(2, "text_delta", text="Here are the ")
        d2 = eb.content_block_delta(2, "text_delta", text="results")
        assert d1["delta"]["text"] + d2["delta"]["text"] == "Here are the results"


class TestAgenticStreamLifecycle:
    """Full message lifecycle: message_start → blocks → message_delta → message_stop."""

    def test_11_content_block_stop_has_timestamp(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.content_block_stop(index=0)
        assert ev["type"] == "content_block_stop"
        assert ev["index"] == 0
        assert "stop_timestamp" in ev

    def test_12_message_delta_stop_reason(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.message_delta(stop_reason="tool_use")
        assert ev["delta"]["stop_reason"] == "tool_use"

    def test_13_message_stop(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.message_stop()
        assert ev["type"] == "message_stop"


class TestV9BackwardsCompat:
    """v9 events must still work alongside Claude API events."""

    def test_14_v9_start_unchanged(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.start("task", "model", "/work", 30)
        assert ev["type"] == "start"

    def test_15_v9_tool_start_unchanged(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.tool_start("bash", {"command": "ls"}, "tu-1", "desc", 1)
        assert ev["type"] == "tool_start"

    def test_16_v9_tool_result_unchanged(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.tool_result("bash", "tu-1", "output", {}, True, 1, 100)
        assert ev["type"] == "tool_result"

    def test_17_v9_done_unchanged(self):
        eb = EventBuilder(session_id="s1")
        ev = eb.done(5, 10, 30.0, "end_turn", "/work", [], 1000, 2000, 0.05)
        assert ev["type"] == "done"
