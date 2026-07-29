"""
معالج الإحالات
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from database import DatabaseManager, User
from config import Config
from keyboards import Keyboards
from utils import format_currency

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
        """شاشة أنظمة الإحالات مثل الصورة"""
        user = db.get_user(update.effective_user.id)
        bot_name = Config.BOT_DISPLAY_NAME

        if user.referral_count and user.referral_count > 0:
            status = (
                f"✅ لديك {user.referral_count} إحالة\n"
                f"💰 أرباحك: {format_currency(user.referral_earnings)}"
            )
        else:
            status = "🚫 لم تقم بإجراء أي إحالات حتى الآن!"

        message = f"""👥 أنظمة الإحالات الخاصة بـ {bot_name}

يقدم {bot_name} نوعين من أنظمة الإحالات، يتيح كل منهما فرصة لتحقيق أرباح مجزية.

1️⃣ النظام الأول: نظام إحالات ثوري يُكافئك اسبوعياً بأفضل نسبة تتجاوز الـ 15%
شرط الحصول على الجوائز هو وجود 3 إحالات نشطة على الاقل وان تقوم احالة واحدة على الاقل بحرق مبلغ اكثر من 100 الف

2️⃣ النظام الثاني: مكافأة مالية محددة بقيمة 2000 ليرة لكل إحالة نشطة قامت بشحن أقل من 100,000 ليرة، و 5000 ليرة للإحالات النشطة التي قامت بشحن أكثر من 100,000 ليرة.

{status}

🎯 لزيادة فرصك في الحصول على المكافآت، شارك رابط الإحالة الخاص بك مع أصدقائك وابدأ اليوم!
"""

        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=Keyboards.referral_menu(),
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
        bot_username = context.bot.username or Config.BOT_USERNAME
        referral_link = ReferralHandler.build_referral_link(bot_username, user)

        share_message = (
            f"رابط الإحالة الخاص بك هو: 🔗\n"
            f"{referral_link}"
        )

        # رسالة جديدة (مثل الصورة) وليس تعديل الرسالة السابقة
        if update.callback_query:
            await update.callback_query.answer()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=share_message,
            )
        else:
            await update.message.reply_text(share_message)
