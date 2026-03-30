"""Tests for eval/metrics.py."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from agents.base import Finding
from eval.metrics import EvalResult, compute_metrics, evaluate_dataset, match_findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(
    file: str = "src/auth.py",
    line_start: int = 42,
    category: str = "sql_injection",
    severity: str = "CRITICAL",
) -> Finding:
    return Finding(
        file=file,
        line_start=line_start,
        line_end=line_start,
        severity=severity,
        category=category,
        description="test",
        suggestion="fix it",
        confidence=0.9,
    )


def _gt(
    file: str = "src/auth.py",
    line_start: int = 42,
    category: str = "sql_injection",
    severity: str = "CRITICAL",
) -> dict:
    return {
        "file": file,
        "line_start": line_start,
        "line_end": line_start,
        "severity": severity,
        "category": category,
        "description": "SQL injection via string format",
    }


# ---------------------------------------------------------------------------
# match_findings
# ---------------------------------------------------------------------------

class TestMatchFindings:
    def test_perfect_match(self):
        pred = [_finding()]
        gt   = [_gt()]
        tp, fp, fn = match_findings(pred, gt)
        assert tp == 1
        assert fp == 0
        assert fn == 0

    def test_no_predictions(self):
        tp, fp, fn = match_findings([], [_gt()])
        assert tp == 0
        assert fp == 0
        assert fn == 1

    def test_all_false_positives(self):
        pred = [_finding(category="bare_except")]
        gt   = [_gt(category="sql_injection")]
        tp, fp, fn = match_findings(pred, gt)
        assert tp == 0
        assert fp == 1
        assert fn == 1

    def test_line_tolerance_within(self):
        """Line difference == 5 should still match."""
        pred = [_finding(line_start=47)]
        gt   = [_gt(line_start=42)]
        tp, fp, fn = match_findings(pred, gt, line_tolerance=5)
        assert tp == 1

    def test_line_tolerance_exceeded(self):
        """Line difference == 6 should NOT match."""
        pred = [_finding(line_start=48)]
        gt   = [_gt(line_start=42)]
        tp, fp, fn = match_findings(pred, gt, line_tolerance=5)
        assert tp == 0
        assert fp == 1
        assert fn == 1

    def test_different_file_no_match(self):
        pred = [_finding(file="other.py")]
        gt   = [_gt(file="src/auth.py")]
        tp, fp, fn = match_findings(pred, gt)
        assert tp == 0

    def test_each_gt_matched_at_most_once(self):
        """Two identical predictions should not both match the same GT entry."""
        pred = [_finding(), _finding()]
        gt   = [_gt()]
        tp, fp, fn = match_findings(pred, gt)
        assert tp == 1
        assert fp == 1
        assert fn == 0


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def test_perfect_match(self):
        result = compute_metrics([_finding()], [_gt()])
        assert result.precision == pytest.approx(1.0)
        assert result.recall    == pytest.approx(1.0)
        assert result.f1        == pytest.approx(1.0)

    def test_no_predictions(self):
        """No predictions: precision=1.0 (no FP), recall=0.0."""
        result = compute_metrics([], [_gt()])
        assert result.precision == pytest.approx(1.0)
        assert result.recall    == pytest.approx(0.0)
        assert result.f1        == pytest.approx(0.0)

    def test_all_false_positives(self):
        pred = [_finding(category="bare_except")]
        gt   = [_gt(category="sql_injection")]
        result = compute_metrics(pred, gt)
        assert result.precision == pytest.approx(0.0)
        assert result.recall    == pytest.approx(0.0)
        assert result.f1        == pytest.approx(0.0)

    def test_partial_match(self):
        """1 TP, 1 FP, 1 FN → precision=0.5, recall=0.5, f1=0.5."""
        pred = [_finding(line_start=42), _finding(line_start=99, category="bare_except")]
        gt   = [_gt(line_start=42), _gt(line_start=10, category="null_deref")]
        result = compute_metrics(pred, gt)
        assert result.tp == 1
        assert result.fp == 1
        assert result.fn == 1
        assert result.precision == pytest.approx(0.5)
        assert result.recall    == pytest.approx(0.5)
        assert result.f1        == pytest.approx(0.5)

    def test_empty_both(self):
        """No predictions, no GT: precision=1.0, recall=0.0, f1=0.0."""
        result = compute_metrics([], [])
        assert result.precision == pytest.approx(1.0)
        assert result.recall    == pytest.approx(0.0)
        assert result.f1        == pytest.approx(0.0)

    def test_returns_eval_result(self):
        result = compute_metrics([_finding()], [_gt()])
        assert isinstance(result, EvalResult)


# ---------------------------------------------------------------------------
# evaluate_dataset
# ---------------------------------------------------------------------------

class TestEvaluateDataset:
    def _write_dataset(self, entries: list) -> str:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump(entries, f)
        f.close()
        return f.name

    def teardown_method(self):
        # clean up any temp files created during tests
        pass

    def test_perfect_dataset(self):
        dataset = [
            {
                "pr_url": "https://github.com/owner/repo/pull/1",
                "human_findings": [_gt()],
            }
        ]
        agent_results = [
            {
                "pr_url": "https://github.com/owner/repo/pull/1",
                "findings": [_finding().__dict__],
            }
        ]
        path = self._write_dataset(dataset)
        try:
            out = evaluate_dataset(path, agent_results)
        finally:
            os.unlink(path)

        assert out["precision"] == pytest.approx(1.0)
        assert out["recall"]    == pytest.approx(1.0)
        assert out["f1"]        == pytest.approx(1.0)
        assert len(out["per_pr"]) == 1

    def test_no_predictions_dataset(self):
        dataset = [
            {
                "pr_url": "https://github.com/owner/repo/pull/2",
                "human_findings": [_gt()],
            }
        ]
        agent_results = [
            {
                "pr_url": "https://github.com/owner/repo/pull/2",
                "findings": [],
            }
        ]
        path = self._write_dataset(dataset)
        try:
            out = evaluate_dataset(path, agent_results)
        finally:
            os.unlink(path)

        assert out["recall"]    == pytest.approx(0.0)
        assert out["precision"] == pytest.approx(1.0)

    def test_missing_pr_treated_as_no_predictions(self):
        """If a PR has no entry in agent_results, it counts as 0 predictions."""
        dataset = [
            {
                "pr_url": "https://github.com/owner/repo/pull/3",
                "human_findings": [_gt()],
            }
        ]
        path = self._write_dataset(dataset)
        try:
            out = evaluate_dataset(path, [])
        finally:
            os.unlink(path)

        assert out["fn"] == 1
        assert out["tp"] == 0
