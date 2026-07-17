"""
ملف الإعدادات للبوت
"""

import os
from typing import Dict, Any

class Config:
    """إعدادات البوت"""
    
    # إعدادات التليجرام
    BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    BOT_USERNAME = os.getenv("BOT_USERNAME", "Napoleonrobert_bot")
    BOT_DISPLAY_NAME = os.getenv("BOT_DISPLAY_NAME", "Napoleon_bot")
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

    # تشغيل على VPS: polling (محلي) أو webhook (بورت 6001)
    BOT_MODE = os.getenv("BOT_MODE", "polling").lower()  # polling | webhook
    WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "6001"))
    WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "telegram-webhook").strip("/")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # https://domain.com/telegram-webhook
    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

    # روابط التواصل (عدّلها في .env)
    FACEBOOK_URL = os.getenv("FACEBOOK_URL", "https://facebook.com/NapoleonBot")
    TELEGRAM_CHANNEL_URL = os.getenv("TELEGRAM_CHANNEL_URL", "https://t.me/NapoleonChannel")
    TELEGRAM_SUPPORT_URL = os.getenv("TELEGRAM_SUPPORT_URL", "https://t.me/NapoleonSupport")
    
    # إعدادات قاعدة البيانات
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///telegram_bot.db")
    
    # إعدادات الإحالات
    REFERRAL_PERCENTAGE = float(os.getenv("REFERRAL_PERCENTAGE", "10"))  # نسبة الربح من الإحالات
    
    # إعدادات API SYRIA - https://apisyria.com/api/docs
    APISYRIA_CONFIG = {
        "base_url": os.getenv("APISYRIA_BASE_URL", "https://apisyria.com/api/v1"),
        "api_key": os.getenv("APISYRIA_API_KEY", ""),
        "syriatel_gsm": os.getenv("APISYRIA_SYRIATEL_GSM", ""),
        "syriatel_pin": os.getenv("APISYRIA_SYRIATEL_PIN", ""),
        "shamcash_account": os.getenv("APISYRIA_SHAMCASH_ACCOUNT", ""),
        # period في API: 7 أو 30 أو all — الفلترة الدقيقة تتم على 15 دقيقة في الكود
        "tx_search_period": os.getenv("APISYRIA_TX_PERIOD", "7"),
        "currency": os.getenv("APISYRIA_CURRENCY", "SYP"),
        # مهلة التحويل والتحقق للزبون (دقائق)
        "deposit_timeout_minutes": int(os.getenv("APISYRIA_DEPOSIT_TIMEOUT", "15")),
    }

    # إعدادات USDT TRC20 - TronGrid
    USDT_CONFIG = {
        "wallet_address": os.getenv("USDT_WALLET_ADDRESS", ""),
        "contract_address": os.getenv(
            "USDT_CONTRACT_ADDRESS",
            "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        ),
        "trongrid_url": os.getenv("TRONGRID_URL", "https://api.trongrid.io"),
        "trongrid_api_key": os.getenv("TRONGRID_API_KEY", ""),
        "syp_rate": float(os.getenv("USDT_SYP_RATE", "15000")),
        "deposit_timeout_minutes": int(os.getenv("USDT_DEPOSIT_TIMEOUT", "30")),
        "poll_interval_seconds": int(os.getenv("USDT_POLL_INTERVAL", "30")),
        "min_confirmations": int(os.getenv("USDT_MIN_CONFIRMATIONS", "1")),
    }

    # إعدادات الدفع
    PAYMENT_METHODS = {
        "syriatel_cash": {
            "name": "SYRIATEL Cash",
            "emoji": "🔴",
            "button_label": "🔴 SYRIATEL Cash",
            "auto_deposit": True,
            "auto_withdraw": False,
            "provider": "apisyria",
        },
        "shamcash": {
            "name": "SHAM Cash",
            "emoji": "🔼",
            "button_label": "🔼 SHAM Cash (AUTO)",
            "auto_deposit": True,
            "auto_withdraw": False,
            "provider": "apisyria",
        },
        "usdt": {
            "name": "USDT",
            "emoji": "🟢",
            "button_label": "🟢 USDT",
            "auto_deposit": True,
            "auto_withdraw": False,
            "provider": "tron",
        }
    }
    
    # الحد الأدنى والأقصى للمعاملات
    MIN_DEPOSIT = float(os.getenv("MIN_DEPOSIT", "10"))
    MAX_DEPOSIT = float(os.getenv("MAX_DEPOSIT", "10000"))
    MIN_WITHDRAWAL = float(os.getenv("MIN_WITHDRAWAL", "20"))
    MAX_WITHDRAWAL = float(os.getenv("MAX_WITHDRAWAL", "5000"))
    MIN_GIFT = float(os.getenv("MIN_GIFT", "5"))
    
    # رسائل البوت
    MESSAGES = {
        "start_step1": """❞ 1️⃣ الخطوة الأولى ❝

يجب عليك شحن رصيدك أولاً. أو يمكنك الشحن عن طريق كود هدية يتم الحصول عليه من الأدمن أو من صفحتنا على الفيسبوك أو من قناتنا على التلغرام.

📱 صفحتنا على الفيسبوك
{facebook_url}

📢 قناتنا على التلغرام
{telegram_channel_url}
""",
        "welcome": """👋 مرحبًا بكم في بوت {bot_name}
شكرا لكم على اختياركم الانضمام إلينا.

❞ 🔷 القائمة الرئيسية: ❝

رصيدك في البوت: {balance}
رقم الايدي الخاص بك: {user_id}
""",
        "main_menu": """❞ 🔷 القائمة الرئيسية: ❝

رصيدك في البوت: {balance}
رقم الايدي الخاص بك: {user_id}
""",
        "balance_updated": "✅ تم تحديث رصيدك بنجاح!\n💵 الرصيد الجديد: {balance}",
        "insufficient_balance": "❌ رصيدك غير كافي لإتمام هذه العملية",
        "invalid_amount": "❌ المبلغ المدخل غير صحيح",
        "user_not_found": "❌ المستخدم غير موجود",
        "operation_cancelled": "❌ تم إلغاء العملية",
        "operation_completed": "✅ تم إتمام العملية بنجاح"
    }
    
    # أزرار الواجهة الكاملة — مطابقة للصورة
    MAIN_BUTTONS = [
        [{"text": "⚡️ شحن وسحب حساب Ichancy", "callback": "ichancy_hub"}],
        [
            {"text": "📩 شحن البوت", "callback": "deposit"},
            {"text": "📩 سحب حوالة", "callback": "withdraw"},
        ],
        [{"text": "👤 معلومات الملف الشخصي", "callback": "profile"}],
        [
            {"text": "🎁 إهداء الرصيد", "callback": "gift_balance"},
            {"text": "🏆 أكواد الجوائز", "callback": "gift_code"},
        ],
        [
            {"text": "📩 تواصل مع الدعم", "callback": "contact"},
            {"text": "🔄 طلب استرداد حوالة", "callback": "refund_request"},
        ],
        [
            {"text": "↗️ صفحة الفيسبوك", "url": "FACEBOOK_URL"},
            {"text": "👥 برنامج الإحالات", "callback": "referrals"},
        ],
        [{"text": "🗄️ عرض السجل المالي", "callback": "transactions"}],
    ]

    # قائمة /start المبسطة ثم «المزيد» تفتح MAIN_BUTTONS
    START_MENU_BUTTONS = [
        [{"text": "⚡️ شحن وسحب حساب Ichancy", "callback": "ichancy_hub"}],
        [{"text": "📩 شحن البوت", "callback": "deposit"}],
        [{"text": "🏆 استخدام أكواد الجوائز", "callback": "gift_code"}],
        [{"text": "👥 برنامج الإحالات", "callback": "referrals"}],
        [{"text": "📋 المزيد من الخدمات", "callback": "full_menu"}],
    ]

    # حد الحسابات المحفوظة: سيريتل 10 — شام كاش 1 فقط
    MAX_SAVED_SYRIATEL = int(os.getenv("MAX_SAVED_SYRIATEL", "10"))
    MAX_SAVED_SHAMCASH = int(os.getenv("MAX_SAVED_SHAMCASH", "1"))
    MAX_SAVED_ACCOUNTS_PER_TYPE = MAX_SAVED_SYRIATEL  # توافق خلفي

    @classmethod
    def max_saved_accounts(cls, account_type: str) -> int:
        if account_type == "shamcash":
            return cls.MAX_SAVED_SHAMCASH
        if account_type == "syriatel_cash":
            return cls.MAX_SAVED_SYRIATEL
        return 10

    # شام كاش — شحن مثل واجهة الصور (سوري / دولار)
    SHAMCASH_DEPOSIT = {
        "min_syp": float(os.getenv("SHAMCASH_MIN_SYP", "200")),
        "min_usd": float(os.getenv("SHAMCASH_MIN_USD", "2")),
        "usd_rate": float(os.getenv("SHAMCASH_USD_RATE", os.getenv("USDT_SYP_RATE", "13125"))),
        "account_syp": os.getenv(
            "APISYRIA_SHAMCASH_ACCOUNT_SYP",
            os.getenv("APISYRIA_SHAMCASH_ACCOUNT", ""),
        ),
        "account_usd": os.getenv(
            "APISYRIA_SHAMCASH_ACCOUNT_USD",
            os.getenv("APISYRIA_SHAMCASH_ACCOUNT", ""),
        ),
    }

    # سيريتل كاش — تحويل يدوي + تحقق أوتو (حتى 10 أكواد استلام)
    @classmethod
    def get_syriatel_codes(cls):
        raw = os.getenv("APISYRIA_SYRIATEL_CODES", "") or os.getenv("APISYRIA_SYRIATEL_GSM", "")
        codes = []
        for part in raw.replace(";", ",").split(","):
            code = "".join(c for c in part.strip() if c.isdigit())
            if code and code not in codes:
                codes.append(code)
        return codes[:10]

    SYRIATEL_DEPOSIT = {
        "timeout_minutes": int(os.getenv("SYRIATEL_DEPOSIT_TIMEOUT", "5")),
        "tx_digits": int(os.getenv("SYRIATEL_TX_DIGITS", "12")),
        "min_amount": float(os.getenv("SYRIATEL_MIN_DEPOSIT", os.getenv("MIN_DEPOSIT", "1000"))),
    }

    @classmethod
    def get_payment_methods_buttons(cls):
        """الحصول على أزرار طرق الدفع"""
        buttons = []
        for method_id, method_info in cls.PAYMENT_METHODS.items():
            label = method_info.get("button_label") or f"{method_info['emoji']} {method_info['name']}"
            buttons.append({
                "text": label,
                "callback": f"payment_{method_id}",
                "method_id": method_id,
            })
        return buttons


    
    # إعدادات الجاكبوت والألعاب
    MIN_JACKPOT = float(os.getenv("MIN_JACKPOT", "1000"))  # الحد الأدنى لسحب الجاكبوت
    JACKPOT_CONTRIBUTION_RATE = float(os.getenv("JACKPOT_CONTRIBUTION_RATE", "0.01"))  # 1% من كل رهان
    JACKPOT_DRAW_TIME = os.getenv("JACKPOT_DRAW_TIME", "23:59")  # وقت سحب الجاكبوت اليومي
    
    # إعدادات ichancy.com — Agent API (signIn / withdrawFromPlayer)
    ICHANCY_CONFIG = {
        "website_url": "https://www.ichancy.com/",
        "api_base_url": os.getenv("ICHANCY_API_URL", "https://www.ichancy.com"),
        "username": os.getenv("ICHANCY_USERNAME", ""),
        "password": os.getenv("ICHANCY_PASSWORD", ""),
        "parent_id": os.getenv("ICHANCY_PARENT_ID", ""),
        "currency": os.getenv("ICHANCY_CURRENCY", "EUR"),
        "currency_code": os.getenv("ICHANCY_CURRENCY_CODE", os.getenv("ICHANCY_CURRENCY", "EUR")),
        "money_status": int(os.getenv("ICHANCY_MONEY_STATUS", "5")),
        # كل زبون يسحب من المنصة للبوت مرة واحدة كل نصف ساعة
        "withdraw_cooldown_minutes": int(os.getenv("ICHANCY_WITHDRAW_COOLDOWN", "30")),
        # الحد الأدنى لشحن حساب ichancy من رصيد البوت
        "min_topup": float(os.getenv("ICHANCY_MIN_TOPUP", "20000")),
    }
    
    # معلومات الدعم الفني
    SUPPORT_INFO = {
        "phone": os.getenv("SUPPORT_PHONE", "+963912345678"),
        "email": os.getenv("SUPPORT_EMAIL", "support@ichancy.com"),
        "hours": os.getenv("SUPPORT_HOURS", "24/7"),
        "telegram": os.getenv("SUPPORT_TELEGRAM", "@ichancy_support"),
        "website_support": "https://www.ichancy.com/support"
    }
    
    # أنواع الألعاب المدعومة
    GAME_TYPES = {
        "casino": {
            "name": "ألعاب الكازينو",
            "emoji": "🎰",
            "categories": {
                "slots": "ماكينات القمار",
                "table_games": "ألعاب الطاولة", 
                "live_casino": "الكازينو المباشر",
                "fast_games": "الألعاب السريعة"
            }
        },
        "sports": {
            "name": "الرهانات الرياضية",
            "emoji": "⚽",
            "categories": {
                "football": "كرة القدم",
                "basketball": "كرة السلة",
                "tennis": "التنس",
                "other_sports": "رياضات أخرى"
            }
        }
    }
    
    # مستويات VIP
    VIP_LEVELS = {
        "beginner": {
            "name": "🆕 مبتدئ",
            "min_bets": 0,
            "max_bets": 4999,
            "cashback": 0,
            "benefits": ["مكافأة ترحيب", "دعم عادي"]
        },
        "bronze": {
            "name": "🥉 Bronze",
            "min_bets": 5000,
            "max_bets": 19999,
            "cashback": 5,
            "benefits": ["مكافأة شهرية", "كاش باك 5%", "دعم محسن"]
        },
        "silver": {
            "name": "🥈 Silver", 
            "min_bets": 20000,
            "max_bets": 49999,
            "cashback": 10,
            "benefits": ["مكافآت شهرية", "كاش باك 10%", "دعم سريع", "مكافآت إضافية"]
        },
        "gold": {
            "name": "🥇 Gold",
            "min_bets": 50000,
            "max_bets": 99999,
            "cashback": 15,
            "benefits": ["مكافآت أسبوعية", "كاش باك 15%", "دعم أولوية", "حدود سحب مرتفعة"]
        },
        "diamond": {
            "name": "💎 Diamond",
            "min_bets": 100000,
            "max_bets": float('inf'),
            "cashback": 20,
            "benefits": ["مدير حساب شخصي", "مكافآت حصرية يومية", "حدود سحب عالية", "دعوات لأحداث خاصة"]
        }
    }
    
    # رسائل الألعاب
    GAMING_MESSAGES = {
        "jackpot_win": "🎉 مبروك! لقد فزت بالجاكبوت!\n💰 المبلغ: {amount}\n🎲 تم إضافة المبلغ لرصيدك",
        "bet_placed": "🎯 تم وضع الرهان بنجاح\n💰 المبلغ: {amount}\n🎮 اللعبة: {game}",
        "bet_won": "🏆 مبروك! لقد فزت!\n💰 الربح: {amount}\n🎮 اللعبة: {game}",
        "bet_lost": "😔 للأسف لم تفز هذه المرة\n💰 المبلغ: {amount}\n🎮 اللعبة: {game}",
        "vip_upgrade": "🎉 مبروك! تم ترقيتك إلى مستوى {level}\n🎁 استمتع بالمزايا الجديدة!"
    }
    
    # إعدادات الأمان
    SECURITY_CONFIG = {
        "max_daily_withdrawals": int(os.getenv("MAX_DAILY_WITHDRAWALS", "3")),
        "max_daily_deposits": int(os.getenv("MAX_DAILY_DEPOSITS", "10")),
        "withdrawal_cooldown": int(os.getenv("WITHDRAWAL_COOLDOWN", "3600")),  # ثانية
        "require_admin_approval": os.getenv("REQUIRE_ADMIN_APPROVAL", "true").lower() == "true",
        "auto_ban_threshold": int(os.getenv("AUTO_BAN_THRESHOLD", "10"))  # عدد المحاولات الفاشلة
    }
    
    # إعدادات التسجيل
    LOGGING_CONFIG = {
        "level": os.getenv("LOG_LEVEL", "INFO"),
        "file_path": os.getenv("LOG_FILE_PATH", "logs/bot.log"),
        "max_file_size": int(os.getenv("LOG_MAX_FILE_SIZE", "10485760")),  # 10MB
        "backup_count": int(os.getenv("LOG_BACKUP_COUNT", "5"))
    }
    
    @classmethod
    def get_vip_level(cls, total_bets):
        """تحديد مستوى VIP بناءً على إجمالي الرهانات"""
        for level_id, level_info in cls.VIP_LEVELS.items():
            if level_info["min_bets"] <= total_bets <= level_info["max_bets"]:
                return level_id, level_info
        return "beginner", cls.VIP_LEVELS["beginner"]
    
    @classmethod
    def get_next_vip_level(cls, current_level):
        """الحصول على المستوى التالي في VIP"""
        levels = list(cls.VIP_LEVELS.keys())
        try:
            current_index = levels.index(current_level)
            if current_index < len(levels) - 1:
                next_level = levels[current_index + 1]
                return next_level, cls.VIP_LEVELS[next_level]
        except ValueError:
            pass
        return None, None

    @classmethod
    def get_shamcash_usd_rate(cls) -> float:
        """سعر صرف شام كاش دولار → ل.س (من DB أو .env)"""
        from database import DatabaseManager
        db = DatabaseManager()
        default = str(cls.SHAMCASH_DEPOSIT.get("usd_rate", 13125))
        raw = db.get_setting("shamcash_usd_rate", default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def get_usdt_syp_rate(cls) -> float:
        """سعر صرف USDT → ل.س (من DB أو .env)"""
        from database import DatabaseManager
        db = DatabaseManager()
        default = str(cls.USDT_CONFIG.get("syp_rate", 15000))
        raw = db.get_setting("usdt_syp_rate", default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(default)

