"""initial schema — jobs, audit_events, evidence_artifacts (M10)

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("registry_version", sa.String(), nullable=False),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("profile_version", sa.String(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
    )
    op.create_index("ix_jobs_account_id", "jobs", ["account_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("registry_version", sa.String(), nullable=False),
        sa.Column("profile", sa.String(), nullable=True),
        sa.Column("profile_version", sa.String(), nullable=True),
        sa.Column("connector_versions", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_audit_job", "audit_events", ["job_id"])
    op.create_index("ix_audit_account", "audit_events", ["account_id"])

    op.create_table(
        "evidence_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("dataset_id", sa.String(), nullable=False),
        sa.Column("authority_id", sa.String(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(), nullable=True),
        sa.Column("page", sa.JSON(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
    )
    op.create_index("ix_evidence_job", "evidence_artifacts", ["job_id"])


def downgrade() -> None:
    op.drop_table("evidence_artifacts")
    op.drop_table("audit_events")
    op.drop_table("jobs")
