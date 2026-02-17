from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, AsyncGenerator, Type
import importlib
import inspect
from pathlib import Path
import yaml

class AIProviderPlugin(ABC):
    """AI 提供商插件基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.name = config.get("name", self.__class__.__name__)
        
    @abstractmethod
    async def initialize(self):
        """初始化插件"""
        pass
    
    @abstractmethod
    async def get_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> Dict[str, Any]:
        """获取完成响应"""
        pass
    
    @abstractmethod
    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式获取响应"""
        pass
    
    @abstractmethod
    async def validate_model(self, model: str) -> bool:
        """验证模型是否可用"""
        pass
    
    def get_capabilities(self) -> Dict[str, Any]:
        """获取插件能力"""
        return {
            "streaming": True,
            "function_calling": False,
            "image_input": False,
            "batch_processing": False
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "status": "healthy",
            "name": self.name
        }

class PluginManager:
    """插件管理器"""
    
    def __init__(self, plugin_dir: str = "app/plugins/ai_providers"):
        self.plugin_dir = Path(plugin_dir)
        self.plugins: Dict[str, AIProviderPlugin] = {}
        self._plugin_classes: Dict[str, Type[AIProviderPlugin]] = {}
        
    async def discover_plugins(self):
        """发现并加载插件"""
        if not self.plugin_dir.exists():
            return
            
        for plugin_file in self.plugin_dir.glob("*.py"):
            if plugin_file.stem.startswith("_"):
                continue
                
            module_name = f"app.plugins.ai_providers.{plugin_file.stem}"
            module = importlib.import_module(module_name)
            
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    issubclass(obj, AIProviderPlugin) and 
                    obj != AIProviderPlugin):
                    self._plugin_classes[plugin_file.stem] = obj
    
    async def load_plugin(self, name: str, config: Dict[str, Any]) -> AIProviderPlugin:
        """加载单个插件"""
        if name in self._plugin_classes:
            plugin_class = self._plugin_classes[name]
            plugin = plugin_class(config)
            await plugin.initialize()
            self.plugins[name] = plugin
            return plugin
        else:
            raise ValueError(f"Plugin {name} not found")
    
    def get_plugin(self, name: str) -> Optional[AIProviderPlugin]:
        """获取插件实例"""
        return self.plugins.get(name)
    
    async def reload_plugin(self, name: str):
        """重新加载插件"""
        if name in self.plugins:
            # 关闭旧插件
            old_plugin = self.plugins[name]
            if hasattr(old_plugin, 'close'):
                await old_plugin.close()
            
            # 重新加载模块
            module_name = f"app.plugins.ai_providers.{name}"
            module = importlib.reload(importlib.import_module(module_name))
            
            # 重新创建插件
            config = old_plugin.config
            await self.load_plugin(name, config)

# 全局插件管理器
plugin_manager = PluginManager()