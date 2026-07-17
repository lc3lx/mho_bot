/**
 * PM2 — تشغيل البوت على VPS
 *
 * إعداد أول مرة:
 *   python3 -m venv venv
 *   source venv/bin/activate && pip install -r requirements.txt
 *   cp .env.example .env   # ثم عدّل القيم
 *   mkdir -p data logs
 *
 * تشغيل:
 *   pm2 start ecosystem.config.js
 *   pm2 save && pm2 startup
 */
module.exports = {
  apps: [
    {
      name: 'ichancy-bot',
      script: 'bot.py',
      interpreter: './venv/bin/python',
      cwd: __dirname,
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      error_file: './logs/pm2-error.log',
      out_file: './logs/pm2-out.log',
      merge_logs: true,
      time: true,
      // bot.py يقرأ .env تلقائياً (python-dotenv)
      // للـ webhook على 6001 ضع في .env:
      // BOT_MODE=webhook
      // WEBHOOK_PORT=6001
      // WEBHOOK_URL=https://yourdomain.com/telegram-webhook
    },
  ],
};
