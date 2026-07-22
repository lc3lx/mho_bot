"""
معالجات أوامر البوت
"""

import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from database import DatabaseManager, User, Transaction
from config import Config
from keyboards import Keyboards
from utils import format_currency, validate_amount, get_user_display_name
from payment_handler import PaymentHandler
from referral_handler import ReferralHandler
from admin_handler import AdminHandler
from contact_handler import ContactHandler
from ichancy_handler import IchancyHandler
from accounts_handler import SavedAccountsHandler

logger = logging.getLogger(__name__)
db = DatabaseManager()

# حالات المحادثة
WAITING_FOR_AMOUNT = "waiting_for_amount"
WAITING_FOR_RECIPIENT = "waiting_for_recipient"
WAITING_FOR_GIFT_CODE = "waiting_for_gift_code"
WAITING_FOR_MESSAGE = "waiting_for_message"
WAITING_FOR_TX_NUMBER = "waiting_for_tx_number"
WAITING_FOR_WITHDRAW_DESTINATION = "waiting_for_withdraw_destination"
WAITING_FOR_ICHANCY_PLAYER_ID = "waiting_for_ichancy_player_id"
WAITING_FOR_ICHANCY_USERNAME = "waiting_for_ichancy_username"
WAITING_FOR_ICHANCY_PASSWORD = "waiting_for_ichancy_password"
WAITING_FOR_SAVED_ACCOUNT = "waiting_for_saved_account"
WAITING_FOR_SHAMCASH_TX = "waiting_for_shamcash_tx"
WAITING_FOR_SHAMCASH_AMOUNT = "waiting_for_shamcash_amount"
WAITING_FOR_SHAMCASH_CONFIRM = "waiting_for_shamcash_confirm"
WAITING_FOR_SYRIATEL_AMOUNT = "waiting_for_syriatel_amount"
WAITING_FOR_SYRIATEL_TX = "waiting_for_syriatel_tx"


async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """التحقق من عضوية المستخدم في القناة المطلوبة."""
    if user_id in Config.ADMIN_IDS:
        return True

    try:
        member = await context.bot.get_chat_member(Config.REQUIRED_CHANNEL_ID, user_id)
        if member.status in ("creator", "administrator", "member"):
            return True
        return member.status == "restricted" and bool(getattr(member, "is_member", False))
    except TelegramError as exc:
        logger.error(
            "تعذر التحقق من اشتراك user_id=%s في %s: %s",
            user_id,
            Config.REQUIRED_CHANNEL_ID,
            exc,
        )
        return False


async def send_subscription_required(update: Update):
    """إظهار بوابة الاشتراك الإلزامي."""
    text = (
        "🔒 يجب الاشتراك في قناتنا أولاً لاستخدام البوت.\n\n"
        "1️⃣ اضغط «الاشتراك في القناة»\n"
        "2️⃣ اشترك في القناة\n"
        "3️⃣ ارجع واضغط «تحقق من الاشتراك»"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=Keyboards.required_subscription(),
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=Keyboards.required_subscription(),
        )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر البدء — الخطوة 1 شحن أولاً، ثم القائمة بعد المتابعة"""
    user_id = update.effective_user.id
    logger = logging.getLogger(__name__)
    logger.info("استلام /start من user_id=%s", user_id)
    
    # التحقق من وجود كود إحالة
    referral_code = None
    if context.args and len(context.args) > 0:
        referral_code = context.args[0]
        context.user_data["pending_referral_code"] = referral_code
    else:
        referral_code = context.user_data.get("pending_referral_code")

    if not await is_subscribed(context, user_id):
        await send_subscription_required(update)
        return
    
    # إنشاء أو الحصول على المستخدم
    user = db.get_user(user_id)
    if not user:
        user = db.create_user(
            telegram_id=user_id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name
        )
        
        # معالجة الإحالة
        if user and referral_code and referral_code != user.referral_code:
            await handle_referral(user, referral_code)

    if not user:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "❌ تعذر إنشاء الحساب. أرسل /start وحاول مرة أخرى."
            )
        else:
            await update.message.reply_text("❌ تعذر إنشاء الحساب. حاول مرة أخرى.")
        return

    # حفظ بيانات العرض في context لتفادي مشاكل الجلسة
    context.user_data["balance"] = user.balance or 0
    context.user_data["telegram_id"] = user.telegram_id
    
    # ── الرسالة 1 فقط: الخطوة الأولى (الشحن) — بدون القائمة الكبيرة ──
    step1_message = Config.MESSAGES["start_step1"].format(
        facebook_url=Config.FACEBOOK_URL,
        telegram_channel_url=Config.TELEGRAM_CHANNEL_URL,
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(
            step1_message,
            reply_markup=Keyboards.start_step1(),
            disable_web_page_preview=False,
        )
    else:
        await update.message.reply_text(
            step1_message,
            reply_markup=Keyboards.start_step1(),
            disable_web_page_preview=False,
        )
    logger.info("تم إرسال الخطوة 1 (شحن) لـ user_id=%s", user_id)


async def start_continue_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بعد الخطوة 1 — فتح القائمة (مبسطة ثم المزيد للقائمة الكاملة)"""
    user = db.get_user(update.effective_user.id)
    if not user:
        user = db.create_user(
            telegram_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
        )
    if not user:
        text = "❌ تعذر تحميل الحساب. أرسل /start من جديد."
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    welcome_message = Config.MESSAGES["welcome"].format(
        bot_name=Config.BOT_DISPLAY_NAME,
        balance=format_currency(user.balance or 0),
        user_id=user.telegram_id,
    )
    # قائمة مبسطة — «المزيد من الخدمات» تفتح القائمة الكبيرة
    if update.callback_query:
        await update.callback_query.edit_message_text(
            welcome_message,
            reply_markup=Keyboards.start_menu(),
        )
    else:
        await update.message.reply_text(
            welcome_message,
            reply_markup=Keyboards.start_menu(),
        )


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج القائمة الرئيسية"""
    if not await is_subscribed(context, update.effective_user.id):
        await send_subscription_required(update)
        return

    user = db.get_user(update.effective_user.id)
    if not user:
        await start_handler(update, context)
        return
    
    message = Config.MESSAGES["main_menu"].format(
        balance=format_currency(user.balance),
        user_id=user.telegram_id,
    )
    
    if update.message:
        await update.message.reply_text(message, reply_markup=Keyboards.main_menu())
    else:
        await update.callback_query.edit_message_text(
            message, reply_markup=Keyboards.main_menu()
        )


async def full_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القائمة الكاملة للخدمات"""
    user = db.get_user(update.effective_user.id)
    if not user:
        await start_handler(update, context)
        return

    message = f"""❞ 🔷 القائمة الرئيسية: ❝

رصيدك في البوت: {format_currency(user.balance)}
رقم الايدي الخاص بك: {user.telegram_id}
"""
    if update.callback_query:
        await update.callback_query.edit_message_text(
            message, reply_markup=Keyboards.main_menu()
        )
    else:
        await update.message.reply_text(message, reply_markup=Keyboards.main_menu())


async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معلومات الملف الشخصي"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    user = db.get_user(update.effective_user.id)
    if not user:
        await start_handler(update, context)
        return

    tg = update.effective_user
    ichancy_line = (
        f"🎰 Ichancy: `{user.ichancy_username}` | Id `{user.ichancy_player_id}`"
        if user.ichancy_player_id
        else "🎰 Ichancy: غير مرتبط"
    )
    sy_count = db.count_saved_accounts(user.id, "syriatel_cash")
    sc_count = db.count_saved_accounts(user.id, "shamcash")

    message = f"""
👤 معلومات الملف الشخصي

🆔 الايدي: `{user.telegram_id}`
👤 الاسم: {get_user_display_name(user)}
📱 يوزر تليجرام: @{tg.username or '—'}
💵 رصيد البوت: {format_currency(user.balance)}
👥 الإحالات: {user.referral_count} | أرباح: {format_currency(user.referral_earnings)}
{ichancy_line}
📱 أرقام سيريتل محفوظة: {sy_count}/{Config.max_saved_accounts('syriatel_cash')}
💳 حساب شام كاش: {sc_count}/{Config.max_saved_accounts('shamcash')}
"""
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 حساباتي المحفوظة", callback_data="saved_accounts")],
        [InlineKeyboardButton("⚡️ حساب Ichancy", callback_data="ichancy_hub")],
        [InlineKeyboardButton("↪️ رجوع", callback_data="full_menu")],
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            message, reply_markup=markup, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            message, reply_markup=markup, parse_mode="Markdown"
        )


async def refund_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """طلب استرداد حوالة — يُرسل للإدمن"""
    message = """
🔄 طلب استرداد حوالة

أرسل تفاصيل الطلب في رسالة واحدة:
• نوع الحوالة (سيريتل / شام كاش / USDT)
• رقم العملية
• المبلغ
• سبب الاسترداد

سيتم مراجعة الطلب من الإدارة.
"""
    context.user_data["state"] = WAITING_FOR_MESSAGE
    context.user_data["operation"] = "refund_request"
    await update.callback_query.edit_message_text(
        message,
        reply_markup=Keyboards.cancel_operation(),
    )


async def deposit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الإيداع — شاشة شحن مثل الصورة"""
    user = db.get_user(update.effective_user.id)
    if not user:
        await start_handler(update, context)
        return

    message = f"""❞ شحن رصيد البوت ❝

💰 الرصيد الخاص بك: {format_currency(user.balance)}

اشحن رصيد في البوت عن طريق احدى وسائل الدفع
"""

    if update.callback_query:
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.payment_methods("deposit"),
        )
    else:
        await update.message.reply_text(
            message,
            reply_markup=Keyboards.payment_methods("deposit"),
        )

async def withdraw_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج السحب"""
    user = db.get_user(update.effective_user.id)
    
    if user.balance < Config.MIN_WITHDRAWAL:
        message = f"❌ الحد الأدنى للسحب هو {format_currency(Config.MIN_WITHDRAWAL)}\n💵 رصيدك الحالي: {format_currency(user.balance)}"
        
        if update.callback_query:
            await update.callback_query.answer(message, show_alert=True)
        else:
            await update.message.reply_text(message, reply_markup=Keyboards.main_menu())
        return
    
    message = f"""
💸 سحب من محفظة البوت إلى الواقع

💵 رصيدك الحالي: {format_currency(user.balance)}
💰 الحد الأدنى: {format_currency(Config.MIN_WITHDRAWAL)}
💰 الحد الأقصى: {format_currency(Config.MAX_WITHDRAWAL)}

⏳ **يتطلب موافقة الإدمن** — سيتم تحويل المبلغ يدوياً

اختر طريقة الاستلام:
    """
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.payment_methods("withdraw")
        )
    else:
        await update.message.reply_text(
            message,
            reply_markup=Keyboards.payment_methods("withdraw")
        )

async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج نظام الإحالات"""
    await ReferralHandler.show_referral_menu(update, context)

async def gift_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إهداء الرصيد"""
    user = db.get_user(update.effective_user.id)
    
    if user.balance < Config.MIN_GIFT:
        message = f"❌ الحد الأدنى للإهداء هو {format_currency(Config.MIN_GIFT)}\n💵 رصيدك الحالي: {format_currency(user.balance)}"
        
        if update.callback_query:
            await update.callback_query.answer(message, show_alert=True)
        else:
            await update.message.reply_text(message, reply_markup=Keyboards.main_menu())
        return
    
    message = f"""
🎁 إهداء رصيد

💵 رصيدك الحالي: {format_currency(user.balance)}
💰 الحد الأدنى للإهداء: {format_currency(Config.MIN_GIFT)}

📝 لإهداء رصيد لصديق، أرسل المبلغ الذي تريد إهداءه:
    """
    
    # حفظ حالة المحادثة
    context.user_data['state'] = WAITING_FOR_AMOUNT
    context.user_data['operation'] = 'gift'
    
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

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج لوحة الإدمن"""
    await AdminHandler.admin_panel(update, context)

async def transaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج سجل المعاملات"""
    message = """
📜 سجل العمليات

اختر نوع المعاملات التي تريد عرضها:
    """
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.transaction_history_menu()
        )
    else:
        await update.message.reply_text(
            message,
            reply_markup=Keyboards.transaction_history_menu()
        )

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج التواصل"""
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

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الاستعلامات المضمنة"""
    query = update.callback_query
    data = query.data

    # لا يُسمح باستخدام أي زر قبل الاشتراك بالقناة.
    if data == "check_subscription":
        if await is_subscribed(context, update.effective_user.id):
            await query.answer("✅ تم التحقق من الاشتراك", show_alert=False)
            await start_handler(update, context)
        else:
            await query.answer(
                "❌ لم يتم العثور على اشتراكك. اشترك ثم حاول مجدداً.",
                show_alert=True,
            )
        return

    await query.answer()
    if not await is_subscribed(context, update.effective_user.id):
        await send_subscription_required(update)
        return
    
    # القائمة الرئيسية
    if data == "main_menu":
        await main_menu_handler(update, context)
    elif data == "full_menu":
        await full_menu_handler(update, context)
    elif data == "start_continue":
        await start_continue_handler(update, context)
    
    # الإيداع والسحب
    elif data == "deposit":
        await deposit_handler(update, context)
    elif data == "withdraw":
        await withdraw_handler(update, context)
    elif data == "profile":
        await profile_handler(update, context)
    elif data == "refund_request":
        await refund_request_handler(update, context)

    # ichancy — حساب / شحن / سحب
    elif data in ("ichancy_to_bot", "ichancy_hub"):
        await IchancyHandler.hub(update, context)
    elif data == "ichancy_create_start":
        await IchancyHandler.start_create_account(update, context)
    elif data == "ichancy_link_account":
        await IchancyHandler.start_link_account(update, context)
    elif data == "ichancy_topup_start":
        await IchancyHandler.start_topup(update, context)
    elif data == "ichancy_withdraw_start":
        await IchancyHandler.start_withdraw_from_ichancy(update, context)
    elif data == "ichancy_change_password":
        await IchancyHandler.change_password_info(update, context)
    elif data == "open_facebook":
        await query.edit_message_text(
            f"📱 صفحتنا على الفيسبوك:\n{Config.FACEBOOK_URL}",
            reply_markup=Keyboards.main_menu(),
        )

    # لوحة الإدمن
    elif data.startswith("admin_") or data == "cancel_admin_operation":
        if update.effective_user.id not in Config.ADMIN_IDS:
            await update.callback_query.answer("❌ غير مصرح", show_alert=True)
            return
        if data == "admin_panel":
            await AdminHandler.admin_panel(update, context)
        elif data == "admin_add_balance":
            await AdminHandler.add_balance(update, context)
        elif data == "admin_deduct_balance":
            await AdminHandler.deduct_balance(update, context)
        elif data == "admin_user_info":
            await AdminHandler.user_info(update, context)
        elif data == "admin_create_gift_code":
            await AdminHandler.create_gift_code(update, context)
        elif data == "admin_stats":
            await AdminHandler.view_statistics(update, context)
        elif data == "admin_view_pending":
            await AdminHandler.pending_transactions(update, context)
        elif data == "admin_approve_transaction":
            await AdminHandler.approve_transaction(update, context)
        elif data == "admin_reject_transaction":
            await AdminHandler.reject_transaction(update, context)
        elif data == "admin_broadcast":
            await AdminHandler.broadcast_message(update, context)
        elif data == "admin_settings":
            await AdminHandler.settings_menu(update, context)
        elif data == "admin_rate_shamcash":
            await AdminHandler.start_set_rate(update, context, "shamcash")
        elif data == "admin_rate_usdt":
            await AdminHandler.start_set_rate(update, context, "usdt")
        elif data == "cancel_admin_operation":
            context.user_data.pop("admin_operation", None)
            await AdminHandler.admin_panel(update, context)
    
    # نظام الإحالات
    elif data == "referrals":
        await referral_handler(update, context)
    elif data == "share_referral":
        await ReferralHandler.share_referral_link(update, context)
    
    # إهداء الرصيد
    elif data == "gift_balance":
        await gift_handler(update, context)
    
    # كود الهدية
    elif data == "gift_code":
        await handle_gift_code_menu(update, context)
    
    # التواصل
    elif data == "contact":
        await contact_handler(update, context)
    
    # رسالة للإدمن
    elif data == "message_admin":
        await handle_message_admin(update, context)
    
    # سجل المعاملات
    elif data == "transactions":
        await transaction_handler(update, context)
    
    # الشروط والأحكام
    elif data == "terms":
        await handle_terms(update, context)

    # الحسابات المحفوظة (سيريتل / شام كاش)
    elif data == "saved_accounts":
        await SavedAccountsHandler.menu(update, context)
    elif data.startswith("saved_acc_list_"):
        account_type = data.replace("saved_acc_list_", "", 1)
        await SavedAccountsHandler.list_accounts(update, context, account_type)
    elif data.startswith("saved_acc_add_"):
        account_type = data.replace("saved_acc_add_", "", 1)
        await SavedAccountsHandler.start_add(update, context, account_type)
    elif data.startswith("saved_acc_del_"):
        account_id = int(data.replace("saved_acc_del_", "", 1))
        await SavedAccountsHandler.delete_account(update, context, account_id)
    elif data.startswith("withdraw_use_acc_"):
        account_id = int(data.replace("withdraw_use_acc_", "", 1))
        user = db.get_user(update.effective_user.id)
        account = db.get_saved_account(account_id, user.id)
        if not account:
            await query.edit_message_text(
                "❌ الحساب غير موجود أو تم حذفه.",
                reply_markup=Keyboards.cancel_operation(),
            )
            return
        await PaymentHandler.execute_manual_withdraw(
            update, context, account.account_value
        )
    elif data.startswith("withdraw_manual_dest_"):
        method = data.replace("withdraw_manual_dest_", "", 1)
        if method == "syriatel_cash":
            prompt = "📱 أرسل **رقم سيريتل كاش** لاستلام المبلغ (مثال: `0999123456`):"
        else:
            prompt = "💳 أرسل **عنوان حساب شام كاش** لاستلام المبلغ:"
        context.user_data["state"] = WAITING_FOR_WITHDRAW_DESTINATION
        await query.edit_message_text(
            prompt,
            reply_markup=Keyboards.cancel_operation(),
            parse_mode="Markdown",
        )

    # شام كاش — شحن مثل الصور
    elif data == "shamcash_cur_syp":
        await PaymentHandler.start_shamcash_currency(update, context, "syp")
    elif data == "shamcash_cur_usd":
        await PaymentHandler.start_shamcash_currency(update, context, "usd")
    elif data == "shamcash_confirm_send":
        await PaymentHandler.confirm_shamcash_deposit(update, context)
    elif data == "shamcash_confirm_cancel":
        context.user_data.clear()
        await query.edit_message_text(
            "❌ تم إلغاء طلب الشحن.",
            reply_markup=Keyboards.start_menu(),
        )

    # سيريتل كاش — تحويل يدوي (AUTO)
    elif data == "syriatel_manual_auto":
        await PaymentHandler.start_syriatel_manual_intro(update, context)
    elif data == "syriatel_continue":
        await PaymentHandler.start_syriatel_amount(update, context, use_previous=False)
    elif data == "syriatel_prev_code":
        await PaymentHandler.start_syriatel_amount(update, context, use_previous=True)
    elif data.startswith("syriatel_pick_"):
        code = data.replace("syriatel_pick_", "", 1)
        await PaymentHandler.pick_syriatel_code(update, context, code)
    
    # معالجة طرق الدفع
    elif data.startswith("deposit_") or data.startswith("withdraw_"):
        await handle_payment_method(update, context)
    
    # إلغاء العملية
    elif data == "cancel_operation":
        await cancel_pending_payment(context)
        context.user_data.clear()
        await main_menu_handler(update, context)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل النصية"""
    if not await is_subscribed(context, update.effective_user.id):
        context.user_data.pop("state", None)
        await send_subscription_required(update)
        return

    if context.user_data.get("admin_operation") and update.effective_user.id in Config.ADMIN_IDS:
        await AdminHandler.handle_admin_input(update, context)
        return

    user_state = context.user_data.get('state')
    
    if user_state == WAITING_FOR_AMOUNT:
        await handle_amount_input(update, context)
    elif user_state == WAITING_FOR_RECIPIENT:
        await handle_recipient_input(update, context)
    elif user_state == WAITING_FOR_GIFT_CODE:
        await handle_gift_code_input(update, context)
    elif user_state == WAITING_FOR_MESSAGE:
        await handle_message_input(update, context)
    elif user_state == WAITING_FOR_TX_NUMBER:
        await handle_tx_number_input(update, context)
    elif user_state == WAITING_FOR_WITHDRAW_DESTINATION:
        await handle_withdraw_destination_input(update, context)
    elif user_state == WAITING_FOR_ICHANCY_PLAYER_ID:
        await handle_ichancy_player_input(update, context)
    elif user_state == WAITING_FOR_ICHANCY_USERNAME:
        await IchancyHandler.process_username(
            update, context, update.message.text.strip()
        )
    elif user_state == WAITING_FOR_ICHANCY_PASSWORD:
        await IchancyHandler.process_password(
            update, context, update.message.text.strip()
        )
    elif user_state == WAITING_FOR_SAVED_ACCOUNT:
        await SavedAccountsHandler.process_add(
            update, context, update.message.text.strip()
        )
    elif user_state == WAITING_FOR_SHAMCASH_TX:
        await PaymentHandler.handle_shamcash_tx_input(
            update, context, update.message.text.strip()
        )
    elif user_state == WAITING_FOR_SHAMCASH_AMOUNT:
        await PaymentHandler.handle_shamcash_amount_input(
            update, context, update.message.text.strip()
        )
    elif user_state == WAITING_FOR_SYRIATEL_AMOUNT:
        await PaymentHandler.handle_syriatel_amount(
            update, context, update.message.text.strip()
        )
    elif user_state == WAITING_FOR_SYRIATEL_TX:
        await PaymentHandler.handle_syriatel_tx(
            update, context, update.message.text.strip()
        )
    else:
        # رسالة افتراضية
        await update.message.reply_text(
            "استخدم الأزرار أدناه للتنقل في البوت:",
            reply_markup=Keyboards.main_menu()
        )

# دوال مساعدة

async def handle_tx_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال رقم العملية للتحقق التلقائي"""
    tx_number = update.message.text.strip()
    await PaymentHandler.verify_auto_deposit(update, context, tx_number)


async def handle_withdraw_destination_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة وجهة السحب للواقع — يدوي بموافقة الإدمن"""
    destination = update.message.text.strip()
    await PaymentHandler.execute_manual_withdraw(update, context, destination)


async def handle_ichancy_player_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ربط حساب ichancy"""
    player_id = update.message.text.strip()
    await IchancyHandler.process_link_account(update, context, player_id)


async def cancel_pending_payment(context: ContextTypes.DEFAULT_TYPE):
    """إلغاء معاملة معلقة عند إلغاء العملية"""
    transaction_id = context.user_data.get("transaction_id")
    operation = context.user_data.get("operation")

    if not transaction_id:
        return

    session = db.get_session()
    try:
        transaction = session.query(Transaction).filter(Transaction.id == transaction_id).first()
        if not transaction or transaction.status != "pending":
            return

        if transaction.transaction_type == "withdraw":
            user = session.query(User).filter(User.id == transaction.user_id).first()
            if user:
                user.balance += transaction.amount

        transaction.status = "cancelled"
        transaction.admin_notes = "ألغى المستخدم العملية"
        transaction.processed_at = datetime.utcnow()
        session.commit()
        logger.info("Cancelled pending transaction %s (%s)", transaction_id, operation)
    finally:
        session.close()


async def handle_referral(user, referral_ref):
    """معالجة الإحالة — يقبل آيدي تليجرام أو كود الإحالة"""
    if not referral_ref:
        return

    session = db.get_session()
    try:
        # لا يحيل نفسه
        if str(user.telegram_id) == str(referral_ref) or user.referral_code == referral_ref:
            return

        referrer = None
        if str(referral_ref).isdigit():
            referrer = session.query(User).filter(
                User.telegram_id == str(referral_ref)
            ).first()

        if not referrer:
            referrer = session.query(User).filter(
                User.referral_code == referral_ref
            ).first()

        if not referrer or referrer.id == user.id:
            return

        # حفظ آيدي المُحيل لربط رابط الإحالة
        db_user = session.query(User).filter(User.id == user.id).first()
        if db_user.referred_by:
            return  # سبق تسجيل إحالة

        db_user.referred_by = str(referrer.telegram_id)
        referrer.referral_count = (referrer.referral_count or 0) + 1
        session.commit()
        logger.info(
            "تم تسجيل إحالة جديدة: %s -> %s",
            user.telegram_id,
            referrer.telegram_id,
        )
    finally:
        session.close()

async def handle_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال المبلغ"""
    try:
        amount = float(update.message.text)
        operation = context.user_data.get('operation')
        method = context.user_data.get('method')
        
        if operation == 'gift':
            user = db.get_user(update.effective_user.id)
            
            if amount < Config.MIN_GIFT:
                await update.message.reply_text(
                    f"❌ الحد الأدنى للإهداء هو {format_currency(Config.MIN_GIFT)}",
                    reply_markup=Keyboards.cancel_operation()
                )
                return
            
            if amount > user.balance:
                await update.message.reply_text(
                    f"❌ رصيدك غير كافي\n💵 رصيدك الحالي: {format_currency(user.balance)}",
                    reply_markup=Keyboards.cancel_operation()
                )
                return
            
            context.user_data['amount'] = amount
            context.user_data['state'] = WAITING_FOR_RECIPIENT
            
            await update.message.reply_text(
                f"💰 المبلغ: {format_currency(amount)}\n\n👤 الآن أرسل معرف المستخدم أو اسم المستخدم للشخص الذي تريد إهداءه:",
                reply_markup=Keyboards.cancel_operation()
            )
        
        elif operation == 'deposit':
            method_config = Config.PAYMENT_METHODS.get(method, {})
            if method_config.get("auto_deposit", method_config.get("auto_enabled")):
                if method_config.get("provider") != "tron":
                    context.user_data.clear()
            await PaymentHandler.process_deposit_request(update, context, amount, method)

        elif operation == 'ichancy_withdraw':
            context.user_data.clear()
            await IchancyHandler.process_ichancy_withdraw(update, context, amount)

        elif operation == 'ichancy_topup':
            context.user_data.clear()
            await IchancyHandler.process_topup(update, context, amount)
        
        elif operation == 'withdraw':
            await PaymentHandler.process_withdraw_request(update, context, amount, method)
    
    except ValueError:
        await update.message.reply_text(
            "❌ يرجى إدخال مبلغ صحيح",
            reply_markup=Keyboards.cancel_operation()
        )

async def handle_recipient_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال المستلم"""
    recipient_input = update.message.text.strip()
    
    # البحث عن المستخدم
    session = db.get_session()
    try:
        recipient = None
        
        # البحث بمعرف التليجرام
        if recipient_input.isdigit():
            recipient = session.query(User).filter(User.telegram_id == recipient_input).first()
        
        # البحث باسم المستخدم
        if not recipient and recipient_input.startswith('@'):
            username = recipient_input[1:]
            recipient = session.query(User).filter(User.username == username).first()
        elif not recipient:
            recipient = session.query(User).filter(User.username == recipient_input).first()
        
        if not recipient:
            await update.message.reply_text(
                "❌ المستخدم غير موجود. تأكد من صحة المعرف أو اسم المستخدم",
                reply_markup=Keyboards.cancel_operation()
            )
            return
        
        # تنفيذ عملية الإهداء
        amount = context.user_data['amount']
        sender = db.get_user(update.effective_user.id)
        
        if sender.balance >= amount:
            # خصم من المرسل
            sender.balance -= amount
            # إضافة للمستلم
            recipient.balance += amount
            
            # إضافة سجل الهدية
            from database import Gift
            gift = Gift(
                sender_id=sender.id,
                receiver_id=recipient.id,
                amount=amount
            )
            session.add(gift)
            session.commit()
            
            # رسالة تأكيد للمرسل
            await update.message.reply_text(
                f"✅ تم إهداء {format_currency(amount)} بنجاح!\n👤 إلى: {get_user_display_name(recipient)}",
                reply_markup=Keyboards.main_menu()
            )
            
            # إشعار للمستلم
            try:
                await context.bot.send_message(
                    chat_id=recipient.telegram_id,
                    text=f"🎁 تهانينا! لقد تلقيت هدية بقيمة {format_currency(amount)}\n👤 من: {get_user_display_name(sender)}",
                    reply_markup=Keyboards.main_menu()
                )
            except TelegramError:
                logger.warning(f"لا يمكن إرسال إشعار للمستخدم {recipient.telegram_id}")
        
        else:
            await update.message.reply_text(
                "❌ رصيدك غير كافي لإتمام هذه العملية",
                reply_markup=Keyboards.main_menu()
            )
        
        # مسح حالة المحادثة
        context.user_data.clear()
        
    finally:
        session.close()

async def handle_gift_code_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مود أكواد الجوائز — مثل الصورة"""
    message = "🏆 ادخل الكود للحصول على الجائزة"

    context.user_data['state'] = WAITING_FOR_GIFT_CODE

    if update.callback_query:
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.cancel_operation(),
        )
    else:
        await update.message.reply_text(
            message,
            reply_markup=Keyboards.cancel_operation(),
        )


async def handle_gift_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التحقق من كود الجائزة"""
    code = update.message.text.strip().upper()

    session = db.get_session()
    try:
        from database import GiftCode, GiftCodeUsage, Transaction

        gift_code = session.query(GiftCode).filter(
            GiftCode.code == code,
            GiftCode.is_active == True,
        ).first()

        # كود خاطئ أو غير موجود — نفس رسالة الصورة
        if not gift_code or gift_code.current_uses >= gift_code.max_uses:
            await update.message.reply_text("🚫 الكود خاطيء")
            # يبقى في المود حتى يحاول مرة أخرى أو يلغي
            return

        user = db.get_user(update.effective_user.id)
        existing_usage = session.query(GiftCodeUsage).filter(
            GiftCodeUsage.code_id == gift_code.id,
            GiftCodeUsage.user_id == user.id,
        ).first()

        if existing_usage:
            await update.message.reply_text("🚫 الكود خاطيء")
            return

        # تطبيق الكود بنجاح — مرة واحدة فقط ثم تعطيله
        db_user = session.query(User).filter(User.id == user.id).first()
        db_user.balance += gift_code.amount
        gift_code.current_uses += 1
        gift_code.is_active = False  # تعطيل نهائي بعد الاستخدام

        session.add(GiftCodeUsage(code_id=gift_code.id, user_id=user.id))
        session.add(Transaction(
            user_id=user.id,
            transaction_type="gift_code",
            amount=gift_code.amount,
            status="completed",
            description=f"كود جائزة (مرة واحدة): {code}",
        ))
        session.commit()

        context.user_data.clear()
        await update.message.reply_text(
            f"✅ تم قبول الكود!\n"
            f"🏆 الجائزة: {format_currency(gift_code.amount)}\n"
            f"💰 رصيدك الآن: {format_currency(db_user.balance)}",
            reply_markup=Keyboards.start_menu(),
        )

    finally:
        session.close()

async def handle_message_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إرسال رسالة للإدمن"""
    message = """
📩 رسالة للإدمن

أرسل رسالتك وسيتم توصيلها للإدارة:
    """
    
    context.user_data['state'] = WAITING_FOR_MESSAGE
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=Keyboards.cancel_operation()
    )

async def handle_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال الرسالة / طلب الاسترداد"""
    message_text = update.message.text
    user = db.get_user(update.effective_user.id)
    operation = context.user_data.get("operation", "message_admin")
    is_refund = operation == "refund_request"
    
    session = db.get_session()
    try:
        from database import AdminMessage
        
        admin_message = AdminMessage(
            user_id=user.id,
            message=(
                f"[طلب استرداد حوالة]\n{message_text}"
                if is_refund
                else message_text
            ),
        )
        session.add(admin_message)
        session.commit()
        
        admin_header = (
            f"🔄 طلب استرداد حوالة من {get_user_display_name(user)}"
            if is_refund
            else f"📩 رسالة جديدة من المستخدم {get_user_display_name(user)}"
        )
        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"{admin_header}\n🆔 {user.telegram_id}\n\n{message_text}",
                )
            except TelegramError:
                logger.warning(f"لا يمكن إرسال إشعار للإدمن {admin_id}")
        
        await update.message.reply_text(
            "✅ تم إرسال طلب الاسترداد للإدارة."
            if is_refund
            else "✅ تم إرسال رسالتك للإدارة. سيتم الرد عليك قريباً",
            reply_markup=Keyboards.main_menu(),
        )
        
        context.user_data.clear()
        
    finally:
        session.close()

async def handle_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الشروط والأحكام"""
    terms_text = """
📌 الشروط والأحكام

🔸 شروط الاستخدام:
• يجب أن تكون فوق 18 سنة لاستخدام الخدمة
• ممنوع استخدام البوت لأغراض غير قانونية
• الحد الأدنى للإيداع: {min_deposit} ل.س
• الحد الأدنى للسحب: {min_withdrawal} ل.س

🔸 سياسة الإحالات:
• تحصل على {referral_percentage}% من كل إيداع يقوم به المُحال
• أرباح الإحالات قابلة للسحب في أي وقت

🔸 سياسة الخصوصية:
• نحن نحترم خصوصيتك ولا نشارك بياناتك مع أطراف ثالثة
• يتم تشفير جميع المعاملات المالية

🔸 المسؤولية:
• الإدارة غير مسؤولة عن أي خسائر ناتجة عن سوء الاستخدام
• يحق للإدارة تعليق أو إغلاق أي حساب يخالف الشروط

📞 للاستفسارات: استخدم زر "تواصل معنا"
    """.format(
        min_deposit=format_currency(Config.MIN_DEPOSIT),
        min_withdrawal=format_currency(Config.MIN_WITHDRAWAL),
        referral_percentage=Config.REFERRAL_PERCENTAGE
    )
    
    await update.callback_query.edit_message_text(
        terms_text,
        reply_markup=Keyboards.back_to_main()
    )

async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار طريقة الدفع"""
    data = update.callback_query.data
    operation, method = data.split('_', 1)
    
    method_info = Config.PAYMENT_METHODS.get(method)
    if not method_info:
        await update.callback_query.answer("❌ طريقة دفع غير صحيحة")
        return

    # شام كاش إيداع — واجهة مثل الصور (اختيار العملة أولاً)
    if operation == "deposit" and method == "shamcash":
        await PaymentHandler.start_shamcash_menu(update, context)
        return

    # سيريتل — تحويل يدوي + تحقق أوتو
    if operation == "deposit" and method == "syriatel_cash":
        await PaymentHandler.start_syriatel_menu(update, context)
        return
    
    if operation == "deposit":
        auto_note = ""
        if method_info.get("auto_deposit", method_info.get("auto_enabled")):
            if method_info.get("provider") == "tron":
                auto_note = (
                    "\n\n⚡ التحقق تلقائي — سيُعطى مبلغ USDT فريد بالضبط "
                    "(فواصل عشرية) لتمييز تحويلك."
                )
            else:
                auto_note = "\n\n⚡ التحقق تلقائي — بعد التحويل أرسل رقم العملية."
        message = f"""
💰 الإيداع عبر {method_info['name']} {method_info['emoji']}

📝 تعليمات الإيداع:
1. أرسل المبلغ الذي تريد إيداعه
2. حوّل المبلغ حسب التعليمات
3. أرسل رقم العملية للتحقق التلقائي{auto_note}

💰 الحد الأدنى: {format_currency(Config.MIN_DEPOSIT)}
💰 الحد الأقصى: {format_currency(Config.MAX_DEPOSIT)}

أرسل المبلغ الآن:
        """
    else:  # withdraw إلى واقع
        user = db.get_user(update.effective_user.id)
        message = f"""
💸 السحب إلى واقع عبر {method_info['name']} {method_info['emoji']}

💵 رصيدك الحالي: {format_currency(user.balance)}
💰 الحد الأدنى: {format_currency(Config.MIN_WITHDRAWAL)}
💰 الحد الأقصى: {format_currency(Config.MAX_WITHDRAWAL)}

⏳ **يتطلب موافقة الإدمن** — تحويل يدوي

📝 الخطوات:
1. أرسل المبلغ الذي تريد سحبه
2. أرسل بيانات الاستلام (رقم/محفظة)
3. انتظر موافقة الإدمن

أرسل المبلغ الآن:
        """
    
    context.user_data['state'] = WAITING_FOR_AMOUNT
    context.user_data['operation'] = operation
    context.user_data['method'] = method
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=Keyboards.cancel_operation()
    )

