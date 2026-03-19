"""
Event Stream Parser — Parse Claude API SSE streams into structured blocks
=========================================================================
Parses raw Server-Sent Events in Claude API format:
  message_start → content_block_start → content_block_delta(s) →
  content_block_stop → message_delta → message_stop

Produces structured content blocks (thinking, text, tool_use) with
fully assembled JSON inputs for tool calls.

Also provides:
  - ToolCallExtractor: extract execution timeline from blocks
  - ToolNameMapper: map between Claude claude.ai tool names and backend names

位置: app/core/agents/event_stream_parser.py
"""

import json
import logging
from typing import Any, Dict, List, Optional
from collections import Counter

logger = logging.getLogger(__name__)


class EventStreamParser:
    """
    Incremental parser for Claude API SSE streams.

    Usage:
        parser = EventStreamParser()
        events = parser.feed(raw_sse_chunk)  # returns list of parsed event dicts
        blocks = parser.get_completed_blocks()  # returns assembled content blocks
    """

    def __init__(self):
        self._buffer: str = ''
        self._active_blocks: Dict[int, Dict[str, Any]] = {}  # index → block state
        self._completed_blocks: List[Dict[str, Any]] = []
        self._message_info: Dict[str, Any] = {}

    def reset(self):
        """Reset parser state for a new message stream."""
        self._buffer = ''
        self._active_blocks.clear()
        self._completed_blocks.clear()
        self._message_info.clear()

    def feed(self, raw: str) -> List[Dict[str, Any]]:
        """
        Feed raw SSE text (potentially partial) and return parsed event dicts.

        Events are only returned once their data line is complete (terminated by \\n\\n).
        Partial data is buffered for the next call.
        """
        self._buffer += raw
        # Normalize line endings
        self._buffer = self._buffer.replace('\r\n', '\n')

        events = []
        parts = self._buffer.split('\n\n')
        # Last part may be incomplete — keep in buffer
        self._buffer = parts.pop()

        for part in parts:
            if not part.strip():
                continue

            event_type = ''
            data_str = ''

            for line in part.split('\n'):
                line = line.strip()
                if line.startswith('event: '):
                    event_type = line[7:].strip()
                elif line.startswith('data: '):
                    data_str += line[6:]
                elif line.startswith('data:'):
                    data_str += line[5:]

            if not data_str:
                continue

            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                logger.warning(f"Skipping malformed JSON: {data_str[:100]}")
                continue

            events.append(data)
            self._process_event(data)

        return events

    def _process_event(self, data: Dict[str, Any]):
        """Process a parsed event and update internal block state."""
        evt_type = data.get('type', '')

        if evt_type == 'message_start':
            msg = data.get('message', {})
            self._message_info = {
                'id': msg.get('id', ''),
                'model': msg.get('model', ''),
                'role': msg.get('role', 'assistant'),
            }

        elif evt_type == 'content_block_start':
            idx = data.get('index', 0)
            cb = data.get('content_block', {})
            block_type = cb.get('type', '')

            block: Dict[str, Any] = {
                'type': block_type,
                'index': idx,
            }

            if block_type == 'thinking':
                block['content'] = cb.get('thinking', '')
                block['summary'] = None
            elif block_type == 'text':
                block['content'] = cb.get('text', '')
            elif block_type == 'tool_use':
                block['id'] = cb.get('id', '')
                block['name'] = cb.get('name', '')
                block['input'] = {}
                block['_json_parts'] = []
                block['message'] = cb.get('message', '')

            self._active_blocks[idx] = block

        elif evt_type == 'content_block_delta':
            idx = data.get('index', 0)
            delta = data.get('delta', {})
            delta_type = delta.get('type', '')

            block = self._active_blocks.get(idx)
            if block is None:
                return

            if delta_type == 'thinking_delta':
                block['content'] = block.get('content', '') + delta.get('thinking', '')

            elif delta_type == 'text_delta':
                block['content'] = block.get('content', '') + delta.get('text', '')

            elif delta_type == 'input_json_delta':
                if '_json_parts' in block:
                    block['_json_parts'].append(delta.get('partial_json', ''))

            elif delta_type == 'tool_use_block_update_delta':
                block['message'] = delta.get('message', block.get('message', ''))

            elif delta_type == 'thinking_summary_delta':
                summary = delta.get('summary', {})
                if isinstance(summary, dict):
                    block['summary'] = summary.get('summary', '')
                elif isinstance(summary, str):
                    block['summary'] = summary

        elif evt_type == 'content_block_stop':
            idx = data.get('index', 0)
            block = self._active_blocks.pop(idx, None)
            if block is None:
                return

            # Finalize tool_use JSON
            if block.get('type') == 'tool_use' and '_json_parts' in block:
                full_json = ''.join(block.pop('_json_parts'))
                if full_json:
                    try:
                        block['input'] = json.loads(full_json)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse tool JSON: {full_json[:200]}")
                        block['input'] = {'_raw': full_json}

            # Remove internal tracking fields
            block.pop('index', None)

            self._completed_blocks.append(block)

    def get_completed_blocks(self) -> List[Dict[str, Any]]:
        """Return all completed content blocks."""
        return list(self._completed_blocks)

    def get_message_info(self) -> Dict[str, Any]:
        """Return message-level info (id, model, role)."""
        return dict(self._message_info)


class ToolCallExtractor:
    """Extract execution timeline from completed content blocks."""

    @staticmethod
    def extract(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract tool_use blocks into a flat execution timeline.

        Each entry contains:
          - tool: tool name (e.g. 'bash_tool', 'str_replace')
          - tool_use_id: the original tool_use id
          - Plus all fields from input (command, path, description, etc.)
        """
        timeline = []
        for block in blocks:
            if block.get('type') != 'tool_use':
                continue

            entry: Dict[str, Any] = {
                'tool': block.get('name', ''),
                'tool_use_id': block.get('id', ''),
            }

            inp = block.get('input', {})
            # Flatten input fields into entry
            for k, v in inp.items():
                entry[k] = v

            timeline.append(entry)

        return timeline

    @staticmethod
    def summary(blocks: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Count tool calls by type.

        Returns dict like {'bash_tool': 5, 'str_replace': 3, 'total': 8}
        """
        counts: Counter = Counter()
        for block in blocks:
            if block.get('type') == 'tool_use':
                counts[block.get('name', 'unknown')] += 1

        result = dict(counts)
        result['total'] = sum(counts.values())
        return result


class ToolNameMapper:
    """
    Map tool names between Claude claude.ai format and our backend executor format.

    Claude claude.ai uses: bash_tool, str_replace, create_file, view, present_files
    Our backend uses: bash, edit_file, write_file, read_file, present_files
    """

    # Claude claude.ai name → backend executor name
    _TO_BACKEND = {
        'bash_tool': 'bash',
        'str_replace': 'edit_file',
        'create_file': 'write_file',
        'view': 'read_file',
        'present_files': 'present_files',
    }

    # Backend executor name → Claude claude.ai name
    _TO_FRONTEND = {v: k for k, v in _TO_BACKEND.items()}

    @classmethod
    def to_backend(cls, frontend_name: str) -> str:
        """Convert Claude claude.ai tool name to backend executor name."""
        return cls._TO_BACKEND.get(frontend_name, frontend_name)

    @classmethod
    def to_frontend(cls, backend_name: str) -> str:
        """Convert backend executor name to Claude claude.ai tool name."""
        return cls._TO_FRONTEND.get(backend_name, backend_name)

    @classmethod
    def transform_input(cls, frontend_name: str, frontend_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform tool input from Claude claude.ai format to backend format.

        For most tools the input is pass-through. Special cases:
        - str_replace: pass through as-is (our edit_file handles old_str/new_str)
        - create_file: rename file_text → content
        - view: rename to read_file compatible format
        """
        result = dict(frontend_input)

        if frontend_name == 'create_file':
            # Backend write_file expects 'content' instead of 'file_text'
            if 'file_text' in result and 'content' not in result:
                result['content'] = result.pop('file_text')

        return result
