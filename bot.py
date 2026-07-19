"""
البوت الرئيسي للتليجرام
"""

import logging
from dotenv import load_dotenv

load_dotenv()

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

from database import DatabaseManager, User
from config import Config
from keyboards import Keyboards
from handlers import (
    start_handler, main_menu_handler, deposit_handler, withdraw_handler,
    referral_handler, gift_handler, admin_handler, transaction_handler,
    contact_handler, callback_query_handler, message_handler
)
from payment_handler import PaymentHandler

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramBot:
    """فئة البوت الرئيسية"""
    
    def __init__(self):
        self.db = DatabaseManager()
        self.application = None
        
    def setup_bot(self):
        """إعداد البوت (متزامن — run_polling/run_webhook يديران الـ loop)"""
        self.db.create_tables()
        if self.db.db_file_path:
            logger.info("قاعدة البيانات المحلية: %s", self.db.db_file_path)
        
        self.application = (
            Application.builder()
            .token(Config.BOT_TOKEN)
            .post_init(self.setup_bot_commands)
            .build()
        )
        
        self.add_handlers()
        self.setup_jobs()
        
    async def setup_bot_commands(self, application: Application):
        """إعداد أوامر البوت بعد تهيئة التطبيق"""
        commands = [
            BotCommand("start", "بدء استخدام البوت"),
            BotCommand("menu", "القائمة الرئيسية"),
            BotCommand("balance", "عرض الرصيد"),
            BotCommand("referral", "نظام الإحالات"),
            BotCommand("help", "المساعدة"),
        ]
        
        try:
            await application.bot.set_my_commands(commands)
            logger.info("تم إعداد أوامر البوت بنجاح")
        except TelegramError as e:
            # Flood control عند إعادة التشغيل المتكرر — لا يمنع تشغيل البوت
            logger.warning("تخطي setMyCommands: %s", e)
    
    def add_handlers(self):
        """إضافة معالجات الأوامر والرسائل"""
        
        # معالجات الأوامر
        self.application.add_handler(CommandHandler("start", start_handler))
        self.application.add_handler(CommandHandler("menu", main_menu_handler))
        self.application.add_handler(CommandHandler("balance", self.balance_command))
        self.application.add_handler(CommandHandler("referral", referral_handler))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("admin", admin_handler))
        
        # معالج الاستعلامات المضمنة
        self.application.add_handler(CallbackQueryHandler(callback_query_handler))
        
        # معالج الرسائل النصية
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        
        # معالج الأخطاء
        self.application.add_error_handler(self.error_handler)

    def setup_jobs(self):
        """مهام مجدولة - مراقبة إيداعات USDT"""
        if self.application.job_queue is None:
            logger.error(
                'JobQueue غير متوفر — نفّذ: '
                'pip install "python-telegram-bot[job-queue]"'
            )
            return
        interval = Config.USDT_CONFIG.get("poll_interval_seconds", 30)
        self.application.job_queue.run_repeating(
            PaymentHandler.poll_usdt_deposits,
            interval=interval,
            first=15,
            name="usdt_deposit_poll",
        )
        logger.info("USDT deposit polling every %s seconds", interval)
        
    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """أمر عرض الرصيد"""
        user = self.db.get_user(update.effective_user.id)
        if not user:
            user = self.db.create_user(
                telegram_id=update.effective_user.id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name
            )
        
        message = f"""
💰 معلومات الرصيد

👤 الاسم: {user.first_name or 'غير محدد'}
💵 الرصيد الحالي: {user.balance:.2f} ل.س
👥 عدد الإحالات: {user.referral_count}
💰 أرباح الإحالات: {user.referral_earnings:.2f} ل.س
🔗 كود الإحالة: {user.referral_code}
        """
        
        await update.message.reply_text(
            message,
            reply_markup=Keyboards.main_menu()
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """أمر المساعدة"""
        help_text = """
🤖 مرحباً بك في بوت الدفع الإلكتروني

📋 الأوامر المتاحة:
/start - بدء استخدام البوت
/menu - القائمة الرئيسية
/balance - عرض الرصيد
/referral - نظام الإحالات
/help - المساعدة

💰 الخدمات المتاحة:
• شحن وسحب الرصيد
• نظام الإحالات والأرباح
• إهداء الرصيد للأصدقاء
• استخدام أكواد الهدايا
• التواصل مع الإدارة

📞 للمساعدة والدعم:
استخدم زر "تواصل معنا" من القائمة الرئيسية
        """
        
        await update.message.reply_text(
            help_text,
            reply_markup=Keyboards.main_menu()
        )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج الأخطاء"""
        logger.error(f"حدث خطأ: {context.error}")
        
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "❌ حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى أو التواصل مع الإدارة.",
                    reply_markup=Keyboards.main_menu()
                )
            except Exception as e:
                logger.error(f"خطأ في إرسال رسالة الخطأ: {e}")
    
    def run(self):
        """تشغيل البوت — polling أو webhook على VPS"""
        self.setup_bot()
        mode = Config.BOT_MODE

        if mode == "webhook":
            if not Config.WEBHOOK_URL:
                raise ValueError(
                    "WEBHOOK_URL مطلوب عند BOT_MODE=webhook "
                    "(مثال: https://yourdomain.com/telegram-webhook)"
                )
            logger.info(
                "Webhook على %s:%s/%s",
                Config.WEBHOOK_HOST,
                Config.WEBHOOK_PORT,
                Config.WEBHOOK_PATH,
            )
            webhook_kwargs = {
                "listen": Config.WEBHOOK_HOST,
                "port": Config.WEBHOOK_PORT,
                "url_path": Config.WEBHOOK_PATH,
                "webhook_url": Config.WEBHOOK_URL.rstrip("/"),
                "allowed_updates": Update.ALL_TYPES,
                "drop_pending_updates": True,
            }
            if Config.WEBHOOK_SECRET:
                webhook_kwargs["secret_token"] = Config.WEBHOOK_SECRET
                logger.info("Webhook secret_token مفعّل")
            else:
                logger.warning(
                    "WEBHOOK_SECRET فارغ أو غير صالح — "
                    "استخدم فقط A-Z a-z 0-9 _ -"
                )
            # لا تستخدم await — run_webhook يدير الـ event loop بنفسه
            self.application.run_webhook(**webhook_kwargs)
        else:
            logger.info("Polling mode — لا يحتاج بورت")
            self.application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    """الدالة الرئيسية"""
    bot = TelegramBot()
    bot.run()

if __name__ == "__main__":
    main()
