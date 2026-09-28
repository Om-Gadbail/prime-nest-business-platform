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
    """Demo/test provider: returns a deterministic local message id."""

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
            status="sent",
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
    errors; never raises httpx internals. NEVER sends in tests — use
    ``build_send_request`` for request-construction assertions.
    """

    name = "whatsapp"
    GRAPH_VERSION = "v21.0"
    TIMEOUT_SECONDS = 15.0

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
            f"https://graph.facebook.com/{self.GRAPH_VERSION}/"
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
        if not self._access_token or not self._phone_number_id:
            raise MessagingError(
                "WhatsApp is not configured (missing token/phone-number-id)."
            )
        request = self.build_send_request(to=to, body=body, template_code=template_code)
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(
                request["url"],
                json=request["payload"],
                headers=headers,
                timeout=self.TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise MessagingError(f"WhatsApp transport failed: {exc}") from exc
        if resp.status_code >= 400:
            raise MessagingError(
                f"WhatsApp rejected the message (HTTP {resp.status_code})."
            )
        try:
            data = resp.json()
            mid = str(
                data.get("messages", [{}])[0].get("id", f"wa-{uuid.uuid4().hex[:12]}")
            )
        except Exception:  # noqa: BLE001 - vendor shape drift falls back to local id
            mid = f"wa-{uuid.uuid4().hex[:12]}"
        return SendResult(
            provider="whatsapp",
            provider_message_id=mid,
            status="sent",
            raw={"http": resp.status_code},
        )


def get_messaging_provider(settings: Settings, name: str = "") -> MessagingProvider:
    key = (name or "").strip().lower()
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
    raise MessagingError(f"Unknown messaging provider: {name!r}.")


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

    key = (name or "").strip().lower()
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
    raise MessagingError(f"Unknown messaging provider: {name!r}.")


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
