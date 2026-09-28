"""Block 2 — Leads & CRM foundation.

Revision ID: 0003_block2_leads_crm
Revises: 0002_identity_multitenancy

DDL: contacts, customers, leads, lead_activities, bookings, notifications,
notification_preferences, idempotency_records, ai_runs (all business-scoped).

Data: insert the 9 new Block 2 permissions and grant them to the system
roles per the matrix in app/models/rbac.py (hardcoded here so this
historical migration never depends on future code changes).
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_block2_leads_crm"
down_revision: Union[str, None] = "0002_identity_multitenancy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Must mirror app/models/rbac.py at Block 2 time.
BLOCK2_PERMISSION_KEYS = (
    "contacts.read",
    "contacts.create",
    "contacts.update",
    "customers.read",
    "customers.create",
    "customers.update",
    "notifications.read",
    "notifications.update",
    "ai.read",
)

BLOCK2_ROLE_GRANTS: dict[str, frozenset[str]] = {
    "OWNER": frozenset(BLOCK2_PERMISSION_KEYS),
    "ADMIN": frozenset(BLOCK2_PERMISSION_KEYS),
    "MANAGER": frozenset(BLOCK2_PERMISSION_KEYS),
    "STAFF": frozenset(
        {"contacts.read", "contacts.create", "customers.read", "notifications.read"}
    ),
    "VIEWER": frozenset({"contacts.read", "customers.read", "notifications.read"}),
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
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("normalized_phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("normalized_email", sa.String(length=320), nullable=True),
        sa.Column("preferred_contact_channel", sa.String(length=16), nullable=False, server_default="other"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("notes", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_contacts_business_id_businesses", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_contacts"),
    )
    op.create_index("ix_contacts_business_id", "contacts", ["business_id"], unique=False)
    op.create_index("ix_contacts_business_created", "contacts", ["business_id", "created_at"], unique=False)
    op.create_index("ix_contacts_business_phone", "contacts", ["business_id", "normalized_phone"], unique=False)
    op.create_index("ix_contacts_business_email", "contacts", ["business_id", "normalized_email"], unique=False)

    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("customer_since", _ts(), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=False, server_default=""),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_customers_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], name="fk_customers_contact_id_contacts", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
        sa.UniqueConstraint("business_id", "contact_id", name="uq_customers_business_contact"),
    )
    op.create_index("ix_customers_business_id", "customers", ["business_id"], unique=False)
    op.create_index("ix_customers_contact_id", "customers", ["contact_id"], unique=False)
    op.create_index("ix_customers_business_created", "customers", ["business_id", "created_at"], unique=False)

    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("normalized_phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("normalized_email", sa.String(length=320), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="website"),
        sa.Column("source_detail", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("assigned_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service_interest", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("message", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("follow_up_at", _ts(), nullable=True),
        sa.Column("last_contacted_at", _ts(), nullable=True),
        sa.Column("converted_at", _ts(), nullable=True),
        sa.Column("lost_reason", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("consent_marketing", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("landing_page", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("referrer", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("utm_source", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("utm_medium", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("utm_campaign", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("utm_term", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("utm_content", sa.String(length=200), nullable=False, server_default=""),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_leads_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], name="fk_leads_contact_id_contacts", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_leads_customer_id_customers", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], name="fk_leads_assigned_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_leads"),
    )
    op.create_index("ix_leads_business_id", "leads", ["business_id"], unique=False)
    op.create_index("ix_leads_contact_id", "leads", ["contact_id"], unique=False)
    op.create_index("ix_leads_customer_id", "leads", ["customer_id"], unique=False)
    op.create_index("ix_leads_business_status", "leads", ["business_id", "status"], unique=False)
    op.create_index("ix_leads_business_created", "leads", ["business_id", "created_at"], unique=False)
    op.create_index("ix_leads_business_assigned", "leads", ["business_id", "assigned_user_id"], unique=False)
    op.create_index("ix_leads_business_phone", "leads", ["business_id", "normalized_phone"], unique=False)
    op.create_index("ix_leads_business_email", "leads", ["business_id", "normalized_email"], unique=False)
    op.create_index("ix_leads_business_follow_up", "leads", ["business_id", "follow_up_at"], unique=False)

    op.create_table(
        "lead_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activity_type", sa.String(length=48), nullable=False, server_default="note"),
        sa.Column("note", sa.String(length=2000), nullable=False, server_default=""),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_lead_activities_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], name="fk_lead_activities_lead_id_leads", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_lead_activities_actor_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_lead_activities"),
    )
    op.create_index("ix_lead_activities_business_id", "lead_activities", ["business_id"], unique=False)
    op.create_index("ix_lead_activities_lead_created", "lead_activities", ["lead_id", "created_at"], unique=False)
    op.create_index("ix_lead_activities_business_created", "lead_activities", ["business_id", "created_at"], unique=False)

    op.create_table(
        "bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("booking_type", sa.String(length=32), nullable=False, server_default="enquiry"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="requested"),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("requested_start_at", _ts(), nullable=True),
        sa.Column("requested_end_at", _ts(), nullable=True),
        sa.Column("assigned_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="website"),
        sa.Column("cancellation_reason", sa.String(length=500), nullable=False, server_default=""),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_bookings_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], name="fk_bookings_contact_id_contacts", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_bookings_customer_id_customers", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], name="fk_bookings_lead_id_leads", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], name="fk_bookings_assigned_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_bookings"),
    )
    op.create_index("ix_bookings_business_id", "bookings", ["business_id"], unique=False)
    op.create_index("ix_bookings_business_start", "bookings", ["business_id", "requested_start_at"], unique=False)
    op.create_index("ix_bookings_business_status", "bookings", ["business_id", "status"], unique=False)
    op.create_index("ix_bookings_business_assigned", "bookings", ["business_id", "assigned_user_id"], unique=False)
    op.create_index("ix_bookings_contact", "bookings", ["contact_id"], unique=False)
    op.create_index("ix_bookings_lead", "bookings", ["lead_id"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.String(length=48), nullable=False, server_default="system"),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("body", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("read_at", _ts(), nullable=True),
        sa.Column("source_type", sa.String(length=48), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("dedupe_key", sa.String(length=128), nullable=True),
        sa.Column("expires_at", _ts(), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_notifications_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], name="fk_notifications_recipient_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.UniqueConstraint("business_id", "recipient_user_id", "dedupe_key", name="uq_notifications_recipient_dedupe"),
    )
    op.create_index("ix_notifications_business_id", "notifications", ["business_id"], unique=False)
    op.create_index("ix_notifications_recipient_user_id", "notifications", ["recipient_user_id"], unique=False)
    op.create_index("ix_notifications_recipient_unread", "notifications", ["business_id", "recipient_user_id", "read_at"], unique=False)
    op.create_index("ix_notifications_business_created", "notifications", ["business_id", "created_at"], unique=False)

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.String(length=48), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_notification_preferences_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_notification_preferences_business_id_businesses", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "business_id", "notification_type", name="pk_notification_preferences"),
    )
    op.create_index("ix_notification_preferences_business_id", "notification_preferences", ["business_id"], unique=False)

    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=False),
        sa.Column("idem_key", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_idempotency_records_business_id_businesses", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        sa.UniqueConstraint("business_id", "endpoint", "idem_key", name="uq_idempotency_scope_key"),
    )
    op.create_index("ix_idempotency_business_id", "idempotency_records", ["business_id"], unique=False)
    op.create_index("ix_idempotency_created", "idempotency_records", ["created_at"], unique=False)

    op.create_table(
        "ai_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="noop"),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="success"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_chars", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("error", sa.String(length=500), nullable=False, server_default=""),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_ai_runs_business_id_businesses", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_runs"),
    )
    op.create_index("ix_ai_runs_business_id", "ai_runs", ["business_id"], unique=False)
    op.create_index("ix_ai_runs_business_created", "ai_runs", ["business_id", "created_at"], unique=False)
    op.create_index("ix_ai_runs_business_capability", "ai_runs", ["business_id", "capability"], unique=False)

    _seed_block2_permissions()


def _seed_block2_permissions() -> None:
    """Insert Block 2 permissions + system-role grants (idempotent)."""
    bind = op.get_bind()
    for key in BLOCK2_PERMISSION_KEYS:
        exists = bind.execute(
            sa.text("SELECT id FROM permissions WHERE key = :key"),
            {"key": key},
        ).first()
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO permissions (id, key, description) "
                    "VALUES (:id, :key, :description)"
                ),
                {
                    "id": uuid4(),
                    "key": key,
                    "description": f"Block 2 CRM permission: {key}.",
                },
            )
    for role_name, keys in BLOCK2_ROLE_GRANTS.items():
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
        {"keys": list(BLOCK2_PERMISSION_KEYS)},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": list(BLOCK2_PERMISSION_KEYS)},
    )

    op.drop_table("ai_runs")
    op.drop_table("idempotency_records")
    op.drop_table("notification_preferences")
    op.drop_table("notifications")
    op.drop_table("bookings")
    op.drop_table("lead_activities")
    op.drop_table("leads")
    op.drop_table("customers")
    op.drop_table("contacts")
