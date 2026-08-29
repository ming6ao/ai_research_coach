import json
import os

from google import genai
from google.genai import types

from core.config import MODEL, http_retry_options
from evaluators.base import EvaluationResult

_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "score": types.Schema(type=types.Type.NUMBER),
        "rationale": types.Schema(type=types.Type.STRING),
        "feedback": types.Schema(type=types.Type.STRING),
    },
    required=["score", "rationale", "feedback"],
)

_SYSTEM_PROMPT = """\
You are a strict technical judge for AI/ML coding tasks. \
Evaluate the candidate's code solution for correctness, edge-case handling, \
and clarity. Return a JSON object with three keys:

  "score": a number from 0 to {max_score} (in whole-number increments), \
where 0 is completely wrong/empty, {max_score} is correct and complete;
  "rationale": a concise explanation of strengths and weaknesses \
(this will appear in a report as evidence, so be specific but brief);
  "feedback": educational feedback for the user explaining what went wrong \
and how to fix it, or why the solution is correct. \
Use triple-backtick python fenced blocks for any corrected or exemplary code."""


class LLMJudge:
    def evaluate(self, task: dict, answer: str) -> tuple[EvaluationResult, str]:
        max_score = task.get("max_score", 5)
        prompt = task.get("prompt", "")
        client = _client()

        system = _SYSTEM_PROMPT.format(max_score=max_score)
        user = f"Task:\n{prompt}\n\nCandidate's code:\n```\n{answer}\n```"

        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=user,
                config={
                    "system_instruction": system,
                    "response_mime_type": "application/json",
                    "response_schema": _SCHEMA,
                },
            )
            payload = json.loads(resp.text)
            score = float(payload["score"])
            score = max(0.0, min(score, max_score))
            rationale = str(payload.get("rationale", ""))
            feedback = str(payload.get("feedback", ""))
            return EvaluationResult(task["id"], task["skill"], score, max_score, rationale), feedback
        except Exception:
            return (
                EvaluationResult(task["id"], task["skill"], max_score * 0.5, max_score, "Unable to evaluate"),
                "We could not evaluate your answer. Please try again.",
            )


def _client():
    return genai.Client(
        api_key=os.getenv("GOOGLE_API_KEY"),
        http_options=types.HttpOptions(retry_options=http_retry_options()),
    )
