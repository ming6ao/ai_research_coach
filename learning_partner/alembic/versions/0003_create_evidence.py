"""create evidence table

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-31

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("interaction_id", sa.String(length=36), nullable=True),
        sa.Column("assessment_task_id", sa.String(length=36), nullable=True),
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("observation_status", sa.String(length=32), nullable=False),
        sa.Column("correctness", sa.Float(), nullable=True),
        sa.Column("reasoning_quality", sa.Float(), nullable=True),
        sa.Column("independence", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("observed_behavior", sa.Text(), nullable=True),
        sa.Column("assessor_explanation", sa.Text(), nullable=True),
        sa.Column("assessment_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["knowledge_nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_created_at", "evidence", ["created_at"])
    op.create_index("ix_evidence_interaction", "evidence", ["interaction_id"])
    op.create_index("ix_evidence_learner", "evidence", ["learner_id"])
    op.create_index("ix_evidence_node", "evidence", ["node_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_node", table_name="evidence")
    op.drop_index("ix_evidence_learner", table_name="evidence")
    op.drop_index("ix_evidence_interaction", table_name="evidence")
    op.drop_index("ix_evidence_created_at", table_name="evidence")
    op.drop_table("evidence")