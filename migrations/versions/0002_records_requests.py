"""records_requests table (M13)

Revision ID: 0002_records_requests
Revises: 0001_initial
Create Date: 2026-02-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_records_requests"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "records_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("dataset_id", sa.String(), nullable=False),
        sa.Column("parcel_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("expected_by", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("contact", sa.String(), nullable=True),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("documents", sa.JSON(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
    )
    op.create_index("ix_rr_job", "records_requests", ["job_id"])


def downgrade() -> None:
    op.drop_table("records_requests")
