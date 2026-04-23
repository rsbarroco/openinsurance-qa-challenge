# Test Strategy

This strategy assumes the system is an LLM-backed document extraction service with real operational risk. The goal is not to push all quality checks into one layer. The goal is to place the cheapest, fastest checks earliest and reserve expensive comparison-heavy eval for gates that actually need it.

## Layers

| Layer | What it tests | Runs where | Owned by | Cost / SLA | What it blocks |
| --- | --- | --- | --- | --- | --- |
| Unit | Normalizers, parsers, score calculators, invariant functions | CI on every PR | QA / feature author | Seconds | Broken evaluation logic |
| Schema / contract | API shape, extraction schema validity, supported doc types | CI on every PR | QA + backend | Seconds | Contract-breaking changes |
| Integration | End-to-end `/extract` behavior with fixed seeds and noise disabled | CI on every PR | QA | Minutes | Regressions on protected scenarios |
| Eval (offline golden dataset) | Multi-seed accuracy, invariants, variance, model-to-model comparison | Pre-merge for risky changes, nightly for full sweep | QA + model engineering | Minutes in CI, broader nightly budget | Release approval for model/prompt changes |
| Canary | Protected metrics on a sample of live traffic routed to candidate model | Production, after offline approval | Platform + QA + model engineering | Ongoing | Rollout continuation |
| Production monitoring | Drift, error rates, latency, confidence anomalies, review queue spikes | Production | Platform + on-call | Ongoing | Incident creation, rollback decisions |

## What blocks a deploy

For model or prompt changes, the release gate should be explicit:

- all CI unit / schema / integration checks pass;
- no wrong high-confidence classification on protected fixtures;
- no critical invariant failures on protected fixtures;
- offline eval on the labeled golden set shows no material regression on protected metrics;
- candidate canary stays within rollback guardrails.

Recommended CI gate:

- representative subset, not full nightly set;
- `3` seeds per protected document;
- both `v1` baseline and candidate model run on the same seeds;
- block if candidate regresses protected metrics by more than `2` points on mean score, or introduces any new critical invariant failure.

If a metric is close to threshold and the system is non-deterministic:

- do not make a ship / no-ship decision from one seed;
- rerun the protected subset with a larger seed sample before approving.

## What does not block a deploy

These should be visible in reports and dashboards but should not automatically gate:

- optional low-severity field drift with no aggregate or invariant impact
- unlabeled-doc heuristics by themselves
- latency blips caused by synthetic noise during local dev
- single-seed failures that disappear when rerun and have no stable pattern

The reason is simple: a founding QA function should keep the gate hard on correctness, but not make delivery hostage to every noisy signal.

## Cost Model

Constraints from the challenge:

- CI under `8` minutes
- eval budget around `$200/day`
- only `50` new labels per quarter

Recommended operating model:

- PR CI:
  - `5` protected documents
  - `3` seeds each
  - current prod model vs candidate
  - roughly `30` extraction calls
- Nightly full labeled eval:
  - all `10` labeled documents
  - `5` seeds each
  - current prod model vs release candidate when applicable
  - roughly `100` extraction calls
- Unlabeled documents:
  - sampled into nightly label-free checks
  - promoted into the golden set only when they represent a new edge case worth spending labeling budget on

Pre-compute and cache:

- truth bundles
- alternate-label metadata
- normalization maps
- per-document protected-field lists

## Model-Version Comparison

When `v2` is proposed:

1. run deterministic smoke checks on protected fixtures;
2. run offline multi-seed comparison against `v1`;
3. inspect field deltas, not only one blended score;
4. inspect invariant failures separately from raw accuracy;
5. rollout to a small canary with a hard kill switch.

Decision criteria:

- ship if `v2` improves or holds protected metrics and does not introduce new critical failure modes;
- do not ship if `v2` fixes one visible issue but introduces a financial aggregate bug elsewhere.

This matters directly in this challenge:

- `v2` improves `sov_pacific_realty` `total_tiv`;
- `v2` also introduces a serious `loss_run_libertymutual` rollup bug;
- the correct decision is therefore not "ship because one metric improved."

## Trade-offs

- I am not proposing exhaustive labeled coverage across all 15 document types in CI. That would be too expensive and too slow.
- I am separating deterministic CI gates from broader nightly eval because they solve different problems.
- I am intentionally treating invariants as first-class signals, not just field-level accuracy, because financial correctness failures can hide inside otherwise high-looking match rates.

## Open Questions for the Team

- Which fields truly drive auto-commit in production, as opposed to only helping reviewers?
- Are there document-level business rules by customer or carrier that should become invariant libraries?
- How is ground-truth versioning handled today when labels change after a historical baseline already exists?
- What is the acceptable false-positive rate for blocking deploys on nightly eval?
- How much live traffic can safely be exposed in canary before a human must review candidate outputs?
