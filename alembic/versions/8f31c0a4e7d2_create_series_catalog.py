"""create series_catalog

The discoverability half of the server. ``time_series_source`` holds
observations for sources that cannot be fetched per request; this holds
*metadata* for every series meida can serve, whichever route serves it.

Without it the two halves are asymmetric: ``timeseries_source_list`` can
enumerate the 180 stored series, but nothing can enumerate the ~2,500 Socrata
ones -- they are fetchable only if you already know their facets. The catalog
YAML that knows they exist is gitignored build output that no runtime code
reads, so on a clean checkout it does not exist at all.

Deliberately not CDC-specific: ``source`` namespaces the rows the same way it
does in ``time_series_source``, so the BIS and BLS catalogs can load into this
table later without a migration. ``retrieval`` is what makes one listing serve
both routes -- it names the tool that fetches a given row.

Revision ID: 8f31c0a4e7d2
Revises: 0d2b2b6d7904
Create Date: 2026-09-07 15:02:11.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "8f31c0a4e7d2"
down_revision: Union[str, Sequence[str], None] = "0d2b2b6d7904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "series_catalog",
        sa.Column("catalog_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        # Provider namespace: "cdc" today, "bis"/"bls" when their catalogs land.
        sa.Column("source", sa.Text(), nullable=False),
        # The catalog's own identifier, e.g.
        # "cdc/alcohol_binge/hksd-2xuw/state=ak/race=aian/age_adjusted".
        sa.Column("series_id", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text(), nullable=True),
        sa.Column("concept", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        # LLM-generated; shared across a bucket of series that differ only by
        # facet value, so it is not a discriminator on its own.
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("units", sa.Text(), nullable=True),
        sa.Column("frequency", sa.Text(), nullable=True),
        sa.Column("provisional", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        # The facet values that pick this series out of its dataset. These are
        # the same keys cdc_series_data takes as arguments, so a row read here
        # can be passed straight back in.
        sa.Column("facets", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # Which tool serves this row: {"tool": "cdc_series_data", ...} for the
        # live Socrata route, {"tool": "timeseries_source_data", "source": ...,
        # "native_id": ...} for the stored one.
        sa.Column("retrieval", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("observation_start", sa.Date(), nullable=True),
        sa.Column("observation_end", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("source", "series_id", name="uq_sc_source_series"),
    )
    op.create_index("idx_sc_source", "series_catalog", ["source"])
    op.create_index("idx_sc_concept", "series_catalog", ["concept"])
    op.create_index("idx_sc_dataset", "series_catalog", ["dataset_id"])
    op.create_index("idx_sc_active", "series_catalog", ["is_active"])
    # Containment queries -- "every series with state=TX" -- are the main
    # search path, and JSONB needs GIN for @> to use an index.
    op.create_index("idx_sc_facets", "series_catalog", ["facets"],
                    postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("idx_sc_facets", table_name="series_catalog")
    op.drop_index("idx_sc_active", table_name="series_catalog")
    op.drop_index("idx_sc_dataset", table_name="series_catalog")
    op.drop_index("idx_sc_concept", table_name="series_catalog")
    op.drop_index("idx_sc_source", table_name="series_catalog")
    op.drop_table("series_catalog")
