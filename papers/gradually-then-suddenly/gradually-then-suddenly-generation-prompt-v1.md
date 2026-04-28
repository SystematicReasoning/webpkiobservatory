# WebPKI Audit Paper — Generation Prompt v1

## System prompt

You are a research scientist writing an IMC-quality academic measurement paper on WebPKI audit effectiveness. You have deep expertise in PKI, certificate transparency, compliance auditing, and internet security standards. Your writing is precise, fair, and analytically rigorous. You never use em dashes, colons as section labels, or AI phrasing patterns. You write in a human voice.

---

## User prompt

Write a complete LaTeX paper titled "Gradually, Then Suddenly: Measuring Audit Failure in the Web PKI" using the three attached inputs: (1) the current LLM snapshot JSON from webpki.systematicreasoning.com/llm_snapshot.json, (2) the JSON schema describing its structure, and (3) the reference PDF showing the sister paper "Unmonitored by Design" as a structural and stylistic guide.

### How to use the inputs

The reference PDF is the sister paper. It establishes the measurement apparatus and the governance context this paper builds on. Match its LaTeX style, figure conventions, tone, and citation format exactly. Every quantitative claim in the paper you produce must come from the current snapshot JSON, specifically the `auditIntelligence` object and the `incidents` fields. Where the reference PDF and the snapshot disagree, the snapshot is authoritative. Verify every number before writing it.

**Author and affiliation:** Single author block — "Research / Systematic Reasoning, Inc. / info@systematicreasoning.com". No named individuals. Include a DRAFT watermark and "Working Draft v0 — Not for citation or distribution" subtitle.

**Sister paper citation:** The paper must cite the sister paper as: R. Hurst, "Unmonitored by Design: A Longitudinal Measurement Study of Governance Failure in the Web PKI," Systematic Reasoning, Inc., Working Draft, 2026. It must be referenced in the introduction as establishing the measurement corpus this paper uses, and in the discussion where audit detection connects to the governance capacity collapse the sister paper documents.


---

### Sister paper style — match these specific properties

The reference PDF establishes a precise style. These are not generic instructions — they are the specific properties that make these papers recognizable as a pair.

**Opening sentence construction.** Paper 1 opens: "The security of HTTPS traffic does not ultimately rest on cryptographic primitives. It rests on the willingness and capacity of browser vendors to enforce compliance." The technique: one sentence states what the reader assumes, the next sentence replaces it with what is actually true. The opening of this paper should use the same construction: one sentence stating what readers assume about annual audits, the next replacing it with the measured reality.

**Paragraph rhythm.** Paper 1 uses short declarative sentences to open and close paragraphs, with longer analytical sentences in the middle. Avoid multi-clause opening sentences. The reader should never need to re-read an opening sentence to understand it.

**Quantitative claim format.** Numbers appear parenthetically after the analytical claim, not before it. Write "the relationship is tight ($r = -0.940$)" not "$r = -0.940$, indicating a tight relationship." The analysis comes first; the supporting number follows.

**Naming specific actors.** Paper 1 names specific CAs (GoDaddy, IdenTrust, ISRG), specific coverage rates, and specific individuals' contribution fractions. This paper must name specific auditor firms — MATRIX Ltd., Scott S. Perry CPA, KPMG, Ernst & Young, LSTI — with their detection rates. Named firms are not accused; they are measured. The paper names them the way a financial paper names companies: factually, with the data as the only claim being made.

**The confounder acknowledgment structure.** Every section that presents a finding that could be explained by structural factors rather than individual failure must include an explicit confounder paragraph. Paper 1 does this for Chrome's coverage decline (three confounders: program independence launch, workforce reductions, eIDAS challenge). This paper must do it for zero-detection firms (confounders: the pipeline cannot observe undisclosed matter treatment; letters may address incidents without explicit Bugzilla citation; scope of engagement letters may exclude certain incident types).

**Section openings.** Each empirical section opens by stating what the measurement captures and what it does not, before presenting any numbers. Paper 1: "The coverage rate measures Bugzilla comment engagement only." This paper's detection section must open with an equivalent scope statement before any percentages.

**The positive-before-negative structure.** Paper 1 credits high-performing actors before presenting failures — Apple's rising participation, the enforcement record demonstrating the distrust function works. This paper must credit MATRIX (100%), SunRise (58%), and AENOR (56%) before presenting the zero-detection firms.

**Table formatting.** Use `\footnotesize`, `\setlength{\tabcolsep}{3pt}`, `tabularx`, `\toprule`, `\midrule`, `\bottomrule`. The main auditor detection table should match Table 1's format exactly.

**Figure captions.** Captions in Paper 1 state the finding, then the supporting statistics, then any exclusions or caveats — in that order. Example: "Tail CAs carry failure densities $>10^3\times$ the head [finding]. Slope $=-0.87$, $r=-0.938$ [statistics]. CAs with share $=0$ are excluded from the regression [exclusion]." Follow this structure for every figure caption.

**The closing paragraph of each empirical section.** Paper 1 ends each empirical section by stating the governance implication, not restating the finding. The power law section does not end by repeating the slope; it ends with "Root program engineers are therefore systematically underweighting the CAs with the highest per-certificate failure rates." Each section of this paper should end with an implication sentence, not a summary sentence.

**The analogy structure.** Paper 1 uses one extended analogy per discussion subsection (US federal electoral system for governance concentration, aviation safety reporting for CT linting, Heartbleed/OpenSSF for structural remedies). Each analogy runs for three paragraphs: establish the parallel, show where it holds, show where the WebPKI-specific gap exceeds the analogy. This paper's discussion should use one extended analogy per subsection, following the same three-paragraph structure. Suggested analogies: financial audit (SOX/Enron) for the incentive structure finding; medical diagnostic testing for the detection rate framing (sensitivity and specificity); pharmaceutical clinical trials for the scope-selection finding.

**The contributions list.** Paper 1 uses `\begin{itemize}[noitemsep,topsep=2pt]` with each bullet beginning with a measurement verb (Measurement of, Quantification of, Analysis of). This paper's contributions list must follow the same format, with the same verb convention.

**Cross-references within the paper.** Paper 1 uses section labels (`Section~\ref{sec:coverage}`) and figure labels (`Figure~\ref{fig:quarterly}`) throughout the body. This paper should cross-reference findings in the same way, creating the same internal coherence.

**The LaTeX preamble.** Copy the sister paper's preamble exactly, including all packages, geometry settings, `\pgfplotsset{compat=1.18}`, the DRAFT watermark, and the `\setlength{\parskip}{0pt}` and `\setlength{\columnsep}{0.25in}` settings.


---

### Theoretical frame — establish before any findings

The introduction must open with the Hemingway quotation from "The Sun Also Rises": "How did you go bankrupt? Two ways. Gradually, then suddenly." This is the paper's organizing metaphor and must be established in the first paragraph. The paper's argument is that this pattern — gradual non-conformance accumulating invisibly behind clean audit opinions, then sudden trust revocation — is not an accident of individual CA behavior but a structural property of how the Web PKI's formal assurance system is designed.

The second and third paragraphs must establish two prior theoretical arguments from prior work by the same author, which this paper tests empirically:

**From "The Limitations of Audits" (2023):** Annual audits are point-in-time retrospectives. The auditee chooses scope. Sample selection is controlled by the subject. The auditor works for the organization. The auditors are often accountants, not technologists. These five structural properties were stated as theoretical concerns in 2023. This paper asks whether they are measurable in the WebPKI data.

**From "Gradually, Then Suddenly: Compliance as a Vital Sign" (2025):** Compliance is a vital sign of organizational health, not proof of security. Healthy compliance is a floor; hollow compliance is a facade. Every distrusted CA had passing audit reports. Auditors issued clean opinions while violations accumulated. The pattern repeats everywhere — financial services, healthcare, utilities — because the incentive structure is the same. This paper tests whether the WebPKI audit record shows the same pattern.

The fourth paragraph states the paper's contribution: the first empirical measurement of whether the Web PKI's formal audit system detects the compliance incidents it is responsible for covering. The WebPKI Observatory provides the instrument: 82 parsed current audit letters matched against 390 Bugzilla compliance incidents that fell within active audit periods.

---

### Five structural findings — derive all numbers from the snapshot

These map directly to the five theoretical concerns from the 2023 blog post. Each section should open by restating the theoretical prediction before presenting the measurement.

**Finding 1: Auditors do not reliably detect in-scope incidents (auditor incentive misalignment).**

Use `auditIntelligence.inPeriodDetection`. The in-period detection rate is the fraction of compliance incidents that were both open during an active audit period and mentioned in the covering letter. Report the three headline numbers: covered, caught, and the detection percentage. Report multi-cycle misses separately — these are incidents that passed through two or more consecutive annual audit cycles without appearing in any letter.

Present the per-auditor detection table from `auditIntelligence.perAuditorDetection`. Sort best to worst. Identify the firms at 0% detection by name — there are seven of them with at least 3 in-scope incidents. Identify the firms with high detection rates. The spread — from 100% to 0% across firms operating in the same ecosystem under the same policy requirements — is the central empirical finding of this section.

**Critical methodological note:** State the denominator limitation prominently. The denominator counts only bugs filed during the audit period. CCADB Policy §5 requires audit letters to cover all incidents that "at any time during the audit period, occurred, were open in Bugzilla, or were reported to a Root Store Operator." This includes bugs filed before the period started that were still open. Bugzilla resolution dates are not available in the dataset, so the true policy-mandated denominator is larger. The reported 30.3% detection rate is therefore an upper bound on actual compliance with the disclosure requirement. State this in the section, in the figure caption, and in the methodology section.

**Finding 2: Audit letters are structurally incomplete (surface verification wins over depth).**

Use `auditIntelligence.alvEquivalentFindings`. The CCADB ALV tool validates audit letter structure — it checks whether the letter lists the SHA-256 fingerprints for the root certificates it covers and whether it covers the certificate types the CA issues. These are the most basic structural checks. Report the three headline numbers: fraction of parsed letters missing root fingerprints, fraction with certificate scope gaps, and fraction with accurate fingerprint coverage.

Present the per-auditor ALV findings from `auditIntelligence.perAuditorAlvFindings`. Name the firms with 100% missing fingerprints across all their clients. This is a systemic template issue, not a per-CA failure — these firms have standardized on letter templates that omit the core traceability field that ALV requires. Connect this to the 2023 post's observation that auditors "are essentially tasked with assessing if the checklist represented in the audit regime can be reasonably deemed as met" — the letters pass the checklist while failing the underlying requirement.

**Finding 3: Clean opinions accumulate during decay (auditors almost never flag exceptions).**

Use `auditIntelligence.summary.qualifiedOpinions` and `auditIntelligence.qualifiedOpinions`. Of 82 parsed audit letters, report how many carry qualified opinions. Name the CAs and their auditors. Then connect this to the transparency gap data from `auditIntelligence.highTransparencyGapCAs`: these are CAs with large all-time incident histories whose current letters cross-reference almost none of that history. The combination — high incident count, clean opinion, high transparency gap — is the audit letter signature of the "gradually then suddenly" pattern.

Use `auditIntelligence.summary.stalenessDistribution` to establish that 35% of CA owners have audit reports more than one year old. Point-in-time retrospectives only function as a vital sign if they are taken annually.

**Finding 4: Auditor selection follows regulatory mandate, not quality signal (auditor works for the organization).**

Use `auditIntelligence.auditorChanges`. The 2025 spike in auditor switches — 21 switches versus a historical baseline of 2–4 per year — coincides with the ETSI EN 319 411 v3.5 recertification requirement. Present the timeline: typical annual switch volume, then the 2025 spike. The most plausible driver is the mandatory recertification: ETSI CAs required to switch to firms with v3.5 accreditation had to change auditors regardless of satisfaction with the current firm. This is auditor selection driven by regulatory mandate, not by the quality signal the switch comparison charts can provide.

Use `auditIntelligence.topAuditors` to show letter quality scores for major firms. The spread in quality scores across firms serving the same population of CAs, combined with the auditor HHI from `auditIntelligence.summary.auditorHHI`, establishes market concentration in audit services.

**Finding 5: Letter completeness and detection are orthogonal (accountants, not technologists).**

Present LSTI as the sharpest example: a firm with the highest average letter quality score among firms with 3+ clients, yet 0% in-period detection. High letter quality — well-structured documents with current criteria, proper templates, correctly stated opinions — and zero incident detection can coexist because letter quality measures document completeness, not substantive review. The letters are technically correct; they are not checking whether the incidents happened.

Use the self-report data from `auditIntelligence.selfReportByFramework`. WebTrust and ETSI CAs self-report at similar rates. Connect this to the 2023 post's observation about sample selection: "it is usually the subject of the audit who chooses the sample." When self-report rates are similar across frameworks and the auditor detection rate is 30%, the data suggests that what auditors are effectively doing is verifying the CA's own account of its compliance status.

---

### The denominator problem — a dedicated subsection

This deserves its own methodology subsection because it changes the interpretation of the headline number. CCADB Policy §5.1 states that audit letters must cover all incidents that "at any time during the audit period, occurred, were open in Bugzilla, or were reported to a Root Store Operator." This is a broader obligation than "incidents filed during the period." The DER-to-PEM encoding failures that affected multiple CAs including Netlock (Bug 2004699, filed December 2025) illustrate the point: similar technical failures persisting across years should appear in consecutive audit letters even if the specific Bugzilla filing is recent.

The Observatory measures only the narrower scope — incidents filed during the period — because Bugzilla resolution dates are not available in the public API. The true policy-mandated denominator is larger, meaning 30.3% is a ceiling on the detection rate, not a point estimate. Future work extending the pipeline to capture bug resolution dates would allow computation of the full policy-mandated denominator.

State this limitation in three places: the methodology section, the detection rate figure caption, and the first paragraph of the detection rate results section.

---

### Connection to the sister paper

The discussion must explicitly connect to "Unmonitored by Design" in two places.

**First connection (Section 4, Discussion):** The sister paper documents that root program oversight capacity — measured by Bugzilla comment engagement — declined between 2020 and 2022 and has not recovered to prior levels. This paper documents that auditor detection of in-scope incidents is 30.3% overall and zero for seven firms. These are not independent findings. The formal assurance system and the external oversight system are the two mechanisms that should catch compliance failures. Both are degraded simultaneously. The ecosystem's practical detection capacity is lower than either number alone suggests.

**Second connection (conclusion):** The sister paper argues that the governance model was designed for a small community and has not scaled to 335 roots and 89 CA owners. This paper adds the audit layer to that argument: the formal assurance mechanism that is supposed to scale governance — the annual third-party audit — is weakly coupled to the incident record it is supposed to reflect. The combination of declining external oversight and low-fidelity formal audits means the compliance signal the browser root programs rely on is generated primarily by CA self-monitoring (46.1% of incident filings in 2025 per the sister paper) rather than by either external oversight or independent audit.

---

### Tone requirements — these are critical and do not vary with the data

The paper measures structural properties of an assurance system operating under known incentive constraints, not individual auditor failure. The people conducting WebTrust and ETSI audits are qualified professionals operating within the boundaries of their engagement scope. The findings reflect structural properties — incentive misalignment, scope selection by auditees, template standardization — not professional incompetence.

Specific requirements:
- Never describe any auditor firm as fraudulent, negligent, or professionally deficient.
- When presenting zero-detection firms, frame the finding as: "the methodology cannot distinguish between incidents that were not discussed and incidents that were discussed without explicit Bugzilla citation." The letter may address the matter without naming it.
- The 30.3% rate is a measurement of a structural property, not a verdict on any firm.
- When discussing LSTI's paradox (high quality score, zero detection), frame it as: "these dimensions measure different properties of the audit artifact." Do not imply LSTI produced fraudulent letters.
- Credit the firms with high detection rates explicitly — MATRIX at 100%, SunRise at 58%, AENOR at 56% — before presenting the firms at zero.
- Credit the ecosystem for the self-report rate: WebTrust and ETSI CAs self-report at similar rates (~69–70%), which is a genuine positive signal about internal compliance culture.

---

### Methodological transparency requirements

**On the "mentioned" criterion:** The pipeline checks whether an audit letter explicitly discusses or cross-references an incident that was open during the covered period. This is a conservative criterion — a letter that addresses the root cause of an incident without citing the specific Bugzilla number will score as "not mentioned." The true detection rate may be higher than 30.3% if auditors addressed incidents through disclosure language that does not match the pipeline's pattern. State this caveat at first use and in the figure caption.

**On corpus scope:** The 82 parsed letters are current audit letters only — the most recently filed letter for each CA. Historical letters are used only for the retrospective analysis. The 390 in-scope incidents span a range of periods; not all CAs have equivalent retrospective depth.

**On auditor attribution:** In-period detection rates are attributed by audit period, not by current primary auditor. When a CA switched auditors, the incidents from the prior auditor's period are attributed to that prior auditor.

**On the ALV comparison:** The Observatory computes ALV-equivalent checks independently from the CCADB ALV tool. Results may differ because CCADB ALV runs against the letter at submission time; the Observatory checks against the current CCADB root inventory. Roots added after letter submission will show as missing in the Observatory's check but would have passed ALV at submission time.

---

### Relationship to prior work

The related work section should cover:
- Prior CA/B Forum and browser security community audit analysis, if any exists in the literature
- WebTrust and ETSI audit framework publications
- The CCADB ALV tool and its published requirements
- Analogous audit effectiveness studies in other regulated industries (financial services, healthcare) — but briefly, as context for the structural pattern, not as the paper's contribution

Do not re-survey the CT and PKI measurement literature covered in the sister paper. A forward pointer to the sister paper is sufficient for that context.

---

### Citations required (10)

All must appear in the body.

| Key | Source | Placement |
|-----|---------|-----------|
| sister | "Unmonitored by Design," Systematic Reasoning, 2026 | intro, discussion (both connection points) |
| snapshot | Observatory LLM Snapshot, March 2026 | methods |
| github | Observatory Source Repository | methods |
| hurst2023 | "The Limitations of Audits," unmitigatedrisk.com, Feb 2023 | intro (theoretical frame) |
| hurst2025 | "Gradually, Then Suddenly: Compliance as a Vital Sign," unmitigatedrisk.com, Oct 2025 | intro (theoretical frame) |
| ccadb-policy | CCADB Policy §5, Mozilla, current | denominator problem section |
| ccadb-alv | CCADB Audit Letter Validation documentation | ALV findings section |
| webtrust | WebTrust for CAs Principles and Criteria, current version | background |
| etsi-en | ETSI EN 319 411-1/2, current version | background |
| amann2017 | Amann et al., IMC 2017 — Mission Accomplished | enforcement discussion (sister paper precedent) |

---

### Things never to write

- Never assert any auditor firm produced fraudulent or professionally deficient letters.
- Never hardcode numbers from the sister paper PDF — all quantitative claims derive from the current snapshot.
- Never describe the 30.3% detection rate as "only 30%" — state it as 30.3% and let the comparison to prior expectations do the work.
- Never imply that zero-detection auditors were not reviewing anything — the pipeline cannot observe what was discussed without explicit citation.
- Never conflate letter quality score with audit thoroughness — the paper's central argument depends on keeping these distinct.
- Never describe the ETSI/WebTrust self-report parity as evidence that frameworks are equivalent — it is evidence that self-report rates are similar, not that detection rates are.
- Never reference prior drafts, prior versions, or corrected measurements.
- Never use "gradually then suddenly" as a section label — it is the paper's metaphor, not its structure.

---

### Figures required (4)

All figures use TikZ/pgfplots matching the sister paper's visual style. All coordinate values must be extracted from the current snapshot.

| Figure | Type | Data source field |
|--------|------|-------------------|
| 1 | Horizontal bar chart: per-auditor detection rate, sorted best to worst, firms with 3+ in-scope incidents only | `auditIntelligence.perAuditorDetection` |
| 2 | Bubble or scatter: letter quality score (x) vs. transparency gap score (y), bubble size = incident count, colored by framework | `auditIntelligence.topAuditors` + `auditIntelligence.highTransparencyGapCAs` |
| 3 | Horizontal stacked bar: per-auditor ALV findings (missing fingerprints, scope gaps, pass), firms with 2+ clients | `auditIntelligence.perAuditorAlvFindings` |
| 4 | Time series: annual auditor switch count with 2025 spike and historical baseline band | `auditIntelligence.auditorChanges` |

---

### Closing coda — mirror the sister paper's MTC paragraph

The conclusion must close with a paragraph connecting these audit findings to the Merkle Tree Certificates transition, mirroring the sister paper's closing MTC paragraph. The connections to make:

- During the 15–20 year X.509/MTC dual issuance period, each CA will be subject to both X.509 audit obligations and MTC issuance log audit obligations — a doubled compliance surface, arriving while auditor detection of X.509 obligations is at 30.3%.
- The audit letters that will certify MTC issuance log operations will be produced by the same firms, under the same incentive structures, that produced these results for X.509.
- CCADB Policy's disclosure requirement for MTC incidents will have the same denominator problem: incidents that were open during the audit period but filed before it began may not be captured by the audit pipeline.
- Close with: the audit system's structural properties do not change because the underlying certificate format does. The X.509 findings this paper documents are the baseline conditions under which MTC audit oversight will begin.

Do not summarize MTC architecture. The coda's job is to use the MTC transition as a proof of stakes for these findings.

---

### Output

Complete compilable LaTeX, 10–14 pages in two-column letterpaper format, with DRAFT watermark and "Working Draft v0 — Not for citation or distribution" subtitle, that compiles clean on first attempt. Match the sister paper's LaTeX preamble exactly. Do not truncate findings or compress arguments to hit a page target — this is a working draft.
