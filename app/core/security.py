from typing import Optional, Union, Any
from datetime import datetime, timedelta
from passlib.context import CryptContext
import secrets
import hashlib
import hmac

from app.config import settings

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SecurityUtils:
    """安全工具类"""

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def get_password_hash(password: str) -> str:
        """生成密码哈希"""
        return pwd_context.hash(password)

    @staticmethod
    def generate_random_token(length: int = 32) -> str:
        """生成随机令牌"""
        return secrets.token_urlsafe(length)

    @staticmethod
    def generate_api_key() -> str:
        """生成API密钥"""
        return f"sk-{secrets.token_urlsafe(48)}"

    @staticmethod
    def create_signature(data: str, secret: str) -> str:
        """创建签名"""
        return hmac.new(
            secret.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()

    @staticmethod
    def verify_signature(data: str, signature: str, secret: str) -> bool:
        """验证签名"""
        expected_signature = SecurityUtils.create_signature(data, secret)
        return hmac.compare_digest(signature, expected_signature)

    @staticmethod
    def mask_api_key(api_key: str) -> str:
        """遮蔽API密钥"""
        if not api_key or len(api_key) < 8:
            return "***"
        return f"{api_key[:4]}...{api_key[-4:]}"

    @staticmethod
    def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
        """
        验证密码强度

        Returns:
            (是否有效, 错误消息)
        """
        if len(password) < 8:
            return False, "密码长度至少8个字符"

        if not any(char.isdigit() for char in password):
            return False, "密码必须包含至少一个数字"

        if not any(char.isalpha() for char in password):
            return False, "密码必须包含至少一个字母"

        if not any(char.isupper() for char in password):
            return False, "密码必须包含至少一个大写字母"

        if not any(char.islower() for char in password):
            return False, "密码必须包含至少一个小写字母"

        return True, None

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """清理文件名"""
        import re
        # 移除特殊字符
        filename = re.sub(r'[^\w\s.-]', '', filename)
        # 限制长度
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        if len(name) > 200:
            name = name[:200]
        return f"{name}.{ext}" if ext else name

    @staticmethod
    def is_safe_url(url: str, allowed_hosts: list[str] = None) -> bool:
        """检查URL是否安全"""
        from urllib.parse import urlparse

        if not url:
            return False

        try:
            result = urlparse(url)

            # 检查协议
            if result.scheme not in ['http', 'https']:
                return False

            # 检查主机
            if allowed_hosts and result.netloc not in allowed_hosts:
                return False

            return True
        except:
            return False


# CORS配置
def get_cors_origins() -> list[str]:
    """获取CORS允许的源"""
    origins = settings.CORS_ORIGINS
    if isinstance(origins, str):
        return [origins]
    return origins


# 安全头部
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
}


# IP白名单/黑名单管理
class IPFilter:
    """IP过滤器"""

    def __init__(self):
        self.whitelist: set[str] = set()
        self.blacklist: set[str] = set()

    def add_to_whitelist(self, ip: str):
        """添加到白名单"""
        self.whitelist.add(ip)
        self.blacklist.discard(ip)

    def add_to_blacklist(self, ip: str):
        """添加到黑名单"""
        self.blacklist.add(ip)
        self.whitelist.discard(ip)

    def is_allowed(self, ip: str) -> bool:
        """检查IP是否允许"""
        if self.whitelist and ip not in self.whitelist:
            return False
        if ip in self.blacklist:
            return False
        return True


# 内容过滤
class ContentFilter:
    """内容过滤器"""

    def __init__(self):
        self.sensitive_words = set()
        self.load_sensitive_words()

    def load_sensitive_words(self):
        """加载敏感词列表"""
        # 这里可以从文件或数据库加载
        pass

    def contains_sensitive_content(self, text: str) -> bool:
        """检查是否包含敏感内容"""
        text_lower = text.lower()
        for word in self.sensitive_words:
            if word in text_lower:
                return True
        return False

    def filter_content(self, text: str) -> str:
        """过滤敏感内容"""
        for word in self.sensitive_words:
            text = text.replace(word, "*" * len(word))
        return text