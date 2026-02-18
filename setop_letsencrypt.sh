#!/bin/bash

# 为 baloonet.tech 配置 Let's Encrypt SSL 证书

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

log_info "开始为 ${DOMAIN} 配置 Let's Encrypt SSL 证书..."

# 步骤 1: 安装 Certbot（如果还没安装）
log_info "检查并安装 Certbot..."
if ! command -v certbot &> /dev/null; then
    apt-get update
    apt-get install -y certbot python3-certbot-nginx
fi

# 步骤 2: 创建新的 Nginx 配置（支持域名）
log_info "更新 Nginx 配置以支持域名..."

cat > /etc/nginx/sites-available/${PROJECT_NAME} <<EOF
# HTTP 服务器 - 用于 Let's Encrypt 验证和重定向
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} www.${DOMAIN};
    
    # Let's Encrypt 验证目录
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    # 其他请求重定向到 HTTPS
    location / {
        return 301 https://\$server_name:${PUBLIC_PORT}\$request_uri;
    }
}

# HTTPS 服务器 - 端口 ${PUBLIC_PORT}
server {
    listen ${PUBLIC_PORT} ssl http2;
    listen [::]:${PUBLIC_PORT} ssl http2;
    server_name ${DOMAIN} www.${DOMAIN};
    
    # SSL 证书（将由 certbot 自动配置）
    # ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    
    # SSL 优化配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_stapling on;
    ssl_stapling_verify on;
    
    # 安全头部
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    
    # 客户端配置
    client_max_body_size 100M;
    client_body_buffer_size 128k;
    
    # 代理超时设置
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 300s;
    
    # API 路由
    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;
        
        # 代理头部
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$server_name;
        proxy_set_header X-Forwarded-Port \$server_port;
        
        # 禁用缓冲以支持流式响应
        proxy_buffering off;
        proxy_cache off;
        
        # SSE 支持
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
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # WebSocket 超时
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
    
    # 健康检查端点
    location /health {
        access_log off;
        proxy_pass http://127.0.0.1:${APP_PORT}/health;
    }
}

# 标准 HTTPS 端口 443 - 重定向到自定义端口
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN} www.${DOMAIN};
    
    # SSL 证书（将由 certbot 自动配置）
    # ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    
    # 重定向到自定义端口
    return 301 https://\$server_name:${PUBLIC_PORT}\$request_uri;
}
EOF

# 步骤 3: 临时使用非 SSL 配置以便申请证书
log_info "创建临时配置以申请证书..."

cat > /etc/nginx/sites-available/${PROJECT_NAME}-temp <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} www.${DOMAIN};
    
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    location / {
        return 404;
    }
}
EOF

# 启用临时配置
ln -sf /etc/nginx/sites-available/${PROJECT_NAME}-temp /etc/nginx/sites-enabled/${PROJECT_NAME}

# 测试并重启 Nginx
nginx -t && systemctl restart nginx

# 步骤 4: 申请 Let's Encrypt 证书
log_info "申请 Let's Encrypt 证书..."

# 申请证书
certbot certonly --webroot -w /var/www/html -d ${DOMAIN} -d www.${DOMAIN} \
    --non-interactive --agree-tos --email ${EMAIL}

# 检查证书是否申请成功
if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
    log_info "证书申请成功！"
else
    log_error "证书申请失败"
    exit 1
fi

# 步骤 5: 启用正式配置
log_info "启用正式的 SSL 配置..."

# 删除临时配置
rm -f /etc/nginx/sites-available/${PROJECT_NAME}-temp

# 更新配置文件，添加证书路径
sed -i "s|# ssl_certificate /etc/letsencrypt|ssl_certificate /etc/letsencrypt|g" /etc/nginx/sites-available/${PROJECT_NAME}

# 启用正式配置
ln -sf /etc/nginx/sites-available/${PROJECT_NAME} /etc/nginx/sites-enabled/${PROJECT_NAME}

# 测试配置
if nginx -t; then
    log_info "Nginx 配置测试通过"
    systemctl restart nginx
else
    log_error "Nginx 配置测试失败"
    exit 1
fi

# 步骤 6: 设置自动续期
log_info "设置证书自动续期..."

# 添加 cron 任务
(crontab -l 2>/dev/null || true; echo "0 3 * * * /usr/bin/certbot renew --quiet --post-hook 'systemctl reload nginx'") | crontab -

# 步骤 7: 更新 .env 文件中的 CORS 配置
log_info "更新 CORS 配置..."

if [ -f "/root/dylan/ChatGPT-Telegram-Bot/CheapBuy/.env" ]; then
    # 备份原文件
    cp /root/dylan/ChatGPT-Telegram-Bot/CheapBuy/.env /root/dylan/ChatGPT-Telegram-Bot/CheapBuy/.env.bak
    
    # 更新 CORS_ORIGINS
    sed -i "s|CORS_ORIGINS=.*|CORS_ORIGINS=[\"https://${DOMAIN}\",\"https://${DOMAIN}:${PUBLIC_PORT}\",\"https://www.${DOMAIN}\",\"https://www.${DOMAIN}:${PUBLIC_PORT}\"]|g" /root/dylan/ChatGPT-Telegram-Bot/CheapBuy/.env
fi

# 重启应用服务
log_info "重启应用服务..."
systemctl restart ${PROJECT_NAME}

# 完成
echo -e "\n${GREEN}========== 配置完成！ ==========${NC}"
echo -e "${BLUE}域名:${NC} ${DOMAIN}"
echo -e "${BLUE}证书位置:${NC} /etc/letsencrypt/live/${DOMAIN}/"
echo -e "${BLUE}证书有效期:${NC} 90天（已配置自动续期）"

echo -e "\n${GREEN}========== 访问地址 ==========${NC}"
echo -e "${BLUE}API 文档:${NC} https://${DOMAIN}:${PUBLIC_PORT}/docs"
echo -e "${BLUE}ReDoc:${NC} https://${DOMAIN}:${PUBLIC_PORT}/redoc"
echo -e "${BLUE}健康检查:${NC} https://${DOMAIN}:${PUBLIC_PORT}/health"
echo -e "${BLUE}WebSocket:${NC} wss://${DOMAIN}:${PUBLIC_PORT}/ws"

echo -e "\n${GREEN}========== 备用访问 ==========${NC}"
echo -e "${BLUE}标准端口:${NC} https://${DOMAIN}/docs (会重定向到端口 ${PUBLIC_PORT})"

echo -e "\n${YELLOW}注意事项:${NC}"
echo -e "1. 确保域名 DNS 已经指向 ${PUBLIC_IP}"
echo -e "2. 证书会在 90 天后自动续期"
echo -e "3. 可以使用 'certbot certificates' 查看证书状态"
echo -e "4. 使用 'systemctl status ${PROJECT_NAME}' 查看服务状态"
