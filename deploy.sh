#!/bin/bash
# deploy.sh — skynetCheapBuy 完整部署脚本
# 包含: Docker/PostgreSQL/Redis 服务管理 + Nginx/SSL + Systemd + 前后端部署
#
# 用法:
#   bash deploy.sh              # 完整部署（首次 or 日常更新）
#   bash deploy.sh --restart    # 仅重启后端服务
#   bash deploy.sh --pull       # 仅拉代码
#   bash deploy.sh --local       # 部署本地代码（不拉取 git，保护本地修改）
#   bash deploy.sh --stop       # 停止后端服务
#   bash deploy.sh --status     # 查看所有服务状态
#   bash deploy.sh --build-frontend  # 构建前端
#   bash deploy.sh --fix-deps   # 修复 Python 依赖
#   bash deploy.sh --setup-ssl  # 仅配置 SSL
#   bash deploy.sh --logs       # 查看日志
#   bash deploy.sh --help       # 帮助

set -e

# ═══════════════════════════════════════════════════════════
# 配置区 — 按实际环境修改
# ═══════════════════════════════════════════════════════════
PROJECT_NAME="skynetCheapBuy"
PROJECT_DIR="/root/dylan/skynetCheapBuy/skynetCheapBuy"
FRONTEND_DIR="/root/dylan/skynetCheapBuy/skynetFronted"
VENV_DIR="${PROJECT_DIR}/.venv"
LOG_DIR="${PROJECT_DIR}/logs"
PID_FILE="${PROJECT_DIR}/server.pid"

# 网络配置
PUBLIC_IP="8.163.12.28"
DOMAIN="baloonet.tech"
APP_PORT=8000               # Uvicorn 内部端口
BACKEND_PORT=17432          # 对外服务端口 (Nginx 代理到 APP_PORT)
BACKEND_HOST="0.0.0.0"
EMAIL="dogechat@163.com"

# Git 配置
GIT_BRANCH="main"
BACKEND_REPO="https://github.com/dylanyunlon/skynetCheapBuy.git"
FRONTEND_REPO="https://github.com/dylanyunlon/skynetFronted.git"

# Uvicorn 配置
WORKERS=1                   # worker 数 (小内存服务器建议 1)
LOG_LEVEL="info"
PYTHON_VERSION="3.10"

# ═══════════════════════════════════════════════════════════
# 颜色输出
# ═══════════════════════════════════════════════════════════
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "\n${BLUE}═══ $1 ═══${NC}"; }

# ═══════════════════════════════════════════════════════════
# 1. 基础检查
# ═══════════════════════════════════════════════════════════

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要 root 权限运行"
        exit 1
    fi
}

check_project() {
    if [ ! -d "$PROJECT_DIR" ]; then
        log_error "项目目录不存在: $PROJECT_DIR"
        exit 1
    fi
    if [ ! -f "$PROJECT_DIR/app/main.py" ]; then
        log_error "未找到 app/main.py"
        exit 1
    fi
    log_info "项目目录检查通过"
}

check_env() {
    log_step "检查环境配置"

    if [ ! -f "${PROJECT_DIR}/.env" ]; then
        log_error ".env 文件不存在！"
        log_warn "请先创建: cp ${PROJECT_DIR}/env.example ${PROJECT_DIR}/.env && vim ${PROJECT_DIR}/.env"
        exit 1
    fi

    source "${PROJECT_DIR}/.env" 2>/dev/null || true
    [ -z "$DATABASE_URL" ] && log_warn "DATABASE_URL 未设置"
    [ -z "$SECRET_KEY" ]   && log_warn "SECRET_KEY 未设置"

    # 确保目录存在
    mkdir -p "${LOG_DIR}" "${PROJECT_DIR}/workspace" "${PROJECT_DIR}/uploads" "${PROJECT_DIR}/output/projects" "${PROJECT_DIR}/data"

    log_info "环境检查完成"
}

# ═══════════════════════════════════════════════════════════
# 2. Docker + PostgreSQL + Redis 服务管理
# ═══════════════════════════════════════════════════════════

start_docker() {
    log_step "检查 Docker"

    if ! command -v docker &>/dev/null; then
        log_warn "Docker 未安装，跳过容器管理"
        log_warn "如果 PostgreSQL/Redis 以系统服务方式运行则无影响"
        return 0
    fi

    if systemctl is-active --quiet docker; then
        log_info "Docker 已运行"
    else
        log_info "启动 Docker..."
        systemctl start docker
        systemctl enable docker
        sleep 3
        log_info "Docker 已启动"
    fi
}

start_postgresql() {
    log_step "检查 PostgreSQL"

    # 方法 1: 检查系统服务
    if systemctl is-active --quiet postgresql 2>/dev/null; then
        log_info "PostgreSQL 系统服务已运行"
        return 0
    fi

    # 方法 2: 检查 Docker 容器
    if command -v docker &>/dev/null; then
        PG_CONTAINERS=("postgres" "postgresql" "chatbot-postgres" "chatbot_postgres" "skynet-postgres")
        PG_CONTAINER=""

        for container in "${PG_CONTAINERS[@]}"; do
            if docker ps -a --format "{{.Names}}" | grep -q "^${container}$"; then
                PG_CONTAINER=$container
                break
            fi
        done

        if [ -n "$PG_CONTAINER" ]; then
            if docker ps --format "{{.Names}}" | grep -q "^${PG_CONTAINER}$"; then
                log_info "PostgreSQL 容器 '${PG_CONTAINER}' 已运行"
            else
                log_info "启动 PostgreSQL 容器 '${PG_CONTAINER}'..."
                docker start ${PG_CONTAINER}
                sleep 5
            fi

            # 等待就绪
            log_info "等待 PostgreSQL 就绪..."
            for i in {1..30}; do
                if docker exec ${PG_CONTAINER} pg_isready &>/dev/null; then
                    log_info "PostgreSQL 已就绪"
                    return 0
                fi
                sleep 1
            done
            log_error "PostgreSQL 启动超时"
            return 1
        fi
    fi

    # 方法 3: 尝试启动系统服务
    if systemctl list-unit-files | grep -q postgresql; then
        log_info "启动 PostgreSQL 系统服务..."
        systemctl start postgresql
        sleep 3
        if systemctl is-active --quiet postgresql; then
            log_info "PostgreSQL 已启动"
            return 0
        fi
    fi

    # 方法 4: 直接测试连接
    if pg_isready -h localhost -p 5432 &>/dev/null; then
        log_info "PostgreSQL 已在运行 (非 systemd/docker 管理)"
        return 0
    fi

    log_error "PostgreSQL 未运行且无法自动启动！"
    log_warn "请手动启动 PostgreSQL 或创建 Docker 容器:"
    echo "  docker run -d --name postgres \\"
    echo "    -e POSTGRES_PASSWORD=your_password \\"
    echo "    -e POSTGRES_DB=chatbot_db \\"
    echo "    -p 5432:5432 \\"
    echo "    -v postgres_data:/var/lib/postgresql/data \\"
    echo "    postgres:15"
    return 1
}

start_redis() {
    log_step "检查 Redis"

    # 方法 1: 系统服务
    if systemctl is-active --quiet redis-server 2>/dev/null || systemctl is-active --quiet redis 2>/dev/null; then
        log_info "Redis 系统服务已运行"
        return 0
    fi

    # 方法 2: Docker 容器
    if command -v docker &>/dev/null; then
        REDIS_CONTAINERS=("redis" "chatbot-redis" "chatbot_redis" "skynet-redis")
        REDIS_CONTAINER=""

        for container in "${REDIS_CONTAINERS[@]}"; do
            if docker ps -a --format "{{.Names}}" | grep -q "^${container}$"; then
                REDIS_CONTAINER=$container
                break
            fi
        done

        if [ -n "$REDIS_CONTAINER" ]; then
            if docker ps --format "{{.Names}}" | grep -q "^${REDIS_CONTAINER}$"; then
                log_info "Redis 容器 '${REDIS_CONTAINER}' 已运行"
            else
                log_info "启动 Redis 容器 '${REDIS_CONTAINER}'..."
                docker start ${REDIS_CONTAINER}
                sleep 3
            fi

            if docker exec ${REDIS_CONTAINER} redis-cli ping &>/dev/null; then
                log_info "Redis 连接成功"
                return 0
            fi
            log_error "Redis 连接失败"
            return 1
        fi
    fi

    # 方法 3: 尝试启动系统服务
    for svc in redis-server redis; do
        if systemctl list-unit-files | grep -q "^${svc}"; then
            log_info "启动 ${svc}..."
            systemctl start ${svc}
            sleep 2
            if systemctl is-active --quiet ${svc}; then
                log_info "Redis 已启动"
                return 0
            fi
        fi
    done

    # 方法 4: 直接测试连接
    if redis-cli ping &>/dev/null 2>&1; then
        log_info "Redis 已在运行"
        return 0
    fi

    log_error "Redis 未运行且无法自动启动！"
    log_warn "请手动启动或创建 Docker 容器:"
    echo "  docker run -d --name redis \\"
    echo "    -p 6379:6379 \\"
    echo "    -v redis_data:/data \\"
    echo "    redis:7-alpine redis-server --appendonly yes"
    return 1
}

# ═══════════════════════════════════════════════════════════
# 3. 代码拉取 + 依赖安装
# ═══════════════════════════════════════════════════════════

pull_code() {
    log_step "拉取代码"

    # 后端
    if [ -d "${PROJECT_DIR}/.git" ]; then
        cd "${PROJECT_DIR}"
        log_info "拉取后端代码..."

        # 检查是否有未提交的本地修改
        if git diff --quiet && git diff --cached --quiet; then
            # 没有本地修改，安全拉取
            git pull origin ${GIT_BRANCH} 2>&1
            log_info "后端代码更新完成"
        else
            # 有本地修改 —— 使用 rebase + autostash（自动恢复本地修改）
            log_warn "检测到本地未提交的修改，使用 autostash 保护..."
            git pull --rebase --autostash origin ${GIT_BRANCH} 2>&1 || {
                # 如果 autostash 冲突，提示用户
                log_error "拉取代码时发生冲突！请手动解决:"
                log_error "  cd ${PROJECT_DIR} && git stash pop && git diff"
                log_warn "跳过代码拉取，使用本地版本继续部署"
                git rebase --abort 2>/dev/null || true
            }
            log_info "后端代码更新完成（本地修改已保留）"
        fi
    else
        log_warn "后端目录不是 git 仓库，跳过"
    fi

    # 前端
    if [ -d "${FRONTEND_DIR}/.git" ]; then
        cd "${FRONTEND_DIR}"
        log_info "拉取前端代码..."

        if git diff --quiet && git diff --cached --quiet; then
            git pull origin ${GIT_BRANCH} 2>&1
            log_info "前端代码更新完成"
        else
            log_warn "检测到前端本地修改，使用 autostash 保护..."
            git pull --rebase --autostash origin ${GIT_BRANCH} 2>&1 || {
                log_error "前端拉取冲突！请手动解决:"
                log_error "  cd ${FRONTEND_DIR} && git stash pop && git diff"
                log_warn "跳过前端代码拉取，使用本地版本继续部署"
                git rebase --abort 2>/dev/null || true
            }
            log_info "前端代码更新完成（本地修改已保留）"
        fi
    else
        log_warn "前端目录不是 git 仓库，跳过"
    fi
}

install_deps() {
    log_step "安装 Python 依赖"
    cd "${PROJECT_DIR}"

    if [ -f "requirements.txt" ]; then
        if [ -d "${VENV_DIR}" ]; then
            log_info "使用虚拟环境: ${VENV_DIR}"
            source "${VENV_DIR}/bin/activate"
        else
            log_info "创建虚拟环境..."
            python3 -m venv "${VENV_DIR}"
            source "${VENV_DIR}/bin/activate"
        fi
        log_info "安装依赖..."
        pip install -r requirements.txt -q 2>&1 | tail -5
        log_info "依赖安装完成"
    fi
}

fix_python_deps() {
    log_step "修复 Python 依赖"

    DEPS_FIXED_FLAG="${PROJECT_DIR}/.deps_fixed_v2"
    if [ -f "$DEPS_FIXED_FLAG" ]; then
        log_info "依赖已修复过，跳过 (删除 ${DEPS_FIXED_FLAG} 可强制重新修复)"
        return
    fi

    cd "${PROJECT_DIR}"
    source "${VENV_DIR}/bin/activate" 2>/dev/null || true

    log_info "安装系统 OpenSSL 开发包..."
    apt-get install -y libssl-dev libffi-dev python3-dev -q 2>/dev/null || true

    log_info "重新安装加密相关包..."
    pip install --force-reinstall --no-cache-dir \
        "cryptography>=41.0.0" "pyOpenSSL>=23.2.0" 2>&1 | tail -3

    pip install --force-reinstall --no-cache-dir \
        "urllib3>=2.0.0,<3.0.0" "requests>=2.31.0" "certifi>=2023.7.22" 2>&1 | tail -3

    if [ -f "${PROJECT_DIR}/requirements.txt" ]; then
        pip install -r "${PROJECT_DIR}/requirements.txt" -q 2>&1 | tail -3
    fi

    touch "$DEPS_FIXED_FLAG"
    log_info "Python 依赖修复完成"
}

# ═══════════════════════════════════════════════════════════
# 4. 后端服务启停 (Uvicorn 直接运行 or Systemd)
# ═══════════════════════════════════════════════════════════

stop_service() {
    log_step "停止后端服务"

    # 方法 1: systemd
    if systemctl is-active --quiet ${PROJECT_NAME} 2>/dev/null; then
        log_info "通过 systemd 停止 ${PROJECT_NAME}..."
        systemctl stop ${PROJECT_NAME}
        sleep 2
        log_info "Systemd 服务已停止"
        # ★ 修复: 去掉 return，继续执行端口清理，防止 [Errno 98] address already in use
    fi

    # 方法 2: PID 文件
    if [ -f "${PID_FILE}" ]; then
        PID=$(cat "${PID_FILE}")
        if kill -0 "$PID" 2>/dev/null; then
            log_info "停止进程 PID=${PID}..."
            kill "$PID" 2>/dev/null || true
            sleep 2
            kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null || true
            log_info "进程已停止"
        fi
        rm -f "${PID_FILE}"
    fi

    # 方法 3: 清理端口占用 (兜底，无论方法 1/2 是否执行都会运行)
    PIDS=$(lsof -ti:${APP_PORT} 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        log_warn "清理端口 ${APP_PORT} 的残留进程: ${PIDS}"
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
        sleep 1
    fi

    # 最终验证端口已释放
    PIDS_FINAL=$(lsof -ti:${APP_PORT} 2>/dev/null || true)
    if [ -n "$PIDS_FINAL" ]; then
        log_warn "端口 ${APP_PORT} 仍被占用: ${PIDS_FINAL}，使用 fuser 强制释放..."
        fuser -k ${APP_PORT}/tcp 2>/dev/null || true
        sleep 1
    fi

    log_info "✅ 服务停止完成，端口 ${APP_PORT} 已释放"

    # ★ v9: 额外等待确保 TCP TIME_WAIT 完全释放
    sleep 2
}

start_service() {
    log_step "启动后端服务"
    cd "${PROJECT_DIR}"

    # ★ v9 修复: 启动前确保端口已释放
    PIDS_PRE=$(lsof -ti:${APP_PORT} 2>/dev/null || true)
    if [ -n "$PIDS_PRE" ]; then
        log_warn "启动前发现端口 ${APP_PORT} 仍被占用: ${PIDS_PRE}，强制清理..."
        echo "$PIDS_PRE" | xargs kill -9 2>/dev/null || true
        sleep 2
    fi

    # ★ v9 修复: 启动前确保 PostgreSQL 可连接 (防止 sqlalchemy e3q8 错误)
    log_info "验证 PostgreSQL 连接..."
    source "${PROJECT_DIR}/.env" 2>/dev/null || true
    PG_READY=false
    for i in $(seq 1 20); do
        # 方法1: docker pg_isready
        if command -v docker &>/dev/null && docker ps --format "{{.Names}}" | grep -qi "postgres"; then
            PG_CONTAINER=$(docker ps --format "{{.Names}}" | grep -i postgres | head -1)
            if docker exec ${PG_CONTAINER} pg_isready -U postgres &>/dev/null; then
                PG_READY=true
                break
            fi
        fi
        # 方法2: 系统 pg_isready
        if pg_isready -h localhost -p 5432 &>/dev/null 2>&1; then
            PG_READY=true
            break
        fi
        [ $i -eq 1 ] && log_info "等待 PostgreSQL 就绪..."
        sleep 1
    done
    if $PG_READY; then
        log_info "PostgreSQL 连接验证通过"
    else
        log_warn "PostgreSQL 连接验证超时，继续尝试启动 (可能仍会成功)..."
    fi

    # 如果有 systemd service，使用它
    if [ -f "/etc/systemd/system/${PROJECT_NAME}.service" ]; then
        log_info "通过 systemd 启动 ${PROJECT_NAME}..."
        systemctl start ${PROJECT_NAME}

        # ★ v9 修复: 等待端口实际监听而不仅仅是 systemd active
        log_info "等待服务就绪..."
        SVC_READY=false
        for i in $(seq 1 30); do
            if ss -tlnp 2>/dev/null | grep -q ":${APP_PORT} "; then
                SVC_READY=true
                break
            fi
            sleep 1
        done

        if $SVC_READY; then
            log_info "✅ 服务启动成功 (systemd, 端口 ${APP_PORT} 已监听)"
            log_info "   后端: https://${DOMAIN}:${BACKEND_PORT}"
            log_info "   文档: https://${DOMAIN}:${BACKEND_PORT}/docs"
            log_info "   日志: journalctl -u ${PROJECT_NAME} -f"
            return 0
        else
            # 检查 systemd 状态
            if systemctl is-active --quiet ${PROJECT_NAME}; then
                log_warn "systemd 显示 active 但端口未监听，等待更长时间..."
                sleep 10
                if ss -tlnp 2>/dev/null | grep -q ":${APP_PORT} "; then
                    log_info "✅ 服务最终启动成功 (延迟)"
                    return 0
                fi
            fi
            log_error "systemd 启动失败或超时，回退到直接启动..."
            log_error "错误日志:"
            journalctl -u ${PROJECT_NAME} --no-pager -n 20 || true
            systemctl stop ${PROJECT_NAME} 2>/dev/null || true
            sleep 2
            fuser -k ${APP_PORT}/tcp 2>/dev/null || true
            sleep 1
        fi
    fi

    # 直接启动 (fallback)
    if [ -d "${VENV_DIR}" ]; then
        source "${VENV_DIR}/bin/activate"
    fi
    export PYTHONPATH="${PROJECT_DIR}:${PYTHONPATH}"

    log_info "启动 ${PROJECT_NAME} (直接模式) 于 ${BACKEND_HOST}:${APP_PORT}..."
    nohup uvicorn app.main:app \
        --host ${BACKEND_HOST} \
        --port ${APP_PORT} \
        --workers ${WORKERS} \
        --log-level ${LOG_LEVEL} \
        --access-log \
        >> "${LOG_DIR}/app.log" 2>> "${LOG_DIR}/error.log" &

    echo $! > "${PID_FILE}"
    sleep 3

    if kill -0 "$(cat ${PID_FILE})" 2>/dev/null; then
        log_info "✅ 服务启动成功! PID=$(cat ${PID_FILE})"
        log_info "   后端: https://${DOMAIN}:${BACKEND_PORT}"
        log_info "   文档: https://${DOMAIN}:${BACKEND_PORT}/docs"
        log_info "   日志: tail -f ${LOG_DIR}/app.log"
    else
        log_error "服务启动失败！检查日志:"
        tail -30 "${LOG_DIR}/error.log" 2>/dev/null
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════
# 5. Logging 配置 (JSON 格式，解决 KeyError: 'formatters')
# ═══════════════════════════════════════════════════════════

setup_logging_config() {
    log_step "配置 Logging (JSON)"

    mkdir -p "${PROJECT_DIR}/config"
    mkdir -p "${LOG_DIR}"

    # 删除可能导致冲突的旧格式 logging 配置文件
    for f in logging.conf logging.ini logging.cfg; do
        if [ -f "${PROJECT_DIR}/${f}" ]; then
            log_warn "发现可能导致冲突的配置文件: ${f}，已备份"
            mv "${PROJECT_DIR}/${f}" "${PROJECT_DIR}/${f}.bak.$(date +%s)"
        fi
    done

    # ★ 修复: 写入 JSON 格式日志配置，uvicorn 能正确解析 'formatters' 键
    cat > "${PROJECT_DIR}/config/logging_config.json" <<'LOGCFG'
{
    "version": 1,
    "disable_existing_loggers": false,
    "formatters": {
        "default": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S"
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": "%(asctime)s - %(client_addr)s - \"%(request_line)s\" %(status_code)s",
            "datefmt": "%Y-%m-%d %H:%M:%S"
        }
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "filename": "logs/app.log",
            "maxBytes": 10485760,
            "backupCount": 5,
            "encoding": "utf-8"
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "filename": "logs/error.log",
            "maxBytes": 10485760,
            "backupCount": 5,
            "encoding": "utf-8",
            "level": "ERROR"
        }
    },
    "loggers": {
        "uvicorn": {
            "handlers": ["default", "file"],
            "level": "INFO",
            "propagate": false
        },
        "uvicorn.error": {
            "handlers": ["default", "file", "error_file"],
            "level": "INFO",
            "propagate": false
        },
        "uvicorn.access": {
            "handlers": ["default", "file"],
            "level": "INFO",
            "propagate": false
        },
        "app": {
            "handlers": ["default", "file", "error_file"],
            "level": "INFO",
            "propagate": false
        },
        "app.core.agents": {
            "handlers": ["default", "file", "error_file"],
            "level": "DEBUG",
            "propagate": false
        }
    },
    "root": {
        "handlers": ["default", "file"],
        "level": "INFO"
    }
}
LOGCFG

    log_info "✅ 日志配置已写入: ${PROJECT_DIR}/config/logging_config.json"
}

# ═══════════════════════════════════════════════════════════
# 6. Systemd 服务创建
# ═══════════════════════════════════════════════════════════

create_systemd_service() {
    log_step "配置 Systemd 服务"

    # 确定 Python 路径
    if [ -d "${VENV_DIR}" ]; then
        PYTHON_BIN="${VENV_DIR}/bin/python3"
        UVICORN_BIN="${VENV_DIR}/bin/uvicorn"
    else
        PYTHON_BIN="/usr/bin/python${PYTHON_VERSION}"
        UVICORN_BIN="$(which uvicorn)"
    fi

    mkdir -p /var/log/${PROJECT_NAME}

    # ★ v9: 创建启动前检查脚本 (避免 heredoc 变量展开问题)
    cat > ${PROJECT_DIR}/pre_start.sh <<'PRESCRIPT'
#!/bin/bash
# 清理端口占用
fuser -k 8000/tcp 2>/dev/null || true
sleep 1
# 等待 PostgreSQL 就绪
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    docker exec postgres pg_isready -U postgres >/dev/null 2>&1 && exit 0
    pg_isready -h localhost -p 5432 >/dev/null 2>&1 && exit 0
    sleep 1
done
echo "WARNING: PostgreSQL readiness check timed out, proceeding anyway"
exit 0
PRESCRIPT
    chmod +x ${PROJECT_DIR}/pre_start.sh

    cat > /etc/systemd/system/${PROJECT_NAME}.service <<EOF
[Unit]
Description=skynetCheapBuy API Service
After=network.target docker.service postgresql.service redis.service
Wants=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=${PROJECT_DIR}
Environment="PATH=${VENV_DIR}/bin:/usr/bin:/usr/local/bin"
Environment="PYTHONPATH=${PROJECT_DIR}"
Environment="PYTHONUNBUFFERED=1"

# ★ v9 修复: 启动前清理端口 + 验证 DB 就绪
ExecStartPre=/bin/bash ${PROJECT_DIR}/pre_start.sh

# ★ 修复: --log-config 使用 JSON 格式，解决 KeyError: 'formatters'
ExecStart=${UVICORN_BIN} app.main:app --host 0.0.0.0 --port ${APP_PORT} --workers ${WORKERS} --log-level ${LOG_LEVEL} --log-config ${PROJECT_DIR}/config/logging_config.json
Restart=always
RestartSec=10
StartLimitBurst=5
StartLimitIntervalSec=60
StandardOutput=append:/var/log/${PROJECT_NAME}/stdout.log
StandardError=append:/var/log/${PROJECT_NAME}/stderr.log

# 安全限制
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable ${PROJECT_NAME}

    log_info "Systemd 服务已配置"
    log_info "使用: systemctl {start|stop|restart|status} ${PROJECT_NAME}"
}

# ═══════════════════════════════════════════════════════════
# 6. Nginx 配置
# ═══════════════════════════════════════════════════════════

configure_nginx_initial() {
    log_step "配置 Nginx (初始)"

    # 安装 nginx (如果没有)
    if ! command -v nginx &>/dev/null; then
        log_info "安装 Nginx..."
        apt-get install -y nginx -q
    fi

    # 清理所有可能冲突的配置文件
    # 移除 default 和任何其他包含本域名的配置
    [ -f /etc/nginx/sites-enabled/default ] && rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
    [ -f /etc/nginx/sites-enabled/default.bak ] && rm -f /etc/nginx/sites-enabled/default.bak 2>/dev/null || true

    # 清理 sites-enabled 中除本项目外的任何包含 DOMAIN 的配置
    if [ -n "$DOMAIN" ]; then
        for conf in /etc/nginx/sites-enabled/*; do
            [ -f "$conf" ] || continue
            local conf_basename=$(basename "$conf")
            if [ "$conf_basename" != "${PROJECT_NAME}" ] && grep -q "$DOMAIN" "$conf" 2>/dev/null; then
                log_warn "移除冲突的 Nginx 配置: $conf"
                rm -f "$conf"
            fi
        done
    fi

    if [ -z "$DOMAIN" ]; then
        SERVER_NAME=$PUBLIC_IP
    else
        SERVER_NAME="$DOMAIN www.$DOMAIN"
    fi

    mkdir -p /var/www/html/.well-known/acme-challenge
    chmod -R 755 /var/www/html

    cat > /etc/nginx/sites-available/${PROJECT_NAME} <<NGINX_EOF
# HTTP — Let's Encrypt 验证 + 临时代理
server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAME};

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/html;
        allow all;
        try_files \$uri =404;
    }

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}

# 端口 ${BACKEND_PORT} — 临时无 SSL
server {
    listen ${BACKEND_PORT};
    listen [::]:${BACKEND_PORT};
    server_name ${SERVER_NAME};

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_set_header X-Accel-Buffering 'no';
    }

    location /ws {
        proxy_pass http://127.0.0.1:${APP_PORT}/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 86400;
    }
}
NGINX_EOF

    ln -sf /etc/nginx/sites-available/${PROJECT_NAME} /etc/nginx/sites-enabled/

    if nginx -t 2>&1; then
        systemctl restart nginx
        systemctl enable nginx
        log_info "Nginx 初始配置完成"
    else
        log_error "Nginx 配置测试失败"
        nginx -t
        exit 1
    fi
}

configure_nginx_final() {
    local cert_path=$1
    local key_path=$2

    log_info "更新 Nginx 最终 HTTPS 配置..."

    if [ -z "$DOMAIN" ]; then
        SERVER_NAME=$PUBLIC_IP
    else
        SERVER_NAME="$DOMAIN www.$DOMAIN"
    fi

    cat > /etc/nginx/sites-available/${PROJECT_NAME} <<NGINX_EOF
# HTTP — 重定向到 HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAME};

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/html;
        allow all;
        try_files \$uri =404;
    }

    location / {
        return 301 https://\$host:${BACKEND_PORT}\$request_uri;
    }
}

# HTTPS 服务 — 端口 ${BACKEND_PORT}
server {
    listen ${BACKEND_PORT} ssl http2;
    listen [::]:${BACKEND_PORT} ssl http2;
    server_name ${SERVER_NAME};

    ssl_certificate ${cert_path};
    ssl_certificate_key ${key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # 安全头部
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    client_max_body_size 100M;

    # 代理超时 (Agentic Loop 需要长超时)
    proxy_connect_timeout 6000s;
    proxy_send_timeout 6000s;
    proxy_read_timeout 30000s;

    # API 代理
    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # SSE / 流式响应支持
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_set_header Cache-Control 'no-cache';
        proxy_set_header X-Accel-Buffering 'no';
    }

    # WebSocket 支持
    location /ws {
        proxy_pass http://127.0.0.1:${APP_PORT}/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 86400;
    }

    # 健康检查 (不记录日志)
    location /health {
        access_log off;
        proxy_pass http://127.0.0.1:${APP_PORT}/health;
    }
}

# 443 端口 — 重定向到自定义端口
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${SERVER_NAME};

    ssl_certificate ${cert_path};
    ssl_certificate_key ${key_path};

    return 301 https://\$host:${BACKEND_PORT}\$request_uri;
}
NGINX_EOF

    if nginx -t 2>&1; then
        systemctl restart nginx
        log_info "Nginx HTTPS 配置完成"
    else
        log_error "Nginx 配置测试失败"
        nginx -t
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════
# 7. SSL 证书 (Let's Encrypt / 自签名)
# ═══════════════════════════════════════════════════════════

install_certbot() {
    if command -v certbot &>/dev/null; then
        log_info "Certbot 已安装"
        return
    fi

    log_info "安装 Certbot..."
    apt-get remove -y certbot python3-certbot-nginx 2>/dev/null || true

    if command -v snap &>/dev/null; then
        snap install core 2>/dev/null || true
        snap refresh core 2>/dev/null || true
        snap install --classic certbot
        ln -sf /snap/bin/certbot /usr/bin/certbot
    else
        apt-get install -y certbot
    fi

    certbot --version && log_info "Certbot 安装成功" || log_error "Certbot 安装失败"
}

configure_ssl() {
    log_step "配置 SSL 证书"

    if [ -z "$DOMAIN" ]; then
        log_warn "未设置域名，使用自签名证书"
        configure_self_signed_ssl
    else
        configure_lets_encrypt
    fi
}

configure_self_signed_ssl() {
    mkdir -p /etc/nginx/ssl

    if [ -f "/etc/nginx/ssl/${PROJECT_NAME}.crt" ] && [ -f "/etc/nginx/ssl/${PROJECT_NAME}.key" ]; then
        log_info "自签名证书已存在"
    else
        log_info "生成自签名证书..."
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout /etc/nginx/ssl/${PROJECT_NAME}.key \
            -out /etc/nginx/ssl/${PROJECT_NAME}.crt \
            -subj "/C=CN/ST=State/L=City/O=Organization/CN=${PUBLIC_IP}"
    fi

    configure_nginx_final "/etc/nginx/ssl/${PROJECT_NAME}.crt" "/etc/nginx/ssl/${PROJECT_NAME}.key"
    log_warn "使用自签名证书，浏览器会显示安全警告"
}

configure_lets_encrypt() {
    log_info "配置 Let's Encrypt..."

    mkdir -p /var/www/html/.well-known/acme-challenge
    chmod -R 755 /var/www/html

    if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
        log_info "证书已存在，使用现有证书"
        configure_nginx_final \
            "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" \
            "/etc/letsencrypt/live/${DOMAIN}/privkey.pem"

        # 确保自动续期
        if command -v snap &>/dev/null && snap list certbot &>/dev/null; then
            systemctl enable snap.certbot.renew.timer 2>/dev/null || true
            systemctl start snap.certbot.renew.timer 2>/dev/null || true
        fi
        log_info "证书自动续期已配置"
    else
        log_info "申请新证书..."
        install_certbot
        certbot certonly --webroot \
            -w /var/www/html \
            -d ${DOMAIN} \
            --non-interactive \
            --agree-tos \
            --email ${EMAIL}

        if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
            log_info "证书申请成功！"
            configure_nginx_final \
                "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" \
                "/etc/letsencrypt/live/${DOMAIN}/privkey.pem"

            # 自动续期
            (crontab -l 2>/dev/null || true; echo "0 3 * * * /snap/bin/certbot renew --quiet --post-hook 'systemctl reload nginx'") | sort -u | crontab -
        else
            log_error "证书申请失败，回退到自签名"
            configure_self_signed_ssl
        fi
    fi
}

# ═══════════════════════════════════════════════════════════
# 8. 防火墙配置
# ═══════════════════════════════════════════════════════════

configure_firewall() {
    log_step "配置防火墙"

    if ! command -v ufw &>/dev/null; then
        log_warn "ufw 未安装，跳过防火墙配置"
        return
    fi

    ufw allow 22/tcp   comment 'SSH'           2>/dev/null || true
    ufw allow 80/tcp   comment 'HTTP'          2>/dev/null || true
    ufw allow 443/tcp  comment 'HTTPS'         2>/dev/null || true
    ufw allow ${BACKEND_PORT}/tcp comment 'skynetCheapBuy API' 2>/dev/null || true

    echo "y" | ufw enable 2>/dev/null || true
    log_info "防火墙配置完成"
}

# ═══════════════════════════════════════════════════════════
# 9. 前端构建
# ═══════════════════════════════════════════════════════════

build_frontend() {
    log_step "构建前端"

    if [ ! -d "${FRONTEND_DIR}" ]; then
        log_warn "前端目录不存在: ${FRONTEND_DIR}，跳过"
        return
    fi

    cd "${FRONTEND_DIR}"

    if [ ! -d "node_modules" ]; then
        log_info "安装前端依赖..."
        npm install 2>&1 | tail -3
    fi

    log_info "构建前端..."
    npm run build 2>&1 | tail -5
    log_info "前端构建完成"
}

# ═══════════════════════════════════════════════════════════
# 10. 监控 + 日志轮转
# ═══════════════════════════════════════════════════════════

setup_monitoring() {
    log_step "配置日志轮转"

    mkdir -p /var/log/${PROJECT_NAME}

    cat > /etc/logrotate.d/${PROJECT_NAME} <<EOF
/var/log/${PROJECT_NAME}/*.log ${LOG_DIR}/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root root
    sharedscripts
    postrotate
        systemctl reload ${PROJECT_NAME} > /dev/null 2>&1 || true
    endscript
}
EOF

    log_info "日志轮转已配置"
}

# ═══════════════════════════════════════════════════════════
# 11. 状态检查
# ═══════════════════════════════════════════════════════════

show_status() {
    log_step "服务状态总览"

    echo ""
    # Docker
    if command -v docker &>/dev/null; then
        if systemctl is-active --quiet docker; then
            log_info "✅ Docker: 运行中"
        else
            log_warn "⚠️  Docker: 未运行"
        fi
    fi

    # PostgreSQL
    PG_OK=false
    if systemctl is-active --quiet postgresql 2>/dev/null; then
        log_info "✅ PostgreSQL: 运行中 (系统服务)"
        PG_OK=true
    elif command -v docker &>/dev/null && docker ps --format "{{.Names}}" | grep -qi "postgres"; then
        log_info "✅ PostgreSQL: 运行中 (Docker)"
        PG_OK=true
    fi
    $PG_OK || log_warn "⚠️  PostgreSQL: 未检测到"

    # Redis
    REDIS_OK=false
    if systemctl is-active --quiet redis-server 2>/dev/null || systemctl is-active --quiet redis 2>/dev/null; then
        log_info "✅ Redis: 运行中 (系统服务)"
        REDIS_OK=true
    elif command -v docker &>/dev/null && docker ps --format "{{.Names}}" | grep -qi "redis"; then
        log_info "✅ Redis: 运行中 (Docker)"
        REDIS_OK=true
    fi
    $REDIS_OK || log_warn "⚠️  Redis: 未检测到"

    # 后端
    if systemctl is-active --quiet ${PROJECT_NAME} 2>/dev/null; then
        log_info "✅ 后端: 运行中 (systemd)"
    elif [ -f "${PID_FILE}" ] && kill -0 "$(cat ${PID_FILE} 2>/dev/null)" 2>/dev/null; then
        log_info "✅ 后端: 运行中 (PID=$(cat ${PID_FILE}))"
    else
        log_warn "⚠️  后端: 未运行"
    fi

    # Nginx
    if systemctl is-active --quiet nginx 2>/dev/null; then
        log_info "✅ Nginx: 运行中"
    else
        log_warn "⚠️  Nginx: 未运行"
    fi

    # 端口检查
    echo ""
    for port in ${APP_PORT} ${BACKEND_PORT}; do
        if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
            log_info "✅ 端口 ${port}: 已监听"
        else
            log_warn "⚠️  端口 ${port}: 未监听"
        fi
    done

    # Health check
    echo ""
    for url in "http://localhost:${APP_PORT}/health" "https://localhost:${BACKEND_PORT}/health"; do
        HEALTH=$(curl -sk -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null || echo "000")
        if [ "$HEALTH" = "200" ]; then
            log_info "✅ Health (${url}): OK"
        else
            log_warn "⚠️  Health (${url}): HTTP ${HEALTH}"
        fi
    done

    # 最近错误
    echo ""
    if [ -f "${LOG_DIR}/error.log" ] && [ -s "${LOG_DIR}/error.log" ]; then
        log_info "最近错误 (最后 5 行):"
        tail -5 "${LOG_DIR}/error.log"
    fi
    if [ -f "/var/log/${PROJECT_NAME}/stderr.log" ] && [ -s "/var/log/${PROJECT_NAME}/stderr.log" ]; then
        log_info "Systemd 错误 (最后 5 行):"
        tail -5 "/var/log/${PROJECT_NAME}/stderr.log"
    fi
}

show_logs() {
    log_step "日志位置"
    echo "  1. 应用日志:   tail -f ${LOG_DIR}/app.log"
    echo "  2. 错误日志:   tail -f ${LOG_DIR}/error.log"
    echo "  3. Systemd:    journalctl -u ${PROJECT_NAME} -f"
    echo "  4. Nginx:      tail -f /var/log/nginx/error.log"
    echo ""
    log_info "最近 30 行错误日志:"
    tail -30 "${LOG_DIR}/error.log" 2>/dev/null || echo "  (无)"
}

# ═══════════════════════════════════════════════════════════
# 12. 部署信息
# ═══════════════════════════════════════════════════════════

show_deployment_info() {
    echo ""
    echo -e "${GREEN}══════════════════════════════════════${NC}"
    echo -e "${GREEN}  skynetCheapBuy 部署完成 🎉${NC}"
    echo -e "${GREEN}══════════════════════════════════════${NC}"
    echo ""
    echo -e "${CYAN}访问地址:${NC}"
    echo -e "  API 文档:   https://${DOMAIN}:${BACKEND_PORT}/docs"
    echo -e "  ReDoc:      https://${DOMAIN}:${BACKEND_PORT}/redoc"
    echo -e "  健康检查:   https://${DOMAIN}:${BACKEND_PORT}/health"
    echo -e "  WebSocket:  wss://${DOMAIN}:${BACKEND_PORT}/ws"
    echo ""
    echo -e "${CYAN}管理命令:${NC}"
    echo -e "  重启:       bash deploy.sh --restart"
    echo -e "  状态:       bash deploy.sh --status"
    echo -e "  日志:       bash deploy.sh --logs"
    echo -e "  Systemd:    systemctl {start|stop|restart|status} ${PROJECT_NAME}"
    echo ""
}

# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

case "${1:-}" in
    --local)
        # ══════════ 本地部署（不拉取 git，保护本地修改）══════════
        log_step "本地部署 ${PROJECT_NAME}（跳过 git pull）"
        echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""

        check_root
        check_project

        start_docker
        start_postgresql
        start_redis

        check_env
        # 注意：不调用 pull_code()，保护本地修改
        log_info "⏭️  跳过 git pull，使用本地代码"
        install_deps

        setup_logging_config
        create_systemd_service
        configure_nginx_initial
        configure_ssl
        configure_firewall

        stop_service
        start_service

        setup_monitoring
        show_status
        show_deployment_info
        ;;
    --restart)
        start_docker
        start_postgresql
        start_redis
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
    --logs)
        show_logs
        ;;
    --build-frontend)
        pull_code
        build_frontend
        ;;
    --fix-deps)
        check_root
        check_project
        install_deps
        fix_python_deps
        stop_service
        start_service
        show_status
        ;;
    --setup-ssl)
        check_root
        configure_nginx_initial
        configure_ssl
        ;;
    --setup-systemd)
        check_root
        setup_logging_config
        create_systemd_service
        ;;
    --help|-h)
        echo "用法: bash deploy.sh [选项]"
        echo ""
        echo "选项:"
        echo "  (无参数)           完整部署: 服务检查 + 拉代码 + 安装依赖 + Nginx/SSL + 启动"
        echo "  --local            本地部署: 跳过 git pull，保护本地修改的文件（推荐日常使用）"
        echo "  --restart          重启后端 (先启动 Docker/PG/Redis)"
        echo "  --pull             仅拉代码"
        echo "  --stop             停止后端服务"
        echo "  --status           查看所有服务状态"
        echo "  --logs             查看日志"
        echo "  --build-frontend   构建前端"
        echo "  --fix-deps         修复 Python 依赖问题"
        echo "  --setup-ssl        配置/更新 SSL 证书"
        echo "  --setup-systemd    创建/更新 systemd 服务"
        echo "  --help             显示帮助"
        ;;
    *)
        # ══════════ 完整部署流程 ══════════
        log_step "开始完整部署 ${PROJECT_NAME}"
        echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""

        check_root
        check_project

        # 1. 基础服务
        start_docker
        start_postgresql
        start_redis

        # 2. 环境 + 代码 + 依赖
        check_env
        pull_code
        install_deps

        # 3. Systemd 服务
        setup_logging_config
        create_systemd_service

        # 4. Nginx + SSL
        configure_nginx_initial
        configure_ssl

        # 5. 防火墙
        configure_firewall

        # 6. 停旧启新
        stop_service
        start_service

        # 7. 监控
        setup_monitoring

        # 8. 状态检查
        show_status
        show_deployment_info
        ;;
esac