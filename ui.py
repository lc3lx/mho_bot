"""
طبقة التصميم: إطارات، أشرطة تقدّم، وتأثيرات حركية للرسائل.

تيليجرام لا يسمح بتلوين أزرار الـ inline أو تحريكها، لذلك الإحساس البصري
يُبنى من: تنسيق HTML (عريض/اقتباس/نص قابل للنسخ)، فواصل، وتعديل الرسالة
على عدة إطارات لمحاكاة الحركة.
"""

import asyncio
import html as _html

from telegram.constants import ChatAction
from telegram.error import TelegramError

DIVIDER = "━━━━━━━━━━━━━━━━"
DIVIDER_SOFT = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"

FILLED = "▰"
EMPTY = "▱"

# إطارات فتح القائمة — كل إطار تعديل واحد للرسالة
OPEN_FRAMES = (
    f"⚡ {FILLED * 2}{EMPTY * 6}",
    f"⚡ {FILLED * 5}{EMPTY * 3}",
    f"⚡ {FILLED * 8}",
)

# إطارات الانتظار للعمليات البطيئة
WORK_FRAMES = ("◐", "◓", "◑", "◒")


def esc(value) -> str:
    """تهريب نص المستخدم قبل وضعه داخل رسالة HTML"""
    return _html.escape(str(value), quote=False)


def bar(ratio: float, width: int = 10) -> str:
    """شريط تقدّم نصي من 0.0 إلى 1.0"""
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * width)
    return FILLED * filled + EMPTY * (width - filled)


def card(title: str, rows: list[tuple[str, str]], footer: str = "") -> str:
    """
    بطاقة HTML موحّدة الشكل.
    rows: قائمة (تسمية، قيمة) — القيمة تُوضع كما هي (يمكن أن تحوي وسوم HTML).
    """
    lines = [f"<b>{esc(title)}</b>", DIVIDER]
    for label, value in rows:
        lines.append(f"{esc(label)} {value}")
    if footer:
        lines += [DIVIDER, f"<i>{esc(footer)}</i>"]
    return "\n".join(lines)


def quote(text: str) -> str:
    """اقتباس — يظهر بشريط جانبي ملوّن في تيليجرام"""
    return f"<blockquote>{esc(text)}</blockquote>"


async def typing(context, chat_id: str | int) -> None:
    """مؤشر «يكتب…» — حركة حقيقية يراها المستخدم"""
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except TelegramError:
        pass


async def animate(query, frames=OPEN_FRAMES, delay: float = 0.18, reply_markup=None) -> None:
    """
    تشغيل إطارات على نفس الرسالة لمحاكاة الحركة.

    تُمرَّر لوحة المفاتيح مع كل إطار كي لا تختفي الأزرار لو فشل التعديل الأخير.
    أي فشل هنا يُتجاهل — التأثير تجميلي ولا يجوز أن يكسر التدفق.
    """
    if not query or not query.message:
        return
    for frame in frames:
        try:
            await query.edit_message_text(frame, reply_markup=reply_markup)
        except TelegramError:
            return
        await asyncio.sleep(delay)
