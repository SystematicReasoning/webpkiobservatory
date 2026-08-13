#!/usr/bin/env python3
"""
Generate analyst-quality TabIntro text for each Observatory tab using Claude.

Reads the LLM snapshot, extracts a concise data digest, and calls the
Anthropic API to produce one paragraph per tab that:
  - States the key finding from this tab's data with specific numbers
  - Connects it to related tabs (where relevant)
  - Uses plain declarative sentences — no hype, no hedging

Output: data/tab_intros.json
Fallback: if generation fails, existing static text is used unchanged.

Run: python pipeline/fetch_tab_intros.py
CI: runs daily after export_llm_snapshot.py
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from utils import ANTHROPIC_URL, ANTHROPIC_VERSION

DATA_DIR   = os.environ.get("PIPELINE_DATA_DIR", "data")
SCRIPT_DIR = Path(__file__).parent
NOW        = datetime.now(timezone.utc)

# ── Model ──
MODEL = "claude-sonnet-4-5"

# ── Tab definitions (id, label, focus) ──
TABS = [
    ("market",      "Market Share",           "CA issuance volume, concentration, web coverage per CA"),
    ("trust",       "Trust Surface",          "335 total roots across 4 stores, 38 CA owners in all 4 stores, 90 roots in all 4 stores. 142 roots are Microsoft-only (not in Chrome/Mozilla/Apple). Per-store root and owner counts. Combination matrix showing which root combinations exist across stores. Store disagreements create operational complexity — a chain trusted in one browser may fail in another. Focus on the disagreement and concentration story, not Chrome growth."),
    ("conc",        "Concentration Risk",     "HHI, top-N share, systemic dependency"),
    ("tail",        "Long Tail Risk",         "Low-volume CAs with full trust store inclusion"),
    ("geo",         "Geographic Risk",        "Where CAs are incorporated by region and country, issuance share per region, US vs Europe vs Asia-Pacific concentration — NOT legal frameworks (that is the Jurisdiction Risk tab)"),
    ("gov",         "Government Risk",        "State-operated and state-owned CAs, trust store presence"),
    ("jurisdiction","Jurisdiction Risk",      "Legal frameworks, compelled disclosure risk by country"),
    ("ops",         "Operational Risk",       "Incident rates, self-detection, policy/disclosure failures"),
    ("crypto",      "Cryptographic Posture",  "Root algorithms, key sizes, standards compliance"),
    ("distrust",    "Distrust History",       "All browser distrust events, posture, compliance patterns"),
    ("policy",      "BR Readiness",          "Two sections: (1) Per-CA certificate validity readiness — 43 active TLS issuers measured by actual replacement behavior vs SC-081 thresholds of 200d (Mar 2026), 100d (Mar 2027), 47d (Mar 2029). Use the brReadiness numbers. (2) Compliance Complexity — the regulatory surface CAs must navigate, grown 52x since 2005 to ~2600 obligations across CA/B Forum BRs, root programs, IETF, WebTrust/ETSI, ISO/NIST. Use the regulatorySurface numbers. Write one paragraph covering both sections as a connected story: readiness is hard partly because the compliance surface keeps expanding."),
    ("governance",  "Governance Risk",        "Root program oversight coverage, declining rates, Microsoft"),
    ("community",   "Ecosystem Participation","CABF member activity, ballot leadership, silent majority"),
    ("audit",       "Audit Intelligence",     "Audit letter quality vs Bugzilla incident history. Use the auditIntelligence numbers from the digest: inPeriodDetectionRate (the % of in-scope incidents auditors caught in their letters), highTransparencyGap, qualifiedOpinions, etsiV35Count, changesIn2025, wtSelfReportPct, etsiSelfReportPct. Lead with the surveillance gap finding — clean audit letters coexist with real incident histories. Do not use a hardcoded percentage; use the actual inPeriodDetectionRate from the digest."),
]


def build_digest(snap: dict) -> dict:
    """Extract a concise data digest from the snapshot for the prompt."""
    m = snap.get("market", [])
    dm_totals = snap["governance"]["discoveryMethods"]["totals"]
    grand = sum(dm_totals.values()) or 1
    cov = snap["governance"]["coverageRateByYear"]
    ep = snap["ecosystemParticipation"]
    inc = snap["incidents"]
    wb = inc.get("whiteboardTags", {})
    cats = inc.get("categories", [])
    dist_events = snap.get("distrustEvents", [])
    dist_stats  = snap.get("distrustStats", {})
    conc = snap.get("concentration", {})

    OPS_TAGS = {
        "inadequate_incident_response", "pattern_of_issues",
        "lack_of_meaningful_improvement", "non_responsive_to_root_programs",
        "minimized_severity", "active_deception", "hidden_corporate_changes",
        "concealed_breach_or_incident", "delayed_or_refused_revocation",
    }
    pattern_count = sum(
        1 for e in dist_events
        if "pattern_of_issues" in (e.get("reasonTags") or e.get("reason_tags") or [])
    )
    ops_count = sum(
        1 for e in dist_events
        if any(t in (e.get("reasonTags") or e.get("reason_tags") or []) for t in OPS_TAGS)
    )

    pms = snap["governance"]["programCommentSummary"]

    return {
        "generatedAt": NOW.isoformat(),
        "market": {
            "top5": [
                {"ca": c["caOwner"], "sharePct": round(c["share"], 1)}
                for c in m[:5]
            ],
            "cr3Pct": conc.get("cr3"),
            "cr5Pct": conc.get("cr5"),
            "hhi": conc.get("hhi"),
            "totalTrustedCAs": len(m),
            "tailCAs": sum(1 for c in m if c.get("share", 0) < 0.01),
        },
        "incidents": {
            "total": inc["total"],
            "caCount": inc["caCount"],
            "categories": cats,
            "policyFailure": wb.get("policy-failure", 0),
            "disclosureFailure": wb.get("disclosure-failure", 0),
            "auditFinding": wb.get("audit-finding", 0),
        },
        "discovery": {
            "selfPct": round(dm_totals["self_detected"] / grand * 100),
            "rootProgramPct": round(dm_totals["root_program"] / grand * 100),
            "automatedToolsPct": round(dm_totals["community"] / grand * 100),
            "externalResearcherPct": round(dm_totals["external_researcher"] / grand * 100),
            "auditPct": round(dm_totals["audit"] / grand * 100),
        },
        "distrust": {
            "totalEvents": dist_stats.get("totalEvents", len(dist_events)),
            "patternOfIssuesCount": pattern_count,
            "complianceOpsFailureCount": ops_count,
            "postureDistribution": dist_stats.get("postureDistribution", {}),
            "medianRunwayDays": dist_stats.get("medianRunwayDays"),
        },
        "governance": {
            "coverageRateLatestFullYear": cov[-2] if len(cov) >= 2 else cov[-1] if cov else None,
            "coverageRate2019": next((y for y in cov if y["y"] == 2019), None),
            "programCommentSummary": {
                prog: {
                    "bugsOversight": pms[prog]["bugs_oversight"],
                    "bugsSubstantive": pms[prog]["bugs_technical_oversight"],
                    "recentSubstantive": pms[prog]["recent_bugs_technical_oversight"],
                }
                for prog in ["chrome", "mozilla", "apple", "microsoft"]
                if prog in pms
            },
            "bugCorpusTotal": snap["governance"]["meta"]["bugsTotal"],
        },
        "ecosystem": {
            "cabfMemberCount": ep["cabfMemberCount"],
            "activeMemberCount": ep["activeMemberCount"],
            "zeroContributionCount": ep["zeroContributionCount"],
            "topOrg": ep["topOrganizations"][0]["name"] if ep.get("topOrganizations") else None,
            "topBallotIndividual": ep["topBallotIndividuals"][0] if ep.get("topBallotIndividuals") else None,
        },
        "geography": {
            "regions": [
                {"region": r["region"], "caCount": r["caCount"], "issuancePct": r["issuancePct"]}
                for r in snap.get("geography", [])
            ],
            "topCountry": snap.get("geography", [{}])[0].get("region") if snap.get("geography") else None,
            "topCountryPct": snap.get("geography", [{}])[0].get("issuancePct") if snap.get("geography") else None,
        },
        "government": {
            "govCAs": snap["governmentRisk"]["total"],
            "issuancePct": snap["governmentRisk"]["issuancePct"],
        },
        "jurisdiction": {
            "highRisk": [j["country"] for j in snap.get("jurisdictionRisk", []) if j.get("risk") == "high"],
            "moderateRisk": [j["country"] for j in snap.get("jurisdictionRisk", []) if j.get("risk") == "moderate"],
        },
        "chromeGrowth": {
            "from": snap["chromeRootStoreGrowth"]["entries"][0]["totalRoots"] if snap.get("chromeRootStoreGrowth", {}).get("entries") else None,
            "to": snap["chromeRootStoreGrowth"]["entries"][-1]["totalRoots"] if snap.get("chromeRootStoreGrowth", {}).get("entries") else None,
            "fromDate": snap["chromeRootStoreGrowth"]["entries"][0]["date"] if snap.get("chromeRootStoreGrowth", {}).get("entries") else None,
        },
        "browser": snap["browserCoverage"],
        "brReadiness": {
            "totalActiveTls": snap.get("brReadiness", {}).get("totalActiveTls", 0),
            "atRisk200d": snap.get("brReadiness", {}).get("subscriberRisk200d", 0),
            "atRisk100d": snap.get("brReadiness", {}).get("subscriberRisk100d", 0),
            "ready47d": snap.get("brReadiness", {}).get("ready47d", 0),
            "medianUseDays": snap.get("brReadiness", {}).get("medianUseDays"),
        },
        "regulatorySurface": {
            "totalObligations": snap.get("regulatorySurface", {}).get("totalObligations", 0),
            "growthMultiple": snap.get("regulatorySurface", {}).get("growthMultiple", 0),
            "baselineYear": snap.get("regulatorySurface", {}).get("baselineYear"),
            "mandatory": snap.get("regulatorySurface", {}).get("mandatory", 0),
            "mandatoryPct": snap.get("regulatorySurface", {}).get("mandatoryPct", 0),
            "ballotsSince2022": snap.get("regulatorySurface", {}).get("ballots", {}).get("since2022", 0),
        },
        "auditIntelligence": _build_audit_digest(),
    }


def _build_audit_digest() -> dict:
    """Extract key numbers from audits.json for the tab intro prompt."""
    audits_path = Path(DATA_DIR) / "audits.json"
    if not audits_path.exists():
        return {}
    try:
        data = json.loads(audits_path.read_text())
        s = data.get("summary", {})
        profiles = data.get("profiles", [])
        agg = data.get("auditor_aggregates", {})
        parsed = [p for p in profiles if p.get("pdf_parsed")]

        # Self-report by framework
        wt_self = [p["self_report_pct"] for p in profiles
                   if p.get("primary_framework") == "WebTrust"
                   and p.get("self_report_pct") is not None]
        etsi_self = [p["self_report_pct"] for p in profiles
                     if p.get("primary_framework") == "ETSI"
                     and p.get("self_report_pct") is not None]
        wt_avg  = round(sum(wt_self) / len(wt_self), 1) if wt_self else None
        etsi_avg = round(sum(etsi_self) / len(etsi_self), 1) if etsi_self else None

        # Auditor changes in 2025
        changes_2025 = sum(
            1 for p in profiles
            for c in (p.get("timeline_trends") or {}).get("auditor_changes", [])
            if c.get("year", 0) == 2025
        )

        # ETSI AAL V3.5 adoption
        etsi_parsed = [p for p in parsed if p.get("primary_framework") == "ETSI"]
        v35_count = sum(1 for p in etsi_parsed
                        if (p.get("criteria_check") or {}).get("aal_version") == "3.5")

        # Top auditors by CA count
        top_auditors = [
            {"name": name, "caCount": a["ca_count"],
             "avgQuality": a.get("avg_quality_score"),
             "avgGap": a.get("avg_gap_score")}
            for name, a in list(agg.items())[:5]
        ]

        # In-period detection rate — compute live from profiles rather than
        # reading from summary, since audits.json may be from the current run
        # (summary written after this function runs) or a previous run.
        ip_covered = ip_caught = 0
        for prof in profiles:
            for r in (prof.get("bug_retrospective") or []):
                if r.get("covering_letters", 0) > 0:
                    ip_covered += 1
                    if r.get("mentioned_in", 0) > 0:
                        ip_caught += 1
        ip_det_rate = round(ip_caught / ip_covered * 100) if ip_covered else None

        return {
            "totalCAs":              s.get("total_ca_owners"),
            "parsedLetters":         s.get("pdf_parsed_count"),
            "highTransparencyGap":   s.get("high_transparency_gap"),
            "qualifiedOpinions":     s.get("qualified_opinions"),
            "auditorHHI":            s.get("auditor_hhi"),
            "changesIn2025":         changes_2025,
            "etsiV35Count":          v35_count,
            "etsiParsed":            len(etsi_parsed),
            "wtSelfReportPct":       wt_avg,
            "etsiSelfReportPct":     etsi_avg,
            "topAuditors":           top_auditors,
            "inPeriodDetectionRate": ip_det_rate,
            "inPeriodCaught":        ip_caught,
            "inPeriodCovered":       ip_covered,
        }
    except Exception as e:
        return {"error": str(e)}


def build_prompt(digest: dict) -> str:
    tab_list = "\n".join(f"  {i+1}. {label} ({focus})" for i, (_, label, focus) in enumerate(TABS))
    return f"""You are writing analyst notes for the WebPKI Observatory, a public dashboard that measures trust, risk, and governance in the internet's certificate infrastructure. The site has 13 tabs that tell a connected story about who issues certificates, where the risks are, and how well the system is governed.

Here is the current data digest:
{json.dumps(digest, indent=2)}

Write one paragraph for each of these 14 tabs:
{tab_list}

Requirements for each paragraph:
- 2-4 sentences, plain declarative prose
- Lead with the most important finding from that tab's data, using specific numbers from the digest
- Where natural, connect to another tab's data — show how this tab's finding relates to what comes before or after
- No hype, no hedging, no "this tab shows" framing — write as if briefing a PKI professional
- Do not mention ForgeIQ, any vendor, or any commercial product
- Do not use em dashes or colons as section labels
- Write in present tense

Return a JSON object with keys matching these tab IDs exactly:
{json.dumps([tab_id for tab_id, _, _ in TABS])}

Each value is the paragraph string. Return only the JSON object, no markdown fences."""


def call_api(prompt: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    payload = json.dumps({
        "model": MODEL,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP Error {e.code}: {e.reason}") from e

    text = body["content"][0]["text"].strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()

    return json.loads(text)


def main():
    print(f"fetch_tab_intros.py — {NOW.isoformat()[:19]}")

    snap_path = Path(DATA_DIR) / "llm_snapshot.json"
    if not snap_path.exists():
        print(f"  WARNING: {snap_path} not found — skipping tab intro generation")
        sys.exit(0)

    snap = json.loads(snap_path.read_text())

    try:
        digest = build_digest(snap)
    except Exception as e:
        print(f"  ERROR building digest: {e}")
        out = {"generatedAt": NOW.isoformat(), "error": str(e), "intros": {}}
        Path(DATA_DIR, "tab_intros.json").write_text(json.dumps(out, indent=2))
        sys.exit(0)

    # Hash the digest to detect whether the underlying data has changed.
    # If unchanged, skip the LLM call and keep existing tab_intros.json.
    import hashlib
    digest_hash = hashlib.sha256(json.dumps(digest, sort_keys=True).encode()).hexdigest()[:16]
    intros_path = Path(DATA_DIR) / "tab_intros.json"
    if intros_path.exists():
        existing = json.loads(intros_path.read_text())
        if existing.get("digestHash") == digest_hash and existing.get("intros"):
            print(f"  Digest unchanged ({digest_hash}) — skipping LLM call")
            sys.exit(0)

    prompt = build_prompt(digest)

    print(f"  Prompt: ~{len(prompt)//4} tokens")
    print(f"  Calling {MODEL}...")

    try:
        intros = call_api(prompt)
    except Exception as e:
        print(f"  ERROR: {e}")
        # Write an empty file so CI doesn't fail — UI falls back to static text
        out = {"generatedAt": NOW.isoformat(), "error": str(e), "intros": {}}
        Path(DATA_DIR, "tab_intros.json").write_text(json.dumps(out, indent=2))
        sys.exit(0)

    # Validate all tabs are present
    missing = [tab_id for tab_id, _, _ in TABS if tab_id not in intros]
    if missing:
        print(f"  WARNING: missing tabs: {missing}")

    out = {
        "generatedAt": NOW.isoformat(),
        "model": MODEL,
        "digestHash": digest_hash,
        "intros": intros,
    }

    out_path = Path(DATA_DIR) / "tab_intros.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"  Wrote {out_path} ({out_path.stat().st_size // 1024}KB)")
    print(f"  Generated {len(intros)} tab intros")

    # Print a sample
    sample_id = "ops"
    if sample_id in intros:
        print(f"\n  Sample ({sample_id}):")
        print(f"  {intros[sample_id][:200]}...")


if __name__ == "__main__":
    main()

