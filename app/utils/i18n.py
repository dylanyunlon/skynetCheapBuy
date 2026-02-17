from typing import Dict, Any, Optional
import json
import os
from pathlib import Path

from app.config import settings

# 翻译字符串存储
translations: Dict[str, Dict[str, str]] = {}

# 默认翻译
default_translations = {
    "en": {
        "welcome": "Welcome to ChatBot API!",
        "message_think": "Thinking...",
        "message_reset": "Conversation has been reset.",
        "message_doc": "Document uploaded successfully.",
        "message_command_text_none": "Please provide a message.",
        "model_command_usage": "Usage: /model <model_name>",
        "model_name_invalid": "Invalid model name.",
        "model_not_available": "Model {model_name} is not available.",
        "model_changed": "Model changed to {model_name}",
        "message_banner": "\n\n---\nPowered by ChatBot API",
        "group_title": "Model Group",
        "error_generic": "An error occurred: {error}",
        "error_rate_limit": "Too many requests. Please try again later.",
        "error_unauthorized": "Unauthorized access.",
        "error_not_found": "Resource not found.",
        "settings_updated": "Settings updated successfully.",
        "file_upload_success": "File uploaded successfully.",
        "file_upload_error": "Failed to upload file: {error}",
        "conversation_created": "New conversation created.",
        "message_sent": "Message sent.",
        "typing_indicator": "AI is typing...",
        "search_in_progress": "Searching for information...",
        "generating_image": "Generating image...",
        "follow_up_prompt": "Based on our conversation, you might want to ask:",
    },
    "zh-hans": {
        "welcome": "欢迎使用 ChatBot API！",
        "message_think": "思考中...",
        "message_reset": "对话已重置。",
        "message_doc": "文档上传成功。",
        "message_command_text_none": "请提供消息内容。",
        "model_command_usage": "用法：/model <模型名称>",
        "model_name_invalid": "无效的模型名称。",
        "model_not_available": "模型 {model_name} 不可用。",
        "model_changed": "模型已切换到 {model_name}",
        "message_banner": "\n\n---\n由 ChatBot API 提供支持",
        "group_title": "模型分组",
        "error_generic": "发生错误：{error}",
        "error_rate_limit": "请求过于频繁，请稍后再试。",
        "error_unauthorized": "未授权访问。",
        "error_not_found": "资源未找到。",
        "settings_updated": "设置更新成功。",
        "file_upload_success": "文件上传成功。",
        "file_upload_error": "文件上传失败：{error}",
        "conversation_created": "新对话已创建。",
        "message_sent": "消息已发送。",
        "typing_indicator": "AI 正在输入...",
        "search_in_progress": "正在搜索信息...",
        "generating_image": "正在生成图片...",
        "follow_up_prompt": "基于我们的对话，您可能想问：",
    },
    "zh-hant": {
        "welcome": "歡迎使用 ChatBot API！",
        "message_think": "思考中...",
        "message_reset": "對話已重置。",
        "message_doc": "文檔上傳成功。",
        "message_command_text_none": "請提供消息內容。",
        "model_command_usage": "用法：/model <模型名稱>",
        "model_name_invalid": "無效的模型名稱。",
        "model_not_available": "模型 {model_name} 不可用。",
        "model_changed": "模型已切換到 {model_name}",
        "message_banner": "\n\n---\n由 ChatBot API 提供支持",
        "group_title": "模型分組",
        "error_generic": "發生錯誤：{error}",
        "error_rate_limit": "請求過於頻繁，請稍後再試。",
        "error_unauthorized": "未授權訪問。",
        "error_not_found": "資源未找到。",
        "settings_updated": "設置更新成功。",
        "file_upload_success": "文件上傳成功。",
        "file_upload_error": "文件上傳失敗：{error}",
        "conversation_created": "新對話已創建。",
        "message_sent": "消息已發送。",
        "typing_indicator": "AI 正在輸入...",
        "search_in_progress": "正在搜索信息...",
        "generating_image": "正在生成圖片...",
        "follow_up_prompt": "基於我們的對話，您可能想問：",
    },
    "ru": {
        "welcome": "Добро пожаловать в ChatBot API!",
        "message_think": "Думаю...",
        "message_reset": "Диалог сброшен.",
        "message_doc": "Документ успешно загружен.",
        "message_command_text_none": "Пожалуйста, введите сообщение.",
        "model_command_usage": "Использование: /model <название_модели>",
        "model_name_invalid": "Недопустимое название модели.",
        "model_not_available": "Модель {model_name} недоступна.",
        "model_changed": "Модель изменена на {model_name}",
        "message_banner": "\n\n---\nРаботает на ChatBot API",
        "group_title": "Группа моделей",
        "error_generic": "Произошла ошибка: {error}",
        "error_rate_limit": "Слишком много запросов. Попробуйте позже.",
        "error_unauthorized": "Неавторизованный доступ.",
        "error_not_found": "Ресурс не найден.",
        "settings_updated": "Настройки успешно обновлены.",
        "file_upload_success": "Файл успешно загружен.",
        "file_upload_error": "Не удалось загрузить файл: {error}",
        "conversation_created": "Создан новый диалог.",
        "message_sent": "Сообщение отправлено.",
        "typing_indicator": "ИИ печатает...",
        "search_in_progress": "Поиск информации...",
        "generating_image": "Генерация изображения...",
        "follow_up_prompt": "Основываясь на нашем разговоре, вы можете спросить:",
    }
}

def init_translations():
    """初始化翻译"""
    global translations
    
    # 加载默认翻译
    translations = default_translations.copy()
    
    # 尝试从文件加载自定义翻译
    translations_dir = Path("translations")
    if translations_dir.exists():
        for lang_file in translations_dir.glob("*.json"):
            lang_code = lang_file.stem
            try:
                with open(lang_file, 'r', encoding='utf-8') as f:
                    translations[lang_code] = json.load(f)
            except Exception as e:
                print(f"Failed to load translation file {lang_file}: {e}")

def get_text(key: str, lang: str = "en", **kwargs) -> str:
    """
    获取翻译文本
    
    Args:
        key: 翻译键
        lang: 语言代码
        **kwargs: 格式化参数
    
    Returns:
        翻译后的文本
    """
    # 语言代码标准化
    lang = normalize_language_code(lang)
    
    # 获取翻译
    if lang in translations and key in translations[lang]:
        text = translations[lang][key]
    elif key in translations.get("en", {}):
        text = translations["en"][key]
    else:
        text = key  # 如果找不到翻译，返回键本身
    
    # 格式化文本
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    
    return text

def normalize_language_code(lang: str) -> str:
    """
    标准化语言代码
    
    Args:
        lang: 原始语言代码
    
    Returns:
        标准化的语言代码
    """
    # 语言代码映射
    lang_mapping = {
        "zh": "zh-hans",
        "zh-cn": "zh-hans",
        "zh-tw": "zh-hant",
        "zh-hk": "zh-hant",
        "russian": "ru",
        "english": "en",
        "simplified chinese": "zh-hans",
        "traditional chinese": "zh-hant",
    }
    
    lang_lower = lang.lower()
    
    # 检查映射
    if lang_lower in lang_mapping:
        return lang_mapping[lang_lower]
    
    # 检查是否是支持的语言
    if lang_lower in settings.SUPPORTED_LANGUAGES:
        return lang_lower
    
    # 默认返回英语
    return "en"

def get_available_languages() -> Dict[str, str]:
    """
    获取可用语言列表
    
    Returns:
        语言代码到语言名称的映射
    """
    return {
        "en": "English",
        "zh-hans": "简体中文",
        "zh-hant": "繁體中文",
        "ru": "Русский",
        "ja": "日本語",
        "ko": "한국어",
        "es": "Español",
        "fr": "Français",
        "de": "Deutsch"
    }

def detect_user_language(accept_language: Optional[str] = None) -> str:
    """
    检测用户语言偏好
    
    Args:
        accept_language: HTTP Accept-Language 头
    
    Returns:
        检测到的语言代码
    """
    if not accept_language:
        return "en"
    
    # 解析Accept-Language头
    # 格式: "en-US,en;q=0.9,zh-CN;q=0.8"
    languages = []
    for lang_q in accept_language.split(','):
        parts = lang_q.strip().split(';')
        lang = parts[0].strip()
        q = 1.0
        
        if len(parts) > 1:
            try:
                q = float(parts[1].split('=')[1])
            except:
                q = 1.0
        
        languages.append((lang, q))
    
    # 按优先级排序
    languages.sort(key=lambda x: x[1], reverse=True)
    
    # 查找支持的语言
    for lang, _ in languages:
        # 尝试完整语言代码
        normalized = normalize_language_code(lang)
        if normalized in translations:
            return normalized
        
        # 尝试语言前缀
        lang_prefix = lang.split('-')[0]
        normalized = normalize_language_code(lang_prefix)
        if normalized in translations:
            return normalized
    
    return "en"

# 为FastAPI创建的依赖项
def get_user_language(
    accept_language: Optional[str] = None,
    user_lang: Optional[str] = None
) -> str:
    """
    获取用户语言（用于依赖注入）
    
    Args:
        accept_language: HTTP头中的语言偏好
        user_lang: 用户设置的语言
    
    Returns:
        用户语言代码
    """
    if user_lang:
        return normalize_language_code(user_lang)
    
    return detect_user_language(accept_language)