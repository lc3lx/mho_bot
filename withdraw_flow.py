"""
سحب / تقبيض محفظة البوت (فضي محفظتي) — رصيد محجوز + طرق قابلة للتوسعة.
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
import payout_service as ps
import withdraw_ops as ops
from utils import (
    format_currency,
    get_user_display_name,
    safe_edit_callback_message,
    tg_code,
)

logger = logging.getLogger(__name__)
db = DatabaseManager()

# حالات التقبيض الثابتة
ST_PENDING_REVIEW = ops.ST_PENDING_REVIEW
ST_AWAITING_PAYOUT = ops.ST_AWAITING_PAYOUT
ST_CANCEL_REQUESTED = ops.ST_CANCEL_REQUESTED
ST_PROCESSING = ops.ST_PROCESSING
ST_PAID = ops.ST_PAID
ST_CANCELLED = ops.ST_CANCELLED
ST_REJECTED = ops.ST_REJECTED

LEGACY_ACTIVE = {
    "pending",
    ST_PENDING_REVIEW,
    ST_AWAITING_PAYOUT,
    ST_CANCEL_REQUESTED,
    ST_PROCESSING,
}
ACTIVE_CANCELLABLE = ops.ACTIVE_CANCELLABLE
BLOCK_CANCEL_APPROVE = ops.BLOCK_CANCEL_APPROVE

STATUS_AR = ops.STATUS_AR


def status_label(status: str) -> str:
    return ops.status_label(status)


def method_label(method: str) -> str:
    return ops.method_label(method)


def fee_breakdown(amount: float) -> tuple[float, float, float]:
    return ops.fee_breakdown(amount)


def _admin_name(admin_user) -> str:
    return ops.admin_name(admin_user)


def _stamp_decision(tx: Transaction, admin_user, note: str = ""):
    ops.stamp_decision(tx, admin_user, note)


def _order_ref(tx: Transaction) -> str:
    return ops.order_ref(tx)


class WithdrawFlow:
    """واجهة سحب محفظة البوت."""

    # ─── دخول ─────────────────────────────────────────────

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        balance = float(user.balance or 0)
        min_w = float(ps.get_min_withdraw())

        # احتفظ برسالة الشاشة السابقة إن وجدت لتعديلها
        prev_msg = context.user_data.get("wd_msg_id")
        context.user_data.clear()
        if prev_msg:
            context.user_data["wd_msg_id"] = prev_msg

        if balance < min_w:
            # نخلي الحالة فعّالة حتى لو الرصيد فاضي — أي رقم يطلعله خطأ واضح
            context.user_data["operation"] = "wallet_withdraw"
            context.user_data["state"] = "waiting_for_withdraw_amount"
            text = (
                "🏧 المحفظة ما فيها شي ينسحب\n\n"
                f"💎 رصيدك الحالي {format_currency(balance)}\n"
                f"📌 اقل مبلغ للسحب {format_currency(min_w)}\n\n"
                "المحاسب فتح الدرج\n"
                "ما لقى غير هوا 😂"
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
            "اكتب المبلغ اللي بدك تسحبه\n"
            "ارقام فقط\n\n"
            "والمحاسب رح يتصرف كأنه كان ناطرك من الصبح 😂"
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
        min_w = float(ps.get_min_withdraw())

        if amount < min_w:
            context.user_data["state"] = "waiting_for_withdraw_amount"
            context.user_data["operation"] = "wallet_withdraw"
            if balance < min_w:
                await WithdrawFlow._show(
                    update,
                    context,
                    "🏧 المحفظة ما فيها شي ينسحب\n\n"
                    f"💎 رصيدك الحالي {format_currency(balance)}\n"
                    f"📌 اقل مبلغ للسحب {format_currency(min_w)}\n\n"
                    "عبّي المحفظة أول شي",
                    Keyboards.withdraw_empty_menu(),
                )
            else:
                await WithdrawFlow._show(
                    update,
                    context,
                    "🤨 المبلغ صغير شوي\n\n"
                    f"اقل مبلغ للسحب هو {format_currency(min_w)}\n\n"
                    "كبره شوي\n\n"
                    "المحاسب ما بيطلع من مكتبه عالفاضي 😂",
                    Keyboards.withdraw_amount_menu(),
                )
            return

        if amount > balance:
            context.user_data["state"] = "waiting_for_withdraw_amount"
            context.user_data["operation"] = "wallet_withdraw"
            await WithdrawFlow._show(
                update,
                context,
                "🚫 المبلغ اكبر من رصيده\n\n"
                f"طلبت {format_currency(amount)}\n"
                f"ورصيدك كله {format_currency(balance)}\n\n"
                "المحفظة ما بتستدين حتى من اقرب الناس 😂",
                Keyboards.withdraw_empty_menu()
                if balance < min_w
                else Keyboards.withdraw_amount_menu(),
            )
            return

        lim_err = ops.check_user_limits(user, amount)
        if lim_err:
            context.user_data["state"] = "waiting_for_withdraw_amount"
            context.user_data["operation"] = "wallet_withdraw"
            await WithdrawFlow._show(
                update, context, lim_err, Keyboards.withdraw_amount_menu()
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
        methods = ps.list_methods(enabled_only=True)
        if not methods:
            methods = [type("M", (), {"code": "shamcash", "name": "💠 شام كاش"})()]
        names = "\n".join(f"{m.name}" for m in methods)
        text = (
            "💸 طريقة التقبيض\n\n"
            f"💰 مبلغ السحب {format_currency(float(amount))}\n\n"
            "حاليا التقبيض متوفر عن طريق\n"
            f"{names}\n\n"
            "اختارها ومنكمل"
        )
        await WithdrawFlow._show(
            update, context, text, Keyboards.withdraw_methods_menu(methods)
        )

    # ─── طرق الاستلام ─────────────────────────────────────

    @staticmethod
    async def choose_method(
        update: Update, context: ContextTypes.DEFAULT_TYPE, method: str
    ):
        amount = context.user_data.get("amount")
        if not amount:
            await WithdrawFlow.start(update, context)
            return

        pm = ps.get_method(method)
        enabled_methods = ps.list_methods(enabled_only=True)
        if pm and not pm.enabled:
            await WithdrawFlow._show(
                update,
                context,
                "هذه الطريقة غير مفعّلة حالياً.",
                Keyboards.withdraw_methods_menu(enabled_methods),
            )
            return
        if not pm and method not in ("shamcash", "syriatel_cash", "usdt"):
            await WithdrawFlow.show_methods(update, context)
            return

        if pm:
            if pm.min_amount and float(amount) < float(pm.min_amount):
                await WithdrawFlow._show(
                    update,
                    context,
                    f"أقل مبلغ لهذه الطريقة {format_currency(pm.min_amount)}",
                    Keyboards.withdraw_methods_menu(enabled_methods),
                )
                return
            if pm.max_amount and float(amount) > float(pm.max_amount):
                await WithdrawFlow._show(
                    update,
                    context,
                    f"أعلى مبلغ لهذه الطريقة {format_currency(pm.max_amount)}",
                    Keyboards.withdraw_methods_menu(enabled_methods),
                )
                return

        context.user_data["method"] = method
        context.user_data["payout_method_code"] = method
        context.user_data["operation"] = "wallet_withdraw"

        if method == "usdt":
            context.user_data["state"] = "waiting_for_crypto_choice"
            text = (
                "🌐 سحب عملات رقمية\n\n"
                "اختار العملة والشبكة اللي بدك تستلم عليها\n\n"
                "مهم جدا تكون العملة والشبكة صح\n"
                "الشبكة الغلط بتاخد المصاري وبتعمل حالها ما بتعرفنا 😂"
            )
            await WithdrawFlow._show(
                update, context, text, Keyboards.withdraw_crypto_menu()
            )
            return

        context.user_data["state"] = "waiting_for_withdraw_destination"
        instructions = (pm.instructions if pm and pm.instructions else "").strip()
        if not instructions:
            if method == "shamcash":
                instructions = (
                    "ابعت عنوان محفظة شام كاش اللي بدك تستلم عليه\n"
                    "انسخه مثل ما هو:\n\n"
                    "راجع العنوان منيح\n"
                    "لانه بعد التقبيض ما عاد فينا نقول كانت تجربة 😂"
                )
            elif method == "syriatel_cash":
                instructions = (
                    "ابعت رقم سيرياتيل كاش اللي بدك تستلم عليه\n\n"
                    "مثال\n09XXXXXXXX\n\n"
                    "راجع الرقم منيح"
                )
            else:
                instructions = "ابعت بيانات الاستلام المطلوبة."

        if method == "shamcash":
            text = f"💠 التقبيض عن طريق شام كاش\n\n{instructions}"
        elif method == "syriatel_cash":
            text = f"📱 سحب عن طريق سيرياتيل كاش\n\n{instructions}"
        else:
            text = f"{method_label(method)}\n\n{instructions}"

        await WithdrawFlow._show(
            update, context, text, Keyboards.withdraw_dest_back_menu()
        )

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
        amount = float(context.user_data.get("amount") or 0)
        method = context.user_data.get("method")
        dest = context.user_data.get("withdraw_destination") or "—"
        fee, net, profit = fee_breakdown(amount)
        fee_pct = ps.get_fee_percent()
        masked = ps.mask_destination(dest)

        method_txt = method_label(method)
        if method == "usdt":
            cur = context.user_data.get("crypto_currency", "USDT")
            netw = context.user_data.get("crypto_network", "TRC20")
            method_txt = f"🌐 {cur} / {netw}"

        text = (
            "🧾 راجع طلب التقبيض\n\n"
            f"💰 مبلغ السحب {format_currency(amount)}\n"
            f"📈 الربح المحتسب {format_currency(profit)}\n"
            f"🧮 عمولة السحب {fee_pct:g} بالمية من مبلغ السحب "
            f"{format_currency(fee)}\n"
            f"✅ الصافي اللي رح تقبضه {format_currency(net)}\n\n"
            f"💠 الطريقة {method_txt}\n"
            f"📍 العنوان {tg_code(masked)}\n\n"
            "اذا كلشي صح أكد"
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
                "✋ الطلب موجود اصلًا\n\nلا تعملنا نسختين من نفس الفيلم 😂",
                Keyboards.start_menu(),
            )
            context.user_data.clear()
            return

        lim_err = ops.check_user_limits(user, amount)
        if lim_err:
            context.user_data["withdraw_submit_lock"] = False
            await WithdrawFlow._show(
                update, context, lim_err, Keyboards.withdraw_amount_menu()
            )
            return

        public_id = ps.new_public_order_id()
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
                payout_method_code=method,
                status=ST_PENDING_REVIEW,
                withdraw_destination=dest,
                fee_amount=fee,  # متوقعة
                net_amount=net,  # متوقع
                profit_amount=profit,
                crypto_currency=crypto_c,
                crypto_network=crypto_n,
                public_id=public_id,
                description=(
                    f"تقبيض محفظة — {method_txt} — وجهة {dest} — "
                    f"عمولة متوقعة {fee} — صافي متوقع {net}"
                ),
            )
            session.add(tx)
            session.commit()
            session.refresh(tx)
            order_id = tx.id
            public_id = tx.public_id or public_id
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
            "⏳ طلب التقبيض وصل\n\n"
            f"💰 المبلغ {format_currency(amount)}\n"
            f"🧮 العمولة المتوقعة {format_currency(fee)}\n"
            f"✅ الصافي المتوقع {format_currency(net)}\n"
            f"{method_label(method)}\n"
            f"🧾 رقم الطلب {tg_code(public_id)}\n\n"
            "الطلب صار عند الإدارة\n"
            "والمحاسب فتح الملف وعمل حاله مستعجل 😂"
        )
        await WithdrawFlow._show(
            update,
            context,
            text,
            Keyboards.withdraw_submitted_menu(order_id),
            parse_mode="HTML",
        )
        try:
            chat_id = update.effective_chat.id if update.effective_chat else None
            msg_id = context.user_data.get("wd_msg_id")
            if chat_id and msg_id:
                session = db.get_session()
                try:
                    row = (
                        session.query(Transaction)
                        .filter(Transaction.id == order_id)
                        .first()
                    )
                    if row:
                        row.user_track_chat_id = str(chat_id)
                        row.user_track_message_id = int(msg_id)
                        session.commit()
                finally:
                    session.close()
        except Exception:
            pass

        try:
            await WithdrawFlow._notify_admins_new(context, order_id)
        except Exception:
            logger.exception("فشل إشعار الإدمن بطلب سحب")

    # ─── إلغاء من المستخدم ────────────────────────────────

    @staticmethod
    async def start_refund_holds(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """استرداد مبلغ قيد السحب — طلب للإدارة، مو إرجاع فوري."""
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        holds = ops.list_user_holds(user.id)
        reserved = float(getattr(user, "reserved_balance", 0) or 0)
        # #region agent log
        try:
            from _agent_debug import dbg
            dbg(
                "D",
                "withdraw_flow.start_refund_holds",
                "user opened refund holds",
                {
                    "holds": len(holds),
                    "reserved": reserved,
                    "ids": [h.id for h in holds],
                },
                run_id="post-fix",
            )
        except Exception:
            pass
        # #endregion
        if not holds:
            await WithdrawFlow._show(
                update,
                context,
                "↩️ استرداد مبلغ قيد السحب\n\n"
                "ما في مبلغ محجوز حالياً.\n"
                f"📤 قيد السحب {format_currency(reserved)}\n\n"
                "إذا في طلب تقبيض خلص، الاسترداد ما بيصير.",
                Keyboards.wallet_menu(),
            )
            return
        if len(holds) == 1:
            tx = holds[0]
            if tx.status == ST_CANCEL_REQUESTED:
                await WithdrawFlow._show(
                    update,
                    context,
                    "⏳ طلب الاسترداد عند الإدارة\n\n"
                    f"💰 المبلغ {format_currency(tx.amount)}\n"
                    f"🧾 رقم الطلب {tg_code(_order_ref(tx))}\n\n"
                    "الرصيد ما بيرجع إلا بعد موافقتهم\n"
                    "مشان ما يتقبض ويتسترد بنفس الوقت.",
                    Keyboards.withdraw_submitted_menu(tx.id, can_cancel=False),
                    parse_mode="HTML",
                )
                return
            await WithdrawFlow.ask_cancel(update, context, tx.id)
            return
        lines = [
            "↩️ استرداد مبلغ قيد السحب\n",
            "اختار الطلب اللي بدك تسترده.",
            "طلبك بروح للإدارة — الرصيد ما بيرجع لحاله.\n",
        ]
        for tx in holds:
            lines.append(
                f"• {tg_code(_order_ref(tx))} — "
                f"{format_currency(tx.amount)} — {status_label(tx.status)}"
            )
        await WithdrawFlow._show(
            update,
            context,
            "\n".join(lines),
            Keyboards.wallet_hold_list_menu(holds),
            parse_mode="HTML",
        )

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
            "↩️ طلب استرداد مبلغ قيد السحب\n\n"
            "رح ينبعت لكروب التقبيض:\n"
            "فلان طلب استرداد لمبلغه.\n\n"
            "الرصيد المحجوز ما بيرجع لمحفظتك\n"
            "إلا بعد موافقة الإدارة.\n\n"
            "إذا المبلغ اتقبض — الاسترداد بينرفض\n"
            "مشان ما يتقبض ويتسترد بنفس الوقت."
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

            tx.status_before_cancel = tx.status
            tx.status = ST_CANCEL_REQUESTED
            tx.cancel_requested_at = datetime.utcnow()
            _stamp_decision(tx, None, "المستخدم طلب إلغاء السحب")
            session.commit()
            public_id = _order_ref(tx)
        finally:
            session.close()

        text = (
            "⏳ وصل طلب الاسترداد للإدارة\n\n"
            "المبلغ لسا محجوز قيد السحب.\n"
            "ما تحول ولا رجع لمحفظتك.\n\n"
            "إذا وافقوا ولمّا يكون ما اتقبض\n"
            "برجع كامل الرصيد بدون عمولة.\n\n"
            f"🧾 رقم الطلب {tg_code(public_id)}"
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
        masked = ps.mask_destination(tx.withdraw_destination or "")
        text = (
            f"📋 متابعة الطلب {tg_code(_order_ref(tx))}\n\n"
            f"الحالة: {status_label(tx.status)}\n\n"
            f"💰 مبلغ السحب {format_currency(tx.amount)}\n"
            f"📈 الربح المحتسب {format_currency(profit)}\n"
            f"🧮 العمولة {format_currency(fee)}\n"
            f"✅ الصافي {format_currency(net)}\n"
            f"💳 {method_label(tx.method or getattr(tx, 'payout_method_code', None))}\n"
            f"📍 {tg_code(masked)}"
        )
        if getattr(tx, "assigned_admin_name", None) and getattr(tx, "accepted_at", None):
            text += (
                f"\n\n👤 استلمه: {tx.assigned_admin_name}"
                f"\n🕒 {tx.accepted_at}"
            )
        if tx.decided_by_name and getattr(tx, "paid_at", None):
            text += (
                f"\n\n✅ نفّذها: {tx.decided_by_name}"
                f"\n🕒 {tx.paid_at}"
            )
        can_cancel = tx.status in ACTIVE_CANCELLABLE
        await WithdrawFlow._show(
            update,
            context,
            text,
            Keyboards.withdraw_submitted_menu(order_id, can_cancel=can_cancel),
            parse_mode="HTML",
        )

    # ─── دعم مربوط بالطلب ─────────────────────────────────

    @staticmethod
    async def start_support(update, context, order_id: int):
        await ops.start_support(update, context, order_id)

    @staticmethod
    async def handle_support_message(update, context, text: str):
        await ops.handle_support_message(update, context, text)

    # ─── قرارات الإدارة ───────────────────────────────────

    @staticmethod
    async def admin_accept_order(context, order_id: int, admin_user=None):
        return await ops.admin_accept_order(context, order_id, admin_user)

    @staticmethod
    async def admin_transfer_to_me(context, order_id: int, admin_user=None):
        return await ops.admin_transfer_to_me(context, order_id, admin_user)

    @staticmethod
    async def admin_approve_cancel(context, order_id: int, admin_user=None):
        return await ops.admin_approve_cancel(context, order_id, admin_user)

    @staticmethod
    async def admin_reject_cancel(
        context, order_id: int, reason: str = "", paid: bool = False, admin_user=None
    ):
        return await ops.admin_reject_cancel(
            context, order_id, reason=reason, paid=paid, admin_user=admin_user
        )

    @staticmethod
    async def admin_mark_processing(context, order_id: int, admin_user=None):
        return await ops.admin_accept_order(context, order_id, admin_user)

    @staticmethod
    async def admin_mark_paid(context, order_id: int, admin_user=None):
        return await ops.admin_mark_paid(context, order_id, admin_user)

    @staticmethod
    async def send_payout_receipt_photo(context, order_id: int, message, admin_user=None):
        return await ops.send_payout_receipt_photo(
            context, order_id, message, admin_user=admin_user
        )

    @staticmethod
    async def admin_reject_withdraw(
        context, order_id: int, reason: str = "", admin_user=None, reason_code: str = ""
    ):
        return await ops.admin_reject_withdraw(
            context, order_id, reason=reason, admin_user=admin_user, reason_code=reason_code
        )

    @staticmethod
    async def admin_forward_to_support(context, order_id: int, admin_user=None):
        return await ops.admin_forward_to_support(context, order_id, admin_user)

    # ─── مساعدات ──────────────────────────────────────────

    @staticmethod
    def _get_tx(order_id: int):
        return ops.get_tx(order_id)

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
        await ops.notify_admins_new(context, order_id)

    @staticmethod
    async def _notify_admins_cancel(context, order_id: int):
        await ops.notify_admins_cancel(context, order_id)
