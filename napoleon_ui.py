"""
نصوص واجهة نابليون + مزاج عشوائي + أدوات تنقّل.
"""

from __future__ import annotations

import random
import time
from typing import Optional

import ui
from config import Config
from utils import format_currency

DIV = "━━━━━━━━━━━━━━"
HOME_CB = "main_menu"
RATE_LIMIT_SECONDS = 2.0

BOT_MOODS = [
    "المحاسب فات عالدوام بإرادته...\nالوضع مبشّر 😂",
    "الأزرار مرتاحة اليوم...\nيعني الخدمات شغّالة ☕",
    "نابليون راجع من استراحة قصيرة...\nجاهزين للشغل 👑",
    "المقر هادي شوي...\nبس المحفظة لسا عم تراقب 👀",
    "اليوم المزاج رسمي مع لمسة سخرية...\nزي العادة 😌",
    "السيرفر شارب قهوته...\nوالبوت جاهز للضغط ⚡",
    "لا دراما اليوم...\nبس عمليات واضحة ومرتبة ✅",
    "المحاسب ابتسم...\nوهذا نادر، فاغتنم اللحظة 😂",
]

HOME_BACK_TEXT = (
    "🏠 رجعناك عالمقر.\n\n"
    "الحمد لله ما ضيّعنا حدا بالطريق 😂"
)

PRESS_SPAM_TEXT = "الزر وكّل محامي، ضغطة وحدة بتكفي 😂"

SECRET_REPLIES = {
    "وينك؟": "هون، كنت عم راقب الأزرار لا يهربوا.",
    "وينك": "هون، كنت عم راقب الأزرار لا يهربوا.",
    "مستعجل": "شغّلنا وضع لا ترمش 🏃",
    "هههه": "ضحكتك وصلت للمحاسبة، سجلوها كإيداع معنوي.",
    "ههه": "ضحكتك وصلت للمحاسبة، سجلوها كإيداع معنوي.",
    "😂": "ضحكتك وصلت للمحاسبة، سجلوها كإيداع معنوي.",
    "🤣": "ضحكتك وصلت للمحاسبة، سجلوها كإيداع معنوي.",
}


def pick_mood() -> str:
    return random.choice(BOT_MOODS)


def build_hq_home(user) -> str:
    balance = format_currency(user.balance or 0)
    uid = ui.esc(user.telegram_id)
    mood = ui.esc(pick_mood())
    return (
        f"🛡️ <b>تنبيه أمني</b>\n\n"
        f"لا تعتمد أي رابط أو رسالة خارج هذا البوت\n"
        f"الدعم الرسمي موجود من زر الدعم فقط.\n\n"
        f"{DIV}\n\n"
        f"👑 <b>مقر نابليون</b>\n\n"
        f"💎 رصيدك: <b>{balance}</b>\n"
        f"🆔 رقمك: <code>{uid}</code>\n\n"
        f"📢 مزاج البوت اليوم:\n{mood}\n\n"
        f"{DIV}\n\n"
        f"اختار العملية وضغطة وحدة بتكفي 👇"
    )


def rate_limited(context, user_id: int) -> bool:
    """True إذا الضغط مبكر (خلال ثانيتين)."""
    now = time.monotonic()
    key = "_cb_rate"
    bucket = context.application.bot_data.setdefault(key, {})
    last = bucket.get(user_id, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return True
    bucket[user_id] = now
    return False


def withdraw_review_text(account: str, amount: float, method: str) -> str:
    return (
        "🧾 <b>راجع العملية</b>\n\n"
        f"🆔 الحساب: <code>{ui.esc(account)}</code>\n"
        f"💰 المبلغ: <b>{format_currency(amount)}</b>\n"
        f"💳 الطريقة: <b>{ui.esc(method)}</b>\n\n"
        "المحاسب رافع إيده عن أي رقم كتبته وإنت مغمّض 😂"
    )


def withdraw_pending_receipt(order_id, amount, account, when: str) -> str:
    return (
        f"🧾 العملية: <b>#{ui.esc(order_id)}</b>\n"
        f"🟡 الحالة: قيد المراجعة\n"
        f"🕒 وقت الطلب: {ui.esc(when)}\n\n"
        f"💰 المبلغ: <b>{format_currency(amount)}</b>\n"
        f"🆔 الحساب: <code>{ui.esc(account)}</code>\n\n"
        "الطلب وصل للمحاسبة... لا تضغط مرتين 🔒"
    )


def withdraw_done_receipt(order_id, amount, account, when: str) -> str:
    return (
        "👑 <b>إيصال نابليون</b>\n\n"
        "✅ تمت العملية بنجاح\n"
        f"💰 المبلغ: <b>{format_currency(amount)}</b>\n"
        f"🆔 الحساب: <code>{ui.esc(account)}</code>\n"
        f"🧾 الرقم: <b>#{ui.esc(order_id)}</b>\n"
        f"🕒 الوقت: {ui.esc(when)}\n\n"
        "المحاسب ختمها ورجع يختفي بالغموض 😂"
    )


def withdraw_failed_receipt(order_id, when: str = "") -> str:
    return (
        f"🧾 العملية: <b>#{ui.esc(order_id)}</b>\n"
        f"🔴 الحالة: تعذّر التنفيذ\n"
        + (f"🕒 الوقت: {ui.esc(when)}\n" if when else "")
        + "\nإذا بدك، افتح طلب جديد من المقر."
    )


def duplicate_order_text() -> str:
    return "الطلب موجود أصلًا.\n\nلا تعملنا نسختين من نفس الفيلم 😂"


def share_referral_text(link: str) -> str:
    return (
        "لقيت بوت مرتب لتعبئة وسحب iChancy،\n"
        "والأغرب إن ردوده أظرف من بعض البشر 😂\n\n"
        f"ادخل من رابطي:\n{link}\n\n"
        "🔞 للبالغين فقط، واستخدم الخدمة بمسؤولية."
    )


def match_secret_reply(text: str) -> Optional[str]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned in SECRET_REPLIES:
        return SECRET_REPLIES[cleaned]
    lower = cleaned.lower()
    if lower in ("هههه", "ههه", "ههاها", "hahaha", "haha"):
        return SECRET_REPLIES["هههه"]
    if cleaned in ("😂", "🤣", "😆", "😅"):
        return SECRET_REPLIES["😂"]
    return None
