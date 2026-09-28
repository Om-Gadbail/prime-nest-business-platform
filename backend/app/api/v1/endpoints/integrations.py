"""Safe integration status (Pre-Prompt-7 foundation).

GET /integrations/status — internal diagnostic for staff/owner dashboards.

- Business-scoped: the WhatsApp section ALWAYS describes the caller's OWN
  server-verified business (JWT + DB membership). A Prime staff member can
  never see Nest credentials — and not even Nest's section, unless they hold
  ``owner.combined.read`` (combined owner overview, booleans only).
- Secret-free: ONLY ``configured`` / ``enabled`` / ``mode`` / ``model``
  booleans and names. API keys, access tokens, app secrets, and verify
  tokens are NEVER returned (see integration_configs.safe_status).
- No live calls: this endpoint never sends messages and never calls Gemini;
  it reports configuration state only (Prompt 7 owns live testing).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api import deps
from app.core.config import get_settings
from app.services import integration_configs as iconf
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status", summary="Integration configuration status (safe)")
def integration_status(
    ctx: AuthenticatedContext = Depends(deps.require_permission("settings.read")),
):
    assert ctx.business is not None
    settings = get_settings()
    gemini = iconf.resolve_gemini_config(settings)
    own = iconf.resolve_whatsapp_config(settings, ctx.business)
    body: dict = {
        "business": {
            "slug": ctx.business.slug,
            "external_id": getattr(ctx.business, "external_id", None),
        },
        "gemini": gemini.safe_summary(),
        "whatsapp": own.safe_summary(),
    }
    # Combined owner overview (booleans only, no secrets): visible only to
    # callers who may access combined analytics. Staff without that grant
    # see ONLY their own business section above.
    if "owner.combined.read" in ctx.permissions:
        body["businesses"] = {
            "prime_whatsapp": iconf.resolve_whatsapp_config(
                settings, "prime"
            ).safe_summary(),
            "nest_whatsapp": iconf.resolve_whatsapp_config(
                settings, "nest"
            ).safe_summary(),
        }
    return body
