#!/usr/bin/env python
"""
CheapBuy Code Tree Builder - 基于RepoMaster的tree_code.py适配
用于解析代码仓库并创建结构化代码树，支持LLM分析

v2.0 更新:
- 解决大型仓库(如Django)的WatchFiles和语法错误问题
- 添加Tree抽象层：扁平化路径格式存储
- 增强过滤机制，排除测试语法错误文件
- 优化大仓库处理性能
"""

import os
import ast
import re
import json
import subprocess
import logging
from typing import Dict, List, Set, Tuple, Optional, Any
from collections import defaultdict
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# ==================== 忽略配置 ====================

# 忽略的目录
IGNORED_DIRS = {
    '__pycache__', '.git', '.svn', '.hg', 'node_modules', 'venv', '.venv',
    'env', '.env', 'build', 'dist', '.eggs', '*.egg-info', '.tox', '.nox',
    '.pytest_cache', '.mypy_cache', '.coverage', 'htmlcov', '.idea', '.vscode',
    '.DS_Store', 'Thumbs.db', '.ipynb_checkpoints', 'wandb', 'logs', 'output',
    '__MACOSX', '.cache', 'tmp', 'temp', '.tmp', '.temp',
    # 新增：大型仓库常见的可忽略目录
    'locale', 'locales', 'i18n', 'translations',
    'fixtures', 'test_data', 'testdata', 'samples',
    'docs', 'documentation', 'doc',
    'static', 'media', 'assets', 'public',
    'migrations', 'versions',  # 数据库迁移
    'vendor', 'third_party', 'external',
    'benchmark_results', 'reports', 'coverage',
    '.github', '.gitlab', '.circleci',
}

# 忽略的文件模式
IGNORED_FILE_PATTERNS = [
    r'.*\.pyc$', r'.*\.pyo$', r'.*\.pyd$', r'.*\.so$', r'.*\.dll$',
    r'.*\.exe$', r'.*\.bin$', r'.*\.pkl$', r'.*\.pickle$', r'.*\.pt$',
    r'.*\.pth$', r'.*\.h5$', r'.*\.hdf5$', r'.*\.ckpt$', r'.*\.safetensors$',
    r'.*\.onnx$', r'.*\.pb$', r'.*\.tflite$', r'.*\.mlmodel$',
    r'.*\.jpg$', r'.*\.jpeg$', r'.*\.png$', r'.*\.gif$', r'.*\.bmp$',
    r'.*\.ico$', r'.*\.svg$', r'.*\.webp$', r'.*\.mp3$', r'.*\.mp4$',
    r'.*\.wav$', r'.*\.avi$', r'.*\.mov$', r'.*\.mkv$',
    r'.*\.zip$', r'.*\.tar$', r'.*\.gz$', r'.*\.rar$', r'.*\.7z$',
    r'.*\.log$', r'.*\.lock$', r'package-lock\.json$', r'yarn\.lock$',
    # 新增：忽略特定测试文件
    r'.*syntax_error.*\.py$',  # 故意的语法错误测试文件
    r'.*_invalid.*\.py$',
    r'.*broken.*\.py$',
    r'test_.*_error\.py$',
]

# 忽略的路径模式（用于大型仓库如Django）
IGNORED_PATH_PATTERNS = [
    r'.*/tests/.*/test_.*\.py$',  # 深层测试文件
    r'.*/conf/locale/.*',  # 本地化文件
    r'.*/contrib/.*/locale/.*',
    r'.*/test_runner_apps/.*',  # 测试运行器应用
    r'.*/migrations_test_apps/.*',  # 迁移测试应用
]

# tree命令的默认忽略模式
TREE_IGNORE_PATTERNS = [
    '__pycache__', 'node_modules', '.git', '.svn', '.hg',
    'venv', '.venv', 'env', '.env', 'build', 'dist',
    'logs', 'log', 'output', 'outputs', 'tmp', 'temp',
    'dataset', 'datasets', 'data', 'checkpoint', 'checkpoints',
    'wandb', '.pytest_cache', '.mypy_cache', 'htmlcov',
    '.ipynb_checkpoints', 'locale', 'locales', 'migrations',
    'fixtures', 'test_data', 'docs', 'documentation',
    'static', 'media', 'assets', '*.egg-info',
]


def should_ignore_path(path: str) -> bool:
    """检查路径是否应该被忽略"""
    path_parts = path.split(os.sep)
    
    # 检查目录
    for part in path_parts:
        if part in IGNORED_DIRS:
            return True
    
    # 检查文件模式
    filename = os.path.basename(path)
    for pattern in IGNORED_FILE_PATTERNS:
        if re.match(pattern, filename, re.IGNORECASE):
            return True
    
    # 检查路径模式
    for pattern in IGNORED_PATH_PATTERNS:
        if re.match(pattern, path, re.IGNORECASE):
            return True
    
    return False


def is_likely_syntax_error_test(file_path: str, content: str) -> bool:
    """
    检测文件是否是故意的语法错误测试文件
    这类文件在Django等大型项目中用于测试语法错误处理
    """
    path_lower = file_path.lower()
    
    # 路径检测
    syntax_error_indicators = [
        'syntax_error', 'invalid_syntax', 'broken_',
        'test_runner_apps', 'migrations_test_apps',
        '_error.py', '_invalid.py', '_broken.py'
    ]
    
    for indicator in syntax_error_indicators:
        if indicator in path_lower:
            return True
    
    # 内容检测：文件头部注释表明是故意的语法错误
    first_lines = content[:500].lower()
    if any(marker in first_lines for marker in [
        'intentional syntax error',
        'purposely invalid',
        'test syntax error',
        'this file contains syntax error'
    ]):
        return True
    
    return False


class TreeAbstraction:
    """
    Tree抽象层 - 位于AST和图探索之上的轻量级抽象
    
    功能:
    1. 使用tree命令快速获取仓库结构
    2. 扁平化路径格式存储 (src/services/api.py -> src_services_api.py)
    3. 过滤无关目录减少搜索空间
    4. 为LLM提供结构化的仓库视图
    """
    
    def __init__(self, repo_path: str):
        self.repo_path = os.path.abspath(repo_path)
        self.tree_content: str = ""
        self.flat_paths: Dict[str, str] = {}  # flat_name -> original_path
        self.path_to_flat: Dict[str, str] = {}  # original_path -> flat_name
        self.file_count: int = 0
        self.dir_count: int = 0
    
    def build(self, max_depth: int = 5) -> str:
        """
        构建Tree抽象层
        
        Args:
            max_depth: 最大目录深度
            
        Returns:
            tree结构字符串
        """
        # 构建忽略模式
        ignore_pattern = '|'.join(TREE_IGNORE_PATTERNS)
        
        try:
            # 使用tree命令
            cmd = [
                'tree', '-I', ignore_pattern,
                '-L', str(max_depth),
                '--noreport',  # 不显示统计
                '--charset', 'ascii',
                self.repo_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.repo_path
            )
            
            if result.returncode == 0:
                self.tree_content = result.stdout
            else:
                # 如果tree命令失败，使用Python实现
                self.tree_content = self._build_tree_python(max_depth)
                
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # tree命令不可用或超时，使用Python实现
            self.tree_content = self._build_tree_python(max_depth)
        
        # 构建扁平化路径映射
        self._build_flat_paths()
        
        return self.tree_content
    
    def _build_tree_python(self, max_depth: int) -> str:
        """Python实现的tree命令"""
        lines = []
        
        def _walk(path: str, prefix: str = "", depth: int = 0):
            if depth > max_depth:
                return
            
            try:
                entries = sorted(os.listdir(path))
            except (PermissionError, OSError):
                return
            
            # 过滤
            entries = [e for e in entries 
                      if e not in IGNORED_DIRS 
                      and not e.startswith('.')
                      and not any(e.endswith(ext) for ext in ['.pyc', '.pyo', '.log'])]
            
            dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
            files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
            
            # 限制数量
            if len(dirs) > 30:
                dirs = dirs[:15] + [f"... ({len(dirs) - 15} more dirs)"]
            if len(files) > 30:
                files = files[:15] + [f"... ({len(files) - 15} more files)"]
            
            all_entries = dirs + files
            
            for i, name in enumerate(all_entries):
                is_last = (i == len(all_entries) - 1)
                connector = "`-- " if is_last else "|-- "
                
                if isinstance(name, str) and name.startswith("..."):
                    lines.append(f"{prefix}{connector}{name}")
                else:
                    full_path = os.path.join(path, name)
                    if os.path.isdir(full_path):
                        lines.append(f"{prefix}{connector}{name}/")
                        new_prefix = prefix + ("    " if is_last else "|   ")
                        _walk(full_path, new_prefix, depth + 1)
                    else:
                        lines.append(f"{prefix}{connector}{name}")
                        self.file_count += 1
        
        lines.append(os.path.basename(self.repo_path) + "/")
        _walk(self.repo_path)
        self.dir_count = len([l for l in lines if l.rstrip().endswith('/')])
        
        return "\n".join(lines)
    
    def _build_flat_paths(self) -> None:
        """构建扁平化路径映射"""
        for root, dirs, files in os.walk(self.repo_path):
            # 过滤目录
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith('.')]
            
            rel_root = os.path.relpath(root, self.repo_path)
            if rel_root == '.':
                rel_root = ''
            
            for file in files:
                if should_ignore_path(os.path.join(rel_root, file)):
                    continue
                
                # 原始路径
                original_path = os.path.join(rel_root, file) if rel_root else file
                
                # 扁平化路径: src/services/api.py -> src_services_api.py
                flat_name = original_path.replace('/', '_').replace('\\', '_')
                
                self.flat_paths[flat_name] = original_path
                self.path_to_flat[original_path] = flat_name
    
    def get_flat_name(self, original_path: str) -> Optional[str]:
        """获取路径的扁平化名称"""
        return self.path_to_flat.get(original_path)
    
    def get_original_path(self, flat_name: str) -> Optional[str]:
        """从扁平化名称获取原始路径"""
        return self.flat_paths.get(flat_name)
    
    def search_files(self, keyword: str, limit: int = 20) -> List[str]:
        """按关键词搜索文件路径"""
        keyword_lower = keyword.lower()
        results = []
        
        for flat_name, original_path in self.flat_paths.items():
            if keyword_lower in original_path.lower():
                results.append(original_path)
                if len(results) >= limit:
                    break
        
        return results
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'repo_path': self.repo_path,
            'tree_content': self.tree_content,
            'flat_paths': self.flat_paths,
            'file_count': self.file_count,
            'dir_count': self.dir_count
        }
    
    def save_json(self, output_path: str) -> None:
        """保存为JSON"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


class CodeTreeBuilder:
    """
    代码树构建器 - 解析代码仓库并构建LLM友好的结构化表示
    
    核心功能:
    1. 解析Python/JS/多语言代码文件
    2. 构建函数调用图和模块依赖图
    3. 识别关键组件和入口点
    4. 生成LLM可理解的代码摘要
    5. Tree抽象层支持
    """
    
    def __init__(self, repo_path: str):
        """初始化代码树构建器"""
        self.repo_path = os.path.abspath(repo_path)
        self.modules: Dict[str, Dict] = {}  # 模块信息
        self.functions: Dict[str, Dict] = {}  # 函数信息
        self.classes: Dict[str, Dict] = {}  # 类信息
        self.other_files: Dict[str, Dict] = {}  # 其他文件信息
        self.imports: Dict[str, List] = defaultdict(list)  # 导入信息
        
        # Tree抽象层
        self.tree_abstraction = TreeAbstraction(repo_path)
        
        # 解析统计
        self.parse_stats = {
            'total_files_scanned': 0,
            'files_parsed': 0,
            'files_skipped': 0,
            'syntax_errors': 0,
            'syntax_error_files': []  # 记录语法错误文件
        }
        
        self.code_tree = {
            'modules': {},
            'stats': {
                'total_modules': 0,
                'total_classes': 0,
                'total_functions': 0,
                'total_lines': 0
            },
            'key_components': [],
            'key_modules': []
        }
        
        # 支持的代码文件扩展名
        self.code_extensions = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'javascript',
            '.tsx': 'typescript',
            '.sh': 'bash',
            '.bash': 'bash',
        }
        
        # 文档文件扩展名
        self.doc_extensions = {'.md', '.rst', '.txt', '.yaml', '.yml', '.json', '.toml'}
        
        logger.info(f"CodeTreeBuilder initialized for: {self.repo_path}")
    
    def parse_repository(self, max_depth: int = 4, max_files_per_dir: int = 50) -> None:
        """
        解析整个代码仓库
        
        Args:
            max_depth: 最大目录深度
            max_files_per_dir: 每个目录最大处理文件数
        """
        logger.info(f"开始解析代码仓库: {self.repo_path}")
        
        # 首先构建Tree抽象层
        logger.info("构建Tree抽象层...")
        self.tree_abstraction.build(max_depth=max_depth)
        logger.info(f"Tree抽象层构建完成: {len(self.tree_abstraction.flat_paths)} 个文件")
        
        for root, dirs, files in os.walk(self.repo_path):
            # 计算当前目录深度
            rel_path = os.path.relpath(root, self.repo_path)
            current_depth = 0 if rel_path == '.' else len(rel_path.split(os.sep))
            
            # 深度限制
            if current_depth > max_depth:
                dirs[:] = []
                continue
            
            # 过滤忽略的目录
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith('.')]
            
            # 大目录处理：跳过文件过多的目录
            if len(files) > 100:
                logger.debug(f"跳过大目录: {rel_path} ({len(files)} 文件)")
                continue
            elif len(files) > 50:
                files = files[:10]  # 只处理前10个文件
            
            file_count = 0
            for file in files:
                if file_count >= max_files_per_dir:
                    break
                
                file_path = os.path.join(root, file)
                rel_file_path = os.path.relpath(file_path, self.repo_path)
                
                self.parse_stats['total_files_scanned'] += 1
                
                if should_ignore_path(rel_file_path):
                    self.parse_stats['files_skipped'] += 1
                    continue
                
                # 文件大小限制 (10MB)
                try:
                    file_size = os.path.getsize(file_path)
                    if file_size > 10 * 1024 * 1024:
                        self.parse_stats['files_skipped'] += 1
                        continue
                except:
                    continue
                
                try:
                    ext = os.path.splitext(file)[1].lower()
                    
                    if ext == '.py':
                        self._parse_python_file(file_path, rel_file_path)
                    elif ext in self.code_extensions:
                        self._parse_code_file(file_path, rel_file_path, ext)
                    elif ext in self.doc_extensions or file.upper() in ['README', 'LICENSE', 'CHANGELOG']:
                        self._parse_doc_file(file_path, rel_file_path)
                    
                    file_count += 1
                    self.parse_stats['files_parsed'] += 1
                    
                except Exception as e:
                    logger.warning(f"解析文件失败 {rel_file_path}: {e}")
                    self.parse_stats['files_skipped'] += 1
        
        # 构建层次化代码树
        self._build_hierarchical_tree()
        
        # 识别关键模块
        self._identify_key_modules()
        
        logger.info(f"仓库解析完成: {self.code_tree['stats']}")
        logger.info(f"解析统计: 扫描={self.parse_stats['total_files_scanned']}, "
                   f"解析={self.parse_stats['files_parsed']}, "
                   f"跳过={self.parse_stats['files_skipped']}, "
                   f"语法错误={self.parse_stats['syntax_errors']}")
    
    def _parse_python_file(self, file_path: str, rel_path: str) -> None:
        """解析Python文件，增强语法错误处理"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 检查是否是故意的语法错误测试文件
            if is_likely_syntax_error_test(rel_path, content):
                logger.debug(f"跳过语法错误测试文件: {rel_path}")
                self.parse_stats['files_skipped'] += 1
                return
            
            # 尝试解析AST
            try:
                tree = ast.parse(content)
            except SyntaxError as e:
                # 记录语法错误但不中断
                self.parse_stats['syntax_errors'] += 1
                self.parse_stats['syntax_error_files'].append({
                    'path': rel_path,
                    'error': str(e)
                })
                logger.warning(f"Python语法错误 {rel_path}: {e}")
                
                # 即使有语法错误，仍记录基本信息
                module_id = rel_path.replace('/', '.').replace('\\', '.').rstrip('.py')
                self.modules[module_id] = {
                    'id': module_id,
                    'path': rel_path,
                    'type': 'module',
                    'content': content,
                    'lines': len(content.splitlines()),
                    'classes': [],
                    'functions': [],
                    'imports': [],
                    'docstring': '',
                    'has_syntax_error': True,
                    'syntax_error': str(e)
                }
                return
            
            module_id = rel_path.replace('/', '.').replace('\\', '.').rstrip('.py')
            
            # 提取模块信息
            module_info = {
                'id': module_id,
                'path': rel_path,
                'type': 'module',
                'content': content,
                'lines': len(content.splitlines()),
                'classes': [],
                'functions': [],
                'imports': [],
                'docstring': ast.get_docstring(tree) or '',
                'has_syntax_error': False
            }
            
            # 遍历AST
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_info = self._extract_class_info(node, module_id)
                    module_info['classes'].append(class_info['name'])
                    self.classes[f"{module_id}.{class_info['name']}"] = class_info
                    
                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    func_info = self._extract_function_info(node, module_id)
                    module_info['functions'].append(func_info['name'])
                    self.functions[f"{module_id}.{func_info['name']}"] = func_info
                    
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports[module_id].append({
                            'type': 'import',
                            'name': alias.name,
                            'alias': alias.asname
                        })
                        
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for alias in node.names:
                            self.imports[module_id].append({
                                'type': 'from_import',
                                'module': node.module,
                                'name': alias.name,
                                'alias': alias.asname
                            })
            
            module_info['imports'] = self.imports[module_id]
            self.modules[module_id] = module_info
            
            # 更新统计
            self.code_tree['stats']['total_modules'] += 1
            self.code_tree['stats']['total_classes'] += len(module_info['classes'])
            self.code_tree['stats']['total_functions'] += len(module_info['functions'])
            self.code_tree['stats']['total_lines'] += module_info['lines']
            
        except Exception as e:
            logger.warning(f"解析Python文件失败 {rel_path}: {e}")
    
    def _extract_class_info(self, node: ast.ClassDef, module_id: str) -> Dict:
        """提取类信息"""
        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(item.name)
        
        return {
            'name': node.name,
            'module': module_id,
            'bases': [self._get_name(base) for base in node.bases],
            'decorators': [self._get_decorator_name(d) for d in node.decorator_list],
            'methods': methods,
            'docstring': ast.get_docstring(node) or '',
            'lineno': node.lineno
        }
    
    def _extract_function_info(self, node, module_id: str) -> Dict:
        """提取函数信息"""
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        
        return {
            'name': node.name,
            'module': module_id,
            'args': args,
            'decorators': [self._get_decorator_name(d) for d in node.decorator_list],
            'is_async': isinstance(node, ast.AsyncFunctionDef),
            'docstring': ast.get_docstring(node) or '',
            'lineno': node.lineno
        }
    
    def _get_name(self, node) -> str:
        """获取AST节点名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_name(node.func)
        elif isinstance(node, ast.Subscript):
            return f"{self._get_name(node.value)}[...]"
        return str(node)
    
    def _get_decorator_name(self, node) -> str:
        """获取装饰器名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_decorator_name(node.func)
        return str(node)
    
    def _parse_code_file(self, file_path: str, rel_path: str, ext: str) -> None:
        """解析非Python代码文件（简化处理）"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            lang = self.code_extensions.get(ext, 'text')
            
            self.other_files[rel_path] = {
                'path': rel_path,
                'type': lang,
                'content': content,
                'lines': len(content.splitlines())
            }
            
        except Exception as e:
            logger.warning(f"读取代码文件失败 {rel_path}: {e}")
    
    def _parse_doc_file(self, file_path: str, rel_path: str) -> None:
        """解析文档文件"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            ext = os.path.splitext(file_path)[1].lower()
            
            self.other_files[rel_path] = {
                'path': rel_path,
                'type': 'markdown' if ext == '.md' else 'text',
                'content': content,
                'lines': len(content.splitlines())
            }
            
        except Exception as e:
            logger.warning(f"读取文档文件失败 {rel_path}: {e}")
    
    def _build_hierarchical_tree(self) -> None:
        """构建层次化代码树"""
        for module_id, module_info in self.modules.items():
            parts = module_id.split('.')
            
            current = self.code_tree['modules']
            for i, part in enumerate(parts[:-1]):
                if part not in current:
                    current[part] = {'_children': {}}
                current = current[part]['_children']
            
            # 添加模块信息
            final_part = parts[-1]
            current[final_part] = {
                'path': module_info['path'],
                'classes': module_info['classes'],
                'functions': module_info['functions'],
                'lines': module_info['lines'],
                'has_syntax_error': module_info.get('has_syntax_error', False)
            }
    
    def _identify_key_modules(self) -> None:
        """识别关键模块"""
        key_modules = []
        
        important_keywords = ['main', 'app', 'core', 'model', 'view', 'controller',
                            'service', 'api', 'router', 'handler', 'manager', 'engine',
                            'train', 'inference', 'predict', 'data', 'utils', 'config']
        
        for module_id, module_info in self.modules.items():
            # 跳过有语法错误的模块
            if module_info.get('has_syntax_error', False):
                continue
            
            score = 0.0
            
            # 1. 基于名称的语义分析
            name_lower = module_info['path'].lower()
            for keyword in important_keywords:
                if keyword in name_lower:
                    score += 2.0
                    break
            
            # 2. 根目录文件更重要
            if '/' not in module_info['path'] and '\\' not in module_info['path']:
                score += 3.0
            
            # 3. 类和函数数量
            score += len(module_info['classes']) * 0.5
            score += len(module_info['functions']) * 0.3
            
            # 4. 被导入次数
            import_count = sum(
                1 for imports in self.imports.values()
                for imp in imports
                if module_id in str(imp.get('module', '')) or module_id in str(imp.get('name', ''))
            )
            score += import_count * 1.5
            
            # 5. 特殊文件
            if module_info['path'] in ['main.py', 'app.py', '__init__.py', 'setup.py']:
                score += 5.0
            
            key_modules.append({
                'id': module_id,
                'name': os.path.basename(module_info['path']),
                'path': module_info['path'],
                'importance_score': score
            })
        
        # 按重要性排序
        key_modules.sort(key=lambda x: x['importance_score'], reverse=True)
        self.code_tree['key_modules'] = key_modules[:20]  # 保留前20个
    
    def get_repository_structure(self, max_depth: int = 3) -> str:
        """获取仓库目录结构（使用Tree抽象层）"""
        if self.tree_abstraction.tree_content:
            # 裁剪到指定深度
            lines = self.tree_abstraction.tree_content.split('\n')
            filtered_lines = []
            for line in lines:
                # 计算深度（基于缩进）
                stripped = line.lstrip('|`- ')
                indent_count = len(line) - len(stripped)
                depth = indent_count // 4
                
                if depth <= max_depth:
                    filtered_lines.append(line)
            
            return '\n'.join(filtered_lines[:200])  # 限制行数
        
        # 回退到旧方法
        return self._build_structure_fallback(max_depth)
    
    def _build_structure_fallback(self, max_depth: int) -> str:
        """构建目录结构的回退方法"""
        lines = []
        
        def _build_tree(path: str, prefix: str = "", depth: int = 0):
            if depth > max_depth:
                return
            
            try:
                entries = sorted(os.listdir(path))
            except:
                return
            
            # 过滤
            entries = [e for e in entries if e not in IGNORED_DIRS and not e.startswith('.')]
            
            dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
            files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
            
            # 限制数量
            if len(files) > 20:
                files = files[:10] + [f"... ({len(files) - 10} more files)"]
            
            for i, name in enumerate(dirs + files):
                is_last = (i == len(dirs) + len(files) - 1)
                connector = "└── " if is_last else "├── "
                
                if isinstance(name, str) and name.startswith("..."):
                    lines.append(f"{prefix}{connector}{name}")
                else:
                    full_path = os.path.join(path, name)
                    if os.path.isdir(full_path):
                        lines.append(f"{prefix}{connector}{name}/")
                        new_prefix = prefix + ("    " if is_last else "│   ")
                        _build_tree(full_path, new_prefix, depth + 1)
                    else:
                        lines.append(f"{prefix}{connector}{name}")
        
        lines.append(os.path.basename(self.repo_path) + "/")
        _build_tree(self.repo_path)
        
        return "\n".join(lines)
    
    def generate_llm_summary(self, max_tokens: int = 4000) -> str:
        """生成LLM可理解的仓库摘要"""
        summary_parts = []
        
        # 1. 基本统计
        summary_parts.append("## 仓库概览")
        summary_parts.append(f"- 总模块数: {self.code_tree['stats']['total_modules']}")
        summary_parts.append(f"- 总类数: {self.code_tree['stats']['total_classes']}")
        summary_parts.append(f"- 总函数数: {self.code_tree['stats']['total_functions']}")
        summary_parts.append(f"- 总代码行数: {self.code_tree['stats']['total_lines']}")
        
        # 解析统计
        if self.parse_stats['syntax_errors'] > 0:
            summary_parts.append(f"- ⚠️ 语法错误文件: {self.parse_stats['syntax_errors']} (已跳过)")
        summary_parts.append("")
        
        # 2. 目录结构
        summary_parts.append("## 目录结构")
        summary_parts.append("```")
        summary_parts.append(self.get_repository_structure(max_depth=2))
        summary_parts.append("```")
        summary_parts.append("")
        
        # 3. 关键模块
        if self.code_tree['key_modules']:
            summary_parts.append("## 关键模块")
            for module in self.code_tree['key_modules'][:10]:
                summary_parts.append(f"- **{module['path']}** (重要性: {module['importance_score']:.1f})")
            summary_parts.append("")
        
        # 4. README内容
        readme_files = [f for f in self.other_files.values() if 'readme' in f['path'].lower()]
        if readme_files:
            summary_parts.append("## README摘要")
            readme_content = readme_files[0]['content'][:2000]
            summary_parts.append(readme_content)
            summary_parts.append("")
        
        return "\n".join(summary_parts)
    
    def get_file_content(self, file_path: str) -> Optional[str]:
        """获取文件内容"""
        # 尝试从modules获取
        for module in self.modules.values():
            if module['path'] == file_path:
                return module['content']
        
        # 尝试从other_files获取
        for file_info in self.other_files.values():
            if file_info['path'] == file_path:
                return file_info['content']
        
        # 直接读取
        full_path = os.path.join(self.repo_path, file_path)
        if os.path.exists(full_path):
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except:
                pass
        
        return None
    
    def search_code(self, keyword: str, max_results: int = 10) -> List[Dict]:
        """搜索代码"""
        results = []
        keyword_lower = keyword.lower()
        
        # 搜索模块
        for module_id, module_info in self.modules.items():
            if keyword_lower in module_info['content'].lower():
                # 找到包含关键词的行
                lines = module_info['content'].splitlines()
                for i, line in enumerate(lines):
                    if keyword_lower in line.lower():
                        results.append({
                            'file': module_info['path'],
                            'line': i + 1,
                            'content': line.strip(),
                            'type': 'python'
                        })
                        if len(results) >= max_results:
                            return results
        
        # 搜索其他文件
        for file_id, file_info in self.other_files.items():
            if keyword_lower in file_info.get('content', '').lower():
                lines = file_info['content'].splitlines()
                for i, line in enumerate(lines):
                    if keyword_lower in line.lower():
                        results.append({
                            'file': file_info['path'],
                            'line': i + 1,
                            'content': line.strip(),
                            'type': file_info.get('type', 'text')
                        })
                        if len(results) >= max_results:
                            return results
        
        return results
    
    def get_flat_path(self, original_path: str) -> Optional[str]:
        """获取扁平化路径名称"""
        return self.tree_abstraction.get_flat_name(original_path)
    
    def get_original_from_flat(self, flat_name: str) -> Optional[str]:
        """从扁平化名称获取原始路径"""
        return self.tree_abstraction.get_original_path(flat_name)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'repo_path': self.repo_path,
            'stats': self.code_tree['stats'],
            'parse_stats': self.parse_stats,
            'key_modules': self.code_tree['key_modules'],
            'tree_abstraction': {
                'file_count': len(self.tree_abstraction.flat_paths),
                'tree_content_length': len(self.tree_abstraction.tree_content)
            },
            'modules': {k: {
                'path': v['path'],
                'classes': v['classes'],
                'functions': v['functions'],
                'lines': v['lines'],
                'has_syntax_error': v.get('has_syntax_error', False)
            } for k, v in self.modules.items()},
            'classes': {k: {
                'name': v['name'],
                'module': v['module'],
                'methods': v['methods']
            } for k, v in self.classes.items()},
            'functions': {k: {
                'name': v['name'],
                'module': v['module'],
                'args': v['args']
            } for k, v in self.functions.items()}
        }
    
    def save_json(self, output_path: str) -> None:
        """保存为JSON文件"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    # 测试
    import sys
    if len(sys.argv) > 1:
        repo_path = sys.argv[1]
    else:
        repo_path = "."
    
    builder = CodeTreeBuilder(repo_path)
    builder.parse_repository()
    
    print(builder.generate_llm_summary())
    print("\n--- Tree抽象层统计 ---")
    print(f"文件数: {len(builder.tree_abstraction.flat_paths)}")
    print(f"解析统计: {builder.parse_stats}")
