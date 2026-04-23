# DocExtract Eval - On-Call Runbook

This runbook is for the engineer paged on extraction-quality or eval-regression alerts. Assume the reader has not studied the framework internals and needs a fast, reliable path to triage.

## When You Get Paged

| Alert | What it likely means | First check |
| --- | --- | --- |
| `eval-regression: total_tiv accuracy below baseline` | Model drift, truth change, or stale baseline | Compare current truth revision vs historical baseline revision |
| `eval-regression: hallucinated coverage rate spiked` | Precision regression, often on COI / legacy layouts | Inspect added coverage lines and compare to raw text |
| `eval-flake: nightly run timed out` | Noise, rate limit, retry logic, or runner issue | Check retry logs and whether eval ran with noise disabled |
| `canary: 5xx rate > 5%` | Service instability, dependency issue, or synthetic noise accidentally left on | Confirm traffic slice and infra health before treating as model quality issue |
| `canary: latency p99 > 5s` | Platform issue, throttling, or noisy config | Check rate limiting, retries, and platform changes |
| `production: confidence calibration drifted` | Classifier confidence no longer tracks correctness | Inspect wrong high-confidence samples immediately |

## First 15 Minutes

1. Acknowledge the page and freeze further rollout if a candidate model is in canary.
2. Identify whether the alert is on:
   - extraction correctness;
   - eval pipeline correctness;
   - platform noise / execution reliability.
3. Confirm what changed since the previous healthy run:
   - model version;
   - prompt or post-processor;
   - route weights;
   - ground truth or baseline refresh;
   - canary configuration.
4. Reproduce the failing document on fixed seeds with noise disabled.
5. Post an internal Slack update with:
   - impacted metric;
   - candidate scope;
   - whether rollback is already in progress;
   - ETA for next update.

## Diagnosis Flow

For an extraction-quality regression:

1. Is it a model change?
   - Check active route weights and release tags.
   - Re-run the same doc on `v1` and `v2` with the same seeds.
2. Is it a ground-truth change?
   - Diff the current ground-truth file against the version used for the baseline.
   - If the truth changed and the baseline did not refresh, treat the alert as partially invalid.
3. Is it an eval-pipeline bug?
   - Check whether historical baseline and current run were computed against different truth revisions.
   - Check whether noise, rate limits, or retries contaminated the sample.
4. Is it real traffic drift?
   - Compare canary-only behavior vs offline deterministic reruns.
   - If only canary is failing, verify routing, traffic mix, and review outcomes.

## Rollback Criteria

Roll back immediately if any of the following is true:

- new critical invariant failure on a financial aggregate
- wrong high-confidence classification on protected documents
- candidate model clearly worse than production on a protected metric
- canary shows stable regression across reruns

Prefer fix-forward only when:

- the failure is isolated to the eval pipeline, not extraction behavior;
- the candidate model is not serving meaningful traffic;
- there is a safe, fast patch and rollback would cause unnecessary churn.

At 3am, rollback authority should sit with the on-call in consultation with model engineering when reachable. Lack of immediate confirmation from model engineering is not a reason to leave a known bad candidate live.

## Common False-Positive Patterns

- Baseline staleness after a ground-truth refresh
  - Historical baseline still points to old labels, current run uses new labels.
- Seed luck on too-small sample size
  - One bad seed can exaggerate an unstable metric.
- Noise contamination
  - Rate limit or transient failures accidentally included in score computation.
- Canary routing misunderstanding
  - The failing document may not even have hit the candidate model.

## Comms Templates

Status page:
> We are investigating a document-extraction quality regression affecting candidate rollout validation. Production traffic remains on the stable model while we verify impact.

Customer-facing if production-impacting:
> We identified degraded accuracy in a subset of automated document-processing results and shifted traffic back to the last known-good model. We are validating impacted outputs and will share follow-up once mitigation is complete.

Internal Slack update:
> Investigating eval regression on `<metric>` for `<document/doc type>`. Candidate model rollout is paused / rolled back. Current hypothesis: `<model bug / truth drift / eval issue>`. Next update in `<time>`.

## After the Incident

The incident owner should attach:

- timeline of alerts, acknowledgements, and mitigation
- exact model / prompt / post-processor versions involved
- route-weight state during the incident
- truth revision and baseline revision used in the failing comparison
- fixed-seed repro steps
- follow-up action items with owners and due dates

## Useful Commands

```bash
# Health and config
curl http://localhost:8000/health
curl http://localhost:8000/config

# Reproduce a specific document on a fixed seed
curl -X POST http://localhost:8000/extract \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"loss_run_libertymutual","seed":17,"model":"v2"}'

# Compare v1 vs v2 on one or more documents
python -m eval.cli \
  --document-id sov_pacific_realty \
  --document-id loss_run_libertymutual \
  --compare-models \
  --runs 5

# Check current bug assignments
curl http://localhost:8000/admin/bug-registry

# Rotate bug assignments to confirm the eval framework is not overfit to doc IDs
curl -X POST 'http://localhost:8000/admin/reseed-bugs?seed=42'
```
