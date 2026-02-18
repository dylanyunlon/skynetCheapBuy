"""
Skynet Agentic Loop - FastAPI Server
=====================================
REST API + SSE streaming for the agentic loop.
Provides endpoints matching Claude Code's feature set.
"""

import asyncio
import json
import os
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any

# Import core components
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core import (
    AgentLoop, ToolRegistry, ContextManager, EventQueue,
    LoopStatus,
)
from backend.tools import register_all_tools


# === App Setup ===
app = FastAPI(
    title="Skynet Agentic Loop API",
    description="Claude Code-style agentic loop with tool execution and SSE streaming",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Global state ===
tool_registry = ToolRegistry()
register_all_tools(tool_registry)
event_queue = EventQueue()
context_manager = ContextManager()

# Active sessions
sessions: Dict[str, AgentLoop] = {}


# === Request/Response Models ===

class AgentRequest(BaseModel):
    """Request to start an agentic loop"""
    message: str = Field(..., description="User message / task description")
    session_id: Optional[str] = Field(None, description="Session ID for continuation")
    system_prompt: Optional[str] = Field(None, description="Custom system prompt")
    working_dir: Optional[str] = Field(None, description="Working directory for commands")
    max_iterations: int = Field(50, description="Max loop iterations")


class ToolExecuteRequest(BaseModel):
    """Direct tool execution request"""
    tool_name: str
    arguments: Dict[str, Any] = {}


class InterruptRequest(BaseModel):
    """Interrupt a running session"""
    session_id: str


class SteeringRequest(BaseModel):
    """Inject a steering message mid-task"""
    session_id: str
    message: str


# === Endpoints ===

@app.get("/")
async def root():
    return {
        "service": "Skynet Agentic Loop",
        "version": "1.0.0",
        "features": [
            "agentic_loop",
            "tool_execution",
            "sse_streaming",
            "file_operations",
            "command_execution",
            "web_search",
            "context_management",
        ],
    }


@app.get("/api/tools")
async def list_tools():
    """List all available tools"""
    return {
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "risk_level": tool.risk_level,
            }
            for tool in tool_registry._tools.values()
        ]
    }


@app.post("/api/agent/run")
async def run_agent(request: AgentRequest):
    """
    Start an agentic loop and return SSE stream.
    
    This is the main endpoint - equivalent to sending a message in Claude Code.
    Returns Server-Sent Events for real-time streaming of the loop execution.
    """
    session_id = request.session_id or str(uuid.uuid4())
    
    agent_loop = AgentLoop(
        tool_registry=tool_registry,
        context_manager=context_manager,
        event_queue=event_queue,
        max_iterations=request.max_iterations,
    )
    sessions[session_id] = agent_loop
    
    async def event_generator():
        try:
            async for event in agent_loop.run(
                user_message=request.message,
                system_prompt=request.system_prompt,
                session_id=session_id,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}})}\n\n"
        finally:
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-Id": session_id,
        },
    )


@app.post("/api/agent/run-sync")
async def run_agent_sync(request: AgentRequest):
    """
    Run agent loop synchronously (non-streaming).
    Returns complete results when done.
    """
    session_id = request.session_id or str(uuid.uuid4())
    
    agent_loop = AgentLoop(
        tool_registry=tool_registry,
        context_manager=context_manager,
        event_queue=event_queue,
        max_iterations=request.max_iterations,
    )
    
    events = []
    async for event in agent_loop.run(
        user_message=request.message,
        system_prompt=request.system_prompt,
        session_id=session_id,
    ):
        events.append(event)
    
    return {"session_id": session_id, "events": events}


@app.post("/api/tool/execute")
async def execute_tool(request: ToolExecuteRequest):
    """
    Execute a single tool directly.
    Useful for testing and direct tool access.
    """
    try:
        result = await tool_registry.execute(request.tool_name, request.arguments)
        return {"success": True, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agent/interrupt")
async def interrupt_agent(request: InterruptRequest):
    """Interrupt a running agentic loop"""
    agent = sessions.get(request.session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Session not found")
    agent.interrupt()
    return {"success": True, "message": "Interrupt signal sent"}


@app.post("/api/agent/steer")
async def steer_agent(request: SteeringRequest):
    """Inject a steering message into a running session"""
    event_queue.inject_steering(request.message)
    return {"success": True, "message": "Steering message injected"}


@app.get("/api/events/stream")
async def event_stream():
    """
    Global SSE event stream.
    Subscribe to all agentic loop events in real-time.
    """
    subscriber = event_queue.subscribe()
    
    async def generator():
        try:
            async for event in event_queue.listen(subscriber):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            event_queue.unsubscribe(subscriber)
    
    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/events/history")
async def event_history(since: int = Query(0, description="Sequence number to fetch from")):
    """Get event history"""
    return {"events": event_queue.get_history(since)}


# === File operation shortcuts (matching Claude Code UI actions) ===

@app.post("/api/file/read")
async def api_read_file(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None):
    """Read a file - shortcut for the read_file tool"""
    result = await tool_registry.execute("read_file", {
        "path": path, "start_line": start_line, "end_line": end_line
    })
    return result


@app.post("/api/file/view-truncated")
async def api_view_truncated(path: str, section: str = "middle"):
    """View truncated section - Feature #2"""
    result = await tool_registry.execute("view_truncated", {
        "path": path, "section": section
    })
    return result


@app.post("/api/file/view-multiple")
async def api_view_multiple(paths: List[str]):
    """View multiple files - Feature #3"""
    result = await tool_registry.execute("view_files", {"paths": paths})
    return result


@app.post("/api/file/edit")
async def api_edit_file(path: str, old_str: str, new_str: str, description: str = ""):
    """Edit a file - Feature #8-9"""
    result = await tool_registry.execute("edit_file", {
        "path": path, "old_str": old_str, "new_str": new_str, "description": description
    })
    return result


@app.post("/api/command/run")
async def api_run_command(command: str, working_dir: Optional[str] = None, description: str = ""):
    """Run a command - Features #6-7"""
    result = await tool_registry.execute("bash", {
        "command": command, "working_dir": working_dir, "description": description
    })
    return result


@app.post("/api/search/web")
async def api_web_search(query: str, max_results: int = 10):
    """Web search - Feature #4"""
    result = await tool_registry.execute("web_search", {
        "query": query, "max_results": max_results
    })
    return result


@app.post("/api/search/fetch")
async def api_web_fetch(url: str):
    """Fetch webpage - Feature #5"""
    result = await tool_registry.execute("web_fetch", {"url": url})
    return result


# === Health check ===
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "tools_count": len(tool_registry.list_tools()),
        "active_sessions": len(sessions),
        "timestamp": time.time(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
