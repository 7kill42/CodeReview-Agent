"""Tests for GitHub client error handling."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.github_client import GitHubClient
from tools.scm_factory import get_scm_client


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


def test_get_change_set_returns_domain_filediff():
    """The SCM API should return the shared domain FileDiff model."""
    client = GitHubClient(token="test-token")
    pr = MagicMock()
    pr.get_files.return_value = [
        MagicMock(filename="app.py", patch="@@ -0,0 +1,1 @@\n+print('hi')\n")
    ]

    with patch.object(GitHubClient, "_get_pr", return_value=pr):
        files = client.get_change_set("https://github.com/owner/repo/pull/1")

    assert len(files) == 1
    assert files[0].filename == "app.py"
    assert files[0].language == "python"
    assert files[0].added_lines == [(1, "print('hi')")]
    assert files[0].raw_diff


def test_legacy_methods_delegate_to_new_scm_api():
    """Backward-compatible method names should still call the new SCM API."""
    client = GitHubClient(token="test-token")

    with (
        patch.object(client, "_get_pr", return_value=MagicMock(title="Example", body="", user=None)),
        patch.object(client, "get_change_set", return_value=[]) as mock_change_set,
        patch.object(client, "get_metadata", return_value={"title": "Example"}) as mock_metadata,
        patch.object(client, "post_summary_comment", return_value=True) as mock_summary,
    ):
        diff = client.get_pr_diff("https://github.com/owner/repo/pull/1")
        metadata = client.get_pr_metadata("https://github.com/owner/repo/pull/1")
        ok = client.post_review_comment("https://github.com/owner/repo/pull/1", "body")

    assert diff.files == []
    assert metadata == {"title": "Example"}
    assert ok is True
    mock_change_set.assert_called_once()
    mock_metadata.assert_called_once()
    mock_summary.assert_called_once()


def test_scm_factory_selects_github_client():
    client = get_scm_client("https://github.com/owner/repo/pull/1")
    assert isinstance(client, GitHubClient)


def test_scm_factory_rejects_unknown_hosts():
    with pytest.raises(ValueError, match="Unsupported SCM URL"):
        get_scm_client("https://example.com/reviews/1")
