"""
معالج الإحالات
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

import ui
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
            progress = ui.bar(min(user.referral_count, 5) / 5)
            status = (
                f"✅ لديك <b>{user.referral_count}</b> إحالة\n"
                f"💰 أرباحك: <b>{format_currency(user.referral_earnings)}</b>\n"
                f"🎯 التقدّم نحو الجائزة: {progress} {min(user.referral_count, 5)}/5"
            )
        else:
            status = (
                f"🚫 لم تقم بإجراء أي إحالات حتى الآن!\n"
                f"🎯 التقدّم نحو الجائزة: {ui.bar(0)} 0/5"
            )

        message = f"""<b>💠 نظام الإحالات الخاص بـ {ui.esc(bot_name)}</b>
{ui.DIVIDER}
1️⃣ <b>النظام الأول:</b> نسبة ربح <b>{Config.REFERRAL_PERCENTAGE:g}%</b> من رابط الإحالة.
<blockquote>شرط الحصول على الجوائز هو إنشاء 5 حسابات على الأقل من رابطك، وأن يقوم واحد منهم على الأقل بحرق 100 ألف أو أكثر.</blockquote>
{ui.DIVIDER}
{status}
{ui.DIVIDER}
<i>🎯 لزيادة فرصك في الحصول على المكافآت، شارك رابط الإحالة الخاص بك مع أصدقائك وابدأ اليوم!</i>
"""

        if update.callback_query:
            await safe_edit_callback_message(
                update,
                message,
                reply_markup=Keyboards.referral_menu(),
                parse_mode="HTML",
                context=context,
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.referral_menu(),
                parse_mode="HTML",
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
            "<b>🔗 رابط الإحالة الخاص بك</b>\n"
            f"{ui.DIVIDER}\n"
            f"<code>{ui.esc(referral_link)}</code>\n"
            f"{ui.DIVIDER}\n"
            "<i>اضغط على الرابط لنسخه، وشاركه مع أصدقائك — "
            "عند تسجيلهم عبره تُحتسب لك الإحالة ✅</i>"
        )

        # رسالة جديدة (مثل الصورة) وليس تعديل الرسالة السابقة
        await ui.typing(context, update.effective_chat.id)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=share_message,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
