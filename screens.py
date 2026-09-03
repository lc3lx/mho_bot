"""
شاشات مقر نابليون — نصوص + عرض عبر edit message
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_

import ui
from config import Config
from database import DatabaseManager, Transaction, User
from keyboards import Keyboards
from utils import format_currency, safe_edit_callback_message, tg_code

db = DatabaseManager()

DEPOSIT_PENDING_STATUSES = ("pending", "pending_review")
WITHDRAW_TYPES = ("withdraw", "ichancy_withdraw")
DEPOSIT_TYPES = ("deposit", "ichancy_topup")


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
        "🧰 شغلات زيادة:\n\n"
        "🌐 لفّة عالفيس — يفتح صفحتك الرسمية\n"
        "↩️ رجعلي حوالتي — للاسترداد ومتابعة الحوالة\n"
        "🎁 مفاجآت المعلم — أكواد عروض ومفاجآت البوت\n"
        "📘 فهمني من الآخر — الدليل الكامل بس بشكل مختصر\n"
        "⚙️ دبّرلي الإعدادات — الحساب والتنبيهات والخصوصية\n"
        "📢 شو صاير بالمقر — آخر الأخبار والتحديثات\n"
        "📸 ورجيني وضعي — بطاقة قابلة للتصوير\n"
        "🏆 إنجازاتي — المفتوح والمقفول\n"
        "📊 تقريري الأسبوعي — ملخص خفيف ومضحك\n\n"
        "وإذا ضعت هون لا تلوم البوت 😂"
    )
    await show_screen(update, context, text, Keyboards.extras_menu())


async def show_fun_status(update, context, user, tg_user=None, refresh: bool = False):
    import fun_service

    first = ""
    if tg_user:
        first = (tg_user.first_name or "").strip()
    comment = None
    if refresh:
        comment = fun_service.pick_profile_comment()
    text = fun_service.build_status_card(user, first_name=first, comment=comment)
    context.user_data["fun_status_card"] = text
    await show_screen(update, context, text, Keyboards.fun_status_menu())


async def show_fun_achievements(update, context, user):
    import fun_service

    text = fun_service.build_achievements_list(user.id)
    await show_screen(update, context, text, Keyboards.fun_achievements_menu())


async def show_fun_weekly(update, context, user):
    import fun_service

    text = fun_service.build_weekly_report(user)
    context.user_data["fun_weekly_report"] = text
    await show_screen(update, context, text, Keyboards.fun_weekly_menu())


async def show_hq_news(update, context):
    import fun_service

    text = f"📢 شو صاير بالمقر\n\n{fun_service.pick_news()}"
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
    """بداية التعبئة — اطلب المبلغ أولاً."""
    min_dep = Config.MIN_DEPOSIT
    text = (
        "💳 تعبئة محفظة البوت\n\n"
        "ابعت المبلغ كتابه فقط 👇\n\n"
        "اكتب المبلغ العمله الجديده يا ملك\n\n"
        f"اقل مبلغ ايداع : {format_currency(min_dep)} ل.س\n\n"
        "اكتبه بالليره الجديده وبتلاقيه بحسابك بالليره القديمه\n\n"
        "المحاسب جاهز… بس خلّي الرقم واضح من أول مرة 😂"
    )
    context.user_data["state"] = "waiting_for_amount"
    context.user_data["operation"] = "wallet_deposit"
    await show_screen(update, context, text, Keyboards.cancel_operation())


async def show_wallet_deposit_methods(update, context, amount: float):
    """بعد المبلغ — اختيار طريقة الدفع."""
    amt = format_currency(amount)
    text = (
        "💳 تعبئة محفظة البوت\n\n"
        f"المبلغ {amt}\n\n"
        f"مبلغك {amt} ل.س جديد بس جوا الحساب بتلاقيهن بالعمله القديمه ياملك\n"
        "اكتبه بالليره الجديده وبتلاقيه بحسابك بالليره القديمه\n\n"
        "هلق اختار طريقة الدفع المناسبة 👇\n\n"
        "المحاسب جاهز\n"
        "بس لا تغير رأيك كل شوي 😂"
    )
    await show_screen(update, context, text, Keyboards.wallet_deposit_menu())


async def show_withdraw_hub(update, context, user):
    """توافق — يوجّه للمسار الجديد."""
    from withdraw_flow import WithdrawFlow
    await WithdrawFlow.start(update, context)


def _pending_sums(user_id: int):
    import withdraw_ops as ops

    session = db.get_session()
    try:
        rows = session.query(Transaction).filter(Transaction.user_id == user_id).all()
        hold_set = set(ops.HOLD_STATUSES)
        pending_in = sum(
            float(t.amount or 0)
            for t in rows
            if t.transaction_type in DEPOSIT_TYPES
            and (t.status or "") in DEPOSIT_PENDING_STATUSES
        )
        pending_out = sum(
            float(t.amount or 0)
            for t in rows
            if t.transaction_type in WITHDRAW_TYPES
            and (t.status or "") in hold_set
        )
        return pending_in, pending_out
    finally:
        session.close()


async def show_pocket(update, context, user):
    import withdraw_ops as ops

    fresh = db.get_user_by_db_id(user.id) or db.get_user(user.telegram_id) or user
    user = fresh
    pending_in, pending_out = _pending_sums(user.id)
    tx_sum, reserved, hold_count = ops.pending_withdraw_totals(user.id)
    held = max(reserved, pending_out, tx_sum)
    available = float(user.balance or 0)
    # #region agent log
    try:
        from _agent_debug import dbg

        dbg(
            "E",
            "screens.show_pocket",
            "wallet hold totals",
            {
                "user_id": user.id,
                "balance": available,
                "reserved": reserved,
                "tx_sum": tx_sum,
                "pending_out": pending_out,
                "held": held,
                "hold_count": hold_count,
            },
            run_id="post-fix",
        )
    except Exception:
        pass
    # #endregion
    text = (
        "👛 هاي جيبتك الإلكترونية\n\n"
        f"💎 الرصيد: <b>{format_currency(available)}</b>\n"
        f"📤 قيد السحب: <b>{format_currency(held)}</b>\n"
    )
    if hold_count:
        text += f"🧾 طلبات تقبيض معلقة: <b>{hold_count}</b>\n"
    if pending_in > 0:
        text += f"📥 قيد الإضافة: <b>{format_currency(pending_in)}</b>\n"
    text += (
        "\nالمبلغ قيد السحب محجوز عند الإدارة.\n"
        "ما بيرجع لمحفظتك إلا بعد موافقة الأدمن على الاسترداد.\n\n"
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
        name = user.first_name or "—"
    join = getattr(user, "created_at", None)
    join_s = join.strftime("%Y-%m-%d") if join else "—"
    title = "☕ زبون جديد بالمقر"
    try:
        import fun_service
        title = fun_service.resolve_title(user)
    except Exception:
        pass
    text = (
        "🪪 ملفك الرسمي عند نابليون.\n\n"
        f"👤 الاسم: <b>{ui.esc(name)}</b>\n"
        f"🎖️ اللقب: <b>{ui.esc(title)}</b>\n"
        f"🆔 رقمك: {tg_code(user.telegram_id)}\n"
        f"📅 تاريخ الانضمام: <b>{ui.esc(join_s)}</b>\n\n"
        "للتصوير والمشاركة استخدم:\n"
        "🧰 شغلات زيادة → 📸 ورجيني وضعي\n\n"
        "صورة شخصية مو مطلوبة...\n"
        "نحنا بوت مو دائرة نفوس 😂"
    )
    await show_screen(update, context, text, Keyboards.profile_menu())


async def show_support(update, context):
    text = (
        "🚑 تم إيقاظ الدعم من الاستراحة.\n\n"
        " اكتب مشكلتك برسالة واحدة\n"
        "وبتوصل لكروب الدعم مباشرة، \n ورح يتم الرد عليك هون "
    )
    await show_screen(update, context, text, Keyboards.support_menu())


async def show_gift_code(update, context):
    from gift_code_flow import GiftCodeFlow
    await GiftCodeFlow.start(update, context)


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
    try:
        import withdraw_ops as ops

        status_label = ops.status_label
    except Exception:
        status_label = lambda s: s or "—"
    lines = []
    for t in rows[:20]:
        st = status_label(t.status)
        ref = getattr(t, "public_id", None) or t.id
        when = t.created_at.strftime("%m-%d %H:%M") if t.created_at else "—"
        lines.append(
            f"• {ref} | {t.transaction_type} | "
            f"{format_currency(t.amount or 0)} | {st} | {when}"
        )
    return "\n".join(lines)


async def show_history(update, context, user, kind: str):
    import withdraw_ops as ops

    session = db.get_session()
    try:
        q = session.query(Transaction).filter(Transaction.user_id == user.id)
        title = "السجل"
        if kind == "deposits":
            q = q.filter(Transaction.transaction_type.in_(DEPOSIT_TYPES))
            title = "💸 عمليات التعبئة"
        elif kind == "withdrawals":
            q = q.filter(Transaction.transaction_type.in_(WITHDRAW_TYPES))
            title = "💰 عمليات السحب"
        elif kind == "pending":
            hold = list(ops.HOLD_STATUSES)
            q = q.filter(
                or_(
                    and_(
                        Transaction.transaction_type.in_(DEPOSIT_TYPES),
                        Transaction.status.in_(list(DEPOSIT_PENDING_STATUSES)),
                    ),
                    and_(
                        Transaction.transaction_type.in_(WITHDRAW_TYPES),
                        Transaction.status.in_(hold),
                    ),
                )
            )
            title = "⏳ العمليات المعلقة"
        rows = q.order_by(Transaction.created_at.desc()).limit(20).all()
        # #region agent log
        try:
            from _agent_debug import dbg

            dbg(
                "E",
                "screens.show_history",
                "pending history query",
                {
                    "kind": kind,
                    "user_id": user.id,
                    "count": len(rows),
                    "statuses": [r.status for r in rows[:5]],
                    "types": [r.transaction_type for r in rows[:5]],
                },
                run_id="post-fix",
            )
        except Exception:
            pass
        # #endregion
        body = format_tx_list(rows)
        text = f"<b>{title}</b>\n\n{body}"
    finally:
        session.close()
    await show_screen(update, context, text, Keyboards.ledger_menu())
