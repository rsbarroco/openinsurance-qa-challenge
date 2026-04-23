"""Reusable evaluation harness for the DocExtract challenge."""

from eval.harness import (
    compare_models,
    create_eval_client,
    evaluate_document,
    evaluate_run,
    load_truth_bundle,
)

__all__ = [
    "compare_models",
    "create_eval_client",
    "evaluate_document",
    "evaluate_run",
    "load_truth_bundle",
]
