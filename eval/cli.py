from __future__ import annotations

import argparse
import json

from eval.harness import compare_models, create_eval_client, evaluate_document, json_ready_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DocExtract evaluation harness")
    parser.add_argument("--document-id", action="append", required=True, help="Document id to evaluate")
    parser.add_argument("--model", default="v1", help="Model version for single-model evaluation")
    parser.add_argument("--runs", type=int, default=5, help="Number of seeded runs per document")
    parser.add_argument("--compare-models", action="store_true", help="Run v1 vs v2 comparison")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    client = create_eval_client(disable_noise=True)
    seeds = list(range(args.runs))

    if args.compare_models:
        report = compare_models(client, document_ids=args.document_id, seeds=seeds)
    else:
        report = {
            "documents": {
                document_id: evaluate_document(client, document_id=document_id, model=args.model, seeds=seeds)
                for document_id in args.document_id
            }
        }

    print(json.dumps(json_ready_report(report), indent=2))


if __name__ == "__main__":
    main()
