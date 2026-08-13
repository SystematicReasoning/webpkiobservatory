#!/usr/bin/env python3
"""
Obligation parsers — one per document structural convention.

Conventions identified across CA compliance documents:
  RFC2119_INLINE      — MUST/SHOULD/MAY inline (TLS BR, EVG, CS BR, RFCs, Mozilla MRSP)
  SHALL_LETTERED_LIST — SHALL: header + a. b. c. sub-items (NSR, S/MIME BR)
  EU_LEGAL            — lowercase shall paragraphs under Articles (NIS2)
  NIST_OSCAL          — structured JSON control catalog (NIST 800-53)

Key design decision: certificate PROFILE SPECIFICATIONS are counted separately
from OPERATIONAL OBLIGATIONS. Profile specs (Section 7 of TLS BR, profile
tables in S/MIME BR) express certificate field constraints that a CA implements
once in its CA software. They are not independent compliance activities.

Operational obligations (validation procedures, audit requirements, incident
response, key management) are the primary compliance burden — each requires
documented policy, staffing, and ongoing execution.

Both are returned and the caller can use either or both.
"""

import re
import json


# ── Convention detection ──────────────────────────────────────────────────────

def detect_convention(text: str) -> str:
    MUST_upper  = len(re.findall(r'\bMUST\b', text))
    SHALL_upper = len(re.findall(r'\bSHALL\b', text))
    shall_lower = len(re.findall(r'\bshall\b', text, re.I)) - SHALL_upper
    shall_hdrs  = len(re.findall(r'SHALL:\s*\n', text))
    lettered    = len(re.findall(r'^[a-z]\.\s+\S', text, re.M))
    articles    = len(re.findall(r'Article\s+\d+', text, re.I))

    if shall_hdrs >= 3 and lettered > 20:
        return "SHALL_LETTERED_LIST"
    if articles > 20 and shall_lower > 100:
        return "EU_LEGAL"
    return "RFC2119_INLINE"


# ── Section classification for RFC2119_INLINE documents ──────────────────────

# CABF documents follow RFC 3647 structure. Section 7 is always certificate
# profiles; sections 1-6 and 8-9 are operational.
# Profile specs produce one implementation artifact; operational sections
# require ongoing documented processes.

def split_profile_operational(text: str) -> tuple[str, str]:
    """
    Split a CABF markdown document into profile spec text and operational text.
    Returns (operational_text, profile_text).
    """
    # Section 7 = Certificate/CRL/OCSP Profiles in RFC 3647 structure
    sec7 = re.search(r'^# 7\.\s', text, re.M)
    sec8 = re.search(r'^# 8\.\s', text, re.M)

    if sec7 and sec8:
        profile_text     = text[sec7.start():sec8.start()]
        operational_text = text[:sec7.start()] + text[sec8.start():]
    elif sec7:
        profile_text     = text[sec7.start():]
        operational_text = text[:sec7.start()]
    else:
        profile_text     = ""
        operational_text = text

    return operational_text, profile_text


# ── Parser 1: RFC 2119 inline keywords ───────────────────────────────────────

def _count_rfc2119(text: str) -> dict:
    mandatory = (
        len(re.findall(r'\bMUST\b(?!\s+NOT)',   text)) +
        len(re.findall(r'\bMUST\s+NOT\b',       text)) +
        len(re.findall(r'\bSHALL\b(?!\s+NOT)',  text)) +
        len(re.findall(r'\bSHALL\s+NOT\b',      text)) +
        len(re.findall(r'\bREQUIRED\b',         text))
    )
    recommended = (
        len(re.findall(r'\bSHOULD\b(?!\s+NOT)', text)) +
        len(re.findall(r'\bSHOULD\s+NOT\b',     text)) +
        len(re.findall(r'\bRECOMMENDED\b',       text))
    )
    optional = (
        len(re.findall(r'\bMAY\b',              text)) +
        len(re.findall(r'\bOPTIONAL\b',         text))
    )
    return {"mandatory": mandatory, "recommended": recommended, "optional": optional}


def parse_rfc2119_inline(text: str) -> dict:
    """
    RFC 2119 inline keywords. Used by: CABF TLS BR, EVG, CS BR, Mozilla MRSP, RFCs.

    Splits CABF documents into operational (sections 1-6, 8-9) and profile spec
    (section 7) counts. The primary metric is operational; profile is reported
    separately for completeness.
    """
    op_text, prof_text = split_profile_operational(text)

    op   = _count_rfc2119(op_text)
    prof = _count_rfc2119(prof_text)
    total_op   = op["mandatory"]   + op["recommended"]   + op["optional"]
    total_prof = prof["mandatory"] + prof["recommended"] + prof["optional"]

    return {
        # Total includes both operational and profile spec obligations
        "mandatory":    op["mandatory"]   + prof["mandatory"],
        "recommended":  op["recommended"] + prof["recommended"],
        "optional":     op["optional"]    + prof["optional"],
        "total":        total_op + total_prof,
        "convention":   "RFC2119_INLINE",
        # Expose split for the pipeline to store as separate stack layers
        "operational": {**op,   "total": total_op},
        "profile_spec":{**prof, "total": total_prof},
        "detail": {
            "operational":   {**op,   "total": total_op},
            "profile_spec":  {**prof, "total": total_prof},
            "note": "operational = sections 1-6, 8-9 (validation, audit, key mgmt, etc). "
                    "profile_spec = section 7 certificate/CRL/OCSP profile tables.",
        }
    }


# ── Parser 2: SHALL: header + lettered list ───────────────────────────────────

def parse_shall_lettered(text: str) -> dict:
    """
    SHALL: header + lettered list. Used by: CABF NSR, CABF S/MIME BR.

    For NSR: structural count (lettered + numbered + roman items) is correct.
    For S/MIME BR: the document uses SHALL extensively inline in certificate
    profile tables (same pattern as TLS BR section 7). We split on the same
    RFC 3647 section boundary and count only the operational SHALL obligations.

    The S/MIME BR's profile tables use pattern: `field` (SHALL be present)
    as lettered items — these are profile specs, not operational obligations.
    """
    # Split operational vs profile for documents that have section 7
    op_text, prof_text = split_profile_operational(text)

    # If no section 7 found (NSR), the whole document is operational
    if not prof_text:
        op_text = text

    # Structural count on operational text
    lettered = len(re.findall(r'^[a-z]\.\s+\S',        op_text, re.M))
    numbered = len(re.findall(r'^\s{3,}\d+\.\s+\S',    op_text, re.M))
    roman    = len(re.findall(r'^\s{6,}[ivxlcdm]+\.\s+\S', op_text, re.M))
    structural = lettered + numbered + roman

    # Inline SHALL/MUST in operational text (excluding SHALL: headers)
    shall_headers = len(re.findall(r'SHALL:\s*\n', op_text))
    inline_mandatory = (
        len(re.findall(r'\bSHALL\b(?!\s+NOT)', op_text)) +
        len(re.findall(r'\bSHALL\s+NOT\b',     op_text)) +
        len(re.findall(r'\bMUST\b(?!\s+NOT)',   op_text)) +
        len(re.findall(r'\bMUST\s+NOT\b',       op_text))
    ) - shall_headers

    mandatory = max(structural, inline_mandatory)

    recommended = (
        len(re.findall(r'\bSHOULD\b(?!\s+NOT)', op_text)) +
        len(re.findall(r'\bSHOULD\s+NOT\b',     op_text)) +
        len(re.findall(r'\bRECOMMENDED\b',       op_text))
    )
    optional = len(re.findall(r'\bMAY\b', op_text))

    # Profile spec count for completeness
    prof_shall = len(re.findall(r'\bSHALL\b(?!\s+NOT)', prof_text)) if prof_text else 0

    # Profile spec for completeness
    prof_total = prof_shall  # Only mandatory known for SHALL docs
    return {
        "mandatory":   mandatory + prof_total,
        "recommended": recommended,
        "optional":    optional,
        "total":       mandatory + prof_total + recommended + optional,
        "convention":  "SHALL_LETTERED_LIST",
        "operational": {"mandatory": mandatory, "recommended": recommended,
                        "optional": optional, "total": mandatory + recommended + optional},
        "profile_spec":{"mandatory": prof_total, "recommended": 0,
                        "optional": 0, "total": prof_total},
        "detail": {
            "lettered_items":    lettered,
            "numbered_subitems": numbered,
            "roman_subitems":    roman,
            "structural_total":  structural,
            "inline_mandatory":  inline_mandatory,
            "shall_headers":     shall_headers,
            "profile_spec_shall": prof_shall,
            "SHOULD":            len(re.findall(r'\bSHOULD\b', op_text)),
            "MAY":               len(re.findall(r'\bMAY\b',    op_text)),
        }
    }


# ── Parser 3: EU legal language ───────────────────────────────────────────────

def parse_eu_legal(text: str) -> dict:
    """
    EU legal drafting. Used by: NIS2 Directive.

    'shall' = binding mandatory obligation.
    'should' = recital/political guidance — NOT operative, excluded.
    'may' = discretionary permission.
    """
    mandatory = (
        len(re.findall(r'\bshall\b(?!\s+not)', text, re.I)) +
        len(re.findall(r'\bshall\s+not\b',     text, re.I))
    )
    optional = len(re.findall(r'\bmay\b', text, re.I))

    return {
        "mandatory": mandatory, "recommended": 0, "optional": optional,
        "total": mandatory + optional,
        "convention": "EU_LEGAL",
        "detail": {
            "shall":     len(re.findall(r'\bshall\b(?!\s+not)', text, re.I)),
            "shall_not": len(re.findall(r'\bshall\s+not\b',     text, re.I)),
            "may":       optional,
            "note": "EU 'should' excluded — recital guidance, not operative obligation.",
        }
    }


# ── Parser 4: NIST OSCAL structured catalog ───────────────────────────────────

def parse_nist_oscal(catalog_json: dict, baseline: str = "high") -> dict:
    """
    NIST SP 800-53 structured catalog. Uses High baseline by default.

    The High baseline resolved catalog contains only controls applicable at
    the High impact level — 370 controls vs 1,196 in the full catalog.
    This is the appropriate baseline for CAs, which operate critical infrastructure.

    Pass baseline="all" to count the full catalog.
    Pass a pre-filtered catalog_json (already a High-baseline resolved profile)
    for the most accurate count.
    """
    groups = catalog_json.get("catalog", {}).get("groups", [])
    base_controls = 0
    enhancements  = 0
    by_family     = {}
    for group in groups:
        family_id    = group.get("id", "?").upper()
        family_title = group.get("title", "")
        base = len(group.get("controls", []))
        enh  = sum(len(c.get("controls", [])) for c in group.get("controls", []))
        base_controls += base
        enhancements  += enh
        by_family[family_id] = {"title": family_title, "base": base, "enhancements": enh}

    total = base_controls + enhancements
    return {
        "mandatory": total, "recommended": 0, "optional": 0,
        "total": total,
        "convention": "NIST_OSCAL",
        "detail": {
            "base_controls": base_controls,
            "enhancements":  enhancements,
            "by_family":     by_family,
            "baseline":      baseline,
        }
    }


# ── Dispatch ──────────────────────────────────────────────────────────────────

def parse(text: str, convention: str = None) -> dict:
    """Dispatch to the correct parser, auto-detecting convention if not specified."""
    if convention is None:
        convention = detect_convention(text)
    if convention == "SHALL_LETTERED_LIST":
        return parse_shall_lettered(text)
    if convention == "EU_LEGAL":
        return parse_eu_legal(text)
    return parse_rfc2119_inline(text)
