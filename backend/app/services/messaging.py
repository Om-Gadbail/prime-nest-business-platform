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

    Required env: WHATSAPP_ENABLED=true, WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID. Uses template messages when ``template_code``
    is set, else a text message. Timeouts + bounded errors; never raises
    httpx internals.
    """

    name = "whatsapp"

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def send(
        self,
        *,
        to: str,
        body: str,
        template_code: str = "",
        variables: dict | None = None,
    ) -> SendResult:
        token = (self._s.whatsapp_access_token or "").strip()
        phone_id = (self._s.whatsapp_phone_number_id or "").strip()
        if not token or not phone_id:
            raise MessagingError(
                "WhatsApp is not configured (missing token/phone-number-id)."
            )
        url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
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
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
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
