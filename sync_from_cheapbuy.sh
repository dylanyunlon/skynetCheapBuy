#!/bin/bash
# sync_from_cheapbuy.sh
# 从旧项目 /root/dylan/CheapBuy 同步配置文件到新项目 /root/dylan/skynetCheapBuy/skynetCheapBuy
#
# ⚠️  运行前请确认路径正确！
# 用法: bash sync_from_cheapbuy.sh [--dry-run]

set -e

OLD_DIR="/root/dylan/CheapBuy"
NEW_DIR="/root/dylan/skynetCheapBuy/skynetCheapBuy"
DRY_RUN=false

if [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
    echo "🔍 DRY RUN 模式 — 只显示操作，不实际执行"
fi

echo "=========================================="
echo " 从旧项目同步配置到新仓库"
echo "=========================================="
echo "源: ${OLD_DIR}"
echo "目标: ${NEW_DIR}"
echo ""

# 检查源目录
if [ ! -d "$OLD_DIR" ]; then
    echo "❌ 源目录不存在: $OLD_DIR"
    exit 1
fi
if [ ! -d "$NEW_DIR" ]; then
    echo "❌ 目标目录不存在: $NEW_DIR"
    echo "   请检查路径是否正确"
    exit 1
fi

sync_file() {
    local src="$1"
    local dst="$2"
    local desc="$3"

    if [ -f "$OLD_DIR/$src" ]; then
        if [ -f "$NEW_DIR/$dst" ]; then
            echo "  ⏭️  跳过 $dst (已存在)"
        else
            echo "  📦 同步 $src → $dst  ($desc)"
            if [ "$DRY_RUN" = false ]; then
                mkdir -p "$(dirname "$NEW_DIR/$dst")"
                cp "$OLD_DIR/$src" "$NEW_DIR/$dst"
            fi
        fi
    else
        echo "  ⚠️  源文件不存在: $src"
    fi
}

sync_file_force() {
    # 强制覆盖（用于需要更新的文件）
    local src="$1"
    local dst="$2"
    local desc="$3"

    if [ -f "$OLD_DIR/$src" ]; then
        echo "  📦 同步 $src → $dst  ($desc)"
        if [ "$DRY_RUN" = false ]; then
            mkdir -p "$(dirname "$NEW_DIR/$dst")"
            cp "$OLD_DIR/$src" "$NEW_DIR/$dst"
        fi
    else
        echo "  ⚠️  源文件不存在: $src"
    fi
}

echo "📋 1/5 — 环境配置文件"
sync_file ".env" ".env" "环境变量（API keys, DB URL 等）"
sync_file ".env.example" ".env.example" "环境变量模板"

echo ""
echo "📋 2/5 — 部署和运维文件"
sync_file "deploy.sh" "deploy.sh.old_reference" "旧部署脚本（仅作参考，不直接使用）"
sync_file "Dockerfile" "Dockerfile" "Docker 构建文件"
sync_file "docker-compose.yml" "docker-compose.yml" "Docker Compose"
sync_file "Makefile" "Makefile" "Makefile"
sync_file "gunicorn.conf.py" "gunicorn.conf.py" "Gunicorn 配置"
sync_file "alembic.ini" "alembic.ini" "Alembic 数据库迁移配置"

echo ""
echo "📋 3/5 — SSL 和 Nginx"
sync_file "nginx.conf" "nginx.conf" "Nginx 配置"
sync_file "fix_certbot_ssl.sh" "fix_certbot_ssl.sh" "SSL 证书修复脚本"
sync_file "setop_letsencrypt.sh" "setop_letsencrypt.sh" "Let's Encrypt 安装"

echo ""
echo "📋 4/5 — 数据库迁移"
if [ -d "$OLD_DIR/alembic" ]; then
    echo "  📦 同步 alembic/ 目录"
    if [ "$DRY_RUN" = false ]; then
        if [ ! -d "$NEW_DIR/alembic" ]; then
            cp -r "$OLD_DIR/alembic" "$NEW_DIR/alembic"
        else
            echo "  ⏭️  alembic/ 已存在，跳过"
        fi
    fi
else
    echo "  ⚠️  旧项目没有 alembic/ 目录"
fi

echo ""
echo "📋 5/5 — 日志和数据目录结构"
if [ "$DRY_RUN" = false ]; then
    mkdir -p "$NEW_DIR/logs"
    mkdir -p "$NEW_DIR/workspace"
    mkdir -p "$NEW_DIR/uploads"
    mkdir -p "$NEW_DIR/output/projects"
    mkdir -p "$NEW_DIR/data"
    echo "  ✅ 创建 logs/, workspace/, uploads/, output/, data/ 目录"
else
    echo "  将创建: logs/, workspace/, uploads/, output/, data/"
fi

echo ""
echo "=========================================="
echo "✅ 同步完成！"
echo ""
echo "⚠️  重要后续步骤:"
echo "  1. 检查 .env 文件中的路径是否需要更新"
echo "     特别是 DATABASE_URL, WORKSPACE_PATH 等"
echo "  2. 运行: cd $NEW_DIR && bash deploy.sh"
echo "  3. 如果使用 alembic，更新 alembic.ini 中的 sqlalchemy.url"
echo "=========================================="
