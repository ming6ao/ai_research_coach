"""Generate learning feedback after each code answer.

Uses LLM to explain why an answer was correct/incorrect and provide educational context.
"""

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

    question = task.get("prompt", "")
    score = evaluation_result.get("score", 0)
    max_score = evaluation_result.get("max_score", 1)
    rationale = evaluation_result.get("rationale", "")

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

    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=user,
            config={"system_instruction": system},
        )
        return resp.text.strip()
    except Exception:
        # Fallback: return basic feedback without LLM
        if score == max_score:
            return "Correct! Well done."
        elif score > 0:
            return f"Partial credit. {rationale}"
        else:
            return f"Incorrect. {rationale}"
