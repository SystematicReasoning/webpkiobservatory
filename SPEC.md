# Specification

## Purpose

The WebPKI Observatory provides a quantitative, evidence-based view of the public WebPKI ecosystem by combining public trust-store, certificate-transparency, incident, governance, audit, and standards data.

The implementation follows four rules:

1. **Identity belongs in data, not scoring logic.** Organization and participant names may appear in source datasets when they are required to join public records or display the records themselves. Scoring code, scoring tests, source comments, and methodology specifications must not depend on a named organization or individual.
2. **Core scores are deterministic.** Given the same versioned inputs and the same analysis date, the scoring layer must produce the same result.
3. **Calibration is outcome-based, not person-based.** Historical public outcomes may be used to evaluate a scoring rule. Private opinions, named expert judgments, and organization-specific expected rankings are not test vectors.
4. **Model-assisted interpretation is separate from scoring.** LLM-derived classifications or summaries may be displayed as qualitative context, but they do not alter the deterministic posture score or its threshold.

## Scope

Current-ecosystem analysis covers certificate authorities with at least one currently trusted root or a trusted subordinate relationship in a major public trust store. Historical views retain later-distrusted entities where needed to measure enforcement outcomes and longitudinal behavior.

The site may display organization names because the underlying public records are organization-specific. This does not make identity a scoring input: the same feature vector must receive the same score regardless of which organization produced it.

## Deterministic Scoring Contract

### Inputs

The deterministic posture score may use only structured, reproducible signals derived from public records, including:

- incident filing dates;
- self-report attribution;
- public incident-class tags;
- recurrence across distinct calendar years;
- incident-rate acceleration;
- governance/disclosure failure tags;
- ecosystem-wide recurrence context;
- severity class;
- recency relative to an explicit analysis date; and
- public audit metadata used as non-scoring context.

The deterministic score must not use:

- a named organization's desired rank;
- a named individual's opinion;
- private correspondence;
- LLM-generated candor, RCA, obligation-understanding, or commitment judgments;
- market-share-based assumptions about how easy or desirable an organization would be to distrust; or
- organization-specific overrides.

### Analysis date

Any time-sensitive signal uses an explicit `as_of` date. Daily production runs may set `as_of` to the run date, but tests and reproductions must pin the date.

### Severity scale

Incident classes are assigned an ordinal severity tier. Tier weights use a fixed powers-of-two rule:

| Tier | Weight |
|---|---:|
| 1 | 1 |
| 2 | 2 |
| 3 | 4 |
| 4 | 8 |
| 5 | 16 |

The rule is generic: increasing a severity tier cannot reduce the score. No named incident or organization is used to justify a particular ordering.

### Threshold

The posture threshold is a versioned model parameter. Historical distrust-pathway labels may be used to report sensitivity and specificity, but the public evaluation set is not allowed to contain organization-specific exceptions and does not dynamically change the score for a particular organization.

### Engagement score compatibility

The UI field historically named `eps` remains for compatibility. It is a bounded projection of the deterministic structural score unless and until a separately specified, independently validated priority model is introduced. Qualitative model-assisted fields do not affect ordering or tier assignment.

## Qualitative Context

The repository contains model-assisted incident-response analysis used to summarize public discussions. These fields may include classifications such as response quality, RCA depth, candor, or commitment quality. They are **context**, not deterministic scoring inputs.

Any UI that presents these fields should identify them as model-assisted and distinguish them from the deterministic score.

## Data Sources

### Certificate Transparency

Certificate Transparency data provides certificate-population counts and issuance activity. Root-owner attribution is used as published by the source. Cross-signing can cause operational issuance to be attributed to a different root owner; this is treated as a documented data limitation rather than corrected with entity-specific code.

### Common CA Database

CCADB provides root metadata, trust-store status, capabilities, ownership, jurisdiction, intermediate records, and audit metadata. Cross-signed intermediates are de-duplicated by key identity where applicable.

### Public incident records

Mozilla Bugzilla CA Certificate Compliance records provide incident dates, public tags, filing attribution, comments, and resolution history. The corpus is broad but not exhaustive because not every root program action occurs in Bugzilla.

### Browser share

Browser-market data is used only for reach and trust-surface calculations. It does not alter the deterministic compliance posture score.

### CA/Browser Forum records

Public ballot and revision-history records provide governance-participation data. Participation counts describe observed activity; they are not treated as proof of compliance quality.

### Audit letters

Audit metadata and publicly accessible audit letters are used for audit-period coverage, disclosure matching, and letter-quality analysis. Parse confidence and unavailable documents are represented explicitly.

### Cryptographic standards

Public standards publications provide key-size and algorithm reference data. Root self-signatures are interpreted as metadata about generation era, not as proof of current chain-validation weakness.

## Major Views

### Market Share

Measures issuance concentration from unexpired precertificate counts. Metrics include market share, cumulative share, concentration ratios, and usage-period estimates.

### Trust Surface

Measures root and owner counts, trust-store intersections, expiration timelines, capabilities, and browser reach.

### Concentration Risk

Computes HHI and concentration ratios over certificate issuance.

### Long-Tail Trust

Identifies the set of trusted entities below the configured cumulative issuance boundary while preserving the fact that low-volume roots retain broad technical authority.

### Geographic and Government Exposure

Shows jurisdiction and structural government-affiliation data as descriptive exposure metrics. Jurisdiction is not treated as a substitute for observed operational behavior.

### Operational Risk

Shows incident volume, self-report rate, recurrence, incident density, severity, recency, and deterministic posture score. Model-assisted incident-response fields are displayed separately when available.

### Cryptographic Posture

Shows key family, key size, signature hash, root age, and expiration posture against published standards.

### Distrust History

Shows public distrust events, pathway categories, contributing factors, and time-to-removal. Historical outcomes are used for evaluation of scoring rules, not for named exceptions.

### Policy Compliance

Shows certificate-replacement behavior against versioned Baseline Requirements validity limits. Population-average replacement behavior is a readiness signal and is not itself proof that any individual certificate violates a validity rule.

### Governance Risk

Shows public enforcement actions, Bugzilla participation, substantive-comment context, policy participation, and trust-surface coverage. Model-assisted comment classifications are explicitly non-scoring.

### Ecosystem Participation

Shows organization-level and participant-level public governance activity. Public identities may be required in the data layer to attribute records; scoring comments and specifications remain identity-neutral.

### Audit Intelligence

Matches incidents to audit periods, estimates disclosure coverage, measures auditor concentration, and reports observable letter-quality properties.

## Validation

A release must fail closed if any of the following fail:

- Python pipeline smoke tests;
- deterministic scoring property tests;
- data-schema validation;
- front-end unit tests;
- front-end production build;
- source-neutrality scan for private calibration fingerprints;
- source-neutrality scan for named organization or individual examples in scoring comments/specifications; or
- Git-history rewrite preconditions.

The scoring property suite must include at least:

- identical-input determinism;
- explicit-date reproducibility;
- monotonic severity behavior;
- monotonic recurrence behavior;
- monotonic self-detection behavior;
- deterministic batch collapse;
- score non-negativity; and
- proof that audit/context metadata does not change the deterministic score.

## Versioning and Reproducibility

Published score output should record:

- generation timestamp;
- analysis date;
- scoring-model version;
- parameter values;
- source-data versions or timestamps where available; and
- historical evaluation metrics separately from the score itself.

A score is reproducible only when these inputs are pinned.
