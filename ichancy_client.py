"""
عميل Agent API لمنصة ichancy
حسب وثيقة: Agent API Documentation (2026-01-22)

المصادقة: signIn → accessToken + refreshToken
عند result == "ex": refreshToken ثم إعادة الطلب
"""

import logging
import threading
from typing import Any, Dict, List, Optional

import requests

from config import Config

logger = logging.getLogger(__name__)


class IchancyError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class IchancyClient:
    """عميل Agent API الرسمي لـ ichancy"""

    def __init__(self):
        cfg = Config.ICHANCY_CONFIG
        self.base_url = cfg["api_base_url"].rstrip("/")
        self.username = cfg.get("username", "")
        self.password = cfg.get("password", "")
        self.parent_id = cfg.get("parent_id", "")
        self.currency = cfg.get("currency", "EUR")
        self.currency_code = cfg.get("currency_code", cfg.get("currency", "EUR"))
        self.money_status = int(cfg.get("money_status", 5))

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _extract_error(self, body: Dict[str, Any]) -> str:
        notifications = body.get("notification") or []
        if notifications and isinstance(notifications, list):
            first = notifications[0]
            if isinstance(first, dict) and first.get("content"):
                return str(first["content"])
        return "فشل الطلب على ichancy"

    def _raw_post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        use_auth: bool = True,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if use_auth:
            if not self._access_token:
                self.sign_in()
            headers["Authorization"] = f"Bearer {self._access_token}"

        try:
            response = requests.post(
                self._url(endpoint),
                json=data or {},
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            logger.error("Ichancy connection error: %s", exc)
            raise IchancyError(f"تعذر الاتصال بـ ichancy: {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise IchancyError(
                f"استجابة غير صالحة من ichancy (HTTP {response.status_code})"
            ) from exc

        if response.status_code == 401:
            raise IchancyError(
                self._extract_error(body) or "غير مصرح (401)",
                status_code=401,
            )
        if response.status_code == 403:
            raise IchancyError(
                "ليس لديك صلاحية لهذه العملية على حساب الوكيل",
                status_code=403,
            )
        if response.status_code == 422:
            raise IchancyError(self._extract_error(body), status_code=422)
        if response.status_code >= 400:
            raise IchancyError(
                self._extract_error(body),
                status_code=response.status_code,
            )

        return body

    def sign_in(self) -> Dict[str, str]:
        """POST global/api/UserApi/signIn"""
        if not self.is_configured:
            raise IchancyError(
                "إعدادات ichancy غير مكتملة. أضف ICHANCY_USERNAME و ICHANCY_PASSWORD في .env"
            )

        body = self._raw_post(
            "global/api/UserApi/signIn",
            {"username": self.username, "password": self.password},
            use_auth=False,
        )

        result = body.get("result")
        if not isinstance(result, dict) or not result.get("accessToken"):
            raise IchancyError(self._extract_error(body) or "فشل تسجيل الدخول")

        with self._lock:
            self._access_token = result["accessToken"]
            self._refresh_token = result.get("refreshToken")

        logger.info("Ichancy agent signed in successfully")
        return {
            "accessToken": self._access_token,
            "refreshToken": self._refresh_token or "",
        }

    def refresh_access_token(self) -> Dict[str, str]:
        """POST global/api/UserApi/refreshToken"""
        if not self._refresh_token:
            return self.sign_in()

        body = self._raw_post(
            "global/api/UserApi/refreshToken",
            {"refreshToken": self._refresh_token},
            use_auth=False,
        )

        result = body.get("result")
        if not isinstance(result, dict) or not result.get("accessToken"):
            logger.warning("Ichancy refresh failed, falling back to signIn")
            return self.sign_in()

        with self._lock:
            self._access_token = result["accessToken"]
            self._refresh_token = result.get("refreshToken", self._refresh_token)

        logger.info("Ichancy access token refreshed")
        return {
            "accessToken": self._access_token,
            "refreshToken": self._refresh_token or "",
        }

    def _request(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        retry_on_ex: bool = True,
    ) -> Any:
        """طلب محمي مع معالجة انتهاء التوكن (result == 'ex')"""
        body = self._raw_post(endpoint, data=data, use_auth=True, timeout=timeout)
        result = body.get("result")

        # التوكن منتهي / غير صالح حسب وثيقة API
        if result == "ex" and retry_on_ex:
            self.refresh_access_token()
            body = self._raw_post(endpoint, data=data, use_auth=True, timeout=timeout)
            result = body.get("result")
            if result == "ex":
                raise IchancyError("انتهت صلاحية الجلسة. أعد المحاولة.")

        if result is False:
            raise IchancyError(self._extract_error(body))

        return result

    def get_player_balance(self, player_id: str) -> float:
        """POST global/api/UserApi/getPlayerBalanceById"""
        result = self._request(
            "global/api/UserApi/getPlayerBalanceById",
            {"playerId": str(player_id)},
        )

        if not result:
            raise IchancyError("اللاعب غير موجود أو لا يوجد رصيد")

        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict) and item.get("main", True):
                    return float(item.get("balance", 0) or 0)
            if result and isinstance(result[0], dict):
                return float(result[0].get("balance", 0) or 0)
            return 0.0

        if isinstance(result, dict):
            return float(result.get("balance", 0) or 0)

        return 0.0

    def withdraw_from_player(
        self,
        player_id: str,
        amount: float,
        comment: str = "Bot wallet transfer",
    ) -> Dict[str, Any]:
        """
        POST global/api/UserApi/withdrawFromPlayer
        يخصم من رصيد اللاعب على المنصة (للتحويل إلى محفظة البوت).
        ملاحظة الوثيقة: amount سالب للسحب.
        """
        if amount <= 0:
            raise IchancyError("مبلغ السحب يجب أن يكون أكبر من صفر")

        result = self._request(
            "global/api/UserApi/withdrawFromPlayer",
            {
                "amount": -abs(float(amount)),
                "comment": comment[:200],
                "playerId": str(player_id),
                "currencyCode": self.currency_code,
                "currency": self.currency,
                "moneyStatus": self.money_status,
            },
            timeout=60,
        )

        if not isinstance(result, dict):
            raise IchancyError("استجابة سحب غير متوقعة من ichancy")
        return result

    def deposit_to_player(
        self,
        player_id: str,
        amount: float,
        comment: str = "Bot deposit to platform",
    ) -> Dict[str, Any]:
        """POST global/api/UserApi/depositToPlayer — شحن رصيد اللاعب على المنصة"""
        if amount <= 0:
            raise IchancyError("مبلغ الإيداع يجب أن يكون أكبر من صفر")

        result = self._request(
            "global/api/UserApi/depositToPlayer",
            {
                "amount": abs(float(amount)),
                "comment": comment[:200],
                "playerId": str(player_id),
                "currencyCode": self.currency_code,
                "currency": self.currency,
                "moneyStatus": self.money_status,
            },
            timeout=60,
        )

        if not isinstance(result, dict):
            raise IchancyError("استجابة إيداع غير متوقعة من ichancy")
        return result

    def find_player_by_id(self, player_id: str) -> Optional[Dict[str, Any]]:
        """POST getPlayersForCurrentAgent — بحث بـ playerId"""
        result = self._request(
            "global/api/Player/getPlayersForCurrentAgent",
            {
                "start": 0,
                "limit": 20,
                "filter": {
                    "withoutTotalCount": {"action": "=", "value": True},
                    "playerId": {
                        "action": "=",
                        "value": str(player_id),
                        "valueLabel": str(player_id),
                    },
                },
                "isNextPage": False,
            },
        )

        if not isinstance(result, dict):
            return None
        records = result.get("records") or []
        return records[0] if records else None

    def find_player_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """POST getPlayersForCurrentAgent — بحث بـ userName (like)"""
        result = self._request(
            "global/api/Player/getPlayersForCurrentAgent",
            {
                "start": 0,
                "limit": 20,
                "filter": {
                    "withoutTotalCount": {"action": "=", "value": True},
                    "userName": {
                        "action": "like",
                        "value": username,
                        "valueLabel": username,
                    },
                },
                "isNextPage": False,
            },
        )

        if not isinstance(result, dict):
            return None
        records = result.get("records") or []
        # تفضيل تطابق تام إن وُجد
        for record in records:
            if str(record.get("username", "")).lower() == username.lower():
                return record
        return records[0] if records else None

    def verify_player(self, player_ref: str) -> Dict[str, Any]:
        """التحقق من اللاعب عبر معرف أو اسم مستخدم"""
        player_ref = player_ref.strip()
        player = None

        if player_ref.isdigit():
            player = self.find_player_by_id(player_ref)

        if not player:
            player = self.find_player_by_username(player_ref)

        if not player:
            # محاولة أخيرة: رصيد مباشر بالمعرف
            try:
                balance = self.get_player_balance(player_ref)
                return {
                    "playerId": player_ref,
                    "username": player_ref,
                    "balance": balance,
                }
            except IchancyError:
                raise IchancyError(
                    "اللاعب غير موجود ضمن حساب الوكيل. تأكد من المعرف أو اسم المستخدم."
                )

        return player

    def register_player(
        self,
        login: str,
        password: str,
        email: str,
        parent_id: Optional[str] = None,
    ) -> Any:
        """POST global/api/UserApi/registerPlayer"""
        parent = parent_id or self.parent_id
        if not parent:
            raise IchancyError("ICHANCY_PARENT_ID مطلوب لتسجيل لاعب جديد")

        return self._request(
            "global/api/UserApi/registerPlayer",
            {
                "player": {
                    "email": email,
                    "password": password,
                    "parentId": str(parent),
                    "login": login,
                }
            },
        )
