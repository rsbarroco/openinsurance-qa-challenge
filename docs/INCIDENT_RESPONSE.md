# INCIDENT-2026-04-12 Response

## Executive Summary

This incident is not one bug. It is two failures that surfaced in the same alert:

1. a real `v2` extraction regression on `loss_run_libertymutual`
2. an eval-process failure on `sov_pacific_realty` caused by truth / baseline mismatch

The correct response is therefore split:

- roll back / hold the candidate model because the loss-run regression is real and financially unsafe;
- fix the eval pipeline because the Pacific Realty alert is at least partially invalid as presented.

## First 30 Minutes

### 0-10 minutes: stabilize and scope

1. Acknowledge the alert.
2. Pause rollout progression immediately.
3. Confirm route weights and active model versions.
4. Confirm whether affected docs actually hit `v2`.

Commands / checks:

```bash
curl http://localhost:8000/config
curl http://localhost:8000/admin/bug-registry
python -m eval.cli \
  --document-id sov_pacific_realty \
  --document-id loss_run_libertymutual \
  --compare-models \
  --runs 5
```

### 10-20 minutes: reproduce deterministically

Re-run both failing documents on fixed seeds with noise disabled. The goal is to separate:

- stochastic flake
- routing confusion
- stable extraction bug

Commands:

```bash
curl -X POST http://localhost:8000/extract \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"loss_run_libertymutual","seed":17,"model":"v2"}'

curl -X POST http://localhost:8000/extract \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"loss_run_libertymutual","seed":17,"model":"v1"}'

curl -X POST http://localhost:8000/extract \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"sov_pacific_realty","seed":17,"model":"v2"}'
```

### 20-30 minutes: verify truth and baseline lineage

Inspect whether the alert compares:

- old baseline against old truth
- current run against new truth

That would invalidate the Pacific metric as a clean model comparison.

Checks:

- compare the current `data/ground_truth/sov_pacific_realty.json` to the truth revision used in the last baseline refresh
- confirm baseline refresh date vs truth update date
- confirm whether current canary actually routed Pacific Realty to `v2`

## Diagnosis

### 1. `loss_run_libertymutual` is a real `v2` regression

Evidence:

- Slack thread already points to a totals helper refactor using `abs()`
- the service code confirms a `v2`-only bug on `loss_run_libertymutual`
- negative subrogation recoveries are flipped positive during `total_incurred` rollup
- this breaks a critical financial invariant

Impact:

- financially unsafe aggregate values
- false inflation of losses
- bad downstream underwriting / decision inputs

This alone is enough to block shipping `v2`.

### 2. `sov_pacific_realty` is not clean evidence of `v2` regression

Evidence:

- `v2` is supposed to improve the Pacific `total_tiv` calibration issue
- Slack suggests Pacific may still have been routed to `v1`
- data ops updated Pacific ground truth after the historical baseline was computed
- if the historical baseline still points to old truth while the current run points to new truth, the alert delta is contaminated

Impact:

- the alert overstates or misstates model degradation
- on-call loses time investigating a partially invalid regression
- deploy decisions become noisy and less trustworthy

## Remediation

### Ship today

1. Roll canary back to `100% v1`
2. Block `v2` promotion until the loss-run aggregate bug is fixed
3. Recompute the Pacific baseline against the current truth revision
4. Re-run the comparison once truth and baseline lineage are aligned

### Do not ship today

- do not allow `v2` to continue canary exposure while the loss-run rollup bug exists
- do not make a final Pacific go / no-go call from the contaminated baseline comparison

### After the immediate fix

Once the `abs()` regression is corrected:

1. rerun deterministic offline eval on protected documents
2. explicitly inspect:
   - `loss_run_libertymutual total_incurred`
   - `sov_pacific_realty total_tiv`
   - COI producer omission drift
3. resume canary only if protected metrics are back within guardrails

## Post-Mortem

### What failed in process

1. Change management
   - a `5%` canary shift happened without clear comms in the deploy channel.
2. Separation of concerns
   - a UI-driven desire to hide negative numbers leaked into extraction logic.
3. Baseline governance
   - truth revisions and baseline revisions were not tightly coupled.
4. Incident observability
   - the alert did not make route weights, truth revision, or baseline revision immediately visible.

### Why this was painful

- one alert mixed a real model bug with an eval-process bug
- the team had to debug routing, model behavior, and baseline lineage at the same time
- confidence in the gate itself was degraded right when it was most needed

### Action Items

1. version every eval baseline against a truth revision identifier
2. fail baseline comparisons if truth lineage does not match
3. add protected invariant checks for loss-run sign handling and aggregate rollup
4. require rollout change logging in the deploy channel
5. separate display formatting code from extraction and aggregation logic
6. include route weight snapshot and truth revision directly in the alert payload

## Eval Pipeline Change Proposal

I would add the following to the evaluation framework:

### Protected metrics

- `loss_run.total_incurred_matches_claim_sum`
- `loss_run.total_recoveries_matches_negative_paid_sum`
- `sov.total_tiv_matches_property_sum`
- wrong high-confidence classification count

These should be first-class, named metrics with hard guardrails.

### Truth lineage enforcement

Every baseline should store:

- truth revision hash
- model version
- prompt / post-processor version
- seed set used

If the current run uses a different truth revision, the comparison should be marked invalid instead of silently treated as a regression.

### Seeded protected-set comparison

For candidate promotion, compare `v1` vs candidate on the same fixed seeds over a protected set. This reduces the chance that seed luck or operational noise drives a release decision.

## Final Shipping Decision

Based on the evidence available in this repo and incident prompt:

- `v2` should not ship on April 12, 2026 in its current state
- `loss_run_libertymutual` is a real blocker
- `sov_pacific_realty` should be re-evaluated only after fixing baseline / truth lineage
