# Methodology

## Overview

The WebPKI Observatory combines six public data sources into a unified analytical view of the Certificate Authority ecosystem. This document describes how each metric is computed, what assumptions are made, and where the analysis has known limitations.

All analysis is scoped to **currently trusted CAs** — those with at least one root certificate included in one of the four major trust stores (Mozilla, Chrome, Microsoft, Apple). Distrusted CAs are excluded from all current-ecosystem analysis. Historical data (e.g., incident timelines, distrust events) preserves the full record.

## Data Sources

### crt.sh (Certificate Transparency)

**What it provides:** Certificate population counts per CA owner — both all-time and currently-unexpired precertificates.

**How it works:** crt.sh aggregates certificates from Certificate Transparency logs and groups them by the "Root Owner" field, which identifies the organization that owns the root certificate at the top of the certificate chain.

**Update frequency:** Daily.

**Limitation — Root Owner Attribution:** crt.sh attributes certificates to the owner of the root they chain to, not the CA that operationally issued them. When CA "A" issues certificates through cross-signed intermediates under CA "B"'s root, those certificates appear as CA "B"'s volume. This affects CAs like Amazon Trust Services, whose ACM-issued certificates chain to GoDaddy/Starfield roots and are therefore counted under GoDaddy's totals. There is no known way to correct this from public CT data alone. CAs with known attribution gaps are marked in the dashboard.

### CCADB (Common CA Database)

**What it provides:** Root certificate metadata, trust store inclusion status, CA owner organization details, country of incorporation, capability flags (TLS, EV, S/MIME, code signing), intermediate certificate records, and audit metadata (standard, period, auditor name, audit letter URLs).

**How it works:** CCADB is a shared database maintained by Mozilla and used by all four major root programs. CAs self-report organizational information; trust store inclusion status is maintained by the root programs themselves.

**Update frequency:** Daily (AllCertificateRecordsCSVFormatv4 export).

**Limitation — Country Field:** The "CA Owner" country field reflects the organization's jurisdiction of incorporation, not where its operations, infrastructure, or subscribers are located. A CA incorporated in Belgium may operate servers in the US and issue certificates to subscribers worldwide.

**Intermediate De-duplication:** Cross-signed intermediate certificates share the same Subject Key Identifier (SKI) but appear as separate CCADB records. The pipeline de-duplicates intermediates by SKI after filtering for trusted, non-expired chain paths, so the "Issuing CAs" count reflects operationally distinct issuing CAs.

### Bugzilla (Mozilla CA Compliance)

**What it provides:** CA compliance incident records from 2014 to present, including incident descriptions, filing dates, resolution status, and the identity of the bug filer and commenters.

**How it works:** When a CA violates the Baseline Requirements, root program policies, or its own Certificate Practice Statement, a bug is filed in Mozilla's Bugzilla under the "CA Certificate Compliance" component. These bugs are the canonical public record of CA compliance incidents across all root programs.

**Update frequency:** Daily.

**Limitation — Attribution Completeness:** Not all CA incidents result in Bugzilla bugs. Some may be handled through private channels, other root programs' processes, or CA self-remediation without public filing. The Bugzilla record is the most comprehensive public record but is not exhaustive.

**Limitation — Program Bias:** Mozilla uses Bugzilla as its primary governance channel. Chrome, Apple, and Microsoft govern partly through private channels. Bugzilla participation metrics are therefore biased toward Mozilla's public activity.

### StatCounter

**What it provides:** Global browser market share, used to estimate what proportion of web users are affected by each trust store's decisions.

**How it works:** StatCounter tracks browser usage across a network of participating websites. We map browser engines to root programs: Chrome (includes Edge, Samsung Internet, Opera, and other Chromium-based browsers) → Chrome Root Store; Safari → Apple; Firefox → Mozilla; Internet Explorer/legacy Edge → Microsoft.

**Update frequency:** Daily.

**Limitation — Web vs Platform:** Microsoft's trust store has ~0% web browser share (Edge uses Chrome's root store) but is critical for Windows enterprise TLS, S/MIME, and code signing. The "web coverage" metric is accurate for browser-based TLS but understates Microsoft-only CAs' operational importance in non-browser contexts.

### cabforum.org

**What it provides:** CA/B Forum ballot history across all working groups — Server Certificate (SC), Code Signing Certificate (CSC), S/MIME Certificate (SMC), and Network Security (NS). Each ballot record includes proposers, endorsers, and vote results by organization.

**How it works:** `fetch_cabf_ballots.py` scrapes the official ballot status pages and constructs a structured record. Organization names are mapped to root program affiliation. `fetch_revision_history.py` additionally parses revision tables from the canonical CABF document repositories (TLS BR, EVG, NSR, S/MIME BR, CS BR) to build a dated ballot timeline covering the pre-GitHub era.

**Update frequency:** Daily.

**Limitation:** Ballot counts treat all ballots equally regardless of impact. SC-081 (reducing certificate validity to 47 days) has vastly more impact than a cleanup ballot. Not voting may reflect policy disagreement or deliberate abstention — it is not inherently a governance failure.

### keylength.com

**What it provides:** Cryptographic key size and algorithm recommendations from five standards bodies (NIST SP 800-57, ECRYPT-CSA D5.4, BSI TR-02102-1, ANSSI RGS v2.03, NSA CNSA Suite).

**Update frequency:** Manual (standards body publications change infrequently).

### Audit Letters (WebTrust / ETSI)

**What it provides:** Annual audit opinions and disclosed incident lists for CA root certificates, sourced from CCADB audit metadata and directly fetched PDFs.

**How it works:** CCADB records include audit letter metadata — standard (WebTrust or ETSI), audit period, auditor name, and PDF URL — for each root certificate. `fetch_audits.py` retrieves these PDFs from two sources: the CPA Canada getPDFWebTrust API (for ~365 WebTrust roots) and direct URLs on auditor/CA domains (~175 ETSI roots). Where pdfplumber can extract text, the letter is parsed for opinion type, Appendix D items (disclosed incidents), and qualification language.

**Update frequency:** CCADB metadata is checked daily. PDFs are cached for 90 days (audit letters do not change once issued). A new letter for the same CA/period replaces the prior cached version.

**Limitation — Parse Coverage:** PDF parsing succeeds for approximately 85% of accessible letters. ETSI letters use less structured formats than WebTrust letters; parse confidence scores reflect this. Letters hosted behind authentication walls or on inaccessible domains are recorded as "unavailable" and excluded from quality scoring but retained in presence tracking.

**Limitation — Attribution:** Appendix D items in WebTrust letters rarely include Bugzilla IDs. The pipeline matches items by date proximity, cert serial numbers where present, and description similarity. Matches below a confidence threshold are recorded as probable rather than confirmed.

## Derived Metrics

### Market Share (%)

```
market_share = (CA's unexpired precertificates / total unexpired precertificates) × 100
```

Computed over currently trusted CAs only. Sums to 100%.

### Usage Period (days)

```
turnover = all-time precertificates / unexpired precertificates
usage_period = 365 / turnover
```

Measures how frequently a CA's subscriber base replaces certificates. This is **not** the validity period on the certificate — it reflects actual replacement behavior. Example: Let's Encrypt issues 90-day certificates, but subscribers typically auto-renew at 60 days, resulting in a ~22-day average usage period.

**Important:** The usage period uses `unexpired_precerts` (CT log precertificate counts) for both numerator and denominator. CAs that issue non-TLS certificates (S/MIME, code signing, government credentials) may have large all-time counts from non-TLS issuance, making their usage period meaningless as a TLS BR compliance signal. See the active-TLS filter below.

### BR Validity Status

Each CA's usage period is compared against the BR maximum validity reduction schedule and assigned a `brStatus`:

| Status | Meaning |
|--------|---------|
| `violation` | Usage period > 200 days — currently exceeding the BR limit effective March 2026 |
| `risk_2027` | Usage period 101–200 days — will breach the 100-day limit in March 2027 |
| `risk_2029` | Usage period 48–100 days — will breach the 47-day limit in March 2029 |
| `compliant` | Usage period ≤ 47 days — already meeting the 2029 target |
| `not_applicable` | Does not meet active-TLS qualification (see below) |

**Active-TLS qualification gate** (all three must be true):
- `tls_capable = True` (CCADB capability flag)
- `unexpired_precerts ≥ 1,000` (genuine current TLS issuance visible in CT logs)
- Trusted by at least one current browser store

CAs that don't pass this gate get `not_applicable`. This prevents legacy non-TLS cert populations from producing misleading BR compliance signals. Example: Government of the Netherlands (PKIoverheid) has a nominal usage period of 5,475 days from long-lived government credentials — it is not an active TLS issuer under the BR regime and should not appear in the violation bucket.

### Incidents Per Million (PPM)

```
ppm = (cumulative Bugzilla incidents / all-time precertificates) × 1,000,000
```

Both numerator and denominator are cumulative/all-time values, ensuring the time windows match.

**Why all-time denominator:** Using current unexpired certificates would conflate a 12-year cumulative numerator with a point-in-time snapshot denominator, producing extreme values for CAs with many historical incidents but few current certificates.

**RateDot thresholds:** Green (<10/M), Amber (10–1,000/M), Red (>1,000/M). Calibrated against the observed distribution of all-time PPM values across trusted CAs.

### Self-Report Rate (%)

```
self_report_pct = (incidents filed by the CA / total incidents for that CA) × 100
```

Attribution is based on matching the Bugzilla bug creator's email domain to the CA organization. Higher self-report rates generally indicate stronger internal compliance monitoring.

### Web Coverage (%)

```
web_coverage = Σ (browser_market_share for each store that includes this CA)
```

Approximate proportion of global web browsing traffic that trusts this CA's certificates. A CA in all four stores has ~96.9% coverage. Chrome-only: ~78%.

### HHI (Herfindahl-Hirschman Index)

```
HHI = Σ (market_share_pct²) across all trusted CAs
```

Standard concentration metric. DOJ/FTC thresholds: <1,500 unconcentrated, 1,500–2,500 moderate, >2,500 highly concentrated.

Applied to both CA market share (Concentration Risk tab) and auditor market share (Audit Intelligence tab — auditor HHI weighted by CA audit count over trailing 12 months).

### Tail Boundary

```
head = fewest CAs where cumulative market share ≥ 99.99%
tail = all remaining CAs
```

Computed dynamically on each pipeline run. The boundary adapts as the market evolves.

## Incident Classification (LLM)

Each Bugzilla CA compliance bug is classified into one of four categories using the Anthropic API:

| Category | Definition |
|----------|-----------| 
| Misissuance (mi) | Certificate issued in violation of the Baseline Requirements or CA's own CPS |
| Revocation (rv) | Failure to revoke in time, CRL/OCSP errors, or revocation process failures |
| Governance (gv) | Audit failures, CPS/CP violations, disclosure failures, root program policy violations |
| Validation (vl) | Domain control validation or organization validation errors |

**Pipeline:** `fetch_incidents.py` classifies bugs using a zero-shot LLM prompt with the bug summary and first-comment text. Classifications are cached in `pipeline/incident_classifications.json` (git-tracked) to avoid redundant API calls. The cache is keyed by bug ID; entries are invalidated when bug content changes.

**Accuracy:** Classification is validated by a manual review of a sample of each category. The LLM prompt uses the full taxonomy definitions and is tested against edge cases (e.g., a bug that is both a validation failure and a revocation failure gets the primary category based on the root cause).

## Comment Classification (LLM)

The Governance Risk tab requires distinguishing technically substantive root program governance from process-only enforcement. Each comment on a CA compliance bug is classified with a two-field LLM prompt:

- `governance`: True if the comment represents genuine oversight engagement — not just automated CCADB reminders, duplicate acks, or off-topic discussion
- `technical`: True if the comment contains technical findings — certificate/CRL analysis, specific BR/RFC citations with evidence, root cause identification, or scope quantification

**Bugzilla Coverage** = unique bugs where at least one `governance=True` comment exists from the program.  
**Substantive Oversight** = unique bugs where at least one `governance=True AND technical=True` comment exists.

The split reveals governance quality: 60–80% of governance-flagged comments are process-only enforcement (overdue notices, status requests, housekeeping directives). Chrome's governance comments are more technically substantive (~40%) than Mozilla's (~19% recently).

**Pre-processor:** `classify_comments.py` runs incrementally outside the daily CI pipeline to build `ops_cache/comment_classifications.json`. `fetch_rpe.py` reads this cache at runtime. When the cache is cold, `technical` defaults to False — unknown comments are not counted as substantive, making the cache-cold state visible (Substantive Oversight = 0) rather than silently equal to Coverage.

## Discovery Method Classification

Each CA compliance bug is assigned a discovery channel based on keyword analysis of the first comment, supported by LLM disambiguation:

| Channel | Pattern | Share |
|---------|---------|-------|
| Self-detected | CA's own monitoring, linting, or internal audit | ~22% |
| External researcher | Security researcher, CT watchdog, third party | ~20% |
| Community | CT log analysis tools (pkilint, x509lint, dwklint), MDSP/cabforum discussion | ~17% |
| Unknown | First comment exists but no channel keyword matches | ~29% |
| Audit | External auditor finding | ~8% |
| Root program | Root program staff filing directly | ~4% |

**Corpus:** Active-CA bugs only — 1,505 bugs. The 187 bugs attributed to distrusted CAs are excluded from discovery analysis because they reflect the incident patterns of failed CAs, not the current ecosystem.

**Unknown channel:** The 29% unknown rate is a classifier coverage gap, not missing data. Analysis shows only 1.5% of bugs have no first-comment text. The remaining ~28% have text but use language outside the keyword patterns — typically incident report prose that doesn't trigger channel-specific keywords.

## Audit Intelligence Methodology

### Bug Retrospective

For each CA, the pipeline constructs a retrospective matching Bugzilla incidents to the audit periods that were active when the incident occurred:

1. Each CA's Bugzilla bugs are pulled from `bugs_by_ca.json` with their open date (and incident date where parseable from the first comment).
2. CCADB provides audit period start/end dates for each root certificate. For CAs with multiple root certificates under different audit periods, the periods are unioned.
3. A bug is "in scope" for an audit period if the incident date falls within `[period_start, period_end]`. Where only the bug open date is available (incident date not parseable), the open date is used as a conservative upper bound.
4. The parsed audit letter is searched for the bug: first by Bugzilla ID, then by cert serial numbers extracted from the bug text, then by description similarity against known incident text.
5. Match confidence is recorded as `confirmed` (Bugzilla ID found), `probable` (serial or description match above threshold), or `none` (not found).

The **in-period detection rate** for an auditor is:

```
detection_rate = bugs with confirmed/probable match / total in-scope bugs for that auditor's clients
```

Across the corpus, this figure is approximately 29% as of the most recent pipeline run (114 caught of 390 in-scope bugs) — auditors report about 1 in 3 incidents that occurred during the period they audited. The figure is stored in `audits.json summary.in_period_detection_rate` and updated on each pipeline run; it should not be treated as a fixed constant.

### Letter Quality Score (0–100)

Each audit letter receives a quality score based on observable signals:

| Signal | Points |
|--------|--------|
| Scope completeness (all CCADB roots covered by letter) | 0–25 |
| Period continuity (no gap since prior letter) | 0–15 |
| Opinion type: unqualified | 20, qualified/adverse/disclaimer = proportionally less |
| Appendix D present (WebTrust) or equivalent section (ETSI) | 0–20 |
| Disclosed items with specific identifiers (Bugzilla IDs, cert serials) | 0–20 |

The score is a research instrument, not an official audit quality measure. Letters that cannot be parsed receive no score.

### Auditor Concentration

Auditor HHI is computed from the count of distinct CA audits (one per CA per year) per auditing firm over the trailing 12-month window. A single firm auditing 30% of CAs contributes 900 to the HHI. The same DOJ/FTC thresholds used for market concentration apply.

## Trust Store Changelog Methodology

### Cross-Store Changelog (`trust_store_changelog.json`)

`fetch_trust_snapshots.py` takes a daily snapshot of the full CCADB trust store state (all roots, all four stores, inclusion flags). On each run it diffs today's snapshot against yesterday's. Any root that appears or disappears, or changes inclusion status in any store, generates a changelog entry. This is the only reliable data source for Apple trust store changes — Apple does not publish a structured changelog.

### Microsoft CTL Changelog (`microsoft_ctl_changelog.json`)

`fetch_microsoft_ctl.py` scrapes the monthly deployment notices published at learn.microsoft.com. These notices list roots added, removed, or modified in each monthly update to the Windows Certificate Trust List. The pipeline normalizes organization names and cross-references against CCADB to produce a structured change record. Coverage begins in 2020 (the period for which notices are reliably archived).

### Chrome Root Store Changelog (`chrome_root_store_changelog.json`)

`fetch_chrome_root_store.py` queries the Chromium Gitiles API to retrieve the commit history of the Chrome Root Store's data files. Each commit that modifies root inclusion is parsed to extract added/removed roots. Coverage begins in 2022 (when Chrome's independent root store launched).

## Compliance Obligation Growth Methodology

`fetch_compliance_growth.py` tracks the count of normative obligations placed on CAs across major regulatory sources over time. It uses convention-aware parsers (`obligation_parsers.py`) rather than a single keyword counter — different document types express requirements differently.

**Computed sources** (machine-readable text fetched directly):
- CA/B Forum TLS BR: PDFs 2012–2021 + GitHub tags 2021–present
- CA/B Forum EVG, NSR, S/MIME BR, CS BR: GitHub tags
- Mozilla MRSP: GitHub markdown
- IETF RFCs 5280 (PKIX), 9162 (CT), 8659 (CAA), 8555 (ACME) — operative versions only
- NIS2 Directive: EUR-Lex HTML
- NIST SP 800-53 Rev 5: OSCAL JSON structured catalog

**Curated sources** (paywalled or without clean machine-readable text, manually counted):
- Chrome Root Program Policy (launched September 2022)
- Apple Root Certificate Program
- WebTrust for CAs criteria
- ETSI EN 319 4xx / TS 119 xxx stack

**Limitation:** Obligation counts are a proxy for regulatory complexity, not a direct measure of compliance burden. Two requirements may differ vastly in operational cost. Changes in document structure or numbering can affect counts without changing substantive requirements. The methodology note in the dashboard makes this explicit.

## Trust Scope

All current-ecosystem analysis is restricted to **trusted CAs**: those with `trust_store_count > 0` or a `parent_ca` subordinate relationship.

Of 249 CA owners tracked in CCADB, 97 are currently trusted. The trust scope filter is applied in `export_ui_bundle.py`. Pipeline raw JSON files preserve the full CCADB record.

**Exception — Operational Risk:** Incident timelines and classification breakdowns preserve the full historical record including incidents from later-distrusted CAs. The enforcement arc is part of the analysis.

**Distrust overrides:** `export_ui_bundle.py` applies distrust overrides from `pipeline/distrust/distrusted.json` to handle the lag between operational distrust and CCADB record updates. CNNIC, WoSign, DigiNotar, Entrust (2024), E-Tugra, TrustCor, and others are zeroed regardless of what CCADB currently shows.

## Ungoverned Exclusive CAs (Dark Matter)

For each trust store, the pipeline computes the count of CAs that are:
1. Exclusive to that store (not included in any other store)
2. Have zero public Bugzilla compliance record — never filed a bug, never appeared in a compliance bug

These CAs exist in a trust store but have no public evidence of compliance with the Baseline Requirements. They cannot be assessed by the community, cannot be monitored by other root programs, and have no public oversight trail.

**Current state:**
- Microsoft: 34 of 36 exclusive CAs — 94% of Microsoft-exclusive CAs have no public compliance record
- Mozilla: 2 of 2 exclusive CAs
- Chrome: 0 (no exclusive CAs)
- Apple: 0 (no exclusive CAs)

**Derivation:** `fetch_rpe.py` Phase 4 computes this from the intersection of `market_share.json` (exclusive CAs by store) and the Bugzilla bug filer/commenter record (whether a CA appears in any compliance bug).

## Government Classification Methodology

Government-affiliated CAs are classified into two categories based on structural relationships only:

- **Government-Operated:** The CA is directly run by a government agency as part of its governmental function.
  - Example: FNMT (Spain) — a division of the Royal Mint, a public entity under the Ministry of Economy.

- **State-Owned Enterprise:** The CA's parent organization has direct state ownership or was established by legislative mandate.
  - Example: Chunghwa Telecom (Taiwan) — majority state-owned telecommunications company.

**What does not qualify:** Customer relationships with government agencies.

Source: Manually curated `gov_classifications.json`. Each entry documents the specific structural relationship with supporting references.

## Jurisdiction Risk Methodology

**Three-axis model:** Each jurisdiction is assessed on three independent axes:

| Axis | Question |
|------|----------|
| Key Seizure | Can the government compel disclosure of CA private signing keys? |
| Compelled Issuance | Can the government force a CA to issue a specific certificate? |
| Secrecy | Can the government prohibit the CA from disclosing the compulsion? |

Axis values: Purpose-built (dedicated statutory tool) / General (general judicial process — baseline for any country with courts) / None (no authority or constitutional protection).

Risk tiers: High = all three purpose-built. Moderate = one or two purpose-built. Low = general only.

Source: Cross-verified against official legislation sites, EFF, Global Partners Digital, Wikipedia Key Disclosure Law, and CA/B Forum context. Each entry includes specific legislation with article numbers and statutory excerpts.

## Cryptographic Posture — Root Self-Signature Note

Root CA certificates are self-signed. The signature is **not validated** during certificate chain building — a root is trusted because it is in the trust store. SHA-1 on a self-signed root is not a vulnerability; it indicates generation era, not current exposure.

## Governance Risk — Comment Attribution

Identifying which Bugzilla comments come from root program staff uses a two-tier model:

**Tier 1 — Domain mapping:** Unambiguous root program domains are mapped wholesale: `@mozilla.org/mozilla.com` → Mozilla; `@apple.com` → Apple; `@microsoft.com` → Microsoft; `@chromium.org` → Chrome. Microsoft and Apple present no conflation risk because neither operates a public CA under their corporate domain.

**Tier 2 — Individual address registry:** Three cases require explicit per-address entries:

1. **Google:** Chrome root program and Google Trust Services (a public CA) both use `@google.com`. Named Chrome root program staff are listed individually with tenure dates. All other `@google.com` addresses default to the CA side and are excluded from governance metrics. This is the most consequential attribution decision in the pipeline.

2. **Former Mozilla staff who moved to CA operators.** Comments from their current employer domain are self-incident, not governance. Explicit entries with tenure cutoff dates ensure their post-Mozilla comments are not attributed to Mozilla oversight.

3. **Staff using personal email.** Some Bugzilla contributors used personal addresses throughout their tenure at a root program. These require explicit per-address entries.

**Cutoff dates:** When an individual's role changed, a `(program, cutoff_date)` tuple is stored. Comments after the cutoff are attributed to their current role.

**Default:** Unknown contributors are classified as `other`. The pipeline errs toward `other` when attribution is uncertain.

## CA/B Forum Participation Methodology

**Organization matching:** Each Bugzilla comment author's email domain is matched against the CA/B Forum member organization list. Ballot proposers and endorsers are matched by name using a canonical name mapping.

**Individual attribution:** Comment authors are tracked individually using email address as the primary key. Display names in the UI are masked to initials for privacy. Composite engagement score weights Bugzilla engagement (bugs commented on), bug filings, ballot proposals, and ballot endorsements.

**Recent vs. all-time:** The "Recent" toggle shows activity from 2021 onward for Bugzilla metrics (aligns with the recent governance window used throughout the dashboard) and the last 50 SC ballots for ballot metrics.

## Known Data Quality Issues

| Issue | Impact | Status |
|-------|--------|--------|
| crt.sh root-owner attribution | Amazon undercounted, GoDaddy overcounted | Documented, unfixable from CT data |
| Ministry of Digital Affairs: negative cert counts | Spurious −7 from crt.sh deduplication | Flagged in validation as warning |
| PKIoverheid: high nominal usage period | 5,475d from legacy non-TLS certs | Excluded by active-TLS filter (not_applicable) |
| Apple enforcement undercounting | Apple publishes support docs, not Bugzilla posts | Documented limitation; CCADB snapshots will build history over time |
| Unknown discovery channel (29%) | Classifier coverage gap, not missing data | Documented; LLM classifier validation planned (issue #2) |
| Microsoft CTL changelog lag | Monthly cadence vs. daily snapshot | Expected; documents operational behavior accurately |
| Audit letter parse failures (~15%) | Letters excluded from quality scoring | Recorded as "unavailable"; presence tracking unaffected |
| Audit letter incident attribution confidence | Non-Bugzilla-ID matches are probable, not confirmed | Confidence level recorded per match |

## Validation

A build-time validation script (`scripts/validate-data.cjs`) runs automated checks before every deployment:

- Market share sums to ~100%
- No negative all-time cert counts (warnings only — crt.sh deduplication artifact)
- Intersection root/owner counts internally consistent
- Incident yearly sums match total
- Per-CA self + external = total
- `yearsByClass` sum within tolerance of total (small gap from unclassifiable bugs is expected)
- All jurisdictions have risk level and legislation
- All roots have key_family and sig_hash

The build fails if any critical check fails. Warnings (expected data quality issues) are logged but do not fail the build.
