"""
قاعدة البيانات المحدثة للبوت التليجرام - ichancy.com
"""

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import uuid
import os
from pathlib import Path


def _prepare_database_url(database_url: str) -> str:
    """تجهيز مسار SQLite وإنشاء المجلد إن لم يكن موجوداً"""
    if not database_url.startswith("sqlite"):
        return database_url

    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return database_url

    raw_path = database_url[len(prefix):]
    if raw_path.startswith("/"):
        db_path = Path(raw_path)
    else:
        project_root = Path(__file__).resolve().parent
        db_path = (project_root / raw_path).resolve()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def get_database_url(database_url: str | None = None) -> str:
    """رابط قاعدة البيانات المحلية على VPS (SQLite داخل مجلد المشروع)"""
    if database_url is None:
        database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        project_root = Path(__file__).resolve().parent
        db_path = project_root / "data" / "telegram_bot.db"
        database_url = f"sqlite:///{db_path.as_posix()}"
    return _prepare_database_url(database_url)


def get_local_db_file_path(database_url: str) -> Path | None:
    """مسار ملف SQLite على القرص (للعرض في اللوج)"""
    if not database_url.startswith("sqlite:///"):
        return None
    return Path(database_url[len("sqlite:///"):])


Base = declarative_base()

class User(Base):
    """جدول المستخدمين"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String(50), unique=True, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    last_name = Column(String(100))
    balance = Column(Float, default=0.0)
    referral_code = Column(String(20), unique=True)
    referred_by = Column(String(20))
    referral_count = Column(Integer, default=0)
    referral_earnings = Column(Float, default=0.0)
    # جيش نابليون — أرصدة عمولة منفصلة عن رصيد المحفظة
    commission_available = Column(Float, default=0.0)
    commission_pending = Column(Float, default=0.0)
    commission_withdrawn = Column(Float, default=0.0)
    referral_rank_override = Column(String(40))  # رتبة يدوية من الأدمن
    total_bets = Column(Float, default=0.0)
    total_wins = Column(Float, default=0.0)
    vip_level = Column(String(20), default='beginner')
    is_admin = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    ichancy_player_id = Column(String(100), unique=True)
    ichancy_username = Column(String(100))
    ichancy_password = Column(String(100))
    last_syriatel_code = Column(String(50))
    terms_accepted_at = Column(DateTime)
    reserved_balance = Column(Float, default=0.0)  # مبالغ سحب محجوزة
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)
    
    # العلاقات
    transactions = relationship("Transaction", back_populates="user")
    sent_gifts = relationship("Gift", foreign_keys="Gift.sender_id", back_populates="sender")
    received_gifts = relationship("Gift", foreign_keys="Gift.receiver_id", back_populates="receiver")
    bets = relationship("Bet", back_populates="user")
    jackpot_entries = relationship("JackpotEntry", back_populates="user")
    jackpot_wins = relationship("JackpotWin", back_populates="user")
    saved_payment_accounts = relationship("SavedPaymentAccount", back_populates="user")

class Transaction(Base):
    """جدول المعاملات المالية"""
    __tablename__ = 'transactions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    transaction_type = Column(String(30), nullable=False)  # deposit, withdraw, referral, gift, bet_win, bet_loss, jackpot_win, jackpot_contribution
    amount = Column(Float, nullable=False)
    method = Column(String(50))  # syriatel_cash, shamcash, usdt
    status = Column(String(20), default='pending')  # pending, completed, failed, cancelled
    description = Column(Text)
    admin_notes = Column(Text)
    external_transaction_id = Column(String(100))  # معرف المعاملة الخارجية
    expected_usdt_amount = Column(Float)  # مبلغ USDT الفريد للإيداع
    withdraw_destination = Column(String(200))  # وجهة السحب (رقم/محفظة)
    fee_amount = Column(Float)  # عمولة السحب
    net_amount = Column(Float)  # الصافي للمستلم
    profit_amount = Column(Float)  # ربح محتسب ضمن المبلغ
    cancel_requested_at = Column(DateTime)
    cancel_rejection_reason = Column(Text)
    crypto_currency = Column(String(20))
    crypto_network = Column(String(20))
    decided_by_name = Column(String(120))  # اسم الأدمن عند القرار
    decided_by_telegram_id = Column(Integer)  # آيدي تليغرام للأدمن
    decided_at = Column(DateTime)  # وقت قرار الإدارة
    public_id = Column(String(40), unique=True, index=True)  # رقم طلب فريد للعرض
    assigned_admin_telegram_id = Column(Integer)  # قفل تنفيذ متزامن
    assigned_admin_name = Column(String(120))
    accepted_at = Column(DateTime)
    paid_at = Column(DateTime)
    admin_group_chat_id = Column(String(50))
    admin_group_message_id = Column(Integer)
    user_track_chat_id = Column(String(50))
    user_track_message_id = Column(Integer)
    status_before_cancel = Column(String(30))
    reject_reason_code = Column(String(40))
    payout_method_code = Column(String(50))  # رمز طريقة التقبيض من payout_methods
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)
    
    # العلاقات
    user = relationship("User", back_populates="transactions")


class PayoutMethod(Base):
    """طرق تقبيض قابلة للتوسعة من لوحة الإدارة"""
    __tablename__ = "payout_methods"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    enabled = Column(Boolean, default=False)
    min_amount = Column(Float)  # اختياري — يتجاوز الحد العام إن وُجد
    max_amount = Column(Float)
    # JSON list مثل: ["shamcash_address"] أو ["phone"] أو ["wallet","network"]
    required_fields = Column(Text, default="[]")
    admin_group_id = Column(String(50))  # كروب مسؤول عن هذه الطريقة
    instructions = Column(Text)
    sort_order = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SupportTicket(Base):
    """تذكرة دعم مربوطة بطلب سحب/تقبيض"""
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("transactions.id"), nullable=True, index=True)
    status = Column(String(30), default="open", index=True)  # open | resolved | escalated
    subject = Column(String(200))
    support_group_chat_id = Column(String(50))
    support_group_message_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)
    resolved_by_name = Column(String(120))
    escalated_at = Column(DateTime)


class SupportTicketMessage(Base):
    """رسائل داخل تذكرة الدعم"""
    __tablename__ = "support_ticket_messages"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("support_tickets.id"), nullable=False, index=True)
    direction = Column(String(20), nullable=False)  # user_to_support | support_to_user
    content = Column(Text, nullable=False)
    sender_telegram_id = Column(Integer)
    sender_name = Column(String(120))  # داخلي فقط — لا يُعرض للمستخدم كحساب شخصي
    created_at = Column(DateTime, default=datetime.utcnow)

class Gift(Base):
    """جدول الهدايا بين المستخدمين"""
    __tablename__ = 'gifts'
    
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    receiver_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    amount = Column(Float, nullable=False)
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # العلاقات
    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_gifts")
    receiver = relationship("User", foreign_keys=[receiver_id], back_populates="received_gifts")

class GiftCode(Base):
    """جدول أكواد الهدايا"""
    __tablename__ = 'gift_codes'
    
    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    amount = Column(Float, nullable=False)
    max_uses = Column(Integer, default=1)
    current_uses = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)  # False = ملغي
    # مخصص لمستخدم معيّن (telegram_id) أو NULL للجميع
    assigned_telegram_id = Column(String(50), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    cancelled_at = Column(DateTime)
    cancel_reason = Column(Text)

class GiftCodeUsage(Base):
    """سجل استخدام / رفض أكواد الهدايا"""
    __tablename__ = 'gift_code_usage'
    
    id = Column(Integer, primary_key=True)
    code_id = Column(Integer, ForeignKey('gift_codes.id'), nullable=True, index=True)
    code_text = Column(String(50), index=True)  # النص كما أدخله المستخدم
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    amount = Column(Float, default=0.0)
    # success | rejected
    status = Column(String(20), default="success", index=True)
    reject_reason = Column(Text)
    used_at = Column(DateTime, default=datetime.utcnow)

class Bet(Base):
    """جدول الرهانات"""
    __tablename__ = 'bets'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    game_type = Column(String(50), nullable=False)  # casino, sports
    game_category = Column(String(50))  # slots, football, etc.
    game_name = Column(String(100))
    bet_amount = Column(Float, nullable=False)
    potential_win = Column(Float)
    actual_win = Column(Float, default=0.0)
    odds = Column(Float)
    status = Column(String(20), default='pending')  # pending, won, lost, cancelled
    bet_details = Column(Text)  # JSON string with bet details
    ichancy_bet_id = Column(String(100))  # معرف الرهان في ichancy
    placed_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime)
    
    # العلاقات
    user = relationship("User", back_populates="bets")

class JackpotEntry(Base):
    """جدول مشاركات الجاكبوت"""
    __tablename__ = 'jackpot_entries'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    bet_id = Column(Integer, ForeignKey('bets.id'))
    contribution_amount = Column(Float, nullable=False)
    jackpot_pool_id = Column(String(50))  # معرف مجموعة الجاكبوت
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # العلاقات
    user = relationship("User", back_populates="jackpot_entries")
    bet = relationship("Bet")

class JackpotWin(Base):
    """جدول أرباح الجاكبوت"""
    __tablename__ = 'jackpot_wins'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    jackpot_pool_id = Column(String(50), nullable=False)
    win_amount = Column(Float, nullable=False)
    total_pool = Column(Float, nullable=False)
    participants_count = Column(Integer, default=0)
    win_date = Column(DateTime, default=datetime.utcnow)
    
    # العلاقات
    user = relationship("User", back_populates="jackpot_wins")

class GameSession(Base):
    """جدول جلسات الألعاب"""
    __tablename__ = 'game_sessions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    session_id = Column(String(100), unique=True)
    game_type = Column(String(50), nullable=False)
    start_balance = Column(Float, nullable=False)
    end_balance = Column(Float)
    total_bets = Column(Float, default=0.0)
    total_wins = Column(Float, default=0.0)
    session_duration = Column(Integer)  # بالثواني
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)
    
    # العلاقات
    user = relationship("User")

class Promotion(Base):
    """جدول العروض والمكافآت"""
    __tablename__ = 'promotions'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    promo_type = Column(String(50), nullable=False)  # welcome, deposit, cashback, etc.
    bonus_amount = Column(Float)
    bonus_percentage = Column(Float)
    min_deposit = Column(Float)
    max_bonus = Column(Float)
    wagering_requirement = Column(Float)
    is_active = Column(Boolean, default=True)
    valid_from = Column(DateTime, default=datetime.utcnow)
    valid_until = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserPromotion(Base):
    """جدول استخدام المستخدمين للعروض"""
    __tablename__ = 'user_promotions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    promotion_id = Column(Integer, ForeignKey('promotions.id'), nullable=False)
    bonus_amount = Column(Float, nullable=False)
    wagering_completed = Column(Float, default=0.0)
    wagering_required = Column(Float, nullable=False)
    status = Column(String(20), default='active')  # active, completed, expired
    claimed_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    
    # العلاقات
    user = relationship("User")
    promotion = relationship("Promotion")

class Message(Base):
    """جدول الرسائل بين المستخدمين والإدمن"""
    __tablename__ = 'messages'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    admin_id = Column(Integer, ForeignKey('users.id'))
    message_type = Column(String(20), nullable=False)  # user_to_admin, admin_to_user
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # العلاقات
    user = relationship("User", foreign_keys=[user_id])
    admin = relationship("User", foreign_keys=[admin_id])

class SystemLog(Base):
    """جدول سجلات النظام"""
    __tablename__ = 'system_logs'
    
    id = Column(Integer, primary_key=True)
    log_type = Column(String(50), nullable=False)  # error, warning, info
    module = Column(String(100))
    message = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # العلاقات
    user = relationship("User")


class BotSetting(Base):
    """إعدادات البوت القابلة للتعديل من الإدمن (مثل سعر الصرف)"""
    __tablename__ = 'bot_settings'

    key = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReferralInvite(Base):
    """سجل إحالة ضمن جيش نابليون"""
    __tablename__ = "referral_invites"

    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    invitee_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    # registered | pending_verify | active | rejected
    status = Column(String(30), default="registered", index=True)
    reject_reason = Column(String(255))
    # صافي النشاط المؤهل بالليرة (من مراجعة يدوية / API لاحقاً)
    qualified_net_syp = Column(Float, default=0.0)
    qualified_net_usd = Column(Float, default=0.0)
    activity_source = Column(String(50), default="manual")  # manual | api | none
    activated_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CommissionEntry(Base):
    """سجل عمولة / تسوية / سحب لجيش نابليون"""
    __tablename__ = "commission_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # accrual | release | withdraw | withdraw_request | adjustment
    entry_type = Column(String(30), nullable=False)
    # pending_review | available | awaiting_payout | withdrawn | cancelled | adjusted
    status = Column(String(30), default="pending_review", index=True)
    amount = Column(Float, nullable=False, default=0.0)
    rank_code = Column(String(40))
    rate_percent = Column(Float, default=0.0)
    net_activity_syp = Column(Float, default=0.0)
    invite_id = Column(Integer, ForeignKey("referral_invites.id"), nullable=True)
    payout_method = Column(String(50))
    payout_destination = Column(String(200))
    crypto_currency = Column(String(20))
    crypto_network = Column(String(20))
    description = Column(Text)
    admin_notes = Column(Text)
    available_at = Column(DateTime)  # بعد انتهاء مدة المراجعة
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)


class ArmyAuditLog(Base):
    """سجل تعديلات إدارة جيش نابليون"""
    __tablename__ = "army_audit_logs"

    id = Column(Integer, primary_key=True)
    admin_telegram_id = Column(Integer, index=True)
    admin_name = Column(String(120))
    action = Column(String(80), nullable=False, index=True)
    target_type = Column(String(40))  # invite | commission | setting | user
    target_id = Column(String(80))
    before_value = Column(Text)
    after_value = Column(Text)
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserFunStat(Base):
    """إحصائيات ترفيهية خفيفة (إنجازات / تقرير / ألقاب) — بلا بيانات حساسة"""
    __tablename__ = "user_fun_stats"

    user_id = Column(Integer, primary_key=True)
    back_clicks = Column(Integer, default=0)
    cancel_count = Column(Integer, default=0)
    support_count = Column(Integer, default=0)
    forbidden_presses = Column(Integer, default=0)
    home_opens = Column(Integer, default=0)
    home_opens_today = Column(Integer, default=0)
    home_opens_day = Column(String(10))
    opinion_changes = Column(Integer, default=0)
    correct_tx_first = Column(Integer, default=0)
    terms_read = Column(Boolean, default=False)
    unlocked = Column(Text, default="[]")  # JSON list of achievement codes
    title_override = Column(String(80))
    last_rare_date = Column(String(10))
    week_start = Column(String(10))
    week_logins = Column(Integer, default=0)
    week_orders = Column(Integer, default=0)
    week_backs = Column(Integer, default=0)
    week_cancels = Column(Integer, default=0)
    week_support = Column(Integer, default=0)
    week_achievements = Column(Integer, default=0)
    akhira_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SavedPaymentAccount(Base):
    """أرقام/حسابات محفوظة للزبون (سيريتل كاش / شام كاش)"""
    __tablename__ = 'saved_payment_accounts'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    account_type = Column(String(30), nullable=False)  # syriatel_cash, shamcash
    account_value = Column(String(200), nullable=False)
    label = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="saved_payment_accounts")


class DatabaseManager:
    """مدير قاعدة البيانات"""
    
    def __init__(self, database_url=None):
        self.database_url = get_database_url(database_url)
        self.db_file_path = get_local_db_file_path(self.database_url)
        self.engine = create_engine(
            self.database_url,
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False,
        )
        self.func = func  # إضافة func للاستعلامات المتقدمة
        
    def create_tables(self):
        """إنشاء الجداول"""
        Base.metadata.create_all(bind=self.engine)
        self._run_migrations()

    def _run_migrations(self):
        """ترقيات بسيطة لقاعدة البيانات"""
        from sqlalchemy import inspect, text

        inspector = inspect(self.engine)
        if "transactions" not in inspector.get_table_names():
            return

        columns = {col["name"] for col in inspector.get_columns("transactions")}
        with self.engine.begin() as conn:
            if "expected_usdt_amount" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN expected_usdt_amount FLOAT"))
            if "withdraw_destination" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN withdraw_destination VARCHAR(200)"))
            if "fee_amount" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN fee_amount FLOAT"))
            if "net_amount" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN net_amount FLOAT"))
            if "profit_amount" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN profit_amount FLOAT"))
            if "cancel_requested_at" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN cancel_requested_at TIMESTAMP"))
            if "cancel_rejection_reason" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN cancel_rejection_reason TEXT"))
            if "crypto_currency" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN crypto_currency VARCHAR(20)"))
            if "crypto_network" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN crypto_network VARCHAR(20)"))
            if "decided_by_name" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN decided_by_name VARCHAR(120)"))
            if "decided_by_telegram_id" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN decided_by_telegram_id INTEGER"))
            if "decided_at" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN decided_at TIMESTAMP"))
            if "public_id" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN public_id VARCHAR(40)"))
            if "assigned_admin_telegram_id" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN assigned_admin_telegram_id INTEGER"))
            if "assigned_admin_name" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN assigned_admin_name VARCHAR(120)"))
            if "accepted_at" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN accepted_at TIMESTAMP"))
            if "paid_at" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN paid_at TIMESTAMP"))
            if "admin_group_chat_id" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN admin_group_chat_id VARCHAR(50)"))
            if "admin_group_message_id" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN admin_group_message_id INTEGER"))
            if "user_track_chat_id" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN user_track_chat_id VARCHAR(50)"))
            if "user_track_message_id" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN user_track_message_id INTEGER"))
            if "status_before_cancel" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN status_before_cancel VARCHAR(30)"))
            if "reject_reason_code" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN reject_reason_code VARCHAR(40)"))
            if "payout_method_code" not in columns:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN payout_method_code VARCHAR(50)"))
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "ix_transactions_public_id ON transactions(public_id)"
                    )
                )
            except Exception:
                pass

        self._seed_payout_methods()

        if "users" in inspector.get_table_names():
            user_columns = {col["name"] for col in inspector.get_columns("users")}
            with self.engine.begin() as conn:
                if "ichancy_player_id" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN ichancy_player_id VARCHAR(100)"))
                if "ichancy_username" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN ichancy_username VARCHAR(100)"))
                if "ichancy_password" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN ichancy_password VARCHAR(100)"))
                if "last_syriatel_code" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_syriatel_code VARCHAR(50)"))
                if "terms_accepted_at" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN terms_accepted_at TIMESTAMP"))
                if "commission_available" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN commission_available FLOAT DEFAULT 0"))
                if "commission_pending" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN commission_pending FLOAT DEFAULT 0"))
                if "commission_withdrawn" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN commission_withdrawn FLOAT DEFAULT 0"))
                if "referral_rank_override" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN referral_rank_override VARCHAR(40)"))
                if "reserved_balance" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN reserved_balance FLOAT DEFAULT 0"))

            # حساب Ichancy واحد فقط لكل مستخدم — فهرس فريد على player_id
            with self.engine.begin() as conn:
                try:
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS "
                            "ix_users_ichancy_player_id ON users(ichancy_player_id)"
                        )
                    )
                except Exception:
                    pass

            # تنظيف معرفات وهمية: registerPlayer كان يرجع result=1 فيُحفظ كـ playerId
            with self.engine.begin() as conn:
                try:
                    result = conn.execute(
                        text(
                            "UPDATE users SET ichancy_player_id = NULL "
                            "WHERE ichancy_player_id IN ('0', '1')"
                        )
                    )
                    if result.rowcount:
                        import logging
                        logging.getLogger(__name__).warning(
                            "Cleared %s bogus ichancy_player_id values (0/1)",
                            result.rowcount,
                        )
                except Exception:
                    pass

        # أعمدة سحب العمولة على commission_entries
        if "commission_entries" in inspector.get_table_names():
            ce_cols = {col["name"] for col in inspector.get_columns("commission_entries")}
            with self.engine.begin() as conn:
                if "invite_id" not in ce_cols:
                    conn.execute(text("ALTER TABLE commission_entries ADD COLUMN invite_id INTEGER"))
                if "payout_method" not in ce_cols:
                    conn.execute(text("ALTER TABLE commission_entries ADD COLUMN payout_method VARCHAR(50)"))
                if "payout_destination" not in ce_cols:
                    conn.execute(text("ALTER TABLE commission_entries ADD COLUMN payout_destination VARCHAR(200)"))
                if "crypto_currency" not in ce_cols:
                    conn.execute(text("ALTER TABLE commission_entries ADD COLUMN crypto_currency VARCHAR(20)"))
                if "crypto_network" not in ce_cols:
                    conn.execute(text("ALTER TABLE commission_entries ADD COLUMN crypto_network VARCHAR(20)"))

        # أكواد الهدايا — تخصيص + سجل رفض
        if "gift_codes" in inspector.get_table_names():
            gc_cols = {col["name"] for col in inspector.get_columns("gift_codes")}
            with self.engine.begin() as conn:
                if "assigned_telegram_id" not in gc_cols:
                    conn.execute(text("ALTER TABLE gift_codes ADD COLUMN assigned_telegram_id VARCHAR(50)"))
                if "cancelled_at" not in gc_cols:
                    conn.execute(text("ALTER TABLE gift_codes ADD COLUMN cancelled_at TIMESTAMP"))
                if "cancel_reason" not in gc_cols:
                    conn.execute(text("ALTER TABLE gift_codes ADD COLUMN cancel_reason TEXT"))

        if "gift_code_usage" in inspector.get_table_names():
            gu_cols = {col["name"] for col in inspector.get_columns("gift_code_usage")}
            with self.engine.begin() as conn:
                if "code_text" not in gu_cols:
                    conn.execute(text("ALTER TABLE gift_code_usage ADD COLUMN code_text VARCHAR(50)"))
                if "amount" not in gu_cols:
                    conn.execute(text("ALTER TABLE gift_code_usage ADD COLUMN amount FLOAT DEFAULT 0"))
                if "status" not in gu_cols:
                    conn.execute(text("ALTER TABLE gift_code_usage ADD COLUMN status VARCHAR(20) DEFAULT 'success'"))
                if "reject_reason" not in gu_cols:
                    conn.execute(text("ALTER TABLE gift_code_usage ADD COLUMN reject_reason TEXT"))

    def _seed_payout_methods(self):
        """طرق تقبيض افتراضية — شام كاش مفعّلة فقط حالياً."""
        import json

        defaults = [
            {
                "code": "shamcash",
                "name": "💠 شام كاش",
                "enabled": True,
                "required_fields": ["shamcash_address"],
                "instructions": (
                    "ابعت عنوان محفظة شام كاش اللي بدك تستلم عليه\n"
                    "انسخه مثل ما هو:\n\n"
                    "راجع العنوان منيح\n"
                    "لانه بعد التقبيض ما عاد فينا نقول كانت تجربة 😂"
                ),
                "sort_order": 10,
            },
            {
                "code": "syriatel_cash",
                "name": "📱 سيرياتيل كاش",
                "enabled": False,
                "required_fields": ["phone"],
                "instructions": (
                    "ابعت رقم سيرياتيل كاش اللي بدك تستلم عليه\n\n"
                    "مثال\n09XXXXXXXX\n\n"
                    "راجع الرقم منيح"
                ),
                "sort_order": 20,
            },
            {
                "code": "usdt",
                "name": "🌐 USDT",
                "enabled": False,
                "required_fields": ["wallet", "network"],
                "instructions": (
                    "ابعت عنوان محفظة USDT مع الشبكة الصحيحة\n"
                    "الشبكة الغلط بتاخد المصاري"
                ),
                "sort_order": 30,
            },
            {
                "code": "bank_transfer",
                "name": "🏦 حوالة",
                "enabled": False,
                "required_fields": ["bank_details"],
                "instructions": "ابعت بيانات الحوالة كاملة كما هي في البنك.",
                "sort_order": 40,
            },
        ]
        session = self.get_session()
        try:
            for item in defaults:
                exists = (
                    session.query(PayoutMethod)
                    .filter(PayoutMethod.code == item["code"])
                    .first()
                )
                if exists:
                    continue
                session.add(
                    PayoutMethod(
                        code=item["code"],
                        name=item["name"],
                        enabled=item["enabled"],
                        required_fields=json.dumps(
                            item["required_fields"], ensure_ascii=False
                        ),
                        instructions=item["instructions"],
                        sort_order=item["sort_order"],
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def get_session(self):
        """الحصول على جلسة قاعدة البيانات"""
        return self.SessionLocal()

    def _detach(self, session, obj):
        """فصل الكائن عن الجلسة مع تحميل كل الأعمدة (يمنع DetachedInstanceError)"""
        if obj is None:
            return None
        session.refresh(obj)
        session.expunge(obj)
        return obj
        
    def generate_referral_code(self):
        """توليد كود إحالة فريد"""
        return str(uuid.uuid4())[:8].upper()
        
    def create_user(self, telegram_id, username=None, first_name=None, last_name=None):
        """إنشاء مستخدم جديد"""
        session = self.get_session()
        try:
            # التحقق من وجود المستخدم
            existing_user = session.query(User).filter(User.telegram_id == str(telegram_id)).first()
            if existing_user:
                return self._detach(session, existing_user)
                
            # إنشاء مستخدم جديد
            referral_code = self.generate_referral_code()
            while session.query(User).filter(User.referral_code == referral_code).first():
                referral_code = self.generate_referral_code()
                
            user = User(
                telegram_id=str(telegram_id),
                username=username,
                first_name=first_name,
                last_name=last_name,
                referral_code=referral_code
            )
            session.add(user)
            session.commit()
            return self._detach(session, user)
        finally:
            session.close()
            
    def get_user(self, telegram_id):
        """الحصول على مستخدم بواسطة telegram_id"""
        session = self.get_session()
        try:
            user = session.query(User).filter(User.telegram_id == str(telegram_id)).first()
            if user:
                # تحديث آخر نشاط
                user.last_activity = datetime.utcnow()
                session.commit()
                return self._detach(session, user)
            return None
        finally:
            session.close()

    def sync_user_profile(self, telegram_id, username=None, first_name=None, last_name=None):
        """تحديث اسم/يوزر تيليغرام حتى ما يضل Unknown أو فاضي."""
        session = self.get_session()
        try:
            user = session.query(User).filter(User.telegram_id == str(telegram_id)).first()
            if not user:
                return None
            changed = False
            if username is not None and user.username != username:
                user.username = username
                changed = True
            if first_name is not None and first_name and user.first_name != first_name:
                user.first_name = first_name
                changed = True
            if last_name is not None and user.last_name != last_name:
                user.last_name = last_name
                changed = True
            user.last_activity = datetime.utcnow()
            if changed:
                session.commit()
            else:
                session.commit()
            return self._detach(session, user)
        finally:
            session.close()

    def get_user_by_db_id(self, user_id):
        """الحصول على مستخدم بواسطة id الداخلي"""
        session = self.get_session()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            return self._detach(session, user)
        finally:
            session.close()

    def user_has_funded(self, user_id: int) -> bool:
        """هل أكمل المستخدم شحناً ناجحاً مرة واحدة على الأقل؟"""
        if not user_id:
            return False
        session = self.get_session()
        try:
            row = (
                session.query(Transaction.id)
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.status == "completed",
                    Transaction.amount > 0,
                    Transaction.transaction_type.in_(
                        ("deposit", "gift_code", "manual")
                    ),
                )
                .first()
            )
            return row is not None
        finally:
            session.close()

    def accept_terms(self, telegram_id):
        """تسجيل موافقة المستخدم على الشروط/الآثار الجانبية"""
        session = self.get_session()
        try:
            user = session.query(User).filter(User.telegram_id == str(telegram_id)).first()
            if not user:
                return None
            if not user.terms_accepted_at:
                user.terms_accepted_at = datetime.utcnow()
                session.commit()
            return self._detach(session, user)
        finally:
            session.close()

    def get_user_by_ichancy_player_id(self, player_id):
        """جلب مستخدم مرتبط بمعرف لاعب Ichancy"""
        if not player_id:
            return None
        session = self.get_session()
        try:
            user = session.query(User).filter(
                User.ichancy_player_id == str(player_id)
            ).first()
            return self._detach(session, user)
        finally:
            session.close()

    def get_user_by_ichancy_username(self, username):
        """جلب مستخدم مرتبط باسم مستخدم Ichancy"""
        if not username:
            return None
        session = self.get_session()
        try:
            user = (
                session.query(User)
                .filter(User.ichancy_username.isnot(None))
                .filter(User.ichancy_username.ilike(str(username).strip()))
                .first()
            )
            return self._detach(session, user)
        finally:
            session.close()

    def update_user_balance(self, telegram_id, amount, transaction_type="manual", description="", method=None):
        """تحديث رصيد المستخدم"""
        session = self.get_session()
        try:
            user = session.query(User).filter(User.telegram_id == str(telegram_id)).first()
            if user:
                user.balance += amount
                
                # إضافة معاملة
                transaction = Transaction(
                    user_id=user.id,
                    transaction_type=transaction_type,
                    amount=amount,
                    method=method,
                    status="completed",
                    description=description
                )
                session.add(transaction)
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    def add_bet(self, user_id, game_type, bet_amount, game_category=None, game_name=None, odds=None, bet_details=None):
        """إضافة رهان جديد"""
        session = self.get_session()
        try:
            bet = Bet(
                user_id=user_id,
                game_type=game_type,
                game_category=game_category,
                game_name=game_name,
                bet_amount=bet_amount,
                odds=odds,
                bet_details=bet_details
            )
            session.add(bet)
            session.commit()
            session.refresh(bet)
            return bet
        finally:
            session.close()
    
    def settle_bet(self, bet_id, status, actual_win=0.0):
        """تسوية الرهان"""
        session = self.get_session()
        try:
            bet = session.query(Bet).filter(Bet.id == bet_id).first()
            if bet:
                bet.status = status
                bet.actual_win = actual_win
                bet.settled_at = datetime.utcnow()
                
                # تحديث رصيد المستخدم إذا فاز
                if status == 'won' and actual_win > 0:
                    user = session.query(User).filter(User.id == bet.user_id).first()
                    if user:
                        user.balance += actual_win
                        user.total_wins += actual_win
                        
                        # إضافة معاملة الفوز
                        transaction = Transaction(
                            user_id=user.id,
                            transaction_type='bet_win',
                            amount=actual_win,
                            status='completed',
                            description=f'فوز في {bet.game_name or bet.game_type}'
                        )
                        session.add(transaction)
                
                # تحديث إجمالي الرهانات
                user = session.query(User).filter(User.id == bet.user_id).first()
                if user:
                    user.total_bets += bet.bet_amount
                
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    def add_jackpot_contribution(self, user_id, bet_id, contribution_amount):
        """إضافة مساهمة في الجاكبوت"""
        session = self.get_session()
        try:
            # تحديد معرف مجموعة الجاكبوت (يومي)
            today = datetime.utcnow().date()
            jackpot_pool_id = f"daily_{today.strftime('%Y%m%d')}"
            
            entry = JackpotEntry(
                user_id=user_id,
                bet_id=bet_id,
                contribution_amount=contribution_amount,
                jackpot_pool_id=jackpot_pool_id
            )
            session.add(entry)
            
            # إضافة معاملة المساهمة
            transaction = Transaction(
                user_id=user_id,
                transaction_type='jackpot_contribution',
                amount=contribution_amount,
                status='completed',
                description=f'مساهمة في الجاكبوت اليومي'
            )
            session.add(transaction)
            
            session.commit()
            return True
        finally:
            session.close()
    
    def get_current_jackpot(self):
        """الحصول على قيمة الجاكبوت الحالية"""
        session = self.get_session()
        try:
            today = datetime.utcnow().date()
            jackpot_pool_id = f"daily_{today.strftime('%Y%m%d')}"
            
            total = session.query(func.sum(JackpotEntry.contribution_amount)).filter(
                JackpotEntry.jackpot_pool_id == jackpot_pool_id
            ).scalar() or 0
            
            return total
        finally:
            session.close()
    
    def get_user_betting_stats(self, user_id):
        """الحصول على إحصائيات رهانات المستخدم"""
        session = self.get_session()
        try:
            stats = {
                'total_bets': 0,
                'total_wins': 0,
                'total_losses': 0,
                'win_rate': 0,
                'biggest_win': 0,
                'recent_bets': []
            }
            
            # إجمالي الرهانات
            total_bet_amount = session.query(func.sum(Bet.bet_amount)).filter(
                Bet.user_id == user_id
            ).scalar() or 0
            
            # إجمالي الأرباح
            total_win_amount = session.query(func.sum(Bet.actual_win)).filter(
                Bet.user_id == user_id,
                Bet.status == 'won'
            ).scalar() or 0
            
            # عدد الرهانات الفائزة والخاسرة
            won_bets = session.query(Bet).filter(
                Bet.user_id == user_id,
                Bet.status == 'won'
            ).count()
            
            lost_bets = session.query(Bet).filter(
                Bet.user_id == user_id,
                Bet.status == 'lost'
            ).count()
            
            total_settled_bets = won_bets + lost_bets
            
            # أكبر فوز
            biggest_win = session.query(func.max(Bet.actual_win)).filter(
                Bet.user_id == user_id,
                Bet.status == 'won'
            ).scalar() or 0
            
            # آخر الرهانات
            recent_bets = session.query(Bet).filter(
                Bet.user_id == user_id
            ).order_by(Bet.placed_at.desc()).limit(10).all()
            
            stats.update({
                'total_bets': total_bet_amount,
                'total_wins': total_win_amount,
                'total_losses': total_bet_amount - total_win_amount,
                'win_rate': (won_bets / total_settled_bets * 100) if total_settled_bets > 0 else 0,
                'biggest_win': biggest_win,
                'recent_bets': recent_bets
            })
            
            return stats
        finally:
            session.close()
    
    def update_vip_level(self, user_id):
        """تحديث مستوى VIP للمستخدم"""
        session = self.get_session()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if user:
                from config import Config
                level_id, level_info = Config.get_vip_level(user.total_bets)
                
                old_level = user.vip_level
                user.vip_level = level_id
                
                session.commit()
                
                # إرجاع True إذا تم الترقية
                return old_level != level_id
            return False
        finally:
            session.close()
    
    def log_system_event(self, log_type, module, message, user_id=None):
        """تسجيل حدث في النظام"""
        session = self.get_session()
        try:
            log = SystemLog(
                log_type=log_type,
                module=module,
                message=message,
                user_id=user_id
            )
            session.add(log)
            session.commit()
        finally:
            session.close()

    def is_external_transaction_used(self, external_id: str, method: str = None) -> bool:
        """التحقق من استخدام رقم عملية خارجي مسبقاً"""
        if not external_id:
            return False

        session = self.get_session()
        try:
            query = session.query(Transaction).filter(
                Transaction.external_transaction_id == str(external_id),
                Transaction.status == "completed",
            )
            if method:
                query = query.filter(Transaction.method == method)
            return query.first() is not None
        finally:
            session.close()

    def get_used_usdt_amounts(self) -> set:
        """جلب مبالغ USDT المستخدمة في طلبات معلقة"""
        session = self.get_session()
        try:
            rows = session.query(Transaction.expected_usdt_amount).filter(
                Transaction.method == "usdt",
                Transaction.status == "pending",
                Transaction.expected_usdt_amount.isnot(None),
            ).all()
            return {row[0] for row in rows if row[0] is not None}
        finally:
            session.close()

    def get_used_blockchain_tx_hashes(self) -> set:
        """جلب hashes البلوكشين المستخدمة"""
        session = self.get_session()
        try:
            rows = session.query(Transaction.external_transaction_id).filter(
                Transaction.method == "usdt",
                Transaction.status == "completed",
                Transaction.external_transaction_id.isnot(None),
            ).all()
            return {row[0] for row in rows if row[0]}
        finally:
            session.close()

    def get_pending_usdt_deposits(self):
        """جلب طلبات إيداع USDT المعلقة"""
        session = self.get_session()
        try:
            return session.query(Transaction).filter(
                Transaction.method == "usdt",
                Transaction.transaction_type == "deposit",
                Transaction.status == "pending",
                Transaction.expected_usdt_amount.isnot(None),
            ).all()
        finally:
            session.close()

    def get_saved_accounts(self, user_id: int, account_type: str = None):
        """جلب الحسابات المحفوظة للمستخدم"""
        session = self.get_session()
        try:
            query = session.query(SavedPaymentAccount).filter(
                SavedPaymentAccount.user_id == user_id
            )
            if account_type:
                query = query.filter(SavedPaymentAccount.account_type == account_type)
            return (
                query.order_by(SavedPaymentAccount.created_at.desc()).all()
            )
        finally:
            session.close()

    def count_saved_accounts(self, user_id: int, account_type: str = None) -> int:
        session = self.get_session()
        try:
            query = session.query(SavedPaymentAccount).filter(
                SavedPaymentAccount.user_id == user_id
            )
            if account_type:
                query = query.filter(SavedPaymentAccount.account_type == account_type)
            return query.count()
        finally:
            session.close()

    def get_saved_account(self, account_id: int, user_id: int = None):
        session = self.get_session()
        try:
            query = session.query(SavedPaymentAccount).filter(
                SavedPaymentAccount.id == account_id
            )
            if user_id is not None:
                query = query.filter(SavedPaymentAccount.user_id == user_id)
            return query.first()
        finally:
            session.close()

    def add_saved_account(
        self,
        user_id: int,
        account_type: str,
        account_value: str,
        label: str = None,
        max_per_type: int = 10,
    ):
        """
        إضافة حساب محفوظ.
        يرجع: (account, error_message)
        """
        session = self.get_session()
        try:
            value = account_value.strip()
            existing = (
                session.query(SavedPaymentAccount)
                .filter(
                    SavedPaymentAccount.user_id == user_id,
                    SavedPaymentAccount.account_type == account_type,
                    SavedPaymentAccount.account_value == value,
                )
                .first()
            )
            if existing:
                return existing, "هذا الرقم/الحساب محفوظ مسبقاً"

            count = (
                session.query(SavedPaymentAccount)
                .filter(
                    SavedPaymentAccount.user_id == user_id,
                    SavedPaymentAccount.account_type == account_type,
                )
                .count()
            )
            if count >= max_per_type:
                return None, f"وصلت للحد الأقصى ({max_per_type}) لهذا النوع"

            account = SavedPaymentAccount(
                user_id=user_id,
                account_type=account_type,
                account_value=value,
                label=label,
            )
            session.add(account)
            session.commit()
            session.refresh(account)
            return account, None
        finally:
            session.close()

    def delete_saved_account(self, account_id: int, user_id: int) -> bool:
        session = self.get_session()
        try:
            account = (
                session.query(SavedPaymentAccount)
                .filter(
                    SavedPaymentAccount.id == account_id,
                    SavedPaymentAccount.user_id == user_id,
                )
                .first()
            )
            if not account:
                return False
            session.delete(account)
            session.commit()
            return True
        finally:
            session.close()

    def get_setting(self, key: str, default: str = None):
        session = self.get_session()
        try:
            row = session.query(BotSetting).filter(BotSetting.key == key).first()
            return row.value if row else default
        finally:
            session.close()

    def set_setting(self, key: str, value: str):
        session = self.get_session()
        try:
            row = session.query(BotSetting).filter(BotSetting.key == key).first()
            if row:
                row.value = str(value)
                row.updated_at = datetime.utcnow()
            else:
                session.add(BotSetting(key=key, value=str(value)))
            session.commit()
        finally:
            session.close()

