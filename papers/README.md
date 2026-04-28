# Papers

Three papers derived from the WebPKI Observatory. They share a measurement corpus, citation style, LaTeX format, and analytical frame. Each stands independently but the three form a coherent argument about where and why the Web PKI's accountability system fails.

---

## Paper 1: Unmonitored by Design

**"Unmonitored by Design: A Longitudinal Measurement Study of Governance Failure in the Web PKI"**

Working Draft — Not for citation or distribution

### Thesis
The Web PKI's governance model was designed for fewer than twenty CAs and now governs 335 roots across 89 owners. Root program Bugzilla coverage has declined below 20% for both Chrome and Mozilla through key-person dependency without institutional redundancy. CA self-monitoring has surged to 46.1% of incident filings in 2025. The Microsoft Root Store operates as a structurally separate governance environment with zero cross-program oversight comments across 12 years and 142 exclusive roots. Per-certificate failure rates follow a power law: PPM ∝ share⁻⁰·⁸⁷ (r=−0.94), placing tail CA failure densities 1,130× the head while both hold identical trust.

### Files

| File | Purpose |
|------|---------|
| `unmonitored-by-design/unmonitored-by-design-v1.tex` | LaTeX source |
| `unmonitored-by-design/unmonitored-by-design-v1.pdf` | Compiled PDF |
| `unmonitored-by-design/unmonitored-by-design-generation-prompt-v1.md` | Generation prompt |

---

## Paper 2: Gradually, Then Suddenly

**"Gradually, Then Suddenly: Measuring Audit Failure in the Web PKI"**

Working Draft — Not for citation or distribution

### Thesis
The Web PKI's formal audit system detects 29.2% of compliance incidents open during the periods auditors are responsible for covering — an upper bound, since the policy-mandated denominator is larger than the instrument measures. Four auditor firms detected zero incidents despite having three or more in-scope cases. 12.3% of audit letters fail to cover all certificate types the CA is trusted to issue. During the pre-distrust periods of the two graduated-pathway CAs with overlapping CCADB and Bugzilla records, the in-period detection rate was 7.5% (3 of 40 incidents).

### Files

| File | Purpose |
|------|---------|
| `gradually-then-suddenly/gradually-then-suddenly-v1.tex` | LaTeX source |
| `gradually-then-suddenly/gradually-then-suddenly-v1.pdf` | Compiled PDF |
| `gradually-then-suddenly/gradually-then-suddenly-generation-prompt-v1.md` | Generation prompt |

---

## Paper 3: Before the Runway Expires

**"Before the Runway Expires: A Compliance Posture Framework for Early Engagement in the Web PKI"**

Working Draft — Not for citation or distribution

### Thesis
The median time from first Bugzilla compliance signal to CA distrust across graduated-pathway removals is 1,185 days. This paper proposes the Compliance Posture Framework (CPF), combining the Accountability Loop Score (ALS — structural non-remediation through chronic incident class recurrence) and the Incident Response Quality (IRQ) score (behavioral posture from LLM-assisted classification of 1,546 Bugzilla thread arcs) into an Engagement Priority Score (EPS). Temporal validation shows Entrust would have flagged in 2019 — five years before distrust proceedings — when only 6 of 35 active CAs (17%) carried the same signal. Escalating-arc threads are 5.4× more prevalent in distrusted CA records (χ²=16.2, p<10⁻⁴, OR=5.6). The framework is an engagement prioritization tool, not a distrust predictor.

### Files

| File | Purpose |
|------|---------|
| `before-the-runway-expires/before-the-runway-expires-v1.tex` | LaTeX source (current draft) |
| `before-the-runway-expires/before-the-runway-expires-generation-prompt-v1.md` | Generation prompt with full data specification |

No PDF committed — paper has not been released. Compile with pdflatex when needed.

---

## Relationship between the papers

**Paper 1** measures the external governance layer: root programs, Bugzilla oversight, discovery channels. Both Chrome and Mozilla are below 20% Bugzilla coverage; CA self-monitoring has grown to 46.1% of filings.

**Paper 2** measures the formal assurance layer: auditors certifying CA compliance annually. 29.2% in-period detection rate, structural not incidental.

**Paper 3** measures the remediation layer: whether detected problems get fixed, and where the accountability loop is open. The three failures compound — auditors detect 29.2%, root programs cover 20%, CA self-monitoring carries the rest but cannot substitute for loop closure. Paper 3 gives root programs an operational framework to prioritize engagement without waiting for 1,185 days of accumulation to force action.

---

## Producing a new version

1. Pull latest data: `python3 pipeline/compute_als.py && python3 pipeline/compute_comparable_cases.py`
2. For Paper 3 IRQ rescore: `ANTHROPIC_API_KEY=... python3 pipeline/score_incident_response.py`
3. Use the generation prompt with updated pipeline outputs
4. Verify all quantitative claims against new pipeline outputs — numbers change with each run
5. Compile with `pdflatex` (requires `pgfplots`, `tikz`, `booktabs`, `draftwatermark`)
6. Commit new `.tex` and `.pdf` (Papers 1 and 2 only) with version bump
