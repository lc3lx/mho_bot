"""
إدارة أرقام سيريتل كاش وحسابات شام كاش المحفوظة للزبون
سيريتل: حتى 10 — شام كاش: حساب واحد فقط
"""

import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from database import DatabaseManager
from config import Config
from keyboards import Keyboards

logger = logging.getLogger(__name__)
db = DatabaseManager()

ACCOUNT_TYPE_LABELS = {
    "syriatel_cash": "سيريتل كاش",
    "shamcash": "شام كاش",
}


class SavedAccountsHandler:
    """حفظ وإدارة أرقام الدفع للزبون"""

    @staticmethod
    def normalize_syriatel(value: str) -> str:
        digits = re.sub(r"\D", "", value.strip())
        if digits.startswith("963"):
            digits = "0" + digits[3:]
        elif digits.startswith("00963"):
            digits = "0" + digits[5:]
        return digits

    @staticmethod
    def normalize_shamcash(value: str) -> str:
        return value.strip().replace(" ", "")

    @staticmethod
    def validate_account(account_type: str, value: str):
        """يرجع (normalized, error)"""
        if account_type == "syriatel_cash":
            normalized = SavedAccountsHandler.normalize_syriatel(value)
            if not re.fullmatch(r"09\d{8}", normalized):
                return None, "❌ رقم سيريتل غير صحيح.\nالمطلوب مثل: `0999123456`"
            return normalized, None

        if account_type == "shamcash":
            normalized = SavedAccountsHandler.normalize_shamcash(value)
            if len(normalized) < 8:
                return None, "❌ عنوان شام كاش قصير جداً."
            if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
                return None, "❌ عنوان شام كاش غير صالح."
            return normalized, None

        return None, "❌ نوع حساب غير مدعوم"

    @staticmethod
    async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """قائمة الحسابات المحفوظة"""
        user = db.get_user(update.effective_user.id)
        sy_max = Config.max_saved_accounts("syriatel_cash")
        sc_max = Config.max_saved_accounts("shamcash")
        sy_count = db.count_saved_accounts(user.id, "syriatel_cash")
        sc_count = db.count_saved_accounts(user.id, "shamcash")

        message = f"""
📱 حساباتي المحفوظة

• سيريتل كاش: حتى **{sy_max}** أرقام — الحالي {sy_count}/{sy_max}
• شام كاش: **حساب واحد فقط** — الحالي {sc_count}/{sc_max}

تُستخدم عند السحب إلى الواقع.

اختر نوع الحساب لإدارته:
        """

        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=Keyboards.saved_accounts_menu(),
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=Keyboards.saved_accounts_menu(),
                parse_mode="Markdown",
            )

    @staticmethod
    async def list_accounts(
        update: Update, context: ContextTypes.DEFAULT_TYPE, account_type: str
    ):
        """عرض حسابات نوع معيّن"""
        user = db.get_user(update.effective_user.id)
        accounts = db.get_saved_accounts(user.id, account_type)
        max_n = Config.max_saved_accounts(account_type)
        label = ACCOUNT_TYPE_LABELS.get(account_type, account_type)

        if not accounts:
            text = (
                f"📭 لا توجد حسابات {label} محفوظة.\n"
                f"يمكنك إضافة حتى {max_n}."
            )
        else:
            lines = [f"📋 حسابات {label} ({len(accounts)}/{max_n}):\n"]
            for i, acc in enumerate(accounts, 1):
                lines.append(f"{i}. `{acc.account_value}`")
            text = "\n".join(lines)
            if account_type == "shamcash":
                text += "\n\n⚠️ شام كاش: حساب واحد فقط — احذف الحالي لتغييره."
            else:
                text += "\n\n🗑 اضغط على رقم للحذف، أو أضف حساباً جديداً."

        await update.callback_query.edit_message_text(
            text,
            reply_markup=Keyboards.saved_accounts_list(account_type, accounts, max_n),
            parse_mode="Markdown",
        )

    @staticmethod
    async def start_add(
        update: Update, context: ContextTypes.DEFAULT_TYPE, account_type: str
    ):
        """بدء إضافة حساب"""
        user = db.get_user(update.effective_user.id)
        max_n = Config.max_saved_accounts(account_type)
        count = db.count_saved_accounts(user.id, account_type)
        label = ACCOUNT_TYPE_LABELS.get(account_type, account_type)

        if count >= max_n:
            tip = (
                "احذف الحساب الحالي أولاً لاستبداله."
                if account_type == "shamcash"
                else "احذف حساباً قديماً أولاً لإضافة جديد."
            )
            await update.callback_query.edit_message_text(
                f"❌ وصلت للحد الأقصى ({max_n}) لـ {label}.\n{tip}",
                reply_markup=Keyboards.saved_accounts_list(
                    account_type,
                    db.get_saved_accounts(user.id, account_type),
                    max_n,
                ),
            )
            return

        if account_type == "syriatel_cash":
            prompt = (
                f"📱 إضافة رقم سيريتل كاش ({count + 1}/{max_n})\n\n"
                "أرسل الرقم مثل:\n`0999123456`"
            )
        else:
            prompt = (
                "💳 إضافة حساب شام كاش (حساب واحد فقط)\n\n"
                "أرسل عنوان الحساب كما يظهر في التطبيق."
            )

        context.user_data["state"] = "waiting_for_saved_account"
        context.user_data["operation"] = "add_saved_account"
        context.user_data["saved_account_type"] = account_type

        await update.callback_query.edit_message_text(
            prompt,
            reply_markup=Keyboards.cancel_operation(),
            parse_mode="Markdown",
        )

    @staticmethod
    async def process_add(
        update: Update, context: ContextTypes.DEFAULT_TYPE, raw_value: str
    ):
        """حفظ رقم/حساب جديد"""
        account_type = context.user_data.get("saved_account_type")
        if not account_type:
            context.user_data.clear()
            await update.message.reply_text(
                "❌ انتهت الجلسة. ابدأ من جديد.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        normalized, error = SavedAccountsHandler.validate_account(account_type, raw_value)
        if error:
            await update.message.reply_text(
                error, reply_markup=Keyboards.cancel_operation(), parse_mode="Markdown"
            )
            return

        user = db.get_user(update.effective_user.id)
        account, err = db.add_saved_account(
            user.id,
            account_type,
            normalized,
            max_per_type=Config.max_saved_accounts(account_type),
        )
        context.user_data.clear()

        label = ACCOUNT_TYPE_LABELS.get(account_type, account_type)
        if err:
            await update.message.reply_text(
                f"❌ {err}",
                reply_markup=Keyboards.saved_accounts_menu(),
            )
            return

        await update.message.reply_text(
            f"✅ تم حفظ {label}:\n`{account.account_value}`",
            reply_markup=Keyboards.saved_accounts_list(
                account_type,
                db.get_saved_accounts(user.id, account_type),
                Config.max_saved_accounts(account_type),
            ),
            parse_mode="Markdown",
        )

    @staticmethod
    async def delete_account(
        update: Update, context: ContextTypes.DEFAULT_TYPE, account_id: int
    ):
        """حذف حساب محفوظ"""
        user = db.get_user(update.effective_user.id)
        account = db.get_saved_account(account_id, user.id)
        if not account:
            await update.callback_query.edit_message_text(
                "❌ الحساب غير موجود",
                reply_markup=Keyboards.saved_accounts_menu(),
            )
            return

        account_type = account.account_type
        value = account.account_value
        db.delete_saved_account(account_id, user.id)

        label = ACCOUNT_TYPE_LABELS.get(account_type, account_type)
        accounts = db.get_saved_accounts(user.id, account_type)
        await update.callback_query.edit_message_text(
            f"🗑 تم حذف `{value}` من {label}.\n\n"
            f"المتبقي: {len(accounts)}/{Config.max_saved_accounts(account_type)}",
            reply_markup=Keyboards.saved_accounts_list(
                account_type, accounts, Config.max_saved_accounts(account_type)
            ),
            parse_mode="Markdown",
        )
