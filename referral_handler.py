"""
واجهة جيش نابليون — شاشات المستخدم + سحب العمولة.
"""

from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from accounts_handler import SavedAccountsHandler
from config import Config
from database import DatabaseManager, User
from keyboards import Keyboards
from utils import format_currency, safe_edit_callback_message, tg_code
import napoleon_ui
from referral_service import (
    COMMISSION_STATUS_LABELS,
    ReferralArmyService,
    STATUS_LABELS,
    get_min_commission_withdraw,
)

logger = logging.getLogger(__name__)
db = DatabaseManager()

METHOD_AR = {
    "syriatel_cash": "📱 سيرياتيل كاش",
    "shamcash": "💠 شام كاش",
    "usdt": "🌐 عملات رقمية",
}


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
            "👑 جيش نابليون\n\n"
            "جيب رفقاتك من رابطك الخاص\n\n"
            "وكل إحالة نشطة بتكبر جيشك وبتقربك من رتبة اعلى\n\n"
            f"🎖️ رتبتك {rank['title']}\n\n"
            f"💸 نسبتك الحالية {rank['rate']:g}%\n\n"
            f"👥 كل المدعوين {c['total']}\n\n"
            f"✅ الإحالات النشطة {c['active']}\n\n"
            f"⏳ قيد التحقق {c['pending_total']}\n\n"
            f"💰 العمولة المتاحة {format_currency(dash['available'])}\n\n"
            f"🔒 قيد المراجعة {format_currency(dash['pending'])}\n\n"
            "🔗 رابطك الخاص\n"
            f"{link}\n\n"
            "كل ما كبر الجيش\n"
            "المحاسب صار يناديك حضرتك 😂"
        )
        await _edit(update, context, text, Keyboards.army_menu())

    @staticmethod
    async def show_recruits(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        c = ReferralArmyService.counts_for(user.id)
        listing = ReferralArmyService.list_recruits(user.id, page=page)
        lines = [
            "👥 أفراد جيش نابليون\n",
            f"👥 كل المسجلين {c['total']}",
            f"✅ النشطين {c['active']}",
            f"⏳ قيد التحقق {c['pending_total']}",
            f"❌ غير المؤهلين {c['rejected']}\n",
            "المحاسب عدهم مرتين\nلانه ما وثق بالآلة الحاسبة 😂\n",
        ]
        for item in listing["items"]:
            lines.append(f"👤 المستخدم {item['index']}")
            lines.append(f"📌 الحالة {item['status_label']}")
            lines.append(f"📅 تاريخ الانضمام {item['date']}\n")
            if item["status"] == "rejected" and item.get("reject_reason"):
                lines.append(f"السبب: {item['reject_reason']}\n")
        if not listing["items"]:
            lines.append("لسا ما في أحد بالجيش.")
        await _edit(
            update,
            context,
            "\n".join(lines),
            Keyboards.army_recruits_nav(listing["page"], listing["has_prev"], listing["has_next"]),
        )

    @staticmethod
    async def show_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        dash = ReferralArmyService.dashboard(user)
        monthly = ReferralArmyService.monthly_commission(user.id)
        rank = dash["rank"]
        text = (
            "💰 خزنة العمولات\n\n"
            f"🎖️ رتبتك {rank['title']}\n\n"
            f"💸 نسبتك {rank['rate']:g}%\n\n"
            f"✅ متاح للسحب {format_currency(dash['available'])}\n\n"
            f"⏳ قيد المراجعة {format_currency(dash['pending'])}\n\n"
            f"📆 عمولة هالشهر {format_currency(monthly)}\n\n"
            f"🏦 مجموع اللي سحبته {format_currency(dash['withdrawn'])}\n\n"
            "الخزنة بخير\n"
            "بس كثرة السؤال عنها عم تعمللها توتر 😂"
        )
        await _edit(update, context, text, Keyboards.army_back_menu())

    @staticmethod
    async def show_ledger(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        listing = ReferralArmyService.list_ledger(user.id, page=page)
        lines = ["📊 كشف العمولات\n"]
        if not listing["items"]:
            lines.append("ما في حركات بعد.")
        for item in listing["items"]:
            lines.append(f"🧾 رقم الحركة {item['id']}")
            lines.append(f"📅 التاريخ {item['date']}")
            lines.append(f"💰 القيمة {format_currency(item['amount'])}")
            lines.append(f"📌 الحالة {item['status_label']}\n")
        await _edit(
            update,
            context,
            "\n".join(lines),
            Keyboards.army_ledger_nav(listing["page"], listing["has_prev"], listing["has_next"]),
        )

    @staticmethod
    async def show_my_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        dash = ReferralArmyService.dashboard(user)
        rank = dash["rank"]
        nxt = dash["next_rank"]
        remaining = dash["remaining"]
        if nxt:
            rem_block = f"{remaining}"
            nxt_line = f"للرتبة الجاية باقي\n\n{rem_block}\n\nإحالات نشطة"
        else:
            nxt_line = "وصلت أعلى رتبة\nالإمبراطور ما بيحتاج شرح 👑"
        text = (
            f"🎖️ رتبتك الحالية {rank['title']}\n\n"
            f"👥 إحالاتك النشطة {dash['counts']['active']}\n\n"
            f"📈 نسبتك الحالية {rank['rate']:g}%\n\n"
            f"{nxt_line}\n\n"
            "كمّل جيشك\n"
            "المحاسب بلش يحكي معك بصيغة الجمع 😂"
        )
        await _edit(update, context, text, Keyboards.army_back_menu())

    @staticmethod
    async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (
            "🤡 الشروط اللي محدا بيقراها\n\n"
            "حتى تنحسب إحالتك لازم:\n\n"
            "✅ يكون رفيقك جديد عالبوت\n\n"
            "🔗 يدخل من رابطك\n\n"
            "🎮 يعمل حساب ويلعب فيه\n\n"
            "🛡️ ما يكون مكرر او وهمي\n\n"
            "💰 يستوفي شرط النشاط\n\n"
            "🚫 وممنوع تجيب حالك من رابطك\n\n"
            "مو ناقصنا نابليونين بنفس البيت 😂\n\n"
            "💸 عمولتك حسب صافي النشاط المؤهل ونسبة رتبتك\n\n"
            "⏳ العمولة بتضل قيد المراجعة قبل السحب\n\n"
            "🔞 الخدمة للبالغين فقط والاستخدام بمسؤولية\n\n"
            "اذا قرأت لهون\n"
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
        text = (
            "📤 جنّد رفيق\n\n"
            "انسخ رابطك وابعته لرفقاتك:\n\n"
            f"{link}\n\n"
            "🔞 للبالغين فقط، واستخدم الخدمة بمسؤولية."
        )
        await _edit(update, context, text, Keyboards.army_back_menu())

    # ─── سحب العمولة ──────────────────────────────────────

    @staticmethod
    async def start_withdraw_commission(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        dash = ReferralArmyService.dashboard(user)
        min_w = get_min_commission_withdraw()
        avail = dash["available"]
        if avail < min_w:
            text = (
                "🏧 لسا العمولة ما وصلت لحد السحب\n\n"
                f"💰 المتاح {format_currency(avail)}\n\n"
                f"📌 اقل مبلغ للسحب {format_currency(min_w)}\n\n"
                "المحاسب قال اصبر عليها شوي 😂"
            )
            await _edit(update, context, text, Keyboards.army_back_menu())
            return

        context.user_data.clear()
        context.user_data["operation"] = "army_commission_withdraw"
        context.user_data["state"] = "waiting_army_wd_amount"
        text = (
            "🏧 سحب عمولة جيش نابليون\n\n"
            f"💰 المتاح {format_currency(avail)}\n"
            f"📌 اقل مبلغ {format_currency(min_w)}\n\n"
            "اكتب المبلغ اللي بدك تسحبه\n"
            "أرقام فقط"
        )
        await _edit(update, context, text, Keyboards.army_wd_amount_menu())

    @staticmethod
    async def handle_wd_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: str):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        raw = (raw or "").strip().replace(",", "").replace(" ", "")
        if not re.fullmatch(r"\d+(\.\d+)?", raw):
            await _edit(
                update,
                context,
                "🤨 هاد مو مبلغ\nاكتب أرقام فقط مثل\n200000",
                Keyboards.army_wd_amount_menu(),
            )
            return
        amount = float(raw)
        min_w = get_min_commission_withdraw()
        avail = float(user.commission_available or 0)
        if amount < min_w:
            await _edit(
                update,
                context,
                "🏧 لسا العمولة ما وصلت لحد السحب\n\n"
                f"💰 المتاح {format_currency(avail)}\n\n"
                f"📌 اقل مبلغ للسحب {format_currency(min_w)}",
                Keyboards.army_wd_amount_menu(),
            )
            context.user_data["state"] = "waiting_army_wd_amount"
            return
        if amount > avail:
            await _edit(
                update,
                context,
                f"😅 طلبت {format_currency(amount)}\n"
                f"والمتاح {format_currency(avail)}\n\n"
                "ما في سلف من الخزنة 😂",
                Keyboards.army_wd_amount_menu(),
            )
            context.user_data["state"] = "waiting_army_wd_amount"
            return
        context.user_data["army_wd_amount"] = amount
        context.user_data["operation"] = "army_commission_withdraw"
        context.user_data.pop("state", None)
        await ReferralHandler.show_wd_methods(update, context)

    @staticmethod
    async def withdraw_all_available(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        await ReferralHandler.handle_wd_amount(
            update, context, str(float(user.commission_available or 0))
        )

    @staticmethod
    async def show_wd_methods(update: Update, context: ContextTypes.DEFAULT_TYPE):
        amount = context.user_data.get("army_wd_amount")
        if not amount:
            await ReferralHandler.start_withdraw_commission(update, context)
            return
        text = (
            "💸 اختار طريقة استلام العمولة\n\n"
            f"💰 المبلغ {format_currency(float(amount))}"
        )
        await _edit(update, context, text, Keyboards.army_wd_methods_menu())

    @staticmethod
    async def choose_wd_method(update: Update, context: ContextTypes.DEFAULT_TYPE, method: str):
        if method == "other":
            await _edit(
                update,
                context,
                "🧩 طرق ثانية\n\nالمتاح: سيرياتيل / شام كاش / عملات رقمية.\nللحالة الخاصة تواصل مع الدعم.",
                Keyboards.army_wd_methods_menu(),
            )
            return
        context.user_data["army_wd_method"] = method
        context.user_data["operation"] = "army_commission_withdraw"
        if method == "usdt":
            await _edit(
                update,
                context,
                "🌐 اختار العملة والشبكة",
                Keyboards.army_wd_crypto_menu(),
            )
            return
        context.user_data["state"] = "waiting_army_wd_dest"
        if method == "syriatel_cash":
            text = "📱 ابعت رقم سيرياتيل كاش\nمثال: 09XXXXXXXX"
        else:
            text = "💠 ابعت عنوان محفظة شام كاش\nانسخه مثل ما هو"
        await _edit(update, context, text, Keyboards.army_wd_dest_menu())

    @staticmethod
    async def choose_wd_crypto(update, context, currency: str, network: str):
        context.user_data["army_wd_crypto_c"] = currency
        context.user_data["army_wd_crypto_n"] = network
        context.user_data["army_wd_method"] = "usdt"
        context.user_data["state"] = "waiting_army_wd_dest"
        await _edit(
            update,
            context,
            f"🌐 سحب {currency} · {network}\n\nابعت عنوان المحفظة",
            Keyboards.army_wd_dest_menu(),
        )

    @staticmethod
    async def handle_wd_dest(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: str):
        method = context.user_data.get("army_wd_method")
        amount = context.user_data.get("army_wd_amount")
        if not method or not amount:
            await ReferralHandler.start_withdraw_commission(update, context)
            return
        dest = (raw or "").strip()
        if method == "syriatel_cash":
            dest, err = SavedAccountsHandler.validate_account("syriatel_cash", dest)
            if err:
                await _edit(
                    update,
                    context,
                    "🤨 الرقم مو سوري أو صيغته غلط\nالمطلوب: 09XXXXXXXX",
                    Keyboards.army_wd_dest_menu(),
                )
                return
        elif method == "shamcash":
            dest, err = SavedAccountsHandler.validate_account("shamcash", dest)
            if err:
                await _edit(
                    update,
                    context,
                    (err or "عنوان غير صالح").replace("`", ""),
                    Keyboards.army_wd_dest_menu(),
                )
                return
        elif len(dest) < 8:
            await _edit(
                update,
                context,
                "🤨 العنوان قصير زيادة",
                Keyboards.army_wd_dest_menu(),
            )
            return
        context.user_data["army_wd_dest"] = dest
        context.user_data.pop("state", None)
        await ReferralHandler.show_wd_review(update, context)

    @staticmethod
    async def show_wd_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
        amount = float(context.user_data.get("army_wd_amount") or 0)
        method = context.user_data.get("army_wd_method")
        dest = context.user_data.get("army_wd_dest") or "—"
        method_txt = METHOD_AR.get(method, method or "—")
        if method == "usdt":
            method_txt = (
                f"🌐 {context.user_data.get('army_wd_crypto_c', 'USDT')} / "
                f"{context.user_data.get('army_wd_crypto_n', 'TRC20')}"
            )
        text = (
            "🧾 راجع طلب سحب العمولة\n\n"
            f"💰 المبلغ {format_currency(amount)}\n"
            f"💳 الطريقة {method_txt}\n"
            f"📍 الاستلام {tg_code(dest)}\n\n"
            "راجع قبل التأكيد"
        )
        context.user_data["state"] = "waiting_army_wd_confirm"
        await _edit(
            update, context, text, Keyboards.army_wd_review_menu(), parse_mode="HTML"
        )

    @staticmethod
    async def confirm_wd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if context.user_data.get("army_wd_lock"):
            try:
                await update.callback_query.answer("الطلب موجود اصلًا", show_alert=True)
            except TelegramError:
                pass
            return
        context.user_data["army_wd_lock"] = True
        user = db.get_user(update.effective_user.id)
        amount = float(context.user_data.get("army_wd_amount") or 0)
        method = context.user_data.get("army_wd_method")
        dest = context.user_data.get("army_wd_dest")
        if not user or not amount or not method or not dest:
            context.user_data.clear()
            await _edit(update, context, "انتهت الجلسة.", Keyboards.army_menu())
            return
        ok, msg, order_id = ReferralArmyService.create_withdraw_request(
            user,
            amount,
            method,
            dest,
            crypto_currency=context.user_data.get("army_wd_crypto_c"),
            crypto_network=context.user_data.get("army_wd_crypto_n"),
        )
        context.user_data.clear()
        if not ok:
            await _edit(
                update,
                context,
                f"✋ {msg}",
                Keyboards.army_menu(),
            )
            return
        text = (
            "⏳ وصل طلب سحب العمولة\n\n"
            f"💰 المبلغ {format_currency(amount)}\n"
            f"🧾 رقم الطلب {tg_code(order_id)}\n\n"
            "رح يوصلك إشعار عند التنفيذ"
        )
        await _edit(update, context, text, Keyboards.army_menu(), parse_mode="HTML")
        try:
            await ReferralHandler._notify_admins_wd(context, order_id, user, amount, method, dest)
        except Exception:
            logger.exception("فشل إشعار أدمن بسحب عمولة")

    @staticmethod
    async def _notify_admins_wd(context, order_id, user, amount, method, dest):
        text = (
            f"🏧 طلب سحب عمولة جيش\n"
            f"🧾 #{order_id}\n"
            f"المستخدم: {getattr(user, 'first_name', '')} / {getattr(user, 'telegram_id', '')}\n"
            f"المبلغ: {format_currency(amount)}\n"
            f"الطريقة: {METHOD_AR.get(method, method)}\n"
            f"الوجهة: {dest}\n"
        )
        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=text,
                    reply_markup=Keyboards.admin_army_wd_menu(order_id),
                )
            except TelegramError:
                pass

    # توافق
    show_referral_rewards = show_rewards
    show_ranks = show_my_rank


async def _edit(update, context, text, markup, parse_mode=None):
    kwargs = {"reply_markup": markup, "context": context}
    if parse_mode:
        kwargs["parse_mode"] = parse_mode
    if update.callback_query:
        await safe_edit_callback_message(update, text, **kwargs)
    elif update.effective_message:
        send_kw = {"text": text, "reply_markup": markup}
        if parse_mode:
            send_kw["parse_mode"] = parse_mode
        await update.effective_message.reply_text(**send_kw)
