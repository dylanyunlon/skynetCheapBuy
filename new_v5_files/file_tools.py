"""
File Tools - Read, Write, Edit, MultiEdit, ViewTruncated
=========================================================
Implements Claude Code's file operation tools:
- read_file: Read entire file or line range
- write_file: Create new file with content
- edit_file: Edit file with str_replace (single replacement)
- multi_edit: Multiple edits in one call
- view_truncated: View truncated section of a file (Feature #2 from requirements)
- view_files: Batch view multiple files (Feature #3)
"""

import os
import difflib
from typing import Any, Dict, List, Optional, Tuple


async def read_file(
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    description: str = "",
) -> Dict[str, Any]:
    """
    Read a file's contents, optionally a specific line range.
    
    Returns:
        dict with content, total_lines, truncated info
    """
    if not os.path.exists(path):
        return {"error": f"File not found: {path}", "success": False}
    
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return {"error": str(e), "success": False}
    
    total_lines = len(lines)
    
    if start_line is not None or end_line is not None:
        start = (start_line or 1) - 1  # Convert to 0-indexed
        end = end_line or total_lines
        selected_lines = lines[start:end]
        content = "".join(selected_lines)
        is_truncated = start > 0 or end < total_lines
    else:
        # Auto-truncate large files (like Claude Code does)
        MAX_LINES = 500
        if total_lines > MAX_LINES:
            # Show first 200 and last 200 lines
            head = lines[:200]
            tail = lines[-200:]
            content = (
                "".join(head) + 
                f"\n... [{total_lines - 400} lines truncated] ...\n" +
                "".join(tail)
            )
            is_truncated = True
        else:
            content = "".join(lines)
            is_truncated = False
    
    return {
        "success": True,
        "content": content,
        "total_lines": total_lines,
        "is_truncated": is_truncated,
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
    }


async def view_truncated(
    path: str,
    section: str = "middle",
    description: str = "",
) -> Dict[str, Any]:
    """
    View a truncated section of a file.
    Implements Feature #2: "View truncated section of xxx.py"
    
    Args:
        path: File path
        section: Which section to view - "start", "middle", "end", or line range "100-200"
    """
    if not os.path.exists(path):
        return {"error": f"File not found: {path}", "success": False}
    
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return {"error": str(e), "success": False}
    
    total_lines = len(lines)
    
    if section == "start":
        start, end = 0, min(200, total_lines)
    elif section == "end":
        start, end = max(0, total_lines - 200), total_lines
    elif section == "middle":
        mid = total_lines // 2
        start = max(0, mid - 100)
        end = min(total_lines, mid + 100)
    elif "-" in section:
        try:
            parts = section.split("-")
            start = int(parts[0]) - 1
            end = int(parts[1])
        except (ValueError, IndexError):
            start, end = 0, min(200, total_lines)
    else:
        start, end = 0, min(200, total_lines)
    
    selected = lines[start:end]
    content = "".join(selected)
    
    return {
        "success": True,
        "content": content,
        "total_lines": total_lines,
        "viewed_range": {"start": start + 1, "end": end},
        "path": path,
        "display_title": f"View truncated section of {os.path.basename(path)}",
    }


async def view_files(
    paths: List[str],
    description: str = "",
) -> Dict[str, Any]:
    """
    Batch view multiple files.
    Implements Feature #3: "Viewed 3 files"
    
    Returns summary of all viewed files.
    """
    results = []
    for path in paths:
        result = await read_file(path=path)
        results.append({
            "path": path,
            "success": result["success"],
            "total_lines": result.get("total_lines", 0),
            "is_truncated": result.get("is_truncated", False),
            "preview": result.get("content", "")[:500] if result["success"] else result.get("error", ""),
        })
    
    return {
        "success": True,
        "files_count": len(results),
        "files": results,
        "display_title": f"Viewed {len(results)} files",
    }


async def write_file(
    path: str,
    content: str,
    description: str = "",
) -> Dict[str, Any]:
    """Write content to a new file"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        
        return {
            "success": True,
            "path": path,
            "additions": line_count,
            "deletions": 0,
            "file": path,
            "display_title": f"Created {os.path.basename(path)}",
            "display_detail": f"+{line_count}",
        }
    except Exception as e:
        return {"error": str(e), "success": False}


async def edit_file(
    path: str,
    old_str: str,
    new_str: str,
    description: str = "",
) -> Dict[str, Any]:
    """
    Edit a file by replacing a unique string.
    Implements Feature #8-9: File editing with +N, -N display.
    
    Like Claude Code's Edit tool - the old_str must appear exactly once.
    """
    if not os.path.exists(path):
        return {"error": f"File not found: {path}", "success": False}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            original_content = f.read()
    except Exception as e:
        return {"error": str(e), "success": False}
    
    # Verify old_str appears exactly once
    count = original_content.count(old_str)
    if count == 0:
        return {"error": f"String not found in {path}", "success": False}
    if count > 1:
        return {"error": f"String appears {count} times in {path}, must be unique", "success": False}
    
    # Perform replacement
    new_content = original_content.replace(old_str, new_str, 1)
    
    # Calculate diff stats
    old_lines = old_str.split("\n")
    new_lines = new_str.split("\n")
    additions = len(new_lines)
    deletions = len(old_lines)
    
    # Write back
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    
    # Generate unified diff for display
    diff = list(difflib.unified_diff(
        original_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{os.path.basename(path)}",
        tofile=f"b/{os.path.basename(path)}",
        lineterm="",
    ))
    
    return {
        "success": True,
        "path": path,
        "file": path,
        "additions": additions,
        "deletions": deletions,
        "diff": "".join(diff[:50]),  # First 50 lines of diff
        "display_title": f"{description or 'Edit'}\n{os.path.basename(path)}, +{additions}, -{deletions}",
    }


async def multi_edit(
    path: str,
    edits: List[Dict[str, str]],
    description: str = "",
) -> Dict[str, Any]:
    """
    Multiple edits on a single file in one call.
    
    Args:
        path: File path
        edits: List of {"old_str": "...", "new_str": "..."} dicts
    """
    if not os.path.exists(path):
        return {"error": f"File not found: {path}", "success": False}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return {"error": str(e), "success": False}
    
    original = content
    total_additions = 0
    total_deletions = 0
    
    for edit in edits:
        old_str = edit["old_str"]
        new_str = edit["new_str"]
        
        if old_str not in content:
            return {"error": f"String not found: {old_str[:50]}...", "success": False}
        
        content = content.replace(old_str, new_str, 1)
        total_additions += len(new_str.split("\n"))
        total_deletions += len(old_str.split("\n"))
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    
    return {
        "success": True,
        "path": path,
        "file": path,
        "edits_applied": len(edits),
        "additions": total_additions,
        "deletions": total_deletions,
        "display_title": f"{description}\n{os.path.basename(path)}, +{total_additions}, -{total_deletions}",
    }


# Tool definitions for registration
FILE_TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "Read a file's contents, optionally a specific line range",
        "handler": read_file,
        "category": "file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"},
                "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
                "end_line": {"type": "integer", "description": "End line (inclusive)"},
                "description": {"type": "string", "description": "Why reading this file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "view_truncated",
        "description": "View a truncated section of a large file",
        "handler": view_truncated,
        "category": "file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "section": {"type": "string", "description": "Section: 'start', 'middle', 'end', or '100-200'"},
                "description": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "view_files",
        "description": "Batch view multiple files at once",
        "handler": view_files,
        "category": "file",
        "parameters": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "List of file paths"},
                "description": {"type": "string"},
            },
            "required": ["paths"],
        },
    },
    {
        "name": "write_file",
        "description": "Create a new file with content",
        "handler": write_file,
        "category": "edit",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to create"},
                "content": {"type": "string", "description": "File content"},
                "description": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Edit file by replacing a unique string occurrence",
        "handler": edit_file,
        "category": "edit",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_str": {"type": "string", "description": "Unique string to replace"},
                "new_str": {"type": "string", "description": "Replacement string"},
                "description": {"type": "string"},
            },
            "required": ["path", "old_str", "new_str"],
        },
    },
    {
        "name": "multi_edit",
        "description": "Apply multiple edits to a single file",
        "handler": multi_edit,
        "category": "edit",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_str": {"type": "string"},
                            "new_str": {"type": "string"},
                        },
                        "required": ["old_str", "new_str"],
                    },
                },
                "description": {"type": "string"},
            },
            "required": ["path", "edits"],
        },
    },
]
