"""
Permission Gate — Risk Assessment & Approval for Agentic Loop v7
=================================================================
Implements Claude Code's permission system:
  - Command risk classification (safe/medium/risky/blocked)
  - Configurable auto-approve patterns
  - User approval flow for risky operations
  - Audit logging for all permission decisions

Drop-in at: app/core/agents/permission_gate.py
"""

import re
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    SAFE = "safe"
    MEDIUM = "medium"
    RISKY = "risky"
    BLOCKED = "blocked"


# Patterns that make a command RISKY (require user approval)
RISKY_PATTERNS = [
    r'\brm\s+(-rf?|--recursive)\b',
    r'\bsudo\b',
    r'\bchmod\b.*777',
    r'\bgit\s+push\b',
    r'\bgit\s+reset\s+--hard\b',
    r'\bgit\s+force\b',
    r'\breboot\b',
    r'\bshutdown\b',
    r'\bdrop\s+(table|database)\b',
    r'\btruncate\b',
    r'\bmkfs\b',
    r'\bdd\s+if=',
    r'>\s*/dev/',
    r'\bcurl\b.*\|\s*(bash|sh)\b',
    r'\bwget\b.*\|\s*(bash|sh)\b',
    r'\bkill\s+-9\b',
    r'\bsystemctl\s+(stop|restart|disable)\b',
    r'\bdocker\s+(rm|rmi|prune|system\s+prune)\b',
    r'\biptables\b',
]

# Patterns that are BLOCKED (never allowed)
BLOCKED_PATTERNS = [
    r':\(\)\{\s*:\|:&\s*\};:',   # Fork bomb
    r'\brm\s+-rf\s+/\s*$',       # rm -rf /
    r'\brm\s+-rf\s+/\*',         # rm -rf /*
    r'>\s*/dev/sda',              # Overwrite disk
    r'\bmkfs\s+/dev/sd[a-z]$',   # Format root disk
]

# Commands that are always SAFE
SAFE_PREFIXES = [
    "ls", "cat", "head", "tail", "wc", "grep", "find", "tree",
    "echo", "pwd", "whoami", "date", "env", "which", "type",
    "python --version", "python3 --version", "pip list", "pip show",
    "node --version", "npm --version", "npm list",
    "git status", "git log", "git diff", "git branch", "git show",
    "git rev-parse", "git remote -v",
    "du -sh", "df -h", "free -h", "uptime",
    "file ", "stat ", "readlink",
]


@dataclass
class PermissionDecision:
    """Record of a permission decision"""
    command: str
    risk_level: RiskLevel
    approved: bool
    reason: str
    tool_name: str = ""
    tool_use_id: str = ""


class PermissionGate:
    """
    Command risk assessment and approval gate.

    Usage:
        gate = PermissionGate()
        risk = gate.assess("rm -rf /tmp/build")
        if risk == RiskLevel.RISKY:
            # Ask user for approval
            ...
    """

    def __init__(
        self,
        auto_approve_patterns: Optional[List[str]] = None,
        blocked_patterns: Optional[List[str]] = None,
    ):
        self._auto_approve = set(auto_approve_patterns or [])
        self._extra_blocked = [re.compile(p, re.IGNORECASE) for p in (blocked_patterns or [])]
        self._decisions: List[PermissionDecision] = []

        # Compile patterns
        self._risky_compiled = [re.compile(p, re.IGNORECASE) for p in RISKY_PATTERNS]
        self._blocked_compiled = [re.compile(p, re.IGNORECASE) for p in BLOCKED_PATTERNS]

    def assess(self, command: str) -> RiskLevel:
        """Assess the risk level of a command"""
        cmd = command.strip()

        # Check blocked patterns
        for pattern in self._blocked_compiled + self._extra_blocked:
            if pattern.search(cmd):
                logger.warning(f"[PermissionGate] BLOCKED: {cmd[:100]}")
                return RiskLevel.BLOCKED

        # Check auto-approve
        for pattern in self._auto_approve:
            if re.search(pattern, cmd, re.IGNORECASE):
                return RiskLevel.SAFE

        # Check safe prefixes
        cmd_lower = cmd.lower()
        for prefix in SAFE_PREFIXES:
            if cmd_lower.startswith(prefix):
                return RiskLevel.SAFE

        # Check risky patterns
        for pattern in self._risky_compiled:
            if pattern.search(cmd):
                return RiskLevel.RISKY

        # Default: medium (allowed without explicit approval)
        return RiskLevel.MEDIUM

    def assess_tool(self, tool_name: str, tool_input: Dict) -> RiskLevel:
        """Assess risk for any tool call"""
        if tool_name == "bash":
            return self.assess(tool_input.get("command", ""))
        if tool_name == "batch_commands":
            # Assess all commands in batch
            commands = tool_input.get("commands", [])
            levels = [self.assess(c.get("command", "")) for c in commands]
            if RiskLevel.BLOCKED in levels:
                return RiskLevel.BLOCKED
            if RiskLevel.RISKY in levels:
                return RiskLevel.RISKY
            return RiskLevel.MEDIUM
        if tool_name == "run_script":
            # Scripts are inherently medium risk
            return RiskLevel.MEDIUM
        # File operations are safe
        if tool_name in ("read_file", "batch_read", "view_truncated", "list_dir",
                         "grep_search", "file_search", "glob", "todo_read",
                         "memory_read", "web_search"):
            return RiskLevel.SAFE
        return RiskLevel.MEDIUM

    def record(self, decision: PermissionDecision):
        """Record a permission decision for audit"""
        self._decisions.append(decision)
        if decision.risk_level in (RiskLevel.RISKY, RiskLevel.BLOCKED):
            logger.info(
                f"[PermissionGate] {decision.risk_level.value}: "
                f"{decision.command[:100]} → {'approved' if decision.approved else 'denied'}"
            )

    def get_audit_log(self) -> List[Dict]:
        """Get audit log of all permission decisions"""
        return [
            {
                "command": d.command[:200],
                "risk_level": d.risk_level.value,
                "approved": d.approved,
                "reason": d.reason,
                "tool_name": d.tool_name,
            }
            for d in self._decisions
        ]
