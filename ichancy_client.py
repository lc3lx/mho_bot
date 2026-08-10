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

# #region agent log
def _agent_dbg(hypothesis_id: str, location: str, message: str, data: dict | None = None):
    try:
        import json, time
        from pathlib import Path
        payload = {
            "sessionId": "73d636",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        path = Path(__file__).resolve().parent / "debug-73d636.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
# #endregion

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
        self.player_api_url = (
            cfg.get("player_api_url") or "https://www.ichancy.com"
        ).rstrip("/")
        self.username = cfg.get("username", "")
        self.password = cfg.get("password", "")
        self.parent_id = cfg.get("parent_id", "")
        self.currency = cfg.get("currency", "NSP")
        self.currency_code = cfg.get("currency_code", cfg.get("currency", "NSP"))
        self.money_status = int(cfg.get("money_status", 5))
        self.amount_scale = max(1, int(cfg.get("amount_scale", 100) or 100))
        self.default_timeout = int(cfg.get("request_timeout", 60))

        proxy_cfg = Config.get_ichancy_proxy_config()
        self._proxies = self._build_proxies(proxy_cfg)

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._lock = threading.Lock()
        self._warmed_up = False
        self._player_warmed_up = False

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

    def _player_url(self, endpoint: str) -> str:
        return f"{self.player_api_url}/{endpoint.lstrip('/')}"

    def _extract_error(self, body: Dict[str, Any]) -> str:
        if not isinstance(body, dict):
            return "فشل الطلب على ichancy"

        notifications = body.get("notification") or []
        if notifications and isinstance(notifications, list):
            first = notifications[0]
            if isinstance(first, dict) and first.get("content"):
                content = str(first["content"])
                low = content.lower()
                if "min deposit" in low:
                    return (
                        "المبلغ أقل من الحد الأدنى للشحن على منصة iChancy.\n"
                        "جرّب مبلغ أكبر أو تأكد من إعداد التحويل (×100)."
                    )
                return content
            if isinstance(first, str) and first.strip():
                return first.strip()

        # ASP.NET / FluentValidation — شائع مع HTTP 422
        errors = body.get("errors") or body.get("Errors")
        if isinstance(errors, dict) and errors:
            parts = []
            for key, val in errors.items():
                if isinstance(val, list):
                    parts.append(f"{key}: {', '.join(str(x) for x in val)}")
                else:
                    parts.append(f"{key}: {val}")
            if parts:
                return " | ".join(parts)
        if isinstance(errors, list) and errors:
            return " | ".join(str(x) for x in errors)

        for key in ("title", "message", "error", "Error", "msg", "description", "detail"):
            val = body.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict) and val.get("content"):
                return str(val["content"])
        return "فشل الطلب على ichancy"

    @staticmethod
    def _id_from_jwt(token: str) -> Optional[str]:
        """استخراج معرف مستخدم محتمل من JWT بدون تحقق توقيع."""
        if not token or not isinstance(token, str) or token.count(".") < 2:
            return None
        try:
            import base64
            import json

            payload_b64 = token.split(".")[1]
            pad = "=" * (-len(payload_b64) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        for key in (
            "playerId",
            "PlayerId",
            "userId",
            "UserId",
            "clientId",
            "ClientId",
            "sub",
            "id",
            "uid",
        ):
            val = data.get(key)
            if IchancyClient._is_plausible_player_id(val):
                return str(val).strip()
        # بعض التوكنات تضع المعرف داخل كائن user
        for nest_key in ("user", "player", "data", "profile"):
            nested = data.get(nest_key)
            if isinstance(nested, dict):
                found = IchancyClient._deep_find_player_id(nested)
                if found:
                    return found
        return IchancyClient._deep_find_player_id(data)

    def _warm_up_host(self, base_url: str, timeout: int) -> None:
        try:
            self._session.get(
                f"{base_url.rstrip('/')}/",
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=timeout,
            )
        except Exception as exc:
            logger.debug("Ichancy warm-up (%s) failed: %s", base_url, exc)

    def _warm_up(self, timeout: int) -> None:
        """زيارة الصفحة الرئيسية مرة واحدة لالتقاط كوكيز Cloudflare."""
        if self._warmed_up:
            return
        self._warmed_up = True
        self._warm_up_host(self.base_url, timeout)

    def _post_json(
        self,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = None,
    ) -> Dict[str, Any]:
        """POST JSON إلى URL مطلق مع نفس معالجة Cloudflare."""
        req_timeout = timeout if timeout is not None else self.default_timeout
        hdrs = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
        if curl_requests is None:
            hdrs["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        if headers:
            hdrs.update(headers)
        try:
            response = self._session.post(
                url, json=data or {}, headers=hdrs, timeout=req_timeout
            )
        except Exception as exc:
            raise IchancyError(f"تعذر الاتصال بـ ichancy: {exc}") from exc

        content_type = (response.headers.get("content-type") or "").lower()
        raw_text = (response.text or "")[:500]
        if "text/html" in content_type or raw_text.lstrip().startswith("<!"):
            if response.status_code in (403, 503) or "cloudflare" in raw_text.lower():
                raise IchancyError(
                    "منصة Ichancy حجب الاتصال (Cloudflare 403).",
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
        if response.status_code >= 400:
            raise IchancyError(
                self._extract_error(body) if isinstance(body, dict) else "فشل الطلب",
                status_code=response.status_code,
            )
        return body if isinstance(body, dict) else {"result": body}

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
            detail = self._extract_error(body)
            # #region agent log
            _agent_dbg(
                "C,D",
                "ichancy_client.py:_raw_post",
                "HTTP 422 validation",
                {
                    "detail": detail,
                    "body_snip": str(body)[:800],
                    "errors": body.get("errors") or body.get("Errors"),
                    "notif": body.get("notification"),
                },
            )
            # #endregion
            print(
                f"[ICHANCY FAIL] http=422 detail={detail!r} body={str(body)[:800]!r}",
                flush=True,
            )
            logger.error("Ichancy HTTP 422: %s", str(body)[:800])
            raise IchancyError(detail, status_code=422)
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

    def force_reauth(self) -> Dict[str, str]:
        """مسح التوكنات وتسجيل دخول جديد بالكامل."""
        with self._lock:
            self._access_token = None
            self._refresh_token = None
            self._warmed_up = False
        return self.sign_in()

    def _request_full(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        retry_on_ex: bool = True,
    ) -> Dict[str, Any]:
        """مثل _request لكن يعيد جسم الرد كاملاً (مهم لـ registerPlayer)."""
        body = self._raw_post(endpoint, data=data, use_auth=True, timeout=timeout)
        result = body.get("result")

        if result == "ex" and not retry_on_ex:
            # #region agent log
            _agent_dbg(
                "E",
                "ichancy_client.py:_request_full",
                "result=ex retry disabled",
                {
                    "endpoint": endpoint,
                    "detail": self._extract_error(body),
                    "notif": body.get("notification") if isinstance(body, dict) else None,
                    "body_snip": str(body)[:500],
                },
            )
            # #endregion

        if result == "ex" and retry_on_ex:
            logger.warning(
                "Ichancy returned result=ex on %s — forcing fresh signIn",
                endpoint,
            )
            try:
                self.force_reauth()
            except IchancyError:
                raise
            body = self._raw_post(endpoint, data=data, use_auth=True, timeout=timeout)
            result = body.get("result")
            if result == "ex":
                detail = self._extract_error(body)
                logger.error(
                    "Ichancy still result=ex after reauth on %s: %s",
                    endpoint,
                    str(body)[:300],
                )
                # #region agent log
                _agent_dbg(
                    "E",
                    "ichancy_client.py:_request_full",
                    "result=ex after reauth",
                    {
                        "endpoint": endpoint,
                        "detail": detail,
                        "body_keys": list(body.keys()) if isinstance(body, dict) else None,
                        "notif": (body.get("notification") if isinstance(body, dict) else None),
                        "result": result,
                    },
                )
                # #endregion
                raise IchancyError(
                    detail
                    if detail and detail != "فشل الطلب على ichancy"
                    else (
                        "انتهت صلاحية جلسة الوكيل أو الحساب بلا صلاحية لهذه العملية.\n"
                        "تحقق من ICHANCY_USERNAME / PASSWORD / PARENT_ID "
                        "أو أعد تسجيل دخول الوكيل من لوحة الأدمن."
                    )
                )

        if result is False:
            # #region agent log
            _agent_dbg(
                "A",
                "ichancy_client.py:_request_full",
                "API result=False",
                {
                    "endpoint": endpoint,
                    "detail": self._extract_error(body),
                    "notif": (body.get("notification") if isinstance(body, dict) else None),
                    "result": result,
                    "status": body.get("status") if isinstance(body, dict) else None,
                    "body_snip": str(body)[:500] if body is not None else None,
                },
            )
            # #endregion
            # يظهر مباشرة في pm2-out / pm2-error
            print(
                f"[ICHANCY FAIL] endpoint={endpoint} "
                f"detail={self._extract_error(body)!r} body={str(body)[:800]!r}",
                flush=True,
            )
            logger.error(
                "Ichancy result=False on %s: %s",
                endpoint,
                str(body)[:800],
            )
            raise IchancyError(self._extract_error(body))

        return body if isinstance(body, dict) else {"result": body}

    def _request(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        retry_on_ex: bool = True,
    ) -> Any:
        """طلب محمي مع معالجة انتهاء التوكن (result == 'ex')"""
        body = self._request_full(
            endpoint, data=data, timeout=timeout, retry_on_ex=retry_on_ex
        )
        return body.get("result")

    @staticmethod
    def _is_plausible_player_id(val: Any) -> bool:
        """
        يميّز معرف اللاعب الحقيقي عن أكواد النجاح.
        على بوابة Ichancy: registerPlayer يرجع result=1 عند النجاح — مو playerId.
        """
        if val is None or isinstance(val, bool):
            return False
        s = str(val).strip()
        if not s.isdigit():
            return False
        # 0/1 أكواد نجاح/فشل شائعة — ليست معرف لاعب
        if s in ("0", "1"):
            return False
        # معرفات اللاعبين عادة أطول من 3 أرقام
        if len(s) < 4:
            return False
        return True

    @staticmethod
    def _deep_find_player_id(obj: Any, depth: int = 0) -> Optional[str]:
        """بحث عميق عن أي مفتاح يشبه playerId داخل الرد."""
        if depth > 6 or obj is None:
            return None
        if isinstance(obj, bool):
            return None
        if isinstance(obj, (int, float)) and not isinstance(obj, bool):
            # أرقام مجردة ما منعتبرها ID إلا ضمن dict بمفتاح معروف
            return None
        if isinstance(obj, str):
            s = obj.strip()
            if IchancyClient._is_plausible_player_id(s):
                return s
            return None
        if isinstance(obj, dict):
            for key in (
                "playerId",
                "PlayerId",
                "player_id",
                "playerid",
                "userId",
                "UserId",
                "clientId",
                "ClientId",
            ):
                val = obj.get(key)
                if IchancyClient._is_plausible_player_id(val):
                    return str(int(val)) if isinstance(val, float) else str(val).strip()
            # id فقط إذا ما كان parentId/context
            for key, val in obj.items():
                lk = str(key).lower()
                if lk in ("id", "playerid", "player_id", "userid") and "parent" not in lk:
                    if IchancyClient._is_plausible_player_id(val):
                        return str(int(float(val))) if isinstance(val, float) else str(val).strip()
            for val in obj.values():
                found = IchancyClient._deep_find_player_id(val, depth + 1)
                if found:
                    return found
        if isinstance(obj, list):
            for item in obj:
                found = IchancyClient._deep_find_player_id(item, depth + 1)
                if found:
                    return found
        return None

    def find_player_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        POST getPlayersForCurrentAgent — بحث بـ userName حسب الوثائق.
        Example B في APIIntegration.pdf: filter.userName action=like
        """
        username = (username or "").strip()
        if not username:
            return None

        filter_variants = [
            # الوثائق: Example B — Search by userName (like)
            {
                "withoutTotalCount": {"action": "=", "value": True},
                "userName": {
                    "action": "like",
                    "value": username,
                    "valueLabel": username,
                },
            },
            {
                "withoutTotalCount": {"action": "=", "value": True},
                "userName": {
                    "action": "=",
                    "value": username,
                    "valueLabel": username,
                },
            },
            {
                "withoutTotalCount": {"action": "=", "value": True},
                "login": {
                    "action": "=",
                    "value": username,
                    "valueLabel": username,
                },
            },
        ]
        endpoints = (
            "global/api/Player/getPlayersForCurrentAgent",
            "global/api/UserApi/getPlayersForCurrentAgent",
        )

        for endpoint in endpoints:
            for filt in filter_variants:
                try:
                    print(
                        f"[ICHANCY getPlayers] try endpoint={endpoint} "
                        f"userName={username!r} filter_keys={list(filt.keys())}",
                        flush=True,
                    )
                    result = self._request(
                        endpoint,
                        {
                            "start": 0,
                            "limit": 20,
                            "filter": filt,
                            "isNextPage": False,
                        },
                        retry_on_ex=False,
                    )
                except IchancyError as exc:
                    print(
                        f"[ICHANCY getPlayers] FAIL {username!r}: {exc.message}",
                        flush=True,
                    )
                    logger.warning(
                        "find_player_by_username(%s) failed: %s", username, exc.message
                    )
                    continue

                msg = (
                    f"[ICHANCY getPlayers] OK type={type(result).__name__} "
                    f"result={result!r}"
                )
                print(msg[:500], flush=True)
                if not isinstance(result, dict):
                    continue
                records = result.get("records") or []
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    uname = str(
                        record.get("username")
                        or record.get("userName")
                        or record.get("login")
                        or ""
                    )
                    pid = record.get("playerId") or record.get("PlayerId")
                    if uname.lower() == username.lower() and self._is_plausible_player_id(pid):
                        print(
                            f"[ICHANCY getPlayers] MATCH username={uname!r} "
                            f"playerId={pid!r}",
                            flush=True,
                        )
                        return record
                # تطابق تقريبي إذا سجل واحد فقط
                if len(records) == 1 and isinstance(records[0], dict):
                    pid = records[0].get("playerId") or records[0].get("PlayerId")
                    if self._is_plausible_player_id(pid):
                        print(
                            f"[ICHANCY getPlayers] SINGLE record playerId={pid!r}",
                            flush=True,
                        )
                        return records[0]
        return None

    def resolve_player_id_by_username(
        self,
        username: str,
        password: str = "",
        attempts: int = 5,
    ) -> Optional[str]:
        """
        يجيب playerId من اليوزرنيم (خلفية فقط).
        المسار الرسمي: getPlayersForCurrentAgent → records[].playerId
        """
        import time

        username = (username or "").strip()
        if not username:
            return None

        for i in range(max(1, attempts)):
            if i:
                time.sleep(0.7 * i)
            found = self.find_player_by_username(username)
            pid = None
            if found:
                pid = found.get("playerId") or found.get("PlayerId")
            if self._is_plausible_player_id(pid):
                print(
                    f"[ICHANCY resolve] username={username!r} -> playerId={pid!r} "
                    f"(attempt {i + 1})",
                    flush=True,
                )
                return str(pid).strip()

            if password:
                via_site = self.resolve_player_via_site_login(username, password)
                if via_site and self._is_plausible_player_id(via_site.get("playerId")):
                    pid = str(via_site["playerId"]).strip()
                    print(
                        f"[ICHANCY resolve] via site login username={username!r} "
                        f"-> playerId={pid!r}",
                        flush=True,
                    )
                    return pid

        print(
            f"[ICHANCY resolve] FAILED username={username!r} after {attempts} attempts",
            flush=True,
        )
        return None

    def resolve_player_via_site_login(
        self, login: str, password: str
    ) -> Optional[Dict[str, Any]]:
        """
        بعد registerPlayer (result=1 بدون ID): نسجّل دخول اللاعب على موقع اللعب
        ونستخرج playerId من الرد أو من الـ JWT.
        """
        login = (login or "").strip()
        password = (password or "").strip()
        if not login or not password:
            return None

        if not self._player_warmed_up:
            self._warm_up_host(self.player_api_url, self.default_timeout)
            self._player_warmed_up = True

        url = self._player_url("global/api/UserApi/signIn")
        try:
            body = self._post_json(
                url,
                {"username": login, "password": password},
                headers={
                    "Origin": self.player_api_url,
                    "Referer": f"{self.player_api_url}/",
                },
                timeout=45,
            )
        except IchancyError as exc:
            logger.warning(
                "player site signIn failed for %s: %s", login, exc.message
            )
            return None

        logger.info(
            "player site signIn for %s preview=%s",
            login,
            str(body)[:350],
        )

        extracted = self.extract_player_from_register(body, login=login)
        if extracted and self._is_plausible_player_id(extracted.get("playerId")):
            return extracted

        pid = self._deep_find_player_id(body)
        if pid:
            return {"playerId": pid, "username": login}

        result = body.get("result") if isinstance(body, dict) else None
        token = None
        if isinstance(result, dict):
            token = (
                result.get("accessToken")
                or result.get("token")
                or result.get("authToken")
            )
            for key in ("userId", "playerId", "UserId", "clientId", "id"):
                if self._is_plausible_player_id(result.get(key)):
                    return {
                        "playerId": str(result.get(key)).strip(),
                        "username": login,
                    }
        if isinstance(token, str):
            jwt_id = self._id_from_jwt(token)
            if jwt_id:
                return {"playerId": jwt_id, "username": login}

        return None

    def resolve_player_after_register(
        self,
        login: str,
        register_body: Any = None,
        password: str = "",
        attempts: int = 4,
    ) -> Optional[Dict[str, Any]]:
        """محاولات متكررة لجلب playerId بعد التسجيل."""
        import time

        player = self.extract_player_from_register(register_body, login=login)
        if player and player.get("playerId"):
            return player

        for i in range(attempts):
            if i:
                time.sleep(0.8 * i)

            # 1) تسجيل دخول اللاعب على الموقع — أهم مسار لما قائمة الوكيل = ex
            if password:
                via_site = self.resolve_player_via_site_login(login, password)
                if via_site and via_site.get("playerId"):
                    logger.info(
                        "Resolved playerId via site login: %s -> %s",
                        login,
                        via_site.get("playerId"),
                    )
                    return via_site

            found = self.find_player_by_username(login)
            if found and self._is_plausible_player_id(found.get("playerId")):
                return found

            for ep, payload in (
                ("global/api/UserApi/getPlayerByLogin", {"login": login}),
                ("global/api/UserApi/getPlayerByUserName", {"userName": login}),
                ("global/api/UserApi/getPlayerInfo", {"login": login}),
                ("global/api/Player/getPlayerByUserName", {"userName": login}),
                ("global/api/Client/getClientByLogin", {"login": login}),
                ("global/api/UserApi/findPlayer", {"login": login}),
            ):
                try:
                    body = self._request_full(
                        ep, payload, timeout=20, retry_on_ex=False
                    )
                except IchancyError:
                    continue
                extracted = self.extract_player_from_register(body, login=login)
                if extracted and extracted.get("playerId"):
                    return extracted
                pid = self._deep_find_player_id(body)
                if pid:
                    return {"playerId": pid, "username": login}

        return player

    def extract_player_from_register(result: Any, login: str = "") -> Optional[Dict[str, Any]]:
        """استخراج بيانات اللاعب من رد registerPlayer (result أو الجسم الكامل)."""
        if result is None or result is False or result == "ex":
            return None

        # إذا مرّ الجسم الكامل {status, result, ...}
        if isinstance(result, dict) and "result" in result and (
            "status" in result or "notification" in result or "html" in result
        ):
            nested = IchancyClient.extract_player_from_register(
                result.get("result"), login=login
            )
            if nested and nested.get("playerId"):
                return nested
            pid = IchancyClient._deep_find_player_id(result)
            if pid:
                return {"playerId": pid, "username": login}
            return None

        candidates: List[Any] = []
        if isinstance(result, dict):
            candidates.append(result)
            for key in ("player", "Player", "data", "user", "record", "value"):
                nested = result.get(key)
                if nested is not None:
                    candidates.append(nested)
            records = result.get("records")
            if isinstance(records, list):
                candidates.extend(records)
        elif isinstance(result, list):
            candidates.extend(result)
        elif isinstance(result, bool):
            return None
        elif isinstance(result, (int, float)) or (
            isinstance(result, str) and str(result).strip().isdigit()
        ):
            # result=1 يعني نجاح على Ichancy — ليس معرف لاعب
            if not IchancyClient._is_plausible_player_id(result):
                return None
            return {"playerId": str(int(result)), "username": login}

        for item in candidates:
            if isinstance(item, bool):
                continue
            if not isinstance(item, dict):
                if IchancyClient._is_plausible_player_id(item):
                    return {"playerId": str(int(item)), "username": login}
                continue
            pid = (
                item.get("playerId")
                or item.get("PlayerId")
                or item.get("player_id")
                or item.get("userId")
                or item.get("UserId")
            )
            # تجنب أخذ parentId بالخطأ عبر مفتاح id العام إلا إذا وُجد مع login/username
            if not IchancyClient._is_plausible_player_id(pid):
                raw_id = item.get("id")
                has_user_marker = any(
                    item.get(k)
                    for k in ("username", "userName", "login", "email", "playerId")
                )
                if has_user_marker and IchancyClient._is_plausible_player_id(raw_id):
                    pid = raw_id
                else:
                    pid = None
            if not IchancyClient._is_plausible_player_id(pid):
                continue
            username = (
                item.get("username")
                or item.get("userName")
                or item.get("login")
                or login
            )
            out = {"playerId": str(pid).strip(), "username": str(username or login)}
            for k, v in item.items():
                if k not in ("password",) and k not in out:
                    out[k] = v
            return out

        pid = IchancyClient._deep_find_player_id(result)
        if pid:
            return {"playerId": pid, "username": login}
        return None


    def register_player(
        self,
        login: str,
        password: str,
        email: str,
        parent_id: Optional[str] = None,
    ) -> Any:
        """POST registerPlayer — النجاح يكفي (result=1). الـ ID اختياري."""
        parent = parent_id or self.parent_id
        if not parent:
            raise IchancyError("ICHANCY_PARENT_ID مطلوب لتسجيل لاعب جديد")

        self.force_reauth()

        body = self._request_full(
            "global/api/UserApi/registerPlayer",
            {
                "player": {
                    "email": email,
                    "password": password,
                    "parentId": str(parent),
                    "login": login,
                }
            },
            timeout=60,
        )
        result = body.get("result")
        # لوج كامل بوضوح بالكونسول لنفهم قصة الـ ID
        print("=" * 60, flush=True)
        print("[ICHANCY registerPlayer] FULL RESPONSE", flush=True)
        print(f"  login={login}", flush=True)
        print(f"  body={body!r}", flush=True)
        print(f"  result_type={type(result).__name__} result={result!r}", flush=True)
        print("=" * 60, flush=True)
        logger.info(
            "registerPlayer FULL login=%s body=%s result_type=%s result=%s",
            login,
            body,
            type(result).__name__,
            result,
        )

        # نجاح المنصة: True / 1 / dict فيه لاعب
        ok = (
            result is True
            or result == 1
            or result == "1"
            or (isinstance(result, dict) and result is not False)
        )
        if result is False or result == "ex":
            raise IchancyError(self._extract_error(body) or "فشل تسجيل اللاعب")

        # ما عادنا نطارد playerId — اليوزر كافي
        if not ok:
            if not (isinstance(body, dict) and body.get("status") is True):
                raise IchancyError(
                    self._extract_error(body)
                    or f"رد تسجيل غير متوقع: {str(result)[:120]}"
                )

        print(
            f"[ICHANCY registerPlayer] SUCCESS without requiring playerId "
            f"login={login} ok={ok}",
            flush=True,
        )
        return {
            "login": login,
            "username": login,
            "created": True,
            "raw": result,
        }
    def get_player_balance(self, player_ref: str) -> float:
        """POST getPlayerBalanceById — حسب الوثائق: playerId فقط."""
        player_ref = str(player_ref).strip()
        if not self._is_plausible_player_id(player_ref):
            raise IchancyError(
                f"getPlayerBalanceById يحتاج playerId رقمي، وصل: {player_ref!r}"
            )
        print(f"[ICHANCY getPlayerBalance] playerId={player_ref}", flush=True)
        result = self._request(
            "global/api/UserApi/getPlayerBalanceById",
            {"playerId": player_ref},
            retry_on_ex=False,
        )
        print(f"[ICHANCY getPlayerBalance] OK result={result!r}", flush=True)
        logger.info("getPlayerBalance OK playerId=%s result=%s", player_ref, result)

        # بعض البوابات ترجع result فارغ/False لما الرصيد صفر — مو معناه اللاعب مش موجود
        if result is None or result is False or result == "" or result == [] or result == {}:
            return 0.0

        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict) and item.get("main", True):
                    return self._from_api_amount(item.get("balance", 0))
            if result and isinstance(result[0], dict):
                return self._from_api_amount(result[0].get("balance", 0))
            return 0.0

        if isinstance(result, dict):
            return self._from_api_amount(
                result.get("balance", result.get("Balance", result.get("amount", 0)))
            )

        try:
            return self._from_api_amount(result)
        except (TypeError, ValueError):
            return 0.0

    def _from_api_amount(self, raw_amount) -> float:
        """من وحدة API → وحدة البوت (÷ scale)."""
        try:
            val = float(raw_amount or 0)
        except (TypeError, ValueError):
            return 0.0
        scale = max(1, int(self.amount_scale or 1))
        return val / scale

    def _transfer_amount(self, amount: float, *, negative: bool = False):
        """
        مبلغ البوت → مبلغ API.
        مثال: الزبون يكتب 20 → نرسل 2000 (scale=100).
        """
        val = abs(float(amount)) * max(1, int(self.amount_scale or 1))
        if abs(val - round(val)) < 1e-9:
            out = int(round(val))
        else:
            out = round(val, 2)
        return -out if negative else out

    def _transfer_payload(
        self, player_ref: str, amount: float, comment: str, *, withdraw: bool
    ) -> Dict[str, Any]:
        """payload موحّد — playerId رقمي (int) + تحويل ×scale."""
        pid = int(str(player_ref).strip())
        currency = (self.currency_code or self.currency or "NSP").strip().upper()
        if currency in ("SYP", "SYL", "SY"):
            currency = "NSP"
        api_amount = self._transfer_amount(amount, negative=withdraw)
        return {
            "amount": api_amount,
            "comment": (comment or "")[:200],
            "playerId": pid,
            "currencyCode": currency,
            "currency": currency,
            "moneyStatus": int(self.money_status),
        }

    def withdraw_from_player(
        self,
        player_ref: str,
        amount: float,
        comment: str = "Bot wallet transfer",
    ) -> Dict[str, Any]:
        """
        POST withdrawFromPlayer — حسب الوثائق: playerId + amount سالب.
        """
        if amount <= 0:
            raise IchancyError("مبلغ السحب يجب أن يكون أكبر من صفر")

        player_ref = str(player_ref).strip()
        if not self._is_plausible_player_id(player_ref):
            raise IchancyError(
                f"withdrawFromPlayer يحتاج playerId رقمي، وصل: {player_ref!r}"
            )

        payload = self._transfer_payload(
            player_ref, amount, comment, withdraw=True
        )
        try:
            bal = self._request(
                "global/api/UserApi/getPlayerBalanceById",
                {"playerId": int(str(player_ref).strip())},
                timeout=30,
                retry_on_ex=True,
            )
            if isinstance(bal, list) and bal and isinstance(bal[0], dict):
                code = str(bal[0].get("currencyCode") or "").strip().upper()
                if code:
                    payload["currencyCode"] = code
                    payload["currency"] = code
        except Exception:
            pass
        # #region agent log
        _agent_dbg(
            "B,C,D",
            "ichancy_client.py:withdraw_from_player",
            "withdraw payload",
            {
                "playerId": payload["playerId"],
                "amount": payload["amount"],
                "currency": payload["currency"],
                "currencyCode": payload["currencyCode"],
                "moneyStatus": payload["moneyStatus"],
                "amount_type": type(payload["amount"]).__name__,
                "playerId_type": type(payload["playerId"]).__name__,
            },
        )
        # #endregion
        print(
            f"[ICHANCY withdraw] playerId={payload['playerId']} "
            f"amount={payload['amount']!r} currency={payload['currency']}",
            flush=True,
        )
        try:
            result = self._request(
                "global/api/UserApi/withdrawFromPlayer",
                payload,
                timeout=60,
                retry_on_ex=True,
            )
        except IchancyError as exc:
            # #region agent log
            _agent_dbg(
                "A,E",
                "ichancy_client.py:withdraw_from_player",
                "withdraw failed",
                {"error": exc.message, "status_code": exc.status_code, "playerId": payload["playerId"]},
            )
            # #endregion
            print(
                f"[ICHANCY withdraw FAIL] playerId={payload['playerId']} "
                f"amount={payload['amount']!r} error={exc.message!r} "
                f"http={exc.status_code}",
                flush=True,
            )
            raise
        print(f"[ICHANCY withdraw] OK result={result!r}", flush=True)
        logger.info("withdraw OK playerId=%s", payload["playerId"])
        if not isinstance(result, dict):
            raise IchancyError("استجابة سحب غير متوقعة من ichancy")
        return result

    def deposit_to_player(
        self,
        player_ref: str,
        amount: float,
        comment: str = "Bot deposit to platform",
    ) -> Dict[str, Any]:
        """POST depositToPlayer — حسب الوثائق: playerId فقط (مو login)."""
        if amount <= 0:
            raise IchancyError("مبلغ الإيداع يجب أن يكون أكبر من صفر")

        player_ref = str(player_ref).strip()
        if not self._is_plausible_player_id(player_ref):
            raise IchancyError(
                f"depositToPlayer يحتاج playerId رقمي، وصل: {player_ref!r}"
            )

        payload = self._transfer_payload(
            player_ref, amount, comment, withdraw=False
        )
        # طابق عملة المحفظة الفعلية من المنصة إن توفرت (NSP بعد الإصلاح)
        try:
            bal = self._request(
                "global/api/UserApi/getPlayerBalanceById",
                {"playerId": int(str(player_ref).strip())},
                timeout=30,
                retry_on_ex=True,
            )
            if isinstance(bal, list) and bal and isinstance(bal[0], dict):
                code = str(bal[0].get("currencyCode") or "").strip().upper()
                if code:
                    payload["currencyCode"] = code
                    payload["currency"] = code
        except Exception:
            pass
        # #region agent log
        _agent_dbg(
            "C",
            "ichancy_client.py:deposit_to_player",
            "deposit payload",
            {
                "playerId": payload["playerId"],
                "amount": payload["amount"],
                "currency": payload["currency"],
                "currencyCode": payload["currencyCode"],
                "moneyStatus": payload["moneyStatus"],
                "amount_type": type(payload["amount"]).__name__,
                "playerId_type": type(payload["playerId"]).__name__,
            },
        )
        # #endregion
        print(
            f"[ICHANCY deposit] playerId={payload['playerId']} "
            f"amount={payload['amount']!r} currency={payload['currency']} "
            f"moneyStatus={payload['moneyStatus']} scale={self.amount_scale}",
            flush=True,
        )
        try:
            result = self._request(
                "global/api/UserApi/depositToPlayer",
                payload,
                timeout=60,
                retry_on_ex=True,
            )
        except IchancyError as exc:
            # #region agent log
            _agent_dbg(
                "A,E",
                "ichancy_client.py:deposit_to_player",
                "deposit failed",
                {"error": exc.message, "status_code": exc.status_code, "playerId": payload["playerId"]},
            )
            # #endregion
            print(
                f"[ICHANCY deposit FAIL] playerId={payload['playerId']} "
                f"amount={payload['amount']!r} error={exc.message!r} "
                f"http={exc.status_code}",
                flush=True,
            )
            raise
        print(f"[ICHANCY deposit] OK result={result!r}", flush=True)
        logger.info("deposit OK playerId=%s result=%s", payload["playerId"], result)
        if not isinstance(result, dict):
            raise IchancyError("استجابة إيداع غير متوقعة من ichancy")
        return result

    def find_player_by_id(self, player_id: str) -> Optional[Dict[str, Any]]:
        """POST getPlayersForCurrentAgent — بحث بـ playerId"""
        try:
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
        except IchancyError as exc:
            logger.warning("find_player_by_id failed: %s", exc.message)
            return None

        if not isinstance(result, dict):
            return None
        records = result.get("records") or []
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
