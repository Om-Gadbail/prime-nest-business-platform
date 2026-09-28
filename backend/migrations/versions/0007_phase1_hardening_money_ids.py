"""Phase 1 hardening — money precision + provider id nullability.

Revision ID: 0007_phase1_hardening_money_ids
Revises: 0006_block8_12_growth_ai

- ``attributions.revenue`` VARCHAR(32) -> NUMERIC(12,2) NOT NULL DEFAULT 0.00.
  Non-numeric legacy values are coerced to 0.00 (no data loss for valid
  decimals; garbage strings were never aggregatable anyway).
- ``analytics_snapshots.value`` VARCHAR(64) -> NUMERIC(14,2) NOT NULL
  DEFAULT 0.00 (counts stored as e.g. 42.00, money as 1234.50).
- ``messages.provider_message_id`` / ``message_delivery_events`` equivalent:
  NOT NULL DEFAULT '' -> NULLABLE, legacy '' -> NULL so the
  (business_id, provider_message_id) unique constraint never collides on
  unset values (NULLs are distinct in Postgres and SQLite).
- ``conversations``: partial UNIQUE INDEX on
  (business_id, channel, external_id) WHERE external_id <> '' to close the
  check-then-insert race at the DB layer (SQLite + Postgres compatible).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_phase1_hardening_money_ids"
down_revision: Union[str, None] = "0006_block8_12_growth_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind is not None else "postgresql"

    # -- attributions.revenue: string -> numeric ---------------------------------
    if dialect == "postgresql":
        bind.execute(sa.text(
            "UPDATE attributions SET revenue = '0' "
            "WHERE revenue IS NULL OR btrim(revenue) = '' "
            "OR revenue !~ '^\\s*-?[0-9]+(\\.[0-9]+)?\\s*$'"
        ))
        # Drop the string default first: Postgres cannot auto-cast it to NUMERIC.
        bind.execute(sa.text("ALTER TABLE attributions ALTER COLUMN revenue DROP DEFAULT"))
        op.alter_column(
            "attributions", "revenue",
            existing_type=sa.String(32),
            type_=sa.Numeric(12, 2),
            existing_nullable=False,
            existing_server_default=None,
            server_default="0.00",
            postgresql_using="btrim(revenue)::NUMERIC(12,2)",
        )
    else:
        # SQLite (tests/dev): recreate via batch mode for type fidelity.
        with op.batch_alter_table("attributions") as batch:
            batch.alter_column(
                "revenue",
                existing_type=sa.String(32),
                type_=sa.Numeric(12, 2),
                existing_nullable=False,
                existing_server_default="0",
                server_default="0.00",
            )

    # -- analytics_snapshots.value: string -> numeric ----------------------------
    if dialect == "postgresql":
        bind.execute(sa.text(
            "UPDATE analytics_snapshots SET value = '0' "
            "WHERE value IS NULL OR btrim(value) = '' "
            "OR value !~ '^\\s*-?[0-9]+(\\.[0-9]+)?\\s*$'"
        ))
        bind.execute(sa.text("ALTER TABLE analytics_snapshots ALTER COLUMN value DROP DEFAULT"))
        op.alter_column(
            "analytics_snapshots", "value",
            existing_type=sa.String(64),
            type_=sa.Numeric(14, 2),
            existing_nullable=False,
            existing_server_default=None,
            server_default="0.00",
            postgresql_using="btrim(value)::NUMERIC(14,2)",
        )
    else:
        with op.batch_alter_table("analytics_snapshots") as batch:
            batch.alter_column(
                "value",
                existing_type=sa.String(64),
                type_=sa.Numeric(14, 2),
                existing_nullable=False,
                existing_server_default="0",
                server_default="0.00",
            )

    # -- provider_message_id: '' -> NULL, nullable --------------------------------
    for table in ("messages", "message_delivery_events"):
        if dialect == "postgresql":
            bind.execute(sa.text(
                f"UPDATE {table} SET provider_message_id = NULL "
                f"WHERE provider_message_id = ''"
            ))
            bind.execute(sa.text(
                f"ALTER TABLE {table} ALTER COLUMN provider_message_id DROP DEFAULT"
            ))
            op.alter_column(
                table, "provider_message_id",
                existing_type=sa.String(200),
                type_=sa.String(200),
                existing_nullable=False,
                nullable=True,
                existing_server_default=None,
                server_default=None,
            )
        else:
            bind.execute(sa.text(
                f"UPDATE {table} SET provider_message_id = NULL "
                f"WHERE provider_message_id = ''"
            )) if _table_exists(bind, table) else None
            with op.batch_alter_table(table) as batch:
                batch.alter_column(
                    "provider_message_id",
                    existing_type=sa.String(200),
                    type_=sa.String(200),
                    existing_nullable=False,
                    nullable=True,
                    existing_server_default="",
                    server_default=None,
                )

    # -- conversations dedupe: partial unique index --------------------------------
    # Postgres + SQLite both support partial UNIQUE indexes (WHERE ...).
    op.create_index(
        "uq_conversations_business_channel_external",
        "conversations",
        ["business_id", "channel", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id <> ''"),
        sqlite_where=sa.text("external_id <> ''"),
    )


def downgrade() -> None:
    op.drop_index("uq_conversations_business_channel_external", table_name="conversations")

    for table in ("message_delivery_events", "messages"):
        op.alter_column(
            table, "provider_message_id",
            existing_type=sa.String(200),
            type_=sa.String(200),
            existing_nullable=True,
            nullable=False,
            existing_server_default=None,
            server_default="",
        )
        bind = op.get_bind()
        if bind is not None and _table_exists(bind, table):
            bind.execute(sa.text(
                f"UPDATE {table} SET provider_message_id = '' "
                f"WHERE provider_message_id IS NULL"
            ))

    op.alter_column(
        "analytics_snapshots", "value",
        existing_type=sa.Numeric(14, 2),
        type_=sa.String(64),
        existing_nullable=False,
        existing_server_default="0.00",
        server_default="0",
    )
    op.alter_column(
        "attributions", "revenue",
        existing_type=sa.Numeric(12, 2),
        type_=sa.String(32),
        existing_nullable=False,
        existing_server_default="0.00",
        server_default="0",
    )


def _table_exists(bind, table: str) -> bool:
    try:
        insp = sa.inspect(bind)
        return table in insp.get_table_names()
    except Exception:  # noqa: BLE001 - downgrade introspection must never fail hard
        return True
