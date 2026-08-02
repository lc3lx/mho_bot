"""
معالجات أوامر البوت
"""

import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

import ui
import napoleon_ui
import screens
from database import DatabaseManager, User, Transaction
from config import Config
from keyboards import Keyboards
from utils import (
    format_currency,
    validate_amount,
    get_user_display_name,
    safe_edit_callback_message,
    tg_code,
)
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


def user_is_funded(user) -> bool:
    """هل أكمل المستخدم شحناً ناجحاً مرة واحدة؟ (اختياري — لم يعد قيداً)"""
    if not user:
        return False
    return db.user_has_funded(user.id)


def user_has_ichancy(user) -> bool:
    """هل لدى المستخدم حساب Ichancy مرتبط؟ (اليوزر يكفي — الـ ID مش مطلوب)"""
    return bool(user and (user.ichancy_username or user.ichancy_player_id))


def user_is_banned(user) -> bool:
    """هل المستخدم محظور؟"""
    return bool(user and getattr(user, "is_banned", False))


def user_accepted_terms(user) -> bool:
    """هل ضغط المستخدم زر الموافقة على الآثار الجانبية؟"""
    return bool(user and getattr(user, "terms_accepted_at", None))


def get_user_stage(user, telegram_id: int | None = None) -> str:
    """
    مرحلة المستخدم بعد الاشتراك.
    لا يوجد قيد شحن ولا قيد حساب Ichancy — القائمة مفتوحة للجميع.
    """
    return "ready"


def stage_markup_for_user(user, telegram_id: int | None = None):
    return Keyboards.stage_markup(get_user_stage(user, telegram_id))


async def send_consent_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رسالة «دخّلني» + زر الموافقة — تظهر لمن لم يوافق بعد."""
    text = Config.MESSAGES["first_start_consent"]
    markup = Keyboards.first_start_consent()
    if await ui.show_banner_screen(update, context, text, markup, Config.CONSENT_BANNER):
        return
    try:
        if update.callback_query:
            await safe_edit_callback_message(
                update, text, reply_markup=markup, parse_mode="HTML", context=context
            )
        elif update.effective_message:
            await ui.typing(context, update.effective_message.chat_id)
            await update.effective_message.reply_text(
                text, reply_markup=markup, parse_mode="HTML"
            )
        elif update.effective_user:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=text,
                reply_markup=markup,
                parse_mode="HTML",
            )
    except TelegramError:
        logger.exception("فشل إرسال بوابة الموافقة")


async def show_user_home(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    """توجيه المستخدم لشاشة مرحلته الحالية فقط (رسالة واحدة واضحة)."""
    await show_funded_home(update, context, user)


async def check_channel_subscription(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> tuple[bool, str | None]:
    """
    التحقق من عضوية المستخدم في القناة المطلوبة.
    يعيد: (مشترك؟, سبب الفشل أو None)
    أسباب شائعة: not_subscribed | bot_not_admin | channel_error
    """
    if not Config.REQUIRE_CHANNEL_SUBSCRIPTION:
        return True, None

    channel_ids = Config.get_required_channel_ids()
    if not channel_ids:
        logger.error("REQUIRED_CHANNEL_ID غير مضبوط — تخطي فرض الاشتراك")
        return True, "channel_error"

    bot_name = (
        getattr(context.bot, "username", None) or Config.BOT_USERNAME or ""
    ).lstrip("@")
    last_error = None

    for chat_id in channel_ids:
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            status = getattr(member, "status", None)
            if status in ("creator", "administrator", "member"):
                return True, None
            if status == "restricted" and bool(getattr(member, "is_member", False)):
                return True, None
            # left / kicked / غير عضو — تحقق ناجح لكن غير مشترك
            return False, "not_subscribed"
        except TelegramError as exc:
            last_error = exc
            logger.warning(
                "تعذر التحقق من اشتراك user_id=%s في %s: %s",
                user_id,
                chat_id,
                exc,
            )
            continue

    # وصلنا هنا يعني كل المحاولات فشلت — غالباً البوت ليس مشرفاً في القناة
    if Config.SUBSCRIPTION_STRICT_MODE:
        logger.error(
            "فشل التحقق من الاشتراك (%s). أضف @%s كمشرف في القناة %s",
            last_error,
            bot_name,
            Config.REQUIRED_CHANNEL_ID,
        )
        return False, "bot_not_admin"

    logger.warning(
        "تخطي فرض الاشتراك (SUBSCRIPTION_STRICT_MODE=false): %s — "
        "أضف @%s كمشرف في القناة لتفعيل التحقق",
        last_error,
        bot_name,
    )
    return True, None


async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """التحقق من عضوية المستخدم في القناة المطلوبة."""
    ok, _reason = await check_channel_subscription(context, user_id)
    return ok


def subscription_failure_message(reason: str | None) -> str:
    """رسالة واضحة حسب سبب فشل التحقق."""
    if reason == "bot_not_admin":
        return (
            "⚠️ تعذر التحقق من الاشتراك حالياً.\n\n"
            "السبب المحتمل: البوت ليس مشرفاً في القناة.\n"
            "أضِف البوت كمشرف في القناة ثم أعد المحاولة."
        )
    if reason == "channel_error":
        return "⚠️ إعدادات القناة غير مكتملة. تواصل مع الإدارة."
    return (
        "❌ الاشتراك غير موجود.\n"
        "ادخل القناة واشترك، ثم اضغط «اشتركت — افتح البوابة»."
    )


async def send_subscription_required(
    update: Update,
    reason: str | None = None,
    bot_username: str | None = None,
    context: ContextTypes.DEFAULT_TYPE | None = None,
):
    """بوابة الشروط + اشتراك بقناة واحدة."""
    bot_username = (bot_username or Config.BOT_USERNAME or "Napoleonrobert_bot").lstrip("@")
    if reason == "bot_not_admin":
        text = (
            "⚠️ التحقق معطل مؤقتاً: البوت مو مشرف بالقناة.\n\n"
            "اشتراكك وحدو ما يكفي. لازم تضيف البوت نفسه مشرف:\n"
            f"1) افتح القناة {Config.TELEGRAM_CHANNEL_URL}\n"
            "2) Administrators → Add Admin\n"
            f"3) ابحث عن: @{bot_username}\n"
            "4) ضيفو مشرف (أي صلاحية بسيطة تكفي)\n"
            "5) ارجع واضغط «اشتركت — افتح البوابة»\n\n"
            "مهم: ضيف البوت مو حساب شخصي."
        )
    else:
        text = (
            f"{Config.MESSAGES['ad_warning']}\n\n"
            + Config.MESSAGES["terms_gate"].format(bot_name=Config.BOT_DISPLAY_NAME)
            + "\n\n"
            + Config.MESSAGES["subscription_verify_hint"]
        )
    markup = Keyboards.required_subscription()
    try:
        if update.callback_query:
            await safe_edit_callback_message(
                update, text, reply_markup=markup, context=context
            )
        elif update.message:
            await update.message.reply_text(text, reply_markup=markup)
        elif update.effective_chat:
            await update.effective_chat.send_message(text, reply_markup=markup)
    except TelegramError as exc:
        if "message is not modified" in str(exc).lower():
            return
        try:
            chat = update.effective_chat
            if chat:
                await chat.send_message(text, reply_markup=markup)
        except TelegramError:
            logger.exception("فشل إرسال رسالة الاشتراك")


async def interactive_answer(query, text: str, alert: bool = False):
    """رد تفاعلي سريع على ضغط الزر."""
    if not query:
        return
    try:
        await query.answer(text[:200], show_alert=alert)
    except TelegramError:
        pass


def build_home_card(user) -> str:
    """بطاقة مقر نابليون"""
    return napoleon_ui.build_hq_home(user)


async def show_funded_home(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    """القائمة الرئيسية."""
    welcome_message = build_home_card(user)
    markup = Keyboards.start_menu()
    context.user_data.pop("state", None)

    if await ui.show_banner_screen(
        update, context, welcome_message, markup, Config.MENU_BANNER
    ):
        if update.callback_query:
            await interactive_answer(update.callback_query, "🏠 رجوع للمقر")
        return

    if update.callback_query:
        await safe_edit_callback_message(
            update,
            welcome_message,
            reply_markup=markup,
            parse_mode="HTML",
            context=context,
        )
    elif update.effective_message:
        await ui.typing(context, update.effective_message.chat_id)
        await update.effective_message.reply_text(
            welcome_message,
            reply_markup=Keyboards.start_menu(),
            parse_mode="HTML",
        )
    else:
        await context.bot.send_message(
            chat_id=user.telegram_id,
            text=welcome_message,
            reply_markup=Keyboards.start_menu(),
            parse_mode="HTML",
        )



async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """موافقة → اشتراك → القائمة الرئيسية (الشحن وحساب Ichancy اختياريان)."""
    user_id = update.effective_user.id
    logger.info("استلام /start من user_id=%s", user_id)

    referral_code = None
    if context.args and len(context.args) > 0:
        referral_code = context.args[0]
        context.user_data["pending_referral_code"] = referral_code
    else:
        referral_code = context.user_data.get("pending_referral_code")

    user = db.get_user(user_id)
    if not user:
        user = db.create_user(
            telegram_id=user_id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
        )
        if user and referral_code and referral_code != user.referral_code:
            await handle_referral(user, referral_code, context)

        if not user:
            await update.effective_message.reply_text(
                "❌ تعذر إنشاء الحساب. أرسل /start وحاول مرة أخرى."
            )
            return
    elif referral_code:
        # مستخدم قديم فتح رابط إحالة
        if update.effective_message:
            await update.effective_message.reply_text(
                "🔴 الإحالة ما انحسبت.\n\n"
                "الحساب كان مسجل سابقًا،\n"
                "يعني رفيقك وصل قبل الدعوة وسبقك عالباب 😌"
            )

    if user_is_banned(user) and user_id not in Config.ADMIN_IDS:
        text = "🚫 حسابك محظور من استخدام البوت.\nتواصل مع الدعم إن كنت تظن أن هذا خطأ."
        if update.callback_query:
            await interactive_answer(update.callback_query, "حساب محظور", alert=True)
            await safe_edit_callback_message(update, text, context=context)
        elif update.effective_message:
            await update.effective_message.reply_text(text)
        return

    # الإدمن يتجاوز بوابة الموافقة والاشتراك
    if user_id in Config.ADMIN_IDS:
        if not user_accepted_terms(user):
            db.accept_terms(user_id)
            user = db.get_user(user_id)
        context.user_data["balance"] = user.balance or 0
        context.user_data["telegram_id"] = user.telegram_id
        await show_funded_home(update, context, user)
        return

    if not user_accepted_terms(user):
        await send_consent_gate(update, context)
        return

    subscribed, reason = await check_channel_subscription(context, user_id)
    if not subscribed:
        await send_subscription_required(
            update, reason, getattr(context.bot, "username", None), context=context
        )
        return

    context.user_data["balance"] = user.balance or 0
    context.user_data["telegram_id"] = user.telegram_id

    if update.callback_query:
        await interactive_answer(update.callback_query, "✅ تم فك القفل — أهلاً فيك")

    await show_funded_home(update, context, user)


async def start_continue_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """توجيه حسب مرحلة المستخدم"""
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
            await safe_edit_callback_message(update, text, context=context)
        else:
            await update.message.reply_text(text)
        return

    await show_user_home(update, context, user)


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج القائمة الرئيسية / رجوع للمقر"""
    subscribed, reason = await check_channel_subscription(
        context, update.effective_user.id
    )
    if not subscribed:
        await send_subscription_required(
            update, reason, getattr(context.bot, "username", None), context=context
        )
        return

    user = db.get_user(update.effective_user.id)
    if not user or not user_accepted_terms(user):
        await start_handler(update, context)
        return

    if update.callback_query:
        await interactive_answer(update.callback_query, napoleon_ui.HOME_BACK_TEXT[:180])

    await show_funded_home(update, context, user)


async def full_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القائمة الكاملة للخدمات"""
    user = db.get_user(update.effective_user.id)
    if not user or not user_accepted_terms(user):
        await start_handler(update, context)
        return
    await show_funded_home(update, context, user)


async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بطاقة المستخدم"""
    user = db.get_user(update.effective_user.id)
    if not user:
        await start_handler(update, context)
        return
    await screens.show_card(update, context, user, update.effective_user)


async def refund_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """طلب استرداد حوالة"""
    message = (
        "🔁 رجّعلي حوالتي\n\n"
        "أرسل تفاصيل الطلب في رسالة واحدة:\n"
        "• نوع الحوالة\n• رقم العملية\n• المبلغ\n• سبب الاسترداد\n\n"
        "المحاسب رح يراجع الطلب... بلا دراما زيادة 😂"
    )
    context.user_data["state"] = WAITING_FOR_MESSAGE
    context.user_data["operation"] = "refund_request"
    await safe_edit_callback_message(
        update, message, reply_markup=Keyboards.cancel_operation(), context=context
    )


async def deposit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عبّي محفظتي"""
    from payment_handler import reset_payment_session
    user = db.get_user(update.effective_user.id)
    if not user:
        await start_handler(update, context)
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    await reset_payment_session(context, bot=context.bot, chat_id=chat_id)
    await screens.show_deposit_hub(update, context, user)


async def withdraw_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فضّي محفظتي"""
    user = db.get_user(update.effective_user.id)
    if not user:
        await start_handler(update, context)
        return
    await screens.show_withdraw_hub(update, context, user)


async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await start_handler(update, context)
        return
    await ReferralHandler.show_referral_menu(update, context)


async def wallet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """جيبتي"""
    user = db.get_user(update.effective_user.id)
    if not user:
        await start_handler(update, context)
        return
    await screens.show_pocket(update, context, user)


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الحقني يا دعم"""
    await screens.show_support(update, context)


async def gift_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إهداء الرصيد"""
    user = db.get_user(update.effective_user.id)
    
    if user.balance < Config.MIN_GIFT:
        message = (
            f"❌ الحد الأدنى للإهداء هو {format_currency(Config.MIN_GIFT)}\n"
            f"💵 رصيدك الحالي: {format_currency(user.balance)}"
        )
        if update.callback_query:
            await safe_edit_callback_message(
                update, message, reply_markup=Keyboards.wallet_menu(), context=context
            )
        else:
            await update.message.reply_text(message, reply_markup=Keyboards.wallet_menu())
        return
    
    message = ui.card(
        "🎁 إهداء رصيد",
        [
            ("💵 رصيدك:", f"<b>{format_currency(user.balance)}</b>"),
            ("💰 الحد الأدنى:", f"<b>{format_currency(Config.MIN_GIFT)}</b>"),
        ],
        footer="أرسل المبلغ اللي بدك تهديه — بعدها منطلب آيدي المستلم ✍️",
    )
    
    # حفظ حالة المحادثة
    context.user_data['state'] = WAITING_FOR_AMOUNT
    context.user_data['operation'] = 'gift'
    
    if update.callback_query:
        await safe_edit_callback_message(
            update,
            message,
            reply_markup=Keyboards.cancel_operation(),
            parse_mode="HTML",
            context=context,
        )
    else:
        await update.message.reply_text(
            message,
            reply_markup=Keyboards.cancel_operation(),
            parse_mode="HTML",
        )

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج لوحة الإدمن"""
    await AdminHandler.admin_panel(update, context)

async def transaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دفتر الفضايح"""
    await screens.show_ledger(update, context)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الاستعلامات المضمنة"""
    query = update.callback_query
    data = query.data

    # منع الضغط المتكرر (ثانيتان) — عدا الاشتراك/الموافقة/الزر الممنوع
    if data not in ("accept_side_effects", "check_subscription", "forbidden_press"):
        if napoleon_ui.rate_limited(context, update.effective_user.id):
            await interactive_answer(query, napoleon_ui.pick_spam_toast(), alert=True)
            return

    if data == "accept_side_effects":
        db.create_user(
            telegram_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
        )
        db.accept_terms(update.effective_user.id)
        await interactive_answer(query, "🚀 تم قبول الآثار الجانبية")
        await start_handler(update, context)
        return

    # لا يُسمح باستخدام أي زر قبل الاشتراك بالقناة.
    if data == "check_subscription":
        subscribed, reason = await check_channel_subscription(
            context, update.effective_user.id
        )
        if subscribed:
            await interactive_answer(query, "✅ تم فك القفل — أهلاً فيك", alert=False)
            await start_handler(update, context)
        else:
            await interactive_answer(
                query, subscription_failure_message(reason), alert=True
            )
            await send_subscription_required(
                update, reason, getattr(context.bot, "username", None), context=context
            )
        return

    # ردود تفاعلية قصيرة حسب الزر
    toast = {
        "deposit": "⚡ تنعش المحفظة…",
        "withdraw": "🏧 قسم الإخراج…",
        "ichancy_hub": "⚡️ حسابك…",
        "ichancy_create_start": "⚔️ إنشاء حساب…",
        "ichancy_random_name": "🎲 سميني…",
        "ichancy_topup_start": "💸 بوابة التعبئة…",
        "ichancy_withdraw_start": "💰 قسم السحب…",
        "gift_code": "🎟️ الكود يا بطل…",
        "gift_balance": "👛 جيبتي…",
        "gift_send": "🎁 هدية…",
        "contact": "🚑 الدعم…",
        "referrals": "👥 جيش نابليون…",
        "profile": "🪪 بطاقتك…",
        "transactions": "🧾 دفتر الفضايح…",
        "main_menu": "🏠 رجوع للمقر…",
        "full_menu": "📋 القائمة…",
        "extras_menu": "🧰 شغلات زيادة…",
        "guide_quick": "📘 فهمني بسرعة…",
        "refund_request": "🔁 استرداد…",
        "terms": "📘 الدليل…",
        "cancel_operation": "❌ تم الإلغاء",
    }.get(data)
    if toast:
        await interactive_answer(query, toast)
    else:
        try:
            await query.answer()
        except TelegramError:
            pass

    # اعتراض دفاعي للأزرار القديمة قبل جميع بوابات التسجيل.
    if data == "ichancy_link_account":
        await IchancyHandler.start_link_account(update, context)
        return

    subscribed, reason = await check_channel_subscription(
        context, update.effective_user.id
    )
    is_admin = update.effective_user.id in Config.ADMIN_IDS
    if not subscribed and not is_admin:
        await send_subscription_required(
            update, reason, getattr(context.bot, "username", None), context=context
        )
        return

    # بوابة الموافقة
    user = db.get_user(update.effective_user.id)
    if user_is_banned(user) and not is_admin:
        await interactive_answer(query, "حساب محظور", alert=True)
        await safe_edit_callback_message(
            update,
            "🚫 حسابك محظور من استخدام البوت.",
            context=context,
        )
        return
    if user and not user_accepted_terms(user) and not is_admin:
        await send_consent_gate(update, context)
        return

    # القائمة الرئيسية
    if data == "main_menu":
        await main_menu_handler(update, context)
        return
    if data == "full_menu":
        await full_menu_handler(update, context)
        return
    if data == "start_continue":
        await start_continue_handler(update, context)
        return

    # شاشات نابليون الجديدة
    if data == "forbidden_press":
        await interactive_answer(query, napoleon_ui.forbidden_press_text(), alert=True)
        return
    if data == "extras_menu":
        await screens.show_extras(update, context)
        return
    if data == "guide_quick":
        await screens.show_guide(update, context)
        return
    if data == "extras_surprises":
        await safe_edit_callback_message(
            update,
            "🎁 مفاجآت المعلم\n\nلسا عم نحضّرها بالمستودع الخلفي.\nخلّيك قريب 😂",
            reply_markup=Keyboards.extras_menu(),
            context=context,
        )
        return
    if data == "extras_news":
        await safe_edit_callback_message(
            update,
            "📢 آخر الأخبار\n\nما في بيان رسمي اليوم.\nالمقر هادي… وهذا خبر كويس 😌",
            reply_markup=Keyboards.extras_menu(),
            context=context,
        )
        return
    if data == "extras_settings":
        await safe_edit_callback_message(
            update,
            "⚙️ الإعدادات\n\nقريبًا من هون بتقدر تضبط إشعاراتك وحساباتك المحفوظة.",
            reply_markup=Keyboards.extras_menu(),
            context=context,
        )
        return
    if data == "wallet_refresh":
        user = db.get_user(update.effective_user.id)
        await screens.show_pocket(update, context, user)
        return
    if data == "deposit_other":
        await safe_edit_callback_message(
            update,
            "💵 طرق ثانية\n\nحاليًا المتاح: سيرياتيل / شام كاش / عملات رقمية.\nإذا عندك طريقة خاصة تواصل مع الدعم.",
            reply_markup=Keyboards.wallet_deposit_menu(),
            context=context,
        )
        return
    if data == "withdraw_enter_amount":
        context.user_data["state"] = WAITING_FOR_AMOUNT
        context.user_data["operation"] = "withdraw"
        context.user_data.pop("method", None)
        await safe_edit_callback_message(
            update,
            "💰 اكتب المبلغ رقمًا فقط\n\n"
            f"الحد الأدنى: {format_currency(Config.MIN_WITHDRAWAL)}\n"
            f"الحد الأقصى: {format_currency(Config.MAX_WITHDRAWAL)}",
            reply_markup=Keyboards.cancel_operation(),
            context=context,
        )
        return
    if data == "withdraw_rules":
        await safe_edit_callback_message(
            update,
            "📋 شروط السحب\n\n"
            f"• الحد الأدنى: {format_currency(Config.MIN_WITHDRAWAL)}\n"
            f"• الرسوم: {Config.WITHDRAWAL_FEE_PERCENTAGE:g}%\n"
            "• الطلب يمر بمراجعة يدوية\n"
            "• لا تضغط مرتين على نفس الطلب\n"
            "• استخدم الخدمة بمسؤولية 🔞",
            reply_markup=Keyboards.wallet_withdraw_gate(),
            context=context,
        )
        return
    if data == "ichancy_topup_know_id":
        await IchancyHandler.start_topup(update, context)
        return
    if data == "ichancy_topup_where_id":
        # زر قديم — ما عاد في ID
        await IchancyHandler.start_topup(update, context)
        return
    if data == "ichancy_random_name":
        await IchancyHandler.random_name_and_create(update, context)
        return
    if data == "ichancy_withdraw_continue":
        await IchancyHandler.start_withdraw_from_ichancy(update, context)
        return
    if data == "ichancy_withdraw_rules":
        mins = Config.ICHANCY_CONFIG.get("withdraw_cooldown_minutes", 30)
        await safe_edit_callback_message(
            update,
            "📋 شروط السحب من iChancy\n\n"
            f"• سحب واحد كل {mins} دقيقة\n"
            "• لازم يكون عندك حساب مرتبط بالبوت\n"
            "• المبلغ ينزل لمحفظة البوت بعد التنفيذ\n"
            "• استخدم الخدمة بمسؤولية 🔞",
            reply_markup=Keyboards.ichancy_withdraw_gate(),
            context=context,
        )
        return
    if data == "gift_code_enter":
        context.user_data["state"] = WAITING_FOR_GIFT_CODE
        await safe_edit_callback_message(
            update,
            "⌨️ اكتب الكود هون مثل ما هو\nولا تزخرفه... الكود حساس وبيزعل بسرعة 😂",
            reply_markup=Keyboards.cancel_operation(),
            context=context,
        )
        return
    if data == "gift_code_history":
        await safe_edit_callback_message(
            update,
            "📋 أكوادك السابقة\n\nالسجل التفصيلي قريبًا.\nإذا استخدمت كود ناجح، الرصيد بينضاف مباشرة.",
            reply_markup=Keyboards.gift_code_menu(),
            context=context,
        )
        return
    if data.startswith("guide_"):
        tips = {
            "guide_deposit": "💸 عبّي محفظتك من زر «عبّي محفظتي»، اختار الطريقة واتبع الخطوات.",
            "guide_withdraw": "💰 اسحب من «فضّي محفظتي»، راجع الشاشة النهائية قبل التثبيت.",
            "guide_wallet": "👛 المحفظة رصيد البوت الداخلي: تعبئة ← شحن iChancy أو سحب للواقع.",
            "guide_faq": "🆘 مشكلة شائعة: تأكد من الأرقام، لا تضغط مرتين، وتأكد إن الطلب مش معلّق.",
            "guide_responsible": "🔞 الخدمة للبالغين فقط. استخدمها بمسؤولية وبدون مخاطرة زيادة.",
        }
        tip = tips.get(data, "📘 اختار موضوع من الدليل.")
        await safe_edit_callback_message(
            update, tip, reply_markup=Keyboards.guide_menu(), context=context
        )
        return
    if data in ("history_deposits", "history_withdrawals", "history_pending", "history_by_date", "history_all", "history_gifts", "history_referrals"):
        user = db.get_user(update.effective_user.id)
        kind = {
            "history_deposits": "deposits",
            "history_withdrawals": "withdrawals",
            "history_pending": "pending",
            "history_all": "all",
            "history_gifts": "all",
            "history_referrals": "all",
            "history_by_date": "all",
        }[data]
        if data == "history_by_date":
            await safe_edit_callback_message(
                update,
                "📆 اختيار التاريخ\n\nقريبًا تقدر تصفّي حسب يوم معيّن.\nهلّق اعرض السجل من الأزرار الثانية.",
                reply_markup=Keyboards.ledger_menu(),
                context=context,
            )
            return
        await screens.show_history(update, context, user, kind)
        return
    if data in ("profile_edit", "profile_security"):
        await safe_edit_callback_message(
            update,
            "🪪 القسم قيد التجهيز.\nالحسابات المحفوظة من زر بطاقتي السابق صارت ضمن الإعدادات قريبًا.",
            reply_markup=Keyboards.profile_menu(),
            context=context,
        )
        return
    if data in ("support_photo", "support_tx_issue"):
        context.user_data["state"] = WAITING_FOR_MESSAGE
        context.user_data["operation"] = "message_admin"
        await safe_edit_callback_message(
            update,
            "📝 اكتب مشكلتك برسالة واحدة واضحة.\nإذا صورة، أرسلها مع تعليق قصير.",
            reply_markup=Keyboards.cancel_operation(),
            context=context,
        )
        return
    if data == "referral_recruits" or data == "army_recruits":
        await ReferralHandler.show_recruits(update, context)
        return
    if data == "referral_rewards" or data == "army_commission":
        await ReferralHandler.show_rewards(update, context)
        return
    if data == "referral_rules" or data == "army_rules":
        await ReferralHandler.show_rules(update, context)
        return
    if data == "army_ranks":
        await ReferralHandler.show_ranks(update, context)
        return
    if data == "army_ledger":
        await ReferralHandler.show_ledger(update, context)
        return
    if data == "army_my_rank":
        await ReferralHandler.show_my_rank(update, context)
        return
    if data == "army_withdraw":
        await ReferralHandler.start_withdraw_commission(update, context)
        return
    if data == "withdraw_confirm_submit":
        await PaymentHandler.confirm_withdraw_review(update, context)
        return
    if data == "withdraw_edit_data":
        await withdraw_handler(update, context)
        return
    if data == "withdraw_abort":
        context.user_data.clear()
        await safe_edit_callback_message(
            update,
            "🗑️ انسفنا العملية.\nما صار شي بالحساب.",
            reply_markup=Keyboards.back_to_main(),
            context=context,
        )
        return
    if data == "withdraw_cancel_pending":
        await PaymentHandler.cancel_pending_withdraw(update, context)
        return
    if data == "withdraw_locked":
        await interactive_answer(query, "🔒 فات الطلب عالتنفيذ", alert=True)
        return

    # الإيداع والسحب
    if data == "deposit":
        await deposit_handler(update, context)
        return
    if data == "withdraw":
        await withdraw_handler(update, context)
        return
    if data == "profile":
        await profile_handler(update, context)
        return
    if data == "refund_request":
        await refund_request_handler(update, context)
        return


    # ichancy — حساب / شحن / سحب
    elif data in ("ichancy_to_bot", "ichancy_hub"):
        await IchancyHandler.hub(update, context)
    elif data == "ichancy_create_start":
        await IchancyHandler.start_create_account(update, context)
    elif data == "ichancy_topup_start":
        await screens.show_ichancy_topup_gate(update, context)
    elif data == "ichancy_withdraw_start":
        await screens.show_ichancy_withdraw_gate(update, context)
    elif data == "ichancy_change_password":
        await IchancyHandler.change_password_info(update, context)
    elif data == "open_facebook":
        await safe_edit_callback_message(
            update,
            f"📱 صفحتنا على الفيسبوك:\n{Config.FACEBOOK_URL}",
            reply_markup=stage_markup_for_user(user, update.effective_user.id),
            context=context,
        )

    # لوحة الإدمن
    elif data.startswith("admin_") or data == "cancel_admin_operation":
        if update.effective_user.id not in Config.ADMIN_IDS:
            await update.callback_query.answer("❌ غير مصرح", show_alert=True)
            return
        if data == "admin_panel":
            await AdminHandler.admin_panel(update, context)
        elif data == "admin_users":
            await AdminHandler.user_management(update, context)
        elif data == "admin_add_balance":
            await AdminHandler.add_balance(update, context)
        elif data == "admin_deduct_balance":
            await AdminHandler.deduct_balance(update, context)
        elif data == "admin_user_info":
            await AdminHandler.user_info(update, context)
        elif data == "admin_ban_user":
            await AdminHandler.ban_user(update, context)
        elif data == "admin_unban_user":
            await AdminHandler.unban_user(update, context)
        elif data == "admin_user_stats":
            await AdminHandler.user_stats(update, context)
        elif data == "admin_create_gift_code":
            await AdminHandler.create_gift_code(update, context)
        elif data == "admin_stats":
            await AdminHandler.view_statistics(update, context)
        elif data in ("admin_view_pending", "admin_transactions"):
            await AdminHandler.pending_transactions(update, context)
        elif data == "admin_approve_transaction":
            await AdminHandler.approve_transaction(update, context)
        elif data == "admin_reject_transaction":
            await AdminHandler.reject_transaction(update, context)
        elif data == "admin_broadcast":
            await AdminHandler.broadcast_message(update, context)
        elif data == "admin_messages":
            await ContactHandler.view_messages(update, context)
        elif data == "admin_settings":
            await AdminHandler.settings_menu(update, context)
        elif data == "admin_proxy":
            await AdminHandler.proxy_menu(update, context)
        elif data == "admin_proxy_set":
            await AdminHandler.start_set_proxy(update, context)
        elif data == "admin_proxy_test":
            await AdminHandler.test_current_proxy(update, context)
        elif data == "admin_proxy_disable":
            await AdminHandler.disable_proxy(update, context)
        elif data == "admin_rate_shamcash":
            await AdminHandler.start_set_rate(update, context, "shamcash")
        elif data == "admin_rate_usdt":
            await AdminHandler.start_set_rate(update, context, "usdt")
        elif data == "admin_army":
            await AdminHandler.army_menu(update, context)
        elif data == "admin_army_ranks":
            await AdminHandler.army_ranks_prompt(update, context)
        elif data == "admin_army_hold":
            await AdminHandler.army_set_number(update, context, "hold")
        elif data == "admin_army_min_withdraw":
            await AdminHandler.army_set_number(update, context, "min_withdraw")
        elif data == "admin_army_min_activity":
            await AdminHandler.army_set_number(update, context, "min_activity")
        elif data == "admin_army_activate":
            await AdminHandler.army_activate_prompt(update, context)
        elif data == "admin_army_accrue":
            await AdminHandler.army_accrue_prompt(update, context)
        elif data == "admin_army_rank_override":
            await AdminHandler.army_rank_override_prompt(update, context)
        elif data == "cancel_admin_operation":
            context.user_data.pop("admin_operation", None)
            await AdminHandler.admin_panel(update, context)
        else:
            await update.callback_query.answer("⚠️ زر غير معروف", show_alert=True)
    
    # نظام الإحالات
    elif data == "referrals":
        await referral_handler(update, context)
    elif data == "share_referral":
        await ReferralHandler.share_referral_link(update, context)
    
    # محفظة البوت / إهداء الرصيد
    elif data == "gift_balance":
        await wallet_handler(update, context)
    elif data == "gift_send":
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
        await PaymentHandler.show_withdraw_review(
            update, context, account.account_value
        )
    elif data.startswith("withdraw_manual_dest_"):
        from utils import tg_bold, tg_code
        method = data.replace("withdraw_manual_dest_", "", 1)
        if method == "syriatel_cash":
            prompt = (
                f"📱 أرسل {tg_bold('رقم سيريتل كاش')} لاستلام المبلغ "
                f"(مثال: {tg_code('0999123456')}):"
            )
        else:
            prompt = f"💳 أرسل {tg_bold('عنوان حساب شام كاش')} لاستلام المبلغ:"
        context.user_data["state"] = WAITING_FOR_WITHDRAW_DESTINATION
        await safe_edit_callback_message(
            update,
            prompt,
            reply_markup=Keyboards.cancel_operation(),
            context=context,
            parse_mode="HTML",
        )

    # شام كاش — شحن مثل الصور
    elif data == "shamcash_cur_syp":
        await PaymentHandler.start_shamcash_currency(update, context, "syp")
    elif data == "shamcash_cur_usd":
        await PaymentHandler.start_shamcash_currency(update, context, "usd")
    elif data == "shamcash_confirm_send":
        await PaymentHandler.confirm_shamcash_deposit(update, context)
    elif data == "shamcash_confirm_cancel":
        from payment_handler import reset_payment_session
        chat_id = update.effective_chat.id if update.effective_chat else None
        await reset_payment_session(context, bot=context.bot, chat_id=chat_id)
        user = db.get_user(update.effective_user.id)
        await show_user_home(update, context, user)

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
        from payment_handler import reset_payment_session
        chat_id = update.effective_chat.id if update.effective_chat else None
        await reset_payment_session(context, bot=context.bot, chat_id=chat_id)
        user = db.get_user(update.effective_user.id)
        await show_user_home(update, context, user)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل النصية"""
    is_admin = update.effective_user.id in Config.ADMIN_IDS

    if context.user_data.get("admin_operation") and is_admin:
        await AdminHandler.handle_admin_input(update, context)
        return

    user = db.get_user(update.effective_user.id)
    if user_is_banned(user) and not is_admin:
        await update.message.reply_text("🚫 حسابك محظور من استخدام البوت.")
        return

    subscribed, reason = await check_channel_subscription(
        context, update.effective_user.id
    )
    if not subscribed and not is_admin:
        context.user_data.pop("state", None)
        await send_subscription_required(
            update, reason, getattr(context.bot, "username", None), context=context
        )
        return

    user_state = context.user_data.get('state')

    if user and not user_accepted_terms(user) and not is_admin:
        await send_consent_gate(update, context)
        return

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
        if context.user_data.get("method") != "shamcash":
            context.user_data.clear()
            await update.message.reply_text(
                "⚠️ جلسة شام كاش غير صالحة. اختر طريقة الشحن من جديد.",
                reply_markup=Keyboards.payment_methods("deposit"),
            )
            return
        await PaymentHandler.handle_shamcash_tx_input(
            update, context, update.message.text.strip()
        )
    elif user_state == WAITING_FOR_SHAMCASH_AMOUNT:
        if context.user_data.get("method") != "shamcash":
            context.user_data.clear()
            await update.message.reply_text(
                "⚠️ جلسة شام كاش غير صالحة. اختر طريقة الشحن من جديد.",
                reply_markup=Keyboards.payment_methods("deposit"),
            )
            return
        await PaymentHandler.handle_shamcash_amount_input(
            update, context, update.message.text.strip()
        )
    elif user_state == WAITING_FOR_SYRIATEL_AMOUNT:
        if context.user_data.get("method") != "syriatel_cash":
            context.user_data.clear()
            await update.message.reply_text(
                "⚠️ جلسة سيريتل غير صالحة. اختر طريقة الشحن من جديد.",
                reply_markup=Keyboards.payment_methods("deposit"),
            )
            return
        await PaymentHandler.handle_syriatel_amount(
            update, context, update.message.text.strip()
        )
    elif user_state == WAITING_FOR_SYRIATEL_TX:
        if context.user_data.get("method") != "syriatel_cash":
            context.user_data.clear()
            await update.message.reply_text(
                "⚠️ جلسة سيريتل غير صالحة. اختر طريقة الشحن من جديد.",
                reply_markup=Keyboards.payment_methods("deposit"),
            )
            return
        await PaymentHandler.handle_syriatel_tx(
            update, context, update.message.text.strip()
        )
    else:
        # ردود سرّية على كلمات معيّنة
        secret = napoleon_ui.match_secret_reply(update.message.text or "")
        if secret:
            await update.message.reply_text(secret)
            return
        if user:
            await show_user_home(update, context, user)
        else:
            await start_handler(update, context)

# دوال مساعدة

async def handle_tx_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال رقم العملية للتحقق التلقائي"""
    tx_number = update.message.text.strip()
    await PaymentHandler.verify_auto_deposit(update, context, tx_number)


async def handle_withdraw_destination_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بعد إدخال الوجهة — شاشة مراجعة نهائية قبل التثبيت"""
    destination = update.message.text.strip()
    await PaymentHandler.show_withdraw_review(update, context, destination)


async def handle_ichancy_player_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مسار قديم لإدخال ID — نحوّله لطلب المبلغ باليوزرنيم."""
    operation = context.user_data.get("operation")
    if operation == "ichancy_topup":
        await IchancyHandler.process_topup_player_id(update, context, "")
        return
    if operation == "ichancy_withdraw":
        await IchancyHandler.process_withdraw_player_id(update, context, "")
        return
    await IchancyHandler.process_link_account(update, context, "")


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



async def handle_referral(user, referral_ref, context=None):
    """تسجيل إحالة جديدة في جيش نابليون (مستخدم جديد فقط)."""
    if not referral_ref:
        return

    from referral_service import ReferralArmyService

    session = db.get_session()
    try:
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

        db_user = session.query(User).filter(User.id == user.id).first()
        if db_user.referred_by:
            return

        referrer_detached = db._detach(session, referrer)
        invitee_detached = db._detach(session, db_user)
    finally:
        session.close()

    ReferralArmyService.create_invite(referrer_detached, invitee_detached)
    logger.info(
        "جيش نابليون: إحالة %s -> %s",
        user.telegram_id,
        referrer_detached.telegram_id,
    )
    if context:
        try:
            await context.bot.send_message(
                chat_id=referrer_detached.telegram_id,
                text=(
                    "🟡 رفيقك وصل للمقر،\n"
                    "بس لسا عم يتفرّج عالأزرار.\n"
                    "الإحالة تُحتسب نشطة بعد ربط iChancy والنشاط المؤهل."
                ),
            )
        except Exception:
            pass

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
                f"💰 المبلغ: {format_currency(amount)}\n\n"
                f"👤 الآن أرسل آيدي التليجرام للشخص اللي بدك تهديه "
                f"(الرقم اللي بيظهر عنده بالقائمة الرئيسية):",
                reply_markup=Keyboards.cancel_operation()
            )
        
        elif operation == 'deposit':
            method_config = Config.PAYMENT_METHODS.get(method, {})
            if method_config.get("auto_deposit", method_config.get("auto_enabled")):
                if method_config.get("provider") != "tron":
                    context.user_data.clear()
            await PaymentHandler.process_deposit_request(update, context, amount, method)

        elif operation == 'ichancy_withdraw':
            await IchancyHandler.process_ichancy_withdraw(update, context, amount)

        elif operation == 'ichancy_topup':
            await IchancyHandler.process_topup(update, context, amount)
        
        elif operation == 'withdraw':
            if not method:
                is_valid, validated_amount, error_msg = validate_amount(
                    str(amount),
                    Config.MIN_WITHDRAWAL,
                    Config.MAX_WITHDRAWAL,
                )
                if not is_valid:
                    await update.message.reply_text(
                        error_msg, reply_markup=Keyboards.cancel_operation()
                    )
                    return
                user = db.get_user(update.effective_user.id)
                if user.balance < validated_amount:
                    await update.message.reply_text(
                        f"❌ رصيدك غير كافي\n💵 رصيدك: {format_currency(user.balance)}",
                        reply_markup=Keyboards.cancel_operation(),
                    )
                    return
                context.user_data["amount"] = validated_amount
                context.user_data["state"] = None
                context.user_data["operation"] = "withdraw"
                await update.message.reply_text(
                    f"💰 المبلغ: {format_currency(validated_amount)}\n\n"
                    "اختار طريقة الاستلام:",
                    reply_markup=Keyboards.payment_methods("withdraw"),
                )
                return
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
                "❌ المستخدم غير موجود على البوت.\n"
                "تأكد إنو الآيدي صحيح وإنو الشخص عمل /start قبل.",
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
                ui.card(
                    "✅ تم الإهداء بنجاح",
                    [
                        ("🎁 المبلغ:", f"<b>{format_currency(amount)}</b>"),
                        ("👤 إلى:", ui.esc(get_user_display_name(recipient))),
                        ("💵 رصيدك الآن:", f"<b>{format_currency(sender.balance)}</b>"),
                    ],
                ),
                reply_markup=Keyboards.main_menu(),
                parse_mode="HTML",
            )
            
            # إشعار للمستلم
            try:
                await context.bot.send_message(
                    chat_id=recipient.telegram_id,
                    text=ui.card(
                        "🎉 وصلتك هدية!",
                        [
                            ("🎁 المبلغ:", f"<b>{format_currency(amount)}</b>"),
                            ("👤 من:", ui.esc(get_user_display_name(sender))),
                        ],
                    ),
                    reply_markup=Keyboards.main_menu(),
                    parse_mode="HTML",
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
    """كودك يا بطل"""
    await screens.show_gift_code(update, context)


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
            await update.message.reply_text("🤨 هالكود دخل متنكّر.\n\nتأكد من الأحرف والأرقام،\nوجرّب مرة ثانية بلا بهارات 😂", reply_markup=Keyboards.gift_code_menu())
            # يبقى في المود حتى يحاول مرة أخرى أو يلغي
            return

        user = db.get_user(update.effective_user.id)
        existing_usage = session.query(GiftCodeUsage).filter(
            GiftCodeUsage.code_id == gift_code.id,
            GiftCodeUsage.user_id == user.id,
        ).first()

        if existing_usage:
            await update.message.reply_text("🤨 هالكود دخل متنكّر.\n\nتأكد من الأحرف والأرقام،\nوجرّب مرة ثانية بلا بهارات 😂", reply_markup=Keyboards.gift_code_menu())
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
            reply_markup=Keyboards.back_to_main(),
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
        from database import Message
        
        admin_message = Message(
            user_id=user.id,
            message_type="user_to_admin",
            content=(
                f"[طلب استرداد حوالة]\n{message_text}"
                if is_refund
                else message_text
            ),
            is_read=False,
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
                    text=(
                        f"{admin_header}\n"
                        f"🆔 {user.telegram_id}\n\n"
                        f"{message_text}\n\n"
                        f"للرد: /reply {user.telegram_id} نص الرد"
                    ),
                )
            except TelegramError:
                logger.warning(f"لا يمكن إرسال إشعار للإدمن {admin_id}")
        
        await update.message.reply_text(
            "✅ وصلت رسالتك للدعم.\n\nصار الملف برقبتهم رسميًا...\nوالبوت انسحب من القضية بكل احترام 😂",
            reply_markup=Keyboards.back_to_main(),
        )
        
        context.user_data.clear()
        
    finally:
        session.close()

async def handle_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الشروط والأحكام"""
    terms_text = (
        Config.MESSAGES["terms_gate"].format(bot_name=Config.BOT_DISPLAY_NAME)
        + f"""

🩸 حدود التشغيل:
• الحد الأدنى للإيداع: {format_currency(Config.MIN_DEPOSIT)}
• الحد الأدنى للسحب: {format_currency(Config.MIN_WITHDRAWAL)}
• نسبة الإحالات: {Config.REFERRAL_PERCENTAGE:g}%

أي مخالفة = إغلاق الحساب بدون نقاش.
"""
    )
    await safe_edit_callback_message(
        update,
        terms_text,
        reply_markup=Keyboards.back_to_main(),
        context=context,
    )

async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار طريقة الدفع"""
    from payment_handler import reset_payment_session

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

    chat_id = update.effective_chat.id if update.effective_chat else None

    # سحب: إذا المبلغ محدد مسبقاً من شاشة «اكتب المبلغ»
    if operation == "withdraw" and context.user_data.get("amount"):
        amount = context.user_data["amount"]
        context.user_data["method"] = method
        context.user_data["operation"] = "withdraw"
        await PaymentHandler.process_withdraw_request_from_callback(
            update, context, float(amount), method
        )
        return

    await reset_payment_session(context, bot=context.bot, chat_id=chat_id)
    
    if operation == "deposit":
        auto_note = ""
        if method_info.get("auto_deposit", method_info.get("auto_enabled")):
            if method_info.get("provider") == "tron":
                rate = Config.get_usdt_syp_rate()
                min_usdt = float(Config.USDT_CONFIG.get("min_usdt", 2))
                auto_note = (
                    "\n\n⚡ التحقق تلقائي — سيُعطى مبلغ USDT فريد بالضبط "
                    "(فواصل عشرية) لتمييز تحويلك.\n"
                    f"💱 السعر الحالي: {format_currency(rate)} ل.س = 1 $\n"
                    "الرصيد يُضاف لمحفظتك بالليرة السورية."
                )
                message = f"""
💰 الإيداع عبر {method_info['name']} {method_info['emoji']}

📝 أرسل المبلغ بالدولار / USDT اللي بدك تحوّله.
بعد وصول التحويل، ينضاف الرصيد بالليرة حسب سعر الأدمن.{auto_note}

💰 الحد الأدنى: {min_usdt:.2f} $
💰 الحد الأقصى: {format_currency(Config.MAX_DEPOSIT)} ل.س (بعد التحويل)

أرسل مبلغ الدولار الآن:
                """
                context.user_data['state'] = WAITING_FOR_AMOUNT
                context.user_data['operation'] = operation
                context.user_data['method'] = method
                await safe_edit_callback_message(
                    update,
                    message,
                    reply_markup=Keyboards.cancel_operation(),
                    context=context,
                )
                return
            else:
                auto_note = "\n\n⚡ التحقق تلقائي — بعد التحويل أرسل رقم العملية."
        min_label = format_currency(Config.MIN_DEPOSIT)
        if method == "syriatel_cash":
            min_label = format_currency(
                float(Config.SYRIATEL_DEPOSIT.get("min_amount", Config.MIN_DEPOSIT))
            )
        message = f"""
💰 الإيداع عبر {method_info['name']} {method_info['emoji']}

📝 تعليمات الإيداع:
1. أرسل المبلغ الذي تريد إيداعه (بالليرة)
2. حوّل المبلغ حسب التعليمات
3. أرسل رقم العملية للتحقق التلقائي{auto_note}

💰 الحد الأدنى: {min_label}
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
📉 رسوم السحب: {Config.WITHDRAWAL_FEE_PERCENTAGE:g}% لصاحب البوت

⏳ يتطلب موافقة الإدمن — تحويل يدوي

📝 الخطوات:
1. أرسل المبلغ الذي تريد سحبه
2. أرسل بيانات الاستلام (رقم/محفظة)
3. انتظر موافقة الإدمن

أرسل المبلغ الآن:
        """
    
    context.user_data['state'] = WAITING_FOR_AMOUNT
    context.user_data['operation'] = operation
    context.user_data['method'] = method
    
    await safe_edit_callback_message(
        update,
        message,
        reply_markup=Keyboards.cancel_operation(),
        context=context,
    )

