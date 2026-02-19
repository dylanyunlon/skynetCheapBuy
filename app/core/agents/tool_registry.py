"""
Tool Registry — Centralized Tool Management for Agentic Loop v7
================================================================
Inspired by Claude Code's internal tool architecture:
  - Declarative tool registration with categories
  - Permission-level classification per tool
  - Schema validation for tool inputs
  - Dynamic tool filtering for sub-agents
  - Usage statistics per tool

Drop-in at: app/core/agents/tool_registry.py
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    """Tool categories matching Claude Code's internal grouping"""
    COMMAND = "command"       # bash, run_script, batch_commands
    FILE_READ = "file_read"  # read_file, batch_read, view_truncated
    FILE_WRITE = "file_write"  # write_file, edit_file, multi_edit, revert_edit
    SEARCH = "search"        # grep_search, file_search, glob
    WEB = "web"              # web_search, web_fetch
    PLANNING = "planning"    # todo_write, todo_read
    AGENT = "agent"          # task (sub-agent)
    MEMORY = "memory"        # memory_read, memory_write
    CONTROL = "control"      # task_complete


class PermissionLevel(str, Enum):
    """Permission levels (Claude Code-style)"""
    SAFE = "safe"            # Always allowed (read operations)
    NORMAL = "normal"        # Allowed by default (file edits)
    RISKY = "risky"          # Requires user confirmation (rm, sudo, etc.)
    BLOCKED = "blocked"      # Never allowed


@dataclass
class ToolDefinition:
    """Complete tool definition with metadata"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    category: ToolCategory
    permission: PermissionLevel = PermissionLevel.NORMAL
    handler: Optional[Callable] = None
    # Display hints for frontend
    icon: str = "zap"
    display_label: str = ""
    # Stats
    call_count: int = 0
    total_duration_ms: float = 0
    error_count: int = 0

    @property
    def avg_duration_ms(self) -> float:
        if self.call_count == 0:
            return 0
        return self.total_duration_ms / self.call_count

    def to_api_schema(self) -> Dict[str, Any]:
        """Convert to Anthropic API tool format"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """
    Centralized tool registry for the Agentic Loop.

    Key features:
    - Register tools with metadata (category, permissions, icons)
    - Filter tools by category or permission for sub-agents
    - Track per-tool usage statistics
    - Generate API-compatible tool schemas
    """

    # Icon mapping for frontend display
    ICON_MAP = {
        "bash": "terminal",
        "read_file": "file-text",
        "batch_read": "files",
        "write_file": "file-plus",
        "edit_file": "pencil",
        "multi_edit": "pencil-ruler",
        "list_dir": "folder-open",
        "grep_search": "search",
        "file_search": "file-search",
        "glob": "file-search",
        "web_search": "globe",
        "web_fetch": "download",
        "task_complete": "check-circle",
        "view_truncated": "eye",
        "batch_commands": "terminal",
        "run_script": "code",
        "revert_edit": "rotate-ccw",
        "todo_write": "list-todo",
        "todo_read": "list-checks",
        "task": "git-branch",
        "memory_read": "brain",
        "memory_write": "brain",
    }

    # Category mapping for auto-classification
    CATEGORY_MAP = {
        "bash": ToolCategory.COMMAND,
        "batch_commands": ToolCategory.COMMAND,
        "run_script": ToolCategory.COMMAND,
        "read_file": ToolCategory.FILE_READ,
        "batch_read": ToolCategory.FILE_READ,
        "view_truncated": ToolCategory.FILE_READ,
        "write_file": ToolCategory.FILE_WRITE,
        "edit_file": ToolCategory.FILE_WRITE,
        "multi_edit": ToolCategory.FILE_WRITE,
        "revert_edit": ToolCategory.FILE_WRITE,
        "list_dir": ToolCategory.SEARCH,
        "grep_search": ToolCategory.SEARCH,
        "file_search": ToolCategory.SEARCH,
        "glob": ToolCategory.SEARCH,
        "web_search": ToolCategory.WEB,
        "web_fetch": ToolCategory.WEB,
        "todo_write": ToolCategory.PLANNING,
        "todo_read": ToolCategory.PLANNING,
        "task": ToolCategory.AGENT,
        "memory_read": ToolCategory.MEMORY,
        "memory_write": ToolCategory.MEMORY,
        "task_complete": ToolCategory.CONTROL,
    }

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        category: Optional[ToolCategory] = None,
        permission: Optional[PermissionLevel] = None,
        handler: Optional[Callable] = None,
        icon: Optional[str] = None,
        display_label: Optional[str] = None,
    ) -> ToolDefinition:
        """Register a tool with full metadata"""
        tool = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema,
            category=category or self.CATEGORY_MAP.get(name, ToolCategory.COMMAND),
            permission=permission or PermissionLevel.NORMAL,
            handler=handler,
            icon=icon or self.ICON_MAP.get(name, "zap"),
            display_label=display_label or name.replace("_", " ").title(),
        )
        self._tools[name] = tool
        return tool

    def register_from_definition(self, definition: Dict[str, Any]) -> ToolDefinition:
        """Register from legacy TOOL_DEFINITIONS format"""
        name = definition["name"]
        return self.register(
            name=name,
            description=definition.get("description", ""),
            input_schema=definition.get("input_schema", {"type": "object", "properties": {}}),
            handler=definition.get("handler"),
        )

    def register_all(self, definitions: List[Dict[str, Any]]) -> None:
        """Register a list of tool definitions"""
        for d in definitions:
            self.register_from_definition(d)

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_all(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def get_names(self) -> List[str]:
        return list(self._tools.keys())

    def get_api_schemas(self, tool_names: Optional[List[str]] = None) -> List[Dict]:
        """Get tool schemas for Anthropic API calls"""
        if tool_names:
            return [
                self._tools[n].to_api_schema()
                for n in tool_names if n in self._tools
            ]
        return [t.to_api_schema() for t in self._tools.values()]

    def filter_by_category(self, categories: Set[ToolCategory]) -> List[ToolDefinition]:
        """Filter tools by category (used for sub-agent tool sets)"""
        return [t for t in self._tools.values() if t.category in categories]

    def filter_by_names(self, names: List[str]) -> List[Dict]:
        """Get API schemas for specific tool names"""
        return [self._tools[n].to_api_schema() for n in names if n in self._tools]

    def get_subagent_tools(self, subagent_type: str) -> List[Dict]:
        """
        Get tool set for a specific sub-agent type.
        Matches Claude Code's sub-agent tool restrictions.
        """
        tool_sets = {
            "explore": {ToolCategory.FILE_READ, ToolCategory.SEARCH, ToolCategory.CONTROL},
            "plan": {ToolCategory.FILE_READ, ToolCategory.SEARCH, ToolCategory.PLANNING, ToolCategory.CONTROL},
            "general": None,  # All tools except 'task' itself
        }
        categories = tool_sets.get(subagent_type)
        if categories is None:
            # General: all tools except recursive sub-agent spawning
            return [t.to_api_schema() for t in self._tools.values() if t.name != "task"]
        tools = self.filter_by_category(categories)
        return [t.to_api_schema() for t in tools]

    def record_call(self, name: str, duration_ms: float, error: bool = False):
        """Record a tool call for statistics"""
        tool = self._tools.get(name)
        if tool:
            tool.call_count += 1
            tool.total_duration_ms += duration_ms
            if error:
                tool.error_count += 1

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics for all tools"""
        stats = {}
        for name, tool in self._tools.items():
            if tool.call_count > 0:
                stats[name] = {
                    "calls": tool.call_count,
                    "errors": tool.error_count,
                    "avg_ms": round(tool.avg_duration_ms, 1),
                    "total_ms": round(tool.total_duration_ms, 1),
                }
        return stats

    def get_category_display(self, tool_name: str) -> str:
        """Get display category for turn summaries"""
        cat = self.CATEGORY_MAP.get(tool_name, ToolCategory.COMMAND)
        return {
            ToolCategory.COMMAND: "command",
            ToolCategory.FILE_READ: "view",
            ToolCategory.FILE_WRITE: "edit",
            ToolCategory.SEARCH: "search",
            ToolCategory.WEB: "web",
            ToolCategory.PLANNING: "planning",
            ToolCategory.AGENT: "agent",
            ToolCategory.MEMORY: "memory",
            ToolCategory.CONTROL: "control",
        }.get(cat, "other")
