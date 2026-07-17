"""
معالج حساب ichancy: إنشاء / شحن / سحب
حسب Agent API Documentation (registerPlayer, depositToPlayer, withdrawFromPlayer)
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from database import DatabaseManager, User, Transaction
from config import Config
from keyboards import Keyboards
from utils import format_currency, validate_amount, generate_transaction_reference
from ichancy_client import IchancyClient, IchancyError

logger = logging.getLogger(__name__)
db = DatabaseManager()
ichancy_client = IchancyClient()


class IchancyHandler:
    """إنشاء حساب ichancy + شحن من البوت + سحب للمنصة"""

    @staticmethod
    def _format_remaining(seconds: int) -> str:
        minutes, secs = divmod(max(0, seconds), 60)
        if minutes and secs:
            return f"{minutes} دقيقة و {secs} ثانية"
        if minutes:
            return f"{minutes} دقيقة"
        return f"{secs} ثانية"

    @staticmethod
    def validate_username(username: str):
        username = username.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{2,29}", username):
            return None, (
                "🔴 اسم المستخدم غير صالح.\n"
                "• أحرف إنجليزية فقط\n"
                "• يجب أن يحتوي أرقاماً لتجنب التشابه\n"
                "• بدون رموز خاصة\n"
                "مثال: `Walter12`"
            )
        if not re.search(r"\d", username):
            return None, (
                "🔴 يجب أن يحتوي اسم المستخدم على أرقام.\n"
                "مثال: `Walter12`"
            )
        return username, None

    @staticmethod
    def validate_password(password: str):
        password = password.strip()
        if len(password) < 8 or len(password) > 16:
            return None, (
                "🔴 يجب أن تحتوي كلمة المرور على أرقام بالإضافة إلى أحرف كبيرة "
                "وصغيرة، وأن تكون بطول 8 أحرف فما فوق، وألا تزيد عن 16 محرف."
            )
        if not re.search(r"[a-z]", password):
            return None, (
                "🔴 يجب أن تحتوي كلمة المرور على أحرف صغيرة وأرقام وأحرف كبيرة."
            )
        if not re.search(r"[A-Z]", password):
            return None, (
                "🔴 يجب أن تحتوي كلمة المرور على أحرف كبيرة بالإضافة إلى أرقام."
            )
        if not re.search(r"\d", password):
            return None, (
                "🔴 يجب أن تحتوي كلمة المرور على أرقام بالإضافة إلى أحرف كبيرة "
                "وصغيرة، وأن تكون بطول 8 أحرف فما فوق، وألا تزيد عن 16 محرف."
            )
        return password, None

    @staticmethod
    def get_withdraw_cooldown(user_id: int):
        cooldown_minutes = Config.ICHANCY_CONFIG.get("withdraw_cooldown_minutes", 30)
        session = db.get_session()
        try:
            last = (
                session.query(Transaction)
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.transaction_type == "ichancy_withdraw",
                    Transaction.status == "completed",
                )
                .order_by(
                    Transaction.processed_at.desc(),
                    Transaction.created_at.desc(),
                )
                .first()
            )
            if not last:
                return True, 0

            last_time = last.processed_at or last.created_at
            if not last_time:
                return True, 0

            elapsed = datetime.utcnow() - last_time
            cooldown = timedelta(minutes=cooldown_minutes)
            if elapsed >= cooldown:
                return True, 0
            return False, int((cooldown - elapsed).total_seconds())
        finally:
            session.close()

    @staticmethod
    async def hub(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مركز شحن/سحب حساب Ichancy"""
        user = db.get_user(update.effective_user.id)

        if not user.ichancy_player_id:
            await IchancyHandler.show_create_prompt(update, context)
            return

        await IchancyHandler.show_account_info(update, context)

    @staticmethod
    async def show_create_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """الخطوة الثانية: إنشاء حساب"""
        text = (
            "2️⃣ الخطوة الثانية\n"
            "بعد إتمام الشحن، يجب عليك إنشاء حساب.\n\n"
            "اضغط الزر لإنشاء حساب Ichancy."
        )
        markup = Keyboards.ichancy_create_prompt()
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=markup)
        else:
            await update.message.reply_text(text, reply_markup=markup)

    @staticmethod
    async def show_account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معلومات حساب ichancy مثل الصورة"""
        user = db.get_user(update.effective_user.id)
        username = user.ichancy_username or "—"
        password = user.ichancy_password or "—"
        player_id = user.ichancy_player_id or "—"

        platform_balance = "—"
        if user.ichancy_player_id and ichancy_client.is_configured:
            try:
                balance = await asyncio.to_thread(
                    ichancy_client.get_player_balance, user.ichancy_player_id
                )
                platform_balance = format_currency(balance)
            except IchancyError:
                platform_balance = "تعذر الجلب"

        text = (
            "🔐 معلومات حسابك في ايشانسي\n\n"
            f"👤 Username: `{username}`\n"
            f"🔑 Password: `{password}`\n"
            f"🆔 Id: `{player_id}`\n"
            f"💰 Balance: {platform_balance}\n\n"
            "اضغط على اسم المستخدم وكلمة المرور للنسخ"
        )

        if update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=Keyboards.ichancy_account_menu(),
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=Keyboards.ichancy_account_menu(),
                parse_mode="Markdown",
            )

    # توافق مع الاسم القديم
    ichancy_menu = hub

    @staticmethod
    async def start_create_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """بدء إنشاء حساب — طلب اسم المستخدم"""
        user = db.get_user(update.effective_user.id)
        if user.ichancy_player_id:
            await update.callback_query.edit_message_text(
                "✅ لديك حساب Ichancy مسبقاً.",
                reply_markup=Keyboards.ichancy_account_menu(),
            )
            return

        if not ichancy_client.is_configured:
            await update.callback_query.edit_message_text(
                "❌ خدمة ichancy غير مُعدّة. تواصل مع الإدارة.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        text = (
            "🔷 إنشاء حساب iChancy - اسم المستخدم\n\n"
            "يرجى اختيار اسم مستخدم يحقق الشروط التالية:\n"
            "1. أن يحتوي على أحرف إنجليزية فقط.\n"
            "2. أن يحتوي على أرقام لتجنب التشابه.\n"
            "3. ألا يحتوي على رموز خاصة مثل .?!- +_()*&^%$#@\n\n"
            "مثال على اسم المستخدم: `Walter12`"
        )
        context.user_data["state"] = "waiting_for_ichancy_username"
        context.user_data["operation"] = "create_ichancy"
        await update.callback_query.edit_message_text(
            text,
            reply_markup=Keyboards.cancel_operation(),
            parse_mode="Markdown",
        )

    @staticmethod
    async def process_username(
        update: Update, context: ContextTypes.DEFAULT_TYPE, username: str
    ):
        username, err = IchancyHandler.validate_username(username)
        if err:
            await update.message.reply_text(
                err, reply_markup=Keyboards.cancel_operation(), parse_mode="Markdown"
            )
            return

        context.user_data["ichancy_new_username"] = username
        context.user_data["state"] = "waiting_for_ichancy_password"
        await update.message.reply_text(
            "🔷 إنشاء حساب iChancy - كلمة المرور\n\n"
            "ادخل كلمة المرور يجب أن يتراوح طولها بين 8-16 حرف، "
            "وأن تحتوي على أحرف كبيرة وصغيرة، بالإضافة إلى أرقام.",
            reply_markup=Keyboards.cancel_operation(),
        )

    @staticmethod
    async def process_password(
        update: Update, context: ContextTypes.DEFAULT_TYPE, password: str
    ):
        password, err = IchancyHandler.validate_password(password)
        if err:
            await update.message.reply_text(
                f"🔄 حاول مرة اخرى\n\n{err}",
                reply_markup=Keyboards.cancel_operation(),
            )
            return

        username = context.user_data.get("ichancy_new_username")
        if not username:
            context.user_data.clear()
            await update.message.reply_text(
                "❌ انتهت الجلسة. ابدأ من جديد.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        wait_msg = await update.message.reply_text("⏳ انتظر ريثما يتم انشاء الحساب")

        email = f"{username.lower()}@gmail.com"
        try:
            await asyncio.to_thread(
                ichancy_client.register_player, username, password, email
            )
            # بعد التسجيل نجلب playerId
            player = await asyncio.to_thread(
                ichancy_client.find_player_by_username, username
            )
            if not player:
                # محاولة تحقق بديلة
                player = await asyncio.to_thread(
                    ichancy_client.verify_player, username
                )
            player_id = str(player.get("playerId") or "")
            if not player_id:
                raise IchancyError("تم التسجيل لكن تعذر جلب معرف اللاعب")

            session = db.get_session()
            try:
                user = session.query(User).filter(
                    User.telegram_id == str(update.effective_user.id)
                ).first()
                user.ichancy_player_id = player_id
                user.ichancy_username = username
                user.ichancy_password = password
                session.commit()
            finally:
                session.close()

            context.user_data.clear()
            try:
                await wait_msg.delete()
            except Exception:
                pass

            await update.message.reply_text(
                "✅ تم إنشاء حسابك بنجاح\n"
                "معلومات الحساب هي:\n\n"
                f"اسم المستخدم: `{username}`\n"
                f"كلمة السر: `{password}`\n\n"
                "اضغط على اسم المستخدم وكلمة المرور للنسخ",
                parse_mode="Markdown",
                reply_markup=Keyboards.ichancy_account_menu(),
            )

        except IchancyError as exc:
            context.user_data.clear()
            await update.message.reply_text(
                f"❌ فشل إنشاء الحساب:\n{exc.message}",
                reply_markup=Keyboards.main_menu(),
            )

    @staticmethod
    async def start_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شحن حساب ichancy من رصيد البوت"""
        user = db.get_user(update.effective_user.id)
        min_topup = Config.ICHANCY_CONFIG.get("min_topup", 20000)

        if not user.ichancy_player_id:
            await update.callback_query.edit_message_text(
                "❌ أنشئ حساب Ichancy أولاً.",
                reply_markup=Keyboards.ichancy_create_prompt(),
            )
            return

        text = (
            "🔄 شحن رصيد 🔄\n\n"
            "ادخل المبلغ الذي تريد إضافته الى حسابك في ايشانسي\n\n"
            f"ملاحظة: اقل مبلغ لشحن الحساب هو {format_currency(min_topup)}\n\n"
            f"💵 رصيد البوت المتاح: {format_currency(user.balance)}"
        )
        context.user_data["state"] = "waiting_for_amount"
        context.user_data["operation"] = "ichancy_topup"
        context.user_data["method"] = "ichancy"
        await update.callback_query.edit_message_text(
            text,
            reply_markup=Keyboards.cancel_operation(),
        )

    @staticmethod
    async def process_topup(
        update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float
    ):
        """تنفيذ شحن ichancy عبر depositToPlayer وخصم من رصيد البوت"""
        user = db.get_user(update.effective_user.id)
        min_topup = Config.ICHANCY_CONFIG.get("min_topup", 20000)

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            await update.message.reply_text(
                "❌ المبلغ غير صحيح",
                reply_markup=Keyboards.cancel_operation(),
            )
            return

        if amount < min_topup:
            await update.message.reply_text(
                f"❌ اقل مبلغ لشحن الحساب هو {format_currency(min_topup)}",
                reply_markup=Keyboards.cancel_operation(),
            )
            return

        if user.balance < amount:
            await update.message.reply_text(
                f"❌ رصيد البوت غير كافٍ.\n💵 رصيدك: {format_currency(user.balance)}",
                reply_markup=Keyboards.main_menu(),
            )
            context.user_data.clear()
            return

        if not user.ichancy_player_id:
            context.user_data.clear()
            await update.message.reply_text(
                "❌ لا يوجد حساب Ichancy مرتبط.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        wait = await update.message.reply_text("⌛ لحظات من فضلك")
        reference = generate_transaction_reference()

        session = db.get_session()
        try:
            db_user = session.query(User).filter(User.id == user.id).first()
            if db_user.balance < amount:
                await update.message.reply_text("❌ رصيد غير كافٍ")
                context.user_data.clear()
                return

            transaction = Transaction(
                user_id=user.id,
                transaction_type="ichancy_topup",
                amount=amount,
                method="ichancy",
                status="pending",
                description=(
                    f"شحن حساب ichancy (depositToPlayer) — "
                    f"playerId {user.ichancy_player_id}"
                ),
            )
            session.add(transaction)
            db_user.balance -= amount
            session.commit()
            session.refresh(transaction)

            try:
                result = await asyncio.to_thread(
                    ichancy_client.deposit_to_player,
                    user.ichancy_player_id,
                    amount,
                    f"Bot topup {user.telegram_id} REF:{reference}",
                )
                transaction.status = "completed"
                transaction.processed_at = datetime.utcnow()
                transaction.external_transaction_id = f"TOP_{reference}"
                transaction.description += f"\nنتيجة API: {result.get('balance', '')}"
                session.commit()

                context.user_data.clear()
                try:
                    await wait.delete()
                except Exception:
                    pass

                await update.message.reply_text(
                    f"✅ تم شحن الحساب بمبلغ {format_currency(amount)}",
                    reply_markup=Keyboards.ichancy_account_menu(),
                )

            except IchancyError as exc:
                # إرجاع الرصيد
                db_user.balance += amount
                transaction.status = "failed"
                transaction.admin_notes = exc.message
                transaction.processed_at = datetime.utcnow()
                session.commit()
                context.user_data.clear()
                await update.message.reply_text(
                    f"❌ فشل شحن الحساب:\n{exc.message}\n💵 تم إرجاع المبلغ لرصيد البوت.",
                    reply_markup=Keyboards.main_menu(),
                )
        finally:
            session.close()

    @staticmethod
    async def start_link_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ربط حساب موجود (احتياطي)"""
        message = """
🔗 ربط حساب ichancy

أرسل **معرف اللاعب (playerId)** أو **اسم المستخدم** على ichancy
        """
        context.user_data["state"] = "waiting_for_ichancy_player_id"
        context.user_data["operation"] = "link_ichancy"
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.cancel_operation(),
            parse_mode="Markdown",
        )

    @staticmethod
    async def process_link_account(
        update: Update, context: ContextTypes.DEFAULT_TYPE, player_ref: str
    ):
        player_ref = player_ref.strip()
        if len(player_ref) < 3:
            await update.message.reply_text(
                "❌ المعرف قصير جداً.",
                reply_markup=Keyboards.cancel_operation(),
            )
            return

        resolved_id = player_ref
        display_name = player_ref

        if ichancy_client.is_configured:
            await update.message.reply_text("⏳ جاري التحقق من الحساب على ichancy...")
            try:
                player = await asyncio.to_thread(
                    ichancy_client.verify_player, player_ref
                )
                resolved_id = str(player.get("playerId") or player_ref)
                display_name = player.get("username") or resolved_id
            except IchancyError as exc:
                await update.message.reply_text(
                    f"❌ لم يتم العثور على الحساب:\n{exc.message}",
                    reply_markup=Keyboards.cancel_operation(),
                )
                return

        session = db.get_session()
        try:
            user = session.query(User).filter(
                User.telegram_id == str(update.effective_user.id)
            ).first()
            user.ichancy_player_id = resolved_id
            user.ichancy_username = display_name
            session.commit()
        finally:
            session.close()

        context.user_data.clear()
        await update.message.reply_text(
            f"✅ تم ربط الحساب!\n🎰 Id: `{resolved_id}`\n👤 `{display_name}`",
            reply_markup=Keyboards.ichancy_account_menu(),
            parse_mode="Markdown",
        )

    @staticmethod
    async def start_withdraw_from_ichancy(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """سحب من ichancy إلى محفظة البوت"""
        user = db.get_user(update.effective_user.id)

        if not user.ichancy_player_id:
            await update.callback_query.edit_message_text(
                "❌ أنشئ حساب Ichancy أولاً.",
                reply_markup=Keyboards.ichancy_create_prompt(),
            )
            return

        if not ichancy_client.is_configured:
            await update.callback_query.edit_message_text(
                "❌ خدمة ichancy غير مُعدّة.",
                reply_markup=Keyboards.main_menu(),
            )
            return

        allowed, remaining = IchancyHandler.get_withdraw_cooldown(user.id)
        cooldown_minutes = Config.ICHANCY_CONFIG.get("withdraw_cooldown_minutes", 30)
        if not allowed:
            await update.callback_query.edit_message_text(
                f"⏱ مسموح سحب واحد كل {cooldown_minutes} دقيقة.\n"
                f"المتبقي: {IchancyHandler._format_remaining(remaining)}",
                reply_markup=Keyboards.ichancy_account_menu(),
            )
            return

        currency = Config.ICHANCY_CONFIG.get("currency_code", "")
        message = f"""
⬇️ سحب رصيد الحساب إلى محفظة البوت

🎰 Id: `{user.ichancy_player_id}`
⏱ بعد السحب: انتظار {cooldown_minutes} دقيقة قبل سحب آخر

أرسل المبلغ الذي تريد سحبه من ichancy ({currency}):
        """
        context.user_data["state"] = "waiting_for_amount"
        context.user_data["operation"] = "ichancy_withdraw"
        await update.callback_query.edit_message_text(
            message,
            reply_markup=Keyboards.cancel_operation(),
            parse_mode="Markdown",
        )

    @staticmethod
    async def process_ichancy_withdraw(
        update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float
    ):
        """تنفيذ سحب ichancy → البوت عبر withdrawFromPlayer"""
        user = db.get_user(update.effective_user.id)

        is_valid, validated_amount, error_msg = validate_amount(
            str(amount), Config.MIN_DEPOSIT, Config.MAX_DEPOSIT
        )
        if not is_valid:
            try:
                validated_amount = float(amount)
            except (TypeError, ValueError):
                await update.message.reply_text(
                    error_msg, reply_markup=Keyboards.cancel_operation()
                )
                return
            if validated_amount <= 0:
                await update.message.reply_text(
                    "❌ المبلغ غير صحيح",
                    reply_markup=Keyboards.cancel_operation(),
                )
                return

        if not user.ichancy_player_id:
            context.user_data.clear()
            await update.message.reply_text(
                "❌ يجب ربط حساب ichancy أولاً",
                reply_markup=Keyboards.main_menu(),
            )
            return

        cooldown_minutes = Config.ICHANCY_CONFIG.get("withdraw_cooldown_minutes", 30)
        allowed, remaining = IchancyHandler.get_withdraw_cooldown(user.id)
        if not allowed:
            context.user_data.clear()
            await update.message.reply_text(
                f"⏱ مسموح سحب واحد كل {cooldown_minutes} دقيقة.\n"
                f"⏳ المتبقي: {IchancyHandler._format_remaining(remaining)}",
                reply_markup=Keyboards.main_menu(),
            )
            return

        await update.message.reply_text("⏳ جاري سحب الرصيد من ichancy...")

        reference = generate_transaction_reference()
        session = db.get_session()
        try:
            transaction = Transaction(
                user_id=user.id,
                transaction_type="ichancy_withdraw",
                amount=validated_amount,
                method="ichancy",
                status="pending",
                description=(
                    f"سحب من ichancy (withdrawFromPlayer) — "
                    f"playerId {user.ichancy_player_id}"
                ),
            )
            session.add(transaction)
            session.commit()
            session.refresh(transaction)

            try:
                platform_balance = await asyncio.to_thread(
                    ichancy_client.get_player_balance, user.ichancy_player_id
                )
                if platform_balance < validated_amount:
                    raise IchancyError(
                        f"رصيد المنصة غير كافٍ. المتاح: {format_currency(platform_balance)}"
                    )

                result = await asyncio.to_thread(
                    ichancy_client.withdraw_from_player,
                    user.ichancy_player_id,
                    validated_amount,
                    f"Bot wallet {user.telegram_id} REF:{reference}",
                )

                external_id = f"ICH_{reference}_{user.ichancy_player_id}"
                new_platform_balance = result.get("balance")

                db_user = session.query(User).filter(User.id == user.id).first()
                db_user.balance += validated_amount

                transaction.status = "completed"
                transaction.external_transaction_id = external_id
                transaction.processed_at = datetime.utcnow()
                transaction.description += (
                    f"\nمرجع: {external_id}"
                    f"\nرصيد المنصة بعد السحب: {new_platform_balance}"
                )
                session.commit()

                context.user_data.clear()
                await update.message.reply_text(
                    f"✅ تم سحب الرصيد من ichancy بنجاح!\n\n"
                    f"💸 المبلغ: {format_currency(validated_amount)}\n"
                    f"💵 رصيد محفظة البوت: {format_currency(db_user.balance)}\n"
                    f"🎰 رصيد المنصة: {format_currency(float(new_platform_balance or 0))}\n\n"
                    f"⏱ السحب التالي بعد {cooldown_minutes} دقيقة.",
                    reply_markup=Keyboards.ichancy_account_menu(),
                )

            except IchancyError as exc:
                transaction.status = "failed"
                transaction.admin_notes = exc.message
                transaction.processed_at = datetime.utcnow()
                session.commit()
                context.user_data.clear()
                await update.message.reply_text(
                    f"❌ فشل السحب من ichancy:\n{exc.message}",
                    reply_markup=Keyboards.main_menu(),
                )
        finally:
            session.close()

    @staticmethod
    async def change_password_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """لا يوجد endpoint لتغيير كلمة المرور في وثيقة Agent API"""
        site = Config.ICHANCY_CONFIG.get("website_url", "https://www.ichancy.com/")
        await update.callback_query.edit_message_text(
            "🖊️ تغيير كلمة مرور الحساب\n\n"
            "حسب وثيقة Agent API لا يتوفر Endpoint لتغيير كلمة المرور من البوت.\n"
            f"غيّرها من الموقع: {site}\n\n"
            "بعد التغيير يمكنك تحديثها المحفوظة هنا عبر الدعم.",
            reply_markup=Keyboards.ichancy_account_menu(),
        )
