"""
عمليات إدارة التقبيض + تذاكر الدعم + إشعارات الكروب.
يُستدعى من withdraw_flow لتفادي تضخيم الملف الأساسي.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from telegram.error import TelegramError

from config import Config
from database import (
    DatabaseManager,
    SupportTicket,
    SupportTicketMessage,
    Transaction,
    User,
)
from keyboards import Keyboards
import payout_service as ps
from utils import (
    format_currency,
    get_user_display_name,
    tg_code,
    user_identity_block,
)

logger = logging.getLogger(__name__)
db = DatabaseManager()

ST_PENDING_REVIEW = "pending_review"
ST_AWAITING_PAYOUT = "awaiting_payout"
ST_CANCEL_REQUESTED = "cancel_requested"
ST_PROCESSING = "processing"
ST_PAID = "paid"
ST_CANCELLED = "cancelled"
ST_REJECTED = "rejected"

HOLD_STATUSES = {
    ST_PENDING_REVIEW,
    ST_AWAITING_PAYOUT,
    ST_PROCESSING,
    ST_CANCEL_REQUESTED,
    "pending",
}
ACTIVE_CANCELLABLE = {
    ST_PENDING_REVIEW,
    ST_AWAITING_PAYOUT,
    ST_PROCESSING,
    "pending",
}
BLOCK_CANCEL_APPROVE = {ST_PAID, "completed"}

STATUS_AR = {
    ST_PENDING_REVIEW: "⏳ بانتظار المراجعة",
    ST_AWAITING_PAYOUT: "⏳ بانتظار المراجعة",
    ST_CANCEL_REQUESTED: "↩️ إلغاء قيد المراجعة",
    ST_PROCESSING: "🔎 قيد التنفيذ",
    ST_PAID: "✅ تم التقبيض",
    ST_CANCELLED: "↩️ ملغي",
    ST_REJECTED: "❌ مرفوض",
    "pending": "⏳ بانتظار المراجعة",
    "completed": "✅ تم التقبيض",
    "failed": "❌ مرفوض",
    "cancelled": "↩️ ملغي",
}


def status_label(status: str) -> str:
    return STATUS_AR.get(status or "", status or "—")


def method_label(method: str) -> str:
    return ps.method_display_name(method)


def fee_breakdown(amount: float) -> tuple[float, float, float]:
    fee, net = ps.calculate_fee(amount)
    return fee, net, 0.0


def admin_name(admin_user) -> str:
    if not admin_user:
        return "admin"
    uname = getattr(admin_user, "username", None)
    if uname:
        return f"@{uname}"
    first = getattr(admin_user, "first_name", None) or ""
    last = getattr(admin_user, "last_name", None) or ""
    full = f"{first} {last}".strip()
    return full or str(getattr(admin_user, "id", "admin"))


def stamp_decision(tx: Transaction, admin_user, note: str = ""):
    now = datetime.utcnow()
    tx.decided_at = now
    tx.processed_at = now
    if admin_user:
        tx.decided_by_telegram_id = int(getattr(admin_user, "id", 0) or 0) or None
        tx.decided_by_name = admin_name(admin_user)
    if note:
        stamp = f"[{now.isoformat()} | {tx.decided_by_name or 'admin'}] {note}"
        tx.admin_notes = ((tx.admin_notes or "").rstrip() + "\n" + stamp).strip()


def order_ref(tx: Transaction) -> str:
    return getattr(tx, "public_id", None) or str(tx.id)


def list_user_holds(user_id: int) -> list:
    """طلبات سحب لسا محجوزة (ما اتقبضت وما انلغت)."""
    session = db.get_session()
    try:
        rows = (
            session.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_type.in_(["withdraw", "ichancy_withdraw"]),
                Transaction.status.in_(list(HOLD_STATUSES)),
            )
            .order_by(Transaction.id.desc())
            .all()
        )
        return [db._detach(session, r) for r in rows]
    finally:
        session.close()


def pending_withdraw_totals(user_id: int) -> tuple[float, float, int]:
    """(مجموع من الطلبات, reserved_balance, عدد الطلبات)"""
    session = db.get_session()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        reserved = float(user.reserved_balance or 0) if user else 0.0
        rows = (
            session.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_type.in_(["withdraw", "ichancy_withdraw"]),
                Transaction.status.in_(list(HOLD_STATUSES)),
            )
            .all()
        )
        tx_sum = sum(float(t.amount or 0) for t in rows)
        return tx_sum, reserved, len(rows)
    finally:
        session.close()


def get_tx(order_id: int) -> Optional[Transaction]:
    session = db.get_session()
    try:
        tx = session.query(Transaction).filter(Transaction.id == order_id).first()
        return db._detach(session, tx)
    finally:
        session.close()


def resolve_notify_chat_ids(tx: Transaction) -> list:
    ids = []
    pm = ps.get_method(getattr(tx, "payout_method_code", None) or tx.method or "")
    if pm and pm.admin_group_id:
        try:
            ids.append(int(pm.admin_group_id))
        except (TypeError, ValueError):
            pass
    gid = ps.get_payout_admin_group_id()
    if gid and gid not in ids:
        ids.append(gid)
    if not ids:
        ids.extend(Config.ADMIN_IDS)
    return ids


def build_admin_order_text(tx: Transaction, user: User, *, full_address: bool = True) -> str:
    fee = float(tx.fee_amount or 0)
    net = float(tx.net_amount or 0)
    profit = float(tx.profit_amount or 0)
    dest = tx.withdraw_destination or "—"
    if not full_address:
        dest = ps.mask_destination(dest)
    ichancy = getattr(user, "ichancy_username", None) or "—"
    if tx.status in (ST_PENDING_REVIEW, "pending", ST_AWAITING_PAYOUT):
        title = "👑 طلب تقبيض جديد"
    else:
        title = f"👑 طلب تقبيض — {status_label(tx.status)}"
    lines = [
        title,
        f"🧾 رقم الطلب {order_ref(tx)} (#{tx.id})",
        "",
        user_identity_block(user),
        f"🎮 حساب iChancy {ichancy}",
        f"💰 مبلغ السحب {format_currency(tx.amount)}",
        f"📈 الربح المحتسب {format_currency(profit)}",
        f"🧮 العمولة {format_currency(fee)}",
        f"✅ الصافي المطلوب تقبيضه {format_currency(net)}",
        f"💠 الطريقة {method_label(tx.method or getattr(tx, 'payout_method_code', None))}",
        f"📍 عنوان {dest}",
        f"🕒 وقت الطلب {tx.created_at}",
        f"📌 الحالة {status_label(tx.status)}",
    ]
    if getattr(tx, "assigned_admin_name", None):
        lines.append(f"👤 استلمه {tx.assigned_admin_name}")
        if getattr(tx, "accepted_at", None):
            lines.append(f"🕒 وقت الاستلام {tx.accepted_at}")
    if tx.status == ST_PAID and getattr(tx, "paid_at", None):
        lines.append("✅ تم التقبيض")
        lines.append(
            f"👤 نفذها {tx.decided_by_name or tx.assigned_admin_name or '—'}"
        )
        lines.append(f"🕒 {tx.paid_at}")
    if tx.status == ST_CANCEL_REQUESTED:
        lines.append("")
        lines.append("🚨 المستخدم طلب استرداد مبلغ قيد السحب")
        lines.append("⚠️ ممنوع التقبيض والإرجاع بنفس الوقت")
        lines.append("وافق على الإلغاء فقط إذا المبلغ لسا ما اتقبض")
        if tx.cancel_requested_at:
            lines.append(f"🕒 طلب الاسترداد {tx.cancel_requested_at}")
    return "\n".join(lines)


async def refresh_admin_group_message(context, order_id: int) -> bool:
    tx = get_tx(order_id)
    if not tx or not getattr(tx, "admin_group_chat_id", None) or not getattr(
        tx, "admin_group_message_id", None
    ):
        return False
    user = db.get_user_by_db_id(tx.user_id)
    text = build_admin_order_text(tx, user, full_address=True)
    markup = Keyboards.admin_withdraw_order_menu(
        order_id,
        assigned=bool(getattr(tx, "assigned_admin_telegram_id", None)),
        cancel_req=(tx.status == ST_CANCEL_REQUESTED),
    )
    if tx.status in (ST_PAID, ST_CANCELLED, ST_REJECTED, "completed"):
        markup = None
    try:
        await context.bot.edit_message_text(
            chat_id=int(tx.admin_group_chat_id),
            message_id=int(tx.admin_group_message_id),
            text=text,
            reply_markup=markup,
        )
        return True
    except TelegramError:
        return False


async def notify_admins_new(context, order_id: int):
    tx = get_tx(order_id)
    if not tx:
        return
    user = db.get_user_by_db_id(tx.user_id)
    text = build_admin_order_text(tx, user, full_address=True)
    markup = Keyboards.admin_withdraw_order_menu(order_id, assigned=False)
    primary_chat = None
    primary_msg = None
    targets = resolve_notify_chat_ids(tx)
    # #region agent log
    try:
        from _agent_debug import dbg
        dbg(
            "A",
            "withdraw_ops.notify_admins_new",
            "notify targets resolved",
            {
                "order_id": order_id,
                "targets": targets,
                "payout_group": ps.get_payout_admin_group_id(),
                "support_group": ps.get_support_group_id(),
                "fallback_admins": not bool(ps.get_payout_admin_group_id()),
            },
        )
    except Exception:
        pass
    # #endregion
    sent_ok = False
    last_error = None
    for chat_id in targets:
        try:
            sent = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=markup,
            )
            if primary_chat is None:
                primary_chat = chat_id
                primary_msg = sent.message_id
            sent_ok = True
            # #region agent log
            try:
                from _agent_debug import dbg
                dbg(
                    "C",
                    "withdraw_ops.notify_admins_new",
                    "send_message ok",
                    {"order_id": order_id, "chat_id": chat_id, "msg_id": sent.message_id},
                    run_id="post-fix",
                )
            except Exception:
                pass
            # #endregion
        except TelegramError as e:
            last_error = str(e)[:200]
            logger.exception("فشل إرسال طلب سحب لـ %s", chat_id)
            # #region agent log
            try:
                from _agent_debug import dbg
                dbg(
                    "C",
                    "withdraw_ops.notify_admins_new",
                    "send_message fail",
                    {"order_id": order_id, "chat_id": chat_id, "error": last_error},
                    run_id="post-fix",
                )
            except Exception:
                pass
            # #endregion
    if not sent_ok:
        logger.error("طلب سحب %s ما انبعت لأي كروب. last_error=%s targets=%s", order_id, last_error, targets)
    if primary_chat is not None:
        session = db.get_session()
        try:
            row = session.query(Transaction).filter(Transaction.id == order_id).first()
            if row:
                row.admin_group_chat_id = str(primary_chat)
                row.admin_group_message_id = primary_msg
                session.commit()
        finally:
            session.close()


async def notify_admins_cancel(context, order_id: int):
    tx = get_tx(order_id)
    if not tx:
        return
    user = db.get_user_by_db_id(tx.user_id)
    edited = await refresh_admin_group_message(context, order_id)
    alert = (
        "🚨 طلب استرداد مبلغ قيد السحب\n\n"
        f"{user_identity_block(user)}\n"
        f"🧾 رقم الطلب {order_ref(tx)}\n"
        f"💰 المبلغ المحجوز {format_currency(tx.amount)}\n"
        f"📌 الحالة {status_label(tx.status)}\n\n"
        "المبلغ ما بيرجع للمحفظة إلا بعد موافقتكم.\n"
        "اذا التقبيض تم — ارفضوا الاسترداد."
    )
    markup = Keyboards.admin_withdraw_order_menu(
        order_id,
        assigned=bool(getattr(tx, "assigned_admin_telegram_id", None)),
        cancel_req=True,
    )
    # #region agent log
    try:
        from _agent_debug import dbg
        dbg(
            "D",
            "withdraw_ops.notify_admins_cancel",
            "refund request to group",
            {
                "order_id": order_id,
                "edited_existing": edited,
                "targets": resolve_notify_chat_ids(tx),
                "amount": float(tx.amount or 0),
            },
            run_id="post-fix",
        )
    except Exception:
        pass
    # #endregion
    for chat_id in resolve_notify_chat_ids(tx):
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=alert, reply_markup=markup
            )
        except TelegramError:
            pass


async def admin_accept_order(context, order_id: int, admin_user=None):
    session = db.get_session()
    try:
        tx = session.query(Transaction).filter(Transaction.id == order_id).first()
        if not tx:
            return False, "الطلب غير موجود"
        if tx.status in (
            ST_PAID,
            ST_CANCELLED,
            ST_REJECTED,
            "completed",
            "failed",
            "cancelled",
        ):
            return False, f"لا يمكن: {status_label(tx.status)}"
        if tx.status == ST_CANCEL_REQUESTED:
            return False, "يوجد طلب إلغاء — عالج الإلغاء أولاً"

        admin_tid = int(getattr(admin_user, "id", 0) or 0)
        if (
            getattr(tx, "assigned_admin_telegram_id", None)
            and tx.assigned_admin_telegram_id != admin_tid
            and tx.status == ST_PROCESSING
        ):
            return (
                False,
                f"الطلب محجوز لـ {tx.assigned_admin_name or tx.assigned_admin_telegram_id}",
            )

        now = datetime.utcnow()
        tx.assigned_admin_telegram_id = admin_tid or None
        tx.assigned_admin_name = admin_name(admin_user)
        tx.accepted_at = now
        tx.status = ST_PROCESSING
        stamp_decision(tx, admin_user, "استلام الطلب — قيد التنفيذ")
        user = session.query(User).filter(User.id == tx.user_id).first()
        telegram_id = user.telegram_id if user else None
        public_id = order_ref(tx)
        session.commit()
    finally:
        session.close()

    if telegram_id:
        text = (
            "🔎 طلبك صار قيد التنفيذ\n\n"
            f"🧾 رقم الطلب {tg_code(public_id)}\n\n"
            "الموظف استلمه\n"
            "هلق صار في حدا رسمي يتحمل المسؤولية 😂"
        )
        try:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="HTML",
                reply_markup=Keyboards.withdraw_submitted_menu(order_id),
            )
        except TelegramError:
            pass
    await refresh_admin_group_message(context, order_id)
    return True, "تم استلام الطلب"


async def admin_transfer_to_me(context, order_id: int, admin_user=None):
    session = db.get_session()
    try:
        tx = session.query(Transaction).filter(Transaction.id == order_id).first()
        if not tx:
            return False, "غير موجود"
        if tx.status in (ST_PAID, ST_CANCELLED, ST_REJECTED, "completed"):
            return False, f"لا يمكن: {status_label(tx.status)}"
        admin_tid = int(getattr(admin_user, "id", 0) or 0)
        prev = getattr(tx, "assigned_admin_name", None)
        tx.assigned_admin_telegram_id = admin_tid or None
        tx.assigned_admin_name = admin_name(admin_user)
        tx.accepted_at = datetime.utcnow()
        if tx.status in (ST_PENDING_REVIEW, ST_AWAITING_PAYOUT, "pending"):
            tx.status = ST_PROCESSING
        stamp_decision(
            tx, admin_user, f"تحويل من {prev or '—'} → {admin_name(admin_user)}"
        )
        session.commit()
    finally:
        session.close()
    await refresh_admin_group_message(context, order_id)
    return True, "تم التحويل إليك"


async def admin_mark_paid(context, order_id: int, admin_user=None):
    session = db.get_session()
    was_cancel = False
    try:
        tx = session.query(Transaction).filter(Transaction.id == order_id).first()
        if not tx:
            return False, "غير موجود"
        if tx.status == ST_PAID or tx.status == "completed":
            return False, "تم التقبيض مسبقاً — ممنوع التكرار"
        if tx.status in (ST_CANCELLED, ST_REJECTED, "cancelled", "failed"):
            return False, f"لا يمكن: {status_label(tx.status)}"

        admin_tid = int(getattr(admin_user, "id", 0) or 0)
        if (
            getattr(tx, "assigned_admin_telegram_id", None)
            and admin_tid
            and tx.assigned_admin_telegram_id != admin_tid
        ):
            return (
                False,
                f"الطلب محجوز لـ {tx.assigned_admin_name} — حوّله أولاً",
            )

        user = session.query(User).filter(User.id == tx.user_id).first()
        if tx.status == ST_CANCEL_REQUESTED:
            was_cancel = True
            tx.cancel_rejection_reason = "تم التقبيض أثناء طلب الإلغاء"

        amount = float(tx.amount or 0)
        fee, net, profit = fee_breakdown(amount)
        tx.fee_amount = fee
        tx.net_amount = net
        tx.profit_amount = float(tx.profit_amount or profit)

        if user:
            user.reserved_balance = max(
                0.0, float(user.reserved_balance or 0) - amount
            )
        method_txt = method_label(tx.method or getattr(tx, "payout_method_code", None))
        if tx.crypto_currency and tx.crypto_network:
            method_txt = f"{tx.crypto_currency}/{tx.crypto_network}"

        now = datetime.utcnow()
        tx.status = ST_PAID
        tx.paid_at = now
        if not getattr(tx, "assigned_admin_telegram_id", None) and admin_user:
            tx.assigned_admin_telegram_id = admin_tid or None
            tx.assigned_admin_name = admin_name(admin_user)
        stamp_decision(
            tx, admin_user, f"تأكيد التقبيض — عمولة {fee} — صافي {net}"
        )
        telegram_id = user.telegram_id if user else None
        user_db_id = user.id if user else None
        public_id = order_ref(tx)
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
                    f"🧾 رقم الطلب {tg_code(public_id)}"
                ),
                parse_mode="HTML",
                reply_markup=Keyboards.withdraw_locked_menu(order_id),
            )
        except TelegramError:
            pass

    if telegram_id:
        comment = ""
        try:
            import fun_service

            if user_db_id:
                fun_service.track_order_success(user_db_id)
            comment = f"\n\n📢 تعليق المحاسب\n{fun_service.pick_receipt_comment()}"
        except Exception:
            pass
        text = (
            "✅ تم التقبيض\n\n"
            f"💰 مبلغ السحب {format_currency(amount)}\n"
            f"🧮 العمولة {format_currency(fee)}\n"
            f"✅ الصافي المقبوض {format_currency(net)}\n"
            f"{method_txt}\n"
            f"🧾 رقم الطلب {tg_code(public_id)}\n\n"
            "خلصت العملية\n"
            "المحاسب وقع الورقة قبل ما حدا يغير رأيه 😂"
            f"{comment}"
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

    await refresh_admin_group_message(context, order_id)
    return True, "تم التقبيض"


def _extract_image_file_id(message) -> Optional[str]:
    if not message:
        return None
    if message.photo:
        return message.photo[-1].file_id
    doc = message.document
    if doc and (doc.mime_type or "").startswith("image/"):
        return doc.file_id
    return None


async def send_payout_receipt_photo(
    context, order_id: int, message, admin_user=None
) -> tuple[bool, str]:
    """إرسال صورة إشعار الحوالة للزبون بالخاص."""
    file_id = _extract_image_file_id(message)
    if not file_id:
        return False, "ابعت صورة إشعار الحوالة (صورة فقط)"

    tx = get_tx(order_id)
    if not tx:
        return False, "الطلب غير موجود"
    if tx.status not in (ST_PAID, "completed"):
        return False, "لازم يكون الطلب متقبض قبل إرسال الإشعار"

    user = db.get_user_by_db_id(tx.user_id)
    if not user or not user.telegram_id:
        return False, "المستخدم غير موجود"

    amount = float(tx.amount or 0)
    net = float(tx.net_amount or 0)
    public_id = order_ref(tx)
    caption = (
        "📸 إشعار التقبيض\n\n"
        f"🧾 رقم الطلب {public_id}\n"
        f"💰 مبلغ السحب {format_currency(amount)}\n"
        f"✅ الصافي المقبوض {format_currency(net)}\n\n"
        "صورة إشعار الحوالة من المحاسب"
    )

    # #region agent log
    try:
        from _agent_debug import dbg

        dbg(
            "F",
            "withdraw_ops.send_payout_receipt_photo",
            "sending receipt to user",
            {
                "order_id": order_id,
                "user_tg": str(user.telegram_id),
                "admin_id": getattr(admin_user, "id", None),
            },
            run_id="post-fix",
        )
    except Exception:
        pass
    # #endregion

    try:
        await context.bot.send_photo(
            chat_id=int(user.telegram_id),
            photo=file_id,
            caption=caption,
            reply_markup=Keyboards.withdraw_paid_menu(order_id),
        )
    except TelegramError as e:
        logger.exception("فشل إرسال إشعار التقبيض للزبون")
        return False, f"فشل الإرسال: {str(e)[:120]}"

    session = db.get_session()
    try:
        row = session.query(Transaction).filter(Transaction.id == order_id).first()
        if row:
            who = admin_name(admin_user)
            stamp = f"[{datetime.utcnow().isoformat()} | {who}] أُرسل إشعار حوالة للزبون"
            row.admin_notes = ((row.admin_notes or "").rstrip() + "\n" + stamp).strip()
            session.commit()
    finally:
        session.close()

    return True, "✅ وصل إشعار الحوالة للزبون بالخاص"


async def admin_reject_withdraw(
    context, order_id: int, reason: str = "", admin_user=None, reason_code: str = ""
):
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
            user.balance = float(user.balance or 0) + amount
            user.reserved_balance = max(
                0.0, float(user.reserved_balance or 0) - amount
            )
        if reason_code:
            tx.reject_reason_code = reason_code
            if not reason:
                reason = ps.REJECT_REASONS.get(reason_code, reason_code)
        tx.status = ST_REJECTED
        tx.fee_amount = 0.0
        tx.net_amount = 0.0
        stamp_decision(
            tx, admin_user, f"رفض السحب قبل التقبيض — إرجاع كامل — {reason}"
        )
        new_balance = float(user.balance or 0) if user else 0
        telegram_id = user.telegram_id if user else None
        public_id = order_ref(tx)
        session.commit()
    finally:
        session.close()

    if telegram_id:
        text = (
            "❌ ما قدرنا ننفذ طلب التقبيض\n\n"
            f"السبب\n{reason or '—'}\n\n"
            "رجعنا المبلغ كامل لمحفظتك\n\n"
            f"💰 المبلغ الراجع {format_currency(amount)}\n"
            f"💎 رصيدك الحالي {format_currency(new_balance)}\n"
            f"🧾 رقم الطلب {tg_code(public_id)}"
        )
        try:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="HTML",
                reply_markup=Keyboards.withdraw_rejected_menu(order_id),
            )
        except TelegramError:
            pass
    await refresh_admin_group_message(context, order_id)
    return True, "مرفوض مع إرجاع الرصيد"


async def admin_approve_cancel(context, order_id: int, admin_user=None):
    session = db.get_session()
    try:
        tx = session.query(Transaction).filter(Transaction.id == order_id).first()
        if not tx:
            return False, "الطلب غير موجود"
        if tx.status in BLOCK_CANCEL_APPROVE:
            return False, "ممنوع: تم التقبيض"
        if tx.status != ST_CANCEL_REQUESTED:
            return False, f"حالة الطلب الآن: {status_label(tx.status)}"

        user = session.query(User).filter(User.id == tx.user_id).first()
        amount = float(tx.amount or 0)
        if user:
            user.balance = float(user.balance or 0) + amount
            user.reserved_balance = max(
                0.0, float(user.reserved_balance or 0) - amount
            )
        tx.status = ST_CANCELLED
        tx.fee_amount = 0.0
        tx.net_amount = 0.0
        stamp_decision(
            tx, admin_user, "موافقة على إلغاء السحب — إرجاع كامل بدون عمولة"
        )
        session.commit()
        telegram_id = user.telegram_id if user else None
        new_balance = float(user.balance or 0) if user else 0
        public_id = order_ref(tx)
    finally:
        session.close()

    if telegram_id:
        text = (
            "✅ تم إلغاء السحب\n\n"
            f"💰 رجعنا {format_currency(amount)} لمحفظتك\n"
            f"💎 رصيدك الحالي {format_currency(new_balance)}\n"
            f"🧾 رقم الطلب {tg_code(public_id)}\n\n"
            "المحاسب رجع المصاري\n"
            "بس كتب بالملاحظات انك غيرت رأيك 😂"
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
    await refresh_admin_group_message(context, order_id)
    return True, "تم إلغاء السحب وإرجاع المبلغ"


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
        public_id = order_ref(tx)

        if paid or tx.status in BLOCK_CANCEL_APPROVE:
            tx.cancel_rejection_reason = reason or "تم التقبيض"
            if tx.status == ST_CANCEL_REQUESTED:
                tx.status = ST_PAID if paid else ST_PROCESSING
            stamp_decision(tx, admin_user, f"رفض إلغاء بعد التقبيض — {reason}")
            session.commit()
            msg = (
                "❌ ما عاد فينا نلغي السحب\n\n"
                "العملية اتقبضت أو فاتت بالتنفيذ النهائي\n\n"
                f"🧾 رقم الطلب {tg_code(public_id)}"
            )
            markup = Keyboards.withdraw_locked_menu(order_id)
        else:
            if tx.status != ST_CANCEL_REQUESTED:
                return False, f"حالة الطلب: {status_label(tx.status)}"
            restore = getattr(tx, "status_before_cancel", None) or ST_PENDING_REVIEW
            if restore == ST_CANCEL_REQUESTED:
                restore = ST_PENDING_REVIEW
            tx.cancel_rejection_reason = reason or "رفض إداري"
            tx.status = restore
            stamp_decision(tx, admin_user, f"رفض طلب الإلغاء — {reason}")
            session.commit()
            msg = (
                "❌ ما تمت الموافقة على الإلغاء\n\n"
                f"السبب\n{reason or '—'}\n\n"
                "طلب السحب لسا شغال بشكل طبيعي\n\n"
                f"🧾 رقم الطلب {tg_code(public_id)}"
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
    await refresh_admin_group_message(context, order_id)
    return True, "تم رفض طلب الإلغاء"


async def admin_forward_to_support(context, order_id: int, admin_user=None):
    tx = get_tx(order_id)
    if not tx:
        return False, "غير موجود"
    user = db.get_user_by_db_id(tx.user_id)
    text = (
        f"🚑 تحويل للدعم من الإدارة\n"
        f"طلب {order_ref(tx)} (#{order_id})\n"
        f"المستخدم: {get_user_display_name(user)}\n"
        f"المبلغ: {format_currency(tx.amount)}\n"
        f"الحالة: {status_label(tx.status)}\n"
        f"من: {admin_name(admin_user)}"
    )
    support_gid = ps.get_support_group_id()
    targets = [support_gid] if support_gid else list(Config.ADMIN_IDS)
    for chat_id in targets:
        if not chat_id:
            continue
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=Keyboards.admin_withdraw_order_menu(
                    order_id,
                    assigned=bool(getattr(tx, "assigned_admin_telegram_id", None)),
                    cancel_req=(tx.status == ST_CANCEL_REQUESTED),
                ),
            )
        except TelegramError:
            pass
    session = db.get_session()
    try:
        row = session.query(Transaction).filter(Transaction.id == order_id).first()
        if row:
            stamp_decision(row, admin_user, "تحويل للدعم")
            session.commit()
    finally:
        session.close()
    return True, "تم التحويل للدعم"


# ─── دعم ─────────────────────────────────────────────────

def _open_or_create_ticket(
    user_id: int, *, order_id: Optional[int] = None, subject: str
) -> int:
    session = db.get_session()
    try:
        q = session.query(SupportTicket).filter(
            SupportTicket.user_id == user_id,
            SupportTicket.status.in_(["open", "escalated"]),
        )
        if order_id:
            q = q.filter(SupportTicket.order_id == order_id)
        else:
            q = q.filter(SupportTicket.order_id.is_(None))
        ticket = q.order_by(SupportTicket.id.desc()).first()
        if not ticket:
            ticket = SupportTicket(
                user_id=user_id,
                order_id=order_id,
                status="open",
                subject=subject,
            )
            session.add(ticket)
            session.commit()
            session.refresh(ticket)
        return int(ticket.id)
    finally:
        session.close()


async def start_general_support(update, context):
    """دردشة مباشرة عامة → تذكرة مربوطة بكروب الدعم (بدون طلب سحب)."""
    from utils import safe_edit_callback_message

    tg_user = update.effective_user
    user = db.get_user(tg_user.id)
    if not user:
        if update.callback_query:
            await update.callback_query.answer("سجّل أولاً", show_alert=True)
        return
    try:
        db.sync_user_profile(
            tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        user = db.get_user(tg_user.id) or user
    except Exception:
        pass

    ticket_id = _open_or_create_ticket(
        user.id, order_id=None, subject="دردشة مباشرة / دعم عام"
    )
    context.user_data["state"] = "waiting_payout_support_msg"
    context.user_data["support_ticket_id"] = ticket_id
    context.user_data["support_order_id"] = 0

    # #region agent log
    try:
        from _agent_debug import dbg

        dbg(
            "A",
            "withdraw_ops.start_general_support",
            "live chat ticket opened",
            {
                "ticket_id": ticket_id,
                "user_tg": int(user.telegram_id),
                "support_gid": ps.get_support_group_id(),
                "username": tg_user.username,
            },
            run_id="post-fix",
        )
    except Exception:
        pass
    # #endregion

    text = (
        "🚑 فتحتلك تذكرة دعم\n\n"
        f"🧾 رقم التذكرة {ticket_id}\n\n"
        "اكتب شو المشكلة برسالة وحدة\n"
        "بتوصل لكروب الدعم مع اسمك واليوزر\n"
        "ويردّوا عليك هون بالخاص"
    )
    markup = Keyboards.support_menu()
    if update.callback_query:
        await safe_edit_callback_message(
            update, text, reply_markup=markup, context=context
        )
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def start_support(update, context, order_id: int):
    from withdraw_flow import WithdrawFlow

    user = db.get_user(update.effective_user.id)
    tx = get_tx(order_id)
    if not user or not tx or tx.user_id != user.id:
        await update.callback_query.answer("الطلب غير موجود", show_alert=True)
        return

    ticket_id = _open_or_create_ticket(
        user.id,
        order_id=order_id,
        subject=f"دعم طلب سحب {order_ref(tx)}",
    )

    context.user_data["state"] = "waiting_payout_support_msg"
    context.user_data["support_ticket_id"] = ticket_id
    context.user_data["support_order_id"] = order_id

    text = (
        "🚑 فتحتلك تذكرة دعم\n\n"
        f"🧾 الطلب {tg_code(order_ref(tx))}\n\n"
        "اكتب شو المشكلة برسالة وحدة\n"
        "والدعم بيشوف كل تفاصيل العملية"
    )
    await WithdrawFlow._show(
        update,
        context,
        text,
        Keyboards.withdraw_submitted_menu(
            order_id, can_cancel=tx.status in ACTIVE_CANCELLABLE
        ),
        parse_mode="HTML",
    )


async def handle_support_message(update, context, text: str):
    user = db.get_user(update.effective_user.id)
    ticket_id = int(context.user_data.get("support_ticket_id") or 0)
    order_id = int(context.user_data.get("support_order_id") or 0)
    msg = (text or "").strip()
    if not user or not ticket_id or not msg:
        return

    tx = get_tx(order_id) if order_id else None
    session = db.get_session()
    try:
        ticket = session.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
        if not ticket:
            await update.message.reply_text("التذكرة غير موجودة.")
            return
        session.add(
            SupportTicketMessage(
                ticket_id=ticket_id,
                direction="user_to_support",
                content=msg,
                sender_telegram_id=int(user.telegram_id),
                sender_name=get_user_display_name(user),
            )
        )
        session.commit()
    finally:
        session.close()

    context.user_data.pop("state", None)

    if tx:
        group_text = (
            "🚑 تذكرة جديدة — طلب سحب\n\n"
            f"🧾 رقم التذكرة {ticket_id}\n"
            f"🧾 طلب السحب {order_ref(tx)}\n"
            f"{user_identity_block(user)}\n"
            f"💰 المبلغ {format_currency(tx.amount)}\n"
            f"📌 حالة الطلب {status_label(tx.status)}\n\n"
            f"💬 المشكلة\n{msg}\n\n"
            "ردّوا من الزر — الرد بيوصل للمستخدم بالخاص من البوت"
        )
    else:
        group_text = (
            "🚑 تذكرة دعم جديدة\n\n"
            f"🧾 رقم التذكرة {ticket_id}\n"
            f"{user_identity_block(user)}\n\n"
            f"💬 المشكلة\n{msg}\n\n"
            "ردّوا من الزر — الرد بيوصل للمستخدم بالخاص من البوت"
        )
    support_gid = ps.get_support_group_id()
    targets = [support_gid] if support_gid else []
    # #region agent log
    try:
        from _agent_debug import dbg
        dbg(
            "A",
            "withdraw_ops.handle_support_message",
            "support ticket notify",
            {
                "ticket_id": ticket_id,
                "order_id": order_id,
                "support_gid": support_gid,
                "targets": targets,
                "fallback_admins": support_gid is None,
            },
            run_id="post-fix",
        )
    except Exception:
        pass
    # #endregion
    sent_ok = False
    last_error = None
    if not targets:
        last_error = "كروب الدعم مو مربوط"
        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "⚠️ تذكرة دعم ما وصلت للكروب — الكروب مو مربوط.\n"
                        "داخل كروب دعم أرسل /bind_support\n\n"
                        + group_text
                    ),
                    reply_markup=Keyboards.support_ticket_admin_menu(ticket_id, order_id),
                )
            except TelegramError:
                pass
    for chat_id in targets:
        if not chat_id:
            continue
        try:
            sent = await context.bot.send_message(
                chat_id=chat_id,
                text=group_text,
                reply_markup=Keyboards.support_ticket_admin_menu(ticket_id, order_id),
            )
            sent_ok = True
            session = db.get_session()
            try:
                t = (
                    session.query(SupportTicket)
                    .filter(SupportTicket.id == ticket_id)
                    .first()
                )
                if t:
                    t.support_group_chat_id = str(chat_id)
                    t.support_group_message_id = sent.message_id
                    session.commit()
            finally:
                session.close()
            # #region agent log
            try:
                from _agent_debug import dbg
                dbg(
                    "C",
                    "withdraw_ops.handle_support_message",
                    "support send ok",
                    {"ticket_id": ticket_id, "chat_id": chat_id, "msg_id": sent.message_id},
                    run_id="post-fix",
                )
            except Exception:
                pass
            # #endregion
        except TelegramError as e:
            last_error = str(e)[:200]
            logger.exception("فشل إرسال تذكرة دعم")
            # #region agent log
            try:
                from _agent_debug import dbg
                dbg(
                    "C",
                    "withdraw_ops.handle_support_message",
                    "support send fail",
                    {"ticket_id": ticket_id, "chat_id": chat_id, "error": last_error},
                    run_id="post-fix",
                )
            except Exception:
                pass
            # #endregion

    if sent_ok:
        await update.message.reply_text(
            "✅ وصلت رسالتك لكروب الدعم\nرح يردّوا عليك هون بالخاص من البوت",
            reply_markup=(
                Keyboards.withdraw_submitted_menu(
                    order_id, can_cancel=bool(tx and tx.status in ACTIVE_CANCELLABLE)
                )
                if order_id and tx
                else Keyboards.support_menu()
            ),
        )
    else:
        await update.message.reply_text(
            "⚠️ وصلت رسالتك، بس ما قدرت أرسلها لكروب الدعم.\n"
            "الإدارة لازم تربط الكروب بأمر /bind_support داخل كروب دعم.",
            reply_markup=Keyboards.support_menu(),
        )


async def support_send_reply(context, ticket_id: int, reply_text: str, admin_user):
    session = db.get_session()
    try:
        ticket = session.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
        if not ticket:
            return False, "التذكرة غير موجودة"
        user = session.query(User).filter(User.id == ticket.user_id).first()
        if not user:
            return False, "المستخدم غير موجود"
        session.add(
            SupportTicketMessage(
                ticket_id=ticket_id,
                direction="support_to_user",
                content=reply_text,
                sender_telegram_id=int(getattr(admin_user, "id", 0) or 0) or None,
                sender_name=admin_name(admin_user),
            )
        )
        session.commit()
        telegram_id = user.telegram_id
        order_id = ticket.order_id
    finally:
        session.close()

    user_text = f"💬 رد الدعم\n\n{reply_text}\n\n🧾 تذكرة #{ticket_id}"
    try:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=user_text,
            reply_markup=Keyboards.withdraw_submitted_menu(order_id or 0)
            if order_id
            else Keyboards.support_menu(),
        )
    except TelegramError:
        return False, "فشل إرسال الرد للمستخدم"
    return True, "تم إرسال الرد"


async def support_resolve(
    context,
    ticket_id: int,
    admin_user,
    *,
    group_message_text: str | None = None,
):
    session = db.get_session()
    try:
        ticket = session.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
        if not ticket:
            return False, "غير موجودة"
        ticket.status = "resolved"
        ticket.resolved_at = datetime.utcnow()
        ticket.resolved_by_name = admin_name(admin_user)
        user = session.query(User).filter(User.id == ticket.user_id).first()
        telegram_id = user.telegram_id if user else None
        order_id = int(ticket.order_id or 0)
        group_chat_id = ticket.support_group_chat_id
        group_message_id = ticket.support_group_message_id
        session.commit()
    finally:
        session.close()
    if telegram_id:
        try:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=(
                    f"✅ تذكرة الدعم #{ticket_id}\n"
                    "تم الرد و نحلت.\n"
                    "إذا احتجت شي تاني افتح تذكرة جديدة."
                ),
            )
        except TelegramError:
            pass
    if group_chat_id and group_message_id:
        base = (group_message_text or "").strip()
        if base and "تم الرد و نحلت" not in base:
            base = f"{base}\n\n✅ تم الرد و نحلت"
        elif not base:
            base = f"🧾 تذكرة #{ticket_id}\n\n✅ تم الرد و نحلت"
        try:
            await context.bot.edit_message_text(
                chat_id=int(group_chat_id),
                message_id=int(group_message_id),
                text=base,
                reply_markup=None,
            )
        except TelegramError:
            pass
    return True, "تم الرد و نحلت"


async def _escalation_target_ids(context) -> list[int]:
    username = (Config.SUPPORT_ESCALATION_USERNAME or "NapoleonRobert").strip().lstrip("@")
    if username:
        try:
            chat = await context.bot.get_chat(f"@{username}")
            if chat and chat.id:
                return [int(chat.id)]
        except TelegramError:
            pass
    return [int(x) for x in (Config.ADMIN_IDS or []) if x]


def get_ticket_order_id(ticket_id: int) -> int:
    session = db.get_session()
    try:
        ticket = session.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
        return int(ticket.order_id or 0) if ticket else 0
    finally:
        session.close()


async def support_escalate(context, ticket_id: int, admin_user):
    session = db.get_session()
    try:
        ticket = session.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
        if not ticket:
            return False, "غير موجودة"
        ticket.status = "escalated"
        ticket.escalated_at = datetime.utcnow()
        order_id = int(ticket.order_id or 0)
        user = session.query(User).filter(User.id == ticket.user_id).first()
        last_msg = (
            session.query(SupportTicketMessage)
            .filter(SupportTicketMessage.ticket_id == ticket_id)
            .order_by(SupportTicketMessage.id.desc())
            .first()
        )
        session.commit()
    finally:
        session.close()

    problem = (last_msg.content if last_msg else "").strip() or "—"
    note = (
        f"🚨 تصعيد تذكرة #{ticket_id}\n\n"
        f"{user_identity_block(user) if user else '—'}\n"
    )
    if order_id:
        note += f"🧾 طلب السحب: {order_id}\n"
    note += (
        f"\n💬 المشكلة:\n{problem}\n\n"
        f"👤 من موظف الدعم: {admin_name(admin_user)}"
    )
    targets = await _escalation_target_ids(context)
    sent = 0
    for admin_id in targets:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=note,
                reply_markup=Keyboards.support_ticket_admin_menu(ticket_id, order_id),
            )
            sent += 1
        except TelegramError:
            pass
    if not sent:
        return False, "تعذر إرسال التصعيد — تأكد أن @NapoleonRobert فتح البوت (/start)"
    return True, f"تم التصعيد لـ @{Config.SUPPORT_ESCALATION_USERNAME}"


def check_user_limits(user: User, amount: float) -> Optional[str]:
    """رسالة خطأ إن تجاوز الحدود، أو None."""
    max_w = ps.get_max_withdraw()
    if max_w is not None and amount > max_w:
        return (
            f"🤨 المبلغ فوق الحد الأعلى\n\n"
            f"أعلى مبلغ للسحب {format_currency(max_w)}"
        )

    session = db.get_session()
    try:
        day_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        todays = (
            session.query(Transaction)
            .filter(
                Transaction.user_id == user.id,
                Transaction.transaction_type == "withdraw",
                Transaction.created_at >= day_start,
                Transaction.status.notin_(
                    [ST_CANCELLED, ST_REJECTED, "cancelled", "failed"]
                ),
            )
            .all()
        )
        max_reqs = ps.get_max_requests_per_day()
        if max_reqs > 0 and len(todays) >= max_reqs:
            return (
                f"✋ وصلت لحد طلبات السحب اليوم ({max_reqs})\n"
                "جرّب بكرا — المحاسب بياخد إجازة نوم 😂"
            )
        daily_cap = ps.get_daily_amount_limit()
        if daily_cap is not None:
            used = sum(float(t.amount or 0) for t in todays)
            if used + amount > daily_cap + 1e-9:
                return (
                    f"✋ الحد اليومي للسحب {format_currency(daily_cap)}\n"
                    f"استخدمت اليوم {format_currency(used)}"
                )

        cooldown = ps.get_cooldown_seconds()
        if cooldown > 0:
            last = (
                session.query(Transaction)
                .filter(
                    Transaction.user_id == user.id,
                    Transaction.transaction_type == "withdraw",
                )
                .order_by(Transaction.created_at.desc())
                .first()
            )
            if last and last.created_at:
                elapsed = (datetime.utcnow() - last.created_at).total_seconds()
                if elapsed < cooldown:
                    left = int(cooldown - elapsed)
                    mins = max(1, (left + 59) // 60)
                    return (
                        f"⏱ مهلك شوي\n\n"
                        f"لازم تنتظر حوالي {mins} دقيقة بين طلبين"
                    )
    finally:
        session.close()
    return None
