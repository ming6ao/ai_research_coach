"""create learner misconceptions tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-31

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learner_misconceptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("misconception_node_id", sa.String(length=36), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["misconception_node_id"], ["knowledge_nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_misconceptions_learner", "learner_misconceptions", ["learner_id"])
    op.create_index("ix_misconceptions_node", "learner_misconceptions", ["misconception_node_id"])

    op.create_table(
        "misconception_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("misconception_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("relationship", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.ForeignKeyConstraint(["misconception_id"], ["learner_misconceptions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("misconception_id", "evidence_id", name="uq_misconception_evidence_pair"),
    )
    op.create_index("ix_misconception_evidence_mc", "misconception_evidence", ["misconception_id"])


def downgrade() -> None:
    op.drop_index("ix_misconception_evidence_mc", table_name="misconception_evidence")
    op.drop_table("misconception_evidence")
    op.drop_index("ix_misconceptions_node", table_name="learner_misconceptions")
    op.drop_index("ix_misconceptions_learner", table_name="learner_misconceptions")
    op.drop_table("learner_misconceptions")