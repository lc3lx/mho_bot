"""
معالج الإحالات — جيب رفيقك
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

import ui
from database import DatabaseManager, User, Transaction
from config import Config
from keyboards import Keyboards
from utils import format_currency, safe_edit_callback_message
import napoleon_ui

logger = logging.getLogger(__name__)
db = DatabaseManager()


class ReferralHandler:
    """معالج الإحالات"""

    @staticmethod
    def build_referral_link(bot_username: str, user: User) -> str:
        username = bot_username or Config.BOT_USERNAME or "Napoleonrobert_bot"
        return f"https://t.me/{username}?start={user.telegram_id}"

    @staticmethod
    async def show_referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            user = db.create_user(
                telegram_id=update.effective_user.id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name,
            )
        bot_username = getattr(context.bot, "username", None) or Config.BOT_USERNAME
        link = ReferralHandler.build_referral_link(bot_username, user)

        message = (
            "👥 برنامج «جيب رفيقك»\n\n"
            "شارك رابطك الخاص مع رفيقك.\n\n"
            "لما يسجّل من رابطك ويكمل أول عملية ناجحة\n"
            "تنضاف مكافأتك تلقائيًا بعد المراجعة 🎁\n\n"
            f"🔗 رابطك:\n<code>{ui.esc(link)}</code>\n\n"
            "المهم يجي من الرابط...\n"
            "مو يقول «بعرف نابليون شخصيًا» 😂"
        )

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
    def _recruit_stats(referrer: User):
        session = db.get_session()
        try:
            invited = (
                session.query(User)
                .filter(User.referred_by == str(referrer.telegram_id))
                .all()
            )
            total = len(invited)
            completed = 0
            pending = 0
            for u in invited:
                has_deposit = (
                    session.query(Transaction.id)
                    .filter(
                        Transaction.user_id == u.id,
                        Transaction.transaction_type == "deposit",
                        Transaction.status == "completed",
                    )
                    .first()
                )
                if has_deposit:
                    completed += 1
                else:
                    pending += 1
            return total, completed, pending, float(referrer.referral_earnings or 0)
        finally:
            session.close()

    @staticmethod
    async def show_recruits(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        total, completed, pending, rewards = ReferralHandler._recruit_stats(user)
        text = (
            "👥 سجلّ التجنيد الرسمي\n\n"
            f"إجمالي المدعوين: <b>{total}</b>\n"
            f"✅ مكتملون: <b>{completed}</b>\n"
            f"⏳ قيد الانتظار: <b>{pending}</b>\n"
            f"🎁 مكافآتك: <b>{format_currency(rewards)}</b>\n\n"
            "باقي تجيب مدير المحاسبة نفسه...\n"
            "بس غالبًا ما رح يرد 😂"
        )
        await safe_edit_callback_message(
            update,
            text,
            reply_markup=Keyboards.referral_menu(),
            parse_mode="HTML",
            context=context,
        )

    @staticmethod
    async def show_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        text = (
            "🎁 وين مكافأتي؟\n\n"
            f"نسبة المكافأة: <b>{Config.REFERRAL_PERCENTAGE:g}%</b> "
            "من أول تعبئة ناجحة لرفيقك بعد المراجعة.\n\n"
            f"أرباحك الحالية: <b>{format_currency(user.referral_earnings or 0)}</b>\n\n"
            "المكافأة مش مربوطة بحجم رهان أو خسارة —\n"
            "بخدمة تعبئة مكتملة وواضحة فقط."
        )
        await safe_edit_callback_message(
            update,
            text,
            reply_markup=Keyboards.referral_menu(),
            parse_mode="HTML",
            context=context,
        )

    @staticmethod
    async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (
            "📜 الشروط بلا فلسفة\n\n"
            "1) رابط إحالة فريد لكل مستخدم\n"
            "2) تسجيل صاحب الدعوة عند أول دخول فقط\n"
            "3) ممنوع تحيل حالك\n"
            "4) الحسابات القديمة ما بتنحسب\n"
            "5) المكافأة بعد أول تعبئة ناجحة + مراجعة\n"
            "6) ما في تكرار مكافأة لنفس الشخص\n"
            "7) الحالات: جديد / قيد التحقق / مكتمل / مرفوض\n"
            "8) استخدم الخدمة بمسؤولية 🔞"
        )
        await safe_edit_callback_message(
            update,
            text,
            reply_markup=Keyboards.referral_menu(),
            context=context,
        )

    @staticmethod
    async def share_referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            user = db.create_user(
                telegram_id=update.effective_user.id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name,
            )
        if not user:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ تعذر تحميل حسابك. أرسل /start ثم حاول مجدداً.",
            )
            return

        bot_username = getattr(context.bot, "username", None) or Config.BOT_USERNAME
        referral_link = ReferralHandler.build_referral_link(bot_username, user)
        share_message = napoleon_ui.share_referral_text(referral_link)

        await ui.typing(context, update.effective_chat.id)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=share_message,
            disable_web_page_preview=True,
            reply_markup=Keyboards.back_to_main(),
        )
