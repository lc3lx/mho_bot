"""
عميل Agent API لمنصة ichancy
حسب وثيقة: Agent API Documentation (2026-01-22)

المصادقة: signIn → accessToken + refreshToken
عند result == "ex": refreshToken ثم إعادة الطلب
"""

import ipaddress
import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

import requests

from config import Config

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

logger = logging.getLogger(__name__)

# بصمة متصفح حقيقية تساعد على تجاوز فحص Cloudflare
BROWSER_IMPERSONATE = "chrome124"
ALLOWED_PROXY_SCHEMES = ("http", "https", "socks5", "socks5h")
PROXY_TEST_TIMEOUT = 25


class IchancyError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass
class ProxyTestResult:
    ok: bool
    code: str  # ok | invalid | ssrf | proxy_error | cloudflare | auth | bad_json
    message: str
    masked_proxy: str = "none"
    http_status: Optional[int] = None
    elapsed_ms: int = 0


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

        proxy_cfg = Config.get_ichancy_proxy_config()
        self._proxies = self._build_proxies(proxy_cfg)

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._lock = threading.Lock()
        self._warmed_up = False

        self._session = self._make_session(self._proxies)

    def _make_session(self, proxies: Optional[Dict[str, str]]):
        if curl_requests is not None:
            session = curl_requests.Session(impersonate=BROWSER_IMPERSONATE)
        else:
            session = requests.Session()
            logger.warning(
                "curl_cffi غير مثبت — احتمال حجب Cloudflare أعلى. ثبّت curl_cffi."
            )
        if proxies:
            session.proxies.update(proxies)
            logger.info(
                "Ichancy requests via proxy: %s",
                self._mask_proxy(proxies.get("https") or proxies.get("http")),
            )
        else:
            logger.info("Ichancy requests: direct (no proxy)")
        return session

    @staticmethod
    def _mask_proxy(proxy_url: Optional[str]) -> str:
        if not proxy_url:
            return "none"
        if "@" in proxy_url:
            try:
                scheme, rest = proxy_url.split("://", 1)
                creds, host = rest.rsplit("@", 1)
                user = creds.split(":", 1)[0]
                return f"{scheme}://{user}:***@{host}"
            except ValueError:
                return "***"
        return proxy_url

    @classmethod
    def validate_proxy_input(
        cls,
        raw_url: str,
        user: str = "",
        password: str = "",
        *,
        allow_private: bool = False,
    ) -> Tuple[Dict[str, str], str]:
        """
        يتحقق من صيغة البروكسي ويعيد (cfg_dict, masked_display).
        يرفع ValueError برسالة عربية عند الفشل.
        """
        raw = (raw_url or "").strip()
        user = (user or "").strip()
        password = (password or "").strip()

        if not raw:
            raise ValueError("الرابط فارغ. أرسل بروكسي بصيغة scheme://host:port")

        if any(ch.isspace() for ch in raw):
            raise ValueError("الرابط يحتوي مسافات غير مسموحة.")

        if len(raw) > 450:
            raise ValueError("رابط البروكسي طويل جداً (الحد 450 حرف).")

        if "://" not in raw:
            raise ValueError(
                "لازم تحدد النوع صراحةً.\n"
                "مثال: socks5h://user:pass@host:port\n"
                "أو: http://host:port"
            )

        parsed = urlparse(raw)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ALLOWED_PROXY_SCHEMES:
            raise ValueError(
                f"نوع غير مدعوم: {scheme or '—'}\n"
                f"المسموح: {', '.join(ALLOWED_PROXY_SCHEMES)}"
            )

        host = parsed.hostname
        if not host:
            raise ValueError("المضيف (host) غير موجود في الرابط.")

        port = parsed.port
        if port is None:
            raise ValueError("المنفذ (port) مطلوب، مثال: :1080")
        if not (1 <= int(port) <= 65535):
            raise ValueError("المنفذ يجب أن يكون بين 1 و 65535.")

        if parsed.username and user:
            raise ValueError(
                "لا تجمع يوزر/باسورد داخل الرابط ومع حقول منفصلة معاً."
            )

        if not allow_private:
            cls._assert_public_proxy_host(host)

        url_user = unquote(parsed.username) if parsed.username else ""
        url_pass = unquote(parsed.password) if parsed.password else ""
        if user:
            final_user, final_pass = user, password
        else:
            final_user, final_pass = url_user, url_pass

        clean_url = f"{scheme}://{host}:{int(port)}"
        cfg = {
            "proxy_url": clean_url,
            "proxy_user": final_user,
            "proxy_pass": final_pass if final_user else "",
        }
        built = cls._build_proxies(cfg)
        masked = cls._mask_proxy(
            (built or {}).get("https") or (built or {}).get("http") or clean_url
        )
        return cfg, masked

    @staticmethod
    def _assert_public_proxy_host(host: str) -> None:
        """يمنع توجيه البروكسي لعناوين داخلية/محلية (SSRF)."""
        lowered = host.strip().lower().rstrip(".")
        if lowered in ("localhost", "localhost.localdomain") or lowered.endswith(
            ".localhost"
        ):
            raise ValueError("ممنوع استخدام localhost كبروكسي.")

        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            try:
                infos = socket.getaddrinfo(host, None)
            except socket.gaierror:
                return
            for info in infos:
                addr = info[4][0]
                try:
                    ip = ipaddress.ip_address(addr)
                except ValueError:
                    continue
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                    or ip.is_multicast
                ):
                    raise ValueError(
                        f"مضيف البروكسي يشير لعنوان داخلي محظور ({addr})."
                    )
            return

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or str(ip) == "169.254.169.254"
        ):
            raise ValueError(f"عنوان البروكسي محظور (خاص/محلي): {host}")

    @staticmethod
    def _build_proxies(cfg: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """يبني إعدادات بروكسي لطلبات Ichancy فقط."""
        raw = (cfg.get("proxy_url") or "").strip()
        if not raw:
            return None

        user = (cfg.get("proxy_user") or "").strip()
        password = (cfg.get("proxy_pass") or "").strip()

        if "://" not in raw:
            raw = f"http://{raw}"

        if user:
            scheme, rest = raw.split("://", 1)
            if "@" not in rest:
                raw = (
                    f"{scheme}://{quote(user, safe='')}:{quote(password, safe='')}@{rest}"
                )

        return {"http": raw, "https": raw}

    def get_proxy_status(self) -> Dict[str, Any]:
        cfg = Config.get_ichancy_proxy_config()
        active = None
        if self._proxies:
            active = self._proxies.get("https") or self._proxies.get("http")
        return {
            "enabled": bool(self._proxies),
            "masked": self._mask_proxy(active),
            "source": cfg.get("source", "env"),
            "backend": "curl_cffi" if curl_requests is not None else "requests",
            "configured_agent": self.is_configured,
            "user_set": bool(cfg.get("proxy_user")),
        }

    def test_proxy_config(
        self,
        cfg: Optional[Dict[str, Any]] = None,
        timeout: int = PROXY_TEST_TIMEOUT,
    ) -> ProxyTestResult:
        """اختبار بروكسي بجلسة مؤقتة — لا يمس الجلسة الحية."""
        if cfg is None:
            cfg = Config.get_ichancy_proxy_config()

        try:
            proxies = self._build_proxies(cfg)
            masked = self._mask_proxy(
                (proxies or {}).get("https") or (proxies or {}).get("http")
            )
        except Exception as exc:
            return ProxyTestResult(
                ok=False,
                code="invalid",
                message=f"إعداد بروكسي غير صالح: {exc}",
                masked_proxy="none",
            )

        if not self.is_configured:
            return ProxyTestResult(
                ok=False,
                code="auth",
                message="بيانات وكيل Ichancy غير مكتملة في .env",
                masked_proxy=masked,
            )

        started = time.monotonic()
        session = None
        try:
            if curl_requests is not None:
                session = curl_requests.Session(impersonate=BROWSER_IMPERSONATE)
            else:
                session = requests.Session()
            if proxies:
                session.proxies.update(proxies)

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/",
            }
            if curl_requests is None:
                headers["User-Agent"] = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )

            try:
                session.get(
                    f"{self.base_url}/",
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    timeout=timeout,
                )
            except Exception:
                pass

            response = session.post(
                f"{self.base_url}/global/api/UserApi/signIn",
                json={"username": self.username, "password": self.password},
                headers=headers,
                timeout=timeout,
            )
            elapsed = int((time.monotonic() - started) * 1000)
            content_type = (response.headers.get("content-type") or "").lower()
            raw_text = (response.text or "")[:400]

            if "text/html" in content_type or raw_text.lstrip().startswith("<!"):
                if response.status_code in (403, 503) or "cloudflare" in raw_text.lower():
                    return ProxyTestResult(
                        ok=False,
                        code="cloudflare",
                        message="Cloudflare حجب الاتصال عبر هذا البروكسي.",
                        masked_proxy=masked,
                        http_status=response.status_code,
                        elapsed_ms=elapsed,
                    )
                return ProxyTestResult(
                    ok=False,
                    code="bad_json",
                    message=f"استجابة غير صالحة (HTTP {response.status_code})",
                    masked_proxy=masked,
                    http_status=response.status_code,
                    elapsed_ms=elapsed,
                )

            try:
                body = response.json()
            except ValueError:
                return ProxyTestResult(
                    ok=False,
                    code="bad_json",
                    message="الرد ليس JSON صالحاً.",
                    masked_proxy=masked,
                    http_status=response.status_code,
                    elapsed_ms=elapsed,
                )

            result = body.get("result")
            if response.status_code in (401, 403) or not (
                isinstance(result, dict) and result.get("accessToken")
            ):
                err = self._extract_error(body) if isinstance(body, dict) else ""
                return ProxyTestResult(
                    ok=False,
                    code="auth",
                    message=err
                    or "البروكسي وصل لكن تسجيل الدخول فشل (تحقق من بيانات الوكيل).",
                    masked_proxy=masked,
                    http_status=response.status_code,
                    elapsed_ms=elapsed,
                )

            return ProxyTestResult(
                ok=True,
                code="ok",
                message="الاتصال ناجح — تم تسجيل الدخول عبر البروكسي.",
                masked_proxy=masked,
                http_status=response.status_code,
                elapsed_ms=elapsed,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            logger.warning(
                "Proxy test failed (%s): %s", masked, type(exc).__name__
            )
            return ProxyTestResult(
                ok=False,
                code="proxy_error",
                message=f"فشل الاتصال عبر البروكسي: {exc}",
                masked_proxy=masked,
                elapsed_ms=elapsed,
            )
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def apply_proxy_config(
        self,
        cfg: Optional[Dict[str, Any]],
        *,
        reauth: bool = True,
    ) -> ProxyTestResult:
        """يطبق بروكسي على الجلسة الحية ذرياً. cfg فارغ/None = اتصال مباشر."""
        cfg = cfg or {"proxy_url": "", "proxy_user": "", "proxy_pass": ""}
        new_proxies = self._build_proxies(cfg)
        masked = self._mask_proxy(
            (new_proxies or {}).get("https") or (new_proxies or {}).get("http")
        )

        with self._lock:
            old_session = self._session
            self._proxies = new_proxies
            self._session = self._make_session(new_proxies)
            self._warmed_up = False
            self._access_token = None
            self._refresh_token = None
            try:
                old_session.close()
            except Exception:
                pass

        if reauth and self.is_configured:
            try:
                self.sign_in()
            except IchancyError as exc:
                return ProxyTestResult(
                    ok=False,
                    code="cloudflare" if "Cloudflare" in (exc.message or "") else "auth",
                    message=f"طُبّق الإعداد لكن إعادة الدخول فشلت: {exc.message}",
                    masked_proxy=masked,
                    http_status=exc.status_code,
                )
            except Exception as exc:
                return ProxyTestResult(
                    ok=False,
                    code="proxy_error",
                    message=f"طُبّق الإعداد لكن الاتصال فشل: {exc}",
                    masked_proxy=masked,
                )

        return ProxyTestResult(
            ok=True,
            code="ok",
            message="تم تطبيق البروكسي على الجلسة الحية.",
            masked_proxy=masked,
        )

    def apply_and_persist_proxy(
        self,
        cfg: Dict[str, Any],
        *,
        test_first: bool = True,
    ) -> ProxyTestResult:
        """اختبار ثم حفظ ثم تطبيق — عند الفشل لا يُحفظ شيء."""
        probe = None
        if test_first:
            probe = self.test_proxy_config(cfg)
            if not probe.ok:
                return probe

        Config.save_ichancy_proxy_config(
            cfg.get("proxy_url", ""),
            cfg.get("proxy_user", ""),
            cfg.get("proxy_pass", ""),
        )
        applied = self.apply_proxy_config(cfg, reauth=True)
        if probe is not None:
            applied.elapsed_ms = probe.elapsed_ms
            if applied.ok:
                applied.message = probe.message
        return applied

    def disable_and_persist_proxy(self) -> ProxyTestResult:
        """تعطيل صريح + تطبيق اتصال مباشر."""
        Config.disable_ichancy_proxy_config()
        return self.apply_proxy_config(
            {"proxy_url": "", "proxy_user": "", "proxy_pass": ""},
            reauth=True,
        )

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
            logger.error(
                "Ichancy connection error (proxy=%s): %s",
                bool(self._proxies),
                exc,
            )
            raise IchancyError(f"تعذر الاتصال بـ ichancy: {exc}") from exc

        content_type = (response.headers.get("content-type") or "").lower()
        raw_text = (response.text or "")[:500]

        if "text/html" in content_type or raw_text.lstrip().startswith("<!"):
            logger.error(
                "Ichancy blocked/non-JSON HTTP %s: %s",
                response.status_code,
                raw_text[:200],
            )
            if response.status_code in (403, 503) or "cloudflare" in raw_text.lower():
                hint = ""
                if not self._proxies:
                    hint = (
                        "\nفعّل بروكسي Ichancy من لوحة الأدمن "
                        "أو ICHANCY_PROXY في .env."
                    )
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
