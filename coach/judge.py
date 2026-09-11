"""LLM judge + coach: scores candidate code and teaches back the gap."""

from __future__ import annotations

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
    skill: str
    score: float
    max_score: float
    rationale: str
    coach: Optional[dict] = None

    @property
    def fraction(self) -> float:
        return self.score / self.max_score if self.max_score else 0.0

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "skill": self.skill,
            "score": self.score,
            "max_score": self.max_score,
            "rationale": self.rationale,
            "coach": self.coach,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            d["task_id"],
            d["skill"],
            d["score"],
            d["max_score"],
            d["rationale"],
            d.get("coach"),
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

_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "score": types.Schema(type=types.Type.NUMBER),
        "rationale": types.Schema(type=types.Type.STRING),
        "feedback": types.Schema(type=types.Type.STRING),
        "misconception": types.Schema(type=types.Type.STRING),
        "steps": types.Schema(type=types.Type.ARRAY, items=_STEP_SCHEMA),
    },
    required=["score", "rationale", "feedback", "misconception", "steps"],
)

_SYSTEM_PROMPT = """\
You are a strict technical judge AND a patient coach for AI/ML coding tasks. \
Evaluate the candidate's code solution for correctness, edge-case handling, \
and clarity. Return a JSON object with five keys:

  "score": a number from 0 to {max_score} (in whole-number increments), \
where 0 is completely wrong/empty, {max_score} is correct and complete;
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


class LLMJudge:
    def evaluate(self, task: dict, answer: str) -> tuple[EvaluationResult, CoachContent]:
        max_score = task.get("max_score", 5)
        prompt = task.get("prompt", "")
        skill = task.get("skill", "")
        client = _client()

        system = _SYSTEM_PROMPT.format(max_score=max_score)
        user = (
            f"Skill: {skill}\n\n"
            f"Task:\n{prompt}\n\n"
            f"Candidate's code:\n```\n{answer}\n```"
        )

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
                task["id"], task["skill"], score, max_score, rationale, coach.to_dict()
            ), coach
        except Exception:
            fallback = CoachContent(
                feedback="We could not evaluate your answer. Please try again.",
                misconception="",
                steps=[],
            )
            return (
                EvaluationResult(
                    task["id"], task["skill"], max_score * 0.5, max_score, "Unable to evaluate", fallback.to_dict()
                ),
                fallback,
            )


def _client():
    return genai.Client(
        api_key=os.getenv("GOOGLE_API_KEY"),
        http_options=types.HttpOptions(retry_options=http_retry_options()),
    )
