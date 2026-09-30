"""Blocks 8-12 Pydantic contracts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Page(BaseModel):
    items: list[dict]
    total: int
    limit: int
    offset: int


# -- automation ---------------------------------------------------------------


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    event_type: str = Field(min_length=1, max_length=64)
    is_active: bool = True
    priority: int = Field(default=100, ge=0, le=1000)
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class RuleOut(BaseModel):
    id: UUID
    business_id: UUID
    name: str
    event_type: str
    is_active: bool
    priority: int
    conditions: dict[str, Any]
    actions: list[dict[str, Any]]
    config: dict[str, Any]


class ExecutionOut(BaseModel):
    id: UUID
    business_id: UUID
    rule_id: UUID | None
    event_type: str
    status: str
    attempt_count: int
    idempotency_key: str
    correlation_id: str
    error: str


class TriggerIn(BaseModel):
    event_type: str = Field(min_length=1, max_length=64)
    entity_type: str | None = Field(default=None, max_length=48)
    entity_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


# -- communications -------------------------------------------------------------


class ConversationOut(BaseModel):
    id: UUID
    channel: str
    external_id: str
    status: str
    subject_name: str


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID | None
    direction: str
    channel: str
    body: str
    status: str
    provider: str


class SendMessageIn(BaseModel):
    channel: str = Field(default="whatsapp", max_length=32)
    to: str = Field(min_length=1, max_length=320)
    body: str = Field(default="", max_length=4000)
    template_code: str = Field(default="", max_length=128)
    conversation_id: UUID | None = None
    # Safe request-level idempotency: retries with the same key return the
    # existing message without re-sending (see communications.send_message).
    idempotency_key: str = Field(default="", max_length=128)
    # Provider hint: "" (auto) | "mock"/"log" (demo-safe) |
    # "meta_cloud"/"whatsapp" (live Meta Cloud API via own business creds).
    provider: str = Field(default="", max_length=32)


class TemplateIn(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    channel: str = Field(default="whatsapp", max_length=32)
    name: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=4000)
    variables: list[str] = Field(default_factory=list)
    is_active: bool = True


class PreferenceIn(BaseModel):
    channel: str = Field(min_length=1, max_length=32)
    address: str = Field(min_length=1, max_length=320)
    opt_in: bool = True


class HandoffIn(BaseModel):
    """AI -> staff handoff (Prompt 7): verified summary only, no secrets."""

    model_config = {"extra": "forbid"}

    customer_name: str = Field(default="", max_length=200)
    customer_phone: str = Field(default="", max_length=32)
    conversation_id: UUID | None = None
    summary_points: list[str] = Field(default_factory=list, max_length=10)
    reason: str = Field(default="", max_length=500)


# -- AI --------------------------------------------------------------------------


class PublicChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    visitor_key: str = Field(default="anon", max_length=200)
    conversation_id: str = Field(default="", max_length=64)


class PublicChatOut(BaseModel):
    reply: str
    conversation_id: str
    escalated: bool = False


class AssistIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    scope: str = Field(default="business", max_length=16)


class AssistOut(BaseModel):
    reply: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    escalated: bool = False


class RecommendationOut(BaseModel):
    id: UUID
    rec_type: str
    title: str
    reason: str
    confidence: str
    suggested_action: str
    status: str
    risk_level: str


class RecommendationDecideIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")


# -- growth -----------------------------------------------------------------------


class SourceOut(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool


class AttributionIn(BaseModel):
    subject_type: str = Field(min_length=1, max_length=32)
    subject_id: UUID | None = None
    source_code: str = Field(default="other", max_length=64)
    campaign: str = Field(default="", max_length=200)


class ReferralIn(BaseModel):
    referrer_name: str = Field(min_length=1, max_length=200)
    referrer_phone: str | None = Field(default=None, max_length=32)
    referred_name: str = Field(min_length=1, max_length=200)
    referred_phone: str | None = Field(default=None, max_length=32)
    source: str = Field(default="other", max_length=64)
    consent: bool = False
    create_lead: bool = True
    notes: str = Field(default="", max_length=2000)


class CrossSellIn(BaseModel):
    target_business_id: UUID
    member_id: UUID | None = None
    customer_id: UUID | None = None
    lead_id: UUID | None = None
    reason: str = Field(default="", max_length=1000)
    offer: str = Field(default="", max_length=1000)


class ConsentIn(BaseModel):
    consent: bool
