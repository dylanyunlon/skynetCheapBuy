#!/usr/bin/env python
"""
CheapBuy Repository Analyzer Service
整合代码树构建和重要性分析，提供完整的仓库理解能力

v2.0 更新:
- 集成Tree抽象层
- 优化大型仓库处理
- 增强错误处理和日志记录

功能:
1. 克隆/加载Git仓库
2. 解析仓库结构
3. 分析代码重要性
4. 生成LLM可理解的摘要
5. 提供代码搜索和导航
6. Tree抽象层支持
"""

import os
import re
import json
import shutil
import subprocess
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from datetime import datetime
import logging
import tempfile
import uuid

from .tree_builder import CodeTreeBuilder, TreeAbstraction, should_ignore_path
from .importance_analyzer import ImportanceAnalyzer, FileImportanceCalculator

logger = logging.getLogger(__name__)


class RepoAnalyzer:
    """
    仓库分析器 - 提供完整的代码仓库理解能力
    
    核心能力:
    1. Git仓库克隆和管理
    2. 代码结构解析
    3. 重要性分析
    4. 代码搜索
    5. LLM摘要生成
    6. Tree抽象层支持
    """
    
    def __init__(self, work_dir: str = "./workspace/repos"):
        """
        初始化仓库分析器
        
        Args:
            work_dir: 工作目录，用于存储克隆的仓库
        """
        self.work_dir = os.path.abspath(work_dir)
        os.makedirs(self.work_dir, exist_ok=True)
        
        # 已分析的仓库缓存
        self._repo_cache: Dict[str, Dict] = {}
        
        # Tree抽象层缓存
        self._tree_cache: Dict[str, TreeAbstraction] = {}
        
        logger.info(f"RepoAnalyzer initialized with work_dir: {self.work_dir}")
    
    async def analyze_repository(
        self,
        repo_source: str,
        force_refresh: bool = False,
        max_depth: int = 4,
        use_tree_abstraction: bool = True
    ) -> Dict[str, Any]:
        """
        分析代码仓库
        
        Args:
            repo_source: 仓库来源 (Git URL 或本地路径)
            force_refresh: 是否强制刷新（重新克隆/解析）
            max_depth: 最大解析深度
            use_tree_abstraction: 是否使用Tree抽象层
            
        Returns:
            分析结果字典
        """
        # 确定仓库类型和路径
        repo_type, repo_path, repo_name = await self._resolve_repo_source(repo_source, force_refresh)
        
        # 检查缓存
        cache_key = f"{repo_type}:{repo_source}"
        if not force_refresh and cache_key in self._repo_cache:
            logger.info(f"使用缓存的分析结果: {repo_name}")
            return self._repo_cache[cache_key]
        
        logger.info(f"开始分析仓库: {repo_name} (type={repo_type})")
        
        try:
            # 构建代码树
            tree_builder = CodeTreeBuilder(repo_path)
            tree_builder.parse_repository(max_depth=max_depth)
            
            # 分析重要性
            importance_analyzer = ImportanceAnalyzer(
                repo_path=repo_path,
                modules=tree_builder.modules,
                classes=tree_builder.classes,
                functions=tree_builder.functions,
                imports=tree_builder.imports
            )
            
            # 获取关键模块
            key_modules = importance_analyzer.get_key_modules(top_n=20)
            
            # 获取入口点
            entry_points = importance_analyzer.get_entry_points()
            
            # 构建分析结果
            result = {
                'success': True,
                'repo_name': repo_name,
                'repo_path': repo_path,
                'repo_type': repo_type,
                'repo_source': repo_source,
                'analyzed_at': datetime.utcnow().isoformat(),
                
                # 统计信息
                'stats': tree_builder.code_tree['stats'],
                
                # 解析统计（新增）
                'parse_stats': tree_builder.parse_stats,
                
                # 结构信息
                'structure': tree_builder.get_repository_structure(max_depth=3),
                
                # 关键组件
                'key_modules': key_modules,
                'entry_points': entry_points,
                
                # LLM摘要
                'llm_summary': tree_builder.generate_llm_summary(max_tokens=4000),
                
                # Tree抽象层信息（新增）
                'tree_abstraction': {
                    'enabled': use_tree_abstraction,
                    'flat_paths_count': len(tree_builder.tree_abstraction.flat_paths),
                    'tree_content_preview': tree_builder.tree_abstraction.tree_content[:1000] if tree_builder.tree_abstraction.tree_content else ''
                },
                
                # 引用（用于后续操作）
                '_tree_builder': tree_builder,
                '_importance_analyzer': importance_analyzer,
                '_tree_abstraction': tree_builder.tree_abstraction
            }
            
            # 缓存结果
            self._repo_cache[cache_key] = result
            self._tree_cache[cache_key] = tree_builder.tree_abstraction
            
            logger.info(f"仓库分析完成: {repo_name}, 模块数={result['stats']['total_modules']}, "
                       f"语法错误={result['parse_stats']['syntax_errors']}")
            
            return result
            
        except Exception as e:
            logger.error(f"仓库分析失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'repo_source': repo_source
            }
    
    async def build_tree_abstraction_only(
        self,
        repo_source: str,
        max_depth: int = 5
    ) -> Dict[str, Any]:
        """
        仅构建Tree抽象层（轻量级，用于快速预览）
        
        Args:
            repo_source: 仓库来源
            max_depth: 最大深度
            
        Returns:
            Tree抽象层信息
        """
        repo_type, repo_path, repo_name = await self._resolve_repo_source(repo_source, False)
        
        logger.info(f"构建Tree抽象层: {repo_name}")
        
        tree_abs = TreeAbstraction(repo_path)
        tree_content = tree_abs.build(max_depth=max_depth)
        
        return {
            'success': True,
            'repo_name': repo_name,
            'tree_content': tree_content,
            'flat_paths_count': len(tree_abs.flat_paths),
            'file_count': tree_abs.file_count,
            'dir_count': tree_abs.dir_count
        }
    
    async def _resolve_repo_source(
        self,
        repo_source: str,
        force_refresh: bool
    ) -> Tuple[str, str, str]:
        """
        解析仓库来源
        
        Returns:
            (repo_type, repo_path, repo_name)
        """
        # 检查是否是Git URL
        if repo_source.startswith('http://') or repo_source.startswith('https://') or repo_source.startswith('git@'):
            # Git URL
            repo_name = self._extract_repo_name(repo_source)
            repo_path = os.path.join(self.work_dir, repo_name)
            
            # 克隆或更新仓库
            if os.path.exists(repo_path):
                if force_refresh:
                    shutil.rmtree(repo_path)
                    await self._clone_repo(repo_source, repo_path)
                else:
                    # 尝试更新
                    await self._update_repo(repo_path)
            else:
                await self._clone_repo(repo_source, repo_path)
            
            return 'git', repo_path, repo_name
        
        elif os.path.isdir(repo_source):
            # 本地目录
            repo_path = os.path.abspath(repo_source)
            repo_name = os.path.basename(repo_path)
            return 'local', repo_path, repo_name
        
        else:
            raise ValueError(f"无效的仓库来源: {repo_source}")
    
    def _extract_repo_name(self, url: str) -> str:
        """从URL提取仓库名称"""
        # 移除.git后缀
        url = url.rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]
        
        # 提取最后一部分作为名称
        return url.split('/')[-1]
    
    async def _clone_repo(self, url: str, target_path: str) -> None:
        """克隆Git仓库"""
        logger.info(f"克隆仓库: {url} -> {target_path}")
        
        cmd = ['git', 'clone', '--depth', '1', url, target_path]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        
        if process.returncode != 0:
            error_msg = stderr.decode('utf-8', errors='ignore')
            raise RuntimeError(f"Git克隆失败: {error_msg}")
        
        logger.info(f"仓库克隆完成: {target_path}")
    
    async def _update_repo(self, repo_path: str) -> None:
        """更新Git仓库"""
        try:
            cmd = ['git', '-C', repo_path, 'pull', '--ff-only']
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await asyncio.wait_for(process.communicate(), timeout=60)
            
        except Exception as e:
            logger.warning(f"仓库更新失败（忽略）: {e}")
    
    def search_code(
        self,
        repo_source: str,
        keyword: str,
        max_results: int = 20
    ) -> List[Dict]:
        """
        在仓库中搜索代码
        
        Args:
            repo_source: 仓库来源
            keyword: 搜索关键词
            max_results: 最大结果数
            
        Returns:
            搜索结果列表
        """
        cache_key = f"git:{repo_source}" if repo_source.startswith('http') else f"local:{repo_source}"
        
        if cache_key not in self._repo_cache:
            logger.warning(f"仓库未分析，无法搜索: {repo_source}")
            return []
        
        tree_builder = self._repo_cache[cache_key].get('_tree_builder')
        if not tree_builder:
            return []
        
        return tree_builder.search_code(keyword, max_results)
    
    def search_files_by_path(
        self,
        repo_source: str,
        keyword: str,
        limit: int = 20
    ) -> List[str]:
        """
        按路径搜索文件（使用Tree抽象层）
        
        Args:
            repo_source: 仓库来源
            keyword: 搜索关键词
            limit: 最大结果数
            
        Returns:
            文件路径列表
        """
        cache_key = f"git:{repo_source}" if repo_source.startswith('http') else f"local:{repo_source}"
        
        if cache_key not in self._tree_cache:
            logger.warning(f"Tree抽象层未构建: {repo_source}")
            return []
        
        tree_abs = self._tree_cache[cache_key]
        return tree_abs.search_files(keyword, limit)
    
    def get_flat_path(self, repo_source: str, original_path: str) -> Optional[str]:
        """获取扁平化路径"""
        cache_key = f"git:{repo_source}" if repo_source.startswith('http') else f"local:{repo_source}"
        
        if cache_key not in self._tree_cache:
            return None
        
        return self._tree_cache[cache_key].get_flat_name(original_path)
    
    def get_original_path(self, repo_source: str, flat_name: str) -> Optional[str]:
        """从扁平化名称获取原始路径"""
        cache_key = f"git:{repo_source}" if repo_source.startswith('http') else f"local:{repo_source}"
        
        if cache_key not in self._tree_cache:
            return None
        
        return self._tree_cache[cache_key].get_original_path(flat_name)
    
    def get_file_content(self, repo_source: str, file_path: str) -> Optional[str]:
        """获取仓库中文件的内容"""
        cache_key = f"git:{repo_source}" if repo_source.startswith('http') else f"local:{repo_source}"
        
        if cache_key not in self._repo_cache:
            return None
        
        tree_builder = self._repo_cache[cache_key].get('_tree_builder')
        if not tree_builder:
            return None
        
        return tree_builder.get_file_content(file_path)
    
    def get_function_details(self, repo_source: str, function_name: str) -> Optional[Dict]:
        """获取函数详情"""
        cache_key = f"git:{repo_source}" if repo_source.startswith('http') else f"local:{repo_source}"
        
        if cache_key not in self._repo_cache:
            return None
        
        tree_builder = self._repo_cache[cache_key].get('_tree_builder')
        if not tree_builder:
            return None
        
        # 搜索函数
        for func_id, func_info in tree_builder.functions.items():
            if func_info['name'] == function_name or func_id.endswith(f".{function_name}"):
                return func_info
        
        return None
    
    def get_class_details(self, repo_source: str, class_name: str) -> Optional[Dict]:
        """获取类详情"""
        cache_key = f"git:{repo_source}" if repo_source.startswith('http') else f"local:{repo_source}"
        
        if cache_key not in self._repo_cache:
            return None
        
        tree_builder = self._repo_cache[cache_key].get('_tree_builder')
        if not tree_builder:
            return None
        
        # 搜索类
        for class_id, class_info in tree_builder.classes.items():
            if class_info['name'] == class_name or class_id.endswith(f".{class_name}"):
                return class_info
        
        return None
    
    def list_repository_structure(self, repo_source: str, max_depth: int = 3) -> str:
        """列出仓库结构"""
        cache_key = f"git:{repo_source}" if repo_source.startswith('http') else f"local:{repo_source}"
        
        if cache_key in self._repo_cache:
            tree_builder = self._repo_cache[cache_key].get('_tree_builder')
            if tree_builder:
                return tree_builder.get_repository_structure(max_depth)
        
        return "仓库未分析"
    
    def get_tree_abstraction(self, repo_source: str) -> Optional[Dict]:
        """获取Tree抽象层信息"""
        cache_key = f"git:{repo_source}" if repo_source.startswith('http') else f"local:{repo_source}"
        
        if cache_key not in self._tree_cache:
            return None
        
        tree_abs = self._tree_cache[cache_key]
        return tree_abs.to_dict()
    
    def cleanup_repo(self, repo_source: str) -> bool:
        """清理克隆的仓库"""
        try:
            repo_name = self._extract_repo_name(repo_source)
            repo_path = os.path.join(self.work_dir, repo_name)
            
            if os.path.exists(repo_path):
                shutil.rmtree(repo_path)
                
            # 清除缓存
            cache_key = f"git:{repo_source}"
            if cache_key in self._repo_cache:
                del self._repo_cache[cache_key]
            if cache_key in self._tree_cache:
                del self._tree_cache[cache_key]
            
            logger.info(f"已清理仓库: {repo_name}")
            return True
            
        except Exception as e:
            logger.error(f"清理仓库失败: {e}")
            return False


class RepoAnalyzerTools:
    """
    仓库分析工具集 - 提供给Agent调用的工具函数
    
    这些函数可以注册为AutoGen工具，供Agent在任务执行时调用
    """
    
    def __init__(self, analyzer: RepoAnalyzer):
        self.analyzer = analyzer
        self._current_repo: Optional[str] = None
    
    async def analyze_repo(
        self,
        repo_url: str,
        force_refresh: bool = False
    ) -> str:
        """
        分析GitHub仓库或本地代码目录
        
        Args:
            repo_url: GitHub仓库URL或本地路径
            force_refresh: 是否强制重新分析
            
        Returns:
            分析结果摘要
        """
        result = await self.analyzer.analyze_repository(repo_url, force_refresh)
        
        if not result['success']:
            return f"分析失败: {result.get('error', '未知错误')}"
        
        self._current_repo = repo_url
        
        # 返回摘要
        summary = f"""
## 仓库分析完成: {result['repo_name']}

### 统计信息
- 模块数: {result['stats']['total_modules']}
- 类数: {result['stats']['total_classes']}
- 函数数: {result['stats']['total_functions']}
- 代码行数: {result['stats']['total_lines']}

### 解析统计
- 扫描文件: {result['parse_stats']['total_files_scanned']}
- 成功解析: {result['parse_stats']['files_parsed']}
- 语法错误: {result['parse_stats']['syntax_errors']} (已跳过)

### 关键模块
{chr(10).join(f"- {m['path']} (重要性: {m['importance_score']:.1f})" for m in result['key_modules'][:5])}

### 入口点
{chr(10).join(f"- {e['path']}: {e['reason']}" for e in result['entry_points'][:3]) if result['entry_points'] else '未找到明确入口点'}

### Tree抽象层
- 扁平化路径数: {result['tree_abstraction']['flat_paths_count']}

### 目录结构
```
{result['structure'][:1500]}
```
"""
        return summary
    
    async def quick_tree_scan(self, repo_url: str, max_depth: int = 5) -> str:
        """
        快速扫描仓库结构（仅Tree抽象层，不解析代码）
        
        Args:
            repo_url: 仓库URL
            max_depth: 最大深度
            
        Returns:
            Tree结构
        """
        result = await self.analyzer.build_tree_abstraction_only(repo_url, max_depth)
        
        if not result['success']:
            return f"扫描失败"
        
        return f"""
## 仓库快速扫描: {result['repo_name']}

- 文件数: {result['file_count']}
- 目录数: {result['dir_count']}
- 扁平化路径数: {result['flat_paths_count']}

### 目录结构
```
{result['tree_content'][:2000]}
```
"""
    
    def search_in_repo(self, keyword: str, max_results: int = 10) -> str:
        """
        在当前分析的仓库中搜索代码
        
        Args:
            keyword: 搜索关键词
            max_results: 最大结果数
            
        Returns:
            搜索结果
        """
        if not self._current_repo:
            return "请先使用 analyze_repo 分析一个仓库"
        
        results = self.analyzer.search_code(self._current_repo, keyword, max_results)
        
        if not results:
            return f"未找到包含 '{keyword}' 的代码"
        
        output = [f"## 搜索结果: '{keyword}' ({len(results)} 个匹配)\n"]
        
        for r in results:
            output.append(f"### {r['file']}:{r['line']}")
            output.append(f"```{r['type']}")
            output.append(r['content'])
            output.append("```\n")
        
        return "\n".join(output)
    
    def search_files(self, keyword: str, limit: int = 20) -> str:
        """
        按路径搜索文件（使用Tree抽象层）
        
        Args:
            keyword: 关键词
            limit: 最大结果数
            
        Returns:
            匹配的文件路径列表
        """
        if not self._current_repo:
            return "请先使用 analyze_repo 分析一个仓库"
        
        files = self.analyzer.search_files_by_path(self._current_repo, keyword, limit)
        
        if not files:
            return f"未找到包含 '{keyword}' 的文件路径"
        
        output = [f"## 匹配的文件 ({len(files)} 个)\n"]
        for f in files:
            flat_name = self.analyzer.get_flat_path(self._current_repo, f)
            output.append(f"- {f}")
            if flat_name:
                output.append(f"  (扁平化: {flat_name})")
        
        return "\n".join(output)
    
    def view_file(self, file_path: str, start_line: int = 1, end_line: int = 100) -> str:
        """
        查看仓库中的文件内容
        
        Args:
            file_path: 文件相对路径
            start_line: 起始行
            end_line: 结束行
            
        Returns:
            文件内容
        """
        if not self._current_repo:
            return "请先使用 analyze_repo 分析一个仓库"
        
        content = self.analyzer.get_file_content(self._current_repo, file_path)
        
        if content is None:
            return f"文件不存在: {file_path}"
        
        lines = content.splitlines()
        total_lines = len(lines)
        
        # 调整范围
        start_line = max(1, start_line)
        end_line = min(total_lines, end_line)
        
        selected_lines = lines[start_line-1:end_line]
        
        output = f"## {file_path} (行 {start_line}-{end_line} / 共 {total_lines} 行)\n"
        output += "```python\n"
        
        for i, line in enumerate(selected_lines, start=start_line):
            output += f"{i:4d} | {line}\n"
        
        output += "```"
        
        return output
    
    def get_function_info(self, function_name: str) -> str:
        """
        获取函数的详细信息
        
        Args:
            function_name: 函数名称
            
        Returns:
            函数详情
        """
        if not self._current_repo:
            return "请先使用 analyze_repo 分析一个仓库"
        
        func_info = self.analyzer.get_function_details(self._current_repo, function_name)
        
        if not func_info:
            return f"未找到函数: {function_name}"
        
        output = f"""
## 函数: {func_info['name']}

- **所在模块**: {func_info['module']}
- **参数**: {', '.join(func_info['args']) or '无'}
- **装饰器**: {', '.join(func_info['decorators']) or '无'}
- **异步**: {'是' if func_info['is_async'] else '否'}
- **行号**: {func_info['lineno']}

### 文档字符串
{func_info['docstring'] or '无文档'}
"""
        return output
    
    def get_class_info(self, class_name: str) -> str:
        """
        获取类的详细信息
        
        Args:
            class_name: 类名称
            
        Returns:
            类详情
        """
        if not self._current_repo:
            return "请先使用 analyze_repo 分析一个仓库"
        
        class_info = self.analyzer.get_class_details(self._current_repo, class_name)
        
        if not class_info:
            return f"未找到类: {class_name}"
        
        output = f"""
## 类: {class_info['name']}

- **所在模块**: {class_info['module']}
- **继承自**: {', '.join(class_info['bases']) or 'object'}
- **装饰器**: {', '.join(class_info['decorators']) or '无'}
- **方法**: {', '.join(class_info['methods'][:10])}{'...' if len(class_info['methods']) > 10 else ''}
- **行号**: {class_info['lineno']}

### 文档字符串
{class_info['docstring'] or '无文档'}
"""
        return output
    
    def list_structure(self, max_depth: int = 3) -> str:
        """
        列出仓库目录结构
        
        Args:
            max_depth: 显示深度
            
        Returns:
            目录结构
        """
        if not self._current_repo:
            return "请先使用 analyze_repo 分析一个仓库"
        
        structure = self.analyzer.list_repository_structure(self._current_repo, max_depth)
        
        return f"```\n{structure}\n```"
    
    def get_flat_path_info(self, path: str) -> str:
        """
        获取路径的扁平化信息
        
        Args:
            path: 原始路径或扁平化名称
            
        Returns:
            路径信息
        """
        if not self._current_repo:
            return "请先使用 analyze_repo 分析一个仓库"
        
        # 尝试作为原始路径
        flat_name = self.analyzer.get_flat_path(self._current_repo, path)
        if flat_name:
            return f"原始路径: {path}\n扁平化名称: {flat_name}"
        
        # 尝试作为扁平化名称
        original_path = self.analyzer.get_original_path(self._current_repo, path)
        if original_path:
            return f"扁平化名称: {path}\n原始路径: {original_path}"
        
        return f"未找到路径: {path}"


# 全局单例
_repo_analyzer: Optional[RepoAnalyzer] = None

def get_repo_analyzer(work_dir: str = "./workspace/repos") -> RepoAnalyzer:
    """获取RepoAnalyzer单例"""
    global _repo_analyzer
    if _repo_analyzer is None:
        _repo_analyzer = RepoAnalyzer(work_dir)
    return _repo_analyzer


if __name__ == "__main__":
    import sys
    
    async def main():
        analyzer = RepoAnalyzer()
        
        # 测试分析
        repo_url = sys.argv[1] if len(sys.argv) > 1 else "."
        
        result = await analyzer.analyze_repository(repo_url)
        
        if result['success']:
            print(result['llm_summary'])
            print("\n--- Tree抽象层 ---")
            print(f"扁平化路径数: {result['tree_abstraction']['flat_paths_count']}")
        else:
            print(f"分析失败: {result['error']}")
    
    asyncio.run(main())
