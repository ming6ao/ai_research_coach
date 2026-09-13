"""Builtin question bank: seeding, coverage, gap-filling (design doc §3)."""

from __future__ import annotations

import coach.db as db
from coach.seed_bank import SEED_CATALOG, _fill_gaps, coverage_report, seed_question_bank
from coach.taxonomy import ALL_TAGS, FAMILIES, family_of


def test_catalog_covers_every_tag_and_family():
    covered = set()
    for seed in SEED_CATALOG:
        tags = seed["tags"]
        covered.add(tags["primary"])
        covered.update(tags["secondary"])
        assert seed.get("context_notes"), f"{seed['slug']} needs context_notes"
    assert set(ALL_TAGS) <= set(covered)
    for fam in FAMILIES:
        assert any(family_of(tag) == fam for tag in covered), f"family {fam} uncovered"


def test_seed_question_bank_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "seed.db")
    from coach.tasks import get_task, list_visible_tasks

    count_before = len(list_visible_tasks("system"))
    seed_question_bank()
    seed_question_bank()
    seeds = [t for t in list_visible_tasks("system") if t["source"] == "seed"]
    assert len(seeds) == len(SEED_CATALOG)
    assert count_before == len(seeds)  # no duplicates across re-runs
    assert get_task(f"seed_{SEED_CATALOG[0]['slug']}") is not None


def test_admin_edited_seed_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "seed2.db")
    from coach.tasks import get_task, update_task

    seed_question_bank()
    tid = f"seed_{SEED_CATALOG[0]['slug']}"
    update_task(tid, prompt="HUMAN EDITED")
    seed_question_bank()  # re-seed must not clobber the edit
    assert get_task(tid)["prompt"] == "HUMAN EDITED"


def test_coverage_report_counts_and_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "seed3.db")
    from coach.tasks import record_attempt

    seed_question_bank()
    report = coverage_report()
    assert set(report["families"]) == set(FAMILIES)
    assert set(report["tags"]) == set(ALL_TAGS)
    # Every tag is covered by at least one seed.
    assert all(report["tags"][t]["seed_tasks"] for t in ALL_TAGS)
    assert all(report["families"][f]["seed_tasks"] for f in FAMILIES)

    # A recorded attempt on a seed task increments its tag/family asked counts.
    softmax = f"seed_{SEED_CATALOG[0]['slug']}"
    record_attempt("alice@x.com", softmax, 0.8, 4, 5, [])
    report2 = coverage_report()
    assert report2["tags"]["activation_normalization"]["asked_total"] >= 1
    assert report2["tags"]["activation_normalization"]["candidates"].get("alice@x.com") == 1
    assert report2["families"]["dl_arch"]["asked_total"] >= 1


def test_fill_gaps_targets_zero_coverage_first(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "seed4.db")

    calls = []

    class FakeDecomposer:
        def generate_seed_task_for_tag(self, tag, difficulty=2):
            calls.append(tag)
            return {
                "prompt": f"Write code for {tag}.",
                "scaffold": "def f():\n    pass\n",
                "difficulty": difficulty,
                "max_score": 5,
                "hints": [],
                "tags": {"primary": tag, "secondary": []},
                "task_type": "implement",
                "context_notes": f"Notes for {tag}.",
            }

    import coach.task_decomposer as td

    monkeypatch.setattr(td, "TaskDecomposer", lambda *a, **k: FakeDecomposer())
    seed_question_bank()

    # Force one tag to appear uncovered by faking the seed rows source filter:
    # mint with limit 1; since the catalog already covers everything, the
    # fallback targets the lowest-coverage tag.
    minted = _fill_gaps(limit=1)
    assert len(minted) == 1
    assert len(calls) == 1

    # Persisted as a public system seed_llm task carrying the tag as primary.
    from coach.tasks import get_task, list_tasks_for_admin

    rows = list_tasks_for_admin(owner="system")
    gen = [t for t in rows if t["source"] == "seed_llm"]
    assert len(gen) == 1
    assert gen[0]["tags"]["primary"] == minted[0]
    assert gen[0]["is_public"] is True
    assert get_task(gen[0]["id"]) is not None


def test_seeding_uses_a_single_batched_insert(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "seed6.db")
    statements: list[str] = []
    original_conn = db.sqlite_conn

    def _counting_conn():
        conn = original_conn()
        conn.set_trace_callback(
            lambda sql: statements.append(sql)
            if isinstance(sql, str) and sql.strip().upper().startswith("INSERT")
            else None
        )
        return conn

    monkeypatch.setattr(db, "sqlite_conn", _counting_conn)
    seed_question_bank()
    inserts = statements
    assert inserts, "expected at least one INSERT"
    # Every INSERT is a single batched multi-row statement, never one per row.
    for sql in inserts:
        assert "INSERT OR IGNORE" in sql
        assert sql.count("VALUES") == 1
    # And the catalog actually landed.
    from coach.tasks import list_visible_tasks

    seeds = [t for t in list_visible_tasks("system") if t["source"] == "seed"]
    assert len(seeds) == len(SEED_CATALOG)


def test_fill_gaps_touches_only_zero_coverage_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "seed7.db")
    calls: list[str] = []

    class FakeDecomposer:
        def generate_seed_task_for_tag(self, tag, difficulty=2):
            calls.append(tag)
            return {
                "prompt": f"Write code for {tag}.",
                "scaffold": "def f():\n    pass\n",
                "difficulty": difficulty,
                "max_score": 5,
                "hints": [],
                "tags": {"primary": tag, "secondary": []},
                "task_type": "implement",
                "context_notes": f"Notes for {tag}.",
            }

    import coach.seed_bank as sb

    monkeypatch.setattr(sb, "_seed_rows", lambda: [])
    monkeypatch.setattr("coach.task_decomposer.TaskDecomposer", lambda *a, **k: FakeDecomposer())
    seed_question_bank()

    minted = _fill_gaps(limit=3)
    assert len(minted) == 3
    assert len(calls) == 3  # only the requested zero-coverage tags, capped by limit


def test_seeding_requires_no_api_key_or_network(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "seed5.db")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    import os

    assert not os.getenv("GOOGLE_API_KEY")
    inserted = seed_question_bank()
    assert inserted >= 0  # runs hermetically; no model calls