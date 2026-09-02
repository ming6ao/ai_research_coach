"""create learner frontier table

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-31

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learner_frontier",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("source_node_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["knowledge_nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("learner_id", "node_id", name="uq_learner_frontier_learner_node"),
    )
    op.create_index("ix_learner_frontier_learner", "learner_frontier", ["learner_id"])


def downgrade() -> None:
    op.drop_index("ix_learner_frontier_learner", table_name="learner_frontier")
    op.drop_table("learner_frontier")