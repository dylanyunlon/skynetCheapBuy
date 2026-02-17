from typing import Optional, List, Dict, Union,Any
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
    
    # 新增：Bash脚本生成配置
    BASH_SCRIPT_GENERATION: bool = True
    BASH_SCRIPT_TIMEOUT: int = 120  # bash脚本执行超时时间（秒）
    BASH_SCRIPT_MAX_SIZE: int = 50000  # 最大脚本大小（字符）
    BASH_SCRIPT_VALIDATION: bool = True  # 是否启用脚本安全验证
    
    # 新增：Heredoc文件生成配置
    HEREDOC_FILE_GENERATION: bool = True
    MAX_FILE_SIZE_IN_SCRIPT: int = 10000  # 脚本中单个文件最大大小（字符）
    HEREDOC_SAFETY_CHECK: bool = True  # 是否启用heredoc安全检查
    
    # 新增：部署自动化配置
    AUTO_PORT_MANAGEMENT: bool = True  # 自动端口冲突处理
    AUTO_SERVER_STARTUP: bool = True   # 自动服务器启动
    CROSS_PLATFORM_COMPATIBILITY: bool = True  # 跨平台兼容性
    DEFAULT_PROJECT_PORT: int = 17430  # 默认项目端口
    PORT_RANGE_START: int = 17430     # 端口范围开始
    PORT_RANGE_END: int = 17530       # 端口范围结束
    
    # 新增：Bash脚本缓存配置
    BASH_SCRIPT_CACHE_ENABLED: bool = True
    BASH_SCRIPT_CACHE_TTL: int = 3600  # 缓存时间（秒）
    BASH_SCRIPT_CACHE_MAX_SIZE: int = 1000  # 最大缓存数量
    
    # 新增：AI调用优化配置
    AI_META_TEMPERATURE: float = 0.7  # Meta-prompt的温度
    AI_GENERATION_TEMPERATURE: float = 0.2  # 代码生成的温度
    AI_EXTRACTION_TEMPERATURE: float = 0.1  # 代码提取的温度
    AI_MAX_RETRIES: int = 3  # AI调用最大重试次数
    AI_TIMEOUT: int = 6000  # AI调用超时时间（秒）
    
    # 新增：系统提示词配置
        # Vibe Coding 配置
    ENABLE_VIBE_CODING: bool = True
    VIBE_SYSTEM_PROMPT_VERSION: str = "2.0"
    VIBE_ENHANCED_EXTRACTION: bool = True
    VIBE_ZERO_FALLBACK_MODE: bool = True  # 零降级模式
    SYSTEM_PROMPT_CACHE_ENABLED: bool = True
    SYSTEM_PROMPT_CACHE_TTL: int = 3600  # 1小时
    
    # 新增：工作空间配置
    WORKSPACE_PATH: str = "./workspace"  # 工作空间基础路径
    WORKSPACE_MAX_SIZE: int = 1073741824  # 1GB工作空间最大大小
    WORKSPACE_CLEANUP_INTERVAL: int = 86400  # 24小时清理间隔
    WORKSPACE_BACKUP_ENABLED: bool = True  # 是否启用工作空间备份
    
    # 新增：预览服务配置
    PREVIEW_SERVER_HOST: str = "8.163.12.28"  # 预览服务器主机
    PREVIEW_URL_TEMPLATE: str = "http://{host}:{port}"  # 预览URL模板
    PREVIEW_TIMEOUT: int = 30  # 预览生成超时时间
    
    # 新增：安全配置
    BASH_SCRIPT_SECURITY_LEVEL: str = "medium"  # low, medium, high
    ALLOWED_BASH_COMMANDS: List[str] = [
        "echo", "cat", "mkdir", "cd", "pwd", "ls",
        "python3", "python", "node", "npm",
        "lsof", "ps", "kill", "sleep",
        "date", "which", "command", "chmod", "touch"
    ]
    FORBIDDEN_BASH_PATTERNS: List[str] = [
        r'rm\s+-rf\s+/',
        r'dd\s+if=/dev/zero',
        r':\(\)\s*\{.*\|\s*:\s*&',
        r'curl.*\|\s*sh',
        r'wget.*\|\s*sh',
        r'eval\s*\$\(',
        r'chmod\s+777\s+/'
    ]
    
    # 新增：监控和日志配置
    BASH_GENERATION_METRICS: bool = True  # 启用bash生成指标
    BASH_EXECUTION_LOGGING: bool = True   # 启用bash执行日志
    PERFORMANCE_MONITORING: bool = True   # 启用性能监控
    ERROR_REPORTING: bool = True          # 启用错误报告
    
    # 新增：实验性功能配置
    EXPERIMENTAL_FEATURES: Dict[str, bool] = {
        "parallel_ai_calls": False,      # 并行AI调用
        "smart_caching": True,           # 智能缓存
        "auto_optimization": False,      # 自动优化
        "advanced_debugging": True,      # 高级调试
        "multi_model_ensemble": False    # 多模型集成
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
            "FILE_UPLOAD_MESS": True,
            # 新增：Bash脚本相关偏好
            "BASH_SCRIPT_GENERATION": True,
            "AUTO_SCRIPT_EXECUTION": False,
            "SCRIPT_SAFETY_CHECK": True,
            "PREFER_BASH_AUTOMATION": True
        }
        
        self.default_plugins = {
            "search": False,
            "url_reader": False,
            "generate_image": False,
            # 新增：Bash脚本插件
            "bash_script_generator": True,
            "heredoc_file_creator": True,
            "auto_deployment": True
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
            "api_url": "",
            # 新增：Bash脚本配置
            "bash_config": {
                "auto_generation": settings.BASH_SCRIPT_GENERATION,
                "timeout": settings.BASH_SCRIPT_TIMEOUT,
                "security_level": settings.BASH_SCRIPT_SECURITY_LEVEL,
                "cache_enabled": settings.BASH_SCRIPT_CACHE_ENABLED
            }
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

# 新增：Bash脚本配置辅助函数
def get_bash_script_config() -> Dict[str, Any]:
    """获取Bash脚本生成配置"""
    return {
        "enabled": settings.BASH_SCRIPT_GENERATION,
        "timeout": settings.BASH_SCRIPT_TIMEOUT,
        "max_size": settings.BASH_SCRIPT_MAX_SIZE,
        "validation": settings.BASH_SCRIPT_VALIDATION,
        "heredoc_enabled": settings.HEREDOC_FILE_GENERATION,
        "max_file_size": settings.MAX_FILE_SIZE_IN_SCRIPT,
        "auto_port_management": settings.AUTO_PORT_MANAGEMENT,
        "auto_server_startup": settings.AUTO_SERVER_STARTUP,
        "cross_platform": settings.CROSS_PLATFORM_COMPATIBILITY,
        "default_port": settings.DEFAULT_PROJECT_PORT,
        "port_range": (settings.PORT_RANGE_START, settings.PORT_RANGE_END),
        "security_level": settings.BASH_SCRIPT_SECURITY_LEVEL,
        "allowed_commands": settings.ALLOWED_BASH_COMMANDS,
        "forbidden_patterns": settings.FORBIDDEN_BASH_PATTERNS
    }

def get_ai_optimization_config() -> Dict[str, Any]:
    """获取AI调用优化配置"""
    return {
        "meta_temperature": settings.AI_META_TEMPERATURE,
        "generation_temperature": settings.AI_GENERATION_TEMPERATURE,
        "extraction_temperature": settings.AI_EXTRACTION_TEMPERATURE,
        "max_retries": settings.AI_MAX_RETRIES,
        "timeout": settings.AI_TIMEOUT,
        "cache_enabled": settings.BASH_SCRIPT_CACHE_ENABLED,
        "cache_ttl": settings.BASH_SCRIPT_CACHE_TTL
    }

def get_workspace_config() -> Dict[str, Any]:
    """获取工作空间配置"""
    return {
        "path": settings.WORKSPACE_PATH,
        "max_size": settings.WORKSPACE_MAX_SIZE,
        "cleanup_interval": settings.WORKSPACE_CLEANUP_INTERVAL,
        "backup_enabled": settings.WORKSPACE_BACKUP_ENABLED,
        "preview_host": settings.PREVIEW_SERVER_HOST,
        "preview_template": settings.PREVIEW_URL_TEMPLATE,
        "preview_timeout": settings.PREVIEW_TIMEOUT
    }

def is_experimental_feature_enabled(feature: str) -> bool:
    """检查实验性功能是否启用"""
    return settings.EXPERIMENTAL_FEATURES.get(feature, False)

# 配置验证函数
def validate_bash_script_config() -> bool:
    """验证Bash脚本配置的有效性"""
    try:
        # 检查必要的配置项
        assert settings.BASH_SCRIPT_TIMEOUT > 0, "Bash script timeout must be positive"
        assert settings.BASH_SCRIPT_MAX_SIZE > 0, "Bash script max size must be positive"
        assert settings.PORT_RANGE_START < settings.PORT_RANGE_END, "Invalid port range"
        assert settings.DEFAULT_PROJECT_PORT >= 1024, "Default port must be >= 1024"
        
        # 检查路径配置
        if not os.path.exists(settings.WORKSPACE_PATH):
            os.makedirs(settings.WORKSPACE_PATH, exist_ok=True)
        
        return True
    except Exception as e:
        print(f"Bash script configuration validation failed: {e}")
        return False

# 在模块加载时验证配置
if not validate_bash_script_config():
    print("Warning: Bash script configuration validation failed. Some features may not work properly.")