"""Taxonomy migration CLI: map integrity, dry-run safety, in-place apply."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import coach.db as db
from coach.taxonomy import is_leaf
from coach.taxonomy_migration import DROP, OLD_TAG_MAP, map_tag


def _insert_task(task_id: str, tags: dict, parts: list | None = None) -> None:
    """Insert a task row directly (bypasses the new-taxonomy validation)."""
    from coach.db import create_schema, learner_session
    from coach.tasks import TaskModel

    create_schema()
    session = learner_session()
    try:
        session.add(
            TaskModel(
                id=task_id,
                owner="bank@example.com",
                prompt=f"Prompt for {task_id}",
                difficulty=2,
                max_score=5,
                parts_json=json.dumps(parts or []),
                tags_json=json.dumps(tags),
                task_type="implement",
                language="python",
                source="user",
                delivery="block",
                is_public=1,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        session.commit()
    finally:
        session.close()


def _insert_session(session_id: str, session_json: dict) -> None:
    from coach.db import create_schema, sqlite_conn

    create_schema()
    with sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO active_sessions (session_id, candidate, session_json, status, updated_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            (session_id, "candidate@x.com", json.dumps(session_json), "2024-01-01T00:00:00"),
        )
        conn.commit()


def test_map_covers_every_retired_tag_and_targets_are_leaves():
    assert len(OLD_TAG_MAP) == 46
    for old, leaf in OLD_TAG_MAP.items():
        assert leaf is None or is_leaf(leaf), f"{old} -> {leaf!r}"
    assert map_tag("attention_transformer") == "attention_variants"
    assert map_tag("kv_cache") == "kv_cache_management"
    assert map_tag("linear_regression") is DROP is None
    assert map_tag("nope") is None


def test_dry_run_mutates_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "dry.db")
    from coach.migrate import run_migration
    from coach.tasks import get_area_beliefs, get_task, save_area_belief

    _insert_task("t1", {"primary": "attention_transformer", "secondary": ["kv_cache"]})
    save_area_belief("cand@x.com", "tag", "attention_transformer", 0.6, 0.1, 2)

    report = run_migration(apply=False, mode="delete", fallback=None, drop_empty=True)
    assert report["apply"] is False
    assert "backup" not in report
    assert get_task("t1")["tags"]["primary"] == "attention_transformer"  # untouched
    assert ("tag", "attention_transformer") in get_area_beliefs("cand@x.com")


def test_apply_remaps_mappable_and_drops_classic(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "apply.db")
    from coach.migrate import run_migration
    from coach.tasks import get_task

    _insert_task("good", {"primary": "attention_transformer", "secondary": ["kv_cache"]})
    _insert_task(
        "classic",
        {"primary": "linear_regression"},
        parts=[{"key": "a", "prompt": "def a(): ...", "tags": {"primary": "linear_regression"},
                "max_score": 5, "difficulty": 2, "pass_score": 4}],
    )

    report = run_migration(apply=True, mode="delete", fallback=None, drop_empty=True)
    assert report["apply"] is True
    assert report["backup"]
    assert report["tasks"]["dropped"] == 1

    good = get_task("good")
    assert good is not None
    assert good["tags"] == {"primary": "attention_variants", "secondary": ["kv_cache_management"]}
    assert get_task("classic") is None


def test_apply_fallback_mode_retags_unmapped(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fallback.db")
    from coach.migrate import run_migration
    from coach.tasks import get_task

    _insert_task("classic", {"primary": "linear_regression"})
    run_migration(apply=True, mode="fallback", fallback="testing", drop_empty=True)
    assert get_task("classic")["tags"] == {"primary": "testing", "secondary": []}


def test_beliefs_tag_to_skill_with_collision_merge_and_family_drop(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "beliefs.db")
    from coach.migrate import run_migration
    from coach.tasks import get_area_beliefs, save_area_belief

    save_area_belief("c1", "global", "overall", 0.5, 0.1, 4)
    save_area_belief("c1", "tag", "gradient_descent_sgd", 0.6, 0.1, 3)
    save_area_belief("c1", "tag", "optimizers_adam", 0.8, 0.0, 1)
    save_area_belief("c1", "tag", "linear_regression", 0.9, 0.0, 5)  # dropped
    save_area_belief("c1", "family", "training", 0.4, 0.1, 7)  # dropped

    run_migration(apply=True, mode="delete", fallback=None, drop_empty=True)

    beliefs = get_area_beliefs("c1")
    assert ("global", "overall") in beliefs
    assert ("family", "training") not in beliefs
    assert ("skill", "linear_regression") not in beliefs
    merged = beliefs[("skill", "optimization_theory")]
    assert merged["questions_answered"] == 4
    assert merged["mean"] == pytest.approx(0.65)


def test_sessions_drop_empty_and_remap_stepful(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sessions.db")
    from coach.db import create_schema, sqlite_conn
    from coach.migrate import run_migration

    create_schema()
    stepful = {
        "session": {
            "candidate": "candidate@x.com",
            "tasks": [
                {"id": "t1", "prompt": "p", "tags": {"primary": "attention_transformer", "secondary": []}}
            ],
        }
    }
    empty = {"session": {"candidate": "candidate@x.com", "tasks": []}}
    _insert_session("stepful", stepful)
    _insert_session("empty", empty)

    from coach.steps import insert_step

    insert_step("stepful", "candidate@x.com", 0, {"id": "t1"}, "bank", "code", 5, 5, 1.0, 1.0, [],
                None, None, {}, None)

    report = run_migration(apply=True, mode="delete", fallback=None, drop_empty=True)
    assert report["sessions"]["dropped_empty"] == 1

    with sqlite_conn() as conn:
        rows = dict(conn.execute("SELECT session_id, session_json FROM active_sessions").fetchall())
    assert "empty" not in rows
    assert "stepful" in rows
    parsed = json.loads(rows["stepful"])
    tags = parsed["session"]["tasks"][0]["tags"]
    assert tags["primary"] == "attention_variants"


def test_coverage_report_counts_task_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "coverage.db")
    from coach.migrate import coverage_report

    _insert_task("cov1", {"primary": "flash_attention", "secondary": ["memory_coalescing"]})
    report = coverage_report()
    assert report["tasks"] == 1
    assert "flash_attention" in report["covered"]
    assert "memory_coalescing" in report["covered"]
    assert "kv_cache_management" in report["uncovered"]
