"""Tests for GitHub client error handling."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from tools.github_client import GitHubClient


def test_get_pr_diff_propagates_fetch_errors():
    """Diff fetch failures should bubble up to the orchestrator."""
    client = GitHubClient(token="test-token")

    with patch.object(GitHubClient, "_get_pr", side_effect=ValueError("bad pr")):
        with pytest.raises(ValueError, match="bad pr"):
            client.get_pr_diff("https://github.com/owner/repo/pull/1")


def test_get_pr_metadata_is_non_blocking_on_error():
    """Metadata fetch can fail softly because it is optional."""
    client = GitHubClient(token="test-token")

    with patch.object(GitHubClient, "_get_pr", side_effect=RuntimeError("boom")):
        metadata = client.get_pr_metadata("https://github.com/owner/repo/pull/1")

    assert metadata == {}
