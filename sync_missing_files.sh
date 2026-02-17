#!/bin/bash
#===============================================================================
# CheapBuy → skynetCheapBuy 缺失文件同步脚本
#
# 分析结果:
#   原始 CheapBuy: 130 个文件
#   skynetCheapBuy: 60 个文件 (已迁移 59 + 新增 1)
#   缺失: 71 个文件
#
# 使用方式:
#   bash sync_missing_files.sh           # 默认全量同步
#   bash sync_missing_files.sh critical  # 只同步关键文件 (33个)
#   bash sync_missing_files.sh all       # 全量同步 (71个)
#   bash sync_missing_files.sh dry       # 预览模式，不实际复制
#===============================================================================

SRC="/root/dylan/CheapBuy"
DEST="/root/dylan/skynetCheapBuy/skynetCheapBuy"
MODE="${1:-all}"

echo "============================================="
echo "CheapBuy → skynetCheapBuy 缺失文件同步"
echo "源: $SRC"
echo "目标: $DEST"
echo "模式: $MODE"
echo "============================================="

# 检查源目录
if [ ! -d "$SRC/app" ]; then
    echo "❌ 错误: 源目录 $SRC/app 不存在!"
    exit 1
fi

COPIED=0
FAILED=0
SKIPPED=0

copy_file() {
    local file="$1"
    local src_path="$SRC/$file"
    local dest_path="$DEST/$file"
    local dest_dir=$(dirname "$dest_path")

    if [ ! -f "$src_path" ]; then
        echo "   ⚠️  源文件不存在: $src_path"
        ((SKIPPED++))
        return
    fi

    if [ "$MODE" = "dry" ]; then
        echo "   [预览] $file"
        ((COPIED++))
        return
    fi

    mkdir -p "$dest_dir"
    if cp "$src_path" "$dest_path" 2>/dev/null; then
        echo "   ✅ $file"
        ((COPIED++))
    else
        echo "   ❌ 复制失败: $file"
        ((FAILED++))
    fi
}

#-----------------------------------------------
# 关键文件 (33 个) — Agentic Loop 改造必需
#-----------------------------------------------
sync_critical() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🔴 关键文件 (Agentic Loop 改造必需) — 33 个"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # API 层 — v1 接口 (chat/code/file 是核心交互)
    copy_file "app/api/__init__.py"
    copy_file "app/api/auth.py"
    copy_file "app/api/chat.py"
    copy_file "app/api/chat_v2.py"
    copy_file "app/api/code.py"
    copy_file "app/api/code_management.py"
    copy_file "app/api/conversations.py"
    copy_file "app/api/enhanced_chat.py"
    copy_file "app/api/enhanced_code.py"
    copy_file "app/api/files.py"
    copy_file "app/api/websocket.py"

    # API v2 补充
    copy_file "app/api/v2/benchmark.py"
    copy_file "app/api/v2/benchmark_tasks.py"
    copy_file "app/api/v2/debug.py"

    # WebSocket (终端实时交互)
    copy_file "app/api/websocket_handlers/__init__.py"
    copy_file "app/api/websocket_handlers/terminal_ws.py"

    # Core — 认证/限流/定时 (基础设施)
    copy_file "app/core/auth.py"
    copy_file "app/core/cron_manager.py"
    copy_file "app/core/rate_limit.py"

    # Core DB (数据库连接池/迁移/优化)
    copy_file "app/core/db/connection_pool.py"
    copy_file "app/core/db/migration_manager.py"
    copy_file "app/core/db/query_optimizer.py"

    # Core Repo (代码仓库分析 — Agentic 需要理解项目结构)
    copy_file "app/core/repo/__init__.py"
    copy_file "app/core/repo/analyzer.py"
    copy_file "app/core/repo/code_utils.py"
    copy_file "app/core/repo/importance_analyzer.py"
    copy_file "app/core/repo/summary.py"
    copy_file "app/core/repo/tree_builder.py"

    # Core Web Search (搜索能力)
    copy_file "app/core/web_search/__init__.py"

    # DB (Redis + 初始化)
    copy_file "app/db/init_db.py"
    copy_file "app/db/redis.py"

    # Services
    copy_file "app/services/user_service.py"

    # Utils (文件处理 + Markdown)
    copy_file "app/utils/__init__.py"
    copy_file "app/utils/file_handler.py"
    copy_file "app/utils/markdown.py"
}

#-----------------------------------------------
# 重要文件 (26 个) — 功能完整性
#-----------------------------------------------
sync_important() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🟡 重要文件 (功能完整性) — 26 个"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # CLI
    copy_file "app/cli/client.py"

    # Benchmark 系统 (完整)
    copy_file "app/core/benchmark/__init__.py"
    copy_file "app/core/benchmark/adapters.py"
    copy_file "app/core/benchmark/code_extractor.py"
    copy_file "app/core/benchmark/evaluators.py"
    copy_file "app/core/benchmark/executor.py"
    copy_file "app/core/benchmark/loaders.py"
    copy_file "app/core/benchmark/session.py"
    copy_file "app/core/benchmark/swe_bench_evaluator.py"

    # __init__ 文件
    copy_file "app/core/chat/__init__.py"
    copy_file "app/core/intent/__init__.py"

    # Monitoring
    copy_file "app/core/monitoring/health_check.py"
    copy_file "app/core/monitoring/metrics.py"
    copy_file "app/monitoring/__init__.py"

    # Models 补充
    copy_file "app/models/__init__.py"
    copy_file "app/models/config.py"
    copy_file "app/models/file.py"

    # Schemas 补充
    copy_file "app/schemas/__init__.py"
    copy_file "app/schemas/auth.py"
    copy_file "app/schemas/code_management.py"
    copy_file "app/schemas/file.py"
    copy_file "app/schemas/models.py"
    copy_file "app/schemas/user.py"

    # Scripts
    copy_file "app/scripts/cleanup_code_tables.py"
    copy_file "app/scripts/detect_database_state.py"
    copy_file "app/scripts/manage_db.py"
    copy_file "app/scripts/migrate_code_tables.py"
    copy_file "app/scripts/migrate_config.py"

    # Services
    copy_file "app/services/__init__.py"
}

#-----------------------------------------------
# 可选文件 (12 个) — 低优先级
#-----------------------------------------------
sync_optional() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🟢 可选文件 (低优先级) — 12 个"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    copy_file "README.md"
    copy_file "app/api/models.py"
    copy_file "app/api/users.py"
    copy_file "app/app.config.py"
    copy_file "app/core/app.core.ai_engine.py"
    copy_file "app/models/app.models.user.py"
    copy_file "app/utils/i18n.py"
}

#-----------------------------------------------
# 执行同步
#-----------------------------------------------
case "$MODE" in
    critical)
        sync_critical
        ;;
    important)
        sync_critical
        sync_important
        ;;
    all|"")
        sync_critical
        sync_important
        sync_optional
        ;;
    dry)
        echo "(预览模式 — 不实际复制文件)"
        sync_critical
        sync_important
        sync_optional
        ;;
    *)
        echo "用法: bash sync_missing_files.sh [critical|important|all|dry]"
        exit 1
        ;;
esac

#-----------------------------------------------
# 汇总
#-----------------------------------------------
echo ""
echo "============================================="
echo "同步完成!"
echo "============================================="
echo "  ✅ 成功复制: $COPIED"
echo "  ❌ 复制失败: $FAILED"
echo "  ⚠️  源不存在: $SKIPPED"
echo "============================================="

if [ "$MODE" != "dry" ]; then
    echo ""
    echo "下一步建议:"
    echo "  1. cd $DEST"
    echo "  2. git add -A"
    echo "  3. git status   # 检查新增文件"
    echo "  4. git commit -m 'sync: 从 CheapBuy 同步 ${COPIED} 个缺失文件'"
    echo "  5. git push"
fi
