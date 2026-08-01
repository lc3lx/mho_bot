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
from utils import format_currency, validate_amount, generate_transaction_reference, safe_edit_callback_message, user_facing_error_message, tg_code
from ichancy_client import IchancyClient, IchancyError

logger = logging.getLogger(__name__)
db = DatabaseManager()
ichancy_client = IchancyClient()


class IchancyHandler:
    """إنشاء حساب ichancy + شحن من البوت + سحب للمنصة"""

    @staticmethod
    def _already_linked_message(user: User) -> str:
        return (
            "✅ لديك حساب Ichancy واحد مرتبط مسبقاً.\n\n"
            f"👤 المستخدم: {tg_code(user.ichancy_username or '—')}\n"
            f"🆔 Id: {tg_code(user.ichancy_player_id)}\n\n"
            "لا يمكن إنشاء حساب ثانٍ."
        )

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
        """نفس شاشة خطوة Ichancy الموحدة"""
        text = Config.MESSAGES["ichancy_required"]
        markup = Keyboards.ichancy_required_menu()
        if update.callback_query:
            await safe_edit_callback_message(
                update, text, reply_markup=markup, context=context
            )
        elif update.effective_message:
            await update.effective_message.reply_text(text, reply_markup=markup)
        else:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=text,
                reply_markup=markup,
            )

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
            f"👤 Username: {tg_code(username)}\n"
            f"🔑 Password: {tg_code(password)}\n"
            f"🆔 Id: {tg_code(player_id)}\n"
            f"💰 Balance: {platform_balance}\n\n"
            "اضغط على اسم المستخدم وكلمة المرور للنسخ"
        )

        if update.callback_query:
            await safe_edit_callback_message(
                update,
                text,
                reply_markup=Keyboards.ichancy_account_menu(),
                context=context,
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=Keyboards.ichancy_account_menu(),
                parse_mode="HTML",
            )

    # توافق مع الاسم القديم
    ichancy_menu = hub

    @staticmethod
    async def start_create_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """بدء إنشاء حساب — طلب اسم المستخدم"""
        user = db.get_user(update.effective_user.id)
        if not user:
            await safe_edit_callback_message(
                update,
                Config.MESSAGES["user_not_found"],
                reply_markup=Keyboards.ichancy_required_menu(),
                context=context,
            )
            return

        if user.ichancy_player_id:
            await safe_edit_callback_message(
                update,
                IchancyHandler._already_linked_message(user),
                reply_markup=Keyboards.ichancy_account_menu(),
                context=context,
                parse_mode="HTML",
            )
            return

        if not ichancy_client.is_configured:
            await safe_edit_callback_message(
                update,
                Config.MESSAGES["ichancy_not_configured"],
                reply_markup=Keyboards.ichancy_required_menu(),
                context=context,
            )
            return

        text = (
            "🔷 إنشاء حساب Ichancy — اسم المستخدم\n\n"
            "⚠️ مسموح بحساب واحد فقط لكل مستخدم.\n\n"
            "الشروط:\n"
            "1) أحرف إنجليزية فقط\n"
            "2) يفضّل إضافة أرقام\n"
            "3) بدون رموز خاصة\n\n"
            f"مثال: {tg_code('Walter12')}\n\n"
            "أرسل اسم المستخدم الآن، أو اضغط إلغاء للرجوع."
        )
        context.user_data["state"] = "waiting_for_ichancy_username"
        context.user_data["operation"] = "create_ichancy"
        await safe_edit_callback_message(
            update,
            text,
            reply_markup=Keyboards.cancel_operation(),
            context=context,
            parse_mode="HTML",
        )

    @staticmethod
    async def process_username(
        update: Update, context: ContextTypes.DEFAULT_TYPE, username: str
    ):
        user = db.get_user(update.effective_user.id)
        if user and user.ichancy_player_id:
            context.user_data.clear()
            await update.message.reply_text(
                IchancyHandler._already_linked_message(user),
                reply_markup=Keyboards.ichancy_account_menu(),
                parse_mode="HTML",
            )
            return

        username, err = IchancyHandler.validate_username(username)
        if err:
            await update.message.reply_text(
                err, reply_markup=Keyboards.cancel_operation()
            )
            return

        taken = db.get_user_by_ichancy_username(username)
        if taken and str(taken.telegram_id) != str(update.effective_user.id):
            await update.message.reply_text(
                "❌ اسم المستخدم هذا مرتبط بمستخدم آخر في البوت.\n"
                "اختر اسماً مختلفاً.",
                reply_markup=Keyboards.cancel_operation(),
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
                Config.MESSAGES["session_expired"],
                reply_markup=Keyboards.ichancy_required_menu(),
            )
            return

        # منع إنشاء حساب ثانٍ حتى لو تجاوز زر البداية
        existing = db.get_user(update.effective_user.id)
        if not existing:
            context.user_data.clear()
            await update.message.reply_text(
                Config.MESSAGES["user_not_found"],
                reply_markup=Keyboards.ichancy_required_menu(),
            )
            return

        if existing.ichancy_player_id:
            context.user_data.clear()
            await update.message.reply_text(
                IchancyHandler._already_linked_message(existing),
                reply_markup=Keyboards.ichancy_account_menu(),
                parse_mode="HTML",
            )
            return

        wait_msg = await update.message.reply_text("⏳ انتظر ريثما يتم انشاء الحساب")

        email = f"{username.lower()}@gmail.com"
        try:
            registered = await asyncio.to_thread(
                ichancy_client.register_player, username, password, email
            )

            player = None
            if isinstance(registered, dict) and registered.get("playerId"):
                player = registered
            else:
                player = ichancy_client.extract_player_from_register(
                    registered, login=username
                )

            if not player or not player.get("playerId"):
                player = await asyncio.to_thread(
                    ichancy_client.find_player_by_username, username
                )

            if not player or not player.get("playerId"):
                try:
                    player = await asyncio.to_thread(
                        ichancy_client.verify_player, username
                    )
                except IchancyError:
                    player = None

            player_id = str((player or {}).get("playerId") or "")
            if not player_id:
                raise IchancyError(
                    "تم إنشاء الحساب على المنصة لكن تعذر جلب معرف اللاعب.\n"
                    "البحث عن اللاعبين غير متاح لهذا الوكيل حالياً."
                )

            owner = db.get_user_by_ichancy_player_id(player_id)
            if owner and str(owner.telegram_id) != str(update.effective_user.id):
                context.user_data.clear()
                try:
                    await wait_msg.delete()
                except Exception:
                    pass
                await update.message.reply_text(
                    "❌ هذا الحساب مرتبط بمستخدم تليجرام آخر.\n"
                    "كل مستخدم يحق له حساب واحد فقط.",
                    reply_markup=Keyboards.ichancy_required_menu(),
                )
                return

            session = db.get_session()
            try:
                user = session.query(User).filter(
                    User.telegram_id == str(update.effective_user.id)
                ).first()
                if user.ichancy_player_id:
                    context.user_data.clear()
                    try:
                        await wait_msg.delete()
                    except Exception:
                        pass
                    await update.message.reply_text(
                        IchancyHandler._already_linked_message(user),
                        reply_markup=Keyboards.ichancy_account_menu(),
                        parse_mode="HTML",
                    )
                    return

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
                f"اسم المستخدم: {tg_code(username)}\n"
                f"كلمة السر: {tg_code(password)}\n\n"
                "اضغط على اسم المستخدم وكلمة المرور للنسخ\n\n"
                "⚠️ هذا حسابك الوحيد المرتبط بهذا البوت.\n"
                "✅ تم فتح باقي خدمات البوت.",
                parse_mode="HTML",
                reply_markup=Keyboards.start_menu(),
            )

        except IchancyError as exc:
            context.user_data.clear()
            await update.message.reply_text(
                f"❌ فشل إنشاء الحساب:\n{exc.message}\n\n"
                "صحّح البيانات أو جرّب اسماً آخر، أو تواصل مع الدعم.",
                reply_markup=Keyboards.ichancy_required_menu(),
            )
        except Exception as exc:
            logger.exception("خطأ غير متوقع أثناء إنشاء حساب Ichancy")
            context.user_data.clear()
            await update.message.reply_text(
                f"❌ تعذر إنشاء الحساب الآن.\n{user_facing_error_message(exc)}",
                reply_markup=Keyboards.ichancy_required_menu(),
            )

    @staticmethod
    async def start_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شحن حساب ichancy من رصيد البوت"""
        user = db.get_user(update.effective_user.id)
        min_topup = Config.ICHANCY_CONFIG.get("min_topup", 200)

        if not user.ichancy_player_id:
            await safe_edit_callback_message(
                update,
                "❌ أنشئ حساب Ichancy أولاً من الزر أدناه.",
                reply_markup=Keyboards.ichancy_required_menu(),
                context=context,
            )
            return

        text = (
            "🔄 شحن رصيد Ichancy\n\n"
            "أرسل المبلغ الذي تريد إضافته إلى حسابك في ايشانسي.\n\n"
            f"ملاحظة: أقل مبلغ للشحن هو {format_currency(min_topup)}\n\n"
            f"💵 رصيد البوت المتاح: {format_currency(user.balance)}"
        )
        context.user_data["state"] = "waiting_for_amount"
        context.user_data["operation"] = "ichancy_topup"
        context.user_data["method"] = "ichancy"
        await safe_edit_callback_message(
            update,
            text,
            reply_markup=Keyboards.cancel_operation(),
            context=context,
        )

    @staticmethod
    async def process_topup(
        update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float
    ):
        """تنفيذ شحن ichancy عبر depositToPlayer وخصم من رصيد البوت"""
        user = db.get_user(update.effective_user.id)
        min_topup = Config.ICHANCY_CONFIG.get("min_topup", 200)

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
        """رفض ربط الحسابات الموجودة عند استدعاء callback قديم."""
        context.user_data.clear()
        await safe_edit_callback_message(
            update,
            "❌ ربط حساب خارجي غير مسموح.\nأنشئ حسابك من داخل البوت فقط.",
            reply_markup=Keyboards.ichancy_required_menu(),
            context=context,
        )

    @staticmethod
    async def process_link_account(
        update: Update, context: ContextTypes.DEFAULT_TYPE, player_ref: str
    ):
        """رفض مسار ربط الحسابات القديمة دون أي كتابة في قاعدة البيانات."""
        context.user_data.clear()
        await update.message.reply_text(
            "❌ ربط حساب خارجي غير مسموح.\nأنشئ حسابك من داخل البوت فقط.",
            reply_markup=Keyboards.ichancy_required_menu(),
        )

    @staticmethod
    async def start_withdraw_from_ichancy(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """سحب من ichancy إلى محفظة البوت"""
        user = db.get_user(update.effective_user.id)

        if not user.ichancy_player_id:
            await safe_edit_callback_message(
                update,
                "❌ أنشئ حساب Ichancy أولاً من الزر أدناه.",
                reply_markup=Keyboards.ichancy_required_menu(),
                context=context,
            )
            return

        if not ichancy_client.is_configured:
            await safe_edit_callback_message(
                update,
                Config.MESSAGES["ichancy_not_configured"],
                reply_markup=Keyboards.ichancy_account_menu(),
                context=context,
            )
            return

        allowed, remaining = IchancyHandler.get_withdraw_cooldown(user.id)
        cooldown_minutes = Config.ICHANCY_CONFIG.get("withdraw_cooldown_minutes", 30)
        if not allowed:
            await safe_edit_callback_message(
                update,
                f"⏱ مسموح سحب واحد كل {cooldown_minutes} دقيقة.\n"
                f"المتبقي: {IchancyHandler._format_remaining(remaining)}",
                reply_markup=Keyboards.ichancy_account_menu(),
                context=context,
            )
            return

        currency = Config.ICHANCY_CONFIG.get("currency_code", "")
        message = f"""
⬇️ سحب رصيد الحساب إلى محفظة البوت

🎰 Id: {tg_code(user.ichancy_player_id)}
⏱ بعد السحب: انتظار {cooldown_minutes} دقيقة قبل سحب آخر

أرسل المبلغ الذي تريد سحبه من ichancy ({currency}):
        """
        context.user_data["state"] = "waiting_for_amount"
        context.user_data["operation"] = "ichancy_withdraw"
        await safe_edit_callback_message(
            update,
            message,
            reply_markup=Keyboards.cancel_operation(),
            context=context,
            parse_mode="HTML",
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
                "❌ يجب إنشاء حساب Ichancy أولاً",
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
                if platform_balance <= 0:
                    raise IchancyError(
                        "ما عندك فلوس يا غالي 😅\n"
                        f"رصيد iChancy الحالي: {format_currency(0)}\n"
                        "عبّي الحساب أول شي، بعدين تفضل عالسحب."
                    )
                if platform_balance < validated_amount:
                    raise IchancyError(
                        "ما بيكفّي الرصيد يا غالي 😅\n"
                        f"المطلوب: {format_currency(validated_amount)}\n"
                        f"المتوفر على iChancy: {format_currency(platform_balance)}"
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
                msg = exc.message
                if "غير موجود أو لا يوجد رصيد" in msg:
                    msg = (
                        "ما عندك فلوس يا غالي 😅\n"
                        "رصيد iChancy فاضي أو ما قدرنا نقرأه.\n"
                        "عبّي الحساب أول شي، بعدين تفضل عالسحب."
                    )
                await update.message.reply_text(
                    f"❌ فشل السحب من ichancy:\n{msg}",
                    reply_markup=Keyboards.main_menu(),
                )
        finally:
            session.close()

    @staticmethod
    async def change_password_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """لا يوجد endpoint لتغيير كلمة المرور في وثيقة Agent API"""
        site = Config.ICHANCY_CONFIG.get("website_url", "https://www.ichancy.com/")
        await safe_edit_callback_message(
            update,
            "🖊️ تغيير كلمة مرور الحساب\n\n"
            "لا يمكن تغيير كلمة المرور من البوت حالياً.\n"
            f"غيّرها من الموقع: {site}\n\n"
            "بعد التغيير يمكنك تحديثها المحفوظة هنا عبر الدعم.",
            reply_markup=Keyboards.ichancy_account_menu(),
            context=context,
        )
