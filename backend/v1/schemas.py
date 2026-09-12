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
    skill: Optional[str] = Field(default=None, max_length=120)


class AnswerSubmitRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    answer: str = Field(min_length=1, max_length=50000)
    hints_used: list[str] = Field(default_factory=list, max_length=50)


class TaskCreateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    skill: str = Field(default="general", max_length=120)
    scaffold: Optional[str] = Field(default=None, max_length=16000)
    difficulty: int = Field(default=2, ge=1, le=5)
    max_score: int = Field(default=5, ge=1, le=100)
    hints: list[dict[str, Any]] = Field(default_factory=list)
    is_public: bool = False
    context_notes: Optional[str] = Field(default=None, max_length=2000)


class TaskPatchRequest(BaseModel):
    prompt: Optional[str] = Field(default=None, min_length=1, max_length=8000)
    skill: Optional[str] = Field(default=None, max_length=120)
    scaffold: Optional[str] = Field(default=None, max_length=16000)
    difficulty: Optional[int] = Field(default=None, ge=1, le=5)
    max_score: Optional[int] = Field(default=None, ge=1, le=100)
    hints: Optional[list[dict[str, Any]]] = None
    is_public: Optional[bool] = None
    context_notes: Optional[str] = Field(default=None, max_length=2000)
