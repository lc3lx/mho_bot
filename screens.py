"""
شاشات مقر نابليون — نصوص + عرض عبر edit message
"""

from __future__ import annotations

from datetime import datetime

import ui
from config import Config
from database import DatabaseManager, Transaction, User
from keyboards import Keyboards
from utils import format_currency, safe_edit_callback_message, tg_code

db = DatabaseManager()


async def show_screen(update, context, text: str, markup, parse_mode="HTML"):
    if update.callback_query:
        await safe_edit_callback_message(
            update, text, reply_markup=markup, parse_mode=parse_mode, context=context
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, reply_markup=markup, parse_mode=parse_mode
        )


async def show_extras(update, context):
    text = (
        "🧰 وصلت للمستودع الخلفي.\n\n"
        "حطّينا هون الأشياء الإضافية\n"
        "حتى القائمة الرئيسية ما تتحول لسوق الجمعة 😂"
    )
    await show_screen(update, context, text, Keyboards.extras_menu())


async def show_ichancy_topup_gate(update, context):
    text = (
        "💸 فتحتلك بوابة التعبئة.\n\n"
        "الشحن عالحساب المرتبط بالبوت (اليوزرنيم).\n"
        "ما بدنا ID — اضغط كمّل وابعث المبلغ.\n\n"
        "البوت سريع، بس لسا ما تعلّم يقرأ النوايا 😂"
    )
    await show_screen(update, context, text, Keyboards.ichancy_topup_gate())


async def show_ichancy_withdraw_gate(update, context):
    text = (
        "💰 قسم السحب صار واقف عإجر وحدة.\n\n"
        "السحب من حسابك المرتبط بالبوت (اليوزرنيم).\n"
        "ما بدنا ID — اضغط كمّل وابعث المبلغ.\n\n"
        "ولا تكتب «مستعجل»...\n"
        "المحاسب بياخدها تحدّي شخصي 😂"
    )
    await show_screen(update, context, text, Keyboards.ichancy_withdraw_gate())


async def show_deposit_hub(update, context, user):
    text = (
        "⚡ بدك تنعش المحفظة؟\n\n"
        "اختار طريقة الدفع تحت\n"
        "والمحاسب رح يتظاهر إنه كان ناطرك من الصبح 😂"
    )
    await show_screen(update, context, text, Keyboards.wallet_deposit_menu())


async def show_withdraw_hub(update, context, user):
    if (user.balance or 0) < Config.MIN_WITHDRAWAL:
        text = (
            f"❌ الحد الأدنى للسحب هو {format_currency(Config.MIN_WITHDRAWAL)}\n"
            f"💵 رصيدك الحالي: {format_currency(user.balance or 0)}"
        )
        await show_screen(update, context, text, Keyboards.back_to_main())
        return
    text = (
        "🏧 أهلاً بقسم إخراج المصاري رسميًا\n\n"
        "اكتب المبلغ اللي بدك تسحبه\n"
        "أرقام فقط... بلا فواصل ولا ذكريات مؤلمة 😂"
    )
    await show_screen(update, context, text, Keyboards.wallet_withdraw_gate())


def _pending_sums(user_id: int):
    session = db.get_session()
    try:
        rows = (
            session.query(Transaction)
            .filter(Transaction.user_id == user_id, Transaction.status == "pending")
            .all()
        )
        pending_in = sum(
            float(t.amount or 0)
            for t in rows
            if t.transaction_type in ("deposit", "ichancy_topup")
        )
        pending_out = sum(
            float(t.amount or 0)
            for t in rows
            if t.transaction_type in ("withdraw", "ichancy_withdraw")
        )
        return pending_in, pending_out
    finally:
        session.close()


async def show_pocket(update, context, user):
    pending_in, pending_out = _pending_sums(user.id)
    text = (
        "👛 هاي جيبتك الإلكترونية\n\n"
        f"💎 الرصيد: <b>{format_currency(user.balance or 0)}</b>\n"
        f"📥 قيد الإضافة: <b>{format_currency(pending_in)}</b>\n"
        f"📤 قيد السحب: <b>{format_currency(pending_out)}</b>\n\n"
        "المحفظة بخير...\n"
        "بس بتحب الزيارات والدعم المعنوي 😂"
    )
    await show_screen(update, context, text, Keyboards.wallet_menu())


async def show_ledger(update, context):
    text = (
        "🧾 فتحنا الأرشيف السري.\n\n"
        "هون بتشوف كل عملياتك السابقة\n"
        "وحتى العمليات اللي كنت بتتمنى ننساها 😂"
    )
    await show_screen(update, context, text, Keyboards.ledger_menu())


async def show_card(update, context, user, tg_user=None):
    name = ""
    if tg_user:
        name = " ".join(
            p for p in [tg_user.first_name, tg_user.last_name] if p
        ).strip()
    if not name:
        name = user.first_name or user.username or "—"
    join = getattr(user, "created_at", None)
    join_s = join.strftime("%Y-%m-%d") if join else "—"
    text = (
        "🪪 ملفك الرسمي عند نابليون.\n\n"
        f"👤 الاسم: <b>{ui.esc(name)}</b>\n"
        f"🆔 رقمك: {tg_code(user.telegram_id)}\n"
        f"📅 تاريخ الانضمام: <b>{ui.esc(join_s)}</b>\n\n"
        "صورة شخصية مو مطلوبة...\n"
        "نحنا بوت مو دائرة نفوس 😂"
    )
    await show_screen(update, context, text, Keyboards.profile_menu())


async def show_support(update, context):
    text = (
        "🚑 تم إيقاظ الدعم من الاستراحة.\n\n"
        "اكتب مشكلتك برسالة وحدة واضحة،\n"
        "وممنوع تقول «مرحبا» وتختفي ساعتين 😂"
    )
    await show_screen(update, context, text, Keyboards.support_menu())


async def show_gift_code(update, context):
    text = (
        "🎟️ عندك كود؟\n\n"
        "اكتبه هون مثل ما هو\n"
        "ولا تزخرفه... الكود حساس وبيزعل بسرعة 😂"
    )
    await show_screen(update, context, text, Keyboards.gift_code_menu())


async def show_guide(update, context):
    text = (
        "📘 الدليل السريع جدًا.\n\n"
        "اختار شو مو واضح،\n"
        "ومنشرحه بدون محاضرة مدتها ثلاث فصول 😂"
    )
    await show_screen(update, context, text, Keyboards.guide_menu())


def format_tx_list(rows, empty="ما في شي هون حالياً.") -> str:
    if not rows:
        return empty
    lines = []
    for t in rows[:20]:
        st = {
            "pending": "🟡",
            "completed": "🟢",
            "failed": "🔴",
            "cancelled": "⚪",
        }.get(t.status, "•")
        when = t.created_at.strftime("%m-%d %H:%M") if t.created_at else "—"
        lines.append(
            f"{st} #{t.id} | {t.transaction_type} | "
            f"{format_currency(t.amount or 0)} | {when}"
        )
    return "\n".join(lines)


async def show_history(update, context, user, kind: str):
    session = db.get_session()
    try:
        q = session.query(Transaction).filter(Transaction.user_id == user.id)
        title = "السجل"
        if kind == "deposits":
            q = q.filter(Transaction.transaction_type.in_(["deposit", "ichancy_topup"]))
            title = "💸 عمليات التعبئة"
        elif kind == "withdrawals":
            q = q.filter(
                Transaction.transaction_type.in_(["withdraw", "ichancy_withdraw"])
            )
            title = "💰 عمليات السحب"
        elif kind == "pending":
            q = q.filter(Transaction.status == "pending")
            title = "⏳ العمليات المعلقة"
        rows = q.order_by(Transaction.created_at.desc()).limit(20).all()
        body = format_tx_list(rows)
        text = f"<b>{title}</b>\n\n{body}"
    finally:
        session.close()
    await show_screen(update, context, text, Keyboards.ledger_menu())
