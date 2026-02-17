from typing import Optional, List, Dict, Union
from pydantic_settings import BaseSettings
import os
from functools import lru_cache

class Settings(BaseSettings):
    # 基本配置
    APP_NAME: str = "ChatBot API"
    DEBUG: bool = False
    VERSION: str = "1.0.0"
    
    # 安全配置
    SECRET_KEY: str
    REFRESH_SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # 数据库配置
    DATABASE_URL: str
    MONGODB_URL: Optional[str] = None
    
    # Redis配置
    REDIS_URL: str
    REDIS_POOL_SIZE: int = 10
    REDIS_POOL_MAX_CONNECTIONS: int = 50
    
    # CORS配置
    CORS_ORIGINS: List[str] = ["*"]
    ALLOWED_HOSTS: List[str] = ["*"]
    
    # 文件上传配置
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE: int = 52428800  # 50MB
    ALLOWED_EXTENSIONS: Dict[str, List[str]] = {
        'image': ['.jpg', '.jpeg', '.png', '.gif', '.webp'],
        'document': ['.pdf', '.txt', '.doc', '.docx', '.md'],
        'code': ['.py', '.js', '.ts', '.java', '.cpp', '.yml', '.yaml', '.json'],
        'audio': ['.mp3', '.wav', '.ogg', '.m4a']
    }
    ENVIRONMENT: str = "development"  # development, staging, production
    
    # AI模型配置
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_API_BASE: str = "https://api.openai.com/v1"
    
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_API_BASE: str = "https://api.anthropic.com"
    
    GOOGLE_AI_API_KEY: Optional[str] = None
    VERTEX_PROJECT_ID: Optional[str] = None
    VERTEX_PRIVATE_KEY: Optional[str] = None
    VERTEX_CLIENT_EMAIL: Optional[str] = None
    
    # 默认模型配置
    DEFAULT_MODEL: str = "o3-gz"  # 使用标准的 OpenAI 模型名称
    DEFAULT_TEMPERATURE: float = 0.7
    DEFAULT_MAX_TOKENS: Optional[int] = None
    DEFAULT_SYSTEM_PROMPT: str = "You are a helpful AI assistant."
    
    # 可用模型列表 - 添加自定义模型
    AVAILABLE_MODELS: Dict[str, List[str]] = {
        "openai": [
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-16k",
            "gpt-4",
            "gpt-4-turbo-preview",
            "gpt-4-vision-preview",
            # 添加自定义模型（通过 OpenAI 兼容接口）
            "o3-gz",
            "Doubao-1.5-lite-256k",
            "Doubao-2.0-pro-256k",
            "claude-opus-4-20250514-all"
        ],
        "anthropic": [
            "claude-3-opus",
            "claude-3-sonnet",
            "claude-3-haiku",
            "claude-2.1"
        ],
        "google": [
            "gemini-pro",
            "gemini-pro-vision"
        ]
    }
    
    # 模型分组
    MODEL_GROUPS: Dict[str, List[str]] = {
        "GPT-3.5": ["gpt-3.5-turbo", "gpt-3.5-turbo-16k"],
        "GPT-4": ["gpt-4", "gpt-4-turbo-preview", "gpt-4-vision-preview"],
        "Claude": ["claude-3-opus", "claude-3-sonnet", "claude-3-haiku", "claude-2.1"],
        "Gemini": ["gemini-pro", "gemini-pro-vision"],
        "Doubao": ["o3-gz", "Doubao-1.5-lite-256k", "Doubao-2.0-pro-256k"]
    }
    
    # 速率限制
    RATE_LIMIT_CALLS: int = 10
    RATE_LIMIT_PERIOD: int = 60  # 秒
    
    # WebSocket配置
    WS_MESSAGE_QUEUE_SIZE: int = 100
    WS_HEARTBEAT_INTERVAL: int = 30  # 秒
    
    # 会话配置
    SESSION_TIMEOUT: int = 3600  # 1小时
    MAX_CONVERSATION_LENGTH: int = 100  # 最大对话轮数
    CONVERSATION_RESET_TIME: int = 1800  # 30分钟无活动后重置
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"
    
    # 语言配置
    SUPPORTED_LANGUAGES: List[str] = ["en", "zh-hans", "zh-hant", "ru", "ja", "ko", "es", "fr", "de"]
    DEFAULT_LANGUAGE: str = "en"
    
    # 插件配置
    AVAILABLE_PLUGINS: Dict[str, bool] = {
        "search": True,
        "url_reader": True,
        "generate_image": True,
        "code_interpreter": False
    }
    
    class Config:
        env_file = ".env"
        case_sensitive = True

@lru_cache()
def get_settings() -> Settings:
    """获取缓存的设置实例"""
    return Settings()

settings = get_settings()

# 用户配置管理（从原bot.py迁移）
class UserConfig:
    """用户配置管理类"""
    
    def __init__(self):
        self.default_preferences = {
            "PASS_HISTORY": 3,
            "LONG_TEXT": False,
            "LONG_TEXT_SPLIT": True,
            "FOLLOW_UP": True,
            "TITLE": True,
            "REPLY": True,
            "TYPING": True,
            "IMAGEQA": True,
            "FILE_UPLOAD_MESS": True
        }
        
        self.default_plugins = {
            "search": False,
            "url_reader": False,
            "generate_image": False
        }
    
    def get_default_config(self):
        """获取默认配置"""
        return {
            "language": settings.DEFAULT_LANGUAGE,
            "engine": settings.DEFAULT_MODEL,
            "system_prompt": settings.DEFAULT_SYSTEM_PROMPT,
            "claude_system_prompt": "",
            "preferences": self.default_preferences.copy(),
            "plugins": self.default_plugins.copy(),
            "api_key": "",
            "api_url": ""
        }

# 创建用户配置实例
user_config = UserConfig()

# 模型配置
def get_all_available_models() -> List[str]:
    """获取所有可用的模型"""
    models = []
    for provider_models in settings.AVAILABLE_MODELS.values():
        models.extend(provider_models)
    return models

def get_model_groups() -> Dict[str, List[str]]:
    """获取模型分组"""
    return settings.MODEL_GROUPS

def get_model_provider(model: str) -> Optional[str]:
    """根据模型名称获取提供商"""
    for provider, models in settings.AVAILABLE_MODELS.items():
        if model in models:
            return provider
    return None

# API密钥管理
def get_api_key_for_model(model: str) -> Optional[str]:
    """根据模型获取对应的API密钥"""
    provider = get_model_provider(model)
    if provider == "openai":
        return settings.OPENAI_API_KEY
    elif provider == "anthropic":
        return settings.ANTHROPIC_API_KEY
    elif provider == "google":
        return settings.GOOGLE_AI_API_KEY
    return None

def get_api_base_for_model(model: str) -> Optional[str]:
    """根据模型获取对应的API基础URL"""
    provider = get_model_provider(model)
    if provider == "openai":
        return settings.OPENAI_API_BASE
    elif provider == "anthropic":
        return settings.ANTHROPIC_API_BASE
    return None