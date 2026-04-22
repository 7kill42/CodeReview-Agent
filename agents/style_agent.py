"""Style Agent – checks code-style issues via Claude tool-use.

Checks performed on *added* lines only:
  1. Naming convention (camelCase vs snake_case, overly short names)
  2. Function length > 50 lines
  3. Missing docstrings on public functions / classes
  4. Magic numbers (bare numeric literals)
  5. Duplicate / similar code blocks
  6. Import hygiene (wildcard imports, unused imports)
"""
from __future__ import annotations

import textwrap
import time
from typing import Any, Dict, List

from config import settings
from llm.provider import LLMResponse, get_provider

from agents.base import AgentResult, BaseReviewAgent, FileDiff, Finding

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ADDED_LINES_PER_CHUNK = 200

# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------

REPORT_FINDINGS_TOOL: Dict[str, Any] = {
    "name": "report_style_findings",
    "description": (
        "Report all style findings discovered in the supplied code diff. "
        "Call this tool exactly once with the complete list of findings. "
        "If there are no issues, call it with an empty list."
    ),
    "input_schema": {
        "type": "object",
        "required": ["findings"],
        "properties": {
            "findings": {
                "type": "array",
                "description": "List of style findings (may be empty).",
                "items": {
                    "type": "object",
                    "required": [
                        "line_start", "line_end", "severity",
                        "category", "description", "suggestion", "confidence",
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
                                "naming | function_length | missing_docstring "
                                "| magic_number | code_duplication | import_hygiene"
                            ),
                        },
                        "description": {"type": "string"},
                        "suggestion":  {"type": "string"},
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                },
            }
        },
    },
}
# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(file_diff: FileDiff, chunk_added: List[tuple[int, str]]) -> str:
    """Build the user prompt for a single chunk of added lines."""
    added_block = "\n".join(
        f"  {lineno:4d} | {text}" for lineno, text in chunk_added
    )
    return textwrap.dedent(f"""\
        You are an expert code reviewer focusing on **style and readability only**.

        File: `{file_diff.filename}` (language: {file_diff.language})

        ## Task
        Review **only the newly added lines** shown below. Do NOT flag deleted lines
        or unchanged context lines. Report every finding by calling the
        `report_style_findings` tool.

        ## Style rules to enforce
        1. **Naming** – flag inconsistent conventions (e.g. camelCase in Python),
           single-letter or cryptic names (`x`, `tmp`, `d`, `n`).
        2. **Function length** – flag any function/method whose added body exceeds
           50 lines; suggest splitting it.
        3. **Missing docstrings** – flag public functions, methods, or classes that
           lack a docstring in the new code.
        4. **Magic numbers** – flag bare numeric literals used in logic (not in
           named-constant assignments).
        5. **Code duplication** – flag near-identical blocks that could be a helper.
        6. **Import hygiene** – flag `from x import *` and apparently unused imports.

        ## Added lines (format: line_number | code)
        {added_block}

        Call `report_style_findings` now with all findings (or an empty list).
    """)


# ---------------------------------------------------------------------------
# Chunking helper
# ---------------------------------------------------------------------------

def _chunk_added_lines(
    added_lines: List[tuple[int, str]],
    chunk_size: int,
) -> List[List[tuple[int, str]]]:
    """Split added_lines into sublists of at most chunk_size entries."""
    if not added_lines:
        return [[]]
    return [
        added_lines[i : i + chunk_size]
        for i in range(0, len(added_lines), chunk_size)
    ]


# ---------------------------------------------------------------------------
# Style Agent
# ---------------------------------------------------------------------------

class StyleAgent(BaseReviewAgent):
    """Style review agent.

    Input: ``FileDiff``
    Output: ``AgentResult`` with structured ``Finding`` entries
    Strategy: LLM review over newly added lines only
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        llm_config = settings.get_llm_config("STYLE_AGENT")
        self._model = model or llm_config.model
        self._provider = get_provider(
            provider=provider or llm_config.provider,
            api_key=api_key or llm_config.api_key or None,
            base_url=base_url or llm_config.base_url or None,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def review(self, file_diff: FileDiff) -> AgentResult:
        """Run a style review on *file_diff* and return an AgentResult."""
        start = time.monotonic()
        all_findings: List[Finding] = []
        total_tokens = 0

        chunks = _chunk_added_lines(file_diff.added_lines, MAX_ADDED_LINES_PER_CHUNK)
        for chunk in chunks:
            findings, tokens = self._call_claude(file_diff, chunk)
            all_findings.extend(findings)
            total_tokens += tokens

        return AgentResult(
            agent_name="StyleAgent",
            findings=all_findings,
            summary=self._build_summary(all_findings),
            execution_time=time.monotonic() - start,
            token_used=total_tokens,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_claude(
        self,
        file_diff: FileDiff,
        chunk_added: List[tuple[int, str]],
    ) -> tuple[List[Finding], int]:
        """Send one chunk to Claude and return (findings, tokens_used)."""
        prompt = _build_prompt(file_diff, chunk_added)
        response = self._provider.messages_create(
            model=self._model,
            max_tokens=4096,
            tools=[REPORT_FINDINGS_TOOL],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": prompt}],
        )
        return self._parse_response(response, file_diff.filename), response.total_tokens

    def _parse_response(
        self,
        response: LLMResponse,
        filename: str,
    ) -> List[Finding]:
        """Extract Finding objects from the tool-use block in *response*."""
        for block in response.tool_calls:
            if block.name != "report_style_findings":
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
        """Return a one-line summary of findings grouped by severity."""
        if not findings:
            return "No style issues found."
        counts: Dict[str, int] = {}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        parts = [f"{sev}: {n}" for sev, n in sorted(counts.items())]
        return f"Style review found {len(findings)} issue(s) – {', '.join(parts)}."
