"""Tests for API helpers and route handlers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.main import _enqueue_review, create_review, ReviewRequest
from storage.models import TaskStatus


@pytest.mark.asyncio
async def test_enqueue_review_creates_task_and_launches_orchestrator():
    """The shared enqueue helper should persist the task and start Orchestrator."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    async def _refresh(task):
        task.id = 42

    db.refresh = AsyncMock(side_effect=_refresh)

    scheduled: dict[str, object] = {}

    def _capture_task(coro):
        scheduled["coro"] = coro
        coro.close()
        return MagicMock()

    with (
        patch("api.main.set_task_status", new_callable=AsyncMock) as mock_set_task_status,
        patch("api.main.Orchestrator") as mock_orchestrator_cls,
        patch("api.main.asyncio.create_task", side_effect=_capture_task) as mock_create_task,
    ):
        mock_orchestrator_cls.return_value.run = AsyncMock()
        task = await _enqueue_review("https://github.com/owner/repo/pull/1", db)

    assert task.id == 42
    assert task.status == TaskStatus.PENDING
    mock_set_task_status.assert_awaited_once_with(42, TaskStatus.PENDING.value)
    mock_orchestrator_cls.return_value.run.assert_called_once_with(
        task_id=42,
        pr_url="https://github.com/owner/repo/pull/1",
    )
    mock_create_task.assert_called_once()
    assert "coro" in scheduled


@pytest.mark.asyncio
async def test_create_review_uses_enqueue_helper():
    """POST /review handler should delegate to the shared enqueue helper."""
    task = MagicMock()
    task.id = 7
    task.status = TaskStatus.PENDING

    with patch("api.main._enqueue_review", new_callable=AsyncMock, return_value=task) as mock_enqueue:
        response = await create_review(
            ReviewRequest(pr_url="https://github.com/owner/repo/pull/7"),
            db=AsyncMock(),
        )

    mock_enqueue.assert_awaited_once()
    assert response.task_id == 7
    assert response.status == "pending"
    assert "GET /review/{task_id}" in response.message
