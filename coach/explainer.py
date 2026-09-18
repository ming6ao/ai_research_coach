"""LLM helper for selection-driven explanations ("Explain this").

Given a passage a learner highlighted (plus the surrounding paragraph and the
active task/step context), returns a grounded explanation of the underlying
concept, notation, and derivation. The model is explicitly forbidden from
solving the learner's task. Mirrors ``coach.judge``/``coach.task_decomposer``:
lazily-created Gemini client with the project retry config, JSON structured
output, and a raise-on-failure contract (no templated fallback).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from google import genai
from google.genai import types

from coach.config import MODEL, http_retry_options

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert AI/ML tutor. A learner highlighted a passage while working on \
a coding task and asked for an explanation.

Return JSON with exactly three keys:
  "title": a short 3-8 word title naming the central concept.
  "explanation": markdown that (1) defines the concept and every symbol, \
(2) derives or justifies any formula step by step, (3) gives one tiny concrete \
example, and (4) states why it matters for this task family.
  "related_terms": an array of 2-5 short related concept names.

Rules:
  - Do NOT solve the learner's task, give the final answer, or write code that \
    completes their step. Explain the underlying idea only.
  - Use $...$ for inline math and $$...$$ for display math.
  - Use fenced code blocks only for small illustrative snippets.
  - Define each symbol before using it; keep notation consistent.
  - If the selection is ambiguous, explain the most likely technical meaning \
    and state the assumption you made.
  - Be concrete and specific to the highlighted text; do not pad with generalities."""

_EXPLAIN_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "title": types.Schema(type=types.Type.STRING),
        "explanation": types.Schema(type=types.Type.STRING),
        "related_terms": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
        ),
    },
    required=["title", "explanation", "related_terms"],
)


class Explainer:
    """Structured LLM explanations for a highlighted passage."""

    def __init__(self, client: Optional[genai.Client] = None, model: Optional[str] = None) -> None:
        self._client_impl = client
        self._client_cached: Optional[genai.Client] = None
        self._model = model or MODEL

    def _client(self) -> genai.Client:
        """Lazily-created shared client (see ``TaskDecomposer._client``).

        Kept in a local for the duration of the call: ``genai.Client.__del__``
        closes the shared httpx client, so a temporary would be GC'd
        mid-request.
        """
        import os

        if self._client_impl is not None:
            return self._client_impl
        if self._client_cached is None:
            self._client_cached = genai.Client(
                api_key=os.getenv("GOOGLE_API_KEY"),
                http_options=types.HttpOptions(retry_options=http_retry_options()),
            )
        return self._client_cached

    def explain(
        self,
        selection: str,
        *,
        context: str = "",
        step_prompt: str = "",
        task_notes: str = "",
        language: str = "python",
        question: str = "",
        prior_explanation: str = "",
    ) -> dict:
        """Explain ``selection`` in the active step's context.

        Returns ``{"title": str, "explanation": str, "related_terms": [str]}``.
        Raises ``RuntimeError`` when ``GOOGLE_API_KEY`` is missing or the call
        fails (including empty/invalid responses), so the route can surface a
        retryable error instead of a templated answer.
        """
        import os

        selection = (selection or "").strip()[:4000]
        if not selection:
            raise RuntimeError("explanation failed: empty selection")
        if not os.getenv("GOOGLE_API_KEY"):
            raise RuntimeError("explanation failed: missing GOOGLE_API_KEY")

        body = f"Highlighted passage:\n{selection}\n"
        if context.strip():
            body += f"\nSurrounding text:\n{context.strip()[:800]}\n"
        if step_prompt.strip():
            body += f"\nCurrent task step:\n{step_prompt.strip()[:2000]}\n"
        if task_notes.strip():
            body += f"\nTask background:\n{task_notes.strip()[:800]}\n"
        body += f"\nImplementation language: {language}\n"
        if prior_explanation.strip():
            body += (
                "\nYour previous explanation (the learner is following up):\n"
                f"{prior_explanation.strip()[:3000]}\n"
            )
        if question.strip():
            body += f"\nLearner's follow-up question:\n{question.strip()[:1000]}\n"
            body += "\nAnswer the follow-up while keeping the explanation grounded in the passage.\n"
        body += "\nReturn the explanation JSON."

        raw = ""
        try:
            client = self._client()
            resp = client.models.generate_content(
                model=self._model,
                contents=body,
                config={
                    "system_instruction": _SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "response_schema": _EXPLAIN_SCHEMA,
                },
            )
            raw = getattr(resp, "text", "") or ""
            payload = json.loads(raw)
            explanation = str(payload.get("explanation") or "").strip()
            if not explanation:
                raise ValueError(f"empty explanation in response: {raw[:1000]!r}")
            terms = payload.get("related_terms") or []
            if not isinstance(terms, list):
                terms = []
            return {
                "title": str(payload.get("title") or "").strip(),
                "explanation": explanation,
                "related_terms": [str(t).strip() for t in terms if str(t).strip()][:5],
            }
        except Exception as exc:
            logger.exception("[explain] LLM call failed (%s: %s)", type(exc).__name__, exc)
            logger.error("[explain] raw model response: %r", raw[:2000])
            raise RuntimeError(
                f"explanation failed: {type(exc).__name__}: {exc}"
            ) from exc
