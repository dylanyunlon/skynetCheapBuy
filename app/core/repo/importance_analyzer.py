#!/usr/bin/env python
"""
CheapBuy Code Importance Analyzer - 基于RepoMaster的importance_analyzer.py适配

功能:
1. 权重综合评分模型
2. 语义分析
3. 代码复杂度分析
4. Git提交历史分析
5. 模块依赖关系分析
"""

import os
import re
import subprocess
import logging
from typing import Dict, List, Set, Tuple, Optional, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class ImportanceAnalyzer:
    """代码重要性分析器 - 评估代码仓库中各组件的重要性"""
    
    def __init__(
        self,
        repo_path: str,
        modules: Dict,
        classes: Dict,
        functions: Dict,
        imports: Dict,
        code_tree: Optional[Dict] = None,
        call_graph: Optional[Any] = None,
        weights: Optional[Dict] = None
    ):
        """
        初始化重要性分析器
        
        Args:
            repo_path: 代码仓库路径
            modules: 模块信息字典
            classes: 类信息字典
            functions: 函数信息字典
            imports: 导入信息字典
            code_tree: 代码树结构
            call_graph: 函数调用图(可选)
            weights: 重要性计算权重(可选)
        """
        self.repo_path = repo_path
        self.modules = modules
        self.classes = classes
        self.functions = functions
        self.imports = imports
        self.code_tree = code_tree or {}
        self.call_graph = call_graph
        
        # 定义重要性计算权重
        default_weights = {
            'key_component': 0.0,       # 关键组件权重
            'usage': 2.0,               # 使用频率权重
            'imports_relationships': 3.0,  # 模块间引用关系权重
            'complexity': 1.0,          # 代码复杂度权重
            'semantic': 0.5,            # 语义重要性权重
            'documentation': 0.0,       # 文档完整性权重
            'git_history': 4.0,         # Git历史权重
            'size': 0.0                 # 代码大小权重
        }
        
        self.weights = default_weights
        if weights:
            self.weights.update(weights)
        
        # 重要语义关键词
        self.important_keywords = [
            'main', 'core', 'engine', 'api', 'service',
            'controller', 'manager', 'handler', 'processor',
            'factory', 'builder', 'provider', 'repository',
            'executor', 'scheduler', 'config', 'security',
            'model', 'view', 'router', 'middleware',
            'train', 'inference', 'predict', 'data', 'utils'
        ]
        
        # 构建模块依赖图
        self.module_dependency_graph = self._build_module_dependency_graph()
        
        logger.info(f"ImportanceAnalyzer initialized with {len(modules)} modules")

    def _build_module_dependency_graph(self) -> Dict[str, Set[str]]:
        """构建模块间依赖图"""
        graph = defaultdict(set)
        reverse_graph = defaultdict(set)  # 被依赖图
        
        # 添加所有模块为节点
        for module_id in self.modules:
            graph[module_id] = set()
        
        # 添加导入关系作为边
        for module_id, imports_list in self.imports.items():
            for imp in imports_list:
                if imp.get('type') == 'import':
                    imported_module = imp.get('name', '')
                    if imported_module in self.modules:
                        graph[module_id].add(imported_module)
                        reverse_graph[imported_module].add(module_id)
                elif imp.get('type') in ['from_import', 'importfrom']:
                    imported_module = imp.get('module', '')
                    if imported_module in self.modules:
                        graph[module_id].add(imported_module)
                        reverse_graph[imported_module].add(module_id)
        
        self.reverse_dependency_graph = reverse_graph
        return graph

    def calculate_module_importance(self, module_info: Dict) -> float:
        """
        计算模块重要性分数
        
        Args:
            module_info: 模块信息
            
        Returns:
            重要性分数 (0.0 - 10.0)
        """
        importance = 0.0
        
        # 1. 使用频率分析
        usage_score = self._analyze_usage(module_info)
        importance += usage_score * self.weights['usage']
        
        # 2. 模块间引用关系分析
        imports_score = self._analyze_imports_relationships(module_info)
        importance += imports_score * self.weights['imports_relationships']
        
        # 3. 代码复杂度分析
        complexity_score = self._analyze_complexity(module_info)
        importance += complexity_score * self.weights['complexity']
        
        # 4. 语义重要性分析
        semantic_score = self._analyze_semantic_importance(module_info)
        importance += semantic_score * self.weights['semantic']
        
        # 5. Git历史分析
        git_score = self._analyze_git_history(module_info)
        importance += git_score * self.weights['git_history']
        
        # 归一化确保分数在合理范围内
        return min(importance, 10.0)

    def _analyze_usage(self, module_info: Dict) -> float:
        """分析模块使用频率"""
        score = 0.0
        module_id = module_info.get('id', '')
        
        # 统计被其他模块导入的次数
        if module_id in self.reverse_dependency_graph:
            import_count = len(self.reverse_dependency_graph[module_id])
            score = min(import_count / 10.0, 1.0)
        
        return score

    def _analyze_imports_relationships(self, module_info: Dict) -> float:
        """分析模块间引用关系的重要性"""
        score = 0.0
        module_id = module_info.get('id', '')
        
        if module_id in self.module_dependency_graph:
            # 计算入度 - 有多少其他模块导入这个模块
            in_degree = len(self.reverse_dependency_graph.get(module_id, set()))
            
            # 计算出度 - 这个模块导入了多少其他模块
            out_degree = len(self.module_dependency_graph.get(module_id, set()))
            
            # 入度更重要(被更多模块使用表示更重要)
            score = (in_degree * 0.7 + out_degree * 0.3) / 10.0
            score = min(score, 1.0)
        
        return score

    def _analyze_complexity(self, module_info: Dict) -> float:
        """分析代码复杂度"""
        score = 0.0
        module_id = module_info.get('id', '')
        
        if module_id in self.modules and 'content' in self.modules[module_id]:
            content = self.modules[module_id]['content']
            
            # 统计分支和循环
            lines = content.splitlines()
            if_count = sum(1 for line in lines if re.search(r'\bif\b', line))
            for_count = sum(1 for line in lines if re.search(r'\bfor\b', line))
            while_count = sum(1 for line in lines if re.search(r'\bwhile\b', line))
            except_count = sum(1 for line in lines if re.search(r'\bexcept\b', line))
            
            # 计算总分支数
            branch_count = if_count + for_count + while_count + except_count
            
            # 归一化复杂度分数
            score = min(branch_count / 50.0, 1.0)
            
            # 检查函数嵌套深度
            def_pattern = re.compile(r'^(\s*)def\s+', re.MULTILINE)
            matches = def_pattern.findall(content)
            if matches:
                max_indent = max(len(indent) for indent in matches)
                indent_level = max_indent / 4
                score += min(indent_level / 5.0, 1.0) * 0.3
        
        return score

    def _analyze_semantic_importance(self, module_info: Dict) -> float:
        """分析语义重要性"""
        score = 0.0
        
        # 从模块名提取语义信息
        name = module_info.get('path', '') or module_info.get('id', '')
        name_lower = name.lower()
        
        # 检查是否包含重要关键词
        for keyword in self.important_keywords:
            if keyword in name_lower:
                score += 0.3
                break
        
        # 特殊处理入口点
        if any(entry in name_lower for entry in ['main', '__main__', 'app', 'run']):
            score += 0.7
        
        # 处理常见重要文件名
        if any(f in name_lower for f in ['__init__', 'settings', 'config', 'utils', 'constants']):
            score += 0.5
        
        return min(score, 1.0)

    def _analyze_git_history(self, module_info: Dict) -> float:
        """分析Git历史"""
        score = 0.0
        
        # 获取文件路径
        file_path = module_info.get('path', '')
        if not file_path:
            return 0.0
        
        full_path = os.path.join(self.repo_path, file_path)
        
        try:
            if not os.path.exists(full_path):
                return 0.0
            
            # 检查是否在Git仓库中
            git_dir = os.path.join(self.repo_path, '.git')
            if not os.path.exists(git_dir):
                return 0.0
            
            # 获取提交次数
            cmd = ['git', '-C', self.repo_path, 'log', '--oneline', '--', file_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=10)
            
            if result.returncode == 0:
                commit_lines = result.stdout.strip().split('\n')
                commit_count = len([line for line in commit_lines if line])
                
                # 根据提交次数计算分数
                score = min(commit_count / 20.0, 1.0)
                
                # 获取最后修改时间
                cmd_last = ['git', '-C', self.repo_path, 'log', '-1', '--format=%at', '--', file_path]
                result_last = subprocess.run(cmd_last, capture_output=True, text=True, check=False, timeout=10)
                
                if result_last.returncode == 0 and result_last.stdout.strip():
                    import time
                    try:
                        last_commit_time = int(result_last.stdout.strip())
                        current_time = int(time.time())
                        days_since = (current_time - last_commit_time) / (60 * 60 * 24)
                        
                        # 最近修改的文件可能更重要
                        recency_score = max(0, 1.0 - (days_since / 365))
                        score = (score * 0.7) + (recency_score * 0.3)
                    except:
                        pass
                
                return score
            
            return 0.0
            
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, Exception) as e:
            logger.debug(f"Git history analysis failed for {file_path}: {e}")
            return 0.0

    def get_key_modules(self, top_n: int = 20) -> List[Dict]:
        """
        获取最重要的模块列表
        
        Args:
            top_n: 返回前N个最重要的模块
            
        Returns:
            按重要性排序的模块列表
        """
        key_modules = []
        
        for module_id, module_info in self.modules.items():
            # 跳过有语法错误的模块
            if module_info.get('has_syntax_error', False):
                continue
            
            # 构建节点信息
            node = {
                'id': module_id,
                'type': 'module',
                'path': module_info.get('path', ''),
                'name': os.path.basename(module_info.get('path', '')),
                **module_info
            }
            
            # 计算重要性
            importance_score = self.calculate_module_importance(node)
            
            # 根目录文件额外加分
            if '/' not in module_info.get('path', '') and '\\' not in module_info.get('path', ''):
                importance_score *= 1.5
            
            # 特殊文件加分
            path_lower = module_info.get('path', '').lower()
            if any(f in path_lower for f in ['main.py', 'app.py', 'setup.py', '__init__.py']):
                importance_score += 2.0
            
            key_modules.append({
                'id': module_id,
                'name': node['name'],
                'path': node['path'],
                'importance_score': importance_score
            })
        
        # 按重要性排序
        key_modules.sort(key=lambda x: x['importance_score'], reverse=True)
        
        return key_modules[:top_n]

    def get_entry_points(self) -> List[Dict]:
        """
        识别仓库入口点
        
        Returns:
            入口点列表
        """
        entry_points = []
        
        # 常见入口点模式
        entry_patterns = [
            ('main.py', '主入口文件'),
            ('app.py', '应用入口'),
            ('run.py', '运行脚本'),
            ('__main__.py', '模块入口'),
            ('cli.py', '命令行入口'),
            ('server.py', '服务入口'),
            ('manage.py', 'Django管理入口'),
            ('setup.py', '安装入口'),
            ('train.py', '训练入口'),
            ('inference.py', '推理入口'),
            ('predict.py', '预测入口'),
        ]
        
        for module_id, module_info in self.modules.items():
            path = module_info.get('path', '').lower()
            
            for pattern, reason in entry_patterns:
                if path.endswith(pattern) or path == pattern:
                    entry_points.append({
                        'id': module_id,
                        'path': module_info.get('path', ''),
                        'reason': reason,
                        'type': 'file_pattern'
                    })
                    break
            
            # 检查是否包含 if __name__ == "__main__"
            content = module_info.get('content', '')
            if 'if __name__' in content and '__main__' in content:
                # 避免重复
                if not any(ep['id'] == module_id for ep in entry_points):
                    entry_points.append({
                        'id': module_id,
                        'path': module_info.get('path', ''),
                        'reason': '包含 __main__ 入口',
                        'type': 'main_block'
                    })
        
        return entry_points


class FileImportanceCalculator:
    """文件重要性快速计算器 - 用于快速评估单个文件的重要性"""
    
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.important_keywords = [
            'main', 'core', 'engine', 'api', 'service', 'model',
            'train', 'inference', 'config', 'utils', 'handler'
        ]
    
    def calculate(self, file_path: str) -> float:
        """计算单个文件的重要性分数"""
        score = 0.0
        
        # 基于文件名
        name_lower = file_path.lower()
        for keyword in self.important_keywords:
            if keyword in name_lower:
                score += 2.0
                break
        
        # 根目录文件
        if '/' not in file_path and '\\' not in file_path:
            score += 3.0
        
        # 特殊文件
        if any(f in name_lower for f in ['readme', 'main.py', 'app.py', 'setup.py']):
            score += 5.0
        
        return min(score, 10.0)


if __name__ == "__main__":
    # 测试
    analyzer = ImportanceAnalyzer(
        repo_path=".",
        modules={},
        classes={},
        functions={},
        imports={}
    )
    print("ImportanceAnalyzer initialized successfully")
