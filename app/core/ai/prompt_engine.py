# app/core/ai/prompt_engine.py - 完整版，修复语法错误
import json
import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class PromptEngine:
    """实现 lovable.ai 风格的双重 AI 调用机制"""
    
    def __init__(self, ai_service):
        self.ai_service = ai_service
        
    async def handle_vibe_coding_meta_stage(self, user_input: str) -> Dict[str, Any]:
        """处理 Vibe Coding Meta 阶段 - 第一次AI调用"""
        
        logger.info(f"Starting Vibe Coding Meta stage for input: {user_input[:100]}...")
        
        # 构建 meta-prompt - 这是关键的第一步
        meta_prompt = self._build_meta_prompt_for_project_creation(user_input)
        
        try:
            # 第一次 AI 调用 - 优化用户输入
            response = await self._call_ai_service(meta_prompt, "meta_optimization")
            
            if response.get("success"):
                optimized_description = response["content"]
                
                # 解析优化后的描述，提取关键信息
                project_info = self._extract_project_info_from_optimization(optimized_description)
                
                return {
                    "success": True,
                    "stage": "meta_complete",
                    "original_input": user_input,
                    "meta_prompt": meta_prompt,
                    "optimized_description": optimized_description,
                    "project_info": project_info,
                    "next_stage": "generate"
                }
            else:
                # AI 调用失败，使用模板
                return self._create_meta_fallback_response(user_input)
                
        except Exception as e:
            logger.error(f"Meta stage failed: {e}")
            return self._create_meta_fallback_response(user_input, str(e))
    
    def _build_meta_prompt_for_project_creation(self, user_input: str) -> str:
        """构建项目创建的 meta-prompt - 核心逻辑"""
        
        # 这就是您要求的核心逻辑：帮我设计这个prompt + 我要拿这个prompt来询问chatgpt
        meta_prompt = f"""你是一个专业的 Prompt 工程师和全栈开发专家。

用户输入：{user_input}

请帮我设计一个完整的项目创建 prompt，我要拿这个 prompt 来询问 ChatGPT 生成一个可以直接运行的完整项目。

请按照以下要求分析和优化：

1. **需求分析**：
   - 分析用户真正想要什么
   - 识别项目类型和核心功能
   - 确定技术方案和实现难度

2. **项目设计**：
   - 设计完整的项目架构
   - 选择最适合的技术栈
   - 规划文件结构和模块划分

3. **实现规划**：
   - 详细的功能需求描述
   - 用户体验设计考虑
   - 部署和运行方案

4. **质量保证**：
   - 确保生成的代码可以直接运行
   - 包含适当的错误处理
   - 考虑安全性和性能

请返回以下格式的项目方案：

**🎯 项目目标**：[简洁描述项目要实现什么]

**🛠️ 技术方案**：[具体的技术栈选择和理由]

**📁 项目结构**：[主要文件和目录规划]

**✨ 核心功能**：[详细的功能列表]

**🚀 部署方案**：[如何运行和部署]

**💡 特色亮点**：[项目的独特之处]

请确保方案详细具体，能够直接用于指导项目生成。"""

        return meta_prompt
    
    async def handle_vibe_coding_generate_stage(self, meta_result: Dict[str, Any]) -> Dict[str, Any]:
        """处理 Vibe Coding Generate 阶段 - 第二次AI调用"""
        
        logger.info(f"Starting Vibe Coding Generate stage")
        
        optimized_description = meta_result.get("optimized_description", "")
        project_info = meta_result.get("project_info", {})
        
        # 构建最终的项目生成 prompt
        generate_prompt = self._build_project_generation_prompt(optimized_description, project_info)
        
        try:
            # 第二次 AI 调用 - 生成实际项目
            response = await self._call_ai_service(generate_prompt, "project_generation")
            
            if response.get("success"):
                ai_response = response["content"]
                
                # 解析 AI 响应为结构化数据
                project_data = await self.parse_ai_response(ai_response)
                
                return {
                    "success": True,
                    "stage": "generate_complete",
                    "ai_response": ai_response,
                    "project_data": project_data,
                    "meta_result": meta_result
                }
            else:
                # AI 调用失败，使用降级方案
                return self._create_generate_fallback_response(meta_result)
                
        except Exception as e:
            logger.error(f"Generate stage failed: {e}")
            return self._create_generate_fallback_response(meta_result, str(e))
    
    def _build_project_generation_prompt(self, optimized_description: str, project_info: Dict[str, Any]) -> str:
        """构建项目生成的最终 prompt"""
        
        final_prompt = f"""
基于以下优化后的项目需求，请生成一个完整的可运行项目：

项目需求描述：
{optimized_description}

项目信息：
- 项目类型：{project_info.get('type', 'web')}
- 目标用户：{project_info.get('target_person', '未指定')}
- 技术栈：{', '.join(project_info.get('technologies', ['html', 'css', 'javascript']))}
- 端口：{project_info.get('port', '8000')}

请返回严格的 JSON 格式，包含完整的项目结构：

```json
{{
  "project_meta": {{
    "name": "项目名称",
    "type": "项目类型",
    "description": "项目描述",
    "tech_stack": ["技术栈列表"],
    "target_person": "目标用户",
    "port": 端口号
  }},
  "files": {{
    "文件路径": {{
      "content": "完整的文件内容",
      "description": "文件说明"
    }}
  }},
  "deployment": {{
    "type": "部署类型",
    "commands": ["部署命令"],
    "entry_point": "入口文件",
    "port": 端口号
  }}
}}```

严格要求：
1. 所有文件内容必须完整且可运行
2. Shell 脚本语法必须正确，特别注意：
   - 使用 `if ! command` 而不是 `if! command`
   - 命令之间要有正确的空格
   - 条件判断要有正确的语法
3. 包含适当的错误处理和用户友好的提示
4. 代码要有清晰的注释
5. 确保用户体验良好
6. 生成的项目要能直接部署运行
7. 特别处理端口冲突问题（自动杀死占用端口的进程）

如果是个人展示网站，请确保：
- 现代化的响应式设计
- 优雅的视觉效果
- 实用的交互功能
- 完善的信息展示

请只返回 JSON，不要包含其他说明文字。
"""
        
        return final_prompt
    
    async def _call_ai_service(self, prompt: str, call_type: str) -> Dict[str, Any]:
        """调用 AI 服务的统一方法"""
        
        try:
            # 检查ai_service的方法类型
            if hasattr(self.ai_service, 'get_completion'):
                response = await self.ai_service.get_completion(
                    messages=[{"role": "user", "content": prompt}],
                    model="claude-opus-4-6",
                    temperature=0.7 if call_type == "meta_optimization" else 0.3,
                    max_tokens=4000
                )
                return {
                    "success": True,
                    "content": response.get("content", ""),
                    "call_type": call_type
                }
                
            elif hasattr(self.ai_service, 'process_message'):
                response = await self.ai_service.process_message(
                    user_id="system",
                    message=prompt,
                    model="claude-opus-4-6"
                )
                return {
                    "success": True,
                    "content": response.get("content", ""),
                    "call_type": call_type
                }
            else:
                logger.warning(f"AI service doesn't have expected methods for {call_type}")
                return {"success": False, "error": "AI service not available"}
                
        except Exception as e:
            logger.error(f"AI service call failed for {call_type}: {e}")
            return {"success": False, "error": str(e)}
    
    def _extract_project_info_from_optimization(self, optimized_description: str) -> Dict[str, Any]:
        """从优化后的描述中提取项目信息"""
        
        project_info = {
            "type": "web",
            "technologies": ["html", "css", "javascript"],
            "target_person": "sky-net",
            "port": 17430
        }
        
        # 提取项目类型
        if any(keyword in optimized_description.lower() for keyword in ["网站", "web", "homepage", "个人主页"]):
            project_info["type"] = "web"
        elif any(keyword in optimized_description.lower() for keyword in ["api", "后端", "服务"]):
            project_info["type"] = "api"
        elif any(keyword in optimized_description.lower() for keyword in ["工具", "脚本", "tool"]):
            project_info["type"] = "tool"
        
        # 提取技术栈
        techs = []
        tech_map = {
            "html": ["html", "网页"],
            "css": ["css", "样式"],
            "javascript": ["javascript", "js", "交互"],
            "python": ["python", "py"],
            "shell": ["shell", "bash", "脚本", "sh"]
        }
        
        for tech, keywords in tech_map.items():
            if any(keyword in optimized_description.lower() for keyword in keywords):
                techs.append(tech)
        
        if techs:
            project_info["technologies"] = techs
        
        # 提取目标用户
        name_match = re.search(r"sky-net|甘.*?晓.*?婷", optimized_description)
        if name_match:
            project_info["target_person"] = "sky-net"
        
        # 提取端口
        port_match = re.search(r"端口.*?(\d+)", optimized_description)
        if port_match:
            project_info["port"] = int(port_match.group(1))
        
        return project_info
    
    def _create_meta_fallback_response(self, user_input: str, error: str = None) -> Dict[str, Any]:
        """创建 Meta 阶段的降级响应"""
        
        # 分析用户输入，提取关键信息
        target_person = "sky-net" if "sky-net" in user_input else "用户"
        
        optimized_description = f"""
📋 **项目需求优化完成**

根据您的需求，我为您设计了以下项目方案：

🎯 **项目目标**：创建{target_person}个人信息展示网站
- 现代化的个人主页设计
- 响应式布局，支持移动设备
- 优雅的视觉效果和交互体验

🛠️ **技术方案**：HTML5 + CSS3 + JavaScript + Shell脚本
- 纯静态网站，无需数据库
- Python内置服务器提供Web服务
- 智能端口管理，自动处理冲突

📁 **项目结构**：
- index.html：主页面，包含个人信息展示
- start_server.sh：启动脚本，处理端口冲突
- README.md：项目说明和使用指南

✨ **核心功能**：
- 个人信息展示模块
- 实时时间显示
- 联系方式展示
- 服务器状态监控
- 一键启动部署

🚀 **部署方案**：使用端口17430，智能处理端口占用问题
- 自动检测并终止占用端口的进程
- 启动Python静态文件服务器
- 提供完整的启动和停止提示

💡 **特色亮点**：
- 智能端口冲突处理
- 现代渐变色UI设计
- 响应式布局适配
- 用户友好的错误提示
- 完整的项目文档

确认开始生成项目吗？
"""
        
        project_info = {
            "type": "web",
            "technologies": ["html", "css", "javascript", "shell"],
            "target_person": target_person,
            "port": 17430
        }
        
        return {
            "success": True,
            "stage": "meta_complete",
            "original_input": user_input,
            "optimized_description": optimized_description,
            "project_info": project_info,
            "next_stage": "generate",
            "fallback": True,
            "error": error
        }
    
    def _create_generate_fallback_response(self, meta_result: Dict[str, Any], error: str = None) -> Dict[str, Any]:
        """创建 Generate 阶段的降级响应"""
        
        project_info = meta_result.get("project_info", {})
        target_person = project_info.get("target_person", "sky-net")
        port = project_info.get("port", 17430)
        
        # 使用完善的降级项目结构
        fallback_structure = self._get_enhanced_fallback_project_structure(target_person, port)
        
        return {
            "success": True,
            "stage": "generate_complete",
            "ai_response": json.dumps(fallback_structure),
            "project_data": fallback_structure,
            "meta_result": meta_result,
            "fallback": True,
            "error": error
        }

    async def parse_ai_response(self, ai_response: str) -> Dict[str, Any]:
        """解析 AI 响应为结构化数据 - 增强版"""
        
        try:
            # 尝试直接解析 JSON
            return json.loads(ai_response)
        except json.JSONDecodeError:
            # 尝试提取 JSON 代码块
            json_patterns = [
                r'```json\s*(\{.*?\})\s*```',
                r'```\s*(\{.*?\})\s*```',
                r'(\{[^}]*"project_meta"[^}]*\}.*)',
            ]
            
            for pattern in json_patterns:
                match = re.search(pattern, ai_response, re.DOTALL | re.IGNORECASE)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except json.JSONDecodeError:
                        continue
            
            # 如果都失败了，返回默认结构
            logger.warning(f"Failed to parse AI response as JSON: {ai_response[:200]}...")
            return self._get_enhanced_fallback_project_structure()

    def _get_enhanced_fallback_project_structure(self, target_person: str = "sky-net", port: int = 17430) -> Dict[str, Any]:
        """获取增强的默认项目结构 - 修复语法错误"""
        
        return {
            "project_meta": {
                "name": f"{target_person}个人网站",
                "type": "web",
                "description": f"{target_person}的个人信息展示网站，使用端口{port}",
                "tech_stack": ["html", "css", "javascript", "shell"],
                "target_person": target_person,
                "port": port
            },
            "files": {
                "start_server.sh": {
                    "content": f"""#!/bin/bash

# {target_person}个人网站启动脚本
# 使用端口 {port}，如果被占用则杀死其他进程

echo "==================================="
echo "   {target_person}个人网站启动脚本"
echo "==================================="

# 设置端口
PORT={port}

echo "正在检查端口 $PORT..."

# 检查端口是否被占用 - 修复语法错误
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  警告: 端口 $PORT 已被占用！"
    echo "正在查找占用进程..."
    
    # 显示占用端口的进程信息
    echo "占用端口 $PORT 的进程："
    lsof -Pi :$PORT -sTCP:LISTEN
    
    echo ""
    echo "正在终止占用端口 $PORT 的进程..."
    
    # 杀死占用端口的进程 - 修复语法错误
    PIDS=$(lsof -ti:$PORT)
    if [ ! -z "$PIDS" ]; then
        echo "终止进程 ID: $PIDS"
        kill -9 $PIDS
        echo "✅ 已终止占用端口 $PORT 的所有进程"
    else
        echo "未找到占用端口的进程"
    fi
    
    # 等待端口释放
    echo "等待端口释放..."
    sleep 3
else
    echo "✅ 端口 $PORT 可用"
fi

# 再次检查端口是否已释放
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "❌ 错误: 无法释放端口 $PORT"
    echo "请手动检查并停止占用端口的进程"
    exit 1
fi

echo ""
echo "🚀 正在启动{target_person}个人网站..."
echo "📍 服务器地址: http://localhost:$PORT"
echo "📁 网站目录: $(pwd)"
echo "🌐 主页文件: index.html"
echo ""
echo "✨ 网站功能："
echo "   - 个人信息展示"
echo "   - 实时时间更新"
echo "   - 联系方式"
echo "   - 服务器状态"
echo ""
echo "⏹️  按 Ctrl+C 停止服务器"
echo ""

# 启动 Python 静态文件服务器
echo "启动中..."

# 检查 Python 版本并启动服务器 - 修复语法错误
if command -v python3 >/dev/null 2>&1; then
    echo "使用 Python3 启动服务器..."
    python3 -m http.server $PORT
elif command -v python >/dev/null 2>&1; then
    echo "使用 Python2 启动服务器..."
    python -m SimpleHTTPServer $PORT
else
    echo "❌ 错误: 未找到 Python，无法启动服务器"
    echo "请安装 Python3 或 Python2"
    exit 1
fi

echo ""
echo "🛑 {target_person}个人网站已停止"
""",
                    "description": "网站启动脚本，修复了语法错误"
                },
                "index.html": {
                    "content": f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{target_person} - 个人信息</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        
        .container {{
            max-width: 600px;
            width: 100%;
            background: rgba(255, 255, 255, 0.95);
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(10px);
            text-align: center;
            animation: fadeInUp 0.8s ease-out;
        }}
        
        @keyframes fadeInUp {{
            from {{
                opacity: 0;
                transform: translateY(30px);
            }}
            to {{
                opacity: 1;
                transform: translateY(0);
            }}
        }}
        
        .profile-img {{
            width: 120px;
            height: 120px;
            border-radius: 50%;
            margin: 0 auto 30px;
            background: linear-gradient(45deg, #667eea, #764ba2);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 48px;
            color: white;
            font-weight: bold;
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.3);
            animation: pulse 2s infinite;
        }}
        
        @keyframes pulse {{
            0%, 100% {{
                transform: scale(1);
            }}
            50% {{
                transform: scale(1.05);
            }}
        }}
        
        .name {{
            font-size: 2.5rem;
            color: #2c3e50;
            margin-bottom: 20px;
            font-weight: 300;
            letter-spacing: 2px;
        }}
        
        .subtitle {{
            font-size: 1.1rem;
            color: #7f8c8d;
            margin-bottom: 30px;
            font-style: italic;
        }}
        
        .info-section {{
            margin: 30px 0;
            padding: 25px;
            background: rgba(102, 126, 234, 0.1);
            border-radius: 15px;
            text-align: left;
            border-left: 4px solid #667eea;
        }}
        
        .info-title {{
            font-size: 1.3rem;
            color: #667eea;
            margin-bottom: 15px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        .info-item {{
            margin: 12px 0;
            padding: 12px;
            background: rgba(255, 255, 255, 0.8);
            border-radius: 8px;
            display: flex;
            align-items: center;
            transition: all 0.3s ease;
        }}
        
        .info-item:hover {{
            background: rgba(255, 255, 255, 0.95);
            transform: translateX(5px);
        }}
        
        .info-label {{
            font-weight: 600;
            color: #2c3e50;
            min-width: 80px;
        }}
        
        .info-value {{
            color: #34495e;
            flex: 1;
        }}
        
        .contact-btn {{
            background: linear-gradient(45deg, #667eea, #764ba2);
            color: white;
            padding: 12px 30px;
            border: none;
            border-radius: 25px;
            font-size: 1rem;
            cursor: pointer;
            margin: 10px;
            transition: all 0.3s ease;
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.3);
        }}
        
        .contact-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
            background: linear-gradient(45deg, #5a6fd8, #6a5acd);
        }}
        
        .server-info {{
            background: rgba(46, 204, 113, 0.1);
            padding: 20px;
            border-radius: 12px;
            margin: 20px 0;
            border-left: 4px solid #2ecc71;
        }}
        
        .status-indicator {{
            display: inline-block;
            width: 8px;
            height: 8px;
            background: #2ecc71;
            border-radius: 50%;
            margin-right: 8px;
            animation: blink 1.5s infinite;
        }}
        
        @keyframes blink {{
            0%, 50% {{
                opacity: 1;
            }}
            51%, 100% {{
                opacity: 0.3;
            }}
        }}
        
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid rgba(102, 126, 234, 0.3);
            color: #7f8c8d;
            font-size: 0.9rem;
        }}
        
        @media (max-width: 600px) {{
            .container {{
                margin: 10px;
                padding: 30px 20px;
            }}
            
            .name {{
                font-size: 2rem;
            }}
            
            .profile-img {{
                width: 100px;
                height: 100px;
                font-size: 40px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="profile-img">
            {target_person[0] if target_person else '用'}
        </div>
        
        <h1 class="name">{target_person}</h1>
        <p class="subtitle">个人信息展示网站</p>
        
        <div class="info-section">
            <div class="info-title">
                📋 基本信息
            </div>
            <div class="info-item">
                <span class="info-label">姓名:</span>
                <span class="info-value">{target_person}</span>
            </div>
            <div class="info-item">
                <span class="info-label">状态:</span>
                <span class="info-value">
                    <span class="status-indicator"></span>在线
                </span>
            </div>
            <div class="info-item">
                <span class="info-label">更新:</span>
                <span class="info-value" id="current-time">加载中...</span>
            </div>
        </div>
        
        <div class="server-info">
            <div class="info-title">
                🖥️ 服务器信息
            </div>
            <div class="info-item">
                <span class="info-label">端口:</span>
                <span class="info-value">{port}</span>
            </div>
            <div class="info-item">
                <span class="info-label">状态:</span>
                <span class="info-value">
                    <span class="status-indicator"></span>运行中
                </span>
            </div>
            <div class="info-item">
                <span class="info-label">地址:</span>
                <span class="info-value">http://localhost:{port}</span>
            </div>
        </div>
        
        <div class="info-section">
            <div class="info-title">
                💼 联系方式
            </div>
            <div class="info-item">
                <span class="info-label">网站:</span>
                <span class="info-value">个人主页</span>
            </div>
            <div class="info-item">
                <span class="info-label">邮箱:</span>
                <span class="info-value">contact@{target_person.lower()}.com</span>
            </div>
        </div>
        
        <div>
            <button class="contact-btn" onclick="showContact()">联系我</button>
            <button class="contact-btn" onclick="showServer()">服务器详情</button>
            <button class="contact-btn" onclick="showInfo()">更多信息</button>
        </div>
        
        <div class="footer">
            <p>© 2025 {target_person}个人网站 | 端口: {port} | 由 AI 助手创建</p>
            <p style="margin-top: 5px; font-size: 0.8rem;">现代化响应式设计 • 智能端口管理 • 用户友好界面</p>
        </div>
    </div>
    
    <script>
        // 更新当前时间
        function updateTime() {{
            const now = new Date();
            const options = {{
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false
            }};
            const timeString = now.toLocaleString('zh-CN', options);
            document.getElementById('current-time').textContent = timeString;
        }}
        
        // 联系功能
        function showContact() {{
            const contactInfo = `联系{target_person}

📧 邮箱: contact@{target_person.lower()}.com
🌐 网站: http://localhost:{port}
📱 状态: 在线
⏰ 更新: ${{new Date().toLocaleString('zh-CN')}}

感谢您的关注！这是一个现代化的个人展示网站。`;
            
            alert(contactInfo);
        }}
        
        // 服务器信息
        function showServer() {{
            const serverInfo = `服务器详细信息

🖥️ 端口: {port}
📍 地址: http://localhost:{port}
⚡ 状态: 运行中
🔧 启动: bash start_server.sh
📁 目录: 当前工作目录
🛡️ 安全: 自动端口冲突处理

技术栈:
• HTML5 + CSS3 + JavaScript
• Python HTTP Server
• 响应式设计
• 智能端口管理

特色功能:
• 现代渐变色UI设计
• 实时时间显示
• 移动设备适配
• 用户友好交互`;
            
            alert(serverInfo);
        }}
        
        // 更多信息
        function showInfo() {{
            const moreInfo = `关于这个网站

✨ 特色功能:
• 现代化响应式设计
• 智能端口冲突处理  
• 实时信息更新
• 优雅的视觉效果
• 用户友好的交互体验

🛠️ 技术特点:
• 纯前端实现，无需数据库
• 使用 CSS3 动画和渐变
• 响应式布局，支持移动设备
• 智能的 Shell 脚本部署
• Python 内置服务器

🚀 使用说明:
1. 运行 bash start_server.sh 启动
2. 访问 http://localhost:{port}
3. 享受现代化的个人网站体验

© 2025 由 AI 助手创建 | 遵循现代 Web 标准`;
            
            alert(moreInfo);
        }}
        
        // 初始化
        updateTime();
        setInterval(updateTime, 1000);
        
        // 页面加载完成效果
        window.addEventListener('load', function() {{
            console.log('🎉 {target_person}个人网站已加载完成！');
            console.log('🚀 服务器运行在端口 {port}');
            console.log('🌐 访问地址: http://localhost:{port}');
            
            // 显示加载完成提示
            setTimeout(() => {{
                if (confirm('🎉 网站加载完成！\\n\\n是否查看使用说明？')) {{
                    showInfo();
                }}
            }}, 2000);
        }});
        
        // 键盘快捷键
        document.addEventListener('keydown', function(e) {{
            if (e.ctrlKey && e.key === 'h') {{
                e.preventDefault();
                showInfo();
            }}
            if (e.ctrlKey && e.key === 's') {{
                e.preventDefault();
                showServer();
            }}
            if (e.ctrlKey && e.key === 'c') {{
                e.preventDefault();
                showContact();
            }}
        }});
    </script>
</body>
</html>""",
                    "description": f"{target_person}个人信息展示页面，现代化设计"
                },
                "README.md": {
                    "content": f"""# {target_person}个人网站

这是一个专门为{target_person}创建的个人信息展示网站，具有现代化设计和智能端口管理功能。

## 🌟 功能特点

- 📱 **响应式设计**：完美支持移动设备和桌面端
- 🎨 **现代化UI**：使用渐变色和CSS3动画
- ⚡ **快速加载**：纯静态网站，无需数据库
- 🔧 **智能端口管理**：自动处理端口冲突
- ⏰ **实时更新**：动态时间显示和状态监控
- 🛡️ **安全可靠**：包含完善的错误处理

## 🚀 快速启动

### 方法1：使用启动脚本（推荐）
```bash
# 赋予执行权限
chmod +x start_server.sh

# 启动网站
bash start_server.sh
```

### 方法2：手动启动
```bash
# 检查端口占用
lsof -Pi :{port} -sTCP:LISTEN

# 如果端口被占用，终止进程
lsof -ti:{port} | xargs kill -9

# 启动服务器
python3 -m http.server {port}
```

## 🌐 访问网站

启动后，在浏览器中访问：
- 本地访问：http://localhost:{port}
- 网络访问：http://[你的IP]:{port}

## 📁 文件结构

```
{target_person}个人网站/
├── index.html          # 主页面（现代化响应式设计）
├── start_server.sh     # 启动脚本（智能端口管理）
└── README.md          # 说明文档
```

## 🎯 设计特色

### 🎨 视觉设计
- **渐变背景**：使用现代渐变色营造科技感
- **玻璃效果**：毛玻璃背景模糊效果
- **动画交互**：平滑的动画和悬停效果
- **响应式布局**：适配各种设备尺寸

### 🔧 技术特点
- **智能脚本**：自动检测和处理端口冲突
- **兼容性好**：支持Python2和Python3
- **用户友好**：详细的提示信息和错误处理
- **键盘快捷键**：Ctrl+H（帮助）、Ctrl+S（服务器）、Ctrl+C（联系）

### 💡 交互功能
- **实时时间**：每秒更新当前时间
- **状态指示**：动态状态指示器
- **信息弹窗**：详细的功能说明
- **快捷操作**：一键查看各类信息

## 🛠️ 技术栈

- **前端**: HTML5 + CSS3 + JavaScript ES6+
- **服务器**: Python HTTP Server
- **脚本**: Bash Shell（跨平台兼容）
- **设计**: 现代响应式设计 + CSS3动画

## 🔧 自定义

### 修改个人信息
编辑 `index.html` 文件中的相关内容：

```html
<!-- 修改姓名 -->
<h1 class="name">{target_person}</h1>

<!-- 修改联系方式 -->
<span class="info-value">contact@{target_person.lower()}.com</span>

<!-- 修改端口（如需要） -->
<!-- 同时需要修改 start_server.sh 中的 PORT 变量 -->
```

### 修改端口
1. 编辑 `start_server.sh`：将 `PORT={port}` 改为您需要的端口
2. 编辑 `index.html`：将所有 `{port}` 替换为新端口号

### 自定义样式
在 `index.html` 的 `<style>` 标签中修改CSS：
- 修改 `background: linear-gradient(...)` 更换背景色
- 修改 `.container` 样式调整布局
- 修改 `.contact-btn` 样式调整按钮外观

## 🚨 使用说明

### 系统要求
- Python 2.7+ 或 Python 3.x
- Linux、macOS 或 Windows（需要Git Bash或WSL）
- 端口 {port} 可用（脚本会自动处理冲突）

### 启动注意事项
1. **权限问题**：某些系统可能需要 sudo 权限
2. **防火墙**：确保防火墙允许端口 {port}
3. **端口冲突**：脚本会自动处理，无需手动干预
4. **网络访问**：局域网访问需要使用实际IP地址

### 故障排除
- **Python未找到**：安装Python或检查PATH环境变量
- **端口被占用**：脚本会自动处理，如仍有问题请手动检查
- **权限不足**：使用 `sudo bash start_server.sh`
- **无法访问**：检查防火墙设置和网络连接

## 📞 联系方式

如有问题，请联系：
- 📧 邮箱：contact@{target_person.lower()}.com
- 🌐 网站：http://localhost:{port}

## 📄 更新日志

### v1.0.0 (2025-07-11)
- ✅ 初始版本发布
- ✅ 现代化响应式设计
- ✅ 智能端口冲突处理
- ✅ 实时时间显示
- ✅ 完整的交互功能
- ✅ 跨平台兼容性

---

© 2025 {target_person}个人网站 | 使用端口 {port} | 由 AI 助手创建

**技术支持**: 现代Web标准 • 响应式设计 • 智能脚本管理
""",
                    "description": "完整的项目文档和使用说明"
                }
            },
            "deployment": {
                "type": "script",
                "commands": ["bash start_server.sh"],
                "entry_point": "start_server.sh",
                "port": port
            }
        }