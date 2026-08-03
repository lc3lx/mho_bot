"""
مسار «كودك يا بطل» — تحقق حقيقي ثم إضافة رصيد.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Optional, Tuple

from telegram import Update
from telegram.ext import ContextTypes

from database import DatabaseManager, GiftCode, GiftCodeUsage, Transaction, User
from keyboards import Keyboards
from utils import format_currency, safe_edit_callback_message

logger = logging.getLogger(__name__)
db = DatabaseManager()

# حالات عرض الكود
ST_ACTIVE = "فعال"
ST_USED = "مستخدم"
ST_EXPIRED = "منتهي"
ST_CANCELLED = "ملغي"

WRONG_CODE_REPLIES = (
    "🤨 هالكود مو معنا\n\nتأكد منه وجرب مرة تانية\n\nلا تضيف عليه بهارات 😂",
    "🤨 هالكود مو معنا\n\nيمكن انكتب غلط… أو من فيلم تاني 😂",
    "🤨 هالكود مو معنا\n\nالمحاسب قلب الدرج وما لقاه\nجرب مرة تانية بلا زخرفة",
    "🤨 هالكود مو معنا\n\nتأكد من الأحرف والأرقام\nوبلا بهارات زيادة 😂",
    "🤨 هالكود مو معنا\n\nهاد مش من مطبخنا\nرجّع صحّح وارجع 😂",
)


def code_public_status(gc: GiftCode) -> str:
    now = datetime.utcnow()
    if not gc.is_active:
        return ST_CANCELLED
    if gc.expires_at and gc.expires_at < now:
        return ST_EXPIRED
    if (gc.current_uses or 0) >= (gc.max_uses or 1):
        return ST_USED
    return ST_ACTIVE


class GiftCodeFlow:
    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["state"] = "waiting_for_gift_code"
        context.user_data["operation"] = "gift_code"
        text = (
            "🎟️ عندك كود؟\n\n"
            "اكتبه هون متل ما هو\n\n"
            "لا مسافات زيادة ولا زخرفة\n\n"
            "الكود حساس اكتر من المحاسب 😂"
        )
        await GiftCodeFlow._show(update, context, text, Keyboards.gift_code_menu())

    @staticmethod
    async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        session = db.get_session()
        try:
            rows = (
                session.query(GiftCodeUsage)
                .filter(
                    GiftCodeUsage.user_id == user.id,
                    GiftCodeUsage.status == "success",
                )
                .order_by(GiftCodeUsage.used_at.desc())
                .limit(10)
                .all()
            )
            if not rows:
                text = (
                    "📭 ما عندك اكواد سابقة\n\n"
                    "السجل نضيف بشكل مريب 😂"
                )
                await GiftCodeFlow._show(
                    update, context, text, Keyboards.gift_code_back_menu()
                )
                return

            lines = ["📋 أكوادك السابقة\n"]
            for u in rows:
                code_txt = u.code_text or "—"
                if u.code_id:
                    gc = session.query(GiftCode).filter(GiftCode.id == u.code_id).first()
                    if gc:
                        code_txt = gc.code
                        st = code_public_status(gc)
                    else:
                        st = ST_USED
                else:
                    st = ST_USED
                when = u.used_at.strftime("%Y-%m-%d %H:%M") if u.used_at else "—"
                lines.append(f"🎟️ الكود {code_txt}")
                lines.append(f"🎁 القيمة {format_currency(u.amount or 0)}")
                lines.append(f"📅 التاريخ {when}")
                lines.append(f"📌 الحالة {st}\n")
            await GiftCodeFlow._show(
                update, context, "\n".join(lines), Keyboards.gift_code_back_menu()
            )
        finally:
            session.close()

    @staticmethod
    async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: str):
        user = db.get_user(update.effective_user.id)
        if not user:
            return
        code = (raw or "").strip().upper().replace(" ", "")
        if not code:
            await GiftCodeFlow._show(
                update,
                context,
                random.choice(WRONG_CODE_REPLIES),
                Keyboards.gift_code_retry_menu(),
            )
            context.user_data["state"] = "waiting_for_gift_code"
            return

        ok, kind, payload = GiftCodeFlow._redeem(user, code)
        if ok:
            context.user_data.pop("state", None)
            context.user_data.pop("operation", None)
            text = (
                "✅ الكود اشتغل\n\n"
                f"🎁 القيمة {format_currency(payload['amount'])}\n\n"
                f"🧾 الكود {payload['code']}\n\n"
                "انضافت لحسابك بنجاح\n\n"
                "المحاسب وافق عليه بدون اعتراض\n"
                "وثق اللحظة 😂"
            )
            await GiftCodeFlow._show(
                update, context, text, Keyboards.gift_code_success_menu()
            )
            return

        # أخطاء معروفة
        context.user_data["state"] = "waiting_for_gift_code"
        context.user_data["operation"] = "gift_code"
        if kind == "already_used":
            text = (
                "😂 سبقت حالك\n\n"
                "هاد الكود مستخدم من قبل\n\n"
                "المحاسب عنده ذاكرة وقت المصاري بس"
            )
        elif kind == "expired":
            text = (
                "⌛ هالكود خلص عمره\n\n"
                "كان بيناتنا ايام حلوة 😂\n\n"
                "جرب كود غيره"
            )
        elif kind == "not_yours":
            text = (
                "🚫 هالكود مو إلك\n\n"
                "واضح حاولت تدخل ععرس مو معزوم عليه 😂"
            )
        elif kind == "cancelled":
            text = (
                "❌ هالكود ملغي\n\n"
                "المحاسب سكره من المصدر 😂"
            )
        elif kind == "exhausted":
            text = (
                "😂 سبقت حالك\n\n"
                "هاد الكود مستخدم من قبل\n\n"
                "المحاسب عنده ذاكرة وقت المصاري بس"
            )
        else:
            text = random.choice(WRONG_CODE_REPLIES)

        await GiftCodeFlow._show(
            update, context, text, Keyboards.gift_code_retry_menu()
        )

    @staticmethod
    def _log_reject(
        session,
        user_id: int,
        code_text: str,
        reason: str,
        code_id: Optional[int] = None,
    ):
        try:
            session.add(
                GiftCodeUsage(
                    code_id=code_id,
                    code_text=code_text,
                    user_id=user_id,
                    amount=0.0,
                    status="rejected",
                    reject_reason=reason,
                )
            )
            session.flush()
        except Exception:
            logger.warning("تعذر تسجيل رفض الكود %s: %s", code_text, reason)

    @staticmethod
    def _redeem(user: User, code: str) -> Tuple[bool, str, dict]:
        """
        تحقق حقيقي من السيرفر/قاعدة البيانات ثم إضافة الرصيد.
        يعيد (ok, error_kind, payload).
        """
        session = db.get_session()
        try:
            gc = session.query(GiftCode).filter(GiftCode.code == code).first()
            if not gc:
                GiftCodeFlow._log_reject(session, user.id, code, "غير موجود")
                session.commit()
                return False, "wrong", {}

            # ملغي
            if not gc.is_active:
                GiftCodeFlow._log_reject(
                    session, user.id, code, "ملغي", code_id=gc.id
                )
                session.commit()
                return False, "cancelled", {}

            # منتهي
            if gc.expires_at and gc.expires_at < datetime.utcnow():
                GiftCodeFlow._log_reject(
                    session, user.id, code, "منتهي", code_id=gc.id
                )
                session.commit()
                return False, "expired", {}

            # مخصص لمستخدم آخر
            if gc.assigned_telegram_id and str(gc.assigned_telegram_id) != str(
                user.telegram_id
            ):
                GiftCodeFlow._log_reject(
                    session, user.id, code, "مو مخصص لهذا المستخدم", code_id=gc.id
                )
                session.commit()
                return False, "not_yours", {}

            # استنفد الاستخدامات
            if (gc.current_uses or 0) >= (gc.max_uses or 1):
                GiftCodeFlow._log_reject(
                    session, user.id, code, "مستخدم بالكامل", code_id=gc.id
                )
                session.commit()
                return False, "exhausted", {}

            # نفس المستخدم استخدمه من قبل (حتى لو multi-use للعموم — مرة لكل يوزر)
            existing = (
                session.query(GiftCodeUsage)
                .filter(
                    GiftCodeUsage.code_id == gc.id,
                    GiftCodeUsage.user_id == user.id,
                    GiftCodeUsage.status == "success",
                )
                .first()
            )
            if existing:
                GiftCodeFlow._log_reject(
                    session, user.id, code, "استخدمه هذا المستخدم مسبقاً", code_id=gc.id
                )
                session.commit()
                return False, "already_used", {}

            # تطبيق حقيقي
            db_user = session.query(User).filter(User.id == user.id).first()
            if not db_user:
                return False, "wrong", {}

            amount = float(gc.amount or 0)
            db_user.balance = float(db_user.balance or 0) + amount
            gc.current_uses = int(gc.current_uses or 0) + 1
            # إذا استنفد الحد — يبقى is_active True لكن الحالة المعروضة «مستخدم»
            session.add(
                GiftCodeUsage(
                    code_id=gc.id,
                    code_text=code,
                    user_id=user.id,
                    amount=amount,
                    status="success",
                )
            )
            session.add(
                Transaction(
                    user_id=user.id,
                    transaction_type="gift_code",
                    amount=amount,
                    status="completed",
                    description=f"كود جائزة: {code}",
                    processed_at=datetime.utcnow(),
                )
            )
            session.commit()
            return True, "ok", {"amount": amount, "code": code}
        except Exception:
            session.rollback()
            logger.exception("فشل استرداد كود هدية")
            return False, "wrong", {}
        finally:
            session.close()

    @staticmethod
    async def _show(update, context, text, markup):
        if update.callback_query:
            await safe_edit_callback_message(
                update, text, reply_markup=markup, context=context
            )
            try:
                context.user_data["gift_msg_id"] = update.callback_query.message.message_id
            except Exception:
                pass
            return
        msg_id = context.user_data.get("gift_msg_id")
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id and msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                    reply_markup=markup,
                )
                return
            except Exception:
                pass
        target = update.effective_message or update.message
        if target:
            sent = await target.reply_text(text, reply_markup=markup)
            context.user_data["gift_msg_id"] = sent.message_id
