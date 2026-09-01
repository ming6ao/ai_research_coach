"""Replay report data models (Stage 10)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StateSnapshot(BaseModel):
    mastery: float
    uncertainty: float
    evidence_count: int
    status: str
    conceptual: float = 0.0
    procedural: float = 0.0
    implementation: float = 0.0
    transfer: float = 0.0
    fluency: float = 0.0
    self_confidence: float = 0.0
    reasoning: float = 0.0


class ReplayReport(BaseModel):
    scenario: str
    states: dict[str, StateSnapshot] = Field(default_factory=dict)
    evidence_counts: dict[str, int] = Field(default_factory=dict)
    misconceptions: list[dict] = Field(default_factory=list)
    frontier: list[dict] = Field(default_factory=list)
    actions: list[dict] = Field(default_factory=list)
    selected_action: Optional[dict] = None
    passed: bool = False
    failures: list[str] = Field(default_factory=list)