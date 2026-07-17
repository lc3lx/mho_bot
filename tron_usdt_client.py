"""
عميل USDT TRC20 عبر TronGrid
التحقق التلقائي بمبلغ فريد (فواصل عشرية) لكل طلب إيداع
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

import requests

from config import Config

logger = logging.getLogger(__name__)

USDT_DECIMALS = 6


class TronUsdtError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class TronUsdtClient:
    """مراقبة وتحقق تحويلات USDT TRC20"""

    def __init__(self):
        cfg = Config.USDT_CONFIG
        self.api_base = cfg["trongrid_url"].rstrip("/")
        self.api_key = cfg.get("trongrid_api_key", "")
        self.wallet_address = cfg.get("wallet_address", "")
        self.contract_address = cfg.get(
            "contract_address", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        )
        self.syp_rate = float(cfg.get("syp_rate", 15000))
        self.min_confirmations = int(cfg.get("min_confirmations", 1))
        self.deposit_timeout_minutes = int(cfg.get("deposit_timeout_minutes", 30))

    def current_syp_rate(self) -> float:
        return Config.get_usdt_syp_rate()

    @property
    def is_configured(self) -> bool:
        return bool(self.wallet_address and self.wallet_address.startswith("T"))

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["TRON-PRO-API-KEY"] = self.api_key
        return headers

    def syp_to_usdt_base(self, syp_amount: float) -> float:
        """تحويل الليرة إلى USDT (جزء أساسي بخانتين عشريتين)"""
        return math.floor((syp_amount / self.current_syp_rate()) * 100) / 100

    def generate_unique_usdt_amount(
        self, syp_amount: float, used_amounts: Set[float], transaction_id: int
    ) -> float:
        """
        توليد مبلغ USDT فريد بإضافة خانات عشرية تمييزية
        مثال: 10.00 → 10.001, 10.002, 10.003 ...
        """
        base = self.syp_to_usdt_base(syp_amount)
        if base <= 0:
            raise TronUsdtError("المبلغ صغير جداً بعد التحويل لـ USDT")

        normalized_used = {round(a, USDT_DECIMALS) for a in used_amounts if a}

        for suffix in range(1, 1000):
            candidate = round(base + suffix / 1000, 3)
            if candidate not in normalized_used:
                return candidate

        for suffix in range(1000, 1_000_000):
            candidate = round(base + suffix / 1_000_000, 6)
            if candidate not in normalized_used:
                return candidate

        fallback = round(base + (transaction_id % 999999) / 1_000_000, 6)
        if fallback not in normalized_used:
            return fallback

        raise TronUsdtError("تعذر توليد مبلغ فريد. حاول لاحقاً.")

    @staticmethod
    def usdt_to_sun(usdt_amount: float) -> int:
        return int(round(usdt_amount * (10 ** USDT_DECIMALS)))

    @staticmethod
    def sun_to_usdt(sun_value: str) -> float:
        return int(sun_value) / (10 ** USDT_DECIMALS)

    @staticmethod
    def format_usdt(amount: float) -> str:
        text = f"{amount:.{USDT_DECIMALS}f}".rstrip("0").rstrip(".")
        return text if "." in text else f"{text}.0"

    def fetch_incoming_transfers(self, limit: int = 100) -> List[Dict[str, Any]]:
        """جلب آخر تحويلات USDT الواردة للمحفظة"""
        if not self.is_configured:
            raise TronUsdtError("محفظة USDT غير مُعدّة")

        url = f"{self.api_base}/v1/accounts/{self.wallet_address}/transactions/trc20"
        params = {
            "limit": limit,
            "only_confirmed": "true",
            "contract_address": self.contract_address,
            "only_to": "true",
        }

        try:
            response = requests.get(
                url, params=params, headers=self._headers(), timeout=30
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            logger.error("TronGrid request failed: %s", exc)
            raise TronUsdtError(f"تعذر الاتصال بـ TronGrid: {exc}") from exc

        return payload.get("data", [])

    def find_matching_transfer(
        self,
        expected_usdt: float,
        since: datetime,
        used_tx_hashes: Set[str],
    ) -> Optional[Dict[str, Any]]:
        """البحث عن تحويل وارد يطابق المبلغ الفريد"""
        expected_sun = self.usdt_to_sun(expected_usdt)
        since_ms = int(since.timestamp() * 1000) - 60_000
        wallet = self.wallet_address

        try:
            transfers = self.fetch_incoming_transfers()
        except TronUsdtError:
            return None

        for item in transfers:
            if item.get("type") != "Transfer":
                continue

            if item.get("to", "") != wallet:
                continue

            tx_hash = item.get("transaction_id", "")
            if not tx_hash or tx_hash in used_tx_hashes:
                continue

            block_ts = int(item.get("block_timestamp", 0))
            if block_ts < since_ms:
                continue

            try:
                value_sun = int(item.get("value", "0"))
            except (TypeError, ValueError):
                continue

            if value_sun == expected_sun:
                return {
                    "transaction_id": tx_hash,
                    "amount_usdt": self.sun_to_usdt(str(value_sun)),
                    "from": item.get("from", ""),
                    "block_timestamp": block_ts,
                }

        return None

    def is_deposit_expired(self, created_at: datetime) -> bool:
        expiry = created_at + timedelta(minutes=self.deposit_timeout_minutes)
        return datetime.utcnow() > expiry
