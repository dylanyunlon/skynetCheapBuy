from fastapi import APIRouter, WebSocket, Depends, Query
from typing import Optional
import logging

from app.dependencies import get_current_user_ws
from app.api.websocket_handlers.terminal_ws import terminal_endpoint

router = APIRouter(prefix="/api/v2/terminal", tags=["terminal"])
logger = logging.getLogger(__name__)

@router.websocket("/{project_id}")
async def project_terminal(
    websocket: WebSocket,
    project_id: str,
    token: Optional[str] = Query(None)
):
    """项目终端 WebSocket 端点"""
    # token 通过查询参数传递，因为 WebSocket 不支持标准的 Authorization header
    await terminal_endpoint(websocket, project_id, token)