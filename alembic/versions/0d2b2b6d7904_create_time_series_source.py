"""create time_series_source

Revision ID: 0d2b2b6d7904
Revises: 
Create Date: 2026-09-06 12:36:27.804904

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = '0d2b2b6d7904'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "time_series_source",
        sa.Column("source_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        # Provider namespace. Distinct from Socrata's "cdc": these are the
        # file-delivered sources, whose refresh mechanics differ.
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("native_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("frequency", sa.Text(), nullable=False),
        sa.Column("units", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("observations", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # Unlike yada's cache, expiry here means "due for an update" -- when a
        # refresh should go re-run the WONDER pull or look for a new NVSR
        # volume. Reads never withhold an expired row.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ttl_days", sa.Integer(), nullable=True),
        sa.Column("observation_start", sa.Date(), nullable=True),
        sa.Column("observation_end", sa.Date(), nullable=True),
        sa.UniqueConstraint("source", "native_id", "frequency",
                            name="uq_tss_source_native_frequency"),
    )
    op.create_index("idx_tss_source", "time_series_source", ["source"])
    op.create_index("idx_tss_native_id", "time_series_source", ["native_id"])
    op.create_index("idx_tss_expires_at", "time_series_source", ["expires_at"])
    op.create_index("idx_tss_metadata_gin", "time_series_source", ["metadata"],
                    postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("idx_tss_metadata_gin", table_name="time_series_source")
    op.drop_index("idx_tss_expires_at", table_name="time_series_source")
    op.drop_index("idx_tss_native_id", table_name="time_series_source")
    op.drop_index("idx_tss_source", table_name="time_series_source")
    op.drop_table("time_series_source")
