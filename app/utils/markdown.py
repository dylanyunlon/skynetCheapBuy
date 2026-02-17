import re
from typing import List, Tuple

def escape_markdown(text: str, italic: bool = True) -> str:
    """
    转义Markdown特殊字符
    
    Args:
        text: 要转义的文本
        italic: 是否转义斜体字符
    
    Returns:
        转义后的文本
    """
    # 需要转义的字符
    chars_to_escape = ['\\', '`', '*', '[', ']', '(', ')', '#', '+', '-', '.', '!', '|', '{', '}']
    
    if italic:
        chars_to_escape.append('_')
    
    # 转义特殊字符
    for char in chars_to_escape:
        text = text.replace(char, f'\\{char}')
    
    return text

def split_code(text: str) -> str:
    """
    分割代码块，确保代码块完整性
    """
    # 查找所有代码块
    code_blocks = re.findall(r'```[\s\S]*?```', text)
    
    if not code_blocks:
        return text
    
    # 标记代码块位置
    for i, block in enumerate(code_blocks):
        text = text.replace(block, f'@|CODE_BLOCK_{i}|@', 1)
    
    return text

def replace_all(text: str, pattern: str, replacement_func) -> str:
    """
    替换所有匹配的模式
    """
    return re.sub(pattern, replacement_func, text, flags=re.MULTILINE | re.DOTALL)

def format_message_for_telegram(text: str) -> str:
    """
    格式化消息以适应Telegram的MarkdownV2格式
    """
    # 处理代码块
    text = re.sub(r'```(\w+)?\n([\s\S]*?)```', lambda m: f'```{m.group(1) or ""}\n{m.group(2)}```', text)
    
    # 处理内联代码
    text = re.sub(r'`([^`]+)`', r'`\1`', text)
    
    # 处理粗体
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
    
    # 处理斜体
    text = re.sub(r'(?<!\*)_(.+?)_(?!\*)', r'_\1_', text)
    
    # 处理链接
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'[\1](\2)', text)
    
    return text

def extract_urls(text: str) -> List[str]:
    """
    从文本中提取所有URL
    """
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+(?:\.[^\s<>"{}|\\^`\[\]]+)*'
    return re.findall(url_pattern, text)

def extract_image_urls(text: str) -> List[str]:
    """
    从文本中提取图片URL
    """
    image_extensions = r'\.(jpg|jpeg|png|gif|webp|bmp|svg)(?:\?[^\s]*)?'
    image_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+' + image_extensions
    
    return re.findall(image_pattern, text, re.IGNORECASE)

def split_long_message(text: str, max_length: int = 3500) -> List[str]:
    """
    分割长消息，保持格式完整性
    """
    if len(text) <= max_length:
        return [text]
    
    messages = []
    current_message = ""
    
    # 按段落分割
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        # 如果单个段落就超过最大长度，需要进一步分割
        if len(paragraph) > max_length:
            # 尝试按句子分割
            sentences = re.split(r'(?<=[.!?])\s+', paragraph)
            for sentence in sentences:
                if len(current_message) + len(sentence) + 2 > max_length:
                    messages.append(current_message.strip())
                    current_message = sentence
                else:
                    current_message += " " + sentence if current_message else sentence
        else:
            if len(current_message) + len(paragraph) + 4 > max_length:
                messages.append(current_message.strip())
                current_message = paragraph
            else:
                current_message += "\n\n" + paragraph if current_message else paragraph
    
    if current_message:
        messages.append(current_message.strip())
    
    return messages

def remove_markdown(text: str) -> str:
    """
    移除Markdown格式，返回纯文本
    """
    # 移除代码块
    text = re.sub(r'```[\s\S]*?```', '', text)
    
    # 移除内联代码
    text = re.sub(r'`([^`]+)`', r'\1', text)
    
    # 移除粗体和斜体
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    
    # 移除标题标记
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    
    # 移除链接，保留链接文本
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    
    # 移除列表标记
    text = re.sub(r'^[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    
    # 移除引用标记
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
    
    # 移除水平线
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    
    return text.strip()

def highlight_code(code: str, language: str = '') -> str:
    """
    为代码添加语法高亮（返回HTML）
    """
    # 这里可以集成pygments或其他语法高亮库
    # 简化示例
    return f'<pre><code class="language-{language}">{escape_html(code)}</code></pre>'

def escape_html(text: str) -> str:
    """
    转义HTML特殊字符
    """
    escape_dict = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }
    
    for char, escape in escape_dict.items():
        text = text.replace(char, escape)
    
    return text