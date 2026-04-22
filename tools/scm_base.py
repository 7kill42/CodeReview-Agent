from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agents.base import FileDiff


class SCMClient(ABC):
    """Abstract interface for source-control providers."""

    @abstractmethod
    def get_change_set(self, target_url: str) -> list[FileDiff]:
        """Return the changed files for the review target."""

    @abstractmethod
    def get_metadata(self, target_url: str) -> dict[str, Any]:
        """Return flat metadata for the review target."""

    @abstractmethod
    def post_summary_comment(self, target_url: str, body: str) -> bool:
        """Post a top-level summary comment to the review target."""

    @abstractmethod
    def post_inline_review(
        self,
        target_url: str,
        findings: list[dict[str, Any]],
        summary: str,
    ) -> bool:
        """Post inline review comments for the given findings."""

    @abstractmethod
    def get_head_commit_sha(self, target_url: str) -> str | None:
        """Return the head commit SHA for the review target when available."""
