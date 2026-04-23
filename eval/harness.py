from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app import config
from app.main import app
from app.schemas import (
    BinderExtraction,
    COIExtraction,
    EndorsementExtraction,
    LossRunExtraction,
    SOVExtraction,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
GROUND_TRUTH_DIR = DATA_DIR / "ground_truth"
GROUND_TRUTH_ALT_DIR = DATA_DIR / "ground_truth_alt"
DOCUMENTS_DIR = DATA_DIR / "documents"

SCHEMA_BY_DOC_TYPE: dict[str, type[BaseModel]] = {
    "sov": SOVExtraction,
    "coi": COIExtraction,
    "loss_run": LossRunExtraction,
    "endorsement": EndorsementExtraction,
    "binder": BinderExtraction,
}

LIST_FIELD_CONFIG = {
    "sov": ("properties", lambda item: _compound_key(item, ("address", "city", "state"))),
    "coi": ("coverages", lambda item: _compound_key(item, ("coverage_type", "policy_number"))),
    "binder": ("coverages", lambda item: _compound_key(item, ("coverage_type", "policy_number"))),
    "loss_run": ("claims", lambda item: _compound_key(item, ("claim_number",))),
}

FIELD_WEIGHTS = {
    "classification": 0.15,
    "field_match": 0.55,
    "invariants": 0.20,
    "schema": 0.10,
}

MONEY_FIELDS = {
    "building_value",
    "contents_value",
    "business_income_value",
    "total_insured_value",
    "total_tiv",
    "each_occurrence_limit",
    "general_aggregate_limit",
    "products_completed_ops",
    "paid_amount",
    "reserved_amount",
    "total_incurred",
    "total_paid",
    "total_recoveries",
    "premium_delta",
}

STRINGIFIED_MONEY_FIELDS = {"old_value", "new_value"}
DATE_FIELDS = {
    "effective_date",
    "expiration_date",
    "date_of_loss",
    "policy_effective_date",
    "valuation_date",
    "binder_effective_date",
    "binder_expiration_date",
    "endorsement_effective_date",
}
CANONICAL_CARRIERS = {
    "hartford": "hartford financial services",
    "the hartford": "hartford financial services",
    "hartford financial services": "hartford financial services",
    "travelers": "the travelers indemnity company",
    "travelers insurance": "the travelers indemnity company",
    "the travelers indemnity company": "the travelers indemnity company",
    "zurich": "zurich insurance",
    "zurich north america": "zurich insurance",
    "zurich insurance": "zurich insurance",
    "nationwide": "nationwide insurance",
    "nationwide mutual": "nationwide insurance",
    "nationwide insurance": "nationwide insurance",
    "liberty mutual": "liberty mutual insurance",
    "liberty mutual insurance": "liberty mutual insurance",
    "liberty mutual fire insurance company": "liberty mutual fire insurance company",
    "chubb": "chubb commercial insurance",
    "chubb commercial insurance": "chubb commercial insurance",
    "xl catlin commercial": "xl catlin commercial",
    "cna insurance": "cna insurance",
}
TEXT_NORMALIZATION_RE = re.compile(r"\s+")
NON_NUMERIC_RE = re.compile(r"[^0-9.\-]")


@dataclass
class TruthBundle:
    document_id: str
    doc_type: str | None
    primary_extraction: dict[str, Any] | None
    alt_field_values: dict[str, Any]
    partial_field_paths: set[str]
    source_document: dict[str, Any] | None
    has_ground_truth: bool


def _compound_key(item: dict[str, Any], fields: tuple[str, ...]) -> str:
    return "|".join(_normalize_text(item.get(field)) or "<missing>" for field in fields)


def create_eval_client(disable_noise: bool = True) -> TestClient:
    if disable_noise:
        config.LATENCY_ENABLED = False
        config.FAILURES_ENABLED = False
        config.RATELIMIT_ENABLED = False
    return TestClient(app)


def load_truth_bundle(document_id: str) -> TruthBundle:
    truth_path = GROUND_TRUTH_DIR / f"{document_id}.json"
    alt_path = GROUND_TRUTH_ALT_DIR / f"{document_id}.json"
    source_path = DOCUMENTS_DIR / f"{document_id}.json"

    primary_payload: dict[str, Any] | None = None
    alt_payload: dict[str, Any] | None = None
    source_payload: dict[str, Any] | None = None

    if truth_path.is_file():
        primary_payload = json.loads(truth_path.read_text(encoding="utf-8"))
    if alt_path.is_file():
        alt_payload = json.loads(alt_path.read_text(encoding="utf-8"))
    if source_path.is_file():
        source_payload = json.loads(source_path.read_text(encoding="utf-8"))

    if primary_payload is None:
        return TruthBundle(
            document_id=document_id,
            doc_type=None,
            primary_extraction=None,
            alt_field_values={},
            partial_field_paths=set(),
            source_document=source_payload,
            has_ground_truth=False,
        )

    doc_type = primary_payload["doc_type"]
    partial_paths = _build_partial_field_paths(primary_payload, doc_type)
    alt_values: dict[str, Any] = {}
    if alt_payload and alt_payload.get("extraction"):
        alt_values = flatten_extraction(doc_type, alt_payload["extraction"])

    return TruthBundle(
        document_id=document_id,
        doc_type=doc_type,
        primary_extraction=primary_payload["extraction"],
        alt_field_values=alt_values,
        partial_field_paths=partial_paths,
        source_document=source_payload,
        has_ground_truth=True,
    )


def _build_partial_field_paths(payload: dict[str, Any], doc_type: str) -> set[str]:
    partial_paths: set[str] = set()
    if doc_type != "sov":
        return partial_paths

    properties = payload.get("extraction", {}).get("properties", [])
    for entry in payload.get("partial_truth_fields", []):
        property_index = entry.get("property_index")
        field_name = entry.get("field")
        if property_index is None or field_name is None:
            continue
        if 0 <= property_index < len(properties):
            key = LIST_FIELD_CONFIG["sov"][1](properties[property_index])
            partial_paths.add(f"properties[{key}].{field_name}")
    return partial_paths


def flatten_extraction(doc_type: str, extraction: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    list_config = LIST_FIELD_CONFIG.get(doc_type)
    list_field = list_config[0] if list_config else None
    key_builder = list_config[1] if list_config else None

    for key, value in extraction.items():
        if key == list_field and isinstance(value, list):
            for item in value:
                item_key = key_builder(item)
                for child_key, child_value in item.items():
                    flat[f"{key}[{item_key}].{child_key}"] = child_value
        else:
            flat[key] = value
    return flat


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    text = TEXT_NORMALIZATION_RE.sub(" ", text)
    text = (
        text.replace("street", "st")
        .replace("avenue", "ave")
        .replace("boulevard", "blvd")
        .replace("road", "rd")
    )
    return text


def _parse_money(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    is_negative = text.startswith("(") and text.endswith(")")
    text = text.replace(",", "")
    text = text.replace("$", "")
    text = text.replace("%", "")
    text = text.replace("(", "").replace(")", "")
    try:
        parsed = float(text)
    except ValueError:
        return None
    return -parsed if is_negative else parsed


def _date_candidates(value: Any) -> set[str]:
    if value is None:
        return set()
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return {text}
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
        a, b, year = text.split("/")
        month_first = _valid_iso_date(int(year), int(a), int(b))
        day_first = _valid_iso_date(int(year), int(b), int(a))
        candidates = {candidate for candidate in (month_first, day_first) if candidate}
        return candidates
    return set()


def _valid_iso_date(year: int, month: int, day: int) -> str | None:
    try:
        from datetime import date

        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _canonical_carrier(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    return CANONICAL_CARRIERS.get(normalized, normalized)


def _is_amount_field(field_name: str) -> bool:
    return field_name in MONEY_FIELDS or field_name in STRINGIFIED_MONEY_FIELDS


def _is_date_field(field_name: str) -> bool:
    return field_name in DATE_FIELDS


def _numeric_close(field_name: str, expected: float, actual: float) -> bool:
    if field_name == "loss_ratio":
        return math.isclose(expected, actual, rel_tol=0.03, abs_tol=0.01)
    return math.isclose(expected, actual, rel_tol=0.03, abs_tol=100.0)


def _compare_values(path: str, expected: Any, actual: Any, alt_expected: Any | None = None) -> tuple[bool, str]:
    field_name = path.split(".")[-1]
    if expected is None and actual is None:
        return True, "both_null"
    if expected is None and actual is not None:
        return False, "unexpected_value"
    if expected is not None and actual is None:
        return False, "missing_value"

    if field_name == "carrier":
        options = {_canonical_carrier(expected)}
        if alt_expected is not None:
            options.add(_canonical_carrier(alt_expected))
        return _canonical_carrier(actual) in options, "carrier_canonicalized"

    if _is_date_field(field_name):
        expected_candidates = _date_candidates(expected)
        if alt_expected is not None:
            expected_candidates |= _date_candidates(alt_expected)
        actual_candidates = _date_candidates(actual)
        return bool(expected_candidates & actual_candidates), "date_normalized"

    if _is_amount_field(field_name) or field_name == "loss_ratio":
        actual_number = _parse_money(actual)
        if actual_number is None:
            return False, "invalid_numeric"
        expected_numbers = [_parse_money(expected)]
        if alt_expected is not None:
            expected_numbers.append(_parse_money(alt_expected))
        return any(
            number is not None and _numeric_close(field_name, number, actual_number)
            for number in expected_numbers
        ), "numeric_tolerance"

    if isinstance(expected, str) or isinstance(actual, str):
        normalized_actual = _normalize_text(actual)
        normalized_expected = {_normalize_text(expected)}
        if alt_expected is not None:
            normalized_expected.add(_normalize_text(alt_expected))
        return normalized_actual in normalized_expected, "text_normalized"

    return expected == actual or actual == alt_expected, "exact_match"


def validate_extraction(doc_type: str | None, extraction: dict[str, Any]) -> tuple[bool, list[str]]:
    if doc_type is None:
        return False, ["missing_doc_type"]
    schema = SCHEMA_BY_DOC_TYPE.get(doc_type)
    if schema is None:
        return False, [f"unsupported_doc_type:{doc_type}"]
    try:
        schema.model_validate(extraction)
        return True, []
    except ValidationError as exc:
        return False, [error["loc"] for error in exc.errors()]


def evaluate_invariants(doc_type: str | None, extraction: dict[str, Any]) -> list[dict[str, Any]]:
    if doc_type == "sov":
        return _evaluate_sov_invariants(extraction)
    if doc_type == "coi":
        return _evaluate_coverage_date_invariants(extraction.get("coverages", []), prefix="coi")
    if doc_type == "binder":
        return _evaluate_binder_invariants(extraction)
    if doc_type == "loss_run":
        return _evaluate_loss_run_invariants(extraction)
    if doc_type == "endorsement":
        return _evaluate_endorsement_invariants(extraction)
    return []


def _evaluate_sov_invariants(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    properties = extraction.get("properties", [])
    for prop in properties:
        property_key = LIST_FIELD_CONFIG["sov"][1](prop)
        component_sum = sum(
            _parse_money(prop.get(field)) or 0.0
            for field in ("building_value", "contents_value", "business_income_value")
        )
        total_value = _parse_money(prop.get("total_insured_value")) or 0.0
        results.append(
            {
                "name": f"sov.property_components_match_total[{property_key}]",
                "passed": _numeric_close("total_insured_value", component_sum, total_value),
                "details": {"component_sum": component_sum, "total_insured_value": total_value},
                "severity": "high",
            }
        )
    total_tiv = _parse_money(extraction.get("total_tiv")) or 0.0
    property_sum = sum(_parse_money(prop.get("total_insured_value")) or 0.0 for prop in properties)
    results.append(
        {
            "name": "sov.total_tiv_matches_property_sum",
            "passed": _numeric_close("total_tiv", property_sum, total_tiv),
            "details": {"property_sum": property_sum, "total_tiv": total_tiv},
            "severity": "critical",
        }
    )
    return results


def _evaluate_coverage_date_invariants(
    coverages: list[dict[str, Any]], prefix: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for coverage in coverages:
        coverage_key = _compound_key(coverage, ("coverage_type", "policy_number"))
        start_candidates = _date_candidates(coverage.get("effective_date"))
        end_candidates = _date_candidates(coverage.get("expiration_date"))
        passed = any(start <= end for start in start_candidates for end in end_candidates)
        results.append(
            {
                "name": f"{prefix}.coverage_date_order[{coverage_key}]",
                "passed": passed,
                "details": {
                    "effective_date": coverage.get("effective_date"),
                    "expiration_date": coverage.get("expiration_date"),
                },
                "severity": "high",
            }
        )
    return results


def _evaluate_binder_invariants(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    results = _evaluate_coverage_date_invariants(extraction.get("coverages", []), prefix="binder")
    start_candidates = _date_candidates(extraction.get("binder_effective_date"))
    end_candidates = _date_candidates(extraction.get("binder_expiration_date"))
    passed = any(start <= end for start in start_candidates for end in end_candidates)
    results.append(
        {
            "name": "binder.date_order",
            "passed": passed,
            "details": {
                "binder_effective_date": extraction.get("binder_effective_date"),
                "binder_expiration_date": extraction.get("binder_expiration_date"),
            },
            "severity": "critical",
        }
    )
    return results


def _evaluate_loss_run_invariants(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    claims = extraction.get("claims", [])

    for claim in claims:
        claim_key = claim.get("claim_number", "<missing>")
        paid = _parse_money(claim.get("paid_amount")) or 0.0
        reserved = _parse_money(claim.get("reserved_amount")) or 0.0
        total = _parse_money(claim.get("total_incurred")) or 0.0
        results.append(
            {
                "name": f"loss_run.claim_total_matches_components[{claim_key}]",
                "passed": _numeric_close("total_incurred", paid + reserved, total),
                "details": {"paid_amount": paid, "reserved_amount": reserved, "total_incurred": total},
                "severity": "high",
            }
        )
        if claim.get("status") == "closed":
            results.append(
                {
                    "name": f"loss_run.closed_claim_has_zero_reserve[{claim_key}]",
                    "passed": _numeric_close("reserved_amount", 0.0, reserved),
                    "details": {"reserved_amount": reserved},
                    "severity": "medium",
                }
            )

    total_paid = _parse_money(extraction.get("total_paid")) or 0.0
    total_incurred = _parse_money(extraction.get("total_incurred")) or 0.0
    total_recoveries = _parse_money(extraction.get("total_recoveries")) or 0.0
    claim_paid_sum = sum(_parse_money(claim.get("paid_amount")) or 0.0 for claim in claims)
    claim_incurred_sum = sum(_parse_money(claim.get("total_incurred")) or 0.0 for claim in claims)
    recoveries_sum = sum(
        -(_parse_money(claim.get("paid_amount")) or 0.0)
        for claim in claims
        if (_parse_money(claim.get("paid_amount")) or 0.0) < 0
    )

    results.extend(
        [
            {
                "name": "loss_run.total_paid_matches_claim_sum",
                "passed": _numeric_close("total_paid", claim_paid_sum, total_paid),
                "details": {"claim_paid_sum": claim_paid_sum, "total_paid": total_paid},
                "severity": "critical",
            },
            {
                "name": "loss_run.total_incurred_matches_claim_sum",
                "passed": _numeric_close("total_incurred", claim_incurred_sum, total_incurred),
                "details": {"claim_total_incurred_sum": claim_incurred_sum, "total_incurred": total_incurred},
                "severity": "critical",
            },
            {
                "name": "loss_run.total_recoveries_matches_negative_paid_sum",
                "passed": _numeric_close("total_recoveries", recoveries_sum, total_recoveries),
                "details": {"recoveries_sum": recoveries_sum, "total_recoveries": total_recoveries},
                "severity": "high",
            },
        ]
    )
    return results


def _evaluate_endorsement_invariants(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    premium_delta = _parse_money(extraction.get("premium_delta"))
    return [
        {
            "name": "endorsement.premium_delta_is_numeric_when_present",
            "passed": premium_delta is not None or extraction.get("premium_delta") is None,
            "details": {"premium_delta": extraction.get("premium_delta")},
            "severity": "medium",
        }
    ]


def evaluate_run(
    client: TestClient,
    document_id: str,
    model: str = "v1",
    seed: int | None = None,
) -> dict[str, Any]:
    truth = load_truth_bundle(document_id)
    response = client.post("/extract", json={"document_id": document_id, "model": model, "seed": seed})
    if response.status_code != 200:
        return {
            "document_id": document_id,
            "model": model,
            "seed": seed,
            "request_ok": False,
            "http_status": response.status_code,
            "error": response.text,
        }

    payload = response.json()
    predicted_doc_type = payload["classification"]["doc_type"]
    comparison_doc_type = truth.doc_type or predicted_doc_type
    schema_valid, schema_errors = validate_extraction(comparison_doc_type, payload["extraction"])
    invariants = evaluate_invariants(comparison_doc_type, payload["extraction"])

    field_results: list[dict[str, Any]] = []
    field_match_rate: float | None = None
    total_scored_fields = 0
    if truth.has_ground_truth and truth.primary_extraction is not None:
        expected_flat = flatten_extraction(truth.doc_type or predicted_doc_type, truth.primary_extraction)
        actual_flat = flatten_extraction(truth.doc_type or predicted_doc_type, payload["extraction"])
        all_paths = sorted(set(expected_flat) | set(actual_flat))
        for path in all_paths:
            if path in truth.partial_field_paths:
                field_results.append(
                    {
                        "path": path,
                        "status": "not_scored",
                        "score": None,
                        "expected": expected_flat.get(path),
                        "actual": actual_flat.get(path),
                        "note": "partial_truth_unknown",
                    }
                )
                continue
            if path not in expected_flat:
                field_results.append(
                    {
                        "path": path,
                        "status": "extra",
                        "score": 0.0,
                        "expected": None,
                        "actual": actual_flat.get(path),
                        "note": "hallucinated_or_unexpected_field",
                    }
                )
                total_scored_fields += 1
                continue
            if path not in actual_flat:
                field_results.append(
                    {
                        "path": path,
                        "status": "missing",
                        "score": 0.0,
                        "expected": expected_flat.get(path),
                        "actual": None,
                        "note": "omitted_field",
                    }
                )
                total_scored_fields += 1
                continue

            matches, rule = _compare_values(
                path,
                expected_flat[path],
                actual_flat[path],
                truth.alt_field_values.get(path),
            )
            field_results.append(
                {
                    "path": path,
                    "status": "match" if matches else "mismatch",
                    "score": 1.0 if matches else 0.0,
                    "expected": expected_flat[path],
                    "actual": actual_flat[path],
                    "note": rule,
                }
            )
            total_scored_fields += 1

        scored_fields = [result["score"] for result in field_results if result["score"] is not None]
        field_match_rate = round(sum(scored_fields) / len(scored_fields), 4) if scored_fields else None

    classification_correct = truth.doc_type is None or predicted_doc_type == truth.doc_type
    invariant_pass_rate = (
        round(sum(1 for invariant in invariants if invariant["passed"]) / len(invariants), 4)
        if invariants
        else 1.0
    )
    schema_score = 1.0 if schema_valid else 0.0
    classification_score = 1.0 if classification_correct else 0.0
    overall_score = None
    if field_match_rate is not None:
        overall_score = round(
            FIELD_WEIGHTS["classification"] * classification_score
            + FIELD_WEIGHTS["field_match"] * field_match_rate
            + FIELD_WEIGHTS["invariants"] * invariant_pass_rate
            + FIELD_WEIGHTS["schema"] * schema_score,
            4,
        )

    decision = _decide_run(
        truth_has_labels=truth.has_ground_truth,
        classification_correct=classification_correct,
        classification_confidence=payload["classification"]["confidence"],
        schema_valid=schema_valid,
        invariants=invariants,
        field_match_rate=field_match_rate,
    )

    return {
        "document_id": document_id,
        "model": model,
        "seed": seed,
        "request_ok": True,
        "doc_type_expected": truth.doc_type,
        "doc_type_predicted": predicted_doc_type,
        "classification_confidence": payload["classification"]["confidence"],
        "classification_correct": classification_correct,
        "schema_valid": schema_valid,
        "schema_errors": schema_errors,
        "field_match_rate": field_match_rate,
        "field_results": field_results,
        "fields_scored": total_scored_fields,
        "invariant_pass_rate": invariant_pass_rate,
        "invariants": invariants,
        "overall_score": overall_score,
        "decision": decision,
        "metadata": payload["metadata"],
    }


def _decide_run(
    *,
    truth_has_labels: bool,
    classification_correct: bool,
    classification_confidence: float,
    schema_valid: bool,
    invariants: list[dict[str, Any]],
    field_match_rate: float | None,
) -> str:
    if not truth_has_labels:
        return "human_review"
    if not classification_correct and classification_confidence >= 90:
        return "reject"
    if not schema_valid:
        return "reject"
    if any(not invariant["passed"] and invariant["severity"] == "critical" for invariant in invariants):
        return "reject"
    if field_match_rate is None:
        return "human_review"
    if field_match_rate >= 0.97 and classification_correct:
        return "auto_commit"
    if field_match_rate >= 0.85:
        return "human_review"
    return "reject"


def evaluate_document(
    client: TestClient,
    document_id: str,
    model: str = "v1",
    seeds: list[int] | range | None = None,
) -> dict[str, Any]:
    seed_values = list(seeds) if seeds is not None else list(range(5))
    runs = [evaluate_run(client, document_id=document_id, model=model, seed=seed) for seed in seed_values]
    successful_runs = [run for run in runs if run.get("request_ok")]

    metric_names = ("field_match_rate", "overall_score", "invariant_pass_rate", "classification_confidence")
    metric_summary: dict[str, dict[str, float | None]] = {}
    for metric_name in metric_names:
        values = [run[metric_name] for run in successful_runs if run.get(metric_name) is not None]
        metric_summary[metric_name] = _summarize_numeric(values)

    field_status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    field_score_totals: dict[str, list[float]] = defaultdict(list)
    for run in successful_runs:
        for field_result in run.get("field_results", []):
            field_status_counts[field_result["path"]][field_result["status"]] += 1
            if field_result["score"] is not None:
                field_score_totals[field_result["path"]].append(float(field_result["score"]))

    field_summary = {
        path: {
            "match_rate": round(sum(scores) / len(scores), 4) if scores else None,
            "status_counts": dict(field_status_counts[path]),
        }
        for path, scores in sorted(field_score_totals.items())
    }
    for path, counts in field_status_counts.items():
        field_summary.setdefault(path, {"match_rate": None, "status_counts": dict(counts)})

    invariant_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for run in successful_runs:
        for invariant in run.get("invariants", []):
            invariant_counts[invariant["name"]]["pass" if invariant["passed"] else "fail"] += 1

    invariant_summary = {
        name: {
            "pass_rate": round(counts["pass"] / (counts["pass"] + counts["fail"]), 4)
            if (counts["pass"] + counts["fail"])
            else None,
            "status_counts": dict(counts),
        }
        for name, counts in sorted(invariant_counts.items())
    }

    decisions = Counter(run.get("decision", "unknown") for run in successful_runs)

    return {
        "document_id": document_id,
        "model": model,
        "seeds": seed_values,
        "runs": runs,
        "metrics": metric_summary,
        "field_summary": field_summary,
        "invariant_summary": invariant_summary,
        "decision_counts": dict(decisions),
    }


def compare_models(
    client: TestClient,
    document_ids: list[str],
    seeds: list[int] | range | None = None,
    models: tuple[str, str] = ("v1", "v2"),
) -> dict[str, Any]:
    comparison: dict[str, Any] = {"documents": {}, "models": list(models), "seeds": list(seeds or range(5))}
    for document_id in document_ids:
        doc_reports = {model: evaluate_document(client, document_id, model=model, seeds=seeds) for model in models}
        baseline = doc_reports[models[0]]
        candidate = doc_reports[models[1]]
        comparison["documents"][document_id] = {
            models[0]: baseline,
            models[1]: candidate,
            "delta": {
                "field_match_rate_mean": _safe_delta(
                    candidate["metrics"]["field_match_rate"]["mean"],
                    baseline["metrics"]["field_match_rate"]["mean"],
                ),
                "overall_score_mean": _safe_delta(
                    candidate["metrics"]["overall_score"]["mean"],
                    baseline["metrics"]["overall_score"]["mean"],
                ),
                "invariant_pass_rate_mean": _safe_delta(
                    candidate["metrics"]["invariant_pass_rate"]["mean"],
                    baseline["metrics"]["invariant_pass_rate"]["mean"],
                ),
            },
        }
    return comparison


def _safe_delta(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None:
        return None
    return round(current - baseline, 4)


def _summarize_numeric(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "min": None, "max": None}
    return {
        "mean": round(sum(values) / len(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def json_ready_report(report: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(report, default=_json_default))


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if dataclass_isinstance(value):
        return asdict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def dataclass_isinstance(value: Any) -> bool:
    return hasattr(value, "__dataclass_fields__")
