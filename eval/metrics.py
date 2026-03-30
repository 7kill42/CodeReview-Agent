"""Evaluation metrics for CodeReview-Agent findings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from agents.base import Finding


@dataclass
class EvalResult:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float


def match_findings(
    predicted: List[Finding],
    ground_truth: List[dict],
    line_tolerance: int = 5,
) -> tuple[int, int, int]:
    """Match predicted findings against ground-truth, return (TP, FP, FN)."""
    matched_gt: set[int] = set()
    matched_pred: set[int] = set()

    for pi, pred in enumerate(predicted):
        for gi, gt in enumerate(ground_truth):
            if gi in matched_gt:
                continue
            if (
                pred.file == gt["file"]
                and pred.category == gt["category"]
                and abs(pred.line_start - gt["line_start"]) <= line_tolerance
            ):
                matched_gt.add(gi)
                matched_pred.add(pi)
                break

    tp = len(matched_pred)
    fp = len(predicted) - tp
    fn = len(ground_truth) - len(matched_gt)
    return tp, fp, fn


def compute_metrics(
    predicted: List[Finding],
    ground_truth: List[dict],
    line_tolerance: int = 5,
) -> EvalResult:
    """Compute Precision / Recall / F1 for a single PR."""
    tp, fp, fn = match_findings(predicted, ground_truth, line_tolerance)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return EvalResult(tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1)


def evaluate_dataset(dataset_path: str, agent_results: List[dict]) -> dict:
    """Batch-evaluate over an entire dataset JSON file.

    Parameters
    ----------
    dataset_path:
        Path to a JSON file containing a list of entries, each with keys
        ``pr_url`` and ``human_findings``.
    agent_results:
        List of dicts, each with keys ``pr_url`` and ``findings``
        (list of dicts matching :class:`~agents.base.Finding` fields).

    Returns
    -------
    dict with keys ``precision``, ``recall``, ``f1``, ``tp``, ``fp``, ``fn``,
    and ``per_pr`` (list of per-PR :class:`EvalResult` dicts).
    """
    import json

    with open(dataset_path) as f:
        dataset = json.load(f)

    # Build lookup: pr_url -> ground-truth findings
    gt_map: dict[str, list] = {entry["pr_url"]: entry["human_findings"] for entry in dataset}
    # Build lookup: pr_url -> predicted findings
    pred_map: dict[str, list] = {r["pr_url"]: r["findings"] for r in agent_results}

    total_tp = total_fp = total_fn = 0
    per_pr: list[dict] = []

    for pr_url, gt_findings in gt_map.items():
        raw_preds = pred_map.get(pr_url, [])
        predictions = [
            Finding(**p) if isinstance(p, dict) else p
            for p in raw_preds
        ]
        result = compute_metrics(predictions, gt_findings)
        total_tp += result.tp
        total_fp += result.fp
        total_fn += result.fn
        per_pr.append({"pr_url": pr_url, **result.__dict__})

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0
    recall    = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1        = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "per_pr": per_pr,
    }
