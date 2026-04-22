from __future__ import annotations

from tools.github_client import GitHubClient
from tools.scm_base import SCMClient


def get_scm_client(target_url: str) -> SCMClient:
    """Return the SCM client implementation for *target_url*."""
    if "github.com" in target_url:
        return GitHubClient()
    raise ValueError(f"Unsupported SCM URL: {target_url}")
