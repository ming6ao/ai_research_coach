import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from google.adk.agents.llm_agent import Agent
from google.adk.tools import ToolContext

from core.config import MODEL
from core.session import Session
from core.picker import next_task
from core.report import build_report
from core.storage import save_assessment, list_assessments
from evaluators.registry import get_evaluator


def start_assessment(candidate_name: str, target_role: str, tool_context: ToolContext) -> dict:
    """Begin an evaluation for a candidate targeting a role ('ml_researcher' or 'ml_infra_engineer'). Returns the first task."""
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
    """Submit an answer for the current task. Returns the score and the next task (or none if finished)."""
    if "session" not in tool_context.state:
        return {"error": "No active assessment. Call start_assessment first."}
    session = Session.from_dict(tool_context.state["session"])
    task = next((t for t in session.tasks if t["id"] == task_id), None)
    if task is None:
        return {"error": f"Task {task_id} not found in this assessment."}
    result = get_evaluator(task["type"]).evaluate(task, answer)
    session.results.append(result)
    session.index += 1
    tool_context.state["session"] = session.to_dict()
    nxt = next_task(session)
    return {
        "result": result.to_dict(),
        "next_task": _task_view(nxt) if nxt else None,
        "remaining": len(session.tasks) - session.index,
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
    }
    if task["type"] == "mcq":
        view["options"] = task.get("options", [])
    return view


root_agent = Agent(
    model=MODEL,
    name="ai_research_coach",
    description="Evaluates a candidate's AI/ML understanding and coding skills for ML Researcher or ML Infra Engineer roles.",
    instruction=(
        "You are an evaluation coach. To assess a candidate, call start_assessment with their name and target role "
        "('ml_researcher' or 'ml_infra_engineer'). Present one task at a time from the returned 'first_task'/'next_task'. "
        "For mcq tasks show the options and collect the letter; for open/code tasks collect the free-text answer. "
        "Call submit_answer with the task id and the candidate's answer, then present the next task returned. "
        "When all tasks are done (next_task is null), call get_report and summarize the verdict and skill gaps for the candidate. "
        "Never evaluate answers yourself; always rely on the tools' results."
    ),
    tools=[start_assessment, submit_answer, get_report, get_history],
)
