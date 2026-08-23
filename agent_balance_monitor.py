"""
مراقبة رصيد كاشير الوكيل (حساب iChancy) وتنبيه كروب التقبيض عند الانخفاض.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from config import Config
from database import DatabaseManager
from ichancy_client import IchancyError
from ichancy_handler import ichancy_client
from utils import format_currency

import payout_service as ps
from _agent_debug import dbg

logger = logging.getLogger(__name__)
db = DatabaseManager()

SK_LAST_BALANCE = "ichancy_agent_last_balance"
SK_LAST_ALERT_AT = "ichancy_agent_low_alert_at"
SK_LAST_OK_AT = "ichancy_agent_balance_ok_at"


def _looks_like_agent_insufficient(msg: str) -> bool:
    if not msg:
        return False
    low = msg.lower()
    markers = (
        "insufficient",
        "not enough",
        "balance",
        "credit",
        "رصيد",
        "غير كاف",
        "لا يكفي",
        "credit limit",
        "لا يوجد رصيد",
    )
    return any(m in low or m in msg for m in markers)


def build_alert_text(balance: float, threshold: float) -> str:
    agent_user = (Config.ICHANCY_CONFIG.get("username") or "").strip() or "—"
    return (
        "🚨 *تنبيه: رصيد الكاشير منخفض*\n\n"
        f"💰 الرصيد الحالي: *{format_currency(balance)}*\n"
        f"⚠️ الحد التحذيري: *{format_currency(threshold)}*\n"
        f"👤 حساب الوكيل: `{agent_user}`\n\n"
        "يرجى شحن حساب الوكيل (الكاشير) فوراً حتى لا تتوقف عمليات الشحن للزبائن."
    )


async def notify_low_balance(
    context,
    balance: float,
    threshold: float,
    *,
    reason: str = "poll",
) -> bool:
    chat_id = ps.get_payout_admin_group_id()
    targets: list[int] = []
    if chat_id:
        targets.append(int(chat_id))
    else:
        targets.extend(Config.ADMIN_IDS or [])

    if not targets:
        dbg(
            "H4",
            "agent_balance_monitor:notify",
            "no notify targets",
            {"balance": balance, "reason": reason},
        )
        logger.warning("agent low balance but no payout group / admins configured")
        return False

    text = build_alert_text(balance, threshold)
    sent = 0
    for tid in targets:
        try:
            await context.bot.send_message(
                chat_id=tid,
                text=text,
                parse_mode="Markdown",
            )
            sent += 1
        except Exception as exc:
            logger.warning("failed agent balance alert to %s: %s", tid, exc)

    if sent:
        db.set_setting(SK_LAST_ALERT_AT, datetime.now(timezone.utc).isoformat())
        db.set_setting(SK_LAST_BALANCE, str(balance))
        dbg(
            "H3",
            "agent_balance_monitor:notify",
            "alert sent",
            {
                "balance": balance,
                "threshold": threshold,
                "targets": len(targets),
                "sent": sent,
                "reason": reason,
            },
        )
    return sent > 0


def _should_send_alert(balance: float, threshold: float) -> bool:
    if balance > threshold:
        return False
    cooldown = ps.get_agent_balance_alert_cooldown_seconds()
    last_raw = db.get_setting(SK_LAST_ALERT_AT, "") or ""
    if not str(last_raw).strip():
        return True
    try:
        last = datetime.fromisoformat(str(last_raw).replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed >= cooldown
    except (TypeError, ValueError):
        return True


async def check_agent_balance(
    context,
    *,
    force_alert: bool = False,
    reason: str = "poll",
) -> Optional[float]:
    if not ichancy_client.is_configured:
        dbg("H1", "agent_balance_monitor:check", "not configured", {})
        return None

    threshold = ps.get_agent_low_balance_threshold()
    try:
        balance = await asyncio.to_thread(ichancy_client.get_agent_balance)
    except IchancyError as exc:
        dbg(
            "H2",
            "agent_balance_monitor:check",
            "fetch failed",
            {"error": exc.message},
        )
        logger.warning("agent balance check failed: %s", exc.message)
        return None
    except Exception as exc:
        dbg(
            "H2",
            "agent_balance_monitor:check",
            "fetch exception",
            {"error": str(exc)},
        )
        logger.warning("agent balance check failed: %s", exc)
        return None

    db.set_setting(SK_LAST_BALANCE, str(balance))
    dbg(
        "H1",
        "agent_balance_monitor:check",
        "balance read",
        {
            "balance": balance,
            "threshold": threshold,
            "low": balance <= threshold,
            "reason": reason,
        },
    )

    if balance > threshold:
        db.set_setting(SK_LAST_OK_AT, datetime.now(timezone.utc).isoformat())
        db.set_setting(SK_LAST_ALERT_AT, "")
        return balance

    if force_alert or _should_send_alert(balance, threshold):
        await notify_low_balance(context, balance, threshold, reason=reason)
    return balance


async def poll_agent_balance(context) -> None:
    await check_agent_balance(context, reason="scheduled_poll")


async def maybe_alert_after_deposit_failure(context, error_message: str) -> None:
    if not _looks_like_agent_insufficient(error_message):
        return
    await check_agent_balance(context, force_alert=True, reason="deposit_failed")
