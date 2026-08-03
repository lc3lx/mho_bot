"""
جيش نابليون — منطق الإحالات والعمولات والرتب.
العمولة من صافي النشاط المؤهل فقط (مراجعة يدوية حالياً).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from config import Config
from database import (
    ArmyAuditLog,
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
        "rate": 10.0,
    },
    {
        "code": "captain",
        "title": "🥈 قائد الكتيبة",
        "min_active": 20,
        "rate": 12.0,
    },
    {
        "code": "general",
        "title": "🥇 جنرال نابليون",
        "min_active": 75,
        "rate": 16.0,
    },
    {
        "code": "emperor",
        "title": "👑 الإمبراطور",
        "min_active": 150,
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

COMMISSION_STATUS_LABELS = {
    "pending_review": "⏳ قيد المراجعة",
    "available": "✅ متاحة",
    "awaiting_payout": "🏧 بانتظار التقبيض",
    "withdrawn": "🏧 مسحوبة",
    "cancelled": "❌ ملغية",
    "adjusted": "❌ معدّلة",
}

LEDGER_PAGE_SIZE = 5


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
    return _get_float("army_min_commission_withdraw", 200000.0)


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


def audit_log(
    admin_user,
    action: str,
    target_type: str = "",
    target_id: str = "",
    before: str = "",
    after: str = "",
    reason: str = "",
) -> None:
    session = db.get_session()
    try:
        name = "admin"
        tg_id = None
        if admin_user:
            tg_id = int(getattr(admin_user, "id", 0) or 0) or None
            uname = getattr(admin_user, "username", None)
            first = getattr(admin_user, "first_name", None) or ""
            name = f"@{uname}" if uname else (first or str(tg_id or "admin"))
        session.add(
            ArmyAuditLog(
                admin_telegram_id=tg_id,
                admin_name=name,
                action=action,
                target_type=target_type,
                target_id=str(target_id or ""),
                before_value=(before or "")[:2000],
                after_value=(after or "")[:2000],
                reason=(reason or "")[:1000],
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("فشل تسجيل audit جيش نابليون")
    finally:
        session.close()


class ReferralArmyService:
    """خدمة جيش نابليون"""

    @staticmethod
    def create_invite(referrer: User, invitee: User) -> Optional[ReferralInvite]:
        session = db.get_session()
        try:
            if str(referrer.telegram_id) == str(invitee.telegram_id):
                return None
            if referrer.id == invitee.id:
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
    def reject_invite(
        invite_id: int,
        reason: str,
        admin_user=None,
        notify_telegram_id: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """يرفض إحالة ويعيد (ok, msg, invitee_telegram_id)."""
        session = db.get_session()
        try:
            invite = (
                session.query(ReferralInvite)
                .filter(ReferralInvite.id == invite_id)
                .first()
            )
            if not invite:
                return False, "الإحالة غير موجودة", None
            if invite.status == STATUS_ACTIVE:
                return False, "الإحالة نشطة مسبقاً — لا تُرفض هكذا", None
            before = invite.status
            invite.status = STATUS_REJECTED
            invite.reject_reason = (reason or "رفض إداري")[:255]
            invite.updated_at = datetime.utcnow()
            invitee = session.query(User).filter(User.id == invite.invitee_id).first()
            tg = invitee.telegram_id if invitee else None
            session.commit()
            audit_log(
                admin_user,
                "reject_invite",
                "invite",
                str(invite_id),
                before,
                STATUS_REJECTED,
                reason,
            )
            return True, "تم رفض الإحالة", tg
        finally:
            session.close()

    @staticmethod
    def set_invite_status(
        invite_id: int,
        status: str,
        reason: str = "",
        admin_user=None,
    ) -> Tuple[bool, str]:
        if status not in (
            STATUS_REGISTERED,
            STATUS_PENDING,
            STATUS_ACTIVE,
            STATUS_REJECTED,
        ):
            return False, "حالة غير صالحة"
        session = db.get_session()
        try:
            invite = (
                session.query(ReferralInvite)
                .filter(ReferralInvite.id == invite_id)
                .first()
            )
            if not invite:
                return False, "غير موجودة"
            before = invite.status
            invite.status = status
            if reason:
                invite.reject_reason = reason[:255]
            invite.updated_at = datetime.utcnow()
            if status == STATUS_ACTIVE:
                invite.activated_at = datetime.utcnow()
            session.commit()
            audit_log(
                admin_user,
                "set_invite_status",
                "invite",
                str(invite_id),
                before,
                status,
                reason,
            )
            return True, f"تم تحديث الحالة إلى {STATUS_LABELS.get(status, status)}"
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

            if invitee.ichancy_username:
                other = (
                    session.query(User)
                    .filter(
                        User.ichancy_username == invitee.ichancy_username,
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

            if not invitee.ichancy_player_id and not invitee.ichancy_username:
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
        admin_user=None,
        auto_accrue: bool = True,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """اعتماد إحالة نشطة بعد تحقق الشروط / المراجعة اليدوية."""
        min_usd = get_min_activity_usd()
        session = db.get_session()
        try:
            invite = session.query(ReferralInvite).filter(ReferralInvite.id == invite_id).first()
            if not invite:
                return False, "الإحالة غير موجودة", None
            if invite.status == STATUS_REJECTED:
                return False, "الإحالة مرفوضة", None
            invitee = session.query(User).filter(User.id == invite.invitee_id).first()
            if not invitee or (
                not invitee.ichancy_player_id and not invitee.ichancy_username
            ):
                return False, "لا يوجد حساب iChancy موثق", None

            # شرط النشاط: USD أو ما يعادله تقريباً عبر صافي SYP إن أُدخل يدوياً
            if float(net_usd or 0) < min_usd and float(net_syp or 0) <= 0:
                return False, f"النشاط أقل من الحد الأدنى ({min_usd:g}$)", None

            referrer = session.query(User).filter(User.id == invite.referrer_id).first()
            old_rank = None
            if referrer:
                old_counts = ReferralArmyService.counts_for(referrer.id)
                old_rank = resolve_rank(old_counts["active"], referrer.referral_rank_override)

            before = invite.status
            invite.status = STATUS_ACTIVE
            invite.qualified_net_syp = float(net_syp or 0)
            invite.qualified_net_usd = float(net_usd or 0)
            invite.activity_source = source
            invite.activated_at = datetime.utcnow()
            invite.updated_at = datetime.utcnow()
            session.commit()

            audit_log(
                admin_user,
                "activate_invite",
                "invite",
                str(invite_id),
                before,
                STATUS_ACTIVE,
                f"net_usd={net_usd} net_syp={net_syp}",
            )

            promotion = None
            if referrer:
                new_counts = ReferralArmyService.counts_for(referrer.id)
                new_rank = resolve_rank(new_counts["active"], referrer.referral_rank_override)
                if old_rank and new_rank and old_rank.get("code") != new_rank.get("code"):
                    if new_rank.get("min_active", 0) > old_rank.get("min_active", 0):
                        promotion = {
                            "telegram_id": referrer.telegram_id,
                            "rank_title": new_rank.get("title"),
                            "rate": new_rank.get("rate"),
                        }

            # عمولة يدوية من صافي النشاط المعتمد إن وُجد
            if auto_accrue and float(net_syp or 0) > 0 and referrer:
                ReferralArmyService.accrue_commission_from_net(
                    referrer.id,
                    float(net_syp),
                    note=f"عمولة إحالة #{invite_id}",
                    invite_id=invite_id,
                    admin_user=admin_user,
                )

            return True, "تم اعتماد الإحالة نشطة", promotion
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
            registered = sum(1 for r in rows if r.status == STATUS_REGISTERED)
            pending = sum(1 for r in rows if r.status == STATUS_PENDING)
            rejected = sum(1 for r in rows if r.status == STATUS_REJECTED)
            return {
                "total": total,
                "active": active,
                "registered": registered,
                "pending": pending,
                "pending_total": registered + pending,
                "rejected": rejected,
            }
        finally:
            session.close()

    @staticmethod
    def list_recruits(referrer_id: int, page: int = 0, page_size: int = 8) -> Dict[str, Any]:
        session = db.get_session()
        try:
            q = (
                session.query(ReferralInvite)
                .filter(ReferralInvite.referrer_id == referrer_id)
                .order_by(ReferralInvite.created_at.asc())
            )
            total = q.count()
            rows = q.offset(page * page_size).limit(page_size).all()
            items = []
            for i, inv in enumerate(rows, start=page * page_size + 1):
                items.append(
                    {
                        "index": i,
                        "status": inv.status,
                        "status_label": STATUS_LABELS.get(inv.status, inv.status),
                        "date": inv.created_at.strftime("%Y-%m-%d") if inv.created_at else "—",
                        "reject_reason": inv.reject_reason or "",
                    }
                )
            return {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
                "has_prev": page > 0,
                "has_next": (page + 1) * page_size < total,
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
                    CommissionEntry.status.in_(
                        ["pending_review", "available", "withdrawn", "awaiting_payout"]
                    ),
                )
                .all()
            )
            return sum(float(r.amount or 0) for r in rows)
        finally:
            session.close()

    @staticmethod
    def list_ledger(user_id: int, page: int = 0, page_size: int = LEDGER_PAGE_SIZE) -> Dict[str, Any]:
        session = db.get_session()
        try:
            q = (
                session.query(CommissionEntry)
                .filter(CommissionEntry.user_id == user_id)
                .order_by(CommissionEntry.created_at.desc())
            )
            total = q.count()
            rows = q.offset(page * page_size).limit(page_size).all()
            items = []
            for e in rows:
                items.append(
                    {
                        "id": e.id,
                        "date": e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else "—",
                        "amount": float(e.amount or 0),
                        "status": e.status,
                        "status_label": COMMISSION_STATUS_LABELS.get(e.status, e.status),
                        "type": e.entry_type,
                    }
                )
            return {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
                "has_prev": page > 0,
                "has_next": (page + 1) * page_size < total,
            }
        finally:
            session.close()

    @staticmethod
    def accrue_commission_from_net(
        referrer_id: int,
        net_activity_syp: float,
        note: str = "",
        invite_id: Optional[int] = None,
        admin_user=None,
    ) -> Tuple[bool, str]:
        """عمولة = صافي النشاط المؤهل × نسبة الرتبة. تبدأ قيد المراجعة."""
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
                invite_id=invite_id,
                description=note or "عمولة من صافي النشاط المؤهل",
                available_at=available_at,
            )
            session.add(entry)
            user.commission_pending = float(user.commission_pending or 0) + amount
            user.referral_earnings = float(user.referral_earnings or 0) + amount
            session.commit()
            session.refresh(entry)
            audit_log(
                admin_user,
                "accrue_commission",
                "commission",
                str(entry.id),
                "",
                str(amount),
                note,
            )
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
    def admin_approve_commission(entry_id: int, admin_user=None) -> Tuple[bool, str]:
        """اعتماد مبكر: تحويل قيد المراجعة → متاحة فوراً."""
        session = db.get_session()
        try:
            entry = session.query(CommissionEntry).filter(CommissionEntry.id == entry_id).first()
            if not entry or entry.entry_type != "accrual":
                return False, "الحركة غير موجودة"
            if entry.status != "pending_review":
                return False, f"الحالة الحالية: {entry.status}"
            user = session.query(User).filter(User.id == entry.user_id).first()
            amt = float(entry.amount or 0)
            entry.status = "available"
            entry.processed_at = datetime.utcnow()
            entry.available_at = datetime.utcnow()
            if user:
                user.commission_pending = max(0.0, float(user.commission_pending or 0) - amt)
                user.commission_available = float(user.commission_available or 0) + amt
            session.commit()
            audit_log(admin_user, "approve_commission", "commission", str(entry_id), "pending_review", "available")
            return True, "تم اعتماد العمولة وأصبحت متاحة"
        finally:
            session.close()

    @staticmethod
    def admin_reject_commission(entry_id: int, reason: str = "", admin_user=None) -> Tuple[bool, str]:
        session = db.get_session()
        try:
            entry = session.query(CommissionEntry).filter(CommissionEntry.id == entry_id).first()
            if not entry or entry.entry_type != "accrual":
                return False, "الحركة غير موجودة"
            if entry.status not in ("pending_review", "available"):
                return False, f"لا يمكن رفض حالة {entry.status}"
            user = session.query(User).filter(User.id == entry.user_id).first()
            amt = float(entry.amount or 0)
            before = entry.status
            if entry.status == "pending_review" and user:
                user.commission_pending = max(0.0, float(user.commission_pending or 0) - amt)
            elif entry.status == "available" and user:
                user.commission_available = max(0.0, float(user.commission_available or 0) - amt)
            entry.status = "cancelled"
            entry.admin_notes = reason or "رفض إداري"
            entry.processed_at = datetime.utcnow()
            session.commit()
            audit_log(admin_user, "reject_commission", "commission", str(entry_id), before, "cancelled", reason)
            return True, "تم إلغاء العمولة"
        finally:
            session.close()

    @staticmethod
    def admin_adjust_commission(
        entry_id: int, new_amount: float, reason: str = "", admin_user=None
    ) -> Tuple[bool, str]:
        session = db.get_session()
        try:
            entry = session.query(CommissionEntry).filter(CommissionEntry.id == entry_id).first()
            if not entry or entry.entry_type != "accrual":
                return False, "الحركة غير موجودة"
            if entry.status not in ("pending_review", "available"):
                return False, "لا يمكن التعديل الآن"
            user = session.query(User).filter(User.id == entry.user_id).first()
            old = float(entry.amount or 0)
            new_amount = float(new_amount)
            delta = new_amount - old
            if entry.status == "pending_review" and user:
                user.commission_pending = float(user.commission_pending or 0) + delta
            elif entry.status == "available" and user:
                user.commission_available = float(user.commission_available or 0) + delta
            entry.amount = new_amount
            entry.status = "adjusted" if new_amount <= 0 else entry.status
            if new_amount <= 0:
                entry.status = "cancelled"
            entry.admin_notes = (entry.admin_notes or "") + f"\nتعديل: {old}→{new_amount} | {reason}"
            entry.processed_at = datetime.utcnow()
            session.commit()
            audit_log(
                admin_user,
                "adjust_commission",
                "commission",
                str(entry_id),
                str(old),
                str(new_amount),
                reason,
            )
            return True, f"تم تعديل العمولة إلى {new_amount:g}"
        finally:
            session.close()

    @staticmethod
    def create_withdraw_request(
        user: User,
        amount: float,
        method: str,
        destination: str,
        crypto_currency: str = None,
        crypto_network: str = None,
    ) -> Tuple[bool, str, Optional[int]]:
        """حجز من العمولة المتاحة وإنشاء طلب تقبيض."""
        min_w = get_min_commission_withdraw()
        amount = float(amount)
        if amount < min_w:
            return False, f"الحد الأدنى لسحب العمولة {min_w:g}", None
        session = db.get_session()
        try:
            db_user = session.query(User).filter(User.id == user.id).first()
            avail = float(db_user.commission_available or 0)
            if amount > avail:
                return False, "الرصيد المتاح غير كافٍ", None

            # منع تكرار نفس الطلب النشط
            dup = (
                session.query(CommissionEntry)
                .filter(
                    CommissionEntry.user_id == user.id,
                    CommissionEntry.entry_type == "withdraw_request",
                    CommissionEntry.status == "awaiting_payout",
                    CommissionEntry.amount == amount,
                    CommissionEntry.payout_destination == destination,
                )
                .first()
            )
            if dup:
                return False, "الطلب موجود اصلًا", None

            db_user.commission_available = avail - amount
            entry = CommissionEntry(
                user_id=db_user.id,
                entry_type="withdraw_request",
                status="awaiting_payout",
                amount=amount,
                payout_method=method,
                payout_destination=destination,
                crypto_currency=crypto_currency,
                crypto_network=crypto_network,
                description=f"طلب سحب عمولة — {method} — {destination}",
            )
            session.add(entry)
            session.commit()
            session.refresh(entry)
            return True, "تم تسجيل طلب السحب", entry.id
        finally:
            session.close()

    @staticmethod
    def admin_pay_withdraw(entry_id: int, admin_user=None) -> Tuple[bool, str, Optional[str]]:
        session = db.get_session()
        try:
            entry = session.query(CommissionEntry).filter(CommissionEntry.id == entry_id).first()
            if not entry or entry.entry_type != "withdraw_request":
                return False, "الطلب غير موجود", None
            if entry.status != "awaiting_payout":
                return False, f"حالة الطلب: {entry.status}", None
            user = session.query(User).filter(User.id == entry.user_id).first()
            amt = float(entry.amount or 0)
            entry.status = "withdrawn"
            entry.entry_type = "withdraw"
            entry.processed_at = datetime.utcnow()
            if user:
                user.commission_withdrawn = float(user.commission_withdrawn or 0) + amt
            tg = user.telegram_id if user else None
            session.commit()
            audit_log(admin_user, "pay_commission_withdraw", "commission", str(entry_id), "awaiting_payout", "withdrawn")
            return True, "تم التقبيض", tg
        finally:
            session.close()

    @staticmethod
    def admin_reject_withdraw(entry_id: int, reason: str = "", admin_user=None) -> Tuple[bool, str, Optional[str]]:
        session = db.get_session()
        try:
            entry = session.query(CommissionEntry).filter(CommissionEntry.id == entry_id).first()
            if not entry or entry.entry_type != "withdraw_request":
                return False, "الطلب غير موجود", None
            if entry.status != "awaiting_payout":
                return False, f"حالة الطلب: {entry.status}", None
            user = session.query(User).filter(User.id == entry.user_id).first()
            amt = float(entry.amount or 0)
            if user:
                user.commission_available = float(user.commission_available or 0) + amt
            entry.status = "cancelled"
            entry.admin_notes = reason or "رفض سحب"
            entry.processed_at = datetime.utcnow()
            tg = user.telegram_id if user else None
            session.commit()
            audit_log(admin_user, "reject_commission_withdraw", "commission", str(entry_id), "awaiting_payout", "cancelled", reason)
            return True, "تم رفض السحب وإرجاع العمولة", tg
        finally:
            session.close()

    @staticmethod
    def commission_summary_for_referrer(referrer_id: int) -> Dict[str, float]:
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
            commission = sum(
                float(e.amount or 0) for e in entries if e.status not in ("cancelled",)
            )
            return {"net_activity_syp": net, "commission_total": commission}
        finally:
            session.close()

    @staticmethod
    def search_invites(query: str = "", limit: int = 15) -> List[Dict[str, Any]]:
        session = db.get_session()
        try:
            q = session.query(ReferralInvite).order_by(ReferralInvite.created_at.desc())
            rows = q.limit(80).all()
            out = []
            needle = (query or "").strip().lower()
            for inv in rows:
                referrer = session.query(User).filter(User.id == inv.referrer_id).first()
                invitee = session.query(User).filter(User.id == inv.invitee_id).first()
                blob = " ".join(
                    [
                        str(inv.id),
                        str(getattr(referrer, "telegram_id", "")),
                        str(getattr(invitee, "telegram_id", "")),
                        str(getattr(referrer, "username", "") or ""),
                        str(getattr(invitee, "username", "") or ""),
                        str(getattr(referrer, "first_name", "") or ""),
                        str(getattr(invitee, "first_name", "") or ""),
                    ]
                ).lower()
                if needle and needle not in blob:
                    continue
                out.append(
                    {
                        "id": inv.id,
                        "status": inv.status,
                        "status_label": STATUS_LABELS.get(inv.status, inv.status),
                        "referrer_tg": getattr(referrer, "telegram_id", ""),
                        "invitee_tg": getattr(invitee, "telegram_id", ""),
                        "reject_reason": inv.reject_reason or "",
                        "created_at": inv.created_at,
                    }
                )
                if len(out) >= limit:
                    break
            return out
        finally:
            session.close()

    @staticmethod
    def pending_commissions(limit: int = 20) -> List[CommissionEntry]:
        session = db.get_session()
        try:
            rows = (
                session.query(CommissionEntry)
                .filter(
                    CommissionEntry.status.in_(["pending_review", "awaiting_payout"])
                )
                .order_by(CommissionEntry.created_at.desc())
                .limit(limit)
                .all()
            )
            return [db._detach(session, r) for r in rows]
        finally:
            session.close()

    # توافق خلفي — لا يُستخدم للتحويل الصامت للمحفظة
    @staticmethod
    def request_withdraw(user: User, amount: float) -> Tuple[bool, str]:
        return False, "استخدم مسار سحب العمولة الجديد"
