"""
test_ryan_expectations.py
─────────────────────────
Test suite encoding Ryan Dickson's expert judgment about CA compliance
posture as ground-truth assertions. Ryan is a root program manager who
decides which CAs get distrusted — his ordering is the test vector.

Run:  pytest pipeline/test_ryan_expectations.py -v
      python pipeline/test_ryan_expectations.py

Sources:
  Ryan's feedback (March 2026):
  - "I'd also consider CAs like CFCA, SHECA, Izenpe, and Firmaprofessional
    to be worse. ITrusChina, too. These CAs all seem to offer disproportionate
    value considering risk and signs of incompetence/mismanagement."
  - "I wouldn't assess Sectigo in the same class as DigiCert."
    (DigiCert is worse than Sectigo)
  - "I'd assess no CA with a worse performance in bugzilla over the last
    9 months [than Microsoft]"
  - "Firmaprofessional recently was reported to have missed a CA certificate.
    I'd say that's much more indicative than sectigo or digicert boinking a
    few dozen OV/EV attributes."
  - "Same is true with characteristics of those disclosures (self or third
    party) - and the quality of responses to questions from the community."
"""

import json
import sys
from pathlib import Path

DATA_DIR   = Path(__file__).parent.parent / "data"
PUBLIC_DIR = Path(__file__).parent.parent / "app" / "public"


def load_ranking() -> list[dict]:
    """Load cpf_data.json and return active elevated CAs sorted by EPS desc."""
    cpf_path = PUBLIC_DIR / "cpf_data.json"
    if not cpf_path.exists():
        cpf_path = Path(__file__).parent.parent / "docs" / "cpf_data.json"
    cpf = json.loads(cpf_path.read_text())
    rows = [r for r in cpf["rows"] if r["population"] == "active"]
    rows.sort(key=lambda x: -x["eps"])
    return rows


def rank_of(rows: list[dict], keyword: str) -> int:
    """1-based rank of the first CA whose name contains keyword (case-insensitive)."""
    kw = keyword.lower()
    for i, r in enumerate(rows, 1):
        if kw in r["ca"].lower():
            return i
    raise ValueError(f"CA not found: {keyword!r}")


def eps_of(rows: list[dict], keyword: str) -> float:
    kw = keyword.lower()
    for r in rows:
        if kw in r["ca"].lower():
            return r["eps"]
    raise ValueError(f"CA not found: {keyword!r}")


def flagged(rows: list[dict], keyword: str) -> bool:
    kw = keyword.lower()
    for r in rows:
        if kw in r["ca"].lower():
            return r["flagged"]
    raise ValueError(f"CA not found: {keyword!r}")


# ── Test cases ────────────────────────────────────────────────────────────────

def test_ryan_worse_cas_all_elevated():
    """Ryan explicitly said CFCA, SHECA, Izenpe, Firmaprofesional, iTrusChina
    show signs of incompetence/mismanagement — they must all be flagged/elevated."""
    rows = load_ranking()
    for kw in ["China Financial", "Shanghai Electronic", "Izenpe", "Firmaprofes", "iTrusChina"]:
        assert flagged(rows, kw), f"{kw} should be elevated/flagged per Ryan"


def test_ryan_worse_cas_above_digicert():
    """All 5 of Ryan's 'worse' CAs must rank above DigiCert (higher EPS = worse posture)."""
    rows = load_ranking()
    dc_rank = rank_of(rows, "DigiCert")
    for kw in ["China Financial", "Shanghai Electronic", "Izenpe", "Firmaprofes", "iTrusChina"]:
        r = rank_of(rows, kw)
        assert r < dc_rank, (
            f"{kw} (rank {r}) should rank above DigiCert (rank {dc_rank}) — "
            f"Ryan said these CAs show worse posture"
        )


def test_ryan_worse_cas_above_sectigo():
    """All 5 of Ryan's 'worse' CAs must rank above Sectigo."""
    rows = load_ranking()
    se_rank = rank_of(rows, "Sectigo")
    for kw in ["China Financial", "Shanghai Electronic", "Izenpe", "Firmaprofes", "iTrusChina"]:
        r = rank_of(rows, kw)
        assert r < se_rank, (
            f"{kw} (rank {r}) should rank above Sectigo (rank {se_rank})"
        )


def test_digicert_worse_than_sectigo():
    """Ryan: 'I wouldn't assess Sectigo in the same class as DigiCert.'
    DigiCert is worse — it must rank above (lower rank number, higher EPS)."""
    rows = load_ranking()
    dc_rank = rank_of(rows, "DigiCert")
    se_rank = rank_of(rows, "Sectigo")
    dc_eps  = eps_of(rows, "DigiCert")
    se_eps  = eps_of(rows, "Sectigo")
    assert dc_rank < se_rank, (
        f"DigiCert (rank {dc_rank}, EPS {dc_eps}) should rank above "
        f"Sectigo (rank {se_rank}, EPS {se_eps}) — Ryan said DigiCert is worse"
    )


def test_firmaprofesional_elevated_high():
    """Ryan: Firmaprofesional's missed CA certificate is 'much more indicative'
    than Sectigo/DigiCert attribute misissuances. Should be in top 5."""
    rows = load_ranking()
    rank = rank_of(rows, "Firmaprofes")
    assert rank <= 5, (
        f"Firmaprofesional at rank {rank} — missed CA cert should put it in top 5"
    )


def test_microsoft_elevated_high():
    """Ryan: 'I'd assess no CA with a worse performance in bugzilla over the
    last 9 months' than Microsoft. Should be in top 10."""
    rows = load_ranking()
    rank = rank_of(rows, "Microsoft")
    assert rank <= 10, (
        f"Microsoft at rank {rank} — 9 months of bad performance should put it in top 10"
    )


def test_large_cas_not_dominating_top():
    """Large CAs (DigiCert, Sectigo) should not be in the top 10 — incident
    count alone must not dominate. Ryan's point: incident count != CA quality."""
    rows = load_ranking()
    for kw in ["DigiCert", "Sectigo"]:
        rank = rank_of(rows, kw)
        assert rank > 10, (
            f"{kw} at rank {rank} — large CA incident volume should not dominate top 10"
        )


def test_isrg_not_elevated():
    """ISRG (Let's Encrypt) should not be elevated — clean record, high self-detection."""
    rows = load_ranking()
    try:
        is_flag = flagged(rows, "Internet Security Research")
        assert not is_flag, "ISRG should not be flagged — it's a clean reference CA"
    except ValueError:
        pass  # Not in corpus at all is fine


def test_google_trust_services_reasonable():
    """Google Trust Services is a young CA with a managed record — should not
    be in top 5."""
    rows = load_ranking()
    try:
        rank = rank_of(rows, "Google Trust Services")
        assert rank > 5, f"Google Trust Services at rank {rank} seems too high"
    except ValueError:
        pass


def test_distrust_pathway_cas_elevated():
    """Camerfirma and Entrust (graduated distrust) must be elevated — they are
    the core test vectors for the ALS scoring model."""
    als = json.loads((DATA_DIR / "als_scores.json").read_text())
    for kw in ["Camerfirma", "Entrust"]:
        r = next((x for x in als["scores"] if kw.lower() in x["ca"].lower()), None)
        if r:
            assert r["scores"]["flagged"], (
                f"{kw} should be flagged — graduated distrust CA is a core test vector"
            )


def test_sensitivity_acceptable():
    """ALS sensitivity on graduated-pathway distrust CAs (n>=5) must be >=60%."""
    als = json.loads((DATA_DIR / "als_scores.json").read_text())
    meta = als.get("test_vectors", {})
    sens = meta.get("sensitivity")
    if sens is not None:
        assert sens >= 0.60, f"ALS sensitivity {sens:.0%} below 60% floor"


def test_specificity_perfect():
    """ALS specificity must be 100% — no false positives on clean CAs."""
    als = json.loads((DATA_DIR / "als_scores.json").read_text())
    meta = als.get("test_vectors", {})
    spec = meta.get("specificity")
    if spec is not None:
        assert spec == 1.0, f"ALS specificity {spec:.0%} — false positives detected"


def test_eps_range_sane():
    """All EPS scores should be in [0, 100]."""
    rows = load_ranking()
    for r in rows:
        assert 0 <= r["eps"] <= 100, f"{r['ca']} EPS={r['eps']} out of range"


def test_no_clean_reference_cas_elevated():
    """ISRG, Amazon, Apple should not be elevated — they are clean reference CAs."""
    rows = load_ranking()
    for kw in ["Internet Security Research", "Amazon Trust", "Apple Inc"]:
        try:
            is_flag = flagged(rows, kw)
            assert not is_flag, f"{kw} should not be elevated — clean reference CA"
        except ValueError:
            pass  # Not in corpus is fine


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_ryan_worse_cas_all_elevated,
        test_ryan_worse_cas_above_digicert,
        test_ryan_worse_cas_above_sectigo,
        test_digicert_worse_than_sectigo,
        test_firmaprofesional_elevated_high,
        test_microsoft_elevated_high,
        test_large_cas_not_dominating_top,
        test_isrg_not_elevated,
        test_google_trust_services_reasonable,
        test_distrust_pathway_cas_elevated,
        test_sensitivity_acceptable,
        test_specificity_perfect,
        test_eps_range_sane,
        test_no_clean_reference_cas_elevated,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}")
            print(f"      {e}")
            failed += 1
        except Exception as e:
            print(f"  ! {t.__name__} — error: {e}")
            failed += 1

    print(f"\n{passed}/{passed+failed} tests passed")
    sys.exit(0 if failed == 0 else 1)
