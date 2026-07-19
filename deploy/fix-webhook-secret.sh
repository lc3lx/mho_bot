#!/bin/bash
# إصلاح سريع لـ WEBHOOK_SECRET + إيقاف حلقة الانهيار
# الاستخدام: bash deploy/fix-webhook-secret.sh

set -e
cd "$(dirname "$0")/.."

echo "Stopping bot..."
pm2 stop ichancy-bot 2>/dev/null || pm2 stop 8 2>/dev/null || true

# أظهر الأسطر المشكلة
echo "=== current WEBHOOK lines ==="
grep -n 'WEBHOOK\|BOT_MODE\|^[^#].*─' .env 2>/dev/null || true
sed -n '1,25p' .env

# أصلح / أضف secret صالح
if grep -q '^WEBHOOK_SECRET=' .env; then
  sed -i 's/^WEBHOOK_SECRET=.*/WEBHOOK_SECRET=ichancy_bot_secret_6001/' .env
else
  echo 'WEBHOOK_SECRET=ichancy_bot_secret_6001' >> .env
fi

# تأكد BOT_MODE
if grep -q '^BOT_MODE=' .env; then
  sed -i 's/^BOT_MODE=.*/BOT_MODE=webhook/' .env
else
  echo 'BOT_MODE=webhook' >> .env
fi

echo ""
echo "=== after fix ==="
grep -E '^(BOT_MODE|WEBHOOK_)' .env

echo ""
echo "Done. Wait 15s then: pm2 restart ichancy-bot"
echo "If pull failed: git pull --rebase origin main"
