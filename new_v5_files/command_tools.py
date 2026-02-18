"""
Command Tools - Bash execution and script running
==================================================
Implements Claude Code's command execution:
- bash: Execute shell commands
- run_script: Run multi-line scripts
- batch_commands: Run multiple commands with summary

Features #6-7, #10-11 from requirements:
"Ran 7 commands", "Ran 3 commands", "Test VALU XOR changes"
"""

import asyncio
import os
import time
import shlex
from typing import Any, Dict, List, Optional


# Commands that require approval (high risk)
HIGH_RISK_PATTERNS = [
    "rm -rf", "rm -r", "mkfs", "dd if=", ":(){ :|:& };:",
    "chmod 777", "> /dev/sda", "shutdown", "reboot",
    "curl | sh", "wget | sh", "pip install",
]

# Commands that are always safe
SAFE_COMMANDS = [
    "ls", "cat", "head", "tail", "wc", "grep", "find",
    "echo", "pwd", "whoami", "date", "env",
    "git status", "git log", "git diff", "git branch",
    "python --version", "node --version", "npm --version",
]


async def bash(
    command: str,
    timeout: int = 120,
    working_dir: Optional[str] = None,
    description: str = "",
) -> Dict[str, Any]:
    """
    Execute a shell command.
    
    Like Claude Code's Bash tool:
    - Persistent session (uses working_dir)
    - Timeout protection
    - Risk assessment
    - Output capture (stdout + stderr)
    """
    # Risk assessment
    risk_level = _assess_risk(command)
    
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env={**os.environ, "TERM": "dumb"},
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "command": command,
                "error": "timeout",
            }
        
        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")
        
        # Truncate very long output
        MAX_OUTPUT = 50000
        stdout_truncated = len(stdout_str) > MAX_OUTPUT
        stderr_truncated = len(stderr_str) > MAX_OUTPUT
        
        if stdout_truncated:
            stdout_str = stdout_str[:MAX_OUTPUT] + f"\n... [output truncated, {len(stdout_str)} total chars]"
        if stderr_truncated:
            stderr_str = stderr_str[:MAX_OUTPUT] + f"\n... [stderr truncated, {len(stderr_str)} total chars]"
        
        return {
            "success": process.returncode == 0,
            "exit_code": process.returncode,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "command": command,
            "risk_level": risk_level,
            "display_title": description or _generate_command_title(command),
        }
        
    except Exception as e:
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
            "command": command,
            "error": str(e),
        }


async def run_script(
    script: str,
    interpreter: str = "bash",
    timeout: int = 300,
    working_dir: Optional[str] = None,
    description: str = "",
) -> Dict[str, Any]:
    """
    Run a multi-line script.
    
    Used for Feature #6: "Ran 7 commands" with expandable Script display.
    Creates a temp script file, executes it, cleans up.
    """
    import tempfile
    
    # Determine file extension and shebang
    ext_map = {"bash": ".sh", "python": ".py", "node": ".js"}
    shebang_map = {
        "bash": "#!/bin/bash\nset -e\n",
        "python": "#!/usr/bin/env python3\n",
        "node": "#!/usr/bin/env node\n",
    }
    
    ext = ext_map.get(interpreter, ".sh")
    shebang = shebang_map.get(interpreter, "#!/bin/bash\n")
    
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=ext, delete=False, dir=working_dir or "/tmp"
        ) as f:
            f.write(shebang + script)
            script_path = f.name
        
        os.chmod(script_path, 0o755)
        
        result = await bash(
            command=f"{interpreter} {script_path}",
            timeout=timeout,
            working_dir=working_dir,
            description=description,
        )
        
        result["script"] = script
        result["interpreter"] = interpreter
        result["display_title"] = description or "Script"
        
        return result
        
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


async def batch_commands(
    commands: List[Dict[str, str]],
    working_dir: Optional[str] = None,
    stop_on_error: bool = True,
    description: str = "",
) -> Dict[str, Any]:
    """
    Run multiple commands in sequence.
    
    Implements Feature #6-7: "Ran 7 commands" / "Ran 3 commands"
    Each command has a description and the result shows success/failure for each.
    
    Args:
        commands: List of {"command": "...", "description": "..."}
        stop_on_error: If True, stop on first failure
    """
    results = []
    total_success = 0
    total_failed = 0
    
    for cmd_info in commands:
        command = cmd_info.get("command", "")
        cmd_desc = cmd_info.get("description", "")
        
        result = await bash(
            command=command,
            working_dir=working_dir,
            description=cmd_desc,
        )
        
        results.append({
            "command": command,
            "description": cmd_desc,
            "success": result["success"],
            "exit_code": result["exit_code"],
            "stdout_preview": result["stdout"][:500] if result["stdout"] else "",
            "stderr_preview": result["stderr"][:200] if result["stderr"] else "",
        })
        
        if result["success"]:
            total_success += 1
        else:
            total_failed += 1
            if stop_on_error:
                break
    
    return {
        "success": total_failed == 0,
        "total_commands": len(commands),
        "executed": len(results),
        "succeeded": total_success,
        "failed": total_failed,
        "results": results,
        "display_title": f"Ran {len(results)} command{'s' if len(results) > 1 else ''}",
    }


def _assess_risk(command: str) -> str:
    """Assess risk level of a command"""
    cmd_lower = command.lower().strip()
    
    for pattern in HIGH_RISK_PATTERNS:
        if pattern in cmd_lower:
            return "high"
    
    for safe in SAFE_COMMANDS:
        if cmd_lower.startswith(safe):
            return "low"
    
    return "medium"


def _generate_command_title(command: str) -> str:
    """Generate a human-readable title for a command"""
    cmd = command.strip()
    if len(cmd) > 80:
        cmd = cmd[:80] + "..."
    return cmd


# Tool definitions for registration
COMMAND_TOOL_DEFINITIONS = [
    {
        "name": "bash",
        "description": "Execute a shell command",
        "handler": bash,
        "category": "command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120)"},
                "working_dir": {"type": "string", "description": "Working directory"},
                "description": {"type": "string", "description": "What this command does"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "run_script",
        "description": "Run a multi-line script with specified interpreter",
        "handler": run_script,
        "category": "command",
        "parameters": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "Script content"},
                "interpreter": {"type": "string", "description": "bash, python, or node"},
                "timeout": {"type": "integer"},
                "working_dir": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["script"],
        },
    },
    {
        "name": "batch_commands",
        "description": "Run multiple commands in sequence with individual descriptions",
        "handler": batch_commands,
        "category": "command",
        "parameters": {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["command"],
                    },
                },
                "working_dir": {"type": "string"},
                "stop_on_error": {"type": "boolean"},
                "description": {"type": "string"},
            },
            "required": ["commands"],
        },
    },
]
