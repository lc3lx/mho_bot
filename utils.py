"""
أدوات مساعدة للبوت
"""

import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from database import User, Transaction

def format_currency(amount: float) -> str:
    """تنسيق العملة"""
    return f"{amount:,.2f}"

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
    """الحصول على اسم المستخدم للعرض"""
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    elif user.username:
        return f"@{user.username}"
    else:
        return f"المستخدم {user.telegram_id}"

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
        "completed": "✅ مكتملة",
        "failed": "❌ فاشلة",
        "cancelled": "🚫 ملغية"
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

