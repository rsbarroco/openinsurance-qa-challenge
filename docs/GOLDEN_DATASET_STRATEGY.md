# Golden Dataset Strategy

The golden dataset should not try to be a random mirror of all production traffic. With only `50` new labels per quarter, it must be curated as a risk-management asset.

## Goals

The dataset should support four jobs:

- release gating for model / prompt changes
- regression detection on protected business-critical fields
- incident repro on known failure modes
- controlled expansion into new document types and edge cases

## Dataset Shape

I would maintain the golden set in three tiers.

### 1. Release Set

Small, stable, always-on, used in CI and candidate approval.

- one representative happy-path document per doc type
- one high-risk edge case per doc type where available
- protected fields and invariants explicitly marked

This set stays small because it must run quickly and often.

### 2. Nightly Set

Larger labeled set used for broader drift detection.

- multiple docs per high-volume / high-risk type
- includes known troublesome layouts such as legacy ACORDs, disputed SOV totals, and loss runs with recoveries
- multi-seed evaluation by default

### 3. Investigation Set

Documents promoted from incidents, customer escalations, and unusual review findings.

- not every investigation doc becomes part of the release gate
- only durable, reusable failure patterns should graduate into the nightly or release sets

## What Gets Labeled Next

New labels should be allocated by risk, not by fairness across document types.

Priority order:

1. failure modes that can create financially wrong aggregates
2. document types with highest production volume
3. cases that repeatedly trigger human review
4. novel layouts or carriers not represented in the current set
5. documents needed to validate a new extraction capability

## Selection Rules

For each doc type, intentionally seek coverage across:

- clean vs noisy OCR
- modern vs legacy layouts
- dense vs sparse field population
- common vs rare carriers / producers
- benign omissions vs high-risk hallucination opportunities
- aggregate-sensitive docs vs single-record docs

The point is not raw count. The point is coverage of failure classes.

## Label Governance

Every golden document should store metadata alongside truth:

- `doc_type`
- source / ingestion method
- OCR confidence band
- why the document is in the set
- protected fields
- known caveats: partial truth, disputed truth, missing spans, currency ambiguity
- truth revision history

Truth changes must be versioned. Historical baselines should be tied to a truth revision hash so the team never compares old baselines against new labels by accident.

## Promotion and Retirement

Promote a document into the golden set when:

- it exposed a real incident or near miss
- it covers a new failure class
- it materially changes release confidence

Retire or demote a document when:

- it is redundant with newer examples
- the failure class is no longer relevant
- it adds runtime cost without adding distinct signal

Do not delete history. Keep retired cases archived for incident lookback.

## How This Scales to 15 Doc Types / 2,000 Docs per Day

The scalable model is:

- small gated release set
- broader nightly labeled set
- large unlabeled monitoring pool

Most production docs should never be manually labeled. Instead:

- run label-free checks in production and nightly smoke jobs
- sample from review queues and incidents
- spend labels only where they improve the next release decision

## Unlabeled Monitoring Pool

For the large unlabeled population, track:

- schema validity
- invariant failures
- confidence shifts
- field-population drift
- human-review rate by doc type

If one segment drifts repeatedly, promote a few examples from that segment into the labeled set.

## Quarterly Labeling Plan

With `50` labels per quarter, I would reserve:

- `20` for new incidents and newly discovered failure modes
- `15` for underrepresented but high-volume doc types
- `10` for rollout of new features / doc types
- `5` as emergency reserve

This prevents the entire budget from being consumed by one noisy quarter.

## Practical Outcome

The golden dataset becomes:

- small enough to gate releases quickly
- sharp enough to catch known critical failures
- flexible enough to evolve from production learnings
- governed tightly enough that truth updates do not invalidate baseline comparisons silently
