#!/usr/bin/env python3
"""
export_llm_snapshot.py — Generate an LLM-ready snapshot of the WebPKI Observatory.

Reads all pipeline output JSON files and produces a single, self-describing
JSON document (~65-70K tokens) conforming to the published schema at:
  https://webpki.systematicreasoning.com/schema.json

Outputs:
  data/llm_snapshot.json              — stable URL, always current
  data/llm_snapshot_YYYY-MM-DD.json   — dated archive copy

Usage:
  python pipeline/export_llm_snapshot.py [--data-dir data/] [--pipeline-dir pipeline/]
"""
import json
from utils import load_json_dir as load_json, slugify
import os
from pathlib import Path
import sys
from collections import Counter
from urllib.parse import quote as _quote
from datetime import datetime, timezone

# Shared config
sys.path.insert(0, os.path.dirname(__file__))
from config import BR_VALIDITY, DISTRUST_OVERRIDES, COUNTRY_NAMES

SCHEMA_VERSION = "1.0.0"
SCHEMA_URL = "https://webpki.systematicreasoning.com/schema.json"
SNAPSHOT_URL = "https://webpki.systematicreasoning.com/llm_snapshot.json"

DATA_DIR = os.environ.get("PIPELINE_DATA_DIR", "data")
PIPELINE_DIR = os.environ.get("PIPELINE_DIR", "pipeline")

for arg in sys.argv[1:]:
    if arg.startswith("--data-dir="):
        DATA_DIR = arg.split("=", 1)[1]
    elif arg.startswith("--pipeline-dir="):
        PIPELINE_DIR = arg.split("=", 1)[1]






def norm_country(c):
    return COUNTRY_NAMES.get(c, c) if c else ""



# ══════════════════════════════════════════════════════════════════
# Export sliced JSON files for LLMs with limited context windows
# Each slice is a self-contained subset of the full snapshot



def export_slices(snapshot: dict, out_dir: Path, full_roots: list = None) -> None:
    """
    Publish focused slices so LLMs can fetch just what they need.

    Token budget of the full snapshot (~78k tokens) is dominated by:
      rootAlgorithms  36%  — per-root crypto detail
      market          19%  — per-CA market share rows
      governance      16%  — large but critical
      distrustEvents   9%  — event detail

    Slices let an LLM fetch governance+policy (~16k tok) or
    distrust+incidents (~15k tok) without burning budget on roots.
    """
    # Common header fields included in every slice
    header = {
        "$schema":      snapshot["$schema"],
        "version":      snapshot["version"],
        "generatedAt":  snapshot["generatedAt"],
        "snapshotUrl":  snapshot["snapshotUrl"],
        "note": "Sliced subset of llm_snapshot.json. Fetch the full snapshot for complete data.",
    }

    SLICES = {
        # Governance and compliance — the sections most LLMs need for policy analysis
        "llm_snapshot_governance.json": {
            **header,
            "governance":          snapshot.get("governance", {}),
            "ecosystemParticipation": snapshot.get("ecosystemParticipation", {}),
            "regulatorySurface":   snapshot.get("regulatorySurface", {}),
            "brThresholds":        snapshot.get("brThresholds", {}),
            "brReadiness":         snapshot.get("brReadiness", {}),
            "auditIntelligence":   snapshot.get("auditIntelligence", {}),
            "tabIntros":           snapshot.get("tabIntros", {}),
        },
        # Distrust and incident history
        "llm_snapshot_distrust.json": {
            **header,
            "distrustEvents":  snapshot.get("distrustEvents", []),
            "distrustStats":   snapshot.get("distrustStats", {}),
            "incidents":       snapshot.get("incidents", {}),
        },
        # Market structure and trust surface
        "llm_snapshot_market.json": {
            **header,
            "market":              snapshot.get("market", []),
            "browserCoverage":     snapshot.get("browserCoverage", {}),
            "trustSurface":        snapshot.get("trustSurface", {}),
            "concentration":       snapshot.get("concentration", {}),
            "chromeRootStoreGrowth": snapshot.get("chromeRootStoreGrowth", {}),
        },
        # Risk profile — geography, government, jurisdiction, crypto
        # rootAlgorithms here is the FULL per-root list (not the summary in the main snapshot)
        "llm_snapshot_risk.json": {
            **header,
            "geography":           snapshot.get("geography", []),
            "governmentRisk":      snapshot.get("governmentRisk", {}),
            "jurisdictionRisk":    snapshot.get("jurisdictionRisk", {}),
            "cryptoSummary":       snapshot.get("cryptoSummary", {}),
            "rootAlgorithms":      full_roots if full_roots is not None else snapshot.get("rootAlgorithms", {}),
        },
    }

    base_url = snapshot.get("snapshotUrl", "").rsplit("/", 1)[0]

    for filename, content in SLICES.items():
        path = out_dir / filename
        path.write_text(json.dumps(content, indent=2, ensure_ascii=False))
        size = path.stat().st_size
        tokens = size // 4
        print(f"  Slice {filename}: {size:,} bytes (~{tokens:,} tokens)")

    # Write a slice index
    index = {
        **header,
        "slices": {
            "governance": f"{base_url}/llm_snapshot_governance.json",
            "distrust":   f"{base_url}/llm_snapshot_distrust.json",
            "market":     f"{base_url}/llm_snapshot_market.json",
            "risk":       f"{base_url}/llm_snapshot_risk.json",
            "full":       snapshot.get("snapshotUrl"),
        },
        "sliceGuide": {
            "governance": "CA/Browser Forum governance, oversight rates, compliance complexity, BR readiness, ecosystem participation, audit letter quality and transparency gap analysis",
            "distrust":   "Distrust history (16 events 2011-2024), incident patterns, Bugzilla CA compliance data",
            "market":     "CA market share, trust surface, browser coverage, concentration metrics",
            "risk":       "Geographic, government, jurisdiction, and cryptographic risk data",
            "full":       "Complete snapshot (~78k tokens) — all sections combined",
        },
    }
    idx_path = out_dir / "llm_snapshot_index.json"
    idx_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    print(f"  Index: {idx_path}")

def _build_crl_health_snapshot(crl_health: dict) -> dict:
    """
    Summarise CRL infrastructure health for the LLM snapshot.
    Includes key metrics, issue breakdown, and revocation reason distribution.
    """
    if not crl_health:
        return {}
    s = crl_health.get("summary", {})
    urls = crl_health.get("urls", [])

    # Issues by store presence
    issues_by_store: dict = {}
    for u in urls:
        if u.get("status") == "ok":
            continue
        w = u.get("in_microsoft", False)
        a = u.get("in_apple", False)
        c = u.get("in_chrome", False)
        m = u.get("in_mozilla", False)
        if w and not any([a, c, m]):
            issues_by_store["microsoftOnly"] = issues_by_store.get("microsoftOnly", 0) + 1
        else:
            for k, v in [("apple", a), ("chrome", c), ("mozilla", m)]:
                if v:
                    issues_by_store[k] = issues_by_store.get(k, 0) + 1

    # Notable CAs with issues
    ca_issues: dict = {}
    for u in urls:
        if u.get("status") != "ok":
            ca = u.get("ca_owner", "")
            if ca not in ca_issues:
                ca_issues[ca] = {"ca": ca, "status": u["status"],
                                 "in_apple": u.get("in_apple"), "in_chrome": u.get("in_chrome"),
                                 "in_mozilla": u.get("in_mozilla"), "in_microsoft": u.get("in_microsoft")}

    return {
        "generatedAt":          crl_health.get("generated_at"),
        "totalUrls":            s.get("total_urls"),
        "okCount":              s.get("ok_count"),
        "issueCount":           s.get("issue_count"),
        "casTotal":             s.get("ca_count"),
        "casWithIssues":        s.get("cas_with_issues"),
        "healthPct":            round(s["ok_count"] / s["total_urls"] * 100, 1)
                                if s.get("total_urls") else None,
        "statusBreakdown":      s.get("status_counts", {}),
        "totalRevoked":         s.get("total_revoked"),
        "revocationsPerDay":    s.get("revocations_per_day"),
        "globalRevocationPpm":  s.get("global_revocation_ppm"),
        "revocationReasons":    s.get("revocation_reasons", {}),
        "issuesByStore":        issues_by_store,
        "casWithIssuesList":    list(ca_issues.values()),
        "note": (
            "CRL URLs are filed in CCADB by CA operators. "
            "issuer_mismatch means the wrong CRL URL is filed — CRLite/CRL Sets "
            "aggregators may miss revocations from that CA though CDP-fetching browsers "
            "are unaffected. br_violation means CRL validity window exceeds BR §4.9.7 limits. "
            "Microsoft-only CAs are often government PKIs not governed by CA/B Forum BRs."
        ),
    }


def _build_audit_snapshot(audits_data: dict) -> dict:
    """
    Extract a concise audit intelligence summary for the LLM snapshot.
    Designed for LLM consumption — structured for analysis, not UI rendering.
    """
    if not audits_data:
        return {}

    s        = audits_data.get("summary", {})
    profiles = audits_data.get("profiles", [])
    agg      = audits_data.get("auditor_aggregates", {})
    parsed   = [p for p in profiles if p.get("pdf_parsed")]

    # Per-framework self-report rates
    def avg_self(fw):
        vals = [p["self_report_pct"] for p in profiles
                if p.get("primary_framework") == fw
                and p.get("self_report_pct") is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    # Qualified opinion CAs
    qualified = [
        {"ca": p["ca_owner"], "stores": p.get("trusted_stores", []),
         "auditor": p.get("primary_auditor")}
        for p in parsed if p.get("opinion_type") == "qualified"
    ]

    # High transparency gap CAs (top 10 by incident count)
    high_gap = sorted(
        [p for p in parsed
         if (p.get("transparency_gap") or {}).get("gap_level") == "high"],
        key=lambda p: -(p.get("incident_count") or 0)
    )[:10]

    # Auditor changes — last 3 years (not hardcoded year-1).
    # The LLM snapshot truncates to recent changes for token budget reasons.
    # The full timeline is available per-CA in audit_timeline.
    # Using 3 years to capture the full context of the 2025 spike
    # (baseline years 2023-2024 + spike year 2025).
    import datetime
    since_year = datetime.date.today().year - 2
    changes = []
    for p in profiles:
        for c in (p.get("timeline_trends") or {}).get("auditor_changes", []):
            if c.get("year", 0) >= since_year:
                changes.append({
                    "year": c["year"], "ca": p["ca_owner"],
                    "from": c.get("from_auditor"), "to": c.get("to_auditor"),
                })

    # ETSI AAL adoption
    etsi_parsed = [p for p in parsed if p.get("primary_framework") == "ETSI"]
    aal_counts = {}
    for p in etsi_parsed:
        v = (p.get("criteria_check") or {}).get("aal_version") or "unknown"
        aal_counts[v] = aal_counts.get(v, 0) + 1

    # Matters without Bugzilla anchor
    no_bz_matters = [
        {"ca": p["ca_owner"], "summary": m.get("summary", "")[:80]}
        for p in parsed
        for m in (p.get("disclosed_matters") or [])
        if not (m.get("bugzilla_ids") or [])
    ]

    # Top auditors summary
    top_auditors = [
        {
            "name": name,
            "caCount": a["ca_count"],
            "country": a.get("auditor_country"),
            "avgQualityScore": a.get("avg_quality_score"),
            "avgGapScore": a.get("avg_gap_score"),
            "highGapCount": a.get("high_gap_count", 0),
            "avgMattersPerCA": a.get("avg_matters_per_ca"),
        }
        for name, a in list(agg.items())[:12]
    ]

    # In-period detection rate (unique bugs as denominator — matches UI headline)
    # retro_covered: bugs with at least one covering audit period
    # retro_caught:  bugs mentioned in at least one covering letter
    # retro_multi:   bugs that were missed by ALL covering letters AND
    #                had 2+ covering periods (survived multiple audit cycles)
    #                Note: this is a subset of (retro_covered - retro_caught),
    #                not an independent count.
    retro_covered = retro_caught = retro_multi = 0
    for p in profiles:
        for r in (p.get("bug_retrospective") or []):
            if r.get("covering_letters", 0) > 0:
                retro_covered += 1
                if r.get("mentioned_in", 0) > 0:
                    retro_caught += 1
                elif r.get("missed_by", 0) >= 2:
                    retro_multi += 1

    # Per-auditor detection rates (attributed by audit_timeline stmt_date)
    from collections import defaultdict
    aud_det = defaultdict(lambda: {"caught": 0, "total": 0})
    for p in profiles:
        stmt_to_aud = {
            e["stmt_date"]: e.get("auditor")
            for e in (p.get("audit_timeline") or []) if e.get("stmt_date")
        }
        for r in (p.get("bug_retrospective") or []):
            for c in (r.get("audit_coverage") or []):
                firm = stmt_to_aud.get(c.get("stmt_date")) or p.get("primary_auditor")
                if not firm:
                    continue
                aud_det[firm]["total"] += 1
                if c.get("mentioned"):
                    aud_det[firm]["caught"] += 1
    auditor_detection = sorted(
        [
            {
                "auditor": firm,
                "caught": v["caught"],
                "total": v["total"],
                "detectionPct": round(v["caught"] / v["total"] * 100, 1) if v["total"] else 0,
            }
            for firm, v in aud_det.items() if v["total"] >= 3
        ],
        key=lambda x: -x["detectionPct"],
    )

    # ALV-equivalent completeness findings
    alv_fp_missing  = sum(1 for p in parsed if (p.get("fingerprint_check") or {}).get("engagement_fps_missing"))
    alv_scope_gaps  = sum(1 for p in parsed if (p.get("oid_check") or {}).get("gaps"))
    alv_accurate    = sum(1 for p in parsed if (p.get("fingerprint_check") or {}).get("engagement_accurate") is True)
    alv_untraced    = sum(p.get("root_coverage", {}).get("roots_without_url", 0) for p in parsed)

    # Per-auditor ALV completeness (2+ clients, current letters)
    from collections import defaultdict as dd2
    aud_alv = dd2(lambda: {"total": 0, "fpMissing": 0, "scopeGap": 0})
    for p in parsed:
        firm = p.get("primary_auditor") or "Unknown"
        fc = p.get("fingerprint_check") or {}
        oc = p.get("oid_check") or {}
        aud_alv[firm]["total"] += 1
        if fc.get("engagement_fps_missing"):
            aud_alv[firm]["fpMissing"] += 1
        if oc.get("gaps"):
            aud_alv[firm]["scopeGap"] += 1
    auditor_alv = sorted(
        [
            {
                "auditor": firm,
                "clients": v["total"],
                "missingFingerprintsPct": round(v["fpMissing"] / v["total"] * 100),
                "scopeGapPct": round(v["scopeGap"] / v["total"] * 100),
            }
            for firm, v in aud_alv.items() if v["total"] >= 2
        ],
        key=lambda x: -x["missingFingerprintsPct"],
    )

    return {
        "generatedAt": audits_data.get("generated_at"),
        "summary": {
            "totalCAOwners":        s.get("total_ca_owners"),
            "parsedLetters":        s.get("pdf_parsed_count"),
            "highTransparencyGap":  s.get("high_transparency_gap"),
            "qualifiedOpinions":    s.get("qualified_opinions"),
            "mattersWithoutBzAnchor": s.get("matters_without_bz_anchor"),
            "auditorHHI":           s.get("auditor_hhi"),
            "auditRecordStatus":    s.get("audit_record_status"),
            "stalenessDistribution": s.get("staleness_buckets"),
        },
        "frameworkStats": s.get("framework_stats"),
        "selfReportByFramework": {
            "webTrust": avg_self("WebTrust"),
            "etsi":     avg_self("ETSI"),
        },
        "inPeriodDetection": {
            "covered":       retro_covered,
            "caught":        retro_caught,
            "multiCycleMisses": retro_multi,
            "detectionPct":  round(retro_caught / retro_covered * 100, 1) if retro_covered else None,
            "note": "Denominator = unique bugs with at least one covering audit period. Caught = mentioned in any covering letter.",
        },
        "perAuditorDetection": auditor_detection,
        "alvEquivalentFindings": {
            "parsedLetters":        len(parsed),
            "missingRootFingerprints": alv_fp_missing,
            "certificateScopeGaps": alv_scope_gaps,
            "accurateFingerprintCoverage": alv_accurate,
            "untracedRoots":        alv_untraced,
            "missingFingerprintsPct": round(alv_fp_missing / len(parsed) * 100) if parsed else 0,
            "scopeGapsPct":          round(alv_scope_gaps  / len(parsed) * 100) if parsed else 0,
        },
        "perAuditorAlvFindings": auditor_alv,
        "qualifiedOpinions": qualified,
        "highTransparencyGapCAs": [
            {
                "ca": p["ca_owner"],
                "incidentCount": p.get("incident_count"),
                "gapScore": (p.get("transparency_gap") or {}).get("gap_score"),
                "mattersCount": (p.get("transparency_gap") or {}).get("matters_count"),
                "auditor": p.get("primary_auditor"),
                "framework": p.get("primary_framework"),
            }
            for p in high_gap
        ],
        "etsiAalAdoption": aal_counts,
        "auditorChanges": changes,
        "mattersWithoutBzAnchor": no_bz_matters,
        "topAuditors": top_auditors,
    }


def main():
    print("Generating LLM snapshot...")
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    # ── Load all pipeline outputs ──
    market_share = load_json(DATA_DIR, "market_share.json") or []
    intersections = load_json(DATA_DIR, "intersections.json") or {}
    geography = load_json(DATA_DIR, "geography.json") or {}
    gov_risk = load_json(DATA_DIR, "gov_risk.json") or {}
    incidents = load_json(DATA_DIR, "incidents.json") or {}
    jurisdiction_risk = load_json(DATA_DIR, "jurisdiction_risk.json") or {}
    root_algo = load_json(DATA_DIR, "root_algorithms.json") or {}
    browser_cov = load_json(DATA_DIR, "browser_coverage.json") or {}
    rpe = load_json(DATA_DIR, "root_program_effectiveness.json") or {}
    distrust = load_json(PIPELINE_DIR, "distrust/distrusted.json") or {}
    community = load_json(DATA_DIR, "community_engagement.json") or {}
    chrome_cl = load_json(DATA_DIR, "chrome_root_store_changelog.json") or {}
    compliance_growth = load_json(DATA_DIR, "compliance_growth.json") or {}
    audits_data       = load_json(DATA_DIR, "audits.json") or {}
    crl_health        = load_json(DATA_DIR, "crl_health.json") or {}

    # ── Incident lookup ──
    inc_by_ca = {}
    for ca in incidents.get("cas", []):
        inc_by_ca[ca.get("ca", "")] = ca

    # ── Browser coverage ──
    cov = browser_cov.get("coverage", {})
    browser_coverage = {
        "chrome": cov.get("chrome", 0.77),
        "apple": cov.get("apple", 0.18),
        "mozilla": cov.get("mozilla", 0.025),
        "microsoft": cov.get("microsoft", 0.005),
    }

    # ═══════════════════════════════════════════════════════════════
    # Section 1: Market
    # ═══════════════════════════════════════════════════════════════
    trusted = [ca for ca in market_share
               if ca.get("trust_store_count", 0) > 0
               and ca.get("ca_owner", "") not in DISTRUST_OVERRIDES]
    total_certs = sum(ca["unexpired_precerts"] for ca in trusted)

    market = []
    for ca in trusted:
        all_time = ca.get("all_precerts", 0)
        unexpired = ca["unexpired_precerts"]
        turnover = all_time / unexpired if unexpired > 0 and all_time > 0 else 0
        usage_days = round(365 / turnover) if turnover > 0 else 0
        tb = ca.get("trusted_by", {})
        web_cov = sum(browser_coverage.get(s, 0) for s, v in tb.items() if v) * 100
        inc = inc_by_ca.get(ca["ca_owner"])
        ppm = None
        self_pct = None
        inc_count = 0
        if inc:
            inc_count = inc.get("n", 0)
            self_pct = inc.get("selfPct")
            if all_time > 0 and inc_count > 0:
                ppm = round((inc_count / all_time) * 1e6, 3)
        market.append({
            "rank": ca["rank"], "id": slugify(ca["ca_owner"]),
            "caSlug": slugify(ca["ca_owner"]), "caOwner": ca["ca_owner"],
            "certs": unexpired, "allTimeCerts": all_time,
            "share": ca.get("market_share_pct", 0),
            "turnover": round(turnover, 1), "usageDays": usage_days,
            "trustedBy": tb, "storeCount": ca.get("trust_store_count", 0),
            "country": norm_country(ca.get("country", "")),
            "rootCount": ca.get("root_count", 0),
            "intermediateCount": ca.get("intermediates_count", 0),
            "webCoverage": round(web_cov, 1),
            "tls": ca.get("tls_capable", False), "ev": ca.get("ev_capable", False),
            "smime": ca.get("smime_capable", False), "codeSigning": ca.get("code_signing_capable", False),
            "ppm": ppm, "selfReportPct": self_pct, "incidentCount": inc_count,
            "matched": ca.get("matched", False), "inferred": ca.get("inferred", False),
            "parent": ca.get("parent_ca", ""),
            "note": ca.get("attribution_note", ca.get("note", "")),
            "issuanceCaveat": ca.get("issuance_caveat", ""),
            "crtshUrl": f"https://crt.sh/?CAName={_quote(ca['ca_owner'])}",
        })
    print(f"  Market: {len(market)} trusted CAs")

    # ═══════════════════════════════════════════════════════════════
    # Section 2: Concentration
    # ═══════════════════════════════════════════════════════════════
    shares = [ca["share"] for ca in market]
    hhi = round(sum(s ** 2 for s in shares))
    hhi_label = "highly concentrated" if hhi > 2500 else "moderately concentrated" if hhi > 1500 else "unconcentrated"
    total_certs_conc = sum(ca["certs"] for ca in market)
    cum_certs = 0
    head_count = len(market)
    for i, ca in enumerate(market):
        cum_certs += ca["certs"]
        if total_certs_conc > 0 and (cum_certs / total_certs_conc) * 100 >= 99.99:
            head_count = i + 1
            break
    head_pct = round(sum(shares[:head_count]), 4)
    concentration = {
        "hhi": hhi, "hhiLabel": hhi_label,
        "cr3": round(sum(shares[:3]), 2), "cr5": round(sum(shares[:5]), 2), "cr7": round(sum(shares[:7]), 2),
        "headCount": head_count, "headPct": head_pct,
        "tailCount": len(market) - head_count, "tailPct": round(100 - head_pct, 4),
    }

    # ═══════════════════════════════════════════════════════════════
    # Section 3: Trust Surface
    # ═══════════════════════════════════════════════════════════════
    trust_surface = {
        "totalRoots": intersections.get("total_included_roots", 0),
        "totalOwners": intersections.get("total_active_owners", 0),
        "allFourStores": {
            "roots": intersections.get("all_four_stores", {}).get("roots", 0),
            "owners": intersections.get("all_four_stores", {}).get("owners", 0),
        },
        "perStore": {s: {"roots": d.get("roots", 0), "owners": d.get("owners", 0)}
                     for s, d in intersections.get("per_store", {}).items()},
        "rootCombinations": [{"stores": c.get("stores", []), "count": c.get("root_count", 0)}
                             for c in intersections.get("root_combinations", [])],
        "ownerCombinations": [{"stores": c.get("stores", []), "count": c.get("owner_count", 0)}
                              for c in intersections.get("owner_combinations", [])],
        "capabilities": {
            cap: {"cas": len([ca for ca in market if ca.get(cap)]),
                  "pct": round(len([ca for ca in market if ca.get(cap)]) / max(len(market), 1) * 100)}
            for cap in ["tls", "ev", "smime", "codeSigning"]
        },
    }

    # ═══════════════════════════════════════════════════════════════
    # Section 4: Geography
    # ═══════════════════════════════════════════════════════════════
    geo = []
    for r in geography.get("regions", []):
        region_cas = [ca for ca in market if norm_country(ca["country"]) in
                      [norm_country(c["country"]) for c in r.get("countries", [])]]
        region_certs = sum(ca["certs"] for ca in region_cas)
        region_pct = round((region_certs / total_certs * 100), 2) if total_certs > 0 else 0
        countries = []
        for c in r.get("countries", []):
            cn = norm_country(c["country"])
            c_cas = [ca for ca in market if ca["country"] == cn]
            if not c_cas:
                continue
            c_certs = sum(ca["certs"] for ca in c_cas)
            countries.append({"country": cn, "caCount": len(c_cas),
                              "issuancePct": round((c_certs / total_certs * 100), 2) if total_certs > 0 else 0})
        if not countries:
            continue
        geo.append({"region": r["region"], "caCount": sum(c["caCount"] for c in countries),
                     "issuancePct": region_pct, "certs": region_certs, "countries": countries})

    # ═══════════════════════════════════════════════════════════════
    # Section 5: Government Risk
    # ═══════════════════════════════════════════════════════════════
    # Only include government-operated and state-owned enterprise types in the
    # government risk snapshot. classified_cas also contains commercial and
    # other types for the full detail view; issuancePct must reflect only
    # CAs with a structural government relationship.
    GOV_TYPES = {"government", "state_enterprise"}
    type_map = {"government": "government_operated", "state_enterprise": "state_owned_enterprise"}
    gov_cas = []
    for ca in gov_risk.get("classified_cas", []):
        if (ca.get("trust_store_count", 0) or 0) == 0:
            continue
        if ca.get("ca_owner", ca.get("ca", "")) in DISTRUST_OVERRIDES:
            continue
        if ca.get("type") not in GOV_TYPES:
            continue
        gov_cas.append({
            "caOwner": ca.get("ca_owner", ca.get("ca", "")),
            "crtshUrl": f"https://crt.sh/?CAName={_quote(ca.get('ca_owner', ca.get('ca', '')))}",
            "type": type_map.get(ca.get("type"), ca.get("type", "")),
            "country": norm_country(ca.get("jurisdiction", "")),
            "relationship": ca.get("state_influence", ca.get("info", "")),
            "storeCount": ca.get("trust_store_count", 0),
            "certs": ca.get("issued", ca.get("certs", 0)),
        })
    gov_certs = sum(c["certs"] for c in gov_cas)
    go_cas = [c for c in gov_cas if c["type"] == "government_operated"]
    se_cas = [c for c in gov_cas if c["type"] == "state_owned_enterprise"]
    government_risk = {
        "total": len(gov_cas),
        "issuancePct": round((gov_certs / total_certs * 100), 2) if total_certs > 0 else 0,
        "byType": {
            "governmentOperated": {"count": len(go_cas), "certs": sum(c["certs"] for c in go_cas),
                                    "pct": round(sum(c["certs"] for c in go_cas) / max(total_certs, 1) * 100, 2)},
            "stateOwnedEnterprise": {"count": len(se_cas), "certs": sum(c["certs"] for c in se_cas),
                                     "pct": round(sum(c["certs"] for c in se_cas) / max(total_certs, 1) * 100, 2)},
        },
        "cas": gov_cas,
    }

    # ═══════════════════════════════════════════════════════════════
    # Section 6: Jurisdiction Risk
    # ═══════════════════════════════════════════════════════════════
    jrs = []
    for j in jurisdiction_risk.get("jurisdictions", []):
        axes = j.get("axes", {})
        j_cas = [ca for ca in market if ca["country"] == norm_country(j["country"])]
        jrs.append({
            "country": j["country"], "risk": j.get("risk", "low"),
            "axes": {"keySeizure": axes.get("key_seizure", "general"),
                     "compelledIssuance": axes.get("compelled_issuance", "general"),
                     "secrecy": axes.get("secrecy", "none")},
            "summary": j.get("summary", ""),
            "laws": [{"name": l.get("name", ""), "section": l.get("section", ""), "excerpt": l.get("excerpt", "")}
                     for l in j.get("laws", [])],
            "caCount": len(j_cas),
            "exposedCerts": sum(ca["certs"] for ca in j_cas),
        })

    # ═══════════════════════════════════════════════════════════════
    # Section 7: Incidents (GAP 3 FIX: include yearsByClass, fingerprints, categories)
    # ═══════════════════════════════════════════════════════════════
    trusted_ids = set(ca["id"] for ca in market)
    per_ca = []
    for ca in incidents.get("cas", []):
        ca_id = slugify(ca.get("ca", ""))
        all_time = 0
        for m in market:
            if m["id"] == ca_id:
                all_time = m["allTimeCerts"]
                break
        ppm = round((ca["n"] / all_time) * 1e6, 3) if all_time > 0 and ca["n"] > 0 else None
        per_ca.append({
            "ca": ca["ca"], "id": ca_id, "count": ca["n"],
            "selfReported": ca.get("self", 0), "externallyReported": ca.get("ext", 0),
            "selfReportPct": ca.get("selfPct", 0), "ppm": ppm,
            "trusted": ca_id in trusted_ids,
        })

    # Classification totals from fingerprints
    cat_totals = {"misissuance": 0, "revocation": 0, "governance": 0, "validation": 0}
    for fp in incidents.get("fingerprints", []):
        cat_totals["misissuance"] += fp.get("mi", 0)
        cat_totals["revocation"] += fp.get("rv", 0)
        cat_totals["governance"] += fp.get("gv", 0)
        cat_totals["validation"] += fp.get("vl", 0)

    # yearsByClass: per-year category breakdown
    years_by_class = [
        {"year": y["y"], "misissuance": y.get("mi", 0), "revocation": y.get("rv", 0),
         "governance": y.get("gv", 0), "validation": y.get("vl", 0)}
        for y in incidents.get("yearsByClass", [])
    ]

    # Per-CA fingerprints: category breakdown per CA
    fingerprints = [
        {"ca": fp["ca"], "misissuance": fp.get("mi", 0), "revocation": fp.get("rv", 0),
         "governance": fp.get("gv", 0), "validation": fp.get("vl", 0)}
        for fp in incidents.get("fingerprints", [])
    ]

    incidents_out = {
        "total": incidents.get("total", 0),
        "caCount": incidents.get("ca_count", 0),
        "years": [{"year": y["y"], "count": y["n"]} for y in incidents.get("years", [])],
        "perCA": per_ca,
        "classification": cat_totals,
        "yearsByClass": years_by_class,
        "fingerprints": fingerprints,
        "categories": [{"category": c["cat"], "count": c["n"]} for c in incidents.get("categories", [])],
        "whiteboardTags": incidents.get("whiteboardTags", {}),
    }

    # ═══════════════════════════════════════════════════════════════
    # Section 8: BR Thresholds + per-CA validity readiness
    # ═══════════════════════════════════════════════════════════════
    br_thresholds = BR_VALIDITY

    # Per-CA BR validity readiness — only active TLS issuers
    # (matches the PolicyCompliance tab filter)
    br_readiness = []
    for ca in market_share:
        status = ca.get("br_status", "not_applicable")
        if status == "not_applicable":
            continue
        at = ca.get("all_precerts", 0)
        un = ca.get("unexpired_precerts", 0)
        use_days = round(365 / (at / un)) if at and un else 0
        br_readiness.append({
            "ca": ca.get("ca_owner", ""),
            "useDays": use_days,
            "status": status,
            "share": ca.get("market_share_pct", 0),
            "unexpiredCerts": un,
        })
    br_readiness.sort(key=lambda x: -x["useDays"])

    # ═══════════════════════════════════════════════════════════════
    # Section 9: Crypto + Root Algorithms (GAP 1 FIX: merge store/capability into rootAlgorithms)
    # ═══════════════════════════════════════════════════════════════
    ra_roots = root_algo.get("roots", [])
    trusted_owners = set(ca["caOwner"] for ca in market)
    trusted_roots = [r for r in ra_roots if r.get("ca_owner") in trusted_owners]

    key_families, key_sizes, sig_hashes = {}, {}, {}
    for r in trusted_roots:
        kf = r.get("key_family", "unknown")
        key_families[kf] = key_families.get(kf, 0) + 1
        ks = f'{kf}-{r.get("key_bits", "?")}'
        if kf == "ECC" and r.get("curve"):
            ks = r["curve"]
        key_sizes[ks] = key_sizes.get(ks, 0) + 1
        sh = r.get("sig_hash", "unknown")
        sig_hashes[sh] = sig_hashes.get(sh, 0) + 1

    crypto_summary = {
        "totalRoots": len(trusted_roots), "caCount": len(trusted_owners),
        "keyFamilies": key_families,
        "keySizes": dict(sorted(key_sizes.items(), key=lambda x: -x[1])),
        "sigHashes": dict(sorted(sig_hashes.items(), key=lambda x: -x[1])),
    }

    # Root algorithm summary + per-CA breakdown + lookup URLs
    # Full 317-root per-cert list omitted (~29k tokens) — available via crt.sh URLs
    from collections import Counter as _Counter
    _ra_families = _Counter(r.get("key_family","") for r in trusted_roots)
    _ra_bits     = _Counter(r.get("key_bits", 0)   for r in trusted_roots)
    _ra_hashes   = _Counter(r.get("sig_hash","")   for r in trusted_roots)

    # Per-CA root crypto breakdown (96 CA owners, not 317 individual roots)
    _by_ca = {}
    for r in trusted_roots:
        owner = r.get("ca_owner", "")
        if owner not in _by_ca:
            _by_ca[owner] = {"rsa": 0, "ecc": 0, "roots": 0,
                             "crtshUrl": f"https://crt.sh/?CAName={_quote(owner)}"}
        _by_ca[owner]["roots"] += 1
        if r.get("key_family","") == "RSA":
            _by_ca[owner]["rsa"] += 1
        else:
            _by_ca[owner]["ecc"] += 1

    root_algorithms = {
        "totalRoots":  len(trusted_roots),
        "byKeyFamily": dict(sorted(_ra_families.items(), key=lambda x: -x[1])),
        "byKeyBits":   dict(sorted(_ra_bits.items(),    key=lambda x: -x[1])),
        "bySigHash":   dict(sorted(_ra_hashes.items(),  key=lambda x: -x[1])),
        "tlsCapable":  sum(1 for r in trusted_roots if r.get("tls")),
        "evCapable":   sum(1 for r in trusted_roots if r.get("ev")),
        "sha1Roots":   sum(1 for r in trusted_roots if r.get("sig_hash","") == "SHA-1"),
        "perCA": sorted(_by_ca.values(), key=lambda x: -x["roots"]),
        "lookupUrl": "https://crt.sh/?CAName={caOwner}",
        "note": "Summary view. Full per-root detail in llm_snapshot_risk.json.",
    }

    # Full per-root list — used only in the risk slice, not the main snapshot
    root_algorithms_full = [
        {
            "name": r.get("name", ""), "caOwner": r.get("ca_owner", ""),
            "sha256": r.get("sha256", ""),
            "keyFamily": r.get("key_family", ""), "keyBits": r.get("key_bits", 0),
            "sigHash": r.get("sig_hash", ""), "curve": r.get("curve"),
            "stores": r.get("stores", ""),
            "validFrom": r.get("not_before", r.get("valid_from", "")),
            "validTo": r.get("not_after", r.get("valid_to", "")),
            "tls": r.get("tls", False), "ev": r.get("ev", False),
            "smime": r.get("smime", False), "codeSigning": r.get("cs", False),
            "crtshUrl": f"https://crt.sh/?q={r.get('sha256', '')}",
        }
        for r in trusted_roots
    ]

    # ═══════════════════════════════════════════════════════════════
    # Section 10: Distrust (GAP 4 FIX: include timelines and references)
    # ═══════════════════════════════════════════════════════════════
    distrust_events = []
    for e in distrust.get("events", []):
        ca_owner = e.get("ca_owner", e["ca"])
        event = {
            "ca": e["ca"], "caOwner": ca_owner,
            "crtshUrl": f"https://crt.sh/?CAName={_quote(ca_owner)}",
            "year": e["year"], "country": e.get("country", ""),
            "compliancePosture": e["compliance_posture"],
            "distrustPathway": e.get("distrust_pathway", ""),
            "responseQuality": e.get("response_quality", ""),
            "reasonTags": e.get("reason_tags", []),
            "summary": e.get("summary", ""),
            "distrustDates": e.get("distrust_dates", {}),
            "classificationTier": e.get("classification_tier", "medium"),
            "postureEvidence": e.get("posture_evidence", ""),
            "tagEvidence": e.get("tag_evidence", {}),
        }
        # Timeline (gap 4)
        tl = e.get("timeline", {})
        if tl:
            event["timeline"] = {
                "firstBugDate": tl.get("first_bug_date"),
                "lastBugDate": tl.get("last_bug_date"),
                "distrustDate": tl.get("distrust_date"),
                "runwayDays": tl.get("runway_days"),
            }
        # References (gap 4)
        refs = e.get("references", {})
        if refs:
            event["references"] = {
                "rootProgramAnnouncements": refs.get("root_program_announcements", []),
                "mdspThreads": refs.get("mdsp_threads", []),
                "ccadbThreads": refs.get("ccadb_threads", []),
                "articles": [{"url": a.get("url", ""), "source": a.get("source", ""), "title": a.get("title", "")}
                             for a in refs.get("articles", [])] if isinstance(refs.get("articles"), list) else [],
            }
        distrust_events.append(event)

    posture_dist = Counter(e["compliancePosture"] for e in distrust_events)
    # Pull pre-computed stats from raw distrust file (avg interval, runway, response %)
    _raw_stats = distrust.get("stats", {})
    distrust_stats = {
        "totalEvents":        len(distrust_events),
        "postureDistribution": dict(posture_dist),
        "avgIntervalYears":   _raw_stats.get("avg_interval_years"),
        "avgIntervalMonths":  round(_raw_stats["avg_interval_years"] * 12) if _raw_stats.get("avg_interval_years") else None,
        "medianRunwayDays":   _raw_stats.get("median_runway_days"),
        "maxRunwayDays":      _raw_stats.get("max_runway_days"),
        "avgRunwayDays":      _raw_stats.get("avg_runway_days"),
        "responseDrivenPct":  _raw_stats.get("response_driven_pct"),
    }

    # ═══════════════════════════════════════════════════════════════
    # Section 11: Governance (GAP 2 FIX: include full RPE data)
    # ═══════════════════════════════════════════════════════════════
    report_card = {}
    for prog in ["chrome", "mozilla", "apple", "microsoft"]:
        e = (rpe.get("enforcement") or {}).get(prog, {})
        c = (rpe.get("program_comment_summary") or {}).get(prog, {})
        p = (rpe.get("policy_leadership") or {}).get("programs", {}).get(prog, {})
        sp = (rpe.get("store_posture") or {}).get(prog, {})
        bc = (rpe.get("ballot_classification") or {}).get("browser_summary", {}).get(prog, {})
        report_card[prog] = {
            "enforcement": f"{e.get('acted', 0)}/{e.get('total', 0)}",
            "firstPublicAction": e.get("initiated", 0),
            "neverActed": (e.get("total", 0)) - (e.get("acted", 0)),
            "stillTrusts": len(e.get("still_trusts", [])),
            "bugzillaCoverage": c.get("bugs_oversight", 0),
            "bugzillaCoverageRecent": c.get("recent_bugs_oversight", 0),
            "substantiveOversight": c.get("bugs_technical_oversight", 0),
            "substantiveOversightRecent": c.get("recent_bugs_technical_oversight", 0),
            "oversightComments": c.get("oversight_comments", 0),
            "ballotsProposed": p.get("proposed", 0),
            "voteParticipation": f"{p.get('voted', 0)}/{p.get('ballots_with_votes', 0)}",
            "substantiveBallots": bc.get("substantive", 0),
            "caOwners": sp.get("owners", 0),
            "roots": sp.get("roots", 0),
            "exclusiveRoots": sp.get("exclusive_count", 0),
            "ungoverned_exclusive": (sp.get("dark_matter") or {}).get("exclusive_zero_incident", 0),
        }

    governance = {
        "reportCard": report_card,
        "meta": {
            "bugsTotal": (rpe.get("meta") or {}).get("bugs_total", 0),
            "bugsWithComments": (rpe.get("meta") or {}).get("bugs_with_comments", 0),
            "totalCommentsAnalyzed": (rpe.get("meta") or {}).get("total_comments_analyzed", 0),
        },
        # Bug creation (who files bugs)
        "bugCreationByYear": [
            {"y": y.get("y"), "chrome": y.get("chrome", 0), "mozilla": y.get("mozilla", 0),
             "apple": y.get("apple", 0), "microsoft": y.get("microsoft", 0), "other": y.get("other", 0)}
            for y in rpe.get("bug_creation_by_year", [])
        ],
        "bugCreationTotals": rpe.get("bug_creation_totals", {}),
        # Discovery methods
        "discoveryMethods": rpe.get("discovery_methods", {}),
        # Oversight
        "programCommentSummary": rpe.get("program_comment_summary", {}),
        "oversightConcentration": {
            prog: {k: v for k, v in data.items() if k != "contributors"}
            for prog, data in rpe.get("oversight_concentration", {}).items()
        },
        "oversightQuarterly": rpe.get("oversight_quarterly", []),
        # Enforcement detail
        "enforcement": rpe.get("enforcement", {}),
        "distrustEvents": rpe.get("distrust_events", []),
        # Store posture
        "storePosture": rpe.get("store_posture", {}),
        # Policy leadership
        "policyLeadership": rpe.get("policy_leadership", {}),
        # Ballot classification (Who Shapes Policy)
        "ballotClassification": rpe.get("ballot_classification", {}),
        # Notable gaps
        "notableGaps": rpe.get("notable_gaps", {}),
        # Inclusion velocity
        "inclusionVelocity": rpe.get("inclusion_velocity", {}),
        "coverageRateByYear": rpe.get("coverage_rate_by_year", []),
    }

    # ── Community / Ecosystem Participation ──
    orgs = community.get("organizations", {})
    inds = community.get("individuals", {})
    bal_inds = community.get("ballot_individuals", {})
    cabf_members = [o for o, d in orgs.items() if d.get("cabf_member")]
    active_members = [o for o in cabf_members
                      if (orgs[o].get("bugzilla") or {}).get("bugs_engaged", 0) > 0
                      or (orgs[o].get("ballots") or {}).get("proposed", 0) > 0
                      or (orgs[o].get("ballots") or {}).get("endorsed", 0) > 0
                      or (orgs[o].get("bug_filing") or {}).get("bugs_filed", 0) > 0]
    community_out = {
        "meta": community.get("meta", {}),
        "cabfMemberCount": len(cabf_members),
        "activeMemberCount": len(active_members),
        "zeroContributionCount": len(cabf_members) - len(active_members),
        "topOrganizations": sorted(
            [{"name": o,
              "cabfMember": d.get("cabf_member", False),
              "bugzillaEngaged": (d.get("bugzilla") or {}).get("bugs_engaged", 0),
              "ballotsProposed": (d.get("ballots") or {}).get("proposed", 0),
              "ballotsEndorsed": (d.get("ballots") or {}).get("endorsed", 0),
              "bugsFiled": (d.get("bug_filing") or {}).get("bugs_filed", 0)}
             for o, d in orgs.items() if
             (d.get("bugzilla") or {}).get("bugs_engaged", 0) + (d.get("ballots") or {}).get("proposed", 0) + (d.get("bug_filing") or {}).get("bugs_filed", 0) > 0],
            key=lambda x: -(x["bugzillaEngaged"] * 2 + x["ballotsProposed"] * 3 + x["ballotsEndorsed"] + x["bugsFiled"] * 3)
        )[:20],
        "topBallotIndividuals": sorted(
            [{"name": n, "proposed": (v or {}).get("proposed", 0), "endorsed": (v or {}).get("endorsed", 0)}
             for n, v in bal_inds.items() if (v or {}).get("proposed", 0) + (v or {}).get("endorsed", 0) > 0],
            key=lambda x: -(x["proposed"] * 3 + x["endorsed"])
        )[:15],
        "individualCount": len(inds),
    }

    # ── Chrome Root Store Growth ──
    chrome_growth = {
        "source": "chromium/src/net/data/ssl/chrome_root_store commit history",
        "entries": [
            {"date": e["date"], "totalRoots": e["total_after"],
             "added": e["added_count"], "removed": e["removed_count"]}
            for e in chrome_cl.get("changelog", [])
        ],
    }

    # ── Regulatory Surface (compliance obligation growth) ──
    regulatory_surface = {}
    if compliance_growth:
        cg_ts = compliance_growth.get("time_series", [])
        cg_latest = cg_ts[-1] if cg_ts else {}
        cg_first  = next((r for r in cg_ts if r.get("totals", {}).get("total", 0) > 0), {})

        def _grp(row, *keys):
            return sum(
                row.get("by_source", {}).get(k, {}).get("mandatory", 0) +
                row.get("by_source", {}).get(k, {}).get("recommended", 0) +
                row.get("by_source", {}).get(k, {}).get("optional", 0)
                for k in keys
            )

        total_2026   = cg_latest.get("totals", {}).get("total", 0)
        total_first  = cg_first.get("totals", {}).get("total", 1)
        mandatory    = cg_latest.get("totals", {}).get("mandatory", 0)
        recommended  = cg_latest.get("totals", {}).get("recommended", 0)
        optional_    = cg_latest.get("totals", {}).get("optional", 0)

        rev_hist = compliance_growth.get("revision_history", {})
        total_ballots = sum(len(v) for v in rev_hist.values())
        recent_ballots = sum(
            len([b for b in v if b.get("date", "") >= "2022-01-01"])
            for v in rev_hist.values()
        )

        # Year-by-year totals (compact — just year and total)
        time_series_compact = [
            {"y": r["year"], "t": r["totals"]["total"],
             "m": r["totals"]["mandatory"]}
            for r in cg_ts
        ]

        regulatory_surface = {
            "currentYear":      cg_latest.get("year"),
            "totalObligations": total_2026,
            "mandatory":        mandatory,
            "recommended":      recommended,
            "optional":         optional_,
            "mandatoryPct":     round(mandatory / total_2026 * 100) if total_2026 else 0,
            "baselineYear":     cg_first.get("year"),
            "baselineTotal":    total_first,
            "growthMultiple":   round(total_2026 / total_first) if total_first else 0,
            "sourceTotals": {
                "cabfForum":    _grp(cg_latest, "tls_br_op", "tls_br_prof", "ev_g_op", "ev_g_prof",
                                     "ns_reqs", "ns_reqs_op", "smime_br_op", "smime_br_prof",
                                     "cs_br_op", "cs_br_prof"),
                "rootPrograms": _grp(cg_latest, "mozilla_mrsp", "chrome_root", "apple_root"),
                "auditIetf":    _grp(cg_latest, "webtrust", "etsi_stack", "rfc_pkix",
                                     "rfc_ct", "rfc_caa", "rfc_acme"),
                "regulatory":   _grp(cg_latest, "nist", "nis2"),
            },
            "tlsBr": {
                "v1_0_total":   278,
                "current_total": _grp(cg_latest, "tls_br_op", "tls_br_prof"),
                "operational":   _grp(cg_latest, "tls_br_op"),
                "profileSpec":   _grp(cg_latest, "tls_br_prof"),
            },
            "ballots": {
                "total":        total_ballots,
                "since2022":    recent_ballots,
                "byDoc": {doc: len(entries) for doc, entries in rev_hist.items()},
            },
            "timeSeries": time_series_compact,
            "methodology": compliance_growth.get("methodology", {}).get("counting_method", ""),
        }

    # ── Tab Intros (analyst notes generated by LLM from prior run) ──
    tab_intros_data = load_json(DATA_DIR, "tab_intros.json") or {}
    tab_intros_out = {
        "generatedAt": tab_intros_data.get("generatedAt"),
        "model": tab_intros_data.get("model"),
        "note": "Analyst summaries generated by Claude from the prior day's snapshot. Each paragraph states the key finding for that tab with specific numbers and connects to related tabs.",
        "intros": tab_intros_data.get("intros", {}),
    }

    # ═══════════════════════════════════════════════════════════════
    # Assemble
    # ═══════════════════════════════════════════════════════════════
    snapshot = {
        "$schema": SCHEMA_URL,
        "version": SCHEMA_VERSION,
        "generatedAt": now.isoformat(),
        "snapshotUrl": SNAPSHOT_URL,
        "slices": {
            "index":      "https://webpki.systematicreasoning.com/llm_snapshot_index.json",
            "governance": "https://webpki.systematicreasoning.com/llm_snapshot_governance.json",
            "distrust":   "https://webpki.systematicreasoning.com/llm_snapshot_distrust.json",
            "market":     "https://webpki.systematicreasoning.com/llm_snapshot_market.json",
            "risk":       "https://webpki.systematicreasoning.com/llm_snapshot_risk.json",
        },
        "sliceGuide": "This snapshot is ~50k tokens. For targeted analysis fetch a slice: "
                      "governance (CA/Browser Forum oversight, compliance, BR readiness, audit letter quality), "
                      "distrust (16 distrust events 2011-2024 + incidents), "
                      "market (CA market share, trust surface), "
                      "risk (geographic, government, jurisdiction, full 317-root crypto data). "
                      "Each slice is self-contained with generatedAt and snapshotUrl.",
        "dataSources": {
            "crtSh": "Certificate Transparency logs via crt.sh — unexpired and all-time precertificate counts per CA owner. Updated daily.",
            "ccadb": "Common CA Database (AllCertificateRecordsCSVFormatv4) — root/intermediate metadata, trust store inclusion, CA owner details. Updated daily.",
            "bugzilla": "Mozilla Bugzilla CA Certificate Compliance — incident reports, root program comments, CA responses. 2014-present. Updated daily.",
            "statcounter": "StatCounter global browser market share — mapped to root programs for web coverage estimates. Updated daily.",
            "cabforum": "CA/Browser Forum ballot records — proposers, endorsers, vote results across Server Certificate, Code Signing, S/MIME, and Network Security working groups.",
            "keylength": "keylength.com — cryptographic key size recommendations from NIST, ECRYPT-CSA, BSI, ANSSI, and NSA CNSA.",
            "cabforumMembers": "CA/B Forum membership roster — CA members, browser members, interested parties. Used for ecosystem participation baseline.",
            "chromeRootStore": "Chrome Root Store git commit history — root additions and removals with timestamps.",
            "tabIntros": "Analyst summaries generated daily by Claude Sonnet from the prior day's data digest. Each intro states the key finding for that tab with specific numbers and connects related tabs.",
            "regulatorySurface": "Normative obligation counts across all CA compliance documents — CA/Browser Forum BRs (PDF archive 2012-2021 + GitHub tags 2021-present), root program policies, IETF RFCs (operative versions), NIS2 Directive (EUR-Lex), NIST SP 800-53 Rev 5 (OSCAL). Four convention-aware parsers: RFC2119_INLINE, SHALL_LETTERED_LIST, EU_LEGAL, NIST_OSCAL. Ballot timeline from document revision history tables.",
        },
        "browserCoverage": browser_coverage,
        "market": market,
        "concentration": concentration,
        "trustSurface": trust_surface,
        "chromeRootStoreGrowth": chrome_growth,
        "geography": geo,
        "governmentRisk": government_risk,
        "jurisdictionRisk": jrs,
        "incidents": incidents_out,
        "brThresholds": br_thresholds,
        "brReadiness": {
            "cas": br_readiness,
            "totalActiveTls": len(br_readiness),
            "subscriberRisk200d": sum(1 for c in br_readiness if c["useDays"] > 200),
            "subscriberRisk100d":  sum(1 for c in br_readiness if 100 < c["useDays"] <= 200),
            "ready47d":            sum(1 for c in br_readiness if c["useDays"] < 47),
            "medianUseDays":       sorted([c["useDays"] for c in br_readiness])[len(br_readiness)//2] if br_readiness else None,
        },
        "cryptoSummary": crypto_summary,
        "rootAlgorithms": root_algorithms,
        "distrustEvents": distrust_events,
        "distrustStats": distrust_stats,
        "governance": governance,
        "ecosystemParticipation": community_out,
        "regulatorySurface": regulatory_surface,
        "tabIntros": tab_intros_out,
        "auditIntelligence": _build_audit_snapshot(audits_data),
        "crlInfrastructureHealth": _build_crl_health_snapshot(crl_health),
    }

    # ── Write ──
    stable_path = os.path.join(DATA_DIR, "llm_snapshot.json")
    dated_path = os.path.join(DATA_DIR, f"llm_snapshot_{today}.json")

    with open(stable_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, separators=(",", ":"))
    size = os.path.getsize(stable_path)
    tokens = size // 4
    print(f"  Wrote {stable_path} ({size:,} bytes, ~{tokens:,} tokens)")

    with open(dated_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, separators=(",", ":"))
    print(f"  Wrote {dated_path}")

    # Export sliced JSON files for LLMs with limited context windows
    print("  Exporting slices...")
    export_slices(snapshot, Path(DATA_DIR), root_algorithms_full)

    # ── Validate ──
    assert len(market) > 0, "No trusted CAs"
    assert abs(sum(ca["share"] for ca in market) - 100) < 0.1, "Market shares don't sum to 100%"
    assert len(distrust_events) > 0, "No distrust events"
    assert distrust_stats["totalEvents"] == len(distrust_events), "Stats/events mismatch"
    assert root_algorithms.get("totalRoots", 0) > 0, "No root algorithms"
    if len(incidents_out.get("yearsByClass", [])) == 0:
        print("  WARNING: No yearsByClass data — classification cache cold. Snapshot will be incomplete.", file=sys.stderr)
    if len(incidents_out.get("fingerprints", [])) == 0:
        print("  WARNING: No fingerprint data — classification cache cold.", file=sys.stderr)
    assert len(governance.get("oversightQuarterly", [])) > 0, "No quarterly oversight data"
    assert len(governance.get("bugCreationByYear", [])) > 0, "No bug creation data"
    print(f"  Validation passed: {len(market)} CAs, {len(distrust_events)} distrust events, "
          f"{incidents_out['total']} incidents, {len(root_algorithms)} roots, "
          f"{len(governance['oversightQuarterly'])} quarterly oversight periods")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"ERROR: export_llm_snapshot.py failed: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
# ══════════════════════════════════════════════════════════════════
