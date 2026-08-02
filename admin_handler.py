"""
معالج صلاحيات الإدمن
"""

import asyncio
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from database import DatabaseManager, User, Transaction, GiftCode
from config import Config
from keyboards import Keyboards
from utils import (
    format_currency,
    get_user_display_name,
    calculate_withdrawal_fee,
    safe_edit_callback_message,
)
from ichancy_handler import ichancy_client
from ichancy_client import IchancyClient
import html as _html

logger = logging.getLogger(__name__)
db = DatabaseManager()


async def _admin_edit(
    update: Update, text: str, reply_markup=None, context=None, parse_mode=None
):
    """تعديل/إرسال رسالة لوحة الإدمن بأمان (نص أو وسائط)."""
    if update.callback_query:
        await safe_edit_callback_message(
            update,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            context=context,
        )
    elif update.effective_message:
        kwargs = {"text": text, "reply_markup": reply_markup}
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        await update.effective_message.reply_text(**kwargs)


class AdminHandler:
    """فئة معالج صلاحيات الإدمن"""
    
    @staticmethod
    async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """لوحة تحكم الإدمن الرئيسية"""
        user_id = update.effective_user.id
        
        if user_id not in Config.ADMIN_IDS:
            target = update.effective_message or (
                update.callback_query.message if update.callback_query else None
            )
            if target:
                await target.reply_text("❌ ليس لديك صلاحية للوصول إلى لوحة الإدمن")
            return
        
        # إحصائيات عامة
        session = db.get_session()
        try:
            total_users = session.query(User).count()
            banned_users = session.query(User).filter(User.is_banned == True).count()
            total_balance = session.query(User).with_entities(db.func.sum(User.balance)).scalar() or 0
            today_transactions = session.query(Transaction).filter(
                Transaction.created_at >= datetime.now().date()
            ).count()
            pending_count = session.query(Transaction).filter(
                Transaction.status == "pending"
            ).count()
            
            message = f"""
🔧 لوحة تحكم الإدمن

📊 إحصائيات عامة:
👥 إجمالي المستخدمين: {total_users}
🚫 المحظورون: {banned_users}
💰 إجمالي الأرصدة: {format_currency(total_balance)}
📈 معاملات اليوم: {today_transactions}
⏳ معاملات معلقة: {pending_count}

اختر العملية المطلوبة:
            """
            
            await _admin_edit(
                update, message, reply_markup=Keyboards.admin_panel(), context=context
            )
        finally:
            session.close()
    
    @staticmethod
    async def user_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إدارة المستخدمين"""
        message = """
👥 إدارة المستخدمين

اختر العملية المطلوبة:
        """
        
        await _admin_edit(
            update,
            message,
            reply_markup=Keyboards.user_management_menu(),
            context=context,
        )
    
    @staticmethod
    async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إضافة رصيد لمستخدم"""
        message = """
💰 إضافة رصيد

أرسل معرف المستخدم والمبلغ بالتنسيق التالي:
معرف_المستخدم المبلغ

مثال: 123456789 100
        """
        
        context.user_data['admin_operation'] = 'add_balance'
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.cancel_admin_operation()
        )
    
    @staticmethod
    async def deduct_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """خصم رصيد من مستخدم"""
        message = """
💸 خصم رصيد

أرسل معرف المستخدم والمبلغ بالتنسيق التالي:
معرف_المستخدم المبلغ

مثال: 123456789 50
        """
        
        context.user_data['admin_operation'] = 'deduct_balance'
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.cancel_admin_operation()
        )
    
    @staticmethod
    async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض معلومات مستخدم"""
        message = """
ℹ️ معلومات المستخدم

أرسل معرف المستخدم أو اسم المستخدم:
        """
        
        context.user_data['admin_operation'] = 'user_info'
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.cancel_admin_operation()
        )

    @staticmethod
    async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """حظر مستخدم"""
        context.user_data["admin_operation"] = "ban_user"
        await _admin_edit(
            update,
            "🚫 حظر مستخدم\n\nأرسل معرف التليجرام للمستخدم المراد حظره:",
            reply_markup=Keyboards.cancel_admin_operation(),
            context=context,
        )

    @staticmethod
    async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """فك حظر مستخدم"""
        context.user_data["admin_operation"] = "unban_user"
        await _admin_edit(
            update,
            "✅ فك حظر مستخدم\n\nأرسل معرف التليجرام للمستخدم:",
            reply_markup=Keyboards.cancel_admin_operation(),
            context=context,
        )

    @staticmethod
    async def user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إحصائيات المستخدمين"""
        session = db.get_session()
        try:
            total = session.query(User).count()
            banned = session.query(User).filter(User.is_banned == True).count()
            with_ichancy = session.query(User).filter(
                User.ichancy_player_id.isnot(None)
            ).count()
            funded = (
                session.query(User.id)
                .join(Transaction, Transaction.user_id == User.id)
                .filter(
                    Transaction.status == "completed",
                    Transaction.transaction_type.in_(("deposit", "gift_code", "manual")),
                    Transaction.amount > 0,
                )
                .distinct()
                .count()
            )
            top = session.query(User).order_by(User.balance.desc()).limit(5).all()
            lines = [
                "📊 إحصائيات المستخدمين",
                "",
                f"👥 الإجمالي: {total}",
                f"🚫 المحظورون: {banned}",
                f"🎰 لديهم Ichancy: {with_ichancy}",
                f"💵 شحنوا مرة على الأقل: {funded}",
                "",
                "🏆 أعلى 5 أرصدة:",
            ]
            for i, u in enumerate(top, 1):
                lines.append(
                    f"{i}. {get_user_display_name(u)} — "
                    f"{format_currency(u.balance or 0)} (ID {u.telegram_id})"
                )
            await _admin_edit(
                update,
                "\n".join(lines),
                reply_markup=Keyboards.admin_back_menu(),
                context=context,
            )
        finally:
            session.close()
    
    @staticmethod
    async def create_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إنشاء كود جائزة (استخدام مرة واحدة فقط)"""
        message = """
🏆 مود أكواد الجوائز — إنشاء كود

الكود يُستخدم **مرة واحدة فقط**.

أرسل:
الكود المبلغ

مثال:
PRIZE100 10000
        """

        context.user_data['admin_operation'] = 'create_gift_code'

        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.cancel_admin_operation()
        )
    
    @staticmethod
    async def view_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض الإحصائيات التفصيلية"""
        session = db.get_session()
        try:
            # إحصائيات المستخدمين
            total_users = session.query(User).count()
            active_users_today = session.query(User).filter(
                User.last_activity >= datetime.now().date()
            ).count()
            
            # إحصائيات المعاملات
            today = datetime.now().date()
            week_ago = today - timedelta(days=7)
            month_ago = today - timedelta(days=30)
            
            today_deposits = session.query(Transaction).filter(
                Transaction.transaction_type == 'deposit',
                Transaction.created_at >= today
            ).count()
            
            today_withdrawals = session.query(Transaction).filter(
                Transaction.transaction_type == 'withdraw',
                Transaction.created_at >= today
            ).count()
            
            week_transactions = session.query(Transaction).filter(
                Transaction.created_at >= week_ago
            ).count()
            
            month_transactions = session.query(Transaction).filter(
                Transaction.created_at >= month_ago
            ).count()
            
            # إحصائيات الأرصدة
            total_balance = session.query(User).with_entities(db.func.sum(User.balance)).scalar() or 0
            avg_balance = session.query(User).with_entities(db.func.avg(User.balance)).scalar() or 0
            
            message = f"""
📊 إحصائيات تفصيلية

👥 المستخدمون:
• إجمالي المستخدمين: {total_users}
• نشطون اليوم: {active_users_today}

💰 المعاملات:
• إيداعات اليوم: {today_deposits}
• سحوبات اليوم: {today_withdrawals}
• معاملات الأسبوع: {week_transactions}
• معاملات الشهر: {month_transactions}

💵 الأرصدة:
• إجمالي الأرصدة: {format_currency(total_balance)}
• متوسط الرصيد: {format_currency(avg_balance)}
            """
            
            await update.callback_query.edit_message_text(
                message,
                reply_markup=Keyboards.admin_back_menu()
            )
        finally:
            session.close()
    
    @staticmethod
    async def pending_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض المعاملات المعلقة"""
        session = db.get_session()
        try:
            pending = session.query(Transaction).filter(
                Transaction.status == 'pending'
            ).order_by(Transaction.created_at.desc()).limit(10).all()
            
            if not pending:
                message = "✅ لا توجد معاملات معلقة حالياً"
            else:
                message = "⏳ المعاملات المعلقة:\n\n"
                for i, transaction in enumerate(pending, 1):
                    user = session.query(User).filter(User.id == transaction.user_id).first()
                    message += f"{i}. {transaction.transaction_type.upper()}\n"
                    message += f"👤 {get_user_display_name(user)}\n"
                    message += f"💰 {format_currency(transaction.amount)}\n"
                    if transaction.transaction_type == "withdraw":
                        fee, net_amount = calculate_withdrawal_fee(transaction.amount)
                        message += (
                            f"📉 رسوم ({Config.WITHDRAWAL_FEE_PERCENTAGE:g}%): "
                            f"{format_currency(fee)}\n"
                            f"💵 حوّل: {format_currency(net_amount)}\n"
                        )
                    if transaction.withdraw_destination:
                        message += f"📍 الوجهة: {transaction.withdraw_destination}\n"
                    message += f"📅 {transaction.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                    message += f"🆔 ID: {transaction.id}\n\n"
            
            await _admin_edit(
                update,
                message,
                reply_markup=Keyboards.pending_transactions_menu(),
                context=context,
            )
        finally:
            session.close()
    
    @staticmethod
    async def approve_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """الموافقة على معاملة"""
        message = """
✅ الموافقة على معاملة

أرسل رقم المعاملة للموافقة عليها:
        """
        
        context.user_data['admin_operation'] = 'approve_transaction'
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.cancel_admin_operation()
        )
    
    @staticmethod
    async def reject_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """رفض معاملة"""
        message = """
❌ رفض معاملة

أرسل رقم المعاملة لرفضها:
        """
        
        context.user_data['admin_operation'] = 'reject_transaction'
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.cancel_admin_operation()
        )
    
    @staticmethod
    async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إرسال رسالة جماعية"""
        message = """
📢 إرسال رسالة جماعية

أرسل الرسالة التي تريد إرسالها لجميع المستخدمين:
        """
        
        context.user_data['admin_operation'] = 'broadcast'
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.cancel_admin_operation()
        )
    
    @staticmethod
    async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالجة مدخلات الإدمن"""
        operation = context.user_data.get('admin_operation')
        text = update.message.text.strip()
        
        if operation == 'add_balance':
            await AdminHandler._handle_balance_operation(update, context, text, 'add')
        elif operation == 'deduct_balance':
            await AdminHandler._handle_balance_operation(update, context, text, 'deduct')
        elif operation == 'user_info':
            await AdminHandler._handle_user_info(update, context, text)
        elif operation == 'create_gift_code':
            await AdminHandler._handle_create_gift_code(update, context, text)
        elif operation == 'approve_transaction':
            await AdminHandler._handle_transaction_action(update, context, text, 'approve')
        elif operation == 'reject_transaction':
            await AdminHandler._handle_transaction_action(update, context, text, 'reject')
        elif operation == 'broadcast':
            await AdminHandler._handle_broadcast(update, context, text)
        elif operation == 'ban_user':
            await AdminHandler._handle_ban_action(update, context, text, ban=True)
        elif operation == 'unban_user':
            await AdminHandler._handle_ban_action(update, context, text, ban=False)
        elif operation == 'set_shamcash_rate':
            ok = await AdminHandler._handle_set_rate(
                update, context, text, "shamcash_usd_rate"
            )
            if not ok:
                return
        elif operation == 'set_usdt_rate':
            ok = await AdminHandler._handle_set_rate(
                update, context, text, "usdt_syp_rate"
            )
            if not ok:
                return
        elif operation == 'set_proxy':
            ok = await AdminHandler._handle_set_proxy(update, context, text)
            if not ok:
                return
        elif str(operation or "").startswith("army_"):
            ok = await AdminHandler._handle_army_input(update, context, text, operation)
            if not ok:
                return
        
        # مسح العملية
        context.user_data.pop('admin_operation', None)
    
    @staticmethod
    async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض أسعار الصرف الحالية"""
        sham = Config.get_shamcash_usd_rate()
        usdt = Config.get_usdt_syp_rate()
        message = f"""
💱 أسعار الصرف

💵 شام كاش: 1 $ = {format_currency(sham)}
🟢 USDT: 1 USDT = {format_currency(usdt)}

اختر السعر الذي تريد تعديله:
        """
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.admin_exchange_rates(),
        )

    @staticmethod
    async def start_set_rate(
        update: Update, context: ContextTypes.DEFAULT_TYPE, rate_type: str
    ):
        if rate_type == "shamcash":
            context.user_data["admin_operation"] = "set_shamcash_rate"
            current = Config.get_shamcash_usd_rate()
            label = "شام كاش (دولار → ل.س)"
        else:
            context.user_data["admin_operation"] = "set_usdt_rate"
            current = Config.get_usdt_syp_rate()
            label = "USDT (USDT → ل.س)"

        await update.callback_query.edit_message_text(
            f"💱 تعديل سعر {label}\n\n"
            f"السعر الحالي: {format_currency(current)}\n\n"
            f"أرسل السعر الجديد (رقم فقط، مثال: 13500):",
            reply_markup=Keyboards.cancel_admin_operation(),
        )

    @staticmethod
    async def _handle_set_rate(
        update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, setting_key: str
    ) -> bool:
        try:
            rate = float(text.replace(",", "").strip())
            if rate <= 0:
                raise ValueError("rate must be positive")
        except ValueError:
            await update.message.reply_text(
                "❌ أدخل رقماً صحيحاً أكبر من صفر.",
                reply_markup=Keyboards.cancel_admin_operation(),
            )
            return False

        db.set_setting(setting_key, str(rate))
        label = "شام كاش" if setting_key == "shamcash_usd_rate" else "USDT"
        await update.message.reply_text(
            f"✅ تم تحديث سعر {label}:\n"
            f"1 = {format_currency(rate)} ل.س\n\n"
            f"يُطبَّق فوراً على طلبات الشحن الجديدة.",
            reply_markup=Keyboards.admin_panel(),
        )
        return True

    @staticmethod
    async def proxy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شاشة حالة بروكسي Ichancy"""
        status = ichancy_client.get_proxy_status()
        source_label = {
            "admin": "لوحة الأدمن",
            "env": "ملف .env",
        }.get(status["source"], status["source"])
        enabled = status["enabled"]
        message = f"""
🌐 بروكسي Ichancy

الحالة: {"✅ مفعّل" if enabled else "⏹ معطّل / اتصال مباشر"}
الرابط: <code>{_html.escape(status["masked"])}</code>
المصدر: {source_label}
المحرك: {status["backend"]}
يوزر مضبوط: {"نعم" if status["user_set"] else "لا"}

• التعيين يختبر البروكسي أولاً ثم يحفظه ويطبّقه فوراً
• إذا فشل الاختبار يبقى البروكسي الحالي كما هو
• التعطيل قرار صريح ولن يرجع تلقائياً لـ .env
        """
        await _admin_edit(
            update,
            message,
            reply_markup=Keyboards.admin_proxy_menu(enabled=enabled),
            context=context,
            parse_mode="HTML",
        )

    @staticmethod
    async def start_set_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """طلب رابط بروكسي جديد من الأدمن"""
        context.user_data["admin_operation"] = "set_proxy"
        await _admin_edit(
            update,
            "🌐 تعيين بروكسي Ichancy\n\n"
            "أرسل الرابط بسطر واحد:\n"
            "<code>socks5h://user:pass@host:port</code>\n"
            "أو\n"
            "<code>http://host:port</code>\n\n"
            "الأنواع المسموحة: http / https / socks5 / socks5h\n"
            "⚠️ سيتم اختباره على Ichancy قبل الحفظ.",
            reply_markup=Keyboards.cancel_admin_operation(),
            context=context,
            parse_mode="HTML",
        )

    @staticmethod
    async def _handle_set_proxy(
        update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> bool:
        try:
            cfg, masked = IchancyClient.validate_proxy_input(text)
        except ValueError as exc:
            await update.message.reply_text(
                f"❌ {exc}",
                reply_markup=Keyboards.cancel_admin_operation(),
                parse_mode="HTML",
            )
            return False

        wait = await update.message.reply_text(
            f"🧪 جاري اختبار البروكسي…\n<code>{masked}</code>\n"
            "لن يتغيّر الحالي إذا فشل الاختبار.",
            parse_mode="HTML",
        )
        result = await asyncio.to_thread(
            ichancy_client.apply_and_persist_proxy, cfg, test_first=True
        )
        try:
            await wait.delete()
        except TelegramError:
            pass

        if not result.ok:
            await update.message.reply_text(
                f"❌ فشل الاختبار — لم يُحفظ شيء\n"
                f"السبب: {_html.escape(result.message)}\n"
                f"البروكسي: <code>{_html.escape(result.masked_proxy)}</code>\n"
                f"المدة: {result.elapsed_ms}ms",
                reply_markup=Keyboards.admin_proxy_menu(
                    enabled=ichancy_client.get_proxy_status()["enabled"]
                ),
                parse_mode="HTML",
            )
            return True

        await update.message.reply_text(
            f"✅ تم اعتماد البروكسي وتطبيقه فوراً\n"
            f"<code>{_html.escape(result.masked_proxy)}</code>\n"
            f"{_html.escape(result.message)}\n"
            f"المدة: {result.elapsed_ms}ms",
            reply_markup=Keyboards.admin_proxy_menu(enabled=True),
            parse_mode="HTML",
        )
        return True

    @staticmethod
    async def test_current_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """اختبار الإعداد الفعّال دون تعديل"""
        status = ichancy_client.get_proxy_status()
        await _admin_edit(
            update,
            f"🧪 جاري اختبار البروكسي الحالي…\n<code>{status['masked']}</code>",
            reply_markup=Keyboards.admin_proxy_menu(enabled=status["enabled"]),
            context=context,
            parse_mode="HTML",
        )
        result = await asyncio.to_thread(ichancy_client.test_proxy_config, None)
        icon = "✅" if result.ok else "❌"
        await _admin_edit(
            update,
            f"{icon} نتيجة الاختبار\n"
            f"البروكسي: <code>{_html.escape(result.masked_proxy)}</code>\n"
            f"{_html.escape(result.message)}\n"
            f"المدة: {result.elapsed_ms}ms"
            + (f"\nHTTP: {result.http_status}" if result.http_status else ""),
            reply_markup=Keyboards.admin_proxy_menu(
                enabled=ichancy_client.get_proxy_status()["enabled"]
            ),
            context=context,
            parse_mode="HTML",
        )

    @staticmethod
    async def disable_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تعطيل البروكسي بشكل صريح"""
        await _admin_edit(
            update,
            "🛑 جاري تعطيل البروكسي والعودة للاتصال المباشر…",
            reply_markup=Keyboards.admin_proxy_menu(enabled=False),
            context=context,
        )
        result = await asyncio.to_thread(ichancy_client.disable_and_persist_proxy)
        warn = ""
        if not result.ok:
            warn = (
                "\n\n⚠️ التعطيل تم حفظه، لكن الاتصال المباشر فشل "
                f"({result.message}). قد تحتاج بروكسي شغال."
            )
        await _admin_edit(
            update,
            "⏹ تم تعطيل بروكسي Ichancy.\n"
            "الطلبات الآن مباشرة من السيرفر.\n"
            "لن يرجع تلقائياً لبروكسي .env."
            + warn,
            reply_markup=Keyboards.admin_proxy_menu(enabled=False),
            context=context,
        )
    
    @staticmethod
    async def _handle_balance_operation(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, operation: str):
        """معالجة عمليات الرصيد"""
        try:
            parts = text.split()
            if len(parts) != 2:
                await update.message.reply_text(
                    "❌ تنسيق خاطئ. استخدم: معرف_المستخدم المبلغ",
                    reply_markup=Keyboards.admin_panel()
                )
                return
            
            user_id = int(parts[0])
            amount = float(parts[1])
            
            session = db.get_session()
            try:
                user = session.query(User).filter(User.telegram_id == user_id).first()
                if not user:
                    await update.message.reply_text(
                        "❌ المستخدم غير موجود",
                        reply_markup=Keyboards.admin_panel()
                    )
                    return
                
                if operation == 'add':
                    user.balance += amount
                    action = "إضافة"
                    emoji = "➕"
                else:
                    if user.balance < amount:
                        await update.message.reply_text(
                            f"❌ رصيد المستخدم غير كافي\n💵 الرصيد الحالي: {format_currency(user.balance)}",
                            reply_markup=Keyboards.admin_panel()
                        )
                        return
                    user.balance -= amount
                    action = "خصم"
                    emoji = "➖"
                
                # إضافة سجل المعاملة
                transaction = Transaction(
                    user_id=user.id,
                    transaction_type='admin_adjustment',
                    amount=amount if operation == 'add' else -amount,
                    status='completed',
                    description=f"{action} رصيد من الإدمن"
                )
                session.add(transaction)
                session.commit()
                
                # إشعار المستخدم
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=f"{emoji} تم {action} {format_currency(amount)} إلى رصيدك\n💵 رصيدك الحالي: {format_currency(user.balance)}"
                    )
                except TelegramError:
                    logger.warning(f"لا يمكن إرسال إشعار للمستخدم {user.telegram_id}")
                
                await update.message.reply_text(
                    f"✅ تم {action} {format_currency(amount)} بنجاح\n👤 المستخدم: {get_user_display_name(user)}\n💵 الرصيد الجديد: {format_currency(user.balance)}",
                    reply_markup=Keyboards.admin_panel()
                )
            finally:
                session.close()
                
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ تنسيق خاطئ. استخدم: معرف_المستخدم المبلغ",
                reply_markup=Keyboards.admin_panel()
            )
    
    @staticmethod
    async def _handle_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """معالجة عرض معلومات المستخدم"""
        session = db.get_session()
        try:
            user = None
            
            # البحث بمعرف التليجرام
            if text.isdigit():
                user = session.query(User).filter(User.telegram_id == int(text)).first()
            
            # البحث باسم المستخدم
            if not user:
                username = text.replace('@', '')
                user = session.query(User).filter(User.username == username).first()
            
            if not user:
                await update.message.reply_text(
                    "❌ المستخدم غير موجود",
                    reply_markup=Keyboards.admin_panel()
                )
                return
            
            # إحصائيات المستخدم
            total_deposits = session.query(Transaction).filter(
                Transaction.user_id == user.id,
                Transaction.transaction_type == 'deposit',
                Transaction.status == 'completed'
            ).with_entities(db.func.sum(Transaction.amount)).scalar() or 0
            
            total_withdrawals = session.query(Transaction).filter(
                Transaction.user_id == user.id,
                Transaction.transaction_type == 'withdraw',
                Transaction.status == 'completed'
            ).with_entities(db.func.sum(Transaction.amount)).scalar() or 0
            
            transaction_count = session.query(Transaction).filter(
                Transaction.user_id == user.id
            ).count()
            
            message = f"""
👤 معلومات المستخدم

🆔 معرف التليجرام: {user.telegram_id}
👤 الاسم: {get_user_display_name(user)}
📱 اسم المستخدم: @{user.username or 'غير محدد'}
📅 تاريخ التسجيل: {user.created_at.strftime('%Y-%m-%d')}
📅 آخر نشاط: {user.last_activity.strftime('%Y-%m-%d %H:%M') if user.last_activity else 'غير محدد'}

💰 الأرصدة:
💵 الرصيد الحالي: {format_currency(user.balance)}
📈 إجمالي الإيداعات: {format_currency(total_deposits)}
📉 إجمالي السحوبات: {format_currency(total_withdrawals)}

👥 الإحالات:
🔗 كود الإحالة: {user.referral_code}
👥 عدد الإحالات: {user.referral_count}
💰 أرباح الإحالات: {format_currency(user.referral_earnings)}
👤 أحاله: {user.referred_by or 'لا يوجد'}

📊 الإحصائيات:
📈 عدد المعاملات: {transaction_count}
            """
            
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.admin_panel()
            )
        finally:
            session.close()
    
    @staticmethod
    async def _handle_create_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """معالجة إنشاء كود جائزة — استخدام مرة واحدة فقط"""
        try:
            parts = text.split()
            if len(parts) < 2:
                await update.message.reply_text(
                    "❌ تنسيق خاطئ. استخدم: الكود المبلغ\nمثال: PRIZE100 10000",
                    reply_markup=Keyboards.admin_panel()
                )
                return

            code = parts[0].upper()
            amount = float(parts[1])
            # الكود لمرة واحدة فقط دائماً
            max_uses = 1

            session = db.get_session()
            try:
                existing = session.query(GiftCode).filter(GiftCode.code == code).first()
                if existing:
                    await update.message.reply_text(
                        "❌ هذا الكود موجود بالفعل",
                        reply_markup=Keyboards.admin_panel()
                    )
                    return

                gift_code = GiftCode(
                    code=code,
                    amount=amount,
                    max_uses=max_uses,
                    current_uses=0,
                    is_active=True,
                    created_by=update.effective_user.id
                )
                session.add(gift_code)
                session.commit()

                await update.message.reply_text(
                    f"✅ تم إنشاء كود الجائزة\n"
                    f"🏆 الكود: `{code}`\n"
                    f"💰 المبلغ: {format_currency(amount)}\n"
                    f"🔢 الاستخدام: مرة واحدة فقط",
                    reply_markup=Keyboards.admin_panel(),
                    parse_mode="Markdown",
                )
            finally:
                session.close()

        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ تنسيق خاطئ. استخدم: الكود المبلغ\nمثال: PRIZE100 10000",
                reply_markup=Keyboards.admin_panel()
            )
    
    @staticmethod
    async def _handle_transaction_action(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, action: str):
        """معالجة الموافقة/رفض المعاملات"""
        try:
            transaction_id = int(text)
            
            session = db.get_session()
            try:
                transaction = session.query(Transaction).filter(Transaction.id == transaction_id).first()
                if not transaction:
                    await update.message.reply_text(
                        "❌ المعاملة غير موجودة",
                        reply_markup=Keyboards.admin_panel()
                    )
                    return
                
                if transaction.status != 'pending':
                    await update.message.reply_text(
                        f"❌ المعاملة {transaction.status} بالفعل",
                        reply_markup=Keyboards.admin_panel()
                    )
                    return
                
                user = session.query(User).filter(User.id == transaction.user_id).first()
                
                if action == 'approve':
                    transaction.status = 'completed'
                    transaction.processed_at = datetime.utcnow()

                    if transaction.transaction_type == 'deposit':
                        user.balance += transaction.amount

                    status_text = "تمت الموافقة على"
                    emoji = "✅"
                else:
                    if (
                        transaction.transaction_type == 'withdraw'
                        and transaction.status == 'pending'
                    ):
                        user.balance += transaction.amount

                    transaction.status = 'failed'
                    transaction.processed_at = datetime.utcnow()
                    status_text = "تم رفض"
                    emoji = "❌"
                
                session.commit()
                
                # إشعار المستخدم
                try:
                    import napoleon_ui

                    when = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
                    chat_id = user.telegram_id

                    if action == "approve":
                        progress_msg = await context.bot.send_message(
                            chat_id=chat_id,
                            text=napoleon_ui.REVIEW_PROGRESS_FRAMES[0],
                        )

                        async def edit_progress(frame: str):
                            try:
                                await context.bot.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=progress_msg.message_id,
                                    text=frame,
                                )
                            except TelegramError:
                                pass

                        await napoleon_ui.animate_review_progress(edit_progress, finish=True)

                        account = (
                            transaction.withdraw_destination
                            if transaction.transaction_type == "withdraw"
                            else ""
                        )
                        user_msg = napoleon_ui.operation_done_receipt(
                            transaction.id,
                            transaction.amount,
                            when,
                            account=account or "",
                        )
                        try:
                            await context.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=progress_msg.message_id,
                                text=user_msg,
                                parse_mode="HTML",
                            )
                        except TelegramError:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=user_msg,
                                parse_mode="HTML",
                            )
                    elif transaction.transaction_type == "withdraw":
                        user_msg = napoleon_ui.withdraw_failed_receipt(
                            transaction.id, when
                        )
                        user_msg += "\n💵 تم إرجاع المبلغ لرصيدك"
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=user_msg,
                            parse_mode="HTML",
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=(
                                f"{emoji} {status_text} طلب {transaction.transaction_type} "
                                f"بقيمة {format_currency(transaction.amount)}"
                            ),
                        )
                except TelegramError:
                    logger.warning(f"لا يمكن إرسال إشعار للمستخدم {user.telegram_id}")
                
                await update.message.reply_text(
                    f"{emoji} {status_text} المعاملة رقم {transaction_id} بنجاح",
                    reply_markup=Keyboards.admin_panel()
                )
            finally:
                session.close()
                
        except ValueError:
            await update.message.reply_text(
                "❌ رقم المعاملة غير صحيح",
                reply_markup=Keyboards.admin_panel()
            )
    
    @staticmethod
    async def _handle_ban_action(
        update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, ban: bool
    ):
        """حظر أو فك حظر مستخدم بالآيدي"""
        try:
            telegram_id = int(text.strip())
        except ValueError:
            await update.message.reply_text(
                "❌ أرسل رقم آيدي صحيح.",
                reply_markup=Keyboards.cancel_admin_operation(),
            )
            return

        if telegram_id in Config.ADMIN_IDS:
            await update.message.reply_text(
                "❌ لا يمكن حظر حساب إدمن.",
                reply_markup=Keyboards.admin_panel(),
            )
            return

        session = db.get_session()
        try:
            user = session.query(User).filter(User.telegram_id == str(telegram_id)).first()
            if not user:
                await update.message.reply_text(
                    "❌ المستخدم غير موجود.",
                    reply_markup=Keyboards.admin_panel(),
                )
                return

            user.is_banned = ban
            session.commit()
            label = "حظر" if ban else "فك حظر"
            await update.message.reply_text(
                f"✅ تم {label} المستخدم {get_user_display_name(user)}\n"
                f"🆔 {user.telegram_id}",
                reply_markup=Keyboards.admin_panel(),
            )
            try:
                if ban:
                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text="🚫 تم حظر حسابك من استخدام البوت.\nتواصل مع الدعم إن كنت تظن أن هذا خطأ.",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text="✅ تم فك الحظر عن حسابك. أرسل /start للمتابعة.",
                    )
            except TelegramError:
                pass
        finally:
            session.close()

    @staticmethod
    async def _handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """معالجة الرسالة الجماعية"""
        session = db.get_session()
        try:
            users = session.query(User).all()
            sent_count = 0
            failed_count = 0
            
            for user in users:
                if user.is_banned:
                    continue
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=f"📢 رسالة من الإدارة:\n\n{text}"
                    )
                    sent_count += 1
                except TelegramError:
                    failed_count += 1
                    logger.warning(f"فشل إرسال الرسالة للمستخدم {user.telegram_id}")
            
            await update.message.reply_text(
                f"📢 تم إرسال الرسالة الجماعية\n✅ تم الإرسال: {sent_count}\n❌ فشل الإرسال: {failed_count}",
                reply_markup=Keyboards.admin_panel()
            )
        finally:
            session.close()

    # ─── جيش نابليون (إدارة) ─────────────────────────────────

    @staticmethod
    async def army_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        from referral_service import (
            get_rank_defs,
            get_hold_days,
            get_min_commission_withdraw,
            get_min_activity_usd,
        )

        lines = ["👑 <b>إدارة جيش نابليون</b>\n"]
        for r in get_rank_defs():
            lines.append(
                f"{r['title']}: {r['min_active']} نشطة → {r['rate']:g}%"
            )
        lines.append(
            f"\n⏱ مراجعة: {get_hold_days()} يوم"
            f"\n💵 حد سحب عمولة: {format_currency(get_min_commission_withdraw())}"
            f"\n📈 حد نشاط: {get_min_activity_usd():g}$"
        )
        await safe_edit_callback_message(
            update,
            "\n".join(lines),
            reply_markup=Keyboards.admin_army_menu(),
            parse_mode="HTML",
            context=context,
        )

    @staticmethod
    async def army_ranks_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["admin_operation"] = "army_set_ranks"
        await safe_edit_callback_message(
            update,
            "🎖️ تعديل الرتب\n\n"
            "أرسل سطر لكل رتبة بالشكل:\n"
            "<code>code min rate</code>\n\n"
            "مثال:\n"
            "<code>soldier 5 12</code>\n"
            "<code>captain 10 14</code>\n"
            "<code>general 25 16</code>\n"
            "<code>emperor 50 18</code>",
            reply_markup=Keyboards.cancel_admin_operation(),
            parse_mode="HTML",
            context=context,
        )

    @staticmethod
    async def army_set_number(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
        from referral_service import (
            get_hold_days,
            get_min_commission_withdraw,
            get_min_activity_usd,
        )

        mapping = {
            "hold": ("army_set_hold", get_hold_days(), "مدة المراجعة بالأيام"),
            "min_withdraw": (
                "army_set_min_withdraw",
                get_min_commission_withdraw(),
                "الحد الأدنى لسحب العمولة (ل.س)",
            ),
            "min_activity": (
                "army_set_min_activity",
                get_min_activity_usd(),
                "حد النشاط المؤهل بالدولار",
            ),
        }
        op, current, label = mapping[kind]
        context.user_data["admin_operation"] = op
        await safe_edit_callback_message(
            update,
            f"✏️ {label}\n\nالقيمة الحالية: <b>{current}</b>\nأرسل الرقم الجديد:",
            reply_markup=Keyboards.cancel_admin_operation(),
            parse_mode="HTML",
            context=context,
        )

    @staticmethod
    async def army_activate_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["admin_operation"] = "army_activate"
        await safe_edit_callback_message(
            update,
            "✅ اعتماد إحالة نشطة\n\n"
            "أرسل:\n"
            "<code>invite_id net_usd net_syp</code>\n\n"
            "مثال: <code>12 15 200000</code>",
            reply_markup=Keyboards.cancel_admin_operation(),
            parse_mode="HTML",
            context=context,
        )

    @staticmethod
    async def army_accrue_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["admin_operation"] = "army_accrue"
        await safe_edit_callback_message(
            update,
            "➕ تسجيل عمولة يدوية\n\n"
            "أرسل:\n"
            "<code>telegram_id net_activity_syp</code>\n\n"
            "تُحسب العمولة = النشاط × نسبة رتبة صاحب الرابط\n"
            "وتبقى قيد المراجعة حسب المدة المضبوطة.",
            reply_markup=Keyboards.cancel_admin_operation(),
            parse_mode="HTML",
            context=context,
        )

    @staticmethod
    async def army_rank_override_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["admin_operation"] = "army_rank_override"
        await safe_edit_callback_message(
            update,
            "👤 رتبة يدوية لمستخدم\n\n"
            "أرسل:\n"
            "<code>telegram_id rank_code</code>\n\n"
            "الرتب: soldier / captain / general / emperor\n"
            "أو <code>clear</code> لإلغاء التثبيت اليدوي.",
            reply_markup=Keyboards.cancel_admin_operation(),
            parse_mode="HTML",
            context=context,
        )

    @staticmethod
    async def _handle_army_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, operation: str) -> bool:
        from referral_service import (
            ReferralArmyService,
            DEFAULT_RANKS,
        )

        try:
            if operation == "army_set_ranks":
                for line in text.splitlines():
                    parts = line.strip().split()
                    if len(parts) != 3:
                        continue
                    code, mn, rate = parts[0].lower(), int(float(parts[1])), float(parts[2])
                    if code not in {r["code"] for r in DEFAULT_RANKS}:
                        continue
                    db.set_setting(f"army_rank_{code}_min", str(mn))
                    db.set_setting(f"army_rank_{code}_rate", str(rate))
                await update.message.reply_text(
                    "✅ تم تحديث رتب الجيش.",
                    reply_markup=Keyboards.admin_army_menu(),
                )
                return True

            if operation == "army_set_hold":
                days = int(float(text))
                if days < 0:
                    raise ValueError("سالب")
                db.set_setting("army_commission_hold_days", str(days))
                await update.message.reply_text(
                    f"✅ مدة المراجعة: {days} يوم",
                    reply_markup=Keyboards.admin_army_menu(),
                )
                return True

            if operation == "army_set_min_withdraw":
                val = float(text)
                db.set_setting("army_min_commission_withdraw", str(val))
                await update.message.reply_text(
                    f"✅ حد سحب العمولة: {format_currency(val)}",
                    reply_markup=Keyboards.admin_army_menu(),
                )
                return True

            if operation == "army_set_min_activity":
                val = float(text)
                db.set_setting("army_min_activity_usd", str(val))
                await update.message.reply_text(
                    f"✅ حد النشاط المؤهل: {val:g}$",
                    reply_markup=Keyboards.admin_army_menu(),
                )
                return True

            if operation == "army_activate":
                parts = text.split()
                invite_id = int(parts[0])
                net_usd = float(parts[1]) if len(parts) > 1 else 0
                net_syp = float(parts[2]) if len(parts) > 2 else 0
                ok, msg, promotion = ReferralArmyService.activate_invite(
                    invite_id, net_syp=net_syp, net_usd=net_usd, source="manual"
                )
                if ok and promotion:
                    try:
                        import napoleon_ui
                        await context.bot.send_message(
                            chat_id=promotion["telegram_id"],
                            text=napoleon_ui.rank_promotion_text(
                                promotion["rank_title"],
                                promotion["rate"],
                            ),
                            parse_mode="HTML",
                        )
                    except TelegramError:
                        pass
                await update.message.reply_text(
                    f"{'✅' if ok else '❌'} {msg}",
                    reply_markup=Keyboards.admin_army_menu(),
                )
                return True

            if operation == "army_accrue":
                parts = text.split()
                tg_id, net_syp = parts[0], float(parts[1])
                user = db.get_user(tg_id)
                if not user:
                    await update.message.reply_text(
                        "❌ المستخدم غير موجود",
                        reply_markup=Keyboards.admin_army_menu(),
                    )
                    return True
                ok, msg = ReferralArmyService.accrue_commission_from_net(
                    user.id, net_syp, note=f"عمولة يدوية من الأدمن — نشاط {net_syp}"
                )
                if ok:
                    try:
                        await context.bot.send_message(
                            chat_id=user.telegram_id,
                            text=(
                                "💰 عمولة جديدة قيد المراجعة في خزنة جيش نابليون.\n"
                                "بعد انتهاء مدة المراجعة تصير متاحة للسحب."
                            ),
                        )
                    except TelegramError:
                        pass
                await update.message.reply_text(
                    f"{'✅' if ok else '❌'} {msg}",
                    reply_markup=Keyboards.admin_army_menu(),
                )
                return True

            if operation == "army_rank_override":
                parts = text.split()
                tg_id, code = parts[0], parts[1].lower()
                user = db.get_user(tg_id)
                if not user:
                    await update.message.reply_text(
                        "❌ المستخدم غير موجود",
                        reply_markup=Keyboards.admin_army_menu(),
                    )
                    return True
                from referral_service import resolve_rank, ReferralArmyService, get_rank_defs

                old_counts = ReferralArmyService.counts_for(user.id)
                old_rank = resolve_rank(old_counts["active"], user.referral_rank_override)
                session = db.get_session()
                try:
                    db_user = session.query(User).filter(User.id == user.id).first()
                    if code == "clear":
                        db_user.referral_rank_override = None
                    else:
                        valid = {r["code"] for r in get_rank_defs()}
                        if code not in valid:
                            await update.message.reply_text(
                                f"❌ رتبة غير معروفة: {code}",
                                reply_markup=Keyboards.admin_army_menu(),
                            )
                            return True
                        db_user.referral_rank_override = code
                    session.commit()
                    refreshed = db._detach(session, db_user)
                finally:
                    session.close()
                new_rank = resolve_rank(
                    old_counts["active"], refreshed.referral_rank_override
                )
                if (
                    code != "clear"
                    and new_rank
                    and old_rank
                    and new_rank.get("code") != old_rank.get("code")
                ):
                    try:
                        import napoleon_ui
                        await context.bot.send_message(
                            chat_id=user.telegram_id,
                            text=napoleon_ui.rank_promotion_text(
                                new_rank.get("title"),
                                new_rank.get("rate"),
                            ),
                            parse_mode="HTML",
                        )
                    except TelegramError:
                        pass
                await update.message.reply_text(
                    f"✅ تم تحديث الرتبة اليدوية لـ {tg_id}",
                    reply_markup=Keyboards.admin_army_menu(),
                )
                return True
        except Exception as exc:
            await update.message.reply_text(
                f"❌ بيانات غير صالحة: {exc}",
                reply_markup=Keyboards.cancel_admin_operation(),
            )
            return False
        return False

