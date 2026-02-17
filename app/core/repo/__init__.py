"""
CheapBuy Repository Analysis Module
提供代码仓库理解和分析能力
"""

import logging

logger = logging.getLogger(__name__)

# ==================== 导入 tree_builder ====================
CodeTreeBuilder = None
TreeAbstraction = None
should_ignore_path = None

try:
    from .tree_builder import CodeTreeBuilder, TreeAbstraction, should_ignore_path
    logger.debug("Successfully imported from tree_builder")
except ImportError as e:
    logger.error(f"Failed to import from tree_builder: {e}")
    # 尝试直接查看模块内容
    try:
        from . import tree_builder
        logger.error(f"tree_builder module contents: {dir(tree_builder)}")
    except Exception as e2:
        logger.error(f"Cannot even import tree_builder module: {e2}")

# ==================== 导入 importance_analyzer ====================
ImportanceAnalyzer = None
FileImportanceCalculator = None

try:
    from .importance_analyzer import ImportanceAnalyzer, FileImportanceCalculator
    logger.debug("Successfully imported from importance_analyzer")
except ImportError as e:
    logger.warning(f"Failed to import from importance_analyzer: {e}")

# ==================== 导入 analyzer ====================
RepoAnalyzer = None
RepoAnalyzerTools = None
get_repo_analyzer = None

try:
    from .analyzer import RepoAnalyzer, RepoAnalyzerTools, get_repo_analyzer
    logger.debug("Successfully imported from analyzer")
except ImportError as e:
    logger.warning(f"Failed to import from analyzer: {e}")

# ==================== 导出列表 ====================
__all__ = [
    'CodeTreeBuilder',
    'TreeAbstraction', 
    'should_ignore_path',
    'ImportanceAnalyzer',
    'FileImportanceCalculator',
    'RepoAnalyzer',
    'RepoAnalyzerTools',
    'get_repo_analyzer',
]

# ==================== 验证导入 ====================
def _validate_imports():
    """验证核心导入是否成功"""
    missing = []
    if CodeTreeBuilder is None:
        missing.append('CodeTreeBuilder')
    if RepoAnalyzer is None:
        missing.append('RepoAnalyzer')
    
    if missing:
        logger.warning(f"Missing core imports: {missing}")
        return False
    return True

# 启动时验证
_imports_valid = _validate_imports()