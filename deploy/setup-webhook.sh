#!/bin/bash
# إعداد Webhook على بورت 6001 خلف Nginx + SSL
# الاستخدام:
#   DOMAIN=bot.example.com ./deploy/setup-webhook.sh

set -e

DOMAIN="${DOMAIN:-}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [ -z "$DOMAIN" ]; then
  echo "استخدم: DOMAIN=yourdomain.com ./deploy/setup-webhook.sh"
  exit 1
fi

echo "=== Webhook setup for $DOMAIN ==="

# مكتبات webhook
source venv/bin/activate
pip install -q "python-telegram-bot[webhooks]==20.7"

# Nginx + certbot
if command -v apt-get &>/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq nginx certbot python3-certbot-nginx
fi

# ملف Nginx
NGINX_CONF="/etc/nginx/sites-available/ichancy-bot"
sudo tee "$NGINX_CONF" > /dev/null <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location /telegram-webhook {
        proxy_pass http://127.0.0.1:6001/telegram-webhook;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
EOF

sudo ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/ichancy-bot
sudo nginx -t
sudo systemctl reload nginx

# SSL
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || \
  sudo certbot --nginx -d "$DOMAIN"

# تحديث .env
SECRET=$(openssl rand -hex 16)
if [ -f .env ]; then
  sed -i 's/^BOT_MODE=.*/BOT_MODE=webhook/' .env
  grep -q '^WEBHOOK_HOST=' .env && sed -i 's/^WEBHOOK_HOST=.*/WEBHOOK_HOST=127.0.0.1/' .env || echo 'WEBHOOK_HOST=127.0.0.1' >> .env
  grep -q '^WEBHOOK_PORT=' .env && sed -i 's/^WEBHOOK_PORT=.*/WEBHOOK_PORT=6001/' .env || echo 'WEBHOOK_PORT=6001' >> .env
  grep -q '^WEBHOOK_PATH=' .env && sed -i 's/^WEBHOOK_PATH=.*/WEBHOOK_PATH=telegram-webhook/' .env || echo 'WEBHOOK_PATH=telegram-webhook' >> .env
  grep -q '^WEBHOOK_URL=' .env && sed -i "s|^WEBHOOK_URL=.*|WEBHOOK_URL=https://${DOMAIN}/telegram-webhook|" .env || echo "WEBHOOK_URL=https://${DOMAIN}/telegram-webhook" >> .env
  grep -q '^WEBHOOK_SECRET=' .env && sed -i "s/^WEBHOOK_SECRET=.*/WEBHOOK_SECRET=${SECRET}/" .env || echo "WEBHOOK_SECRET=${SECRET}" >> .env
fi

echo ""
echo "تم. أعد تشغيل البوت:"
echo "  pm2 restart ichancy-bot"
echo "  pm2 logs ichancy-bot"
echo ""
echo "WEBHOOK_URL=https://${DOMAIN}/telegram-webhook"
echo "البوت يستمع على 127.0.0.1:6001"
