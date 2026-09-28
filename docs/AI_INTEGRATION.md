# AI Integration — Central Gemini Gateway

## Architecture (locked)

```text
Dashboards / websites / WhatsApp → backend AI runtime → AI Gateway → provider
                                        (app/services/ai_chat.py)   (app/services/ai_gateway.py)
                                                                        ├─ NoopChatProvider (fake, default)
                                                                        └─ GeminiChatProvider (live)
```

- `GEMINI_API_KEY` lives ONLY in backend env (never `VITE_*`, never in bundles — verified by scan).
- Frontend never calls Gemini directly. Website widget posts to `/public/{slug}/ai/chat`;
  dashboards post to `/ai/assistant`. Tenant context attaches server-side from the slug
  (public) or JWT + DB membership (staff); client `business_id` is never trusted.
- Tools (`app/services/ai_tools.py`): 15 PUBLIC + 9 PRIVATE, allowlisted, schema-validated,
  business-scoped. Public callers get `PermissionError` on private tools. No unrestricted DB
  access; no autonomous payments/membership/settings writes.

## Configuration

| Env | Meaning |
|---|---|
| `AI_ENABLED=false` | Kill switch → honest fallback, everything else keeps working |
| `AI_PROVIDER=noop` | Fake provider (default): replies labeled demo, full flows testable |
| `AI_PROVIDER=gemini` + `GEMINI_API_KEY` | Live path: REST `generateContent` + functionDeclarations |
| `GEMINI_MODEL` | Configurable (default `gemini-2.0-flash`); temperature 0.4, bounded tokens |
| `AI_MAX_OUTPUT_TOKENS`, `AI_MAX_TOOL_CALLS`, `AI_TIMEOUT_SECONDS`, `AI_PUBLIC_CHAT_ENABLED` | Guardrails |

Fake works with no credentials; production fails safely (fallback + escalation, never invented data).

## Resilience

- Per-attempt timeout (`AI_TIMEOUT_SECONDS`), up to 3 attempts with exponential backoff on
  transport/429/5xx only (4xx fails fast); structured logs + usage hook (`set_usage_hook`)
  per attempt; `AIProviderError` → shared runtime returns `FALLBACK_PUBLIC` and marks escalation.
- Every turn audited: `ai_runs` (provider/model/latency/status) + `ai_tool_calls` (args/result/status/caller).
- Business prompts live server-side (`build_system_prompt`); no business-specific prompts in frontend.

## Endpoints

- Public: `POST /public/{slug}/ai/chat`, `GET /public/{slug}/business-info`, `GET /public/{slug}/availability?date=`
- Staff: `POST /ai/assistant`, `GET /ai/recommendations`, `POST /ai/recommendations/{id}/decide`
- Dashboard: `/assistant` (chat + approvals); websites: `<WebsiteChat/>` quick actions invoke real tools.
