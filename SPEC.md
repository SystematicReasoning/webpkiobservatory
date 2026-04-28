# Specification

## Purpose

The WebPKI Observatory provides a quantitative, evidence-based view of the Certificate Authority ecosystem that underpins TLS on the public internet. It exists because:

1. **No single source shows the full picture.** crt.sh has issuance data. CCADB has trust store metadata. Bugzilla has incident records. StatCounter has browser share. cabforum.org has governance records. No existing tool combines these into a unified analytical view.

2. **Policy decisions need data.** Root program managers, CA/B Forum participants, and security researchers make consequential decisions about which CAs to trust. These decisions should be informed by observable data, not institutional memory or anecdote.

3. **The trust surface should be visible.** Every CA root in a trust store can issue a certificate for any domain on the internet. The ecosystem's actual concentration, geographic distribution, government exposure, governance quality, and operational track record should be measurable and public.

## Scope

**In scope:** Currently trusted CAs — those with at least one root certificate included in Mozilla, Chrome, Microsoft, or Apple trust stores, plus subordinate CAs operating under a trusted parent's roots.

**Out of scope:** Distrusted CAs, private/enterprise CAs, CAs that have applied but not yet been included, certificate transparency log operators, ACME protocol providers (as distinct from CAs), and non-WebPKI certificate ecosystems (e.g., national eID, S/MIME-only issuers not in browser stores).

## What Each Tab Measures

### Tab 1: Market Share

**Question:** How is certificate issuance distributed across CAs?

**Metric:** Unexpired precertificates per CA owner, from Certificate Transparency logs via crt.sh.

**Unit of analysis:** CA Owner (organization level, not individual root or intermediate).

**Derivations:**
- Market share % = CA's unexpired precerts / total unexpired precerts × 100
- Cumulative share = running sum of market share by rank
- Usage period = 365 / (all-time precerts / unexpired precerts) — measures replacement behavior, not certificate validity period
- Web coverage = sum of browser market shares for trust stores that include this CA

**Known limitation:** crt.sh attributes certificates to the root owner, not the issuing CA. Certificates issued through cross-signed intermediates (e.g., Amazon ACM issuing under GoDaddy/Starfield roots) are attributed to the root owner. CAs with known attribution gaps are flagged with ⚠.

---

### Tab 2: Trust Surface

**Question:** What does the root certificate infrastructure look like across the four major trust stores?

**Metrics:**
- Root and owner counts per store and per store combination
- Per-store portfolio incident rate (weighted by issuance volume)
- Root expiration timeline and heatmap
- Capability distribution (TLS, EV, S/MIME, code signing)
- Web coverage by store combination
- Notable trust store disagreements

**Derivations:**
- Web coverage uses StatCounter browser market share: Chrome (~78%, includes Edge/Samsung/Opera/Chromium-based), Apple (~16%), Mozilla (~2.3%), Microsoft (~0% web — Edge uses Chrome's store)
- Portfolio ops rate = (total incidents for CAs in this store / total all-time certs for CAs in this store) × 1,000,000
- Intermediate count de-duplicates by Subject Key Identifier — cross-signed intermediates sharing the same key are counted once

---

### Tab 3: Concentration Risk

**Question:** How concentrated is certificate issuance, and what does that mean for ecosystem resilience?

**Metrics:**
- Herfindahl-Hirschman Index (HHI)
- CR3, CR5, CR7 (concentration ratios)
- Cumulative concentration curve
- Market share treemap

**Derivations:**
- HHI = Σ(market share %)² across all trusted CAs. DOJ/FTC thresholds: <1,500 unconcentrated, 1,500–2,500 moderate, >2,500 highly concentrated.

**Context:** Concentration matters for blast radius (misissuance at a dominant CA affects more of the internet), root program dynamics, and ecosystem resilience if a major CA is distrusted.

---

### Tab 4: Long Tail Risk

**Question:** How many CAs carry disproportionate trust relative to their issuance volume?

**Metric:** CAs below the 99.99% cumulative issuance threshold.

**Derivations:**
- Head = fewest CAs whose cumulative issuance ≥ 99.99% of all unexpired certificates. Everything below is "tail."
- Tail CAs grouped by trust store presence (4 stores, 3 stores, 2 stores, 1 store)

**Key insight:** Every trusted root carries identical technical capability regardless of volume. A root in all 4 stores can issue for any domain whether it issues 500 million certificates or 5.

---

### Tab 5: Geographic Risk

**Question:** Where are trusted CA organizations headquartered?

**Metrics:**
- CA count and issuance share by region and country
- Divergence between "by CA count" and "by issuance" per region

**Derivations:**
- Country = CA Owner country from CCADB (jurisdiction of incorporation)
- Regions: United States, Europe, Asia-Pacific, Americas, Middle East/Africa, Other

**Known limitation:** Jurisdiction reflects incorporation, not operational location or subscriber geography.

---

### Tab 6: Government Risk

**Question:** How many trusted CAs have structural ties to governments?

**Metrics:**
- Count of government-operated and state-owned enterprise CAs
- Issuance share from government-tied CAs
- Trust store presence of government CAs
- Geographic distribution

**Derivations:**
- Government-Operated: CA directly run by a government agency
- State-Owned Enterprise: entity with direct state ownership or legislative mandate
- Customer relationships with government agencies do not qualify

**Source:** Manually curated `gov_classifications.json` — each classification documents a specific structural relationship.

---

### Tab 7: Jurisdiction Risk

**Question:** Which trusted CAs are in jurisdictions with government key seizure or compelled cooperation laws?

**Metrics:**
- Three-axis compulsion assessment per jurisdiction: key seizure, compelled issuance, secrecy
- Certificate volume exposed per risk tier (high, moderate, low)
- CA count per jurisdiction with legislation excerpts

**Three-axis model:**
- Key Seizure: Can the government compel disclosure of CA private signing keys?
- Compelled Issuance: Can the government force a CA to issue a specific certificate?
- Secrecy: Can the government prohibit the CA from disclosing the compulsion?

Each axis: Purpose-built (dedicated statutory authority) / General (judicial process, baseline for any country with courts) / None (no authority or constitutional protection).

**Risk tiers:** High = all three axes purpose-built (China, UK, Australia). Moderate = one or two purpose-built. Low = general process only (US, Germany, Canada).

**The critical threat:** Compelled issuance + secrecy = a CA forced to issue a fraudulent certificate that cannot disclose it to root programs, auditors, or subscribers.

---

### Tab 8: Operational Risk

**Question:** What is the incident track record of trusted CAs?

**Metrics:**
- Annual incident volume (2014–present) with milestone annotations
- Per-CA incident count, self-report rate, and incidents per million all-time certificates (PPM)
- LLM-classified incident taxonomy: misissuance, revocation, governance, validation
- Discovery method attribution: how incidents are detected (self-detected, CT/community, external researcher, audit, root program)
- Detection capability scatter plot (self-report rate vs. incident density)

**Derivations:**
- PPM = (cumulative Bugzilla bugs / all-time precertificates) × 1,000,000
- Self-report rate = proportion of incidents filed by the CA itself (Bugzilla creator email domain match)
- Discovery classification: keyword + LLM classifier on the first comment of each bug. Corpus: 1,505 active-CA bugs (187 distrusted-CA bugs excluded from discovery analysis)

**Discovery channels:**
- Self-detected (~22%): CA's own linting, monitoring, or internal audit
- External researcher (~20%): Security researcher, CT watchdog, or third party
- Community (~17%): CT log analysis tools (pkilint, x509lint), MDSP/cabforum discussion
- Unknown (~29%): First comment exists but no channel keyword matches
- Audit (~8%): External auditor finding
- Root program (~4%): Root program staff filing directly

**Scope note:** Yearly totals and per-CA fingerprints preserve the full historical record including incidents from later-distrusted CAs. The PPM metric normalizes for volume. High incident count at a transparent CA with a strong self-report rate is a sign of health, not failure.

---

### Tab 9: Cryptographic Posture

**Question:** What cryptographic algorithms do trusted root certificates use?

**Metrics:**
- Key family distribution (RSA vs. ECC)
- Key size distribution (RSA-2048, RSA-4096, P-256, P-384)
- Signature hash distribution (SHA-1, SHA-256, SHA-384, SHA-512)
- Per-CA algorithm posture with standards body compliance flags
- Root creation timeline (algorithm trends over time)
- Soonest expiring roots

**Standards bodies:** NIST SP 800-57, ECRYPT-CSA D5.4, BSI TR-02102-1, ANSSI RGS v2.03, NSA CNSA Suite.

**Important context:** Root CA certificates are self-signed. SHA-1 on a self-signed root is not a vulnerability — roots are trusted because they are in the trust store, not because their self-signature is verified. The hash algorithm indicates generation era, not current cryptographic exposure.

---

### Tab 10: Distrust History

**Question:** What does the historical record of CA distrusts tell us about ecosystem governance?

**Metrics:**
- 16 distrust events (2011–2024) classified across four dimensions
- Compliance posture: Willful, Argumentative, Negligent, Incompetent, Accidental
- Distrust pathway: Immediate, Triggered, Gradual, Negotiated
- Response quality assessment per CA
- 22 contributing factor tags from Bugzilla evidence
- Per-store distrust dates and first-action attribution
- Time-to-removal: median ~3 years from first incident to distrust

**Data:** `pipeline/distrust/distrusted.json` — curated dataset, single source of truth for both this tab and the Governance Risk enforcement metrics. When a new CA is distrusted, updating this file once updates both tabs.

**Classification tiers:** Curated (pre-2017, hand-reviewed against root program announcements), High (5+ Bugzilla bugs + cached metadata), Med-High (sparse Bugzilla, primarily metadata), Medium (Bugzilla only).

**Accuracy:** 87% posture accuracy and 88% tag recall against a 15-event ground truth set.

---

### Tab 11: Policy Compliance

**Question:** How are CAs tracking against the BR certificate validity reductions, and which subscriber populations are not yet ready?

**Metrics:**
- Active TLS issuers grouped by average certificate usage period vs. upcoming BR thresholds
- ">200d avg" flag for CAs whose subscriber population average exceeds the 200-day limit (effective March 15, 2026). This measures subscriber readiness, not active issuance compliance — certs issued before the enforcement date are grandfathered.
- Projected impact at 100-day (March 2027) and 47-day (March 2029) limits

**BR validity schedule:**
- 200 days: March 15, 2026 (current)
- 100 days: March 15, 2027
- 47 days: March 15, 2029

**Derivations:**
- Usage period = 365 / (all-time precerts / unexpired precerts). Measures how frequently subscribers replace certificates, not the validity period on the certificate. Let's Encrypt issues 90-day certs but the usage period is ~22 days because subscribers auto-renew at 60 days.
- `brStatus` is computed in `fetch_and_join.py` using `unexpired_precerts` (CT log counts) to match the `avgDays` calculation. Status values: `violation` / `risk_2027` / `risk_2029` / `compliant` / `not_applicable`.

**Active-TLS filter:** The tab excludes CAs that don't meet the active-TLS qualification gate:
- `tls_capable = True`
- `unexpired_precerts ≥ 1,000` (genuine current TLS issuance from CT logs)
- Trusted by at least one current browser store

CAs failing this gate get `brStatus = not_applicable`. This prevents legacy cert populations — old S/MIME chains, historical code signing roots, government PKI certs issued under different regulatory regimes — from inflating the ">200d" bucket. Example: Government of the Netherlands (PKIoverheid) shows a usage period of 5,475 days because it issued long-lived government certs years ago; it is not an active TLS issuer.

**BREACH NOW:** A CA labeled BREACH NOW has a population-average usage period exceeding 200 days. This means their subscriber base is replacing certificates less frequently than the BR now requires. It does not mean the CA is issuing individual certificates with excess validity — a CA can have a low overall usage period while still having a specific batch that exceeded the limit (see D-Trust bug 2023458: 19 precertificates exceeding 200 days, all revoked after self-detection).

**CAs with subscriber populations averaging >200d (as of March 2026):** HARICA (343d), NAVER Cloud Trust Services (309d), TrustAsia Technologies (286d), OISTE (365d). These CAs face the most subscriber disruption from the new limit, but actual issuance compliance requires Bugzilla verification.

If `brStatus` is not present in the bundle (older build), the tab shows `DataPending` rather than falling back to unfiltered behavior.

---

### Tab 12: Governance Risk

**Question:** How effectively do root programs govern the CAs they trust?

**Metrics:**
- Report card heatmap: 8 metrics per program across governance activity and trust surface
- KPI cards: enforcement leadership (who initiated distrusts) + oversight comments (who comments on other CAs' bugs)
- Enforcement: 16 distrust events — who led, who followed, who hasn't acted, who still trusts removed CAs
- Bugzilla coverage rate by year: percentage of all open compliance bugs each program commented on
- Oversight breakdown: Bugzilla Coverage vs. Substantive Oversight (with percentage)
- Oversight trend: quarterly comments per program with concentration analysis
- Policy leadership: CA/B Forum ballot proposals, endorsements, votes
- Trust surface: CA owners, roots, exclusive roots, gov-affiliated CAs
- Ungoverned exclusive CAs (dark matter): CAs exclusive to one store with zero public compliance record

**Report card rows:**
1. Enforcement (acted / total distrust events)
2. Led Distrust (times the program was first to publicly act)
3. Bugzilla Coverage (CA compliance bugs engaged with governance comments)
4. Substantive Oversight (bugs where the program left a technically substantive comment — cert/CRL analysis, specific BR citations with evidence; shown as count and % of coverage)
5. Ballots Proposed (SC + NetSec working groups)
6. Ballots Voted (participation rate)
7. CA Owners (trust store size)
8. Ungoverned Exclusive CAs (dark matter)

**Substantive Oversight:** Classified by LLM with a two-field prompt per comment: `governance` (is this a genuine governance engagement?) and `technical` (does it contain technical findings — cert/CRL analysis, specific BR citations with evidence, root cause identification, scope quantification — rather than process enforcement only?). Bugzilla Coverage counts governance=True comments; Substantive Oversight counts governance=True AND technical=True comments. The split reveals that 60–80% of governance comments are process-only (overdue notices, follow-up requests, housekeeping). Chrome's governance comments are more technically substantive (~40%) than Mozilla's (~19% recently).

**Ungoverned Exclusive CAs (dark matter):** Per store, the count of CAs exclusive to that store (not in any other store) with zero public Bugzilla compliance record — never filed a bug, never appeared in a compliance bug. Microsoft: 34 of 36 exclusive CAs have no public compliance record. Chrome and Apple: 0. These CAs have no public evidence that they comply with the Baseline Requirements.

**Key attribution note:** Microsoft operates a CA (Microsoft PKI Services). Nearly all of Microsoft's Bugzilla activity is self-incident responses to their own CA's compliance failures, not governance oversight of other CAs. The pipeline separates self-incident from oversight attribution by email domain.

---

### Tab 13: Ecosystem Participation

**Question:** Who participates in CA/Browser Forum governance, and how actively?

**Metrics:**
- Per-organization engagement across three dimensions: Bugzilla (commenting on CA compliance bugs), ballot activity (proposing and endorsing SC/CSC/SMC/NS ballots), and bug filing (creating compliance bugs)
- Individual participation leaderboard: Bugzilla bugs engaged, technical comments, bug filings, ballot proposals
- Zero-engagement count: CA/B Forum member organizations with no public activity in any channel
- Recent vs. all-time toggle

**Data:**
- Organization list from CA/B Forum member roster (CCADB member organizations)
- Bugzilla engagement from comment author email domain matching
- Ballot data from `cabforum_ballots.json` covering all SC, CSC, SMC, and NS working group ballots

**Context:** 35 of 56 CA/B Forum member organizations show zero engagement across all three channels. This includes CAs that participate through other means (F2F attendance, private communications) not captured by public data.

**Individual leaderboard sort options:** Composite score (default), Bugzilla engagement, technical comments, bug filings, ballot proposals, name.

**Privacy:** Individual email addresses are masked in the UI (initials only). The pipeline stores full addresses in the cache for attribution but the dashboard exposes only display names and aggregate counts.

---

### Tab 14: Audit Intelligence

**Question:** Do annual audit letters reflect the compliance record CAs actually generated?

**Metrics:**
- Per-CA audit profile: audit standard (WebTrust / ETSI), opinion type, audit period, auditor identity, and whether the audit letter was parseable
- Bug retrospective: for each CA, which of its Bugzilla compliance incidents fell within each completed audit period — and whether the auditor reported them
- Per-auditor detection rate: of incidents that occurred during an audit period, what fraction appear in the corresponding letter's disclosed items
- Auditor concentration: HHI and CR3/CR5 across auditing firms weighted by number of CA audits
- Letter quality score (0–100): composite of completeness signals — scope coverage, Appendix D presence, disclosed item count, ALV-equivalent fingerprint checks
- Transparency gap: incidents in scope that appear in zero audit letters

**Key finding:** Across the corpus, auditors disclose in their letters approximately 29% of incidents that occurred during their audit period (114 of 390 in-scope bugs as of the most recent pipeline run). The remainder appear in Bugzilla without any corresponding disclosure in the auditor's letter. This figure is computed dynamically — see `audits.json summary.in_period_detection_rate` for the current value.

**Data sources:**
- CCADB CSV: audit metadata (standard, dates, auditor, PDF URL) for every root certificate
- CPA Canada getPDFWebTrust API: direct PDF access for ~365 WebTrust roots
- Direct PDF URLs on auditor/CA domains: ~175 ETSI roots
- `bugs_by_ca.json`: per-CA incident timeline from Bugzilla (produced by `fetch_incidents.py`)

**Bug retrospective methodology:** Each Bugzilla bug is matched to audit periods by comparing the bug's open date (or incident date where parseable from the first comment) against each CA's audit period start/end dates. A bug is "in scope" for an audit if the incident occurred during the audit period. The letter is checked for disclosure by scanning for the Bugzilla bug ID, known cert serial numbers from the incident, or substantive description matches.

**Auditor concentration:** Auditor HHI is computed from the count of distinct CA audits per firm over the trailing 12 months. Big Four firms (KPMG, EY, Deloitte, PwC) and WebTrust specialists (Schellman, BDO, STRA) dominate. High concentration in the auditor market is itself a systemic risk signal — a single auditor methodology failure affects a large fraction of the ecosystem.

**Letter quality score components:** Scope completeness (are all roots in the CCADB record covered by this letter?), period continuity (does the audit period follow immediately from the previous letter with no gap?), opinion type (unqualified = full marks), Appendix D presence (WebTrust letters should include an Appendix D for disclosed incidents), item specificity (disclosed items with Bugzilla IDs or cert serials score higher than narrative-only disclosures).

**Scope:** Analysis covers active CAs only. Letters for distrusted CAs are included where they contributed to the distrust decision (historical record) but are excluded from current detection rate statistics.

**Limitation:** PDF parsing succeeds for ~85% of accessible letters. ETSI letters have less structured formats than WebTrust letters, producing lower parse confidence scores. Letters hosted behind authentication walls or on inaccessible domains are recorded as "unavailable" and excluded from quality scoring but not from presence tracking.

---

## Data Freshness

The pipeline runs daily at 06:00 UTC. Data freshness is tracked in `metadata.json` and displayed in the dashboard footer.

| Source | Stale Warning | Critical Warning |
|--------|--------------|--------------------|
| crt.sh / CCADB | 48 hours | 7 days |
| Bugzilla | 72 hours | 14 days |
| StatCounter | 30 days | 90 days |
| Audit letters (CCADB metadata) | 48 hours | 7 days |
| Audit letters (PDF cache) | 90 days TTL | — |
| Legislation (jurisdiction) | Manual review | — |
| Government classifications | Manual review | — |

## Validation

A build-time validation script (`scripts/validate-data.cjs`) runs automated checks before every build:
- Market share sums to ~100%
- No negative certificate counts (crt.sh deduplication artifact, flagged as warning)
- Intersection root/owner counts internally consistent
- Incident yearly sums match total
- Per-CA self + external = total
- `yearsByClass` sum within tolerance of total (small gap expected from unclassifiable bugs)
- All jurisdictions have risk level and legislation
- All roots have key_family and sig_hash

The build fails if any critical check fails. Warnings (data quality issues that are documented and expected) do not fail the build.
