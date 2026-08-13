#!/usr/bin/env python3
"""
WebPKI Observatory — Audit Intelligence Pipeline
=================================================
Builds per-CA audit profiles from CCADB metadata and, where accessible,
parses WebTrust/ETSI audit letter PDFs to extract:
  - Opinion type (unqualified / qualified / adverse / disclaimer)
  - Incidents disclosed in Appendix D (with Bugzilla IDs where present)
  - Qualifications / exception language

Data sources
------------
  Primary : CCADB AllCertificateRecordsCSVFormatv4 (audit metadata, dates, URLs)
  Secondary: CPA Canada getPDFWebTrust API (direct PDF for ~365 WebTrust roots)
  Secondary: Direct PDF URLs on auditor/CA domains (~175 ETSI roots)

Output
------
  data/audits.json  — per-CA audit profiles + auditor concentration stats

Cache
-----
  pipeline/audit_pdf_cache/  — one JSON file per attachmentId / URL hash
  Cache TTL: 90 days (audit letters don't change once issued)
"""

import csv
import hashlib
import io
import json
import re
import time
import urllib.request
import urllib.error
from collections import defaultdict, Counter
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from config import normalize_ca_owner
from utils import ANTHROPIC_URL, ANTHROPIC_MODEL, ANTHROPIC_VERSION

# Optional: pdfplumber for PDF text extraction
try:
    import pdfplumber
    import warnings as _warnings
    import logging as _logging
    # Suppress pdfminer ToUnicode map noise — cosmetic, not functional errors
    _warnings.filterwarnings("ignore", message=".*ToUnicode.*")
    _warnings.filterwarnings("ignore", message=".*cid.*")
    # Also suppress via logging since pdfminer uses both
    _logging.getLogger("pdfminer").setLevel(_logging.ERROR)
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    print("  [audits] pdfplumber not installed — PDF parsing disabled. "
          "Run: pip install pdfplumber")

PIPELINE_DIR = Path(__file__).parent
OUTPUT_DIR = PIPELINE_DIR.parent / "data"
CACHE_DIR = PIPELINE_DIR / "audit_pdf_cache"
CACHE_DIR.mkdir(exist_ok=True)

CACHE_TTL_DAYS = 90

# Load CA type classifications (commercial, government, state_enterprise, non_profit, regulated)
_gov_cls_path = PIPELINE_DIR / "gov_classifications.json"
try:
    _gov_cls_raw = json.loads(_gov_cls_path.read_text(encoding="utf-8"))
    CA_TYPE_MAP = {ca: v.get("type", "commercial")
                  for ca, v in _gov_cls_raw.get("classifications", {}).items()}
except Exception as e:
    print(f"  WARNING: could not load gov_classifications.json: {e}", file=__import__("sys").stderr)
    print(f"  WARNING: all CAs will default to type='commercial' in audit profiles", file=__import__("sys").stderr)
    CA_TYPE_MAP = {}

# CA owner normalization: imported from config.py


# Auditor name normalization table — maps raw CCADB strings to canonical names
# Key is a substring match (lowercased), value is the canonical display name
AUDITOR_ALIASES = {
    "kpmg":                         "KPMG",
    "ernst & young":                "Ernst & Young",
    "ernst and young":              "Ernst & Young",
    "deloitte":                     "Deloitte",
    "pricewaterhousecoopers":       "PwC",
    "pwc":                          "PwC",
    "bdo international":            "BDO International",
    "bdo usa":                      "BDO USA",
    "bdo consulting":               "BDO Consulting (Malaysia)",
    "bdo israel":                   "BDO Israel",
    "schellman":                    "Schellman",
    "sunrise cpas":                 "SunRise CPAs / DFK",
    "dfk international":            "SunRise CPAs / DFK",
    "lsti":                         "LSTI",
    "tüvit":                        "TÜViT",
    "tuvit":                        "TÜViT",
    "tüv nord":                     "TÜV NORD",
    "tuv nord":                     "TÜV NORD",
    "tüv austria":                  "TÜV Austria",
    "datenschutz cert":             "datenschutz cert GmbH",
    "aenor":                        "AENOR",
    "qmscert":                      "QMSCERT",
    "csqa":                         "CSQA Certificazioni",
    "dekra":                        "DEKRA",
    "a-sit":                        "A-SIT",
    "baker tilly":                  "Baker Tilly",
    "sensiba":                      "Sensiba San Filippo",
    "richter":                      "Richter LLP",
}

# Auditor → country mapping for geographic analysis
# Keyed on the normalized auditor name (post-AUDITOR_ALIASES)
AUDITOR_COUNTRY = {
    # Big 4 — global firms, headquartered US/UK
    "KPMG":                        "Global (US/UK)",
    "Deloitte":                    "Global (US/UK)",
    "Ernst & Young":               "Global (US/UK)",
    "PwC":                         "Global (US/UK)",
    "BDO International":           "Global (US/UK)",
    "BDO USA":                     "United States",
    "BDO Consulting (Malaysia)":   "Malaysia",
    "BDO Israel":                  "Israel",
    # US WebTrust specialists
    "Schellman":                   "United States",
    "SunRise CPAs / DFK":          "United States",
    "Baker Tilly":                 "United States",
    "Sensiba San Filippo":         "United States",
    "Scott S. Perry CPA, PLLC":    "United States",
    "Richter LLP":                 "Canada",
    "Anthony Kam & Associates Ltd.": "Hong Kong",
    # European ETSI auditors
    "LSTI":                        "France",
    "datenschutz cert GmbH":       "Germany",
    "TÜV NORD":                    "Germany",
    "TÜViT":                       "Germany",
    "TÜV Austria":                 "Austria",
    "A-SIT":                       "Austria",
    "AENOR":                       "Spain",
    "DEKRA":                       "Spain",
    "Auren":                       "Spain",
    "CSQA Certificazioni":         "Italy",
    "Bureau Veritas Italia S.p.A": "Italy",
    "IMQ S.p.A.":                  "Italy",
    "TayllorCox PCEB":             "Czech Republic",
    "Attestic B.V.":               "Netherlands",
    "BSI":                         "United Kingdom",
    "LRQA - Lloyds Register":      "United Kingdom",
    "LRQA - Lloyds Register Quality Assurance": "United Kingdom",
    "BDO Cyber Security":          "Global (US/UK)",
    "Crowe FST Audit Ltd":         "Romania",
    "QSCert":                      "Slovakia",
    "QMSCERT":                     "Greece",
    "SIQ Ljubljana":               "Slovenia",
    "Elektrotechnický zkušební ústav, s.p.": "Czech Republic",
    "Hunguard":                    "Hungary",
    "MATRIX Ltd.":                 "Hungary",
    "Certop":                      "Hungary",
    "Audit Trust":                 "Latvia",
    "Žydrūnas Skardžius (CISA)":   "Lithuania",
    "SLOVENIAN ACCREDITATION":     "Slovenia",
    "PKI Contabilidade e Auditoria Ltda.": "Brazil",
    "Moreira Associados Auditores Independentes": "Brazil",
    "Digital Age Strategies Pvt Ltd": "India",
    "M. Kuppuswamy P S G & Co LLP": "India",
    # East Asia
    "RSM Hong Kong":               "Hong Kong",
    "KIWA CERMET Italia S.p.A":    "Italy",
    "Bureau Veritas d.o.o.":       "Slovenia",
    "Sharony - Shefler & Co. CPA": "Israel",
    "The Slandala Company":        "United States",
    "Ionize":                      "Australia",
    "SUSCERTE Registered Auditor": "Venezuela",
    "Associação Portuguesa de Certificação (APCER)": "Portugal",
    "ICTA/BTK":                    "Turkey",
    "French Government":           "France",
    "Certi-Trust":                 "Switzerland",
}

DIRECT_PDF_DOMAINS = {
    "datenschutz-cert.de",
    "lsti-certification.fr",
    "tuev-nord.de",
    "tuvit.de",
    "it-tuv.com",
    "qmscert.com",
    "qscert.com",           # QSCert, Slovak auditor (e.g. Disig)
    "csqa.it",
    "aenor.com",
    "tayllorcox.cz",
    "hunguard.hu",
    "a-sit.at",
    "dekra-checkme.com",
    "matrix-tanusito.hu",
    "bmoattachments.org",
    "mozilla.org",          # bugzilla.mozilla.org attachment URLs (e.g. reference entity)
    "bureauveritas.it",
    "actalis.it",
    "buypass.no",
    "webtrust.org",         # 503 currently but may recover
    "attestic.eu",          # Attestic B.V. (e.g. reference entity 2026)
}

HTTP_HEADERS = {
    "User-Agent": "WebPKI-Observatory-Audit-Bot/1.0 (https://webpki.x509.io; research)",
    "Accept": "application/pdf,*/*",
}


def _try_parse_date(s):
    """
    Parse a date string in any of the formats that appear in audit letter PDFs
    and CCADB records. Returns a date object or None.
    """
    if not s:
        return None
    for fmt in ("%B %d, %Y", "%B %d %Y", "%d %B %Y",
                "%Y-%m-%d", "%B, %d %Y", "%b %d, %Y",
                "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y",
                "July %d, %Y", "September %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    # Remove ordinal suffixes (1st, 2nd, 3rd, 4th) and retry
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", s.strip())
    for fmt in ("%B %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_ccadb_date(s):
    """Parse CCADB date strings like '2025.11.06' or '2025-11-06'."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Auditor name normalisation
# ---------------------------------------------------------------------------

def normalize_auditor(raw):
    """Return canonical auditor name, or the raw string if no alias matches."""
    if not raw:
        return None
    lower = raw.lower()
    for fragment, canonical in AUDITOR_ALIASES.items():
        if fragment in lower:
            return canonical
    return raw.strip()


# ---------------------------------------------------------------------------
# Audit framework normalisation
# ---------------------------------------------------------------------------

def normalize_framework(raw):
    """WebTrust / ETSI / Other."""
    if not raw:
        return None
    r = raw.strip()
    if "webtrust" in r.lower() or "WebTrust" in r:
        return "WebTrust"
    if "etsi" in r.lower():
        return "ETSI"
    return r


# ---------------------------------------------------------------------------
# PDF cache helpers
# ---------------------------------------------------------------------------

def _cache_key(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _cache_path(url):
    return CACHE_DIR / f"{_cache_key(url)}.json"


def _load_cache(url):
    p = _cache_path(url)
    if not p.exists():
        return None
    try:
        with open(p) as f:
            entry = json.load(f)
        cached_at = datetime.fromisoformat(entry["cached_at"])
        if datetime.now(timezone.utc).replace(tzinfo=None) - cached_at > timedelta(days=CACHE_TTL_DAYS):
            return None
        return entry["result"]
    except Exception as e:
        # Corrupted or unreadable cache entry — treat as cache miss and re-fetch.
        print(f"    WARNING: cache read error for {p}: {e}", file=sys.stderr)
        return None


def _save_cache(url, result):
    p = _cache_path(url)
    try:
        with open(p, "w") as f:
            json.dump({"cached_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), "result": result}, f)
    except Exception as e:
        # Cache write failure means next run will re-fetch this PDF — wasteful but not wrong.
        # Log so repeated failures are visible in CI output.
        print(f"    WARNING: cache write failed for {url[:60]}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# PDF fetch
# ---------------------------------------------------------------------------

def fetch_pdf_bytes(url, timeout=20):
    """Fetch a PDF URL. Returns bytes or None."""
    try:
        req = urllib.request.Request(url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            ct = resp.headers.get("Content-Type", "")
            data = resp.read()
            # Validate it's actually a PDF
            if not data.startswith(b"%PDF"):
                return None
            return data
    except Exception as e:
        # Log which URL failed so repeated fetch errors are visible in CI.
        print(f"    WARNING: PDF fetch failed: {e}", file=__import__("sys").stderr)
        return None


def is_fetchable_url(url):
    """Return True if we expect to be able to fetch this URL as a PDF."""
    if not url:
        return False
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    # CPA Canada direct PDF API — always fetchable
    if "cpacanada.ca" in netloc:
        return True
    # Direct PDF on known auditor domains
    domain_key = ".".join(netloc.split(".")[-2:])
    if domain_key in DIRECT_PDF_DOMAINS:
        return True
    # Explicit .pdf extension URLs on any domain
    if parsed.path.lower().endswith(".pdf"):
        return True
    return False


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

# Haiku for cost efficiency — same model used by classify_comments.py

# ---------------------------------------------------------------------------
# Audit standard version timelines — epoch-aware scoring
# ---------------------------------------------------------------------------
# Each entry: (version_string, effective_from_YYYY-MM, superseded_YYYY-MM|None)
# A letter is "current" if stmt_date falls within [effective_from, superseded).
# superseded=None means still current today.
# Sources: CPA Canada WebTrust release archive, ETSI ESIG AAL publication log.

WEBTRUST_CRITERIA_TIMELINE = [
    # ── Principles and Criteria (General / CA baseline) ─────────────────────
    ("2.0",   "2013-01", "2016-01"),
    ("2.1",   "2016-01", "2018-01"),
    ("2.2",   "2018-01", "2018-08"),
    ("2.2.1", "2018-08", "2020-04"),
    ("2.2.2", "2020-04", None),          # no v2.3 final released
    # ── TLS / SSL Baseline Requirements ─────────────────────────────────────
    ("2.0",   "2014-01", "2017-06"),
    ("2.3",   "2017-06", "2019-04"),
    ("2.4",   "2019-04", "2020-10"),
    ("2.5",   "2020-10", "2020-12"),
    ("2.6",   "2020-12", "2022-01"),
    ("2.7",   "2022-01", "2023-01"),
    ("2.8",   "2023-01", "2023-10"),
    ("2.9",   "2023-10", "2024-07"),
    ("2.10",  "2024-07", None),
    # ── Extended Validation (EV SSL) ─────────────────────────────────────────
    ("1.6.2", "2014-01", "2017-03"),
    ("1.6.5", "2017-03", "2018-07"),
    ("1.7.0", "2017-03", "2018-07"),
    ("1.7.2", "2018-07", "2020-06"),
    ("1.7.4", "2020-06", "2022-01"),
    ("1.7.6", "2022-01", "2023-04"),
    ("1.7.7", "2023-04", "2024-01"),
    ("1.7.8", "2024-01", None),
    # ── S/MIME ───────────────────────────────────────────────────────────────
    ("1.0",   "2023-01", "2023-10"),
    ("1.0.4", "2023-10", "2024-04"),
    ("1.0.8", "2024-04", None),
    # ── Network Security ─────────────────────────────────────────────────────
    ("2.0",   "2022-07", "2024-01"),
    ("2.0.5", "2024-01", None),
]

# ETSI AAL (Audit Attestation Letter) template versions
# Source: ETSI ESIG publication log
ETSI_AAL_TIMELINE = [
    ("2.9",  "2019-01", "2020-07"),
    ("3.0",  "2020-07", "2022-01"),
    ("3.1",  "2022-01", "2022-08"),
    ("3.2",  "2022-08", "2023-04"),
    ("3.3",  "2023-04", "2024-01"),
    ("3.4",  "2024-01", "2026-03"),
    ("3.5",  "2026-03", None),           # mandatory from March 2026
]

# Audit epochs — quality scoring and chart faceting
# pre_aal  : before AAL template existed; template_compliance not applicable
# aal_v3x  : AAL V3.x era; template scored against what was current then
# post_v35 : V3.5 mandatory; strictest template scoring
AUDIT_EPOCHS = [
    ("pre_aal",  "2000-01", "2020-07"),
    ("aal_v3x",  "2020-07", "2026-03"),
    ("post_v35", "2026-03", None),
]

# Disclosure expectation epoch — CCADB §5.2 item 13 wasn't systematically
# enforced until Mozilla policy update of 2023. Pre-2023 letters are not
# penalised for missing disclosure cross-references.
DISCLOSURE_ENFORCED_FROM = "2023-01"


def _ym(s):
    """Convert 'YYYY-MM' string to a comparable int YYYYMM."""
    if not s:
        return None
    p = str(s)[:7].split("-")
    return int(p[0]) * 100 + int(p[1])


def get_audit_epoch(stmt_date_str):
    """Return the audit epoch for a statement date ('YYYY-MM-DD' or 'YYYY-MM').
    Returns 'pre_aal', 'aal_v3x', 'post_v35', or None."""
    if not stmt_date_str:
        return None
    stmt = _ym(str(stmt_date_str)[:7])
    for epoch, start, end in AUDIT_EPOCHS:
        s = _ym(start)
        e = _ym(end) if end else 999999
        if s <= stmt < e:
            return epoch
    return None


def is_webtrust_version_current(version_str, stmt_date_str):
    """True if version_str was a current WebTrust version at stmt_date_str.
    Returns None if version unknown or stmt_date missing."""
    if not version_str or not stmt_date_str:
        return None
    stmt = _ym(str(stmt_date_str)[:7])
    found = False
    for ver, start, end in WEBTRUST_CRITERIA_TIMELINE:
        if ver != version_str:
            continue
        found = True
        s = _ym(start)
        e = _ym(end) if end else 999999
        if s <= stmt < e:
            return True
        if stmt >= e:
            return False
    return None  # version not in table


def is_etsi_aal_current(aal_version_str, stmt_date_str):
    """True if aal_version_str was the current AAL template at stmt_date_str.
    Returns None if version missing or not in table."""
    if not aal_version_str or not stmt_date_str:
        return None
    stmt = _ym(str(stmt_date_str)[:7])
    for ver, start, end in ETSI_AAL_TIMELINE:
        if ver != aal_version_str:
            continue
        s = _ym(start)
        e = _ym(end) if end else 999999
        if s <= stmt < e:
            return True
        if stmt >= e:
            return False
    return None


# CA/B Forum policy OIDs that should appear in audit letters
# per CCADB Policy §5.2 item 14
CABF_POLICY_OIDS = {
    # TLS
    "2.23.140.1.2.1": "TLS DV",
    "2.23.140.1.2.2": "TLS OV",
    "2.23.140.1.2.3": "TLS IV",
    "2.23.140.1.1":   "TLS EV",
    # Code Signing
    "2.23.140.1.4.1": "CS",
    "2.23.140.1.4.2": "CS EV",
    "2.23.140.1.3":   "CS timestamp",
    # S/MIME (selected)
    "2.23.140.1.5.1.1": "SMIME Mailbox DV",
    "2.23.140.1.5.2.1": "SMIME Org DV",
    "2.23.140.1.5.3.1": "SMIME Sponsor DV",
    "2.23.140.1.5.4.1": "SMIME Individual DV",
}

AUDIT_EXTRACT_PROMPT = """\
You are extracting structured data from a WebTrust or ETSI audit letter for a \
Certificate Authority. The text below is extracted from a PDF and may include \
pages from both the beginning and end of the document, possibly with a cover \
page or table of contents before the actual letter.

Extract the following and return ONLY a valid JSON object, no other text:

{
  "auditor_firm": "Name of the audit firm from the letter header. Look past cover pages and DocuSign headers. Examples: 'BDO USA, P.C.', 'Ernst & Young LLP', 'Deloitte LLP', 'LSTI'.",
  "ca_name": "Name of the CA being audited, from the scope paragraph.",
  "period_start": "Audit period start date exactly as written (e.g. 'September 1, 2024', '1 October 2024').",
  "period_end": "Audit period end date exactly as written.",
  "opinion_type": "One of: unqualified, qualified, adverse, disclaimer, unknown",
  "audit_framework": "One of: WebTrust, ETSI, other",
  "audit_criteria": "Full version string of criteria used. E.g. 'WebTrust Principles and Criteria for Certification Authorities Version 2.2.2' or 'ETSI EN 319 411-1 V1.2.2, DVCP;OVCP'. If multiple criteria, join with '; '.",
  "etsi_aal_version": "For ETSI letters only: the AAL template version string, e.g. '3.5', '3.4', '3.3'. Look for 'AAL Version', 'Template Version', 'V3.x'. Null if not ETSI or not found.",
  "policy_oids_present": ["2.23.140.1.2.1", "2.23.140.1.2.2"],
  "in_scope_sha256": [
    "ABCDEF...64 uppercase hex chars, no colons or spaces"
  ],
  "locations_audited": ["Phoenix, Arizona, USA", "London, UK"],
  "subservice_organizations": ["IdenTrust Services, LLC"],
  "qualifications": [
    "Verbatim text of any qualification, exception, or basis-for-qualified-opinion paragraph"
  ],
  "disclosed_matters": [
    {
      "item": 1,
      "topic": "Short topic label if present (e.g. 'Certificate Content'), else null",
      "summary": "One sentence summary of the matter",
      "bugzilla_ids": ["1972745"],
      "certificate_count": 443453,
      "self_reported": true
    }
  ]
}

Extraction rules:
- opinion_type: 'unqualified' = 'fairly stated in all material respects'; 'qualified' = 'except for' or 'Basis for Qualified Opinion'; 'disclaimer' = 'unable to obtain'; 'adverse' = 'do not present fairly'
- audit_framework: 'WebTrust' if letter mentions WebTrust seal or CPA Canada; 'ETSI' if letter mentions ETSI EN 319 or ACAB'c AAL template
- etsi_aal_version: look for version markers like 'CAB-Forum_AAL_Template...V3.5' in headers/footers, or explicit version statements
- policy_oids_present: extract any CA/B Forum OIDs of the form 2.23.140.x.x.x that appear in the letter text — these confirm scope coverage per CCADB Policy §5.2 item 14
- in_scope_sha256: fingerprints listed in Attachment A/B or in-scope appendices. Exactly 64 uppercase hex chars. Return [] if none found in extracted text.
- locations_audited: physical locations mentioned as audited (data centers, offices)
- subservice_organizations: any third-party organizations whose controls the CA relies on (e.g. HSM providers, RA operators listed as subservice orgs)
- disclosed_matters: incidents in 'Other Matter/Matters' section (BDO format) OR 'Appendix D' disclosure table (EY format)
- self_reported: true if the matter text says the CA 'disclosed' it; false if 'identified by' external party or root program
- bugzilla_ids: extract from 'Mozilla Bug #XXXXXXX' or '(#XXXXXXX)'
- certificate_count: number of affected certs if stated, else null
- Return null (not empty string) for missing scalar fields; [] for missing array fields

AUDIT LETTER TEXT (front pages + back pages of document):
"""


def _call_llm(text, api_key, max_tokens=1500):
    """
    Call Claude Haiku to extract structured data from audit letter text.
    Returns parsed JSON dict or None on failure.
    """
    body = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": AUDIT_EXTRACT_PROMPT + text}],
    }).encode()

    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        raw = data["content"][0]["text"].strip()
        # Strip any accidental markdown fences
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        return {"_llm_error": str(e)}


def _extract_front_pages(pdf_bytes, max_pages=20):
    """
    Extract text from a PDF, returning the pages most relevant to the
    audit opinion and incident disclosures.

    Strategy:
    - Always include pages 1-6 (opinion, Other Matter section)
    - Always include the last 6 pages (Appendix D in EY/GTS format sits late)
    - Deduplicate overlapping page ranges
    - Cap total text sent to LLM at ~7000 chars to keep Haiku cost low

    Returns (text, total_page_count) or (None, 0) on failure.
    """
    if not HAS_PDFPLUMBER:
        return None, 0
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total = len(pdf.pages)
            all_text = [p.extract_text() or "" for p in pdf.pages]

        # Always include first 6 and last 6 pages (deduplicated)
        front_idx = list(range(min(6, total)))
        back_idx  = list(range(max(0, total - 6), total))
        keep_idx  = sorted(set(front_idx + back_idx))

        selected = "\n".join(all_text[i] for i in keep_idx)
        return selected, total
    except Exception as e:
        print(f"    WARNING: PDF text extraction failed: {e}", file=__import__("sys").stderr)
        return None, 0


def parse_audit_pdf(pdf_bytes, api_key=None):
    """
    Extract structured fields from a WebTrust or ETSI audit letter PDF.

    Uses Claude Haiku to parse the extracted text — handles all auditor
    template variants (BDO 'Other Matter', EY 'Appendix D', ETSI letters,
    non-English documents) without brittle regex.

    Falls back to a minimal metadata-only result if no api_key is provided
    or if the LLM call fails.

    Returns dict with:
      auditor_firm        str | None
      ca_name_from_pdf    str | None
      period_start        str | None
      period_end          str | None
      opinion_type        'unqualified' | 'qualified' | 'adverse' |
                          'disclaimer' | 'unknown'
      audit_criteria      str | None   (e.g. 'WebTrust ... Version 2.2.2')
      in_scope_sha256     list[str]    (64-char uppercase hex fingerprints)
      qualifications      list[str]
      disclosed_matters   list[dict]  {item, topic, summary, bugzilla_ids,
                                       certificate_count}
      pages               int
      text_length         int
      parse_error         str | None
      llm_used            bool
    """
    if not HAS_PDFPLUMBER:
        return {"parse_error": "pdfplumber not installed", "llm_used": False}

    front_text, page_count = _extract_front_pages(pdf_bytes)
    if front_text is None:
        return {"parse_error": "pdf extraction failed", "llm_used": False}

    # NOTE: actual slicing is done below based on document length
    base = {
        "pages": page_count,
        "text_length": len(front_text),
        "parse_error": None,
        "llm_used": False,
    }

    if not api_key:
        return {**base, "parse_error": "no api_key — metadata only"}

    # Strategy: front 8000 chars captures opinion + Other Matter for most letters.
    # For longer reports (GTS Appendix D at page 16), append the last 3000 chars.
    front_slice = front_text[:8000]
    if len(front_text) > 8000:
        llm_input = front_slice + "\n\n[...]\n\n" + front_text[-3000:]
    else:
        llm_input = front_slice

    llm_result = _call_llm(llm_input, api_key)

    if not llm_result or "_llm_error" in llm_result:
        return {**base,
                "parse_error": llm_result.get("_llm_error", "llm call failed")}

    # Validate and normalise SHA-256 fingerprints — must be exactly 64
    # uppercase hex chars (ALV format requirement §5.2.3)
    raw_fps = llm_result.get("in_scope_sha256") or []
    valid_fps = [
        fp.upper().replace(":", "").replace(" ", "")
        for fp in raw_fps
        if re.fullmatch(r"[0-9A-Fa-f]{64}", fp.replace(":", "").replace(" ", ""))
    ]

    # Validate policy OIDs — must match known CA/B Forum OID pattern
    raw_oids = llm_result.get("policy_oids_present") or []
    valid_oids = [
        oid.strip() for oid in raw_oids
        if re.fullmatch(r"[\d.]{10,30}", oid.strip())
    ]

    return {
        "auditor_firm":             llm_result.get("auditor_firm"),
        "ca_name_from_pdf":         llm_result.get("ca_name"),
        "period_start":             llm_result.get("period_start"),
        "period_end":               llm_result.get("period_end"),
        "opinion_type":             llm_result.get("opinion_type", "unknown"),
        "audit_framework":          llm_result.get("audit_framework"),
        "audit_criteria":           llm_result.get("audit_criteria"),
        "etsi_aal_version":         llm_result.get("etsi_aal_version"),
        "policy_oids_present":      valid_oids,
        "in_scope_sha256":          valid_fps,
        "locations_audited":        llm_result.get("locations_audited") or [],
        "subservice_organizations": llm_result.get("subservice_organizations") or [],
        "qualifications":           llm_result.get("qualifications") or [],
        "disclosed_matters":        llm_result.get("disclosed_matters") or [],
        "pages":                    page_count,
        "text_length":              len(front_text),
        "parse_error":              None,
        "llm_used":                 True,
    }


# ---------------------------------------------------------------------------
# Cross-checks: ALV-equivalent + things ALV can't do
# ---------------------------------------------------------------------------


def build_root_coverage_map(all_ccadb_records):
    """
    Build a per-CA root coverage map from ALL CCADB records (trusted + removed).
    This is the ground truth about audit regime architecture — done once at
    pipeline startup, passed into profile building.

    Returns dict: ca_owner -> {
        'total_roots'         : int
        'roots_with_url'      : int
        'roots_without_url'   : int
        'unaudited_fps'       : list[str]   root FPs with no audit URL
        'url_groups'          : {url: [fp, ...]}  which roots share each letter
        'distinct_url_count'  : int
    }
    """
    from collections import defaultdict

    def is_trusted_root(r):
        if r.get("Certificate Record Type") != "Root Certificate":
            return False
        for s in ["Apple Status", "Chrome Status",
                  "Microsoft Status", "Mozilla Status"]:
            if r.get(s, "").strip() == "Included":
                return True
        return False

    trusted = [r for r in all_ccadb_records if is_trusted_root(r)]
    result = defaultdict(lambda: {
        "total_roots": 0,
        "roots_with_url": 0,
        "roots_without_url": 0,
        "unaudited_fps": [],
        "url_groups": defaultdict(list),
        "distinct_url_count": 0,
    })

    for r in trusted:
        ca = normalize_ca_owner(r.get("CA Owner", "").strip())
        if not ca:
            continue
        fp = r.get("SHA-256 Fingerprint", "").upper().replace(":", "").replace(" ", "")
        d = result[ca]
        d["total_roots"] += 1

        assigned_url = None
        for prefix in ["TLS BR", "Standard"]:
            url = r.get(f"{prefix} Audit URL", "").strip()
            if url and is_fetchable_url(url):
                assigned_url = url
                break

        if assigned_url:
            d["roots_with_url"] += 1
            if len(fp) == 64:
                d["url_groups"][assigned_url].append(fp)
        else:
            d["roots_without_url"] += 1
            if len(fp) == 64:
                d["unaudited_fps"].append(fp)

    # Finalise
    for ca, d in result.items():
        d["distinct_url_count"] = len(d["url_groups"])
        d["url_groups"] = dict(d["url_groups"])  # convert defaultdict

    return dict(result)


def crosscheck_fingerprints(pdf_result, ccadb_roots_for_url,
                            root_coverage_map_entry,
                            all_ca_fps=None,
                            global_fp_type=None,
                            cross_signed_fps=None):
    """
    Two-layer fingerprint check, with an optional Layer 1b for cross-signs.

    Layer 1 — per-engagement accuracy:
      Are all TLS-relevant trusted roots for this CA listed in the letter?
      A TLS BR audit letter covers TLS compliance only. The expected set is
      restricted to roots where TLS Capable = True AND Mozilla or Chrome
      Status = Included. Non-TLS roots (Code Signing, S/MIME, Client Auth,
      Timestamping, Document Signing) and Microsoft-only roots are excluded.

      engagement_fps_missing = TLS-relevant roots absent from letter.
      engagement_fps_extra   = FPs in letter not matching any trusted root.
        Subclassified into:
          engagement_fps_extra_disclosed   = match a CCADB intermediate (normal)
          engagement_fps_extra_undisclosed = not in CCADB at all (potential finding)

    Layer 1b — cross-signed certificate enumeration (CCADB Policy §5.1):
      Cross-signed CA certificates MUST be included in all relevant audit
      statements of the entity that performed the cross-signing (the issuer).
      cross_signed_fps: set of SHA-256 fps of active cross-signed intermediates
      that this CA issued. Missing from the letter = §5.1 gap.

    Layer 2 — ecosystem coverage:
      Are there trusted roots with no audit URL at all?

    all_ca_fps:    dict fp->cert_type for this CA's CCADB records.
    global_fp_type: dict fp->cert_type across ALL CCADB records — used to
                   correctly classify sub-operator intermediates registered
                   under a different CA owner (e.g. reference entity under reference entity).
    """
    letter_fps = set(
        fp.upper() for fp in (pdf_result.get("in_scope_sha256") or [])
    )

    # Layer 1: TLS-relevant roots only.
    # Restrict to: TLS Capable = True AND (Mozilla = Included OR Chrome = Included).
    engagement_fps = set()
    for r in ccadb_roots_for_url:
        fp = r.get("SHA-256 Fingerprint", "").upper().replace(":", "").replace(" ", "")
        if len(fp) != 64:
            continue
        tls_capable = r.get("TLS Capable", "").strip().lower() == "true"
        in_tls_store = (
            r.get("Mozilla Status", "").strip() == "Included" or
            r.get("Chrome Status", "").strip() == "Included"
        )
        if tls_capable and in_tls_store:
            engagement_fps.add(fp)

    eng_matched = sorted(letter_fps & engagement_fps)
    eng_missing = sorted(engagement_fps - letter_fps)

    # Classify extra FPs using the CA's own records first, then the global
    # lookup to catch sub-operator intermediates from other CA owners.
    extra_fps    = letter_fps - engagement_fps
    ca_known     = all_ca_fps or {}
    glb_known    = global_fp_type or {}
    eng_extra_intermediates = sorted(
        fp for fp in extra_fps
        if ca_known.get(fp) == "Intermediate Certificate"
        or glb_known.get(fp) == "Intermediate Certificate"
    )
    inter_set = set(eng_extra_intermediates)
    eng_extra_old_roots = sorted(
        fp for fp in extra_fps
        if fp not in inter_set
        and (ca_known.get(fp) == "Root Certificate"
             or glb_known.get(fp) == "Root Certificate")
    )
    eng_extra_undisclosed = sorted(
        fp for fp in extra_fps
        if fp not in ca_known and fp not in glb_known
    )
    # Keep combined lists for backward compat
    eng_extra_disclosed = sorted(eng_extra_intermediates + eng_extra_old_roots)
    eng_extra           = sorted(extra_fps)

    # Layer 1b: cross-signed certificate enumeration (§5.1).
    # The issuing CA's audit letter must list the fingerprints of any active
    # cross-signed intermediates it issued, even though those certs are owned
    # by a different CA. Missing = direct §5.1 gap.
    xs_fps = set(cross_signed_fps or [])
    xs_missing = sorted(xs_fps - letter_fps)  # cross-signed fps absent from letter
    xs_present = sorted(xs_fps & letter_fps)  # cross-signed fps confirmed in letter
    xs_gap = bool(xs_missing)

    if not engagement_fps or not letter_fps:
        engagement_accurate = None
    elif eng_matched and eng_missing:
        engagement_accurate = False  # matched some, missed others — clear gap
    elif not eng_missing:
        engagement_accurate = True   # matched everything expected
    else:
        engagement_accurate = None   # matched nothing — ambiguous scope

    # Layer 2: ecosystem coverage (from pre-built map)
    cov = root_coverage_map_entry or {}
    n_total   = cov.get("total_roots", 0)
    n_with    = cov.get("roots_with_url", 0)
    n_without = cov.get("roots_without_url", 0)
    unaudited = cov.get("unaudited_fps", [])
    n_letters = cov.get("distinct_url_count", 0)

    regime = "multi" if n_letters > 1 else "single" if n_letters == 1 else "none"

    return {
        "engagement_roots_expected":       len(engagement_fps),
        "engagement_fps_in_letter":        len(letter_fps),
        "engagement_fps_matched":          len(eng_matched),
        "engagement_fps_missing":          eng_missing,
        "engagement_fps_extra":                eng_extra,
        "engagement_fps_extra_disclosed":      eng_extra_disclosed,       # in CCADB (any type)
        "engagement_fps_extra_intermediates":  eng_extra_intermediates,   # CCADB intermediate
        "engagement_fps_extra_old_roots":      eng_extra_old_roots,       # CCADB root, not trusted
        "engagement_fps_extra_undisclosed":    eng_extra_undisclosed,     # not in CCADB at all
        "engagement_accurate":             engagement_accurate,
        "ca_total_roots":       n_total,
        "ca_roots_with_url":    n_with,
        "ca_roots_without_url": n_without,
        "ca_unaudited_fps":     unaudited,
        "ca_audit_regime":      regime,
        # Layer 1b — §5.1 cross-signed certificate audit enumeration
        "cross_signed_fps_expected": sorted(xs_fps),
        "cross_signed_fps_missing":  xs_missing,
        "cross_signed_fps_present":  xs_present,
        "cross_signed_gap":          xs_gap,
    }


def crosscheck_incident_disclosure(pdf_result, bugzilla_bugs, ca_name,
                                    ccadb_period_start=None, ccadb_period_end=None,
                                    bugs_by_ca=None):
    """
    CCADB Policy §5.2 item 13: the audit letter MUST list all incidents
    open in Bugzilla during the audit period.

    We compare Bugzilla IDs mentioned in the letter against bugs filed
    for this CA during the audit period.

    Parameters
    ----------
    bugzilla_bugs   : list[dict]  all bugs (fallback only — prefer bugs_by_ca)
    ca_name         : str         canonical CCADB CA owner name
    ccadb_period_*  : date | None from CCADB metadata (fallback if PDF parse failed)
    bugs_by_ca      : dict | None {ca_owner: [{id, filed, ...}]} — preferred source.
                      When provided, avoids the weak summary-prefix CA matching used
                      in the fallback path and uses the same canonical mapping that
                      build_bug_retrospective uses, ensuring consistency.

    Returns dict:
      period_start_used   : str
      period_end_used     : str
      bugs_in_period      : list[int]   bug IDs filed during audit period
      disclosed_in_letter : list[str]   bug IDs mentioned in letter
      undisclosed_bugs    : list[int]   in period but NOT in letter
      disclosure_rate     : float | None  % of period bugs mentioned in letter
      note                : str | None
    """
    # Resolve audit period dates — prefer PDF parse, fall back to CCADB metadata
    # Delegate to the module-level _try_parse_date which is the canonical
    # superset of all format lists used across this file.
    _try_parse = _try_parse_date

    p_start = _try_parse(pdf_result.get("period_start")) or ccadb_period_start
    p_end   = _try_parse(pdf_result.get("period_end"))   or ccadb_period_end

    if not p_start or not p_end:
        return {"note": "audit period could not be determined", "disclosure_rate": None}

    # Collect bug IDs for this CA during the audit period.
    # Prefer bugs_by_ca (canonical mapping from fetch_incidents.py) over the
    # fallback summary-prefix matcher, which false-positives on shared name
    # prefixes (e.g. "BDO International" matching "BDO Consulting" bugs).
    period_bug_ids = []
    if bugs_by_ca is not None:
        for bug in bugs_by_ca.get(ca_name, []):
            filed = bug.get("filed", "")
            try:
                filed_date = date.fromisoformat(filed)
            except (ValueError, TypeError):
                continue
            if p_start <= filed_date <= p_end:
                period_bug_ids.append(bug["id"])
    else:
        # Fallback: scan all bugs with summary prefix matching.
        # Less accurate — use only when bugs_by_ca is unavailable.
        for bug in (bugzilla_bugs or []):
            summary = bug.get("summary", "")
            if not _bug_matches_ca(summary, ca_name):
                continue
            created = bug.get("creation_time", "")[:10]  # YYYY-MM-DD
            try:
                created_date = date.fromisoformat(created)
            except ValueError:
                continue
            if p_start <= created_date <= p_end:
                period_bug_ids.append(bug["id"])

    # Collect Bugzilla IDs mentioned in the audit letter
    disclosed_ids = set()
    for matter in (pdf_result.get("disclosed_matters") or []):
        for bz_id in (matter.get("bugzilla_ids") or []):
            try:
                disclosed_ids.add(int(bz_id))
            except (ValueError, TypeError):
                pass

    period_set = set(period_bug_ids)
    undisclosed = sorted(period_set - disclosed_ids)
    disclosure_rate = (
        round(len(disclosed_ids & period_set) / len(period_set) * 100, 1)
        if period_set else None
    )

    return {
        "period_start_used":   p_start.isoformat(),
        "period_end_used":     p_end.isoformat(),
        "bugs_in_period":      sorted(period_bug_ids),
        "disclosed_in_letter": sorted(disclosed_ids),
        "undisclosed_bugs":    undisclosed,
        "disclosure_rate":     disclosure_rate,
        "note": None,
    }


def _bug_matches_ca(summary, ca_name):
    """
    Returns True if a Bugzilla bug summary appears to be about the given CA.
    Bugzilla CA compliance bugs follow the pattern: "CA Name: Description"
    """
    if not summary or not ca_name:
        return False
    # Normalise both for comparison
    norm_summary = summary.lower()
    # Try the most common patterns
    ca_lower = ca_name.lower()
    # Direct prefix match  "reference entity: ..."
    if norm_summary.startswith(ca_lower + ":"):
        return True
    # Some bugs use abbreviations or alternate names — check first word
    ca_first = ca_lower.split()[0]
    if len(ca_first) > 4 and norm_summary.startswith(ca_first):
        return True
    return False


def crosscheck_audit_criteria(pdf_result, stmt_date=None, period_end=None):
    """
    Check whether the cited audit criteria version was current during the
    audit period — specifically at period_end, when coverage closed.

    The audit scheme in effect is what matters: a letter covering a period
    that ended September 2024 should cite the standard current in September 2024,
    not the standard current when the letter was issued months later.

    Uses period_end as primary reference date; falls back to stmt_date if
    period_end is unavailable.

    Returns dict:
      criteria_raw           : str | None
      framework              : 'WebTrust' | 'ETSI' | 'unknown'
      criteria_version       : str | None
      criteria_current       : bool | None  — current *at period_end*
      criteria_current_today : bool | None  — current as of today
      aal_version            : str | None   ETSI only
      aal_current            : bool | None  — current *at period_end*
      aal_current_today      : bool | None  — current as of today
      score_epoch            : str | None   — 'pre_aal'|'aal_v3x'|'post_v35'
      aal_applicable         : bool         — False for pre-AAL letters
    """
    from datetime import date as _date
    criteria    = pdf_result.get("audit_criteria") or ""
    framework   = pdf_result.get("audit_framework") or (
        "WebTrust" if "webtrust" in criteria.lower() else
        "ETSI"     if "etsi"     in criteria.lower() else
        "unknown"
    )
    aal_version = pdf_result.get("etsi_aal_version")

    # Use period_end as reference — the standard must have been current
    # when the audit coverage closed, not when the letter was later issued.
    ref_date    = period_end or stmt_date
    epoch       = get_audit_epoch(ref_date)
    aal_applicable = (epoch in ("aal_v3x", "post_v35")) and framework == "ETSI"
    today_ym    = _date.today().strftime("%Y-%m")

    criteria_version       = None
    criteria_current       = None
    criteria_current_today = None
    aal_current            = None
    aal_current_today      = None

    if framework == "WebTrust" and criteria:
        m = re.search(r"[Vv]ersion\s+([\d.]+)|[Vv]([\d.]+)", criteria)
        if m:
            criteria_version       = m.group(1) or m.group(2)
            criteria_current       = is_webtrust_version_current(criteria_version, ref_date)
            criteria_current_today = is_webtrust_version_current(criteria_version, today_ym)

    elif framework == "ETSI" and criteria:
        m = re.search(r"(EN\s+319\s+[\d]+-[\d]+\s+V[\d.]+|EN\s+319\s+[\d]+-[\d]+)",
                      criteria, re.IGNORECASE)
        if m:
            criteria_version = m.group(1).upper().replace("  ", " ")
            # ETSI standard numbers don't version the same way — current if
            # it mentions a known active ETSI standard number
            criteria_current = any(s in criteria_version
                                   for s in ["EN 319 411-1", "EN 319 411-2",
                                             "EN 319 403"])
            criteria_current_today = criteria_current

    if aal_version:
        aal_current       = is_etsi_aal_current(aal_version, ref_date)
        aal_current_today = is_etsi_aal_current(aal_version, today_ym)
    elif framework == "ETSI" and aal_applicable:
        # In AAL era but no version found — should have one
        aal_current = False
        aal_current_today = False

    return {
        "criteria_raw":            criteria or None,
        "framework":               framework,
        "criteria_version":        criteria_version,
        "criteria_current":        criteria_current,
        "criteria_current_today":  criteria_current_today,
        "aal_version":             aal_version,
        "aal_current":             aal_current,
        "aal_current_today":       aal_current_today,
        "score_epoch":             epoch,
        "aal_applicable":          aal_applicable,
    }


def infer_policy_coverage(audit_criteria, audit_framework):
    """
    Infer CA/B Forum policy OID coverage from the criteria string we already
    extracted — no additional LLM call needed.

    WebTrust letters name criteria like "SSL Baseline" or "TLS Baseline" or
    "Extended Validation". ETSI letters cite specific policy profiles like
    DVCP, OVCP, EVCP, NCP, or standard numbers like TS 119 411-6 (S/MIME).

    Returns dict:
      inferred_oids    : list[str]   CA/B Forum OIDs implied by criteria
      cert_types       : list[str]   human-readable types (e.g. ['TLS DV', 'TLS OV'])
      source           : 'criteria_string'
    """
    if not audit_criteria:
        return {"inferred_oids": [], "cert_types": [], "source": None}

    c = audit_criteria.lower()
    oids = set()
    cert_types = set()

    # --- WebTrust ---
    if audit_framework == "WebTrust":
        # "WebTrust Principles and Criteria for Certification Authorities" is the
        # base WebTrust standard required alongside all BR-specific criteria.
        # When cited as the SOLE criteria (not alongside SSL Baseline / TLS Baseline),
        # it does NOT by itself certify TLS BR compliance — it's the base standard.
        # However, when a CA has TLS-capable roots and only files "WebTrust for CAs"
        # (the base standard) without any TLS BR criteria, that IS a scope gap.
        # So: only count "Principles and Criteria for CAs" (base) as covering TLS DV/OV
        # if it appears alongside a TLS BR criteria string; otherwise let it produce a gap.
        has_tls_br_criteria = any(t in c for t in [
            "ssl baseline", "tls baseline",
            "ssl baseline with network", "tls baseline with",
            "baseline requirements",
        ])
        # SSL/TLS Baseline → DV + OV
        if has_tls_br_criteria:
            oids.update(["2.23.140.1.2.1", "2.23.140.1.2.2"])
            cert_types.update(["TLS DV", "TLS OV"])
        # Extended Validation / EV
        if any(t in c for t in ["extended validation", "ev ssl", "ev guidelines",
                                 "tls ev", "ssl ev"]):
            oids.add("2.23.140.1.1")
            cert_types.add("TLS EV")
        # S/MIME
        if "s/mime" in c or "smime" in c:
            oids.add("2.23.140.1.5.1.1")
            cert_types.add("S/MIME")
        # Code Signing
        if "code signing" in c:
            oids.add("2.23.140.1.4.1")
            cert_types.add("Code Signing")

    # --- ETSI ---
    elif audit_framework == "ETSI":
        # 411-1 = publicly-trusted TLS (DVCP, OVCP, IVCP, NCP, NCP+)
        if "319 411-1" in c:
            # Check for specific policy profiles in the criteria string
            if "dvcp" in c:
                oids.add("2.23.140.1.2.1"); cert_types.add("TLS DV")
            if "ovcp" in c or "ncp+" in c or "ncp +" in c:
                # NCP+ under 411-1 = OV-equivalent for publicly-trusted TLS
                oids.add("2.23.140.1.2.2"); cert_types.add("TLS OV")
            if "ncp" in c and "ncp+" not in c and "ncp +" not in c:
                # NCP (without +) under 411-1 = OV-level natural person certs
                oids.add("2.23.140.1.2.2"); cert_types.add("TLS OV")
            if "ivcp" in c:
                oids.add("2.23.140.1.2.3"); cert_types.add("TLS IV")
            if "evcp" in c or "qevcp" in c:
                oids.add("2.23.140.1.1"); cert_types.add("TLS EV")
            if "qncp-w" in c:
                oids.add("2.23.140.1.2.2"); cert_types.add("TLS OV")
            # If no specific profile named, 411-1 implies at minimum DV+OV
            if not (oids & {"2.23.140.1.2.1","2.23.140.1.2.2","2.23.140.1.1"}):
                oids.update(["2.23.140.1.2.1", "2.23.140.1.2.2"])
                cert_types.update(["TLS DV", "TLS OV"])
        # 411-2 = qualified trust (NCP, NCP+) — code signing context
        if "319 411-2" in c:
            oids.add("2.23.140.1.4.1"); cert_types.add("Code Signing")
        # TS 119 411-6 = S/MIME
        if "119 411-6" in c or "411-6" in c:
            oids.add("2.23.140.1.5.1.1"); cert_types.add("S/MIME")
        # EV guidelines explicitly cited
        if "ev guidelines" in c or "guidelines for the issuance and management of extended" in c:
            oids.add("2.23.140.1.1"); cert_types.add("TLS EV")

    return {
        "inferred_oids": sorted(oids),
        "cert_types":    sorted(cert_types),
        "source":        "criteria_string" if oids else None,
    }


def crosscheck_policy_oids(pdf_result, ca_capabilities, separate_audit_types=None,
                           combined_types=None, **_kwargs):
    """
    Check policy OID coverage by inferring from the criteria string.

    separate_audit_types: cert-type audit letters filed under a DIFFERENT URL
    than the TLS BR letter. The TLS BR letter is not responsible for those
    cert types — they are covered by their own dedicated letter.
    (Code Signing, S/MIME BR, TLS EVG filed at a different URL)

    combined_types: cert-type audit letters whose URL is IDENTICAL to the TLS BR URL.
    CCADB filed the same PDF as both the TLS BR letter and the other cert-type letter.
    The TLS BR letter IS that cert type's letter — one document covers both.
    No gap exists for combined types.

    In both cases, no scope gap is raised because the cert type has audit coverage.
    The distinction matters for accurate classification: separate = two letters,
    combined = one letter covering multiple cert types.

    Returns dict with gaps, covered_by_separate_letter, covered_by_combined_letter, etc.
    """
    criteria  = pdf_result.get("audit_criteria")
    framework = pdf_result.get("audit_framework")
    inferred  = infer_policy_coverage(criteria, framework)

    if not inferred["inferred_oids"] and not ca_capabilities:
        return {"inferred_oids": [], "cert_types": [], "gaps": [],
                "covered_separately": [], "capabilities_match": None,
                "note": "no criteria or capabilities"}

    separate = set(separate_audit_types or [])
    combined = set(combined_types or [])
    # Both separate and combined types have audit coverage — no gap raised.
    # Separate = cert type covered by a different letter at a different URL.
    # Combined = cert type covered by this same letter (one PDF, multiple cert types).
    covered_types = separate | combined
    expected_types = set()
    separately_covered = set()

    if ca_capabilities.get("tls"):
        expected_types.update(["TLS DV", "TLS OV"])
    if ca_capabilities.get("ev"):
        if "TLS EVG" in covered_types:
            separately_covered.add("TLS EV")
        else:
            expected_types.add("TLS EV")
    if ca_capabilities.get("cs"):
        if "Code Signing" in covered_types:
            separately_covered.add("Code Signing")
        else:
            expected_types.add("Code Signing")
    if ca_capabilities.get("smime"):
        if "S/MIME BR" in covered_types:
            # S/MIME BR audit coverage exists — either a dedicated letter or this combined letter.
            separately_covered.add("S/MIME")
        else:
            expected_types.add("S/MIME")

    inferred_types = set(inferred["cert_types"])
    gaps = sorted(expected_types - inferred_types)

    capabilities_match = None
    if expected_types:
        capabilities_match = len(gaps) == 0

    return {
        "inferred_oids":      inferred["inferred_oids"],
        "cert_types":         inferred["cert_types"],
        "capabilities_match": capabilities_match,
        "gaps":               gaps,
        "covered_separately": sorted(separately_covered),
        "note":               None,
    }


def score_audit_letter(profile):
    """
    Compute a quality score (0-100) for an audit letter, scored against
    the standard that was current at the time the letter was issued.

    Dimensions and weights:
      opinion_clarity         (1.5) — opinion type clearly stated
      criteria_currency       (2.0) — criteria version current *at stmt_date*
      template_compliance     (2.0) — ETSI aal_v3x/post_v35 only: AAL current
                                      *at stmt_date*. Not scored pre-AAL.
      disclosure_completeness (3.0) — % Bugzilla bugs in period mentioned.
                                      Only scored for letters from 2023+.
      scope_coverage          (1.5) — criteria implies correct CA capabilities

    score_epoch stored on result so UI can facet by era.
    """
    if not profile.get("pdf_parsed"):
        return {"overall": None, "note": "no pdf parsed"}

    crit      = profile.get("criteria_check") or {}
    stmt_date = profile.get("latest_stmt_date") or ""
    epoch     = crit.get("score_epoch") or get_audit_epoch(stmt_date)
    stmt_ym   = stmt_date[:7] if stmt_date else ""

    scores  = {}
    weights = {}

    # 1. Opinion clarity — timeless
    opinion = profile.get("opinion_type")
    if opinion in ("unqualified", "qualified", "adverse", "disclaimer"):
        scores["opinion_clarity"] = 100
    elif opinion == "unknown":
        scores["opinion_clarity"] = 0
    else:
        scores["opinion_clarity"] = 50
    weights["opinion_clarity"] = 1.5

    # 2. Criteria currency — contemporaneous check
    if crit.get("criteria_current") is True:
        scores["criteria_currency"] = 100
    elif crit.get("criteria_current") is False:
        scores["criteria_currency"] = 0
    else:
        scores["criteria_currency"] = 50
    weights["criteria_currency"] = 2.0

    # 3. ETSI AAL template — only applicable in aal_v3x / post_v35 epochs
    #    Pre-AAL ETSI letters get neutral partial credit (template didn't exist)
    if crit.get("framework") == "ETSI":
        if crit.get("aal_applicable", False):
            if crit.get("aal_current") is True:
                scores["template_compliance"] = 100
            elif crit.get("aal_current") is False:
                scores["template_compliance"] = 0
            else:
                scores["template_compliance"] = 50
            weights["template_compliance"] = 2.0
        elif epoch == "pre_aal":
            scores["template_compliance"] = 50   # neutral — not expected yet
            weights["template_compliance"] = 1.0  # lower weight

    # 4. Incident disclosure completeness — only post-2023 (enforcement era)
    if stmt_ym >= DISCLOSURE_ENFORCED_FROM:
        inc = profile.get("incident_disclosure_check") or {}
        if inc.get("disclosure_rate") is not None:
            scores["disclosure_completeness"] = inc["disclosure_rate"]
            weights["disclosure_completeness"] = 3.0

    # 5. Scope coverage
    oid = profile.get("oid_check") or {}
    if oid.get("capabilities_match") is True:
        scores["scope_coverage"] = 100
        weights["scope_coverage"] = 1.5
    elif oid.get("capabilities_match") is False:
        n_expected = len(oid.get("cert_types", [])) + len(oid.get("gaps", []))
        n_gaps = len(oid.get("gaps", []))
        scores["scope_coverage"] = round((1 - n_gaps / max(n_expected, 1)) * 100, 1)
        weights["scope_coverage"] = 1.5
    elif oid.get("inferred_oids"):
        scores["scope_coverage"] = 75
        weights["scope_coverage"] = 1.0

    if not scores:
        return {"overall": None, "dimensions": {}, "note": "insufficient data"}

    total_weight = sum(weights[k] for k in scores)
    overall = round(
        sum(scores[k] * weights[k] for k in scores) / total_weight, 1
    )

    return {
        "overall":     overall,
        "dimensions":  scores,
        "score_epoch": epoch,
        "note":        None,
    }


def compute_timeline_trends(profile):
    """
    Derive over-time signals from a CA's audit_timeline.
    Called after all PDFs are parsed so timeline entries have parse results.

    Returns dict added to profile["timeline_trends"]:
      letter_count          : int    total letters in history
      years_covered         : int    year span (most recent - oldest)
      auditor_changes       : list   [{year, from, to}]
      auditor_tenure_years  : float  years with current auditor
      criteria_adoption_lag : int|None  days between criteria release and first use
      quality_trend         : str|None  'improving'|'declining'|'stable'|None
      quality_by_year       : {year_str: score}
      disclosure_by_year    : {year_str: rate}
    """
    timeline = profile.get("audit_timeline") or []
    parsed_entries = [e for e in timeline if e.get("letter_parsed")]

    if not timeline:
        return {"letter_count": 0, "note": "no timeline data"}

    # Sort by statement date
    dated = sorted(
        (e for e in timeline if e.get("stmt_date")),
        key=lambda e: e["stmt_date"]
    )
    if not dated:
        return {"letter_count": len(timeline), "note": "no dated entries"}

    oldest_year = int(dated[0]["stmt_date"][:4])
    newest_year = int(dated[-1]["stmt_date"][:4])
    years_covered = newest_year - oldest_year

    # Auditor changes: find transitions
    auditor_changes = []
    prev_auditor = None
    for e in dated:
        aud = e.get("auditor")
        if aud and prev_auditor and aud != prev_auditor:
            auditor_changes.append({
                "year": int(e["stmt_date"][:4]),
                "from_auditor": prev_auditor,
                "to_auditor": aud,
            })
        if aud:
            prev_auditor = aud

    # Current auditor tenure — how long have they been using the current auditor?
    current_auditor = profile.get("primary_auditor")
    auditor_tenure_years = None
    if current_auditor and dated:
        # Find when current auditor first appeared
        first_current = next(
            (e for e in dated if e.get("auditor") == current_auditor), None
        )
        if first_current:
            first_year = int(first_current["stmt_date"][:4])
            auditor_tenure_years = round(newest_year - first_year, 1)

    # Quality scores by year
    quality_by_year = {}
    disclosure_by_year = {}
    for e in dated:
        yr = e["stmt_date"][:4]
        if e.get("quality_score") is not None:
            quality_by_year[yr] = e["quality_score"]
        if e.get("disclosure_rate") is not None:
            disclosure_by_year[yr] = e["disclosure_rate"]

    # Quality trend — compare oldest half vs newest half of scored entries
    scores = [e["quality_score"] for e in dated if e.get("quality_score") is not None]
    quality_trend = None
    if len(scores) >= 3:
        mid = len(scores) // 2
        old_avg = sum(scores[:mid]) / mid
        new_avg = sum(scores[mid:]) / (len(scores) - mid)
        diff = new_avg - old_avg
        if diff > 5:
            quality_trend = "improving"
        elif diff < -5:
            quality_trend = "declining"
        else:
            quality_trend = "stable"

    return {
        "letter_count":          len(dated),
        "years_covered":         years_covered,
        "oldest_stmt_date":      dated[0]["stmt_date"],
        "newest_stmt_date":      dated[-1]["stmt_date"],
        "auditor_changes":       auditor_changes,
        "auditor_tenure_years":  auditor_tenure_years,
        "quality_trend":         quality_trend,
        "quality_by_year":       quality_by_year,
        "disclosure_by_year":    disclosure_by_year,
    }


def compute_auditor_aggregates(profiles):
    """
    Compute per-auditor aggregate signals across all parsed profiles.
    These are the cross-CA patterns root programs can't see from ALV.

    Returns dict: {auditor_name: aggregate_dict}
    """
    from collections import defaultdict

    auditor_data = defaultdict(lambda: {
        "ca_count": 0,
        "parsed_count": 0,
        "opinion_counts": Counter(),
        "fp_coverages": [],
        "disclosure_rates": [],
        "criteria_current_count": 0,
        "criteria_outdated_count": 0,
        "aal_current_count": 0,
        "aal_outdated_count": 0,
        "total_undisclosed_bugs": 0,
        "total_matters_count": 0,
        "quality_scores": [],
        "ca_names": [],
        # Timeline-derived signals
        "tenure_years": [],          # how long each CA has been with this auditor
        "historical_letter_counts": [],  # depth of history per CA
        "quality_trends": Counter(), # improving/declining/stable counts
        # Per-year quality scores across all CAs (for ecosystem trend chart)
        "quality_by_year": defaultdict(list),
        "disclosure_by_year": defaultdict(list),
    })

    for p in profiles:
        auditor = p.get("primary_auditor")
        if not auditor:
            continue

        d = auditor_data[auditor]
        d["ca_count"] += 1
        d["ca_names"].append(p["ca_owner"])

        # Timeline signals — available even without PDF parsing
        trends = p.get("timeline_trends") or {}
        if trends.get("letter_count"):
            d["historical_letter_counts"].append(trends["letter_count"])
        if trends.get("auditor_tenure_years") is not None:
            d["tenure_years"].append(trends["auditor_tenure_years"])
        if trends.get("quality_trend"):
            d["quality_trends"][trends["quality_trend"]] += 1
        for yr, score in (trends.get("quality_by_year") or {}).items():
            d["quality_by_year"][yr].append(score)
        for yr, rate in (trends.get("disclosure_by_year") or {}).items():
            d["disclosure_by_year"][yr].append(rate)

        if not p.get("pdf_parsed"):
            continue

        d["parsed_count"] += 1
        d["opinion_counts"][p.get("opinion_type", "unknown")] += 1
        d["total_matters_count"] += len(p.get("disclosed_matters") or [])

        fp = p.get("fingerprint_check") or {}
        if fp.get("coverage_pct") is not None:
            d["fp_coverages"].append(fp["coverage_pct"])

        inc = p.get("incident_disclosure_check") or {}
        if inc.get("disclosure_rate") is not None:
            d["disclosure_rates"].append(inc["disclosure_rate"])
        d["total_undisclosed_bugs"] += len(inc.get("undisclosed_bugs") or [])

        crit = p.get("criteria_check") or {}
        if crit.get("criteria_current") is True:
            d["criteria_current_count"] += 1
        elif crit.get("criteria_current") is False:
            d["criteria_outdated_count"] += 1
        if crit.get("aal_current") is True:
            d["aal_current_count"] += 1
        elif crit.get("aal_current") is False:
            d["aal_outdated_count"] += 1

        qs = p.get("letter_quality_score") or {}
        if qs.get("overall") is not None:
            d["quality_scores"].append(qs["overall"])

        # Transparency gap signals
        tg = p.get("transparency_gap") or {}
        if tg.get("gap_score") is not None:
            d.setdefault("gap_scores", []).append(tg["gap_score"])
        if tg.get("gap_level") == "high":
            d["high_gap_count"] = d.get("high_gap_count", 0) + 1
        d["total_incidents"]        = d.get("total_incidents", 0) + (tg.get("incident_count") or 0)
        d["total_matters_with_bz"]  = d.get("total_matters_with_bz", 0) + (tg.get("matters_with_bugzilla") or 0)
        d["externally_found_count"] = d.get("externally_found_count", 0) + (tg.get("externally_found") or 0)

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    result = {}
    for auditor, d in sorted(auditor_data.items(), key=lambda x: -x[1]["ca_count"]):
        quality_by_year = {
            yr: avg(scores)
            for yr, scores in sorted(d["quality_by_year"].items())
        }
        disclosure_by_year = {
            yr: avg(rates)
            for yr, rates in sorted(d["disclosure_by_year"].items())
        }

        result[auditor] = {
            "ca_count":               d["ca_count"],
            "parsed_count":           d["parsed_count"],
            "ca_names":               sorted(d["ca_names"]),
            "auditor_country":        AUDITOR_COUNTRY.get(auditor),
            "opinion_counts":         dict(d["opinion_counts"]),
            # Current-letter quality signals
            "avg_fp_coverage":        avg(d["fp_coverages"]),
            "avg_disclosure_rate":    avg(d["disclosure_rates"]),
            "total_undisclosed_bugs": d["total_undisclosed_bugs"],
            "avg_matters_per_ca":     round(d["total_matters_count"] / d["parsed_count"], 1)
                                      if d["parsed_count"] else None,
            "criteria_current_pct":   round(d["criteria_current_count"] /
                                            d["parsed_count"] * 100, 1)
                                      if d["parsed_count"] else None,
            "aal_current_pct":        round(d["aal_current_count"] /
                                            d["parsed_count"] * 100, 1)
                                      if d["parsed_count"] else None,
            "avg_quality_score":      avg(d["quality_scores"]),
            # Transparency gap — clean letter vs known incident history
            "avg_gap_score":          avg(d.get("gap_scores", [])),
            "high_gap_count":         d.get("high_gap_count", 0),
            "total_incidents":        d.get("total_incidents", 0),
            "total_matters_with_bz":  d.get("total_matters_with_bz", 0),
            "externally_found_count": d.get("externally_found_count", 0),
            # Over-time signals
            "avg_tenure_years":       avg(d["tenure_years"]),
            "avg_historical_depth":   avg(d["historical_letter_counts"]),
            "quality_trends":         dict(d["quality_trends"]),
            "quality_by_year":        quality_by_year,
            "disclosure_by_year":     disclosure_by_year,
        }
    return result



def build_bug_retrospective(ca_name, bugs_by_ca, audit_timeline):
    """
    For each Bugzilla incident filed against this CA, determine:
      - Which audit letter periods covered the filing date
      - Whether any of those letters mentioned the bug

    This surfaces the manager's observation: issues that linger undetected
    for years, passing through multiple audit cycles without being caught.

    Parameters
    ----------
    ca_name       : str
    bugs_by_ca    : dict  {ca_owner: [{id, filed, summary, self_reported, whiteboard}]}
    audit_timeline: list  per-profile audit_timeline entries with period dates

    Returns
    -------
    list of dicts, one per bug:
      id              : int
      filed           : str  YYYY-MM-DD
      summary         : str
      self_reported   : bool
      whiteboard      : str
      covering_letters: int   number of audit letters whose period covered the filing date
      mentioned_in    : int   how many of those letters mentioned this bug
      missed_by       : int   covering_letters - mentioned_in
      audit_coverage  : list  [{stmt_date, period_start, period_end, mentioned}]
    """
    ca_bugs = bugs_by_ca.get(ca_name, [])
    if not ca_bugs:
        return []

    # Delegate to the module-level _try_parse_date which is the canonical
    # superset of all format lists used across this file.
    _try_parse = _try_parse_date

    # Build list of (period_start, period_end, stmt_date, mentioned_bz_ids)
    # from the audit timeline entries that have parsed data
    letters = []
    for entry in (audit_timeline or []):
        p_start = _try_parse(entry.get("period_start"))
        p_end   = _try_parse(entry.get("period_end"))
        if not p_start or not p_end:
            # Silently skipping a timeline entry means bugs it covers will appear
            # uncovered. Log so operators can identify malformed CCADB date strings.
            ps_raw = entry.get("period_start", "")
            pe_raw = entry.get("period_end", "")
            if ps_raw or pe_raw:
                import sys as _sys
                print(
                    f"  [retrospective] WARNING: {ca_name}: skipping timeline entry "
                    f"with unparseable dates period_start={ps_raw!r} period_end={pe_raw!r}",
                    file=_sys.stderr,
                )
            continue
        # Collect bug IDs mentioned in this letter
        mentioned = set()
        for matter in (entry.get("disclosed_matters") or []):
            for bz_id in (matter.get("bugzilla_ids") or []):
                try:
                    mentioned.add(int(bz_id))
                except (ValueError, TypeError):
                    pass
        letters.append({
            "stmt_date":   (entry.get("stmt_date") or "")[:10],
            "period_start": p_start,
            "period_end":   p_end,
            "mentioned":    mentioned,
        })

    if not letters:
        return []

    retrospective = []
    for bug in ca_bugs:
        filed_str = bug.get("filed", "")
        try:
            filed_date = date.fromisoformat(filed_str)
        except (ValueError, TypeError):
            continue

        # Which letters had an audit period that covered the filing date?
        coverage = []
        for letter in letters:
            if letter["period_start"] <= filed_date <= letter["period_end"]:
                mentioned = bug["id"] in letter["mentioned"]
                coverage.append({
                    "stmt_date":    letter["stmt_date"],
                    "period_start": letter["period_start"].isoformat(),
                    "period_end":   letter["period_end"].isoformat(),
                    "mentioned":    mentioned,
                })

        covering = len(coverage)
        mentioned_in = sum(1 for c in coverage if c["mentioned"])
        missed_by = covering - mentioned_in

        # Only include bugs that were covered by at least one letter
        # (bugs filed after all audit periods are future obligations, not gaps)
        if covering == 0:
            continue

        retrospective.append({
            "id":             bug["id"],
            "filed":          filed_str,
            "summary":        bug.get("summary", ""),
            "self_reported":  bug.get("self_reported", False),
            "whiteboard":     bug.get("whiteboard", ""),
            "covering_letters": covering,
            "mentioned_in":   mentioned_in,
            "missed_by":      missed_by,
            "audit_coverage": coverage,
        })

    # Sort: most-missed first, then by filing date desc
    retrospective.sort(key=lambda x: (-x["missed_by"], x["filed"]))
    return retrospective


def generate_chart_insights(profiles_list, result, api_key=None):
    """
    Call the LLM once with computed audit stats to generate per-chart
    interpretive sentences. Returns a dict keyed by chart name.
    Falls back to empty dict on any error.
    """
    import os, urllib.request, urllib.error
    if api_key is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {}

    agg = result.get("auditor_aggregates", {})

    # Auditor changes by year
    changes_by_year = {}
    for p in profiles_list:
        for c in (p.get("timeline_trends") or {}).get("auditor_changes", []):
            yr = c.get("year")
            if yr:
                changes_by_year[yr] = changes_by_year.get(yr, 0) + 1
    sorted_years = sorted(changes_by_year.items())

    # Self-report by framework
    wt_self  = [p["self_report_pct"] for p in profiles_list
                if p.get("primary_framework") == "WebTrust" and p.get("self_report_pct") is not None]
    etsi_self = [p["self_report_pct"] for p in profiles_list
                 if p.get("primary_framework") == "ETSI" and p.get("self_report_pct") is not None]
    wt_avg   = round(sum(wt_self)  / len(wt_self),  1) if wt_self  else None
    etsi_avg = round(sum(etsi_self) / len(etsi_self), 1) if etsi_self else None

    # In-period detection
    covered = caught = multi = 0
    for p in profiles_list:
        for r in (p.get("bug_retrospective") or []):
            if r.get("covering_letters", 0) > 0:
                covered += 1
                if r.get("mentioned_in", 0) > 0:
                    caught += 1
                elif r.get("missed_by", 0) >= 2:
                    multi += 1
    det_rate = round(caught / covered * 100) if covered else None

    # Auditor detection by firm
    aud_det = {}
    for p in profiles_list:
        stmt_to_aud = {e["stmt_date"]: e.get("auditor")
                       for e in (p.get("audit_timeline") or []) if e.get("stmt_date")}
        for r in (p.get("bug_retrospective") or []):
            for c in (r.get("audit_coverage") or []):
                aud = stmt_to_aud.get(c["stmt_date"]) or p.get("primary_auditor")
                if not aud: continue
                if aud not in aud_det:
                    aud_det[aud] = {"caught": 0, "total": 0}
                aud_det[aud]["total"] += 1
                if c.get("mentioned"):
                    aud_det[aud]["caught"] += 1
    aud_rates = {k: round(v["caught"]/v["total"]*100)
                 for k, v in aud_det.items() if v["total"] >= 5}

    # ETSI AAL — version distribution with timeline context
    etsi_parsed = [p for p in profiles_list
                   if p.get("primary_framework") == "ETSI" and p.get("pdf_parsed")]
    v35 = sum(1 for p in etsi_parsed
              if (p.get("criteria_check") or {}).get("aal_version") == "3.5")
    v34 = sum(1 for p in etsi_parsed
              if (p.get("criteria_check") or {}).get("aal_version") == "3.4")
    v33 = sum(1 for p in etsi_parsed
              if (p.get("criteria_check") or {}).get("aal_version") == "3.3")
    older = len(etsi_parsed) - v35 - v34 - v33 - sum(
        1 for p in etsi_parsed
        if (p.get("criteria_check") or {}).get("aal_version") is None
    )
    # Oldest version in use
    versions_in_use = sorted(set(
        (p.get("criteria_check") or {}).get("aal_version")
        for p in etsi_parsed
        if (p.get("criteria_check") or {}).get("aal_version")
    ))

    stats = {
        "auditor_changes_by_year": sorted_years,
        "wt_self_report_pct": wt_avg,
        "etsi_self_report_pct": etsi_avg,
        "in_period_detection_rate": det_rate,
        "in_period_caught": caught,
        "in_period_covered": covered,
        "multi_cycle_misses": multi,
        "auditor_detection_rates": aud_rates,
        "etsi_aal": {
            "v35_adopted": v35,
            "v34_current": v34,
            "v33_outdated": v33,
            "older_versions": older,
            "total_etsi_parsed": len(etsi_parsed),
            "versions_in_use": versions_in_use,
            "timeline_note": "V3.4 was mandatory 2022-March2026; V3.5 mandatory from March2026; V3.3 was superseded in 2022; V3.1 in 2020",
        },
        "total_profiles": len(profiles_list),
        "parsed_letters": sum(1 for p in profiles_list if p.get("pdf_parsed")),
    }

    prompt = f"""You are writing one-sentence analyst insights for specific charts in the WebPKI Observatory audit tab.
Each insight appears directly below its chart to help readers interpret what they see.
Write in plain declarative prose. Do not start with "This chart" or "The data shows".
Be specific — use the numbers provided. Do not hedge excessively but do not overstate causation.

Data from this build:
{json.dumps(stats, indent=2)}

Return a JSON object with exactly these keys and one sentence per value:

{{
  "auditor_changes": "One sentence interpreting the auditor changes by year chart — mention the most notable year if there is a clear spike, what drove it if inferable from context (e.g. Entrust distrust), and what a normal rate looks like.",
  "self_report": "One sentence comparing WebTrust vs ETSI self-report rates and what the difference might suggest — be careful not to overstate causation.",
  "detection_rate": "One sentence on the overall in-period detection rate and what the per-auditor variation means for the ecosystem.",
  "etsi_aal": "One sentence on which AAL template versions ETSI CAs are actually using. Mention the oldest version still in use, how outdated it is relative to the timeline, and whether V3.5 adoption has started. Be concrete — name the versions and the gap. Do not say 'suggesting slow migration' — state the facts directly."
}}

Return only the JSON object, no markdown fences."""

    payload = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": 500,
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        raw = body["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(raw), stats
    except Exception as e:
        print(f"  [chart_insights] WARNING: LLM call failed — {e}")
        return {}, stats


def build_audit_profiles(ccadb_records, fetch_pdfs=True, max_pdfs=None,
                         api_key=None, bugzilla_bugs=None, bugs_by_ca=None, verbose=True):
    """
    Build per-CA-owner audit profiles from CCADB root certificate records.

    Parameters
    ----------
    ccadb_records : list[dict]   rows from CCADB CSV (all cert types)
    fetch_pdfs    : bool          whether to fetch & parse PDF audit letters
    max_pdfs      : int | None    cap on PDF fetches (None = unlimited)
    verbose       : bool

    Returns
    -------
    dict with keys:
      profiles       : {ca_owner: profile_dict}
      auditor_stats  : {auditor_name: {ca_count, ca_owners: []}}
      framework_stats: {framework: count}
      staleness_buckets
      generated_at
    """
    today = date.today()

    STORE_FIELDS = {
        "apple":     "Apple Status",
        "chrome":    "Chrome Status",
        "microsoft": "Microsoft Status",
        "mozilla":   "Mozilla Status",
    }
    REMOVED_VALUES = {"Removed", "Disabled", "Blocked"}

    def root_store_status(r):
        """
        Returns (currently_trusted: bool, stores: list[str], removed_from: list[str]).
        Uses exact equality — 'Not Yet Included' and 'Not Included' are NOT trusted.
        """
        trusted_in = []
        removed_from = []
        for store, field in STORE_FIELDS.items():
            val = r.get(field, "").strip()
            if val == "Included":
                trusted_in.append(store)
            elif val in REMOVED_VALUES:
                removed_from.append(store)
        return bool(trusted_in), trusted_in, removed_from

    def is_root(r):
        return r.get("Certificate Record Type") == "Root Certificate"

    # Split into three clean sets — used for filtering and cross-checks
    all_roots       = [r for r in ccadb_records if is_root(r)]
    trusted_roots   = []   # currently Included in at least one store
    distrusted_roots = []  # Removed/Disabled/Blocked from all stores that had them

    for r in all_roots:
        is_trusted, trusted_in, removed_from = root_store_status(r)
        if is_trusted:
            trusted_roots.append(r)
        elif removed_from:
            distrusted_roots.append(r)
        # else: "Not Included" / "Not Yet Included" — never included, skip entirely

    if verbose:
        print(f"  [audits] {len(trusted_roots)} currently trusted root records "
              f"({len(distrusted_roots)} removed/distrusted, "
              f"{len(all_roots) - len(trusted_roots) - len(distrusted_roots)} never included)")

    # Build CA owner → trusted root records index for per-URL fingerprint checks.
    # Also build per-URL root index (which roots share each audit letter URL).
    # Also build CA → all CCADB records (roots + intermediates) for FP classification.
    ca_root_records = defaultdict(list)
    ca_all_fps      = defaultdict(dict)  # ca -> {fp: cert_type} for all CCADB records
    url_root_records = defaultdict(list)  # url -> [root records assigned to it]
    for r in trusted_roots:
        ca = normalize_ca_owner(r.get("CA Owner", "").strip())
        if ca:
            ca_root_records[ca].append(r)
        # Index this root under EVERY letter URL it is assigned to across all
        # letter types. A CA's roots are distributed across multiple letters
        # (TLS BR, TLS EVG, S/MIME BR, Code Signing, NetSec, Standard) and
        # each letter only covers the subset of roots pointing to its URL.
        seen_urls = set()
        for prefix in ["TLS BR", "Standard", "NetSec", "TLS EVG",
                       "Code Signing", "S/MIME BR"]:
            url = r.get(f"{prefix} Audit URL", "").strip()
            if url and is_fetchable_url(url) and url not in seen_urls:
                url_root_records[url].append(r)
                seen_urls.add(url)

    # Index ALL CCADB records (including intermediates) by CA owner for FP lookup.
    # Also build global_fp_type — fp -> cert_type across all CA owners, so
    # sub-operator intermediates registered under a different CA owner are
    # correctly classified rather than landing in engagement_fps_extra_undisclosed.
    global_fp_type = {}
    for r in ccadb_records:
        ca = normalize_ca_owner(r.get("CA Owner", "").strip())
        fp = r.get("SHA-256 Fingerprint", "").upper().replace(":", "").replace(" ", "")
        cert_type = r.get("Certificate Record Type", "")
        if ca and len(fp) == 64:
            ca_all_fps[ca][fp] = cert_type
        if len(fp) == 64 and fp not in global_fp_type:
            global_fp_type[fp] = cert_type

    # Build cross_signed_fps_by_issuer:
    #   issuing_ca_owner -> set of SHA-256 fingerprints of cross-signed
    #   intermediate certificates that CA issued.
    #
    # Per CCADB Policy §5.1: cross-signed CA certificates MUST be included in
    # all relevant audit statements of the entity that possesses the private key
    # that performed the cross-signing (i.e. the issuer, not the subject).
    #
    # A cross-sign is an Intermediate Certificate whose Subject Key Identifier
    # matches the SKI of a trusted Root Certificate owned by a *different*
    # CA Owner — meaning the subject key (and thus the trust) belongs to one
    # CA but the signature (and thus the audit obligation) belongs to another.
    #
    # We only track active cross-signs: unexpired intermediates currently
    # trusted in at least one store. Historical (expired / fully removed)
    # cross-signs are excluded because their audit periods have passed.
    #
    # IMPORTANT: The issuer is identified by the CA Owner field on the
    # intermediate record itself — NOT by looking up who currently owns the
    # parent fingerprint in ca_all_fps. The parent-fp lookup is wrong because
    # it reflects post-acquisition ownership (e.g. reference entity now owns reference entity
    # root records, so looking up an Entrust-signed cert's parent fp incorrectly
    # returns reference entity). The CA Owner field on the intermediate record is set by
    # the CA that actually filed it and is the authoritative issuer identity.

    _root_ski_to_owner = {}
    for r in trusted_roots:
        ski = r.get("Subject Key Identifier", "").strip().upper()
        if ski:
            _root_ski_to_owner[ski] = normalize_ca_owner(r.get("CA Owner", "").strip())

    cross_signed_fps_by_issuer = defaultdict(set)  # issuer_ca -> {fp, ...}

    from datetime import datetime as _dt, timezone as _tz
    _now = _dt.now(_tz.utc)

    for r in ccadb_records:
        if r.get("Certificate Record Type") != "Intermediate Certificate":
            continue
        ski = r.get("Subject Key Identifier", "").strip().upper()
        if not ski or ski not in _root_ski_to_owner:
            continue  # SKI doesn't match any trusted root — not a cross-sign

        subject_owner = _root_ski_to_owner[ski]  # the CA whose key is cross-signed

        # Issuer = CA Owner on THIS record — the CA that filed/issued this cert.
        # Do NOT use parent_fp lookups via ca_all_fps: those reflect current
        # post-acquisition CCADB ownership, not the historical signing entity.
        issuer_owner = normalize_ca_owner(r.get("CA Owner", "").strip())
        if not issuer_owner:
            continue

        subject_owner = _root_ski_to_owner[ski]  # already normalized above

        # Intra-org check: normalized names must differ.
        # normalize_ca_owner already collapses known CCADB capitalization
        # variants (reference entity→reference entity, SECOM variants, etc.) so direct equality
        # is sufficient. Intra-org cross-signs (e.g. reference entity→reference entity,
        # reference entity→GlobalSign) are naturally excluded because
        # the CA Owner field on those records will match the subject_owner.
        if issuer_owner == subject_owner:
            continue  # intra-org — not a cross-sign for audit purposes

        # Check not revoked (CCADB tracks revocation explicitly for intermediates)
        revocation = r.get("Revocation Status", "").strip()
        if revocation in ("Revoked", "Parent Cert Revoked"):
            continue

        # Check not expired
        valid_to = r.get("Valid To (GMT)", "").strip()
        if valid_to:
            try:
                expiry = _dt.strptime(valid_to, "%Y.%m.%d").replace(tzinfo=_tz.utc)
                if expiry < _now:
                    continue  # expired — audit obligation has passed
            except ValueError:
                pass

        fp = r.get("SHA-256 Fingerprint", "").upper().replace(":", "").replace(" ", "")
        if len(fp) == 64:
            cross_signed_fps_by_issuer[issuer_owner].add(fp)

    if cross_signed_fps_by_issuer:
        total_xs = sum(len(v) for v in cross_signed_fps_by_issuer.values())
        print(f"  [audits] {len(cross_signed_fps_by_issuer)} CAs issued active cross-signed "
              f"certs ({total_xs} total) — §5.1 audit enumeration check enabled")

    # Build ecosystem-level root coverage map — which roots have audit URLs,
    # which have multiple audit engagements, which have none.
    # Done once here using all CCADB records so the model is correct.
    root_coverage_map = build_root_coverage_map(ccadb_records)

    # Build CA owner → country from CCADB (using the first root record's Country field)
    ca_country_map = {}
    for r in trusted_roots:
        ca = normalize_ca_owner(r.get("CA Owner", "").strip())
        country = r.get("Country", "").strip()
        if ca and country and ca not in ca_country_map:
            ca_country_map[ca] = country

    # Load incident data for enrichment — incidents.json is produced by
    # fetch_incidents.py and is always available in CI
    incident_map = {}   # ca_owner -> {n, self, ext, selfPct}
    incident_path = OUTPUT_DIR / "incidents.json"
    if incident_path.exists():
        try:
            inc_data = json.loads(incident_path.read_text())
            for entry in inc_data.get("cas", []):
                incident_map[entry["ca"]] = entry
        except Exception as e:
            # If incidents.json fails to load, all per-CA incident_count fields will be
            # null in audit output — a silent data quality regression. Log prominently.
            print(f"  ERROR: failed to load incidents.json: {e}", file=sys.stderr)
            print(f"  WARNING: incident_count, self_report_pct will be null for all CAs", file=sys.stderr)

    # Build per-store exclusive CA map for the governance link-back.
    # A CA is "store-exclusive" if it appears in only one root program —
    # these are the ones with zero cross-program oversight pressure.
    ca_trusted_stores = defaultdict(set)
    for r in trusted_roots:
        ca = normalize_ca_owner(r.get("CA Owner", "").strip())
        if not ca: continue
        _, stores, _ = root_store_status(r)
        for s in stores:
            ca_trusted_stores[ca].add(s)

    exclusive_store = {}   # ca -> store name if exclusive to one store, else None
    for ca, stores in ca_trusted_stores.items():
        exclusive_store[ca] = list(stores)[0] if len(stores) == 1 else None

    # Build per-CA owner profile — from trusted roots only
    raw_profiles = defaultdict(lambda: {
        "auditors_raw": Counter(),
        "frameworks_raw": Counter(),
        "stmt_dates": [],
        "period_end_dates": [],
        "period_start_dates": [],
        "audit_urls": [],           # (url_type, url)
        "root_count": 0,
        "no_audit_roots": 0,
        "stores": set(),
    })

    for r in trusted_roots:
        ca = normalize_ca_owner(r.get("CA Owner", "").strip())
        if not ca:
            continue
        p = raw_profiles[ca]
        p["root_count"] += 1

        aud = r.get("Auditor", "").strip()
        if aud:
            p["auditors_raw"][aud] += 1

        # Collect frameworks and dates across all audit types
        # Priority order: TLS BR > Standard > NetSec
        best_type = None
        best_stmt = None
        best_pend = None
        best_pstart = None

        for prefix in ["TLS BR", "Standard", "NetSec", "TLS EVG",
                       "Code Signing", "S/MIME BR"]:
            t = r.get(f"{prefix} Audit Type", "").strip()
            stmt = parse_ccadb_date(r.get(f"{prefix} Audit Statement Date", ""))
            pend = parse_ccadb_date(r.get(f"{prefix} Audit Period End Date", ""))
            pstart = parse_ccadb_date(r.get(f"{prefix} Audit Period Start Date", ""))
            url = r.get(f"{prefix} Audit URL", "").strip()

            if t:
                p["frameworks_raw"][t] += 1

            # Track the most recent statement date across all audit types
            if stmt:
                p["stmt_dates"].append(stmt)
                if best_stmt is None or stmt > best_stmt:
                    best_stmt = stmt
                    best_type = t
            if pend:
                p["period_end_dates"].append(pend)
                if best_pend is None or pend > best_pend:
                    best_pend = pend
            if pstart:
                p["period_start_dates"].append(pstart)
                if best_pstart is None or pstart < best_pstart:
                    best_pstart = pstart

            if url and (url, prefix) not in [(u, tp) for tp, u in p["audit_urls"]]:
                p["audit_urls"].append((prefix, url))

        if not p["stmt_dates"]:
            p["no_audit_roots"] += 1

        # Track which stores include this CA (for exclusive_store linkback)
        _, stores, _ = root_store_status(r)
        for s in stores:
            p["stores"].add(s)

    # --- Second pass: collect ALL historical audit letters from ALL root records ---
    # Trusted roots contain current letters; removed/distrusted roots contain
    # historical letters. Together they give us the full audit timeline per CA.
    # IMPORTANT: only collect history for CAs that currently have trusted roots.
    trusted_ca_owners = set(normalize_ca_owner(r.get("CA Owner", "").strip()) for r in trusted_roots)

    # Key: (ca_owner, url) → timeline entry.
    # We use URL as the dedup key — same letter appears on multiple root records.
    ca_timeline_map = defaultdict(dict)   # ca -> {url: timeline_entry}

    for r in all_roots:
        ca = normalize_ca_owner(r.get("CA Owner", "").strip())
        if not ca or ca not in trusted_ca_owners:
            continue   # skip CAs with no currently trusted roots

        aud_raw = r.get("Auditor", "").strip()
        auditor = normalize_auditor(aud_raw) if aud_raw else None

        for prefix in ["TLS BR", "Standard"]:
            stmt  = parse_ccadb_date(r.get(f"{prefix} Audit Statement Date", ""))
            pend  = parse_ccadb_date(r.get(f"{prefix} Audit Period End Date", ""))
            pstart = parse_ccadb_date(r.get(f"{prefix} Audit Period Start Date", ""))
            url   = r.get(f"{prefix} Audit URL", "").strip()
            atype = r.get(f"{prefix} Audit Type", "").strip()

            if not (stmt or pend):
                continue

            # Only track letters we can actually fetch and parse
            if not is_fetchable_url(url):
                url = ""

            # Use url+stmt_date as key; if no URL use stmt_date string only
            key = url or (stmt.isoformat() if stmt else "unknown")

            if key not in ca_timeline_map[ca]:
                ca_timeline_map[ca][key] = {
                    "stmt_date":    stmt.isoformat() if stmt else None,
                    "period_start": pstart.isoformat() if pstart else None,
                    "period_end":   pend.isoformat() if pend else None,
                    "auditor":      auditor,
                    "audit_type":   normalize_framework(atype),
                    "url":          url or None,
                    # PDF parse results — populated after fetching
                    "letter_parsed":          False,
                    "opinion_type":           None,
                    "disclosed_matters":      [],
                    "disclosed_matters_count": None,
                    "disclosure_rate":        None,
                    "fp_coverage_pct":        None,
                    "quality_score":          None,
                    "criteria_version":       None,
                    "criteria_current":       None,
                    "etsi_aal_version":       None,
                }
            else:
                # Merge — keep the most informative values
                existing = ca_timeline_map[ca][key]
                if not existing["auditor"] and auditor:
                    existing["auditor"] = auditor
                if not existing["stmt_date"] and stmt:
                    existing["stmt_date"] = stmt.isoformat()
                if not existing["period_start"] and pstart:
                    existing["period_start"] = pstart.isoformat()
                if not existing["period_end"] and pend:
                    existing["period_end"] = pend.isoformat()
            break   # use first prefix that has data

    # Convert timeline maps to sorted, deduplicated lists
    # Multiple roots from the same CA can produce duplicate entries (same
    # stmt_date + auditor, different cert types). Dedupe by (stmt_date, url).
    for ca, url_map in ca_timeline_map.items():
        entries = sorted(
            url_map.values(),
            key=lambda e: (e["stmt_date"] or "0000-00-00", e.get("url") or "")
        )
        # Collapse entries with identical stmt_date + auditor where only
        # one has a URL (prefer the one with a URL)
        seen = {}
        deduped = []
        for e in entries:
            key = (e.get("stmt_date"), e.get("auditor"))
            if key in seen:
                # Keep whichever has a URL
                if e.get("url") and not seen[key].get("url"):
                    seen[key].update(e)
                continue
            seen[key] = e
            deduped.append(e)
        raw_profiles[ca]["timeline_entries"] = deduped

    if verbose:
        total_letters = sum(
            len(p.get("timeline_entries", []))
            for p in raw_profiles.values()
        )
        multi_year = sum(
            1 for p in raw_profiles.values()
            if len(p.get("timeline_entries", [])) > 1
        )
        print(f"  [audits] {total_letters} total historical letter entries "
              f"({multi_year} CAs with multi-year history)")

    # Summarize into clean profiles
    profiles = {}
    pdf_queue = []   # (ca_owner, url) to fetch

    for ca, p in raw_profiles.items():
        primary_auditor_raw = (
            p["auditors_raw"].most_common(1)[0][0] if p["auditors_raw"] else None
        )
        all_auditors_raw = list(p["auditors_raw"].keys())

        primary_auditor = normalize_auditor(primary_auditor_raw)
        all_auditors = [normalize_auditor(a) for a in all_auditors_raw]
        # Deduplicate after normalization
        seen = set()
        all_auditors_deduped = []
        for a in all_auditors:
            if a and a not in seen:
                seen.add(a)
                all_auditors_deduped.append(a)

        primary_framework = normalize_framework(
            p["frameworks_raw"].most_common(1)[0][0] if p["frameworks_raw"] else None
        )

        latest_stmt = max(p["stmt_dates"]) if p["stmt_dates"] else None
        latest_pend = max(p["period_end_dates"]) if p["period_end_dates"] else None
        earliest_pstart = min(p["period_start_dates"]) if p["period_start_dates"] else None

        stmt_age_days = (today - latest_stmt).days if latest_stmt else None
        coverage_gap_days = (today - latest_pend).days if latest_pend else None

        # Staleness classification for CAs that have audit records
        if coverage_gap_days is None:
            staleness = "no_record"
        elif coverage_gap_days < 180:
            staleness = "current"
        elif coverage_gap_days < 365:
            staleness = "aging"
        elif coverage_gap_days < 730:
            staleness = "stale"
        else:
            staleness = "very_stale"

        # Select the TLS BR letter URL to parse.
        # Only use the TLS BR Audit URL column — that is the letter that covers
        # TLS Baseline Requirements. Falling back to Standard Audit URL would
        # parse a general CA practices letter and produce misleading results for
        # TLS coverage checks. If no TLS BR URL exists, that itself is a finding.
        # Within TLS BR URLs, prefer CPA Canada (most reliable PDF delivery).
        tls_br_pdf_url = None
        for url_type, url in p["audit_urls"]:
            if url_type != "TLS BR":
                continue
            if not is_fetchable_url(url):
                continue
            if tls_br_pdf_url is None:
                tls_br_pdf_url = url
            elif "cpacanada" in url and "cpacanada" not in tls_br_pdf_url:
                tls_br_pdf_url = url  # prefer CPA Canada within TLS BR URLs

        # For CAs with no TLS BR URL, fall back to Standard only if the CA
        # has no TLS capability (e.g. S/MIME-only CAs). TLS-capable CAs with
        # no TLS BR URL have a genuine missing-letter finding.
        has_tls_br_url = tls_br_pdf_url is not None
        tls_capable = any(
            r.get("TLS Capable", "").lower() == "true"
            for r in ca_root_records.get(ca, [])
        )
        if not tls_br_pdf_url:
            # No TLS BR URL — use Standard only for non-TLS-primary CAs
            for url_type, url in p["audit_urls"]:
                if url_type != "Standard":
                    continue
                if not is_fetchable_url(url):
                    continue
                if tls_br_pdf_url is None:
                    tls_br_pdf_url = url
                elif "cpacanada" in url and "cpacanada" not in tls_br_pdf_url:
                    tls_br_pdf_url = url

        tls_br_pdf_url = tls_br_pdf_url  # selected TLS BR letter URL (no fallback to Standard for TLS-capable CAs)

        # Precise audit record status — replaces the vague "unknown" catch-all.
        # Determined by what's actually in CCADB for this CA.
        has_any_url = bool(p["audit_urls"])
        has_any_type = bool(p["frameworks_raw"])
        has_any_date = bool(p["stmt_dates"] or p["period_end_dates"])

        if primary_auditor:
            audit_record_status = "named"
        elif tls_br_pdf_url:
            audit_record_status = "extractable"
        elif has_any_type or has_any_date:
            audit_record_status = "lapsed"
        else:
            audit_record_status = "no_record"

        profile = {
            "ca_owner": ca,
            "ca_country": ca_country_map.get(ca),
            "primary_auditor": primary_auditor,
            "auditor_country": AUDITOR_COUNTRY.get(primary_auditor),
            "all_auditors": all_auditors_deduped,
            "auditor_count": len(all_auditors_deduped),
            "primary_framework": primary_framework,
            "audit_record_status": audit_record_status,  # named|extractable|lapsed|no_record
            "trusted_stores": sorted(p["stores"]),        # which stores currently include this CA
            "exclusive_store": exclusive_store.get(ca),   # non-None if trusted by exactly one store
            "latest_stmt_date": latest_stmt.isoformat() if latest_stmt else None,
            "latest_period_end": latest_pend.isoformat() if latest_pend else None,
            "earliest_period_start": earliest_pstart.isoformat() if earliest_pstart else None,
            "stmt_age_days": stmt_age_days,
            "coverage_gap_days": coverage_gap_days,
            "staleness": staleness,
            "root_count": p["root_count"],
            "no_audit_roots": p["no_audit_roots"],
            "tls_br_pdf_url": tls_br_pdf_url,
            # Whether a TLS BR Audit URL is filed in CCADB for any of this CA's roots.
            # False means no TLS BR letter exists — that itself is a finding for
            # TLS-capable CAs. The parsed letter (if any) is a Standard/fallback letter.
            "has_tls_br_url": has_tls_br_url,
            # Which cert-type audit letters exist SEPARATELY in CCADB (beyond TLS BR).
            # Used to suppress spurious scope gaps: if reference entity has a Code Signing
            # Audit URL filed that differs from the TLS BR URL, flagging the TLS letter
            # for not covering CS is wrong.
            # IMPORTANT: exclude letter types whose URL equals the TLS BR URL — these are
            # combined letters (one PDF covers multiple cert types). A combined letter
            # is not a "separate" filing; the TLS BR letter IS the S/MIME BR letter.
            "separate_audit_types": sorted(set(
                t for t, u in p["audit_urls"]
                if t not in ("TLS BR", "Standard", "NetSec")
                and u
                and u != tls_br_pdf_url   # exclude combined letters
            )),
            # Cert-type audit letters whose URL is IDENTICAL to the TLS BR URL.
            # One PDF covers multiple cert types. The TLS BR letter IS the other
            # cert type's letter. No separate filing exists — no gap.
            "combined_audit_types": sorted(set(
                t for t, u in p["audit_urls"]
                if t not in ("TLS BR", "Standard", "NetSec")
                and u
                and u == tls_br_pdf_url   # same URL = one combined letter
            )),
            # CA operator type from gov_classifications.json
            # Values: commercial | government | state_enterprise | non_profit | regulated
            "ca_type": CA_TYPE_MAP.get(ca, "commercial"),
            # Whether any CCADB root record for this CA has an S/MIME BR Audit URL.
            # Informational only — used by the UI to show audit regime details.
            # NOT used to determine S/MIME BR compliance obligation; that is determined
            # by current Mozilla inclusion (see ca_caps.smime above). Past S/MIME BR
            # filings don't create ongoing obligations if the CA has since stopped issuing
            # S/MIME certificates and had the capability flag removed.
            "smime_br_url_in_ccadb": any(
                r.get("S/MIME BR Audit URL", "").strip()
                for r in ca_root_records.get(ca, [])
            ),
            # CA capabilities from CCADB (available even without PDF parsing)
            "ca_capabilities": {
                "tls":   any(r.get("TLS Capable", "").lower() == "true"
                             for r in ca_root_records.get(ca, [])),
                "ev":    any(r.get("TLS EV Capable", "").lower() == "true"
                             for r in ca_root_records.get(ca, [])),
                "smime": any(r.get("S/MIME Capable", "").lower() == "true"
                             for r in ca_root_records.get(ca, [])),
                "cs":    any(r.get("Code Signing Capable", "").lower() == "true"
                             for r in ca_root_records.get(ca, [])),
            },
            # Incident data from Bugzilla (always available from incidents.json)
            "incident_count":    incident_map.get(ca, {}).get("n"),
            "self_report_pct":   incident_map.get(ca, {}).get("selfPct"),
            "ext_report_count":  incident_map.get(ca, {}).get("ext"),
            # PDF parsing results (populated below if fetch_pdfs=True)
            "pdf_parsed": False,
            "opinion_type": None,
            "audit_framework": None,
            "audit_criteria": None,
            "etsi_aal_version": None,
            "policy_oids_present": [],
            "in_scope_sha256": [],
            "locations_audited": [],
            "subservice_organizations": [],
            "qualifications": [],
            "disclosed_matters": [],
            "pdf_auditor_firm": None,
            "pdf_period_start": None,
            "pdf_period_end": None,
            "pdf_pages": None,
            # Cross-check results (populated after PDF parsing)
            "fingerprint_check": None,
            "incident_disclosure_check": None,
            "criteria_check": None,
            "oid_check": None,
            "letter_quality_score": None,
            "transparency_gap": None,
            "score_epoch": get_audit_epoch(
                latest_stmt.isoformat() if latest_stmt else None
            ),
            # Root coverage — from CCADB data, always available regardless of PDF
            # Describes the CA's audit regime architecture
            "root_coverage": {
                "total_roots":       root_coverage_map.get(ca, {}).get("total_roots", 0),
                "roots_with_url":    root_coverage_map.get(ca, {}).get("roots_with_url", 0),
                "roots_without_url": root_coverage_map.get(ca, {}).get("roots_without_url", 0),
                "unaudited_fps":     root_coverage_map.get(ca, {}).get("unaudited_fps", []),
                "distinct_letters":  root_coverage_map.get(ca, {}).get("distinct_url_count", 0),
                "audit_regime":      (
                    "multi"  if root_coverage_map.get(ca, {}).get("distinct_url_count", 0) > 1 else
                    "single" if root_coverage_map.get(ca, {}).get("distinct_url_count", 0) == 1 else
                    "none"
                ),
            },
            # Full audit timeline (current + historical letters, sorted by date)
            "audit_timeline": p.get("timeline_entries", []),
        }
        profiles[ca] = profile

        # Queue current letter for PDF parsing
        if fetch_pdfs and tls_br_pdf_url:
            pdf_queue.append((ca, tls_br_pdf_url, "current"))

        # Queue historical letters too (unique URLs not already queued)
        if fetch_pdfs:
            current_urls = {tls_br_pdf_url} if tls_br_pdf_url else set()
            for entry in p.get("timeline_entries", []):
                url = entry.get("url")
                if url and url not in current_urls:
                    pdf_queue.append((ca, url, "historical"))
                    current_urls.add(url)

    # --- Build dual-framework URL map ---
    # For CAs that file both ETSI and WebTrust letters with CCADB, identify
    # the most recent URL for the non-primary framework. These CAs are a
    # natural within-CA controlled experiment: same CA, same period, two
    # different audit frameworks producing two different letters.
    from datetime import datetime as _dt_cls

    def _parse_ccadb_date_strict(s):
        if not s: return None
        for fmt in ('%Y.%m.%d', '%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d'):
            try: return _dt_cls.strptime(s.strip(), fmt)
            except ValueError: pass
        return None

    # Collect (framework, stmt_date, url) per CA across all roots + TLS BR/Standard cols
    _ca_fw_entries = defaultdict(lambda: defaultdict(list))
    for r in ccadb_records:
        _ca = normalize_ca_owner(r.get("CA Owner", "").strip())
        if not _ca: continue
        for _pfx in ["TLS BR", "Standard"]:
            _at  = r.get(f"{_pfx} Audit Type", "").strip().lower()
            _url = r.get(f"{_pfx} Audit URL", "").strip()
            _dt  = _parse_ccadb_date_strict(r.get(f"{_pfx} Audit Statement Date", ""))
            if not _url or not is_fetchable_url(_url): continue
            if "etsi" in _at:
                _ca_fw_entries[_ca]["ETSI"].append((_dt, _url))
            elif "webtrust" in _at or "web trust" in _at:
                _ca_fw_entries[_ca]["WebTrust"].append((_dt, _url))

    # dual_fw_url_map: ca -> {"framework": str, "url": str} for the secondary framework
    dual_fw_url_map = {}
    for _ca, _fws in _ca_fw_entries.items():
        if "ETSI" not in _fws or "WebTrust" not in _fws: continue
        if _ca not in profiles: continue
        _primary_fw = profiles[_ca].get("primary_framework", "")
        _other_fw = "WebTrust" if _primary_fw == "ETSI" else "ETSI"
        _entries = sorted(_ca_fw_entries[_ca][_other_fw],
                          key=lambda x: (x[0] or _dt_cls.min), reverse=True)
        # Selection priority:
        # 1. Already-cached URL with parsed content (parse_error is None or absent)
        # 2. CPA Canada hosted URL (most reliable WebTrust delivery)
        # 3. Most recent by statement date
        _best = None
        _best_priority = -1
        for _d, _u in _entries[:10]:
            _cache_key = hashlib.sha256(_u.encode()).hexdigest()[:16]
            _cache_file = CACHE_DIR / f"{_cache_key}.json"
            _priority = 0
            if os.path.exists(_cache_file):
                try:
                    _cached = json.loads(open(_cache_file).read())
                    if not _cached.get("parse_error"):
                        _priority = 3  # cached with parsed content — best
                    elif _cached.get("parse_error") == "fetch_failed":
                        _priority = -1  # known bad — skip
                except Exception as e:
                    print(f"    WARNING: cache priority read error for URL: {e}", file=__import__("sys").stderr)
            if _priority == -1:
                continue  # skip known-bad URLs
            if "cpacanada" in _u and _priority < 2:
                _priority = 2  # prefer CPA Canada if not already cached
            if _best is None or _priority > _best_priority:
                _best = (_d, _u)
                _best_priority = _priority
        if _best:
            dual_fw_url_map[_ca] = {"framework": _other_fw, "url": _best[1]}

    if verbose:
        print(f"  [audits] Dual-framework CAs: {len(dual_fw_url_map)}")

    # Queue secondary framework letters now that dual_fw_url_map is populated
    if fetch_pdfs:
        for ca, sec_info in dual_fw_url_map.items():
            sec_url = sec_info["url"]
            # Don't re-queue if already in pdf_queue (e.g. it was also a historical URL)
            already_queued = any(u == sec_url for _, u, _ in pdf_queue)
            if not already_queued:
                pdf_queue.append((ca, sec_url, "secondary"))


    if fetch_pdfs and HAS_PDFPLUMBER:
        # Deduplicate by URL. Each unique URL is fetched once and its parsed
        # result applied to:
        #   (a) the profile's top-level fields if it's the CA's current letter
        #   (b) the matching timeline entry in profile["audit_timeline"]
        #   (c) profile["secondary_audit"] if it's the secondary framework letter
        url_to_entries = {}  # url -> list of (ca, letter_type, timeline_entry_ref)

        for ca, url, letter_type in pdf_queue:
            if url not in url_to_entries:
                url_to_entries[url] = []
            # Find the matching timeline entry for this CA+URL
            timeline_entry = next(
                (e for e in profiles[ca].get("audit_timeline", [])
                 if e.get("url") == url),
                None
            )
            url_to_entries[url].append((ca, letter_type, timeline_entry))

        unique_queue = list(url_to_entries.items())
        if max_pdfs is not None:
            unique_queue = unique_queue[:max_pdfs]

        if verbose:
            current_count = sum(
                1 for entries in url_to_entries.values()
                if any(lt == "current" for _, lt, _ in entries)
            )
            secondary_count = sum(
                1 for entries in url_to_entries.values()
                if any(lt == "secondary" for _, lt, _ in entries)
            )
            historical_count = len(unique_queue) - current_count - secondary_count
            print(f"  [audits] {len(unique_queue)} unique PDF URLs to fetch "
                  f"({current_count} current, {secondary_count} secondary, "
                  f"{historical_count} historical)")

        fetched = 0
        skipped_cache = 0
        failed = 0

        for url, entries in unique_queue:
            cached = _load_cache(url)
            if cached is not None:
                skipped_cache += 1
                parsed = cached
            else:
                pdf_bytes = fetch_pdf_bytes(url)
                if pdf_bytes is None:
                    failed += 1
                    _save_cache(url, {"parse_error": "fetch_failed"})
                    continue

                parsed = parse_audit_pdf(pdf_bytes, api_key=api_key)
                if parsed.get("parse_error") != "no api_key — metadata only":
                    _save_cache(url, parsed)
                fetched += 1

                if verbose and (fetched % 10 == 0):
                    print(f"    {fetched}/{len(unique_queue)} fetched, "
                          f"{skipped_cache} cached, {failed} failed")

                time.sleep(0.8 if api_key else 0.5)

            # Apply result to all CAs that reference this URL
            for ca, letter_type, timeline_entry in entries:
                if ca not in profiles:
                    continue
                is_current   = (letter_type == "current")
                is_secondary = (letter_type == "secondary")

                # Always update the timeline entry with parsed data
                if timeline_entry is not None and not parsed.get("parse_error"):
                    timeline_entry["letter_parsed"] = True
                    timeline_entry["opinion_type"] = parsed.get("opinion_type")
                    # Use period_end as reference date — the scheme in effect
                    # during the audit period is what matters
                    _cc = crosscheck_audit_criteria(
                        parsed,
                        stmt_date  = timeline_entry.get("stmt_date"),
                        period_end = timeline_entry.get("period_end"),
                    )
                    timeline_entry["criteria_version"] = _cc.get("criteria_version")
                    timeline_entry["criteria_current"] = _cc.get("criteria_current")
                    timeline_entry["etsi_aal_version"] = parsed.get("etsi_aal_version")
                    matters = parsed.get("disclosed_matters") or []
                    timeline_entry["disclosed_matters_count"] = len(matters)
                    timeline_entry["disclosed_matters"] = matters
                    # Auditor from PDF overrides CCADB if CCADB was blank
                    if not timeline_entry.get("auditor") and parsed.get("auditor_firm"):
                        timeline_entry["auditor"] = normalize_auditor(
                            parsed.get("auditor_firm", "")
                        )

                # Only apply to profile top-level fields for the current letter
                if is_current:
                    profiles[ca].update(_apply_pdf_result(parsed))

                # Store secondary framework letter result separately
                if is_secondary and not parsed.get("parse_error"):
                    profiles[ca]["secondary_audit"] = {
                        "framework":      parsed.get("audit_framework"),
                        "criteria":       parsed.get("audit_criteria"),
                        "auditor":        normalize_auditor(parsed.get("auditor_firm", "")),
                        "opinion_type":   parsed.get("opinion_type"),
                        "quality_score":  parsed.get("letter_quality_score"),
                        "in_scope_sha256": parsed.get("in_scope_sha256", []),
                        "policy_oids_present": parsed.get("policy_oids_present", []),
                        "disclosed_matters": parsed.get("disclosed_matters", []),
                        "url":            url,
                        "fw_label":       dual_fw_url_map.get(ca, {}).get("framework"),
                    }

        if verbose:
            print(f"  [audits] PDF fetch complete: {fetched} new, "
                  f"{skipped_cache} cached, {failed} failed")

    # --- Cross-checks for parsed profiles ---
    if verbose:
        print("  [audits] Running cross-checks...")

    parsed_count = 0
    for ca, profile in profiles.items():
        if not profile.get("pdf_parsed"):
            continue

        # Reconstruct pdf_result from profile fields for cross-check functions
        pdf_result = {
            "period_start":             profile.get("pdf_period_start"),
            "period_end":               profile.get("pdf_period_end"),
            "in_scope_sha256":          profile.get("in_scope_sha256", []),
            "disclosed_matters":        profile.get("disclosed_matters", []),
            "audit_criteria":           profile.get("audit_criteria"),
            "audit_framework":          profile.get("audit_framework"),
            "etsi_aal_version":         profile.get("etsi_aal_version"),
            "policy_oids_present":      profile.get("policy_oids_present", []),
        }

        # 1. Per-engagement fingerprint accuracy + ecosystem root coverage
        # Compare letter fingerprints against the roots whose CCADB audit URL
        # matches this specific letter — not all roots for the CA owner.
        # A CA's roots are distributed across multiple letters (TLS BR, TLS EVG,
        # S/MIME BR, Code Signing, NetSec, Standard). Each letter only covers
        # the roots assigned to its URL in CCADB. Using all CA roots produces
        # false positives for roots legitimately covered by other letter types.
        # Analysis confirmed: 37 of 38 "missing root" cases were false positives
        # caused by this; only 1 CA (Turkey Kamu SM) had a genuinely missing root.
        roots_for_this_url = url_root_records.get(tls_br_pdf_url, [])
        if not roots_for_this_url:
            # URL not in our map — rare edge case, fall back to all CA roots
            roots_for_this_url = ca_root_records.get(ca, [])
        profile["fingerprint_check"] = crosscheck_fingerprints(
            pdf_result,
            roots_for_this_url,
            root_coverage_map.get(ca),
            all_ca_fps=ca_all_fps.get(ca, {}),
            global_fp_type=global_fp_type,
            cross_signed_fps=cross_signed_fps_by_issuer.get(ca, set()),
        )

        # 2. Incident disclosure completeness (beyond ALV — policy §5.2 item 13)
        # Always use the CCADB latest period as the authoritative window.
        # The PDF-parsed dates are only used if they match the latest period
        # (within 60 days) — otherwise the PDF is from a different/older letter
        # and its period dates would produce a stale check.
        if bugzilla_bugs:
            ccadb_pstart = (date.fromisoformat(profile["earliest_period_start"])
                            if profile.get("earliest_period_start") else None)
            ccadb_pend   = (date.fromisoformat(profile["latest_period_end"])
                            if profile.get("latest_period_end") else None)

            # Check whether pdf_period_end is close to the CCADB latest period
            pdf_pend_raw = profile.get("pdf_period_end")
            pdf_pend = None
            if pdf_pend_raw:
                try:
                    pdf_pend = date.fromisoformat(pdf_pend_raw[:10])
                except ValueError:
                    pass
            pdf_matches_current = (
                pdf_pend and ccadb_pend and
                abs((pdf_pend - ccadb_pend).days) <= 60
            )

            # Build pdf_result_for_check: if PDF period matches CCADB, pass full
            # pdf_result so disclosed_matters are used. Otherwise pass empty
            # pdf_result so crosscheck falls back purely to CCADB period dates.
            if pdf_matches_current:
                pdf_result_for_check = pdf_result
            else:
                pdf_result_for_check = {
                    "period_start": None, "period_end": None,
                    "disclosed_matters": profile.get("disclosed_matters", []),
                }

            profile["incident_disclosure_check"] = crosscheck_incident_disclosure(
                pdf_result_for_check, bugzilla_bugs, ca,
                ccadb_period_start=ccadb_pstart,
                ccadb_period_end=ccadb_pend,
                bugs_by_ca=bugs_by_ca,
            )

        # 3. Criteria and AAL template currency (beyond ALV)
        # Use period_end as reference — the scheme in effect during the audit
        # period is what matters, not when the letter was later issued.
        profile["criteria_check"] = crosscheck_audit_criteria(
            pdf_result,
            stmt_date  = profile.get("latest_stmt_date"),
            period_end = profile.get("latest_period_end"),
        )

        # 4. Policy scope coverage — inferred from criteria string + CCADB capabilities
        # CCADB uses title-case 'True'/'False' for capability columns
        roots_for_ca = ca_root_records.get(ca, [])
        ca_caps = {
            "tls":   any(r.get("TLS Capable", "").lower() == "true"
                         for r in roots_for_ca),
            "ev":    any(r.get("TLS EV Capable", "").lower() == "true"
                         for r in roots_for_ca),
            # S/MIME capability requires an ACTIVE obligation under an enforcing root program.
            # "S/MIME Capable = True" in CCADB is a historical flag that predates the S/MIME
            # BR and was set for many Microsoft-only roots (national identity CAs, government
            # document-signing CAs, payment networks) that have no S/MIME BR obligation.
            # Microsoft has not published S/MIME BR enforcement deadlines. Mozilla has (MRSP
            # §3.1: periods ending after Oct 30 2023).
            # The correct signal: does this CA have S/MIME-capable roots currently in Mozilla?
            # Mozilla is the only root program with a published, active S/MIME BR enforcement
            # policy. Using "S/MIME BR URL already filed" is wrong — a CA that stopped issuing
            # S/MIME and had the flag removed would still match; past filings don't create
            # current obligations.
            "smime": any(
                r.get("S/MIME Capable", "").lower() == "true"
                and r.get("Mozilla Status", "").strip() == "Included"
                for r in roots_for_ca
            ),
            "cs":    any(r.get("Code Signing Capable", "").lower() == "true"
                         for r in roots_for_ca),
        }
        # Store on profile so UI can display CA capabilities independently
        profile["ca_capabilities"] = ca_caps
        profile["oid_check"] = crosscheck_policy_oids(
            pdf_result, ca_caps,
            separate_audit_types=profile.get("separate_audit_types", []),
            combined_types=profile.get("combined_audit_types", []),
        )

        # 5. Letter quality score (aggregate of all checks)
        profile["letter_quality_score"] = score_audit_letter(profile)

        # 5b. Secondary framework letter cross-checks (dual-framework CAs only)
        # Run fingerprint and scope checks on the secondary letter and store
        # results so the UI can compare the two frameworks side-by-side.
        sec = profile.get("secondary_audit")
        if sec and sec.get("in_scope_sha256") is not None:
            sec_pdf_result = {
                "in_scope_sha256":     sec.get("in_scope_sha256", []),
                "audit_criteria":      sec.get("criteria"),
                "audit_framework":     sec.get("framework"),
                "policy_oids_present": sec.get("policy_oids_present", []),
            }
            sec_url = sec.get("url", "")
            sec_roots = url_root_records.get(sec_url, []) if sec_url else []
            if not sec_roots:
                sec_roots = ca_root_records.get(ca, [])
            sec["fingerprint_check"] = crosscheck_fingerprints(
                sec_pdf_result,
                sec_roots,
                root_coverage_map.get(ca),
                all_ca_fps=ca_all_fps.get(ca, {}),
                global_fp_type=global_fp_type,
                cross_signed_fps=cross_signed_fps_by_issuer.get(ca, set()),
            )
            sec["oid_check"] = crosscheck_policy_oids(
                sec_pdf_result,
                profile.get("ca_capabilities", {}),
                separate_audit_types=profile.get("separate_audit_types", []),
                combined_types=profile.get("combined_audit_types", []),
            )
            # Score using same scoring function applied to primary
            sec_profile_stub = dict(profile)
            sec_profile_stub.update(_apply_pdf_result(sec_pdf_result))
            sec["quality_score"] = score_audit_letter(sec_profile_stub)

        # 6. Transparency gap — the core signal:
        #    clean letter (unqualified, few/no matters) vs Bugzilla incident history.
        #    High gap = auditor gave clean opinion but community tracked real issues.
        #    This is the most direct measurement of audit methodology adequacy.
        n_incidents    = profile.get("incident_count") or 0
        n_matters      = len(profile.get("disclosed_matters") or [])
        n_matters_with_bz = sum(
            1 for m in (profile.get("disclosed_matters") or [])
            if m.get("bugzilla_ids")
        )
        n_externally_found = sum(
            1 for m in (profile.get("disclosed_matters") or [])
            if m.get("self_reported") is False
        )
        # gap_score: 0 = full transparency, 100 = complete opacity
        # Defined as: incidents known but not appearing in letter / total incidents
        # Only meaningful when we have both Bugzilla data and a parsed letter
        gap_score = None
        if n_incidents > 0 and profile.get("pdf_parsed"):
            # If letter has 0 matters but CA has incidents → high gap
            # If letter has matters with Bugzilla IDs → those are "visible"
            visible = n_matters_with_bz
            gap_score = round(max(0, n_incidents - visible) / n_incidents * 100, 1)

        profile["transparency_gap"] = {
            "incident_count":         n_incidents,
            "matters_count":          n_matters,
            "matters_with_bugzilla":  n_matters_with_bz,
            "externally_found":       n_externally_found,
            "gap_score":              gap_score,
            # Human-readable classification
            "gap_level": (
                "high"     if gap_score is not None and gap_score >= 70 else
                "moderate" if gap_score is not None and gap_score >= 30 else
                "low"      if gap_score is not None else
                "unknown"
            ),
        }

        # Backfill quality score and fp/disclosure rates into the current
        # timeline entry so the over-time chart has full data
        current_url = profile.get("tls_br_pdf_url")
        if current_url:
            current_entry = next(
                (e for e in profile.get("audit_timeline", [])
                 if e.get("url") == current_url),
                None
            )
            if current_entry:
                qs   = profile["letter_quality_score"]
                crit = profile.get("criteria_check") or {}
                current_entry["quality_score"]          = qs.get("overall") if qs else None
                current_entry["score_epoch"]            = qs.get("score_epoch") if qs else None
                current_entry["criteria_current"]       = crit.get("criteria_current")
                current_entry["criteria_current_today"] = crit.get("criteria_current_today")
                current_entry["aal_current"]            = crit.get("aal_current")
                current_entry["aal_current_today"]      = crit.get("aal_current_today")
                fp  = profile.get("fingerprint_check") or {}
                current_entry["fp_coverage_pct"] = fp.get("coverage_pct")
                inc = profile.get("incident_disclosure_check") or {}
                current_entry["disclosure_rate"] = inc.get("disclosure_rate")
                # Backfill disclosed_matters so retrospective can check catches
                if profile.get("disclosed_matters"):
                    current_entry["disclosed_matters"] = profile["disclosed_matters"]

        parsed_count += 1

    # Compute timeline trends and transparency gap for ALL profiles
    # (timeline runs on metadata even without PDF; gap uses incident_count
    # which is always populated from incidents.json)
    for ca, profile in profiles.items():
        profile["timeline_trends"] = compute_timeline_trends(profile)

        # Transparency gap for unparsed profiles — partial signal
        n_incidents = profile.get("incident_count") or 0
        if not profile.get("pdf_parsed") and n_incidents > 0:
            profile["transparency_gap"] = {
                "incident_count":        n_incidents,
                "matters_count":         None,
                "matters_with_bugzilla": None,
                "externally_found":      None,
                "gap_score":             None,
                "gap_level":             "unknown",
            }

        # Bug retrospective — cross-letter incident coverage analysis
        # Requires bugs_by_ca (from fetch_incidents.py) and a timeline with period dates
        if bugs_by_ca and profile.get("audit_timeline"):
            profile["bug_retrospective"] = build_bug_retrospective(
                ca, bugs_by_ca, profile["audit_timeline"]
            )
        else:
            profile["bug_retrospective"] = []

    if verbose:
        print(f"  [audits] Cross-checks complete for {parsed_count} parsed profiles")

    # --- Auditor aggregate signals (cross-CA patterns ALV can't see) ---
    auditor_aggregates = compute_auditor_aggregates(list(profiles.values()))


    auditor_stats = defaultdict(lambda: {"ca_count": 0, "ca_owners": []})
    for ca, p in profiles.items():
        # Use primary_auditor only (current engagement) for HHI and concentration stats.
        # all_auditors includes historical firms and would double-count CAs that switched.
        aud = p.get("primary_auditor")
        if aud:
            auditor_stats[aud]["ca_count"] += 1
            auditor_stats[aud]["ca_owners"].append(ca)

    # Sort by ca_count desc
    auditor_stats_sorted = dict(
        sorted(auditor_stats.items(), key=lambda x: -x[1]["ca_count"])
    )

    # --- Framework stats ---
    framework_stats = Counter()
    for p in profiles.values():
        fw = p["primary_framework"] or "(unknown)"
        framework_stats[fw] += 1

    # --- Staleness buckets ---
    staleness_buckets = Counter(p["staleness"] for p in profiles.values())

    # --- HHI for auditor concentration ---
    # Use audit_record_status for consistency with named_auditor_count output field.
    # "named" = auditor identified from CCADB; "extractable" = identified from PDF.
    total_named = sum(
        1 for p in profiles.values()
        if p.get("audit_record_status") in ("named", "extractable")
    )
    auditor_hhi = None
    if total_named > 0:
        auditor_hhi = round(
            sum(
                (v["ca_count"] / total_named * 100) ** 2
                for v in auditor_stats.values()
            ),
            1,
        )

    # Count exclusive-store CAs (governance linkback)
    exclusive_store_counts = Counter(
        p["exclusive_store"] for p in profiles.values()
        if p.get("exclusive_store")
    )

    return {
        "profiles": profiles,
        "auditor_stats": auditor_stats_sorted,
        "auditor_aggregates": auditor_aggregates,
        "framework_stats": dict(framework_stats.most_common()),
        "staleness_buckets": dict(staleness_buckets),
        "total_ca_owners": len(profiles),
        "named_auditor_count": total_named,
        "auditor_hhi": auditor_hhi,
        "distrusted_root_count": len(distrusted_roots),
        "exclusive_store_counts": dict(exclusive_store_counts),
        "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
    }


def _apply_pdf_result(result):
    """Map a parse_audit_pdf() result dict onto a profile update dict."""
    if not result or result.get("parse_error"):
        return {"pdf_parsed": False}
    return {
        "pdf_parsed":               True,
        "opinion_type":             result.get("opinion_type"),
        "audit_framework":          result.get("audit_framework"),
        "audit_criteria":           result.get("audit_criteria"),
        "etsi_aal_version":         result.get("etsi_aal_version"),
        "policy_oids_present":      result.get("policy_oids_present", []),
        "in_scope_sha256":          result.get("in_scope_sha256", []),
        "locations_audited":        result.get("locations_audited", []),
        "subservice_organizations": result.get("subservice_organizations", []),
        "qualifications":           result.get("qualifications", []),
        "disclosed_matters":        result.get("disclosed_matters", []),
        "pdf_auditor_firm":         result.get("auditor_firm"),
        "pdf_period_start":         result.get("period_start"),
        "pdf_period_end":           result.get("period_end"),
        "pdf_pages":                result.get("pages"),
    }


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _json_serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serialisable")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(ccadb_records, fetch_pdfs=True, max_pdfs=None, api_key=None, verbose=True):
    """
    Called by the main pipeline runner (run_pipeline.py / CI).

    Parameters
    ----------
    ccadb_records : list[dict]   from fetch_and_join.fetch_ccadb()
    fetch_pdfs    : bool
    max_pdfs      : int | None   set to a small number for dev/testing
    api_key       : str | None   Anthropic API key for LLM PDF parsing.
                                 Falls back to ANTHROPIC_API_KEY env var.

    Writes
    ------
    data/audits.json
    """
    import os
    if api_key is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    if fetch_pdfs and not api_key:
        print("  [audits] WARNING: no ANTHROPIC_API_KEY — PDF parsing disabled")

    # Load Bugzilla bug data for incident disclosure cross-checks.
    # The ops_cache stores raw bug metadata from fetch_incidents.py.
    bugzilla_bugs = None
    bugs_cache_path = PIPELINE_DIR / "ops_cache" / "bugs_raw.json"
    if bugs_cache_path.exists():
        try:
            bugzilla_bugs = json.loads(bugs_cache_path.read_text())
            if verbose:
                print(f"  [audits] Loaded {len(bugzilla_bugs)} Bugzilla bugs "
                      f"for incident cross-checks")
        except Exception as e:
            if verbose:
                print(f"  [audits] WARNING: could not load bugs_raw.json: {e}")
    else:
        if verbose:
            print("  [audits] No bugs_raw.json found — incident cross-checks skipped")

    # Load bugs_by_ca.json for retrospective analysis (written by fetch_incidents.py)
    bugs_by_ca = None
    bugs_by_ca_path = OUTPUT_DIR / "bugs_by_ca.json"
    if bugs_by_ca_path.exists():
        try:
            bugs_by_ca = json.loads(bugs_by_ca_path.read_text())
            if verbose:
                total_bugs = sum(len(v) for v in bugs_by_ca.values())
                print(f"  [audits] Loaded bugs_by_ca.json "
                      f"({total_bugs} bugs across {len(bugs_by_ca)} CAs) for retrospective")
        except Exception as e:
            if verbose:
                print(f"  [audits] WARNING: could not load bugs_by_ca.json: {e}")

    # Load bugs_by_ca_distrusted.json for distrust audit retrospective
    bugs_by_ca_distrusted = None
    bugs_by_ca_dist_path = OUTPUT_DIR / "bugs_by_ca_distrusted.json"
    if bugs_by_ca_dist_path.exists():
        try:
            bugs_by_ca_distrusted = json.loads(bugs_by_ca_dist_path.read_text())
            if verbose:
                total_dist = sum(len(v) for v in bugs_by_ca_distrusted.values())
                print(f"  [audits] Loaded bugs_by_ca_distrusted.json "
                      f"({total_dist} bugs across {len(bugs_by_ca_distrusted)} distrusted CAs)")
        except Exception as e:
            if verbose:
                print(f"  [audits] WARNING: could not load bugs_by_ca_distrusted.json: {e}")

    if verbose:
        print("Building audit profiles...")

    result = build_audit_profiles(
        ccadb_records,
        fetch_pdfs=fetch_pdfs,
        max_pdfs=max_pdfs,
        api_key=api_key,
        bugzilla_bugs=bugzilla_bugs,
        bugs_by_ca=bugs_by_ca,
        verbose=verbose,
    )

    # Convert profiles dict to sorted list for the UI
    profiles_list = sorted(
        result["profiles"].values(),
        key=lambda p: (p["coverage_gap_days"] or 99999),
        reverse=True,
    )

    # Compute audit_record_status breakdown for the summary
    record_status_counts = Counter(
        p["audit_record_status"] for p in profiles_list
    )    # Aggregate cross-check signals across all parsed profiles
    qualified_count = sum(
        1 for p in profiles_list
        if p.get("opinion_type") == "qualified"
    )
    fp_gap_count = sum(
        1 for p in profiles_list
        if p.get("fingerprint_check") and p["fingerprint_check"].get("missing_fps")
    )
    disclosure_gap_count = sum(
        1 for p in profiles_list
        if p.get("incident_disclosure_check") and
           p["incident_disclosure_check"].get("undisclosed_bugs")
    )
    outdated_criteria_count = sum(
        1 for p in profiles_list
        if p.get("criteria_check") and p["criteria_check"].get("criteria_current") is False
    )
    high_gap_count = sum(
        1 for p in profiles_list
        if (p.get("transparency_gap") or {}).get("gap_level") == "high"
    )
    # CAs with matters in letter but no Bugzilla anchor — disclosed to auditor but
    # not cross-referenced to root program tracker
    no_bz_anchor_count = sum(
        1 for p in profiles_list
        if any(
            not (m.get("bugzilla_ids") or [])
            for m in (p.get("disclosed_matters") or [])
        )
    )
    # CAs that issued active cross-signed certificates but whose audit letter
    # does not enumerate at least one of those fingerprints (§5.1 gap)
    cross_signed_gap_count = sum(
        1 for p in profiles_list
        if (p.get("fingerprint_check") or {}).get("cross_signed_gap")
    )
    cross_signed_gap_fps_total = sum(
        len((p.get("fingerprint_check") or {}).get("cross_signed_fps_missing") or [])
        for p in profiles_list
    )

    # Generate LLM chart insights from this run's actual numbers
    chart_insights, chart_insights_stats = generate_chart_insights(profiles_list, result, api_key=api_key)
    if verbose and chart_insights:
        print(f"  Generated {len(chart_insights)} chart insights via LLM")

    # --- Distrust audit retrospective ---
    # For each distrusted CA, run the retrospective: did the audit letters
    # covering the compliance period mention the bugs that contributed to distrust?
    distrust_retrospective = []
    if bugs_by_ca_distrusted:
        distrust_json_path = PIPELINE_DIR / "distrust" / "distrusted.json"
        if distrust_json_path.exists():
            distrust_events = json.loads(distrust_json_path.read_text()).get("events", [])
            for dist_event in distrust_events:
                ca_owner = dist_event.get("ca_owner")   # CCADB canonical name
                ca_bz    = dist_event.get("ca")          # Bugzilla display name (key in bugs_by_ca_distrusted)
                if not ca_bz:
                    continue

                # Find bugs: try Bugzilla display name, then ca_owner, then case-insensitive
                bugs = (bugs_by_ca_distrusted.get(ca_bz) or
                        bugs_by_ca_distrusted.get(ca_owner) or
                        next((v for k, v in bugs_by_ca_distrusted.items()
                              if k.lower() == ca_bz.lower()), None) or [])

                # Also collect bugs under case/spacing variants of the CA name
                # (e.g. "reference entity" and "reference entity")
                if ca_bz:
                    for k, v in bugs_by_ca_distrusted.items():
                        if k.lower() == ca_bz.lower() and v not in [bugs]:
                            bugs = bugs + v  # merge variant keys

                if not bugs:
                    continue

                # Find audit profile (distrusted CAs may still be in CCADB)
                profile = result["profiles"].get(ca_owner) if ca_owner else None
                # Also try case-insensitive profile lookup for variant names
                if not profile and ca_owner:
                    profile = next(
                        (p for k, p in result["profiles"].items()
                         if k.lower() == ca_owner.lower()), None
                    )
                timeline = profile.get("audit_timeline", []) if profile else []

                retro = build_bug_retrospective(ca_bz, {ca_bz: bugs}, timeline) if timeline else []
                covered = len([r for r in retro if r.get("covering_letters", 0) > 0])
                caught  = len([r for r in retro if r.get("mentioned_in", 0) > 0])

                # Compute timeline_status to explain why in_scope may be zero:
                #   "overlap"   — periods and bugs overlap: genuine detection data
                #   "post_date" — CCADB has letters but all periods post-date the bugs
                #                 (CA cleaned up after distrust; letters predate CCADB)
                #   "no_record" — no CCADB audit records at all (CA removed too early)
                if not timeline:
                    timeline_status = "no_record"
                else:
                    bug_dates = sorted(b["filed"] for b in bugs if b.get("filed"))
                    latest_bug = bug_dates[-1] if bug_dates else None
                    earliest_period = min(
                        (e["period_start"] for e in timeline if e.get("period_start")),
                        default=None
                    )
                    if latest_bug and earliest_period and earliest_period > latest_bug:
                        timeline_status = "post_date"
                    else:
                        timeline_status = "overlap"

                distrust_retrospective.append({
                    "ca":              ca_bz,
                    "ca_owner":        ca_owner,
                    "distrust_year":   dist_event.get("year"),
                    "auditor":         profile.get("primary_auditor") if profile else None,
                    "framework":       profile.get("primary_framework") if profile else None,
                    "opinion_type":    profile.get("opinion_type") if profile else None,
                    "total_bugs":      len(bugs),
                    "bugs_in_scope":   covered,
                    "bugs_caught":     caught,
                    "detection_pct":   round(caught / covered * 100, 1) if covered else None,
                    "timeline_status": timeline_status,
                    "runway_days":     (dist_event.get("timeline") or {}).get("runway_days"),
                    "compliance_posture": dist_event.get("compliance_posture"),
                    "reason_tags":     dist_event.get("reason_tags", []),
                    "retrospective":   retro,
                })

        distrust_retrospective.sort(key=lambda x: -(x.get("total_bugs") or 0))
        if verbose:
            in_scope = sum(r["bugs_in_scope"] for r in distrust_retrospective)
            caught_n = sum(r["bugs_caught"] for r in distrust_retrospective)
            rate = round(caught_n / in_scope * 100, 1) if in_scope else 0
            print(f"  Distrust retrospective: {len(distrust_retrospective)} CAs, "
                  f"{in_scope} in-scope bugs, {caught_n} caught ({rate}%)")

    output = {
        "generated_at": result["generated_at"],
        "chart_insights": chart_insights,
        "summary": {
            "total_ca_owners":          result["total_ca_owners"],
            "named_auditor_count":      result["named_auditor_count"],
            "distrusted_root_count":    result["distrusted_root_count"],
            "exclusive_store_counts":   result["exclusive_store_counts"],
            # Precise breakdown of audit record status
            "audit_record_status": {
                "named":       record_status_counts.get("named", 0),
                "extractable": record_status_counts.get("extractable", 0),
                "lapsed":      record_status_counts.get("lapsed", 0),
                "no_record":   record_status_counts.get("no_record", 0),
            },
            "auditor_hhi":    result["auditor_hhi"],
            "framework_stats": result["framework_stats"],
            "staleness_buckets": result["staleness_buckets"],
            # Cross-check signals (only non-zero once PDFs are parsed)
            "pdf_parsed_count":         sum(1 for p in profiles_list if p.get("pdf_parsed")),
            "qualified_opinions":       qualified_count,
            "fp_coverage_gaps":         fp_gap_count,
            "incident_disclosure_gaps": disclosure_gap_count,
            "outdated_criteria":        outdated_criteria_count,
            # Transparency gap summary
            "high_transparency_gap":    high_gap_count,
            "matters_without_bz_anchor": no_bz_anchor_count,
            # §5.1 cross-signed certificate audit enumeration gaps
            "cross_signed_gap_cas":     cross_signed_gap_count,
            "cross_signed_gap_fps":     cross_signed_gap_fps_total,
            # In-period detection rate — computed from bug_retrospective across all profiles.
            # Numerator:   bugs that had ≥1 covering letter AND were mentioned in it.
            # Denominator: bugs that had ≥1 covering letter (auditor was responsible).
            # This is the figure cited as the "auditor self-detection rate" in docs/blog.
            "in_period_detection_rate": chart_insights_stats.get("in_period_detection_rate"),
            "in_period_caught":          chart_insights_stats.get("in_period_caught"),
            "in_period_covered":         chart_insights_stats.get("in_period_covered"),
        },
        "auditor_concentration": [
            {
                "auditor":    aud,
                "ca_count":   stats["ca_count"],
                "ca_owners":  sorted(stats["ca_owners"]),
                "share_pct":  round(
                    stats["ca_count"] / max(result["named_auditor_count"], 1) * 100, 1
                ),
                # Attach aggregate signals if available
                **(result["auditor_aggregates"].get(aud, {})),
            }
            for aud, stats in result["auditor_stats"].items()
        ],
        # Per-auditor cross-CA aggregate signals — the main beyond-ALV output
        "auditor_aggregates": result["auditor_aggregates"],
        "profiles": profiles_list,
        # Distrust audit retrospective — did auditors catch the compliance
        # failures that ultimately led to each CA's removal from trust stores?
        "distrust_audit_retrospective": distrust_retrospective,
    }

    out_path = OUTPUT_DIR / "audits.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, default=_json_serial, indent=2)

    if verbose:
        print(f"  Wrote {out_path} "
              f"({len(profiles_list)} CA profiles, "
              f"{len(result['auditor_stats'])} auditors)")
        s = result["staleness_buckets"]
        print(f"  Staleness: current={s.get('current',0)} "
              f"aging={s.get('aging',0)} stale={s.get('stale',0)} "
              f"very_stale={s.get('very_stale',0)} unknown={s.get('unknown',0)}")
        if result["auditor_hhi"]:
            print(f"  Auditor HHI: {result['auditor_hhi']} "
                  f"({'highly concentrated' if result['auditor_hhi'] > 2500 else 'moderately concentrated' if result['auditor_hhi'] > 1500 else 'unconcentrated'})")

    return output


# ---------------------------------------------------------------------------
# Standalone test run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os, sys
    import urllib.request as ur
    from collections import Counter

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY not set — PDF LLM parsing will be skipped")

    print("Fetching CCADB...")
    ccadb_url = "https://ccadb.my.salesforce-sites.com/ccadb/AllCertificateRecordsCSVFormatv4"
    req = ur.Request(ccadb_url, headers={"User-Agent": "WebPKI-Observatory-Test/1.0"})
    with ur.urlopen(req, timeout=60) as resp:
        content = resp.read().decode("utf-8-sig")

    records = list(csv.DictReader(io.StringIO(content)))
    print(f"Loaded {len(records)} CCADB records")

    # Dev run: fetch up to N PDFs (default 5 to keep cost low during testing)
    max_pdfs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    result = run(records, fetch_pdfs=True, max_pdfs=max_pdfs,
                 api_key=api_key, verbose=True)

    # Summary
    parsed = [p for p in result["profiles"] if p.get("pdf_parsed")]
    print(f"\n=== PDF parse results ({len(parsed)} parsed, {max_pdfs} attempted) ===")
    opinions = Counter(p.get("opinion_type") for p in parsed)
    print(f"  Opinion types: {dict(opinions)}")

    with_matters = [p for p in parsed if p.get("disclosed_matters")]
    print(f"  With disclosed matters: {len(with_matters)}")
    for p in with_matters:
        matters = p["disclosed_matters"]
        print(f"\n  {p['ca_owner']} — {len(matters)} matter(s)  "
              f"criteria={p.get('audit_criteria','?')[:50]}")
        for m in matters:
            bz = ", ".join(f"#{b}" for b in (m.get("bugzilla_ids") or []))
            cc = f"  [{m.get('certificate_count')} certs]" if m.get("certificate_count") else ""
            print(f"    {m['item']}. {m.get('summary', m.get('text',''))[:120]}{cc}  {bz}")

        # Show cross-check results
        fp_chk = p.get("fingerprint_check") or {}
        if fp_chk.get("coverage_pct") is not None:
            print(f"    FP coverage: {fp_chk['coverage_pct']}%  "
                  f"({len(fp_chk.get('covered_fps',[]))} covered, "
                  f"{len(fp_chk.get('missing_fps',[]))} missing)")
            for fp in fp_chk.get("missing_fps", []):
                print(f"      MISSING FP: {fp[:16]}...")

        inc_chk = p.get("incident_disclosure_check") or {}
        if inc_chk.get("disclosure_rate") is not None:
            print(f"    Incident disclosure: {inc_chk['disclosure_rate']}%  "
                  f"({len(inc_chk.get('bugs_in_period',[]))} bugs in period, "
                  f"{len(inc_chk.get('undisclosed_bugs',[]))} undisclosed)")
            for bug in inc_chk.get("undisclosed_bugs", [])[:5]:
                print(f"      UNDISCLOSED: bug #{bug}")

        crit_chk = p.get("criteria_check") or {}
        if crit_chk.get("version_string"):
            current = crit_chk.get("is_current")
            flag = "✓" if current else "⚠ OUTDATED" if current is False else "?"
            print(f"    Criteria: {crit_chk['framework']} {crit_chk['version_string']} {flag}")

    print(f"\n=== Auditor concentration (top 10) ===")
    for entry in result["auditor_concentration"][:10]:
        print(f"  {entry['ca_count']:3d} CAs ({entry['share_pct']:4.1f}%)  {entry['auditor']}")
    print(f"\n  HHI: {result['summary']['auditor_hhi']}")
    print(f"  Framework split: {result['summary']['framework_stats']}")
    print(f"  Staleness: {result['summary']['staleness_buckets']}")
