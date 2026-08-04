"""
ميزات ترفيهية قابلة للمشاركة — خفيفة وما تلمس مسارات الدفع الحرجة.
النصوص قابلة للتعديل عبر bot_settings (سطر لكل عنصر).
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from database import DatabaseManager, Transaction, User, UserFunStat

logger = logging.getLogger(__name__)
db = DatabaseManager()

# ─── نصوص افتراضية (قابلة للتعديل من الإدارة) ─────────────

DEFAULT_MOODS = [
    "المحاسب هادي اليوم لا تستفزه",
    "فتح الآلة الحاسبة لحاله الوضع خطير",
    "القهوة واصلة يعني عندنا فرصة",
    "الموظفين صاحيين استغل الفرصة",
    "الانترنت هادي اليوم شكلنا دفعنا اللي علينا",
    "اذا خلص طلبك بسرعة تصرف طبيعي ولا تفضحنا",
    "المحاسب فات عالدوام بإرادته الوضع مبشر",
    "زر الرجوع قدم استقالته من كثرة الاستخدام",
    "الأزرار مرتاحة اليوم يعني الخدمات شغّالة ☕",
    "المقر هادي شوي بس المحفظة لسا عم تراقب 👀",
    "اليوم المزاج رسمي مع لمسة سخرية زي العادة",
    "السيرفر شارب قهوته والبوت جاهز للضغط ⚡",
    "المحاسب ابتسم… وهذا نادر فاغتنم اللحظة 😂",
    "اليوم زر السحب صاحي عاليمين لا تستفزّه",
    "قسم المحاسبة طالب إجازة… تم تجاهل الطلب 😂",
    "نابليون راجع من استراحة قصيرة… جاهزين للشغل 👑",
    "لا دراما اليوم… بس عمليات واضحة ومرتبة ✅",
    "الموظفين صاحيين والقهوة ما خلصت بعد… فرصة ذهبية",
    "الآلة الحاسبة عم تغني لوحدها… الوضع تحت السيطرة نوعاً ما",
    "الدعم لسا عم يفتح عيونه… بس الأزرار جاهزة",
]

DEFAULT_PROFILE_COMMENTS = [
    "داخل عالمقر اكتر من الموظفين 😂",
    "بيعرف زر الرجوع اكتر من بيته",
    "المحاسب صار يعرفه من طريقة الكبس",
    "زبون هادي لحد ما يصير الطلب قيد المراجعة",
    "ساكن دائم عندنا بس بدون مكتب",
    "بيفتح البوت قبل ما يفتح العيون",
    "الموظفين صاروا يسلّموا عليه بالاسم",
    "خبير ضغط الأزرار بدرجة أولى",
    "بيقرا الشروط للنهاية… نادر جداً",
    "المحاسب حاطّه بقائمة الزبائن الموثوقين 😂",
    "بيغيّر رأيه بس بأسلوب راقي",
    "ما بيسأل وين طلبي… صبر أسطوري",
    "بطاقة حضوره بالمقر أطول من دوام الموظفين",
    "المحفظة بتفتح لوحدها لما يشوف اسمه",
    "وضوح بالنوايا… نادر بهالأيام",
    "بيكبس الزر الممنوع فضول علمي مو دراما",
    "الإدارة عم تفكر تعطيه مكتب فخري",
    "كل ما يفوت عالمقر المزاج بيرتفع درجة",
]

DEFAULT_RECEIPT_COMMENTS = [
    "خلصتها انا والبوت اخد الشهرة 😂",
    "تمت بدون ما حدا يصيح عالمحاسب",
    "وقعنا الايصال قبل ما يغير رأيه",
    "العملية تمت والمحاسب طالب علاوة",
    "تم التنفيذ والموظف المسؤول عم ينكر علاقته بالموضوع",
    "الختم نزل والقهوة لسا سخنة ☕",
    "دفشتها بالإجر اليمين ومرّت… لا تعيدها مرتين 😂",
    "دقيقة مراجعة ويا ريت كل الزبائن هيك مرتبين",
    "الإيصال جاهز والفضيحة مؤجلة لوقت لاحق",
    "تمت والمقر عم يصفر من الفرحة بهدوء",
    "رقم العملية صار مشهور اكتر من الزبون",
    "المحاسب ختم ورجع يختفي بالغموض 👑",
    "ما احتجنا تحقيق ولا شاهد عيان",
    "العملية مرت والزر ما اشتكى هالمرة",
    "تم… والمحاسب طلب كاسة مي من الفرح",
]

DEFAULT_WEEKLY_COMMENTS = [
    "اسبوع هادي بشكل يثير الشك 😂",
    "انت مو زبون انت فرد من الطاقم",
    "المحاسب طلب إجازة بعد ما شاف التقرير",
    "استخدام ممتاز بس زر الرجوع قدم شكوى",
    "نشاط منضبط… نادر بالمقر",
    "الاسبوع كان دراما خفيفة بنهاية سعيدة",
    "الدعم ارتاح منك وهذا إنجاز بحد ذاته",
    "حضور قوي بدون ما تفضحنا قدام الإدارة",
    "زر الرجوع بلّش يحفظ رقمك من كثر ما شافك",
    "تقرير نظيف… المحاسب حط عليه نجمة",
    "الاسبوع هاد البوت حس حاله مفيد",
    "ما في صريخ ولا دراما… غريب بس حلو",
]

DEFAULT_RARE_MESSAGES = [
    "🚨 حدث تاريخي\n\nالمحاسب رد من اول مرة\nخد سكرين لان ما رح تتكرر 😂",
    "👀 رسالة نادرة\n\nالبوت شافك داخل عالمقر بدون ما تطلب شي\nواضح جاي تطمن علينا 😂",
    "📢 خبر عاجل\n\nتم العثور على زر الرجوع بعد اختفائه ساعتين\nالتحقيقات مستمرة 😂",
    "☕ حالة استثنائية\n\nالقهوة وصلت قبل المحاسب\nالمقر حاليا تحت إدارة الفنجان 😂",
    "🎖️ بلاغ داخلي\n\nتم رصد مستخدم بيفتح البوت بدون ما يكبس عشرين مرة\nالإدارة فخورة 😂",
    "🕵️ ملاحظة سرية\n\nزر الإلغاء طلب إجازة مرضية\nبسبب ضغط التغييرات المفاجئة 😂",
    "📣 إعلان نادر\n\nالإنترنت كان مستقر لمدة ساعة كاملة\nالمقر عم يحتفل بهدوء",
    "🧪 تجربة مخبرية\n\nاكتشفنا زبون بيقرا الشروط للنهاية\nالعينة قيد الدراسة 😂",
]

DEFAULT_NEWS = [
    "📢 خبر عاجل:\nقسم المحاسبة اعلن انه غير مسؤول عن الارقام اللي بتنكتب من الذاكرة 😂",
    "📢 نشرة المقر\nتم منع الموظفين من قول هلق بشوف لمدة يوم كامل",
    "📢 خبر داخلي\nموظف الدعم فتح الرسالة قبل ما يشرب القهوة\nالإدارة عم تحقق بالحادثة",
    "📢 تنبيه\nالزر اللي بتكبسه عشرين مرة فهم من اول ضغطة",
    "📢 تحديث المقر\nآلة التصوير رفضت تصوّر بيانات حساسة… محترمة اكتر منّا 😂",
    "📢 بيان رسمي\nزر الرجوع ما زال على رأس عمله رغم كثرة الشكاوى",
    "📢 خبر خفيف\nالمحاسب لقى القلم… التحقيقات مستمرة ليش كان ضايع",
    "📢 نشرة الظهيرة\nتم تخفيض دراما المقر بنسبة 3٪… الرقم تقريبي",
]

DEFAULT_TITLES = [
    # code|min_home|min_backs|min_orders|min_support|min_forbidden|label
    "friend|5|0|0|0|0|☕ صديق المحاسب",
    "back_enemy|0|20|0|0|0|🔙 عدو زر الرجوع",
    "support_vip|0|0|0|3|0|🚑 زبون الدعم المفضل",
    "expert|0|0|5|0|0|🧠 الخبير بعد النتيجة",
    "resident|30|0|0|0|0|👑 ساكن دائم بالمقر",
    "receipts|0|0|10|0|0|🧾 جامع الإيصالات",
    "waiter|0|0|0|0|0|⏳ ملك الانتظار",
    "honor|50|50|0|0|0|🎖️ موظف شرف بالمقر",
    "forbidden|0|0|0|0|1|🚫 كابس الزر الممنوع",
]

ACHIEVEMENTS = [
    {
        "code": "terms_end",
        "name": "🏆 قرأت الشروط للنهاية",
        "desc": "وصلت لآخر سطر… نادر بالمقر",
        "check": lambda s: bool(s.terms_read),
    },
    {
        "code": "forbidden",
        "name": "🏆 كبست الزر الممنوع",
        "desc": "فضول رسمي موثق",
        "check": lambda s: int(s.forbidden_presses or 0) >= 1,
    },
    {
        "code": "tx_first",
        "name": "🏆 دخلت رقم العملية صح من اول مرة",
        "desc": "المحاسب صفّق من بعيد",
        "check": lambda s: int(s.correct_tx_first or 0) >= 1,
    },
    {
        "code": "change_mind",
        "name": "🏆 غيرت رأيك ثلاث مرات بنفس الطلب",
        "desc": "حرية التعبير عن الرأي… بالمقر",
        "check": lambda s: int(s.opinion_changes or 0) >= 3,
    },
    {
        "code": "ten_opens",
        "name": "🏆 فتحت البوت عشر مرات بيوم واحد",
        "desc": "الطمأنينة فن",
        "check": lambda s: int(s.home_opens_today or 0) >= 10,
    },
    {
        "code": "no_support",
        "name": "🏆 ما سألت الدعم وين طلبي",
        "desc": "صبر نادر… نادر جداً",
        "check": lambda s: int(s.home_opens or 0) >= 15 and int(s.support_count or 0) == 0,
    },
    {
        "code": "back_20",
        "name": "🏆 استخدمت زر الرجوع اكتر من عشرين مرة",
        "desc": "زر الرجوع صار يعرفك بالاسم",
        "check": lambda s: int(s.back_clicks or 0) >= 20,
    },
    {
        "code": "name_saved",
        "name": "🏆 المحاسب حفظ اسمك",
        "desc": "صرت من الزبائن المعروفين",
        "check": lambda s: int(s.home_opens or 0) >= 25 or int(s.week_orders or 0) + int(getattr(s, "_lifetime_orders", 0) or 0) >= 3,
    },
]


def _pool(key: str, defaults: List[str]) -> List[str]:
    try:
        raw = db.get_setting(key, "") or ""
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        return lines if lines else list(defaults)
    except Exception:
        return list(defaults)


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _week_start() -> str:
    now = datetime.utcnow()
    start = now - timedelta(days=now.weekday())
    return start.strftime("%Y-%m-%d")


def daily_mood() -> str:
    moods = _pool("fun_daily_moods", DEFAULT_MOODS)
    day = datetime.utcnow().strftime("%Y%m%d")
    idx = int(hashlib.md5(f"mood-{day}".encode()).hexdigest(), 16) % len(moods)
    return moods[idx]


def pick_profile_comment() -> str:
    return random.choice(_pool("fun_profile_comments", DEFAULT_PROFILE_COMMENTS))


def pick_receipt_comment() -> str:
    return random.choice(_pool("fun_receipt_comments", DEFAULT_RECEIPT_COMMENTS))


def pick_weekly_comment() -> str:
    return random.choice(_pool("fun_weekly_comments", DEFAULT_WEEKLY_COMMENTS))


def pick_rare_message() -> str:
    return random.choice(_pool("fun_rare_messages", DEFAULT_RARE_MESSAGES))


def pick_news() -> str:
    items = _pool("fun_hq_news", DEFAULT_NEWS)
    day = datetime.utcnow().strftime("%Y%m%d")
    # يتغير كل ~6 ساعات ضمن اليوم
    slot = datetime.utcnow().hour // 6
    idx = int(hashlib.md5(f"news-{day}-{slot}".encode()).hexdigest(), 16) % len(items)
    return items[idx]


def get_or_create_stats(user_id: int) -> UserFunStat:
    session = db.get_session()
    try:
        row = session.query(UserFunStat).filter(UserFunStat.user_id == user_id).first()
        if not row:
            row = UserFunStat(user_id=user_id, unlocked="[]")
            session.add(row)
            session.commit()
            session.refresh(row)
        # أسبوع جديد
        ws = _week_start()
        if row.week_start != ws:
            row.week_start = ws
            row.week_logins = 0
            row.week_orders = 0
            row.week_backs = 0
            row.week_cancels = 0
            row.week_support = 0
            row.week_achievements = 0
            session.commit()
        # يوم جديد لفتح المقر
        today = _today()
        if row.home_opens_day != today:
            row.home_opens_day = today
            row.home_opens_today = 0
            session.commit()
        return db._detach(session, row)
    finally:
        session.close()


def _mutate(user_id: int, fn) -> Tuple[UserFunStat, List[Dict[str, str]]]:
    """عدّل الإحصائيات وأعد الإنجازات الجديدة إن فُتحت."""
    session = db.get_session()
    newly = []
    try:
        row = session.query(UserFunStat).filter(UserFunStat.user_id == user_id).first()
        if not row:
            row = UserFunStat(user_id=user_id, unlocked="[]")
            session.add(row)
            session.flush()
        ws = _week_start()
        if row.week_start != ws:
            row.week_start = ws
            row.week_logins = 0
            row.week_orders = 0
            row.week_backs = 0
            row.week_cancels = 0
            row.week_support = 0
            row.week_achievements = 0
        today = _today()
        if row.home_opens_day != today:
            row.home_opens_day = today
            row.home_opens_today = 0

        fn(row)

        # lifetime orders for title/achievement
        try:
            orders = (
                session.query(Transaction)
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.status.in_(["completed", "paid"]),
                )
                .count()
            )
        except Exception:
            orders = 0
        row._lifetime_orders = orders  # type: ignore

        unlocked = set(json.loads(row.unlocked or "[]"))
        for ach in ACHIEVEMENTS:
            code = ach["code"]
            if code in unlocked:
                continue
            try:
                if ach["check"](row):
                    unlocked.add(code)
                    newly.append({"code": code, "name": ach["name"], "desc": ach["desc"]})
                    row.week_achievements = int(row.week_achievements or 0) + 1
            except Exception:
                continue
        row.unlocked = json.dumps(list(unlocked), ensure_ascii=False)
        row.updated_at = datetime.utcnow()
        session.commit()
        return db._detach(session, row), newly
    except Exception:
        session.rollback()
        logger.exception("فشل تحديث إحصائيات الترفيه")
        return get_or_create_stats(user_id), []
    finally:
        session.close()


def track_home_open(
    user_id: int, count_back: bool = False
) -> Tuple[UserFunStat, List[Dict[str, str]]]:
    def fn(row):
        row.home_opens = int(row.home_opens or 0) + 1
        row.home_opens_today = int(row.home_opens_today or 0) + 1
        row.week_logins = int(row.week_logins or 0) + 1
        if count_back:
            row.back_clicks = int(row.back_clicks or 0) + 1
            row.week_backs = int(row.week_backs or 0) + 1

    return _mutate(user_id, fn)


def maybe_rare(user_id: int, chance: float = 0.20) -> Optional[str]:
    """رسالة نادرة مرة واحدة باليوم كحد أقصى — بلا مكافآت."""
    try:
        stats = get_or_create_stats(user_id)
        if stats.last_rare_date == _today():
            return None
        if random.random() >= chance:
            return None
        session = db.get_session()
        try:
            row = session.query(UserFunStat).filter(UserFunStat.user_id == user_id).first()
            if not row or row.last_rare_date == _today():
                return None
            row.last_rare_date = _today()
            session.commit()
        finally:
            session.close()
        return pick_rare_message()
    except Exception:
        logger.exception("فشل توليد رسالة نادرة")
        return None


def track_back(user_id: int):
    def fn(row):
        row.back_clicks = int(row.back_clicks or 0) + 1
        row.week_backs = int(row.week_backs or 0) + 1

    return _mutate(user_id, fn)


def track_cancel(user_id: int):
    def fn(row):
        row.cancel_count = int(row.cancel_count or 0) + 1
        row.opinion_changes = int(row.opinion_changes or 0) + 1
        row.week_cancels = int(row.week_cancels or 0) + 1

    return _mutate(user_id, fn)


def track_support(user_id: int):
    def fn(row):
        row.support_count = int(row.support_count or 0) + 1
        row.week_support = int(row.week_support or 0) + 1

    return _mutate(user_id, fn)


def track_forbidden(user_id: int):
    def fn(row):
        row.forbidden_presses = int(row.forbidden_presses or 0) + 1

    return _mutate(user_id, fn)


def track_terms_read(user_id: int):
    def fn(row):
        row.terms_read = True

    return _mutate(user_id, fn)


def track_order_success(user_id: int):
    def fn(row):
        row.week_orders = int(row.week_orders or 0) + 1

    return _mutate(user_id, fn)


def track_correct_tx(user_id: int):
    def fn(row):
        row.correct_tx_first = int(row.correct_tx_first or 0) + 1

    return _mutate(user_id, fn)


def bump_akhira(user_id: int) -> int:
    def fn(row):
        row.akhira_count = int(row.akhira_count or 0) + 1

    stats, _ = _mutate(user_id, fn)
    return int(stats.akhira_count or 1)


def resolve_title(user: User, stats: Optional[UserFunStat] = None) -> str:
    stats = stats or get_or_create_stats(user.id)
    if stats.title_override:
        return stats.title_override

    session = db.get_session()
    try:
        orders = (
            session.query(Transaction)
            .filter(
                Transaction.user_id == user.id,
                Transaction.status.in_(["completed", "paid"]),
            )
            .count()
        )
    finally:
        session.close()

    raw = _pool("fun_titles", DEFAULT_TITLES)
    best = "☕ زبون جديد بالمقر"
    best_score = -1
    for line in raw:
        parts = line.split("|")
        if len(parts) < 7:
            continue
        code, mh, mb, mo, ms, mf, label = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
        try:
            need = (
                int(mh),
                int(mb),
                int(mo),
                int(ms),
                int(mf),
            )
        except ValueError:
            continue
        ok = (
            int(stats.home_opens or 0) >= need[0]
            and int(stats.back_clicks or 0) >= need[1]
            and orders >= need[2]
            and int(stats.support_count or 0) >= need[3]
            and int(stats.forbidden_presses or 0) >= need[4]
        )
        if ok:
            score = sum(need)
            if score >= best_score:
                best_score = score
                best = label
    return best


def experience_level(stats: UserFunStat, orders: int) -> str:
    score = int(stats.home_opens or 0) + orders * 3 + int(stats.back_clicks or 0) // 5
    if score >= 80:
        return "أسطورة المقر"
    if score >= 40:
        return "محترف أزرار"
    if score >= 15:
        return "متدرّب رسمي"
    return "مبتدئ واعد"


def accountant_rating(stats: UserFunStat) -> int:
    base = 70
    base += min(20, int(stats.home_opens or 0) // 2)
    base -= min(15, int(stats.cancel_count or 0))
    base += min(10, int(stats.correct_tx_first or 0) * 5)
    return max(35, min(99, base))


def _completed_orders(user_id: int) -> int:
    session = db.get_session()
    try:
        return (
            session.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.status.in_(["completed", "paid"]),
            )
            .count()
        )
    finally:
        session.close()


def build_status_card(user: User, first_name: str = "", comment: Optional[str] = None) -> str:
    """بطاقة قابلة للتصوير — بلا موبايل / تيليغرام / محفظة / مبالغ."""
    stats = get_or_create_stats(user.id)
    orders = _completed_orders(user.id)
    name = (first_name or user.first_name or "ضيف المقر").strip()
    # لا نعرض username أو telegram_id
    join = user.created_at.strftime("%Y-%m-%d") if user.created_at else "—"
    title = resolve_title(user, stats)
    note = comment or pick_profile_comment()
    return (
        "👑 بطاقة نابليون الرسمية\n\n"
        f"👤 الاسم {name}\n\n"
        f"🎖️ اللقب {title}\n\n"
        f"🧾 عدد العمليات {orders}\n\n"
        f"📅 عضو من {join}\n\n"
        f"🧠 مستوى الخبرة {experience_level(stats, orders)}\n\n"
        f"☕ رضا المحاسب {accountant_rating(stats)} بالمية\n\n"
        "📢 ملاحظة الإدارة\n"
        f"{note}"
    )


FUN_SETTING_KEYS = {
    "moods": ("fun_daily_moods", DEFAULT_MOODS, "مزاج المحاسب اليومي"),
    "profile": ("fun_profile_comments", DEFAULT_PROFILE_COMMENTS, "تعليقات البطاقة"),
    "receipt": ("fun_receipt_comments", DEFAULT_RECEIPT_COMMENTS, "تعليقات الإيصال"),
    "weekly": ("fun_weekly_comments", DEFAULT_WEEKLY_COMMENTS, "تعليقات التقرير"),
    "rare": ("fun_rare_messages", DEFAULT_RARE_MESSAGES, "الرسائل النادرة"),
    "news": ("fun_hq_news", DEFAULT_NEWS, "أخبار المقر"),
    "titles": ("fun_titles", DEFAULT_TITLES, "الألقاب (code|home|backs|orders|support|forbidden|label)"),
}


def pool_preview(kind: str, limit: int = 8) -> str:
    meta = FUN_SETTING_KEYS.get(kind)
    if not meta:
        return "غير معروف"
    key, defaults, title = meta
    items = _pool(key, defaults)
    head = "\n".join(f"• {x[:120]}" for x in items[:limit])
    more = f"\n… و{len(items) - limit} غيرهم" if len(items) > limit else ""
    return f"📝 {title}\n\nعدد العناصر: {len(items)}\n\n{head}{more}"


def save_pool(kind: str, text: str) -> int:
    meta = FUN_SETTING_KEYS.get(kind)
    if not meta:
        return 0
    key, _defaults, _title = meta
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return 0
    db.set_setting(key, "\n".join(lines))
    return len(lines)


def method_label(method: str) -> str:
    labels = {
        "shamcash": "شام كاش",
        "syriatel_cash": "سيريتل كاش",
        "usdt": "عملات رقمية",
        "withdraw": "سحب محفظة",
    }
    return labels.get((method or "").lower(), method or "—")


def build_success_receipt(order_id, amount, method: str, when: str) -> str:
    """إيصال نجاح للعرض — بدون موبايل/محفظة/آيدي تيليغرام."""
    from utils import format_currency

    return (
        "👑 NAPOLEON BOT\n\n"
        "✅ تمت العملية\n\n"
        f"🧾 رقم العملية {order_id}\n\n"
        f"💰 المبلغ {format_currency(amount) if isinstance(amount, (int, float)) else amount}\n\n"
        f"💳 الطريقة {method_label(method)}\n\n"
        f"🕒 الوقت {when}\n\n"
        "📢 تعليق المحاسب\n"
        f"{pick_receipt_comment()}"
    )


def build_photo_receipt_from_tx(tx) -> str:
    from utils import format_currency

    if getattr(tx, "processed_at", None):
        when = tx.processed_at.strftime("%Y-%m-%d %H:%M")
    elif getattr(tx, "created_at", None):
        when = tx.created_at.strftime("%Y-%m-%d %H:%M")
    else:
        when = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    return build_photo_receipt(
        tx.id,
        format_currency(tx.amount or 0),
        method_label(tx.method or ""),
        when,
    )


def build_achievements_list(user_id: int) -> str:
    stats = get_or_create_stats(user_id)
    unlocked = set(json.loads(stats.unlocked or "[]"))
    lines = ["🏆 إنجازاتي\n"]
    for ach in ACHIEVEMENTS:
        if ach["code"] in unlocked:
            lines.append(f"{ach['name']}\n{ach['desc']}\n")
        else:
            lines.append(f"🔒 {ach['name']}\n")
    lines.append("المقفول يبقى غامض… فضول صحي 😂")
    return "\n".join(lines)


def achievement_notify(ach: Dict[str, str]) -> str:
    return (
        "🚨 إنجاز جديد\n\n"
        "فتحت إنجاز\n\n"
        f"{ach['name']}\n"
        f"{ach['desc']}\n\n"
        "الإدارة ما كانت متوقعة منك هالمستوى 😂"
    )


def build_weekly_report(user: User) -> str:
    stats = get_or_create_stats(user.id)
    return (
        "📊 تقريرك الأسبوعي:\n\n"
        f"🚪 دخلت عالمقر {int(stats.week_logins or 0)} مرة\n\n"
        f"🧾 عملت {int(stats.week_orders or 0)} طلب\n\n"
        f"🔙 استخدمت زر الرجوع {int(stats.week_backs or 0)} مرة\n\n"
        f"🔄 غيرت رأيك {int(stats.week_cancels or 0)} مرة\n\n"
        f"🚑 حكيت الدعم {int(stats.week_support or 0)} مرة\n\n"
        f"🏆 فتحت {int(stats.week_achievements or 0)} إنجاز جديد\n\n"
        "📢 تقييم المحاسب\n"
        f"{pick_weekly_comment()}"
    )


def build_photo_receipt(order_id, amount, method: str, when: str) -> str:
    """إيصال مرتب للتصوير — بدون بيانات حساسة."""
    return (
        "👑 NAPOLEON BOT\n\n"
        "✅ تمت العملية\n\n"
        f"🧾 رقم العملية {order_id}\n\n"
        f"💰 المبلغ {amount}\n\n"
        f"💳 الطريقة {method}\n\n"
        f"🕒 الوقت {when}\n\n"
        "📢 تعليق المحاسب\n"
        f"{pick_receipt_comment()}"
    )


def match_secret(text: str, user_id: int = None) -> Optional[str]:
    if not text:
        return None
    cleaned = text.strip()
    lower = cleaned.lower()

    if cleaned in ("وينك", "وينك؟", "وينك؟؟"):
        return "👀 هون\n\nكنت عم راقب الازرار لا يهرب واحد منهن"
    if "مستعجل" in cleaned:
        return (
            "🏃 فعلنا وضع لا ترمش\n\n"
            "بس لا تكبس الزر اربعطعش مرة كرمال تساعدنا 😂"
        )
    if cleaned in ("هههه", "ههه", "ههاها") or lower in ("hahaha", "haha"):
        return "😂 تم استلام الضحكة\n\nضفناها لرصيد الدعم المعنوي للمحاسب"
    if cleaned in ("😂", "🤣", "😆"):
        return "😂 تم استلام الضحكة\n\nضفناها لرصيد الدعم المعنوي للمحاسب"
    if "اخر مرة" in cleaned or "آخر مرة" in cleaned:
        n = bump_akhira(user_id) if user_id else 1
        return f"تم تسجيل الجملة\n\nهي المرة رقم {n} اللي بتقولها 😂"
    return None
