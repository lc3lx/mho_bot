"""
سحب محفظة البوت — مسار خفيف بحالات واضحة ورصيد محجوز.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from accounts_handler import SavedAccountsHandler
from config import Config
from database import DatabaseManager, Transaction, User
from keyboards import Keyboards
from utils import (
    calculate_withdrawal_fee,
    format_currency,
    safe_edit_callback_message,
    tg_code,
)

logger = logging.getLogger(__name__)
db = DatabaseManager()

# حالات السحب
ST_PENDING_REVIEW = "pending_review"  # قيد المراجعة
ST_AWAITING_PAYOUT = "awaiting_payout"  # بانتظار التقبيض
ST_CANCEL_REQUESTED = "cancel_requested"  # طلب إلغاء قيد المراجعة
ST_PROCESSING = "processing"  # قيد التنفيذ
ST_PAID = "paid"  # تم التقبيض
ST_CANCELLED = "cancelled"  # ملغي
ST_REJECTED = "rejected"  # مرفوض

LEGACY_ACTIVE = {
    "pending",
    ST_PENDING_REVIEW,
    ST_AWAITING_PAYOUT,
    ST_CANCEL_REQUESTED,
    ST_PROCESSING,
}
ACTIVE_CANCELLABLE = {ST_PENDING_REVIEW, ST_AWAITING_PAYOUT, "pending"}
# بعد التقبيض أو أثناء التنفيذ النهائي — ممنوع الموافقة على الإلغاء
BLOCK_CANCEL_APPROVE = {ST_PAID, ST_PROCESSING, "completed"}

STATUS_AR = {
    ST_PENDING_REVIEW: "قيد المراجعة",
    ST_AWAITING_PAYOUT: "بانتظار التقبيض",
    ST_CANCEL_REQUESTED: "طلب إلغاء قيد المراجعة",
    ST_PROCESSING: "قيد التنفيذ",
    ST_PAID: "تم التقبيض",
    ST_CANCELLED: "ملغي",
    ST_REJECTED: "مرفوض",
    "pending": "قيد المراجعة",
    "completed": "تم التقبيض",
    "failed": "مرفوض",
    "cancelled": "ملغي",
}

METHOD_AR = {
    "syriatel_cash": "📱 سيرياتيل كاش",
    "shamcash": "💠 شام كاش",
    "usdt": "🌐 عملات رقمية",
}


def status_label(status: str) -> str:
    return STATUS_AR.get(status or "", status or "—")


def method_label(method: str) -> str:
    return METHOD_AR.get(method or "", method or "—")


def fee_breakdown(amount: float) -> tuple[float, float, float]:
    """عمولة 10% من مبلغ السحب فقط → (fee, net, profit)."""
    fee, net = calculate_withdrawal_fee(amount, Config.WITHDRAWAL_FEE_PERCENTAGE)
    profit = 0.0
    return fee, net, profit


def _admin_name(admin_user) -> str:
    if not admin_user:
        return "admin"
    uname = getattr(admin_user, "username", None)
    if uname:
        return f"@{uname}"
    first = getattr(admin_user, "first_name", None) or ""
    last = getattr(admin_user, "last_name", None) or ""
    full = f"{first} {last}".strip()
    return full or str(getattr(admin_user, "id", "admin"))


def _stamp_decision(tx: Transaction, admin_user, note: str = ""):
    """يحفظ اسم الأدمن ووقت القرار مع كل موافقة/رفض."""
    now = datetime.utcnow()
    tx.decided_at = now
    tx.processed_at = now
    if admin_user:
        tx.decided_by_telegram_id = int(getattr(admin_user, "id", 0) or 0) or None
        tx.decided_by_name = _admin_name(admin_user)
    if note:
        stamp = f"[{now.isoformat()} | {tx.decided_by_name or 'admin'}] {note}"
        tx.admin_notes = ((tx.admin_notes or "").rstrip() + "\n" + stamp).strip()


class WithdrawFlow:
    """واجهة سحب محفظة البوت."""

    # ─── دخول ─────────────────────────────────────────────

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        balance = float(user.balance or 0)
        min_w = float(Config.MIN_WITHDRAWAL)

        # احتفظ برسالة الشاشة السابقة إن وجدت لتعديلها
        prev_msg = context.user_data.get("wd_msg_id")
        context.user_data.clear()
        if prev_msg:
            context.user_data["wd_msg_id"] = prev_msg

        if balance < min_w:
            text = (
                "🏧 المحفظة ما فيها شي ينسحب\n\n"
                f"💎 رصيدك الحالي {format_currency(balance)}\n"
                f"📌 اقل مبلغ للسحب {format_currency(min_w)}\n\n"
                "المحاسب فتح الدرج… هوا بس 😂"
            )
            await WithdrawFlow._show(
                update, context, text, Keyboards.withdraw_empty_menu()
            )
            return

        context.user_data["operation"] = "wallet_withdraw"
        context.user_data["state"] = "waiting_for_withdraw_amount"
        text = (
            "🏧 سحب من محفظة البوت\n\n"
            f"💎 رصيدك الحالي {format_currency(balance)}\n"
            f"📌 اقل مبلغ للسحب {format_currency(min_w)}\n\n"
            "اكتب المبلغ — أرقام فقط"
        )
        await WithdrawFlow._show(
            update, context, text, Keyboards.withdraw_amount_menu()
        )

    @staticmethod
    async def withdraw_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        amount = float(user.balance or 0)
        await WithdrawFlow._accept_amount(update, context, amount, from_callback=True)

    @staticmethod
    async def handle_amount_text(
        update: Update, context: ContextTypes.DEFAULT_TYPE, raw: str
    ):
        raw = (raw or "").strip().replace(",", "").replace(" ", "")
        if not re.fullmatch(r"\d+(\.\d+)?", raw):
            await WithdrawFlow._show(
                update,
                context,
                "🤨 هاد مو مبلغ\n\n"
                "اكتب أرقام فقط مثل\n"
                "200\n\n"
                "بلا فواصل وبلا شرح",
                Keyboards.withdraw_amount_menu(),
            )
            return
        try:
            amount = float(raw)
        except ValueError:
            await WithdrawFlow._show(
                update,
                context,
                "🤨 هاد مو مبلغ\n\nاكتب أرقام فقط مثل\n200",
                Keyboards.withdraw_amount_menu(),
            )
            return
        await WithdrawFlow._accept_amount(update, context, amount, from_callback=False)

    @staticmethod
    async def _accept_amount(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        amount: float,
        from_callback: bool,
    ):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        balance = float(user.balance or 0)
        min_w = float(Config.MIN_WITHDRAWAL)

        if amount < min_w:
            context.user_data["state"] = "waiting_for_withdraw_amount"
            context.user_data["operation"] = "wallet_withdraw"
            await WithdrawFlow._show(
                update,
                context,
                "🤨 المبلغ صغير شوي\n\n"
                f"اقل مبلغ للسحب هو {format_currency(min_w)}\n\n"
                "كبره شوي",
                Keyboards.withdraw_amount_menu(),
            )
            return

        if amount > balance:
            context.user_data["state"] = "waiting_for_withdraw_amount"
            context.user_data["operation"] = "wallet_withdraw"
            await WithdrawFlow._show(
                update,
                context,
                "😅 على مهلك\n\n"
                f"طلبت {format_currency(amount)}\n"
                f"ورصيدك كله {format_currency(balance)}\n\n"
                "المحفظة ما بتستدين 😂",
                Keyboards.withdraw_amount_menu(),
            )
            return

        context.user_data["amount"] = float(amount)
        context.user_data["operation"] = "wallet_withdraw"
        context.user_data.pop("state", None)
        await WithdrawFlow.show_methods(update, context)

    @staticmethod
    async def show_methods(update: Update, context: ContextTypes.DEFAULT_TYPE):
        amount = context.user_data.get("amount")
        if not amount:
            await WithdrawFlow.start(update, context)
            return
        text = (
            "💸 اختار طريقة استلام المبلغ\n\n"
            f"💰 مبلغ السحب {format_currency(float(amount))}\n\n"
            "اختار الطريقة اللي بدك توصلك عليها"
        )
        await WithdrawFlow._show(
            update, context, text, Keyboards.withdraw_methods_menu()
        )

    # ─── طرق الاستلام ─────────────────────────────────────

    @staticmethod
    async def choose_method(
        update: Update, context: ContextTypes.DEFAULT_TYPE, method: str
    ):
        if method == "other":
            await WithdrawFlow._show(
                update,
                context,
                "🧩 طرق ثانية\n\n"
                "المتاح الآن: سيرياتيل / شام كاش / عملات رقمية.\n"
                "لحالة خاصة تواصل مع الدعم.",
                Keyboards.withdraw_methods_menu(),
            )
            return

        amount = context.user_data.get("amount")
        if not amount:
            await WithdrawFlow.start(update, context)
            return

        context.user_data["method"] = method
        context.user_data["operation"] = "wallet_withdraw"

        if method == "syriatel_cash":
            context.user_data["state"] = "waiting_for_withdraw_destination"
            text = (
                "📱 سحب عن طريق سيرياتيل كاش\n\n"
                "ابعت رقم سيرياتيل كاش\n\n"
                "مثال: 09XXXXXXXX\n\n"
                "راجع الرقم منيح"
            )
            await WithdrawFlow._show(
                update, context, text, Keyboards.withdraw_dest_back_menu()
            )
            return

        if method == "shamcash":
            context.user_data["state"] = "waiting_for_withdraw_destination"
            text = (
                "💠 سحب عن طريق شام كاش\n\n"
                "ابعت عنوان محفظة شام كاش\n\n"
                "انسخه مثل ما هو — لا تكتبه من الذاكرة"
            )
            await WithdrawFlow._show(
                update, context, text, Keyboards.withdraw_dest_back_menu()
            )
            return

        if method == "usdt":
            context.user_data["state"] = "waiting_for_crypto_choice"
            text = (
                "🌐 سحب عملات رقمية\n\n"
                "اختار العملة والشبكة\n\n"
                "مهم: الشبكة الغلط بتاخد المصاري"
            )
            await WithdrawFlow._show(
                update, context, text, Keyboards.withdraw_crypto_menu()
            )
            return

        await WithdrawFlow.show_methods(update, context)

    @staticmethod
    async def choose_crypto(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        currency: str,
        network: str,
    ):
        context.user_data["crypto_currency"] = currency
        context.user_data["crypto_network"] = network
        context.user_data["method"] = "usdt"
        context.user_data["state"] = "waiting_for_withdraw_destination"
        text = (
            f"🌐 سحب {currency} · {network}\n\n"
            "ابعت عنوان المحفظة\n\n"
            "انسخه كامل من تطبيقك"
        )
        await WithdrawFlow._show(
            update, context, text, Keyboards.withdraw_dest_back_menu()
        )

    @staticmethod
    async def handle_destination(
        update: Update, context: ContextTypes.DEFAULT_TYPE, raw: str
    ):
        method = context.user_data.get("method")
        amount = context.user_data.get("amount")
        if not method or not amount:
            await WithdrawFlow._show(
                update,
                context,
                "انتهت الجلسة. ابدأ السحب من جديد.",
                Keyboards.start_menu(),
            )
            context.user_data.clear()
            return

        dest = (raw or "").strip()
        if method == "syriatel_cash":
            dest, err = SavedAccountsHandler.validate_account("syriatel_cash", dest)
            if err:
                await WithdrawFlow._show(
                    update,
                    context,
                    "🤨 الرقم مو سوري أو صيغته غلط\n\n"
                    "المطلوب: 09XXXXXXXX\n"
                    "10 أرقام ويبدأ بـ 09",
                    Keyboards.withdraw_dest_back_menu(),
                )
                return
        elif method == "shamcash":
            dest, err = SavedAccountsHandler.validate_account("shamcash", dest)
            if err:
                await WithdrawFlow._show(
                    update,
                    context,
                    (err or "عنوان شام كاش غير صالح").replace("`", ""),
                    Keyboards.withdraw_dest_back_menu(),
                )
                return
        else:
            if len(dest) < 8:
                await WithdrawFlow._show(
                    update,
                    context,
                    "🤨 العنوان قصير زيادة.\nانسخه كامل من المحفظة.",
                    Keyboards.withdraw_dest_back_menu(),
                )
                return

        context.user_data["withdraw_destination"] = dest
        context.user_data.pop("state", None)
        await WithdrawFlow.show_review(update, context)

    @staticmethod
    async def show_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        amount = float(context.user_data.get("amount") or 0)
        method = context.user_data.get("method")
        dest = context.user_data.get("withdraw_destination") or "—"
        fee, net, profit = fee_breakdown(amount)
        balance = float(user.balance or 0) if user else 0

        method_txt = method_label(method)
        if method == "usdt":
            cur = context.user_data.get("crypto_currency", "USDT")
            netw = context.user_data.get("crypto_network", "TRC20")
            method_txt = f"🌐 {cur} / {netw}"

        text = (
            "🧾 راجع طلب السحب\n\n"
            f"💎 رصيدك الحالي {format_currency(balance)}\n"
            f"💰 مبلغ السحب {format_currency(amount)}\n"
            f"📈 الربح المحتسب ضمن المبلغ {format_currency(profit)}\n"
            f"🧮 العمولة {Config.WITHDRAWAL_FEE_PERCENTAGE:g}% من المبلغ المسحوب "
            f"{format_currency(fee)}\n"
            f"✅ الصافي اللي رح تستلمه {format_currency(net)}\n\n"
            f"💳 طريقة الاستلام {method_txt}\n"
            f"📍 بيانات الاستلام {tg_code(dest)}\n\n"
            "راجع قبل التأكيد — بعد التنفيذ ما بينلغى بسهولة"
        )
        context.user_data["state"] = "waiting_withdraw_confirm"
        context.user_data["fee_amount"] = fee
        context.user_data["net_amount"] = net
        context.user_data["profit_amount"] = profit

        await WithdrawFlow._show(
            update,
            context,
            text,
            Keyboards.withdraw_review_menu(),
            parse_mode="HTML",
        )

    # ─── تأكيد / تنفيذ ────────────────────────────────────

    @staticmethod
    async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if context.user_data.get("withdraw_submit_lock"):
            try:
                await update.callback_query.answer(
                    "✋ الطلب موجود اصلًا", show_alert=True
                )
            except TelegramError:
                pass
            return
        context.user_data["withdraw_submit_lock"] = True

        user = db.get_user(update.effective_user.id)
        amount = float(context.user_data.get("amount") or 0)
        method = context.user_data.get("method")
        dest = context.user_data.get("withdraw_destination")
        # العمولة متوقعة فقط — ما بتنخصم نهائي إلا بعد التقبيض
        fee, net, profit = fee_breakdown(amount)
        crypto_c = context.user_data.get("crypto_currency")
        crypto_n = context.user_data.get("crypto_network")

        if not user or not amount or not method or not dest:
            context.user_data.clear()
            await WithdrawFlow._show(
                update,
                context,
                "انتهت الجلسة. ابدأ السحب من جديد.",
                Keyboards.start_menu(),
            )
            return

        if WithdrawFlow._has_duplicate(user.id, amount, method, dest):
            try:
                await update.callback_query.answer(
                    "✋ الطلب موجود اصلًا",
                    show_alert=True,
                )
            except TelegramError:
                pass
            await WithdrawFlow._show(
                update,
                context,
                "✋ الطلب موجود اصلًا\n\nلا تعملنا نسختين من نفس الطلب",
                Keyboards.start_menu(),
            )
            context.user_data.clear()
            return

        session = db.get_session()
        try:
            db_user = session.query(User).filter(User.id == user.id).first()
            if not db_user or float(db_user.balance or 0) < amount:
                await WithdrawFlow._show(
                    update,
                    context,
                    "😅 الرصيد ما عاد يكفي. ابدأ من جديد.",
                    Keyboards.start_menu(),
                )
                context.user_data.clear()
                return

            # خصم من المتاح → محجوز (بدون خصم عمولة نهائي)
            db_user.balance = float(db_user.balance or 0) - amount
            db_user.reserved_balance = float(db_user.reserved_balance or 0) + amount

            method_txt = method_label(method)
            if crypto_c and crypto_n:
                method_txt = f"{crypto_c}/{crypto_n}"

            tx = Transaction(
                user_id=user.id,
                transaction_type="withdraw",
                amount=amount,
                method=method,
                status=ST_PENDING_REVIEW,
                withdraw_destination=dest,
                fee_amount=fee,  # متوقعة
                net_amount=net,  # متوقع
                profit_amount=profit,
                crypto_currency=crypto_c,
                crypto_network=crypto_n,
                description=(
                    f"سحب محفظة — {method_txt} — وجهة {dest} — "
                    f"عمولة متوقعة {fee} — صافي متوقع {net}"
                ),
            )
            session.add(tx)
            session.commit()
            session.refresh(tx)
            order_id = tx.id
        except Exception:
            session.rollback()
            logger.exception("فشل إنشاء طلب سحب")
            context.user_data.clear()
            await WithdrawFlow._show(
                update,
                context,
                "❌ فشل تثبيت الطلب. حاول مرة ثانية.",
                Keyboards.start_menu(),
            )
            return
        finally:
            session.close()

        try:
            if method in ("syriatel_cash", "shamcash"):
                db.add_saved_account(user.id, method, dest)
        except Exception:
            pass

        wd_msg = context.user_data.get("wd_msg_id")
        context.user_data.clear()
        if wd_msg:
            context.user_data["wd_msg_id"] = wd_msg
        context.user_data["pending_withdraw_id"] = order_id

        text = (
            "⏳ وصل طلب السحب\n\n"
            f"💰 مبلغ السحب {format_currency(amount)}\n"
            f"🧮 العمولة المتوقعة {format_currency(fee)}\n"
            f"✅ الصافي المتوقع {format_currency(net)}\n"
            f"🧾 رقم الطلب {tg_code(order_id)}\n\n"
            "رح يوصلك إشعار أول ما يتم التقبيض"
        )
        await WithdrawFlow._show(
            update,
            context,
            text,
            Keyboards.withdraw_submitted_menu(order_id),
            parse_mode="HTML",
        )

        try:
            await WithdrawFlow._notify_admins_new(context, order_id)
        except Exception:
            logger.exception("فشل إشعار الإدمن بطلب سحب")

    # ─── إلغاء من المستخدم ────────────────────────────────

    @staticmethod
    async def ask_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int):
        user = db.get_user(update.effective_user.id)
        tx = WithdrawFlow._get_tx(order_id)
        if not tx or not user or tx.user_id != user.id:
            await update.callback_query.answer("الطلب غير موجود", show_alert=True)
            return
        if tx.status not in ACTIVE_CANCELLABLE:
            await WithdrawFlow._show(
                update,
                context,
                "❌ ما عاد فينا نلغي السحب\n\n"
                "العملية اتقبضت أو فاتت بالتنفيذ النهائي\n\n"
                f"🧾 رقم الطلب {tg_code(order_id)}",
                Keyboards.withdraw_locked_menu(order_id),
                parse_mode="HTML",
            )
            return

        text = (
            "↩️ طلب إلغاء السحب\n\n"
            "رح نبعت طلبك للإدارة\n\n"
            "إذا المبلغ لسا ما اتقبض منرجعلك كامل المبلغ المحجوز\n"
            "بدون أي عمولة\n\n"
            "إذا التقبيض تم ما عاد فينا نرجع العملية"
        )
        await WithdrawFlow._show(
            update, context, text, Keyboards.withdraw_cancel_confirm_menu(order_id)
        )

    @staticmethod
    async def confirm_cancel_request(
        update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int
    ):
        user = db.get_user(update.effective_user.id)
        session = db.get_session()
        try:
            tx = session.query(Transaction).filter(Transaction.id == order_id).first()
            if not tx or not user or tx.user_id != user.id:
                await update.callback_query.answer("الطلب غير موجود", show_alert=True)
                return
            if tx.status in BLOCK_CANCEL_APPROVE:
                await WithdrawFlow._show(
                    update,
                    context,
                    "❌ ما عاد فينا نلغي السحب\n\n"
                    "العملية اتقبضت أو فاتت بالتنفيذ النهائي\n\n"
                    f"🧾 رقم الطلب {tg_code(order_id)}",
                    Keyboards.withdraw_locked_menu(order_id),
                    parse_mode="HTML",
                )
                return
            if tx.status == ST_CANCEL_REQUESTED:
                await update.callback_query.answer(
                    "طلب الإلغاء موجود أصلًا", show_alert=True
                )
                return
            if tx.status not in ACTIVE_CANCELLABLE:
                await update.callback_query.answer("ما عاد ممكن الإلغاء", show_alert=True)
                return

            tx.status = ST_CANCEL_REQUESTED
            tx.cancel_requested_at = datetime.utcnow()
            session.commit()
        finally:
            session.close()

        text = (
            "⏳ وصل طلب الإلغاء\n\n"
            "الإدارة رح تتأكد إذا المبلغ لسا ما اتقبض\n"
            "إذا لسا معنا بيرجع كامل الرصيد لمحفظتك بدون عمولة\n\n"
            f"🧾 رقم الطلب {tg_code(order_id)}"
        )
        await WithdrawFlow._show(
            update,
            context,
            text,
            Keyboards.withdraw_submitted_menu(order_id, can_cancel=False),
            parse_mode="HTML",
        )
        try:
            await WithdrawFlow._notify_admins_cancel(context, order_id)
        except Exception:
            logger.exception("فشل إشعار إلغاء سحب")

    @staticmethod
    async def keep_withdraw(
        update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int
    ):
        await WithdrawFlow.track_order(update, context, order_id)

    @staticmethod
    async def track_order(
        update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int
    ):
        tx = WithdrawFlow._get_tx(order_id)
        if not tx:
            await update.callback_query.answer("الطلب غير موجود", show_alert=True)
            return
        fee = float(tx.fee_amount or fee_breakdown(tx.amount)[0])
        net = float(tx.net_amount or fee_breakdown(tx.amount)[1])
        profit = float(tx.profit_amount or 0)
        text = (
            f"📋 متابعة الطلب {tg_code(order_id)}\n\n"
            f"الحالة: {status_label(tx.status)}\n\n"
            f"💰 مبلغ السحب {format_currency(tx.amount)}\n"
            f"📈 الربح المحتسب {format_currency(profit)}\n"
            f"🧮 العمولة {format_currency(fee)}\n"
            f"✅ الصافي {format_currency(net)}\n"
            f"💳 {method_label(tx.method)}\n"
            f"📍 {tg_code(tx.withdraw_destination or '—')}"
        )
        if tx.decided_by_name and tx.decided_at:
            text += (
                f"\n\n👤 قرار الإدارة: {tx.decided_by_name}"
                f"\n🕒 {tx.decided_at}"
            )
        can_cancel = tx.status in ACTIVE_CANCELLABLE
        await WithdrawFlow._show(
            update,
            context,
            text,
            Keyboards.withdraw_submitted_menu(order_id, can_cancel=can_cancel),
            parse_mode="HTML",
        )

    # ─── قرارات الإدارة ───────────────────────────────────

    @staticmethod
    async def admin_approve_cancel(context, order_id: int, admin_user=None):
        session = db.get_session()
        try:
            tx = session.query(Transaction).filter(Transaction.id == order_id).first()
            if not tx:
                return False, "الطلب غير موجود"
            # ممنوع الموافقة على الإلغاء بعد التقبيض / أثناء التنفيذ
            if tx.status in BLOCK_CANCEL_APPROVE:
                return False, "ممنوع: تم التقبيض أو الطلب قيد التنفيذ"
            if tx.status != ST_CANCEL_REQUESTED:
                return False, f"حالة الطلب الآن: {status_label(tx.status)}"

            user = session.query(User).filter(User.id == tx.user_id).first()
            amount = float(tx.amount or 0)
            if user:
                # إرجاع كامل المحجوز — بدون عمولة
                user.balance = float(user.balance or 0) + amount
                user.reserved_balance = max(
                    0.0, float(user.reserved_balance or 0) - amount
                )
            tx.status = ST_CANCELLED
            # العمولة ملغاة بالكامل — ما انخصمت أصلاً
            tx.fee_amount = 0.0
            tx.net_amount = 0.0
            _stamp_decision(tx, admin_user, "موافقة على إلغاء السحب — إرجاع كامل بدون عمولة")
            session.commit()
            telegram_id = user.telegram_id if user else None
            new_balance = float(user.balance or 0) if user else 0
        finally:
            session.close()

        if telegram_id:
            text = (
                "✅ تم إلغاء السحب\n\n"
                "رجعنا كامل المبلغ المحجوز لمحفظتك بدون عمولة\n\n"
                f"💰 المبلغ الراجع {format_currency(amount)}\n"
                f"💎 رصيدك الحالي {format_currency(new_balance)}\n"
                f"🧾 رقم الطلب {tg_code(order_id)}"
            )
            try:
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=Keyboards.withdraw_cancelled_done_menu(),
                )
            except TelegramError:
                pass
        return True, "تم إلغاء السحب وإرجاع المبلغ"

    @staticmethod
    async def admin_reject_cancel(
        context, order_id: int, reason: str = "", paid: bool = False, admin_user=None
    ):
        session = db.get_session()
        try:
            tx = session.query(Transaction).filter(Transaction.id == order_id).first()
            if not tx:
                return False, "الطلب غير موجود"
            user = session.query(User).filter(User.id == tx.user_id).first()
            telegram_id = user.telegram_id if user else None

            # بعد التقبيض / قيد التنفيذ — رفض إلغاء فقط (بدون تغيير حالة السحب المدفوع)
            if paid or tx.status in BLOCK_CANCEL_APPROVE:
                tx.cancel_rejection_reason = reason or "تم التقبيض / قيد التنفيذ"
                # لا نلمس حالة paid/processing إن كانت كذلك
                if tx.status == ST_CANCEL_REQUESTED:
                    tx.status = ST_PAID if paid else ST_AWAITING_PAYOUT
                _stamp_decision(tx, admin_user, f"رفض إلغاء بعد التقبيض/تنفيذ — {reason}")
                session.commit()
                msg = (
                    "❌ ما عاد فينا نلغي السحب\n\n"
                    "العملية اتقبضت أو فاتت بالتنفيذ النهائي\n\n"
                    f"🧾 رقم الطلب {tg_code(order_id)}"
                )
                markup = Keyboards.withdraw_locked_menu(order_id)
            else:
                if tx.status != ST_CANCEL_REQUESTED:
                    return False, f"حالة الطلب: {status_label(tx.status)}"
                tx.cancel_rejection_reason = reason or "رفض إداري"
                tx.status = ST_AWAITING_PAYOUT
                _stamp_decision(tx, admin_user, f"رفض طلب الإلغاء — {reason}")
                session.commit()
                msg = (
                    "❌ ما تمت الموافقة على الإلغاء\n\n"
                    f"السبب\n{reason or '—'}\n\n"
                    "طلب السحب لسا شغال بشكل طبيعي\n\n"
                    f"🧾 رقم الطلب {tg_code(order_id)}"
                )
                markup = Keyboards.withdraw_submitted_menu(order_id)
        finally:
            session.close()

        if telegram_id:
            try:
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=msg,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            except TelegramError:
                pass
        return True, "تم رفض طلب الإلغاء"

    @staticmethod
    async def admin_mark_processing(context, order_id: int, admin_user=None):
        session = db.get_session()
        try:
            tx = session.query(Transaction).filter(Transaction.id == order_id).first()
            if not tx:
                return False, "غير موجود"
            if tx.status in (ST_PAID, ST_CANCELLED, ST_REJECTED, "completed", "failed", "cancelled"):
                return False, f"لا يمكن: {status_label(tx.status)}"
            prev = tx.status
            # إذا كان فيه طلب إلغاء — يُرفض تلقائياً عند الدخول للتنفيذ
            if prev == ST_CANCEL_REQUESTED:
                tx.cancel_rejection_reason = "فات للتنفيذ أثناء طلب الإلغاء"
            tx.status = ST_PROCESSING
            _stamp_decision(tx, admin_user, "تحويل لقيد التنفيذ")
            session.commit()
        finally:
            session.close()
        return True, "قيد التنفيذ"

    @staticmethod
    async def admin_mark_paid(context, order_id: int, admin_user=None):
        """تأكيد التقبيض الحقيقي فقط — هنا تظهر رسالة نجاح السحب وتُثبت العمولة."""
        session = db.get_session()
        was_cancel = False
        try:
            tx = session.query(Transaction).filter(Transaction.id == order_id).first()
            if not tx:
                return False, "غير موجود"
            if tx.status == ST_PAID or tx.status == "completed":
                return False, "تم التقبيض مسبقاً"
            if tx.status in (ST_CANCELLED, ST_REJECTED, "cancelled", "failed"):
                return False, f"لا يمكن: {status_label(tx.status)}"

            user = session.query(User).filter(User.id == tx.user_id).first()
            if tx.status == ST_CANCEL_REQUESTED:
                was_cancel = True
                tx.cancel_rejection_reason = "تم التقبيض أثناء طلب الإلغاء — رُفض الإلغاء تلقائياً"

            amount = float(tx.amount or 0)
            # تثبيت العمولة عند نجاح التقبيض فقط (10% من مبلغ السحب)
            fee, net, profit = fee_breakdown(amount)
            tx.fee_amount = fee
            tx.net_amount = net
            tx.profit_amount = float(tx.profit_amount or profit)

            if user:
                user.reserved_balance = max(
                    0.0, float(user.reserved_balance or 0) - amount
                )
            method_txt = method_label(tx.method)
            if tx.crypto_currency and tx.crypto_network:
                method_txt = f"{tx.crypto_currency}/{tx.crypto_network}"

            tx.status = ST_PAID
            _stamp_decision(
                tx,
                admin_user,
                f"تأكيد التقبيض — عمولة {fee} — صافي {net}",
            )
            telegram_id = user.telegram_id if user else None
            session.commit()
        finally:
            session.close()

        if telegram_id and was_cancel:
            try:
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=(
                        "❌ ما عاد فينا نلغي السحب\n\n"
                        "العملية اتقبضت\n\n"
                        f"🧾 رقم الطلب {tg_code(order_id)}"
                    ),
                    parse_mode="HTML",
                    reply_markup=Keyboards.withdraw_locked_menu(order_id),
                )
            except TelegramError:
                pass

        if telegram_id:
            text = (
                "✅ تم السحب بنجاح\n\n"
                f"💰 مبلغ السحب {format_currency(amount)}\n"
                f"📈 الربح المحتسب {format_currency(profit)}\n"
                f"🧮 العمولة {format_currency(fee)}\n"
                f"✅ الصافي اللي استلمته {format_currency(net)}\n"
                f"💳 طريقة الاستلام {method_txt}\n"
                f"🧾 رقم الطلب {tg_code(order_id)}"
            )
            try:
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=Keyboards.withdraw_paid_menu(order_id),
                )
            except TelegramError:
                pass
        return True, "تم التقبيض"

    @staticmethod
    async def admin_reject_withdraw(context, order_id: int, reason: str = "", admin_user=None):
        session = db.get_session()
        try:
            tx = session.query(Transaction).filter(Transaction.id == order_id).first()
            if not tx:
                return False, "غير موجود"
            if tx.status in (ST_PAID, "completed"):
                return False, "تم التقبيض مسبقاً — ما عاد ممكن الرفض مع إرجاع"
            user = session.query(User).filter(User.id == tx.user_id).first()
            amount = float(tx.amount or 0)
            already_closed = tx.status in (
                ST_CANCELLED,
                ST_REJECTED,
                "cancelled",
                "failed",
            )
            if user and not already_closed:
                # إرجاع كامل المحجوز بدون عمولة
                user.balance = float(user.balance or 0) + amount
                user.reserved_balance = max(
                    0.0, float(user.reserved_balance or 0) - amount
                )
            tx.status = ST_REJECTED
            tx.fee_amount = 0.0
            tx.net_amount = 0.0
            _stamp_decision(
                tx, admin_user, f"رفض السحب قبل التقبيض — إرجاع كامل — {reason}"
            )
            new_balance = float(user.balance or 0) if user else 0
            telegram_id = user.telegram_id if user else None
            session.commit()
        finally:
            session.close()

        if telegram_id:
            text = (
                "❌ ما قدرنا ننفذ طلب السحب\n\n"
                f"السبب\n{reason or '—'}\n\n"
                "رجعنا كامل المبلغ المحجوز لمحفظتك بدون عمولة\n\n"
                f"💰 المبلغ الراجع {format_currency(amount)}\n"
                f"💎 رصيدك الحالي {format_currency(new_balance)}\n"
                f"🧾 رقم الطلب {tg_code(order_id)}"
            )
            try:
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=Keyboards.withdraw_rejected_menu(),
                )
            except TelegramError:
                pass
        return True, "مرفوض مع إرجاع الرصيد"

    # ─── مساعدات ──────────────────────────────────────────

    @staticmethod
    def _get_tx(order_id: int) -> Optional[Transaction]:
        session = db.get_session()
        try:
            tx = session.query(Transaction).filter(Transaction.id == order_id).first()
            return db._detach(session, tx)
        finally:
            session.close()

    @staticmethod
    def _has_duplicate(user_id: int, amount: float, method: str, dest: str) -> bool:
        session = db.get_session()
        try:
            q = (
                session.query(Transaction)
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.transaction_type == "withdraw",
                    Transaction.amount == amount,
                    Transaction.method == method,
                    Transaction.withdraw_destination == dest,
                    Transaction.status.in_(list(LEGACY_ACTIVE)),
                )
                .first()
            )
            return bool(q)
        finally:
            session.close()

    @staticmethod
    async def _show(update, context, text, markup, parse_mode=None):
        """عدّل نفس رسالة المسار قدر الإمكان بدل إغراق الشات."""
        chat_id = update.effective_chat.id if update.effective_chat else None
        msg_id = context.user_data.get("wd_msg_id")

        # كولباك → تعديل رسالة الزر مباشرة
        if update.callback_query and update.callback_query.message:
            await safe_edit_callback_message(
                update,
                text,
                reply_markup=markup,
                parse_mode=parse_mode,
                context=context,
            )
            try:
                context.user_data["wd_msg_id"] = update.callback_query.message.message_id
            except Exception:
                pass
            return

        # رد نصي → حاول تعديل شاشة السحب السابقة
        if chat_id and msg_id:
            try:
                kwargs = {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "reply_markup": markup,
                }
                if parse_mode:
                    kwargs["parse_mode"] = parse_mode
                await context.bot.edit_message_text(**kwargs)
                return
            except TelegramError:
                pass

        # أول رسالة / فشل التعديل → أرسل جديدة واحفظ معرفها
        target = update.effective_message or update.message
        if not target:
            return
        kwargs = {"text": text, "reply_markup": markup}
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        try:
            sent = await target.reply_text(**kwargs)
            context.user_data["wd_msg_id"] = sent.message_id
        except TelegramError as exc:
            if parse_mode and "parse" in str(exc).lower():
                kwargs.pop("parse_mode", None)
                sent = await target.reply_text(**kwargs)
                context.user_data["wd_msg_id"] = sent.message_id
            else:
                raise

    @staticmethod
    async def _notify_admins_new(context, order_id: int):
        tx = WithdrawFlow._get_tx(order_id)
        if not tx:
            return
        user = db.get_user_by_db_id(tx.user_id) if hasattr(db, "get_user_by_db_id") else None
        if not user:
            session = db.get_session()
            try:
                user = session.query(User).filter(User.id == tx.user_id).first()
                user = db._detach(session, user)
            finally:
                session.close()
        fee = float(tx.fee_amount or 0)
        net = float(tx.net_amount or 0)
        profit = float(tx.profit_amount or 0)
        text = (
            f"🏧 طلب سحب جديد\n"
            f"🧾 رقم الطلب {order_id}\n\n"
            f"الحالة: {status_label(tx.status)}\n"
            f"المستخدم: {getattr(user, 'first_name', '')}\n"
            f"آيدي تليغرام: {getattr(user, 'telegram_id', '')}\n"
            f"المبلغ: {format_currency(tx.amount)}\n"
            f"الربح: {format_currency(profit)}\n"
            f"العمولة (متوقعة): {format_currency(fee)}\n"
            f"الصافي (متوقع): {format_currency(net)}\n"
            f"الطريقة: {method_label(tx.method)}\n"
            f"الوجهة: {tx.withdraw_destination}\n"
            f"وقت الطلب: {tx.created_at}\n"
        )
        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=text,
                    reply_markup=Keyboards.admin_withdraw_order_menu(order_id),
                )
            except TelegramError:
                pass

    @staticmethod
    async def _notify_admins_cancel(context, order_id: int):
        tx = WithdrawFlow._get_tx(order_id)
        if not tx:
            return
        session = db.get_session()
        try:
            user = session.query(User).filter(User.id == tx.user_id).first()
            user = db._detach(session, user)
        finally:
            session.close()
        fee = float(tx.fee_amount or 0)
        net = float(tx.net_amount or 0)
        profit = float(tx.profit_amount or 0)
        text = (
            f"↩️ طلب إلغاء سحب\n"
            f"🧾 رقم الطلب {order_id}\n\n"
            f"المستخدم: {getattr(user, 'first_name', '')}\n"
            f"آيدي تليغرام: {getattr(user, 'telegram_id', '')}\n"
            f"مبلغ السحب: {format_currency(tx.amount)}\n"
            f"الربح المحتسب: {format_currency(profit)}\n"
            f"العمولة: {format_currency(fee)}\n"
            f"الصافي: {format_currency(net)}\n"
            f"طريقة الاستلام: {method_label(tx.method)}\n"
            f"بيانات الاستلام: {tx.withdraw_destination}\n"
            f"وقت طلب السحب: {tx.created_at}\n"
            f"وقت طلب الإلغاء: {tx.cancel_requested_at}\n"
            f"حالة التقبيض: {status_label(tx.status)}\n"
        )
        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=text,
                    reply_markup=Keyboards.admin_withdraw_cancel_menu(order_id),
                )
            except TelegramError:
                pass
