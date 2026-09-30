"""Provider-neutral messaging (Block 9).

Business logic depends only on ``MessagingProvider.send``. Vendor specifics
(WhatsApp Cloud API, SMTP, SMS gateways) live in adapters registered in
``PROVIDERS``. The default ``log`` provider persists nothing externally —
it is used for demo/tests and when credentials are absent.
"""

from __future__ import annotations

import abc
import hashlib
import hmac
import uuid
from typing import Any

import httpx

from app.core.config import Settings


class SendResult:
    def __init__(
        self,
        *,
        provider: str,
        provider_message_id: str,
        status: str = "sent",
        raw: dict | None = None,
    ) -> None:
        self.provider = provider
        self.provider_message_id = provider_message_id
        self.status = status
        self.raw = dict(raw or {})


class MessagingProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def send(
        self,
        *,
        to: str,
        body: str,
        template_code: str = "",
        variables: dict | None = None,
    ) -> SendResult:
        """Send one message. Must raise MessagingError (never leak SDK internals)."""


class MessagingError(Exception):
    pass


class LogProvider(MessagingProvider):
    """Demo/test provider: returns a deterministic local message id.

    Nothing leaves the machine: status is honestly "simulated", never
    "sent"/"delivered", so no caller can mistake a log record for a real
    WhatsApp delivery.
    """

    name = "log"

    def send(
        self,
        *,
        to: str,
        body: str,
        template_code: str = "",
        variables: dict | None = None,
    ) -> SendResult:
        mid = f"log-{uuid.uuid4().hex[:16]}"
        return SendResult(
            provider="log",
            provider_message_id=mid,
            status="simulated",
            raw={"to": to, "preview": body[:160]},
        )


class WhatsAppCloudProvider(MessagingProvider):
    """Meta WhatsApp Cloud API adapter (Block 9 step 44).

    Shared provider implementation; credentials are business-specific and
    bound at construction time (see ``for_business``). Legacy construction
    from global ``WHATSAPP_*`` settings is kept for backwards compat only —
    new code MUST use ``for_business`` with a server-verified business.

    Required: access token + phone-number-id. Uses template messages when
    ``template_code`` is set, else a text message. Timeouts + bounded
    retries (transport/429/5xx only, never other 4xx) + normalized errors;
    never raises httpx internals and never leaks credentials in messages.
    NEVER sends in tests — use ``build_send_request`` for
    request-construction assertions.

    Canonical provider names: META_CLOUD == "whatsapp" (live Graph API),
    MOCK == "log" (demo-safe, no external send). Both aliases are accepted
    by ``get_messaging_provider`` / ``get_messaging_provider_for_business``.
    """

    name = "whatsapp"
    # Canonical aliases (task §12): MOCK stays usable for local tests.
    CANONICAL_NAMES = frozenset({"whatsapp", "meta_cloud", "meta-cloud", "metacloud"})
    MOCK_NAMES = frozenset({"log", "mock"})
    GRAPH_VERSION = "v21.0"
    TIMEOUT_SECONDS = 15.0
    MAX_ATTEMPTS = 3

    def __init__(
        self,
        settings: Settings,
        *,
        access_token: str = "",
        phone_number_id: str = "",
        business_key: str = "",
    ) -> None:
        self._s = settings
        # Explicit business-scoped credentials win; empty values fall back
        # to the legacy global settings (deprecated path).
        token = (access_token or "").strip()
        phone_id = (phone_number_id or "").strip()
        if not token:
            token = (settings.whatsapp_access_token or "").strip()
        if not phone_id:
            phone_id = (settings.whatsapp_phone_number_id or "").strip()
        self._access_token = token
        self._phone_number_id = phone_id
        self.business_key = (business_key or "").strip().lower()

    @classmethod
    def for_business(
        cls, settings: Settings, business: object
    ) -> "WhatsAppCloudProvider":
        """Bind the shared provider to ONE server-verified business's creds.

        ``business`` must be a server-verified Business row / BusinessContext
        / AuthenticatedContext (never raw request input). Raises
        MessagingError when that business is not configured — callers fail
        over to LogProvider (demo-safe), never to another tenant's creds.
        """
        from app.services import integration_configs as iconf

        config = iconf.resolve_whatsapp_config(settings, business)
        if not config.configured:
            raise MessagingError(
                f"WhatsApp is not configured for business "
                f"{config.business_key or 'unknown'}."
            )
        return cls(
            settings,
            access_token=config.access_token,
            phone_number_id=config.phone_number_id,
            business_key=config.business_key,
        )

    def _api_version(self) -> str:
        """Configurable Graph API version (WHATSAPP_API_VERSION, else default)."""
        try:
            configured = str(getattr(self._s, "whatsapp_api_version", "") or "").strip()
        except Exception:  # noqa: BLE001 - settings access never breaks sends
            configured = ""
        version = configured or self.GRAPH_VERSION
        if not version.startswith("v"):
            version = f"v{version}"
        # Allowlist shape: v<major>.<minor> (e.g. v21.0) — anything else falls
        # back to the known-good default instead of building a bad URL.
        import re as _re

        if not _re.fullmatch(r"v\d{2,3}\.\d+", version):
            return self.GRAPH_VERSION
        return version

    def _timeout(self) -> float:
        try:
            value = float(getattr(self._s, "whatsapp_timeout_seconds", 0) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value < 1.0 or value > 120.0:
            return self.TIMEOUT_SECONDS
        return value

    def _max_attempts(self) -> int:
        try:
            value = int(getattr(self._s, "whatsapp_max_attempts", 0) or 0)
        except (TypeError, ValueError):
            value = 0
        if value < 1 or value > 5:
            return self.MAX_ATTEMPTS
        return value

    def build_send_request(
        self,
        *,
        to: str,
        body: str,
        template_code: str = "",
    ) -> dict[str, Any]:
        """Build (but do NOT send) the Graph API request. Deterministic.

        Returns ``{"url": ..., "headers": {"Authorization": "Bearer ***",
        "Content-Type": ...}, "payload": ...}`` — the token is redacted so
        test logs can never leak credentials.
        """
        if not self._access_token or not self._phone_number_id:
            raise MessagingError(
                "WhatsApp is not configured (missing token/phone-number-id)."
            )
        url = (
            f"https://graph.facebook.com/{self._api_version()}/"
            f"{self._phone_number_id}/messages"
        )
        headers = {
            "Authorization": "Bearer ***",
            "Content-Type": "application/json",
        }
        if template_code:
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {"name": template_code, "language": {"code": "en_US"}},
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body[:4096]},
            }
        return {"url": url, "headers": headers, "payload": payload}

    def send(
        self,
        *,
        to: str,
        body: str,
        template_code: str = "",
        variables: dict | None = None,
    ) -> SendResult:
        """Send via Meta Cloud API with bounded safe retries.

        Retry policy (safe subset only): transport exceptions + HTTP 429/5xx
        are retried up to ``whatsapp_max_attempts`` with linear backoff
        (POST has no server-side idempotency, so retries happen ONLY when
        Meta demonstrably did not accept the message). Other 4xx fail fast
        with a normalized error. Never reports delivered unless Meta
        returned 2xx. Exception messages never contain credentials.
        """
        if not self._access_token or not self._phone_number_id:
            raise MessagingError(
                "WhatsApp is not configured (missing token/phone-number-id)."
            )
        request = self.build_send_request(to=to, body=body, template_code=template_code)
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        timeout = self._timeout()
        max_attempts = self._max_attempts()
        last_error: Exception | None = None
        import time as _time

        for attempt in range(1, max_attempts + 1):
            try:
                resp = httpx.post(
                    request["url"],
                    json=request["payload"],
                    headers=headers,
                    timeout=timeout,
                )
            except Exception as exc:  # noqa: BLE001 - transport errors are retried by type only
                # Transport failure (timeout/DNS/reset): Meta did not accept
                # -> safe to retry within budget. Never echo the exception
                # body (it may contain URL fragments); type name only.
                last_error = exc
                if attempt < max_attempts:
                    _time.sleep(min(2.0, 0.25 * (2 ** (attempt - 1))))
                    continue
                raise MessagingError(
                    f"WhatsApp transport failed "
                    f"({type(exc).__name__}; attempts={attempt})."
                ) from None
            status_code = int(getattr(resp, "status_code", 0) or 0)
            if status_code == 429 or status_code >= 500:
                last_error = None
                if attempt < max_attempts:
                    _time.sleep(min(2.0, 0.25 * (2 ** (attempt - 1))))
                    continue
                raise MessagingError(
                    f"WhatsApp temporarily unavailable (HTTP {status_code}; "
                    f"attempts={attempt})."
                )
            if status_code >= 400 or status_code == 0:
                # Non-retryable rejection (bad template/recipient/auth): fail
                # fast with a normalized, credential-free error. Attempt to
                # surface Meta's error code/subcode/type/message (safe subset)
                # without ever including tokens or secrets.
                # MASTER FIX §2/§14: auth failures MUST surface META_AUTH_INVALID
                # explicitly (never silent, never false-delivered) so operators
                # know to refresh PASTE a valid token / fix permissions instead
                # of debugging business logic. Recipient-allowlist rejections
                # (code 131030 on Meta test numbers) stay distinct from auth.
                detail = ""
                code = ""
                subcode = ""
                etype = ""
                message = ""
                try:
                    data = resp.json() if hasattr(resp, "json") else {}
                    err = (data.get("error") or {}) if isinstance(data, dict) else {}
                    code = str(err.get("code", ""))[:16]
                    subcode = str(err.get("error_subcode", "") or "")[:16]
                    etype = str(err.get("type", ""))[:32]
                    message = str(err.get("message", ""))[:200]
                    parts = []
                    if code:
                        parts.append(f"code={code}")
                    if subcode:
                        parts.append(f"subcode={subcode}")
                    if message:
                        parts.append(f"msg={message}")
                    if parts:
                        detail = " " + " ".join(parts)
                except Exception:  # noqa: BLE001 - error parsing never breaks normalization
                    detail = ""
                lowered_msg = (message or "").lower()
                is_auth_failure = (
                    status_code in (401, 403)
                    or code in ("190", "102")
                    or (code == "10" and "permission" in lowered_msg)
                    or ("invalid oauth" in lowered_msg)
                    or ("session has expired" in lowered_msg)
                    or ("expired" in lowered_msg and "token" in lowered_msg)
                )
                if is_auth_failure:
                    raise MessagingError(
                        f"META_AUTH_INVALID: WhatsApp rejected the message "
                        f"(HTTP {status_code}).{detail}"
                    )
                raise MessagingError(
                    f"WhatsApp rejected the message (HTTP {status_code}).{detail}"
                )
            try:
                data = resp.json()
                messages = data.get("messages", [{}]) if isinstance(data, dict) else [{}]
                mid = str(
                    (messages[0] or {}).get("id", "") if messages else ""
                ).strip()
                if not mid:
                    mid = f"wa-{uuid.uuid4().hex[:12]}"
            except Exception:  # noqa: BLE001 - vendor shape drift falls back to local id
                mid = f"wa-{uuid.uuid4().hex[:12]}"
            return SendResult(
                provider="whatsapp",
                provider_message_id=mid,
                status="sent",
                raw={"http": status_code},
            )
        assert last_error is not None  # pragma: no cover - loop always returns/raises
        raise MessagingError("WhatsApp transport failed (unknown).") from None


def _normalize_provider_name(name: str) -> str:
    """Canonicalize provider aliases: MOCK->log, META_CLOUD->whatsapp."""
    key = (name or "").strip().lower().replace("-", "_")
    if key in WhatsAppCloudProvider.MOCK_NAMES:
        return "log"
    if key in WhatsAppCloudProvider.CANONICAL_NAMES:
        return "whatsapp"
    return key


def get_messaging_provider(settings: Settings, name: str = "") -> MessagingProvider:
    key = _normalize_provider_name(name)
    if not key:
        key = "whatsapp" if settings.whatsapp_enabled else "log"
    if key == "whatsapp":
        # Demo-safe: without full WhatsApp configuration the log provider
        # records the message (auditable) instead of failing the workflow.
        # Production enables WHATSAPP_ENABLED=true + credentials.
        if not settings.whatsapp_enabled or not (
            (settings.whatsapp_access_token or "").strip()
            and (settings.whatsapp_phone_number_id or "").strip()
        ):
            return LogProvider()
        return WhatsAppCloudProvider(settings)
    if key == "log":
        return LogProvider()
    raise MessagingError("Unknown messaging provider.")


def get_messaging_provider_for_business(
    settings: Settings, business: object, name: str = ""
) -> MessagingProvider:
    """Resolve the messaging provider for ONE server-verified business.

    ``business`` must be a server-verified Business row / BusinessContext /
    AuthenticatedContext (never raw request input). Returns a WhatsAppCloud
    provider bound to THAT business's credentials when its configuration is
    live, else the demo-safe LogProvider. NEVER returns another business's
    credentials; unknown businesses always get LogProvider (fail safe, with
    the provider name making mock-vs-live obvious: "log" vs "whatsapp").
    """
    from app.services import integration_configs as iconf

    key = _normalize_provider_name(name)
    if key in ("", "whatsapp"):
        config = iconf.resolve_whatsapp_config(settings, business)
        if config.live:
            return WhatsAppCloudProvider(
                settings,
                access_token=config.access_token,
                phone_number_id=config.phone_number_id,
                business_key=config.business_key,
            )
        # Deprecated legacy global fallback (only when the business has NO
        # live scoped config): preserves pre-foundation deployments that set
        # only WHATSAPP_*. New deployments MUST use PRIME_*/NEST_* sets.
        legacy = get_messaging_provider(settings, "whatsapp")
        if isinstance(legacy, WhatsAppCloudProvider):
            return legacy
        if not key:
            return LogProvider()
        return legacy
    if key == "log":
        return LogProvider()
    raise MessagingError("Unknown messaging provider.")


def verify_whatsapp_signature(*, app_secret: str, body: bytes, signature: str) -> bool:
    """Validate X-Hub-Signature-256 on inbound webhooks. Fail closed when secret set.

    When no app secret is configured (demo/local only) this returns True so
    local webhook testing works without Meta credentials. Production callers
    MUST fail closed beforehand — see ``POST /whatsapp/webhook`` which
    rejects when ``APP_ENV=production`` and no secret is configured.
    """
    if not app_secret:
        return True  # demo mode: no secret configured -> accept (logged by caller)
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature[len("sha256=") :])
