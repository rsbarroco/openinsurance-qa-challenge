# Eval Rubric

This rubric defines what "correct" means for the DocExtract pipeline and how an extraction should be dispositioned as `auto-commit`, `human review`, or `reject`.

The framework should score four things separately:

- classification correctness and confidence calibration;
- field-level extraction accuracy after normalization;
- cross-field invariants;
- run-to-run stability across multiple seeds.

## Field Categories and Match Rules

| Field type | Example fields | Match rule | Tolerance / notes |
| --- | --- | --- | --- |
| Identifiers | `policy_number`, `claim_number`, `binder_number`, `endorsement_number` | Case-insensitive exact match after whitespace normalization | Missing identifier is a hard miss. |
| Party names | `insured_name`, `certificate_holder`, `producer`, `claimant` | Case-insensitive normalized string match | Minor spacing / casing differences allowed; semantic substitutions are not. |
| Carrier names | `carrier` | Canonicalize known legal / marketing variants before compare | `Zurich`, `Zurich North America`, and `Zurich Insurance` should collapse to one canonical form. |
| Dates | `effective_date`, `expiration_date`, `date_of_loss`, `valuation_date` | Normalize ISO, US, and EU short formats and compare on canonical date value | Ambiguous slash dates are accepted if one valid interpretation matches the truth. |
| Dollar amounts | `building_value`, `paid_amount`, limits, `premium_delta` | Numeric comparison after currency-string parsing | Use `3%` relative tolerance or `$100` absolute tolerance to absorb extraction jitter while still catching material drift. |
| Derived aggregates | `total_tiv`, `total_paid`, `total_recoveries`, `total_incurred`, `loss_ratio` | Numeric compare plus invariant check | Aggregates are more important than any single leaf amount because downstream financial decisions depend on them. |
| Structural / enum | `doc_type`, `construction_type`, `coverage_type`, `status`, `change_type` | Exact normalized match | Wrong `doc_type` is a top-severity failure. |
| Optional / nullable | `producer`, `year_built`, `square_footage`, `old_value`, `binding_authority_reference` | If truth is present, omission counts against accuracy; if truth is null, hallucinated values count against precision | Optional does not mean disposable. |

## Cross-Field Invariants

These checks are evaluated independently from ground truth and should block auto-commit when violated.

- SOV: `building_value + contents_value + business_income_value ~= total_insured_value`
- SOV: `sum(properties[*].total_insured_value) ~= total_tiv`
- COI / Binder: every coverage must satisfy `expiration_date >= effective_date`
- Binder: `binder_expiration_date >= binder_effective_date`
- Loss run: `paid_amount + reserved_amount ~= total_incurred` per claim
- Loss run: `status == closed` implies `reserved_amount == 0`
- Loss run: `sum(claim.total_incurred) ~= total_incurred`
- Loss run: `sum(claim.paid_amount) ~= total_paid`
- Loss run: `abs(sum(negative paid_amount)) ~= total_recoveries`

Critical invariant failures should be treated as `reject`, even if most fields match.

## Classification Calibration

The classifier should not only be accurate; it should also be well-calibrated.

- Wrong `doc_type` with confidence `>= 90` is a severe calibration failure and a `reject`.
- Correct classifications should cluster higher than incorrect ones.
- If the system is more confident on wrong classifications than on correct ones, that is a model-quality and operational-risk issue, not just a metric anomaly.

## Pass / Review / Reject Thresholds

These thresholds are intentionally simple and align to a production review flow.

- `Auto-commit`
  - classification correct;
  - schema valid;
  - no critical invariant failures;
  - field match rate `>= 0.97`.
- `Human review`
  - schema valid;
  - no critical invariant failure;
  - field match rate between `0.85` and `0.97`; or
  - document has no ground truth; or
  - document contains partial / disputed truth that cannot be fully auto-resolved.
- `Reject`
  - wrong high-confidence classification;
  - schema invalid;
  - critical invariant failure;
  - field match rate `< 0.85`.

## Per-Doc-Type Considerations

- SOV
  - `total_tiv` and per-property totals are protected fields.
  - A model that gets addresses right but drifts materially on property values should not pass.
- COI
  - Precision matters as much as recall.
  - Hallucinated coverage lines, especially on legacy ACORD layouts, should force review or reject.
- Loss Run
  - Sign handling and aggregate rollups are critical.
  - A model that flips recoveries positive is unsafe even if many claim rows look correct.
- Endorsement
  - `change_type`, `affected_field`, `old_value`, `new_value`, and `premium_delta` are the decision-driving fields.
- Binder
  - Chronology is critical.
  - Any date swap that creates impossible coverage order is a reject.

## Normalization Rules

- Carrier names: canonicalize common aliases to a legal-entity baseline.
- Dates: accept ISO, `MM/DD/YYYY`, and `DD/MM/YYYY`; compare canonical values.
- Dollar amounts: strip `$`, commas, and parentheses; parse `($8,200.00)` as `-8200.00`.
- Addresses and whitespace: compare case-insensitively after whitespace normalization and basic street suffix normalization.
- Legacy vs. modern ACORD layouts: compare on canonical coverage fields, not on layout-specific label wording.

## Handling Non-Determinism

The pipeline is explicitly non-deterministic, so single-run evaluation is not enough.

- Run each labeled document across multiple seeds.
- Report both `mean score` and `failure rate` by field / invariant.
- Treat stable wrong behavior as bias.
- Treat occasional misses as variance or flake.
- A model should not be approved on the strength of one lucky seed.

## Partial, Disputed, and Missing Ground Truth

- Partial truth
  - Example: `sov_acme_properties` has one `square_footage` explicitly marked `unknown`.
  - Do not score that field as right or wrong against a fabricated label.
  - Keep it visible in the report as `not_scored`.
- Disputed truth
  - Example: `sov_keystone_reit` has an alternate label for `total_tiv`.
  - Accept either approved interpretation for the disputed field and record that the field is disputed.
- Missing truth
  - Example: `coi_unlabeled_mystery`.
  - Evaluate only schema validity, invariants, confidence behavior, and seed stability.
  - Default disposition should be `human review`.

## Precision vs. Recall

- Hallucinated fields or list entries are precision failures.
- Omitted expected values are recall failures.
- For financial and insurance extraction, hallucinated coverages and inflated aggregates are riskier than many benign omissions, so precision failures on critical fields should be weighted more heavily.

## Out of Scope / Next Improvements

- provenance checks tying each extracted value back to a span in `raw_text`
- currency-aware handling beyond the current CAD/USD dispute example
- learned calibration thresholds from historical production distributions
