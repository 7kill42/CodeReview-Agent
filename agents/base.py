"""Shared data models and abstract base class for all review agents."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from pydantic import BaseModel, Field


class Finding(BaseModel):
    """A single issue found in a code diff."""

    file: str
    line_start: int
    line_end: int
    severity: str        # CRITICAL / HIGH / MEDIUM / LOW
    category: str        # e.g. naming, magic_number, …
    description: str     # human-readable problem description
    suggestion: str      # concrete fix recommendation
    confidence: float = Field(ge=0.0, le=1.0)  # 0.0 – 1.0


class AgentResult(BaseModel):
    """Aggregated output from a single review agent run."""

    agent_name: str
    findings: List[Finding]
    summary: str
    execution_time: float   # seconds
    token_used: int


class FileDiff(BaseModel):
    """Parsed representation of one file's unified diff."""

    filename: str
    language: str = "python"
    # (line_number, line_text) pairs for '+' lines in the diff
    added_lines: List[tuple[int, str]] = Field(default_factory=list)
    # (line_number, line_text) pairs for '-' lines in the diff
    removed_lines: List[tuple[int, str]] = Field(default_factory=list)
    raw_diff: str = ""


class BaseReviewAgent(ABC):
    """Abstract base that every specialised agent must implement."""

    @abstractmethod
    async def review(self, file_diff: FileDiff) -> AgentResult:
        """Analyse *file_diff* and return an :class:`AgentResult`."""
