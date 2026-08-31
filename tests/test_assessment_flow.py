"""End-to-end assessment flow test with a fake judge.

Verifies that viewing hints reduces the effective mastery for a task even when
the submitted code is perfect.
"""

from evaluators.base import EvaluationResult, CoachContent, CoachStep
import app.agent as agent


class FakeJudge:
    """Judge that always awards full marks with a canned rationale."""

    def evaluate(self, task, answer):
        max_score = task.get("max_score", 5)
        coach = CoachContent(
            feedback="Great job!",
            misconception="You had no misconception; the solution is sound.",
            steps=[CoachStep("Confirm the approach", "The implementation is correct.", None)],
        )
        result = EvaluationResult(
            task["id"], task["skill"], max_score, max_score, "Perfect.", coach.to_dict()
        )
        return result, coach


class FakeToolContext:
    def __init__(self):
        self.state = {}


def start_session(monkeypatch):
    monkeypatch.setattr(agent, "LLMJudge", FakeJudge)
    ctx = FakeToolContext()
    started = agent.start_assessment("candidate", ctx)
    assert "error" not in started
    return ctx, started


def test_hints_reduce_mastery_for_perfect_code(monkeypatch):
    ctx, started = start_session(monkeypatch)
    task = started["first_task"]
    assert task is not None
    assert task["hints"], "task should carry hints"

    no_hints = agent.submit_answer(task["id"], "def f(): pass", hints_used=[], tool_context=ctx)
    assert "error" not in no_hints
    score_without_hints = no_hints["skill_update"]["new_score"]

    ctx2, started2 = start_session(monkeypatch)
    task2 = started2["first_task"]
    all_hint_ids = [h["id"] for h in task2["hints"]]
    with_hints = agent.submit_answer(task2["id"], "def f(): pass", hints_used=all_hint_ids, tool_context=ctx2)
    assert "error" not in with_hints
    score_with_hints = with_hints["skill_update"]["new_score"]

    assert score_with_hints < score_without_hints


def test_task_view_reveals_hints_based_on_ability(monkeypatch):
    ctx, started = start_session(monkeypatch)
    task = started["first_task"]
    # At initial ability (0.5) the gentler hints (threshold 0.65) are pre-revealed.
    pre = [h for h in task["hints"] if h["pre_revealed"]]
    assert pre, "at least the gentlest hint should be pre-revealed initially"


def test_request_hint_records_against_session(monkeypatch):
    ctx, started = start_session(monkeypatch)
    task = started["first_task"]
    first = task["hints"][0]
    if first["pre_revealed"]:
        first = next(h for h in task["hints"] if not h["pre_revealed"])

    requested = agent.request_hint(task["id"], ctx)
    assert "error" not in requested
    assert requested["hint"]["id"] == first["id"]

    # The requested hint is auto-counted even if the caller omits hints_used.
    submitted = agent.submit_answer(task["id"], "code", tool_context=ctx)
    assert submitted["skill_update"]["hints_used"] == [first["id"]]


def test_submit_idempotent(monkeypatch):
    ctx, started = start_session(monkeypatch)
    task = started["first_task"]
    first = agent.submit_answer(task["id"], "code", tool_context=ctx)
    second = agent.submit_answer(task["id"], "code", tool_context=ctx)
    assert second["note"] == "Answer was already recorded; returning the stored result."
    assert second["result"]["task_id"] == first["result"]["task_id"]


def test_submit_returns_coaching_and_next_task(monkeypatch):
    ctx, started = start_session(monkeypatch)
    task = started["first_task"]
    resp = agent.submit_answer(task["id"], "def f(): pass", tool_context=ctx)
    assert "error" not in resp
    assert resp["coach"]["misconception"], "coach should identify a gap/misconception"
    assert resp["coach"]["steps"], "coach should provide step-by-step guidance"
    assert resp["coach"]["steps"][0]["title"]
    assert "next_task" in resp, "the picked task is still returned (gated by the UI)"
    assert resp["feedback"] == "Great job!"


def test_stored_coach_returned_on_resubmit(monkeypatch):
    ctx, started = start_session(monkeypatch)
    task = started["first_task"]
    first = agent.submit_answer(task["id"], "code", tool_context=ctx)
    second = agent.submit_answer(task["id"], "code", tool_context=ctx)
    assert second["coach"] == first["coach"]