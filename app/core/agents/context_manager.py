"""
Context Manager v10 — Sliding Window + Progressive Compaction
================================================================
Knuth-inspired rewrite addressing 0228demo's O(n²) cost problem:

  KEY CHANGE: Don't wait until 92% to compact. Instead:
    - Micro-compact every 5 turns (compress old turns into summaries)
    - Maintain a sliding window of 4 recent turns at full fidelity
    - Keep total context budget ~40K tokens instead of letting it grow to 165K

  0228 DEMO BEFORE: 30 turns, 3K→70K tokens, $3.18 total
  PROJECTED AFTER:  30 turns, 3K→35K tokens, ~$0.80 total

Original kept for backwards compatibility — all public APIs preserved.

Drop-in at: app/core/agents/context_manager.py
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_CONTEXT_TOKENS = 180_000        # Claude 200k window, keep 20k buffer
COMPACT_THRESHOLD_PCT = 0.92        # Legacy threshold (kept for safety net)
COMPACT_THRESHOLD = int(MAX_CONTEXT_TOKENS * COMPACT_THRESHOLD_PCT)
TARGET_AFTER_COMPACT = int(MAX_CONTEXT_TOKENS * 0.60)

# v10: Sliding window parameters
SLIDING_WINDOW_SIZE = 4             # Keep last N turns at full fidelity
MICRO_COMPACT_INTERVAL = 5          # Run micro-compaction every N turns
MICRO_COMPACT_BUDGET = 40_000       # Target max context tokens for micro-compact
MAX_SUMMARY_TOKENS = 2000           # Max tokens for a context summary

# Token estimation calibration
CHARS_PER_TOKEN = 3.8  # Calibrated for code+English mix


# =============================================================================
# Token Estimation (unchanged — these work well)
# =============================================================================

def estimate_tokens(text: str) -> int:
    """
    Estimate token count for a string.
    Uses a calibrated chars/token ratio that works well for code+English.
    """
    if not text:
        return 0
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
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
            return (
                estimate_tokens(block.get("name", ""))
                + estimate_tokens(json.dumps(block.get("input", {})))
                + 20
            )
        elif block_type == "tool_result":
            content = block.get("content", "")
            if isinstance(content, str):
                return estimate_tokens(content) + 10
            elif isinstance(content, list):
                return sum(estimate_block_tokens(b) for b in content) + 10
            return 10
    return 5


def estimate_message_tokens(message: Dict) -> int:
    """Estimate tokens for a single message"""
    tokens = 4
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


# =============================================================================
# Message Priority (enhanced with cost awareness)
# =============================================================================

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

    # v10: Tools that indicate important state changes
    HIGH_PRIORITY_TOOLS = frozenset({
        "edit_file", "multi_edit", "write_file", "revert_edit",
        "todo_write", "task_complete", "task",
    })

    # v10: Tools whose results are typically large but low-value for context
    LOW_VALUE_RESULTS = frozenset({
        "read_file", "batch_read", "list_dir", "glob",
        "grep_search", "file_search", "web_fetch",
        "view_truncated", "bash",
    })

    @staticmethod
    def classify(message: Dict, index: int, total: int) -> int:
        """Classify a message's priority for compaction"""
        if index == 0:
            return MessagePriority.CRITICAL
        if index >= total - 4:
            return MessagePriority.CRITICAL

        content = message.get("content", "")
        role = message.get("role", "")

        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    name = block.get("name", "")
                    if name in MessagePriority.HIGH_PRIORITY_TOOLS:
                        return MessagePriority.HIGH
                    if block.get("type") == "tool_result":
                        return MessagePriority.LOW

        if role == "assistant" and isinstance(content, str):
            return MessagePriority.MEDIUM

        return MessagePriority.COMPACTABLE

    @staticmethod
    def classify_tool_result_value(tool_name: str, result: str) -> int:
        """
        v10: Classify how much of a tool result should be kept.
        Returns max chars to retain in context.
        """
        if tool_name in MessagePriority.HIGH_PRIORITY_TOOLS:
            return 5000   # Keep more for edits
        if tool_name in ("web_search",):
            return 3000   # Search results are medium value
        if tool_name in MessagePriority.LOW_VALUE_RESULTS:
            return 1000   # Aggressive truncation for reads
        return 2000       # Default


# =============================================================================
# ContextManager v10 — Sliding Window + Progressive Compaction
# =============================================================================

class ContextManager:
    """
    Manages the conversation context window for the Agentic Loop.

    v10 KEY CHANGES:
    1. Progressive micro-compaction every 5 turns (not just at 92%)
    2. Sliding window of 4 recent turns at full fidelity
    3. Aggressive tool result truncation for old turns
    4. Budget-based compaction targeting ~40K tokens

    Backwards-compatible: all v7 public methods preserved.
    """

    def __init__(
        self,
        max_tokens: int = MAX_CONTEXT_TOKENS,
        compact_threshold: int = COMPACT_THRESHOLD,
        target_after_compact: int = TARGET_AFTER_COMPACT,
        # v10 params
        sliding_window_size: int = SLIDING_WINDOW_SIZE,
        micro_compact_interval: int = MICRO_COMPACT_INTERVAL,
        micro_compact_budget: int = MICRO_COMPACT_BUDGET,
    ):
        self.max_tokens = max_tokens
        self.compact_threshold = compact_threshold
        self.target_after_compact = target_after_compact
        # v10
        self.sliding_window_size = sliding_window_size
        self.micro_compact_interval = micro_compact_interval
        self.micro_compact_budget = micro_compact_budget
        self._usage_history: List[int] = []
        self._compaction_count = 0
        self._total_tokens_saved = 0

    # -------------------------------------------------------------------------
    # Public API (v7 compatible)
    # -------------------------------------------------------------------------

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
            # v10: additional stats
            "compaction_count": self._compaction_count,
            "total_tokens_saved": self._total_tokens_saved,
        }

    def needs_compaction(self, messages: List[Dict]) -> bool:
        """Check if compaction is needed (v7 API preserved)"""
        return estimate_messages_tokens(messages) > self.compact_threshold

    def needs_micro_compaction(self, messages: List[Dict], turn: int) -> bool:
        """
        v10: Check if progressive micro-compaction should run.
        Triggers earlier and more often than full compaction.
        """
        if turn < self.micro_compact_interval:
            return False
        if turn % self.micro_compact_interval != 0:
            return False
        current = estimate_messages_tokens(messages)
        return current > self.micro_compact_budget

    async def micro_compact(
        self,
        messages: List[Dict],
        turn: int,
    ) -> List[Dict]:
        """
        v10: Progressive micro-compaction.

        Strategy:
        1. Keep first message (task definition)
        2. Keep last SLIDING_WINDOW_SIZE*2 messages (recent turns)
        3. For everything in between:
           - Keep HIGH priority messages
           - Truncate tool results aggressively
           - Replace COMPACTABLE messages with one-line summaries
        4. No AI call needed — this is purely mechanical

        This runs every 5 turns and prevents the O(n²) cost growth.
        """
        total = len(messages)
        window_keep = self.sliding_window_size * 2  # each turn = 2 messages (assistant + user/tool)

        if total <= window_keep + 2:
            return messages

        before_tokens = estimate_messages_tokens(messages)

        # Split: [first_msg] + [middle...] + [recent_window]
        first_msg = messages[0]
        middle = messages[1:total - window_keep]
        recent = messages[total - window_keep:]

        # Process middle: truncate and compress
        compressed_middle = self._compress_middle(middle)

        # Reconstruct
        compacted = [first_msg] + compressed_middle + recent

        after_tokens = estimate_messages_tokens(compacted)
        saved = before_tokens - after_tokens
        self._compaction_count += 1
        self._total_tokens_saved += saved

        logger.info(
            f"[ContextManager v10] Micro-compact turn {turn}: "
            f"{before_tokens}→{after_tokens} tokens "
            f"({len(messages)}→{len(compacted)} msgs, saved {saved} tokens)"
        )

        return compacted

    async def compact(
        self,
        messages: List[Dict],
        ai_engine=None,
        model: str = None,
    ) -> List[Dict]:
        """
        Full compaction (v7 API preserved).
        Now used as safety net — micro_compact handles most cases.
        """
        total = len(messages)
        if total <= 6:
            return messages

        current_tokens = estimate_messages_tokens(messages)
        logger.info(
            f"[ContextManager] Full compacting: {current_tokens} tokens "
            f"({current_tokens/self.max_tokens*100:.1f}%) → target {self.target_after_compact}"
        )

        priorities = [
            MessagePriority.classify(msg, i, total)
            for i, msg in enumerate(messages)
        ]

        keep_indices = {0} | set(range(max(0, total - 4), total))

        for i, (msg, prio) in enumerate(zip(messages, priorities)):
            if prio >= MessagePriority.HIGH:
                keep_indices.add(i)

        to_summarize = [
            msg for i, (msg, _) in enumerate(zip(messages, priorities))
            if i not in keep_indices
        ]

        if not to_summarize:
            return messages

        summary_text = self._build_summary_input(to_summarize)
        summary = await self._generate_summary(summary_text, ai_engine, model)

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
        saved = current_tokens - new_tokens
        self._compaction_count += 1
        self._total_tokens_saved += saved

        logger.info(
            f"[ContextManager] Compacted: {current_tokens} → {new_tokens} tokens "
            f"({len(messages)} → {len(compacted)} messages)"
        )

        return compacted

    # -------------------------------------------------------------------------
    # v10: Middle compression (mechanical, no AI needed)
    # -------------------------------------------------------------------------

    def _compress_middle(self, messages: List[Dict]) -> List[Dict]:
        """
        Compress middle messages without AI call.

        Strategy:
        - HIGH priority: keep but truncate tool results to 1000 chars
        - MEDIUM: keep but truncate heavily (500 chars)
        - LOW/COMPACTABLE: replace with one-line summary
        """
        total = len(messages)
        compressed = []
        summary_lines = []

        for i, msg in enumerate(messages):
            prio = MessagePriority.classify(msg, i + 1, total + 2)  # offset for first msg

            if prio >= MessagePriority.HIGH:
                # Keep but truncate tool results
                compressed.append(self._truncate_message(msg, max_content=2000))
            elif prio >= MessagePriority.MEDIUM:
                compressed.append(self._truncate_message(msg, max_content=500))
            else:
                # Collect one-liner for batch summary
                line = self._message_one_liner(msg)
                if line:
                    summary_lines.append(line)

        # Bundle compactable messages into a single summary message
        if summary_lines:
            # Group into chunks of 10 to avoid one giant message
            batch_summary = "\n".join(summary_lines[:30])
            compressed.insert(0, {
                "role": "user",
                "content": f"[Earlier context — {len(summary_lines)} exchanges]\n{batch_summary}"
            })
            compressed.insert(1, {
                "role": "assistant",
                "content": "Understood, continuing with this context."
            })

        return compressed

    def _truncate_message(self, msg: Dict, max_content: int = 2000) -> Dict:
        """Truncate a message's content while preserving structure"""
        content = msg.get("content", "")

        if isinstance(content, str):
            if len(content) > max_content:
                return {
                    **msg,
                    "content": content[:max_content] + "…[truncated]"
                }
            return msg

        if isinstance(content, list):
            truncated_blocks = []
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "tool_result":
                        # Aggressively truncate tool results
                        result = block.get("content", "")
                        if isinstance(result, str) and len(result) > max_content:
                            truncated_blocks.append({
                                **block,
                                "content": result[:max_content] + "…[truncated]"
                            })
                        else:
                            truncated_blocks.append(block)
                    elif btype == "text":
                        text = block.get("text", "")
                        if len(text) > max_content:
                            truncated_blocks.append({
                                **block,
                                "text": text[:max_content] + "…[truncated]"
                            })
                        else:
                            truncated_blocks.append(block)
                    else:
                        truncated_blocks.append(block)
                else:
                    truncated_blocks.append(block)
            return {**msg, "content": truncated_blocks}

        return msg

    def _message_one_liner(self, msg: Dict) -> Optional[str]:
        """Extract a one-line summary of a message"""
        content = msg.get("content", "")
        role = msg.get("role", "")

        if isinstance(content, str):
            first_line = content.split("\n")[0][:120]
            return f"[{role}] {first_line}"

        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "tool_use":
                        name = block.get("name", "?")
                        desc = block.get("input", {}).get("description", "")[:60]
                        parts.append(f"{name}({desc})")
                    elif btype == "tool_result":
                        result = str(block.get("content", ""))[:60]
                        parts.append(f"→ {result}")
                    elif btype == "text":
                        parts.append(block.get("text", "")[:60])
            if parts:
                return f"[{role}] {' | '.join(parts[:3])}"

        return None

    # -------------------------------------------------------------------------
    # Summarization (v7 preserved)
    # -------------------------------------------------------------------------

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
        return "\n".join(lines[:60])

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

        return self._mechanical_summary(summary_input)

    def _mechanical_summary(self, summary_input: str) -> str:
        """Create a mechanical summary without AI"""
        lines = summary_input.split("\n")
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

    # -------------------------------------------------------------------------
    # Utility methods (v7 preserved)
    # -------------------------------------------------------------------------

    def inject_reminder(self, system_prompt: str, reminder: str) -> str:
        """Inject TODO status reminder into system prompt"""
        if reminder:
            return system_prompt + f"\n\n{reminder}"
        return system_prompt

    def truncate_tool_output(self, output: str, max_len: int = 15_000) -> str:
        """Truncate tool output while preserving useful content"""
        if len(output) <= max_len:
            return output

        try:
            data = json.loads(output)
            if isinstance(data, dict) and "content" in data:
                content = data["content"]
                if isinstance(content, str) and len(content) > max_len - 500:
                    data["content"] = content[:max_len - 500] + "\n...[truncated]"
                    data["_truncated"] = True
                    return json.dumps(data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass

        head_size = int(max_len * 0.7)
        tail_size = max_len - head_size - 100
        return (
            output[:head_size]
            + f"\n\n...[{len(output) - max_len} chars truncated]...\n\n"
            + output[-tail_size:]
        )