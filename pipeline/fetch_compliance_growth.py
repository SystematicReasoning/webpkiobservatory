#!/usr/bin/env python3
"""
Compliance Obligation Growth Pipeline
======================================
Tracks normative obligations placed on CAs over time across all major
regulatory sources. Uses a family of convention-aware parsers (obligation_parsers.py)
rather than a single keyword counter — different documents use different
structural conventions to express requirements.

Computed sources (fetched from canonical text):
  - CA/B Forum TLS BR: PDFs 2012-2021 + GitHub tags 2021-present
  - CA/B Forum EVG, NSR, S/MIME BR, CS BR: GitHub tags
  - Mozilla MRSP: GitHub markdown
  - IETF RFCs: 5280 (PKIX), 9162 (CT), 8659 (CAA), 8555 (ACME) — operative versions only
  - NIS2 Directive: EUR-Lex HTML
  - NIST SP 800-53 Rev 5: OSCAL JSON structured catalog

Curated sources (paywalled or no clean machine-readable text):
  - Chrome Root Program Policy (launched Sep 2022)
  - Apple Root Certificate Program
  - WebTrust for CAs criteria
  - ETSI EN 319 4xx / TS 119 xxx stack

Output: data/compliance_growth.json
"""

import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Add pipeline dir to path for obligation_parsers
sys.path.insert(0, str(Path(__file__).parent))
from obligation_parsers import parse as parse_obligations, parse_nist_oscal, detect_convention

try:
    from pdfminer.high_level import extract_text as pdf_extract_text
    HAS_PDFMINER = True
except ImportError:
    HAS_PDFMINER = False
    print("  WARNING: pdfminer.six not installed — historical PDFs skipped")

PIPELINE_DIR = Path(__file__).parent
OUTPUT_DIR   = PIPELINE_DIR.parent / "data"
CACHE_PATH   = PIPELINE_DIR / "ops_cache" / "compliance_growth_cache.json"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def _headers(github=False):
    h = {"User-Agent": "Mozilla/5.0 WebPKI-Observatory/1.0 (research)"}
    if github and GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h

def fetch_text(url, timeout=30):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")

def fetch_bytes(url, timeout=60):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers=_headers(github=True))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ── CABF source definitions ───────────────────────────────────────────────────

# Historical PDFs for TLS BR pre-GitHub era
CABF_PDFS = [
    ("2012-02-01", "https://cabforum.org/uploads/Baseline_Requirements_V1.pdf",        "BR v1.0"),
    ("2013-04-01", "https://cabforum.org/uploads/Baseline_Requirements_V1_1.pdf",       "BR v1.1"),
    ("2015-08-01", "https://cabforum.org/uploads/CA-Browser-Forum-BR-1.3.4.pdf",        "BR v1.3.4"),
    ("2016-09-01", "https://cabforum.org/uploads/CA-Browser-Forum-BR-1.4.1.pdf",        "BR v1.4.1"),
    ("2017-11-01", "https://cabforum.org/uploads/CA-Browser-Forum-BR-1.5.1.pdf",        "BR v1.5.1"),
    ("2018-08-01", "https://cabforum.org/uploads/CA-Browser-Forum-BR-1.6.0.pdf",        "BR v1.6.0"),
    ("2019-11-01", "https://cabforum.org/uploads/CA-Browser-Forum-BR-1.6.9.pdf",        "BR v1.6.9"),
    ("2021-04-01", "https://cabforum.org/uploads/CA-Browser-Forum-BR-1.7.3.pdf",        "BR v1.7.3"),
]

# GitHub repos: (doc_key, repo, tag_prefix, filepath, label)
CABF_GH = [
    ("tls_br",   "cabforum/servercert",   "BRs/",  "docs/BR.md",    "CA/B Forum TLS BR"),
    ("ev_g",     "cabforum/servercert",   "EVGs/", "docs/EVG.md",   "CA/B Forum EV Guidelines"),
    ("ns_reqs",  "cabforum/servercert",   "NSRs/", "docs/NSR.md",   "CA/B Forum NS Reqs"),
    ("smime_br", "cabforum/smime",        "SMC",   "SBR.md",        "CA/B Forum S/MIME BR"),
    ("cs_br",    "cabforum/code-signing", "v",     "docs/CSBR.md",  "CA/B Forum CS BR"),
]

# Operative RFCs only — no stacking superseded versions.
# A CA reads the current operative RFC, not its predecessors.
RFCS = [
    ("pkix",  "5280", "2008-05-01", "RFC 5280 (PKIX X.509 v3)"),
    ("ct",    "9162", "2021-12-01", "RFC 9162 (CT v2)"),
    ("caa",   "8659", "2019-11-01", "RFC 8659 (CAA)"),
    ("acme",  "8555", "2019-03-01", "RFC 8555 (ACME)"),
]

# Curated: paywalled or no clean machine-readable normative text
CURATED = {
    "chrome_root": {
        "label": "Chrome Root Program Policy", "color": "#4285f4",
        "history": [
            {"date": "2022-09-01", "mandatory": 45,  "recommended": 18, "optional": 8},
            {"date": "2023-06-01", "mandatory": 80,  "recommended": 25, "optional": 12},
            {"date": "2024-03-01", "mandatory": 110, "recommended": 32, "optional": 15},
            {"date": "2025-03-01", "mandatory": 130, "recommended": 38, "optional": 18},
        ]
    },
    "apple_root": {
        "label": "Apple Root Certificate Program", "color": "#555555",
        "history": [
            {"date": "2013-01-01", "mandatory": 20,  "recommended": 5,  "optional": 3},
            {"date": "2018-01-01", "mandatory": 40,  "recommended": 10, "optional": 5},
            {"date": "2022-01-01", "mandatory": 65,  "recommended": 15, "optional": 8},
            {"date": "2024-01-01", "mandatory": 90,  "recommended": 20, "optional": 10},
        ]
    },
    "webtrust": {
        "label": "WebTrust for CAs (TLS + Net Sec)", "color": "#e67e22",
        "history": [
            {"date": "2000-01-01", "mandatory": 40,  "recommended": 10, "optional": 5},
            {"date": "2008-01-01", "mandatory": 80,  "recommended": 20, "optional": 10},
            {"date": "2012-01-01", "mandatory": 120, "recommended": 30, "optional": 15},
            {"date": "2017-01-01", "mandatory": 180, "recommended": 40, "optional": 20},
            {"date": "2022-01-01", "mandatory": 220, "recommended": 50, "optional": 25},
            {"date": "2025-01-01", "mandatory": 250, "recommended": 55, "optional": 28},
        ]
    },
    "etsi_stack": {
        "label": "ETSI TSP Stack (EN 319 4xx / TS 119 xxx)", "color": "#16a085",
        "notes": "Paywalled. EN 319 401 + 411 + 412 + TS 119 461 + EN 419 221-5/241-2.",
        "history": [
            {"date": "2015-07-01", "mandatory": 180, "recommended": 40, "optional": 20},
            {"date": "2018-01-01", "mandatory": 280, "recommended": 60, "optional": 30},
            {"date": "2021-06-01", "mandatory": 380, "recommended": 80, "optional": 40},
            {"date": "2024-06-01", "mandatory": 515, "recommended": 95, "optional": 45},
        ]
    },
}

SOURCE_GROUPS = {
    "tls_br_op":   {"label": "TLS BR (operational)",         "color": "#2ecc71"},
    "tls_br_prof": {"label": "TLS BR (profile spec)",        "color": "#82e0aa"},
    "ev_g_op":     {"label": "EV Guidelines (operational)",  "color": "#27ae60"},
    "ev_g_prof":   {"label": "EV Guidelines (profile spec)", "color": "#7dcea0"},
    "ns_reqs":     {"label": "CA/B Forum NS Reqs",           "color": "#1abc9c"},
    "ns_reqs_op":  {"label": "CA/B Forum NS Reqs",           "color": "#1abc9c"},
    "smime_br_op": {"label": "S/MIME BR (operational)",      "color": "#16a085"},
    "smime_br_prof":{"label": "S/MIME BR (profile spec)",    "color": "#76d7c4"},
    "cs_br_op":    {"label": "CS BR (operational)",          "color": "#0e8a73"},
    "cs_br_prof":  {"label": "CS BR (profile spec)",         "color": "#45b39d"},
    "mozilla_mrsp":{"label": "Mozilla MRSP",                 "color": "#ff6f00"},
    "chrome_root": {"label": "Chrome Root Policy",           "color": "#4285f4"},
    "apple_root":  {"label": "Apple Root Policy",            "color": "#555555"},
    "rfc_pkix":    {"label": "RFC 5280 (PKIX)",              "color": "#8e44ad"},
    "rfc_ct":      {"label": "RFC 9162 (CT)",                "color": "#9b59b6"},
    "rfc_caa":     {"label": "RFC 8659 (CAA)",               "color": "#a569bd"},
    "rfc_acme":    {"label": "RFC 8555 (ACME)",              "color": "#b07cc6"},
    "webtrust":    {"label": "WebTrust / ETSI Audit",        "color": "#e67e22"},
    "etsi_stack":  {"label": "ETSI TSP Stack",               "color": "#16a085"},
    "nist":        {"label": "NIST SP 800-53 Rev 5",         "color": "#c0392b"},
    "nis2":        {"label": "NIS2 Directive",               "color": "#922b21"},
}


# ── Fetch functions ───────────────────────────────────────────────────────────

def get_commit_date(repo, sha):
    data = fetch_json(f"https://api.github.com/repos/{repo}/commits/{sha}")
    return data["commit"]["committer"]["date"][:10]


def fetch_cabf_pdfs(cache):
    print("  CA/B Forum TLS BR (PDFs)...")
    results = []
    for date, url, label in CABF_PDFS:
        ck = f"pdf:{url}"
        if ck in cache:
            results.append(cache[ck])
            print(f"    {label}: cached (total={cache[ck]['total']})")
            continue
        if not HAS_PDFMINER:
            continue
        try:
            raw = fetch_bytes(url, timeout=60)
            text = pdf_extract_text(io.BytesIO(raw))
            result = parse_obligations(text)
            entry = {
                "date": date, "label": label, "doc": "tls_br",
                "source": "CA/B Forum TLS BR (PDF)",
                "convention": result["convention"],
                "mandatory": result["mandatory"],
                "recommended": result["recommended"],
                "optional": result["optional"],
                "total": result["total"],
            }
            cache[ck] = entry
            results.append(entry)
            print(f"    {label} ({date}): {result['convention']} "
                  f"mand={result['mandatory']} rec={result['recommended']} "
                  f"opt={result['optional']} total={result['total']}")
        except Exception as e:
            print(f"    {label}: ERROR {e}")
    return sorted(results, key=lambda x: x["date"])


def fetch_cabf_github(doc_key, repo, tag_prefix, filepath, label, cache):
    print(f"  {label}...")
    results = []
    try:
        tags = fetch_json(f"https://api.github.com/repos/{repo}/tags?per_page=100")
        relevant = [t for t in tags if t["name"].startswith(tag_prefix)]
        for t in relevant:
            ck = f"gh:{repo}:{t['name']}"
            if ck in cache:
                results.append(cache[ck])
                continue
            sha = t["commit"]["sha"]
            try:
                date = get_commit_date(repo, sha)
            except Exception:
                continue
            raw_url = f"https://raw.githubusercontent.com/{repo}/{t['name']}/{filepath}"
            try:
                text = fetch_text(raw_url)
                result = parse_obligations(text)
                entry = {
                    "date": date, "tag": t["name"], "doc": doc_key,
                    "source": label, "convention": result["convention"],
                    "mandatory": result["mandatory"],
                    "recommended": result["recommended"],
                    "optional": result["optional"],
                    "total": result["total"],
                }
                # Store operational/profile split if available
                if "operational" in result:
                    entry["operational"] = result["operational"]
                    entry["profile_spec"] = result["profile_spec"]
                cache[ck] = entry
                results.append(entry)
                print(f"    {t['name']} ({date}): {result['convention']} "
                      f"mand={result['mandatory']} rec={result['recommended']} "
                      f"opt={result['optional']} total={result['total']}")
            except Exception as e:
                print(f"    {t['name']}: ERROR {e}")
    except Exception as e:
        print(f"    ERROR: {e}")
    return sorted(results, key=lambda x: x["date"])


def fetch_rfcs(cache):
    print("  IETF RFCs (operative versions only)...")
    results = []
    for track, rfc_id, date, label in RFCS:
        ck = f"rfc_v2:{rfc_id}"
        if ck in cache:
            results.append(cache[ck])
            print(f"    {label}: cached (total={cache[ck]['total']})")
            continue
        try:
            text = fetch_text(f"https://www.rfc-editor.org/rfc/rfc{rfc_id}.txt")
            result = parse_obligations(text)
            entry = {
                "date": date, "rfc": rfc_id, "track": track, "label": label,
                "source": "IETF RFCs", "convention": result["convention"],
                "mandatory": result["mandatory"],
                "recommended": result["recommended"],
                "optional": result["optional"],
                "total": result["total"],
            }
            cache[ck] = entry
            results.append(entry)
            print(f"    {label} ({date}): mand={result['mandatory']} "
                  f"rec={result['recommended']} opt={result['optional']} total={result['total']}")
        except Exception as e:
            print(f"    RFC {rfc_id}: ERROR {e}")
    return sorted(results, key=lambda x: x["date"])


def fetch_mozilla_mrsp(cache):
    ck = "mozilla_mrsp_v2:current"
    if ck in cache:
        print(f"  Mozilla MRSP: cached (total={cache[ck]['total']})")
        return cache[ck]
    print("  Mozilla MRSP...")
    url = "https://raw.githubusercontent.com/mozilla/pkipolicy/master/rootstore/policy.md"
    text = fetch_text(url)
    result = parse_obligations(text)
    entry = {
        "source": "Mozilla MRSP", "date": "2004-08-01",
        "convention": result["convention"],
        "mandatory": result["mandatory"],
        "recommended": result["recommended"],
        "optional": result["optional"],
        "total": result["total"],
    }
    cache[ck] = entry
    print(f"    {result['convention']} mand={result['mandatory']} "
          f"rec={result['recommended']} opt={result['optional']} total={result['total']}")
    return entry


def fetch_nis2(cache):
    ck = "nis2_v2:32022L2555"
    if ck in cache:
        print(f"  NIS2: cached (total={cache[ck]['total']})")
        return cache[ck]
    print("  NIS2 Directive (EUR-Lex)...")
    url = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32022L2555"
    text = fetch_text(url)
    result = parse_obligations(text)
    entry = {
        "source": "NIS2 Directive", "date": "2024-10-18",
        "convention": result["convention"],
        "mandatory": result["mandatory"],
        "recommended": result["recommended"],
        "optional": result["optional"],
        "total": result["total"],
        "notes": "EU 'shall' = binding. QTSPs are Essential Entities (Art 3(1)(b)).",
    }
    cache[ck] = entry
    print(f"    {result['convention']} mand={result['mandatory']} "
          f"opt={result['optional']} total={result['total']}")
    return entry


def fetch_nist(cache):
    ck = "nist_v3:800-53-r5-high"
    if ck in cache:
        print(f"  NIST 800-53: cached (total={cache[ck]['total']})")
        return cache[ck]
    print("  NIST SP 800-53 Rev 5 (OSCAL)...")
    url = ("https://raw.githubusercontent.com/usnistgov/oscal-content/main/"
           "nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_HIGH-baseline-resolved-profile_catalog.json")
    raw = fetch_bytes(url, timeout=90)
    data = json.loads(raw)
    result = parse_nist_oscal(data, baseline="high")
    entry = {
        "source": "NIST SP 800-53 Rev 5", "date": "2020-09-23",
        "convention": "NIST_OSCAL",
        "mandatory": result["mandatory"],
        "recommended": result["recommended"],
        "optional": result["optional"],
        "total": result["total"],
        "detail": result["detail"],
        "notes": "All base controls + enhancements. CAs under NIS2 must demonstrate alignment.",
    }
    cache[ck] = entry
    d = result["detail"]
    print(f"    NIST_OSCAL High baseline: {d['base_controls']} base + {d['enhancements']} enh = {result['total']} (High only)")
    return entry


# ── Time series ───────────────────────────────────────────────────────────────

def build_time_series(all_data):
    # Gather all (group_key, date, mandatory, recommended, optional) data points
    points = []

    # CABF: merge PDF and GitHub per doc_key, split operational/profile
    cabf_by_doc = {}
    for e in all_data.get("cabf_pdfs", []):
        cabf_by_doc.setdefault(e["doc"], []).append(e)
    for dk, history in all_data.get("cabf_gh", {}).items():
        for e in history:
            cabf_by_doc.setdefault(dk, []).append(e)
    for dk, entries in cabf_by_doc.items():
        for e in sorted(entries, key=lambda x: x["date"]):
            if "operational" in e:
                # Emit two groups: operational and profile spec
                op = e["operational"]
                pr = e["profile_spec"]
                points.append({"group": f"{dk}_op", "date": e["date"],
                               "mandatory": op["mandatory"],
                               "recommended": op["recommended"],
                               "optional": op["optional"]})
                points.append({"group": f"{dk}_prof", "date": e["date"],
                               "mandatory": pr["mandatory"],
                               "recommended": pr.get("recommended", 0),
                               "optional": pr.get("optional", 0)})
            else:
                # No split available (NSR has no certificate profiles section)
                points.append({"group": dk,
                               "date": e["date"],
                               "mandatory": e["mandatory"],
                               "recommended": e["recommended"],
                               "optional": e["optional"]})

    # RFCs — operative versions, by track (no stacking superseded)
    for e in all_data.get("rfcs", []):
        points.append({"group": f"rfc_{e['track']}", "date": e["date"],
                       "mandatory": e["mandatory"],
                       "recommended": e["recommended"],
                       "optional": e["optional"]})

    # Mozilla MRSP
    m = all_data.get("mozilla_mrsp", {})
    if m:
        points.append({"group": "mozilla_mrsp", "date": m["date"],
                       "mandatory": m["mandatory"],
                       "recommended": m["recommended"],
                       "optional": m["optional"]})

    # NIS2
    n = all_data.get("nis2", {})
    if n:
        points.append({"group": "nis2", "date": n["date"],
                       "mandatory": n["mandatory"],
                       "recommended": 0,
                       "optional": n["optional"]})

    # NIST
    ns = all_data.get("nist", {})
    if ns:
        points.append({"group": "nist", "date": ns["date"],
                       "mandatory": ns["mandatory"],
                       "recommended": 0, "optional": 0})

    # Curated
    for key, cfg in CURATED.items():
        for e in cfg.get("history", []):
            points.append({"group": key, "date": e["date"],
                           "mandatory": e.get("mandatory", 0),
                           "recommended": e.get("recommended", 0),
                           "optional": e.get("optional", 0)})

    # Build year-by-year using latest operative value per group
    current_year = datetime.now(timezone.utc).year
    all_groups = list({p["group"] for p in points})
    series = []

    for year in range(2000, current_year + 1):
        cutoff = f"{year}-12-31"
        row = {"year": year, "by_source": {},
               "totals": {"mandatory": 0, "recommended": 0, "optional": 0, "total": 0}}

        for g in all_groups:
            relevant = [p for p in points if p["group"] == g and p["date"] <= cutoff]
            if not relevant:
                continue
            latest = max(relevant, key=lambda x: x["date"])
            label = SOURCE_GROUPS.get(g, {}).get("label", g)
            row["by_source"][g] = {
                "label": label,
                "mandatory": latest["mandatory"],
                "recommended": latest["recommended"],
                "optional": latest["optional"],
            }
            row["totals"]["mandatory"]   += latest["mandatory"]
            row["totals"]["recommended"] += latest["recommended"]
            row["totals"]["optional"]    += latest["optional"]

        row["totals"]["total"] = (row["totals"]["mandatory"] +
                                  row["totals"]["recommended"] +
                                  row["totals"]["optional"])
        if row["totals"]["total"] > 0:
            series.append(row)

    return series


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Compliance Obligation Growth Pipeline")
    print("=" * 60)
    if not GITHUB_TOKEN:
        print("  WARNING: No GITHUB_TOKEN — GitHub API may rate-limit")

    cache = {}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text())
            print(f"  Loaded {len(cache)} cached entries\n")
        except Exception as e:
            print(f"  WARNING: could not load compliance growth cache: {e}", file=__import__("sys").stderr)

    all_data = {}

    print("── CA/B Forum TLS BR (PDF archive, pre-2021) ──")
    all_data["cabf_pdfs"] = fetch_cabf_pdfs(cache)

    print("\n── CA/B Forum (GitHub tags) ──")
    all_data["cabf_gh"] = {}
    for doc_key, repo, tag_prefix, filepath, label in CABF_GH:
        all_data["cabf_gh"][doc_key] = fetch_cabf_github(
            doc_key, repo, tag_prefix, filepath, label, cache)

    print("\n── IETF RFCs (operative versions) ──")
    all_data["rfcs"] = fetch_rfcs(cache)

    print("\n── Mozilla MRSP ──")
    all_data["mozilla_mrsp"] = fetch_mozilla_mrsp(cache)

    print("\n── NIS2 Directive ──")
    all_data["nis2"] = fetch_nis2(cache)

    print("\n── NIST SP 800-53 Rev 5 ──")
    all_data["nist"] = fetch_nist(cache)

    print("\n── Building time series ──")
    time_series = build_time_series(all_data)
    print(f"  {len(time_series)} annual data points")

    if time_series:
        first = next((r for r in time_series if r["year"] == 2000), time_series[0])
        latest = time_series[-1]
        print(f"  {first['year']}: total={first['totals']['total']:,}")
        print(f"  {latest['year']}: total={latest['totals']['total']:,}")
        if first["totals"]["total"] > 0:
            print(f"  Growth: {latest['totals']['total'] / first['totals']['total']:.0f}×")

        # Per-source breakdown for latest year
        print(f"\n  {latest['year']} breakdown:")
        for g, v in sorted(latest["by_source"].items(),
                           key=lambda x: -(x[1]["mandatory"]+x[1]["recommended"]+x[1]["optional"])):
            t = v["mandatory"] + v["recommended"] + v["optional"]
            print(f"    {g:<20} mand={v['mandatory']:4} rec={v['recommended']:3} "
                  f"opt={v['optional']:3} total={t:4}  ({SOURCE_GROUPS.get(g,{}).get('label',g)})")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_groups": SOURCE_GROUPS,
        "methodology": {
            "computed_sources": [
                "tls_br (PDF 2012-2021 + GitHub 2021-present)",
                "ev_g, ns_reqs, smime_br, cs_br (GitHub tags)",
                "mozilla_mrsp (GitHub markdown)",
                "rfc_pkix (RFC 5280), rfc_ct (RFC 9162), rfc_caa (RFC 8659), rfc_acme (RFC 8555)",
                "nis2 (EUR-Lex HTML)", "nist_800_53 (OSCAL JSON)",
            ],
            "curated_sources": ["chrome_root", "apple_root", "webtrust", "etsi_stack"],
            "parsers": {
                "RFC2119_INLINE": "MUST/MUST NOT/SHALL/SHALL NOT/SHOULD/MAY uppercase keywords. "
                    "Used by: TLS BR, EVG, CS BR, Mozilla MRSP, RFCs.",
                "SHALL_LETTERED_LIST": "SHALL: section header + lettered sub-items (a. b. c.) + "
                    "numbered/roman sub-sub-items. Structural item count as primary, "
                    "inline keyword count as floor. Used by: NSR, S/MIME BR.",
                "EU_LEGAL": "Lowercase 'shall' = binding obligation. EU 'should' excluded "
                    "(recital/political guidance, not operative). Used by: NIS2.",
                "NIST_OSCAL": "Structured JSON control catalog count: base controls + enhancements. "
                    "Used by: NIST SP 800-53 Rev 5.",
            },
            "rfc_approach": "Operative versions only — no stacking superseded RFCs. "
                "A CA reads the current operative version, not its predecessors. "
                "RFC 5280 superseded 3280/2459; RFC 9162 superseded 6962; RFC 8659 superseded 6844.",
            "caveats": [
                "Keyword/structural counts include some definitional and example uses — "
                "trends are more reliable than absolute values.",
                "NIST 800-53 shown in full; CAs under NIS2 must demonstrate alignment "
                "but not all controls apply directly.",
                "NIS2 counts full directive; TSP-specific obligations are a subset (~150-180).",
                "Curated sources (ETSI, WebTrust, Chrome, Apple) are expert estimates "
                "from published document summaries.",
            ],
        },
        "time_series": time_series,
        "current": {
            "year": time_series[-1]["year"] if time_series else None,
            "totals": time_series[-1]["totals"] if time_series else {},
        },
    }

    out_path = OUTPUT_DIR / "compliance_growth.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n  Wrote {out_path} ({out_path.stat().st_size:,} bytes)")

    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
    print(f"  Saved {len(cache)} cache entries")


if __name__ == "__main__":
    main()
