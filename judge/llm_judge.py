import json
import os

from google import genai
from google.genai import types

from core.config import MODEL, http_retry_options


class JudgeRetryableError(Exception):
    """Raised when the judge's model call fails transiently (rate limit / 5xx).

    The caller should NOT record a score of 0 for the answer — it should
    surface this to the user and ask them to resend the answer.
    """


def _client():
    return genai.Client(
        api_key=os.getenv("GOOGLE_API_KEY"),
        http_options=types.HttpOptions(retry_options=http_retry_options()),
    )


def score_open(prompt: str, answer: str, rubric: str, max_score: int):
    client = _client()
    system = (
        f"You are a strict evaluator. Score the candidate answer from 0 to {max_score} "
        "based on correctness, completeness, and the rubric. "
        'Respond ONLY with JSON of the form {"score": <int>, "rationale": "<short>"}.'
    )
    user = f"TASK: {prompt}\nRUBRIC: {rubric}\nANSWER: {answer}"

    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=user,
            config={"system_instruction": system},
        )
    except Exception as e:
        raise JudgeRetryableError(f"Judge model call failed: {type(e).__name__}: {e}") from e

    text = resp.text.strip().strip("`").replace("json", "", 1).strip()
    try:
        data = json.loads(text)
        score = int(data.get("score", 0))
        score = max(0, min(max_score, score))
        return score, data.get("rationale", "")
    except Exception:
        return 0, f"Judge parse failure: {text[:200]}"
