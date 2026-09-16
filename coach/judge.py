"""LLM judge + coach: scores candidate code and teaches back the gap.

A code-block task carries ``parts``; a single submission fills the whole
block and the judge returns a per-part score for every listed function. The
aggregate ``EvaluationResult.score`` is the sum of the per-part scores (so
``fraction`` stays the overall block fraction). Tasks without parts are
treated as one implicit part.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
import json
import os
from google import genai
from google.genai import types
from coach.config import MODEL, http_retry_options


@dataclass
class EvaluationResult:
    task_id: str
    score: float
    max_score: float
    rationale: str
    coach: Optional[dict] = None
    parts: Optional[list] = None

    @property
    def fraction(self) -> float:
        return self.score / self.max_score if self.max_score else 0.0

    def to_dict(self):
        d = {
            "task_id": self.task_id,
            "score": self.score,
            "max_score": self.max_score,
            "rationale": self.rationale,
            "coach": self.coach,
        }
        if self.parts:
            d["parts"] = self.parts
        return d

    @classmethod
    def from_dict(cls, d):
        # Legacy dicts may carry a removed skill tag; it is ignored.
        return cls(
            d["task_id"],
            d["score"],
            d["max_score"],
            d["rationale"],
            d.get("coach"),
            d.get("parts"),
        )


@dataclass
class CoachStep:
    """One step on the path to the correct solution."""

    title: str
    explanation: str
    code: Optional[str] = None

    def to_dict(self):
        return {"title": self.title, "explanation": self.explanation, "code": self.code}

    @classmethod
    def from_dict(cls, d):
        return cls(
            d.get("title", ""),
            d.get("explanation", ""),
            d.get("code"),
        )


@dataclass
class CoachContent:
    """Structured teaching response shown after a submit.

    Identifies the user's misconception/gap and walks them step-by-step to the
    correct solution. `feedback` remains the concise summary used in reports.
    """

    feedback: str = ""
    misconception: str = ""
    steps: list = field(default_factory=list)

    def to_dict(self):
        return {
            "feedback": self.feedback,
            "misconception": self.misconception,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            d.get("feedback", ""),
            d.get("misconception", ""),
            [CoachStep.from_dict(s) for s in d.get("steps", [])],
        )

_STEP_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "title": types.Schema(type=types.Type.STRING),
        "explanation": types.Schema(type=types.Type.STRING),
        "code": types.Schema(type=types.Type.STRING),
    },
    required=["title", "explanation"],
)

_PART_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "key": types.Schema(type=types.Type.STRING),
        "score": types.Schema(type=types.Type.NUMBER),
        "rationale": types.Schema(type=types.Type.STRING),
    },
    required=["key", "score", "rationale"],
)

_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "parts": types.Schema(type=types.Type.ARRAY, items=_PART_SCHEMA),
        "rationale": types.Schema(type=types.Type.STRING),
        "feedback": types.Schema(type=types.Type.STRING),
        "misconception": types.Schema(type=types.Type.STRING),
        "steps": types.Schema(type=types.Type.ARRAY, items=_STEP_SCHEMA),
    },
    required=["parts", "rationale", "feedback", "misconception", "steps"],
)

_SYSTEM_PROMPT = """\
You are a strict technical judge AND a patient coach for AI/ML coding tasks. \
The task asks the candidate to implement one or more functions (the "parts" \
list in the user message, each with its own max score). Evaluate each listed \
function independently for correctness, edge-case handling, and clarity. \
Return a JSON object with five keys:

  "parts": an array with exactly one entry per part key, each entry \
{"key", "score", "rationale"} where "key" matches the given key exactly and \
"score" is a number from 0 to that part's max (in whole-number increments);
  "rationale": a concise explanation of strengths and weaknesses \
(this will appear in a report as evidence, so be specific but brief);
  "feedback": a short (2-4 sentence) summary of the result for the user;
  "misconception": identify the specific gap or misconception in the \
candidate's skills/knowledge that caused their answer to be wrong or \
incomplete. Name the concept clearly (e.g. "You confused overfitting with \
underfitting: ...") and explain precisely where their reasoning/approach \
went astray. If the answer is correct, describe what it demonstrates.
  "steps": a step-by-step path from the candidate's answer to the correct \
solution, ordered from the most fundamental misunderstanding to the final \
correct implementation. Each step has a "title" (one short phrase), an \
"explanation" (clear detail with concrete reasoning), and optionally a \
"code" snippet showing the relevant correction or example (use plain \
python code, no fences). Include concrete examples so the user can arrive \
at the correct solution on their own. Use as many steps as needed (typically \
2-5) to guide them fully. If the answer is already correct, steps should \
reinforce why it works and point out any edge cases to harden.

Use triple-backtick python fenced blocks for any corrected or exemplary code \
inside "rationale" and "feedback", with a blank line before and after each \
code block (the opening fence must start on its own line)."""


def score_targets(task: dict) -> list[dict]:
    """The parts to score: the task's parts, or one implicit part.

    A legacy single-question task (no parts) is treated as one implicit part
    whose key is the function named in the prompt (or "solution").
    """
    parts = task.get("parts") or []
    if parts:
        return [dict(p) for p in parts]
    m = re.search(r"def\s+([A-Za-z_]\w*)\s*\(", task.get("prompt", ""))
    key = m.group(1) if m else "solution"
    return [
        {
            "key": key,
            "prompt": task.get("prompt", ""),
            "tags": task.get("tags") or {"primary": "python", "secondary": []},
            "max_score": int(task.get("max_score") or 5),
            "difficulty": int(task.get("difficulty") or 1),
        }
    ]


class LLMJudge:
    @staticmethod
    def _score_targets(task: dict) -> list[dict]:
        """Alias kept for the belief loop in the submit path."""
        return score_targets(task)

    def evaluate(
        self, task: dict, answer: str, previous_code: Optional[str] = None
    ) -> tuple[EvaluationResult, CoachContent]:
        targets = self._score_targets(task)
        max_score = sum(int(p.get("max_score") or 5) for p in targets)
        client = _client()

        system = _SYSTEM_PROMPT.format(max_score=max_score)
        parts_block = "\n".join(
            f"{i + 1}. {p['key']} (max {int(p.get('max_score') or 5)}):\n{p.get('prompt', '')}"
            for i, p in enumerate(targets)
        )
        user = (
            f"Task:\n{task.get('prompt', '')}\n\n"
            f"Parts to implement:\n{parts_block}\n\n"
        )
        if previous_code:
            user += (
                "Previous implementation this builds on:\n"
                f"```\n{previous_code}\n```\n\n"
            )
        user += f"Candidate's code:\n```\n{answer}\n```"

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
            raw_parts = payload.get("parts") or []
            by_key = {
                str(p.get("key") or ""): p
                for p in raw_parts
                if isinstance(p, dict)
            }
            scored: list[dict] = []
            total = 0.0
            for p in targets:
                part_max = int(p.get("max_score") or 5)
                rp = by_key.get(p["key"])
                if rp is None:
                    score = part_max * 0.5
                    part_rationale = ""
                else:
                    try:
                        score = float(rp.get("score") or 0.0)
                    except (TypeError, ValueError):
                        score = 0.0
                    part_rationale = str(rp.get("rationale") or "") if isinstance(rp, dict) else ""
                score = max(0.0, min(score, part_max))
                total += score
                scored.append(
                    {"key": p["key"], "score": score, "rationale": part_rationale}
                )
            rationale = str(payload.get("rationale", ""))
            steps = [
                CoachStep(
                    str(s.get("title", "")),
                    str(s.get("explanation", "")),
                    s.get("code"),
                )
                for s in payload.get("steps", []) or []
            ]
            coach = CoachContent(
                feedback=str(payload.get("feedback", "")),
                misconception=str(payload.get("misconception", "")),
                steps=steps,
            )
            return EvaluationResult(
                task["id"], total, max_score, rationale, coach.to_dict(), scored
            ), coach
        except Exception:
            scored = [
                {"key": p["key"], "score": int(p.get("max_score") or 5) * 0.5, "rationale": ""}
                for p in targets
            ]
            fallback = CoachContent(
                feedback="We could not evaluate your answer. Please try again.",
                misconception="",
                steps=[],
            )
            return (
                EvaluationResult(
                    task["id"], max_score * 0.5, max_score, "Unable to evaluate",
                    fallback.to_dict(), scored,
                ),
                fallback,
            )


def _client():
    return genai.Client(
        api_key=os.getenv("GOOGLE_API_KEY"),
        http_options=types.HttpOptions(retry_options=http_retry_options()),
    )