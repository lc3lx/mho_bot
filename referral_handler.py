"""
معالج الإحالات
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from database import DatabaseManager, User
from config import Config
from keyboards import Keyboards
from utils import format_currency, safe_edit_callback_message

logger = logging.getLogger(__name__)
db = DatabaseManager()


class ReferralHandler:
    """معالج الإحالات"""

    @staticmethod
    def build_referral_link(bot_username: str, user: User) -> str:
        """رابط الإحالة — يستخدم آيدي التليجرام مثل الصورة"""
        username = bot_username or Config.BOT_USERNAME or "Napoleonrobert_bot"
        return f"https://t.me/{username}?start={user.telegram_id}"

    @staticmethod
    async def show_referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شاشة نظام الإحالات"""
        user = db.get_user(update.effective_user.id)
        if not user:
            user = db.create_user(
                telegram_id=update.effective_user.id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name,
            )
        bot_name = Config.BOT_DISPLAY_NAME

        if user and user.referral_count and user.referral_count > 0:
            status = (
                f"✅ لديك {user.referral_count} إحالة\n"
                f"💰 أرباحك: {format_currency(user.referral_earnings)}"
            )
        else:
            status = "🚫 لم تقم بإجراء أي إحالات حتى الآن!"

        message = f"""نظام الإحالات الخاص بـ {bot_name}

1️⃣ النظام الأول: نسبة ربح {Config.REFERRAL_PERCENTAGE:g}% من رابط الإحالة.
شرط الحصول على الجوائز هو إنشاء 5 حسابات على الأقل من رابطك وأن يقوم واحد منهم على الأقل بحرق 100 ألف أو أكثر.

{status}

🎯 لزيادة فرصك في الحصول على المكافآت، شارك رابط الإحالة الخاص بك مع أصدقائك وابدأ اليوم!
"""

        if update.callback_query:
            await safe_edit_callback_message(
                update,
                message,
                reply_markup=Keyboards.referral_menu(),
                context=context,
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.referral_menu(),
            )

    @staticmethod
    async def share_referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إرسال رابط الإحالة — مثل الصورة"""
        user = db.get_user(update.effective_user.id)
        if not user:
            user = db.create_user(
                telegram_id=update.effective_user.id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name,
            )

        if not user:
            text = "❌ تعذر تحميل حسابك. أرسل /start ثم حاول مجدداً."
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=text
            )
            return

        bot_username = getattr(context.bot, "username", None) or Config.BOT_USERNAME
        referral_link = ReferralHandler.build_referral_link(bot_username, user)

        share_message = (
            "رابط الإحالة الخاص بك هو: 🔗\n"
            f"{referral_link}\n\n"
            "شاركه مع أصدقائك — عند تسجيلهم عبره تُحتسب لك الإحالة."
        )

        # رسالة جديدة (مثل الصورة) وليس تعديل الرسالة السابقة
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=share_message,
            disable_web_page_preview=True,
        )
