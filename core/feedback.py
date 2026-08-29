"""Generate learning feedback after each answer.

Uses LLM to explain why an answer was correct/incorrect and provide educational context.
"""

import json
import os

from google import genai
from google.genai import types

from core.config import MODEL, http_retry_options


class FeedbackError(Exception):
    """Raised when feedback generation fails."""
    pass


def _client():
    return genai.Client(
        api_key=os.getenv("GOOGLE_API_KEY"),
        http_options=types.HttpOptions(retry_options=http_retry_options()),
    )


def generate_feedback(
    task: dict,
    user_answer: str,
    evaluation_result: dict,
) -> str:
    """Generate learning feedback for the user.

    Args:
        task: The original task/question
        user_answer: What the user answered
        evaluation_result: The evaluation result with score and rationale

    Returns:
        A feedback string explaining the answer and providing learning context
    """
    client = _client()

    task_type = task.get("type", "unknown")
    question = task.get("prompt", "")
    correct_answer = task.get("answer", "")
    rubric = task.get("rubric", "")
    score = evaluation_result.get("score", 0)
    max_score = evaluation_result.get("max_score", 1)
    rationale = evaluation_result.get("rationale", "")

    if task_type == "mcq":
        system = (
            "You are a helpful ML tutor. Explain why the correct answer is correct "
            "and why the user's answer was wrong (if applicable). "
            "Be concise but educational. Focus on the key concept being tested."
        )
        user = (
            f"Question: {question}\n"
            f"User's answer: {user_answer}\n"
            f"Correct answer: {correct_answer}\n"
            f"Score: {score}/{max_score}"
        )
    elif task_type == "open":
        system = (
            "You are a helpful ML tutor. Provide a model answer or key concepts "
            "that should have been included. Compare with the user's answer "
            "to highlight what was correct and what was missing. Be concise but educational."
        )
        user = (
            f"Question: {question}\n"
            f"Rubric: {rubric}\n"
            f"User's answer: {user_answer}\n"
            f"Evaluation: {rationale}\n"
            f"Score: {score}/{max_score}"
        )
    elif task_type == "code":
        system = (
            "You are a helpful ML tutor. Explain what went wrong with the code "
            "and how to fix it. If all tests passed, explain why the solution works. "
            "Focus on the key concept being tested. Be concise but educational."
        )
        user = (
            f"Task: {question}\n"
            f"User's code: {user_answer}\n"
            f"Test results: {rationale}\n"
            f"Score: {score}/{max_score}"
        )
    else:
        system = "You are a helpful ML tutor. Provide brief feedback on the answer."
        user = f"Question: {question}\nAnswer: {user_answer}\nScore: {score}/{max_score}"

    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=user,
            config={"system_instruction": system},
        )
        return resp.text.strip()
    except Exception as e:
        # Fallback: return basic feedback without LLM
        if score == max_score:
            return "Correct! Well done."
        elif score > 0:
            return f"Partial credit. {rationale}"
        else:
            return f"Incorrect. {rationale}"
