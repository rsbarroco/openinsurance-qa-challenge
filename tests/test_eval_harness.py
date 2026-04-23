from __future__ import annotations

from eval.harness import compare_models, evaluate_document, evaluate_run


def test_compare_models_surfaces_known_model_tradeoffs(eval_client) -> None:
    report = compare_models(
        eval_client,
        document_ids=["sov_pacific_realty", "loss_run_libertymutual"],
        seeds=range(5),
    )

    pacific = report["documents"]["sov_pacific_realty"]
    liberty = report["documents"]["loss_run_libertymutual"]

    assert (
        pacific["v2"]["field_summary"]["total_tiv"]["match_rate"]
        > pacific["v1"]["field_summary"]["total_tiv"]["match_rate"]
    )
    assert (
        liberty["v2"]["metrics"]["field_match_rate"]["mean"]
        < liberty["v1"]["metrics"]["field_match_rate"]["mean"]
    )
    assert (
        liberty["v2"]["invariant_summary"]["loss_run.total_incurred_matches_claim_sum"]["pass_rate"]
        < liberty["v1"]["invariant_summary"]["loss_run.total_incurred_matches_claim_sum"]["pass_rate"]
    )


def test_partial_truth_unknown_square_footage_is_not_scored(eval_client) -> None:
    run = evaluate_run(eval_client, document_id="sov_acme_properties", model="v1", seed=0)
    partial_paths = [result for result in run["field_results"] if result["status"] == "not_scored"]

    assert any(path["path"].endswith(".square_footage") for path in partial_paths)


def test_wrong_high_confidence_classification_is_visible(eval_client) -> None:
    run = evaluate_run(eval_client, document_id="coi_travelers_umbrella", model="v1", seed=0)

    assert run["classification_correct"] is False
    assert run["classification_confidence"] >= 95.0
    assert run["decision"] == "reject"


def test_unlabeled_document_falls_back_to_label_free_checks(eval_client) -> None:
    summary = evaluate_document(eval_client, document_id="coi_unlabeled_mystery", model="v1", seeds=[0, 1, 2])

    assert summary["metrics"]["field_match_rate"]["mean"] is None
    assert summary["metrics"]["invariant_pass_rate"]["mean"] == 1.0
    assert summary["decision_counts"]["human_review"] == 3
