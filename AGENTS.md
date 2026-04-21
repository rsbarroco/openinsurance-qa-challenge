## Repo Facts

- App: FastAPI mock extraction service under `app/`
- Data:
  - `11` source documents in `data/documents/`
  - `10` primary ground-truth labels in `data/ground_truth/`
  - `1` alternate label in `data/ground_truth_alt/`
- Existing docs/templates:
  - `docs/EVAL_RUBRIC_TEMPLATE.md`
  - `docs/TEST_STRATEGY_TEMPLATE.md`
  - `docs/RUNBOOK_TEMPLATE.md`
- Incident prompt:
  - `incidents/2026-04-12-tiv-regression.md`

Ground-truth distribution:

- `sov`: 3
- `coi`: 3
- `loss_run`: 2
- `endorsement`: 1
- `binder`: 1

Special cases shipped intentionally:

- partial truth: `sov_acme_properties`
- disputed truth: `sov_keystone_reit`
- missing truth: `coi_unlabeled_mystery`

## Deliverables Requested by the README

There are six deliverables listed:

1. eval framework
2. eval rubric
3. test strategy
4. production runbook
5. incident response
6. golden dataset strategy

Important instruction from the README:

- a focused submission covering `3-4` deliverables thoroughly can beat a shallow attempt at all `6`.

Current recommendation:

- still aim to cover all requested docs if time allows;
- keep the code and written material opinionated and scoped;
- do not over-engineer low-signal surfaces.

## Evaluation Weights

The README weights the review as follows:

- architecture and judgment: `35%`
- operational thinking: `25%`
- eval rubric quality: `20%`
- code quality and communication: `20%`

Important implication:

- bug count is explicitly not the main signal;
- prioritization quality and reasoning quality matter more than exhaustive defect hunting.

## Important Service Behaviors Already Confirmed

### API surface

- `POST /extract`
- `GET /config`
- `GET /health`
- `GET /`
- `POST /admin/reseed-bugs`
- `GET /admin/bug-registry`

### Operational noise

`/extract` injects realistic production noise by default:

- latency
- transient `500`s
- `429` rate limiting

Noise can be disabled with env vars:

- `DOCEXTRACT_LATENCY=off`
- `DOCEXTRACT_FAILURES=off`
- `DOCEXTRACT_RATELIMIT=off`

Implication:

- CI and reproducible eval should usually run with noise off;
- retry behavior and operational resilience should still be tested deliberately, not ignored.

### Model routing

- default model is `v1`
- `v2` is available via request body
- README explicitly asks to decide which model to ship

### Classification behavior

Confirmed from the code:

- `coi_travelers_umbrella` is intentionally misclassified as `policy`
- the classifier gives inflated confidence when overridden

Implication:

- the framework must evaluate classification accuracy and calibration separately from extraction values;
- high confidence on a wrong doc type must be treated as a severe failure.

## Known Extraction Behaviors from the Code

These are intentional signals in the mock service and should shape the eval design.

### SOV

- `sov_pacific_realty`:
  - `v1` has a systematic `total_tiv` calibration bias downward;
  - `v2` fixes that specific bias;
  - there is also component-vs-total drift on property values.
- `sov_keystone_reit`:
  - one document can lose `construction_type` at a higher rate;
  - bug assignment can move after `reseed-bugs`.
- `sov_acme_properties`:
  - one `square_footage` is intentionally partial truth (`unknown`);
  - the model may guess a value anyway.

### COI

- carrier names may appear in multiple valid surface forms and require canonicalization;
- `coi_zurich_legacy` can gain a hallucinated `cyber` coverage;
- `v2` omits `producer` more often across COIs.

### Loss run

- `v1` may emit `policy_effective_date` in mixed US/EU formats;
- one loss-run document can emit `paid_amount` in cents instead of dollars on some claims;
- `loss_run_libertymutual` in `v2` has a serious aggregation bug:
  - `abs()` is applied during incurred rollup;
  - negative subrogation recoveries are treated as positive loss;
  - this is a real ship blocker.

### Binder

- one binder can swap effective and expiration dates;
- this bug assignment should be caught semantically, not by document ID.

### Unlabeled document

- `coi_unlabeled_mystery` has no shipped ground truth;
- it must be handled via label-free checks:
  - schema validity;
  - invariants;
  - seed stability;
  - source traceability heuristics;
  - human review path.

## Incident Analysis Premises

From the incident prompt and the service behavior, the likely diagnosis is multi-causal:

1. `loss_run_libertymutual`
   - likely real `v2` regression;
   - matches the code-level `abs()` sign bug;
   - should trigger rollback / hold for `v2`.

2. `sov_pacific_realty`
   - likely not a simple model-quality regression;
   - the Slack thread suggests baseline drift after ground-truth update;
   - the alert compares historical baseline against old truth and current run against new truth;
   - this points to an eval-pipeline/process failure, not only a model failure.

Implication:

- the incident response document should explicitly separate:
  - product regression;
  - evaluation baseline bug;
  - rollout/routing confusion;
  - change-management failure.

## Solution Premises

These should guide all implementation decisions.

### Premise 1: Do not hardcode by `document_id`

The repo includes `POST /admin/reseed-bugs` specifically to catch overfit eval logic.

Allowed exceptions:

- loading alternate truth metadata for known disputed labels;
- loading partial-truth annotations shipped with the truth set.

Not allowed:

- rule logic like "if `document_id == X`, ignore field Y".

### Premise 2: Separate bias from variance

A single seeded run is not enough for model evaluation here.

The framework should:

- run multiple seeds per doc;
- summarize mean, spread, and invariant failure rate;
- distinguish stable wrong behavior from occasional noise.

### Premise 3: Field equality is not enough

The framework must combine:

- normalized value comparison;
- cross-field invariants;
- classification correctness;
- calibration checks;
- list precision/recall for repeated entities like properties, coverages, claims.

### Premise 4: Missing labels do not mean "cannot evaluate at all"

For unlabeled docs, evaluation should degrade gracefully into:

- schema validation;
- semantic self-consistency;
- variance checks;
- traceability / hallucination smoke checks;
- mandatory review recommendation.

### Premise 5: CI and nightly eval have different jobs

CI constraints from the README:

- under `8` minutes
- under `$200/day` total eval cost

Implication:

- CI should run a smaller deterministic gate;
- deeper multi-seed and canary analysis belongs in nightly or pre-release comparisons.

### Premise 6: The submission must be explainable live

Every major artifact should be defendable in a meeting.

This means:

- prefer explicit scoring rules over magical aggregate scores;
- use docs that another engineer can operate from;
- keep trade-offs written down;
- state what is deliberately out of scope.

## Risks and Weak Spots to Call Out Later

- `AUTO_COMMIT_THRESHOLD = 5` in `app/config.py` is suspiciously low for a 0-100 confidence scale.
- The review UI keeps the commit button enabled regardless of confidence.
- Operational noise can create false-positive regressions if retries/sampling are naive.
- Ground-truth updates can invalidate baselines if eval history is not versioned against truth revisions.
- Classification and extraction quality can diverge; the framework must score both.

These are useful discussion points in the debrief because they show product and ops awareness, not only test-writing ability.

## Recommended Order of Execution

1. create the eval harness and its scoring model
2. write the eval rubric to match the code behavior
3. write the test strategy with CI/nightly/canary separation
4. write the incident response and runbook
5. add golden dataset strategy if time remains strong enough

## Git / Submission State

Current repository state:

- inside a git worktree: yes
- current branch: `main`
- current remote `origin`: upstream challenge repo
- GitHub CLI is installed and authenticated as `rsbarroco`

Implication for submission:

- before push, the remote should be changed to Rodrigo's public GitHub repo or a new repo should be created and used as a separate remote;
- do not push back to the upstream challenge repository.

## First Commit Recommendation

The first public commit should establish structure and intent cleanly.

Recommended first commit contents:

- working brief / planning artifact
- initial eval framework scaffolding
- document templates replaced with first pass content only if already coherent

Recommended first commit message:

- `chore: add eval brief and submission scaffolding`

## Debrief Talking Points

When explaining the final solution later, make sure the narrative is:

1. what the system is and where quality can fail
2. why deterministic assertions are insufficient for LLM extraction
3. how the framework separates classification, extraction accuracy, invariants, and variance
4. how the design avoids overfitting to known documents
5. how incident handling distinguishes model bugs from eval-pipeline bugs
6. how the proposal stays within runtime, budget, and labeling constraints

## Current Status

Completed:

- repository read-through
- job-description and resume alignment review
- README review
- incident review
- service-code review
- ground-truth caveat review
- git and GitHub CLI readiness check

Not started yet:

- code implementation of the eval harness
- replacement of the deliverable docs
- creation of submission repo / first push
