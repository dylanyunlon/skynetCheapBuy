"""
Debug Agent — Automated Debug Cycle for Agentic Loop v8
=========================================================
Inspired by Claude Code's debug loop behavior (features #10-#14):

  ★ TestRunner        — Run tests and capture structured results
  ★ DebugCycle        — Multi-step investigation: read error → trace → fix → verify
  ★ CorrectnessCheck  — Compare outputs against reference
  ★ RevertManager     — Track edit history for safe rollback
  ★ DiffTracker       — Detailed +N/-M line change accounting

Drop-in at: app/core/agents/debug_agent.py

Usage in AgenticLoop:
    debug = DebugAgent(work_dir=self.work_dir)
    result = await debug.run_test(command="python -m pytest tests/")
    if not result["passed"]:
        fix_plan = await debug.diagnose(result)
"""

import os
import json
import asyncio
import logging
import time
import hashlib
import difflib
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# Edit History — Track all file changes for revert support
# =============================================================================

@dataclass
class EditRecord:
    """A single file edit that can be reverted"""
    edit_id: str
    path: str
    old_content: str
    new_content: str
    description: str
    timestamp: float = field(default_factory=time.time)
    tool_name: str = "edit_file"
    # Diff stats
    added_lines: int = 0
    removed_lines: int = 0
    
    @property
    def diff_display(self) -> str:
        """Claude Code-style +N/-M display"""
        parts = []
        if self.added_lines:
            parts.append(f"+{self.added_lines}")
        if self.removed_lines:
            parts.append(f"-{self.removed_lines}")
        return ",".join(parts) if parts else "no change"
    
    def compute_diff(self) -> str:
        """Generate unified diff"""
        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{os.path.basename(self.path)}",
            tofile=f"b/{os.path.basename(self.path)}",
            lineterm=""
        )
        return "\n".join(diff)


class RevertManager:
    """
    Manages edit history for safe revert operations.
    Matches Claude Code's revert behavior (Feature #12-14).
    """
    
    def __init__(self, max_history: int = 200):
        self._history: List[EditRecord] = []
        self._max_history = max_history
    
    def record_edit(
        self,
        path: str,
        old_content: str,
        new_content: str,
        description: str = "",
        tool_name: str = "edit_file",
    ) -> EditRecord:
        """Record an edit for potential revert"""
        # Calculate diff stats
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        diff = list(difflib.unified_diff(old_lines, new_lines))
        added = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
        removed = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))
        
        edit_id = hashlib.sha256(
            f"{path}:{time.time()}:{description}".encode()
        ).hexdigest()[:12]
        
        record = EditRecord(
            edit_id=edit_id,
            path=path,
            old_content=old_content,
            new_content=new_content,
            description=description,
            tool_name=tool_name,
            added_lines=added,
            removed_lines=removed,
        )
        
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        
        return record
    
    def revert_last(self, path: str) -> Optional[EditRecord]:
        """Revert the most recent edit to a file"""
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i].path == path:
                record = self._history[i]
                # Write old content back
                try:
                    with open(record.path, 'w', encoding='utf-8') as f:
                        f.write(record.old_content)
                    self._history.pop(i)
                    return record
                except Exception as e:
                    logger.error(f"Revert failed: {e}")
                    return None
        return None
    
    def revert_by_id(self, edit_id: str) -> Optional[EditRecord]:
        """Revert a specific edit by ID"""
        for i, record in enumerate(self._history):
            if record.edit_id == edit_id:
                try:
                    with open(record.path, 'w', encoding='utf-8') as f:
                        f.write(record.old_content)
                    self._history.pop(i)
                    return record
                except Exception as e:
                    logger.error(f"Revert failed: {e}")
                    return None
        return None
    
    def get_history(self, path: Optional[str] = None, limit: int = 20) -> List[Dict]:
        """Get edit history"""
        records = self._history
        if path:
            records = [r for r in records if r.path == path]
        return [
            {
                "edit_id": r.edit_id,
                "path": r.path,
                "description": r.description,
                "diff_display": r.diff_display,
                "timestamp": r.timestamp,
                "tool_name": r.tool_name,
            }
            for r in records[-limit:]
        ]
    
    def get_file_versions(self, path: str) -> int:
        """Count how many edits have been made to a file"""
        return sum(1 for r in self._history if r.path == path)


# =============================================================================
# Test Runner — Structured test execution (Feature #10)
# =============================================================================

@dataclass
class TestResult:
    """Structured test execution result"""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    passed: bool
    duration_s: float
    # Parsed test details
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    error_tests: int = 0
    skipped_tests: int = 0
    failure_details: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "passed": self.passed,
            "duration_s": round(self.duration_s, 2),
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "error_tests": self.error_tests,
            "skipped_tests": self.skipped_tests,
            "failure_details": self.failure_details[:10],  # Top 10 failures
            "stdout_preview": self.stdout[:2000] if self.stdout else "",
            "stderr_preview": self.stderr[:2000] if self.stderr else "",
        }


class TestRunner:
    """
    Execute tests and parse results.
    Supports pytest, unittest, npm test, etc.
    """
    
    def __init__(self, work_dir: str, timeout: int = 300):
        self.work_dir = work_dir
        self.timeout = timeout
    
    async def run(self, command: str, env: Optional[Dict[str, str]] = None) -> TestResult:
        """Run a test command and parse results"""
        start = time.time()
        
        run_env = {**os.environ}
        if env:
            run_env.update(env)
        run_env["HOME"] = self.work_dir
        run_env["PWD"] = self.work_dir
        
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir,
                env=run_env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
            
            stdout_str = stdout.decode('utf-8', errors='replace')
            stderr_str = stderr.decode('utf-8', errors='replace')
            duration = time.time() - start
            
            # Parse test results
            result = TestResult(
                command=command,
                exit_code=proc.returncode,
                stdout=stdout_str,
                stderr=stderr_str,
                passed=(proc.returncode == 0),
                duration_s=duration,
            )
            
            # Try to parse structured output
            self._parse_pytest_output(result, stdout_str + stderr_str)
            
            return result
            
        except asyncio.TimeoutError:
            return TestResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=f"Test timed out after {self.timeout}s",
                passed=False,
                duration_s=time.time() - start,
            )
        except Exception as e:
            return TestResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                passed=False,
                duration_s=time.time() - start,
            )
    
    def _parse_pytest_output(self, result: TestResult, output: str):
        """Parse pytest-style output for structured results"""
        import re
        
        # Match pytest summary: "X passed, Y failed, Z error"
        summary_match = re.search(
            r'(\d+) passed(?:.*?(\d+) failed)?(?:.*?(\d+) error)?(?:.*?(\d+) skipped)?',
            output
        )
        if summary_match:
            result.passed_tests = int(summary_match.group(1) or 0)
            result.failed_tests = int(summary_match.group(2) or 0)
            result.error_tests = int(summary_match.group(3) or 0)
            result.skipped_tests = int(summary_match.group(4) or 0)
            result.total_tests = (
                result.passed_tests + result.failed_tests + 
                result.error_tests + result.skipped_tests
            )
        
        # Extract individual failure details
        failure_pattern = re.compile(
            r'FAILED\s+([\w/\.]+(?:::\w+)*)\s*-?\s*(.*?)(?=\n(?:FAILED|=====|$))',
            re.DOTALL
        )
        for match in failure_pattern.finditer(output):
            result.failure_details.append({
                "test": match.group(1).strip(),
                "reason": match.group(2).strip()[:500],
            })
        
        # Also try to find assertion errors
        assertion_pattern = re.compile(
            r'(AssertionError|assert\w*Error):\s*(.+?)(?=\n\n|\n(?:FAILED|=====|$))',
            re.DOTALL
        )
        for match in assertion_pattern.finditer(output):
            if not any(d.get("reason", "").startswith(match.group(2)[:50]) 
                      for d in result.failure_details):
                result.failure_details.append({
                    "test": "assertion",
                    "reason": f"{match.group(1)}: {match.group(2).strip()[:500]}",
                })


# =============================================================================
# Correctness Checker — Compare outputs (Feature #10, #11)
# =============================================================================

class CorrectnessChecker:
    """
    Verify correctness by comparing actual vs expected outputs.
    Used in debug cycles to detect regressions.
    """
    
    @staticmethod
    def compare_output(actual: str, expected: str) -> Dict[str, Any]:
        """Compare actual output against expected"""
        actual_lines = actual.strip().splitlines()
        expected_lines = expected.strip().splitlines()
        
        matches = actual.strip() == expected.strip()
        
        diff = list(difflib.unified_diff(
            expected_lines, actual_lines,
            fromfile="expected", tofile="actual",
            lineterm=""
        ))
        
        return {
            "matches": matches,
            "diff_lines": len(diff),
            "diff": "\n".join(diff[:50]),
            "actual_preview": actual[:500],
            "expected_preview": expected[:500],
        }
    
    @staticmethod
    def compare_files(actual_path: str, expected_path: str) -> Dict[str, Any]:
        """Compare two files for correctness"""
        try:
            with open(actual_path, 'r') as f:
                actual = f.read()
            with open(expected_path, 'r') as f:
                expected = f.read()
            result = CorrectnessChecker.compare_output(actual, expected)
            result["actual_path"] = actual_path
            result["expected_path"] = expected_path
            return result
        except FileNotFoundError as e:
            return {"error": str(e), "matches": False}
    
    @staticmethod
    def check_hash(file_path: str, expected_hash: str) -> Dict[str, Any]:
        """Check file hash matches expected"""
        try:
            with open(file_path, 'rb') as f:
                actual_hash = hashlib.sha256(f.read()).hexdigest()
            return {
                "matches": actual_hash == expected_hash,
                "actual_hash": actual_hash,
                "expected_hash": expected_hash,
            }
        except FileNotFoundError:
            return {"error": f"File not found: {file_path}", "matches": False}


# =============================================================================
# Debug Agent — Multi-step debug cycle (Feature #11)
# =============================================================================

class DebugAgent:
    """
    Automated debug cycle matching Claude Code's behavior:
    
    1. Run test → capture failure
    2. Read error → identify failing code
    3. Read file → understand context
    4. Fix → edit file
    5. Re-test → verify fix
    6. If still failing → deeper investigation
    7. If regression → revert and try different approach
    
    This is used by the AgenticLoop as a higher-level abstraction.
    """
    
    MAX_DEBUG_ITERATIONS = 14  # Match Claude Code's debug depth
    
    def __init__(self, work_dir: str, revert_manager: Optional[RevertManager] = None):
        self.work_dir = work_dir
        self.test_runner = TestRunner(work_dir)
        self.revert_manager = revert_manager or RevertManager()
        self.correctness = CorrectnessChecker()
        self.debug_history: List[Dict[str, Any]] = []
    
    async def run_and_debug(
        self,
        test_command: str,
        max_iterations: int = 5,
        reference_output: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run test and debug loop.
        Returns structured result suitable for display.
        """
        iteration = 0
        all_results = []
        
        while iteration < min(max_iterations, self.MAX_DEBUG_ITERATIONS):
            iteration += 1
            
            # Run test
            result = await self.test_runner.run(test_command)
            all_results.append(result.to_dict())
            
            # Check correctness
            if reference_output and result.passed:
                check = self.correctness.compare_output(
                    result.stdout, reference_output
                )
                if not check["matches"]:
                    result.passed = False
                    result.failure_details.append({
                        "test": "correctness_check",
                        "reason": f"Output mismatch: {check['diff'][:300]}",
                    })
            
            if result.passed:
                return {
                    "success": True,
                    "iterations": iteration,
                    "final_result": result.to_dict(),
                    "all_results": all_results,
                    "display": f"Tests passed after {iteration} iteration(s)",
                }
            
            # Record the failure for analysis
            self.debug_history.append({
                "iteration": iteration,
                "exit_code": result.exit_code,
                "failures": result.failure_details[:5],
                "stderr_head": result.stderr[:500],
            })
        
        return {
            "success": False,
            "iterations": iteration,
            "final_result": all_results[-1] if all_results else {},
            "all_results": all_results,
            "display": f"Failed after {iteration} debug iterations",
            "debug_history": self.debug_history,
        }
    
    async def diagnose(self, test_result: TestResult) -> Dict[str, Any]:
        """
        Analyze a test failure and produce a diagnosis.
        Returns structured info the AI can use to fix the issue.
        """
        diagnosis = {
            "error_type": "unknown",
            "likely_files": [],
            "error_summary": "",
            "suggested_actions": [],
        }
        
        combined = f"{test_result.stdout}\n{test_result.stderr}"
        
        # Parse file references from traceback
        import re
        file_refs = re.findall(
            r'File "([^"]+)", line (\d+)',
            combined
        )
        seen = set()
        for fpath, line in file_refs:
            if fpath.startswith(self.work_dir) and fpath not in seen:
                seen.add(fpath)
                diagnosis["likely_files"].append({
                    "path": fpath,
                    "line": int(line),
                })
        
        # Categorize error type
        if "ImportError" in combined or "ModuleNotFoundError" in combined:
            diagnosis["error_type"] = "import_error"
            diagnosis["suggested_actions"] = [
                "Check import paths",
                "Verify dependencies installed",
                "Check __init__.py files",
            ]
        elif "SyntaxError" in combined:
            diagnosis["error_type"] = "syntax_error"
            diagnosis["suggested_actions"] = [
                "Fix syntax at indicated line",
                "Check for unclosed brackets/strings",
            ]
        elif "AssertionError" in combined or "assert" in combined.lower():
            diagnosis["error_type"] = "assertion_error"
            diagnosis["suggested_actions"] = [
                "Compare actual vs expected values",
                "Check test assumptions",
                "Verify computation logic",
            ]
        elif "TypeError" in combined:
            diagnosis["error_type"] = "type_error"
            diagnosis["suggested_actions"] = [
                "Check function signatures",
                "Verify argument types",
            ]
        elif "KeyError" in combined or "IndexError" in combined:
            diagnosis["error_type"] = "data_error"
            diagnosis["suggested_actions"] = [
                "Check data structure access",
                "Add boundary checks",
            ]
        elif test_result.exit_code != 0:
            diagnosis["error_type"] = "runtime_error"
            diagnosis["suggested_actions"] = [
                "Read full error traceback",
                "Check environment setup",
            ]
        
        # Error summary
        error_lines = [l for l in combined.splitlines() if "Error" in l or "error" in l.lower()]
        diagnosis["error_summary"] = "\n".join(error_lines[:5])
        
        return diagnosis
    
    def get_debug_summary(self) -> Dict[str, Any]:
        """Get summary of all debug iterations"""
        return {
            "total_iterations": len(self.debug_history),
            "history": self.debug_history[-10:],
            "revert_history": self.revert_manager.get_history(limit=10),
        }


# =============================================================================
# Diff Tracker — Detailed change accounting (Feature #8-9, #12, #14)
# =============================================================================

class DiffTracker:
    """
    Track file changes with detailed +N/-M accounting.
    Used for Claude Code-style display: "perf_takehome.py, +3, -4"
    """
    
    def __init__(self):
        self.changes: List[Dict[str, Any]] = []
    
    def record_change(
        self,
        path: str,
        old_content: str,
        new_content: str,
        description: str = "",
    ) -> Dict[str, Any]:
        """Record a file change and compute diff stats"""
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
        added = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
        removed = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))
        
        change = {
            "path": path,
            "filename": os.path.basename(path),
            "added": added,
            "removed": removed,
            "display": f"{os.path.basename(path)}, +{added}, -{removed}",
            "description": description,
            "timestamp": time.time(),
            "unified_diff": "\n".join(diff[:100]),
        }
        
        self.changes.append(change)
        return change
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all tracked changes"""
        total_added = sum(c["added"] for c in self.changes)
        total_removed = sum(c["removed"] for c in self.changes)
        unique_files = len(set(c["path"] for c in self.changes))
        
        return {
            "total_changes": len(self.changes),
            "unique_files": unique_files,
            "total_added": total_added,
            "total_removed": total_removed,
            "display": f"{unique_files} files changed, +{total_added}, -{total_removed}",
            "changes": [
                {
                    "filename": c["filename"],
                    "added": c["added"],
                    "removed": c["removed"],
                    "display": c["display"],
                    "description": c["description"],
                }
                for c in self.changes[-30:]
            ],
        }
    
    def get_file_changes(self, path: str) -> List[Dict[str, Any]]:
        """Get all changes for a specific file"""
        return [c for c in self.changes if c["path"] == path]
