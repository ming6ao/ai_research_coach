import os
import re
import sys
from pathlib import Path

# Ensure project root is importable
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from google.adk.agents.llm_agent import Agent
from google.adk.models import Gemini
from google.adk.tools import ToolContext

from core.config import CONV_MODEL, http_retry_options
from core.session import Session, SkillState
from core.picker import next_task as next_task_bank
from core.score import bayesian_update, effective_score, measurement_variance
from core.hints import select_hints, hint_penalty, next_hidden_hint

from core.report import build_report
from core.storage import save_assessment, list_assessments
from evaluators.judge import LLMJudge


def start_assessment(candidate_name: str, tool_context: ToolContext) -> dict:
    """Begin an evaluation for a candidate. Returns the first task.

    All candidates are assessed against the same unified skill tree and task
    bank. Idempotent: if a session already exists for the candidate, it resumes
    it instead of starting over.
    """
    existing = tool_context.state.get("session")
    if existing and existing.get("candidate") == candidate_name:
        session = Session.from_dict(existing)
        task = next_task_bank(session)
        return {
            "message": f"Resumed existing assessment for {session.candidate}.",
            "total_tasks": len(session.tasks),
            "completed": session.index,
            "next_task": _task_view(task, session) if task else None,
        }
    session = Session(candidate_name)
    tool_context.state["session"] = session.to_dict()
    task = next_task_bank(session)

    # Bootstrap the learning-partner MVP graph from the first task.
    try:
        from core.learner_bridge import LearnerBridge

        bridge = LearnerBridge()
        bridge.ensure_learner(candidate_name)
        if task is not None:
            bridge.bootstrap_task(task)
    except Exception:
        pass  # MVP integration must never break the agent.

    return {
        "message": f"Assessment started for {session.candidate}.",
        "total_tasks": len(session.tasks),
        "first_task": _task_view(task, session),
    }


def submit_answer(task_id: str, answer: str, hints_used: list = None, tool_context: ToolContext = None) -> dict:
    """Submit an answer for the current task. Returns the score and the next task (or none if finished).

    `hints_used` is an optional list of hint ids the candidate viewed/requested for this task;
    those hints reduce the effective mastery reflected in the skill score. Any hints requested
    via the `request_hint` tool are included automatically.

    Idempotent: if the task already has a recorded result, the stored result is returned without re-evaluating.
    """
    if "session" not in tool_context.state:
        return {"error": "No active assessment. Call start_assessment first."}
    session = Session.from_dict(tool_context.state["session"])
    task = next((t for t in session.tasks if t["id"] == task_id), None)
    if task is None:
        return {"error": f"Task {task_id} not found in this assessment."}
    existing = next((r for r in session.results if r.task_id == task_id), None)
    if existing is not None:
        nxt = next_task_bank(session)
        return {
            "result": existing.to_dict(),
            "coach": existing.coach,
            "next_task": _task_view(nxt, session) if nxt else None,
            "remaining": len(session.tasks) - session.index,
            "note": "Answer was already recorded; returning the stored result.",
        }
    result, coach = LLMJudge().evaluate(task, answer)

    # Merge hints requested through the tool with any passed explicitly.
    requested = session.viewed_hints.get(task_id, [])
    viewed = list(dict.fromkeys(list(hints_used or []) + requested))

    skill_id = task["skill"]
    state = session.get_skill_state(skill_id)

    # Hint-adjusted mastery: a correct answer solved with many hints counts for less.
    penalty = hint_penalty(task, viewed)
    observation = effective_score(result.fraction, penalty)
    obs_variance = measurement_variance(task.get("difficulty", 1), state.score)
    new_score, new_variance = bayesian_update(state.score, state.variance, observation, obs_variance)

    session.skill_states[skill_id] = SkillState(
        score=new_score,
        variance=new_variance,
        questions_answered=state.questions_answered + 1,
        evidence=state.evidence + [result.rationale],
        hints_used=state.hints_used + viewed,
    )

    # Track asked question and store result
    session.asked_task_ids.add(task_id)
    session.results.append(result)
    session.index += 1

    # Feed the judge result into the learning-partner MVP.
    try:
        from core.learner_bridge import LearnerBridge

        learner_update = LearnerBridge().record_submission(
            session.candidate, task, result, coach, viewed_hints=viewed
        )
    except Exception:
        learner_update = None

    # Iterative remediation: if the learner model still has an actionable gap,
    # generate a simpler task for the highest-information-gain node and make it
    # the next question (overriding the bank picker).
    next_task = None
    if learner_update is not None:
        from core.learner_bridge import LearnerBridge
        from core.remediation import plan_remediation

        snapshot = None
        try:
            snapshot = LearnerBridge().learner_snapshot(session.candidate)
        except Exception:
            snapshot = None

        generated = plan_remediation(
            session, task, result, learner_update, snapshot or {}
        )
        if generated is not None:
            # A generated task persists in the session and is presented next.
            next_task = _task_view(generated, session)

    if next_task is None:
        nxt = next_task_bank(session)
        next_task = _task_view(nxt, session) if nxt else None

    # Save updated session (may include newly generated tasks).
    tool_context.state["session"] = session.to_dict()

    return {
        "result": result.to_dict(),
        "feedback": coach.feedback,
        "coach": coach.to_dict(),
        "next_task": next_task,
        "remaining": len(session.tasks) - session.index,
        "skill_update": {
            "skill": skill_id,
            "new_score": new_score,
            "new_confidence": session.get_skill_state(skill_id).confidence,
            "hints_used": viewed,
        },
        "learner_update": learner_update,
    }


def request_hint(task_id: str, tool_context: ToolContext) -> dict:
    """Reveal the next hidden hint for the current task (in the chat flow).

    Requested hints are recorded against the session and automatically counted
    when the answer is submitted, reducing the effective mastery for the task.
    """
    if "session" not in tool_context.state:
        return {"error": "No active assessment. Call start_assessment first."}
    session = Session.from_dict(tool_context.state["session"])
    task = next((t for t in session.tasks if t["id"] == task_id), None)
    if task is None:
        return {"error": f"Task {task_id} not found in this assessment."}
    ability = session.get_skill_state(task["skill"]).score
    viewed = session.viewed_hints.get(task_id, [])
    hint = next_hidden_hint(task, viewed, ability)
    if hint is None:
        return {"task_id": task_id, "hint": None, "message": "No more hints available for this task."}
    session.viewed_hints.setdefault(task_id, []).append(hint["id"])
    tool_context.state["session"] = session.to_dict()
    return {
        "task_id": task_id,
        "hint": {"id": hint["id"], "text": hint["text"], "weight": hint.get("weight", 0.15)},
        "remaining": len(task.get("hints", [])) - len(viewed) - 1,
    }


def get_report(tool_context: ToolContext) -> dict:
    """Produce the final skills profile and readiness verdict for the candidate, and persist it."""
    if "session" not in tool_context.state:
        return {"error": "No active assessment. Call start_assessment first."}
    session = Session.from_dict(tool_context.state["session"])
    report = build_report(session)
    report["assessment_id"] = save_assessment(session, report)
    return report


def get_history(limit: int = 20, tool_context: ToolContext = None) -> dict:
    """Return recently finished assessments stored in the local database."""
    return {"assessments": list_assessments(limit)}


def _build_code_stub(task: dict):
    """Build an editor scaffold for a code task.

    Scaffold-mode tasks already carry a `scaffold`. For function-mode tasks
    (no scaffold) we generate a stub from the signature mentioned in the prompt
    so the coding area is pre-filled instead of blank.
    """
    if task.get("scaffold"):
        return task["scaffold"]
    m = re.search(r"def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", task.get("prompt", ""))
    if m:
        name, params = m.group(1), m.group(2)
        return f"def {name}({params}):\n    # TODO: implement {name}\n    pass\n"
    return None


def _task_view(task: dict, session: Session) -> dict:
    if task is None:
        return None
    ability = session.get_skill_state(task["skill"]).score
    view = {
        "id": task["id"],
        "skill": task["skill"],
        "type": "code",
        "prompt": task["prompt"],
        "difficulty": task.get("difficulty", 1),
        "scaffold": _build_code_stub(task),
        "hints": select_hints(task, ability),
    }
    if task.get("generated"):
        view["remediation"] = {"node_slug": task.get("mvp_target_slug")}
    return view


root_agent = Agent(
    model=Gemini(model=CONV_MODEL, retry_options=http_retry_options()),
    name="ai_research_coach",
    description="Evaluates a candidate's AI/ML understanding and coding skills across a unified skill tree.",
    instruction=(
        "You are an evaluation coach. To assess a candidate, call start_assessment with their name. "
        "All candidates are evaluated identically against the same skill tree. "
        "Present one coding task at a time from the returned 'first_task'/'next_task'. "
        "Each task includes a 'hints' list; present the pre_revealed hints (pre_revealed is true) as optional help before the candidate "
        "starts, and offer the others as requestable. If the candidate asks for help, call request_hint and show the returned hint. "
        "Collect the candidate's code solution and call submit_answer with the task id, their answer, and the list of hint ids the "
        "candidate viewed (the pre-revealed ids plus any requested via request_hint). "
        "IMPORTANT — Teaching pause: After each submit, DO NOT move on to the next task. "
        "Instead, present the response's 'coach' content in full: explain the candidate's misconception (the specific skill/knowledge gap), "
        "then walk them through the 'steps' one by one with the explanations and code examples so they arrive at the correct solution "
        "step by step. This teaching is the most important part of your job. "
        "Do not reveal or present the next task until the candidate explicitly indicates they are ready to continue; "
        "when they are, present the next task from the 'next_task' field of the response. "
        "When all tasks are done (next_task is null), call get_report and summarize the verdict and skill gaps for the candidate. "
        "Never evaluate answers yourself; always rely on the tools' results."
    ),
    tools=[start_assessment, submit_answer, request_hint, get_report, get_history],
)