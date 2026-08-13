# Methodology

## Overview

The WebPKI Observatory combines public datasets into a common analytical model of trust, issuance, incident history, governance activity, audit coverage, and cryptographic posture.

The methodology deliberately separates three layers:

1. **Observed data**: public records and deterministic transforms of those records.
2. **Deterministic scoring**: transparent functions over structured observed signals.
3. **Model-assisted context**: optional qualitative classifications and summaries that never change the deterministic score or tier.

This separation is a core reproducibility requirement.

## Source-Neutrality Rule

The score is a function of features, not identity.

If two entities have the same scoring feature vector and the same analysis date, they must receive the same score. There are no named-entity ranking expectations, named expert calibration cases, private-feedback weights, or organization-specific score overrides.

Organization and participant names may still exist in raw/public data because joins and UI display require identity. Source comments, scoring tests, and methodology examples are kept identity-neutral.

## Public Inputs

### Certificate Transparency

Certificate Transparency data provides all-time and currently unexpired precertificate counts. Counts are attributed using the source's root-owner model. Cross-signing can therefore shift apparent volume between operational issuers and root owners. The pipeline exposes this as a limitation instead of applying entity-specific corrections.

### Common CA Database

CCADB provides root metadata, trust-store inclusion, owner information, jurisdiction, capability flags, intermediates, and audit metadata. Cross-signed intermediates are de-duplicated by key identity after trust and expiration filtering.

### Public incident corpus

Mozilla Bugzilla CA Certificate Compliance records provide incident dates, public whiteboard tags, creators, comments, and lifecycle state. Bugzilla is the broadest public cross-program incident corpus but is not exhaustive.

### Browser share

Browser-share data estimates web reach for trust-store combinations. It is not a compliance-quality input.

### Public governance records

CA/Browser Forum ballots and public root-program records provide participation and policy-change history. Activity is reported as activity; lack of activity is not automatically converted into a compliance penalty.

### Audit records

CCADB audit metadata and accessible audit-letter PDFs provide audit periods, standards, auditor information, opinion data, and disclosure text. Parsing confidence and document availability are represented explicitly.

## Deterministic Operational Signals

### Self-report rate

```text
self_report_pct = self_reported_incidents / total_incidents * 100
```

The creator is attributed using public organization/domain mapping rules. The mapping itself is a data-join mechanism, not a score override.

### Chronic recurrence

An incident class is chronic when it appears in at least the configured number of distinct calendar years. The current model uses three distinct years.

Same-day batches with identical tag sets are collapsed when they exceed the configured batch threshold so reporting granularity does not inflate recurrence or acceleration.

### Ecosystem context

A recurrence coinciding with a broad ecosystem-wide filing spike receives a modest structural discount. A recurrence that occurs independently retains full weight. The adjustment is computed from corpus-wide counts, not entity identity.

### Ecosystem knowledge

For each chronic class, the pipeline measures how widely and how long the class had appeared elsewhere before the entity's first occurrence. The resulting multiplier is capped and applies equally to any entity with the same history.

### Incident acceleration

The incident rate in the more recent half of the observed years is compared with the earlier half. Corpus-size gates reduce the influence of high ratios produced by very small samples.

### Severity

Public incident tags map to five ordinal severity tiers. Tier weights follow a fixed powers-of-two progression:

```text
1, 2, 4, 8, 16
```

This encodes a generic monotonic rule: higher-severity classes contribute more than lower-severity classes without citing or encoding a named case.

### Recency

Recent severity uses a rolling 365-day window relative to an explicit analysis date:

```text
cutoff = as_of - 365 days
```

Production may set `as_of` to the run date. Reproduction and tests pin `as_of` explicitly.

## Accountability Loop Score

The deterministic structural score has two modes and an acceleration boost.

### Mode A: detection failure and deterioration

Inputs:

- self-report failure rate;
- incident acceleration; and
- governance/disclosure-failure share.

Low sample sizes reduce confidence in detection and acceleration signals.

### Mode B: structural accumulation

Inputs:

- chronic-class count;
- chronic-class density;
- duration of recurrence;
- ecosystem-wide recurrence context;
- ecosystem knowledge context;
- incident severity; and
- governance/disclosure-failure share.

Model-assisted judgments about RCA quality, candor, obligation understanding, commitments, or response quality do not change Mode A, Mode B, the threshold, or tier assignment.

### Final score

```text
total = max(mode_A, mode_B) + acceleration_boost
```

The threshold is a versioned parameter. Historical public distrust pathways are used to report evaluation metrics such as sensitivity and specificity, but evaluation does not create named exceptions.

### Audit context

Audit gap, staleness, and letter-quality fields may accompany the score but do not alter it. This property is tested directly.

## Engagement Score Compatibility

The UI retains the historical `eps` field for compatibility. In the source-neutral model it is a bounded projection of the deterministic structural score:

```text
eps = clamp(als_total, 0, 100)
```

It is not adjusted for organization size, market share, inferred remediation incentives, or LLM-derived behavioral judgments.

## Model-Assisted Context

Some public-record interpretation remains model-assisted, including portions of incident taxonomy, comment classification, RCA summaries, and narrative synthesis.

These fields are useful for exploration but have different epistemic status from deterministic metrics. They are cached and versioned where possible, but a model re-run is not assumed to reproduce identical labels. Therefore:

- they may be displayed as qualitative context;
- they must be labeled as model-assisted in methodology/UI where practical;
- they may not lower a score threshold;
- they may not alter score ordering; and
- deterministic property tests may not depend on them.

## Historical Outcome Evaluation

Distrust history is a public outcome dataset. It can be used to evaluate whether a structural signal would have identified gradual deterioration before removal.

Evaluation is kept separate from construction:

- the model computes scores without reading an entity's desired rank;
- positive/negative pathway labels are applied after scoring;
- sensitivity, specificity, false positives, and false negatives are reported as evaluation results;
- no false-positive or false-negative receives a hard-coded exception; and
- named organizations are not embedded in source comments or specifications as calibration anchors.

This avoids circular tests that merely assert the ranking the model was designed to reproduce.

## Market and Concentration Metrics

### Market share

```text
market_share = unexpired_precertificates / total_unexpired_precertificates * 100
```

### Usage period

```text
turnover = all_time_precertificates / unexpired_precertificates
usage_period = 365 / turnover
```

Usage period estimates replacement behavior, not the validity interval encoded in any individual certificate.

### Incidents per million

```text
ppm = cumulative_incidents / all_time_precertificates * 1,000,000
```

The numerator and denominator use compatible cumulative time horizons.

### HHI

```text
HHI = sum(market_share_pct ** 2)
```

The same calculation is used for issuance concentration and auditor concentration with the appropriate population.

## Policy-Readiness Metrics

Certificate-replacement behavior is compared with versioned Baseline Requirements validity limits. The active-TLS gate requires current TLS capability, meaningful current CT-visible issuance, and inclusion in a current browser trust store.

A population-average replacement period above a policy threshold is a readiness/risk signal. It is not evidence that any specific issued certificate exceeded the allowed validity period.

## Governance Metrics

Public governance activity is derived from Bugzilla participation, public enforcement actions, ballot records, and trust-store coverage.

Participant attribution may require public address/domain mappings. These mappings exist only to join public records to roles. Individual identities are not scoring parameters.

Model-assisted `governance` and `technical` comment labels are qualitative context and do not affect deterministic posture scores.

## Audit Intelligence

For each audit period, incident dates are matched against the period boundaries. Letters are searched for direct identifiers first and then for weaker description-based matches. Match confidence is retained as part of the result.

Letter-quality scoring uses observable features such as scope completeness, period continuity, opinion type, required disclosure sections, and specificity of disclosed items. Unparseable letters receive no quality score rather than an inferred value.

## Reproducibility Metadata

A deterministic score publication should record:

- scoring-model version;
- analysis date;
- generation timestamp;
- threshold and other model parameters;
- source dataset timestamps/versions where available; and
- historical evaluation results separately from score fields.

The generation timestamp itself does not make the score nondeterministic; the score is reproduced by pinning the source inputs and analysis date.

## Validation

The release gate includes:

1. pipeline smoke tests;
2. deterministic scoring property tests;
3. data-schema validation;
4. front-end tests;
5. production front-end build;
6. private-fingerprint scan;
7. source-neutrality scan over scoring comments and specifications; and
8. post-rewrite Git-history verification.

The property suite checks determinism, monotonicity, explicit-date recency, batch-collapse behavior, non-negative scores, and isolation of non-scoring audit context.

## Limitations

- Public incident records are incomplete relative to private enforcement channels.
- Root-owner attribution can misstate operational issuance under cross-signing.
- Public whiteboard tagging quality varies over time.
- A deterministic heuristic is reproducible but is still a research model, not an official root-program judgment.
- Historical outcome evaluation can overfit if repeatedly used to tune the same threshold; evaluation results should therefore be reported with model version and calibration history.
- Model-assisted qualitative fields are not deterministic and must not be confused with the deterministic score.
