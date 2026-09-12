"""Per-task plain-English context + follow-up task generation.

The knowledge graph is gone. Each task optionally carries ``context_notes``:
2-4 plain sentences such as "A is a prerequisite of B, which is often
confused with C." Produced once by an LLM at creation time (empty string
on failure keeps startup/tests hermetic). Follow-up generation takes the
judge's free-text gap (misconception/feedback), not a node id, and requires
an LLM call — failures raise so the cause is visible in logs instead of
serving a confusing templated task.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from google import genai
from google.genai import types

from coach.config import MODEL, http_retry_options

logger = logging.getLogger(__name__)

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
        self._client_cached: Optional[genai.Client] = None
        self._model = model or MODEL

    def _client(self) -> genai.Client:
        """Shared, lazily-created Gemini client with the project retry config.

        The client is cached on the instance and bound to a local at call
        sites: ``genai.Client.__del__`` closes the shared httpx client, so
        the one-shot ``self._client().models.generate_content(...)`` pattern
        lets CPython GC the temporary client mid-request, producing
        ``RuntimeError: Cannot send a request, as the client has been
        closed.`` Holding a reference for the duration of the call (and
        reusing it across calls) avoids that.
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

    # -- plain-English context -------------------------------------------

    def describe_task(self, prompt: str) -> str:
        """Return 2-4 plain sentences of task context, or "" on any failure."""
        import os

        if not os.getenv("GOOGLE_API_KEY"):
            return ""
        try:
            client = self._client()
            resp = client.models.generate_content(
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

        Raises:
            RuntimeError: when ``GOOGLE_API_KEY`` is missing or the LLM call
                fails (including empty/invalid responses). The failure and
                the raw model text (truncated) are logged; callers
                (``coach.remediation.plan_followup``) catch, log, and skip
                the follow-up so the session falls through to the bank
                picker instead of serving a templated task.
        """
        import os

        task_id = f"remed_{uuid.uuid4().hex[:10]}"
        difficulty = max(1, min(5, int(difficulty)))
        gap = (target_text or "").strip() or "the gap in the previous answer"

        if not os.getenv("GOOGLE_API_KEY"):
            reason = "missing GOOGLE_API_KEY"
            logger.error("[followup] %s, cannot generate drill for gap=%r", reason, gap)
            raise RuntimeError(f"Follow-up generation failed: {reason}")

        raw = ""
        try:
            client = self._client()
            resp = client.models.generate_content(
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
            raw = getattr(resp, "text", "") or ""
            payload = json.loads(raw)
            prompt = str(payload.get("prompt") or "").strip()
            if not prompt:
                raise ValueError(f"empty follow-up prompt in model response: {raw[:2000]!r}")
            llm_difficulty = int(payload.get("difficulty", difficulty))
            difficulty = max(1, min(int(original_task.get("difficulty", difficulty)), llm_difficulty))
            return self._build(task_id, difficulty, prompt, gap)
        except Exception as exc:
            logger.exception(
                "[followup] LLM generation failed (%s: %s) for gap=%r",
                type(exc).__name__, exc, gap,
            )
            logger.error("[followup] raw model response: %r", raw[:2000])
            raise RuntimeError(
                f"Follow-up generation failed: {type(exc).__name__}: {exc}; "
                f"raw response: {raw[:2000]!r}"
            ) from exc

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
