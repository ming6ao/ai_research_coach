"""create assessment tasks and targets tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-31

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assessment_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.Float(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "assessment_targets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("target_role", sa.String(length=32), nullable=False),
        sa.Column("expected_signal_strength", sa.Float(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["knowledge_nodes.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["assessment_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "node_id", name="uq_assessment_targets_task_node"),
    )
    op.create_index("ix_assessment_targets_node", "assessment_targets", ["node_id"])
    op.create_index("ix_assessment_targets_task", "assessment_targets", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_assessment_targets_task", table_name="assessment_targets")
    op.drop_index("ix_assessment_targets_node", table_name="assessment_targets")
    op.drop_table("assessment_targets")
    op.drop_table("assessment_tasks")