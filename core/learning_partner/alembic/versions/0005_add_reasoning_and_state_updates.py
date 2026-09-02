"""add reasoning dimension and learner_state_updates table

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-31

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "learner_knowledge_states",
        sa.Column("reasoning", sa.Float(), nullable=False, server_default="0.5"),
    )

    op.create_table(
        "learner_state_updates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("previous_mastery", sa.Float(), nullable=False),
        sa.Column("new_mastery", sa.Float(), nullable=False),
        sa.Column("previous_uncertainty", sa.Float(), nullable=False),
        sa.Column("new_uncertainty", sa.Float(), nullable=False),
        sa.Column("update_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["knowledge_nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_state_updates_learner", "learner_state_updates", ["learner_id"])
    op.create_index("ix_state_updates_node", "learner_state_updates", ["node_id"])


def downgrade() -> None:
    op.drop_index("ix_state_updates_node", table_name="learner_state_updates")
    op.drop_index("ix_state_updates_learner", table_name="learner_state_updates")
    op.drop_table("learner_state_updates")
    op.drop_column("learner_knowledge_states", "reasoning")