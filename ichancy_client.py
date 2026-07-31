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

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

logger = logging.getLogger(__name__)

# بصمة متصفح حقيقية تساعد على تجاوز فحص Cloudflare
BROWSER_IMPERSONATE = "chrome124"


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
        self.default_timeout = int(cfg.get("request_timeout", 60))
        self._proxies = self._build_proxies(cfg)

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._lock = threading.Lock()
        self._warmed_up = False

        if curl_requests is not None:
            self._session = curl_requests.Session(impersonate=BROWSER_IMPERSONATE)
        else:
            self._session = requests.Session()
            logger.warning(
                "curl_cffi غير مثبت — احتمال حجب Cloudflare أعلى. ثبّت curl_cffi."
            )

        if self._proxies:
            self._session.proxies.update(self._proxies)
            logger.info(
                "Ichancy requests via proxy: %s",
                self._mask_proxy(self._proxies.get("https") or self._proxies.get("http")),
            )

    @staticmethod
    def _mask_proxy(proxy_url: Optional[str]) -> str:
        if not proxy_url:
            return "none"
        # أخفِ كلمة السر إن وُجدت
        if "@" in proxy_url:
            scheme, rest = proxy_url.split("://", 1)
            creds, host = rest.rsplit("@", 1)
            user = creds.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}"
        return proxy_url

    @staticmethod
    def _build_proxies(cfg: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """يبني إعدادات بروكسي لطلبات Ichancy فقط."""
        raw = (cfg.get("proxy_url") or "").strip()
        if not raw:
            return None

        user = (cfg.get("proxy_user") or "").strip()
        password = (cfg.get("proxy_pass") or "").strip()

        # دعم IP:PORT أو scheme://IP:PORT
        if "://" not in raw:
            raw = f"http://{raw}"

        if user:
            scheme, rest = raw.split("://", 1)
            # تجنب تكرار بيانات الدخول إن كانت داخل الرابط
            if "@" not in rest:
                from urllib.parse import quote
                raw = (
                    f"{scheme}://{quote(user, safe='')}:{quote(password, safe='')}@{rest}"
                )

        return {"http": raw, "https": raw}

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

    def _warm_up(self, timeout: int) -> None:
        """زيارة الصفحة الرئيسية مرة واحدة لالتقاط كوكيز Cloudflare."""
        if self._warmed_up:
            return
        self._warmed_up = True
        try:
            self._session.get(
                f"{self.base_url}/",
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=timeout,
            )
        except Exception as exc:
            logger.debug("Ichancy warm-up failed: %s", exc)

    def _raw_post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        use_auth: bool = True,
        timeout: int = None,
    ) -> Dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
        }
        # مع curl_cffi يأتي User-Agent من بصمة المتصفح المُقلَّدة
        if curl_requests is None:
            headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        if use_auth:
            if not self._access_token:
                self.sign_in()
            headers["Authorization"] = f"Bearer {self._access_token}"

        req_timeout = timeout if timeout is not None else self.default_timeout
        self._warm_up(req_timeout)
        try:
            response = self._session.post(
                self._url(endpoint),
                json=data or {},
                headers=headers,
                timeout=req_timeout,
            )
        except Exception as exc:
            logger.error("Ichancy connection error (proxy=%s): %s", bool(self._proxies), exc)
            raise IchancyError(f"تعذر الاتصال بـ ichancy: {exc}") from exc

        content_type = (response.headers.get("content-type") or "").lower()
        raw_text = (response.text or "")[:500]

        # Cloudflare / WAF غالباً يعيد HTML بدل JSON
        if "text/html" in content_type or raw_text.lstrip().startswith("<!"):
            logger.error(
                "Ichancy blocked/non-JSON HTTP %s: %s",
                response.status_code,
                raw_text[:200],
            )
            if response.status_code in (403, 503) or "cloudflare" in raw_text.lower():
                hint = ""
                if not self._proxies:
                    hint = "\nفعّل ICHANCY_PROXY في .env أو غيّر IP السيرفر."
                raise IchancyError(
                    "منصة Ichancy حجب الاتصال (Cloudflare 403)."
                    + hint
                    + "\nتحقق أن البروكسي شغّال ويصل لـ ichancy.com.",
                    status_code=response.status_code,
                )
            raise IchancyError(
                f"استجابة غير صالحة من ichancy (HTTP {response.status_code})",
                status_code=response.status_code,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise IchancyError(
                f"استجابة غير صالحة من ichancy (HTTP {response.status_code})",
                status_code=response.status_code,
            ) from exc

        if response.status_code == 401:
            raise IchancyError(
                self._extract_error(body) or "غير مصرح (401) — تحقق من بيانات الوكيل",
                status_code=401,
            )
        if response.status_code == 403:
            raise IchancyError(
                self._extract_error(body)
                or "حساب الوكيل بلا صلاحية لهذه العملية (403).",
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
