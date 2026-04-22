"""Security Agent – detects security vulnerabilities via Semgrep + Claude tool-use.

Checks performed on *added* lines only:
  1. SQL injection (CWE-89)
  2. XSS / unsafe HTML injection (CWE-79)
  3. Hardcoded secrets / credentials (CWE-798)
  4. Path traversal (CWE-22)
  5. Command injection (CWE-78)
  6. Insecure deserialization (CWE-502)
  7. Use of dangerous / deprecated APIs
  8. Missing authentication / authorization checks
"""
from __future__ import annotations

import textwrap
import time
from typing import Any, Dict, List

from config import settings
from llm.provider import LLMResponse, get_provider

from agents.base import AgentResult, BaseReviewAgent, FileDiff, Finding
from tools.semgrep_runner import SemgrepRunner, SecurityIssue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ADDED_LINES_PER_CHUNK = 200

_SEVERITY_MAP = {
    "ERROR": "CRITICAL",
    "WARNING": "HIGH",
    "INFO": "MEDIUM",
}

# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------

REPORT_FINDINGS_TOOL: Dict[str, Any] = {
    "name": "report_security_findings",
    "description": (
        "Report all security findings discovered in the supplied code diff. "
        "Call this tool exactly once with the complete list of findings. "
        "If there are no issues, call it with an empty list."
    ),
    "input_schema": {
        "type": "object",
        "required": ["findings"],
        "properties": {
            "findings": {
                "type": "array",
                "description": "List of security findings (may be empty).",
                "items": {
                    "type": "object",
                    "required": [
                        "line_start", "line_end", "severity",
                        "category", "description", "suggestion",
                        "confidence", "cwe",
                    ],
                    "properties": {
                        "line_start": {"type": "integer"},
                        "line_end":   {"type": "integer"},
                        "severity": {
                            "type": "string",
                            "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        },
                        "category": {
                            "type": "string",
                            "description": (
                                "sql_injection | xss | hardcoded_secret "
                                "| path_traversal | command_injection "
                                "| insecure_deserialization | dangerous_api "
                                "| missing_auth | other"
                            ),
                        },
                        "cwe": {
                            "type": "string",
                            "description": "CWE identifier, e.g. CWE-89",
                        },
                        "description": {"type": "string"},
                        "suggestion":  {"type": "string"},
                        "confidence":  {"type": "number"},
                    },
                },
            }
        },
    },
}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class SecurityAgent(BaseReviewAgent):
    """Security review agent.

    Input: ``FileDiff``
    Output: ``AgentResult`` with structured ``Finding`` entries
    Strategy: Semgrep pre-scan plus LLM validation
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        llm_config = settings.get_llm_config("SECURITY_AGENT")
        self._model = model or llm_config.model
        self._provider = get_provider(
            provider=provider or llm_config.provider,
            api_key=api_key or llm_config.api_key or None,
            base_url=base_url or llm_config.base_url or None,
        )
        self._semgrep = SemgrepRunner()

    # ------------------------------------------------------------------
    async def review(self, file_diff: FileDiff) -> AgentResult:
        start = time.monotonic()
        if not file_diff.added_lines:
            return AgentResult(
                agent_name="SecurityAgent",
                findings=[],
                summary="No added lines to review.",
                execution_time=time.monotonic() - start,
                token_used=0,
            )

        # Run Semgrep on the added code first
        semgrep_issues = self._run_semgrep(file_diff)

        all_findings: List[Finding] = []
        total_tokens = 0

        # Process in chunks
        chunks = self._chunk_lines(file_diff.added_lines)
        for chunk in chunks:
            findings, tokens = self._review_chunk(
                chunk, file_diff.filename, file_diff.language, semgrep_issues
            )
            all_findings.extend(findings)
            total_tokens += tokens

        return AgentResult(
            agent_name="SecurityAgent",
            findings=all_findings,
            summary=self._build_summary(all_findings),
            execution_time=time.monotonic() - start,
            token_used=total_tokens,
        )

    # ------------------------------------------------------------------
    def _run_semgrep(self, file_diff: FileDiff) -> List[SecurityIssue]:
        """Run Semgrep on the raw diff content."""
        code = "\n".join(line for _, line in file_diff.added_lines)
        lang = file_diff.language
        try:
            return self._semgrep.scan(code, lang)
        except Exception:
            return []

    @staticmethod
    def _chunk_lines(
        lines: List[tuple[int, str]],
        size: int = MAX_ADDED_LINES_PER_CHUNK,
    ) -> List[List[tuple[int, str]]]:
        return [lines[i: i + size] for i in range(0, max(len(lines), 1), size)]

    def _review_chunk(
        self,
        chunk: List[tuple[int, str]],
        filename: str,
        language: str,
        semgrep_issues: List[SecurityIssue],
    ) -> tuple[List[Finding], int]:
        """Send one chunk to Claude and return (findings, tokens)."""
        code_block = "\n".join(f"{ln:4d} | {text}" for ln, text in chunk)

        semgrep_ctx = ""
        if semgrep_issues:
            lines_ctx = []
            for iss in semgrep_issues:
                lines_ctx.append(
                    f"  - Line {iss.line}: [{iss.rule_id}] {iss.message}"
                    + (f" ({iss.cwe})" if iss.cwe else "")
                )
            semgrep_ctx = (
                "\n\nStatic analysis pre-scan found these potential issues "
                "(use as hints, validate each one):\n" + "\n".join(lines_ctx)
            )

        prompt = textwrap.dedent(f"""\
            You are a senior security engineer performing a code security review.
            Review the following {language} code diff (added lines only) from `{filename}`.

            Focus on these vulnerability classes:
            - SQL Injection (CWE-89)
            - Cross-Site Scripting / XSS (CWE-79)
            - Hardcoded secrets, passwords, API keys (CWE-798)
            - Path traversal / directory traversal (CWE-22)
            - Command injection / OS injection (CWE-78)
            - Insecure deserialization (CWE-502)
            - Use of dangerous or deprecated APIs
            - Missing authentication or authorization checks

            Rules:
            - Only report issues in the shown code (added lines).
            - Be precise about line numbers.
            - Avoid false positives: only report when you are reasonably confident.
            - Set confidence between 0.0 and 1.0.
            - For CRITICAL findings, confidence must be ≥ 0.7.
            - Provide a concrete remediation suggestion for each finding.
            {semgrep_ctx}

            Code diff:
            ```{language}
            {code_block}
            ```

            Call the `report_security_findings` tool with your results.
        """)

        response = self._provider.messages_create(
            model=self._model,
            max_tokens=2048,
            tools=[REPORT_FINDINGS_TOOL],
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": prompt}],
        )
        findings = self._parse_findings(response, filename)
        return findings, response.total_tokens

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_findings(
        response: "LLMResponse", filename: str
    ) -> List[Finding]:
        for block in response.tool_calls:
            if block.name != "report_security_findings":
                continue
            raw: List[Dict[str, Any]] = block.input.get("findings", [])
            results: List[Finding] = []
            for item in raw:
                try:
                    results.append(
                        Finding(
                            file=filename,
                            line_start=item["line_start"],
                            line_end=item["line_end"],
                            severity=item["severity"],
                            category=item["category"],
                            description=item["description"],
                            suggestion=item["suggestion"],
                            confidence=float(item["confidence"]),
                        )
                    )
                except (KeyError, ValueError):
                    continue
            return results
        return []

    @staticmethod
    def _build_summary(findings: List[Finding]) -> str:
        if not findings:
            return "No security issues found."
        counts: Dict[str, int] = {}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        parts = [f"{sev}: {n}" for sev, n in sorted(counts.items())]
        return f"Security review found {len(findings)} issue(s) – {', '.join(parts)}."
