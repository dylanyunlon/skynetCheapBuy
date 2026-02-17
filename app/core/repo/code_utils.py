#!/usr/bin/env python
"""
CheapBuy Code Utils - 基于RepoMaster的code_utils.py适配
提供代码处理的通用工具函数
"""

import os
import re
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# ==================== 忽略配置 ====================

# 忽略的目录
ignored_dirs = {
    '__pycache__', '.git', '.svn', '.hg', 'node_modules', 'venv', '.venv',
    'env', '.env', 'build', 'dist', '.eggs', '*.egg-info', '.tox', '.nox',
    '.pytest_cache', '.mypy_cache', '.coverage', 'htmlcov', '.idea', '.vscode',
    '.DS_Store', 'Thumbs.db', '.ipynb_checkpoints', 'wandb', 'logs', 'output',
    '__MACOSX', '.cache', 'tmp', 'temp', '.tmp', '.temp',
    'locale', 'locales', 'i18n', 'translations',
    'fixtures', 'test_data', 'testdata', 'samples',
    'docs', 'documentation', 'doc',
    'static', 'media', 'assets', 'public',
    'migrations', 'versions',
    'vendor', 'third_party', 'external',
    '.github', '.gitlab', '.circleci',
}

# 忽略的文件模式
ignored_file_patterns = [
    r'.*\.pyc$', r'.*\.pyo$', r'.*\.pyd$', r'.*\.so$', r'.*\.dll$',
    r'.*\.exe$', r'.*\.bin$', r'.*\.pkl$', r'.*\.pickle$', r'.*\.pt$',
    r'.*\.pth$', r'.*\.h5$', r'.*\.hdf5$', r'.*\.ckpt$', r'.*\.safetensors$',
    r'.*\.onnx$', r'.*\.pb$', r'.*\.tflite$', r'.*\.mlmodel$',
    r'.*\.jpg$', r'.*\.jpeg$', r'.*\.png$', r'.*\.gif$', r'.*\.bmp$',
    r'.*\.ico$', r'.*\.svg$', r'.*\.webp$', r'.*\.mp3$', r'.*\.mp4$',
    r'.*\.wav$', r'.*\.avi$', r'.*\.mov$', r'.*\.mkv$',
    r'.*\.zip$', r'.*\.tar$', r'.*\.gz$', r'.*\.rar$', r'.*\.7z$',
    r'.*\.log$', r'.*\.lock$', r'package-lock\.json$', r'yarn\.lock$',
    r'.*syntax_error.*\.py$',
    r'.*_invalid.*\.py$',
    r'.*broken.*\.py$',
]


def should_ignore_path(path: str) -> bool:
    """检查路径是否应该被忽略"""
    path_parts = path.split(os.sep)
    
    # 检查目录
    for part in path_parts:
        if part in ignored_dirs:
            return True
    
    # 检查文件模式
    filename = os.path.basename(path)
    for pattern in ignored_file_patterns:
        if re.match(pattern, filename, re.IGNORECASE):
            return True
    
    return False


def get_code_abs_token(text: str) -> int:
    """
    估算文本的token数量
    使用简单的启发式方法: 约4个字符 = 1个token
    
    Args:
        text: 输入文本
        
    Returns:
        估算的token数量
    """
    if not text:
        return 0
    
    # 简单估算: 英文约4字符/token, 中文约1.5字符/token
    # 这里使用混合估算
    try:
        # 尝试使用tiktoken (如果可用)
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # 回退到简单估算
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        non_ascii_chars = len(text) - ascii_chars
        return int(ascii_chars / 4 + non_ascii_chars / 1.5)


def _get_code_abs(
    file_path: str, 
    code_content: str, 
    child_context: bool = True,
    max_lines: int = 100
) -> str:
    """
    获取代码的抽象摘要 (使用tree-sitter或简单方法)
    
    Args:
        file_path: 文件路径
        code_content: 代码内容
        child_context: 是否包含子上下文
        max_lines: 最大行数
        
    Returns:
        代码摘要字符串
    """
    try:
        # 尝试使用tree-sitter
        from tree_sitter_language_pack import get_parser
        
        parser = get_parser('python')
        tree = parser.parse(bytes(code_content, 'utf8'))
        root_node = tree.root_node
        
        result = []
        
        def extract_signature(node, depth=0):
            """提取函数/类签名"""
            indent = "    " * depth
            
            if node.type == 'function_definition':
                # 提取函数名和参数
                name_node = node.child_by_field_name('name')
                params_node = node.child_by_field_name('parameters')
                
                name = name_node.text.decode('utf8') if name_node else 'unknown'
                params = params_node.text.decode('utf8') if params_node else '()'
                
                result.append(f"{indent}def {name}{params}:")
                
            elif node.type == 'class_definition':
                name_node = node.child_by_field_name('name')
                name = name_node.text.decode('utf8') if name_node else 'unknown'
                
                # 检查继承
                superclass = node.child_by_field_name('superclasses')
                if superclass:
                    bases = superclass.text.decode('utf8')
                    result.append(f"{indent}class {name}{bases}:")
                else:
                    result.append(f"{indent}class {name}:")
                
                # 递归处理类方法
                if child_context:
                    for child in node.children:
                        if child.type == 'block':
                            for subchild in child.children:
                                extract_signature(subchild, depth + 1)
        
        # 遍历顶层节点
        for child in root_node.children:
            extract_signature(child, 0)
        
        if result:
            return "\n".join(result)
        
    except Exception as e:
        logger.debug(f"Tree-sitter parsing failed: {e}")
    
    # 回退到简单方法
    return _simple_code_summary(code_content, max_lines)


def _simple_code_summary(code_content: str, max_lines: int = 100) -> str:
    """
    简单的代码摘要方法
    
    Args:
        code_content: 代码内容
        max_lines: 最大行数
        
    Returns:
        代码摘要
    """
    lines = code_content.splitlines()
    result = []
    
    for line in lines:
        stripped = line.strip()
        
        # 提取函数和类定义
        if stripped.startswith('def ') or stripped.startswith('async def '):
            result.append(line)
        elif stripped.startswith('class '):
            result.append(line)
        elif stripped.startswith('import ') or stripped.startswith('from '):
            result.append(line)
        
        if len(result) >= max_lines:
            break
    
    return "\n".join(result)


def filter_pip_output(output: str, max_lines: int = 50) -> str:
    """
    过滤pip输出，保留关键信息
    
    Args:
        output: pip输出
        max_lines: 最大行数
        
    Returns:
        过滤后的输出
    """
    if not output:
        return ""
    
    lines = output.splitlines()
    filtered = []
    
    # 保留的关键词
    keep_patterns = [
        'Successfully', 'ERROR', 'Error', 'error:',
        'WARNING', 'Warning', 'Requirement', 'Installing',
        'Collecting', 'Building', 'Running'
    ]
    
    for line in lines:
        if any(pattern in line for pattern in keep_patterns):
            filtered.append(line)
        elif line.startswith('  '):  # 保留缩进的详细信息
            continue
        else:
            filtered.append(line)
        
        if len(filtered) >= max_lines:
            filtered.append(f"... (truncated, total {len(lines)} lines)")
            break
    
    return "\n".join(filtered)


def cut_logs_by_token(logs: str, max_tokens: int = 4000) -> str:
    """
    按token限制截断日志
    
    Args:
        logs: 日志内容
        max_tokens: 最大token数
        
    Returns:
        截断后的日志
    """
    if get_code_abs_token(logs) <= max_tokens:
        return logs
    
    # 从末尾开始保留
    lines = logs.splitlines()
    result = []
    current_tokens = 0
    
    for line in reversed(lines):
        line_tokens = get_code_abs_token(line)
        if current_tokens + line_tokens > max_tokens:
            break
        result.insert(0, line)
        current_tokens += line_tokens
    
    if len(result) < len(lines):
        result.insert(0, f"... (truncated {len(lines) - len(result)} lines)")
    
    return "\n".join(result)


def normalize_path(path: str, repo_path: str = "") -> str:
    """
    规范化文件路径
    
    Args:
        path: 文件路径
        repo_path: 仓库根路径
        
    Returns:
        规范化的路径
    """
    # 移除前导斜杠
    path = path.lstrip('/')
    
    # 如果是相对于仓库的路径
    if repo_path and path.startswith(repo_path):
        path = os.path.relpath(path, repo_path)
    
    return path


def extract_code_blocks(content: str) -> List[Dict[str, str]]:
    """
    从Markdown内容中提取代码块
    
    Args:
        content: Markdown内容
        
    Returns:
        代码块列表 [{'language': 'python', 'content': '...'}]
    """
    pattern = r'```(\w*)\n(.*?)```'
    matches = re.findall(pattern, content, re.DOTALL)
    
    blocks = []
    for lang, code in matches:
        blocks.append({
            'language': lang or 'text',
            'content': code.strip()
        })
    
    return blocks


def is_binary_file(file_path: str) -> bool:
    """
    检查文件是否为二进制文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        是否为二进制文件
    """
    binary_extensions = {
        '.pyc', '.pyo', '.so', '.dll', '.exe', '.bin',
        '.pkl', '.pickle', '.pt', '.pth', '.h5', '.hdf5',
        '.ckpt', '.safetensors', '.onnx', '.pb', '.tflite',
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico',
        '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv',
        '.zip', '.tar', '.gz', '.rar', '.7z', '.pdf'
    }
    
    ext = os.path.splitext(file_path)[1].lower()
    return ext in binary_extensions


def get_file_language(file_path: str) -> str:
    """
    根据文件扩展名获取编程语言
    
    Args:
        file_path: 文件路径
        
    Returns:
        编程语言名称
    """
    ext_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'javascript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.cpp': 'cpp',
        '.c': 'c',
        '.h': 'c',
        '.hpp': 'cpp',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.php': 'php',
        '.sh': 'bash',
        '.bash': 'bash',
        '.sql': 'sql',
        '.md': 'markdown',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.xml': 'xml',
        '.html': 'html',
        '.css': 'css',
    }
    
    ext = os.path.splitext(file_path)[1].lower()
    return ext_map.get(ext, 'text')
