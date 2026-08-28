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
    # تأثيرات حركية عند فتح القائمة — أطفئها إذا صار البوت بطيء
    UI_ANIMATIONS = os.getenv("UI_ANIMATIONS", "true").strip().lower() in ("1", "true", "yes")
    # بانر متحرك أعلى الشاشات: file_id أو رابط https أو مسار ملف GIF/MP4 محلي
    MENU_BANNER = os.getenv("MENU_BANNER", "").strip()
    CONSENT_BANNER = os.getenv("CONSENT_BANNER", "").strip() or MENU_BANNER
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

    # تشغيل على VPS: webhook (موصى به للأداء) أو polling
    BOT_MODE = os.getenv("BOT_MODE", "webhook").lower()  # webhook | polling
    WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "127.0.0.1")
    WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "6001"))
    WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "botich").strip("/")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://www.alipride.com/botich")
    # Telegram يقبل فقط ASCII: A-Z a-z 0-9 _ - (isalnum يقبل العربي — لا تستخدمه)
    _raw_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    WEBHOOK_SECRET = "".join(
        c for c in _raw_secret
        if c.isascii() and (c.isalnum() or c in "_-")
    )[:256]

    # روابط التواصل والاشتراك الإلزامي
    FACEBOOK_URL = os.getenv("FACEBOOK_URL", "https://www.facebook.com/share/1EPqQiSMun/")
    TELEGRAM_CHANNEL_URL = os.getenv("TELEGRAM_CHANNEL_URL", "https://t.me/ESRteam")
    REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID", "@ESRteam").strip()
    TELEGRAM_SUPPORT_URL = os.getenv("TELEGRAM_SUPPORT_URL", "https://t.me/NapoleonSupport")
    # يوزر الإدارة العليا لتصعيد تذاكر الدعم (بدون @)
    SUPPORT_ESCALATION_USERNAME = os.getenv(
        "SUPPORT_ESCALATION_USERNAME", "NapoleonRobert"
    ).strip().lstrip("@")
    # كروب إدارة التقبيض (فضي محفظتي) — رقم سالب للكروب
    _payout_gid = os.getenv("PAYOUT_ADMIN_GROUP_ID", "").strip()
    PAYOUT_ADMIN_GROUP_ID = int(_payout_gid) if _payout_gid.lstrip("-").isdigit() else None
    # كروب الدعم لتذاكر مربوطة بطلبات السحب
    _support_gid = os.getenv("SUPPORT_GROUP_ID", "").strip()
    SUPPORT_GROUP_ID = int(_support_gid) if _support_gid.lstrip("-").isdigit() else None
    # true = فرض الاشتراك | false = تعطيل البوابة بالكامل
    REQUIRE_CHANNEL_SUBSCRIPTION = os.getenv(
        "REQUIRE_CHANNEL_SUBSCRIPTION", "true"
    ).strip().lower() in ("1", "true", "yes", "on")
    # عند فشل التحقق (البوت ليس مشرفاً): true = منع الدخول | false = السماح بالمرور
    SUBSCRIPTION_STRICT_MODE = os.getenv(
        "SUBSCRIPTION_STRICT_MODE", "true"
    ).strip().lower() in ("1", "true", "yes", "on")

    @classmethod
    def get_required_channel_ids(cls):
        """معرّفات القناة للتحقق من الاشتراك (username + numeric إن وُجد)."""
        ids = []
        raw = (cls.REQUIRED_CHANNEL_ID or "").strip()
        if raw:
            if raw.lstrip("-").isdigit():
                ids.append(int(raw))
            else:
                ids.append(raw if raw.startswith("@") else f"@{raw}")

        # استخراج username من رابط القناة كاحتياطي
        url = (cls.TELEGRAM_CHANNEL_URL or "").strip().rstrip("/")
        if "t.me/" in url:
            part = url.split("t.me/", 1)[1].split("?")[0].strip("/")
            if part and not part.startswith("+"):
                username = part if part.startswith("@") else f"@{part}"
                if username not in ids:
                    ids.append(username)

        unique = []
        for item in ids:
            if item not in unique:
                unique.append(item)
        return unique
    # إعدادات قاعدة البيانات
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/telegram_bot.db")
    
    # إعدادات الإحالات
    REFERRAL_PERCENTAGE = float(os.getenv("REFERRAL_PERCENTAGE", "15"))  # نسبة الربح من الإحالات

    # رسوم السحب لصاحب البوت (% من قيمة السحب)
    WITHDRAWAL_FEE_PERCENTAGE = float(os.getenv("WITHDRAWAL_FEE_PERCENTAGE", "10"))
    
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
        "min_usdt": float(os.getenv("USDT_MIN_DEPOSIT", "2")),
        "deposit_timeout_minutes": int(os.getenv("USDT_DEPOSIT_TIMEOUT", "30")),
        "poll_interval_seconds": int(os.getenv("USDT_POLL_INTERVAL", "30")),
        "min_confirmations": int(os.getenv("USDT_MIN_CONFIRMATIONS", "1")),
    }

    # إعدادات الدفع
    PAYMENT_METHODS = {
        "syriatel_cash": {
            "name": "سيرياتيل كاش",
            "emoji": "📱",
            "button_label": "📱 سيرياتيل كاش",
            "auto_deposit": True,
            "auto_withdraw": False,
            "provider": "apisyria",
        },
        "shamcash": {
            "name": "شام كاش",
            "emoji": "💳",
            "button_label": "💳 شام كاش",
            "auto_deposit": True,
            "auto_withdraw": False,
            "provider": "apisyria",
        },
        "usdt": {
            "name": "عملات رقمية",
            "emoji": "🪙",
            "button_label": "🪙 عملات رقمية",
            "auto_deposit": True,
            "auto_withdraw": False,
            "provider": "tron",
        }
    }
    
    # الحد الأدنى والأقصى للمعاملات
    MIN_DEPOSIT = float(os.getenv("MIN_DEPOSIT", "200"))
    MAX_DEPOSIT = float(os.getenv("MAX_DEPOSIT", "10000"))
    MIN_WITHDRAWAL = float(os.getenv("MIN_WITHDRAWAL", "20"))
    MAX_WITHDRAWAL = float(os.getenv("MAX_WITHDRAWAL", "5000"))
    MIN_GIFT = float(os.getenv("MIN_GIFT", "5"))
    
    # رسائل البوت — طابع نابليون
    MESSAGES = {
        "ad_warning": (
            "🛡️ تنبيه أمني\n"
            "لا تعتمد أي رابط أو رسالة خارج هذا البوت\n"
            "الدعم الرسمي موجود من زر الدعم فقط."
        ),
        "terms_gate": """🚪 بوابة نابليون

قبل ما نفوتك عالمقر في شرط واحد بس

📢 انضم للقناة الرسمية

وبس 😂

لا فورم
لا انتظار
لا موافقة موظف
ولا حدا رح يسألك شو اسم ابوك 🤣

انضم واضغط تحقق
والبوت بيفتحلك لحاله

جوا رح تلاقي تعبئة وسحب بأبسط شكل
ونظام إحالة هو الأقوى وسهل لدرجة حتى المحاسب فهمه من أول مرة 😂

🔞 للبالغين فقط والاستخدام بمسؤولية""",
        "subscription_verify_hint": "",
        "start_step1": """⚔️ إنشاء حساب Ichancy

✅ تم فك قفل الاشتراك
⏳ الآن: أنشئ حسابك من داخل البوت

المسار:
1️⃣ إنشاء حساب Ichancy ← أنت هنا
2️⃣ فتح باقي الخدمات

الشحن اختياري — تقدر تشحن لاحقاً من القائمة.

📢 القناة: {telegram_channel_url}
📱 فيسبوك: {facebook_url}
""",
        "deposit_required": """⚔️ لازم تنشئ حساب Ichancy أولاً

الشحن صار اختياري — مو مطلوب للدخول.

اضغط «إنشاء حساب Ichancy الآن».
""",
        "ichancy_required": """⚔️ إنشاء حساب Ichancy

✅ تم فك قفل الاشتراك
⏳ الآن: أنشئ حسابك من داخل البوت فقط

⚠️ حساب واحد مرتبط بتليجرامك.
❌ ربط حساب خارجي ممنوع.

الشحن اختياري — مو مطلوب الآن.

اضغط «إنشاء حساب Ichancy الآن».
""",
        "first_start_consent": (
            "<b>🚀 دخّلني</b>\n"
            "━━━━━━━━━━━━━━━━\n"
            "<blockquote>على وشك تدخل عالم فيه أرباح، حظ، وشوية أدرينالين.\n"
            "الدخول بيتطلب موافقتك على الآثار الجانبية 😈</blockquote>\n"
            "<i>اضغط الزر تحت لتبدأ 👇</i>"
        ),
        "welcome": """{ad_warning}

🔷 القائمة الرئيسية:

رصيدك في البوت: {balance}
رقم الايدي الخاص بك: {user_id}
""",
        "main_menu": """{ad_warning}

🔷 القائمة الرئيسية:

رصيدك في البوت: {balance}
رقم الآيدي الخاص بك: {user_id}
""",
        "operation_cancelled": "❌ تم إلغاء العملية.\nارجع للقائمة من الأزرار.",
        "balance_updated": "✅ تم تحديث رصيدك.\n💵 الرصيد الجديد: {balance}",
        "insufficient_balance": "❌ رصيدك غير كافٍ لإتمام العملية",
        "invalid_amount": "❌ المبلغ المدخل غير صحيح",
        "user_not_found": "❌ الحساب غير موجود. أرسل /start من جديد.",
        "operation_completed": "✅ تم إتمام العملية بنجاح",
        "service_unavailable": "⚠️ الخدمة غير جاهزة حالياً.\nتواصل مع الدعم.",
        "ichancy_not_configured": "⚠️ إنشاء حساب Ichancy غير مفعّل حالياً.\nتواصل مع الدعم.",
        "session_expired": "⏱ انتهت الجلسة.\nابدأ من جديد من الأزرار.",
    }
    
    # مقر نابليون — القائمة الرئيسية
    START_MENU_BUTTONS = [
        [{"text": "🎮 بدّي حساب iChancy", "callback": "ichancy_create_start"}],
        [
            {"text": "💸 عبّي iChancy", "callback": "ichancy_topup_start"},
            {"text": "💰 اسحب من iChancy", "callback": "ichancy_withdraw_start"},
        ],
        [
            {"text": "⚡ عبّي محفظتي", "callback": "deposit"},
            {"text": "🏧 فضّي محفظتي", "callback": "withdraw"},
        ],
        [
            {"text": "👛 جيبتي", "callback": "gift_balance"},
            {"text": "🧾 دفتر الفضايح", "callback": "transactions"},
        ],
        [
            {"text": "🪪 بطاقتي", "callback": "profile"},
            {"text": "🚑 الحقني يا دعم", "callback": "contact"},
        ],
        [
            {"text": "🎟️ كودك يا بطل", "callback": "gift_code"},
            {"text": "👥 جيب رفيقك", "callback": "referrals"},
        ],
        [
            {"text": "📘 فهمني بسرعة", "callback": "guide_quick"},
            {"text": "🧰 شغلات زيادة", "callback": "extras_menu"},
        ],
        [{"text": "🚫 ممنوع تكبس هون", "callback": "forbidden_press"}],
    ]

    # نفس القائمة الرئيسية (بدون تفرقة start/full)
    MAIN_BUTTONS = START_MENU_BUTTONS

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
        "min_amount": float(os.getenv("SYRIATEL_MIN_DEPOSIT", os.getenv("MIN_DEPOSIT", "200"))),
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
        # بوابة الوكيل (إنشاء/شحن/سحب)
        "api_base_url": os.getenv("ICHANCY_API_URL", "https://agents.ichancy100.com"),
        # موقع اللاعب — لجلب playerId عبر signIn بعد الإنشاء إذا قائمة الوكيل ممنوعة
        "player_api_url": os.getenv(
            "ICHANCY_PLAYER_API_URL",
            "https://www.ichancy.com",
        ).rstrip("/"),
        "username": os.getenv("ICHANCY_USERNAME", ""),
        "password": os.getenv("ICHANCY_PASSWORD", ""),
        "parent_id": os.getenv("ICHANCY_PARENT_ID", ""),
        "currency": os.getenv("ICHANCY_CURRENCY", "NSP"),
        "currency_code": os.getenv("ICHANCY_CURRENCY_CODE", os.getenv("ICHANCY_CURRENCY", "NSP")),
        # البوت بالليرة الجديدة — API ايشانسي غالباً بالوحدة القديمة (×100)
        "amount_scale": int(os.getenv("ICHANCY_AMOUNT_SCALE", "100")),
        "money_status": int(os.getenv("ICHANCY_MONEY_STATUS", "5")),
        # كل زبون يسحب من المنصة للبوت مرة واحدة كل نصف ساعة
        "withdraw_cooldown_minutes": int(os.getenv("ICHANCY_WITHDRAW_COOLDOWN", "30")),
        # الحد الأدنى لشحن حساب ichancy من رصيد البوت
        "min_topup": float(os.getenv("ICHANCY_MIN_TOPUP", "200")),
        # بروكسي لطلبات Ichancy فقط (لتجاوز Cloudflare على IP السيرفر)
        "proxy_url": os.getenv("ICHANCY_PROXY", "").strip(),
        "proxy_user": os.getenv("ICHANCY_PROXY_USER", "").strip(),
        "proxy_pass": os.getenv("ICHANCY_PROXY_PASS", "").strip(),
        "request_timeout": int(os.getenv("ICHANCY_TIMEOUT", "60")),
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
        default = float(cls.SHAMCASH_DEPOSIT.get("usd_rate", 13125))
        try:
            from database import DatabaseManager

            db = DatabaseManager()
            raw = db.get_setting("shamcash_usd_rate", str(default))
            return float(raw)
        except Exception:
            return default

    @classmethod
    def get_usdt_syp_rate(cls) -> float:
        """سعر صرف USDT/دولار → ل.س (من لوحة الأدمن أو .env)"""
        default = float(cls.USDT_CONFIG.get("syp_rate", 15000))
        try:
            from database import DatabaseManager

            db = DatabaseManager()
            raw = db.get_setting("usdt_syp_rate", str(default))
            return float(raw)
        except Exception:
            return default

    @classmethod
    def usd_to_syp(cls, usd_amount: float, source: str = "usdt") -> float:
        """تحويل دولار/USDT إلى ليرة حسب سعر الأدمن."""
        rate = (
            cls.get_shamcash_usd_rate()
            if source == "shamcash"
            else cls.get_usdt_syp_rate()
        )
        return round(float(usd_amount) * float(rate), 2)

    @classmethod
    def get_ichancy_proxy_config(cls) -> dict:
        """
        إعداد بروكسي Ichancy الفعّال.
        إذا ضبط الأدمن override من اللوحة → يُستخدم DB (حتى لو فارغ = معطّل).
        وإلا → قيم .env الافتراضية.
        """
        env_cfg = {
            "proxy_url": (cls.ICHANCY_CONFIG.get("proxy_url") or "").strip(),
            "proxy_user": (cls.ICHANCY_CONFIG.get("proxy_user") or "").strip(),
            "proxy_pass": (cls.ICHANCY_CONFIG.get("proxy_pass") or "").strip(),
            "source": "env",
        }
        try:
            from database import DatabaseManager

            db = DatabaseManager()
            override = db.get_setting("ichancy_proxy_override")
        except Exception:
            return env_cfg

        if override == "1":
            return {
                "proxy_url": (db.get_setting("ichancy_proxy_url", "") or "").strip(),
                "proxy_user": (db.get_setting("ichancy_proxy_user", "") or "").strip(),
                "proxy_pass": (db.get_setting("ichancy_proxy_pass", "") or "").strip(),
                "source": "admin",
            }
        return env_cfg

    @classmethod
    def save_ichancy_proxy_config(
        cls, proxy_url: str = "", proxy_user: str = "", proxy_pass: str = ""
    ) -> None:
        """حفظ بروكسي من لوحة الأدمن (override صريح)."""
        from database import DatabaseManager

        db = DatabaseManager()
        db.set_setting("ichancy_proxy_override", "1")
        db.set_setting("ichancy_proxy_url", (proxy_url or "").strip())
        db.set_setting("ichancy_proxy_user", (proxy_user or "").strip())
        db.set_setting("ichancy_proxy_pass", (proxy_pass or "").strip())

    @classmethod
    def disable_ichancy_proxy_config(cls) -> None:
        """تعطيل البروكسي من الأدمن بشكل صريح (لا يرجع لـ .env)."""
        cls.save_ichancy_proxy_config("", "", "")

