"""
جيش نابليون — منطق الإحالات والعمولات والرتب.
المكافأة القديمة على التعبئة ملغاة؛ العمولة من صافي النشاط المؤهل فقط.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from config import Config
from database import (
    CommissionEntry,
    DatabaseManager,
    ReferralInvite,
    User,
)

logger = logging.getLogger(__name__)
db = DatabaseManager()

# رتب افتراضية — تُعدَّل من لوحة الأدمن عبر bot_settings
DEFAULT_RANKS = (
    {
        "code": "soldier",
        "title": "🥉 جندي نابليون",
        "min_active": 5,
        "rate": 12.0,
    },
    {
        "code": "captain",
        "title": "🥈 قائد الكتيبة",
        "min_active": 10,
        "rate": 14.0,
    },
    {
        "code": "general",
        "title": "🥇 جنرال نابليون",
        "min_active": 25,
        "rate": 16.0,
    },
    {
        "code": "emperor",
        "title": "👑 الإمبراطور",
        "min_active": 50,
        "rate": 18.0,
    },
)

STATUS_REGISTERED = "registered"
STATUS_PENDING = "pending_verify"
STATUS_ACTIVE = "active"
STATUS_REJECTED = "rejected"

STATUS_LABELS = {
    STATUS_REGISTERED: "🟡 مسجل جديد",
    STATUS_PENDING: "🟠 قيد التحقق",
    STATUS_ACTIVE: "🟢 نشط",
    STATUS_REJECTED: "🔴 غير مؤهل",
}


def _get_float(key: str, default: float) -> float:
    try:
        raw = db.get_setting(key, str(default))
        return float(raw)
    except Exception:
        return float(default)


def _get_int(key: str, default: int) -> int:
    try:
        return int(float(db.get_setting(key, str(default))))
    except Exception:
        return int(default)


def get_rank_defs() -> List[Dict[str, Any]]:
    ranks = []
    for r in DEFAULT_RANKS:
        code = r["code"]
        ranks.append(
            {
                "code": code,
                "title": db.get_setting(f"army_rank_{code}_title", r["title"]) or r["title"],
                "min_active": _get_int(f"army_rank_{code}_min", r["min_active"]),
                "rate": _get_float(f"army_rank_{code}_rate", r["rate"]),
            }
        )
    ranks.sort(key=lambda x: x["min_active"])
    return ranks


def get_min_activity_usd() -> float:
    return _get_float("army_min_activity_usd", 10.0)


def get_hold_days() -> int:
    return _get_int("army_commission_hold_days", 7)


def get_min_commission_withdraw() -> float:
    return _get_float("army_min_commission_withdraw", 200.0)


def resolve_rank(active_count: int, override: Optional[str] = None) -> Dict[str, Any]:
    ranks = get_rank_defs()
    if override:
        for r in ranks:
            if r["code"] == override:
                return r
    current = {
        "code": "recruit",
        "title": "🪖 مجنّد جديد",
        "min_active": 0,
        "rate": 0.0,
    }
    for r in ranks:
        if active_count >= r["min_active"]:
            current = r
    return current


def next_rank_info(active_count: int) -> Tuple[Optional[Dict[str, Any]], int]:
    ranks = get_rank_defs()
    for r in ranks:
        if active_count < r["min_active"]:
            return r, r["min_active"] - active_count
    return None, 0


class ReferralArmyService:
    """خدمة جيش نابليون"""

    @staticmethod
    def create_invite(referrer: User, invitee: User) -> Optional[ReferralInvite]:
        session = db.get_session()
        try:
            if str(referrer.telegram_id) == str(invitee.telegram_id):
                return None
            existing = (
                session.query(ReferralInvite)
                .filter(ReferralInvite.invitee_id == invitee.id)
                .first()
            )
            if existing:
                return existing

            invite = ReferralInvite(
                referrer_id=referrer.id,
                invitee_id=invitee.id,
                status=STATUS_REGISTERED,
            )
            session.add(invite)
            ref = session.query(User).filter(User.id == referrer.id).first()
            inv = session.query(User).filter(User.id == invitee.id).first()
            if inv and not inv.referred_by:
                inv.referred_by = str(referrer.telegram_id)
            if ref:
                ref.referral_count = (ref.referral_count or 0) + 1
            session.commit()
            session.refresh(invite)
            return invite
        finally:
            session.close()

    @staticmethod
    def reject_invite(invitee_user_id: int, reason: str) -> None:
        session = db.get_session()
        try:
            invite = (
                session.query(ReferralInvite)
                .filter(ReferralInvite.invitee_id == invitee_user_id)
                .first()
            )
            if not invite or invite.status == STATUS_ACTIVE:
                return
            invite.status = STATUS_REJECTED
            invite.reject_reason = (reason or "")[:255]
            invite.updated_at = datetime.utcnow()
            session.commit()
        finally:
            session.close()

    @staticmethod
    def evaluate_after_ichancy_link(invitee: User) -> str:
        """بعد ربط iChancy — ترقية لحالة قيد التحقق أو رفض مكرر."""
        session = db.get_session()
        try:
            invite = (
                session.query(ReferralInvite)
                .filter(ReferralInvite.invitee_id == invitee.id)
                .first()
            )
            if not invite:
                return ""
            if invite.status in (STATUS_ACTIVE, STATUS_REJECTED):
                return invite.status

            # فحص حساب iChancy مكرر تحت مستخدم آخر
            if invitee.ichancy_player_id:
                other = (
                    session.query(User)
                    .filter(
                        User.ichancy_player_id == invitee.ichancy_player_id,
                        User.id != invitee.id,
                    )
                    .first()
                )
                if other:
                    invite.status = STATUS_REJECTED
                    invite.reject_reason = "حساب iChancy مكرر / وهمي"
                    invite.updated_at = datetime.utcnow()
                    session.commit()
                    return STATUS_REJECTED

            if not invitee.ichancy_player_id:
                return invite.status

            invite.status = STATUS_PENDING
            invite.updated_at = datetime.utcnow()
            session.commit()
            return STATUS_PENDING
        finally:
            session.close()

    @staticmethod
    def activate_invite(
        invite_id: int,
        net_syp: float = 0.0,
        net_usd: float = 0.0,
        source: str = "manual",
    ) -> Tuple[bool, str]:
        """اعتماد إحالة نشطة بعد تحقق الشروط / المراجعة اليدوية."""
        min_usd = get_min_activity_usd()
        session = db.get_session()
        try:
            invite = session.query(ReferralInvite).filter(ReferralInvite.id == invite_id).first()
            if not invite:
                return False, "الإحالة غير موجودة"
            if invite.status == STATUS_REJECTED:
                return False, "الإحالة مرفوضة"
            invitee = session.query(User).filter(User.id == invite.invitee_id).first()
            if not invitee or not invitee.ichancy_player_id:
                return False, "لا يوجد حساب iChancy موثق"
            if net_usd < min_usd and net_syp <= 0:
                return False, f"النشاط أقل من الحد الأدنى ({min_usd:g}$)"

            invite.status = STATUS_ACTIVE
            invite.qualified_net_syp = float(net_syp or 0)
            invite.qualified_net_usd = float(net_usd or 0)
            invite.activity_source = source
            invite.activated_at = datetime.utcnow()
            invite.updated_at = datetime.utcnow()
            session.commit()
            return True, "تم اعتماد الإحالة نشطة"
        finally:
            session.close()

    @staticmethod
    def counts_for(referrer_id: int) -> Dict[str, int]:
        session = db.get_session()
        try:
            rows = (
                session.query(ReferralInvite)
                .filter(ReferralInvite.referrer_id == referrer_id)
                .all()
            )
            total = len(rows)
            active = sum(1 for r in rows if r.status == STATUS_ACTIVE)
            pending = sum(
                1 for r in rows if r.status in (STATUS_REGISTERED, STATUS_PENDING)
            )
            rejected = sum(1 for r in rows if r.status == STATUS_REJECTED)
            return {
                "total": total,
                "active": active,
                "pending": pending,
                "rejected": rejected,
            }
        finally:
            session.close()

    @staticmethod
    def dashboard(user: User) -> Dict[str, Any]:
        counts = ReferralArmyService.counts_for(user.id)
        rank = resolve_rank(counts["active"], user.referral_rank_override)
        nxt, remaining = next_rank_info(counts["active"])
        return {
            "rank": rank,
            "next_rank": nxt,
            "remaining": remaining,
            "counts": counts,
            "available": float(user.commission_available or 0),
            "pending": float(user.commission_pending or 0),
            "withdrawn": float(user.commission_withdrawn or 0),
        }

    @staticmethod
    def monthly_commission(user_id: int) -> float:
        session = db.get_session()
        try:
            start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            rows = (
                session.query(CommissionEntry)
                .filter(
                    CommissionEntry.user_id == user_id,
                    CommissionEntry.entry_type == "accrual",
                    CommissionEntry.created_at >= start,
                    CommissionEntry.status.in_(["pending_review", "available", "withdrawn"]),
                )
                .all()
            )
            return sum(float(r.amount or 0) for r in rows)
        finally:
            session.close()

    @staticmethod
    def accrue_commission_from_net(
        referrer_id: int,
        net_activity_syp: float,
        note: str = "",
    ) -> Tuple[bool, str]:
        """
        عمولة = صافي النشاط المؤهل × نسبة الرتبة.
        بدون بيانات رسمية/مراجعة تبقى قيد المراجعة.
        """
        if net_activity_syp <= 0:
            return False, "لا يوجد صافي نشاط مؤهل"

        session = db.get_session()
        try:
            user = session.query(User).filter(User.id == referrer_id).first()
            if not user:
                return False, "المستخدم غير موجود"
            counts = ReferralArmyService.counts_for(referrer_id)
            rank = resolve_rank(counts["active"], user.referral_rank_override)
            rate = float(rank.get("rate") or 0)
            if rate <= 0:
                return False, "لا رتبة مؤهلة للعمولة بعد"

            amount = round(net_activity_syp * (rate / 100.0), 2)
            if amount <= 0:
                return False, "العمولة صفر"

            hold = get_hold_days()
            available_at = datetime.utcnow() + timedelta(days=hold)
            entry = CommissionEntry(
                user_id=user.id,
                entry_type="accrual",
                status="pending_review",
                amount=amount,
                rank_code=rank.get("code"),
                rate_percent=rate,
                net_activity_syp=float(net_activity_syp),
                description=note or "عمولة من صافي النشاط المؤهل",
                available_at=available_at,
            )
            session.add(entry)
            user.commission_pending = float(user.commission_pending or 0) + amount
            # توافق خلفي مع حقل الأرباح القديم للعرض
            user.referral_earnings = float(user.referral_earnings or 0) + amount
            session.commit()
            return True, f"تم تسجيل عمولة {amount:g} قيد المراجعة ({hold} يوم)"
        finally:
            session.close()

    @staticmethod
    def release_matured_commissions() -> int:
        """تحويل العمولات المنتهية مدة مراجعتها إلى متاح."""
        now = datetime.utcnow()
        session = db.get_session()
        released = 0
        try:
            rows = (
                session.query(CommissionEntry)
                .filter(
                    CommissionEntry.entry_type == "accrual",
                    CommissionEntry.status == "pending_review",
                    CommissionEntry.available_at.isnot(None),
                    CommissionEntry.available_at <= now,
                )
                .all()
            )
            for entry in rows:
                user = session.query(User).filter(User.id == entry.user_id).first()
                if not user:
                    continue
                amt = float(entry.amount or 0)
                entry.status = "available"
                entry.processed_at = now
                user.commission_pending = max(0.0, float(user.commission_pending or 0) - amt)
                user.commission_available = float(user.commission_available or 0) + amt
                released += 1
            session.commit()
            return released
        finally:
            session.close()

    @staticmethod
    def request_withdraw(user: User, amount: float) -> Tuple[bool, str]:
        min_w = get_min_commission_withdraw()
        if amount < min_w:
            return False, f"الحد الأدنى لسحب العمولة {min_w:g}"
        session = db.get_session()
        try:
            db_user = session.query(User).filter(User.id == user.id).first()
            avail = float(db_user.commission_available or 0)
            if amount > avail:
                return False, "الرصيد المتاح غير كافٍ"
            db_user.commission_available = avail - amount
            db_user.commission_withdrawn = float(db_user.commission_withdrawn or 0) + amount
            # تحويل لرصيد المحفظة للسحب لاحقاً أو انتظار موافقة أدمن
            db_user.balance = float(db_user.balance or 0) + amount
            session.add(
                CommissionEntry(
                    user_id=db_user.id,
                    entry_type="withdraw",
                    status="withdrawn",
                    amount=amount,
                    description="سحب عمولة إلى محفظة البوت",
                    processed_at=datetime.utcnow(),
                )
            )
            session.commit()
            return True, "تم تحويل العمولة إلى محفظة البوت"
        finally:
            session.close()

    @staticmethod
    def commission_summary_for_referrer(referrer_id: int) -> Dict[str, float]:
        """مجموع صافي النشاط والعمولة فقط — بدون تفاصيل أسماء."""
        session = db.get_session()
        try:
            invites = (
                session.query(ReferralInvite)
                .filter(
                    ReferralInvite.referrer_id == referrer_id,
                    ReferralInvite.status == STATUS_ACTIVE,
                )
                .all()
            )
            net = sum(float(i.qualified_net_syp or 0) for i in invites)
            entries = (
                session.query(CommissionEntry)
                .filter(
                    CommissionEntry.user_id == referrer_id,
                    CommissionEntry.entry_type == "accrual",
                )
                .all()
            )
            commission = sum(float(e.amount or 0) for e in entries if e.status != "cancelled")
            return {"net_activity_syp": net, "commission_total": commission}
        finally:
            session.close()
