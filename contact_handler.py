"""
معالج نظام التواصل
"""

import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from database import DatabaseManager, User, Message
from config import Config
from keyboards import Keyboards
from utils import get_user_display_name, safe_edit_callback_message

logger = logging.getLogger(__name__)
db = DatabaseManager()

class ContactHandler:
    """فئة معالج نظام التواصل"""
    
    @staticmethod
    async def contact_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """قائمة التواصل الرئيسية"""
        message = """
📧 تواصل معنا

يمكنك التواصل معنا من خلال الخيارات التالية:
        """
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=Keyboards.contact_menu()
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.contact_menu()
            )
    
    @staticmethod
    async def message_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إرسال رسالة للإدمن"""
        message = """
📩 رسالة للإدمن

أرسل رسالتك وسيتم توصيلها للإدارة في أقرب وقت:
        """
        
        context.user_data['contact_state'] = 'waiting_for_admin_message'
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=Keyboards.cancel_operation()
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.cancel_operation()
            )
    
    @staticmethod
    async def support_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معلومات الدعم الفني"""
        message = f"""
🛠️ الدعم الفني

📞 للتواصل المباشر:
{Config.SUPPORT_INFO.get('phone', 'غير متوفر')}

📧 البريد الإلكتروني:
{Config.SUPPORT_INFO.get('email', 'غير متوفر')}

🕐 ساعات العمل:
{Config.SUPPORT_INFO.get('hours', 'على مدار الساعة')}

💬 يمكنك أيضاً إرسال رسالة مباشرة من خلال البوت وسيتم الرد عليك في أقرب وقت.
        """
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=Keyboards.contact_back_menu()
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.contact_back_menu()
            )
    
    @staticmethod
    async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """الأسئلة الشائعة"""
        message = """
❓ الأسئلة الشائعة

🔸 كيف أشحن رصيدي؟
اضغط على "شحن رصيد في البوت" واختر طريقة الدفع المناسبة.

🔸 ما هو الحد الأدنى للسحب؟
الحد الأدنى للسحب هو 10 وحدة.

🔸 كيف يعمل نظام الإحالات؟
شارك رابط الإحالة الخاص بك واحصل على نسبة من كل إيداع يقوم به الأصدقاء.

🔸 كم يستغرق معالجة طلبات السحب؟
يتم معالجة الطلبات خلال 24 ساعة في أيام العمل.

🔸 هل يمكنني إلغاء طلب السحب؟
نعم، يمكنك إلغاء الطلب قبل معالجته من قبل الإدارة.

🔸 كيف أستخدم كود الهدية؟
اضغط على "كود هدية" وأدخل الكود للحصول على رصيد مجاني.
        """
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=Keyboards.contact_back_menu()
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.contact_back_menu()
            )
    
    @staticmethod
    async def terms_and_conditions(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """الشروط والأحكام"""
        message = """
📌 الشروط والأحكام

🔸 شروط الاستخدام:
• يجب أن يكون عمر المستخدم 18 سنة أو أكثر
• يُمنع استخدام البوت لأغراض غير قانونية
• يحق للإدارة تعليق أو إغلاق الحسابات المخالفة

🔸 شروط الإيداع والسحب:
• الحد الأدنى للإيداع: 5 وحدات
• الحد الأدنى للسحب: 10 وحدات
• الحد الأقصى للسحب اليومي: 1000 وحدة
• رسوم السحب: 10% من المبلغ

🔸 نظام الإحالات:
• نسبة الربح من الإحالات: 5%
• يتم احتساب الأرباح عند إتمام الإيداع
• لا يمكن سحب أرباح الإحالات منفصلة

🔸 المسؤولية:
• الإدارة غير مسؤولة عن الأخطاء الناتجة عن سوء الاستخدام
• يتحمل المستخدم مسؤولية حماية بيانات حسابه

🔸 التعديلات:
• تحتفظ الإدارة بحق تعديل الشروط في أي وقت
• سيتم إشعار المستخدمين بأي تغييرات مهمة

📅 آخر تحديث: {datetime.now().strftime('%Y-%m-%d')}
        """
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=Keyboards.contact_back_menu()
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.contact_back_menu()
            )
    
    @staticmethod
    async def handle_admin_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالجة رسالة المستخدم للإدمن"""
        user = db.get_user(update.effective_user.id)
        message_text = update.message.text
        
        # حفظ الرسالة في قاعدة البيانات
        session = db.get_session()
        try:
            message_record = Message(
                user_id=user.id,
                message_type='user_to_admin',
                content=message_text,
                is_read=False
            )
            session.add(message_record)
            session.commit()
            
            # إرسال الرسالة للإدمن
            admin_message = f"""
📩 رسالة جديدة من مستخدم

👤 المرسل: {get_user_display_name(user)}
🆔 معرف التليجرام: {user.telegram_id}
📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}

💬 الرسالة:
{message_text}

🔗 للرد على المستخدم، استخدم الأمر:
/reply {user.telegram_id} رسالتك هنا
            """
            
            # إرسال للإدمن الأول
            if Config.ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=Config.ADMIN_IDS[0],
                        text=admin_message
                    )
                except TelegramError:
                    logger.error(f"فشل إرسال الرسالة للإدمن {Config.ADMIN_IDS[0]}")
            
            # تأكيد للمستخدم
            await update.message.reply_text(
                "✅ تم إرسال رسالتك بنجاح!\n📩 سيتم الرد عليك في أقرب وقت ممكن.",
                reply_markup=Keyboards.main_menu()
            )
            
        finally:
            session.close()
        
        # مسح حالة المحادثة
        context.user_data.pop('contact_state', None)
    
    @staticmethod
    async def admin_reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """رد الإدمن على المستخدم"""
        if update.effective_user.id not in Config.ADMIN_IDS:
            return
        
        try:
            # تحليل الأمر: /reply user_id message
            command_parts = update.message.text.split(' ', 2)
            if len(command_parts) < 3:
                await update.message.reply_text(
                    "❌ تنسيق خاطئ. استخدم: /reply معرف_المستخدم الرسالة"
                )
                return
            
            user_id = int(command_parts[1])
            reply_message = command_parts[2]
            
            # البحث عن المستخدم
            session = db.get_session()
            try:
                user = session.query(User).filter(User.telegram_id == user_id).first()
                if not user:
                    await update.message.reply_text("❌ المستخدم غير موجود")
                    return
                
                # حفظ رد الإدمن
                message_record = Message(
                    user_id=user.id,
                    message_type='admin_to_user',
                    content=reply_message,
                    is_read=False,
                    admin_id=update.effective_user.id
                )
                session.add(message_record)
                session.commit()
                
                # إرسال الرد للمستخدم
                user_message = f"""
📧 رد من الإدارة

{reply_message}

📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}
                """
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text=user_message,
                    reply_markup=Keyboards.main_menu()
                )
                
                await update.message.reply_text(
                    f"✅ تم إرسال الرد إلى {get_user_display_name(user)} بنجاح"
                )
                
            finally:
                session.close()
                
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ تنسيق خاطئ. استخدم: /reply معرف_المستخدم الرسالة"
            )
        except TelegramError as e:
            await update.message.reply_text(f"❌ فشل إرسال الرسالة: {str(e)}")
    
    @staticmethod
    async def view_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض الرسائل للإدمن"""
        if update.effective_user.id not in Config.ADMIN_IDS:
            return
        
        session = db.get_session()
        try:
            # الرسائل غير المقروءة
            unread_messages = session.query(Message).filter(
                Message.message_type == 'user_to_admin',
                Message.is_read == False
            ).order_by(Message.created_at.desc()).limit(10).all()
            
            if not unread_messages:
                text = "✅ لا توجد رسائل جديدة\n\nللرد على مستخدم:\n/reply آيدي الرسالة"
            else:
                text = "📩 الرسائل الجديدة:\n\n"
                for i, msg in enumerate(unread_messages, 1):
                    user = session.query(User).filter(User.id == msg.user_id).first()
                    text += f"{i}. من: {get_user_display_name(user)}\n"
                    text += f"🆔 {user.telegram_id if user else '—'}\n"
                    text += f"📅 {msg.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                    text += f"💬 {msg.content[:100]}{'...' if len(msg.content) > 100 else ''}\n"
                    if user:
                        text += f"🔗 /reply {user.telegram_id} رسالتك\n\n"
                    else:
                        text += "\n"
                # تمييزها مقروءة بعد العرض
                for msg in unread_messages:
                    msg.is_read = True
                session.commit()
            
            if update.callback_query:
                await safe_edit_callback_message(
                    update,
                    text,
                    reply_markup=Keyboards.admin_back_menu(),
                    context=context,
                )
            else:
                await update.message.reply_text(
                    text, reply_markup=Keyboards.admin_back_menu()
                )
            
        finally:
            session.close()
    
    @staticmethod
    async def mark_messages_read(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تمييز الرسائل كمقروءة"""
        if update.effective_user.id not in Config.ADMIN_IDS:
            return
        
        session = db.get_session()
        try:
            session.query(Message).filter(
                Message.message_type == 'user_to_admin',
                Message.is_read == False
            ).update({'is_read': True})
            session.commit()
            
            await update.message.reply_text("✅ تم تمييز جميع الرسائل كمقروءة")
            
        finally:
            session.close()

