"""Per-task plain-English context + follow-up task generation.

Each task optionally carries ``context_notes``:
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
from coach.taxonomy import format_vocabulary

logger = logging.getLogger(__name__)

_FOLLOWUP_SYSTEM_PROMPT = """\
You are a tutor for a learning system. A candidate answered the original task \
incorrectly or revealed a gap described below. Create ONE simpler coding task \
that drills directly into that gap so the candidate can rebuild the missing \
skill with a small, focused exercise.

Return JSON with exactly four keys:
  "prompt": the new, simpler coding task prompt (2-6 sentences, self-contained,
    with a clear function signature or spec). Reduce scope versus the original;
    isolate only the gap. Do not reveal the answer.
  "scaffold": a Python code stub for the candidate to fill in (the exact
    function signature from the prompt, with a TODO comment and a `pass`
    body — never the solution).
  "difficulty": an integer in [1, 5] strictly at or below the original task's
    difficulty, reflecting the reduced scope.
  "context_notes": 2-4 plain English sentences describing the prerequisites,
    what builds on what, and common confusions for THIS task."""

_ESCALATE_SYSTEM_PROMPT = """\
You are a tutor for a learning system. The candidate just SOLVED a simpler \
drill task. Create ONE follow-up coding task that raises the challenge back \
toward the original task: same skill/gap family but a harder variant (more \
general input, an extra edge case, or a removed simplification). Do not \
repeat the solved drill verbatim and do not reveal the answer.

Return JSON with exactly four keys:
  "prompt": the new, harder coding task prompt (2-6 sentences, self-contained,
    with a clear function signature or spec).
  "scaffold": a Python code stub for the candidate to fill in (the exact
    function signature from the prompt, with a TODO comment and a `pass`
    body — never the solution).
  "difficulty": an integer in [1, 5], at or above the drill's difficulty \
(prefer one step harder unless that would exceed the root difficulty + 1).
  "context_notes": 2-4 plain English sentences describing the prerequisites,
    what builds on what, and common confusions for THIS task."""

_PIVOT_SYSTEM_PROMPT = """\
You are a tutor for a learning system. The candidate just solved the drill \
and its harder variant. Create ONE follow-up coding task that drills a \
DIFFERENT prerequisite or commonly-confused concept of the same root task \
(see root context and the list of already-drilled gaps to avoid). Keep the \
difficulty similar to the last solved task. Do not repeat prior drills and \
do not reveal the answer.

Return JSON with exactly four keys:
  "prompt": the new coding task prompt (2-6 sentences, self-contained, with
    a clear function signature or spec) isolating the new prerequisite.
  "scaffold": a Python code stub for the candidate to fill in (the exact
    function signature from the prompt, with a TODO comment and a `pass`
    body — never the solution).
  "difficulty": an integer in [1, 5], similar to the last solved task's \
difficulty.
  "context_notes": 2-4 plain English sentences describing the prerequisites,
    what builds on what, and common confusions for THIS task."""

_CHALLENGE_SYSTEM_PROMPT = """\
You are a tutor for a learning system. The candidate has worked through the \
available question bank. Create ONE fresh coding task at the requested \
difficulty that keeps the session going: pick an important AI/ML coding \
skill the candidate has not just drilled (see recent gaps to avoid \
repetition), self-contained with a clear function signature or spec.

Return JSON with exactly four keys:
  "prompt": the new coding task prompt (2-6 sentences, self-contained, with
    a clear function signature or spec). Do not reveal the answer.
  "scaffold": a Python code stub for the candidate to fill in (the exact
    function signature from the prompt, with a TODO comment and a `pass`
    body — never the solution).
  "difficulty": an integer in [1, 5], near the requested difficulty.
  "context_notes": 2-4 plain English sentences describing the prerequisites,
    what builds on what, and common confusions for THIS task."""

_FOLLOWUP_PROMPTS = {
    "remediate": _FOLLOWUP_SYSTEM_PROMPT,
    "escalate": _ESCALATE_SYSTEM_PROMPT,
    "pivot": _PIVOT_SYSTEM_PROMPT,
    "challenge": _CHALLENGE_SYSTEM_PROMPT,
}

_FOLLOWUP_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "prompt": types.Schema(type=types.Type.STRING),
        "scaffold": types.Schema(type=types.Type.STRING),
        "difficulty": types.Schema(type=types.Type.INTEGER),
        "context_notes": types.Schema(type=types.Type.STRING),
    },
    required=["prompt", "difficulty"],
)

_CATEGORIZE_SYSTEM_PROMPT = f"""\
You are a curriculum librarian. Given a coding task, classify it into ONE \
primary skill and at most TWO secondary skills from the closed vocabulary \
below. Primary must be the single best leaf-skill match. Return JSON with \
exactly three keys:
  "context_notes": 2-4 plain English sentences describing prerequisites, what \
    builds on what, and common confusions (concrete, focused on THIS task).
  "primary_tag": one leaf skill from the vocabulary (never a domain/area).
  "secondary_tag": a JSON array of 0-2 leaf skills.

Vocabulary (domain -> area -> skills):
{format_vocabulary()}

Use only leaf skills from this vocabulary; no other strings. If no skill fits \
confidently, return an empty primary_tag."""

_COMBINED_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "context_notes": types.Schema(type=types.Type.STRING),
        "primary_tag": types.Schema(type=types.Type.STRING),
        "secondary_tag": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
        ),
    },
    required=["context_notes", "primary_tag", "secondary_tag"],
)

def _scaffold_for(prompt: str, original_task: dict | None) -> str | None:
    """Derive a fill-in stub when the model omits ``scaffold``.

    Mirrors ``coach.session.build_code_stub``: prefer a ``def`` signature
    found in the new prompt, else reuse the original task's scaffold/stub
    so the editor is never blank for a function-style drill.
    """
    import re

    m = re.search(r"def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", prompt or "")
    if m:
        name, params = m.group(1), m.group(2)
        return f"def {name}({params}):\n    # TODO: implement {name}\n    pass\n"
    orig = original_task or {}
    if orig.get("scaffold"):
        return str(orig["scaffold"])
    m2 = re.search(r"def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", str(orig.get("prompt", "")))
    if m2:
        name, params = m2.group(1), m2.group(2)
        return f"def {name}({params}):\n    # TODO: implement {name}\n    pass\n"
    return None


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

    def describe_and_categorize(self, prompt: str) -> dict:
        """Combined context-notes + tag categorization (ONE LLM call).

        Returns ``{"context_notes": str, "tags": {primary, secondary} | None}``.
        Without an API key or on any failure, ``tags`` is ``None`` (there is no
        fallback tag); callers must reject task creation.
        """
        import os

        from coach.taxonomy import normalize_tag, validate as validate_tags

        if not os.getenv("GOOGLE_API_KEY"):
            return {"context_notes": "", "tags": None}
        raw = ""
        try:
            client = self._client()
            resp = client.models.generate_content(
                model=self._model,
                contents=f"Task:\n{prompt}",
                config={
                    "system_instruction": _CATEGORIZE_SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "response_schema": _COMBINED_SCHEMA,
                },
            )
            raw = getattr(resp, "text", "") or ""
            payload = json.loads(raw)
            notes = str(payload.get("context_notes") or "").strip()[:1000]
            primary = payload.get("primary_tag")
            secondary = payload.get("secondary_tag") or []
            if not isinstance(secondary, list):
                secondary = []
            # LLM output is sanitized: invalid secondary tags are dropped, and
            # a non-leaf/invalid primary yields no tags at all.
            secondary = [t for t in (normalize_tag(s) for s in secondary) if t][:2]
            try:
                tags = validate_tags({"primary": primary, "secondary": secondary})
            except ValueError:
                return {"context_notes": notes, "tags": None}
            return {"context_notes": notes, "tags": tags}
        except Exception:
            logger.warning("[categorize] categorization failed (%s)", raw[:200])
            return {"context_notes": "", "tags": None}

    # -- judge-driven follow-up generation -------------------------------

    def generate_followup_task(
        self,
        target_text: str,
        original_task: dict,
        difficulty: int,
        mode: str = "remediate",
        extra_context: str = "",
    ) -> dict:
        """Generate an adaptive follow-up task drilling a free-text gap.

        Args:
            target_text: judge's gap description (misconception/feedback).
            original_task: the task the candidate just answered (may itself
                be a generated drill; chain bookkeeping is preserved).
            difficulty: pre-tuned difficulty (mode-aware bounds applied).
            mode: ``remediate`` (simpler drill), ``escalate`` (harder variant
                after a solved drill), or ``pivot`` (different prerequisite
                of the same root task after a solved escalation).
            extra_context: root prompt / context_notes / already-drilled gaps
                so escalations don't repeat and pivots pick a new prerequisite.

        Returns a task dict with keys id/type/difficulty/prompt/scaffold/
        max_score plus bookkeeping keys ``generated``, ``generated_kind``,
        ``target_text``, ``parent_task_id`` and ``root_task_id``.

        Raises:
            RuntimeError: when ``GOOGLE_API_KEY`` is missing or the LLM call
                fails (including empty/invalid responses). The failure and
                the raw model text (truncated) are logged; callers
                (``coach.remediation.plan_followup``) catch, log, and skip
                the follow-up so the session falls through to the bank
                picker instead of serving a templated task.
        """
        import os

        mode = mode if mode in _FOLLOWUP_PROMPTS else "remediate"
        task_id = f"remed_{uuid.uuid4().hex[:10]}"
        difficulty = max(1, min(5, int(difficulty)))
        gap = (target_text or "").strip() or "the gap in the previous answer"

        if not os.getenv("GOOGLE_API_KEY"):
            reason = "missing GOOGLE_API_KEY"
            logger.error("[followup:%s] %s, cannot generate drill for gap=%r", mode, reason, gap)
            raise RuntimeError(f"Follow-up generation failed: {reason}")

        raw = ""
        try:
            client = self._client()
            body = (
                f"Original task:\n{original_task.get('prompt', '')}\n\n"
                f"Gap to drill: {gap}\n"
                f"Desired difficulty (1-5): {difficulty}\n"
            )
            if extra_context and extra_context.strip():
                body += f"\nChain context (root task, prerequisites, already drilled — do not repeat):\n{extra_context.strip()[:2000]}\n"
            body += (
                "\nCreate ONE coding task per the system instruction, "
                "self-contained with a clear function signature. Also "
                "provide a 'scaffold' Python stub with that signature, "
                "a TODO comment and a `pass` body (no solution). Do not "
                "reveal the answer."
            )
            resp = client.models.generate_content(
                model=self._model,
                contents=body,
                config={
                    "system_instruction": _FOLLOWUP_PROMPTS[mode],
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
            orig_diff = int((original_task or {}).get("difficulty", difficulty))
            if mode == "remediate":
                difficulty = max(1, min(orig_diff, llm_difficulty, difficulty))
            elif mode == "escalate":
                # Harder than the solved drill, capped near the root level.
                root_cap = max(1, min(5, int((original_task or {}).get("root_difficulty", orig_diff + 1))))
                difficulty = max(1, min(root_cap, max(difficulty, llm_difficulty)))
            else:  # pivot: hold near the last solved level
                difficulty = max(1, min(5, llm_difficulty or difficulty))
            scaffold = str(payload.get("scaffold") or "").strip() or _scaffold_for(prompt, original_task)
            return self._build(
                task_id, difficulty, prompt, gap, scaffold,
                kind=mode, parent_task_id=(original_task or {}).get("id"),
                root_task_id=(original_task or {}).get("root_task_id") or (original_task or {}).get("id"),
                root_difficulty=(original_task or {}).get("root_difficulty", orig_diff),
                tags=(original_task or {}).get("tags"),
                context_notes=str(payload.get("context_notes") or ""),
            )
        except Exception as exc:
            logger.exception(
                "[followup:%s] LLM generation failed (%s: %s) for gap=%r",
                mode, type(exc).__name__, exc, gap,
            )
            logger.error("[followup] raw model response: %r", raw[:2000])
            raise RuntimeError(
                f"Follow-up generation failed: {type(exc).__name__}: {exc}; "
                f"raw response: {raw[:2000]!r}"
            ) from exc

    def generate_challenge_task(
        self,
        difficulty: int,
        avoid_text: str = "",
        prefer_node: str = "",
        tags: dict | None = None,
    ) -> dict:
        """Generate a fresh adaptive task keeping an open-ended session going.

        Used when the task bank is exhausted: picks an important skill at the
        requested difficulty, avoiding recently-drilled gaps in ``avoid_text``.
        ``prefer_node`` (a leaf skill) steers the generated task toward an
        under-explored area (scope widening). ``tags`` are attached as-is
        (defaults to ``prefer_node`` as primary when provided).
        Same raise-on-failure contract as ``generate_followup_task``.
        """
        import os

        task_id = f"remed_{uuid.uuid4().hex[:10]}"
        difficulty = max(1, min(5, int(difficulty)))
        if not os.getenv("GOOGLE_API_KEY"):
            reason = "missing GOOGLE_API_KEY"
            logger.error("[challenge] %s, cannot generate task", reason)
            raise RuntimeError(f"Challenge generation failed: {reason}")
        raw = ""
        try:
            client = self._client()
            body = f"Desired difficulty (1-5): {difficulty}\n"
            if prefer_node:
                body += f"Target skill: {prefer_node}\n"
            if avoid_text and avoid_text.strip():
                body += f"\nRecently drilled gaps to avoid repeating:\n{avoid_text.strip()[:1500]}\n"
            body += (
                "\nCreate ONE coding task per the system instruction, "
                "self-contained with a clear function signature, plus a "
                "'scaffold' Python stub (TODO + pass, no solution). Do not "
                "reveal the answer."
            )
            resp = client.models.generate_content(
                model=self._model,
                contents=body,
                config={
                    "system_instruction": _FOLLOWUP_PROMPTS["challenge"],
                    "response_mime_type": "application/json",
                    "response_schema": _FOLLOWUP_SCHEMA,
                },
            )
            raw = getattr(resp, "text", "") or ""
            payload = json.loads(raw)
            prompt = str(payload.get("prompt") or "").strip()
            if not prompt:
                raise ValueError(f"empty challenge prompt in model response: {raw[:2000]!r}")
            llm_difficulty = int(payload.get("difficulty", difficulty))
            difficulty = max(1, min(5, llm_difficulty or difficulty))
            scaffold = str(payload.get("scaffold") or "").strip() or _scaffold_for(prompt, None)
            task = self._build(
                task_id, difficulty, prompt, "open-ended challenge", scaffold,
                kind="challenge", tags=tags or ({"primary": prefer_node} if prefer_node else None),
                context_notes=str(payload.get("context_notes") or ""),
            )
            task["target_text"] = ""
            return task
        except Exception as exc:
            logger.exception("[challenge] LLM generation failed (%s: %s)", type(exc).__name__, exc)
            logger.error("[challenge] raw model response: %r", raw[:2000])
            raise RuntimeError(
                f"Challenge generation failed: {type(exc).__name__}: {exc}; "
                f"raw response: {raw[:2000]!r}"
            ) from exc

    @staticmethod
    def _build(
        task_id: str,
        difficulty: int,
        prompt: str,
        target_text: str,
        scaffold: str | None = None,
        kind: str = "remediate",
        parent_task_id: str | None = None,
        root_task_id: str | None = None,
        root_difficulty: int | None = None,
        tags: dict | None = None,
        context_notes: str = "",
    ) -> dict:
        task: dict = {
            "id": task_id,
            "type": "code",
            "difficulty": difficulty,
            "prompt": prompt,
            "max_score": 5,
            "generated": True,
            "generated_kind": kind,
            "target_text": target_text,
            "context_notes": (context_notes or "").strip()[:2000],
        }
        if tags:
            from coach.taxonomy import validate as validate_tags

            task["tags"] = validate_tags(tags)
        if parent_task_id:
            task["parent_task_id"] = parent_task_id
        if root_task_id:
            task["root_task_id"] = root_task_id
        if root_difficulty is not None:
            task["root_difficulty"] = root_difficulty
        if scaffold:
            task["scaffold"] = scaffold
        return task
