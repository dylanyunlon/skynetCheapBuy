"""
Search Tools - Web search, grep, glob
======================================
Implements:
- web_search: Search the web (Feature #4: "Searched the web")
- web_fetch: Fetch webpage content (Feature #5: "Fetched: ...")
- grep: Search file contents using regex
- glob: Find files by pattern
- ls: List directory contents
"""

import asyncio
import os
import re
import glob as glob_module
import json
from typing import Any, Dict, List, Optional
from pathlib import Path


async def web_search(
    query: str,
    max_results: int = 10,
    description: str = "",
) -> Dict[str, Any]:
    """
    Search the web.
    
    Implements Feature #4: "Searched the web" with results display.
    Uses external search API (configurable).
    """
    # In production, integrate with actual search API
    # For now, use a simple HTTP request approach
    try:
        import aiohttp
        
        # Use a search API (e.g., SerpAPI, Brave Search, or custom)
        search_url = os.environ.get("SEARCH_API_URL", "")
        search_key = os.environ.get("SEARCH_API_KEY", "")
        
        if search_url and search_key:
            async with aiohttp.ClientSession() as session:
                params = {"q": query, "count": max_results, "key": search_key}
                async with session.get(search_url, params=params) as resp:
                    data = await resp.json()
                    results = data.get("results", [])
        else:
            # Fallback: mock results for development
            results = [{
                "title": f"Search result for: {query}",
                "url": "https://example.com",
                "snippet": "Configure SEARCH_API_URL and SEARCH_API_KEY for real results.",
            }]
        
        formatted_results = []
        for r in results[:max_results]:
            formatted_results.append({
                "title": r.get("title", ""),
                "url": r.get("url", r.get("link", "")),
                "snippet": r.get("snippet", r.get("description", "")),
                "domain": _extract_domain(r.get("url", r.get("link", ""))),
            })
        
        return {
            "success": True,
            "query": query,
            "results_count": len(formatted_results),
            "results": formatted_results,
            "display_title": "Searched the web",
            "display_detail": f"{query}\n\n{len(formatted_results)} results",
        }
        
    except ImportError:
        return {
            "success": False,
            "error": "aiohttp not installed. Run: pip install aiohttp",
            "query": query,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "query": query,
        }


async def web_fetch(
    url: str,
    max_length: int = 50000,
    description: str = "",
) -> Dict[str, Any]:
    """
    Fetch and extract content from a webpage.
    
    Implements Feature #5: "Fetched: Anthropic's original take home assignment"
    """
    try:
        import aiohttp
        from html.parser import HTMLParser
        
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; SkynetBot/1.0)",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                html = await resp.text()
                content_type = resp.headers.get("content-type", "")
        
        # Simple HTML to text extraction
        text = _html_to_text(html)
        
        if len(text) > max_length:
            text = text[:max_length] + f"\n... [truncated, {len(text)} total chars]"
        
        # Extract title
        title = _extract_title(html)
        
        return {
            "success": True,
            "url": url,
            "title": title,
            "content": text,
            "content_length": len(text),
            "content_type": content_type,
            "display_title": f"Fetched: {title or url}",
        }
        
    except ImportError:
        return {"success": False, "error": "aiohttp not installed", "url": url}
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}


async def grep(
    pattern: str,
    path: str = ".",
    include: Optional[str] = None,
    max_results: int = 50,
    context_lines: int = 2,
    description: str = "",
) -> Dict[str, Any]:
    """
    Search file contents using regex pattern.
    Like Claude Code's Grep tool (uses ripgrep under the hood).
    """
    try:
        # Try ripgrep first (faster)
        cmd = f"rg --json -m {max_results}"
        if include:
            cmd += f" --glob '{include}'"
        cmd += f" -C {context_lines}"
        cmd += f" '{pattern}' {path}"
        
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        
        if process.returncode == 0:
            matches = _parse_rg_output(stdout.decode("utf-8", errors="replace"))
        elif process.returncode == 1:
            # No matches
            matches = []
        else:
            # Fallback to grep
            matches = await _fallback_grep(pattern, path, include, max_results, context_lines)
        
        return {
            "success": True,
            "pattern": pattern,
            "path": path,
            "matches_count": len(matches),
            "matches": matches[:max_results],
            "display_title": f"Grep: {pattern}",
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "pattern": pattern,
            "path": path,
        }


async def glob_search(
    pattern: str,
    path: str = ".",
    description: str = "",
) -> Dict[str, Any]:
    """
    Find files matching a glob pattern.
    Like Claude Code's Glob tool.
    """
    try:
        full_pattern = os.path.join(path, pattern)
        matches = glob_module.glob(full_pattern, recursive=True)
        
        results = []
        for match in sorted(matches)[:100]:
            stat = os.stat(match)
            results.append({
                "path": match,
                "name": os.path.basename(match),
                "size": stat.st_size,
                "is_dir": os.path.isdir(match),
            })
        
        return {
            "success": True,
            "pattern": pattern,
            "matches_count": len(results),
            "matches": results,
        }
        
    except Exception as e:
        return {"success": False, "error": str(e), "pattern": pattern}


async def ls(
    path: str = ".",
    depth: int = 2,
    description: str = "",
) -> Dict[str, Any]:
    """
    List directory contents.
    Like Claude Code's LS tool.
    """
    try:
        if not os.path.exists(path):
            return {"error": f"Path not found: {path}", "success": False}
        
        entries = []
        for entry in sorted(os.listdir(path)):
            if entry.startswith(".") or entry == "node_modules" or entry == "__pycache__":
                continue
            
            full_path = os.path.join(path, entry)
            is_dir = os.path.isdir(full_path)
            
            entry_info = {
                "name": entry,
                "path": full_path,
                "is_dir": is_dir,
            }
            
            if not is_dir:
                try:
                    entry_info["size"] = os.path.getsize(full_path)
                except OSError:
                    pass
            
            entries.append(entry_info)
        
        return {
            "success": True,
            "path": path,
            "entries_count": len(entries),
            "entries": entries,
        }
        
    except Exception as e:
        return {"success": False, "error": str(e), "path": path}


# === Helper functions ===

def _extract_domain(url: str) -> str:
    """Extract domain from URL"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc
    except Exception:
        return url


def _extract_title(html: str) -> str:
    """Extract title from HTML"""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _html_to_text(html: str) -> str:
    """Simple HTML to text conversion"""
    # Remove scripts and styles
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&quot;", '"')
    # Clean whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_rg_output(output: str) -> List[Dict]:
    """Parse ripgrep JSON output"""
    matches = []
    for line in output.strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("type") == "match":
                match_data = data.get("data", {})
                matches.append({
                    "file": match_data.get("path", {}).get("text", ""),
                    "line_number": match_data.get("line_number", 0),
                    "text": match_data.get("lines", {}).get("text", "").strip(),
                })
        except json.JSONDecodeError:
            continue
    return matches


async def _fallback_grep(
    pattern: str, path: str, include: Optional[str],
    max_results: int, context_lines: int,
) -> List[Dict]:
    """Fallback to system grep if ripgrep not available"""
    cmd = f"grep -rn"
    if include:
        cmd += f" --include='{include}'"
    cmd += f" -m {max_results} -C {context_lines}"
    cmd += f" '{pattern}' {path}"
    
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    
    matches = []
    for line in stdout.decode("utf-8", errors="replace").split("\n"):
        if ":" in line:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append({
                    "file": parts[0],
                    "line_number": int(parts[1]) if parts[1].isdigit() else 0,
                    "text": parts[2].strip(),
                })
    return matches


# Tool definitions
SEARCH_TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": "Search the web for information",
        "handler": web_search,
        "category": "search",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (default 10)"},
                "description": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": "Fetch and extract content from a webpage URL",
        "handler": web_fetch,
        "category": "fetch",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_length": {"type": "integer"},
                "description": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "grep",
        "description": "Search file contents using regex pattern",
        "handler": grep,
        "category": "search",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern"},
                "path": {"type": "string", "description": "Search path (default: .)"},
                "include": {"type": "string", "description": "File glob pattern to include"},
                "max_results": {"type": "integer"},
                "context_lines": {"type": "integer"},
                "description": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "glob",
        "description": "Find files matching a glob pattern",
        "handler": glob_search,
        "category": "search",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g., **/*.py)"},
                "path": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "ls",
        "description": "List directory contents",
        "handler": ls,
        "category": "view",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
                "depth": {"type": "integer"},
                "description": {"type": "string"},
            },
        },
    },
]
