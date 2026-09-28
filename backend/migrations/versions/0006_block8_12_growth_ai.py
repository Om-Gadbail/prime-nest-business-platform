"""Blocks 8-12 — automation + communication + AI + growth + intelligence.

Revision ID: 0006_block8_12_growth_ai
Revises: 0005_block5_7_operations

DDL (all BUSINESS_SCOPED unless noted):
- ``automation_rules`` / ``automation_executions`` / ``daily_reports``
- ``conversations`` / ``messages`` / ``message_templates`` /
  ``communication_preferences`` / ``message_delivery_events``
- ``ai_conversations`` / ``ai_messages`` / ``ai_tool_calls`` /
  ``ai_recommendations``
- ``growth_sources`` / ``attributions`` / ``referrals`` /
  ``cross_sell_opportunities`` / ``analytics_snapshots``
- ``business_relationships`` (GLOBAL cross-business link, not scoped)

Data: insert Blocks 8-12 permissions + system-role grants (idempotent).
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_block8_12_growth_ai"
down_revision: Union[str, None] = "0005_block5_7_operations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BLOCK812_NEW_PERMISSION_KEYS = (
    "automation.read",
    "automation.manage",
    "communications.read",
    "communications.manage",
    "whatsapp.manage",
    "ai.assist",
    "ai.manage",
    "growth.read",
    "growth.manage",
    "reports.read",
)

BLOCK812_ROLE_GRANTS: dict[str, frozenset[str]] = {
    "OWNER": frozenset(BLOCK812_NEW_PERMISSION_KEYS),
    "ADMIN": frozenset(BLOCK812_NEW_PERMISSION_KEYS),
    "MANAGER": frozenset(
        {"automation.read", "communications.read", "ai.assist", "growth.read", "reports.read"}
    ),
    "STAFF": frozenset({"communications.read", "ai.assist", "growth.read"}),
    "VIEWER": frozenset(
        {"automation.read", "communications.read", "growth.read", "reports.read"}
    ),
}


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def _ts_columns() -> list:
    return [
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _ts(), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("conditions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("actions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automation_rules_business_active", "automation_rules", ["business_id", "is_active"])
    op.create_index("ix_automation_rules_business_event", "automation_rules", ["business_id", "event_type"])

    op.create_table(
        "automation_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("idempotency_key", sa.String(128), nullable=False, server_default=""),
        sa.Column("correlation_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("input_payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("output_payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error", sa.String(2000), nullable=False, server_default=""),
        sa.Column("scheduled_at", _ts(), nullable=True),
        sa.Column("started_at", _ts(), nullable=True),
        sa.Column("completed_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rule_id"], ["automation_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "idempotency_key", name="uq_auto_exec_business_idem"),
    )
    op.create_index("ix_auto_exec_business_status", "automation_executions", ["business_id", "status"])
    op.create_index("ix_auto_exec_business_rule", "automation_executions", ["business_id", "rule_id"])
    op.create_index("ix_auto_exec_business_created", "automation_executions", ["business_id", "created_at"])
    op.create_index("ix_auto_exec_business_event", "automation_executions", ["business_id", "event_type"])

    op.create_table(
        "daily_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_date", sa.String(10), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "report_date", name="uq_daily_reports_business_date"),
    )
    op.create_index("ix_daily_reports_business_created", "daily_reports", ["business_id", "created_at"])

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False, server_default="web"),
        sa.Column("external_id", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("subject_phone", sa.String(32), nullable=True),
        sa.Column("last_message_at", _ts(), nullable=True),
        sa.Column("consent_marketing", sa.Boolean(), nullable=False, server_default="false"),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_business_status", "conversations", ["business_id", "status"])
    op.create_index("ix_conversations_business_channel", "conversations", ["business_id", "channel"])
    op.create_index("ix_conversations_business_lead", "conversations", ["business_id", "lead_id"])
    op.create_index("ix_conversations_business_contact", "conversations", ["business_id", "contact_id"])
    op.create_index("ix_conversations_business_updated", "conversations", ["business_id", "updated_at"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("direction", sa.String(16), nullable=False, server_default="outbound"),
        sa.Column("channel", sa.String(32), nullable=False, server_default="whatsapp"),
        sa.Column("sender", sa.String(200), nullable=False, server_default=""),
        sa.Column("recipient", sa.String(200), nullable=False, server_default=""),
        sa.Column("body", sa.String(4000), nullable=False, server_default=""),
        sa.Column("template_code", sa.String(128), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("provider", sa.String(64), nullable=False, server_default="log"),
        sa.Column("provider_message_id", sa.String(200), nullable=False, server_default=""),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ai_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "provider_message_id", name="uq_messages_business_provider"),
    )
    op.create_index("ix_messages_business_conv", "messages", ["business_id", "conversation_id"])
    op.create_index("ix_messages_business_status", "messages", ["business_id", "status"])
    op.create_index("ix_messages_business_created", "messages", ["business_id", "created_at"])

    op.create_table(
        "message_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False, server_default="whatsapp"),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("body", sa.String(4000), nullable=False, server_default=""),
        sa.Column("variables", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "code", name="uq_msg_templates_business_code"),
    )
    op.create_index("ix_msg_templates_business_channel", "message_templates", ["business_id", "channel"])

    op.create_table(
        "communication_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("address", sa.String(320), nullable=False),
        sa.Column("opt_in", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "channel", "address", name="uq_comm_prefs_business_channel_address"),
    )
    op.create_index("ix_comm_prefs_business_channel", "communication_preferences", ["business_id", "channel"])

    op.create_table(
        "message_delivery_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_message_id", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default=""),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_msg_delivery_business_msg", "message_delivery_events", ["business_id", "message_id"])
    op.create_index("ix_msg_delivery_business_created", "message_delivery_events", ["business_id", "created_at"])

    op.create_table(
        "ai_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False, server_default="web"),
        sa.Column("visitor_key", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="public"),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("consent", sa.Boolean(), nullable=False, server_default="false"),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_conv_business_channel", "ai_conversations", ["business_id", "channel"])
    op.create_index("ix_ai_conv_business_status", "ai_conversations", ["business_id", "status"])
    op.create_index("ix_ai_conv_business_visitor", "ai_conversations", ["business_id", "visitor_key"])

    op.create_table(
        "ai_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.String(8000), nullable=False, server_default=""),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("tool_results", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_msg_business_conv", "ai_messages", ["business_id", "conversation_id"])
    op.create_index("ix_ai_msg_business_created", "ai_messages", ["business_id", "created_at"])

    op.create_table(
        "ai_tool_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="success"),
        sa.Column("caller", sa.String(16), nullable=False, server_default="public"),
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_tool_business_conv", "ai_tool_calls", ["business_id", "conversation_id"])
    op.create_index("ix_ai_tool_business_tool", "ai_tool_calls", ["business_id", "tool_name"])
    op.create_index("ix_ai_tool_business_created", "ai_tool_calls", ["business_id", "created_at"])

    op.create_table(
        "ai_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rec_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("title", sa.String(300), nullable=False, server_default=""),
        sa.Column("reason", sa.String(2000), nullable=False, server_default=""),
        sa.Column("supporting_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.String(16), nullable=False, server_default="low"),
        sa.Column("suggested_action", sa.String(500), nullable=False, server_default=""),
        sa.Column("entity_type", sa.String(48), nullable=False, server_default=""),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("risk_level", sa.String(16), nullable=False, server_default="low"),
        sa.Column("created_by", sa.String(32), nullable=False, server_default="ai"),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_rec_business_status", "ai_recommendations", ["business_id", "status"])
    op.create_index("ix_ai_rec_business_type", "ai_recommendations", ["business_id", "rec_type"])
    op.create_index("ix_ai_rec_business_created", "ai_recommendations", ["business_id", "created_at"])

    op.create_table(
        "growth_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "code", name="uq_growth_sources_business_code"),
    )

    op.create_table(
        "attributions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_code", sa.String(64), nullable=False, server_default="other"),
        sa.Column("campaign", sa.String(200), nullable=False, server_default=""),
        sa.Column("landing_page", sa.String(500), nullable=False, server_default=""),
        sa.Column("referrer", sa.String(500), nullable=False, server_default=""),
        sa.Column("utm", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("converted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("revenue", sa.String(32), nullable=False, server_default="0"),
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attr_business_source", "attributions", ["business_id", "source_code"])
    op.create_index("ix_attr_business_subject", "attributions", ["business_id", "subject_type", "subject_id"])
    op.create_index("ix_attr_business_created", "attributions", ["business_id", "created_at"])

    op.create_table(
        "referrals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("referrer_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("referrer_phone", sa.String(32), nullable=True),
        sa.Column("referrer_member_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("referred_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("referred_phone", sa.String(32), nullable=True),
        sa.Column("referred_lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(64), nullable=False, server_default="other"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("consent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("converted_at", _ts(), nullable=True),
        sa.Column("notes", sa.String(2000), nullable=False, server_default=""),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["referred_lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_referrals_business_status", "referrals", ["business_id", "status"])
    op.create_index("ix_referrals_business_created", "referrals", ["business_id", "created_at"])

    op.create_table(
        "cross_sell_opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("eligibility_reason", sa.String(1000), nullable=False, server_default=""),
        sa.Column("offer", sa.String(1000), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="eligible"),
        sa.Column("consent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("converted_at", _ts(), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_business_id"], ["businesses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_xsell_business_status", "cross_sell_opportunities", ["business_id", "status"])
    op.create_index("ix_xsell_business_target", "cross_sell_opportunities", ["business_id", "target_business_id"])

    op.create_table(
        "business_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rel_type", sa.String(64), nullable=False, server_default="cross_sell"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["from_business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_business_id", "to_business_id", name="uq_business_rel_from_to"),
    )

    op.create_table(
        "analytics_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.String(32), nullable=False),
        sa.Column("metric_key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(64), nullable=False, server_default="0"),
        sa.Column("dimensions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("computed_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "period", "metric_key", name="uq_analytics_business_period_metric"),
    )
    op.create_index("ix_analytics_business_period", "analytics_snapshots", ["business_id", "period"])

    _seed_block812_permissions()


def _seed_block812_permissions() -> None:
    bind = op.get_bind()
    for key in BLOCK812_NEW_PERMISSION_KEYS:
        exists = bind.execute(
            sa.text("SELECT id FROM permissions WHERE key = :key"), {"key": key}
        ).first()
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO permissions (id, key, description) "
                    "VALUES (:id, :key, :description)"
                ),
                {"id": uuid4(), "key": key, "description": f"Blocks 8-12 permission: {key}."},
            )
    for role_name, keys in BLOCK812_ROLE_GRANTS.items():
        for key in keys:
            row = bind.execute(
                sa.text(
                    "SELECT r.id AS role_id, p.id AS perm_id FROM roles r "
                    "JOIN permissions p ON p.key = :key "
                    "WHERE r.name = :role AND r.business_id IS NULL"
                ),
                {"key": key, "role": role_name},
            ).first()
            if row is None:
                continue
            grant = bind.execute(
                sa.text(
                    "SELECT 1 FROM role_permissions "
                    "WHERE role_id = :role_id AND permission_id = :perm_id"
                ),
                {"role_id": row.role_id, "perm_id": row.perm_id},
            ).first()
            if grant is None:
                bind.execute(
                    sa.text(
                        "INSERT INTO role_permissions (role_id, permission_id) "
                        "VALUES (:role_id, :perm_id)"
                    ),
                    {"role_id": row.role_id, "perm_id": row.perm_id},
                )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE key IN :keys)"
        ).bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": list(BLOCK812_NEW_PERMISSION_KEYS)},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": list(BLOCK812_NEW_PERMISSION_KEYS)},
    )
    for table in (
        "analytics_snapshots",
        "business_relationships",
        "cross_sell_opportunities",
        "referrals",
        "attributions",
        "growth_sources",
        "ai_recommendations",
        "ai_tool_calls",
        "ai_messages",
        "ai_conversations",
        "message_delivery_events",
        "communication_preferences",
        "message_templates",
        "messages",
        "conversations",
        "daily_reports",
        "automation_executions",
        "automation_rules",
    ):
        op.drop_table(table)
