from typing import Dict, Any, Optional, List
import yaml
import json
from pathlib import Path
from pydantic import BaseModel, Field
from functools import lru_cache
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import asyncio
from datetime import datetime

class ModelConfig(BaseModel):
    """模型配置"""
    name: str
    provider: str
    display_name: str
    description: str
    capabilities: Dict[str, Any]
    cost: Dict[str, float]
    limits: Dict[str, int]
    tags: List[str] = []
    enabled: bool = True
    priority: int = 0

class ProviderConfig(BaseModel):
    """提供商配置"""
    name: str
    display_name: str
    api_base: Optional[str]
    api_version: Optional[str]
    timeout: int = 6000
    max_retries: int = 3
    rate_limits: Dict[str, int] = {}
    custom_headers: Dict[str, str] = {}
    enabled: bool = True

class ConfigManager:
    """统一配置管理器"""
    
    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self._cache = {}
        self._observers = []
        self._callbacks = {}
        self._load_all_configs()
        
    def _load_all_configs(self):
        """加载所有配置"""
        # 加载提供商配置
        self._load_provider_configs()
        # 加载模型配置
        self._load_model_configs()
        # 加载环境配置
        self._load_environment_config()
        
    def _load_provider_configs(self):
        """加载提供商配置"""
        providers_dir = self.config_dir / "providers"
        self._cache["providers"] = {}
        
        for provider_file in providers_dir.glob("*.yaml"):
            with open(provider_file, 'r') as f:
                config = yaml.safe_load(f)
                provider_name = provider_file.stem
                self._cache["providers"][provider_name] = ProviderConfig(**config)
                
        # 加载自定义提供商
        custom_dir = providers_dir / "custom"
        if custom_dir.exists():
            for custom_file in custom_dir.glob("*.yaml"):
                with open(custom_file, 'r') as f:
                    config = yaml.safe_load(f)
                    provider_name = f"custom.{custom_file.stem}"
                    self._cache["providers"][provider_name] = ProviderConfig(**config)
    
    def _load_model_configs(self):
        """加载模型配置"""
        models_file = self.config_dir / "models" / "registry.yaml"
        self._cache["models"] = {}
        
        if models_file.exists():
            with open(models_file, 'r') as f:
                models = yaml.safe_load(f)
                for model_config in models.get("models", []):
                    model = ModelConfig(**model_config)
                    self._cache["models"][model.name] = model
    
    def _load_environment_config(self):
        """加载环境配置"""
        # 从环境变量或配置文件加载环境相关配置
        env_file = self.config_dir / "environment.yaml"
        self._cache["environment"] = {}
        
        # 如果存在环境配置文件，加载它
        if env_file.exists():
            with open(env_file, 'r') as f:
                config = yaml.safe_load(f)
                self._cache["environment"] = config or {}
        
        # 也可以从环境变量加载
        # 例如：覆盖配置文件中的值
        env_overrides = {
            "debug": os.getenv("DEBUG", "false").lower() == "true",
            "log_level": os.getenv("LOG_LEVEL", "INFO"),
            "environment": os.getenv("ENVIRONMENT", "development"),
        }
        
        # 合并环境变量覆盖
        self._cache["environment"].update({
            k: v for k, v in env_overrides.items() if v is not None
        })
    
    def _get_config_type(self, file_path: str) -> str:
        """根据文件路径判断配置类型"""
        path = Path(file_path)
        if "providers" in path.parts:
            return "providers"
        elif "models" in path.parts:
            return "models"
        elif "environment" in path.name:
            return "environment"
        return "unknown"
        
    def get_provider_config(self, provider: str) -> Optional[ProviderConfig]:
        """获取提供商配置"""
        return self._cache.get("providers", {}).get(provider)
    
    def get_model_config(self, model: str) -> Optional[ModelConfig]:
        """获取模型配置"""
        return self._cache.get("models", {}).get(model)
    
    def get_all_models(self, enabled_only: bool = True) -> List[ModelConfig]:
        """获取所有模型"""
        models = list(self._cache.get("models", {}).values())
        if enabled_only:
            models = [m for m in models if m.enabled]
        return sorted(models, key=lambda x: x.priority, reverse=True)
    
    def get_models_by_provider(self, provider: str) -> List[ModelConfig]:
        """获取特定提供商的模型"""
        return [
            m for m in self.get_all_models()
            if m.provider == provider
        ]
    
    def get_models_by_tag(self, tag: str) -> List[ModelConfig]:
        """根据标签获取模型"""
        return [
            m for m in self.get_all_models()
            if tag in m.tags
        ]
    
    def register_callback(self, config_type: str, callback):
        """注册配置变更回调"""
        if config_type not in self._callbacks:
            self._callbacks[config_type] = []
        self._callbacks[config_type].append(callback)
    
    def start_watch(self):
        """启动配置文件监控"""
        class ConfigFileHandler(FileSystemEventHandler):
            def __init__(self, config_manager):
                self.config_manager = config_manager
                
            def on_modified(self, event):
                if event.src_path.endswith('.yaml'):
                    asyncio.create_task(
                        self.config_manager._reload_config(event.src_path)
                    )
        
        observer = Observer()
        observer.schedule(
            ConfigFileHandler(self),
            str(self.config_dir),
            recursive=True
        )
        observer.start()
        self._observers.append(observer)
    
    async def _reload_config(self, file_path: str):
        """重新加载配置"""
        # 重新加载配置
        self._load_all_configs()
        
        # 触发回调
        config_type = self._get_config_type(file_path)
        if config_type in self._callbacks:
            for callback in self._callbacks[config_type]:
                await callback(self)
    
    def stop_watch(self):
        """停止配置文件监控"""
        for observer in self._observers:
            observer.stop()
            observer.join()

# 全局配置管理器实例
config_manager = ConfigManager()