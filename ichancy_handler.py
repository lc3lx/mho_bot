"""
معالج حساب ichancy: إنشاء / شحن / سحب
حسب Agent API Documentation (registerPlayer, depositToPlayer, withdrawFromPlayer)
"""

import asyncio
import logging
import random
import re
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

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

# #region agent log
def _agent_dbg(hypothesis_id: str, location: str, message: str, data: dict | None = None):
    try:
        import json, time
        from pathlib import Path
        payload = {
            "sessionId": "73d636",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        path = Path(__file__).resolve().parent / "debug-73d636.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
# #endregion

ICHANCY_LOGIN_PREFIX = "Na_"
RANDOM_NAME_POOL = (
    "Ali", "Omar", "Samer", "Rami", "Nour", "Hadi", "Ziad", "Karim",
    "Maya", "Lina", "Sara", "Jana", "Adam", "Yazan", "Tarek", "Bassel",
)


class IchancyHandler:
    """إنشاء حساب ichancy + شحن من البوت + سحب للمنصة"""

    @staticmethod
    def _already_linked_message(user: User) -> str:
        return (
            "✅ لديك حساب Ichancy واحد مرتبط مسبقاً.\n\n"
            f"👤 Username: {tg_code(user.ichancy_username or '—')}\n"
            f"🔑 Password: {tg_code(user.ichancy_password or '—')}\n\n"
            "اضغط على القيم للنسخ\n\n"
            "لا يمكن إنشاء حساب ثانٍ."
        )

    @staticmethod
    def _user_has_account(user: Optional[User]) -> bool:
        return bool(user and (user.ichancy_username or user.ichancy_player_id))

    @staticmethod
    def _store_player_id(user_db_id: int, player_id: str) -> None:
        """حفظ playerId بالخلفية — المستخدم ما بيشوفه."""
        if not player_id or not ichancy_client._is_plausible_player_id(player_id):
            return
        session = db.get_session()
        try:
            db_user = session.query(User).filter(User.id == user_db_id).first()
            if not db_user:
                return
            if str(db_user.ichancy_player_id or "") == str(player_id):
                return
            owner = (
                session.query(User)
                .filter(
                    User.ichancy_player_id == str(player_id),
                    User.id != user_db_id,
                )
                .first()
            )
            if owner:
                logger.warning(
                    "playerId %s already linked to user %s",
                    player_id,
                    owner.telegram_id,
                )
                return
            db_user.ichancy_player_id = str(player_id)
            session.commit()
            print(
                f"[ICHANCY] stored playerId={player_id!r} for user_db_id={user_db_id}",
                flush=True,
            )
        except Exception:
            session.rollback()
            logger.exception("فشل حفظ playerId")
        finally:
            session.close()

    @staticmethod
    def _ensure_platform_player_id(user: User) -> Optional[str]:
        """
        يضمن وجود playerId للمنصة:
        1) من DB إن كان صالح
        2) وإلا بحث getPlayersForCurrentAgent باليوزرنيم (الوثائق)
        """
        if not user:
            return None
        existing = (user.ichancy_player_id or "").strip()
        if existing and ichancy_client._is_plausible_player_id(existing):
            return existing

        username = (user.ichancy_username or "").strip()
        if not username:
            return None

        password = (user.ichancy_password or "").strip()
        print(
            f"[ICHANCY ensure] resolving playerId for username={username!r}",
            flush=True,
        )
        pid = ichancy_client.resolve_player_id_by_username(
            username, password=password, attempts=5
        )
        if pid:
            IchancyHandler._store_player_id(user.id, pid)
            user.ichancy_player_id = pid
        return pid

    @staticmethod
    def _format_remaining(seconds: int) -> str:
        minutes, secs = divmod(max(0, seconds), 60)
        if minutes and secs:
            return f"{minutes} دقيقة و {secs} ثانية"
        if minutes:
            return f"{minutes} دقيقة"
        return f"{secs} ثانية"

    @staticmethod
    def generate_password(length: int = 8) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    @staticmethod
    def normalize_name_part(raw: str):
        """يستخرج الاسم الإنجليزي البسيط من إدخال الزبون."""
        raw = (raw or "").strip().lstrip("@")
        if raw.lower().startswith("na_"):
            raw = raw[3:]
        raw = re.sub(r"[^A-Za-z0-9]", "", raw)
        if not raw:
            return None, (
                "🔴 ابعت اسم إنجليزي بسيط.\n"
                f"مثل: {tg_code('Ali')} أو {tg_code('Omar')}"
            )
        if not raw[0].isalpha():
            return None, (
                "🔴 الاسم لازم يبدأ بحرف إنجليزي.\n"
                f"مثل: {tg_code('Ali')}"
            )
        if len(raw) > 20:
            return None, "🔴 الاسم طويل زيادة. قصّره شوي."
        name = raw[0].upper() + raw[1:]
        return name, None

    @staticmethod
    def build_login_candidates(name_part: str, attempts: int = 30):
        """Na_(اسم)(رقم) مع بدائل تلقائية إذا الاسم محجوز."""
        candidates = []
        has_digit = bool(re.search(r"\d", name_part))
        if has_digit:
            candidates.append(f"{ICHANCY_LOGIN_PREFIX}{name_part}")

        base = re.sub(r"\d+$", "", name_part) or name_part
        base = base[0].upper() + base[1:] if base else name_part
        used = set()
        for _ in range(attempts):
            n = random.randint(10, 99)
            if n in used:
                continue
            used.add(n)
            login = f"{ICHANCY_LOGIN_PREFIX}{base}{n}"
            if login not in candidates:
                candidates.append(login)
        for n in range(10, 100):
            login = f"{ICHANCY_LOGIN_PREFIX}{base}{n}"
            if login not in candidates:
                candidates.append(login)
            if len(candidates) >= attempts + 10:
                break
        return candidates

    @staticmethod
    def is_username_taken_locally(login: str, telegram_id: str) -> bool:
        taken = db.get_user_by_ichancy_username(login)
        return bool(taken and str(taken.telegram_id) != str(telegram_id))

    @staticmethod
    def bot_username_prefix() -> str:
        return ICHANCY_LOGIN_PREFIX.rstrip("_")

    @staticmethod
    def example_username() -> str:
        return f"{ICHANCY_LOGIN_PREFIX}Ali27"

    @staticmethod
    def validate_password(password: str):
        password = password.strip()
        if not re.fullmatch(r"[A-Za-z0-9]{5,32}", password):
            return None, (
                "🔴 كلمة المرور غير صالحة.\n"
                "• من 5 إلى 32\n"
                "• أحرف إنجليزية و/أو أرقام فقط"
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

        if not user.ichancy_player_id and not user.ichancy_username:
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

        platform_balance = "—"
        if ichancy_client.is_configured:
            try:
                player_id = await asyncio.to_thread(
                    IchancyHandler._ensure_platform_player_id, user
                )
                if player_id:
                    balance = await asyncio.to_thread(
                        ichancy_client.get_player_balance, player_id
                    )
                    platform_balance = format_currency(balance)
            except IchancyError:
                platform_balance = "تعذر الجلب"

        text = (
            "🔐 معلومات حسابك في ايشانسي\n\n"
            f"👤 Username: {tg_code(username)}\n"
            f"🔑 Password: {tg_code(password)}\n"
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
        """بداية إنشاء حساب — اسم بسيط فقط."""
        user = db.get_user(update.effective_user.id)
        if not user:
            await safe_edit_callback_message(
                update,
                Config.MESSAGES["user_not_found"],
                reply_markup=Keyboards.ichancy_required_menu(),
                context=context,
            )
            return

        if user.ichancy_username or user.ichancy_player_id:
            await IchancyHandler.show_account_info(update, context)
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
            "👤 سمّي حالك والباقي علينا 😂\n\n"
            "ابعت اسم بسيط بالإنجليزي متل:\n"
            f"{tg_code('Ali')}\n"
            f"{tg_code('Omar')}\n"
            f"{tg_code('Samer')}\n\n"
            "إنت اختار الاسم بس...\n"
            "الـ Na_ والأرقام خليهن شغلة لبوت 😎"
        )
        context.user_data["state"] = "waiting_for_ichancy_username"
        context.user_data["operation"] = "create_ichancy"
        await safe_edit_callback_message(
            update,
            text,
            reply_markup=Keyboards.ichancy_name_prompt(),
            context=context,
            parse_mode="HTML",
        )

    @staticmethod
    async def random_name_and_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
        name = random.choice(RANDOM_NAME_POOL)
        if update.callback_query:
            try:
                await update.callback_query.answer(f"الاسم: {name}")
            except Exception:
                pass
        await IchancyHandler.create_account_from_name(
            update, context, name, via_callback=True
        )

    @staticmethod
    async def process_username(
        update: Update, context: ContextTypes.DEFAULT_TYPE, username: str
    ):
        await IchancyHandler.create_account_from_name(
            update, context, username, via_callback=False
        )

    @staticmethod
    async def create_account_from_name(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        raw_name: str,
        via_callback: bool = False,
    ):
        """يبني Na_Name27 + كلمة سر تلقائية وينشئ الحساب مباشرة."""

        async def reply(msg, **kwargs):
            if via_callback and update.callback_query:
                await safe_edit_callback_message(
                    update, msg, context=context, **kwargs
                )
            elif update.effective_message:
                await update.effective_message.reply_text(msg, **kwargs)

        user = db.get_user(update.effective_user.id)
        if user and IchancyHandler._user_has_account(user):
            context.user_data.clear()
            if via_callback and update.callback_query:
                await IchancyHandler.show_account_info(update, context)
            elif update.effective_message:
                await update.effective_message.reply_text(
                    IchancyHandler._already_linked_message(user),
                    reply_markup=Keyboards.ichancy_account_menu(),
                    parse_mode="HTML",
                )
            return

        name_part, err = IchancyHandler.normalize_name_part(raw_name)
        if err:
            context.user_data["state"] = "waiting_for_ichancy_username"
            await reply(
                err,
                reply_markup=Keyboards.ichancy_name_prompt(),
                parse_mode="HTML",
            )
            return

        if not user:
            context.user_data.clear()
            await reply(
                Config.MESSAGES["user_not_found"],
                reply_markup=Keyboards.ichancy_required_menu(),
            )
            return

        wait_text = "⏳ عم نجهّزلك الحساب... الاسم والرقم علينا"
        wait_msg = None
        if via_callback and update.callback_query:
            await safe_edit_callback_message(update, wait_text, context=context)
        else:
            wait_msg = await update.effective_message.reply_text(wait_text)

        password = IchancyHandler.generate_password(8)
        candidates = IchancyHandler.build_login_candidates(name_part)
        last_error = None
        registered = None
        username = None

        for login in candidates:
            if IchancyHandler.is_username_taken_locally(login, user.telegram_id):
                continue
            email = f"{re.sub(r'[^a-z0-9]', '', login.lower())}@gmail.com"
            try:
                registered = await asyncio.to_thread(
                    ichancy_client.register_player, login, password, email
                )
                username = login
                break
            except IchancyError as exc:
                last_error = exc
                msg = (exc.message or "").lower()
                if any(
                    k in msg
                    for k in (
                        "exist",
                        "already",
                        "duplicate",
                        "taken",
                        "مستخدم",
                        "موجود",
                        "محجوز",
                    )
                ):
                    logger.info("login taken, retry next: %s", login)
                    continue
                break

        async def clear_wait():
            if wait_msg:
                try:
                    await wait_msg.delete()
                except Exception:
                    pass

        if not username or registered is None:
            context.user_data["state"] = "waiting_for_ichancy_username"
            await clear_wait()
            detail = last_error.message if last_error else "تعذر إنشاء الحساب"
            await reply(
                f"❌ فشل إنشاء الحساب:\n{detail}\n\n"
                "جرّب اسماً ثانياً أو اضغط 🎲 سميني انت.",
                reply_markup=Keyboards.ichancy_name_prompt(),
            )
            return

        # المعرف عندنا = اليوزر اللي البوت بيبنيه (Na_...)
        # ما منعتمد على playerId من رد المنصة (غالباً result=1 بس)
        session = db.get_session()
        try:
            db_user = session.query(User).filter(
                User.telegram_id == str(update.effective_user.id)
            ).first()
            if not db_user:
                raise RuntimeError("user missing while saving ichancy")
            if db_user.ichancy_username or db_user.ichancy_player_id:
                context.user_data.clear()
                await clear_wait()
                await reply(
                    IchancyHandler._already_linked_message(db_user),
                    reply_markup=Keyboards.ichancy_account_menu(),
                    parse_mode="HTML",
                )
                return
            db_user.ichancy_username = username
            db_user.ichancy_password = password
            session.commit()
            user_db_id = db_user.id
            print(
                f"[ICHANCY create] SAVED username={username!r} "
                f"telegram={update.effective_user.id} — resolving playerId next",
                flush=True,
            )
            logger.info(
                "Ichancy account saved user=%s login=%s — will resolve playerId",
                update.effective_user.id,
                username,
            )
        except Exception:
            session.rollback()
            logger.exception("فشل حفظ حساب Ichancy")
            context.user_data.clear()
            await clear_wait()
            await reply(
                "❌ الحساب انخلق على المنصة بس فشل الحفظ بالبوت.\n"
                f"Username: {tg_code(username)}\n"
                f"Password: {tg_code(password)}\n\n"
                "تواصل مع الدعم.",
                reply_markup=Keyboards.ichancy_required_menu(),
                parse_mode="HTML",
            )
            return
        finally:
            session.close()

        # خلفية: اليوزرنيم → getPlayersForCurrentAgent → playerId (الوثائق)
        try:
            player_id = await asyncio.to_thread(
                ichancy_client.resolve_player_id_by_username,
                username,
                password,
                6,
            )
            if player_id:
                IchancyHandler._store_player_id(user_db_id, player_id)
            else:
                logger.warning(
                    "create OK but playerId not resolved yet for %s", username
                )
        except Exception:
            logger.exception("فشل جلب playerId بعد الإنشاء لـ %s", username)

        try:
            from referral_service import (
                ReferralArmyService,
                STATUS_PENDING,
                STATUS_REJECTED,
            )
            refreshed = db.get_user(update.effective_user.id)
            status = ReferralArmyService.evaluate_after_ichancy_link(refreshed)
            if status == STATUS_PENDING and refreshed.referred_by:
                try:
                    await context.bot.send_message(
                        chat_id=refreshed.referred_by,
                        text=(
                            "🟠 قيد التحقق\n\n"
                            "رفيقك عمل حساب iChancy\n"
                            "بانتظار النشاط المؤهل ومراجعة الإدارة"
                        ),
                    )
                except Exception:
                    pass
            elif status == STATUS_REJECTED:
                # جلب سبب الرفض
                reason = "حساب مكرر أو غير مؤهل"
                try:
                    session = db.get_session()
                    try:
                        from database import ReferralInvite
                        inv = (
                            session.query(ReferralInvite)
                            .filter(ReferralInvite.invitee_id == refreshed.id)
                            .first()
                        )
                        if inv and inv.reject_reason:
                            reason = inv.reject_reason
                    finally:
                        session.close()
                except Exception:
                    pass
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_user.id,
                        text=(
                            "🔴 إحالتك غير مؤهلة ضمن جيش نابليون\n\n"
                            f"السبب\n{reason}"
                        ),
                    )
                except Exception:
                    pass
                if refreshed.referred_by:
                    try:
                        await context.bot.send_message(
                            chat_id=refreshed.referred_by,
                            text=(
                                "🔴 إحالة بجيشك صارت غير مؤهلة\n\n"
                                f"السبب\n{reason}"
                            ),
                        )
                    except Exception:
                        pass
        except Exception:
            logger.exception("فشل تقييم إحالة بعد إنشاء Ichancy")

        context.user_data.clear()
        await clear_wait()
        await reply(
            "✅ تم إنشاء حسابك بنجاح\n"
            "معلومات الحساب هي:\n\n"
            f"اسم المستخدم: {tg_code(username)}\n"
            f"كلمة السر: {tg_code(password)}\n\n"
            "اضغط على القيم للنسخ\n\n"
            "⚠️ هذا حسابك الوحيد المرتبط بهذا البوت.\n"
            "✅ تم فتح باقي خدمات البوت.",
            parse_mode="HTML",
            reply_markup=Keyboards.start_menu(),
        )

    @staticmethod
    async def process_password(
        update: Update, context: ContextTypes.DEFAULT_TYPE, password: str
    ):
        """توافق خلفي — الإنشاء صار تلقائي من الاسم فقط."""
        raw = context.user_data.get("ichancy_new_username") or ""
        if raw.lower().startswith("na_"):
            raw = raw[3:]
        if raw:
            await IchancyHandler.create_account_from_name(update, context, raw)
            return
        context.user_data.clear()
        await update.message.reply_text(
            "ابدأ إنشاء الحساب من زر 🎮 بدّي حساب iChancy",
            reply_markup=Keyboards.start_menu(),
        )

    @staticmethod
    async def start_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شحن iChancy باليوزرنيم — بدون ID."""
        user = db.get_user(update.effective_user.id)
        min_topup = Config.ICHANCY_CONFIG.get("min_topup", 200)

        if not IchancyHandler._user_has_account(user):
            await safe_edit_callback_message(
                update,
                "❌ أنشئ حساب Ichancy أولاً من الزر أدناه.",
                reply_markup=Keyboards.ichancy_required_menu(),
                context=context,
            )
            return

        text = (
            "💸 شحن حساب iChancy\n\n"
            f"الحساب: {tg_code(user.ichancy_username)}\n\n"
            "هلق ابعت مبلغ التعبئة كتابه فقط\n\n"
            "اكتب المبلغ العمله الجديده يا ملك\n\n"
            "مثال:\n"
            f"{tg_code('250')}\n\n"
            "بلا فواصل\n"
            "المحاسب ما ناقصه ألغاز اليوم 😂\n\n"
            f"💵 رصيد البوت: {format_currency(user.balance)}\n"
            f"اقل مبلغ ايداع : {format_currency(min_topup)} ل.س\n\n"
            "اكتبه بالليره الجديده وبتلاقيه بحسابك بالليره القديمه"
        )
        context.user_data["state"] = "waiting_for_amount"
        context.user_data["operation"] = "ichancy_topup"
        context.user_data["method"] = "ichancy"
        await safe_edit_callback_message(
            update,
            text,
            reply_markup=Keyboards.cancel_operation(),
            context=context,
            parse_mode="HTML",
        )

    # توافق خلفي مع أزرار قديمة
    start_topup_ask_id = start_topup

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

        if not IchancyHandler._user_has_account(user):
            context.user_data.clear()
            await update.message.reply_text(
                "❌ أنشئ حساب Ichancy أولاً من زر إنشاء الحساب.",
                reply_markup=Keyboards.ichancy_required_menu(),
            )
            return

        wait = await update.message.reply_text("⌛ لحظات من فضلك")
        try:
            player_id = await asyncio.to_thread(
                IchancyHandler._ensure_platform_player_id, user
            )
        except Exception:
            logger.exception("فشل resolve playerId قبل التعبئة")
            player_id = None

        if not player_id:
            try:
                await wait.delete()
            except Exception:
                pass
            context.user_data.clear()
            await update.message.reply_text(
                "❌ تعذر ربط حساب المنصة حالياً.\n"
                "جرّب بعد لحظات أو تواصل مع الدعم.",
                reply_markup=Keyboards.ichancy_account_menu(),
            )
            return

        print(
            f"[ICHANCY topup] user={user.telegram_id} username={user.ichancy_username!r} "
            f"playerId={player_id!r} amount={amount}",
            flush=True,
        )
        # #region agent log
        _agent_dbg(
            "B,D",
            "ichancy_handler.py:process_topup",
            "topup before API",
            {
                "username": user.ichancy_username,
                "player_id": player_id,
                "amount": amount,
                "balance": float(user.balance or 0),
                "db_player_id": user.ichancy_player_id,
            },
        )
        # #endregion

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
                    f"user={user.ichancy_username} playerId={player_id}"
                ),
            )
            session.add(transaction)
            db_user.balance -= amount
            session.commit()
            session.refresh(transaction)

            try:
                result = await asyncio.to_thread(
                    ichancy_client.deposit_to_player,
                    player_id,
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
                # #region agent log
                _agent_dbg(
                    "A,B,C,D,E",
                    "ichancy_handler.py:process_topup",
                    "topup IchancyError",
                    {"error": exc.message, "status_code": getattr(exc, "status_code", None), "amount": amount, "player_id": player_id},
                )
                # #endregion
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
        """ما عاد في ربط بـ ID — الهوية = اليوزرنيم."""
        context.user_data.clear()
        user = db.get_user(update.effective_user.id)
        if IchancyHandler._user_has_account(user):
            await update.message.reply_text(
                IchancyHandler._already_linked_message(user),
                reply_markup=Keyboards.ichancy_account_menu(),
                parse_mode="HTML",
            )
            return
        await update.message.reply_text(
            "❌ ما عاد في حاجة لـ ID.\nأنشئ حسابك من داخل البوت — اليوزرنيم يكفي.",
            reply_markup=Keyboards.ichancy_required_menu(),
        )

    @staticmethod
    async def process_topup_player_id(
        update: Update, context: ContextTypes.DEFAULT_TYPE, player_ref: str
    ):
        """توافق خلفي — ما عاد في ID؛ نرجّع لطلب المبلغ."""
        await update.message.reply_text(
            "ما عاد بدنا ID 😂\nالحساب مربوط باليوزرنيم.\nابعت مبلغ التعبئة أرقام فقط.",
            reply_markup=Keyboards.cancel_operation(),
        )
        context.user_data["state"] = "waiting_for_amount"
        context.user_data["operation"] = "ichancy_topup"
        context.user_data["method"] = "ichancy"

    @staticmethod
    async def process_withdraw_player_id(
        update: Update, context: ContextTypes.DEFAULT_TYPE, player_ref: str
    ):
        """توافق خلفي — ما عاد في ID؛ نرجّع لطلب المبلغ."""
        await update.message.reply_text(
            "ما عاد بدنا ID 😂\nالحساب مربوط باليوزرنيم.\nابعت مبلغ السحب أرقام فقط.",
            reply_markup=Keyboards.cancel_operation(),
        )
        context.user_data["state"] = "waiting_for_amount"
        context.user_data["operation"] = "ichancy_withdraw"

    @staticmethod
    async def start_withdraw_from_ichancy(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """سحب من ichancy إلى محفظة البوت باليوزرنيم — بدون ID."""
        user = db.get_user(update.effective_user.id)

        if not IchancyHandler._user_has_account(user):
            await safe_edit_callback_message(
                update,
                "❌ أنشئ حساب Ichancy أولاً من الزر أدناه.",
                reply_markup=Keyboards.ichancy_required_menu(),
                context=context,
            )
            return

        if not user.ichancy_username:
            await safe_edit_callback_message(
                update,
                "❌ حسابك بدون يوزرنيم محفوظ.\nأنشئ حساب جديد من البوت.",
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
        message = (
            "⬇️ سحب رصيد الحساب إلى محفظة البوت\n\n"
            f"الحساب: {tg_code(user.ichancy_username)}\n"
            f"⏱ بعد السحب: انتظار {cooldown_minutes} دقيقة قبل سحب آخر\n\n"
            f"أرسل المبلغ الذي تريد سحبه من ichancy ({currency}):"
        )
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

        if not IchancyHandler._user_has_account(user):
            context.user_data.clear()
            await update.message.reply_text(
                "❌ أنشئ حساب Ichancy أولاً.",
                reply_markup=Keyboards.ichancy_required_menu(),
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

        try:
            player_id = await asyncio.to_thread(
                IchancyHandler._ensure_platform_player_id, user
            )
        except Exception:
            logger.exception("فشل resolve playerId قبل السحب")
            player_id = None

        if not player_id:
            context.user_data.clear()
            await update.message.reply_text(
                "❌ تعذر ربط حساب المنصة حالياً.\n"
                "جرّب بعد لحظات أو تواصل مع الدعم.",
                reply_markup=Keyboards.ichancy_account_menu(),
            )
            return

        print(
            f"[ICHANCY withdraw] user={user.telegram_id} "
            f"username={user.ichancy_username!r} playerId={player_id!r} "
            f"amount={validated_amount}",
            flush=True,
        )

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
                    f"user={user.ichancy_username} playerId={player_id}"
                ),
            )
            session.add(transaction)
            session.commit()
            session.refresh(transaction)

            try:
                platform_balance = await asyncio.to_thread(
                    ichancy_client.get_player_balance, player_id
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
                    player_id,
                    validated_amount,
                    f"Bot wallet {user.telegram_id} REF:{reference}",
                )

                external_id = f"ICH_{reference}_{player_id}"
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
