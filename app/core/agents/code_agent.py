#!/usr/bin/env python
"""
CheapBuy Code Agent - 整合RepoMaster完整能力
保持与原始接口的完全兼容，同时添加仓库理解、代码探索、Web搜索能力

原始接口（保持不变）:
- BaseCodeAgent: 抽象基类
- CodeGenerationAgent: 代码生成代理
- DebugAgent: 调试代理

新增能力:
- 层次化仓库分析
- 代码探索工具
- Web搜索
- 多轮任务执行
"""

import os
import re
import json
import asyncio
import aiohttp
import subprocess
from typing import Dict, List, Optional, Any, Callable, Annotated, Tuple
from datetime import datetime
from pathlib import Path
import logging
import uuid
from abc import ABC, abstractmethod
import ast

logger = logging.getLogger(__name__)


# ============================================================================
# 原始接口 - 保持完全兼容
# ============================================================================

class BaseCodeAgent(ABC):
    """代码代理基类 - 原始接口保持不变"""
    
    @abstractmethod
    async def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """分析代码或需求"""
        pass
    
    @abstractmethod
    async def generate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """生成代码或修复"""
        pass


class CodeGenerationAgent(BaseCodeAgent):
    """代码生成代理 - 原始接口保持不变，内部增强"""
    
    def __init__(self, ai_engine):
        self.ai_engine = ai_engine
        # 新增：可选的仓库分析能力
        self._repo_tools = None
        self._web_search = None
    
    def enable_repo_analysis(self, repo_path: str):
        """启用仓库分析能力（可选）"""
        try:
            self._repo_tools = CodeExplorerTools(repo_path)
            logger.info(f"Repository analysis enabled for: {repo_path}")
        except Exception as e:
            logger.warning(f"Failed to enable repo analysis: {e}")
    
    def enable_web_search(self):
        """启用Web搜索能力（可选）"""
        self._web_search = WebSearchEngine()
    
    async def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """分析用户需求，确定项目结构"""
        user_request = context.get("request", "")
        
        # 如果启用了仓库分析，添加仓库上下文
        repo_context = ""
        if self._repo_tools:
            try:
                repo_context = f"\n\n当前仓库结构：\n{self._repo_tools.list_repository_structure()[:2000]}"
                key_modules = self._repo_tools.get_key_modules(5)
                if key_modules:
                    repo_context += f"\n\n关键模块：\n" + "\n".join(
                        f"- {m['path']}" for m in key_modules
                    )
            except:
                pass
        
        # 构建分析提示词
        prompt = f"""
        分析以下需求，确定需要创建的项目结构：
        
        需求：{user_request}
        {repo_context}
        
        请返回JSON格式的项目结构，包括：
        1. project_type: 项目类型（python/javascript/mixed）
        2. files: 需要创建的文件列表，每个文件包含path和description
        3. dependencies: 项目依赖
        4. entry_point: 入口文件
        5. architecture: 简要架构说明
        """
        
        messages = [
            {"role": "system", "content": "你是一个专业的软件架构师"},
            {"role": "user", "content": prompt}
        ]
        
        response = await self.ai_engine.get_completion(
            messages=messages,
            model=context.get("model", "claude-opus-4-20250514-all"),
            temperature=0.7
        )
        
        # 解析响应
        try:
            json_match = re.search(r'```json\n(.*?)\n```', response["content"], re.DOTALL)
            if json_match:
                project_structure = json.loads(json_match.group(1))
            else:
                project_structure = json.loads(response["content"])
            
            return {
                "success": True,
                "project_structure": project_structure,
                "analysis": response["content"]
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "raw_response": response["content"]
            }
    
    async def generate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """生成项目代码"""
        project_structure = context.get("project_structure", {})
        user_request = context.get("request", "")
        
        generated_files = {}
        
        # 为每个文件生成代码
        for file_info in project_structure.get("files", []):
            file_path = file_info["path"]
            description = file_info.get("description", "")
            
            # 如果启用了仓库分析，搜索相关代码作为参考
            reference_code = ""
            if self._repo_tools and description:
                try:
                    search_results = self._repo_tools.search_keyword_include_code(
                        description.split()[0], max_results=3
                    )
                    if search_results and "No results" not in search_results:
                        reference_code = f"\n\n相关代码参考：\n{search_results[:1500]}"
                except:
                    pass
            
            prompt = f"""
            项目需求：{user_request}
            项目架构：{project_structure.get('architecture', '')}
            
            请生成文件 {file_path} 的完整代码：
            文件描述：{description}
            
            已生成的文件：
            {self._format_generated_files(generated_files)}
            {reference_code}
            
            要求：
            1. 代码要完整可运行
            2. 包含必要的错误处理
            3. 添加适当的注释
            4. 遵循最佳实践
            """
            
            messages = [
                {"role": "system", "content": "你是一个专业的程序员"},
                {"role": "user", "content": prompt}
            ]
            
            response = await self.ai_engine.get_completion(
                messages=messages,
                model=context.get("model", "claude-opus-4-20250514-all"),
                temperature=0.5
            )
            
            code = self._extract_code_from_response(response["content"])
            generated_files[file_path] = {
                "content": code,
                "description": description
            }
        
        return {
            "success": True,
            "files": generated_files,
            "project_structure": project_structure
        }
    
    def _format_generated_files(self, files: Dict[str, Dict]) -> str:
        """格式化已生成的文件信息"""
        if not files:
            return "无"
        
        result = []
        for path, info in files.items():
            result.append(f"- {path}: {info.get('description', '')}")
        
        return "\n".join(result)
    
    def _extract_code_from_response(self, response: str) -> str:
        """从AI响应中提取代码"""
        code_match = re.search(r'```(?:\w+)?\n(.*?)\n```', response, re.DOTALL)
        if code_match:
            return code_match.group(1)
        return response


class DebugAgent(BaseCodeAgent):
    """调试代理 - 分析错误并修复代码，原始接口保持不变"""
    
    def __init__(self, ai_engine):
        self.ai_engine = ai_engine
        self._web_search = None
    
    def enable_web_search(self):
        """启用Web搜索能力（可选）- 用于搜索错误解决方案"""
        self._web_search = WebSearchEngine()
    
    async def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """分析执行错误"""
        error_info = context.get("error_info", {})
        code = context.get("code", "")
        file_path = context.get("file_path", "")
        
        # 如果启用了Web搜索，尝试搜索解决方案
        web_solutions = ""
        if self._web_search:
            error_text = error_info.get('stderr', '')[:200]
            if error_text:
                try:
                    results = await self._web_search.search(
                        f"python {self._classify_error(error_text)} fix solution",
                        max_results=3
                    )
                    if results and 'error' not in results[0]:
                        web_solutions = "\n\n网络搜索解决方案：\n" + "\n".join(
                            f"- {r.get('title', '')}: {r.get('snippet', '')[:100]}"
                            for r in results[:3]
                        )
                except:
                    pass
        
        prompt = f"""
        分析以下代码执行错误：
        
        文件：{file_path}
        错误信息：
        {error_info.get('stderr', '')}
        
        退出码：{error_info.get('exit_code', 'N/A')}
        
        代码：
        ```
        {code}
        ```
        {web_solutions}
        
        请分析：
        1. 错误原因
        2. 错误位置
        3. 修复建议
        4. 是否需要修改其他相关文件
        """
        
        messages = [
            {"role": "system", "content": "你是一个专业的调试专家"},
            {"role": "user", "content": prompt}
        ]
        
        response = await self.ai_engine.get_completion(
            messages=messages,
            model=context.get("model", "claude-opus-4-20250514-all"),
            temperature=0.3
        )
        
        return {
            "success": True,
            "analysis": response["content"],
            "error_type": self._classify_error(error_info.get('stderr', ''))
        }
    
    async def generate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """生成修复后的代码"""
        analysis = context.get("analysis", "")
        code = context.get("code", "")
        file_path = context.get("file_path", "")
        
        prompt = f"""
        基于错误分析，修复以下代码：
        
        错误分析：
        {analysis}
        
        原始代码：
        ```
        {code}
        ```
        
        请提供：
        1. 修复后的完整代码
        2. 修改说明
        3. 测试建议
        """
        
        messages = [
            {"role": "system", "content": "你是一个专业的程序员"},
            {"role": "user", "content": prompt}
        ]
        
        response = await self.ai_engine.get_completion(
            messages=messages,
            model=context.get("model", "claude-opus-4-20250514-all"),
            temperature=0.3
        )
        
        fixed_code = self._extract_code_from_response(response["content"])
        
        return {
            "success": True,
            "fixed_code": fixed_code,
            "explanation": response["content"],
            "changes": self._identify_changes(code, fixed_code)
        }
    
    def _classify_error(self, stderr: str) -> str:
        """分类错误类型"""
        if "SyntaxError" in stderr:
            return "syntax_error"
        elif "ImportError" in stderr or "ModuleNotFoundError" in stderr:
            return "import_error"
        elif "NameError" in stderr:
            return "name_error"
        elif "TypeError" in stderr:
            return "type_error"
        elif "AttributeError" in stderr:
            return "attribute_error"
        elif "ValueError" in stderr:
            return "value_error"
        elif "KeyError" in stderr:
            return "key_error"
        elif "IndexError" in stderr:
            return "index_error"
        elif "FileNotFoundError" in stderr:
            return "file_error"
        else:
            return "runtime_error"
    
    def _identify_changes(self, original: str, fixed: str) -> List[Dict[str, Any]]:
        """识别代码变更"""
        original_lines = original.splitlines()
        fixed_lines = fixed.splitlines()
        
        changes = []
        if len(original_lines) != len(fixed_lines):
            changes.append({
                "type": "lines_changed",
                "original_count": len(original_lines),
                "fixed_count": len(fixed_lines)
            })
        
        return changes

    def _extract_code_from_response(self, response: str) -> str:
        """从AI响应中提取代码"""
        code_match = re.search(r'```(?:\w+)?\n(.*?)\n```', response, re.DOTALL)
        if code_match:
            return code_match.group(1)
        return response


# ============================================================================
# 新增组件 - RepoMaster能力
# ============================================================================

class WebSearchEngine:
    """Web搜索引擎 - 基于Serper API"""
    
    def __init__(self):
        self.api_key = os.environ.get('SERPER_API_KEY', '')
        self.jina_key = os.environ.get('JINA_API_KEY', '')
        self.search_url = "https://google.serper.dev/search"
    
    async def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """执行Google搜索"""
        if not self.api_key:
            return [{"error": "SERPER_API_KEY not configured"}]
        
        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }
        
        payload = {
            'q': query,
            'gl': 'us',
            'hl': 'en',
            'num': max_results
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.search_url, 
                    headers=headers, 
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = []
                        for item in data.get('organic', []):
                            results.append({
                                'title': item.get('title', ''),
                                'snippet': item.get('snippet', ''),
                                'link': item.get('link', '')
                            })
                        return results
                    else:
                        return [{"error": f"Search API error: {response.status}"}]
        except asyncio.TimeoutError:
            return [{"error": "Search timeout"}]
        except Exception as e:
            return [{"error": str(e)}]
    
    async def browse(self, url: str, max_length: int = 20000) -> str:
        """浏览URL获取内容"""
        try:
            jina_url = f"https://r.jina.ai/{url}"
            
            headers = {'X-Return-Format': 'markdown', 'X-Timeout': '15'}
            if self.jina_key:
                headers['Authorization'] = f"Bearer {self.jina_key}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    jina_url, 
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    content = await response.text()
                    content = self._clean_content(content)
                    
                    if len(content) > max_length:
                        content = content[:max_length] + "\n... [truncated]"
                    
                    return content
                    
        except Exception as e:
            return f"Error browsing URL: {e}"
    
    def _clean_content(self, content: str) -> str:
        """清理网页内容"""
        content = re.sub(r'http[s]?://\S+', '', content)
        content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)
        content = re.sub(r'<[^>]+>', '', content)
        content = '\n'.join(line.strip() for line in content.split('\n') if line.strip())
        content = re.sub(r'\n{3,}', '\n\n', content)
        return content.strip()


class CodeExplorerTools:
    """代码探索工具集 - 基于RepoMaster的仓库分析能力"""
    
    # 忽略的目录
    IGNORED_DIRS = {
        '__pycache__', '.git', '.svn', '.hg', 'node_modules', 'venv', '.venv',
        'env', '.env', 'build', 'dist', '.eggs', '.tox', '.nox',
        '.pytest_cache', '.mypy_cache', '.idea', '.vscode', '.cache'
    }
    
    # 忽略的文件模式
    IGNORED_PATTERNS = [
        r'.*\.pyc$', r'.*\.pyo$', r'.*\.so$', r'.*\.dll$',
        r'.*\.exe$', r'.*\.bin$', r'.*\.pkl$', r'.*\.pt$',
        r'.*\.jpg$', r'.*\.jpeg$', r'.*\.png$', r'.*\.gif$',
        r'.*\.zip$', r'.*\.tar$', r'.*\.gz$', r'.*\.rar$',
        r'.*\.log$', r'.*\.lock$',
    ]
    
    def __init__(self, repo_path: str, work_dir: str = None):
        self.repo_path = os.path.abspath(repo_path)
        self.work_dir = work_dir or repo_path
        
        # 解析仓库
        self.modules: Dict[str, Dict] = {}
        self.classes: Dict[str, Dict] = {}
        self.functions: Dict[str, Dict] = {}
        self.imports: Dict[str, List] = {}
        
        self._parse_repository()
        
        logger.info(f"CodeExplorerTools: {len(self.modules)} modules, {len(self.classes)} classes, {len(self.functions)} functions")
    
    def _should_ignore(self, path: str) -> bool:
        """检查是否应该忽略"""
        for part in path.split(os.sep):
            if part in self.IGNORED_DIRS:
                return True
        
        filename = os.path.basename(path)
        for pattern in self.IGNORED_PATTERNS:
            if re.match(pattern, filename, re.IGNORECASE):
                return True
        
        return False
    
    def _parse_repository(self, max_depth: int = 4) -> None:
        """解析仓库"""
        for root, dirs, files in os.walk(self.repo_path):
            rel_path = os.path.relpath(root, self.repo_path)
            current_depth = 0 if rel_path == '.' else len(rel_path.split(os.sep))
            
            if current_depth > max_depth:
                dirs[:] = []
                continue
            
            dirs[:] = [d for d in dirs if d not in self.IGNORED_DIRS]
            
            if len(files) > 100:
                continue
            
            for file in files[:50]:
                if not file.endswith('.py'):
                    continue
                
                file_path = os.path.join(root, file)
                rel_file_path = os.path.relpath(file_path, self.repo_path)
                
                if self._should_ignore(rel_file_path):
                    continue
                
                try:
                    file_size = os.path.getsize(file_path)
                    if file_size > 5 * 1024 * 1024:  # 5MB
                        continue
                    
                    self._parse_python_file(file_path, rel_file_path)
                except Exception as e:
                    logger.debug(f"Parse error {rel_file_path}: {e}")
    
    def _parse_python_file(self, file_path: str, rel_path: str) -> None:
        """解析Python文件"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            tree = ast.parse(content)
            module_id = rel_path.replace('/', '.').replace('\\', '.').rstrip('.py')
            
            self.modules[module_id] = {
                'id': module_id,
                'path': rel_path,
                'content': content,
                'lines': len(content.splitlines()),
                'classes': [],
                'functions': [],
                'docstring': ast.get_docstring(tree) or ''
            }
            
            self.imports[module_id] = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_id = f"{module_id}.{node.name}"
                    methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    self.classes[class_id] = {
                        'name': node.name,
                        'module': module_id,
                        'methods': methods,
                        'bases': [self._get_name(b) for b in node.bases],
                        'docstring': ast.get_docstring(node) or '',
                        'lineno': node.lineno
                    }
                    self.modules[module_id]['classes'].append(node.name)
                    
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # 只记录顶层函数
                    func_id = f"{module_id}.{node.name}"
                    if func_id not in self.functions:
                        args = [arg.arg for arg in node.args.args]
                        self.functions[func_id] = {
                            'name': node.name,
                            'module': module_id,
                            'args': args,
                            'is_async': isinstance(node, ast.AsyncFunctionDef),
                            'docstring': ast.get_docstring(node) or '',
                            'lineno': node.lineno
                        }
                        if node.name not in self.modules[module_id]['functions']:
                            self.modules[module_id]['functions'].append(node.name)
                
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports[module_id].append({
                            'type': 'import',
                            'name': alias.name
                        })
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for alias in node.names:
                            self.imports[module_id].append({
                                'type': 'importfrom',
                                'module': node.module,
                                'name': alias.name
                            })
        
        except SyntaxError:
            pass
        except Exception as e:
            logger.debug(f"Parse error: {e}")
    
    def _get_name(self, node) -> str:
        """从AST节点获取名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        return str(node)
    
    def list_repository_structure(self, path: str = None, max_depth: int = 3) -> str:
        """列出仓库目录结构"""
        target = path or self.repo_path
        if not os.path.isabs(target):
            target = os.path.join(self.repo_path, target)
        
        lines = []
        
        def build_tree(p: str, prefix: str = "", depth: int = 0):
            if depth > max_depth:
                return
            
            try:
                entries = sorted(os.listdir(p))
            except:
                return
            
            entries = [e for e in entries if e not in self.IGNORED_DIRS and not e.startswith('.')]
            dirs = [e for e in entries if os.path.isdir(os.path.join(p, e))]
            files = [e for e in entries if os.path.isfile(os.path.join(p, e))]
            
            if len(files) > 15:
                files = files[:8] + [f"... ({len(files) - 8} more)"]
            
            for i, name in enumerate(dirs + files):
                is_last = (i == len(dirs) + len(files) - 1)
                connector = "└── " if is_last else "├── "
                
                if isinstance(name, str) and name.startswith("..."):
                    lines.append(f"{prefix}{connector}{name}")
                else:
                    full = os.path.join(p, name)
                    if os.path.isdir(full):
                        lines.append(f"{prefix}{connector}{name}/")
                        new_prefix = prefix + ("    " if is_last else "│   ")
                        build_tree(full, new_prefix, depth + 1)
                    else:
                        lines.append(f"{prefix}{connector}{name}")
        
        lines.append(os.path.basename(self.repo_path) + "/")
        build_tree(self.repo_path)
        
        return "\n".join(lines)
    
    def search_keyword_include_code(self, keyword: str, max_results: int = 15) -> str:
        """搜索包含关键词的代码"""
        results = []
        keyword_lower = keyword.lower()
        
        for module_id, module_info in self.modules.items():
            if keyword_lower in module_info.get('content', '').lower():
                lines = module_info['content'].splitlines()
                for i, line in enumerate(lines, 1):
                    if keyword_lower in line.lower():
                        results.append({
                            'file': module_info['path'],
                            'line': i,
                            'content': line.strip()[:100]
                        })
                        if len(results) >= max_results:
                            break
            if len(results) >= max_results:
                break
        
        if not results:
            return f"No results found for '{keyword}'"
        
        output = [f"## Search: '{keyword}' ({len(results)} matches)\n"]
        for r in results:
            output.append(f"**{r['file']}:{r['line']}**: `{r['content']}`")
        
        return "\n".join(output)
    
    def view_file_content(self, file_path: str, start_line: int = 1, end_line: int = 150) -> str:
        """查看文件内容"""
        # 尝试多种路径
        paths = [file_path, os.path.join(self.repo_path, file_path)]
        
        content = None
        for p in paths:
            if os.path.exists(p):
                try:
                    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    break
                except:
                    continue
        
        # 尝试从缓存获取
        if content is None:
            module_id = file_path.replace('/', '.').replace('\\', '.').rstrip('.py')
            if module_id in self.modules:
                content = self.modules[module_id].get('content')
        
        if content is None:
            return f"File not found: {file_path}"
        
        lines = content.splitlines()
        total = len(lines)
        start_line = max(1, start_line)
        end_line = min(total, end_line)
        
        selected = lines[start_line-1:end_line]
        
        output = f"## {file_path} (lines {start_line}-{end_line} of {total})\n```\n"
        for i, line in enumerate(selected, start=start_line):
            output += f"{i:4d} | {line}\n"
        output += "```"
        
        return output
    
    def view_function_details(self, function_name: str) -> str:
        """查看函数详情"""
        for func_id, info in self.functions.items():
            if info['name'] == function_name or func_id.endswith(f".{function_name}"):
                return f"""
## Function: {info['name']}
- Module: {info['module']}
- Args: {', '.join(info.get('args', [])) or 'None'}
- Async: {'Yes' if info.get('is_async') else 'No'}
- Line: {info.get('lineno', 'N/A')}

### Docstring
{info.get('docstring') or 'No documentation'}
"""
        
        matches = [fid for fid in self.functions if function_name.lower() in fid.lower()]
        if matches:
            return f"Function '{function_name}' not found. Did you mean:\n" + "\n".join(f"- {m}" for m in matches[:5])
        return f"Function not found: {function_name}"
    
    def view_class_details(self, class_name: str) -> str:
        """查看类详情"""
        for class_id, info in self.classes.items():
            if info['name'] == class_name or class_id.endswith(f".{class_name}"):
                methods = ', '.join(info.get('methods', [])[:15])
                if len(info.get('methods', [])) > 15:
                    methods += f" ... (+{len(info['methods']) - 15} more)"
                
                return f"""
## Class: {info['name']}
- Module: {info['module']}
- Bases: {', '.join(info.get('bases', [])) or 'object'}
- Line: {info.get('lineno', 'N/A')}
- Methods: {methods}

### Docstring
{info.get('docstring') or 'No documentation'}
"""
        
        matches = [cid for cid in self.classes if class_name.lower() in cid.lower()]
        if matches:
            return f"Class '{class_name}' not found. Did you mean:\n" + "\n".join(f"- {m}" for m in matches[:5])
        return f"Class not found: {class_name}"
    
    def get_key_modules(self, top_n: int = 10) -> List[Dict]:
        """获取关键模块"""
        results = []
        
        important_keywords = ['main', 'core', 'api', 'service', 'app', 'model', 'handler']
        
        for module_id, info in self.modules.items():
            score = 0.0
            path = info.get('path', '').lower()
            
            for kw in important_keywords:
                if kw in path:
                    score += 2.0
                    break
            
            if '/' not in path and '\\' not in path:
                score += 3.0
            
            score += len(info.get('classes', [])) * 0.5
            score += len(info.get('functions', [])) * 0.3
            
            if path in ['main.py', 'app.py', '__init__.py']:
                score += 5.0
            
            results.append({
                'id': module_id,
                'path': info['path'],
                'importance_score': score
            })
        
        results.sort(key=lambda x: x['importance_score'], reverse=True)
        return results[:top_n]


class ScriptExecutor:
    """脚本执行器"""
    
    def __init__(self, work_dir: str):
        self.work_dir = os.path.abspath(work_dir)
        os.makedirs(self.work_dir, exist_ok=True)
    
    async def execute(self, code: str, language: str = "python", timeout: int = 300) -> Dict[str, Any]:
        """执行代码"""
        if language.lower() in ['python', 'py']:
            ext, cmd = '.py', ['python']
        elif language.lower() in ['bash', 'shell', 'sh']:
            ext, cmd = '.sh', ['bash']
        else:
            return {'success': False, 'error': f'Unsupported language: {language}'}
        
        script_id = str(uuid.uuid4())[:8]
        script_path = os.path.join(self.work_dir, f'script_{script_id}{ext}')
        
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(code)
        
        if ext == '.sh':
            os.chmod(script_path, 0o755)
        
        try:
            start = datetime.now()
            
            process = await asyncio.create_subprocess_exec(
                *cmd, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            
            return {
                'success': process.returncode == 0,
                'exit_code': process.returncode,
                'stdout': stdout.decode('utf-8', errors='ignore'),
                'stderr': stderr.decode('utf-8', errors='ignore'),
                'execution_time': (datetime.now() - start).total_seconds(),
                'script_path': script_path
            }
            
        except asyncio.TimeoutError:
            return {'success': False, 'error': f'Timeout ({timeout}s)', 'script_path': script_path}
        except Exception as e:
            return {'success': False, 'error': str(e), 'script_path': script_path}


# ============================================================================
# 增强版Agent - 新增功能（不影响原有接口）
# ============================================================================

class EnhancedCodeAgent:
    """
    增强版代码Agent - 整合RepoMaster完整能力
    
    这是一个独立的类，不影响原有的CodeGenerationAgent和DebugAgent
    提供更强大的仓库理解和任务执行能力
    """
    
    def __init__(
        self,
        ai_engine=None,
        work_dir: str = "./workspace",
        model: str = "claude-opus-4-5-20251101",
        max_turns: int = 30
    ):
        self.ai_engine = ai_engine
        self.work_dir = os.path.abspath(work_dir)
        self.model = model
        self.max_turns = max_turns
        
        os.makedirs(self.work_dir, exist_ok=True)
        
        self.script_executor = ScriptExecutor(os.path.join(self.work_dir, 'scripts'))
        self.web_search = WebSearchEngine()
        
        self.current_repo: Optional[str] = None
        self.code_tools: Optional[CodeExplorerTools] = None
        self.conversation_history: List[Dict] = []
    
    def set_repo(self, repo_path: str) -> None:
        """设置当前仓库"""
        self.current_repo = repo_path
        self.code_tools = CodeExplorerTools(repo_path, self.work_dir)
    
    async def execute_task(
        self,
        task: str,
        repo_path: Optional[str] = None,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """执行任务"""
        start_time = datetime.now()
        
        if repo_path:
            self.set_repo(repo_path)
        
        # 构建上下文
        repo_summary = ""
        if self.code_tools:
            repo_summary = f"""
## Repository Structure
{self.code_tools.list_repository_structure(max_depth=2)}

## Key Modules
{chr(10).join(f"- {m['path']}" for m in self.code_tools.get_key_modules(5))}
"""
        
        user_prompt = f"""
## Task
{task}

{repo_summary}

Please complete this task step by step. Say "TERMINATE" when done.
"""
        
        self.conversation_history = [{"role": "user", "content": user_prompt}]
        
        turn_count = 0
        final_result = None
        
        while turn_count < self.max_turns:
            turn_count += 1
            
            try:
                if self.ai_engine:
                    response = await self.ai_engine.get_completion(
                        messages=self.conversation_history,
                        model=self.model,
                        temperature=0.3,
                        max_tokens=4096
                    )
                    message = response.get('content', '')
                else:
                    message = "AI engine not configured"
                
                self.conversation_history.append({"role": "assistant", "content": message})
                
                if 'TERMINATE' in message.upper():
                    final_result = {'success': True, 'message': message, 'turns': turn_count}
                    break
                
                # 执行工具调用
                tool_results = await self._execute_tools(message)
                
                if tool_results:
                    self.conversation_history.append({
                        "role": "user",
                        "content": f"## Tool Results\n\n{tool_results}"
                    })
                else:
                    final_result = {'success': True, 'message': message, 'turns': turn_count}
                    break
                    
            except Exception as e:
                self.conversation_history.append({
                    "role": "user",
                    "content": f"Error: {e}\nPlease try again."
                })
        
        if not final_result:
            final_result = {'success': False, 'message': 'Max turns reached', 'turns': turn_count}
        
        final_result['duration'] = (datetime.now() - start_time).total_seconds()
        return final_result
    
    async def _execute_tools(self, message: str) -> str:
        """执行工具调用"""
        results = []
        
        # 执行代码块
        code_blocks = re.findall(r'```(python|bash)\n(.*?)```', message, re.DOTALL)
        for lang, code in code_blocks:
            if 'execute' in message.lower() or 'run' in message.lower():
                result = await self.script_executor.execute(code.strip(), lang)
                output = f"## Execution ({lang})\n"
                output += f"Success: {result.get('success')}\n"
                if result.get('stdout'):
                    output += f"```\n{result['stdout'][:2000]}\n```"
                if result.get('stderr'):
                    output += f"\nErrors:\n```\n{result['stderr'][:1000]}\n```"
                results.append(output)
        
        return "\n\n---\n\n".join(results) if results else ""


# ============================================================================
# 工厂函数和便捷方法
# ============================================================================

def create_code_agent(ai_engine, enable_repo: bool = False, repo_path: str = None) -> CodeGenerationAgent:
    """创建CodeGenerationAgent（原始接口）"""
    agent = CodeGenerationAgent(ai_engine)
    if enable_repo and repo_path:
        agent.enable_repo_analysis(repo_path)
    return agent


def create_debug_agent(ai_engine, enable_web_search: bool = False) -> DebugAgent:
    """创建DebugAgent（原始接口）"""
    agent = DebugAgent(ai_engine)
    if enable_web_search:
        agent.enable_web_search()
    return agent


def create_enhanced_agent(ai_engine=None, work_dir: str = "./workspace") -> EnhancedCodeAgent:
    """创建EnhancedCodeAgent（新增功能）"""
    return EnhancedCodeAgent(ai_engine=ai_engine, work_dir=work_dir)


# 保持向后兼容的别名
RepoAnalysisAgent = EnhancedCodeAgent