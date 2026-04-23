# DocExtract Eval Harness

## Overview

You're building the eval and quality infrastructure for a production document extraction pipeline. The system ingests insurance documents (PDFs) and uses an LLM to extract structured data. Your job is to design the eval framework, define what "correct" means, and build the operational safeguards that keep this pipeline trustworthy in production.

## What you're looking at

A mock document extraction service that simulates a production LLM pipeline (PDF → structured JSON, GPT-4o at temp 0.1). It ships with:

- 11 sample documents (SOVs, COIs, loss runs, an endorsement, a binder, plus an unlabeled mystery doc)
- Hand-labeled ground truth for most of them, partial for one, disputed for one, missing for one
- Two model versions (`v1`, `v2`) — pick which to ship
- A web UI at `http://localhost:8000/` (the operator review console — humans look at extractions before they auto-commit)
- Operational noise (latency, transient 5xx, 429 rate limits) toggleable via env vars
- An open SEV-2 incident from this morning at [incidents/2026-04-12-tiv-regression.md](incidents/2026-04-12-tiv-regression.md)

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Verify:

```bash
curl http://localhost:8000/health        # liveness
open  http://localhost:8000/             # operator review console
curl http://localhost:8000/config        # pipeline configuration
curl http://localhost:8000/openapi.json  # full API spec (FastAPI auto-published)
```

## API surface (read this before you start)

| Endpoint | What it does |
| --- | --- |
| `POST /extract` | Body: `{"document_id": "...", "seed": <int?>, "model": "v1"\|"v2"}`. Returns classification + extraction + metadata. Non-deterministic without a seed. |
| `GET /config` | Pipeline config — auto-commit threshold, retry policy, model name, weights. |
| `GET /health` | Liveness probe. |
| `GET /` | Operator review console (HTML). |
| `POST /admin/reseed-bugs?seed=<int?>` | Rotates which documents carry which behavioral patterns. Use this to detect whether your eval framework is overfit to specific `document_id` values. |
| `GET /admin/bug-registry` | Read the current per-doc behavior assignments. |

## Documents

| document_id | Notes |
| --- | --- |
| `sov_acme_properties` | 6 properties, CT/NY/NJ. One property has a partial-truth `square_footage` (see Caveats). |
| `sov_pacific_realty` | 4 properties, CA/OR/WA. |
| `sov_keystone_reit` | 15 properties, 6 states, plus an adversarial Toronto CAD footnote and a duplicated location entry. |
| `coi_hartford_general` | ACORD 25 with 4 coverage lines. |
| `coi_travelers_umbrella` | ACORD 25 with umbrella layer, 3 coverage lines. |
| `coi_zurich_legacy` | Legacy ACORD 25 (2010/05) layout with older limit labels. |
| `coi_unlabeled_mystery` | Production-style COI **with no ground truth shipped** — your call on how to evaluate it. |
| `loss_run_nationwide` | 8 claims over 3 years. |
| `loss_run_libertymutual` | 24 claims, 5 years, with subrogation recoveries (negative `paid_amount`) and reopened claims. |
| `endorsement_chubb_tiv_increase` | Blanket building-limit endorsement. |
| `binder_travelers_temp` | 30-day binder for a newly acquired subsidiary. |

## Ground truth caveats

Three deliberate real-world cases. Shipped explicitly — they're a judgment test, not a gotcha.

1. **Partial** — `sov_acme_properties` flags one `square_footage` as `"unknown"` because the source SOV redacted the figure.
2. **Disputed** — alternate label for `sov_keystone_reit` lives at [data/ground_truth_alt/](data/ground_truth_alt/), disagreeing on `total_tiv` over a Toronto branch interpretation.
3. **Missing** — `coi_unlabeled_mystery` ships with no ground truth at all.

## Operational noise

`/extract` simulates production network conditions. All on by default; toggleable:

| Behavior | Default | Toggle |
| --- | --- | --- |
| Latency (0.5–2.0s per call) | on | `DOCEXTRACT_LATENCY=off` |
| Transient 5xx (~4% of calls) | on | `DOCEXTRACT_FAILURES=off` |
| Rate limit (10 req/60s per IP → 429) | on | `DOCEXTRACT_RATELIMIT=off` |

Both "handle the noise" and "turn it off and explain why" are valid choices.

## Constraints (these matter — your design must respect them)

- **Production scale**: 2,000 docs/day across 15 doc types. The 11 in this repo are a sample.
- **Eval budget**: $200/day compute for the eval pipeline.
- **CI gate**: must complete in under 8 minutes.
- **Labeling capacity**: 50 new ground-truth labels/quarter, no more.
- **You will not be the one running this in production.** Whatever you build needs to be runnable by a different on-call engineer at 3am with an alert in their hand.

## Your deliverables

We value scoping and judgment over completeness — a focused submission that covers 3–4 deliverables thoroughly will beat a superficial pass at all 6.

### 1. Eval framework (code, in `tests/` and/or `eval/`)

Not a test suite — a framework. Someone else on your team should be able to:
- Point it at any of the 11 documents (and ideally a 12th they haven't seen) and get a structured report.
- Run it against `model=v1` vs `model=v2` and produce a comparison.
- Re-run after `POST /admin/reseed-bugs` and not break.

Express your invariants (cross-field, semantic, calibration, precision) cleanly so they're reusable. Run multiple extractions per doc; distinguish variance from bias.

### 2. Eval rubric ([docs/EVAL_RUBRIC_TEMPLATE.md](docs/EVAL_RUBRIC_TEMPLATE.md))

What does "correct" mean per field type? Tolerances, normalization rules, cross-field invariants, calibration expectations, handling of partial / disputed / missing truth.

### 3. Test strategy ([docs/TEST_STRATEGY_TEMPLATE.md](docs/TEST_STRATEGY_TEMPLATE.md))

1–2 pages. What gets tested at which layer (unit / integration / eval / canary / production), what each layer costs, who owns it, what blocks a deploy. Test-pyramid thinking for an LLM-backed service is non-trivial. That's the signal.

### 4. Production runbook ([docs/RUNBOOK_TEMPLATE.md](docs/RUNBOOK_TEMPLATE.md))

What does the on-call do when the nightly eval regresses? Triage steps, escalation, rollback criteria, comms template. Should be usable by someone who has *not* read your eval framework.

### 5. Incident response ([incidents/2026-04-12-tiv-regression.md](incidents/2026-04-12-tiv-regression.md))

Walk through the open SEV-2 in `docs/INCIDENT_RESPONSE.md` (create it). Triage, diagnosis, remediation, 1-page post-mortem, proposed eval-pipeline change. You don't need to write code to fix the bugs — we're evaluating sequencing and judgment.

### 6. Golden dataset strategy ([docs/GOLDEN_DATASET_STRATEGY.md](docs/GOLDEN_DATASET_STRATEGY.md), create it)

How do you scale this to 15 doc types and 2,000 docs/day on the constraints above?

## Tools

Use whatever tools help you ship good work. AI coding tools encouraged. Note what you used and for what at the end of your submission.

## What we evaluate on

| Dimension | Weight |
| --- | --- |
| Architecture & judgment (eval framework design, strategy doc, scoping) | 35% |
| Operational thinking (runbook, incident response, handling noise/cost/scale constraints) | 25% |
| Eval rubric quality (calibration, normalization, partial/disputed/missing truth) | 20% |
| Code quality & communication (structure, clarity, what you skipped and why) | 20% |

Bug counts are *not* a primary axis at this level. Finding 6 of 10 vs 8 of 10 isn't the signal. *Which* you prioritized and how you reasoned about it is.

## Submission Notes

This submission includes:

- a reusable evaluation harness under `eval/`
- multi-seed document and model comparison
- scoring for field accuracy, schema validity, classification, and invariants
- written deliverables for rubric, test strategy, incident response, runbook, and golden dataset strategy

Example harness usage:

```bash
python -m eval.cli \
  --document-id sov_pacific_realty \
  --document-id loss_run_libertymutual \
  --compare-models \
  --runs 5
```

Primary documents delivered:

- [docs/EVAL_RUBRIC_TEMPLATE.md](docs/EVAL_RUBRIC_TEMPLATE.md)
- [docs/TEST_STRATEGY_TEMPLATE.md](docs/TEST_STRATEGY_TEMPLATE.md)
- [docs/INCIDENT_RESPONSE.md](docs/INCIDENT_RESPONSE.md)
- [docs/RUNBOOK_TEMPLATE.md](docs/RUNBOOK_TEMPLATE.md)
- [docs/GOLDEN_DATASET_STRATEGY.md](docs/GOLDEN_DATASET_STRATEGY.md)

## Tools Used

- ChatGPT / Codex:
  - codebase analysis
  - eval harness implementation
  - test drafting
  - documentation drafting and refinement
- GitHub CLI:
  - branch push and pull request workflow
- FastAPI TestClient / pytest:
  - local validation of the framework and seeded regression scenarios

