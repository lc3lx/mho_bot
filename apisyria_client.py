"""
عميل API SYRIA - سيريتل كاش وشام كاش
التوثيق: https://apisyria.com/api/docs
"""

import logging
import re
from typing import Any, Dict, Optional

import requests

from config import Config

logger = logging.getLogger(__name__)


class ApiSyriaError(Exception):
    """خطأ من API SYRIA"""

    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ApiSyriaClient:
    """عميل واجهة API SYRIA"""

    def __init__(self):
        cfg = Config.APISYRIA_CONFIG
        self.base_url = cfg["base_url"].rstrip("/")
        self.api_key = cfg["api_key"]
        self.syriatel_gsm = cfg["syriatel_gsm"]
        self.syriatel_pin = cfg["syriatel_pin"]
        self.shamcash_account = cfg["shamcash_account"]
        self.tx_period = cfg["tx_search_period"]
        self.currency = cfg["currency"]
        self.deposit_timeout_minutes = int(cfg.get("deposit_timeout_minutes", 15))

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def syriatel_ready(self) -> bool:
        codes = Config.get_syriatel_codes()
        return self.is_configured and bool(codes or self.syriatel_gsm)

    def shamcash_ready(self) -> bool:
        return self.is_configured and bool(self.shamcash_account)

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        params: Dict[str, Any],
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        if not self.is_configured:
            raise ApiSyriaError("مفتاح API SYRIA غير مُعدّ. أضف APISYRIA_API_KEY في ملف .env")

        try:
            if method.upper() == "GET":
                response = requests.get(
                    self.base_url,
                    params=params,
                    headers=self._headers(),
                    timeout=timeout,
                )
            else:
                response = requests.post(
                    self.base_url,
                    params=params,
                    data=data,
                    headers={
                        **self._headers(),
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    timeout=timeout,
                )
        except requests.RequestException as exc:
            logger.error("ApiSyria connection error: %s", exc)
            raise ApiSyriaError(f"تعذر الاتصال بـ API SYRIA: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiSyriaError(
                f"استجابة غير صالحة من API SYRIA (HTTP {response.status_code})"
            ) from exc

        if response.status_code >= 400 or not payload.get("success"):
            error_msg = payload.get("error") or payload.get("message") or "فشل الطلب"
            raise ApiSyriaError(str(error_msg), status_code=response.status_code)

        return payload

    def get_status(self) -> Dict[str, Any]:
        return self._request("GET", {"resource": "status"})

    def list_accounts(self) -> Dict[str, Any]:
        return self._request("GET", {"resource": "accounts", "action": "list"})

    def syriatel_find_transaction(self, tx: str, gsm: Optional[str] = None) -> Dict[str, Any]:
        gsm = gsm or self.syriatel_gsm
        return self._request(
            "GET",
            {
                "resource": "syriatel",
                "action": "find_tx",
                "tx": tx.strip(),
                "gsm": gsm,
                "period": self.tx_period,
            },
        )

    def shamcash_find_transaction(self, tx: str, account_address: Optional[str] = None) -> Dict[str, Any]:
        account_address = account_address or self.shamcash_account
        return self._request(
            "GET",
            {
                "resource": "shamcash",
                "action": "find_tx",
                "tx": tx.strip(),
                "account_address": account_address,
            },
        )

    def syriatel_transfer(self, to_gsm: str, amount: float, gsm: Optional[str] = None, pin_code: Optional[str] = None) -> Dict[str, Any]:
        gsm = gsm or self.syriatel_gsm
        pin_code = pin_code or self.syriatel_pin
        if not pin_code:
            raise ApiSyriaError("رمز PIN لسيريتل كاش غير مُعدّ (APISYRIA_SYRIATEL_PIN)")

        return self._request(
            "POST",
            {"resource": "syriatel", "action": "transfer_cash"},
            {
                "gsm": gsm,
                "to_gsm": to_gsm.strip(),
                "amount": str(int(amount) if amount == int(amount) else amount),
                "pin_code": pin_code,
            },
            timeout=60,
        )

    def shamcash_transfer(
        self,
        receive_key: str,
        amount: float,
        account_address: Optional[str] = None,
        currency: Optional[str] = None,
        note: str = "",
    ) -> Dict[str, Any]:
        account_address = account_address or self.shamcash_account
        currency = currency or self.currency

        data = {
            "account_address": account_address,
            "receive_key": receive_key.strip(),
            "amount": str(int(amount) if amount == int(amount) else amount),
            "currency": currency,
        }
        if note:
            data["note"] = note[:180]

        return self._request(
            "POST",
            {"resource": "shamcash", "action": "transfer"},
            data,
            timeout=60,
        )

    @staticmethod
    def normalize_tx_id(tx: str) -> str:
        return re.sub(r"\D", "", tx.strip())

    @staticmethod
    def parse_syriatel_amount(transaction: Dict[str, Any]) -> float:
        return float(str(transaction.get("amount", "0")).replace(",", ""))

    @staticmethod
    def parse_shamcash_amount(transaction: Dict[str, Any]) -> float:
        return float(transaction.get("amount", 0))

    @staticmethod
    def amounts_match(expected: float, actual: float, tolerance: float = 0.01) -> bool:
        return abs(expected - actual) <= tolerance

    @staticmethod
    def parse_tx_datetime(transaction: Dict[str, Any]):
        """استخراج وقت العملية من استجابة سيريتل أو شام كاش"""
        from datetime import datetime

        raw = (
            transaction.get("date")
            or transaction.get("datetime")
            or transaction.get("created_at")
            or ""
        )
        if not raw:
            return None

        text = str(raw).strip()
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
        ):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    def is_within_deposit_window(
        self,
        transaction: Dict[str, Any],
        request_created_at,
        timeout_minutes: int = None,
    ) -> bool:
        """
        يقبل العملية فقط إذا:
        - الطلب نفسه لم يتجاوز المهلة (افتراضياً 15 دقيقة)
        - وقت العملية ضمن آخر ربع ساعة (توقيت UTC أو المحلي — API قد يعيد محلياً)
        """
        from datetime import datetime, timedelta

        minutes = timeout_minutes or self.deposit_timeout_minutes
        now_utc = datetime.utcnow()

        if request_created_at and now_utc - request_created_at > timedelta(minutes=minutes):
            return False

        tx_time = self.parse_tx_datetime(transaction)
        if not tx_time:
            return False

        # تواريخ API قد تكون بتوقيت سوريا المحلي؛ نقبل إذا طابقت UTC أو المحلي
        for now in (now_utc, datetime.now()):
            window_start = now - timedelta(minutes=minutes + 1)
            window_end = now + timedelta(minutes=2)
            if window_start <= tx_time <= window_end:
                return True
        return False
