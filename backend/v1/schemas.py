"""Shared v1 request models.

List endpoints return ``{"data": [...], "meta": {page, page_size, total}}``;
single resources return ``{"data": ...}`` (plain dicts; see pagination.py).
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int


class SessionCreateRequest(BaseModel):
    initial_question: Optional[str] = Field(default=None, max_length=8000)
    task_ids: Optional[list[str]] = Field(default=None, max_length=100)
    random_first: bool = Field(default=False)
    node: Optional[str] = Field(default=None, max_length=64)


class AnswerSubmitRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    answer: str = Field(min_length=1, max_length=50000)


class TaskCreateRequest(BaseModel):
    # A task is one or more steps; a single-step question is a one-part task.
    parts: list[dict[str, Any]] = Field(min_length=1)
    scaffold: Optional[str] = Field(default=None, max_length=16000)
    difficulty: int = Field(default=2, ge=1, le=5)
    max_score: int = Field(default=5, ge=1, le=100)
    is_public: bool = False
    context_notes: Optional[str] = Field(default=None, max_length=2000)
    tags: Optional[dict[str, Any]] = None
    task_type: Optional[str] = Field(default=None, max_length=32)
    language: Optional[str] = Field(default=None, max_length=32)


class TaskPatchRequest(BaseModel):
    scaffold: Optional[str] = Field(default=None, max_length=16000)
    difficulty: Optional[int] = Field(default=None, ge=1, le=5)
    max_score: Optional[int] = Field(default=None, ge=1, le=100)
    parts: Optional[list[dict[str, Any]]] = None
    is_public: Optional[bool] = None
    context_notes: Optional[str] = Field(default=None, max_length=2000)
    tags: Optional[dict[str, Any]] = None
    task_type: Optional[str] = Field(default=None, max_length=32)
    language: Optional[str] = Field(default=None, max_length=32)
    owner: Optional[str] = Field(default=None, max_length=255)


class ExplainCreateRequest(BaseModel):
    """A highlighted passage the learner asked to have explained.

    ``selected_text`` is capped at 4000 chars and ``context`` at 800 (the
    enclosing paragraph); both are enforced client-side too. ``question`` is
    set for a follow-up on an existing explanation (``parent_id``).
    """

    task_id: str = Field(min_length=1, max_length=128)
    step_key: Optional[str] = Field(default=None, max_length=64)
    selected_text: str = Field(min_length=1, max_length=4000)
    context: Optional[str] = Field(default=None, max_length=800)
    source_kind: str = Field(default="other", max_length=16)
    question: Optional[str] = Field(default=None, max_length=1000)
    parent_id: Optional[str] = Field(default=None, max_length=36)


# (AdminSeedCreateRequest removed: no system-owned seed tasks; author via
# POST /api/v1/tasks with is_public=true.)
