#!/bin/bash
# ============================================================
# إعداد كامل للبوت على VPS — قاعدة بيانات SQLite + PM2
# الاستخدام:
#   cd /root/home/alipride/bot_ich
#   chmod +x deploy/setup-vps.sh
#   ./deploy/setup-vps.sh
# ============================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "============================================"
echo " ichancy Bot — إعداد VPS"
echo " المجلد: $PROJECT_DIR"
echo "============================================"

# ─── 1. حزم النظام ─────────────────────────────────────────
echo "[1/6] تثبيت Python..."
if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-venv python3-pip
elif command -v yum &>/dev/null; then
    sudo yum install -y python3 python3-pip
fi

# ─── 2. مجلدات ─────────────────────────────────────────────
echo "[2/6] إنشاء مجلدات data و logs..."
mkdir -p data logs
chmod 755 data logs

# ─── 3. بيئة Python ─────────────────────────────────────────
echo "[3/6] إنشاء venv وتثبيت المكتبات..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# ─── 4. ملف .env ───────────────────────────────────────────
echo "[4/6] ملف الإعدادات .env..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "  → تم نسخ .env.example إلى .env"
        echo "  ⚠️  عدّل .env الآن: nano .env"
        echo "      لازم: BOT_TOKEN و ADMIN_IDS و APISYRIA_API_KEY"
    else
        echo "  ❌ ملف .env.example غير موجود!"
        exit 1
    fi
else
    echo "  → .env موجود مسبقاً"
fi

# ─── 5. قاعدة البيانات SQLite ──────────────────────────────
echo "[5/6] إنشاء قاعدة البيانات المحلية..."
python deploy/init-db.py

# ─── 6. PM2 ────────────────────────────────────────────────
echo "[6/6] تشغيل PM2..."
if ! command -v pm2 &>/dev/null; then
    echo "  تثبيت PM2..."
    if command -v npm &>/dev/null; then
        sudo npm install -g pm2
    else
        echo "  ⚠️  npm غير موجود — ثبّت Node.js ثم: npm install -g pm2"
        echo "  أو شغّل يدوياً: source venv/bin/activate && python bot.py"
        exit 0
    fi
fi

pm2 delete ichancy-bot 2>/dev/null || true
pm2 start ecosystem.config.js
pm2 save

echo ""
echo "============================================"
echo " ✅ تم الإعداد!"
echo "============================================"
echo " قاعدة البيانات: $PROJECT_DIR/data/telegram_bot.db"
echo ""
echo " أوامر مفيدة:"
echo "   pm2 status"
echo "   pm2 logs ichancy-bot"
echo "   pm2 restart ichancy-bot"
echo ""
echo " بعد تعديل .env:"
echo "   nano .env && pm2 restart ichancy-bot"
echo "============================================"
