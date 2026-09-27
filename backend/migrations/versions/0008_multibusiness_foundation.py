"""Multi-business foundation — platform business registry (Prompt 2).

Revision ID: 0008_multibusiness_foundation
Revises: 0007_phase1_hardening_money_ids

STRICTLY ADDITIVE. No tables dropped, no columns dropped, no data deleted,
no history rewritten. Safe to run against the live single ``app_db``:

- ``businesses.external_id`` (nullable, unique): stable platform-wide key
  (``prime-fitness-001`` / ``nest-library-001``). The UUID PK is untouched;
  every existing FK keeps working.
- ``businesses.database_key`` (NOT NULL, default ``''``): trusted
  operational-database routing key (``prime_db`` / ``nest_db``). Empty means
  "no mapping" and the application FAILS CLOSED (no fallback database).
- ``businesses.config_ref`` (nullable): informational config reference.
- Backfill: ``prime`` -> (``prime-fitness-001``, ``prime_db``),
  ``nest`` -> (``nest-library-001``, ``nest_db``). Rows for any other slug
  keep ``''``/NULL and stay fail-closed until platform ops assigns them.
- Unique index on ``external_id`` (NULLs are distinct in Postgres/SQLite).

Cutover strategy (docs/database-migration-report.md): this migration runs
against the existing shared database first (registry in place, physical
topology unchanged = co-located mode). Per-database URLs + data movement
happen later without further schema changes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_multibusiness_foundation"
down_revision: Union[str, None] = "0007_phase1_hardening_money_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind is not None else "postgresql"
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("businesses")}

    # -- additive columns (SQLite: plain add_column; PG: nullable/defaulted) --
    if "external_id" not in existing:
        op.add_column(
            "businesses",
            sa.Column("external_id", sa.String(64), nullable=True),
        )
    if "database_key" not in existing:
        op.add_column(
            "businesses",
            sa.Column("database_key", sa.String(32), nullable=False, server_default=""),
        )
    if "config_ref" not in existing:
        op.add_column(
            "businesses",
            sa.Column("config_ref", sa.String(255), nullable=True),
        )

    # -- backfill canonical registry rows (idempotent UPDATEs, no deletes) ----
    bind.execute(sa.text(
        "UPDATE businesses SET external_id = 'prime-fitness-001', "
        "database_key = 'prime_db', config_ref = 'template:fitness' "
        "WHERE slug = 'prime' AND (database_key IS NULL OR database_key = '')"
    ))
    bind.execute(sa.text(
        "UPDATE businesses SET external_id = 'nest-library-001', "
        "database_key = 'nest_db', config_ref = 'template:self_study_center' "
        "WHERE slug = 'nest' AND (database_key IS NULL OR database_key = '')"
    ))
    # Normalize any legacy NULL database_key to '' (fail-closed sentinel).
    if dialect == "postgresql":
        bind.execute(sa.text(
            "UPDATE businesses SET database_key = '' WHERE database_key IS NULL"
        ))

    # -- unique index on external_id ------------------------------------------
    indexes = {ix["name"] for ix in inspector.get_indexes("businesses")}
    if "uq_businesses_external_id" not in indexes:
        op.create_index(
            "uq_businesses_external_id", "businesses", ["external_id"], unique=True
        )


def downgrade() -> None:
    op.drop_index("uq_businesses_external_id", table_name="businesses")
    op.drop_column("businesses", "config_ref")
    op.drop_column("businesses", "database_key")
    op.drop_column("businesses", "external_id")
