# WebPKI Governance Paper — Generation Prompt v1

## System prompt

You are a research scientist writing an IMC-quality academic measurement paper on WebPKI governance. You have deep expertise in PKI, certificate transparency, and internet security standards. Your writing is precise, fair, and analytically rigorous. You never use em dashes, colons as section labels, or AI phrasing patterns. You write in a human voice.

---

## User prompt

Write a complete LaTeX paper titled "Unmonitored by Design: A Longitudinal Measurement Study of Governance Failure in the Web PKI" using the three attached inputs: (1) the current LLM snapshot JSON from webpki.systematicreasoning.com/llm_snapshot.json, (2) the JSON schema describing its structure, and (3) the reference PDF showing a prior version of this paper as a structural and stylistic guide.

### How to use the inputs

The reference PDF shows the paper's structure, section organization, figure types, tone, and analytical framing. Treat it as a template for how to write, not what to write. Every quantitative claim in the paper you produce must come from the current snapshot JSON, not from numbers visible in the reference PDF. Where the reference PDF and the snapshot disagree, the snapshot is authoritative. Verify every number before writing it.

**Author and affiliation:** Single author block — "Research / Systematic Reasoning, Inc. / info@systematicreasoning.com". No named individuals. Include a DRAFT watermark and "Working Draft v0 — Not for citation or distribution" subtitle.

---

### Framing argument — establish this before the findings

The introduction must state the scaling mismatch explicitly before presenting any findings. The governance model this paper evaluates was designed when fewer than twenty CAs held trust and a handful of browser engineers could realistically know them all. The trust surface today comprises 335 roots across 89 CA owners, in a market so concentrated that six organizations issue 93.8% of all certificates while 74 tail CAs hold identical trust with per-certificate failure rates up to three orders of magnitude higher. The model was not designed for this structure. The paper's four findings are the empirical record of where the gap is.

This framing argument belongs in the third paragraph of the introduction, after the "this paper asks whether enforcement is happening" paragraph and before the contributions list. It should also anchor the first contributions bullet: the paper's primary contribution is the first empirical evaluation of whether a governance model designed for a small closed community still functions at 335 roots and 89 owners.

---

### Four structural findings to look for and establish from the data

These are the analytical questions the paper asks. Derive the specific numbers from the current snapshot.

**1. Power law of compliance.** Compute PPM (lifetime incidents per million all-time precertificates) for all CAs with nonzero incident histories and measurable issuance (share > 0). Use the market table's ppm field directly — it is pre-computed from all-time certificate counts. Run a log-log regression of PPM against market share (n will be the count of market entries with share > 0 and ppm > 0). Report slope, r value, and robustness checks. Tier CAs as head (share ≥ 1%), mid (0.01–1%), and tail (< 0.01%) and plot all tiers. Compute the ratio of tail CA median PPM to head CA mean PPM. In discussing the finding, note that high tail PPM reflects not just oversight underweighting by root programs but a structural compliance capacity gap — the tooling, staffing, and institutional memory that enable consistent compliant operations scale with organizational size.

**2. Root program oversight coverage.** Compute the annual Bugzilla coverage rate for each program from the snapshot's coverageRateByYear field. Identify each program's peak year and value, the decline years, the current 2026 Q1 level, and whether any recovery is occurring. State both peaks explicitly — Chrome and Mozilla peaked in different years — rather than describing a shared high-water mark. For Mozilla, surface any year where coverage recovered before declining again: if 2024 shows a higher rate than 2023, name it and use it analytically — a recovery that did not hold makes the subsequent collapse more significant, not less.

In discussing confounders, always acknowledge:
- (a) the September 2022 Chrome Root Program independence launch — frame this as a healthy evolution that shifted substantive governance to program-specific channels the Bugzilla metric cannot observe, not as a failure;
- (b) the 2022–2023 technology industry workforce reductions;
- (c) the 2023 eIDAS Article 45 legal challenge to root program autonomy.

**3. Discovery channel transition.** The snapshot's discoveryMethods fields will show whether CA self-filing or community/CT/linting is the dominant channel. Do not assume either is dominant — compute from the data. The correct framing depends entirely on what the numbers show. If CA self-filing has surged in recent years, explain what is driving it: the MPIC requirement generated a class of CPS-update governance failures that CT linting structurally cannot surface, and well-resourced CAs with internal compliance teams identified and filed their own deficiencies proactively. The self-filing surge is therefore not a generic improvement in monitoring culture — it is concentrated in the CAs with the institutional capacity to respond proactively, meaning the tail CAs with the highest failure rates are not the ones building self-monitoring discipline. State this asymmetry explicitly.

For the CT detection infrastructure, note its structural limits: CT linting reads certificate bytes and cannot detect whether a CA's CPS accurately describes its actual procedures, whether an incident response plan is credible, or whether a root cause analysis reflects genuine process change. These governance failures — which the yearsByClass data will show constitute a large fraction of 2025 incidents — are invisible to any tool that examines certificates alone.

Identify the rising CA self-filing rate and interpret it as the ecosystem beginning to internalize the monitoring function — with the caveat above about where that internalization is concentrated.

**4. Microsoft governance posture.** Use the enforcement data and comment attribution data in the snapshot to establish Microsoft's governance comment count (oversight of other CAs' incidents), its exclusive root count, and the CAs distrusted by peers that Microsoft still trusts. Distinguish precisely between Microsoft's self-incident responses (CA operator activity) and governance comments (root program oversight activity). For CAs exclusive to the Microsoft store, note that internal self-assessment is the only available monitoring mechanism — external investigative pressure from peer programs does not reach them.

Go further than the participation gap: check the dark matter field in the storePosture data. If a large fraction of Microsoft's exclusive CA owners have zero Bugzilla incident history, name that specifically. This is not merely a participation gap; it is structural invisibility — external investigators, researchers, and peer programs have no surface to examine. Whether the absence of incidents reflects genuine compliance or the absence of anyone looking is, by construction, unknowable from public data.

**5. 47-day validity transition readiness.** Use the usageDays field from the market data to tier CAs by readiness against the 200-day (current), 100-day (March 2027), and 47-day (March 2029) thresholds. Identify the CAs and certificate volumes in each tier. For the CAs in the 100–200d band, compute the percentage reduction in renewal period required and the months remaining until the 100-day cap.

Separate the failure modes by subscriber profile, not generically. GoDaddy's subscriber base is predominantly SMB hosting customers without DevOps pipelines; their dominant failure mode is expiry outages from missing the deadline, not rushed-automation misissuance. IdenTrust's book spans federal PKI, healthcare, and code signing — procurement cycles and change-control requirements that are structurally incompatible with automated renewal timelines, plus certificate uses (S/MIME identity binding, code signing) that do not map cleanly onto ACME's domain-validation model. Name these profiles explicitly rather than treating all at-risk CAs as equivalent. Connect the overall finding to the coverage rate as the velocity-oversight scissor.

---

### MTC transition coda — add this at the end of the conclusion

After the scaling-argument closing paragraph, add one paragraph connecting the paper's findings to the Merkle Tree Certificates transition. The connections to make, each of which must be stated specifically:

- The MTC document identifies CT compliance history as directly predictive of MTC issuance log operational reliability. A CA with persistent CT logging failures faces a harder version of the same problem when its issuance log becomes the trust anchor for signatureless certificates. The Bugzilla corpus this paper measures is the instrument that produces that risk signal.
- The CT linting and monitoring infrastructure this paper identifies as load-bearing is not merely analogous to MTC infrastructure — it is the literal foundation MTC extends. The ecosystem has built this before; that shortens Phase 1.
- The governance fragilities documented in this paper are not a legacy problem the MTC transition will inherit passively. Dual issuance for 15–20 years doubles the compliance surface — every CA must provision both X.509 and MTC pipelines, each subject to separate audit scope and incident obligations — and this arrives while the oversight apparatus sits at its lowest measured capacity in twelve years.
- Close with: the X.509 WebPKI's governance fragilities are the conditions under which the MTC transition will occur.

Do not make this paragraph a summary of MTC architecture or timeline. The paper has no MTC section and needs none. The coda's job is to use the MTC transition as the proof of stakes for the Observatory's measurement work — nothing more.

---

### Tone requirements — these are critical and do not vary with the data

The paper measures institutional behavior under structural constraints, not institutional failure. The people doing this work deserve recognition. Coverage rate declines reflect structural vulnerability, not absent effort. Never use "collapsed" — use "declined." Chrome's partial recovery, if visible in the data, is genuine progress and should be credited. The multi-program architecture is genuinely resilient against organizational rot in any single program — say this before describing its gap. The enforcement distrust record (whatever it shows in the current snapshot) is evidence the function still works on sufficiently documented cases — use it as counterevidence, not just as context.

---

### Methodological transparency requirements — these do not vary with the data

The coverage rate measures Bugzilla comment engagement only. State this scope limitation at the opening of the coverage rate section before presenting any figures. State it in the figure caption. The cross-program comparability note must acknowledge that Bugzilla is Mozilla's infrastructure, that Mozilla generates more administrative comments, and that the LLM classifier's exclusion of administrative actions addresses this asymmetry. It must also explain why the shared single-filing system makes the denominators comparable.

Document and distinguish the two corpus sizes: the incident count (active-CA bugs, excluding distrusted CAs) and the discovery channel corpus (non-distrusted bugs including sub-operator naming variants). Explain the gap between them. In the discovery table, note that the all-time column and the annual columns use different denominators and are not directly comparable in absolute terms.

Address the Unknown discovery channel substantively: show its annual range and that it has no systematic temporal or program skew, and show what the discovery distribution looks like under proportional redistribution. Show that the central finding — whatever channel is dominant — is invariant to any redistribution assumption.

Acknowledge the classifier limitation explicitly: no held-out eval, planned future work. Add a sensitivity argument showing the coverage rate trend is robust to a 20% classifier error rate because the trend spans 40–60 percentage points and would require a structured, mechanistically implausible error pattern to eliminate.

---

### Section 2.2 (Certificate Transparency) — scope carefully

The CT background section should describe what CT and CT linting tools do mechanically, and gesture at their role in incident discovery without previewing the specific percentages. Those belong in Section 5.4 where they are argued properly with the full corpus context. Keep Section 2.2 descriptive: what CT provides, what linting tools do, and a forward pointer to where their measured role is established.

---

### Analogies to use, each in the right place

The US federal electoral system analogy belongs in the first discussion subsection — three paragraphs, leading with architectural resilience before the participation gap. Microsoft's situation maps onto the gap precisely, and the dark matter paragraph (exclusive CAs with zero incident history) extends the analogy: not just a jurisdiction that doesn't participate in oversight, but one where 94% of its exclusive CAs have no public record at all. The aviation safety reporting analogy belongs in the CT linting section: linters count events, investigators classify patterns and route findings to actors who can change conditions — these are complements not substitutes. The Heartbleed/OpenSSF analogy belongs in structural remedies: once the problem is measurable, coordinated institutional investment can address it.

---

### CABF participation desert — frame as voting rights, not just engagement

The section on CABF participation must include the names and bug counts of the leading active CA-side organizations. Then make the voting-rights argument explicitly: a CA that never engages a compliance bug, never proposes or endorses a ballot, and never files a proactive incident report still votes on the Baseline Requirements that govern every CA in the ecosystem. Non-participating members are non-participating voters in a standards process where the requirements they ignore bind everyone.

The individual contributor datum (one person engaging more bugs than all but two member organizations) is a compounding observation. Bridge to it from the institutional level with a sentence like "the institutional thinness compounds at the individual level" — the flow should be: institutions thin → even thinner than you think → one person is load-bearing.

---

### Citations required (15)

All 15 must appear in the body. Placement guidance:

| Key | Paper | Placement |
|-----|-------|-----------|
| snapshot | Observatory LLM Snapshot, March 2026 | methods |
| github | Observatory Source Repository | methods |
| github-code | fetch_rpe.py pipeline | methods |
| durumeric2013 | Durumeric et al., IMC 2013 | related work |
| laurie2014 | Laurie et al., RFC 6962, 2013 | CT background |
| vandersloot2017 | VanderSloot et al., IMC 2016 | related work |
| felt2017 | Felt et al., USENIX Security 2017 | related work |
| akhawe2013 | Akhawe & Felt, USENIX Security 2013 | related work |
| clark2013 | Clark & van Oorschot, IEEE S&P 2013 | related work |
| chung2017 | Chung et al., IMC 2017 | with liu2015 on revocation |
| amann2017 | Amann et al., IMC 2017 — Mission Accomplished | Symantec/Entrust enforcement discussion |
| aas2019 | Aas et al., CCS 2019 — Let's Encrypt | ISRG self-detection rate |
| liu2015 | Liu et al., IMC 2015 — revocation | CT background / revocation |
| sun2024 | Sun et al., NDSS 2024 — CT revisited | CT linting layer description |
| eghbal2016 | Eghbal, Ford Foundation 2016 — Roads and Bridges | structural remedies / OpenSSF paragraph |

---

### Things never to write

- Never reference prior versions, prior drafts, corrected measurements, earlier estimates, or original classifiers. The paper is a single coherent research effort with no revision history.
- Never describe Chrome's governance decline as institutional failure. Always acknowledge the three confounders. Always credit any partial recovery visible in the data.
- Never assert Entrust was the largest CA by market weight ever distrusted without checking — verify against the snapshot's distrust data. If Symantec held larger market share at distrust time, say so explicitly.
- Never write discovery channel percentages that sum to more than 100% within any single column.
- Never hardcode numbers from the reference PDF into the paper — all quantitative claims derive from the current snapshot.
- Never assert CT linting is the dominant discovery channel without verifying the current snapshot. The dominant channel must be computed from the data. Prior drafts had this wrong.
- Never describe Chrome and Mozilla as sharing a single coverage rate peak year. They peaked in different years; name both.
- Never use "partially brightening but still stark" or similar hedge constructions when describing the CABF participation data. State the structural finding directly.

---

### Figures required (6)

All figures use TikZ/pgfplots. All coordinate values must be extracted from the current snapshot fields listed, not copied from the reference PDF. Use `ymajorgrids=true` or `xmajorgrids=true` for grid lines in stacked bar charts rather than `grid=y` or `grid=x`, which are not valid choices in pgfplots 1.18.

| Figure | Type | Data source field |
|--------|------|-------------------|
| 1 | PPM vs market share log-log scatter with regression line | market (ppm and share fields); plot all tiers; n = count of entries with share > 0 and ppm > 0 |
| 2 | Annual Bugzilla coverage rate with dashed departure markers | governance.coverageRateByYear |
| 3 | Quarterly governance comment volume showing step-downs | governance.oversightQuarterly; departure marker indices count from 2017-Q1 = 1 |
| 4 | Governance comment concentration horizontal bars by program | governance.oversightConcentration |
| 5 | Annual incident volume by classification stacked bar | incidents.yearsByClass |
| 6 | Incident discovery channel by year stacked bar | governance.discoveryMethods.by_year |

---

### Output

Complete compilable LaTeX, 12–18 pages in two-column letterpaper format, with DRAFT watermark and "Working Draft v0 — Not for citation or distribution" subtitle, that compiles clean on first attempt. Do not truncate findings or compress arguments to hit a page target — this is a working draft. Page reduction for specific venue submission limits happens in a later pass.
