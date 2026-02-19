"""
Context Manager — Context Window Management for Agentic Loop v7
================================================================
Implements Claude Code's context window strategy:
  - Accurate token estimation (tiktoken-compatible fallback)
  - Auto-compaction at 92% context usage (Claude Code wU2 threshold)
  - Smart summarization preserving critical context
  - Message priority ranking for what to keep vs summarize
  - Real-time context usage tracking for frontend display

Drop-in at: app/core/agents/context_manager.py
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Context window limits
MAX_CONTEXT_TOKENS = 180_000        # Claude 200k window, keep 20k buffer
COMPACT_THRESHOLD_PCT = 0.92        # Matches Claude Code wU2 compactor
COMPACT_THRESHOLD = int(MAX_CONTEXT_TOKENS * COMPACT_THRESHOLD_PCT)
TARGET_AFTER_COMPACT = int(MAX_CONTEXT_TOKENS * 0.60)  # Compact down to ~60%

# Token estimation calibration
CHARS_PER_TOKEN = 3.8  # Calibrated for code+English mix


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for a string.
    Uses a calibrated chars/token ratio that works well for code+English.
    More accurate than simple len/4.
    """
    if not text:
        return 0
    # Count different character types for better estimation
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
    # CJK and other multi-byte characters tend to be ~1 token each
    # ASCII text averages ~3.8 chars per token
    return int(ascii_chars / CHARS_PER_TOKEN) + non_ascii + 1


def estimate_block_tokens(block: Any) -> int:
    """Estimate tokens for a single content block"""
    if isinstance(block, str):
        return estimate_tokens(block)
    if isinstance(block, dict):
        block_type = block.get("type", "")
        if block_type == "text":
            return estimate_tokens(block.get("text", ""))
        elif block_type == "thinking":
            return estimate_tokens(block.get("thinking", ""))
        elif block_type == "tool_use":
            # Tool calls: name + input
            return (
                estimate_tokens(block.get("name", ""))
                + estimate_tokens(json.dumps(block.get("input", {})))
                + 20  # Overhead for tool_use structure
            )
        elif block_type == "tool_result":
            content = block.get("content", "")
            if isinstance(content, str):
                return estimate_tokens(content) + 10
            elif isinstance(content, list):
                return sum(estimate_block_tokens(b) for b in content) + 10
            return 10
    return 5  # Default overhead per block


def estimate_message_tokens(message: Dict) -> int:
    """Estimate tokens for a single message"""
    tokens = 4  # Message overhead (role, structure)
    content = message.get("content", "")
    if isinstance(content, str):
        tokens += estimate_tokens(content)
    elif isinstance(content, list):
        for block in content:
            tokens += estimate_block_tokens(block)
    return tokens


def estimate_messages_tokens(messages: List[Dict]) -> int:
    """Estimate total tokens for a message list"""
    return sum(estimate_message_tokens(msg) for msg in messages)


class MessagePriority:
    """
    Classify message importance for context compaction decisions.

    Priority levels (higher = keep longer):
    - CRITICAL (5): System prompt, first user message, latest turn
    - HIGH (4): Messages with file edits, important results
    - MEDIUM (3): Regular tool calls and results
    - LOW (2): Read-only tool results, verbose output
    - COMPACTABLE (1): Can be safely summarized
    """
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    COMPACTABLE = 1

    @staticmethod
    def classify(message: Dict, index: int, total: int) -> int:
        """Classify a message's priority for compaction"""
        # First message (user task) and last 4 messages are critical
        if index == 0:
            return MessagePriority.CRITICAL
        if index >= total - 4:
            return MessagePriority.CRITICAL

        content = message.get("content", "")
        role = message.get("role", "")

        # Check for important tool types in content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    name = block.get("name", "")
                    # File edits are HIGH priority
                    if name in ("edit_file", "multi_edit", "write_file", "revert_edit"):
                        return MessagePriority.HIGH
                    # Planning tools are HIGH
                    if name in ("todo_write", "task_complete"):
                        return MessagePriority.HIGH
                    # Sub-agent results are HIGH
                    if name == "task":
                        return MessagePriority.HIGH
                    # Tool results that are just reads are LOW
                    if block.get("type") == "tool_result":
                        return MessagePriority.LOW

        # Assistant text responses are MEDIUM
        if role == "assistant" and isinstance(content, str):
            return MessagePriority.MEDIUM

        return MessagePriority.COMPACTABLE


class ContextManager:
    """
    Manages the conversation context window for the Agentic Loop.

    Mirrors Claude Code's approach:
    1. Track token usage in real-time
    2. Trigger compaction at 92% capacity
    3. Summarize low-priority messages
    4. Keep critical context (first task, recent turns, edits)
    5. Inject context summary for continuity
    """

    def __init__(
        self,
        max_tokens: int = MAX_CONTEXT_TOKENS,
        compact_threshold: int = COMPACT_THRESHOLD,
        target_after_compact: int = TARGET_AFTER_COMPACT,
    ):
        self.max_tokens = max_tokens
        self.compact_threshold = compact_threshold
        self.target_after_compact = target_after_compact
        self._usage_history: List[int] = []

    def get_usage(self, messages: List[Dict]) -> Dict[str, Any]:
        """Get current context usage stats"""
        current_tokens = estimate_messages_tokens(messages)
        pct = current_tokens / self.max_tokens if self.max_tokens > 0 else 0
        self._usage_history.append(current_tokens)
        return {
            "current_tokens": current_tokens,
            "max_tokens": self.max_tokens,
            "usage_pct": round(pct * 100, 1),
            "needs_compact": current_tokens > self.compact_threshold,
            "messages_count": len(messages),
        }

    def needs_compaction(self, messages: List[Dict]) -> bool:
        """Check if compaction is needed"""
        return estimate_messages_tokens(messages) > self.compact_threshold

    async def compact(
        self,
        messages: List[Dict],
        ai_engine=None,
        model: str = None,
    ) -> List[Dict]:
        """
        Compact the context by summarizing older messages.

        Strategy (matching Claude Code wU2):
        1. Always keep: first message (task), last 4 messages (recent context)
        2. Keep: HIGH priority messages (edits, plans)
        3. Summarize: Everything else into a compact summary
        4. Target: ~60% of max context after compaction
        """
        total = len(messages)
        if total <= 6:
            return messages  # Too few to compact

        current_tokens = estimate_messages_tokens(messages)
        logger.info(
            f"[ContextManager] Compacting: {current_tokens} tokens "
            f"({current_tokens/self.max_tokens*100:.1f}%) → target {self.target_after_compact}"
        )

        # Classify all messages
        priorities = [
            MessagePriority.classify(msg, i, total)
            for i, msg in enumerate(messages)
        ]

        # Always keep first message and last 4
        keep_indices = {0} | set(range(max(0, total - 4), total))

        # Keep HIGH priority messages
        for i, (msg, prio) in enumerate(zip(messages, priorities)):
            if prio >= MessagePriority.HIGH:
                keep_indices.add(i)

        # Build summary of compactable messages
        to_summarize = []
        for i, (msg, prio) in enumerate(zip(messages, priorities)):
            if i not in keep_indices:
                to_summarize.append(msg)

        if not to_summarize:
            return messages

        # Generate summary
        summary_text = self._build_summary_input(to_summarize)
        summary = await self._generate_summary(
            summary_text, ai_engine, model
        )

        # Reconstruct messages: [first_msg, summary, kept_messages, last_4]
        keep_first = [messages[0]]
        kept_middle = [
            messages[i] for i in sorted(keep_indices)
            if i > 0 and i < total - 4
        ]
        keep_last = messages[max(0, total - 4):]

        compacted = (
            keep_first
            + [{"role": "user", "content": f"[CONTEXT SUMMARY — earlier conversation]\n{summary}"}]
            + [{"role": "assistant", "content": "Understood. I have the context from our earlier work. Continuing."}]
            + kept_middle
            + keep_last
        )

        new_tokens = estimate_messages_tokens(compacted)
        logger.info(
            f"[ContextManager] Compacted: {current_tokens} → {new_tokens} tokens "
            f"({len(messages)} → {len(compacted)} messages)"
        )

        return compacted

    def _build_summary_input(self, messages: List[Dict]) -> str:
        """Build input text for summarization"""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str):
                lines.append(f"[{role}]: {content[:400]}")
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        btype = block.get("type", "")
                        if btype == "text":
                            lines.append(f"[{role}]: {block.get('text', '')[:300]}")
                        elif btype == "tool_use":
                            name = block.get("name", "")
                            desc = block.get("input", {}).get("description", "")
                            lines.append(f"[{role}]: Called {name}: {desc}")
                        elif btype == "tool_result":
                            result_str = str(block.get("content", ""))[:200]
                            lines.append(f"[tool_result]: {result_str}")

        return "\n".join(lines[:60])  # Cap at 60 entries

    async def _generate_summary(
        self, summary_input: str, ai_engine=None, model: str = None
    ) -> str:
        """Generate a summary of the compacted messages"""
        if ai_engine:
            try:
                prompt = (
                    "Summarize this conversation history concisely. "
                    "Focus on: files modified, key decisions made, current task status, "
                    "and any important context needed to continue.\n\n"
                    + summary_input
                )
                result = await ai_engine.get_completion(
                    messages=[{"role": "user", "content": prompt}],
                    model=model or "claude-sonnet-4-5-20250929",
                    temperature=0.1,
                    max_tokens=1024,
                )
                return result.get("content", "Previous context summarized.")
            except Exception as e:
                logger.warning(f"[ContextManager] Summary generation failed: {e}")

        # Fallback: mechanical summary
        return self._mechanical_summary(summary_input)

    def _mechanical_summary(self, summary_input: str) -> str:
        """Create a mechanical summary without AI"""
        lines = summary_input.split("\n")
        # Extract tool calls and results
        tool_calls = []
        edits = []
        for line in lines:
            if "Called" in line:
                tool_calls.append(line.split("Called ", 1)[-1].split(":")[0])
            if any(k in line for k in ["edit_file", "write_file", "multi_edit"]):
                edits.append(line)

        parts = ["Previous conversation involved:"]
        if tool_calls:
            unique = list(dict.fromkeys(tool_calls))
            parts.append(f"- Tool calls: {', '.join(unique[:15])}")
        if edits:
            parts.append(f"- {len(edits)} file modifications")
        parts.append(f"- {len(lines)} total exchanges")
        return "\n".join(parts)

    def inject_reminder(self, system_prompt: str, reminder: str) -> str:
        """Inject TODO status reminder into system prompt"""
        if reminder:
            return system_prompt + f"\n\n{reminder}"
        return system_prompt

    def truncate_tool_output(self, output: str, max_len: int = 15_000) -> str:
        """Truncate tool output while preserving useful content"""
        if len(output) <= max_len:
            return output

        # For JSON output, try to preserve structure
        try:
            data = json.loads(output)
            # If it's a dict with 'content' key, truncate content
            if isinstance(data, dict) and "content" in data:
                content = data["content"]
                if isinstance(content, str) and len(content) > max_len - 500:
                    data["content"] = content[:max_len - 500] + "\n...[truncated]"
                    data["_truncated"] = True
                    return json.dumps(data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass

        # Default: head + tail truncation
        head_size = int(max_len * 0.7)
        tail_size = max_len - head_size - 100
        return (
            output[:head_size]
            + f"\n\n...[{len(output) - max_len} chars truncated]...\n\n"
            + output[-tail_size:]
        )
