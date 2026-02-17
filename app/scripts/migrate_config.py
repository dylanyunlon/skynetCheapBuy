#!/usr/bin/env python3
"""
配置迁移脚本 - 将现有配置迁移到新的配置系统
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
import json
from pathlib import Path
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_provider_configs():
    """迁移提供商配置"""
    config_dir = Path("config/providers")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # OpenAI 配置
    openai_config = {
        "name": "openai",
        "display_name": "OpenAI",
        "api_base": settings.OPENAI_API_BASE,
        "timeout": 60,
        "max_retries": 3,
        "rate_limits": {
            "requests_per_minute": 500,
            "tokens_per_minute": 150000
        },
        "enabled": bool(settings.OPENAI_API_KEY)
    }
    
    with open(config_dir / "openai.yaml", 'w') as f:
        yaml.dump(openai_config, f, default_flow_style=False)
    
    # Anthropic 配置
    anthropic_config = {
        "name": "anthropic",
        "display_name": "Anthropic Claude",
        "api_base": settings.ANTHROPIC_API_BASE,
        "timeout": 60,
        "max_retries": 3,
        "enabled": bool(settings.ANTHROPIC_API_KEY)
    }
    
    with open(config_dir / "anthropic.yaml", 'w') as f:
        yaml.dump(anthropic_config, f, default_flow_style=False)
    
    # Google 配置
    google_config = {
        "name": "google",
        "display_name": "Google AI",
        "timeout": 60,
        "max_retries": 3,
        "enabled": bool(settings.GOOGLE_AI_API_KEY)
    }
    
    with open(config_dir / "google.yaml", 'w') as f:
        yaml.dump(google_config, f, default_flow_style=False)
    
    # Doubao 配置
    custom_dir = config_dir / "custom"
    custom_dir.mkdir(exist_ok=True)
    
    doubao_config = {
        "name": "doubao",
        "display_name": "Doubao AI",
        "api_base": "${DOUBAO_API_BASE}",
        "timeout": 120,
        "max_retries": 3,
        "rate_limits": {
            "requests_per_minute": 60,
            "tokens_per_minute": 150000
        },
        "enabled": True
    }
    
    with open(custom_dir / "doubao.yaml", 'w') as f:
        yaml.dump(doubao_config, f, default_flow_style=False)
    
    logger.info("Provider configurations migrated")

def migrate_model_configs():
    """迁移模型配置"""
    models_dir = Path("config/models")
    models_dir.mkdir(parents=True, exist_ok=True)
    
    models = []
    
    # 从现有配置迁移模型
    for provider, model_list in settings.AVAILABLE_MODELS.items():
        for model_name in model_list:
            # 获取模型信息
            if provider == "openai":
                if model_name.startswith("Doubao"):
                    # Doubao 模型
                    model = {
                        "name": model_name,
                        "provider": "custom.doubao",
                        "display_name": model_name.replace("-", " ").title(),
                        "description": f"Doubao AI model - {model_name}",
                        "capabilities": {
                            "chat": True,
                            "streaming": True,
                            "function_calling": True,
                            "image_input": False,
                            "max_tokens": 4096,
                            "context_window": 262144 if "256k" in model_name else 16384
                        },
                        "cost": {
                            "input_per_1k": 0.0005,
                            "output_per_1k": 0.0015
                        },
                        "limits": {
                            "max_requests_per_minute": 60,
                            "max_tokens_per_minute": 150000
                        },
                        "tags": ["efficient", "long-context"] if "256k" in model_name else ["efficient"],
                        "enabled": True,
                        "priority": 100 if "pro" in model_name else 90
                    }
                else:
                    # OpenAI 模型
                    model = create_openai_model_config(model_name)
            elif provider == "anthropic":
                model = create_anthropic_model_config(model_name)
            elif provider == "google":
                model = create_google_model_config(model_name)
            
            models.append(model)
    
    # 保存模型注册表
    registry = {"models": models}
    
    with open(models_dir / "registry.yaml", 'w') as f:
        yaml.dump(registry, f, default_flow_style=False, sort_keys=False)
    
    logger.info(f"Migrated {len(models)} model configurations")

def create_openai_model_config(model_name: str) -> dict:
    """创建 OpenAI 模型配置"""
    base_config = {
        "name": model_name,
        "provider": "openai",
        "display_name": model_name.replace("-", " ").title(),
        "enabled": True
    }
    
    # 根据模型名称设置特定配置
    if "gpt-4" in model_name:
        base_config.update({
            "description": "Advanced GPT-4 model",
            "capabilities": {
                "chat": True,
                "streaming": True,
                "function_calling": True,
                "image_input": "vision" in model_name,
                "max_tokens": 4096,
                "context_window": 128000 if "turbo" in model_name else 8192
            },
            "cost": {
                "input_per_1k": 0.01 if "turbo" in model_name else 0.03,
                "output_per_1k": 0.03 if "turbo" in model_name else 0.06
            },
            "tags": ["powerful", "reasoning"],
            "priority": 90
        })
    else:  # GPT-3.5
        base_config.update({
            "description": "Fast and efficient GPT-3.5 model",
            "capabilities": {
                "chat": True,
                "streaming": True,
                "function_calling": True,
                "image_input": False,
                "max_tokens": 4096,
                "context_window": 16384 if "16k" in model_name else 4096
            },
            "cost": {
                "input_per_1k": 0.0015,
                "output_per_1k": 0.002
            },
            "tags": ["fast", "efficient"],
            "priority": 70
        })
    
    return base_config

def create_anthropic_model_config(model_name: str) -> dict:
    """创建 Anthropic 模型配置"""
    # 类似的配置创建逻辑
    pass

def create_google_model_config(model_name: str) -> dict:
    """创建 Google 模型配置"""
    # 类似的配置创建逻辑
    pass

def main():
    """主函数"""
    logger.info("Starting configuration migration...")
    
    # 迁移提供商配置
    migrate_provider_configs()
    
    # 迁移模型配置
    migrate_model_configs()
    
    # 创建默认配置
    defaults_config = {
        "default_model": "gpt-3.5-turbo",
        "default_temperature": 0.7,
        "default_system_prompt": "You are a helpful AI assistant.",
        "supported_languages": settings.SUPPORTED_LANGUAGES,
        "default_language": settings.DEFAULT_LANGUAGE
    }
    
    with open("config/defaults.yaml", 'w') as f:
        yaml.dump(defaults_config, f, default_flow_style=False)
    
    logger.info("Configuration migration completed!")
    logger.info("Please update your .env file to include:")
    logger.info("  DOUBAO_API_BASE=<your-doubao-api-base-url>")
    logger.info("  DOUBAO_API_KEY=<your-doubao-api-key>")

if __name__ == "__main__":
    main()