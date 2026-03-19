"""TDD tests for Sprint 1: SSE Protocol Alignment with Claude API format.

TEST-DRIVEN DEVELOPMENT. No mock implementations.
Tests verify event_stream.py emits events matching the Claude API event stream format
as reverse-engineered from eventStream1-4.txt:

  event: message_start
  event: content_block_start  (thinking / text / tool_use)
  event: content_block_delta  (thinking_delta / text_delta / input_json_delta / tool_use_block_update_delta)
  event: content_block_stop
  event: message_delta
  event: message_stop
"""

import json
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.core.agents.event_stream import EventBuilder, EventType, format_sse


class TestMessageStartEvent:
    """Test 1: message_start event matches Claude API format."""

    def test_01_message_start_has_required_fields(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.message_start(message_id="msg_abc123", model="claude-opus-4-6")
        assert ev["type"] == "message_start"
        assert "message" in ev
        msg = ev["message"]
        assert msg["id"] == "msg_abc123"
        assert msg["model"] == "claude-opus-4-6"
        assert msg["role"] == "assistant"
        assert msg["content"] == []
        assert msg["stop_reason"] is None

    def test_02_message_start_sse_format(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.message_start(message_id="msg_abc123", model="claude-opus-4-6")
        sse = format_sse(ev)
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        parsed = json.loads(sse.replace("data: ", "").strip())
        assert parsed["type"] == "message_start"


class TestContentBlockStart:
    """Test 3-5: content_block_start for thinking/text/tool_use."""

    def test_03_content_block_start_thinking(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.content_block_start(index=0, block_type="thinking")
        assert ev["type"] == "content_block_start"
        assert ev["index"] == 0
        cb = ev["content_block"]
        assert cb["type"] == "thinking"
        assert cb["thinking"] == ""

    def test_04_content_block_start_text(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.content_block_start(index=1, block_type="text")
        assert ev["type"] == "content_block_start"
        assert ev["index"] == 1
        cb = ev["content_block"]
        assert cb["type"] == "text"
        assert cb["text"] == ""

    def test_05_content_block_start_tool_use(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.content_block_start(
            index=1, block_type="tool_use",
            tool_id="toolu_abc", tool_name="bash_tool",
            message="Running command"
        )
        assert ev["type"] == "content_block_start"
        cb = ev["content_block"]
        assert cb["type"] == "tool_use"
        assert cb["id"] == "toolu_abc"
        assert cb["name"] == "bash_tool"
        assert cb["input"] == {}
        assert cb["message"] == "Running command"


class TestContentBlockDelta:
    """Test 6-8: content_block_delta for different delta types."""

    def test_06_thinking_delta(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.content_block_delta(index=0, delta_type="thinking_delta", thinking="Let me fix")
        assert ev["type"] == "content_block_delta"
        assert ev["index"] == 0
        assert ev["delta"]["type"] == "thinking_delta"
        assert ev["delta"]["thinking"] == "Let me fix"

    def test_07_text_delta(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.content_block_delta(index=1, delta_type="text_delta", text="Here is the result")
        assert ev["type"] == "content_block_delta"
        assert ev["delta"]["type"] == "text_delta"
        assert ev["delta"]["text"] == "Here is the result"

    def test_08_input_json_delta(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.content_block_delta(index=1, delta_type="input_json_delta", partial_json='{"command":')
        assert ev["type"] == "content_block_delta"
        assert ev["delta"]["type"] == "input_json_delta"
        assert ev["delta"]["partial_json"] == '{"command":'

    def test_09_tool_use_block_update_delta(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.content_block_delta(
            index=1, delta_type="tool_use_block_update_delta",
            message="Running pytest tests"
        )
        assert ev["type"] == "content_block_delta"
        assert ev["delta"]["type"] == "tool_use_block_update_delta"
        assert ev["delta"]["message"] == "Running pytest tests"


class TestContentBlockStopAndMessageEvents:
    """Test 10: content_block_stop and message lifecycle events."""

    def test_10_content_block_stop(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.content_block_stop(index=0)
        assert ev["type"] == "content_block_stop"
        assert ev["index"] == 0
        assert "stop_timestamp" in ev

    def test_11_message_delta(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.message_delta(stop_reason="end_turn")
        assert ev["type"] == "message_delta"
        assert ev["delta"]["stop_reason"] == "end_turn"

    def test_12_message_stop(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.message_stop()
        assert ev["type"] == "message_stop"


class TestBackwardsCompatibility:
    """Verify existing v9 events still work after adding Claude API events."""

    def test_13_v9_start_still_works(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.start("test task", "claude-opus-4-6", "/work", 30)
        assert ev["type"] == "start"
        assert ev["task"] == "test task"

    def test_14_v9_tool_start_still_works(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.tool_start("bash", {"command": "ls"}, "tu-1", "List files", 1)
        assert ev["type"] == "tool_start"
        assert ev["tool"] == "bash"

    def test_15_v9_text_still_works(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.text("Hello world", 1)
        assert ev["type"] == "text"
        assert ev["content"] == "Hello world"

    def test_16_v9_done_still_works(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.done(5, 10, 30.5, "end_turn", "/work", [], 1000, 2000, 0.05)
        assert ev["type"] == "done"
        assert ev["turns"] == 5

    def test_17_format_sse_json_valid(self):
        eb = EventBuilder(session_id="sess-001")
        ev = eb.message_start("msg_1", "claude-opus-4-6")
        sse = format_sse(ev)
        # Must be valid JSON after stripping "data: " prefix
        data_line = sse.strip()
        assert data_line.startswith("data: ")
        parsed = json.loads(data_line[6:])
        assert isinstance(parsed, dict)
