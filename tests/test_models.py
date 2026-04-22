"""Tests for SQLAlchemy model configuration."""
from __future__ import annotations

from storage.models import ReviewTask


def test_review_task_status_enum_uses_lowercase_values():
    """PostgreSQL enum labels should match TaskStatus.value values."""
    enum_type = ReviewTask.__table__.c.status.type
    assert enum_type.enums == ["pending", "running", "completed", "failed"]
