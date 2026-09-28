"""Blocks 8-12 repositories: automation, comms, AI, growth. SQL only."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai_business import (
    AIConversation,
    AIMessage,
    AIRecommendation,
    AIToolCall,
)
from app.models.automation import AutomationExecution, AutomationRule, DailyReport
from app.models.communication import (
    CommunicationPreference,
    Conversation,
    Message,
    MessageDeliveryEvent,
    MessageTemplate,
)
from app.models.growth import (
    AnalyticsSnapshot,
    Attribution,
    BusinessRelationship,
    CrossSellOpportunity,
    GrowthSource,
    Referral,
)
from app.repositories.base import apply_business_scope, get_scoped
from app.repositories.pagination import clamp_page

# -- automation ---------------------------------------------------------------


def create_rule(db: Session, *, business_id: uuid.UUID, fields: dict) -> AutomationRule:
    row = AutomationRule(business_id=business_id, **fields)
    db.add(row)
    db.flush()
    return row


def list_rules(
    db: Session,
    *,
    business_id: uuid.UUID,
    event_type: str | None = None,
    active_only: bool = False,
    limit=None,
    offset=None,
):
    stmt = apply_business_scope(select(AutomationRule), AutomationRule, business_id)
    if event_type:
        stmt = stmt.where(AutomationRule.event_type == event_type)
    if active_only:
        stmt = stmt.where(AutomationRule.is_active.is_(True))
    stmt = stmt.order_by(AutomationRule.priority.asc(), AutomationRule.created_at.asc())
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    return list(db.execute(stmt.offset(off).limit(lim)).scalars().all()), total


def get_execution_by_idem(db: Session, *, business_id: uuid.UUID, idem: str):
    stmt = apply_business_scope(
        select(AutomationExecution), AutomationExecution, business_id
    )
    stmt = stmt.where(AutomationExecution.idempotency_key == idem)
    return db.execute(stmt).scalars().first()


def create_execution(
    db: Session, *, business_id: uuid.UUID, fields: dict
) -> AutomationExecution:
    row = AutomationExecution(business_id=business_id, **fields)
    db.add(row)
    db.flush()
    return row


def list_executions(
    db: Session,
    *,
    business_id: uuid.UUID,
    status: str | None = None,
    rule_id=None,
    limit=None,
    offset=None,
):
    stmt = apply_business_scope(
        select(AutomationExecution), AutomationExecution, business_id
    )
    if status:
        stmt = stmt.where(AutomationExecution.status == status)
    if rule_id:
        stmt = stmt.where(AutomationExecution.rule_id == rule_id)
    stmt = stmt.order_by(AutomationExecution.created_at.desc())
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    return list(db.execute(stmt.offset(off).limit(lim)).scalars().all()), total


def get_report(db: Session, *, business_id: uuid.UUID, report_date: str):
    stmt = apply_business_scope(select(DailyReport), DailyReport, business_id)
    stmt = stmt.where(DailyReport.report_date == report_date)
    return db.execute(stmt).scalars().first()


def upsert_report(
    db: Session, *, business_id: uuid.UUID, report_date: str, payload: dict
) -> DailyReport:
    existing = get_report(db, business_id=business_id, report_date=report_date)
    if existing:
        existing.payload = payload
        existing.status = "ready"
        db.flush()
        return existing
    row = DailyReport(business_id=business_id, report_date=report_date, payload=payload)
    db.add(row)
    db.flush()
    return row


# -- communications -----------------------------------------------------------


def get_or_create_conversation(
    db: Session,
    *,
    business_id: uuid.UUID,
    channel: str,
    external_id: str = "",
    **fields,
) -> Conversation:
    from sqlalchemy.exc import IntegrityError

    if external_id:
        stmt = apply_business_scope(select(Conversation), Conversation, business_id)
        stmt = stmt.where(
            Conversation.channel == channel, Conversation.external_id == external_id
        )
        existing = db.execute(stmt).scalars().first()
        if existing:
            return existing
    savepoint = db.begin_nested()
    try:
        row = Conversation(
            business_id=business_id, channel=channel, external_id=external_id, **fields
        )
        db.add(row)
        db.flush()
        savepoint.commit()
        return row
    except IntegrityError:
        savepoint.rollback()
        if external_id:
            stmt = apply_business_scope(select(Conversation), Conversation, business_id)
            stmt = stmt.where(
                Conversation.channel == channel, Conversation.external_id == external_id
            )
            existing = db.execute(stmt).scalars().first()
            if existing:
                return existing
        raise


def list_conversations(
    db: Session,
    *,
    business_id: uuid.UUID,
    channel=None,
    status=None,
    limit=None,
    offset=None,
):
    stmt = apply_business_scope(select(Conversation), Conversation, business_id)
    if channel:
        stmt = stmt.where(Conversation.channel == channel)
    if status:
        stmt = stmt.where(Conversation.status == status)
    stmt = stmt.order_by(Conversation.updated_at.desc())
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    return list(db.execute(stmt.offset(off).limit(lim)).scalars().all()), total


def create_message(db: Session, *, business_id: uuid.UUID, fields: dict) -> Message:
    # Normalize legacy "" provider ids to NULL so the
    # (business_id, provider_message_id) unique constraint never collides
    # on unset values. Real provider ids are always non-empty strings.
    data = dict(fields)
    if not data.get("provider_message_id"):
        data["provider_message_id"] = None
    row = Message(business_id=business_id, **data)
    db.add(row)
    db.flush()
    return row


def get_message_by_provider(
    db: Session, *, business_id: uuid.UUID, provider_message_id: str | None
):
    if not provider_message_id:
        return None
    stmt = apply_business_scope(select(Message), Message, business_id)
    stmt = stmt.where(Message.provider_message_id == provider_message_id)
    return db.execute(stmt).scalars().first()


def list_messages(
    db: Session,
    *,
    business_id: uuid.UUID,
    conversation_id=None,
    lead_id=None,
    limit=None,
    offset=None,
):
    stmt = apply_business_scope(select(Message), Message, business_id)
    if conversation_id:
        stmt = stmt.where(Message.conversation_id == conversation_id)
    stmt = stmt.order_by(Message.created_at.desc())
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    return list(db.execute(stmt.offset(off).limit(lim)).scalars().all()), total


def upsert_template(
    db: Session, *, business_id: uuid.UUID, code: str, fields: dict
) -> MessageTemplate:
    stmt = apply_business_scope(select(MessageTemplate), MessageTemplate, business_id)
    stmt = stmt.where(MessageTemplate.code == code)
    existing = db.execute(stmt).scalars().first()
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        db.flush()
        return existing
    row = MessageTemplate(business_id=business_id, code=code, **fields)
    db.add(row)
    db.flush()
    return row


def list_templates(
    db: Session, *, business_id: uuid.UUID, channel=None, limit=None, offset=None
):
    stmt = apply_business_scope(select(MessageTemplate), MessageTemplate, business_id)
    if channel:
        stmt = stmt.where(MessageTemplate.channel == channel)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    stmt = stmt.order_by(MessageTemplate.code.asc()).offset(off).limit(lim)
    return list(db.execute(stmt).scalars().all()), total


def get_preference(db: Session, *, business_id: uuid.UUID, channel: str, address: str):
    stmt = apply_business_scope(
        select(CommunicationPreference), CommunicationPreference, business_id
    )
    stmt = stmt.where(
        CommunicationPreference.channel == channel,
        CommunicationPreference.address == address,
    )
    return db.execute(stmt).scalars().first()


def set_preference(
    db: Session,
    *,
    business_id: uuid.UUID,
    channel: str,
    address: str,
    opt_in: bool,
    **fields,
) -> CommunicationPreference:
    existing = get_preference(
        db, business_id=business_id, channel=channel, address=address
    )
    if existing:
        existing.opt_in = opt_in
        for k, v in fields.items():
            setattr(existing, k, v)
        db.flush()
        return existing
    row = CommunicationPreference(
        business_id=business_id,
        channel=channel,
        address=address,
        opt_in=opt_in,
        **fields,
    )
    db.add(row)
    db.flush()
    return row


def record_delivery(
    db: Session, *, business_id: uuid.UUID, fields: dict
) -> MessageDeliveryEvent:
    row = MessageDeliveryEvent(business_id=business_id, **fields)
    db.add(row)
    db.flush()
    return row


# -- AI ------------------------------------------------------------------------


def get_or_create_ai_conversation(
    db: Session,
    *,
    business_id: uuid.UUID,
    channel: str,
    visitor_key: str,
    mode: str = "public",
) -> AIConversation:
    stmt = apply_business_scope(select(AIConversation), AIConversation, business_id)
    stmt = stmt.where(
        AIConversation.channel == channel,
        AIConversation.visitor_key == visitor_key,
        AIConversation.status == "active",
        AIConversation.mode == mode,
    )
    existing = db.execute(stmt).scalars().first()
    if existing:
        return existing
    row = AIConversation(
        business_id=business_id, channel=channel, visitor_key=visitor_key, mode=mode
    )
    db.add(row)
    db.flush()
    return row


def add_ai_message(
    db: Session,
    *,
    business_id: uuid.UUID,
    conversation_id,
    role: str,
    content: str,
    model: str = "",
    tool_calls=None,
    tool_results=None,
) -> AIMessage:
    row = AIMessage(
        business_id=business_id,
        conversation_id=conversation_id,
        role=role,
        content=content[:8000],
        model=model[:128],
        tool_calls=list(tool_calls or []),
        tool_results=list(tool_results or []),
    )
    db.add(row)
    db.flush()
    return row


def recent_ai_messages(
    db: Session, *, business_id: uuid.UUID, conversation_id, limit: int = 20
):
    stmt = apply_business_scope(select(AIMessage), AIMessage, business_id)
    stmt = (
        stmt.where(AIMessage.conversation_id == conversation_id)
        .order_by(AIMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(db.execute(stmt).scalars().all())
    return list(reversed(rows))


def record_tool_call(
    db: Session, *, business_id: uuid.UUID, fields: dict
) -> AIToolCall:
    row = AIToolCall(business_id=business_id, **fields)
    db.add(row)
    db.flush()
    return row


def create_recommendation(
    db: Session, *, business_id: uuid.UUID, fields: dict
) -> AIRecommendation:
    row = AIRecommendation(business_id=business_id, **fields)
    db.add(row)
    db.flush()
    return row


def list_recommendations(
    db: Session, *, business_id: uuid.UUID, status=None, limit=None, offset=None
):
    stmt = apply_business_scope(select(AIRecommendation), AIRecommendation, business_id)
    if status:
        stmt = stmt.where(AIRecommendation.status == status)
    stmt = stmt.order_by(AIRecommendation.created_at.desc())
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    return list(db.execute(stmt.offset(off).limit(lim)).scalars().all()), total


def get_recommendation(
    db: Session, *, business_id: uuid.UUID, rec_id
) -> AIRecommendation | None:
    return get_scoped(db, AIRecommendation, rec_id, business_id)


# -- growth ---------------------------------------------------------------------


def upsert_source(
    db: Session, *, business_id: uuid.UUID, code: str, name: str = ""
) -> GrowthSource:
    stmt = apply_business_scope(select(GrowthSource), GrowthSource, business_id)
    stmt = stmt.where(GrowthSource.code == code)
    existing = db.execute(stmt).scalars().first()
    if existing:
        if name:
            existing.name = name
        db.flush()
        return existing
    row = GrowthSource(business_id=business_id, code=code, name=name or code)
    db.add(row)
    db.flush()
    return row


def list_sources(db: Session, *, business_id: uuid.UUID):
    stmt = apply_business_scope(
        select(GrowthSource), GrowthSource, business_id
    ).order_by(GrowthSource.code.asc())
    return list(db.execute(stmt).scalars().all())


def create_attribution(
    db: Session, *, business_id: uuid.UUID, fields: dict
) -> Attribution:
    row = Attribution(business_id=business_id, **fields)
    db.add(row)
    db.flush()
    return row


def funnel_by_source(db: Session, *, business_id: uuid.UUID):
    # Portable aggregation in Python (avoids dialect-specific boolean casts).
    rows = list(
        db.execute(select(Attribution).where(Attribution.business_id == business_id))
        .scalars()
        .all()
    )
    agg: dict[str, dict] = {}
    for r in rows:
        slot = agg.setdefault(r.source_code, {"leads": 0, "converted": 0})
        slot["leads"] += 1
        if r.converted:
            slot["converted"] += 1
    return agg


def create_referral(db: Session, *, business_id: uuid.UUID, fields: dict) -> Referral:
    row = Referral(business_id=business_id, **fields)
    db.add(row)
    db.flush()
    return row


def list_referrals(
    db: Session, *, business_id: uuid.UUID, status=None, limit=None, offset=None
):
    stmt = apply_business_scope(select(Referral), Referral, business_id)
    if status:
        stmt = stmt.where(Referral.status == status)
    stmt = stmt.order_by(Referral.created_at.desc())
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    return list(db.execute(stmt.offset(off).limit(lim)).scalars().all()), total


def create_xsell(
    db: Session, *, business_id: uuid.UUID, fields: dict
) -> CrossSellOpportunity:
    row = CrossSellOpportunity(business_id=business_id, **fields)
    db.add(row)
    db.flush()
    return row


def list_xsell(
    db: Session, *, business_id: uuid.UUID, status=None, limit=None, offset=None
):
    stmt = apply_business_scope(
        select(CrossSellOpportunity), CrossSellOpportunity, business_id
    )
    if status:
        stmt = stmt.where(CrossSellOpportunity.status == status)
    stmt = stmt.order_by(CrossSellOpportunity.created_at.desc())
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    lim, off = clamp_page(limit, offset)
    return list(db.execute(stmt.offset(off).limit(lim)).scalars().all()), total


def upsert_relationship(
    db: Session, *, from_business_id, to_business_id, rel_type="cross_sell", config=None
) -> BusinessRelationship:
    stmt = select(BusinessRelationship).where(
        BusinessRelationship.from_business_id == from_business_id,
        BusinessRelationship.to_business_id == to_business_id,
    )
    existing = db.execute(stmt).scalars().first()
    if existing:
        existing.rel_type = rel_type
        existing.is_active = True
        if config is not None:
            existing.config = config
        db.flush()
        return existing
    row = BusinessRelationship(
        from_business_id=from_business_id,
        to_business_id=to_business_id,
        rel_type=rel_type,
        config=dict(config or {}),
    )
    db.add(row)
    db.flush()
    return row


def list_relationships(db: Session, *, business_id=None):
    stmt = select(BusinessRelationship)
    if business_id:
        stmt = stmt.where(
            (BusinessRelationship.from_business_id == business_id)
            | (BusinessRelationship.to_business_id == business_id)
        )
    return list(db.execute(stmt).scalars().all())


def upsert_snapshot(
    db: Session,
    *,
    business_id: uuid.UUID,
    period: str,
    metric_key: str,
    value: object,
    dimensions=None,
) -> AnalyticsSnapshot:
    from decimal import Decimal, InvalidOperation

    try:
        amount = Decimal(str(value)) if not isinstance(value, Decimal) else value
    except (InvalidOperation, ValueError, AttributeError, TypeError):
        amount = Decimal("0.00")
    try:
        amount = amount.quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001 - non-finite (NaN/Inf) falls back to zero
        amount = Decimal("0.00")
    stmt = apply_business_scope(
        select(AnalyticsSnapshot), AnalyticsSnapshot, business_id
    )
    stmt = stmt.where(
        AnalyticsSnapshot.period == period, AnalyticsSnapshot.metric_key == metric_key
    )
    existing = db.execute(stmt).scalars().first()
    if existing:
        existing.value = amount
        existing.dimensions = dict(dimensions or {})
        db.flush()
        return existing
    row = AnalyticsSnapshot(
        business_id=business_id,
        period=period,
        metric_key=metric_key,
        value=amount,
        dimensions=dict(dimensions or {}),
    )
    db.add(row)
    db.flush()
    return row
