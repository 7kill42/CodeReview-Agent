from __future__ import annotations

import logging
import re
from typing import Any
from typing import List

from pydantic import BaseModel
from github import Github, GithubException

from agents.base import FileDiff
from config import settings
from tools.scm_base import SCMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_EXT_TO_LANG: dict[str, str] = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "jsx": "javascript", "tsx": "typescript", "java": "java",
    "go": "go", "rb": "ruby", "rs": "rust", "cpp": "cpp",
    "cc": "cpp", "cxx": "cpp", "c": "c", "h": "c",
    "cs": "csharp", "php": "php", "swift": "swift",
    "kt": "kotlin", "scala": "scala", "sh": "bash",
    "bash": "bash", "zsh": "bash", "sql": "sql",
    "html": "html", "css": "css", "scss": "scss",
    "json": "json", "yaml": "yaml", "yml": "yaml",
    "toml": "toml", "md": "markdown",
}


def _detect_language(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _EXT_TO_LANG.get(ext, "unknown")


class PRDiff(BaseModel):
    files: List[FileDiff] = []
    pr_title: str = ""
    pr_description: str = ""
    author: str = ""

# ---------------------------------------------------------------------------
# Patch parsing
# ---------------------------------------------------------------------------

def _parse_patch(patch: str) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Extract added and removed lines with their line numbers from a unified diff patch."""
    added: list[tuple[int, str]] = []
    removed: list[tuple[int, str]] = []
    if not patch:
        return added, removed

    new_lineno = 0
    old_lineno = 0

    for line in patch.splitlines():
        if line.startswith("@@"):
            # e.g. @@ -10,7 +10,8 @@
            m = re.search(r"@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@", line)
            if m:
                old_lineno = int(m.group("old")) - 1
                new_lineno = int(m.group("new")) - 1
        elif line.startswith("+") and not line.startswith("+++"):
            new_lineno += 1
            added.append((new_lineno, line[1:]))
        elif line.startswith("-") and not line.startswith("---"):
            old_lineno += 1
            removed.append((old_lineno, line[1:]))
        else:
            old_lineno += 1
            new_lineno += 1

    return added, removed


# ---------------------------------------------------------------------------
# PR URL parsing
# ---------------------------------------------------------------------------

_PR_URL_RE = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)"
)


def _parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    m = _PR_URL_RE.match(pr_url.strip())
    if not m:
        raise ValueError(f"Invalid GitHub PR URL: {pr_url!r}")
    return m.group("owner"), m.group("repo"), int(m.group("number"))


# ---------------------------------------------------------------------------
# GitHubClient
# ---------------------------------------------------------------------------

class GitHubClient(SCMClient):
    """Thin wrapper around PyGithub for PR-related operations."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token or settings.GITHUB_TOKEN
        self._gh = Github(self._token) if self._token else Github()

    def _get_pr(self, pr_url: str):
        owner, repo, number = _parse_pr_url(pr_url)
        return self._gh.get_repo(f"{owner}/{repo}").get_pull(number)

    # ------------------------------------------------------------------
    def get_change_set(self, target_url: str) -> list[FileDiff]:
        """Fetch per-file diffs for a GitHub Pull Request.

        Raises:
            GithubException: If GitHub rejects the request.
            ValueError: If *target_url* is invalid.
        """
        pr = self._get_pr(target_url)
        files: list[FileDiff] = []
        for f in pr.get_files():
            patch = f.patch or ""
            added, removed = _parse_patch(patch)
            files.append(FileDiff(
                filename=f.filename,
                language=_detect_language(f.filename),
                added_lines=added,
                removed_lines=removed,
                raw_diff=patch,
            ))
        return files

    def get_pr_diff(self, pr_url: str) -> PRDiff:
        """Backward-compatible wrapper returning both diff files and metadata."""
        pr = self._get_pr(pr_url)
        return PRDiff(
            files=self.get_change_set(pr_url),
            pr_title=pr.title or "",
            pr_description=pr.body or "",
            author=pr.user.login if pr.user else "",
        )

    # ------------------------------------------------------------------
    def get_metadata(self, target_url: str) -> dict[str, Any]:
        """Return a flat dict of PR metadata fields."""
        try:
            pr = self._get_pr(target_url)
            return {
                "number": pr.number,
                "title": pr.title,
                "body": pr.body or "",
                "author": pr.user.login if pr.user else "",
                "state": pr.state,
                "created_at": pr.created_at.isoformat() if pr.created_at else "",
                "updated_at": pr.updated_at.isoformat() if pr.updated_at else "",
                "merged": pr.merged,
                "base_branch": pr.base.ref,
                "head_branch": pr.head.ref,
                "additions": pr.additions,
                "deletions": pr.deletions,
                "changed_files": pr.changed_files,
                "url": pr.html_url,
            }
        except (GithubException, ValueError, Exception) as exc:
            logger.warning("Failed to fetch PR metadata for %s: %s", target_url, exc)
            return {}

    def get_pr_metadata(self, pr_url: str) -> dict[str, Any]:
        """Backward-compatible alias for metadata lookup."""
        return self.get_metadata(pr_url)

    # ------------------------------------------------------------------
    def post_summary_comment(self, target_url: str, body: str) -> bool:
        """Post a top-level review comment on the PR. Returns True on success."""
        try:
            pr = self._get_pr(target_url)
            pr.create_issue_comment(body)
            return True
        except (GithubException, ValueError, Exception):
            return False

    def post_review_comment(self, pr_url: str, body: str) -> bool:
        """Backward-compatible alias for top-level review comments."""
        return self.post_summary_comment(pr_url, body)

    # ------------------------------------------------------------------
    def post_inline_review(
        self,
        target_url: str,
        findings: list[dict],
        summary: str = "",
    ) -> bool:
        """Create a GitHub Pull Request Review with per-finding inline comments.

        Each entry in *findings* must have keys:
            file, line_start, severity, category, description, suggestion, confidence

        A single review object is created (``COMMENT`` event) so all inline
        comments appear in one batch. Returns True on success.
        """
        try:
            pr = self._get_pr(target_url)
            # Build the head commit SHA for the review
            commit = pr.get_commits().reversed[0]

            comments = []
            for f in findings:
                body = (
                    f"**[{f['severity']}] {f['category']}**\n\n"
                    f"{f['description']}\n\n"
                    f"**Suggestion:** {f['suggestion']}\n\n"
                    f"*Confidence: {f['confidence']:.0%} "
                    f"| Sources: {', '.join(f.get('source_agents', []))}*"
                )
                comments.append(
                    {
                        "path": f["file"],
                        "line": f["line_start"],
                        "body": body,
                    }
                )

            if not comments:
                return True

            pr.create_review(
                commit=commit,
                body=summary,
                event="COMMENT",
                comments=comments,
            )
            return True
        except (GithubException, ValueError, Exception):
            return False

    # ------------------------------------------------------------------
    def get_head_commit_sha(self, target_url: str) -> str | None:
        """Return the HEAD commit SHA of the PR, or None on error."""
        try:
            pr = self._get_pr(target_url)
            return pr.head.sha
        except (GithubException, ValueError, Exception):
            return None
