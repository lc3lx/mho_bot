#!/bin/bash
# إعداد webhook على https://www.alipride.com/botich
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
DOMAIN="${DOMAIN:-www.alipride.com}"
PATH_NAME="${PATH_NAME:-botich}"

echo "=== Webhook: https://${DOMAIN}/${PATH_NAME} ==="

pm2 stop ichancy-bot 2>/dev/null || true

# .env
touch .env
for key in BOT_MODE WEBHOOK_HOST WEBHOOK_PORT WEBHOOK_PATH WEBHOOK_URL WEBHOOK_SECRET; do
  grep -q "^${key}=" .env || echo "${key}=" >> .env
done
sed -i 's/^BOT_MODE=.*/BOT_MODE=webhook/' .env
sed -i 's/^WEBHOOK_HOST=.*/WEBHOOK_HOST=127.0.0.1/' .env
sed -i 's/^WEBHOOK_PORT=.*/WEBHOOK_PORT=6001/' .env
sed -i "s/^WEBHOOK_PATH=.*/WEBHOOK_PATH=${PATH_NAME}/" .env
sed -i "s|^WEBHOOK_URL=.*|WEBHOOK_URL=https://${DOMAIN}/${PATH_NAME}|" .env
sed -i 's/^WEBHOOK_SECRET=.*/WEBHOOK_SECRET=ichancy_bot_secret_6001/' .env

echo "=== .env webhook ==="
grep -E '^(BOT_MODE|WEBHOOK_)' .env

# Nginx location (أضف للموقع الموجود إن أمكن)
NGINX_SNIPPET="/etc/nginx/snippets/ichancy-botich.conf"
sudo tee "$NGINX_SNIPPET" > /dev/null <<EOF
location /${PATH_NAME} {
    proxy_pass http://127.0.0.1:6001/${PATH_NAME};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_read_timeout 60s;
}
EOF

echo ""
echo "تم إنشاء: $NGINX_SNIPPET"
echo "أضف داخل server لـ ${DOMAIN}:"
echo "  include /etc/nginx/snippets/ichancy-botich.conf;"
echo ""
echo "ثم:"
echo "  sudo nginx -t && sudo systemctl reload nginx"
echo "  pm2 start ichancy-bot"
echo "  curl -sI https://${DOMAIN}/${PATH_NAME}"
