#!/usr/bin/env python3
"""
TDD Sprint 3: Bedrock tool_result content format validation
============================================================
Root cause: AWS Bedrock (via tryallai.com proxy) requires tool_result.content
to be a list of content blocks, NOT a plain string. The direct Anthropic API
accepts both formats, but Bedrock returns:

    ValidationException: ***.***.content: Input should be a valid list

These tests validate:
1. _make_tool_result() helper produces correct list format
2. ClaudeCompatibleProvider._normalize_for_bedrock() catches stale string formats
3. context_manager._truncate_message() preserves list format for tool_result
4. End-to-end message construction in agentic_loop produces valid messages

All tests should FAIL before the fix and PASS after.
"""

import pytest
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ============================================================================
# Test 1: _make_tool_result produces list-format content
# ============================================================================
class TestMakeToolResult:
    def test_content_is_list(self):
        """tool_result content MUST be a list, never a string"""
        from app.core.agents.agentic_loop import _make_tool_result
        result = _make_tool_result("toolu_abc123", "file created successfully")
        assert isinstance(result["content"], list), \
            f"content should be list, got {type(result['content'])}"

    def test_content_block_structure(self):
        """Each item in content list must be {type: text, text: ...}"""
        from app.core.agents.agentic_loop import _make_tool_result
        result = _make_tool_result("toolu_abc123", '{"ok": true}')
        block = result["content"][0]
        assert block["type"] == "text"
        assert block["text"] == '{"ok": true}'

    def test_preserves_tool_use_id(self):
        """tool_use_id must be passed through unchanged"""
        from app.core.agents.agentic_loop import _make_tool_result
        result = _make_tool_result("toolu_xyz789", "output")
        assert result["tool_use_id"] == "toolu_xyz789"
        assert result["type"] == "tool_result"

    def test_empty_string_content(self):
        """Empty string content should still produce a valid list block"""
        from app.core.agents.agentic_loop import _make_tool_result
        result = _make_tool_result("toolu_empty", "")
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 1
        assert result["content"][0]["text"] == ""

    def test_large_content(self):
        """Large content strings should be preserved in the list format"""
        from app.core.agents.agentic_loop import _make_tool_result
        big = "x" * 20000
        result = _make_tool_result("toolu_big", big)
        assert result["content"][0]["text"] == big

    def test_content_with_json(self):
        """JSON content should not be parsed, just wrapped as text"""
        from app.core.agents.agentic_loop import _make_tool_result
        json_str = json.dumps({"files": ["a.py", "b.py"], "count": 2})
        result = _make_tool_result("toolu_json", json_str)
        assert result["content"][0]["text"] == json_str

    def test_content_with_unicode(self):
        """Unicode content must be preserved"""
        from app.core.agents.agentic_loop import _make_tool_result
        result = _make_tool_result("toolu_uni", "文件创建成功 ✓")
        assert result["content"][0]["text"] == "文件创建成功 ✓"

    def test_content_with_newlines(self):
        """Multi-line content must be preserved as single text block"""
        from app.core.agents.agentic_loop import _make_tool_result
        multiline = "line1\nline2\nline3"
        result = _make_tool_result("toolu_ml", multiline)
        assert result["content"][0]["text"] == multiline

    def test_content_with_error_message(self):
        """Error messages should also use list format"""
        from app.core.agents.agentic_loop import _make_tool_result
        err = '{"error": "File not found: /foo/bar.py"}'
        result = _make_tool_result("toolu_err", err)
        assert isinstance(result["content"], list)
        assert result["content"][0]["text"] == err

    def test_result_is_valid_bedrock_schema(self):
        """Full schema check: the result should be accepted by Bedrock"""
        from app.core.agents.agentic_loop import _make_tool_result
        result = _make_tool_result("toolu_schema", "ok")
        # Required fields for Bedrock tool_result
        assert "type" in result
        assert result["type"] == "tool_result"
        assert "tool_use_id" in result
        assert "content" in result
        assert isinstance(result["content"], list)
        for block in result["content"]:
            assert isinstance(block, dict)
            assert "type" in block
            assert block["type"] in ("text", "image")


# ============================================================================
# Test 2: _normalize_for_bedrock catches string content in tool_result
# ============================================================================
class TestNormalizeForBedrock:
    @staticmethod
    def _get_normalizer():
        from app.core.ai_engine import ClaudeCompatibleProvider
        return ClaudeCompatibleProvider._normalize_for_bedrock

    def test_string_tool_result_content_converted(self):
        """tool_result with string content → converted to list"""
        normalize = self._get_normalizer()
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "hello"}
            ]}
        ]
        result = normalize(messages)
        inner = result[0]["content"][0]["content"]
        assert isinstance(inner, list), f"Expected list, got {type(inner)}"
        assert inner[0]["type"] == "text"
        assert inner[0]["text"] == "hello"

    def test_list_tool_result_content_preserved(self):
        """tool_result with list content → left unchanged"""
        normalize = self._get_normalizer()
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": [{"type": "text", "text": "hello"}]}
            ]}
        ]
        result = normalize(messages)
        inner = result[0]["content"][0]["content"]
        assert isinstance(inner, list)
        assert inner[0]["text"] == "hello"

    def test_none_tool_result_content_filled(self):
        """tool_result with None content → filled with empty text block"""
        normalize = self._get_normalizer()
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": None}
            ]}
        ]
        result = normalize(messages)
        inner = result[0]["content"][0]["content"]
        assert isinstance(inner, list)
        assert len(inner) == 1

    def test_plain_string_message_preserved(self):
        """Regular string-content messages stay as strings"""
        normalize = self._get_normalizer()
        messages = [{"role": "user", "content": "hello world"}]
        result = normalize(messages)
        assert result[0]["content"] == "hello world"

    def test_empty_string_message_filled(self):
        """Empty string content → filled with placeholder"""
        normalize = self._get_normalizer()
        messages = [{"role": "assistant", "content": ""}]
        result = normalize(messages)
        assert result[0]["content"] != ""

    def test_empty_content_list_filled(self):
        """Empty content list → filled with placeholder block"""
        normalize = self._get_normalizer()
        messages = [{"role": "assistant", "content": []}]
        result = normalize(messages)
        assert len(result[0]["content"]) > 0

    def test_mixed_blocks_preserved(self):
        """Messages with mixed text + tool_use blocks are preserved"""
        normalize = self._get_normalizer()
        messages = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "I'll do that"},
                {"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "ls"}}
            ]}
        ]
        result = normalize(messages)
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0]["type"] == "text"
        assert result[0]["content"][1]["type"] == "tool_use"

    def test_none_content_handled(self):
        """Message with None content → filled"""
        normalize = self._get_normalizer()
        messages = [{"role": "assistant", "content": None}]
        result = normalize(messages)
        assert result[0]["content"] is not None

    def test_multiple_tool_results_all_fixed(self):
        """Multiple tool_result blocks in one message all get fixed"""
        normalize = self._get_normalizer()
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "result1"},
                {"type": "tool_result", "tool_use_id": "t2", "content": "result2"},
            ]}
        ]
        result = normalize(messages)
        for block in result[0]["content"]:
            assert isinstance(block["content"], list), \
                f"tool_result {block['tool_use_id']} content should be list"

    def test_raw_string_in_list_wrapped(self):
        """Defensive: raw string somehow in content list → wrapped in text block"""
        normalize = self._get_normalizer()
        messages = [
            {"role": "user", "content": ["raw string accidentally"]}
        ]
        result = normalize(messages)
        assert result[0]["content"][0]["type"] == "text"


# ============================================================================
# Test 3: context_manager _truncate_message preserves tool_result list format
# ============================================================================
class TestContextManagerTruncation:
    @staticmethod
    def _get_cm():
        from app.core.agents.context_manager import ContextManager
        return ContextManager(max_tokens=100000)

    def test_truncate_tool_result_string_to_list(self):
        """Legacy string tool_result content → converted to list after truncation"""
        cm = self._get_cm()
        msg = {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "x" * 5000}
            ]
        }
        result = cm._truncate_message(msg, max_content=100)
        inner = result["content"][0]["content"]
        assert isinstance(inner, list), \
            f"truncated tool_result content should be list, got {type(inner)}"

    def test_truncate_tool_result_list_preserved(self):
        """List-format tool_result content → stays as list after truncation"""
        cm = self._get_cm()
        msg = {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": [{"type": "text", "text": "x" * 5000}]}
            ]
        }
        result = cm._truncate_message(msg, max_content=100)
        inner = result["content"][0]["content"]
        assert isinstance(inner, list)
        # The text should be truncated
        assert len(inner[0]["text"]) <= 200  # 100 + truncation marker

    def test_truncate_short_string_to_list(self):
        """Short string tool_result → still converted to list format"""
        cm = self._get_cm()
        msg = {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
            ]
        }
        result = cm._truncate_message(msg, max_content=1000)
        inner = result["content"][0]["content"]
        assert isinstance(inner, list), \
            f"Even short tool_result content should be list, got {type(inner)}"

    def test_truncate_text_block_preserved(self):
        """text blocks should still be truncated normally"""
        cm = self._get_cm()
        msg = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "a" * 5000}
            ]
        }
        result = cm._truncate_message(msg, max_content=100)
        assert len(result["content"][0]["text"]) <= 200

    def test_truncate_mixed_blocks(self):
        """Mixed tool_use + tool_result: tool_use untouched, tool_result fixed"""
        cm = self._get_cm()
        msg = {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "big " * 2000},
                {"type": "tool_result", "tool_use_id": "t2",
                 "content": [{"type": "text", "text": "small"}]},
            ]
        }
        result = cm._truncate_message(msg, max_content=100)
        for block in result["content"]:
            if block["type"] == "tool_result":
                assert isinstance(block["content"], list), \
                    f"tool_result {block['tool_use_id']} content should be list"


# ============================================================================
# Test 4: End-to-end message chain simulation
# ============================================================================
class TestEndToEndMessageChain:
    """Simulate the exact Turn 1 → Turn 2 flow that triggered the Bedrock 400"""

    def test_turn2_messages_have_list_content(self):
        """After Turn 1 tool execution, Turn 2 messages must have list-format tool_result"""
        from app.core.agents.agentic_loop import _make_tool_result

        # Simulate Turn 1 response
        assistant_blocks = [
            {"type": "text", "text": "I'll list the directory."},
            {"type": "tool_use", "id": "toolu_001", "name": "bash",
             "input": {"command": "ls"}}
        ]

        # Simulate tool execution result
        tool_output = json.dumps({"exit_code": 0, "stdout": "file1.py\nfile2.py"})
        tool_result = _make_tool_result("toolu_001", tool_output)

        # Build messages for Turn 2
        messages = [
            {"role": "user", "content": "List the project files"},
            {"role": "assistant", "content": assistant_blocks},
            {"role": "user", "content": [tool_result]},
        ]

        # Validate the tool_result message
        user_msg = messages[2]
        assert isinstance(user_msg["content"], list)
        for block in user_msg["content"]:
            if block.get("type") == "tool_result":
                assert isinstance(block["content"], list), \
                    "tool_result.content must be a list for Bedrock"

    def test_multiple_tool_results_in_turn(self):
        """Turn with multiple tool calls: all results must be list format"""
        from app.core.agents.agentic_loop import _make_tool_result

        results = [
            _make_tool_result("t1", "output1"),
            _make_tool_result("t2", "output2"),
            _make_tool_result("t3", json.dumps({"error": "not found"})),
        ]

        for r in results:
            assert isinstance(r["content"], list)
            assert r["content"][0]["type"] == "text"

    def test_normalize_catches_legacy_format(self):
        """If somehow a legacy string-format tool_result slips through,
        _normalize_for_bedrock catches it before API call"""
        from app.core.ai_engine import ClaudeCompatibleProvider
        normalize = ClaudeCompatibleProvider._normalize_for_bedrock

        # Simulate legacy format that might come from context compaction
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "checking..."},
                {"type": "tool_use", "id": "t1", "name": "bash",
                 "input": {"command": "ls"}}
            ]},
            {"role": "user", "content": [
                # BUG: string content instead of list
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "file1.py\nfile2.py"}
            ]},
        ]

        fixed = normalize(messages)

        # The tool_result should now have list content
        tool_result_msg = fixed[2]
        tool_result_block = tool_result_msg["content"][0]
        assert isinstance(tool_result_block["content"], list), \
            "normalize should fix string content to list"


# ============================================================================
# Test 5: Regression guard — ensure no other message types are broken
# ============================================================================
class TestNoRegressions:
    def test_system_message_not_in_output(self):
        """System messages should be extracted, not forwarded as claude_messages"""
        from app.core.ai_engine import ClaudeCompatibleProvider
        normalize = ClaudeCompatibleProvider._normalize_for_bedrock
        # This tests the normalizer doesn't break system message handling
        messages = [
            {"role": "user", "content": "test"},
            {"role": "assistant", "content": "ok"},
        ]
        result = normalize(messages)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_thinking_blocks_stripped(self):
        """thinking blocks must be stripped — Bedrock rejects them in requests"""
        from app.core.ai_engine import ClaudeCompatibleProvider
        normalize = ClaudeCompatibleProvider._normalize_for_bedrock
        messages = [
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "let me think..."},
                {"type": "text", "text": "Here's my answer"},
            ]}
        ]
        result = normalize(messages)
        types = [b["type"] for b in result[0]["content"]]
        assert "thinking" not in types, "thinking blocks must be stripped for Bedrock"
        assert "text" in types, "text blocks must be preserved"

    def test_thinking_only_message_not_empty(self):
        """If assistant has ONLY thinking blocks, result should not be empty"""
        from app.core.ai_engine import ClaudeCompatibleProvider
        normalize = ClaudeCompatibleProvider._normalize_for_bedrock
        messages = [
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "let me think..."},
            ]}
        ]
        result = normalize(messages)
        assert len(result[0]["content"]) > 0, "Must not produce empty content array"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
