"""Per-task plain-English context + follow-up task generation.

Each task optionally carries ``context_notes``:
2-4 plain sentences such as "A is a prerequisite of B, which is often
confused with C." Produced once by an LLM at creation time (empty string
on failure keeps startup/tests hermetic). Follow-up generation takes the
judge's free-text gap (feedback), not a node id, and requires
an LLM call — failures raise so the cause is visible in logs instead of
serving a confusing templated task.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Optional

from google import genai
from google.genai import types

from coach.config import MODEL, default_pass_score, http_retry_options
from coach.taxonomy import TASK_TYPES, format_vocabulary, is_leaf, normalize_tag

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
  "scaffold": a code stub for the candidate to fill in (the exact
    function signature from the prompt, with a TODO comment and an empty/
    `pass` body — never the solution) in the FIRST requested language.
  "scaffolds": an array with one {"language", "code"} entry for EVERY
    requested language (same stub, translated to that language).
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
  "scaffold": a code stub for the candidate to fill in (the exact
    function signature from the prompt, with a TODO comment and an empty/
    `pass` body — never the solution) in the FIRST requested language.
  "scaffolds": an array with one {"language", "code"} entry for EVERY
    requested language (same stub, translated to that language).
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
  "scaffold": a code stub for the candidate to fill in (the exact
    function signature from the prompt, with a TODO comment and an empty/
    `pass` body — never the solution) in the FIRST requested language.
  "scaffolds": an array with one {"language", "code"} entry for EVERY
    requested language (same stub, translated to that language).
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
  "scaffold": a code stub for the candidate to fill in (the exact
    function signature from the prompt, with a TODO comment and an empty/
    `pass` body — never the solution) in the FIRST requested language.
  "scaffolds": an array with one {"language", "code"} entry for EVERY
    requested language (same stub, translated to that language).
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
        "scaffolds": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "language": types.Schema(type=types.Type.STRING),
                    "code": types.Schema(type=types.Type.STRING),
                },
            ),
        ),
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

_SESSION_SYSTEM_PROMPT = """\
You are naming a practice session in a coding tutor. Given the first question \
the learner attempted (and optionally their answer), write a short title and a \
concise summary describing what the session covers. Do NOT reveal or discuss \
the solution.

Return JSON with exactly two keys:
  "title": 3-6 words, no trailing period, e.g. "Gradient checkpointing basics".
  "summary": 1-2 sentences (max ~200 characters) describing the topics and \
    skills practiced in this session."""

_SESSION_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "title": types.Schema(type=types.Type.STRING),
        "summary": types.Schema(type=types.Type.STRING),
    },
    required=["title", "summary"],
)

def _scaffold_for(prompt: str, original_task: dict | None) -> str | None:
    """Derive a fill-in stub when the model omits ``scaffold``.

    Mirrors ``coach.session.build_code_stub``: prefer a ``def`` signature
    found in the new prompt, else reuse the original task's step scaffold
    so the editor is never blank for a function-style drill.
    """
    import re

    m = re.search(r"def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", prompt or "")
    if m:
        name, params = m.group(1), m.group(2)
        return f"def {name}({params}):\n    # TODO: implement {name}\n    pass\n"
    orig = original_task or {}
    for part in orig.get("parts") or []:
        if isinstance(part, dict) and part.get("scaffold"):
            return str(part["scaffold"])
    m2 = re.search(r"def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", str(orig.get("prompt", "")))
    if m2:
        name, params = m2.group(1), m2.group(2)
        return f"def {name}({params}):\n    # TODO: implement {name}\n    pass\n"
    return None


def _translate_stub(stub: str, language: str) -> str:
    """Best-effort stub in ``language`` when the model gave only one.

    Py-to-X translation is not attempted; a non-Python language gets a TODO
    comment naming the entry point when one can be recovered from the Python
    stub, so the editor is never blank for a multi-language drill.
    """
    if not stub or language == "python":
        return stub
    import re

    match = re.search(r"def\s+([A-Za-z_]\w*)", stub or "")
    if match:
        return f"// TODO: implement {match.group(1)}\n"
    return "// TODO: implement the step described above\n"


def _resolve_scaffolds(payload: dict, default_stub: str, languages: list) -> tuple[list[str], dict[str, str]]:
    """Build a per-language scaffold map from a follow-up model response.

    Uses the model's ``scaffolds`` list when present, otherwise the single
    ``scaffold`` stub for the default language and a translated fallback for
    the rest. Always returns an entry for every declared language.
    """
    from coach.tasks import normalize_language, normalize_languages

    langs = normalize_languages(languages)
    scaffolds: dict[str, str] = {}
    raw = payload.get("scaffolds")
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            lang = normalize_language(entry.get("language"))
            code = str(entry.get("code") or "").strip()
            if code:
                scaffolds[lang] = code
    if default_stub:
        scaffolds.setdefault(langs[0], default_stub)
    for lang in langs:
        if not scaffolds.get(lang):
            scaffolds[lang] = _translate_stub(scaffolds.get(langs[0], ""), lang)
    return langs, scaffolds


def _fallback_session_title_summary(task: dict) -> dict:
    """Deterministic title/summary when the LLM is unavailable.

    Title comes from the primary skill label; the summary falls back to the
    task's generated context notes, then the first step's prompt.
    """
    tags = task.get("tags") or {}
    primary = tags.get("primary")
    parts = task.get("parts") or []
    prompt = (parts[0].get("prompt") if parts else task.get("prompt", "")) or ""
    if primary:
        title = str(primary).replace("_", " ").strip().title()[:60]
    else:
        title = (prompt.split(".")[0] or "Practice session").strip()[:60]
    summary = str(task.get("context_notes") or "").strip()[:240] or prompt.strip()[:240]
    if not summary:
        summary = "A practice session on this question."
    return {"title": title or "Practice session", "summary": summary}


# ---------------------------------------------------------------------------
# Curator quick task authoring (draft from step prompts)
# ---------------------------------------------------------------------------

# A task may have at most this many steps (product decision).
_DRAFT_MAX_STEPS = 5

_DRAFT_STEP_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "key": types.Schema(type=types.Type.STRING),
        "prompt": types.Schema(type=types.Type.STRING),
        "difficulty": types.Schema(type=types.Type.INTEGER),
        "max_score": types.Schema(type=types.Type.INTEGER),
        "pass_score": types.Schema(type=types.Type.INTEGER),
        "primary_tag": types.Schema(type=types.Type.STRING),
        "secondary_tag": types.Schema(
            type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
        ),
        "scaffold": types.Schema(type=types.Type.STRING),
        "scaffolds": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "language": types.Schema(type=types.Type.STRING),
                    "code": types.Schema(type=types.Type.STRING),
                },
            ),
        ),
    },
    required=["prompt"],
)

_DRAFT_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "context_notes": types.Schema(type=types.Type.STRING),
        "task_type": types.Schema(type=types.Type.STRING),
        "steps": types.Schema(type=types.Type.ARRAY, items=_DRAFT_STEP_SCHEMA),
    },
    required=["steps"],
)

_DRAFT_STEP_FIELDS = (
    '"key" (unique snake_case entry-point id), "prompt" (cleaned up and '
    'self-contained natural language describing what to implement; do NOT '
    'repeat the entry-point function signature or any code — the scaffold '
    'already shows it), "difficulty" '
    '[1-5], "max_score" [2-10], "pass_score" [1..max_score], "primary_tag" '
    '(ONE leaf skill), "secondary_tag" (0-2 leaf skills), "scaffold" '
    '(imports + the entry-point function with the exact signature, ONE short '
    'comment and a `pass`/empty body — never the solution) in the FIRST '
    'requested language, and "scaffolds" (an array of {"language", "code"} '
    'with the same stub for EVERY requested language). The FIRST step MUST '
    'provide starter code; a LATER step that should build directly on the '
    'previous step may OMIT "scaffold"/"scaffolds" entirely and will open '
    'from the previous step\'s complete solution. A step that provides starter '
    'code must provide it for every requested language.'
)

_DRAFT_SYSTEM_PROMPT = f"""\
You are a curriculum engineer turning a curator's step prompts into a \
step-by-step coding task for a tutor. Each input step becomes exactly one task \
step, delivered in order; the first step always carries starter code, while a \
later step may omit it to open from the previous step's complete solution.

Return JSON with exactly three keys:
  "context_notes": 2-4 plain English sentences describing the prerequisites, \
    what builds on what, and common confusions for the WHOLE task.
  "task_type": one of {', '.join(sorted(TASK_TYPES))}.
  "steps": a JSON array with EXACTLY the same number of entries as the input \
    steps, in the same order. Each entry has {_DRAFT_STEP_FIELDS}

Never reveal the answer: the scaffold must not contain a formula, a return \
value, or any computation. The `prompt` is prose only — never put the \
function signature, a `def` line, or any code block in it; the learner sees \
the signature in the scaffold. Use only leaf skills from the vocabulary below.

Vocabulary (domain -> area -> skills):
{format_vocabulary()}"""

_REFINE_SYSTEM_PROMPT = f"""\
You are a curriculum engineer revising an existing step-by-step coding task. \
Apply ONLY the curator's instruction; keep the step count, the step order and \
every unrelated field exactly as they are. Never reveal the answer.

Return JSON with exactly three keys:
  "context_notes": the revised task description (keep the existing text \
    unless the instruction concerns it).
  "task_type": one of {', '.join(sorted(TASK_TYPES))}.
  "steps": a JSON array with exactly the same number of entries and the same \
    order as the current task. Each entry keeps the current task's step keys \
    and has {_DRAFT_STEP_FIELDS}

Vocabulary (domain -> area -> skills):
{format_vocabulary()}"""


def _clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


_DEF_IN_PROMPT = re.compile(r"def\s+([A-Za-z_]\w*)\s*\(")
_CALL_IN_PROMPT = re.compile(r"`([A-Za-z_]\w*)\s*\(")
def _strip_duplicate_signature(prompt: str, scaffold: str) -> str:
    """Remove the scaffold's entry-point signature from the question text.

    The starter code already declares the function, so any ``def name(...)``
    or ``name(...)`` in the prompt is reduced to the bare name. Everything
    else is left untouched.
    """
    text = (prompt or "").strip()
    entry = re.search(r"def\s+([A-Za-z_]\w*)\s*\(", scaffold or "")
    if not text or not entry:
        return text
    name = entry.group(1)
    return re.sub(rf"`?\b(?:def\s+)?{re.escape(name)}\s*\([^)]*\)`?", name, text)


def _derive_step_key(prompt: str, index: int) -> str:
    """A stable key from the prompt's entry point, else ``step_N``."""
    match = _DEF_IN_PROMPT.search(prompt or "") or _CALL_IN_PROMPT.search(prompt or "")
    return match.group(1) if match else f"step_{index + 1}"


def _sanitize_step_tags(entry: dict) -> dict:
    """Drop tags the model invented; an invalid primary stays empty."""
    primary = normalize_tag(entry.get("primary_tag"))
    if not is_leaf(primary):
        primary = ""
    secondary: list[str] = []
    raw_secondary = entry.get("secondary_tag") or []
    if not isinstance(raw_secondary, list):
        raw_secondary = []
    for raw in raw_secondary:
        canon = normalize_tag(raw)
        if is_leaf(canon) and canon != primary and canon not in secondary:
            secondary.append(canon)
    return {"primary": primary or "", "secondary": secondary[:2]}


def _dedupe_keys(parts: list[dict]) -> list[dict]:
    """Make step keys unique, preserving order."""
    seen: set[str] = set()
    out: list[dict] = []
    for index, part in enumerate(parts):
        key = str(part.get("key") or "").strip() or f"step_{index + 1}"
        base, suffix = key, 2
        while key in seen:
            key = f"{base}_{suffix}"
            suffix += 1
        seen.add(key)
        out.append({**part, "key": key})
    return out


def _base_draft_parts(seeds, draft, difficulty, language) -> list[dict]:
    """Seed parts from the prompts (and any existing draft), pre-LLM."""
    existing = list((draft or {}).get("parts") or [])
    out: list[dict] = []
    for index, seed in enumerate(seeds):
        base = (
            existing[index]
            if index < len(existing) and isinstance(existing[index], dict)
            else {}
        )
        base_tags = base.get("tags") or {}
        max_score = _clamp_int(base.get("max_score"), 1, 100, 5)
        part = {
            "key": str(base.get("key") or "").strip() or _derive_step_key(seed, index),
            "prompt": str(base.get("prompt") or seed).strip() or seed,
            "tags": _sanitize_step_tags(
                {
                    "primary_tag": base_tags.get("primary"),
                    "secondary_tag": base_tags.get("secondary") or [],
                }
            ),
            "max_score": max_score,
            "difficulty": _clamp_int(
                base.get("difficulty"), 1, 5, _clamp_int(difficulty, 1, 5, 2)
            ),
            "pass_score": _clamp_int(
                base.get("pass_score"), 0, max_score, default_pass_score(max_score)
            ),
        }
        scaffold = str(base.get("scaffold") or "").strip()
        if scaffold:
            part["scaffold"] = scaffold
        raw_scaffolds = base.get("scaffolds")
        if isinstance(raw_scaffolds, dict):
            kept = {
                str(lang): str(code).strip()
                for lang, code in raw_scaffolds.items()
                if str(code or "").strip()
            }
            if kept:
                part["scaffolds"] = kept
        out.append(part)
    return _dedupe_keys(out)


def _draft_result(
    parts,
    task_type,
    language,
    context_notes,
    problems: Optional[list[str]] = None,
    languages: Optional[list] = None,
) -> dict:
    """Package parts in the ``POST /api/v1/tasks`` body shape.

    ``problems`` names anything the model failed to fill in (a missing/invalid
    scaffold or an unresolvable primary tag). It is always copied onto the
    response so the curator UI can explain why a step is still empty instead
    of leaving the assistant silently "successful".
    """
    from coach.tasks import derive_step_tags, normalize_languages

    task_type = str(task_type or "").strip().lower()
    if task_type not in TASK_TYPES:
        task_type = "implement"
    langs = normalize_languages(languages, language)
    return {
        "parts": parts,
        "language": langs[0],
        "languages": langs,
        "task_type": task_type,
        "context_notes": (context_notes or "").strip()[:2000],
        "tags": derive_step_tags(parts) or {"primary": "", "secondary": []},
        "problems": [str(p) for p in (problems or [])],
    }


def _draft_body(
    seeds, draft, language, task_type, difficulty, context, instruction, languages=None
) -> str:
    """The user-turn contents for a draft or refinement call."""
    langs = [str(l) for l in (languages or [language])]
    if draft:
        current = {
            "language": langs[0],
            "languages": langs,
            "task_type": str(draft.get("task_type") or task_type or ""),
            "context_notes": str(draft.get("context_notes") or ""),
            "parts": draft.get("parts") or [],
        }
        return (
            "Current task JSON:\n"
            + json.dumps(current, ensure_ascii=False)[:8000]
            + f"\n\nCurator instruction:\n{(instruction or '').strip()[:2000]}\n"
            + "\nReturn the revised task JSON."
        )
    lines = [f"Language(s): {', '.join(langs)}"]
    if task_type:
        lines.append(f"Preferred task_type: {task_type}")
    if difficulty:
        lines.append(f"Preferred step difficulty (1-5): {difficulty}")
    if (context or "").strip():
        lines.append(f"Extra curation context: {context.strip()[:1000]}")
    lines.append("\nStep prompts (one per step, in order):")
    for index, seed in enumerate(seeds, 1):
        lines.append(f"{index}. {seed}")
    lines.append("\nCreate the task JSON per the system instruction.")
    return "\n".join(lines)


def _assemble_draft(
    payload: dict, base_parts: list[dict], language: str, languages: Optional[list] = None
) -> tuple[list[dict], list[str]]:
    """Merge model output onto the seed parts; returns ``(parts, problems)``."""
    from coach.scaffold_validation import validate_scaffold
    from coach.tasks import normalize_language, normalize_languages

    langs = normalize_languages(languages, language)
    default_lang = langs[0]
    entries = payload.get("steps")
    if not isinstance(entries, list) or len(entries) != len(base_parts):
        raise ValueError("the model returned the wrong number of steps")
    parts: list[dict] = []
    problems: list[str] = []
    for index, (base, entry) in enumerate(zip(base_parts, entries)):
        if not isinstance(entry, dict):
            raise ValueError("a step was not a JSON object")
        prompt = str(entry.get("prompt") or "").strip() or base["prompt"]
        max_score = _clamp_int(entry.get("max_score"), 1, 100, base["max_score"])
        difficulty = _clamp_int(entry.get("difficulty"), 1, 5, base["difficulty"])
        pass_score = _clamp_int(
            entry.get("pass_score"), 0, max_score, default_pass_score(max_score)
        )
        tags = _sanitize_step_tags(entry)
        if not tags["primary"]:
            problems.append(f"step {index + 1} has no valid primary_tag")

        # Gather the model's per-language scaffolds (plus the legacy single
        # one and any base stub from a refinement).
        proposed: dict[str, str] = {}
        raw_scaffolds = entry.get("scaffolds")
        if isinstance(raw_scaffolds, list):
            for item in raw_scaffolds:
                if isinstance(item, dict):
                    lang = normalize_language(item.get("language"))
                    code = str(item.get("code") or "").strip()
                    if code:
                        proposed[lang] = code
        legacy = str(entry.get("scaffold") or "").strip()
        if legacy:
            proposed.setdefault(default_lang, legacy)
        base_scaffolds = base.get("scaffolds") if isinstance(base.get("scaffolds"), dict) else {}
        for lang in langs:
            if not proposed.get(lang):
                fallback = base_scaffolds.get(lang)
                if not fallback and lang == default_lang:
                    fallback = base.get("scaffold")
                if fallback:
                    proposed[lang] = str(fallback).strip()

        cleaned_scaffolds: dict[str, str] = {}
        for lang in langs:
            code = proposed.get(lang)
            if not code:
                continue
            issues = validate_scaffold(code, language=lang)
            if issues:
                problems.append(f"step {index + 1} scaffold ({lang}): {', '.join(issues)}")
                continue
            cleaned_scaffolds[lang] = code
        # The first step must carry starter code. A later step may omit it
        # Only the first step must carry starter code for every language. A
        # later step may leave any language blank; that language then opens
        # from the previous step's solution.
        missing_langs = [lang for lang in langs if lang not in cleaned_scaffolds]
        if missing_langs and index == 0:
            # Never synthesize starter code: a missing LLM scaffold must stay
            # visible so the curator editor can block creation.
            problems.append(
                f"step {index + 1} has no scaffold"
                + (f" for: {', '.join(missing_langs)}" if len(langs) > 1 else "")
            )
        if cleaned_scaffolds.get(default_lang):
            prompt = _strip_duplicate_signature(prompt, cleaned_scaffolds[default_lang])
        part = {
            "key": str(entry.get("key") or "").strip() or base["key"],
            "prompt": prompt,
            "tags": tags,
            "max_score": max_score,
            "difficulty": difficulty,
            "pass_score": pass_score,
        }
        if cleaned_scaffolds.get(default_lang):
            part["scaffold"] = cleaned_scaffolds[default_lang]
        if len(langs) > 1 and cleaned_scaffolds:
            part["scaffolds"] = cleaned_scaffolds
        parts.append(part)
    return _dedupe_keys(parts), problems


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

    def describe_session(self, task: dict, answer: str = "") -> dict:
        """LLM title + summary for a session, with a deterministic fallback.

        Called once when a draft session is first persisted. Returns
        ``{"title": str, "summary": str}`` and never raises: without an API
        key or on any failure the fallback derives a title/summary from the
        task so persistence can proceed.
        """
        import os

        fallback = _fallback_session_title_summary(task)
        if not os.getenv("GOOGLE_API_KEY"):
            return fallback
        parts = task.get("parts") or []
        prompt = (parts[0].get("prompt") if parts else task.get("prompt", "")) or ""
        body = f"Question:\n{prompt[:4000]}\n"
        if task.get("context_notes"):
            body += f"\nBackground: {str(task['context_notes'])[:800]}\n"
        if answer.strip():
            body += f"\nLearner's first answer (context only):\n{answer.strip()[:1500]}\n"
        body += "\nReturn the session title and summary JSON."
        try:
            client = self._client()
            resp = client.models.generate_content(
                model=self._model,
                contents=body,
                config={
                    "system_instruction": _SESSION_SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "response_schema": _SESSION_SCHEMA,
                },
            )
            payload = json.loads(getattr(resp, "text", "") or "{}")
            title = str(payload.get("title") or "").strip()[:80] or fallback["title"]
            summary = str(payload.get("summary") or "").strip()[:300] or fallback["summary"]
            return {"title": title, "summary": summary}
        except Exception:
            logger.warning("[session-summary] generation failed; using fallback")
            return fallback

    # -- curator quick task authoring ------------------------------------

    def draft_task(
        self,
        steps: list[str] | None = None,
        *,
        draft: dict | None = None,
        instruction: str = "",
        language: str = "python",
        languages: list | None = None,
        task_type: str = "",
        difficulty: int | None = None,
        context: str = "",
        retries: int = 2,
    ) -> dict:
        """Draft (or revise) a task body from curator step prompts.

        Two modes, one LLM call each:

        * **initial draft** — ``steps`` are the curator's per-step prompts; the
          model fills in keys, scores, difficulty, tags, scaffolds and
          ``context_notes``.
        * **refinement** — ``draft`` is a current task body and ``instruction``
          a plain-English edit ("make step 2 harder"); the model returns the
          revised body, preserving the step count and order.

        Returns ``{parts, language, task_type, context_notes, tags, problems}``
        in the shape ``POST /api/v1/tasks`` accepts. ``problems`` is a list of
        human-readable reasons the assistant could not fill in a field (e.g. a
        step whose starter code the model omitted or whose stub failed
        validation); it is empty on a complete draft. Never persists anything.
        Without ``GOOGLE_API_KEY`` (or on repeated failure) returns a
        deterministic fallback that keeps the curator's prompts and leaves
        tags/scaffolds empty for manual selection, with ``problems`` explaining
        why.

        Raises:
            ValueError: no steps / no draft steps, or more than
                ``_DRAFT_MAX_STEPS`` steps.
        """
        import os

        from coach.tasks import normalize_language, normalize_languages

        langs = normalize_languages(languages, language)
        language = normalize_language(language)
        refine = bool(draft) and bool((instruction or "").strip())
        if refine:
            raw_parts = [p for p in (draft.get("parts") or []) if isinstance(p, dict)]
            if not raw_parts:
                raise ValueError("The draft has no steps to refine.")
            if len(raw_parts) > _DRAFT_MAX_STEPS:
                raise ValueError(f"A task may have at most {_DRAFT_MAX_STEPS} steps.")
            seeds = [str(p.get("prompt") or "") for p in raw_parts]
        else:
            seeds = [str(s).strip() for s in (steps or []) if str(s or "").strip()]
            if not seeds:
                raise ValueError("At least one step prompt is required.")
            if len(seeds) > _DRAFT_MAX_STEPS:
                raise ValueError(f"A task may have at most {_DRAFT_MAX_STEPS} steps.")

        base_parts = _base_draft_parts(
            seeds, draft if refine else None, difficulty, language
        )
        baseline_task_type = task_type or str((draft or {}).get("task_type") or "")
        baseline_notes = str((draft or {}).get("context_notes") or "")
        if not os.getenv("GOOGLE_API_KEY"):
            return _draft_result(
                base_parts,
                baseline_task_type,
                language,
                baseline_notes,
                problems=[
                    "AI assistant unavailable (GOOGLE_API_KEY is not set): "
                    "starter code and tags were left empty."
                ],
                languages=langs,
            )

        body = _draft_body(
            seeds,
            draft if refine else None,
            language,
            task_type,
            difficulty,
            context,
            instruction,
            languages=langs,
        )
        best_parts = base_parts
        best_notes = baseline_notes
        best_task_type = baseline_task_type
        best_problems: list[str] = []
        feedback = ""
        for _attempt in range(max(1, retries) + 1):
            try:
                payload = self._generate_draft_payload(
                    body, refine=refine, feedback=feedback
                )
            except Exception as exc:  # noqa: BLE001 - degrade to the fallback
                logger.warning(
                    "[draft] generation failed (%s: %s)", type(exc).__name__, exc
                )
                best_problems = [
                    f"AI generation failed ({type(exc).__name__}): {exc}"
                ]
                break
            try:
                parts, problems = _assemble_draft(payload, base_parts, language, langs)
            except ValueError as exc:
                best_problems = [str(exc)]
                feedback = (
                    f"Your previous response was rejected: {exc}. "
                    "Return corrected JSON only."
                )
                continue
            best_parts = parts
            best_notes = str(payload.get("context_notes") or best_notes)[:2000]
            best_task_type = str(payload.get("task_type") or best_task_type)
            best_problems = problems
            if not problems:
                return _draft_result(parts, best_task_type, language, best_notes, languages=langs)
            feedback = (
                "Your previous response had these problems: "
                + "; ".join(problems)
                + ". Return corrected JSON only."
            )
        # The model did not produce a complete draft after retries: return the
        # best partial draft *with* the unresolved problems so the curator UI
        # can say exactly what the assistant could not fill in (never silently).
        if best_problems:
            logger.error(
                "[draft] returning an incomplete draft after retries: %s",
                "; ".join(best_problems),
            )
        return _draft_result(
            best_parts, best_task_type, language, best_notes, problems=best_problems,
            languages=langs,
        )

    def _generate_draft_payload(
        self, body: str, *, refine: bool, feedback: str = ""
    ) -> dict:
        """One structured draft call (separated so tests can patch it)."""
        contents = body if not (feedback or "").strip() else f"{body}\n\n{feedback.strip()}"
        client = self._client()
        resp = client.models.generate_content(
            model=self._model,
            contents=contents,
            config={
                "system_instruction": (
                    _REFINE_SYSTEM_PROMPT if refine else _DRAFT_SYSTEM_PROMPT
                ),
                "response_mime_type": "application/json",
                "response_schema": _DRAFT_SCHEMA,
            },
        )
        return json.loads(getattr(resp, "text", "") or "{}")

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
            target_text: judge's gap description (feedback).
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
        from coach.tasks import normalize_languages

        languages = normalize_languages(
            (original_task or {}).get("languages"),
            (original_task or {}).get("language"),
        )

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
                f"Requested implementation language(s): {', '.join(languages)}\n"
            )
            if extra_context and extra_context.strip():
                body += f"\nChain context (root task, prerequisites, already drilled — do not repeat):\n{extra_context.strip()[:2000]}\n"
            body += (
                "\nCreate ONE coding task per the system instruction, "
                "self-contained with a clear function signature. For EACH "
                f"requested language ({', '.join(languages)}) provide a stub "
                "with that signature, a TODO comment and an empty body (no "
                "solution). Do not reveal the answer."
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
            langs, scaffolds = _resolve_scaffolds(payload, scaffold, languages)
            return self._build(
                task_id, difficulty, prompt, gap, scaffold,
                scaffolds=scaffolds, languages=langs,
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
        scaffolds: dict | None = None,
        languages: list | None = None,
        kind: str = "remediate",
        parent_task_id: str | None = None,
        root_task_id: str | None = None,
        root_difficulty: int | None = None,
        tags: dict | None = None,
        context_notes: str = "",
    ) -> dict:
        from coach.tasks import normalize_languages

        task_languages = normalize_languages(languages)
        default_language = task_languages[0]
        validated_tags = None
        if tags:
            from coach.taxonomy import validate as validate_tags

            validated_tags = validate_tags(tags)
        part: dict = {
            "key": "solution",
            "prompt": prompt,
            "tags": validated_tags or {"primary": None, "secondary": []},
            "max_score": 5,
            "difficulty": difficulty,
        }
        if scaffold:
            part["scaffold"] = scaffold
        if scaffolds:
            cleaned = {
                lang: str(code).strip()
                for lang, code in scaffolds.items()
                if str(code or "").strip()
            }
            if not cleaned.get(default_language) and scaffold:
                cleaned[default_language] = scaffold
            if cleaned:
                part["scaffolds"] = cleaned
                part["scaffold"] = cleaned[default_language]
        task: dict = {
            "id": task_id,
            "type": "code",
            "difficulty": difficulty,
            "prompt": prompt,
            "max_score": 5,
            "parts": [part],
            "languages": task_languages,
            "language": default_language,
            "generated": True,
            "generated_kind": kind,
            "target_text": target_text,
            "context_notes": (context_notes or "").strip()[:2000],
        }
        if validated_tags:
            task["tags"] = validated_tags
        if parent_task_id:
            task["parent_task_id"] = parent_task_id
        if root_task_id:
            task["root_task_id"] = root_task_id
        if root_difficulty is not None:
            task["root_difficulty"] = root_difficulty
        return task
