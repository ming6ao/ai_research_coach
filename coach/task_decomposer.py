"""Per-task plain-English context + follow-up task generation.

The knowledge graph is gone. Each task optionally carries ``context_notes``:
2-4 plain sentences such as "A is a prerequisite of B, which is often
confused with C." Produced once by an LLM at creation time (empty string
fallback keeps startup/tests hermetic). Follow-up generation takes the
judge's free-text gap (misconception/feedback), not a node id.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from google import genai
from google.genai import types

from coach.config import MODEL, http_retry_options

_CONTEXT_SYSTEM_PROMPT = """\
You are a curriculum assistant. Given a coding task, \
describe the background knowledge in 2-4 plain English sentences. \
Name prerequisites ("X is a prerequisite of Y"), what builds on what, \
and what learners often confuse ("Y is often confused with Z"). \
Concrete, focused on THIS task only. Return plain text, no JSON, no bullets."""

_FOLLOWUP_SYSTEM_PROMPT = """\
You are a tutor for a learning system. A candidate answered the original task \
incorrectly or revealed a gap described below. Create ONE simpler coding task \
that drills directly into that gap so the candidate can rebuild the missing \
skill with a small, focused exercise.

Return JSON with exactly two keys:
  "prompt": the new, simpler coding task prompt (2-6 sentences, self-contained,
    with a clear function signature or spec). Reduce scope versus the original;
    isolate only the gap. Do not reveal the answer.
  "difficulty": an integer in [1, 5] strictly at or below the original task's
    difficulty, reflecting the reduced scope."""

_FOLLOWUP_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "prompt": types.Schema(type=types.Type.STRING),
        "difficulty": types.Schema(type=types.Type.INTEGER),
    },
    required=["prompt", "difficulty"],
)


class TaskDecomposer:
    """LLM helpers for context notes + judge-driven follow-up tasks."""

    def __init__(self, client: Optional[genai.Client] = None, model: Optional[str] = None) -> None:
        self._client_impl = client
        self._model = model or MODEL

    def _client(self) -> genai.Client:
        """Shared, lazily-created Gemini client with the project retry config."""
        import os

        return self._client_impl or genai.Client(
            api_key=os.getenv("GOOGLE_API_KEY"),
            http_options=types.HttpOptions(retry_options=http_retry_options()),
        )

    # -- plain-English context -------------------------------------------

    def describe_task(self, prompt: str) -> str:
        """Return 2-4 plain sentences of task context, or "" on any failure."""
        import os

        if not os.getenv("GOOGLE_API_KEY"):
            return ""
        try:
            resp = self._client().models.generate_content(
                model=self._model,
                contents=f"Task:\n{prompt}",
                config={"system_instruction": _CONTEXT_SYSTEM_PROMPT},
            )
            return (resp.text or "").strip()[:1000]
        except Exception:
            return ""

    # -- judge-driven follow-up generation -------------------------------

    def generate_followup_task(
        self,
        target_text: str,
        original_task: dict,
        difficulty: int,
    ) -> dict:
        """Generate a simpler coding task drilling a free-text gap.

        Args:
            target_text: judge's gap description (misconception/feedback).
            original_task: the task the candidate just answered.
            difficulty: pre-tuned difficulty (already <= original).

        Returns a task dict with keys id/type/difficulty/prompt/
        max_score plus bookkeeping keys ``generated`` and ``target_text``.
        Falls back deterministically without an API key.
        """
        import os

        task_id = f"remed_{uuid.uuid4().hex[:10]}"
        difficulty = max(1, min(5, int(difficulty)))
        gap = (target_text or "").strip() or "the gap in the previous answer"

        if not os.getenv("GOOGLE_API_KEY"):
            return self._build(task_id, difficulty, self._fallback_prompt(gap, original_task), gap)

        try:
            resp = self._client().models.generate_content(
                model=self._model,
                contents=(
                    f"Original task:\n{original_task.get('prompt', '')}\n\n"
                    f"Gap to drill: {gap}\n"
                    f"Desired difficulty (1-5): {difficulty}\n\n"
                    "Create ONE simpler coding task drilling only that gap, "
                    "self-contained with a clear function signature. Do not "
                    "reveal the answer."
                ),
                config={
                    "system_instruction": _FOLLOWUP_SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "response_schema": _FOLLOWUP_SCHEMA,
                },
            )
            payload = json.loads(resp.text)
            prompt = str(payload.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("empty follow-up prompt")
            llm_difficulty = int(payload.get("difficulty", difficulty))
            difficulty = max(1, min(int(original_task.get("difficulty", difficulty)), llm_difficulty))
            return self._build(task_id, difficulty, prompt, gap)
        except Exception:
            return self._build(task_id, difficulty, self._fallback_prompt(gap, original_task), gap)

    @staticmethod
    def _build(task_id: str, difficulty: int, prompt: str, target_text: str) -> dict:
        return {
            "id": task_id,
            "type": "code",
            "difficulty": difficulty,
            "prompt": prompt,
            "max_score": 5,
            "hints": [],
            "generated": True,
            "target_text": target_text,
            "context_notes": "",
        }

    @staticmethod
    def _fallback_prompt(gap: str, original_task: dict) -> str:
        return (
            f"Working specifically on this gap: {gap}.\n"
            f"Write a small, self-contained function that demonstrates the correct "
            f"idea in isolation. Keep it focused and minimal; this is a warm-up "
            f"for: {original_task.get('prompt', '')}"
        ).strip()
