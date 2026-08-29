import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from google.adk.agents.llm_agent import Agent
from google.adk.models import Gemini
from google.adk.tools import ToolContext

from core.config import CONV_MODEL, http_retry_options
from core.session import Session
from core.picker import next_task
from core.score import update_skill_score
from core.feedback import generate_feedback
from core.report import build_report
from core.storage import save_assessment, list_assessments
from evaluators.registry import get_evaluator
from judge.llm_judge import JudgeRetryableError


def start_assessment(candidate_name: str, target_role: str, tool_context: ToolContext) -> dict:
    """Begin an evaluation for a candidate targeting a role ('ml_researcher' or 'ml_infra_engineer'). Returns the first task.

    Idempotent: if a session already exists for the same candidate and role, it resumes it instead of starting over.
    """
    existing = tool_context.state.get("session")
    if existing and existing.get("candidate") == candidate_name and existing.get("role") == target_role:
        session = Session.from_dict(existing)
        task = next_task(session)
        return {
            "message": f"Resumed existing assessment for {session.role_cfg['name']}.",
            "total_tasks": len(session.tasks),
            "completed": session.index,
            "next_task": _task_view(task) if task else None,
        }
    try:
        session = Session(candidate_name, target_role)
    except ValueError as e:
        return {"error": str(e)}
    tool_context.state["session"] = session.to_dict()
    task = next_task(session)
    return {
        "message": f"Assessment started for {session.role_cfg['name']}.",
        "total_tasks": len(session.tasks),
        "first_task": _task_view(task),
    }


def submit_answer(task_id: str, answer: str, tool_context: ToolContext) -> dict:
    """Submit an answer for the current task. Returns the score and the next task (or none if finished).

    Idempotent: if the task already has a recorded result, the stored result is returned without re-evaluating.
    If the evaluation fails transiently (e.g. judge rate limit), no result is recorded and an error is returned
    so the caller can ask the candidate to resend.
    """
    if "session" not in tool_context.state:
        return {"error": "No active assessment. Call start_assessment first."}
    session = Session.from_dict(tool_context.state["session"])
    task = next((t for t in session.tasks if t["id"] == task_id), None)
    if task is None:
        return {"error": f"Task {task_id} not found in this assessment."}
    existing = next((r for r in session.results if r.task_id == task_id), None)
    if existing is not None:
        nxt = next_task(session)
        return {
            "result": existing.to_dict(),
            "next_task": _task_view(nxt) if nxt else None,
            "remaining": len(session.tasks) - session.index,
            "note": "Answer was already recorded; returning the stored result.",
        }
    try:
        result = get_evaluator(task["type"]).evaluate(task, answer)
    except JudgeRetryableError as e:
        return {"error": f"Transient evaluation failure: {e}. Please ask the candidate to resend their answer and retry."}

    # Update skill state with the new score
    skill_id = task["skill"]
    state = session.get_skill_state(skill_id)
    normalized_score = result.fraction  # Already 0.0 - 1.0

    new_score, new_confidence = update_skill_score(
        state.score,
        state.confidence,
        normalized_score,
    )

    # Create updated skill state
    from core.session import SkillState
    session.skill_states[skill_id] = SkillState(
        score=new_score,
        confidence=new_confidence,
        questions_answered=state.questions_answered + 1,
        evidence=state.evidence + [result.rationale],
    )

    # Track asked question and store result
    session.asked_task_ids.add(task_id)
    session.results.append(result)
    session.index += 1

    # Save updated session
    tool_context.state["session"] = session.to_dict()

    # Generate learning feedback
    feedback = generate_feedback(task, answer, result.to_dict())

    nxt = next_task(session)
    return {
        "result": result.to_dict(),
        "feedback": feedback,
        "next_task": _task_view(nxt) if nxt else None,
        "remaining": len(session.tasks) - session.index,
        "skill_update": {
            "skill": skill_id,
            "new_score": new_score,
            "new_confidence": new_confidence,
        },
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


def _task_view(task: dict) -> dict:
    if task is None:
        return None
    view = {
        "id": task["id"],
        "skill": task["skill"],
        "type": task["type"],
        "prompt": task["prompt"],
        "difficulty": task.get("difficulty", 1),
        "dimension": task.get("dimension", "conceptual"),
        "scaffold": task.get("scaffold"),
    }
    if task["type"] == "mcq":
        view["options"] = task.get("options", [])
    return view


root_agent = Agent(
    model=Gemini(model=CONV_MODEL, retry_options=http_retry_options()),
    name="ai_research_coach",
    description="Evaluates a candidate's AI/ML understanding and coding skills for ML Researcher or ML Infra Engineer roles.",
    instruction=(
        "You are an evaluation coach. To assess a candidate, call start_assessment with their name and target role "
        "('ml_researcher' or 'ml_infra_engineer'). Present one task at a time from the returned 'first_task'/'next_task'. "
        "For mcq tasks show the options and collect the letter; for open/code tasks collect the free-text answer. "
        "Call submit_answer with the task id and the candidate's answer, then present the next task returned. "
        "IMPORTANT: After each answer, present the feedback from the response to help the user learn. "
        "The feedback explains why the answer was correct/incorrect and provides educational context. "
        "When all tasks are done (next_task is null), call get_report and summarize the verdict and skill gaps for the candidate. "
        "Never evaluate answers yourself; always rely on the tools' results. "
        "If a tool returns an error containing 'Transient evaluation failure', a temporary API problem occurred: "
        "do NOT invent a score. Explain the problem to the candidate, ask them to resend their last answer, "
        "then call submit_answer again with the same task id and answer."
    ),
    tools=[start_assessment, submit_answer, get_report, get_history],
)
