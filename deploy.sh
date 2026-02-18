#!/bin/bash
# deploy.sh — skynetCheapBuy 部署脚本
# 用法:
#   bash deploy.sh              # 完整部署（拉代码 + 安装依赖 + 重启服务）
#   bash deploy.sh --restart    # 仅重启服务
#   bash deploy.sh --pull       # 仅拉代码
#   bash deploy.sh --status     # 查看服务状态

set -e

# ═══════════════════════════════════════════
# 配置区 — 按实际环境修改
# ═══════════════════════════════════════════
PROJECT_NAME="skynetCheapBuy"
PROJECT_DIR="/root/dylan/skynetCheapBuy/skynetCheapBuy"
FRONTEND_DIR="/root/dylan/skynetCheapBuy/skynetFronted"
VENV_DIR="${PROJECT_DIR}/.venv"
LOG_DIR="${PROJECT_DIR}/logs"
PID_FILE="${PROJECT_DIR}/server.pid"

# 服务端口
BACKEND_PORT=17432
BACKEND_HOST="0.0.0.0"

# Git 配置
GIT_BRANCH="main"
BACKEND_REPO="https://github.com/dylanyunlon/skynetCheapBuy.git"
FRONTEND_REPO="https://github.com/dylanyunlon/skynetFronted.git"

# Uvicorn 配置
WORKERS=2
LOG_LEVEL="info"

# ═══════════════════════════════════════════
# 颜色输出
# ═══════════════════════════════════════════
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "\n${BLUE}═══ $1 ═══${NC}"; }

# ═══════════════════════════════════════════
# 函数定义
# ═══════════════════════════════════════════

check_env() {
    log_step "检查环境"

    if [ ! -f "${PROJECT_DIR}/.env" ]; then
        log_error ".env 文件不存在！"
        log_warn "请先创建 .env 文件: cp .env.example .env && vim .env"
        exit 1
    fi

    # 检查必要的环境变量
    source "${PROJECT_DIR}/.env" 2>/dev/null || true
    if [ -z "$DATABASE_URL" ]; then
        log_warn "DATABASE_URL 未设置"
    fi
    if [ -z "$SECRET_KEY" ]; then
        log_warn "SECRET_KEY 未设置"
    fi

    # 确保目录存在
    mkdir -p "${LOG_DIR}"
    mkdir -p "${PROJECT_DIR}/workspace"
    mkdir -p "${PROJECT_DIR}/uploads"
    mkdir -p "${PROJECT_DIR}/output/projects"

    log_info "环境检查完成"
}

pull_code() {
    log_step "拉取代码"

    # 后端
    if [ -d "${PROJECT_DIR}/.git" ]; then
        cd "${PROJECT_DIR}"
        log_info "拉取后端代码..."
        git stash 2>/dev/null || true
        git pull origin ${GIT_BRANCH} 2>&1
        log_info "后端代码更新完成"
    else
        log_warn "后端目录不是 git 仓库，跳过 pull"
    fi

    # 前端
    if [ -d "${FRONTEND_DIR}/.git" ]; then
        cd "${FRONTEND_DIR}"
        log_info "拉取前端代码..."
        git stash 2>/dev/null || true
        git pull origin ${GIT_BRANCH} 2>&1
        log_info "前端代码更新完成"
    else
        log_warn "前端目录不是 git 仓库，跳过 pull"
    fi
}

install_deps() {
    log_step "安装依赖"
    cd "${PROJECT_DIR}"

    # Python 依赖
    if [ -f "requirements.txt" ]; then
        if [ -d "${VENV_DIR}" ]; then
            log_info "使用虚拟环境: ${VENV_DIR}"
            source "${VENV_DIR}/bin/activate"
        else
            log_info "创建虚拟环境..."
            python3 -m venv "${VENV_DIR}"
            source "${VENV_DIR}/bin/activate"
        fi
        log_info "安装 Python 依赖..."
        pip install -r requirements.txt -q 2>&1 | tail -5
        log_info "Python 依赖安装完成"
    fi
}

stop_service() {
    log_step "停止服务"

    # 方法 1: 通过 PID 文件
    if [ -f "${PID_FILE}" ]; then
        PID=$(cat "${PID_FILE}")
        if kill -0 "$PID" 2>/dev/null; then
            log_info "停止进程 PID=${PID}..."
            kill "$PID" 2>/dev/null || true
            sleep 2
            # 如果还没停，强制杀
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID" 2>/dev/null || true
            fi
            log_info "服务已停止"
        fi
        rm -f "${PID_FILE}"
    fi

    # 方法 2: 通过端口查找
    PIDS=$(lsof -ti:${BACKEND_PORT} 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        log_warn "发现占用端口 ${BACKEND_PORT} 的进程: ${PIDS}"
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
        sleep 1
        log_info "已清理端口占用"
    fi
}

start_service() {
    log_step "启动服务"
    cd "${PROJECT_DIR}"

    # 激活虚拟环境
    if [ -d "${VENV_DIR}" ]; then
        source "${VENV_DIR}/bin/activate"
    fi

    # 设置 PYTHONPATH
    export PYTHONPATH="${PROJECT_DIR}:${PYTHONPATH}"

    # 启动 Uvicorn
    log_info "启动 ${PROJECT_NAME} 于 ${BACKEND_HOST}:${BACKEND_PORT}..."
    nohup uvicorn app.main:app \
        --host ${BACKEND_HOST} \
        --port ${BACKEND_PORT} \
        --workers ${WORKERS} \
        --log-level ${LOG_LEVEL} \
        --access-log \
        --log-config /dev/null \
        >> "${LOG_DIR}/app.log" 2>> "${LOG_DIR}/error.log" &

    echo $! > "${PID_FILE}"
    sleep 2

    # 验证启动
    if kill -0 "$(cat ${PID_FILE})" 2>/dev/null; then
        log_info "✅ 服务启动成功! PID=$(cat ${PID_FILE})"
        log_info "   后端: https://baloonet.tech:${BACKEND_PORT}"
        log_info "   文档: https://baloonet.tech:${BACKEND_PORT}/docs"
        log_info "   日志: tail -f ${LOG_DIR}/app.log"
    else
        log_error "服务启动失败！检查日志: ${LOG_DIR}/error.log"
        tail -20 "${LOG_DIR}/error.log" 2>/dev/null
        exit 1
    fi
}

build_frontend() {
    log_step "构建前端"

    if [ ! -d "${FRONTEND_DIR}" ]; then
        log_warn "前端目录不存在: ${FRONTEND_DIR}，跳过"
        return
    fi

    cd "${FRONTEND_DIR}"

    # 检查 node_modules
    if [ ! -d "node_modules" ]; then
        log_info "安装前端依赖..."
        npm install 2>&1 | tail -3
    fi

    log_info "构建前端..."
    npm run build 2>&1 | tail -5
    log_info "前端构建完成"
}

show_status() {
    log_step "服务状态"

    # 检查进程
    if [ -f "${PID_FILE}" ]; then
        PID=$(cat "${PID_FILE}")
        if kill -0 "$PID" 2>/dev/null; then
            log_info "✅ 后端运行中 PID=${PID}"
            # 显示内存和CPU
            ps -p "$PID" -o pid,ppid,%cpu,%mem,etime,cmd --no-headers 2>/dev/null || true
        else
            log_warn "PID 文件存在但进程未运行"
        fi
    else
        log_warn "没有 PID 文件"
    fi

    # 检查端口
    LISTEN=$(ss -tlnp 2>/dev/null | grep ":${BACKEND_PORT}" || true)
    if [ -n "$LISTEN" ]; then
        log_info "端口 ${BACKEND_PORT} 已监听"
    else
        log_warn "端口 ${BACKEND_PORT} 未监听"
    fi

    # 检查 health
    HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${BACKEND_PORT}/health" 2>/dev/null || echo "000")
    if [ "$HEALTH" = "200" ]; then
        log_info "✅ Health check: OK"
    else
        log_warn "Health check: HTTP ${HEALTH}"
    fi

    # 最近日志
    echo ""
    log_info "最近日志 (最后 5 行):"
    tail -5 "${LOG_DIR}/app.log" 2>/dev/null || echo "  (无日志)"
}

# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════

case "${1:-}" in
    --restart)
        stop_service
        start_service
        show_status
        ;;
    --pull)
        pull_code
        ;;
    --stop)
        stop_service
        log_info "服务已停止"
        ;;
    --status)
        show_status
        ;;
    --build-frontend)
        pull_code
        build_frontend
        ;;
    --help|-h)
        echo "用法: bash deploy.sh [选项]"
        echo ""
        echo "选项:"
        echo "  (无参数)         完整部署: 拉代码 + 安装依赖 + 重启"
        echo "  --restart        仅重启服务"
        echo "  --pull           仅拉代码"
        echo "  --stop           停止服务"
        echo "  --status         查看状态"
        echo "  --build-frontend 拉代码 + 构建前端"
        echo "  --help           显示帮助"
        ;;
    *)
        # 完整部署流程
        log_step "开始完整部署 ${PROJECT_NAME}"
        echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""

        check_env
        pull_code
        install_deps
        stop_service
        start_service
        show_status

        echo ""
        log_step "部署完成 🎉"
        ;;
esac
