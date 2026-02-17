# app/core/benchmark/code_extractor.py
# 代码块提取和判断器 - 基于RepoMaster的codeblock_judge逻辑增强

import re
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CodeIntent(str, Enum):
    """代码块意图类型"""
    ENV_SETUP = "env_setup"        # 环境准备：apt-get, pip install等
    DIRECT_EXEC = "direct_exec"    # 直接执行的代码
    SCRIPT_RUN = "script_run"      # 运行脚本命令：python xxx.py
    FILE_WRITE = "file_write"      # 写入文件操作
    DATA_PROCESS = "data_process"  # 数据处理
    MODEL_TRAIN = "model_train"    # 模型训练
    MODEL_INFER = "model_infer"    # 模型推理
    OTHER = "other"


@dataclass
class ExtractedCodeBlock:
    """提取的代码块"""
    index: int
    language: str
    code: str
    intent: CodeIntent = CodeIntent.OTHER
    target_file: Optional[str] = None
    keep: bool = True
    dependencies: List[str] = field(default_factory=list)
    estimated_tokens: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class BenchmarkCodeExtractor:
    """
    Benchmark代码提取器
    
    功能：
    1. 从LLM回复中提取代码块
    2. 判断代码块意图和可执行性
    3. 去重和排序（环境准备优先）
    4. 提取文件名标记
    """
    
    # 语言别名映射
    LANGUAGE_ALIASES = {
        'py': 'python',
        'python3': 'python',
        'sh': 'bash',
        'shell': 'bash',
        'zsh': 'bash',
        'js': 'javascript',
        'ts': 'typescript',
    }
    
    # 可执行语言
    EXECUTABLE_LANGUAGES = {'python', 'bash', 'sh', 'javascript', 'typescript'}
    
    def __init__(self, ai_engine=None):
        """
        初始化代码提取器
        
        Args:
            ai_engine: AI引擎，用于LLM辅助判断（可选）
        """
        self.ai_engine = ai_engine
    
    def extract_code_blocks(self, text: str) -> List[ExtractedCodeBlock]:
        """
        从文本中提取所有代码块
        
        Args:
            text: LLM回复文本
            
        Returns:
            提取的代码块列表
        """
        if not text:
            return []
        
        # 使用正则匹配代码块
        # 支持 ```language\ncode\n``` 格式
        pattern = r'```(\w*)\n(.*?)```'
        matches = re.findall(pattern, text, re.DOTALL)
        
        code_blocks = []
        for idx, (lang, code) in enumerate(matches):
            lang = lang.strip().lower() if lang else 'text'
            lang = self.LANGUAGE_ALIASES.get(lang, lang)
            code = code.strip()
            
            if not code:
                continue
            
            block = ExtractedCodeBlock(
                index=idx,
                language=lang,
                code=code,
                estimated_tokens=self._estimate_tokens(code)
            )
            
            # 提取文件名
            block.target_file = self._extract_filename(code)
            
            # 判断意图
            block.intent = self._detect_intent(lang, code)
            
            # 提取依赖
            block.dependencies = self._extract_dependencies(code)
            
            code_blocks.append(block)
        
        return code_blocks
    
    def _extract_filename(self, code: str) -> Optional[str]:
        """
        从代码中提取文件名
        
        支持格式：
        - # filename: xxx.py
        - # file: xxx.py  
        - //filename: xxx.js
        """
        patterns = [
            r'#\s*filename:\s*([\w\-./]+)',
            r'#\s*file:\s*([\w\-./]+)',
            r'//\s*filename:\s*([\w\-./]+)',
            r'<!--\s*filename:\s*([\w\-./]+)\s*-->',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, code, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return None
    
    def _detect_intent(self, language: str, code: str) -> CodeIntent:
        """检测代码块意图"""
        code_lower = code.lower()
        
        # 环境准备
        if language in ('bash', 'sh'):
            if any(cmd in code_lower for cmd in ['pip install', 'apt-get', 'apt install', 'conda install', 'npm install', 'yarn add']):
                return CodeIntent.ENV_SETUP
            if re.search(r'python\d?\s+[\w\-./]+\.py', code):
                return CodeIntent.SCRIPT_RUN
        
        # Python代码分析
        if language == 'python':
            # 检查是否有文件名标记 -> 直接执行
            if self._extract_filename(code):
                return CodeIntent.DIRECT_EXEC
            
            # 检查是否包含训练相关代码
            if any(kw in code_lower for kw in ['model.train()', 'loss.backward()', 'optimizer.step()', '.fit(']):
                return CodeIntent.MODEL_TRAIN
            
            # 检查是否包含推理相关代码
            if any(kw in code_lower for kw in ['model.eval()', 'torch.no_grad()', '.predict(', 'model.inference']):
                return CodeIntent.MODEL_INFER
            
            # 检查是否包含数据处理
            if any(kw in code_lower for kw in ['pd.read_', 'pd.DataFrame', 'np.load', 'torch.utils.data']):
                return CodeIntent.DATA_PROCESS
            
            return CodeIntent.DIRECT_EXEC
        
        return CodeIntent.OTHER
    
    def _extract_dependencies(self, code: str) -> List[str]:
        """提取代码中的依赖包"""
        dependencies = []
        
        # Python imports
        import_patterns = [
            r'^import\s+([\w.]+)',
            r'^from\s+([\w.]+)\s+import',
        ]
        
        for pattern in import_patterns:
            matches = re.findall(pattern, code, re.MULTILINE)
            for match in matches:
                # 取顶级包名
                top_pkg = match.split('.')[0]
                if top_pkg not in ['os', 'sys', 'json', 're', 'time', 'datetime', 'typing', 'collections', 'itertools', 'functools']:
                    if top_pkg not in dependencies:
                        dependencies.append(top_pkg)
        
        return dependencies
    
    def _estimate_tokens(self, text: str) -> int:
        """估算token数量（简单估算：字符数/4）"""
        return len(text) // 4
    
    def process_and_filter(
        self, 
        code_blocks: List[ExtractedCodeBlock],
        use_llm: bool = False
    ) -> List[ExtractedCodeBlock]:
        """
        处理和过滤代码块
        
        1. 去重
        2. 排序（环境准备优先）
        3. 移除冗余的运行命令
        
        Args:
            code_blocks: 代码块列表
            use_llm: 是否使用LLM辅助判断
            
        Returns:
            处理后的代码块列表
        """
        if not code_blocks:
            return []
        
        if use_llm and self.ai_engine:
            return self._llm_process_blocks(code_blocks)
        
        return self._rule_based_process(code_blocks)
    
    def _rule_based_process(self, code_blocks: List[ExtractedCodeBlock]) -> List[ExtractedCodeBlock]:
        """基于规则的代码块处理"""
        seen_filenames = set()
        seen_code_hashes = set()
        result = []
        
        # 第一遍：标记要保留的块
        for block in code_blocks:
            code_hash = hash(block.code.strip())
            
            # 去重：相同代码
            if code_hash in seen_code_hashes:
                block.keep = False
                continue
            seen_code_hashes.add(code_hash)
            
            # 如果有文件名，检查是否重复
            if block.target_file:
                if block.target_file in seen_filenames:
                    # 如果已有同名文件的直接执行代码，跳过运行命令
                    if block.intent == CodeIntent.SCRIPT_RUN:
                        block.keep = False
                        continue
                seen_filenames.add(block.target_file)
            
            # 如果是运行脚本命令，检查对应的直接执行代码是否存在
            if block.intent == CodeIntent.SCRIPT_RUN:
                script_match = re.search(r'python\d?\s+([\w\-./]+\.py)', block.code)
                if script_match:
                    script_name = script_match.group(1)
                    if script_name in seen_filenames:
                        block.keep = False
                        continue
            
            result.append(block)
        
        # 排序：环境准备 -> 数据处理 -> 直接执行 -> 其他
        priority = {
            CodeIntent.ENV_SETUP: 0,
            CodeIntent.DATA_PROCESS: 1,
            CodeIntent.DIRECT_EXEC: 2,
            CodeIntent.MODEL_TRAIN: 3,
            CodeIntent.MODEL_INFER: 4,
            CodeIntent.SCRIPT_RUN: 5,
            CodeIntent.OTHER: 6,
        }
        
        result.sort(key=lambda x: (priority.get(x.intent, 10), x.index))
        
        return [b for b in result if b.keep]
    
    async def _llm_process_blocks(self, code_blocks: List[ExtractedCodeBlock]) -> List[ExtractedCodeBlock]:
        """使用LLM辅助判断代码块"""
        if not self.ai_engine:
            return self._rule_based_process(code_blocks)
        
        # 构建LLM提示
        raw_blocks = [
            {
                "index": b.index,
                "language": b.language,
                "code": b.code[:500] + "..." if len(b.code) > 500 else b.code
            }
            for b in code_blocks
        ]
        
        system_prompt = """你是一个代码块执行规划器。
分析代码块列表，判断每个代码块：
1. 是否应该执行 (keep)
2. 意图类型 (intent): env_setup/direct_exec/script_run/other
3. 目标文件名 (target_file)

去重规则：
- 如果有直接可执行的Python代码（包含filename注释），则移除运行该脚本的shell命令
- 移除重复的代码块

排序规则：
- 环境准备(env_setup)优先执行
- 数据处理次之
- 然后是直接执行代码

返回JSON格式：
{
  "blocks": [{"index": 0, "keep": true, "intent": "env_setup", "target_file": null}, ...],
  "order": [0, 1, ...]
}"""

        user_prompt = f"代码块列表:\n{json.dumps(raw_blocks, ensure_ascii=False, indent=2)}\n\n请分析并返回JSON:"
        
        try:
            response = await self.ai_engine.get_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model="claude-opus-4-5-20251101",
                temperature=0.1,
                max_tokens=2000
            )
            
            result_text = response.get("content", "{}")
            
            # 尝试解析JSON
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                return self._rule_based_process(code_blocks)
            
            # 应用LLM判断结果
            blocks_info = {item["index"]: item for item in result.get("blocks", [])}
            order = result.get("order", list(range(len(code_blocks))))
            
            # 更新代码块属性
            for block in code_blocks:
                if block.index in blocks_info:
                    info = blocks_info[block.index]
                    block.keep = info.get("keep", True)
                    if info.get("intent"):
                        try:
                            block.intent = CodeIntent(info["intent"])
                        except ValueError:
                            pass
                    if info.get("target_file"):
                        block.target_file = info["target_file"]
            
            # 按顺序返回
            ordered_blocks = []
            seen = set()
            for idx in order:
                if 0 <= idx < len(code_blocks) and idx not in seen:
                    block = code_blocks[idx]
                    if block.keep:
                        ordered_blocks.append(block)
                    seen.add(idx)
            
            return ordered_blocks
            
        except Exception as e:
            logger.error(f"LLM处理代码块失败: {e}")
            return self._rule_based_process(code_blocks)
    
    def format_for_execution(self, blocks: List[ExtractedCodeBlock]) -> List[Dict[str, Any]]:
        """
        将代码块格式化为执行格式
        
        Returns:
            [{"language": "python", "code": "...", "filename": "xxx.py", "intent": "direct_exec"}, ...]
        """
        return [
            {
                "language": block.language,
                "code": block.code,
                "filename": block.target_file,
                "intent": block.intent.value,
                "dependencies": block.dependencies,
                "tokens": block.estimated_tokens
            }
            for block in blocks
        ]


class TreeStructureExtractor:
    """
    目录树结构提取器
    
    功能：
    1. 使用tree命令生成简化目录结构
    2. 扁平化路径命名
    3. 作为AST/图探索之上的抽象层
    """
    
    # 默认忽略的目录
    DEFAULT_IGNORE_DIRS = [
        '__pycache__', '.git', '.vscode', 'venv', 'env', 'node_modules',
        '.pytest_cache', 'build', 'dist', '.github', 'logs', 'log',
        'dataset', 'datasets', 'data', '.idea', '.eggs', '*.egg-info',
        'htmlcov', '.tox', '.nox', 'wandb', 'mlruns', 'outputs',
        'checkpoints', 'models', 'weights'
    ]
    
    # 默认忽略的文件模式
    DEFAULT_IGNORE_PATTERNS = [
        '*.pyc', '*.pyo', '*.so', '*.dll', '*.class',
        '*.log', '*.tmp', '*.cache', '*.lock',
        '*.png', '*.jpg', '*.jpeg', '*.gif', '*.ico',
        '*.mp4', '*.avi', '*.mov', '*.mp3', '*.wav',
        '*.zip', '*.tar', '*.gz', '*.rar',
        '*.pdf', '*.doc', '*.docx', '*.xls', '*.xlsx',
        '.DS_Store', 'Thumbs.db'
    ]
    
    def __init__(
        self, 
        ignore_dirs: Optional[List[str]] = None,
        ignore_patterns: Optional[List[str]] = None,
        max_depth: int = 4
    ):
        self.ignore_dirs = ignore_dirs or self.DEFAULT_IGNORE_DIRS
        self.ignore_patterns = ignore_patterns or self.DEFAULT_IGNORE_PATTERNS
        self.max_depth = max_depth
    
    def get_tree_structure(self, repo_path: str) -> str:
        """
        获取目录树结构
        
        Args:
            repo_path: 仓库路径
            
        Returns:
            tree命令输出的目录结构字符串
        """
        import subprocess
        import os
        
        if not os.path.isdir(repo_path):
            return f"Error: {repo_path} is not a valid directory"
        
        # 构建tree命令的忽略参数
        ignore_pattern = '|'.join(self.ignore_dirs)
        
        try:
            # 使用tree命令，忽略指定目录
            cmd = [
                'tree', 
                '-I', ignore_pattern,
                '-L', str(self.max_depth),
                '--noreport',  # 不显示统计信息
                repo_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return result.stdout
            else:
                # tree命令不可用时的fallback
                return self._python_tree(repo_path)
                
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # tree命令不可用，使用Python实现
            return self._python_tree(repo_path)
    
    def _python_tree(self, repo_path: str, prefix: str = "", level: int = 0) -> str:
        """Python实现的tree功能"""
        import os
        
        if level >= self.max_depth:
            return ""
        
        output = []
        
        try:
            entries = sorted(os.listdir(repo_path))
        except PermissionError:
            return ""
        
        # 过滤忽略的项
        filtered = []
        for entry in entries:
            if entry in self.ignore_dirs:
                continue
            if entry.startswith('.'):
                continue
            if any(self._match_pattern(entry, p) for p in self.ignore_patterns):
                continue
            filtered.append(entry)
        
        for i, entry in enumerate(filtered):
            is_last = i == len(filtered) - 1
            connector = "└── " if is_last else "├── "
            output.append(f"{prefix}{connector}{entry}")
            
            full_path = os.path.join(repo_path, entry)
            if os.path.isdir(full_path):
                extension = "    " if is_last else "│   "
                output.append(self._python_tree(full_path, prefix + extension, level + 1))
        
        return "\n".join(filter(None, output))
    
    def _match_pattern(self, filename: str, pattern: str) -> bool:
        """简单的模式匹配"""
        import fnmatch
        return fnmatch.fnmatch(filename, pattern)
    
    def flatten_paths(self, repo_path: str) -> Dict[str, str]:
        """
        将目录结构扁平化为路径映射
        
        例如: src/services/autogen_upgrade/codeblock_judge.py 
            -> src_services_autogen_upgrade_codeblock_judge.py
        
        Returns:
            {扁平化名称: 原始路径}
        """
        import os
        
        path_map = {}
        
        for root, dirs, files in os.walk(repo_path):
            # 过滤忽略的目录
            dirs[:] = [d for d in dirs if d not in self.ignore_dirs and not d.startswith('.')]
            
            for file in files:
                # 过滤忽略的文件
                if any(self._match_pattern(file, p) for p in self.ignore_patterns):
                    continue
                if file.startswith('.'):
                    continue
                
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, repo_path)
                
                # 扁平化命名
                flat_name = rel_path.replace(os.sep, '_').replace('/', '_')
                path_map[flat_name] = rel_path
        
        return path_map
    
    def generate_summary(self, repo_path: str) -> Dict[str, Any]:
        """
        生成仓库结构摘要
        
        Returns:
            {
                "tree": "目录树字符串",
                "flat_paths": {扁平化名称: 原始路径},
                "stats": {"total_files": N, "python_files": M, ...}
            }
        """
        import os
        
        tree = self.get_tree_structure(repo_path)
        flat_paths = self.flatten_paths(repo_path)
        
        # 统计信息
        stats = {
            "total_files": len(flat_paths),
            "python_files": sum(1 for p in flat_paths.values() if p.endswith('.py')),
            "javascript_files": sum(1 for p in flat_paths.values() if p.endswith(('.js', '.jsx', '.ts', '.tsx'))),
            "config_files": sum(1 for p in flat_paths.values() if p.endswith(('.json', '.yaml', '.yml', '.toml', '.ini'))),
            "markdown_files": sum(1 for p in flat_paths.values() if p.endswith('.md')),
        }
        
        return {
            "tree": tree,
            "flat_paths": flat_paths,
            "stats": stats,
            "repo_name": os.path.basename(repo_path)
        }
