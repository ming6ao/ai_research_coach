"""Curated seed follow-up links: seeding + next-task selection.

Follow-ups are pre-authored pointers (``tasks.followups``) to related seeds.
After a submission ``pick_next_task`` prefers the first unasked curated
follow-up; the LLM remediation loop is the fallback once they run out.
"""

from __future__ import annotations

import coach.db as db
from coach.seed_bank import seed_question_bank
from coach.selection import _curated_followup, pick_next_task
from coach.session import Session


def _seeded_session(tmp_path, monkeypatch, candidate="alice@example.com"):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "curated.db")
    seed_question_bank()
    from coach.tasks import list_visible_tasks

    tasks = [t for t in list_visible_tasks("system") if t["source"] == "seed"]
    return Session(candidate=candidate, tasks=tasks)


def _by_slug(tasks, slug):
    return next(t for t in tasks if t["id"] == f"seed_{slug}")


class TestSelection:
    def _submission(self, task):
        return {"task": task, "result": None, "coach": None}

    def test_curated_followup_after_answer(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        session = _seeded_session(tmp_path, monkeypatch)
        softmax = _by_slug(session.tasks, "softmax")
        picked = pick_next_task(session.candidate, session, last_submission=self._submission(softmax))
        assert picked is not None
        assert picked["id"] == "seed_backprop_mlp"

    def test_curated_followup_skips_already_asked(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        session = _seeded_session(tmp_path, monkeypatch)
        softmax = _by_slug(session.tasks, "softmax")
        session.asked_task_ids.add("seed_backprop_mlp")
        picked = pick_next_task(session.candidate, session, last_submission=self._submission(softmax))
        assert picked is not None
        assert picked["id"] == "seed_attention"

    def test_falls_back_to_bank_when_all_followups_asked(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        session = _seeded_session(tmp_path, monkeypatch)
        softmax = _by_slug(session.tasks, "softmax")
        for link in softmax["followups"]:
            session.asked_task_ids.add(link["task_id"])
        # All curated targets used up; LLM remediation fails hermetically, so
        # the session falls through to the EIG bank picker.
        picked = pick_next_task(session.candidate, session, last_submission=self._submission(softmax))
        assert picked is not None
        assert picked["id"] not in session.asked_task_ids

    def test_curated_helper_first_unasked(self):
        anchor = {"id": "seed_a", "followups": [
            {"task_id": "seed_b", "kind": "sibling"},
            {"task_id": "seed_c", "kind": "sibling"},
        ]}
        session = Session(candidate="x")
        session.tasks = [anchor, {"id": "seed_b"}, {"id": "seed_c"}]
        assert _curated_followup(session, anchor)["id"] == "seed_b"
        session.asked_task_ids.add("seed_b")
        assert _curated_followup(session, anchor)["id"] == "seed_c"
        session.asked_task_ids.add("seed_c")
        assert _curated_followup(session, anchor) is None

    def test_curated_helper_ignores_unknown_targets(self):
        anchor = {"id": "seed_a", "followups": [
            {"task_id": "seed_missing", "kind": "sibling"},
            {"task_id": "seed_b", "kind": "sibling"},
        ]}
        session = Session(candidate="x")
        session.tasks = [anchor, {"id": "seed_b"}]
        assert _curated_followup(session, anchor)["id"] == "seed_b"

    def test_generated_task_has_no_curated_followup(self):
        generated = {"id": "remed_x", "generated": True, "prompt": "drill", "max_score": 5}
        session = Session(candidate="x")
        session.tasks = [generated]
        assert _curated_followup(session, generated) is None