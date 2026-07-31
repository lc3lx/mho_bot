"""
طبقة التصميم: إطارات، أشرطة تقدّم، وتأثيرات حركية للرسائل.

تيليجرام لا يسمح بتلوين أزرار الـ inline أو تحريكها، لذلك الإحساس البصري
يُبنى من: تنسيق HTML (عريض/اقتباس/نص قابل للنسخ)، فواصل، وتعديل الرسالة
على عدة إطارات لمحاكاة الحركة.
"""

import asyncio
import html as _html
import os

from telegram.constants import ChatAction
from telegram.error import TelegramError

# حد تيليجرام لطول الكابشن المرفق بوسائط
CAPTION_LIMIT = 1024

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


def _banner_source(banner: str):
    """
    يقبل file_id أو رابط https أو مسار ملف محلي.
    يعيد كائناً صالحاً للإرسال، أو None إذا كان المسار المحلي مفقوداً.
    """
    if not banner:
        return None
    if banner.startswith(("http://", "https://")):
        return banner
    if os.path.exists(banner):
        return open(banner, "rb")
    # يُفترض أنه file_id
    return banner


async def show_banner_screen(update, context, text, reply_markup, banner: str) -> bool:
    """
    عرض شاشة ببانر متحرك فوق النص (مثل البوتات الاحترافية).

    إذا كانت الرسالة الحالية تحمل وسائط أصلاً نعدّل الكابشن فقط — بدون وميض.
    يعيد False عند الفشل ليُكمل المستدعي بالمسار النصي العادي.
    """
    if not banner or len(text) > CAPTION_LIMIT:
        return False

    query = getattr(update, "callback_query", None)
    message = getattr(query, "message", None) if query else None
    bot = context.bot

    if message and (message.animation or message.photo or message.video):
        try:
            await query.edit_message_caption(
                caption=text, reply_markup=reply_markup, parse_mode="HTML"
            )
            return True
        except TelegramError as exc:
            # نفس المحتوى تماماً — الشاشة معروضة بالفعل، لا داعي لإعادة الإرسال
            if "not modified" in str(exc).lower():
                return True

    chat_id = None
    if message:
        chat_id = message.chat_id
    elif getattr(update, "effective_chat", None):
        chat_id = update.effective_chat.id
    if chat_id is None:
        return False

    if message:
        try:
            await message.delete()
        except TelegramError:
            pass

    source = _banner_source(banner)
    if source is None:
        return False
    try:
        await bot.send_animation(
            chat_id=chat_id,
            animation=source,
            caption=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return True
    except TelegramError:
        return False
    finally:
        if hasattr(source, "close"):
            source.close()


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
