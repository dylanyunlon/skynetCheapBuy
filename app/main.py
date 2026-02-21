# app/main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import sys

# 导入现有路由
from app.api import auth, chat, users, files, models, websocket, conversations, code
from app.api import chat_v2, enhanced_chat, code_management

# 导入新的 v2 路由
from app.api.v2 import chat as v2_chat

# 其他导入
from app.core.rate_limit import rate_limit_middleware
from app.config import settings
from app.utils.i18n import init_translations
from app.db.init_db import check_tables_exist, init_db, init_data
from app.api.v2 import vibe
from app.api.v2.benchmark import router as benchmark_router


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/app.log")
    ]
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("Starting ChatBot API with Vibe Coding Architecture...")
    
    # 检查并初始化数据库
    if not check_tables_exist():
        logger.info("Database tables not found, initializing...")
        init_db()
        
        # 在开发环境下自动创建测试数据
        if settings.ENVIRONMENT == "development":
            logger.info("Creating test data...")
            init_data()
    
    # 初始化翻译
    init_translations()
    
    # 初始化Redis连接池
    from app.db.session import init_redis
    await init_redis()
    
    # 初始化新架构组件
    logger.info("Initializing Vibe Coding components...")
    try:
        # 预热意图识别引擎
        from app.core.intent.engine import IntentEngine
        intent_engine = IntentEngine()
        logger.info("Intent engine initialized successfully")
        
        # 预热Chat路由器
        from app.core.chat.router import ChatRouter
        from app.core.ai_engine import AIEngine
        from app.services.chat_service import ChatService
        from app.db.session import SessionLocal
        from app.db.redis import get_redis
        
        # 创建测试实例以验证组件
        db = SessionLocal()
        redis = await get_redis()
        chat_service = ChatService(db, redis)
        ai_engine = AIEngine()
        chat_router = ChatRouter(chat_service, ai_engine)
        
        db.close()
        logger.info("Chat router initialized successfully")
        
    except Exception as e:
        logger.warning(f"Failed to initialize some Vibe Coding components: {e}")
        # 不阻止应用启动，只记录警告
    
    yield
    
    # 关闭时
    logger.info("Shutting down ChatBot API...")
    
    # 关闭Redis连接
    from app.db.session import close_redis
    await close_redis()

# 创建FastAPI应用
app = FastAPI(
    title="ChatBot API - Vibe Coding Edition",
    description="AI聊天机器人Web服务API - 支持项目感知对话和智能代码生成",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# 配置CORS - 修改为不包含通配符
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://8.163.12.28:5173",
    "https://baloonet.tech",
    "https://baloonet.tech:17432",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # 使用具体的源列表，不使用通配符
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# 配置可信主机
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS
)

# 添加速率限制中间件
app.middleware("http")(rate_limit_middleware)

# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )
    
app.include_router(benchmark_router)

# 注册V2统一架构路由 - 优先级最高
logger.info("Registering V2 Unified Architecture routes...")
app.include_router(v2_chat.router, tags=["V2-Unified"])

# 注册现有路由 - 保持兼容性
logger.info("Registering legacy routes for compatibility...")
app.include_router(auth.router, tags=["Legacy-Auth"])
app.include_router(chat.router, tags=["Legacy-Chat"])
app.include_router(chat_v2.router, tags=["Legacy-ChatV2"])
app.include_router(enhanced_chat.router, tags=["Legacy-Enhanced"])
app.include_router(users.router, tags=["Legacy-Users"])
app.include_router(files.router, tags=["Legacy-Files"])
app.include_router(models.router, tags=["Legacy-Models"])
app.include_router(websocket.router, tags=["Legacy-WebSocket"])
app.include_router(conversations.router, tags=["Legacy-Conversations"])
app.include_router(code.router, tags=["Legacy-Code"])
app.include_router(code_management.router, tags=["Legacy-CodeMgmt"])
app.include_router(vibe.router)  
# 注册其他 v2 路由（如果存在）
try:
    from app.api.v2 import agent, workspace, terminal, debug
    app.include_router(agent.router, tags=["V2-Agent"])
    app.include_router(workspace.router, tags=["V2-Workspace"])
    app.include_router(terminal.router, tags=["V2-Terminal"])
    app.include_router(debug.router, tags=["V2-Debug"])
    logger.info("Additional V2 routes registered successfully")
except ImportError as e:
    logger.info(f"Some V2 routes not available yet: {e}")

# 健康检查端点
@app.get("/health")
async def health_check():
    """健康检查"""
    try:
        # 检查数据库连接
        from app.db.session import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        db_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "unhealthy"
    
    try:
        # 检查Redis连接
        from app.db.redis import get_redis
        redis = await get_redis()
        await redis.ping()
        redis_status = "healthy"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        redis_status = "unhealthy"
    
    # 检查AI引擎
    try:
        from app.core.ai_engine import AIEngine
        ai_engine = AIEngine()
        ai_status = "healthy" if ai_engine.providers else "no_providers"
    except Exception as e:
        logger.error(f"AI engine health check failed: {e}")
        ai_status = "unhealthy"
    
    overall_status = "healthy" if all([
        db_status == "healthy",
        redis_status == "healthy",
        ai_status in ["healthy", "no_providers"]
    ]) else "unhealthy"
    
    return {
        "status": overall_status,
        "version": "2.0.0",
        "service": "ChatBot API - Vibe Coding Edition",
        "components": {
            "database": db_status,
            "redis": redis_status,
            "ai_engine": ai_status
        },
        "features": {
            "unified_chat": True,
            "intent_recognition": True,
            "project_awareness": True,
            "code_generation": True,
            "file_operations": True,
            "legacy_compatibility": True
        }
    }

# API信息端点
@app.get("/")
async def root():
    """API根端点"""
    return {
        "message": "Welcome to ChatBot API - Vibe Coding Edition",
        "version": "2.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "features": {
            "🤖": "智能意图识别",
            "📁": "项目感知对话", 
            "⚡": "实时代码生成",
            "🔧": "工作空间管理",
            "🔄": "向后兼容性"
        },
        "endpoints": {
            "unified_chat": "/api/v2/chat",
            "stream_chat": "/api/v2/chat/stream",
            "legacy_chat": "/api/chat/v2/message",
            "health": "/health"
        }
    }

# API架构信息端点
@app.get("/api/info")
async def api_info():
    """API架构信息"""
    return {
        "architecture": "Vibe Coding",
        "version": "2.0.0",
        "description": "Unified chat interface with project awareness and intelligent code generation",
        "components": {
            "intent_engine": {
                "description": "智能意图识别引擎",
                "supported_intents": [
                    "general_chat",
                    "project_create",
                    "project_modify", 
                    "code_generation",
                    "file_operation",
                    "project_execution",
                    "code_execution",
                    "cron_setup"
                ]
            },
            "chat_router": {
                "description": "统一对话路由器",
                "features": [
                    "智能意图分发",
                    "项目上下文感知",
                    "降级处理",
                    "流式响应"
                ]
            },
            "project_integration": {
                "description": "项目感知对话系统",
                "capabilities": [
                    "项目创建建议",
                    "代码生成到项目",
                    "文件管理",
                    "执行和调试"
                ]
            }
        },
        "migration": {
            "legacy_support": True,
            "backward_compatibility": True,
            "migration_path": "Gradual migration from /api/chat/v2/* to /api/v2/chat"
        }
    }
try:
    # 尝试导入 Vibe Coding 路由
    logger.info("Attempting to import Vibe Coding routes...")
    
    # 导入我们创建的 Vibe Coding 处理器
    from app.core.vibe.vibe_coding_processor import VibeCodingProcessor
    from app.core.vibe.prompt_orchestrator import PromptOrchestrator
    from app.services.vibe_project_service import VibeProjectService
    
    # 创建简化的 Vibe Coding API 端点
    from fastapi import APIRouter, HTTPException, Depends
    from pydantic import BaseModel
    from typing import Optional, Dict, Any
    
    # 创建 Vibe Coding 路由器
    vibe_router = APIRouter(prefix="/api/v2/vibe", tags=["Vibe-Coding"])
    
    class VibeCodingRequest(BaseModel):
        content: str
        conversation_id: str
        stage: str = "meta"  # "meta" 或 "generate"
        meta_result: Optional[Dict[str, Any]] = None
        optimized_prompt: Optional[str] = None
        original_user_input: Optional[str] = None
    
    @vibe_router.post("/process")
    async def process_vibe_coding(
        request: VibeCodingRequest,
        current_user = Depends(get_current_user),
        db = Depends(get_db)
    ):
        """统一的 Vibe Coding 处理端点"""
        try:
            # 创建处理器实例
            from app.core.ai_engine import AIEngine
            from app.core.workspace.workspace_manager import WorkspaceManager
            
            ai_engine = AIEngine()
            prompt_orchestrator = PromptOrchestrator()
            workspace_manager = WorkspaceManager()
            vibe_project_service = VibeProjectService(
                db_session=db,
                workspace_manager=workspace_manager,
                ai_engine=ai_engine
            )
            
            processor = VibeCodingProcessor(
                ai_engine=ai_engine,
                prompt_orchestrator=prompt_orchestrator,
                vibe_project_service=vibe_project_service
            )
            
            # 根据阶段处理请求
            if request.stage == "meta":
                result = await processor.process_vibe_coding_request(
                    user_input=request.content,
                    user_id=str(current_user.id),
                    conversation_id=request.conversation_id,
                    stage="meta"
                )
            elif request.stage == "generate":
                result = await processor._process_generate_stage(
                    user_input=request.content,
                    user_id=str(current_user.id),
                    conversation_id=request.conversation_id,
                    meta_result=request.meta_result,
                    optimized_prompt=request.optimized_prompt
                )
            else:
                raise ValueError(f"Invalid stage: {request.stage}")
            
            return result
            
        except Exception as e:
            logger.error(f"Vibe coding processing failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"处理失败: {str(e)}"
            )
    
    @vibe_router.get("/intent/detect")
    async def detect_intent(text: str):
        """意图检测端点"""
        try:
            # 简单的意图检测逻辑
            vibe_keywords = [
                "创建", "生成", "搭建", "开发", "制作", "建立",
                "网站", "应用", "项目", "系统", "工具", "程序"
            ]
            
            text_lower = text.lower()
            has_vibe_intent = any(keyword in text_lower for keyword in vibe_keywords)
            
            return {
                "is_vibe_intent": has_vibe_intent,
                "confidence": 0.8 if has_vibe_intent else 0.2,
                "text": text
            }
        except Exception as e:
            return {
                "is_vibe_intent": False,
                "confidence": 0.0,
                "error": str(e)
            }
    
    # 注册 Vibe Coding 路由
    app.include_router(vibe_router, tags=["Vibe-Coding"])
    logger.info("✅ Vibe Coding routes registered successfully")
    
except Exception as e:
    logger.warning(f"⚠️ Failed to register Vibe Coding routes: {e}")
    logger.info("Continuing without Vibe Coding functionality...")

# 同时更新现有的 v2 chat 路由以支持 Vibe Coding
# 在现有的 v2_chat.router 中添加 Vibe Coding 支持

# 修改健康检查端点以包含 Vibe Coding 状态
@app.get("/health")
async def health_check():
    """增强的健康检查"""
    try:
        # 检查数据库连接
        from app.db.session import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        db_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "unhealthy"
    
    try:
        # 检查Redis连接
        from app.db.redis import get_redis
        redis = await get_redis()
        await redis.ping()
        redis_status = "healthy"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        redis_status = "unhealthy"
    
    # 检查AI引擎
    try:
        from app.core.ai_engine import AIEngine
        ai_engine = AIEngine()
        ai_status = "healthy" if ai_engine.providers else "no_providers"
    except Exception as e:
        logger.error(f"AI engine health check failed: {e}")
        ai_status = "unhealthy"
    
    # 检查 Vibe Coding 组件
    vibe_coding_status = "disabled"
    try:
        from app.core.vibe.vibe_coding_processor import VibeCodingProcessor
        vibe_coding_status = "enabled"
    except Exception:
        vibe_coding_status = "not_available"
    
    overall_status = "healthy" if all([
        db_status == "healthy",
        redis_status == "healthy",
        ai_status in ["healthy", "no_providers"]
    ]) else "unhealthy"
    
    return {
        "status": overall_status,
        "version": "2.0.0",
        "service": "ChatBot API - Vibe Coding Edition",
        "components": {
            "database": db_status,
            "redis": redis_status,
            "ai_engine": ai_status,
            "vibe_coding": vibe_coding_status
        },
        "features": {
            "unified_chat": True,
            "intent_recognition": True,
            "project_awareness": True,
            "code_generation": True,
            "file_operations": True,
            "legacy_compatibility": True,
            "vibe_coding": vibe_coding_status == "enabled"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info"
    )