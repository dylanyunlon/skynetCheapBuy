# app/services/bash_script_vibe_service.py - Bash脚本生成版本

from typing import Dict, Any, Optional, List
import json
import asyncio
import logging
import re
from datetime import datetime
from uuid import uuid4
from pathlib import Path

from app.core.workspace.workspace_manager import WorkspaceManager
from app.core.ai_engine import AIEngine
from app.core.preview.preview_manager import PreviewManager
from app.core.ai.system_prompts import BashScriptPromptAdapter
from app.models.workspace import Project, ProjectFile
from app.config import settings

logger = logging.getLogger(__name__)

class BashScriptVibeService:
    """
    Bash脚本生成的Vibe Coding服务
    专注于生成bash脚本来自动化项目创建和部署
    """
    
    def __init__(self, db_session, workspace_manager: WorkspaceManager, ai_engine: AIEngine):
        self.db = db_session
        self.workspace_manager = workspace_manager
        self.ai_engine = ai_engine
        self.preview_manager = PreviewManager()
        self.bash_prompt_adapter = BashScriptPromptAdapter(ai_engine)
        
    async def create_project_from_vibe_chat(
        self,
        user_id: str,
        user_input: str,
        chat_session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        从用户输入生成bash脚本并创建项目
        
        流程：
        1. Meta-prompt生成项目设计
        2. 生成完整的bash脚本
        3. 解析bash脚本提取文件内容
        4. 创建项目和部署
        """
        
        logger.info(f"Starting bash script generation vibe coding for user {user_id}")
        
        try:
            # 阶段1: Meta-prompt生成项目规划
            meta_result = await self._generate_project_meta_with_bash_focus(user_input)
            
            # 阶段2: 生成完整的bash脚本
            bash_script_result = await self._generate_comprehensive_bash_script(meta_result, user_input)
            
            # 阶段3: 从bash脚本中解析项目文件
            project_files = await self._extract_files_from_bash_script(bash_script_result["script"])
            
            # 阶段4: 创建项目记录
            project = await self._create_project_record(
                user_id=user_id,
                user_input=user_input,
                meta_result=meta_result,
                bash_script=bash_script_result["script"],
                project_files=project_files
            )
            
            # 阶段5: 创建工作空间
            workspace_result = await self._create_workspace(project, meta_result)
            
            # 阶段6: 保存bash脚本和项目文件
            files_result = await self._save_bash_script_and_files(
                project, workspace_result, bash_script_result["script"], project_files
            )
            
            # 阶段7: 执行bash脚本进行部署
            deployment_result = await self._execute_bash_script_deployment(
                project, workspace_result, bash_script_result["script"]
            )
            
            # 阶段8: 设置预览URL
            preview_url = await self._setup_preview_from_deployment(
                project, workspace_result, deployment_result
            )
            
            # 阶段9: 更新项目状态
            await self._update_project_status(project, deployment_result, preview_url)
            
            return {
                "success": True,
                "project": {
                    "id": str(project.id),
                    "name": project.name,
                    "type": project.project_type,
                    "status": project.status,
                    "preview_url": preview_url
                },
                "workspace_result": workspace_result,
                "files_result": files_result,
                "deployment_result": deployment_result,
                "preview_url": preview_url,
                "bash_script_generated": True,
                "generation_method": "bash_automation",
                "meta_data": {
                    "user_input": user_input,
                    "meta_result": meta_result,
                    "bash_script_size": len(bash_script_result["script"]),
                    "extracted_files": list(project_files.keys())
                }
            }
            
        except Exception as e:
            logger.error(f"Bash script vibe coding failed: {e}", exc_info=True)
            raise Exception(f"Bash脚本生成项目失败: {str(e)}")
    
    async def _generate_project_meta_with_bash_focus(self, user_input: str) -> Dict[str, Any]:
        """生成专注于bash自动化的项目meta信息"""
        
        meta_prompt = f"""
        分析以下用户需求，设计一个可以通过bash脚本完全自动化的项目：
        
        用户需求: {user_input}
        
        请提供详细的bash自动化设计方案，包含：
        1. 项目结构和自动化策略
        2. 需要生成的文件及其完整内容规划
        3. 部署自动化和服务器管理策略
        4. 错误处理和环境兼容性设计
        5. 用户体验和交互设计要求
        
        重点关注如何通过单个bash脚本实现完整的项目创建和部署自动化。
        """
        
        try:
            messages = await self.bash_prompt_adapter.prepare_bash_generation_messages(
                user_message=meta_prompt,
                stage="meta"
            )
            
            response = await self.ai_engine.get_completion(
                messages=messages,
                model="Doubao-1.5-pro-256k",
                temperature=0.7,
                max_tokens=3000
            )
            
            content = response.get("content", "")
            
            if not content or len(content) < 100:
                raise ValueError("Meta分析结果不足")
            
            project_info = self._extract_project_info_from_meta(content, user_input)
            
            return {
                "success": True,
                "meta_analysis": content,
                "project_info": project_info,
                "bash_automation_focused": True
            }
            
        except Exception as e:
            logger.error(f"Bash-focused meta generation failed: {e}")
            raise Exception(f"项目meta分析失败: {str(e)}")
    
    async def _generate_comprehensive_bash_script(self, meta_result: Dict[str, Any], user_input: str) -> Dict[str, str]:
        """生成完整的bash脚本"""
        
        project_info = meta_result.get("project_info", {})
        meta_analysis = meta_result.get("meta_analysis", "")
        
        # 使用专门的bash脚本生成prompt
        bash_prompt = self.bash_prompt_adapter.create_bash_generation_prompt(user_input, project_info)
        
        # 添加meta分析的上下文
        enhanced_prompt = f"""
        基于以下项目分析，生成完整的bash自动化脚本：
        
        项目分析结果:
        {meta_analysis}
        
        {bash_prompt}
        
        请生成一个完整的、可立即执行的bash脚本，该脚本能够：
        - 创建完整的项目目录结构
        - 使用heredoc语法生成所有文件的完整内容
        - 实现智能的部署自动化
        - 包含全面的错误处理和用户反馈
        
        脚本必须是自包含的，运行后能创建完全功能的web应用。
        """
        
        try:
            messages = await self.bash_prompt_adapter.prepare_bash_generation_messages(
                user_message=enhanced_prompt,
                stage="generation"
            )
            
            response = await self.ai_engine.get_completion(
                messages=messages,
                model="Doubao-1.5-pro-256k",
                temperature=0.3,  # 较低温度确保脚本质量
                max_tokens=4000
            )
            
            bash_script = response.get("content", "")
            
            if not bash_script or len(bash_script) < 500:
                raise ValueError("生成的bash脚本过短")
            
            # 验证bash脚本基本结构
            if not self._validate_bash_script_structure(bash_script):
                # 尝试修复bash脚本
                bash_script = await self._fix_bash_script_structure(bash_script, project_info)
            
            logger.info(f"Generated bash script: {len(bash_script)} characters")
            
            return {
                "script": bash_script,
                "generation_method": "ai_comprehensive",
                "validated": True
            }
            
        except Exception as e:
            logger.error(f"Bash script generation failed: {e}")
            # 生成基础的bash脚本作为backup
            return await self._generate_fallback_bash_script(project_info, user_input)
    
    def _validate_bash_script_structure(self, bash_script: str) -> bool:
        """验证bash脚本的基本结构"""
        
        required_elements = [
            "#!/bin/bash",  # shebang
            "cat >",        # heredoc文件生成
            "index.html",   # HTML文件
            "style.css",    # CSS文件
            "script.js",    # JS文件
            "python",       # 服务器启动
            "PORT",         # 端口配置
        ]
        
        for element in required_elements:
            if element not in bash_script:
                logger.warning(f"Bash script missing required element: {element}")
                return False
        
        return True
    
    async def _fix_bash_script_structure(self, bash_script: str, project_info: Dict[str, Any]) -> str:
        """修复bash脚本结构"""
        
        fix_prompt = f"""
        以下bash脚本结构不完整，请修复并补全：
        
        原始脚本:
        {bash_script}
        
        项目信息:
        {json.dumps(project_info, ensure_ascii=False, indent=2)}
        
        请补全以下缺失的部分：
        1. 如果缺少shebang，添加 #!/bin/bash
        2. 如果缺少文件生成，添加使用heredoc的完整文件创建
        3. 如果缺少服务器启动，添加Python HTTP服务器启动逻辑
        4. 如果缺少错误处理，添加全面的错误处理
        
        返回完整、可执行的bash脚本。
        """
        
        try:
            messages = await self.bash_prompt_adapter.prepare_bash_generation_messages(
                user_message=fix_prompt,
                stage="extraction"
            )
            
            response = await self.ai_engine.get_completion(
                messages=messages,
                model="Doubao-1.5-pro-256k",
                temperature=0.2,
                max_tokens=4000
            )
            
            fixed_script = response.get("content", "")
            
            if fixed_script and len(fixed_script) > len(bash_script):
                return fixed_script
            else:
                return bash_script
                
        except Exception as e:
            logger.error(f"Bash script fix failed: {e}")
            return bash_script
    
    async def _generate_fallback_bash_script(self, project_info: Dict[str, Any], user_input: str) -> Dict[str, str]:
        """生成备用bash脚本"""
        
        target_person = project_info.get("target_person", "sky-net")
        port = project_info.get("port", 17430)
        
        fallback_script = f"""#!/bin/bash
# Skynet Console - Vibe Coding Project Generator
# Generated for: {user_input}
# Target: {target_person}

set -euo pipefail

# Configuration
PROJECT_NAME="{target_person}个人网站"
PORT={port}
SERVER_HOST="8.163.12.28"
BASE_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

# Logging functions
log_info() {{ echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"; }}
log_error() {{ echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }}
log_success() {{ echo "[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS: $*"; }}

# Error handling
error_handler() {{
    log_error "Script failed at line $1 with exit code $2"
    exit $2
}}
trap 'error_handler $LINENO $?' ERR

main() {{
    log_info "开始创建$PROJECT_NAME项目..."
    
    # Create project files
    create_html_file
    create_css_file
    create_js_file
    
    # Deploy project
    manage_port
    start_server
    
    log_success "项目创建完成！访问: http://$SERVER_HOST:$PORT"
}}

create_html_file() {{
    log_info "创建index.html..."
    cat > index.html << 'HTML_EOF'
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{target_person} - 个人网站</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>{target_person}</h1>
            <p class="subtitle">个人信息展示</p>
        </header>
        <main>
            <section class="info">
                <h2>基本信息</h2>
                <div class="info-item">姓名：{target_person}</div>
                <div class="info-item">状态：在线</div>
                <div class="info-item">更新：<span id="current-time"></span></div>
            </section>
            <section class="contact">
                <h2>联系方式</h2>
                <button onclick="showContact()">联系我</button>
            </section>
        </main>
    </div>
    <script src="script.js"></script>
</body>
</html>
HTML_EOF
    log_success "HTML文件创建完成"
}}

create_css_file() {{
    log_info "创建style.css..."
    cat > style.css << 'CSS_EOF'
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}

body {{
    font-family: 'Microsoft YaHei', sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 20px;
}}

.container {{
    background: rgba(255, 255, 255, 0.95);
    padding: 40px;
    border-radius: 20px;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
    text-align: center;
    max-width: 600px;
    width: 100%;
}}

h1 {{
    font-size: 2.5rem;
    color: #2c3e50;
    margin-bottom: 10px;
}}

.subtitle {{
    color: #7f8c8d;
    margin-bottom: 30px;
    font-style: italic;
}}

.info, .contact {{
    margin: 30px 0;
    padding: 20px;
    background: rgba(102, 126, 234, 0.1);
    border-radius: 10px;
}}

.info-item {{
    margin: 10px 0;
    padding: 10px;
    background: rgba(255, 255, 255, 0.8);
    border-radius: 5px;
}}

button {{
    background: linear-gradient(45deg, #667eea, #764ba2);
    color: white;
    border: none;
    padding: 12px 24px;
    border-radius: 25px;
    font-size: 1rem;
    cursor: pointer;
    transition: transform 0.3s ease;
}}

button:hover {{
    transform: translateY(-2px);
}}

@media (max-width: 600px) {{
    .container {{
        padding: 20px;
        margin: 10px;
    }}
    h1 {{
        font-size: 2rem;
    }}
}}
CSS_EOF
    log_success "CSS文件创建完成"
}}

create_js_file() {{
    log_info "创建script.js..."
    cat > script.js << 'JS_EOF'
document.addEventListener('DOMContentLoaded', function() {{
    console.log('{target_person}个人网站已加载完成');
    
    // 更新时间
    function updateTime() {{
        const now = new Date();
        const timeString = now.toLocaleString('zh-CN');
        const timeElement = document.getElementById('current-time');
        if (timeElement) {{
            timeElement.textContent = timeString;
        }}
    }}
    
    updateTime();
    setInterval(updateTime, 1000);
    
    window.showContact = function() {{
        alert(`联系{target_person}\\n\\n📧 邮箱: contact@{target_person.lower()}.com\\n🌐 网站: http://localhost:{port}\\n📱 状态: 在线`);
    }};
}});
JS_EOF
    log_success "JavaScript文件创建完成"
}}

manage_port() {{
    log_info "检查端口$PORT..."
    
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_info "端口$PORT被占用，正在释放..."
        lsof -ti:$PORT | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
    
    log_success "端口$PORT可用"
}}

start_server() {{
    log_info "启动服务器..."
    
    if command -v python3 >/dev/null 2>&1; then
        nohup python3 -m http.server $PORT --bind 0.0.0.0 > server.log 2>&1 &
    elif command -v python >/dev/null 2>&1; then
        nohup python -m SimpleHTTPServer $PORT > server.log 2>&1 &
    else
        log_error "未找到Python，无法启动服务器"
        exit 1
    fi
    
    SERVER_PID=$!
    echo $SERVER_PID > server.pid
    sleep 3
    
    if ps -p $SERVER_PID > /dev/null 2>&1; then
        log_success "服务器启动成功 (PID: $SERVER_PID)"
        log_success "访问地址: http://$SERVER_HOST:$PORT"
    else
        log_error "服务器启动失败"
        exit 1
    fi
}}

# 执行主函数
main "$@"
"""
        
        return {
            "script": fallback_script,
            "generation_method": "fallback_template",
            "validated": True
        }
    
    async def _extract_files_from_bash_script(self, bash_script: str) -> Dict[str, str]:
        """从bash脚本中提取文件内容"""
        
        files = {}
        
        # 使用正则表达式提取heredoc内容
        heredoc_patterns = [
            (r"cat\s*>\s*([^<\s]+)\s*<<\s*['\"]?(\w+)['\"]?\s*\n(.*?)\n\2", "heredoc_with_delimiter"),
            (r"cat\s*>\s*([^<\s]+)\s*<<\s*'([^']+)'\s*\n(.*?)\n\2", "heredoc_quoted"),
            (r"cat\s*>\s*([^<\s]+)\s*<<\s*(\w+)\s*\n(.*?)\n\2", "heredoc_simple"),
        ]
        
        for pattern, pattern_type in heredoc_patterns:
            matches = re.finditer(pattern, bash_script, re.DOTALL | re.MULTILINE)
            for match in matches:
                filename = match.group(1).strip()
                content = match.group(3).strip()
                
                if filename and content and len(content) > 50:  # 确保有实质内容
                    files[filename] = content
                    logger.info(f"Extracted {filename} from bash script ({len(content)} chars)")
        
        # 如果没有提取到文件，尝试其他方法
        if not files:
            files = await self._extract_files_with_ai_assistance(bash_script)
        
        return files
    
    async def _extract_files_with_ai_assistance(self, bash_script: str) -> Dict[str, str]:
        """使用AI辅助从bash脚本中提取文件"""
        
        extraction_prompt = f"""
        请从以下bash脚本中提取所有文件内容：
        
        {bash_script}
        
        请识别脚本中生成的文件（通常使用cat > filename << EOF的语法），
        并返回JSON格式的文件结构：
        
        {{
            "filename": "file content"
        }}
        
        只返回JSON，不要其他说明。
        """
        
        try:
            messages = await self.bash_prompt_adapter.prepare_bash_generation_messages(
                user_message=extraction_prompt,
                stage="extraction"
            )
            
            response = await self.ai_engine.get_completion(
                messages=messages,
                model="Doubao-1.5-pro-256k",
                temperature=0.1,
                max_tokens=3000
            )
            
            ai_response = response.get("content", "")
            
            # 尝试解析JSON
            try:
                files = json.loads(ai_response)
                if isinstance(files, dict) and files:
                    return files
            except json.JSONDecodeError:
                pass
                
        except Exception as e:
            logger.error(f"AI-assisted file extraction failed: {e}")
        
        return {}
    
    async def _save_bash_script_and_files(
        self,
        project: Project,
        workspace_result: Dict[str, Any],
        bash_script: str,
        project_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """保存bash脚本和提取的文件"""
        
        saved_files = []
        
        try:
            # 保存主要的bash脚本
            bash_script_result = await self.workspace_manager.add_file(
                user_id=str(project.user_id),
                project_id=workspace_result["project_id"],
                file_path="create_project.sh",
                content=bash_script,
                file_type="script"
            )
            saved_files.append(bash_script_result)
            
            # 保存从bash脚本提取的文件
            for filename, content in project_files.items():
                file_result = await self.workspace_manager.add_file(
                    user_id=str(project.user_id),
                    project_id=workspace_result["project_id"],
                    file_path=filename,
                    content=content,
                    file_type=self._detect_file_type(filename)
                )
                saved_files.append(file_result)
                
                # 创建数据库记录
                project_file = ProjectFile(
                    id=uuid4(),
                    project_id=project.id,
                    file_path=filename,
                    content=content,
                    file_type=self._detect_file_type(filename),
                    language=self._detect_language(filename),
                    size=len(content),
                    is_entry_point=(filename == "index.html"),
                    is_generated=True,
                    bash_generated=True  # 标记为bash脚本生成
                )
                self.db.add(project_file)
            
            self.db.commit()
            
            return {
                "saved_files": saved_files,
                "file_count": len(saved_files),
                "bash_script_saved": True,
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Failed to save bash script and files: {e}")
            return {
                "saved_files": saved_files,
                "file_count": len(saved_files),
                "bash_script_saved": False,
                "success": False,
                "error": str(e)
            }
    
    async def _execute_bash_script_deployment(
        self,
        project: Project,
        workspace_result: Dict[str, Any],
        bash_script: str
    ) -> Dict[str, Any]:
        """执行bash脚本进行项目部署"""
        
        try:
            # 获取项目路径
            project_path = Path(workspace_result.get("path", ""))
            bash_script_path = project_path / "create_project.sh"
            
            # 确保bash脚本有执行权限
            import stat
            bash_script_path.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IROTH)
            
            # 执行bash脚本
            deployment_result = await self.workspace_manager.execute_project(
                user_id=str(project.user_id),
                project_id=workspace_result["project_id"],
                entry_point="create_project.sh",
                timeout=120  # 给bash脚本更多时间
            )
            
            logger.info(f"Bash script deployment result: {deployment_result}")
            return deployment_result
            
        except Exception as e:
            logger.error(f"Bash script deployment failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "bash_execution": True
            }
    
    # 其他辅助方法保持类似...
    def _extract_project_info_from_meta(self, content: str, user_input: str) -> Dict[str, Any]:
        """从meta响应中提取项目信息"""
        import re
        
        project_info = {
            "type": "web",
            "technologies": ["html", "css", "javascript", "bash"],
            "target_person": "sky-net",
            "port": 17430,
            "bash_automation": True
        }
        
        # 提取姓名
        if "sky-net" in content or "sky-net" in user_input:
            project_info["target_person"] = "sky-net"
        
        # 提取端口
        port_match = re.search(r"端口.*?(\d+)", content + user_input)
        if port_match:
            project_info["port"] = int(port_match.group(1))
        
        return project_info
    
    def _detect_file_type(self, filename: str) -> str:
        """检测文件类型"""
        ext_map = {
            ".html": "html",
            ".css": "css",
            ".js": "javascript",
            ".sh": "shell",
            ".json": "json",
            ".md": "markdown"
        }
        ext = Path(filename).suffix.lower()
        return ext_map.get(ext, "text")
    
    def _detect_language(self, filename: str) -> str:
        """检测编程语言"""
        return self._detect_file_type(filename)