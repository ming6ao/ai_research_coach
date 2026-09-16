"""Schema migration + tag round-trip + categorization tests (design doc §6-7)."""

from __future__ import annotations

import json

import pytest

import coach.db as db


def _legacy_belief_rows(conn, candidates):
    for cid, candidate, skill, mean, var, qa in candidates:
        conn.execute(
            "INSERT INTO user_skill_beliefs (id, candidate, skill, mean, variance, questions_answered, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, '2024-01-01')",
            (cid, candidate, skill, mean, var, qa),
        )


def test_legacy_beliefs_migrate_to_level_key(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "migrate.db")
    conn = db.sqlite_conn()
    conn.executescript(
        """
        CREATE TABLE user_skill_beliefs (
            id TEXT PRIMARY KEY,
            candidate TEXT NOT NULL,
            skill TEXT,
            mean REAL,
            variance REAL,
            questions_answered INTEGER DEFAULT 0,
            updated_at TEXT
        );
        """
    )
    # Candidate u1: family row (python), two junk per-skill rows.
    _legacy_belief_rows(conn, [
        ("a", "u1", "python", 0.6, 0.1, 3),
        ("b", "u1", "django", 0.4, 0.2, 5),
        ("c", "u1", "unknown-skill", 0.5, 0.15, 2),
    ])
    conn.commit()

    db.create_schema()

    from coach.tasks import get_area_beliefs, get_skill_belief

    beliefs = get_area_beliefs("u1")
    # Family row survives; junk collapsed to one global/overall (most answered).
    assert ("family", "python") in beliefs
    assert ("global", "overall") in beliefs
    assert beliefs[("global", "overall")]["questions_answered"] == 5
    assert beliefs[("family", "python")]["questions_answered"] == 3
    # Scalar global lookup does not raise MultipleResultsFound.
    g = get_skill_belief("u1")
    assert g is not None and g["questions_answered"] == 5


def test_unique_index_present_and_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "migrate2.db")
    db.create_schema()
    conn = db.sqlite_conn()
    conn.execute(
        "INSERT INTO user_skill_beliefs (id, candidate, level, key, mean, variance, questions_answered, updated_at) "
        "VALUES ('a', 'c', 'global', 'overall', 0.5, 0.1, 1, '2024-01-01')"
    )
    conn.commit()
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO user_skill_beliefs (id, candidate, level, key, mean, variance, questions_answered, updated_at) "
            "VALUES ('b', 'c', 'global', 'overall', 0.6, 0.1, 2, '2024-01-01')"
        )
    from coach.tasks import get_area_beliefs

    assert len(get_area_beliefs("c")) == 1


def test_tags_round_trip_create_get_patch(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "tags.db")
    from coach.tasks import create_task, get_task, update_task

    t = create_task(
        prompt="Implement softmax.",
        tags={"primary": "softmax", "secondary": ["loss_functions"]},
        task_type="implement",
    )
    assert t["tags"] == {"primary": "activation_normalization", "secondary": ["loss_functions"]}
    assert t["task_type"] == "implement"
    got = get_task(t["id"])
    assert got["tags"] == {"primary": "activation_normalization", "secondary": ["loss_functions"]}

    updated = update_task(t["id"], tags={"primary": "cnn"}, task_type="apply")
    assert updated["tags"] == {"primary": "cnn", "secondary": []}
    assert updated["task_type"] == "apply"

    with pytest.raises(ValueError):
        update_task(t["id"], tags={"primary": "bogus"})


def test_unknown_tag_rejected_on_create_and_patch_api(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "tags_api.db")
    monkeypatch.setattr("coach.judge.LLMJudge", object)
    from backend.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    bad = client.post("/api/v1/tasks", json={"prompt": "q", "tags": {"primary": "bogus"}})
    assert bad.status_code == 422

    good = client.post("/api/v1/tasks", json={"prompt": "q", "tags": {"primary": "python"}})
    assert good.status_code == 201

    # Authenticated owner PATCH with an unknown tag is rejected (422).
    import backend.auth as auth

    user = auth.upsert_google_user("alice@x.com", "Alice")
    token = auth.create_token(user["id"])
    headers = {"Authorization": f"Bearer {token}"}
    mine = client.post(
        "/api/v1/tasks",
        json={"prompt": "mine", "tags": {"primary": "cnn"}},
        headers=headers,
    )
    assert mine.status_code == 201
    tid = mine.json()["data"]["id"]
    bad_patch = client.patch(
        f"/api/v1/tasks/{tid}", json={"tags": {"primary": "nope"}}, headers=headers
    )
    assert bad_patch.status_code == 422
    good_patch = client.patch(
        f"/api/v1/tasks/{tid}", json={"tags": {"primary": "mlp"}, "task_type": "apply"}, headers=headers
    )
    assert good_patch.status_code == 200
    assert good_patch.json()["data"]["tags"]["primary"] == "mlp"
    assert good_patch.json()["data"]["task_type"] == "apply"


def test_task_view_emits_tags_and_task_type():
    from coach.session import Session, task_view

    session = Session("c", tasks=[])
    view = task_view(
        {"id": "x", "prompt": "p", "difficulty": 2, "tags": {"primary": "cnn", "secondary": []},
         "task_type": "implement", "scaffold": "def f():\n    pass\n"},
        session,
    )
    assert view["tags"]["primary"] == "cnn"
    assert view["task_type"] == "implement"


def test_categorize_fallback_without_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from coach.task_decomposer import TaskDecomposer

    d = TaskDecomposer()
    assert d.categorize_task("Implement a hash table.") == {"primary": "python", "secondary": []}
    assert d.describe_task("anything") == ""


def test_categorize_combined_call_shape():
    """One structured call returns context_notes + validated tags."""
    from coach.task_decomposer import TaskDecomposer

    class FakeResp:
        text = json.dumps({
            "context_notes": "Softmax is a prerequisite of classification heads.",
            "primary_tag": "random forest",
            "secondary_tag": ["PCA", "bogus"],
        })

    class FakeModels:
        def generate_content(self, **kwargs):
            return FakeResp()

    class FakeClient:
        def __init__(self):
            self.models = FakeModels()

    d = TaskDecomposer(client=FakeClient())
    out = d.describe_and_categorize("classify stuff")
    assert out["context_notes"].startswith("Softmax")
    assert out["tags"]["primary"] == "trees_ensembles"
    assert out["tags"]["secondary"] == ["dimensionality_reduction"]  # bogus dropped


def test_generated_task_inherits_root_tags():
    from coach.task_decomposer import TaskDecomposer

    task = TaskDecomposer._build(
        "remed_x", 2, "Implement drill.", "gap", "def f():\n    pass\n",
        kind="remediate", tags={"primary": "backprop", "secondary": ["mlp"]},
    )
    assert task["tags"] == {"primary": "backprop", "secondary": ["mlp"]}


def test_build_carries_context_notes():
    from coach.task_decomposer import TaskDecomposer

    task = TaskDecomposer._build(
        "remed_x", 2, "Implement drill.", "gap", "def f():\n    pass\n",
        kind="remediate",
        context_notes="Batching is a prerequisite of SGD, which is often confused with full-batch descent.",
    )
    assert task["context_notes"].startswith("Batching")
    assert "hints" not in task


def test_build_defaults_to_empty_notes():
    from coach.task_decomposer import TaskDecomposer

    task = TaskDecomposer._build("remed_x", 2, "Implement drill.", "gap")
    assert task["context_notes"] == ""
    assert "hints" not in task


def test_task_type_validated():
    from coach.tasks import create_task

    with pytest.raises(ValueError):
        create_task(prompt="x", task_type="bogus")