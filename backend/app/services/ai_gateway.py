"""AI Gateway (Block 10): provider-neutral chat completion + tool calling.

Frontend/WhatsApp -> AI Application Service -> AI Gateway -> Provider
Adapter -> Gemini. Business logic never touches vendor SDKs.
"""

from __future__ import annotations

import abc
import logging
import time
from typing import Any, Callable

import httpx

from app.core.config import Settings
from app.services.errors import AIProviderError

logger = logging.getLogger(__name__)

# Usage/logging hook: set via set_usage_hook() (tests/ops). Called with a
# small dict per gateway call; never raises into the chat path.
_UsageHook: Callable[[dict], None] | None = None


def set_usage_hook(hook: Callable[[dict], None] | None) -> None:
    """Inject an AI usage observer (logging/metrics). None disables."""
    global _UsageHook
    _UsageHook = hook


def _emit_usage(event: dict) -> None:
    try:
        if _UsageHook is not None:
            _UsageHook(dict(event))
    except Exception:  # noqa: BLE001 - usage hooks must never break replies
        logger.debug("ai usage hook failed", exc_info=True)


class ChatMessage(dict):
    pass


class GatewayResult:
    def __init__(
        self,
        *,
        text: str,
        tool_calls: list | None = None,
        model: str = "",
        latency_ms: int = 0,
    ) -> None:
        self.text = text
        self.tool_calls = list(tool_calls or [])
        self.model = model
        self.latency_ms = latency_ms


class ChatProvider(abc.ABC):
    name: str = "abstract"
    model: str = ""

    @abc.abstractmethod
    def chat(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> GatewayResult:
        """Single chat turn; may request tool calls (no side effects here)."""


class NoopChatProvider(ChatProvider):
    name = "noop"
    model = "noop-chat-v1"

    def chat(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> GatewayResult:
        last = ""
        for m in reversed(messages):
            if m.get("role") in ("visitor", "user") and m.get("content"):
                last = str(m["content"])[:200]
                break
        return GatewayResult(
            text=f"(Demo assistant — AI provider not configured. You said: {last})",
            tool_calls=[],
            model=self.model,
            latency_ms=1,
        )


class GeminiChatProvider(ChatProvider):
    """Gemini provider adapter (generateContent, function calling).

    Model is configurable via GEMINI_MODEL (default gemini-2.0-flash).
    Uses the REST generateContent endpoint with httpx (no vendor SDK in
    business logic). Tool calling: Gemini functionDeclarations; responses
    parsed into {name, args} calls validated downstream.

    Resilience: bounded timeout (per attempt) + up to 2 safe retries on
    transport/5xx/429 with exponential backoff (POST generateContent has
    no side effects until tools execute downstream, and tool execution is
    separately validated/idempotent). 4xx (other than 429) fails fast.
    Every attempt emits structured logs + the usage hook; failures raise
    AIProviderError so callers fall back honestly (never invented text).
    """

    name = "gemini"
    MAX_ATTEMPTS = 3

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self.model = (settings.gemini_model or "gemini-2.0-flash").strip()

    def chat(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> GatewayResult:
        api_key = (self._s.gemini_api_key or "").strip()
        if not api_key:
            raise AIProviderError("Gemini is not configured (GEMINI_API_KEY missing).")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={api_key}"
        )
        contents: list[dict] = []
        for m in messages[-20:]:
            role = "user" if m.get("role") in ("visitor", "user", "tool") else "model"
            contents.append(
                {"role": role, "parts": [{"text": str(m.get("content", ""))[:4000]}]}
            )
        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system[:8000]}]},
            "contents": contents or [{"role": "user", "parts": [{"text": "Hello"}]}],
            "generationConfig": {
                "maxOutputTokens": max_output_tokens,
                "temperature": 0.4,
            },
        }
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t["name"],
                            "description": t.get("description", "")[:500],
                            "parameters": t.get(
                                "parameters", {"type": "object", "properties": {}}
                            ),
                        }
                        for t in tools[:16]
                    ]
                }
            ]
        last_error: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                resp = httpx.post(url, json=payload, timeout=float(timeout_seconds))
            except Exception as exc:
                last_error = exc
                latency = int((time.monotonic() - started) * 1000)
                logger.warning(
                    "gemini transport failed attempt=%d/%d latency_ms=%d err=%s",
                    attempt,
                    self.MAX_ATTEMPTS,
                    latency,
                    type(exc).__name__,
                )
                _emit_usage(
                    {
                        "provider": "gemini",
                        "model": self.model,
                        "status": "transport_error",
                        "attempt": attempt,
                        "latency_ms": latency,
                    }
                )
                if attempt < self.MAX_ATTEMPTS:
                    time.sleep(min(2.0, 0.25 * (2 ** (attempt - 1))))
                    continue
                raise AIProviderError(f"Gemini transport failed: {exc}") from exc
            latency = int((time.monotonic() - started) * 1000)
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning(
                    "gemini retryable status=%d attempt=%d/%d latency_ms=%d",
                    resp.status_code,
                    attempt,
                    self.MAX_ATTEMPTS,
                    latency,
                )
                _emit_usage(
                    {
                        "provider": "gemini",
                        "model": self.model,
                        "status": f"http_{resp.status_code}",
                        "attempt": attempt,
                        "latency_ms": latency,
                    }
                )
                if attempt < self.MAX_ATTEMPTS:
                    time.sleep(min(2.0, 0.25 * (2 ** (attempt - 1))))
                    continue
                raise AIProviderError(
                    f"Gemini request failed (HTTP {resp.status_code})."
                )
            if resp.status_code >= 400:
                logger.warning(
                    "gemini non-retryable status=%d latency_ms=%d",
                    resp.status_code,
                    latency,
                )
                _emit_usage(
                    {
                        "provider": "gemini",
                        "model": self.model,
                        "status": f"http_{resp.status_code}",
                        "attempt": attempt,
                        "latency_ms": latency,
                    }
                )
                raise AIProviderError(
                    f"Gemini request failed (HTTP {resp.status_code})."
                )
            try:
                data = resp.json()
                cand = (data.get("candidates") or [{}])[0]
                parts = (cand.get("content") or {}).get("parts") or []
            except Exception as exc:
                raise AIProviderError(
                    "Gemini returned an unreadable response."
                ) from exc
            text_chunks: list[str] = []
            tool_calls: list[dict] = []
            for part in parts:
                if "text" in part:
                    text_chunks.append(str(part["text"]))
                if "functionCall" in part:
                    fc = part["functionCall"] or {}
                    tool_calls.append(
                        {
                            "name": str(fc.get("name", "")),
                            "args": dict(fc.get("args", {}) or {}),
                        }
                    )
            _emit_usage(
                {
                    "provider": "gemini",
                    "model": self.model,
                    "status": "success",
                    "attempt": attempt,
                    "latency_ms": latency,
                    "tool_calls": len(tool_calls),
                }
            )
            logger.info(
                "gemini chat success model=%s latency_ms=%d tool_calls=%d",
                self.model,
                latency,
                len(tool_calls),
            )
            return GatewayResult(
                text="".join(text_chunks)[:4000],
                tool_calls=tool_calls,
                model=self.model,
                latency_ms=latency,
            )
        assert last_error is not None  # pragma: no cover - loop always returns/raises
        raise AIProviderError(f"Gemini transport failed: {last_error}") from last_error


def get_chat_provider(settings: Settings) -> ChatProvider:
    """Resolve the chat provider. Server-side only; never trust client input.

    - ``AI_PROVIDER=gemini`` + ``GEMINI_API_KEY`` set  → real Gemini adapter.
    - ``AI_PROVIDER=gemini`` without a key           → raises AIProviderError at
      call time so the shared runtime returns the honest fallback (fail safe).
    - anything else (``noop`` default, empty, unknown) → NoopChatProvider fake,
      which labels itself as a demo assistant and never invents business data.
    """
    key = (settings.ai_provider or "noop").strip().lower()
    if key == "gemini":
        return GeminiChatProvider(settings)
    if key not in ("noop", "none", "fake", "mock", ""):
        logger.warning(
            "unknown AI_PROVIDER=%r; using noop fake provider", settings.ai_provider
        )
        _emit_usage({"provider": "noop", "status": "unknown_provider_fallback"})
    return NoopChatProvider()


# -- prompt / policy management (Block 10 step 48; §28) --------------------------

PUBLIC_SYSTEM = (
    "You are the AI receptionist for {business_name}. Answer ONLY from the business "
    "tools provided. Never invent prices, hours, location, services, availability, "
    "or booking status. If information is unavailable, say so and offer staff contact. "
    "Keep replies short, friendly, and in {language}. Never confirm a booking unless "
    "the booking tool confirms it. Tone: {tone}."
)

STAFF_SYSTEM = (
    "You are the business assistant for {business_name} staff. Use the private "
    "business tools to answer with REAL data only. Distinguish FACT (from tools), "
    "SIGNAL (pattern worth attention), and RECOMMENDATION (suggested action). "
    "Never expose one business's data to another business's user."
)


def build_system_prompt(
    *, mode: str, business_name: str, tone: str = "helpful", language: str = "en"
) -> str:
    template = STAFF_SYSTEM if mode in ("staff", "owner") else PUBLIC_SYSTEM
    return template.format(
        business_name=business_name or "this business", tone=tone, language=language
    )


FALLBACK_PUBLIC = (
    "I'm having trouble accessing the assistant right now. "
    "You can contact the team directly — try WhatsApp or phone, or leave an enquiry and staff will respond."
)
