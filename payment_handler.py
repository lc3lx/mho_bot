"""
معالج المدفوعات والمعاملات المالية
يدعم التحقق التلقائي عبر API SYRIA لسيريتل كاش وشام كاش
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from database import DatabaseManager, User, Transaction
from config import Config
from keyboards import Keyboards
from utils import format_currency, validate_amount, get_user_display_name, generate_transaction_reference
from apisyria_client import ApiSyriaClient, ApiSyriaError
from tron_usdt_client import TronUsdtClient, TronUsdtError

logger = logging.getLogger(__name__)
db = DatabaseManager()
api_client = ApiSyriaClient()
tron_client = TronUsdtClient()


class PaymentHandler:
    """معالج المدفوعات"""

    @staticmethod
    def _get_provider(method: str) -> str:
        return Config.PAYMENT_METHODS.get(method, {}).get("provider", "manual")

    @staticmethod
    def _is_auto_deposit(method: str) -> bool:
        method_config = Config.PAYMENT_METHODS.get(method, {})
        return method_config.get("auto_deposit", method_config.get("auto_enabled", False))

    @staticmethod
    def _is_auto_withdraw(method: str) -> bool:
        """السحب للواقع دائماً يدوي — لا سحب أوتو للطرق الخارجية"""
        method_config = Config.PAYMENT_METHODS.get(method, {})
        return method_config.get("auto_withdraw", False)

    @staticmethod
    def _api_ready(method: str) -> bool:
        provider = PaymentHandler._get_provider(method)
        if provider == "apisyria":
            if method == "syriatel_cash":
                return api_client.syriatel_ready()
            if method == "shamcash":
                return api_client.shamcash_ready()
        if provider == "tron":
            return tron_client.is_configured()
        return False

    # ─── شام كاش — تدفق مثل الصور ───────────────────────────

    @staticmethod
    async def start_shamcash_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """قائمة شام كاش: اختيار العملة + شعار"""
        from pathlib import Path
        from telegram import InputFile

        assets = Path(__file__).resolve().parent / "assets"
        caption = (
            "❝ شحن SHAM CASH\n\n"
            "يرجى اختيار العملة التي تريد شحن محفظة البوت بها"
        )
        logo = assets / "shamcash_logo.png"
        chat_id = update.effective_chat.id

        if logo.exists():
            try:
                if update.callback_query and update.callback_query.message:
                    await update.callback_query.message.delete()
            except TelegramError:
                pass
            with open(logo, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(photo, filename="shamcash_logo.png"),
                    caption=caption,
                    reply_markup=Keyboards.shamcash_currency_menu(),
                )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                caption,
                reply_markup=Keyboards.shamcash_currency_menu(),
            )
        else:
            await update.message.reply_text(
                caption,
                reply_markup=Keyboards.shamcash_currency_menu(),
            )

    @staticmethod
    async def start_shamcash_currency(
        update: Update, context: ContextTypes.DEFAULT_TYPE, currency: str
    ):
        """تعليمات الشحن حسب العملة + صورة رقم العملية"""
        from pathlib import Path
        from telegram import InputFile

        assets = Path(__file__).resolve().parent / "assets"
        cfg = Config.SHAMCASH_DEPOSIT
        timeout = Config.APISYRIA_CONFIG.get("deposit_timeout_minutes", 15)
        currency = currency.lower()

        if currency == "usd":
            account = (
                cfg.get("account_usd")
                or Config.APISYRIA_CONFIG.get("shamcash_account")
                or "غير مُعدّ"
            )
            min_amount = cfg["min_usd"]
            text = (
                f"❝ شحن SHAM CASH - USD\n\n"
                f"اشحن البوت عن طريق شام كاش بالدولار الأمريكي.\n"
                f"الحد الأدنى لشحن شام كاش بالدولار هو {min_amount:.2f} $.\n\n"
                f"قم بالتحويل إلى العنوان المرفق (انقر على العنوان للنسخ):\n"
                f"`{account}`\n\n"
                f"⏰ المهلة: {timeout} دقيقة فقط\n"
                f"ثم ادخل رقم عملية التحويل كما هو موضح بالصورة المرفقة"
            )
        else:
            account = (
                cfg.get("account_syp")
                or Config.APISYRIA_CONFIG.get("shamcash_account")
                or "غير مُعدّ"
            )
            min_amount = cfg["min_syp"]
            text = (
                f"❝ شحن SHAM CASH - SYP\n\n"
                f"اشحن البوت عن طريق شام كاش بالليرة السورية.\n"
                f"الحد الأدنى لشحن شام كاش بالليرة السورية هو {format_currency(min_amount)}.\n\n"
                f"قم بالتحويل إلى العنوان المرفق (انقر على العنوان للنسخ):\n"
                f"`{account}`\n\n"
                f"⏰ المهلة: {timeout} دقيقة فقط\n"
                f"ثم ادخل رقم عملية التحويل كما هو موضح بالصورة المرفقة"
            )

        context.user_data.clear()
        context.user_data["state"] = "waiting_for_shamcash_tx"
        context.user_data["operation"] = "shamcash_deposit"
        context.user_data["method"] = "shamcash"
        context.user_data["shamcash_currency"] = currency
        context.user_data["deposit_started_at"] = datetime.utcnow().isoformat()

        chat_id = update.effective_chat.id
        guide = assets / "shamcash_tx_guide.png"

        try:
            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.delete()
        except TelegramError:
            pass

        if guide.exists():
            with open(guide, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(photo, filename="shamcash_tx_guide.png"),
                    caption=text,
                    parse_mode="Markdown",
                    reply_markup=Keyboards.cancel_operation(),
                )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=Keyboards.cancel_operation(),
            )

    @staticmethod
    async def handle_shamcash_tx_input(
        update: Update, context: ContextTypes.DEFAULT_TYPE, tx_number: str
    ):
        """بعد رقم العملية — طلب المبلغ"""
        tx_number = ApiSyriaClient.normalize_tx_id(tx_number)
        if len(tx_number) < 3:
            await update.message.reply_text(
                "❌ رقم العملية غير صحيح. أرسل الرقم كما في الصورة (مثال: 6278231).",
                reply_markup=Keyboards.cancel_operation(),
            )
            return

        if db.is_external_transaction_used(tx_number, "shamcash"):
            await update.message.reply_text(
                "❌ رقم العملية مستخدم مسبقاً.",
                reply_markup=Keyboards.main_menu(),
            )
            context.user_data.clear()
            return

        context.user_data["shamcash_tx"] = tx_number
        context.user_data["state"] = "waiting_for_shamcash_amount"

        currency = context.user_data.get("shamcash_currency", "syp")
        unit = "$" if currency == "usd" else "ل.س"
        await update.message.reply_text(
            f"💵 يرجى إدخال المبلغ الذي قمت بتحويله ({unit}):",
            reply_markup=Keyboards.cancel_operation(),
        )

    @staticmethod
    async def handle_shamcash_amount_input(
        update: Update, context: ContextTypes.DEFAULT_TYPE, amount_text: str
    ):
        """عرض ملخص التأكيد قبل الإرسال"""
        currency = context.user_data.get("shamcash_currency", "syp")
        tx_number = context.user_data.get("shamcash_tx")
        cfg = Config.SHAMCASH_DEPOSIT

        if not tx_number:
            context.user_data.clear()
            await update.message.reply_text(
                "❌ انتهت الجلسة. ابدأ من جديد.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        try:
            amount = float(str(amount_text).replace(",", "").strip())
        except ValueError:
            await update.message.reply_text(
                "❌ المبلغ غير صحيح. أرسل رقماً فقط.",
                reply_markup=Keyboards.cancel_operation(),
            )
            return

        if currency == "usd":
            min_a = cfg["min_usd"]
            if amount < min_a:
                await update.message.reply_text(
                    f"❌ الحد الأدنى للشحن بالدولار هو {min_a:.2f} $",
                    reply_markup=Keyboards.cancel_operation(),
                )
                return
            rate = Config.get_shamcash_usd_rate()
            syp_amount = round(amount * rate, 2)
            summary = (
                f"❝ طلب شحن - شام كاش USD\n\n"
                f"معلومات الطلب:\n"
                f"• العملة: الدولار الأمريكي\n"
                f"• سعر الصرف الحالي: {format_currency(rate)}\n"
                f"• المبلغ بالدولار: {amount:.2f} $\n"
                f"• المبلغ بالليرة تقريباً: {format_currency(syp_amount)}\n"
                f"• رقم العملية: `{tx_number}`\n\n"
                f"يرجى التأكد من صحة المعلومات قبل الضغط على إرسال"
            )
            context.user_data["amount"] = amount
            context.user_data["credit_amount_syp"] = syp_amount
        else:
            min_a = cfg["min_syp"]
            if amount < min_a:
                await update.message.reply_text(
                    f"❌ الحد الأدنى للشحن بالليرة هو {format_currency(min_a)}",
                    reply_markup=Keyboards.cancel_operation(),
                )
                return
            summary = (
                f"❝ طلب شحن - شام كاش SYP\n\n"
                f"معلومات الطلب:\n"
                f"• العملة: الليرة السورية\n"
                f"• المبلغ: {format_currency(amount)}\n"
                f"• رقم العملية: `{tx_number}`\n\n"
                f"يرجى التأكد من صحة المعلومات قبل الضغط على إرسال"
            )
            context.user_data["amount"] = amount
            context.user_data["credit_amount_syp"] = amount

        context.user_data["state"] = "waiting_for_shamcash_confirm"
        await update.message.reply_text(
            summary,
            parse_mode="Markdown",
            reply_markup=Keyboards.shamcash_confirm_keyboard(),
        )

    @staticmethod
    async def confirm_shamcash_deposit(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """إرسال الطلب والتحقق التلقائي عبر API SYRIA"""
        from datetime import timedelta

        query = update.callback_query
        tx_number = context.user_data.get("shamcash_tx")
        amount = context.user_data.get("amount")
        credit_syp = context.user_data.get("credit_amount_syp")
        currency = context.user_data.get("shamcash_currency", "syp")
        timeout = Config.APISYRIA_CONFIG.get("deposit_timeout_minutes", 15)

        if not tx_number or not amount or not credit_syp:
            context.user_data.clear()
            await query.edit_message_text(
                "❌ انتهت الجلسة. ابدأ من جديد.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        await query.edit_message_text("⏳ لحظات من فضلك...")

        user = db.get_user(update.effective_user.id)
        started = context.user_data.get("deposit_started_at")
        if started:
            try:
                started_dt = datetime.fromisoformat(started)
                if datetime.utcnow() - started_dt > timedelta(minutes=timeout):
                    context.user_data.clear()
                    await query.edit_message_text(
                        f"⏰ انتهى الوقت! كان لديك {timeout} دقيقة.\nأنشئ طلباً جديداً.",
                        reply_markup=Keyboards.start_menu(),
                    )
                    return
            except ValueError:
                pass

        if db.is_external_transaction_used(tx_number, "shamcash"):
            context.user_data.clear()
            await query.edit_message_text(
                "❌ رقم العملية مستخدم مسبقاً.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        session = db.get_session()
        try:
            transaction = Transaction(
                user_id=user.id,
                transaction_type="deposit",
                amount=credit_syp,
                method="shamcash",
                status="pending",
                external_transaction_id=tx_number,
                description=(
                    f"إيداع شام كاش {currency.upper()} — "
                    f"مبلغ التحويل {amount} — رقم العملية {tx_number}"
                ),
            )
            session.add(transaction)
            session.commit()
            session.refresh(transaction)
            transaction_id = transaction.id
            request_created_at = transaction.created_at
        finally:
            session.close()

        try:
            result = await asyncio.to_thread(
                api_client.shamcash_find_transaction, tx_number
            )
            data = result.get("data", {})
            if not data.get("found"):
                PaymentHandler._fail_pending_deposit(
                    transaction_id, "رقم عملية غير موجود"
                )
                context.user_data.clear()
                await query.edit_message_text(
                    "❌ تم رفض طلب الشحن. السبب: رقم عملية غير موجود",
                    reply_markup=Keyboards.start_menu(),
                )
                return

            tx_data = data.get("transaction", {})
            actual_amount = ApiSyriaClient.parse_shamcash_amount(tx_data)
            external_id = str(tx_data.get("tran_id", tx_number))

            if not api_client.is_within_deposit_window(
                tx_data, request_created_at, timeout
            ):
                PaymentHandler._fail_pending_deposit(
                    transaction_id, f"خارج مهلة {timeout} دقيقة"
                )
                context.user_data.clear()
                await query.edit_message_text(
                    f"⏰ العملية خارج المهلة المسموحة ({timeout} دقيقة).",
                    reply_markup=Keyboards.start_menu(),
                )
                return

            if not ApiSyriaClient.amounts_match(float(amount), actual_amount):
                PaymentHandler._fail_pending_deposit(
                    transaction_id,
                    f"مبلغ غير مطابق: مطلوب {amount} / فعلي {actual_amount}",
                )
                context.user_data.clear()
                await query.edit_message_text(
                    f"❌ تم رفض طلب الشحن. السبب: المبلغ غير مطابق.\n"
                    f"المدخل: {amount}\n"
                    f"في العملية: {actual_amount}",
                    reply_markup=Keyboards.start_menu(),
                )
                return

            if db.is_external_transaction_used(external_id, "shamcash"):
                PaymentHandler._fail_pending_deposit(transaction_id, "عملية مكررة")
                context.user_data.clear()
                await query.edit_message_text(
                    "❌ هذه العملية مُسجّلة مسبقاً.",
                    reply_markup=Keyboards.main_menu(),
                )
                return

            session = db.get_session()
            try:
                transaction = session.query(Transaction).filter(
                    Transaction.id == transaction_id
                ).first()
                if transaction:
                    transaction.external_transaction_id = external_id
                    transaction.description += f"\nتحقق تلقائي — {external_id}"
                    session.commit()
            finally:
                session.close()

            context.user_data.clear()
            await PaymentHandler.complete_deposit(transaction_id, update, context)

        except ApiSyriaError as exc:
            PaymentHandler._fail_pending_deposit(transaction_id, exc.message)
            context.user_data.clear()
            await query.edit_message_text(
                f"❌ تم رفض طلب الشحن. السبب: {exc.message}",
                reply_markup=Keyboards.start_menu(),
            )
        except Exception as exc:
            logger.exception("ShamCash confirm failed")
            PaymentHandler._fail_pending_deposit(transaction_id, str(exc))
            context.user_data.clear()
            await query.edit_message_text(
                f"❌ حدث خطأ أثناء التحقق.\n{exc}",
                reply_markup=Keyboards.start_menu(),
            )

    @staticmethod
    def _fail_pending_deposit(transaction_id: int, reason: str):
        session = db.get_session()
        try:
            transaction = session.query(Transaction).filter(
                Transaction.id == transaction_id
            ).first()
            if transaction and transaction.status == "pending":
                transaction.status = "failed"
                transaction.admin_notes = reason
                transaction.processed_at = datetime.utcnow()
                session.commit()
        finally:
            session.close()

    # ─── سيريتل كاش — تحويل يدوي + تحقق أوتو ─────────────────

    @staticmethod
    async def start_syriatel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """قائمة شحن سيريتل — تحويل يدوي (AUTO) فقط"""
        from pathlib import Path
        from telegram import InputFile

        user = db.get_user(update.effective_user.id)
        has_prev = bool(getattr(user, "last_syriatel_code", None))
        caption = "شحن البوت - سيرياتيل كاش"
        assets = Path(__file__).resolve().parent / "assets"
        logo = assets / "syriatel_logo.png"
        chat_id = update.effective_chat.id

        if logo.exists():
            try:
                if update.callback_query and update.callback_query.message:
                    await update.callback_query.message.delete()
            except TelegramError:
                pass
            with open(logo, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(photo, filename="syriatel_logo.png"),
                    caption=caption,
                    reply_markup=Keyboards.syriatel_deposit_menu(has_prev),
                )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                caption,
                reply_markup=Keyboards.syriatel_deposit_menu(has_prev),
            )
        else:
            await update.message.reply_text(
                caption,
                reply_markup=Keyboards.syriatel_deposit_menu(has_prev),
            )

    @staticmethod
    async def start_syriatel_manual_intro(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """مقدمة التحويل اليدوي + صورة الشرح"""
        from pathlib import Path
        from telegram import InputFile

        text = (
            "شحن سيرياتيل كاش - تحويل يدوي\n\n"
            "هذه العملية تحويل يدوي.\n"
            "أي عملية وهمية أو أقل من الحد الأدنى لن تُقبل ولن تُعوَّض.\n\n"
            "الخطوات:\n"
            "1) أدخل المبلغ المراد شحنه على البوت\n"
            "2) اختر أحد أكواد التحويل وحوّل إليه من تطبيق سيريتل\n"
            "3) أرسل رقم عملية التحويل (12 رقم) للتحقق التلقائي"
        )
        assets = Path(__file__).resolve().parent / "assets"
        guide = assets / "syriatel_guide.png"
        chat_id = update.effective_chat.id

        try:
            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.delete()
        except TelegramError:
            pass

        if guide.exists():
            with open(guide, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(photo, filename="syriatel_guide.png"),
                    caption=text,
                    reply_markup=Keyboards.syriatel_continue(),
                )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=Keyboards.syriatel_continue(),
            )

    @staticmethod
    async def start_syriatel_amount(
        update: Update, context: ContextTypes.DEFAULT_TYPE, use_previous: bool = False
    ):
        """الخطوة 1: إدخال المبلغ"""
        codes = Config.get_syriatel_codes()
        if not codes:
            msg = "❌ لم تُضبط أكواد سيريتل. أضف APISYRIA_SYRIATEL_CODES في .env"
            if update.callback_query:
                await update.callback_query.edit_message_text(msg, reply_markup=Keyboards.main_menu())
            return

        if use_previous:
            user = db.get_user(update.effective_user.id)
            prev = getattr(user, "last_syriatel_code", None)
            if not prev or prev not in codes:
                await update.callback_query.edit_message_text(
                    "❌ لا يوجد رقم تاجر سابق محفوظ.",
                    reply_markup=Keyboards.syriatel_deposit_menu(False),
                )
                return
            context.user_data["syriatel_force_code"] = prev

        min_a = Config.SYRIATEL_DEPOSIT["min_amount"]
        text = (
            "شحن سيرياتيل كاش - شحن يدوي\n\n"
            "الخطوة الأولى: الرجاء إدخال المبلغ المراد شحنه على البوت\n\n"
            f"💰 الحد الأدنى: {format_currency(min_a)}"
        )
        context.user_data["state"] = "waiting_for_syriatel_amount"
        context.user_data["operation"] = "syriatel_deposit"
        context.user_data["method"] = "syriatel_cash"
        context.user_data["deposit_started_at"] = datetime.utcnow().isoformat()

        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text, reply_markup=Keyboards.cancel_operation()
                )
            except TelegramError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    reply_markup=Keyboards.cancel_operation(),
                )
        else:
            await update.message.reply_text(text, reply_markup=Keyboards.cancel_operation())

    @staticmethod
    async def handle_syriatel_amount(
        update: Update, context: ContextTypes.DEFAULT_TYPE, amount_text: str
    ):
        """الخطوة 2: اختيار الكود"""
        min_a = Config.SYRIATEL_DEPOSIT["min_amount"]
        try:
            amount = float(str(amount_text).replace(",", "").strip())
        except ValueError:
            await update.message.reply_text(
                "❌ المبلغ غير صحيح.",
                reply_markup=Keyboards.cancel_operation(),
            )
            return

        if amount < min_a:
            await update.message.reply_text(
                f"❌ الحد الأدنى هو {format_currency(min_a)}",
                reply_markup=Keyboards.cancel_operation(),
            )
            return

        context.user_data["amount"] = amount
        force_code = context.user_data.pop("syriatel_force_code", None)
        if force_code:
            await PaymentHandler._syriatel_ask_tx(update, context, force_code, amount)
            return

        codes = Config.get_syriatel_codes()
        timeout = Config.SYRIATEL_DEPOSIT["timeout_minutes"]
        lines = "\n".join(codes)
        text = (
            "شحن سيرياتيل كاش - شحن يدوي\n\n"
            "الخطوة الثانية: قم باختيار أحد الأكواد التالية:\n"
            f"{lines}\n\n"
            f"ثم قم بدفع المبلغ ({format_currency(amount)}) وبعدها اضغط على الكود الذي دفعت إليه\n\n"
            f"ملاحظة 1: مدة طلب الشحن هي {timeout} دقائق فقط\n"
            "ملاحظة 2: تم اختيار أكثر من رقم لتفادي تجاوز الحد اليومي"
        )
        context.user_data["state"] = "waiting_for_syriatel_code"
        await update.message.reply_text(
            text,
            reply_markup=Keyboards.syriatel_codes_keyboard(codes),
        )

    @staticmethod
    async def pick_syriatel_code(
        update: Update, context: ContextTypes.DEFAULT_TYPE, code: str
    ):
        amount = context.user_data.get("amount")
        if not amount:
            await update.callback_query.edit_message_text(
                "❌ انتهت الجلسة. ابدأ من جديد.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        timeout = Config.SYRIATEL_DEPOSIT["timeout_minutes"]
        started = context.user_data.get("deposit_started_at")
        if started:
            from datetime import timedelta
            try:
                if datetime.utcnow() - datetime.fromisoformat(started) > timedelta(minutes=timeout):
                    context.user_data.clear()
                    await update.callback_query.edit_message_text(
                        f"⏰ انتهى الوقت ({timeout} دقائق). أنشئ طلباً جديداً.",
                        reply_markup=Keyboards.start_menu(),
                    )
                    return
            except ValueError:
                pass

        await PaymentHandler._syriatel_ask_tx(update, context, code, amount)

    @staticmethod
    async def _syriatel_ask_tx(update, context, code: str, amount: float):
        context.user_data["syriatel_code"] = code
        context.user_data["state"] = "waiting_for_syriatel_tx"
        digits = Config.SYRIATEL_DEPOSIT["tx_digits"]
        text = (
            "شحن سيرياتيل كاش - شحن يدوي\n\n"
            f"الكود المختار: `{code}`\n"
            f"المبلغ: {format_currency(amount)}\n\n"
            f"الخطوة الثالثة: الرجاء إدخال رقم العملية "
            f"(مثال: `600987123674` — {digits} رقماً)."
        )

        # حفظ آخر كود
        session = db.get_session()
        try:
            user = session.query(User).filter(
                User.telegram_id == str(update.effective_user.id)
            ).first()
            if user:
                user.last_syriatel_code = code
                session.commit()
        finally:
            session.close()

        if update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=Keyboards.cancel_operation(),
            )
        else:
            await update.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=Keyboards.cancel_operation(),
            )

    @staticmethod
    async def handle_syriatel_tx(
        update: Update, context: ContextTypes.DEFAULT_TYPE, tx_raw: str
    ):
        """تحقق أوتو من رقم العملية عبر API SYRIA"""
        from datetime import timedelta

        amount = context.user_data.get("amount")
        code = context.user_data.get("syriatel_code")
        digits = Config.SYRIATEL_DEPOSIT["tx_digits"]
        timeout = Config.SYRIATEL_DEPOSIT["timeout_minutes"]

        if not amount or not code:
            context.user_data.clear()
            await update.message.reply_text(
                "❌ انتهت الجلسة. ابدأ من جديد.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        started = context.user_data.get("deposit_started_at")
        if started:
            try:
                if datetime.utcnow() - datetime.fromisoformat(started) > timedelta(minutes=timeout):
                    context.user_data.clear()
                    await update.message.reply_text(
                        f"⏰ انتهى الوقت ({timeout} دقائق). أنشئ طلباً جديداً.",
                        reply_markup=Keyboards.start_menu(),
                    )
                    return
            except ValueError:
                pass

        tx_number = ApiSyriaClient.normalize_tx_id(tx_raw)
        if len(tx_number) != digits:
            await update.message.reply_text(
                f"🚫 رقم عملية غير صالح. الرجاء إدخال رقم مكون من {digits} رقماً "
                f"(مثال: 600209081068).",
                reply_markup=Keyboards.cancel_operation(),
            )
            return

        if db.is_external_transaction_used(tx_number, "syriatel_cash"):
            context.user_data.clear()
            await update.message.reply_text(
                "❌ رقم العملية مستخدم مسبقاً.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        wait = await update.message.reply_text("⏳ لحظات من فضلك...")
        user = db.get_user(update.effective_user.id)

        session = db.get_session()
        try:
            transaction = Transaction(
                user_id=user.id,
                transaction_type="deposit",
                amount=amount,
                method="syriatel_cash",
                status="pending",
                external_transaction_id=tx_number,
                description=(
                    f"إيداع سيريتل تحويل يدوي (AUTO) — كود {code} — TX {tx_number}"
                ),
            )
            session.add(transaction)
            session.commit()
            session.refresh(transaction)
            transaction_id = transaction.id
            request_created_at = transaction.created_at
        finally:
            session.close()

        try:
            result = await asyncio.to_thread(
                api_client.syriatel_find_transaction, tx_number, code
            )
            data = result.get("data", {})
            if not data.get("found"):
                PaymentHandler._fail_pending_deposit(
                    transaction_id, "رقم عملية غير موجود"
                )
                context.user_data.clear()
                try:
                    await wait.delete()
                except TelegramError:
                    pass
                await update.message.reply_text(
                    "❌ تم رفض طلب الشحن. السبب: رقم عملية غير موجود",
                    reply_markup=Keyboards.start_menu(),
                )
                return

            tx_data = data.get("transaction", {})
            actual_amount = ApiSyriaClient.parse_syriatel_amount(tx_data)
            external_id = str(tx_data.get("transaction_no", tx_number))

            if not api_client.is_within_deposit_window(
                tx_data, request_created_at, timeout
            ):
                PaymentHandler._fail_pending_deposit(
                    transaction_id, f"خارج مهلة {timeout} د"
                )
                context.user_data.clear()
                await update.message.reply_text(
                    f"⏰ العملية خارج المهلة المسموحة ({timeout} دقائق).",
                    reply_markup=Keyboards.start_menu(),
                )
                return

            if not ApiSyriaClient.amounts_match(float(amount), actual_amount):
                PaymentHandler._fail_pending_deposit(
                    transaction_id,
                    f"مبلغ غير مطابق: {amount} / {actual_amount}",
                )
                context.user_data.clear()
                await update.message.reply_text(
                    f"❌ تم رفض طلب الشحن. السبب: المبلغ غير مطابق.\n"
                    f"المطلوب: {format_currency(amount)}\n"
                    f"في العملية: {format_currency(actual_amount)}",
                    reply_markup=Keyboards.start_menu(),
                )
                return

            if db.is_external_transaction_used(external_id, "syriatel_cash"):
                PaymentHandler._fail_pending_deposit(transaction_id, "مكرر")
                context.user_data.clear()
                await update.message.reply_text(
                    "❌ هذه العملية مُسجّلة مسبقاً.",
                    reply_markup=Keyboards.main_menu(),
                )
                return

            session = db.get_session()
            try:
                transaction = session.query(Transaction).filter(
                    Transaction.id == transaction_id
                ).first()
                if transaction:
                    transaction.external_transaction_id = external_id
                    transaction.description += f"\nتحقق تلقائي — {external_id}"
                    session.commit()
            finally:
                session.close()

            context.user_data.clear()
            try:
                await wait.delete()
            except TelegramError:
                pass
            await PaymentHandler.complete_deposit(transaction_id, update, context)

        except ApiSyriaError as exc:
            PaymentHandler._fail_pending_deposit(transaction_id, exc.message)
            context.user_data.clear()
            await update.message.reply_text(
                f"❌ تم رفض طلب الشحن. السبب: {exc.message}",
                reply_markup=Keyboards.start_menu(),
            )
        except Exception as exc:
            logger.exception("Syriatel auto verify failed")
            PaymentHandler._fail_pending_deposit(transaction_id, str(exc))
            context.user_data.clear()
            await update.message.reply_text(
                f"❌ حدث خطأ أثناء التحقق.\n{exc}",
                reply_markup=Keyboards.start_menu(),
            )

    @staticmethod
    async def process_deposit_request(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float, method: str):
        """معالجة طلب الإيداع"""
        user = db.get_user(update.effective_user.id)

        is_valid, validated_amount, error_msg = validate_amount(
            str(amount),
            Config.MIN_DEPOSIT,
            Config.MAX_DEPOSIT
        )

        if not is_valid:
            await update.message.reply_text(error_msg, reply_markup=Keyboards.main_menu())
            return

        if PaymentHandler._is_auto_deposit(method):
            if not PaymentHandler._api_ready(method):
                await update.message.reply_text(
                    "❌ خدمة الدفع التلقائي غير مُعدّة حالياً.\n"
                    "يرجى التواصل مع الإدارة أو استخدام طريقة دفع أخرى.",
                    reply_markup=Keyboards.main_menu()
                )
                return
            if PaymentHandler._get_provider(method) == "tron":
                await PaymentHandler.start_usdt_deposit(update, context, user, validated_amount)
            else:
                await PaymentHandler.start_auto_deposit(update, context, user, validated_amount, method)
            return

        session = db.get_session()
        try:
            transaction = Transaction(
                user_id=user.id,
                transaction_type="deposit",
                amount=validated_amount,
                method=method,
                status="pending",
                description=f"طلب إيداع عبر {Config.PAYMENT_METHODS[method]['name']}"
            )
            session.add(transaction)
            session.commit()
            session.refresh(transaction)
            await PaymentHandler.process_manual_deposit(transaction, update, context)
        finally:
            session.close()

    @staticmethod
    async def start_usdt_deposit(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user: User,
        syp_amount: float,
    ):
        """بدء إيداع USDT TRC20 بمبلغ فريد عشري"""
        session = db.get_session()
        try:
            transaction = Transaction(
                user_id=user.id,
                transaction_type="deposit",
                amount=syp_amount,
                method="usdt",
                status="pending",
                description="إيداع USDT TRC20 تلقائي",
            )
            session.add(transaction)
            session.commit()
            session.refresh(transaction)

            used_amounts = db.get_used_usdt_amounts()
            try:
                unique_usdt = tron_client.generate_unique_usdt_amount(
                    syp_amount, used_amounts, transaction.id
                )
            except TronUsdtError as exc:
                transaction.status = "cancelled"
                transaction.admin_notes = str(exc.message)
                session.commit()
                await update.message.reply_text(
                    f"❌ {exc.message}",
                    reply_markup=Keyboards.main_menu(),
                )
                return

            transaction.expected_usdt_amount = unique_usdt
            transaction.description += (
                f"\nمبلغ USDT الفريد: {TronUsdtClient.format_usdt(unique_usdt)}"
            )
            session.commit()

            wallet = Config.USDT_CONFIG["wallet_address"]
            timeout = Config.USDT_CONFIG["deposit_timeout_minutes"]
            rate = Config.get_usdt_syp_rate()
            usdt_display = TronUsdtClient.format_usdt(unique_usdt)

            message = f"""
✅ تم إنشاء طلب إيداع USDT

💵 المبلغ بالليرة: {format_currency(syp_amount)}
💱 سعر الصرف: {format_currency(rate)} ل.س = 1 USDT

⚠️ **مهم جداً — حوّل المبلغ بالضبط:**
💰 `{usdt_display}` USDT

❗ لا تقرب ولا تقرب المبلغ — الفواصل العشرية فريدة لحسابك
❗ إذا حوّلت مبلغاً مختلفاً لن يُقبل الإيداع تلقائياً

📋 تفاصيل التحويل:
• الشبكة: **TRC20** (TRON) فقط
• العملة: **USDT**
• العنوان:
`{wallet}`

⏰ صالح لمدة {timeout} دقيقة
🔄 البوت يراقب المحفظة تلقائياً ويضيف الرصيد فور وصول التحويل

🔢 رقم الطلب: {transaction.id}
            """

            context.user_data.clear()
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.main_menu(),
                parse_mode="Markdown",
            )
        finally:
            session.close()

    @staticmethod
    async def poll_usdt_deposits(context: ContextTypes.DEFAULT_TYPE):
        """مراقبة دورية لطلبات USDT المعلقة"""
        if not tron_client.is_configured():
            return

        pending = db.get_pending_usdt_deposits()
        if not pending:
            return

        used_hashes = db.get_used_blockchain_tx_hashes()

        for transaction in pending:
            try:
                if tron_client.is_deposit_expired(transaction.created_at):
                    await PaymentHandler._expire_usdt_deposit(transaction.id, context)
                    continue

                match = await asyncio.to_thread(
                    tron_client.find_matching_transfer,
                    transaction.expected_usdt_amount,
                    transaction.created_at,
                    used_hashes,
                )

                if not match:
                    continue

                tx_hash = match["transaction_id"]
                if db.is_external_transaction_used(tx_hash, "usdt"):
                    continue

                session = db.get_session()
                try:
                    tx = session.query(Transaction).filter(
                        Transaction.id == transaction.id,
                        Transaction.status == "pending",
                    ).first()
                    if not tx:
                        continue

                    tx.external_transaction_id = tx_hash
                    tx.description += (
                        f"\nTxHash: {tx_hash}\n"
                        f"من: {match.get('from', '')}"
                    )
                    session.commit()
                finally:
                    session.close()

                used_hashes.add(tx_hash)
                await PaymentHandler.complete_deposit(transaction.id, context)

            except Exception as exc:
                logger.exception(
                    "USDT poll error for transaction %s: %s",
                    transaction.id,
                    exc,
                )

    @staticmethod
    async def _expire_usdt_deposit(transaction_id: int, context: ContextTypes.DEFAULT_TYPE):
        """إلغاء طلب USDT منتهي الصلاحية"""
        session = db.get_session()
        try:
            transaction = session.query(Transaction).filter(
                Transaction.id == transaction_id,
                Transaction.status == "pending",
            ).first()
            if not transaction:
                return

            user = session.query(User).filter(User.id == transaction.user_id).first()
            transaction.status = "cancelled"
            transaction.admin_notes = "انتهت صلاحية طلب الإيداع"
            transaction.processed_at = datetime.utcnow()
            session.commit()

            if user:
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=(
                            f"⏰ انتهت صلاحية طلب إيداع USDT رقم {transaction_id}\n"
                            f"💰 المبلغ المطلوب كان: "
                            f"{TronUsdtClient.format_usdt(transaction.expected_usdt_amount)} USDT\n"
                            "يمكنك إنشاء طلب جديد من القائمة."
                        ),
                        reply_markup=Keyboards.main_menu(),
                    )
                except TelegramError:
                    logger.warning("Cannot notify user %s about USDT expiry", user.telegram_id)
        finally:
            session.close()

    @staticmethod
    async def start_auto_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, amount: float, method: str):
        """بدء إيداع تلقائي - مهلة 15 دقيقة للتحويل"""
        timeout = Config.APISYRIA_CONFIG.get("deposit_timeout_minutes", 15)
        session = db.get_session()
        try:
            transaction = Transaction(
                user_id=user.id,
                transaction_type="deposit",
                amount=amount,
                method=method,
                status="pending",
                description=f"إيداع تلقائي عبر {Config.PAYMENT_METHODS[method]['name']}"
            )
            session.add(transaction)
            session.commit()
            session.refresh(transaction)

            method_info = Config.PAYMENT_METHODS[method]
            instructions = PaymentHandler.get_payment_instructions(method, amount)

            message = f"""
✅ تم تسجيل طلب الإيداع

💰 المبلغ: {format_currency(amount)}
🏦 الطريقة: {method_info['name']} {method_info['emoji']}
🔢 رقم الطلب: {transaction.id}

{instructions}

⏰ **المؤقت: {timeout} دقيقة فقط**
حوّل المبلغ وأرسل رقم العملية خلال هذه المدة.
بعد انتهاء الوقت يُلغى الطلب تلقائياً.

🔍 بعد التحويل أرسل **رقم العملية** من التطبيق للتحقق الفوري.
            """

            context.user_data["state"] = "waiting_for_tx_number"
            context.user_data["operation"] = "deposit_verify"
            context.user_data["method"] = method
            context.user_data["transaction_id"] = transaction.id
            context.user_data["amount"] = amount
            context.user_data["deposit_started_at"] = datetime.utcnow().isoformat()

            await update.message.reply_text(message, reply_markup=Keyboards.cancel_operation())
        finally:
            session.close()

    @staticmethod
    async def verify_auto_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE, tx_number: str):
        """التحقق التلقائي — عمليات آخر 15 دقيقة فقط"""
        from datetime import timedelta

        method = context.user_data.get("method")
        transaction_id = context.user_data.get("transaction_id")
        expected_amount = context.user_data.get("amount")
        timeout = Config.APISYRIA_CONFIG.get("deposit_timeout_minutes", 15)

        if not method or not transaction_id:
            context.user_data.clear()
            await update.message.reply_text(
                "❌ انتهت جلسة العملية. ابدأ من جديد.",
                reply_markup=Keyboards.main_menu()
            )
            return

        # التحقق من انتهاء مهلة الطلب
        session = db.get_session()
        try:
            pending_tx = session.query(Transaction).filter(
                Transaction.id == transaction_id
            ).first()
            if not pending_tx or pending_tx.status != "pending":
                context.user_data.clear()
                await update.message.reply_text(
                    "❌ طلب الإيداع غير صالح أو تمت معالجته.",
                    reply_markup=Keyboards.main_menu(),
                )
                return

            created_at = pending_tx.created_at
            if created_at and datetime.utcnow() - created_at > timedelta(minutes=timeout):
                pending_tx.status = "cancelled"
                pending_tx.admin_notes = f"انتهت مهلة التحويل ({timeout} دقيقة)"
                pending_tx.processed_at = datetime.utcnow()
                session.commit()
                context.user_data.clear()
                await update.message.reply_text(
                    f"⏰ انتهى الوقت!\n"
                    f"كان لديك {timeout} دقيقة للتحويل.\n"
                    f"أنشئ طلب شحن جديد وحاول مرة أخرى.",
                    reply_markup=Keyboards.start_menu(),
                )
                return
        finally:
            session.close()

        tx_number = ApiSyriaClient.normalize_tx_id(tx_number)
        if len(tx_number) < 3:
            await update.message.reply_text(
                "❌ رقم العملية غير صحيح. أرسل الرقم كما يظهر في التطبيق (أرقام فقط).",
                reply_markup=Keyboards.cancel_operation()
            )
            return

        if db.is_external_transaction_used(tx_number, method):
            await update.message.reply_text(
                "❌ رقم العملية مستخدم مسبقاً ولا يمكن استخدامه مرة أخرى.",
                reply_markup=Keyboards.main_menu()
            )
            context.user_data.clear()
            return

        await update.message.reply_text("⏳ جاري التحقق من العملية (آخر 15 دقيقة)...")

        try:
            session = db.get_session()
            try:
                pending_tx = session.query(Transaction).filter(
                    Transaction.id == transaction_id
                ).first()
                request_created_at = pending_tx.created_at if pending_tx else None
            finally:
                session.close()

            if method == "syriatel_cash":
                result = await asyncio.to_thread(api_client.syriatel_find_transaction, tx_number)
                data = result.get("data", {})
                if not data.get("found"):
                    await update.message.reply_text(
                        f"❌ لم يتم العثور على العملية خلال آخر {timeout} دقيقة.\n"
                        "تأكد من رقم العملية وأن التحويل تم الآن.",
                        reply_markup=Keyboards.cancel_operation()
                    )
                    return
                tx_data = data.get("transaction", {})
                actual_amount = ApiSyriaClient.parse_syriatel_amount(tx_data)
                external_id = tx_data.get("transaction_no", tx_number)
            elif method == "shamcash":
                result = await asyncio.to_thread(api_client.shamcash_find_transaction, tx_number)
                data = result.get("data", {})
                if not data.get("found"):
                    await update.message.reply_text(
                        f"❌ لم يتم العثور على العملية خلال آخر {timeout} دقيقة.\n"
                        "تأكد من رقم العملية وأن التحويل تم لحسابنا الآن.",
                        reply_markup=Keyboards.cancel_operation()
                    )
                    return
                tx_data = data.get("transaction", {})
                actual_amount = ApiSyriaClient.parse_shamcash_amount(tx_data)
                external_id = str(tx_data.get("tran_id", tx_number))
            else:
                await update.message.reply_text("❌ طريقة دفع غير مدعومة", reply_markup=Keyboards.main_menu())
                context.user_data.clear()
                return

            # قبول العمليات ضمن نافذة ربع الساعة فقط
            if not api_client.is_within_deposit_window(tx_data, request_created_at, timeout):
                await update.message.reply_text(
                    f"⏰ العملية خارج المهلة المسموحة ({timeout} دقيقة).\n"
                    f"يجب أن يكون التحويل خلال {timeout} دقيقة من فتح طلب الشحن.\n"
                    "أنشئ طلباً جديداً وحوّل فوراً.",
                    reply_markup=Keyboards.start_menu(),
                )
                context.user_data.clear()
                return

            if not ApiSyriaClient.amounts_match(expected_amount, actual_amount):
                await update.message.reply_text(
                    f"❌ المبلغ غير مطابق.\n"
                    f"المبلغ المطلوب: {format_currency(expected_amount)}\n"
                    f"مبلغ العملية: {format_currency(actual_amount)}\n\n"
                    f"أعد المحاولة برقم عملية صحيح أو أنشئ طلباً جديداً بالمبلغ الصحيح.",
                    reply_markup=Keyboards.cancel_operation()
                )
                return

            if db.is_external_transaction_used(external_id, method):
                await update.message.reply_text(
                    "❌ هذه العملية مُسجّلة مسبقاً في النظام.",
                    reply_markup=Keyboards.main_menu()
                )
                context.user_data.clear()
                return

            session = db.get_session()
            try:
                transaction = session.query(Transaction).filter(Transaction.id == transaction_id).first()
                if not transaction or transaction.status != "pending":
                    await update.message.reply_text(
                        "❌ طلب الإيداع غير صالح أو تمت معالجته مسبقاً.",
                        reply_markup=Keyboards.main_menu()
                    )
                    context.user_data.clear()
                    return

                transaction.external_transaction_id = external_id
                transaction.description += f"\nتحقق تلقائي (نافذة {timeout} د) - رقم العملية: {external_id}"
                session.commit()
            finally:
                session.close()

            context.user_data.clear()
            await PaymentHandler.complete_deposit(transaction_id, update, context)

        except ApiSyriaError as exc:
            logger.error("ApiSyria deposit verification failed: %s", exc.message)
            await update.message.reply_text(
                f"❌ فشل التحقق: {exc.message}",
                reply_markup=Keyboards.cancel_operation()
            )
        except Exception as exc:
            logger.exception("Unexpected deposit verification error")
            await update.message.reply_text(
                f"❌ حدث خطأ أثناء التحقق. حاول لاحقاً.\n{exc}",
                reply_markup=Keyboards.cancel_operation()
            )

    @staticmethod
    async def process_withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float, method: str):
        """معالجة طلب السحب إلى الواقع — يدوي بموافقة الإدمن فقط"""
        user = db.get_user(update.effective_user.id)

        is_valid, validated_amount, error_msg = validate_amount(
            str(amount),
            Config.MIN_WITHDRAWAL,
            min(Config.MAX_WITHDRAWAL, user.balance)
        )

        if not is_valid:
            await update.message.reply_text(error_msg, reply_markup=Keyboards.main_menu())
            return

        if user.balance < validated_amount:
            await update.message.reply_text(
                f"❌ رصيدك غير كافي\n💵 رصيدك الحالي: {format_currency(user.balance)}",
                reply_markup=Keyboards.main_menu()
            )
            return

        method_info = Config.PAYMENT_METHODS[method]
        if method == "syriatel_cash":
            dest_prompt = "📱 اختر رقم سيريتل كاش المحفوظ أو أدخل رقماً جديداً:"
        elif method == "shamcash":
            dest_prompt = "💳 اختر حساب شام كاش المحفوظ أو أدخل حساباً جديداً:"
        elif method == "usdt":
            dest_prompt = "💰 أرسل **عنوان محفظة USDT (TRC20)** لاستلام المبلغ:"
        else:
            dest_prompt = "📝 أرسل **بيانات الاستلام** (رقم أو عنوان):"

        message = f"""
✅ تم تسجيل طلب السحب

💸 المبلغ: {format_currency(validated_amount)}
🏦 الطريقة: {method_info['name']} {method_info['emoji']}

⏳ **يتطلب موافقة الإدمن** — سيتم تحويل المبلغ يدوياً بعد المراجعة

{dest_prompt}
        """

        context.user_data["state"] = "waiting_for_withdraw_destination"
        context.user_data["operation"] = "withdraw_manual"
        context.user_data["method"] = method
        context.user_data["amount"] = validated_amount

        # سيريتل / شام كاش: عرض الحسابات المحفوظة إن وُجدت
        if method in ("syriatel_cash", "shamcash"):
            accounts = db.get_saved_accounts(user.id, method)
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.withdraw_destination_choices(accounts, method),
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.cancel_operation(),
                parse_mode="Markdown",
            )

    @staticmethod
    async def execute_manual_withdraw(
        update: Update, context: ContextTypes.DEFAULT_TYPE, destination: str
    ):
        """تسجيل سحب للواقع وانتظار موافقة الإدمن"""
        method = context.user_data.get("method")
        amount = context.user_data.get("amount")
        operation = context.user_data.get("operation")

        async def reply(text, **kwargs):
            target = update.effective_message
            await target.reply_text(text, **kwargs)

        if operation != "withdraw_manual" or not method or not amount:
            context.user_data.clear()
            await reply(
                "❌ انتهت جلسة العملية. ابدأ من جديد.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        destination = destination.strip()
        if len(destination) < 5:
            await reply(
                "❌ بيانات الاستلام غير صحيحة. حاول مرة أخرى.",
                reply_markup=Keyboards.cancel_operation(),
            )
            return

        from accounts_handler import SavedAccountsHandler

        save_note = ""
        if method in ("syriatel_cash", "shamcash"):
            normalized, err = SavedAccountsHandler.validate_account(method, destination)
            if err:
                await reply(
                    err,
                    reply_markup=Keyboards.cancel_operation(),
                    parse_mode="Markdown",
                )
                return
            destination = normalized
            user = db.get_user(update.effective_user.id)
            _, add_err = db.add_saved_account(
                user.id,
                method,
                destination,
                max_per_type=Config.max_saved_accounts(method),
            )
            if not add_err:
                save_note = "\n💾 تم حفظ الرقم/الحساب لاستخدامه لاحقاً."
            elif add_err and "مسبقاً" not in add_err:
                save_note = f"\nℹ️ {add_err}"

        user = db.get_user(update.effective_user.id)
        method_info = Config.PAYMENT_METHODS[method]
        reference = generate_transaction_reference()

        session = db.get_session()
        try:
            db_user = session.query(User).filter(User.id == user.id).first()
            if db_user.balance < amount:
                await reply(
                    "❌ رصيدك غير كافي",
                    reply_markup=Keyboards.main_menu(),
                )
                context.user_data.clear()
                return

            transaction = Transaction(
                user_id=user.id,
                transaction_type="withdraw",
                amount=amount,
                method=method,
                status="pending",
                withdraw_destination=destination,
                description=(
                    f"سحب إلى واقع - {method_info['name']}\n"
                    f"وجهة الاستلام: {destination}\n"
                    f"مرجع: {reference}"
                ),
            )
            session.add(transaction)
            db_user.balance -= amount
            session.commit()
            session.refresh(transaction)

            context.user_data.clear()

            await reply(
                f"""
✅ تم إرسال طلب السحب للإدارة

💸 المبلغ: {format_currency(amount)}
🏦 الطريقة: {method_info['name']} {method_info['emoji']}
📍 الوجهة: `{destination}`
🔢 رقم الطلب: {transaction.id}
⏳ الحالة: **بانتظار موافقة الإدمن**
{save_note}

💵 تم خصم المبلغ مؤقتاً من رصيدك
⏰ سيتم التحويل خلال 24 ساعة بعد الموافقة
                """,
                reply_markup=Keyboards.main_menu(),
                parse_mode="Markdown",
            )

            await PaymentHandler.notify_admin_withdrawal(
                transaction, reference, context, destination
            )

        finally:
            session.close()

    @staticmethod
    async def start_auto_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, amount: float, method: str):
        """بدء سحب تلقائي - خصم الرصيد وانتظار بيانات المستفيد"""
        session = db.get_session()
        try:
            db_user = session.query(User).filter(User.id == user.id).first()
            if db_user.balance < amount:
                await update.message.reply_text(
                    "❌ رصيدك غير كافي",
                    reply_markup=Keyboards.main_menu()
                )
                return

            transaction = Transaction(
                user_id=user.id,
                transaction_type="withdraw",
                amount=amount,
                method=method,
                status="pending",
                description=f"سحب تلقائي عبر {Config.PAYMENT_METHODS[method]['name']}"
            )
            session.add(transaction)
            db_user.balance -= amount
            session.commit()
            session.refresh(transaction)

            method_info = Config.PAYMENT_METHODS[method]
            if method == "syriatel_cash":
                dest_prompt = "📱 أرسل **رقم سيريتل كاش** للمستفيد (مثال: 0999123456):"
            else:
                dest_prompt = "💳 أرسل **عنوان حساب شام كاش** للمستفيد:"

            message = f"""
✅ تم تسجيل طلب السحب

💸 المبلغ: {format_currency(amount)}
🏦 الطريقة: {method_info['name']} {method_info['emoji']}
🔢 رقم الطلب: {transaction.id}

💵 تم خصم المبلغ مؤقتاً من رصيدك

{dest_prompt}
            """

            context.user_data["state"] = "waiting_for_withdraw_destination"
            context.user_data["operation"] = "withdraw_auto"
            context.user_data["method"] = method
            context.user_data["transaction_id"] = transaction.id
            context.user_data["amount"] = amount

            await update.message.reply_text(message, reply_markup=Keyboards.cancel_operation())
        finally:
            session.close()

    @staticmethod
    async def execute_auto_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE, destination: str):
        """تنفيذ السحب التلقائي عبر API SYRIA"""
        method = context.user_data.get("method")
        transaction_id = context.user_data.get("transaction_id")
        amount = context.user_data.get("amount")

        if not method or not transaction_id or not amount:
            context.user_data.clear()
            await update.message.reply_text(
                "❌ انتهت جلسة العملية. ابدأ من جديد.",
                reply_markup=Keyboards.main_menu()
            )
            return

        destination = destination.strip()
        await update.message.reply_text("⏳ جاري تنفيذ التحويل...")

        try:
            if method == "syriatel_cash":
                result = await asyncio.to_thread(
                    api_client.syriatel_transfer,
                    destination,
                    amount,
                )
                transfer_data = result.get("data", {})
                external_id = transfer_data.get("billcode") or f"SYR_{transaction_id}"
            elif method == "shamcash":
                result = await asyncio.to_thread(
                    api_client.shamcash_transfer,
                    destination,
                    amount,
                    note=f"سحب بوت - طلب {transaction_id}",
                )
                transfer_data = result.get("data", {})
                external_id = f"SHAM_{transaction_id}_{int(datetime.utcnow().timestamp())}"
            else:
                await PaymentHandler.reject_transaction(
                    transaction_id,
                    "طريقة سحب غير مدعومة",
                    context,
                )
                context.user_data.clear()
                return

            session = db.get_session()
            try:
                transaction = session.query(Transaction).filter(Transaction.id == transaction_id).first()
                if transaction:
                    transaction.external_transaction_id = external_id
                    transaction.description += f"\nتحويل تلقائي إلى: {destination}"
                    if transfer_data.get("message"):
                        transaction.description += f"\n{transfer_data['message']}"
                    session.commit()
            finally:
                session.close()

            context.user_data.clear()
            await PaymentHandler.complete_withdrawal(transaction_id, update, context)

        except ApiSyriaError as exc:
            logger.error("ApiSyria withdrawal failed: %s", exc.message)
            await PaymentHandler.reject_transaction(
                transaction_id,
                f"فشل التحويل: {exc.message}",
                context,
            )
            context.user_data.clear()
            await update.message.reply_text(
                f"❌ فشل السحب: {exc.message}\n💵 تم إرجاع المبلغ لرصيدك.",
                reply_markup=Keyboards.main_menu()
            )
        except Exception as exc:
            logger.exception("Unexpected withdrawal error")
            await PaymentHandler.reject_transaction(
                transaction_id,
                f"خطأ تقني: {exc}",
                context,
            )
            context.user_data.clear()
            await update.message.reply_text(
                "❌ حدث خطأ أثناء السحب. تم إرجاع المبلغ لرصيدك.",
                reply_markup=Keyboards.main_menu()
            )

    @staticmethod
    async def process_manual_deposit(transaction: Transaction, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالجة الإيداع اليدوي"""
        method_info = Config.PAYMENT_METHODS[transaction.method]
        reference = generate_transaction_reference()

        session = db.get_session()
        try:
            transaction.description += f"\nمرجع المعاملة: {reference}"
            session.commit()
        finally:
            session.close()

        user_message = f"""
✅ تم إنشاء طلب الإيداع بنجاح!

💰 المبلغ: {format_currency(transaction.amount)}
🏦 الطريقة: {method_info['name']} {method_info['emoji']}
🔢 مرجع المعاملة: {reference}
⏳ الحالة: قيد المراجعة

📝 تعليمات الدفع:
{PaymentHandler.get_payment_instructions(transaction.method, transaction.amount)}

⏰ سيتم مراجعة طلبك خلال 24 ساعة وإضافة الرصيد لحسابك بعد التأكيد.
        """

        await update.message.reply_text(user_message, reply_markup=Keyboards.main_menu())
        await PaymentHandler.notify_admin_deposit(transaction, reference, context)

    @staticmethod
    async def process_manual_withdrawal(transaction: Transaction, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالجة السحب اليدوي"""
        method_info = Config.PAYMENT_METHODS[transaction.method]
        reference = generate_transaction_reference()

        session = db.get_session()
        try:
            transaction.description += f"\nمرجع المعاملة: {reference}"
            session.commit()
        finally:
            session.close()

        user_message = f"""
✅ تم إنشاء طلب السحب بنجاح!

💸 المبلغ: {format_currency(transaction.amount)}
🏦 الطريقة: {method_info['name']} {method_info['emoji']}
🔢 مرجع المعاملة: {reference}
⏳ الحالة: قيد المراجعة

💵 تم خصم المبلغ مؤقتاً من رصيدك
⏰ سيتم تحويل المبلغ خلال 24 ساعة بعد المراجعة
        """

        await update.message.reply_text(user_message, reply_markup=Keyboards.main_menu())
        await PaymentHandler.notify_admin_withdrawal(transaction, reference, context)

    @staticmethod
    async def process_automatic_deposit(transaction: Transaction, method_config: Dict[str, Any]) -> bool:
        """معالجة الإيداع التلقائي (يُستخدم عبر verify_auto_deposit)"""
        return False

    @staticmethod
    async def process_automatic_withdrawal(transaction: Transaction, method_config: Dict[str, Any]) -> bool:
        """معالجة السحب التلقائي (يُستخدم عبر execute_auto_withdraw)"""
        return False

    @staticmethod
    async def complete_deposit(transaction_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إتمام عملية الإيداع"""
        session = db.get_session()
        try:
            transaction = session.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                return

            user = session.query(User).filter(User.id == transaction.user_id).first()
            if not user:
                return

            user.balance += transaction.amount
            transaction.status = "completed"
            transaction.processed_at = datetime.utcnow()

            if user.referred_by:
                await PaymentHandler.process_referral_earnings(user, transaction.amount, session)

            session.commit()

            has_ichancy = bool(user.ichancy_player_id)
            telegram_id = user.telegram_id
            credited = transaction.amount
            new_balance = user.balance

            try:
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=(
                        f"✅ تم التأكد من العملية\n"
                        f"تم قبول طلب الشحن آلياً.\n"
                        f"تم إضافة {format_currency(credited)} إلى رصيدك في البوت.\n"
                        f"💵 رصيدك الآن: {format_currency(new_balance)}"
                    ),
                    reply_markup=Keyboards.main_menu() if has_ichancy else Keyboards.ichancy_create_prompt(),
                )
                if not has_ichancy:
                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text=(
                            "2️⃣ الخطوة الثانية\n"
                            "بعد إتمام الشحن، يجب عليك إنشاء حساب."
                        ),
                        reply_markup=Keyboards.ichancy_create_prompt(),
                    )
            except TelegramError:
                logger.warning(f"لا يمكن إرسال إشعار للمستخدم {telegram_id}")

        finally:
            session.close()

    @staticmethod
    async def complete_withdrawal(transaction_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إتمام عملية السحب"""
        session = db.get_session()
        try:
            transaction = session.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                return

            user = session.query(User).filter(User.id == transaction.user_id).first()
            if not user:
                return

            transaction.status = "completed"
            transaction.processed_at = datetime.utcnow()
            session.commit()

            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"✅ تم إتمام عملية السحب بنجاح!\n"
                        f"💸 المبلغ: {format_currency(transaction.amount)}\n"
                        f"💵 رصيدك الحالي: {format_currency(user.balance)}"
                    ),
                    reply_markup=Keyboards.main_menu()
                )
            except TelegramError:
                logger.warning(f"لا يمكن إرسال إشعار للمستخدم {user.telegram_id}")

        finally:
            session.close()

    @staticmethod
    async def reject_transaction(transaction_id: int, reason: str, context: ContextTypes.DEFAULT_TYPE):
        """رفض المعاملة"""
        session = db.get_session()
        try:
            transaction = session.query(Transaction).filter(Transaction.id == transaction_id).first()
            if not transaction:
                return

            user = session.query(User).filter(User.id == transaction.user_id).first()
            if not user:
                return

            if transaction.transaction_type == "withdraw" and transaction.status == "pending":
                user.balance += transaction.amount

            transaction.status = "failed"
            transaction.admin_notes = reason
            transaction.processed_at = datetime.utcnow()
            session.commit()

            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"❌ تم رفض طلب {transaction.transaction_type}\n"
                        f"💰 المبلغ: {format_currency(transaction.amount)}\n"
                        f"📝 السبب: {reason}"
                    ),
                    reply_markup=Keyboards.main_menu()
                )
            except TelegramError:
                logger.warning(f"لا يمكن إرسال إشعار للمستخدم {user.telegram_id}")

        finally:
            session.close()

    @staticmethod
    async def process_referral_earnings(user: User, deposit_amount: float, session):
        """معالجة أرباح الإحالة"""
        if not user.referred_by:
            return

        # البحث عن المُحيل (آيدي تليجرام أو كود إحالة)
        referrer = session.query(User).filter(
            User.telegram_id == str(user.referred_by)
        ).first()
        if not referrer:
            referrer = session.query(User).filter(
                User.referral_code == user.referred_by
            ).first()
        if not referrer:
            return

        earnings = deposit_amount * (Config.REFERRAL_PERCENTAGE / 100)
        referrer.referral_earnings += earnings
        referrer.balance += earnings

        referral_transaction = Transaction(
            user_id=referrer.id,
            transaction_type="referral",
            amount=earnings,
            status="completed",
            description=f"أرباح إحالة من {get_user_display_name(user)} - إيداع {format_currency(deposit_amount)}"
        )
        session.add(referral_transaction)

    @staticmethod
    def get_payment_instructions(method: str, amount: float) -> str:
        """الحصول على تعليمات الدفع"""
        cfg = Config.APISYRIA_CONFIG

        if method == "syriatel_cash":
            gsm = cfg.get("syriatel_gsm") or "غير مُعدّ"
            return f"""
📱 سيريتل كاش:
• حوّل المبلغ {format_currency(amount)} إلى الرقم: {gsm}
• احفظ رقم العملية من التطبيق
• أرسل رقم العملية هنا للتحقق التلقائي
            """

        if method == "shamcash":
            account = cfg.get("shamcash_account") or "غير مُعدّ"
            currency = cfg.get("currency", "SYP")
            return f"""
💳 شام كاش:
• حوّل المبلغ {format_currency(amount)} {currency} إلى:
  {account}
• احفظ رقم العملية (tran_id) من التطبيق
• أرسل رقم العملية هنا للتحقق التلقائي
            """

        if method == "usdt":
            usdt_cfg = Config.USDT_CONFIG
            wallet = usdt_cfg.get("wallet_address") or "غير مُعدّ"
            rate = Config.get_usdt_syp_rate()
            approx = amount / rate
            return f"""
💰 USDT (TRC20):
• العنوان: {wallet}
• الشبكة: TRON (TRC20)
• تقريباً: {approx:.2f} USDT (سعر {format_currency(rate)} ل.س)
• سيُعطى مبلغ فريد بالضبط عند إنشاء الطلب
            """

        return "تعليمات الدفع غير متوفرة"

    @staticmethod
    async def notify_admin_deposit(transaction: Transaction, reference: str, context: ContextTypes.DEFAULT_TYPE):
        """إشعار الإدمن بطلب الإيداع"""
        user = db.get_user_by_id(transaction.user_id)
        method_info = Config.PAYMENT_METHODS[transaction.method]

        admin_message = f"""
🔔 طلب إيداع جديد

👤 المستخدم: {get_user_display_name(user)}
🆔 المعرف: {user.telegram_id}
💰 المبلغ: {format_currency(transaction.amount)}
🏦 الطريقة: {method_info['name']} {method_info['emoji']}
🔢 المرجع: {reference}
📅 التاريخ: {transaction.created_at.strftime('%Y-%m-%d %H:%M')}

استخدم /admin لإدارة الطلبات
        """

        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_message)
            except TelegramError:
                logger.warning(f"لا يمكن إرسال إشعار للإدمن {admin_id}")

    @staticmethod
    async def notify_admin_withdrawal(
        transaction: Transaction,
        reference: str,
        context: ContextTypes.DEFAULT_TYPE,
        destination: str = "",
    ):
        """إشعار الإدمن بطلب سحب للواقع — يحتاج تحويل يدوي"""
        user = db.get_user_by_id(transaction.user_id)
        method_info = Config.PAYMENT_METHODS.get(transaction.method, {"name": transaction.method, "emoji": ""})
        dest = destination or transaction.withdraw_destination or "غير محدد"

        admin_message = f"""
🔔 طلب سحب إلى واقع — **يتطلب إجراء يدوي**

👤 المستخدم: {get_user_display_name(user)}
🆔 المعرف: {user.telegram_id}
💸 المبلغ: {format_currency(transaction.amount)}
🏦 الطريقة: {method_info['name']} {method_info['emoji']}
📍 وجهة الاستلام: {dest}
🔢 رقم الطلب: {transaction.id}
🔢 المرجع: {reference}
💵 رصيد المستخدم بعد الخصم: {format_currency(user.balance)}
📅 التاريخ: {transaction.created_at.strftime('%Y-%m-%d %H:%M')}

⚠️ حوّل المبلغ يدوياً ثم وافق من /admin
        """

        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_message)
            except TelegramError:
                logger.warning(f"لا يمكن إرسال إشعار للإدمن {admin_id}")


def get_user_by_id(user_id: int) -> Optional[User]:
    """الحصول على مستخدم بواسطة ID"""
    session = db.get_session()
    try:
        return session.query(User).filter(User.id == user_id).first()
    finally:
        session.close()


DatabaseManager.get_user_by_id = get_user_by_id
