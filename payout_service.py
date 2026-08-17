"""
إعدادات التقبيض وطرق الدفع القابلة للتوسعة.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from config import Config
from database import DatabaseManager, PayoutMethod

logger = logging.getLogger(__name__)
db = DatabaseManager()

# مفاتيح bot_settings
SK_MIN = "withdraw_min"
SK_MAX = "withdraw_max"
SK_DAILY_LIMIT = "withdraw_daily_limit"
SK_MAX_REQUESTS = "withdraw_max_requests_day"
SK_COOLDOWN = "withdraw_cooldown_seconds"
SK_FEE_PERCENT = "withdraw_fee_percent"
SK_FEE_METHOD = "withdraw_fee_method"  # percent_of_withdraw
SK_PAYOUT_GROUP = "payout_admin_group_id"
SK_SUPPORT_GROUP = "support_group_id"

FEE_METHOD_PERCENT_WITHDRAW = "percent_of_withdraw"

REJECT_REASONS = {
    "bad_shamcash": "بيانات شام كاش غلط",
    "account_issue": "مشكلة بالحساب",
    "wrong_amount": "مبلغ غير صحيح",
    "duplicate": "طلب مكرر",
    "other": "سبب آخر",
}


def _setting_float(key: str, default: float) -> float:
    raw = db.get_setting(key, None)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _setting_int(key: str, default: int) -> int:
    raw = db.get_setting(key, None)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return int(default)


def get_min_withdraw() -> float:
    return _setting_float(SK_MIN, Config.MIN_WITHDRAWAL)


def get_max_withdraw() -> Optional[float]:
    """None = بلا حد أعلى."""
    raw = db.get_setting(SK_MAX, None)
    if raw is None or str(raw).strip() == "":
        # من env إن وُجد رقم موجب
        env_max = float(Config.MAX_WITHDRAWAL or 0)
        return env_max if env_max > 0 else None
    try:
        val = float(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def get_daily_amount_limit() -> Optional[float]:
    """حد يومي بالمبلغ للمستخدم — None بلا حد."""
    raw = db.get_setting(SK_DAILY_LIMIT, "")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        val = float(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def get_max_requests_per_day() -> int:
    return _setting_int(
        SK_MAX_REQUESTS,
        Config.SECURITY_CONFIG.get("max_daily_withdrawals", 3),
    )


def get_cooldown_seconds() -> int:
    return _setting_int(
        SK_COOLDOWN,
        Config.SECURITY_CONFIG.get("withdrawal_cooldown", 3600),
    )


def get_fee_percent() -> float:
    return _setting_float(SK_FEE_PERCENT, Config.WITHDRAWAL_FEE_PERCENTAGE)


def get_fee_method() -> str:
    return (db.get_setting(SK_FEE_METHOD, FEE_METHOD_PERCENT_WITHDRAW) or FEE_METHOD_PERCENT_WITHDRAW).strip()


def calculate_fee(amount: float) -> tuple[float, float]:
    """(fee, net) — حالياً نسبة من مبلغ السحب فقط."""
    method = get_fee_method()
    pct = get_fee_percent()
    if method != FEE_METHOD_PERCENT_WITHDRAW:
        # احتياطي: نفس المنطق حتى تُضاف طرق أخرى
        pass
    fee = round(float(amount or 0) * (pct / 100.0), 2)
    net = round(float(amount or 0) - fee, 2)
    return fee, net


def get_payout_admin_group_id() -> Optional[int]:
    raw = db.get_setting(SK_PAYOUT_GROUP, None)
    if raw is None or str(raw).strip() == "":
        env = getattr(Config, "PAYOUT_ADMIN_GROUP_ID", None)
        raw = env
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def get_support_group_id() -> Optional[int]:
    raw = db.get_setting(SK_SUPPORT_GROUP, None)
    if raw is None or str(raw).strip() == "":
        env = getattr(Config, "SUPPORT_GROUP_ID", None)
        raw = env
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def infer_group_kind(title: str) -> Optional[str]:
    """دعم / قبض من عنوان الكروب."""
    t = (title or "").strip()
    if "دعم" in t:
        return "support"
    if "قبض" in t or "تقبيض" in t:
        return "payout"
    return None


def bind_group_chat(kind: str, chat_id: int) -> None:
    key = SK_PAYOUT_GROUP if kind == "payout" else SK_SUPPORT_GROUP
    set_withdraw_setting(key, str(chat_id))


def maybe_autolink_group(chat_id: int, title: str) -> Optional[str]:
    """يربط كروب قبض/دعم تلقائياً من الاسم. يرجع kind أو None."""
    kind = infer_group_kind(title)
    if not kind or not chat_id:
        return None
    bind_group_chat(kind, int(chat_id))
    return kind


def set_withdraw_setting(key: str, value: str) -> None:
    db.set_setting(key, str(value))


def settings_snapshot() -> Dict[str, Any]:
    max_w = get_max_withdraw()
    daily = get_daily_amount_limit()
    return {
        "min": get_min_withdraw(),
        "max": max_w,
        "daily_limit": daily,
        "max_requests": get_max_requests_per_day(),
        "cooldown": get_cooldown_seconds(),
        "fee_percent": get_fee_percent(),
        "fee_method": get_fee_method(),
        "payout_group": get_payout_admin_group_id(),
        "support_group": get_support_group_id(),
    }


def mask_destination(value: str, keep: int = 4) -> str:
    text = (value or "").strip()
    if len(text) <= keep * 2:
        if len(text) <= 2:
            return "***"
        return text[0] + "***" + text[-1]
    return f"{text[:keep]}…{text[-keep:]}"


def new_public_order_id() -> str:
    return f"WD{uuid.uuid4().hex[:10].upper()}"


def parse_required_fields(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:
        pass
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def list_methods(enabled_only: bool = False) -> List[PayoutMethod]:
    session = db.get_session()
    try:
        q = session.query(PayoutMethod).order_by(
            PayoutMethod.sort_order.asc(), PayoutMethod.id.asc()
        )
        if enabled_only:
            q = q.filter(PayoutMethod.enabled.is_(True))
        rows = q.all()
        return [db._detach(session, r) for r in rows]
    finally:
        session.close()


def get_method(code: str) -> Optional[PayoutMethod]:
    if not code:
        return None
    session = db.get_session()
    try:
        row = (
            session.query(PayoutMethod)
            .filter(PayoutMethod.code == str(code).strip())
            .first()
        )
        return db._detach(session, row)
    finally:
        session.close()


def get_method_by_id(method_id: int) -> Optional[PayoutMethod]:
    session = db.get_session()
    try:
        row = session.query(PayoutMethod).filter(PayoutMethod.id == method_id).first()
        return db._detach(session, row)
    finally:
        session.close()


def upsert_method(
    code: str,
    name: str,
    *,
    enabled: bool = False,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    required_fields: Optional[List[str]] = None,
    admin_group_id: Optional[str] = None,
    instructions: Optional[str] = None,
    sort_order: int = 100,
) -> PayoutMethod:
    session = db.get_session()
    try:
        row = session.query(PayoutMethod).filter(PayoutMethod.code == code).first()
        fields_json = json.dumps(required_fields or [], ensure_ascii=False)
        if row:
            row.name = name
            row.enabled = enabled
            row.min_amount = min_amount
            row.max_amount = max_amount
            row.required_fields = fields_json
            row.admin_group_id = admin_group_id
            if instructions is not None:
                row.instructions = instructions
            row.sort_order = sort_order
        else:
            row = PayoutMethod(
                code=code,
                name=name,
                enabled=enabled,
                min_amount=min_amount,
                max_amount=max_amount,
                required_fields=fields_json,
                admin_group_id=admin_group_id,
                instructions=instructions or "",
                sort_order=sort_order,
            )
            session.add(row)
        session.commit()
        session.refresh(row)
        return db._detach(session, row)
    finally:
        session.close()


def set_method_enabled(method_id: int, enabled: bool) -> Optional[PayoutMethod]:
    session = db.get_session()
    try:
        row = session.query(PayoutMethod).filter(PayoutMethod.id == method_id).first()
        if not row:
            return None
        row.enabled = bool(enabled)
        session.commit()
        return db._detach(session, row)
    finally:
        session.close()


def update_method_field(method_id: int, field: str, value) -> Optional[PayoutMethod]:
    allowed = {
        "name",
        "min_amount",
        "max_amount",
        "admin_group_id",
        "instructions",
        "required_fields",
        "sort_order",
        "enabled",
    }
    if field not in allowed:
        return None
    session = db.get_session()
    try:
        row = session.query(PayoutMethod).filter(PayoutMethod.id == method_id).first()
        if not row:
            return None
        if field == "required_fields":
            if isinstance(value, list):
                value = json.dumps(value, ensure_ascii=False)
            elif value is None:
                value = "[]"
        if field in ("min_amount", "max_amount", "sort_order") and value == "":
            value = None
        setattr(row, field, value)
        session.commit()
        return db._detach(session, row)
    finally:
        session.close()


def method_display_name(code: str) -> str:
    m = get_method(code)
    if m:
        return m.name
    fallback = {
        "shamcash": "💠 شام كاش",
        "syriatel_cash": "📱 سيرياتيل كاش",
        "usdt": "🌐 USDT",
        "bank_transfer": "🏦 حوالة",
    }
    return fallback.get(code or "", code or "—")
