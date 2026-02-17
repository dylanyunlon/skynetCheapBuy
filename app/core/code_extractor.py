import re
import ast
from typing import List, Dict, Optional, Tuple
from enum import Enum
from datetime import datetime

class CodeType(Enum):
    PYTHON = "python"
    BASH = "bash"
    SHELL = "shell"
    SQL = "sql"
    JAVASCRIPT = "javascript"
    JSON = "json"
    YAML = "yaml"
    DOCKERFILE = "dockerfile"
    MAKEFILE = "makefile"

class CodeBlock:
    def __init__(self, code: str, language: str, description: Optional[str] = None):
        self.code = code.strip()
        self.language = self._normalize_language(language)
        self.description = description
        self.is_executable = self.language in [
            CodeType.PYTHON.value, 
            CodeType.BASH.value, 
            CodeType.SHELL.value,
            CodeType.JAVASCRIPT.value
        ]
        self.line_count = len(self.code.splitlines())
        self.size = len(self.code)
    
    def _normalize_language(self, language: str) -> str:
        """标准化语言名称"""
        if not language:
            return "plain"
        
        language = language.lower().strip()
        
        # 语言别名映射
        aliases = {
            "py": "python",
            "python3": "python",
            "sh": "bash",
            "shell": "bash",
            "js": "javascript",
            "node": "javascript",
            "yml": "yaml",
            "dockerfile": "dockerfile",
            "makefile": "makefile"
        }
        
        return aliases.get(language, language)

class CodeExtractor:
    """从AI响应中提取代码块"""
    
    # 改进的正则表达式，支持多种代码块格式
    CODE_BLOCK_PATTERNS = [
        # Markdown代码块（带语言标识）
        (r'```(\w+)?\n(.*?)```', True),
        # 缩进的代码块（4个空格或1个tab）
        (r'(?:^|\n)((?:    |\t).*(?:\n(?:    |\t).*)*)', False),
        # 行内代码（单反引号）
        (r'`([^`]+)`', False)
    ]
    
    # 语言检测模式
    LANGUAGE_PATTERNS = {
        "python": [
            r'^\s*(?:import|from)\s+\w+',
            r'^\s*def\s+\w+\s*\(',
            r'^\s*class\s+\w+',
            r'^\s*if\s+__name__\s*==\s*["\']__main__["\']',
            r'^\s*print\s*\(',
            r'^\s*#.*python',
        ],
        "bash": [
            r'^#!/bin/(?:ba)?sh',
            r'^\s*(?:echo|export|source|alias)\s+',
            r'^\s*(?:if|then|else|fi|for|while|do|done)\s*(?:\[|$)',
            r'^\s*\[\[.*\]\]',
            r'^\s*function\s+\w+\s*\(\)',
            r'^\s*#.*bash',
        ],
        "javascript": [
            r'^\s*(?:const|let|var)\s+\w+\s*=',
            r'^\s*(?:function|async\s+function)\s+\w+\s*\(',
            r'^\s*(?:class|export|import)\s+',
            r'^\s*console\.\w+\s*\(',
            r'=>',
            r'^\s*//.*javascript',
        ],
        "sql": [
            r'^\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\s+',
            r'^\s*(?:FROM|WHERE|JOIN|GROUP BY|ORDER BY)\s+',
            r'^\s*--.*sql',
        ]
    }
    
    @classmethod
    def extract_code_blocks(cls, text: str) -> List[CodeBlock]:
        """提取所有代码块"""
        code_blocks = []
        used_positions = set()
        
        # 首先尝试提取Markdown代码块
        markdown_pattern = re.compile(r'```(\w+)?\n(.*?)```', re.DOTALL | re.MULTILINE)
        for match in markdown_pattern.finditer(text):
            language = match.group(1) or 'plain'
            code = match.group(2).strip()
            
            if not code:  # 跳过空代码块
                continue
            
            # 记录已使用的位置，避免重复提取
            used_positions.add((match.start(), match.end()))
            
            # 获取代码块前的描述
            start_pos = match.start()
            prev_text = text[:start_pos].strip()
            lines = prev_text.split('\n')
            
            # 查找最近的非空行作为描述
            description = None
            for line in reversed(lines):
                line = line.strip()
                if line and not line.startswith('#'):
                    description = line
                    break
            
            # 如果没有显式语言标识，尝试自动检测
            if language == 'plain':
                detected_language = cls._detect_language(code)
                if detected_language:
                    language = detected_language
            
            code_blocks.append(CodeBlock(code, language, description))
        
        # 如果没有找到Markdown代码块，尝试其他格式
        if not code_blocks:
            # 尝试缩进代码块
            indent_pattern = re.compile(r'(?:^|\n)((?:    |\t).*(?:\n(?:    |\t).*)*)', re.MULTILINE)
            for match in indent_pattern.finditer(text):
                # 检查是否在已使用的位置内
                if any(start <= match.start() < end for start, end in used_positions):
                    continue
                
                code = match.group(1)
                # 移除缩进
                lines = code.split('\n')
                min_indent = min(len(line) - len(line.lstrip()) for line in lines if line.strip())
                code = '\n'.join(line[min_indent:] if len(line) > min_indent else line for line in lines)
                code = code.strip()
                
                if not code or len(code) < 20:  # 跳过太短的代码
                    continue
                
                # 自动检测语言
                language = cls._detect_language(code) or 'plain'
                
                # 获取描述
                start_pos = match.start()
                prev_text = text[:start_pos].strip()
                lines = prev_text.split('\n')
                description = lines[-1] if lines else None
                
                code_blocks.append(CodeBlock(code, language, description))
        
        return code_blocks
    
    @classmethod
    def _detect_language(cls, code: str) -> Optional[str]:
        """自动检测代码语言"""
        lines = code.split('\n')
        
        # 对每种语言计算匹配分数
        scores = {}
        
        for language, patterns in cls.LANGUAGE_PATTERNS.items():
            score = 0
            for pattern in patterns:
                for line in lines[:10]:  # 只检查前10行
                    if re.match(pattern, line, re.IGNORECASE):
                        score += 1
                        break  # 每个模式只计一次
            
            if score > 0:
                scores[language] = score
        
        # 返回得分最高的语言
        if scores:
            return max(scores, key=scores.get)
        
        # 基于文件扩展名的提示
        if ".py" in code or "python" in code.lower():
            return "python"
        elif ".sh" in code or "bash" in code.lower():
            return "bash"
        elif ".js" in code or "javascript" in code.lower():
            return "javascript"
        
        return None
    
    @staticmethod
    def validate_python_code(code: str) -> Tuple[bool, Optional[str]]:
        """验证Python代码语法"""
        try:
            # 尝试编译代码
            compile(code, '<string>', 'exec')
            
            # 额外的安全检查
            tree = ast.parse(code)
            
            # 检查危险的导入
            dangerous_imports = {'os', 'subprocess', 'eval', 'exec', '__import__'}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in dangerous_imports:
                            return True, f"Warning: Import of '{alias.name}' detected"
                elif isinstance(node, ast.ImportFrom):
                    if node.module in dangerous_imports:
                        return True, f"Warning: Import from '{node.module}' detected"
            
            return True, None
            
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def validate_bash_code(code: str) -> Tuple[bool, Optional[str]]:
        """验证Bash代码（基础检查）"""
        # 危险命令检查（更全面）
        dangerous_patterns = [
            r'rm\s+-rf\s+/',  # rm -rf /
            r'rm\s+-rf\s+/\*',  # rm -rf /*
            r':\(\)\s*\{\s*:\|\s*:\s*&\s*\}\s*;',  # Fork bomb
            r'dd\s+if=/dev/zero\s+of=/',  # Overwrite with zeros
            r'mkfs\.',  # Format filesystem
            r'>\s*/dev/sda',  # Direct write to disk
            r'wget.*\|\s*sh',  # Download and execute
            r'curl.*\|\s*sh',  # Download and execute
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                return False, f"Dangerous pattern detected: {pattern}"
        
        # 基本语法检查
        open_brackets = code.count('(') - code.count(')')
        if open_brackets != 0:
            return False, f"Unmatched parentheses: {'(' if open_brackets > 0 else ')'} x{abs(open_brackets)}"
        
        open_braces = code.count('{') - code.count('}')
        if open_braces != 0:
            return False, f"Unmatched braces: {'{' if open_braces > 0 else '}'} x{abs(open_braces)}"
        
        open_squares = code.count('[') - code.count(']')
        if open_squares != 0:
            return False, f"Unmatched square brackets: {'[' if open_squares > 0 else ']'} x{abs(open_squares)}"
        
        # 检查基本的bash语法结构
        if_count = len(re.findall(r'\bif\b', code))
        fi_count = len(re.findall(r'\bfi\b', code))
        if if_count != fi_count:
            return False, f"Unmatched if/fi statements: if={if_count}, fi={fi_count}"
        
        do_count = len(re.findall(r'\bdo\b', code))
        done_count = len(re.findall(r'\bdone\b', code))
        if do_count != done_count:
            return False, f"Unmatched do/done statements: do={do_count}, done={done_count}"
        
        case_count = len(re.findall(r'\bcase\b', code))
        esac_count = len(re.findall(r'\besac\b', code))
        if case_count != esac_count:
            return False, f"Unmatched case/esac statements: case={case_count}, esac={esac_count}"
        
        return True, None
    
    @staticmethod
    def validate_javascript_code(code: str) -> Tuple[bool, Optional[str]]:
        """验证JavaScript代码（基础检查）"""
        # 基本语法检查
        open_braces = code.count('{') - code.count('}')
        if open_braces != 0:
            return False, f"Unmatched braces: {'{' if open_braces > 0 else '}'} x{abs(open_braces)}"
        
        open_parens = code.count('(') - code.count(')')
        if open_parens != 0:
            return False, f"Unmatched parentheses: {'(' if open_parens > 0 else ')'} x{abs(open_parens)}"
        
        open_squares = code.count('[') - code.count(']')
        if open_squares != 0:
            return False, f"Unmatched square brackets: {'[' if open_squares > 0 else ']'} x{abs(open_squares)}"
        
        # 检查危险的代码
        dangerous_patterns = [
            r'eval\s*\(',
            r'new\s+Function\s*\(',
            r'innerHTML\s*=',
            r'document\.write\s*\(',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, code):
                return True, f"Warning: Potentially dangerous pattern '{pattern}' detected"
        
        return True, None
    


    @staticmethod
    def add_safety_wrapper(code: str, language: str) -> str:
        """为代码添加安全包装"""
        # 检查是否已经是完整的脚本
        if language == CodeType.PYTHON.value:
            # 如果代码已经包含 shebang 或 main 函数，说明是完整脚本
            if code.strip().startswith('#!/') or 'if __name__ == "__main__":' in code:
                return code  # 直接返回原代码，不添加包装
            
            # 否则添加包装
            return f"""#!/usr/bin/env python3
    # -*- coding: utf-8 -*-
    # Auto-generated code by ChatBot API
    # Generated at: {datetime.now().isoformat()}

    import sys
    import os
    import traceback
    import logging

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    logger = logging.getLogger(__name__)

    def main():
        \"\"\"主函数\"\"\"
        try:
            logger.info("Script execution started")
            
    {chr(10).join('        ' + line for line in code.split(chr(10)))}
            
            logger.info("Script execution completed successfully")
            return 0
        except KeyboardInterrupt:
            logger.warning("Script interrupted by user")
            return 130
        except Exception as e:
            logger.error(f"Script execution failed: {{e}}", exc_info=True)
            return 1

    if __name__ == "__main__":
        sys.exit(main())
    """
        
        elif language in [CodeType.BASH.value, CodeType.SHELL.value]:
            # 检查是否已经有 shebang
            if code.strip().startswith('#!/'):
                return code  # 直接返回原代码
            
            # 否则添加包装
            return f"""#!/bin/bash
    # Auto-generated script by ChatBot API
    # Generated at: {datetime.now().isoformat()}

    set -euo pipefail  # Exit on error, undefined variables, pipe failures

    # 脚本目录
    SCRIPT_DIR="$( cd "$( dirname "${{BASH_SOURCE[0]}}" )" && pwd )"
    SCRIPT_NAME="$(basename "$0")"

    # 日志配置
    LOG_LEVEL="${{LOG_LEVEL:-INFO}}"
    LOG_FILE="${{LOG_FILE:-}}"

    # 日志函数
    log() {{
        local level="$1"
        shift
        local message="$*"
        local timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
        
        if [[ -n "$LOG_FILE" ]]; then
            echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
        fi
        
        case "$level" in
            ERROR)
                echo "[$timestamp] [$level] $message" >&2
                ;;
            *)
                echo "[$timestamp] [$level] $message"
                ;;
        esac
    }}

    log_info() {{ log "INFO" "$@"; }}
    log_warn() {{ log "WARN" "$@"; }}
    log_error() {{ log "ERROR" "$@"; }}

    # 错误处理
    error_handler() {{
        local line_no=$1
        local error_code=$2
        log_error "Script failed at line $line_no with exit code $error_code"
        exit $error_code
    }}

    trap 'error_handler $LINENO $?' ERR

    # 清理函数
    cleanup() {{
        log_info "Performing cleanup..."
        # 添加清理逻辑
    }}

    trap cleanup EXIT

    # 主函数
    main() {{
        log_info "Script $SCRIPT_NAME started"
        
    {code}
        
        log_info "Script $SCRIPT_NAME completed successfully"
    }}

    # 执行主函数
    main "$@"
    """
        
        elif language == CodeType.JAVASCRIPT.value:
            # 检查是否已经有 shebang 或是完整模块
            if code.strip().startswith('#!/') or 'module.exports' in code or 'require.main === module' in code:
                return code  # 直接返回原代码
            
            # 否则添加包装
            return f"""#!/usr/bin/env node
    /**
    * Auto-generated code by ChatBot API
    * Generated at: {datetime.now().isoformat()}
    */

    'use strict';

    const fs = require('fs');
    const path = require('path');
    const util = require('util');

    // 日志配置
    const LOG_LEVELS = {{
        ERROR: 0,
        WARN: 1,
        INFO: 2,
        DEBUG: 3
    }};

    const currentLogLevel = LOG_LEVELS[process.env.LOG_LEVEL || 'INFO'];

    // 日志函数
    function log(level, ...args) {{
        if (LOG_LEVELS[level] <= currentLogLevel) {{
            const timestamp = new Date().toISOString();
            const message = util.format(...args);
            console[level.toLowerCase()](`[${{timestamp}}] [${{level}}] ${{message}}`);
        }}
    }}

    const logger = {{
        error: (...args) => log('ERROR', ...args),
        warn: (...args) => log('WARN', ...args),
        info: (...args) => log('INFO', ...args),
        debug: (...args) => log('DEBUG', ...args)
    }};

    // 错误处理
    process.on('uncaughtException', (error) => {{
        logger.error('Uncaught Exception:', error);
        process.exit(1);
    }});

    process.on('unhandledRejection', (reason, promise) => {{
        logger.error('Unhandled Rejection at:', promise, 'reason:', reason);
        process.exit(1);
    }});

    // 主函数
    async function main() {{
        try {{
            logger.info('Script execution started');
            
    {chr(10).join('        ' + line for line in code.split(chr(10)))}
            
            logger.info('Script execution completed successfully');
        }} catch (error) {{
            logger.error('Script execution failed:', error);
            process.exit(1);
        }}
    }}

    // 执行
    if (require.main === module) {{
        main();
    }}

    module.exports = {{ main }};
    """
        
        # 其他语言直接返回原始代码
        return code


    @staticmethod
    def extract_imports(code: str, language: str) -> List[str]:
        """提取代码中的导入/依赖"""
        imports = []
        
        if language == CodeType.PYTHON.value:
            # Python imports
            import_pattern = re.compile(r'^(?:import|from)\s+(\S+)', re.MULTILINE)
            for match in import_pattern.finditer(code):
                module = match.group(1).split('.')[0]
                if module not in imports:
                    imports.append(module)
        
        elif language == CodeType.JAVASCRIPT.value:
            # JavaScript imports/requires
            import_patterns = [
                re.compile(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]"),
                re.compile(r"require\s*\(['\"]([^'\"]+)['\"]\)"),
            ]
            for pattern in import_patterns:
                for match in pattern.finditer(code):
                    module = match.group(1)
                    if module not in imports:
                        imports.append(module)
        
        return imports
    
    @staticmethod
    def estimate_complexity(code: str, language: str) -> Dict[str, int]:
        """估算代码复杂度"""
        lines = code.split('\n')
        
        metrics = {
            'lines': len(lines),
            'loc': len([l for l in lines if l.strip() and not l.strip().startswith(('#', '//', '/*', '*'))]),
            'functions': 0,
            'classes': 0,
            'imports': 0,
            'complexity': 1  # 基础复杂度
        }
        
        if language == CodeType.PYTHON.value:
            metrics['functions'] = len(re.findall(r'^\s*def\s+', code, re.MULTILINE))
            metrics['classes'] = len(re.findall(r'^\s*class\s+', code, re.MULTILINE))
            metrics['imports'] = len(re.findall(r'^(?:import|from)\s+', code, re.MULTILINE))
            
            # 计算圈复杂度（简化版）
            metrics['complexity'] += len(re.findall(r'\b(?:if|elif|for|while|except)\b', code))
            
        elif language == CodeType.BASH.value:
            metrics['functions'] = len(re.findall(r'^\s*function\s+\w+|^\s*\w+\s*\(\)', code, re.MULTILINE))
            metrics['complexity'] += len(re.findall(r'\b(?:if|elif|for|while|case)\b', code))
            
        elif language == CodeType.JAVASCRIPT.value:
            metrics['functions'] = len(re.findall(r'function\s+\w+|(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:function|\(.*?\)\s*=>)', code))
            metrics['classes'] = len(re.findall(r'class\s+\w+', code))
            metrics['imports'] = len(re.findall(r'(?:import|require)\s*\(', code))
            metrics['complexity'] += len(re.findall(r'\b(?:if|else\s+if|for|while|switch|catch)\b', code))
        
        return metrics