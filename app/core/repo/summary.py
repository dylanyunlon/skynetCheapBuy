#!/usr/bin/env python
"""
CheapBuy Repository Summary Generator - 基于RepoMaster的repo_summary.py适配
用于生成代码仓库的LLM可理解摘要
"""

import json
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


def get_token_count(text: str) -> int:
    """估算文本token数量"""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # 简单估算
        return len(text) // 4


def generate_repository_summary(
    code_list: List[Dict[str, str]],
    max_important_files_token: int = 2000,
    llm_client: Optional[Any] = None
) -> Dict[str, str]:
    """
    生成代码仓库摘要
    
    Args:
        code_list: 包含代码文件信息的列表
            [{'file_path': '文件路径', 'file_content': '文件内容'}]
        max_important_files_token: 重要文件的token限制
        llm_client: LLM客户端(可选)
        
    Returns:
        仓库摘要字典 {file_path: summary}
    """
    
    def judge_file_is_important(files: List[Dict]) -> List[Dict]:
        """判断文件是否重要"""
        if llm_client is None:
            # 没有LLM时使用规则判断
            return _rule_based_importance(files)
        
        # 使用LLM判断
        judge_prompt = """
You are an assistant that helps developers understand code repositories.
Please judge whether the current file is important for understanding the entire repository.
Output yes for important files, no for unimportant files.

Rules:
1. README.md with repository description is very important
2. Configuration, test, and example files are important
3. Files containing core logic are important
4. Keep only one file if multiple have duplicate content

Return JSON list:
[{"file_path": "path", "is_important": "yes" or "no"}]
"""
        try:
            messages = [
                {"role": "system", "content": judge_prompt},
                {"role": "user", "content": json.dumps(files, ensure_ascii=False, indent=2)}
            ]
            response = llm_client.chat(messages, json_format=True)
            
            if not isinstance(response, list):
                return files
            
            important_files = []
            for result in response:
                if result.get('is_important', '').lower() == 'yes':
                    for f in files:
                        if result['file_path'] == f['file_path']:
                            important_files.append(f)
            
            return important_files
            
        except Exception as e:
            logger.warning(f"LLM importance judgment failed: {e}")
            return _rule_based_importance(files)
    
    def _rule_based_importance(files: List[Dict]) -> List[Dict]:
        """基于规则的重要性判断"""
        important_patterns = [
            'readme', 'main', 'app', 'config', 'setup',
            'test', 'example', '__init__', 'core', 'api',
            'model', 'train', 'inference', 'utils'
        ]
        
        important_files = []
        for f in files:
            path_lower = f['file_path'].lower()
            if any(p in path_lower for p in important_patterns):
                important_files.append(f)
        
        return important_files
    
    def split_code_lists(files: List[Dict], max_token: int = 50000) -> List[List[Dict]]:
        """按token分割文件列表"""
        result = []
        current_batch = []
        current_tokens = 0
        
        for f in files:
            file_tokens = get_token_count(str(f))
            if file_tokens > max_token:
                continue
            
            if current_tokens + file_tokens > max_token:
                if current_batch:
                    result.append(current_batch)
                current_batch = [f]
                current_tokens = file_tokens
            else:
                current_batch.append(f)
                current_tokens += file_tokens
        
        if current_batch:
            result.append(current_batch)
        
        return result
    
    # 如果总内容很小，直接返回
    all_content = json.dumps(code_list, ensure_ascii=False)
    if get_token_count(all_content) < max_important_files_token:
        return {f['file_path']: f['file_content'] for f in code_list}
    
    # 分批判断重要文件
    important_files = []
    for batch in split_code_lists(code_list):
        important_files.extend(judge_file_is_important(batch))
    
    logger.info(f"Identified {len(important_files)} important files from {len(code_list)}")
    
    # 生成摘要
    repository_summary = {}
    current_tokens = 0
    
    for f in important_files:
        file_path = f['file_path']
        file_content = f['file_content']
        
        # 检查是否超过token限制
        summary = _get_file_summary(file_content, llm_client)
        summary_tokens = get_token_count(summary)
        
        if current_tokens + summary_tokens > max_important_files_token:
            break
        
        if '<none>' not in summary.lower():
            repository_summary[file_path] = summary
            current_tokens += summary_tokens
    
    return repository_summary


def _get_file_summary(content: str, llm_client: Optional[Any] = None) -> str:
    """
    获取单个文件的摘要
    
    Args:
        content: 文件内容
        llm_client: LLM客户端
        
    Returns:
        文件摘要
    """
    if llm_client is None:
        # 简单截断
        if len(content) > 2000:
            return content[:1000] + "\n...\n" + content[-500:]
        return content
    
    try:
        prompt = """
Summarize this code file concisely:
1. Focus on main functions and architecture
2. Keep important code blocks and commands
3. Include installation methods and usage examples
4. Ignore disclaimers and unimportant content
"""
        
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content[:10000]}  # 限制输入长度
        ]
        
        summary = llm_client.chat(messages)
        return summary
        
    except Exception as e:
        logger.warning(f"File summary generation failed: {e}")
        if len(content) > 2000:
            return content[:1000] + "\n...\n" + content[-500:]
        return content


def get_readme_summary(
    code_content: str,
    history_summary: Dict[str, str],
    llm_client: Optional[Any] = None
) -> str:
    """
    获取README和其他重要文档的摘要
    
    Args:
        code_content: 文档内容
        history_summary: 历史摘要
        llm_client: LLM客户端
        
    Returns:
        文档摘要
    """
    if llm_client is None:
        # 简单处理
        if len(code_content) > 3000:
            return code_content[:1500] + "\n...\n" + code_content[-500:]
        return code_content
    
    try:
        system_prompt = """
You help developers understand code repositories.
Generate a summary based on README and documentation.

Rules:
1. Focus on main functions, architecture, and usage
2. Use <cite>content</cite> for important references
3. Keep summary concise but comprehensive
4. Include installation and examples if available
5. Skip disclaimers and unimportant content
6. Don't repeat content from history_summary
"""
        
        prompt = f"""
Code repository documentation:
<code_content>
{code_content[:8000]}
</code_content>

Other document summaries:
<history_summary>
{json.dumps(history_summary, ensure_ascii=False)}
</history_summary>
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        return llm_client.chat(messages)
        
    except Exception as e:
        logger.warning(f"README summary generation failed: {e}")
        if len(code_content) > 3000:
            return code_content[:1500] + "\n...\n" + code_content[-500:]
        return code_content


class RepoSummaryGenerator:
    """仓库摘要生成器类"""
    
    def __init__(self, llm_client: Optional[Any] = None):
        """
        初始化摘要生成器
        
        Args:
            llm_client: LLM客户端
        """
        self.llm_client = llm_client
    
    def generate(
        self,
        modules: Dict,
        other_files: Dict,
        max_tokens: int = 4000
    ) -> str:
        """
        生成仓库摘要
        
        Args:
            modules: 模块信息字典
            other_files: 其他文件信息字典
            max_tokens: 最大token数
            
        Returns:
            仓库摘要
        """
        # 收集所有文件
        code_list = []
        
        # 优先处理README
        readme_files = []
        other_important = []
        
        for file_id, file_info in {**modules, **other_files}.items():
            file_path = file_info.get('path', '')
            content = file_info.get('content', '')
            
            if not content:
                continue
            
            if 'readme' in file_path.lower():
                readme_files.append({
                    'file_path': file_path,
                    'file_content': content
                })
            elif any(k in file_path.lower() for k in ['main', 'app', 'config', 'example', 'test']):
                other_important.append({
                    'file_path': file_path,
                    'file_content': content
                })
        
        code_list = readme_files + other_important[:20]
        
        # 生成摘要
        summary_dict = generate_repository_summary(
            code_list,
            max_important_files_token=max_tokens,
            llm_client=self.llm_client
        )
        
        # 格式化输出
        output = []
        output.append("# Repository Summary\n")
        
        for file_path, summary in summary_dict.items():
            output.append(f"## {file_path}\n")
            output.append(f"{summary[:1000]}\n")
        
        return "\n".join(output)
    
    def get_key_files_content(
        self,
        modules: Dict,
        other_files: Dict,
        max_files: int = 10,
        max_content_per_file: int = 2000
    ) -> List[Dict]:
        """
        获取关键文件内容
        
        Args:
            modules: 模块字典
            other_files: 其他文件字典
            max_files: 最大文件数
            max_content_per_file: 每个文件最大内容长度
            
        Returns:
            关键文件列表
        """
        key_patterns = [
            'readme', 'main.py', 'app.py', 'config', 'setup.py',
            '__init__.py', 'train', 'inference', 'model'
        ]
        
        key_files = []
        all_files = {**modules, **other_files}
        
        for file_id, file_info in all_files.items():
            file_path = file_info.get('path', '').lower()
            
            if any(p in file_path for p in key_patterns):
                content = file_info.get('content', '')
                if len(content) > max_content_per_file:
                    content = content[:max_content_per_file] + "\n... (truncated)"
                
                key_files.append({
                    'file_path': file_info.get('path', ''),
                    'file_content': content
                })
                
                if len(key_files) >= max_files:
                    break
        
        return key_files
