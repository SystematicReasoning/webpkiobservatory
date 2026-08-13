#!/usr/bin/env python3
"""
build_cpf_data.py — Rebuild cpf_data.json for the CPF prototype (index2.html)

Joins:
  data/als_scores.json          — structural scores, signals, mode, trend
  data/irq_scores.json          — behavioral + epistemic scores (post-rescore)
  data/comparable_cases.json    — top-3 historical parallels per CA
  data/distrust_data.json       — distrust pathway/posture for distrusted CAs
  data/ca_pattern_chains.json   — Sonnet cross-thread synthesis (Pass 3)
  data/market_share.json        — CT-log market share for EPS bump
  app/public/cpf_temporal.json  — year-by-year ALS series (for sparklines)

Writes:
  app/public/cpf_data.json
  docs/cpf_data.json            (Pages mirror)
"""

import json
import math
import sys
from datetime import date
from pathlib import Path

REPO   = Path(__file__).parent.parent
DATA   = REPO / "data"
PUBLIC = REPO / "app" / "public"
DOCS   = REPO / "docs"


def load(path):
    return json.loads(path.read_text())


def save(path, obj):
    path.write_text(json.dumps(obj, separators=(",", ":")))
    print(f"  Wrote {path} ({path.stat().st_size // 1024} KB)")


# ── Load sources ──────────────────────────────────────────────────────────────

als_raw    = load(DATA   / "als_scores.json")
irq_raw    = load(DATA   / "irq_scores.json")
comp_raw   = load(DATA   / "comparable_cases.json")
dist_raw   = load(DATA   / "distrust_data.json")
chains_raw = load(DATA   / "ca_pattern_chains.json") or {"results": {}}
market_raw = load(DATA   / "market_share.json") or []
ca_details_raw = load(DATA / "ca_details.json") or {}
temporal   = load(PUBLIC / "cpf_temporal.json")

# Index by CA name
als_by_ca    = {r["ca"]: r for r in als_raw["scores"]}

# Deduplicate organization names that differ only in capitalization.
# Keep the canonical first-seen entry and discard capitalization variants.
_seen_lower: dict[str, str] = {}
_dedup_als: dict[str, dict] = {}
for ca, entry in als_by_ca.items():
    lower = ca.lower()
    if lower not in _seen_lower:
        _seen_lower[lower] = ca
        _dedup_als[ca] = entry
    # else: silently drop the duplicate variant
als_by_ca = _dedup_als
irq_by_ca    = {r["ca"]: r["scores"] for r in irq_raw["results"]}
comp_by_ca   = {r["ca"]: r for r in comp_raw["results"]}
dist_events  = dist_raw.get("events", dist_raw.get("results", []))
dist_by_ca   = {e["ca"]: e for e in dist_events}
temp_by_ca   = {c["ca"]: c for c in temporal["cas"]}
chains_by_ca   = chains_raw.get("results", {})
market_by_ca   = {m["ca_owner"]: m for m in market_raw}
ca_details_by_ca = ca_details_raw  # keyed by CA owner name already

print(f"Sources: ALS={len(als_by_ca)}, IRQ={len(irq_by_ca)}, "
      f"Comp={len(comp_by_ca)}, Dist={len(dist_by_ca)}, Temporal={len(temp_by_ca)}")


# ── CA metadata helpers ──────────────────────────────────────────────────────

def _market_share(ca_name: str) -> float | None:
    """Return market_share_pct for a CA, with fuzzy name matching."""
    m = market_by_ca.get(ca_name)
    if m:
        return m["market_share_pct"]
    ca_lower = ca_name.lower()
    for owner, data in market_by_ca.items():
        if owner.lower() in ca_lower or ca_lower in owner.lower():
            return data["market_share_pct"]
    return None


def compute_eps(ca_name: str, als_total: float, irq_scores: dict,
                sig: dict, population: str) -> float:
    """Return the source-neutral deterministic engagement score.

    The public UI retains the historical ``eps`` field for compatibility. EPS is
    now a bounded projection of the structural ALS result. The additional
    arguments remain in the signature so existing call sites and data plumbing do
    not break, but identity, market share, and model-assisted qualitative fields
    do not affect the value.
    """
    del ca_name, irq_scores, sig, population
    return round(min(max(float(als_total), 0.0), 100.0), 1)


def eps_tier(als_total: float, irq_failure: float, flagged: bool,
             eps: float = 0.0) -> str:
    """Three-tier classification: elevated / monitoring / routine.

    Elevated: flagged by ALS behavior-adjusted threshold (structural signal).
    Monitoring: not elevated but EPS >= 35 — behavioral/recency signals worth
                tracking even if structural accumulation hasn't crossed threshold.
    Routine: below both thresholds.
    """
    if flagged or als_total >= 48:
        return "elevated"
    if eps >= 35:
        return "monitoring"
    return "routine"

# ── Narrative generators ──────────────────────────────────────────────────────

def why_structural(signals, scores):
    """Plain-English bullets explaining the structural ALS signals."""
    items = []
    n_ch     = signals.get("n_chronic", 0)
    n_closed = scores.get("n_closed_loop", 0) or 0
    n_broken = scores.get("n_broken_promise", 0) or 0
    avg_kw   = scores.get("avg_knowledge_weight", 1.0) or 1.0
    ck       = signals.get("chronic_knowledge", {})

    # Chronic class count
    if n_ch >= 5:
        items.append(f"{n_ch} failure classes have each recurred across 3+ calendar years")
    elif n_ch >= 2:
        items.append(f"{n_ch} failure classes have recurred across 3+ calendar years")
    elif n_ch == 1:
        items.append("1 failure class has recurred across 3+ calendar years")

    # Closed-loop credit (positive)
    if n_closed >= 1:
        cc    = signals.get("closed_loop_classes", [])
        label = ", ".join(cc[:2]) + ("…" if len(cc) > 2 else "")
        items.append(
            f"{n_closed} chronic class{'es' if n_closed > 1 else ''} appear resolved — "
            f"commitment made, 3+ years quiescent ({label})"
        )

    # Broken promise (negative)
    if n_broken >= 1:
        bp    = signals.get("broken_promise_classes", [])
        label = ", ".join(bp[:2]) + ("…" if len(bp) > 2 else "")
        items.append(
            f"{n_broken} governance commitment{'s' if n_broken > 1 else ''} broken — "
            f"{label} recurred within 2 years of an explicit commitment"
        )

    # Ecosystem knowledge weight
    if avg_kw >= 1.3 and ck:
        worst = max(ck.items(), key=lambda x: x[1].get("weight", 1))
        tag, info = worst
        items.append(
            f"Chronic failures on well-documented ecosystem classes — "
            f"{tag} had {info['prior_cas']} prior CAs and {info['eco_age']} years of "
            f"industry precedent before this CA's first occurrence"
        )
    elif avg_kw >= 1.1 and ck:
        items.append(
            f"Chronic failures on classes with established ecosystem precedent "
            f"(knowledge weight {avg_kw:.2f}×)"
        )

    # Self-report rate
    sp = signals.get("self_pct", 100)
    if sp < 20:
        items.append(
            f"Only {sp:.0f}% of incidents were self-reported — "
            "external parties are finding this CA's problems"
        )
    elif sp < 40:
        items.append(f"{sp:.0f}% of incidents were self-reported")

    # Acceleration
    accel = signals.get("accel", 1)
    if accel >= 3:
        items.append(
            f"Incident rate has worsened ({accel:.1f}× faster in recent years)"
        )
    elif accel >= 2:
        items.append(f"Incident rate is accelerating ({accel:.1f}×)")

    # Solo chronic ratio
    solo = signals.get("solo_ratio", 0)
    if solo >= 0.5:
        items.append(
            f"{solo * 100:.0f}% of chronic classes are unique to this CA — "
            "not an ecosystem-wide pattern"
        )

    return items


def why_behavioral(irq, n_silent=0):
    """Plain-English bullets explaining the behavioral IRQ signals."""
    items = []

    esc = irq.get("escalating_fraction", 0) or 0
    if esc >= 0.3:
        items.append(
            f"{esc * 100:.0f}% of compliance threads involve the CA "
            "contesting whether requirements apply"
        )
    elif esc >= 0.1:
        items.append(
            f"{esc * 100:.0f}% of threads involve the CA pushing back on requirements"
        )

    pc_ign = irq.get("pattern_connections_ignored", 0) or 0
    if pc_ign >= 3:
        items.append(
            f"{pc_ign} times the CA did not engage when community members "
            "linked this to a recurring pattern"
        )
    elif pc_ign >= 1:
        items.append(
            f"{pc_ign} pattern connection{'s' if pc_ign > 1 else ''} ignored — "
            "community raised recurring class, CA didn't acknowledge"
        )

    rca = irq.get("avg_rca_depth")
    if rca is not None and rca <= 1.5:
        items.append(
            "Root cause analyses tend to be proximate-only — "
            "systemic causes rarely identified"
        )

    candor = irq.get("candor_failure_rate")
    if candor is not None and candor >= 0.4:
        items.append(
            f"{candor * 100:.0f}% of threads show candor failures — "
            "incomplete or delayed disclosure"
        )

    oblig = irq.get("oblig_failure_rate")
    if oblig is not None and oblig >= 0.4:
        items.append(
            f"{oblig * 100:.0f}% of threads show obligation failures — "
            "CA does not understand the requirement it violated"
        )

    restate = irq.get("restatement_fraction")
    if restate is not None and restate >= 0.3:
        items.append(
            f"{restate * 100:.0f}% of commitments restate prior commitments — "
            "same promises made repeatedly without resolution"
        )

    # Silent disclosure from pattern synthesis
    if n_silent >= 3:
        items.append(
            f"{n_silent} recurring architectural patterns never self-disclosed "
            "in incident reports — CA did not reference prior related failures"
        )
    elif n_silent >= 1:
        items.append(
            f"{n_silent} pattern{'s' if n_silent > 1 else ''} not self-disclosed — "
            "prior related failures not referenced in later incident reports"
        )

    return items


def integrity_label(failure_rate):
    """Convert a failure rate (0–1) to a display label."""
    if failure_rate is None:
        return None
    if failure_rate >= 0.5:
        return "poor"
    if failure_rate >= 0.2:
        return "partial"
    return "good"


def irq_confidence(scores):
    """Return (0–1 float, label) confidence score for the IRQ result."""
    n = scores.get("n_scored", 0) or 0
    if n == 0:
        return 0.0, "no data"

    size_conf = n / (n + 5)

    n_total  = scores.get("n_bugs_total", n)
    coverage = n / max(n_total, 1)

    arcs       = scores.get("arc_distribution", {}) or {}
    total_arcs = sum(arcs.values())
    if total_arcs > 0:
        probs       = [v / total_arcs for v in arcs.values() if v > 0]
        entropy     = -sum(p * math.log2(p) for p in probs)
        consistency = 1 - (entropy / math.log2(5))
    else:
        consistency = 0.5

    conf  = round(size_conf * 0.5 + coverage * 0.3 + consistency * 0.2, 3)
    label = "high" if conf >= 0.7 else "moderate" if conf >= 0.4 else "low"
    return conf, label


# ── Build rows ────────────────────────────────────────────────────────────────

rows = []

for ca_name, als_entry in als_by_ca.items():
    sig    = als_entry["signals"]
    sc     = als_entry["scores"]
    pop    = als_entry["population"]
    dist_e = als_entry.get("distrust_event") or dist_by_ca.get(ca_name)
    irq    = irq_by_ca.get(ca_name, {})
    comp_e = comp_by_ca.get(ca_name, {})
    temp_e = temp_by_ca.get(ca_name, {})
    chains = chains_by_ca.get(ca_name, {})

    als_total   = sc.get("total", 0)
    irq_failure = irq.get("irq_failure", 0) or 0
    patterns    = chains.get("patterns", [])
    eps         = compute_eps(ca_name, als_total, irq, sig, pop)
    tier        = eps_tier(als_total, irq_failure, sc.get("flagged", False), eps) if pop == "active" else "elevated"
    mkt_pct     = _market_share(ca_name)

    # Trust store status from ca_details
    ca_det = ca_details_by_ca.get(ca_name, {})
    if not ca_det:
        # fuzzy match
        ca_lower = ca_name.lower()
        ca_det = next((v for k, v in ca_details_by_ca.items()
                       if k.lower() in ca_lower or ca_lower in k.lower()), {})
    trusted_by = ca_det.get("trusted_by", {})
    in_apple    = trusted_by.get("apple")
    in_chrome   = trusted_by.get("chrome")
    in_mozilla  = trusted_by.get("mozilla")
    in_microsoft= trusted_by.get("microsoft")
    trust_stores_count = ca_det.get("trust_store_count")
    # Note: partial_distrust cannot be reliably determined from CA-level aggregates.
    # in_apple/chrome/mozilla only tells us if any root is trusted, not if specific
    # roots were actively distrusted. Would need root-level CCADB distrust_date fields
    # or Chrome Root Store git history to determine this accurately.
    partial_distrust = False

    # Temporal series for sparkline
    tau    = sc.get("threshold", 48)
    series = temp_e.get("series", [])
    first_flagged = next((pt["year"] for pt in series if pt.get("als", 0) >= tau), None)

    # Arc fractions (percent integers for UI bars)
    esc_frac = round((irq.get("escalating_fraction", 0) or 0) * 100)
    ap_frac  = round((irq.get("accountability_pressure_frac", 0) or 0) * 100)

    # Comparables — top 3 with narrative
    comparables = [
        {
            "ca":        c["comparable_ca"],
            "sim":       round(c["similarity_score"]),
            "pathway":   c.get("distrust_pathway", "gradual"),
            "narrative": "; ".join(c.get("similarity_reasons", [])[:2]),
        }
        for c in comp_e.get("top_comparables", [])[:3]
    ]

    # Distrust pathway (distrusted CAs only)
    distrust_pathway = dist_e.get("distrust_pathway") if dist_e else None

    # IRQ confidence score
    n_scored   = irq.get("n_scored", 0) or 0
    n_bugs     = sig.get("n", 0)
    confidence = min(n_scored / max(n_bugs, 1), 1.0) if n_bugs >= 5 else 0.3

    # Pattern chain disclosure quality counts
    n_silent    = sum(1 for p in patterns if p.get("disclosure_quality") == "silent")
    n_reactive  = sum(1 for p in patterns if p.get("disclosure_quality") == "reactive")
    n_proactive = sum(1 for p in patterns if p.get("disclosure_quality") == "proactive")

    row = {
        "ca":         ca_name,
        "population": pop,
        "tier":       tier,
        "flagged":    sc.get("flagged", False),

        # Scores
        "als":              round(als_total, 1),
        "irq":              round(irq_failure, 1),
        "eps":              round(eps, 1),
        "score_basis":      "deterministic_structural_v1",
        "qualitative_context": "model_assisted_non_scoring",
        "market_share_pct": round(mkt_pct, 6) if mkt_pct is not None else None,
        "in_apple":          in_apple,
        "in_chrome":         in_chrome,
        "in_mozilla":        in_mozilla,
        "in_microsoft":      in_microsoft,
        "trust_stores_count": trust_stores_count,
        "partial_distrust":  partial_distrust,

        # ALS structural signals
        "mode":             sc.get("dominant_mode", "A"),
        "n_bugs":           n_bugs,
        "n_chronic":        sig.get("n_chronic", 0),
        "n_solo_chronic":   sig.get("n_solo_chronic", 0),
        "solo_ratio":       round(sig.get("solo_ratio", 0), 2),
        "self_pct":         round(sig.get("self_pct", 0), 1),
        "accel":            round(sig.get("accel", 1), 2),
        "chronic_classes":  list(sig.get("chronic_classes", {}).keys()),

        # Commitment loop signals (from ALS)
        "avg_knowledge_weight":   round(sc.get("avg_knowledge_weight", 1.0), 3),
        "n_closed_loop":          sc.get("n_closed_loop", 0),
        "n_broken_promise":       sc.get("n_broken_promise", 0),
        "broken_boost":           round(sc.get("broken_boost", 1.0), 3),
        "closed_loop_classes":    sig.get("closed_loop_classes", []),
        "broken_promise_classes": sig.get("broken_promise_classes", []),
        "chronic_knowledge":      sig.get("chronic_knowledge", {}),

        # IRQ behavioral signals
        "esc_frac":   esc_frac,
        "ap_frac":    ap_frac,
        "arc_trend":  irq.get("arc_trend", "stable"),
        "pc_ignored": irq.get("pattern_connections_ignored", 0) or 0,
        "pc_raised":  irq.get("pattern_connections_raised", 0) or 0,

        # IRQ epistemic signals
        "avg_rca_depth":          irq.get("avg_rca_depth"),
        "n_rca_insufficient":     irq.get("n_rca_insufficient"),
        "candor_failure_rate":    irq.get("candor_failure_rate"),
        "acct_failure_rate":      irq.get("acct_failure_rate"),
        "oblig_failure_rate":     irq.get("oblig_failure_rate"),
        "n_poor_candor":          irq.get("n_poor_candor"),
        "n_poor_accountability":  irq.get("n_poor_accountability"),
        "n_poor_obligation":      irq.get("n_poor_obligation"),
        "n_commitments":          irq.get("n_commitments"),
        "n_commitments_grade_A":  irq.get("n_commitments_grade_A"),
        "n_commitments_grade_DF": irq.get("n_commitments_grade_DF"),
        "n_restatements":         irq.get("n_restatements"),
        "restatement_fraction":   irq.get("restatement_fraction"),
        "timeliness":             irq.get("timeliness"),

        # Derived integrity labels (good|partial|poor)
        "candor":                   integrity_label(irq.get("candor_failure_rate")),
        "accountability":           integrity_label(irq.get("acct_failure_rate")),
        "obligation_understanding": integrity_label(irq.get("oblig_failure_rate")),

        # IRQ confidence
        "irq_confidence":       irq_confidence(irq)[0],
        "irq_confidence_label": irq_confidence(irq)[1],

        # Temporal series
        "series":        series,
        "first_flagged": first_flagged,

        # Context
        "comparables":      comparables,
        "distrust_pathway": distrust_pathway,
        "confidence":       round(confidence, 2),

        # Narrative bullets (generated from signals above)
        "why_structural": why_structural(sig, sc),
        "why_behavioral": why_behavioral(irq, n_silent=n_silent),

        # Sonnet pattern synthesis
        "pattern_chains":        patterns,
        "n_pattern_chains":      len(patterns),
        "n_silent_disclosure":   n_silent,
        "n_reactive_disclosure": n_reactive,
        "n_proactive_disclosure":n_proactive,
        "synthesis_notes":       chains.get("synthesis_notes"),

        # Metadata enriched below from existing cpf_data
        "region":    None,
        "framework": None,
        "ca_type":   None,
        "country":   None,
        "trend":     irq.get("arc_trend", "stable"),  # alias for legacy UI refs
    }
    rows.append(row)


# ── Enrich region/framework/ca_type/country from existing cpf_data ───────────
# These come from CCADB. Re-use from previous build to avoid losing them.

try:
    existing      = load(PUBLIC / "cpf_data.json")
    existing_by_ca = {r["ca"]: r for r in existing.get("rows", [])}
    for row in rows:
        ex = existing_by_ca.get(row["ca"], {})
        row["region"]    = ex.get("region")
        row["framework"] = ex.get("framework")
        row["ca_type"]   = ex.get("ca_type")
        row["country"]   = ex.get("country")
    print("  Preserved region/framework/ca_type/country from existing cpf_data")
except Exception as e:
    print(f"  Warning: could not read existing cpf_data for metadata: {e}")


# ── Sort: elevated first, then monitoring, then routine; within tier by EPS ───

TIER_ORDER = {"elevated": 0, "monitoring": 1, "routine": 2}
rows.sort(key=lambda r: (TIER_ORDER.get(r["tier"], 9), -r["eps"]))


# ── Write ─────────────────────────────────────────────────────────────────────

output = {"generated_at": date.today().isoformat(), "rows": rows}

print(f"\nBuilding cpf_data.json — {len(rows)} CAs")
elevated   = sum(1 for r in rows if r["tier"] == "elevated"   and r["population"] == "active")
monitoring = sum(1 for r in rows if r["tier"] == "monitoring" and r["population"] == "active")
print(f"  Active elevated: {elevated}, monitoring: {monitoring}")
print(f"  Epistemic fields populated: {sum(1 for r in rows if r['avg_rca_depth'] is not None)}")
rca_elevated = [r["avg_rca_depth"] for r in rows if r["tier"] == "elevated" and r["avg_rca_depth"]]
if rca_elevated:
    print(f"  Avg RCA depth (elevated): {sum(rca_elevated)/len(rca_elevated):.2f}")

save(PUBLIC / "cpf_data.json", output)
save(DOCS   / "cpf_data.json", output)
print("Done.")
