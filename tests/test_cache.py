"""Tests for Redis cache degradation behavior."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from redis.exceptions import RedisError

from storage.cache import get_dedup_task_id, set_task_status


@pytest.mark.asyncio
async def test_get_dedup_task_id_returns_none_when_redis_unavailable():
    """Dedup lookup should degrade gracefully when Redis is down."""
    with patch("storage.cache._get_client", side_effect=RedisError("down")):
        cached_id = await get_dedup_task_id(
            "https://github.com/owner/repo/pull/1",
            "abc123",
        )

    assert cached_id is None


@pytest.mark.asyncio
async def test_set_task_status_does_not_raise_when_redis_unavailable():
    """Task status writes should be best-effort, not fatal."""
    with patch("storage.cache._get_client", side_effect=RedisError("down")):
        await set_task_status(1, "pending")
