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


class ShareRequest(BaseModel):
    step_index: Optional[int] = Field(default=None, ge=0)


class RedoRequest(BaseModel):
    step_index: int = Field(ge=0)
    answer: str = Field(min_length=1, max_length=50000)


class TaskCreateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    scaffold: Optional[str] = Field(default=None, max_length=16000)
    difficulty: int = Field(default=2, ge=1, le=5)
    max_score: int = Field(default=5, ge=1, le=100)
    parts: Optional[list[dict[str, Any]]] = None
    is_public: bool = False
    context_notes: Optional[str] = Field(default=None, max_length=2000)
    tags: Optional[dict[str, Any]] = None
    task_type: Optional[str] = Field(default=None, max_length=32)
    language: Optional[str] = Field(default=None, max_length=32)


class TaskPatchRequest(BaseModel):
    prompt: Optional[str] = Field(default=None, min_length=1, max_length=8000)
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


# (AdminSeedCreateRequest removed: no system-owned seed tasks; author via
# POST /api/v1/tasks with is_public=true.)
