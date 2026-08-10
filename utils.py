"""
أدوات مساعدة للبوت
"""

import html
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from database import User, Transaction

def format_currency(amount: float) -> str:
    """تنسيق العملة بدون فواصل ولا أصفار زائدة (200 بدل 200.00)."""
    try:
        val = float(amount or 0)
    except (TypeError, ValueError):
        val = 0.0
    if abs(val - round(val)) < 1e-9:
        return str(int(round(val)))
    text = f"{val:.2f}".rstrip("0").rstrip(".")
    return text


def tg_code(value) -> str:
    """نص قابل للنسخ داخل رسالة HTML"""
    return f"<code>{html.escape(str(value), quote=False)}</code>"


def tg_bold(value) -> str:
    """نص عريض داخل رسالة HTML"""
    return f"<b>{html.escape(str(value), quote=False)}</b>"


def calculate_withdrawal_fee(amount: float, fee_percentage: float = None) -> tuple[float, float]:
    """حساب رسوم السحب: (الرسوم، صافي المبلغ للمستلم)"""
    from config import Config
    if fee_percentage is None:
        fee_percentage = Config.WITHDRAWAL_FEE_PERCENTAGE
    fee = round(amount * (fee_percentage / 100), 2)
    net = round(amount - fee, 2)
    return fee, net


async def safe_edit_callback_message(
    update,
    text: str,
    reply_markup=None,
    parse_mode=None,
    context=None,
    disable_web_page_preview=None,
):
    """
    تعديل رسالة الكولباك بأمان.
    رسائل الصور/الفيديو لا تُعدَّل بـ editMessageText — نحذفها ونرسل نصاً جديداً.
    عند فشل التنسيق (Markdown/HTML) نعيد الإرسال كنص عادي.
    """
    from telegram.error import TelegramError

    query = getattr(update, "callback_query", None)
    if not query or not query.message:
        target = getattr(update, "effective_message", None) or getattr(update, "message", None)
        if target:
            kwargs = {"text": text, "reply_markup": reply_markup}
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            if disable_web_page_preview is not None:
                kwargs["disable_web_page_preview"] = disable_web_page_preview
            try:
                await target.reply_text(**kwargs)
            except TelegramError as exc:
                if parse_mode and "parse" in str(exc).lower():
                    kwargs.pop("parse_mode", None)
                    await target.reply_text(**kwargs)
                else:
                    raise
        return

    message = query.message
    bot = context.bot if context is not None else query.get_bot()
    is_media = bool(
        message.photo
        or message.video
        or message.document
        or message.animation
        or message.sticker
        or message.voice
        or message.audio
    )

    send_kwargs = {
        "chat_id": message.chat_id,
        "text": text,
        "reply_markup": reply_markup,
    }
    if parse_mode:
        send_kwargs["parse_mode"] = parse_mode
    if disable_web_page_preview is not None:
        send_kwargs["disable_web_page_preview"] = disable_web_page_preview

    async def _send_plain():
        plain = dict(send_kwargs)
        plain.pop("parse_mode", None)
        # أزل وسوم HTML الظاهرة إن فشل التنسيق
        plain["text"] = re.sub(r"</?[^>]+>", "", text)
        await bot.send_message(**plain)

    if is_media:
        try:
            await message.delete()
        except TelegramError:
            pass
        try:
            await bot.send_message(**send_kwargs)
        except TelegramError as exc:
            if parse_mode and "parse" in str(exc).lower():
                await _send_plain()
            else:
                raise
        return

    try:
        edit_kwargs = {"text": text, "reply_markup": reply_markup}
        if parse_mode:
            edit_kwargs["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            edit_kwargs["disable_web_page_preview"] = disable_web_page_preview
        await query.edit_message_text(**edit_kwargs)
    except TelegramError as exc:
        err = str(exc).lower()
        if parse_mode and "parse" in err:
            try:
                edit_plain = {
                    "text": re.sub(r"</?[^>]+>", "", text),
                    "reply_markup": reply_markup,
                }
                if disable_web_page_preview is not None:
                    edit_plain["disable_web_page_preview"] = disable_web_page_preview
                await query.edit_message_text(**edit_plain)
                return
            except TelegramError:
                pass
        if any(
            key in err
            for key in (
                "no text",
                "message is not modified",
                "message to edit not found",
                "message can't be edited",
                "parse",
            )
        ):
            try:
                await message.delete()
            except TelegramError:
                pass
            try:
                await bot.send_message(**send_kwargs)
            except TelegramError as send_exc:
                if parse_mode and "parse" in str(send_exc).lower():
                    await _send_plain()
                else:
                    raise
            return
        raise


def is_benign_telegram_error(error) -> bool:
    """أخطاء تيليجرام المتوقعة التي لا تستدعي إزعاج المستخدم."""
    if error is None:
        return False
    err = str(error).lower()
    return any(
        key in err
        for key in (
            "no text in the message to edit",
            "message is not modified",
            "message to delete not found",
            "message to edit not found",
            "message can't be edited",
            "message_id_invalid",
            "query is too old",
            "query id is invalid",
            "button_data_invalid",
        )
    )


def user_facing_error_message(error) -> str:
    """رسالة خطأ واضحة للمستخدم بدون تفاصيل تقنية حسّاسة."""
    raw = getattr(error, "message", None) or str(error or "")
    text = raw.lower()

    if "member list is inaccessible" in text or "bot is not a member" in text:
        return (
            "⚠️ تعذر التحقق من الاشتراك بالقناة حالياً.\n"
            "تأكد أن البوت مشرف في القناة ثم أعد المحاولة."
        )
    if "timed out" in text or "timeout" in text:
        return "⏱ انتهت مهلة الاتصال. حاول مرة أخرى خلال لحظات."
    if "connection" in text or "network" in text or "temporary failure" in text:
        return "🌐 مشكلة مؤقتة في الاتصال. حاول مجدداً."
    if "flood" in text or "too many requests" in text or "retry after" in text:
        return "⏳ الطلبات كثيرة الآن. انتظر قليلاً ثم أعد المحاولة."
    if "unauthorized" in text or "forbidden" in text:
        return "❌ لا يمكن إكمال العملية الآن. تواصل مع الدعم."
    if "can't parse entities" in text or "parse entities" in text:
        return "❌ تعذر عرض الرسالة بسبب تنسيق غير صالح. أعد المحاولة."
    if ".env" in text or "traceback" in text or "sqlalchemy" in text:
        return (
            "❌ الخدمة غير جاهزة حالياً.\n"
            "تواصل مع الإدارة."
        )
    if "api syria" in text or "apisyria" in text:
        return (
            "❌ تعذر التحقق عبر خدمة الدفع حالياً.\n"
            "تحقق من رقم العملية أو حاول لاحقاً."
        )
    if "ichancy" in text and "فشل" not in raw:
        return "❌ تعذر إكمال عملية Ichancy حالياً. حاول لاحقاً أو تواصل مع الدعم."

    # رسائل عربية قصيرة وآمنة من طبقة التحقق (مبلغ/عملية/مهلة)
    if raw and len(raw) <= 220 and any("\u0600" <= c <= "\u06FF" for c in raw):
        return raw if raw.startswith(("❌", "⚠️", "⏱")) else f"❌ {raw}"

    return (
        "❌ حدث خطأ أثناء تنفيذ العملية.\n"
        "أعد المحاولة من الأزرار أدناه، وإذا تكرر الخطأ تواصل مع الدعم."
    )

def validate_amount(amount_str: str, min_amount: float = 0, max_amount: float = float('inf')) -> tuple[bool, float, str]:
    """التحقق من صحة المبلغ"""
    try:
        amount = float(amount_str)
        
        if amount <= 0:
            return False, 0, "❌ المبلغ يجب أن يكون أكبر من صفر"
        
        if amount < min_amount:
            return False, 0, f"❌ الحد الأدنى هو {format_currency(min_amount)}"
        
        if amount > max_amount:
            return False, 0, f"❌ الحد الأقصى هو {format_currency(max_amount)}"
        
        return True, amount, ""
        
    except ValueError:
        return False, 0, "❌ يرجى إدخال مبلغ صحيح"

def get_user_display_name(user: User) -> str:
    """الحصول على اسم المستخدم للعرض — بدون Unknown فارغ."""
    if not user:
        return "مستخدم غير معروف"
    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "last_name", None) or "").strip()
    username = (getattr(user, "username", None) or "").strip()
    tg_id = getattr(user, "telegram_id", None)
    if first and last:
        return f"{first} {last}"
    if first:
        return first
    if username:
        return f"@{username}"
    if tg_id:
        return f"مستخدم {tg_id}"
    return "مستخدم غير معروف"

def format_transaction_type(transaction_type: str) -> str:
    """تنسيق نوع المعاملة"""
    types = {
        "deposit": "💰 إيداع",
        "withdraw": "💸 سحب",
        "referral": "👥 إحالة",
        "gift": "🎁 هدية",
        "gift_code": "🎁 كود هدية",
        "manual": "⚙️ يدوي"
    }
    return types.get(transaction_type, transaction_type)

def format_transaction_status(status: str) -> str:
    """تنسيق حالة المعاملة"""
    statuses = {
        "pending": "⏳ قيد المراجعة",
        "pending_review": "⏳ قيد المراجعة",
        "awaiting_payout": "💸 بانتظار التقبيض",
        "cancel_requested": "↩️ طلب إلغاء قيد المراجعة",
        "processing": "⚙️ قيد التنفيذ",
        "paid": "✅ تم التقبيض",
        "completed": "✅ تم التقبيض",
        "failed": "❌ مرفوض",
        "rejected": "❌ مرفوض",
        "cancelled": "🚫 ملغي",
    }
    return statuses.get(status, status)

def format_payment_method(method: str) -> str:
    """تنسيق طريقة الدفع"""
    methods = {
        "syriatel_cash": "📱 سيريتل كاش",
        "shamcash": "💳 شام كاش",
        "bank": "🏦 البنك",
        "usdt": "💰 USDT",
        "manual": "⚙️ يدوي"
    }
    return methods.get(method, method)

def format_datetime(dt: datetime) -> str:
    """تنسيق التاريخ والوقت"""
    if not dt:
        return "غير محدد"
    
    now = datetime.utcnow()
    diff = now - dt
    
    if diff.days == 0:
        if diff.seconds < 3600:  # أقل من ساعة
            minutes = diff.seconds // 60
            return f"منذ {minutes} دقيقة"
        else:  # أقل من يوم
            hours = diff.seconds // 3600
            return f"منذ {hours} ساعة"
    elif diff.days == 1:
        return "أمس"
    elif diff.days < 7:
        return f"منذ {diff.days} أيام"
    else:
        return dt.strftime("%Y-%m-%d %H:%M")

def validate_telegram_id(telegram_id_str: str) -> tuple[bool, str, str]:
    """التحقق من صحة معرف التليجرام"""
    try:
        telegram_id = int(telegram_id_str)
        if telegram_id <= 0:
            return False, "", "❌ معرف التليجرام يجب أن يكون رقم موجب"
        return True, str(telegram_id), ""
    except ValueError:
        return False, "", "❌ معرف التليجرام يجب أن يكون رقم"

def validate_username(username: str) -> tuple[bool, str, str]:
    """التحقق من صحة اسم المستخدم"""
    # إزالة @ إذا كانت موجودة
    if username.startswith('@'):
        username = username[1:]
    
    # التحقق من صحة اسم المستخدم
    if not re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
        return False, "", "❌ اسم المستخدم يجب أن يحتوي على 5-32 حرف (أحرف إنجليزية وأرقام و _ فقط)"
    
    return True, username, ""

def paginate_list(items: List[Any], page: int = 1, per_page: int = 10) -> tuple[List[Any], int, int]:
    """تقسيم القائمة إلى صفحات"""
    total_items = len(items)
    total_pages = (total_items + per_page - 1) // per_page
    
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages
    
    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    
    return items[start_index:end_index], page, total_pages

def format_transaction_history(transactions: List[Transaction], page: int = 1, per_page: int = 10) -> str:
    """تنسيق سجل المعاملات"""
    if not transactions:
        return "📭 لا توجد معاملات"
    
    paginated_transactions, current_page, total_pages = paginate_list(transactions, page, per_page)
    
    message = f"📜 سجل المعاملات (صفحة {current_page}/{total_pages})\n\n"
    
    for transaction in paginated_transactions:
        message += f"""
{format_transaction_type(transaction.transaction_type)} {format_currency(transaction.amount)}
{format_transaction_status(transaction.status)}
{format_payment_method(transaction.method or 'غير محدد')}
📅 {format_datetime(transaction.created_at)}
{'📝 ' + transaction.description if transaction.description else ''}
{'━' * 30}
        """
    
    return message.strip()

def calculate_referral_earnings(deposit_amount: float, referral_percentage: float) -> float:
    """حساب أرباح الإحالة"""
    return deposit_amount * (referral_percentage / 100)

def generate_transaction_reference() -> str:
    """توليد مرجع المعاملة"""
    import uuid
    return str(uuid.uuid4())[:8].upper()

def is_valid_amount_format(amount_str: str) -> bool:
    """التحقق من تنسيق المبلغ"""
    try:
        float(amount_str)
        return True
    except ValueError:
        return False

def clean_phone_number(phone: str) -> str:
    """تنظيف رقم الهاتف"""
    # إزالة جميع الرموز غير الرقمية
    phone = re.sub(r'[^\d]', '', phone)
    
    # إضافة رمز البلد إذا لم يكن موجود
    if phone.startswith('9') and len(phone) == 9:
        phone = '963' + phone
    elif phone.startswith('09') and len(phone) == 10:
        phone = '963' + phone[1:]
    
    return phone

def format_phone_number(phone: str) -> str:
    """تنسيق رقم الهاتف للعرض"""
    if len(phone) == 12 and phone.startswith('963'):
        return f"+{phone[:3]} {phone[3:5]} {phone[5:8]} {phone[8:]}"
    return phone

def get_time_range_filter(range_type: str) -> tuple[datetime, datetime]:
    """الحصول على فلتر النطاق الزمني"""
    now = datetime.utcnow()
    
    if range_type == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif range_type == "week":
        start = now - timedelta(days=7)
        end = now
    elif range_type == "month":
        start = now - timedelta(days=30)
        end = now
    elif range_type == "year":
        start = now - timedelta(days=365)
        end = now
    else:  # all
        start = datetime(2020, 1, 1)
        end = now
    
    return start, end

def escape_markdown(text: str) -> str:
    """تجنب رموز الماركداون"""
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

def truncate_text(text: str, max_length: int = 100) -> str:
    """اختصار النص"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def format_user_stats(user: User) -> str:
    """تنسيق إحصائيات المستخدم"""
    return f"""
👤 معلومات المستخدم

🆔 المعرف: {user.telegram_id}
👤 الاسم: {get_user_display_name(user)}
💰 الرصيد: {format_currency(user.balance)}
👥 الإحالات: {user.referral_count}
💵 أرباح الإحالات: {format_currency(user.referral_earnings)}
🔗 كود الإحالة: {user.referral_code}
📅 تاريخ التسجيل: {format_datetime(user.created_at)}
📅 آخر نشاط: {format_datetime(user.last_activity)}
    """

def validate_gift_code(code: str) -> tuple[bool, str, str]:
    """التحقق من صحة كود الهدية"""
    if not code:
        return False, "", "❌ يرجى إدخال كود الهدية"
    
    # تنظيف الكود
    code = code.strip().upper()
    
    # التحقق من طول الكود
    if len(code) < 4 or len(code) > 20:
        return False, "", "❌ كود الهدية يجب أن يكون بين 4-20 حرف"
    
    # التحقق من الأحرف المسموحة
    if not re.match(r'^[A-Z0-9]+$', code):
        return False, "", "❌ كود الهدية يجب أن يحتوي على أحرف إنجليزية وأرقام فقط"
    
    return True, code, ""

