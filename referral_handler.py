"""
واجهة جيش نابليون (نظام الإحالات الجديد)
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

import ui
from database import DatabaseManager, User
from config import Config
from keyboards import Keyboards
from utils import format_currency, safe_edit_callback_message
import napoleon_ui
from referral_service import (
    ReferralArmyService,
    STATUS_LABELS,
    get_min_commission_withdraw,
    get_rank_defs,
)

logger = logging.getLogger(__name__)
db = DatabaseManager()


class ReferralHandler:
    @staticmethod
    def build_referral_link(bot_username: str, user: User) -> str:
        username = bot_username or Config.BOT_USERNAME or "Napoleonrobert_bot"
        return f"https://t.me/{username}?start={user.telegram_id}"

    @staticmethod
    async def show_referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        bot_username = getattr(context.bot, "username", None) or Config.BOT_USERNAME
        link = ReferralHandler.build_referral_link(bot_username, user)
        dash = ReferralArmyService.dashboard(user)
        rank = dash["rank"]
        c = dash["counts"]

        text = (
            "👑 <b>جيش نابليون</b>\n\n"
            "شارك رابطك الخاص وكل مستخدم جديد يدخل من خلاله "
            "ويستوفي شروط النشاط ينضم إلى جيشك ويزيد دخلك\n\n"
            f"🎖️ رتبتك: <b>{ui.esc(rank['title'])}</b>\n"
            f"💸 نسبتك الحالية: <b>{rank['rate']:g}%</b>\n"
            f"👥 إجمالي المدعوين: <b>{c['total']}</b>\n"
            f"✅ الإحالات النشطة: <b>{c['active']}</b>\n"
            f"⏳ قيد التحقق: <b>{c['pending']}</b>\n"
            f"💰 العمولة المتاحة: <b>{format_currency(dash['available'])}</b>\n"
            f"🔒 قيد المراجعة: <b>{format_currency(dash['pending'])}</b>\n\n"
            f"🔗 رابطك الخاص:\n<code>{ui.esc(link)}</code>\n\n"
            "كل ما كبر الجيش...\n"
            "المحاسب صار يناديك «حضرتك» 😂"
        )
        await _edit(update, context, text, Keyboards.army_menu())

    @staticmethod
    async def show_ranks(update: Update, context: ContextTypes.DEFAULT_TYPE):
        lines = ["🎖️ <b>نظام الرتب والعمولات</b>\n"]
        for r in get_rank_defs():
            lines.append(
                f"{ui.esc(r['title'])}:\n"
                f"{r['min_active']} إحالات نشطة = {r['rate']:g}%\n"
            )
        lines.append(
            "\nالنسب والحدود قابلة للتعديل من لوحة الإدارة."
        )
        await _edit(update, context, "\n".join(lines), Keyboards.army_menu())

    @staticmethod
    async def show_recruits(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        c = ReferralArmyService.counts_for(user.id)
        text = (
            "👥 <b>سجل جيش نابليون</b>\n\n"
            f"إجمالي المسجلين: <b>{c['total']}</b>\n"
            f"✅ نشطون: <b>{c['active']}</b>\n"
            f"⏳ قيد التحقق: <b>{c['pending']}</b>\n"
            f"❌ غير مؤهلين: <b>{c['rejected']}</b>\n\n"
            "المحاسب عدّهم مرتين...\n"
            "لأنه ما وثق بالآلة الحاسبة 😂"
        )
        await _edit(update, context, text, Keyboards.army_menu())

    @staticmethod
    async def show_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عمولتي"""
        user = db.get_user(update.effective_user.id)
        dash = ReferralArmyService.dashboard(user)
        monthly = ReferralArmyService.monthly_commission(user.id)
        rank = dash["rank"]
        text = (
            "💰 <b>خزنة العمولات</b>\n\n"
            f"🎖️ الرتبة: <b>{ui.esc(rank['title'])}</b>\n"
            f"💸 النسبة: <b>{rank['rate']:g}%</b>\n"
            f"✅ متاح للسحب: <b>{format_currency(dash['available'])}</b>\n"
            f"⏳ قيد المراجعة: <b>{format_currency(dash['pending'])}</b>\n"
            f"📆 عمولة الشهر: <b>{format_currency(monthly)}</b>\n"
            f"🏦 إجمالي المسحوب: <b>{format_currency(dash['withdrawn'])}</b>\n\n"
            "الخزنة بخير...\n"
            "بس كترة السؤال عنها عم تعمللها توتر 😂"
        )
        await _edit(update, context, text, Keyboards.army_menu())

    @staticmethod
    async def show_ledger(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        summary = ReferralArmyService.commission_summary_for_referrer(user.id)
        text = (
            "📊 <b>كشف العمولات</b>\n\n"
            f"صافي النشاط المؤهل (مجموع): <b>{format_currency(summary['net_activity_syp'])}</b>\n"
            f"إجمالي العمولات المسجّلة: <b>{format_currency(summary['commission_total'])}</b>\n\n"
            "لا نعرض خسائر كل فرد باسمه — المجموع والعمولة فقط.\n\n"
            "إذا ما توفّرت بيانات رسمية من iChancy، "
            "العمولة تبقى للمراجعة اليدوية من الإدارة."
        )
        await _edit(update, context, text, Keyboards.army_menu())

    @staticmethod
    async def show_my_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        dash = ReferralArmyService.dashboard(user)
        rank = dash["rank"]
        nxt = dash["next_rank"]
        remaining = dash["remaining"]
        if nxt:
            need = f"{remaining} إحالات نشطة إضافية للوصول إلى {nxt['title']}."
        else:
            need = "وصلت أعلى رتبة. الإمبراطور ما بيحتاج شرح 👑"
        text = (
            f"🎖️ رتبتك الحالية: <b>{ui.esc(rank['title'])}</b>\n\n"
            f"👥 إحالاتك النشطة: <b>{dash['counts']['active']}</b>\n"
            f"📈 نسبتك الحالية: <b>{rank['rate']:g}%</b>\n\n"
            f"للرتبة التالية تحتاج:\n{ui.esc(need)}\n\n"
            "كمّل تجنيد...\n"
            "المحاسب بلش يحكي معك بصيغة الجمع 😂"
        )
        await _edit(update, context, text, Keyboards.army_menu())

    @staticmethod
    async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (
            "🤡 <b>الشروط اللي محدا بيقراها</b>\n\n"
            "بما إنك فتحتها...\n"
            "شكلك من النوع النادر 😂\n\n"
            "حتى تنحسب إحالتك:\n\n"
            "✅ يكون جديد\n"
            "🔗 يدخل من رابطك\n"
            "🎮 يربط حساب iChancy موثّق\n"
            "🛡️ ما يكون مكرر أو وهمي\n"
            "💰 يستوفي شرط النشاط\n"
            "🚫 وممنوع تجيب حالك من رابطك...\n"
            "مو ناقصنا نابليونين بنفس البيت 😂\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "💸 عمولتك = صافي النشاط × نسبة رتبتك\n\n"
            "⏳ العمولة بتضل قيد المراجعة قبل السحب\n\n"
            "🔞 للبالغين فقط والاستخدام بمسؤولية.\n\n"
            "إذا قرأت لهون...\n"
            "مبروك صرت أندر من موظف محاسبة يرد بسرعة 😂"
        )
        await _edit(update, context, text, Keyboards.army_rules_ack())

    @staticmethod
    async def share_referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        bot_username = getattr(context.bot, "username", None) or Config.BOT_USERNAME
        link = ReferralHandler.build_referral_link(bot_username, user)
        share = (
            "لقيت بوت مرتب لتعبئة وسحب iChancy،\n"
            "وفوقها نظام جيش نابليون للإحالات 😂\n\n"
            f"ادخل من رابطي:\n{link}\n\n"
            "🔞 للبالغين فقط، واستخدم الخدمة بمسؤولية."
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=share,
            disable_web_page_preview=True,
            reply_markup=Keyboards.back_to_main(),
        )

    @staticmethod
    async def start_withdraw_commission(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        dash = ReferralArmyService.dashboard(user)
        min_w = get_min_commission_withdraw()
        avail = dash["available"]
        if avail < min_w:
            text = (
                "🏧 سحب العمولة\n\n"
                f"المتاح: {format_currency(avail)}\n"
                f"الحد الأدنى: {format_currency(min_w)}\n\n"
                "لسا الخزنة ما وصلت حد السحب.\n"
                "كمّل تجنيد وخلّي المحاسب يفتح الدرج 😂"
            )
            await _edit(update, context, text, Keyboards.army_menu())
            return
        ok, msg = ReferralArmyService.request_withdraw(user, avail)
        user = db.get_user(update.effective_user.id)
        text = (
            f"{'✅' if ok else '❌'} {msg}\n\n"
            f"المتاح الآن: {format_currency(user.commission_available or 0)}\n"
            f"رصيد المحفظة: {format_currency(user.balance or 0)}"
        )
        await _edit(update, context, text, Keyboards.army_menu())

    # توافق أسماء قديمة
    show_referral_rewards = show_rewards


async def _edit(update, context, text, markup):
    if update.callback_query:
        await safe_edit_callback_message(
            update, text, reply_markup=markup, parse_mode="HTML", context=context
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, reply_markup=markup, parse_mode="HTML"
        )
