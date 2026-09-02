"""Alembic migration applies cleanly and produces the expected schema."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parent.parent.parent / "core" / "learning_partner"


def _config(db_path: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(ROOT))
    return cfg


def test_upgrade_to_head(tmp_path):
    db = tmp_path / "knowledge_graph.db"
    command.upgrade(_config(db), "head")

    engine = create_engine(f"sqlite:///{db}")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert {
        "knowledge_nodes", "knowledge_edges",
        "learners", "learner_knowledge_states", "evidence",
        "assessment_tasks", "assessment_targets",
        "learner_state_updates", "learner_misconceptions",
        "misconception_evidence", "learner_frontier",
    } <= tables

    node_columns = {c["name"] for c in insp.get_columns("knowledge_nodes")}
    assert {
        "id", "type", "slug", "name", "description", "metadata",
        "version", "status", "created_at", "updated_at",
    } <= node_columns

    edge_columns = {c["name"] for c in insp.get_columns("knowledge_edges")}
    assert {
        "id", "source_node_id", "target_node_id", "edge_type",
        "weight", "metadata", "created_at",
    } <= edge_columns

    learner_columns = {c["name"] for c in insp.get_columns("learners")}
    assert {"id", "metadata", "created_at", "updated_at"} <= learner_columns

    state_columns = {c["name"] for c in insp.get_columns("learner_knowledge_states")}
    assert {
        "id", "learner_id", "node_id", "mastery", "uncertainty",
        "conceptual", "procedural", "implementation", "transfer",
        "fluency", "self_confidence", "reasoning", "evidence_count",
        "last_assessed_at", "last_decay_at", "status", "metadata",
        "created_at", "updated_at",
    } <= state_columns

    evidence_columns = {c["name"] for c in insp.get_columns("evidence")}
    assert {
        "id", "learner_id", "session_id", "interaction_id", "assessment_task_id",
        "node_id", "evidence_type", "observation_status", "correctness",
        "reasoning_quality", "independence", "confidence", "observed_behavior",
        "assessor_explanation", "assessment_payload", "created_at",
    } <= evidence_columns

    task_columns = {c["name"] for c in insp.get_columns("assessment_tasks")}
    assert {
        "id", "task_type", "title", "prompt", "difficulty",
        "metadata", "created_at", "updated_at",
    } <= task_columns

    target_columns = {c["name"] for c in insp.get_columns("assessment_targets")}
    assert {
        "id", "task_id", "node_id", "target_role",
        "expected_signal_strength", "metadata", "created_at", "updated_at",
    } <= target_columns

    update_columns = {c["name"] for c in insp.get_columns("learner_state_updates")}
    assert {
        "id", "learner_id", "node_id", "evidence_id",
        "previous_mastery", "new_mastery", "previous_uncertainty",
        "new_uncertainty", "update_reason", "created_at",
    } <= update_columns

    mc_columns = {c["name"] for c in insp.get_columns("learner_misconceptions")}
    assert {
        "id", "learner_id", "misconception_node_id", "confidence", "status",
        "first_detected_at", "last_observed_at", "resolved_at", "notes",
        "metadata",
    } <= mc_columns

    frontier_columns = {c["name"] for c in insp.get_columns("learner_frontier")}
    assert {
        "id", "learner_id", "node_id", "priority", "reason",
        "source_node_id", "status", "created_at", "updated_at",
    } <= frontier_columns

    engine.dispose()


def test_downgrade_removes_tables(tmp_path):
    db = tmp_path / "knowledge_graph.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(f"sqlite:///{db}")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "knowledge_nodes" not in tables
    assert "knowledge_edges" not in tables
    assert "learners" not in tables
    assert "learner_knowledge_states" not in tables
    assert "evidence" not in tables
    assert "assessment_tasks" not in tables
    assert "assessment_targets" not in tables
    assert "learner_state_updates" not in tables
    assert "learner_misconceptions" not in tables
    assert "misconception_evidence" not in tables
    assert "learner_frontier" not in tables
    engine.dispose()