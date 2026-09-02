"""create knowledge graph tables

Revision ID: 0001
Revises:
Create Date: 2026-08-31

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_nodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_knowledge_nodes_slug"),
    )

    op.create_table(
        "knowledge_edges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_node_id", sa.String(length=36), nullable=False),
        sa.Column("target_node_id", sa.String(length=36), nullable=False),
        sa.Column("edge_type", sa.String(length=64), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_node_id"], ["knowledge_nodes.id"]),
        sa.ForeignKeyConstraint(["target_node_id"], ["knowledge_nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_node_id",
            "target_node_id",
            "edge_type",
            name="uq_knowledge_edges_source_target_type",
        ),
    )
    op.create_index("ix_knowledge_edges_source", "knowledge_edges", ["source_node_id"])
    op.create_index("ix_knowledge_edges_target", "knowledge_edges", ["target_node_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_edges_target", table_name="knowledge_edges")
    op.drop_index("ix_knowledge_edges_source", table_name="knowledge_edges")
    op.drop_table("knowledge_edges")
    op.drop_table("knowledge_nodes")