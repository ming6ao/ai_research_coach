"""create learner model tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-31

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learners",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "learner_knowledge_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("mastery", sa.Float(), nullable=False),
        sa.Column("uncertainty", sa.Float(), nullable=False),
        sa.Column("conceptual", sa.Float(), nullable=False),
        sa.Column("procedural", sa.Float(), nullable=False),
        sa.Column("implementation", sa.Float(), nullable=False),
        sa.Column("transfer", sa.Float(), nullable=False),
        sa.Column("fluency", sa.Float(), nullable=False),
        sa.Column("self_confidence", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("last_assessed_at", sa.DateTime(), nullable=True),
        sa.Column("last_decay_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["knowledge_nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "learner_id",
            "node_id",
            name="uq_learner_knowledge_states_learner_node",
        ),
    )
    op.create_index(
        "ix_learner_knowledge_states_learner",
        "learner_knowledge_states",
        ["learner_id"],
    )
    op.create_index(
        "ix_learner_knowledge_states_node",
        "learner_knowledge_states",
        ["node_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_learner_knowledge_states_node", table_name="learner_knowledge_states"
    )
    op.drop_index(
        "ix_learner_knowledge_states_learner", table_name="learner_knowledge_states"
    )
    op.drop_table("learner_knowledge_states")
    op.drop_table("learners")