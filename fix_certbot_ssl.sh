#!/bin/bash

# 修复 Certbot 并为 baloonet.tech 配置 SSL 证书

set -e

# 配置变量
DOMAIN="baloonet.tech"
PUBLIC_IP="8.163.12.28"
PROJECT_NAME="chatbot-api"
PUBLIC_PORT="17432"
APP_PORT="8000"
EMAIL="admin@baloonet.tech"  # 请改为你的邮箱

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# 检查 root 权限
if [[ $EUID -ne 0 ]]; then
   log_error "此脚本需要 root 权限运行"
   exit 1
fi

log_info "开始修复 Certbot 并配置 SSL..."

# 步骤 1: 卸载旧版本的 certbot
log_info "卸载旧版本的 Certbot..."
apt-get remove -y certbot python3-certbot-nginx || true
apt-get autoremove -y

# 步骤 2: 安装 snapd（如果还没安装）
log_info "安装 Snap..."
apt-get update
apt-get install -y snapd
systemctl enable --now snapd.socket

# 等待 snap 完全启动
sleep 5

# 步骤 3: 使用 snap 安装最新版 certbot
log_info "使用 Snap 安装最新版 Certbot..."
snap install core
snap refresh core
snap install --classic certbot

# 创建符号链接
ln -sf /snap/bin/certbot /usr/bin/certbot

# 验证安装
log_info "验证 Certbot 安装..."
certbot --version

# 步骤 4: 创建临时的 Nginx 配置用于验证
log_info "配置 Nginx..."

# 先备份现有配置
if [ -f "/etc/nginx/sites-available/${PROJECT_NAME}" ]; then
    cp /etc/nginx/sites-available/${PROJECT_NAME} /etc/nginx/sites-available/${PROJECT_NAME}.bak
fi

# 创建简单的 HTTP 配置用于域名验证
cat > /etc/nginx/sites-available/${PROJECT_NAME} <<EOF
# HTTP 服务器 - 用于 Let's Encrypt 验证
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} www.${DOMAIN};
    
    # Let's Encrypt 验证目录
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    # 临时响应
    location / {
        return 200 "Waiting for SSL setup...";
        add_header Content-Type text/plain;
    }
}

# 临时的端口 ${PUBLIC_PORT} 配置（无 SSL）
server {
    listen ${PUBLIC_PORT};
    listen [::]:${PUBLIC_PORT};
    server_name ${DOMAIN} www.${DOMAIN};
    
    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF

# 测试并重启 Nginx
nginx -t && systemctl restart nginx

# 步骤 5: 申请 Let's Encrypt 证书
log_info "申请 Let's Encrypt 证书..."

# 使用 webroot 方式申请证书
certbot certonly --webroot \
    -w /var/www/html \
    -d ${DOMAIN} \
    -d www.${DOMAIN} \
    --non-interactive \
    --agree-tos \
    --email ${EMAIL}

# 检查证书是否申请成功
if [ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
    log_error "证书申请失败"
    
    # 尝试使用 standalone 模式
    log_warning "尝试使用 standalone 模式..."
    systemctl stop nginx
    certbot certonly --standalone \
        -d ${DOMAIN} \
        -d www.${DOMAIN} \
        --non-interactive \
        --agree-tos \
        --email ${EMAIL}
    systemctl start nginx
fi

# 再次检查证书
if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
    log_info "证书申请成功！"
else
    log_error "证书申请失败，请检查域名 DNS 设置"
    exit 1
fi

# 步骤 6: 更新 Nginx 配置使用 SSL
log_info "更新 Nginx 配置以使用 SSL..."

cat > /etc/nginx/sites-available/${PROJECT_NAME} <<EOF
# HTTP 服务器 - 重定向到 HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} www.${DOMAIN};
    
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    location / {
        return 301 https://\$server_name:${PUBLIC_PORT}\$request_uri;
    }
}

# HTTPS 服务器 - 端口 ${PUBLIC_PORT}
server {
    listen ${PUBLIC_PORT} ssl http2;
    listen [::]:${PUBLIC_PORT} ssl http2;
    server_name ${DOMAIN} www.${DOMAIN};
    
    # SSL 证书
    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    
    # SSL 优化
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # 安全头部
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    
    # 客户端配置
    client_max_body_size 100M;
    
    # API 代理
    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        
        # 流式响应支持
        proxy_buffering off;
        proxy_cache off;
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
    
    # 健康检查
    location /health {
        access_log off;
        proxy_pass http://127.0.0.1:${APP_PORT}/health;
    }
}

# 标准 HTTPS 端口 443 - 重定向
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN} www.${DOMAIN};
    
    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    
    return 301 https://\$server_name:${PUBLIC_PORT}\$request_uri;
}
EOF

# 测试配置
if nginx -t; then
    log_info "Nginx 配置测试通过"
    systemctl restart nginx
else
    log_error "Nginx 配置测试失败"
    exit 1
fi

# 步骤 7: 设置自动续期
log_info "设置证书自动续期..."
systemctl enable snap.certbot.renew.timer
systemctl start snap.certbot.renew.timer

# 或者添加 cron 任务作为备份
(crontab -l 2>/dev/null || true; echo "0 3 * * * /snap/bin/certbot renew --quiet --post-hook 'systemctl reload nginx'") | crontab -

# 步骤 8: 重启应用服务
log_info "重启应用服务..."
systemctl restart ${PROJECT_NAME} || true

# 完成
echo -e "\n${GREEN}========== SSL 配置完成！ ==========${NC}"
echo -e "${BLUE}域名:${NC} ${DOMAIN}"
echo -e "${BLUE}证书位置:${NC} /etc/letsencrypt/live/${DOMAIN}/"

echo -e "\n${GREEN}========== 访问地址 ==========${NC}"
echo -e "${BLUE}API 文档:${NC} https://${DOMAIN}:${PUBLIC_PORT}/docs"
echo -e "${BLUE}ReDoc:${NC} https://${DOMAIN}:${PUBLIC_PORT}/redoc"
echo -e "${BLUE}健康检查:${NC} https://${DOMAIN}:${PUBLIC_PORT}/health"

echo -e "\n${YELLOW}提示:${NC}"
echo -e "1. 使用 'snap list' 查看已安装的 snap 包"
echo -e "2. 使用 'certbot certificates' 查看证书状态"
echo -e "3. 使用 'systemctl status snap.certbot.renew.timer' 查看自动续期状态"
