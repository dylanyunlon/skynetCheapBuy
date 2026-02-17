#!/bin/bash
# ============================================================================
# 收集 CheapBuy 后端关键文件到 skynetCheapBuy 仓库
# 用于 Agentic Loop 改造分析
# ============================================================================

set -e

# 源目录和目标目录
SRC="/root/dylan/CheapBuy"
DEST="/root/dylan/skynetCheapBuy/skynetCheapBuy"

echo "📦 开始收集文件..."
echo "   源: $SRC"
echo "   目标: $DEST"

# ============================================================================
# 第一优先级：AI 调用链核心文件（必须看）
# ============================================================================

echo ""
echo "🔴 [第一优先级] AI 调用链核心"

# 1. 旧的 AI 引擎（和 app/core/ai/engine.py 是两套）
copy_file() {
    local src_file="$SRC/$1"
    local dest_file="$DEST/$1"
    if [ -f "$src_file" ]; then
        mkdir -p "$(dirname "$dest_file")"
        cp "$src_file" "$dest_file"
        echo "   ✅ $1"
    else
        echo "   ❌ 不存在: $1"
    fi
}

# AI 引擎（两个版本都要）
copy_file "app/core/ai_engine.py"
copy_file "app/core/ai/engine.py"
copy_file "app/core/ai/plugin_system.py"
copy_file "app/core/ai/prompt_engine.py"
copy_file "app/core/ai/system_prompts.py"

# Provider 插件（实际调 API 的代码）
copy_file "app/plugins/ai_providers/doubao.py"
copy_file "app/plugins/ai_providers/openai_plugin.py"

# 配置
copy_file "app/config.py"
copy_file "config/providers/doubao.yaml"
copy_file "config/models/register.yaml"
copy_file "config/claude_code.yaml"

# ============================================================================
# 第二优先级：代码提取和执行（当前方式）
# ============================================================================

echo ""
echo "🟠 [第二优先级] 代码提取 & 执行"

copy_file "app/core/code_extractor.py"
copy_file "app/core/script_executor.py"
copy_file "app/services/enhanced_code_service.py"
copy_file "app/services/ai_code_service.py"
copy_file "app/services/ai_service.py"

# ============================================================================
# 第三优先级：Agent 和 Chat API 层
# ============================================================================

echo ""
echo "🟡 [第三优先级] API & Agent 层"

copy_file "app/api/v2/agent.py"
copy_file "app/api/v2/chat.py"
copy_file "app/api/v2/vibe.py"
copy_file "app/api/v2/workspace.py"
copy_file "app/api/v2/terminal.py"
copy_file "app/api/v2/__init__.py"

copy_file "app/core/agents/code_agent.py"
copy_file "app/core/chat/router.py"
copy_file "app/core/intent/engine.py"

# ============================================================================
# 第四优先级：数据模型 & Schema
# ============================================================================

echo ""
echo "🟢 [第四优先级] 模型 & Schema"

copy_file "app/schemas/v2/agent.py"
copy_file "app/schemas/v2/chat.py"
copy_file "app/schemas/v2/execution.py"
copy_file "app/schemas/v2/workspace.py"
copy_file "app/schemas/v2/__init__.py"
copy_file "app/schemas/chat.py"
copy_file "app/schemas/code.py"

copy_file "app/models/workspace.py"
copy_file "app/models/chat.py"
copy_file "app/models/code.py"
copy_file "app/models/user.py"

# ============================================================================
# 第五优先级：服务层 & 基础设施
# ============================================================================

echo ""
echo "🔵 [第五优先级] 服务层 & 基础设施"

copy_file "app/services/chat_service.py"
copy_file "app/services/code_service.py"
copy_file "app/services/enhanced_chat_service.py"
copy_file "app/services/project_service.py"
copy_file "app/services/vibe_project_service.py"
copy_file "app/services/bash_script_vibe_service.py"
copy_file "app/services/file_service.py"

copy_file "app/dependencies.py"
copy_file "app/main.py"
copy_file "app/__init__.py"
copy_file "app/core/__init__.py"
copy_file "app/core/config_manager.py"
copy_file "app/core/cache/cache_manager.py"
copy_file "app/core/session.py"
copy_file "app/core/security.py"

copy_file "app/db/base.py"
copy_file "app/db/session.py"
copy_file "app/db/__init__.py"

# Workspace & Terminal & Vibe
copy_file "app/core/vibe/app.core.vibeprompt_orchestrator.py"
copy_file "app/core/terminal/pty_manager.py"
copy_file "app/core/preview/preview_manager.py"

# ============================================================================
# 第六优先级：已有的 agentic loop 原型 & 测试
# ============================================================================

echo ""
echo "🟣 [第六优先级] Agentic Loop 原型 & 参考文件"

copy_file "test_agentic_loop.py"
copy_file "claude_code.py"
copy_file "requirements.txt"

# ============================================================================
# 项目结构文件
# ============================================================================

echo ""
echo "📁 生成项目结构..."

cd "$SRC"
tree -I "__pycache__|workspace|node_modules|.git|venv|.venv" --charset=ascii > "$DEST/TREE_CHEAPBUY.txt" 2>/dev/null || \
    find . -type f -not -path '*/__pycache__/*' -not -path '*/.git/*' -not -path '*/workspace/*' | sort > "$DEST/TREE_CHEAPBUY.txt"
echo "   ✅ TREE_CHEAPBUY.txt"

# ============================================================================
# 统计 & 推送到 GitHub
# ============================================================================

echo ""
echo "📊 统计:"
cd "$DEST"
file_count=$(find . -type f -not -path '*/.git/*' -not -name 'README.md' | wc -l)
echo "   共复制 $file_count 个文件"
echo ""

# 生成文件清单
echo "# skynetCheapBuy - Agentic Loop 改造项目" > "$DEST/FILE_INDEX.md"
echo "" >> "$DEST/FILE_INDEX.md"
echo "## 文件清单 ($(date '+%Y-%m-%d %H:%M'))" >> "$DEST/FILE_INDEX.md"
echo "" >> "$DEST/FILE_INDEX.md"
echo "### 🔴 第一优先级：AI 调用链核心" >> "$DEST/FILE_INDEX.md"
echo '```' >> "$DEST/FILE_INDEX.md"
echo "app/core/ai_engine.py          # 旧 AI 引擎" >> "$DEST/FILE_INDEX.md"
echo "app/core/ai/engine.py          # 新 AI 引擎（重构版）" >> "$DEST/FILE_INDEX.md"
echo "app/core/ai/plugin_system.py   # 插件系统" >> "$DEST/FILE_INDEX.md"
echo "app/plugins/ai_providers/      # Provider 实现（实际调 API）" >> "$DEST/FILE_INDEX.md"
echo "app/config.py                  # 配置（API KEY/BASE URL）" >> "$DEST/FILE_INDEX.md"
echo '```' >> "$DEST/FILE_INDEX.md"
echo "" >> "$DEST/FILE_INDEX.md"
echo "### 🟠 第二优先级：代码提取 & 执行" >> "$DEST/FILE_INDEX.md"
echo '```' >> "$DEST/FILE_INDEX.md"
echo "app/core/code_extractor.py     # 从 AI 回复中提取代码" >> "$DEST/FILE_INDEX.md"
echo "app/core/script_executor.py    # 执行提取的代码" >> "$DEST/FILE_INDEX.md"
echo "app/services/enhanced_code_service.py  # 增强代码服务" >> "$DEST/FILE_INDEX.md"
echo '```' >> "$DEST/FILE_INDEX.md"
echo "" >> "$DEST/FILE_INDEX.md"
echo "### 🟡 第三优先级：Agent & API" >> "$DEST/FILE_INDEX.md"
echo '```' >> "$DEST/FILE_INDEX.md"
echo "app/api/v2/agent.py            # Agent API 端点" >> "$DEST/FILE_INDEX.md"
echo "app/api/v2/chat.py             # Chat API 端点" >> "$DEST/FILE_INDEX.md"
echo "app/core/agents/code_agent.py  # Code Agent 实现" >> "$DEST/FILE_INDEX.md"
echo '```' >> "$DEST/FILE_INDEX.md"

echo "   ✅ FILE_INDEX.md"

# Git 提交 & 推送
echo ""
echo "🚀 推送到 GitHub..."
cd "$DEST"
git add -A
git commit -m "feat: 收集后端核心文件用于 Agentic Loop 改造分析

包含:
- AI 调用链: ai_engine, providers, config
- 代码提取/执行: code_extractor, script_executor
- Agent/API 层: v2/agent, v2/chat, code_agent
- 数据模型/Schema: workspace, chat, agent
- 服务层: enhanced_code_service, chat_service
- Agentic Loop 原型: test_agentic_loop.py
" || echo "   ⚠️  没有新文件需要提交"

git push origin main || git push origin master
echo ""
echo "✅ 完成！文件已推送到 https://github.com/dylanyunlon/skynetCheapBuy.git"
echo ""
echo "📋 下一步：将此仓库链接发给我，我会基于这些文件制定详细的 Agentic Loop 改造方案"
