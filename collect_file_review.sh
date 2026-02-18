#!/bin/bash
# collect_for_review.sh — 收集所有后端关键文件供 Claude 审查
# 用法: bash collect_for_review.sh
# 输出到: /root/dylan/review_files/

DEST="/root/dylan/review_files"
SRC="/root/dylan/skynetCheapBuy/skynetCheapBuy"

rm -rf "$DEST"
mkdir -p "$DEST/app/core/agents"
mkdir -p "$DEST/app/core/ai"
mkdir -p "$DEST/app/core/workspace"
mkdir -p "$DEST/app/core/web_search"
mkdir -p "$DEST/app/core/chat"
mkdir -p "$DEST/app/core/repo"
mkdir -p "$DEST/app/core/intent"
mkdir -p "$DEST/app/api/v2"
mkdir -p "$DEST/app/schemas/v2"
mkdir -p "$DEST/app/services"
mkdir -p "$DEST/app/cli"
mkdir -p "$DEST/config"

echo "=== 收集 Agentic Loop 核心文件 ==="

# 1. Agentic Loop 核心
cp -v "$SRC/app/core/agents/agentic_loop.py"        "$DEST/app/core/agents/" 2>/dev/null
cp -v "$SRC/app/core/agents/code_agent.py"           "$DEST/app/core/agents/" 2>/dev/null

# 2. AI Engine (调用模型)
cp -v "$SRC/app/core/ai_engine.py"                   "$DEST/app/core/" 2>/dev/null
cp -v "$SRC/app/core/ai/engine.py"                   "$DEST/app/core/ai/" 2>/dev/null
cp -v "$SRC/app/core/ai/prompt_engine.py"            "$DEST/app/core/ai/" 2>/dev/null
cp -v "$SRC/app/core/ai/system_prompts.py"           "$DEST/app/core/ai/" 2>/dev/null
cp -v "$SRC/app/core/ai/plugin_system.py"            "$DEST/app/core/ai/" 2>/dev/null

# 3. API 端点
cp -v "$SRC/app/api/v2/agent.py"                     "$DEST/app/api/v2/" 2>/dev/null
cp -v "$SRC/app/api/v2/chat.py"                      "$DEST/app/api/v2/" 2>/dev/null
cp -v "$SRC/app/api/v2/workspace.py"                 "$DEST/app/api/v2/" 2>/dev/null
cp -v "$SRC/app/api/v2/debug.py"                     "$DEST/app/api/v2/" 2>/dev/null

# 4. Schemas
cp -rv "$SRC/app/schemas/v2/"                        "$DEST/app/schemas/" 2>/dev/null
cp -v "$SRC/app/schemas/"*.py                        "$DEST/app/schemas/" 2>/dev/null

# 5. Services
cp -v "$SRC/app/services/"*.py                       "$DEST/app/services/" 2>/dev/null

# 6. Web Search
cp -v "$SRC/app/core/web_search/"*.py                "$DEST/app/core/web_search/" 2>/dev/null

# 7. Workspace
cp -v "$SRC/app/core/workspace/"*.py                 "$DEST/app/core/workspace/" 2>/dev/null

# 8. Chat
cp -v "$SRC/app/core/chat/"*.py                      "$DEST/app/core/chat/" 2>/dev/null

# 9. Config & main
cp -v "$SRC/app/main.py"                             "$DEST/app/" 2>/dev/null
cp -v "$SRC/app/config.py"                           "$DEST/app/" 2>/dev/null
cp -v "$SRC/app/dependencies.py"                     "$DEST/app/" 2>/dev/null
cp -v "$SRC/config/"*.yaml                           "$DEST/config/" 2>/dev/null
cp -v "$SRC/config/"*.py                             "$DEST/config/" 2>/dev/null
cp -rv "$SRC/config/models/"                         "$DEST/config/" 2>/dev/null
cp -rv "$SRC/config/providers/"                      "$DEST/config/" 2>/dev/null

# 10. CLI
cp -v "$SRC/app/cli/"*.py                            "$DEST/app/cli/" 2>/dev/null

# 11. 根目录文件
cp -v "$SRC/claude_code.py"                          "$DEST/" 2>/dev/null
cp -v "$SRC/test_agentic_loop.py"                    "$DEST/" 2>/dev/null
cp -v "$SRC/requirements.txt"                        "$DEST/" 2>/dev/null
cp -v "$SRC/.env"                                    "$DEST/" 2>/dev/null
cp -v "$SRC/TREE_CHEAPBUY.txt"                       "$DEST/" 2>/dev/null
cp -v "$SRC/FILE_INDEX.md"                           "$DEST/" 2>/dev/null

# 12. Repo 分析
cp -v "$SRC/app/core/repo/"*.py                      "$DEST/app/core/repo/" 2>/dev/null

# 13. Intent engine
cp -v "$SRC/app/core/intent/"*.py                    "$DEST/app/core/intent/" 2>/dev/null

echo ""
echo "=== 收集前端关键文件 ==="
FRONT="/root/dylan/skynetFronted"
mkdir -p "$DEST/frontend/src/components/Agentic"
mkdir -p "$DEST/frontend/src/hooks"
mkdir -p "$DEST/frontend/src/types"
mkdir -p "$DEST/frontend/src/services"

cp -v "$FRONT/src/components/Agentic/"*.tsx          "$DEST/frontend/src/components/Agentic/" 2>/dev/null
cp -v "$FRONT/src/hooks/useAgenticLoop.ts"           "$DEST/frontend/src/hooks/" 2>/dev/null
cp -v "$FRONT/src/types/agentic.ts"                  "$DEST/frontend/src/types/" 2>/dev/null
cp -v "$FRONT/src/services/"*.ts                     "$DEST/frontend/src/services/" 2>/dev/null
cp -v "$FRONT/package.json"                          "$DEST/frontend/" 2>/dev/null

echo ""
echo "=== 完成 ==="
echo "所有文件已收集到: $DEST"
echo ""
echo "文件统计:"
find "$DEST" -type f | wc -l
echo "总大小:"
du -sh "$DEST"
echo ""
echo "目录结构:"
find "$DEST" -type f | sort