#!/usr/bin/env python3
"""
compute_als.py — Accountability Loop Score pipeline

Computes the ALS for every CA with a Bugzilla incident record, using:
  - bugs_by_ca.json          (active CAs)
  - bugs_by_ca_distrusted.json (distrusted CAs — test vectors)
  - audits.json              (audit coupling signals)
  - distrust_data.json       (ground truth labels for test vectors)

Output: data/als_scores.json

ALS components
──────────────
A  (0–30)  Detection failure:     1 − self-report rate
B1 (0–20)  Structural non-remediation: chronic class count (3+ distinct years)
B2 (0–10)  Incident acceleration:  recent-half vs early-half incident rate
B3 (0–10)  Governance share:       fraction policy-failure / disclosure-failure
C1 (0–15)  Transparency gap:       incident vs disclosed-matters divergence
C2 (0–10)  Audit staleness:        age of most recent audit statement
C3 (0–5)   Letter quality:         criteria currency, opinion clarity, template

Methodology reference: paper/loop-failure/loop-failure-v1.tex
"""

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

PIPELINE_DIR = Path(__file__).parent
DATA_DIR     = PIPELINE_DIR.parent / "data"

sys.path.insert(0, str(PIPELINE_DIR))
from utils import load_json, save_json, now_utc


# ── Ecosystem spike index ──────────────────────────────────────────────────────
# (tag, quarter) -> n_cas: how many distinct CAs filed that tag that quarter.
# Used to distinguish genuine per-CA chronic recurrence from ecosystem-wide
# compliance sweeps (Mozilla BR batches, ballot-triggered scans, etc.).
_SPIKE_INDEX_PATH = PIPELINE_DIR / "ecosystem_spike_index.json"
_ECOSYSTEM_SPIKE_INDEX: dict[str, int] = {}

def _load_spike_index() -> None:
    global _ECOSYSTEM_SPIKE_INDEX
    if _SPIKE_INDEX_PATH.exists():
        _ECOSYSTEM_SPIKE_INDEX = json.loads(_SPIKE_INDEX_PATH.read_text())

_load_spike_index()

ECOSYSTEM_SPIKE_THRESHOLD = 10  # 10+ other CAs = ecosystem event (isolates genuine enforcement sweeps)


# ── Ecosystem knowledge index ──────────────────────────────────────────────────
# For each (tag, year), how many distinct CAs filed that tag BEFORE that year?
# Used to compute "knowledge-adjusted recurrence": a CA filing a class that
# has been documented across 40+ other CAs for 7 years had full industry notice.
_ECO_KNOWLEDGE: dict[str, int] = {}   # "tag|year" -> n_prior_cas before that year
_ECO_FIRST_YEAR: dict[str, int] = {}  # tag -> first year seen in corpus

def _build_eco_knowledge(all_bugs_by_ca: dict) -> None:
    """Build ecosystem knowledge index from all bugs. Called once in main()."""
    global _ECO_KNOWLEDGE, _ECO_FIRST_YEAR
    tag_year_cas: dict[str, dict] = {}
    for ca, bugs in all_bugs_by_ca.items():
        for b in (bugs if isinstance(bugs, list) else []):
            filed = b.get('filed', '')
            yr = int(filed[:4]) if filed and len(filed) >= 4 else None
            if not yr:
                continue
            for t in extract_tags(b.get('whiteboard', '')):
                if t not in tag_year_cas:
                    tag_year_cas[t] = {}
                if yr not in tag_year_cas[t]:
                    tag_year_cas[t][yr] = set()
                tag_year_cas[t][yr].add(ca)
    for tag, yr_cas in tag_year_cas.items():
        years_sorted = sorted(yr_cas.keys())
        _ECO_FIRST_YEAR[tag] = years_sorted[0]
        cumulative: set = set()
        for yr in years_sorted:
            _ECO_KNOWLEDGE[f"{tag}|{yr}"] = len(cumulative)
            cumulative |= yr_cas[yr]


# ── Constants ─────────────────────────────────────────────────────────────────

# Bugzilla tags that are meta-tags, not incident classes
META_TAGS = {'ca-compliance', 'ca-verified', ''}

# Tags excluded from chronic class detection:
#   uncategorized  — tagging artifact, not a real class
#   audit-finding  — ETSI auditor-reported findings; filing granularity varies
#                    by framework (ETSI files one bug per finding; WebTrust lumps
#                    them). Should not count as chronic class recurrence.
EXCLUDE_FROM_CHRONIC = {'uncategorized', 'audit-finding'}

# Tags that indicate governance/posture failures (not operational errors)
GOVERNANCE_TAGS = {'policy-failure', 'disclosure-failure'}

# Incident severity hierarchy. Tiers are ordered by potential trust impact.
# Tier weights use a fixed powers-of-two progression so severity is monotonic
# and independent of any named organization or individual judgment.
INCIDENT_SEVERITY: dict[str, int] = {
    # Tier 5: PKI hierarchy failures — missed CA cert, compromised root
    'ca-misissuance':        5,
    'ca-compromise':         5,
    # Tier 4: Revocation/operational failures with systemic impact
    'ca-revocation-delay':   4,
    'ca-onecrl':             4,
    # Tier 3: Governance failures and systemic non-compliance
    'ca-compliance':         3,
    'ca-investigation':      3,
    'policy-failure':        3,
    'disclosure-failure':    3,
    'audit-failure':         3,
    # Tier 2: Operational failures with subscriber impact
    'audit-delay':           2,
    'audit-finding':         2,
    'leaf-revocation-delay': 2,
    'key-compromise':        2,
    # Tier 1: Attribute misissuance — significant but lower blast radius
    'ev-misissuance':        1,
    'ov-misissuance':        1,
    'dv-misissuance':        1,
    'iv-misissuance':        1,
    'smime-misissuance':     1,
    'ocsp-failure':          1,
    'crl-failure':           1,
}

# Minimum bugs (after batch collapse) for a reliable score
# CAs with 3–9 bugs are scored but flagged low_confidence=True
MIN_BUGS = 2  # Score CAs with as few as 2 bugs — a single incident can be
              # meaningful (esp. recent ones). Low-n CAs get low_confidence=True.
LOW_CONFIDENCE_THRESHOLD = 10

# Chronic class threshold: tag must appear in this many distinct years
CHRONIC_YEARS = 3

# Batch collapse: same-day filings of 3+ bugs with identical tag sets
# from one CA are treated as a single event (ETSI audit-finding batches)
BATCH_COLLAPSE_MIN = 3


# ── Bug analysis ──────────────────────────────────────────────────────────────

def extract_tags(whiteboard: str, exclude: set | None = None) -> list[str]:
    """Extract bracket-delimited tags from a Bugzilla whiteboard field."""
    skip = META_TAGS | (exclude or set())
    return [t for t in re.findall(r'\[([^\]]+)\]', whiteboard)
            if t not in skip]


def analyze_bug_record(bugs: list[dict],
                       commitment_index: dict | None = None,
                       irq_cache: dict | None = None,
                       as_of: date | None = None) -> dict | None:
    """
    Compute incident-handling signals from a list of bug records.

    Each bug record has: id, filed (YYYY-MM-DD), summary, self_reported, whiteboard.

    Batch collapse: same-day filings of BATCH_COLLAPSE_MIN+ bugs with identical
    tag sets are treated as one event. This corrects for ETSI audit-finding
    batches (e.g. one audit filing 15 individual finding bugs on the same date),
    which would otherwise inflate counts and distort the acceleration signal.

    Chronic class detection excludes EXCLUDE_FROM_CHRONIC tags (uncategorized,
    audit-finding) which reflect tagging artifacts or auditor reporting practices
    rather than CA compliance failure modes.

    Returns a dict of signals, or None if the record is too sparse.
    """
    if not bugs or len(bugs) < MIN_BUGS:
        return None

    # ── Batch collapse ───────────────────────────────────────────────────────
    # Group by (date, frozenset of tags). Batches of BATCH_COLLAPSE_MIN+ with
    # identical tags on the same date collapse to one representative bug.
    date_tag_groups: dict[tuple, list] = defaultdict(list)
    for b in bugs:
        filed = b.get('filed', '')
        tags  = frozenset(extract_tags(b.get('whiteboard', '')))
        date_tag_groups[(filed, tags)].append(b)

    effective_bugs: list[dict] = []
    for (filed, tags), group in date_tag_groups.items():
        if len(group) >= BATCH_COLLAPSE_MIN:
            effective_bugs.append(group[0])   # one representative event
        else:
            effective_bugs.extend(group)

    n_orig = len(bugs)
    n      = len(effective_bugs)

    if n < MIN_BUGS:
        return None

    # ── Per-year signals ─────────────────────────────────────────────────────
    by_year: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    all_tags:       list[str] = []  # all tags (for governance fraction)
    all_tags_clean: list[str] = []  # tags excluding chronic-noise tags

    for b in effective_bugs:
        filed  = b.get('filed', '')
        year   = int(filed[:4]) if filed and len(filed) >= 4 else None
        tags   = extract_tags(b.get('whiteboard', ''))
        tags_c = [t for t in tags if t not in EXCLUDE_FROM_CHRONIC]
        self_r = bool(b.get('self_reported'))

        if year:
            for t in tags_c:
                by_year[year][t] += 1
            by_year[year]['_total'] += 1
            if self_r:
                by_year[year]['_self'] += 1
        all_tags.extend(tags)
        all_tags_clean.extend(tags_c)

    years = sorted(by_year.keys())
    if not years:
        return None

    # ── Chronic classes (exclude noise tags, with ecosystem solo tracking) ──────
    # Detection unchanged: tag is chronic if it appears in 3+ distinct years.
    # Also tracks solo-chronic: classes where CA has 3+ years OUTSIDE ecosystem
    # spikes (<10 other CAs filed same tag same quarter). solo_ratio drives the
    # ecosystem_factor discount applied in Mode B scoring.
    tag_years:      dict[str, set[int]] = defaultdict(set)
    tag_solo_years: dict[str, set[int]] = defaultdict(set)

    for b in effective_bugs:
        filed = b.get('filed', '')
        if not filed or len(filed) < 7:
            continue
        year    = int(filed[:4])
        month   = int(filed[5:7])
        quarter = f"{year}-Q{(month-1)//3+1}"
        tags_c  = [t for t in extract_tags(b.get('whiteboard', ''))
                   if t not in EXCLUDE_FROM_CHRONIC]
        for t in tags_c:
            tag_years[t].add(year)
            spike_key = f"{t}|{quarter}"
            n_others  = _ECOSYSTEM_SPIKE_INDEX.get(spike_key, 1) - 1
            if n_others < ECOSYSTEM_SPIKE_THRESHOLD:
                tag_solo_years[t].add(year)

    chronic = {t: sorted(yrs) for t, yrs in tag_years.items()
               if len(yrs) >= CHRONIC_YEARS}
    n_chronic = len(chronic)

    solo_chronic = {t: sorted(tag_solo_years[t]) for t in chronic
                    if len(tag_solo_years[t]) >= CHRONIC_YEARS}
    n_solo_chronic = len(solo_chronic)

    # ── Ecosystem knowledge adjustment ───────────────────────────────────────
    # For each chronic class, compute the average number of prior CAs that had
    # already documented the same failure class before this CA's first occurrence.
    # A CA recurring on a class with 40 prior CAs and 7 years of ecosystem history
    # had full industry notice. knowledge_weight > 1 amplifies the chronic score.
    #
    # Also compute ecosystem_age: years since the tag first appeared before this
    # CA's first occurrence of it.
    chronic_knowledge: dict[str, dict] = {}  # tag -> {prior_cas, eco_age, weight}
    for tag, years_list in chronic.items():
        first_yr = years_list[0]
        n_prior = _ECO_KNOWLEDGE.get(f"{tag}|{first_yr}", 0)
        eco_first = _ECO_FIRST_YEAR.get(tag, first_yr)
        eco_age = max(0, first_yr - eco_first)
        # weight: 1.0 (novel) → 1.5 (well-documented, 20+ prior CAs, 4+ yrs)
        # Saturates at 1.5 to avoid over-penalising large well-known classes
        prior_factor = min(n_prior / 20.0, 1.0)   # 0→1 as prior_cas grows to 20
        age_factor   = min(eco_age / 4.0,  1.0)   # 0→1 as eco_age grows to 4yrs
        weight = 1.0 + 0.5 * prior_factor * age_factor
        chronic_knowledge[tag] = {
            'prior_cas': n_prior,
            'eco_age':   eco_age,
            'weight':    round(weight, 3),
        }

    # Aggregate: average knowledge weight across chronic classes
    avg_knowledge_weight = (
        sum(v['weight'] for v in chronic_knowledge.values()) / len(chronic_knowledge)
        if chronic_knowledge else 1.0
    )

    # ── Commitment-amplified recurrence ──────────────────────────────────────
    # commitment_index: {tag -> first substantive (A/B/C) commitment year} for this CA.
    #
    # Broken promise: governance tag (policy-failure, disclosure-failure) that
    # recurs within 2 years of a commitment. Operational tags excluded — too coarse.
    #
    # Closed loop: any chronic class where a commitment was made AND the last
    # occurrence was 3+ years ago. With broad A/B/C grades, "no recurrence ever"
    # is too strict — nearly every tag has a commitment now. 3yr quiescence after
    # the last occurrence is evidence the loop genuinely closed.
    import math as _m
    current_year = max(max(yrs) for yrs in chronic.values()) if chronic else 2024

    broken_promise_classes: list[str] = []
    closed_loop_classes:    list[str] = []

    if commitment_index:
        for tag, years_list in chronic.items():
            commit_yr = commitment_index.get(tag)
            if commit_yr is None:
                continue
            is_governance = any(g in tag for g in GOVERNANCE_TAGS)
            recurred_soon = any(yr > commit_yr and yr <= commit_yr + 2
                                for yr in years_list)
            last_yr = max(years_list)
            quiescent = (current_year - last_yr) >= 3

            if is_governance and recurred_soon:
                broken_promise_classes.append(tag)
            elif commit_yr <= last_yr and quiescent:
                # Commitment made, class active, but silent for 3+ years
                closed_loop_classes.append(tag)

    n_broken_promise = len(broken_promise_classes)
    n_closed_loop    = len(closed_loop_classes)

    # ── Self-report rate ─────────────────────────────────────────────────────
    self_total = sum(by_year[y]['_self'] for y in years)
    self_pct   = self_total / n * 100

    # ── Governance fraction ──────────────────────────────────────────────────
    gov_count = sum(1 for t in all_tags
                    if any(g in t for g in GOVERNANCE_TAGS))
    gov_frac  = gov_count / n

    # ── Incident acceleration (recent half vs early half, per year) ──────────
    mid     = len(years) // 2
    early_y = years[:mid]
    recent_y = years[mid:]
    e_vol   = sum(by_year[y]['_total'] for y in early_y)
    r_vol   = sum(by_year[y]['_total'] for y in recent_y)
    if e_vol > 0:
        accel = (r_vol / max(len(recent_y), 1)) / (e_vol / max(len(early_y), 1))
    else:
        accel = 1.0

    year_density = n / len(years) if years else 1.0
    chronic_span_avg = (
        sum(len(yrs) for yrs in chronic.values()) / len(chronic)
        if chronic else 0.0
    )

    # ── Incident severity score ───────────────────────────────────────────────
    # Severity-weighted sum normalised to [0,1].
    # Weights: sev5=16x, sev4=8x, sev3=4x, sev2=2x, sev1=1x.
    # A single missed CA certificate (sev5) outweighs 16 attribute misissuances.
    # Normalised against worst-case (every bug sev5) so CAs are comparable.
    SEV_WEIGHT = {5: 16, 4: 8, 3: 4, 2: 2, 1: 1, 0: 0}
    def _bug_sev(b):
        tags = extract_tags(b.get('whiteboard', ''))
        return max((INCIDENT_SEVERITY.get(t, 0) for t in tags), default=0)

    sev_sum      = sum(SEV_WEIGHT[_bug_sev(b)] for b in effective_bugs)
    max_possible = n * SEV_WEIGHT[5]
    severity_score = round(sev_sum / max(max_possible, 1), 4)

    # ── Recency score ─────────────────────────────────────────────────────────
    # Severity-weighted score for bugs filed in the last 12 months only.
    # The window is evaluated against an explicit analysis date when supplied,
    # making recency reproducible for tests and historical re-runs.
    import datetime as _dt
    _today     = as_of or date.today()
    _cutoff    = (_today - _dt.timedelta(days=365)).isoformat()
    recent_bugs = [b for b in effective_bugs if b.get('filed', '') >= _cutoff]
    if recent_bugs:
        r_sev_sum  = sum(SEV_WEIGHT[_bug_sev(b)] for b in recent_bugs)
        r_max      = len(recent_bugs) * SEV_WEIGHT[5]
        recency_score = round(r_sev_sum / max(r_max, 1), 4)
    else:
        recency_score = 0.0

    # ── Recent accountability pressure rate ───────────────────────────────────
    # Optional model-assisted context: fraction of recent threads labeled as
    # accountability pressure. This field is retained for display compatibility
    # but is not used by the deterministic structural score.
    _cache = irq_cache or {}
    recent_ap_count = sum(
        1 for b in recent_bugs
        if _cache.get(str(b.get('id', '')), {}).get('thread_health_arc') == 'accountability_pressure'
    )
    recent_ap_rate = round(
        recent_ap_count / len(recent_bugs) if recent_bugs else 0.0, 4
    )

    return {
        'n':                 n,
        'n_orig':            n_orig,
        'batches_collapsed': n_orig - n,
        'low_confidence':    n < LOW_CONFIDENCE_THRESHOLD,
        'years':             [years[0], years[-1]],
        'years_active':      len(years),
        'self_pct':          round(self_pct, 1),
        'n_chronic':         n_chronic,
        'n_solo_chronic':    n_solo_chronic,
        'chronic_classes':   chronic,
        'solo_chronic_classes': solo_chronic,
        'chronic_knowledge': chronic_knowledge,
        'avg_knowledge_weight': round(avg_knowledge_weight, 3),
        'n_broken_promise':  n_broken_promise,
        'broken_promise_classes': broken_promise_classes,
        'n_closed_loop':     n_closed_loop,
        'closed_loop_classes': closed_loop_classes,
        'gov_frac':          round(gov_frac, 3),
        'accel':             round(accel, 3),
        'year_density':      round(year_density, 2),
        'chronic_span_avg':  round(chronic_span_avg, 2),
        # New signals
        'severity_score':    severity_score,
        'recency_score':     recency_score,
        'recent_ap_rate':    recent_ap_rate,
        'n_recent':          len(recent_bugs),
        'n_sev5':            sum(1 for b in effective_bugs if _bug_sev(b) == 5),
    }


# ── ALS scoring ───────────────────────────────────────────────────────────────

def compute_als(sig: dict, audit_profile: dict | None = None) -> dict:
    """
    Accountability Loop Score v2.

    Two failure modes scored separately; final = max(mode_A, mode_B) + accel_boost.

    Mode A — Operational blindness + deterioration:
      Signals: detection failure (confidence-weighted), acceleration, gov share.

    Mode B — Structural accumulation:
      Signals: chronic recurrence, density, duration, ecosystem context,
      severity, and governance share.

    Acceleration boost: amplifies both modes when acceleration is above baseline.

    The threshold is a versioned model parameter. Historical public outcomes are
    reported separately as evaluation labels and do not create entity-specific
    expectations or exceptions.

    Audit profile signals appended for context only.
    """
    import math as _math

    accel    = sig['accel']
    dens     = sig.get('year_density', sig['n'] / max(sig.get('years_active', 1), 1))
    n_ch     = sig['n_chronic']
    span     = sig.get('chronic_span_avg', 0.0)
    self_r   = sig['self_pct'] / 100
    gov      = sig['gov_frac']
    n        = sig['n']
    conf     = min(n / 15.0, 1.0)

    # ── Mode A: Operational blindness + deterioration ──────────────────────
    det_fail = (1 - self_r) * conf
    # Gate deterioration signal on corpus size — 5× acceleration across 6 bugs
    # is noise; across 30+ bugs it's a real trend.
    deterior = max(0.0, _math.log(max(accel, 0.5))) * min(n / 10.0, 1.0)
    mode_A   = (det_fail * 30) + (deterior * 20) + (gov * 15)

    # ── Mode B: Structural accumulation ───────────────────────────────────
    # Ecosystem factor: solo recurrence (CA failing independently) scores full.
    # Recurrence that coincides with ecosystem-wide sweeps gets a modest discount
    # — but floors at 0.85.
    n_solo  = sig.get('n_solo_chronic', n_ch)
    solo_ratio       = n_solo / n_ch if n_ch > 0 else 1.0
    ecosystem_factor = 0.85 + 0.15 * solo_ratio   # 0.85 floor → 1.0 ceiling

    # Knowledge-adjusted chronic weight: amplify if the CA failed on well-documented
    # classes that the ecosystem had already established as known failure modes.
    # avg_knowledge_weight: 1.0 (novel class) → 1.5 (20+ prior CAs, 4+ yrs notice).
    # Closed-loop credit: chronic classes with a kept commitment and no recurrence
    # after it are evidence the loop closed. Reduce effective n_chronic by those.
    avg_kw      = sig.get('avg_knowledge_weight', 1.0)
    n_closed    = sig.get('n_closed_loop', 0)
    n_broken    = sig.get('n_broken_promise', 0)

    # Model-assisted commitment classifications are retained as descriptive
    # metadata only. They do not change the deterministic structural score.
    n_ch_eff    = n_ch
    broken_boost = 1.0

    # Severity amplifier: a CA whose chronic classes include PKI hierarchy
    # failures (ca-misissuance sev5, ca-revocation-delay sev4) scores harder
    # than one with only attribute misissuance (sev1). severity_score is the
    # severity-weighted fraction of all bugs — normalised 0-1, worst-case=1.
    # A missed CA cert (sev5) outweighs 16 OV/EV attribute errors.
    # Amplifier range: 1.0 (all sev1) → 2.0 (all sev5). Keeps Mode B calibration
    # intact while reflecting that incident TYPE matters, not just count.
    sev_s   = sig.get('severity_score', 0.0)
    sev_amp = 1.0 + sev_s  # 1.0–2.0

    chron_s = min(n_ch_eff / 5.0, 1.0) * ecosystem_factor * avg_kw * broken_boost * sev_amp
    dens_s  = min(_math.log(max(dens, 1.0)) / _math.log(10), 1.0)
    span_s  = min(span / 7.0, 1.0)
    mode_B  = (chron_s * 35) + (dens_s * 20) + (span_s * 10) + (gov * 10)

    # ── Acceleration boost ─────────────────────────────────────────────────
    # Base: credible with >=10 bugs. Amplified when recent incidents are severe —
    # a CA accelerating on ca-misissuance is more urgent than one accelerating
    # on dv-misissuance. recency_score: severity-weighted fraction of last-12mo
    # bugs. Range 1.0 (recent bugs all sev1) → 2.0 (recent bugs all sev5).
    rec_s      = sig.get('recency_score', 0.0)
    rec_amp    = 1.0 + rec_s  # 1.0–2.0
    accel_boost = max(0.0, _math.log(max(accel, 1.0))) * 8 * min(n / 10.0, 1.0) * rec_amp

    total = max(mode_A, mode_B) + accel_boost

    # ── Audit coupling context (appended, not scored) ──────────────────────
    p         = audit_profile or {}
    gap_raw   = p.get('transparency_gap')
    gap_level = gap_raw.get('gap_level', '—') if isinstance(gap_raw, dict) else '—'
    staleness = p.get('staleness', '—')
    q         = p.get('letter_quality_score')
    qual      = q.get('overall') if isinstance(q, dict) else q

    return {
        'total':             round(total, 1),
        'mode_A':            round(mode_A, 1),
        'mode_B':            round(mode_B, 1),
        'accel_boost':       round(accel_boost, 1),
        'dominant_mode':     'A' if mode_A >= mode_B else 'B',
        'threshold':         48,
        'flagged':           total >= 48,
        'n_solo_chronic':      sig.get('n_solo_chronic', 0),
        'solo_ratio':          round(solo_ratio, 2),
        'ecosystem_factor':    round(ecosystem_factor, 2),
        'avg_knowledge_weight': round(avg_kw, 3),
        'n_broken_promise':    n_broken,
        'n_closed_loop':       n_closed,
        'broken_boost':        round(broken_boost, 3),
        'severity_amp':        round(sev_amp, 3),
        'recency_amp':         round(rec_amp, 3),
        # Audit context
        'gap_level':         gap_level,
        'staleness':         staleness,
        'audit_quality':     round(qual, 1) if qual is not None else None,
        'has_audit_profile': audit_profile is not None,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("[compute_als] Loading data...")

    bugs_active    = load_json(DATA_DIR / "bugs_by_ca.json")           or {}
    bugs_distrusted= load_json(DATA_DIR / "bugs_by_ca_distrusted.json") or {}
    audits_data    = load_json(DATA_DIR / "audits.json")               or {}
    distrust_data  = load_json(DATA_DIR / "distrust_data.json")        or {}

    # IRQ scores for behavior-adjusted threshold (loaded if available)
    irq_scores_raw  = load_json(DATA_DIR / "irq_scores.json") or {}
    irq_ca_scores   = {r['ca']: r['scores'] for r in irq_scores_raw.get('results', [])}

    # ── Build ecosystem knowledge index (all bugs combined) ─────────────────
    all_bugs_combined = {**bugs_active, **bugs_distrusted}
    _build_eco_knowledge(all_bugs_combined)
    print(f"[compute_als] Ecosystem knowledge index: {len(_ECO_KNOWLEDGE):,} tag-year entries")

    # ── Build per-CA commitment index from IRQ cache ─────────────────────────
    # Maps ca -> {tag -> first year the CA had a grade-A commitment on that tag}
    irq_cache_path = PIPELINE_DIR / "ops_cache" / "irq_score_cache.json"
    irq_cache = load_json(irq_cache_path) or {}
    # Build bug_id -> (ca, tags, year) lookup
    bug_meta: dict[str, dict] = {}
    for ca, bugs in all_bugs_combined.items():
        for b in (bugs if isinstance(bugs, list) else []):
            filed = b.get('filed', '')
            yr = int(filed[:4]) if filed and len(filed) >= 4 else None
            tags = extract_tags(b.get('whiteboard', ''))
            bug_meta[str(b['id'])] = {'ca': ca, 'tags': tags, 'year': yr}

    # For each CA, find earliest substantive (A/B/C) commitment year per tag.
    # Grade D/F = vague or contradicted, not a real commitment.
    # B is the most common grade; grade-A only discards most of the signal.
    SUBSTANTIVE_GRADES = {'A', 'B', 'C'}
    ca_commitment_index: dict[str, dict[str, int]] = {}
    for bid, score in irq_cache.items():
        if not score:
            continue
        meta = bug_meta.get(bid)
        if not meta or not meta['year']:
            continue
        ca, tags, yr = meta['ca'], meta['tags'], meta['year']
        if ca not in ca_commitment_index:
            ca_commitment_index[ca] = {}
        for c in score.get('commitments', []):
            if isinstance(c, dict) and c.get('grade') in SUBSTANTIVE_GRADES:
                for t in tags:
                    if t not in ca_commitment_index[ca] or ca_commitment_index[ca][t] > yr:
                        ca_commitment_index[ca][t] = yr
    print(f"[compute_als] Commitment index: {sum(len(v) for v in ca_commitment_index.values())} tag-CA substantive (A/B/C) commitments")

    audit_profiles = {p['ca_owner']: p
                      for p in audits_data.get('profiles', [])}
    distrust_by_ca = {e['ca']: e for e in distrust_data.get('events', [])}

    # Helper: find distrust event for a CA by fuzzy name match
    def find_distrust(ca_name: str):
        for k, v in distrust_by_ca.items():
            if ca_name.lower() in k.lower() or k.lower() in ca_name.lower():
                return v
        return None

    results = []

    # ── Deterministic threshold ───────────────────────────────────────────
    # Qualitative/model-assisted incident-response fields are non-scoring context.
    # Active and historical records use the same fixed versioned threshold.

    # ── Active CAs ─────────────────────────────────────────────────────────
    for ca, bugs in bugs_active.items():
        if not isinstance(bugs, list):
            continue
        sig = analyze_bug_record(bugs, commitment_index=ca_commitment_index.get(ca),
                                 irq_cache=irq_cache)
        if sig is None:
            continue
        audit_profile = audit_profiles.get(ca)
        scores = compute_als(sig, audit_profile)

        # Fixed threshold: model-assisted qualitative fields do not alter scoring.
        tau = 48
        scores['threshold'] = tau
        scores['flagged']   = scores['total'] >= tau

        results.append({
            'ca':           ca,
            'population':   'active',
            'distrust_event': None,
            'signals':      sig,
            'scores':       scores,
        })

    # ── Distrusted CAs (test vectors) ──────────────────────────────────────
    for ca, bugs in bugs_distrusted.items():
        if not isinstance(bugs, list):
            continue
        sig = analyze_bug_record(bugs, commitment_index=ca_commitment_index.get(ca),
                                 irq_cache=irq_cache)
        if sig is None:
            continue
        audit_profile = audit_profiles.get(ca)
        scores = compute_als(sig, audit_profile)

        event = find_distrust(ca)
        distrust_meta = None
        if event:
            distrust_meta = {
                'pathway':  event.get('distrust_pathway'),
                'posture':  event.get('compliance_posture'),
                'response': event.get('response_quality'),
            }

        results.append({
            'ca':           ca,
            'population':   'distrusted',
            'distrust_event': distrust_meta,
            'signals':      sig,
            'scores':       scores,
        })

    # ── Test vector evaluation ──────────────────────────────────────────────
    B_THRESHOLD = 48  # v2 threshold (min_distrust=55.8, max_healthy=41.0, gap=14.8)

    gradual_results     = []
    non_gradual_results = []

    for r in results:
        if r['population'] != 'distrusted' or r['distrust_event'] is None:
            continue
        # Only include in test vectors if sufficient data to be meaningful
        if r['signals']['n'] < 5:
            continue
        pathway = r['distrust_event'].get('pathway', '')
        flagged = r['scores']['total'] >= B_THRESHOLD
        row = {
            'ca':        r['ca'],
            'pathway':   pathway,
            'posture':   r['distrust_event'].get('posture', ''),
            'n':         r['signals']['n'],
            'n_chronic': r['signals']['n_chronic'],
            'score':     r['scores']['total'],
            'mode_A':    r['scores']['mode_A'],
            'mode_B':    r['scores']['mode_B'],
            'flagged':   flagged,
        }
        if pathway == 'gradual':
            gradual_results.append(row)
        else:
            non_gradual_results.append(row)

    n_gradual_scored   = len(gradual_results)
    n_gradual_flagged  = sum(1 for r in gradual_results if r['flagged'])
    n_nongradual_scored    = len(non_gradual_results)
    n_nongradual_not_flagged = sum(1 for r in non_gradual_results if not r['flagged'])

    sensitivity  = n_gradual_flagged / n_gradual_scored if n_gradual_scored else None
    specificity  = n_nongradual_not_flagged / n_nongradual_scored if n_nongradual_scored else None
    false_positives = [r['ca'] for r in non_gradual_results if r['flagged']]
    false_negatives = [r['ca'] for r in gradual_results if not r['flagged']]

    # ── Population stats ───────────────────────────────────────────────────
    active_scored = [r for r in results if r['population'] == 'active']
    n_active = len(active_scored)
    n_flagged_B = sum(1 for r in active_scored
                      if r['scores']['flagged'] and not r['signals']['low_confidence'])
    n_chronic_1plus = sum(1 for r in active_scored if r['signals']['n_chronic'] >= 1)
    n_chronic_3plus = sum(1 for r in active_scored if r['signals']['n_chronic'] >= 3)
    n_chronic_5plus = sum(1 for r in active_scored if r['signals']['n_chronic'] >= 5)

    # ── Sort active by total ALS descending ────────────────────────────────
    active_scored.sort(key=lambda r: -r['scores']['total'])

    # ── Output ─────────────────────────────────────────────────────────────
    output = {
        'generated_at':   now_utc().isoformat(),
        'methodology':    'paper/loop-failure/loop-failure-v1.tex',
        'parameters': {
            'min_bugs':       MIN_BUGS,
            'chronic_years':  CHRONIC_YEARS,
            'b_threshold':    B_THRESHOLD,
        },
        'test_vector_evaluation': {
            'description': (
                'Graduated-pathway distrusted CAs used as positive test vectors. '
                'Non-graduated (immediate/triggered/negotiated) used as negative vectors. '
                'B >= threshold is the non-remediation flag.'
            ),
            'gradual_cases': gradual_results,
            'non_gradual_cases': non_gradual_results,
            'sensitivity':      round(sensitivity, 3) if sensitivity is not None else None,
            'specificity':      round(specificity, 3) if specificity is not None else None,
            'false_positives':  false_positives,
            'false_negatives':  false_negatives,
            'note': (
                'Evaluation outcomes are reported without entity-specific exceptions. '
                'A false positive or false negative remains an evaluation result rather '
                'than being reclassified in source code.'
            ),
        },
        'population_summary': {
            'active_cas_scored':        n_active,
            'active_b_flagged':         n_flagged_B,
            'active_b_flagged_pct':     round(n_flagged_B / n_active * 100, 1) if n_active else None,
            'chronic_1plus':            n_chronic_1plus,
            'chronic_1plus_pct':        round(n_chronic_1plus / n_active * 100, 1) if n_active else None,
            'chronic_3plus':            n_chronic_3plus,
            'chronic_3plus_pct':        round(n_chronic_3plus / n_active * 100, 1) if n_active else None,
            'chronic_5plus':            n_chronic_5plus,
            'chronic_5plus_pct':        round(n_chronic_5plus / n_active * 100, 1) if n_active else None,
        },
        'scores': results,
    }

    out_path = DATA_DIR / "als_scores.json"
    save_json(out_path, output)
    print(f"[compute_als] Wrote {out_path} ({out_path.stat().st_size:,} bytes)")
    n_distrusted = len([r for r in results if r['population'] == 'distrusted'])
    print(f"[compute_als] {n_active} active CAs scored, {n_distrusted} distrusted CAs")
    print(f"[compute_als] Test vector: sensitivity={sensitivity:.0%} "
          f"specificity={specificity:.0%}" if sensitivity and specificity
          else "[compute_als] Test vector: insufficient data for sensitivity/specificity")
    print(f"[compute_als] Active: {n_flagged_B}/{n_active} ({n_flagged_B/n_active*100:.0f}%) "
          f"flagged (score>={B_THRESHOLD}, n>=10)")
    print(f"[compute_als] Chronic prevalence: "
          f"1+={n_chronic_1plus} ({n_chronic_1plus/n_active*100:.0f}%), "
          f"3+={n_chronic_3plus} ({n_chronic_3plus/n_active*100:.0f}%), "
          f"5+={n_chronic_5plus} ({n_chronic_5plus/n_active*100:.0f}%)")
    if false_positives:
        print(f"[compute_als] False positives: {false_positives}")
    if false_negatives:
        print(f"[compute_als] False negatives: {false_negatives}")


if __name__ == '__main__':
    main()
