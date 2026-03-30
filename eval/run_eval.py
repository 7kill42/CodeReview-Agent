#!/usr/bin/env python3
"""CLI entry point for batch evaluation.

Usage:
    python eval/run_eval.py --dataset eval/data/ground_truth.json \
                            --results eval/data/agent_results.json

The dataset JSON must be a list of {"pr_url": ..., "human_findings": [...]}
The results JSON must be a list of {"pr_url": ..., "findings": [...]}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.metrics import evaluate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-evaluate CodeReview-Agent findings.")
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to ground-truth dataset JSON file.",
    )
    parser.add_argument(
        "--results",
        required=True,
        help="Path to agent results JSON file.",
    )
    parser.add_argument(
        "--line-tolerance",
        type=int,
        default=5,
        dest="line_tolerance",
        help="Max line distance to consider two findings a match (default: 5).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to write the JSON report to.",
    )
    args = parser.parse_args()

    with open(args.results) as f:
        agent_results: list[dict] = json.load(f)

    summary = evaluate_dataset(args.dataset, agent_results)

    print(f"Precision : {summary['precision']:.4f}")
    print(f"Recall    : {summary['recall']:.4f}")
    print(f"F1        : {summary['f1']:.4f}")
    print(f"TP={summary['tp']}  FP={summary['fp']}  FN={summary['fn']}")
    print(f"PRs evaluated: {len(summary['per_pr'])}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\nFull report written to {args.output}")


if __name__ == "__main__":
    main()
