from core.config import MODEL
from google import genai


def _client():
    return genai.Client(api_key=__import__("os").getenv("GOOGLE_API_KEY"))


def score_open(prompt: str, answer: str, rubric: str, max_score: int):
    client = _client()
    system = (
        f"You are a strict evaluator. Score the candidate answer from 0 to {max_score} "
        "based on correctness, completeness, and the rubric. "
        'Respond ONLY with JSON of the form {"score": <int>, "rationale": "<short>"}.'
    )
    user = f"TASK: {prompt}\nRUBRIC: {rubric}\nANSWER: {answer}"

    resp = client.models.generate_content(
        model=MODEL,
        contents=user,
        config={"system_instruction": system},
    )
    text = resp.text.strip().strip("`").replace("json", "", 1).strip()
    try:
        data = __import__("json").loads(text)
        score = int(data.get("score", 0))
        score = max(0, min(max_score, score))
        return score, data.get("rationale", "")
    except Exception:
        return 0, f"Judge parse failure: {text[:200]}"
