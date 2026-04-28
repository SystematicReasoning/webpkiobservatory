#!/usr/bin/env python3
"""
compute_comparable_cases.py — Comparable case synthesis

For each active CA, find the distrusted CA with the most similar compliance
profile and compute a factual similarity score. Enables the paper and
observatory to say "CA X's profile most resembles [Distrusted CA] in [year]"
with a fully computable, transparent basis.

Similarity dimensions:
  chronic class overlap (Jaccard, 35pts)
  dominant mode match A vs B (15pts)
  n_chronic magnitude (15pts)
  self-report rate (15pts)
  acceleration direction (10pts)
  years active (10pts)

Output: data/comparable_cases.json
"""

import json
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
DATA_DIR     = PIPELINE_DIR.parent / "data"

import sys
sys.path.insert(0, str(PIPELINE_DIR))
from utils import load_json, save_json, now_utc


def profile_vector(sig: dict, scores: dict) -> dict:
    return {
        'chronic_classes': set(sig.get('chronic_classes', {}).keys()),
        'n_chronic':       sig.get('n_chronic', 0),
        'n_solo_chronic':  sig.get('n_solo_chronic', 0),
        'years_active':    sig.get('years_active', 1),
        'self_pct':        sig.get('self_pct', 50),
        'accel':           sig.get('accel', 1.0),
        'gov_frac':        sig.get('gov_frac', 0),
        'dominant_mode':   scores.get('dominant_mode', 'B'),
        'total':           scores.get('total', 0),
    }


def similarity(active_v: dict, distrust_v: dict) -> dict:
    score = 0.0
    reasons = []

    # 1. Chronic class overlap (Jaccard)
    a_cls, d_cls = active_v['chronic_classes'], distrust_v['chronic_classes']
    if a_cls and d_cls:
        overlap = a_cls & d_cls
        jaccard = len(overlap) / len(a_cls | d_cls)
        score += jaccard * 35
        if overlap:
            reasons.append(f"shared chronic classes: {', '.join(sorted(overlap)[:3])}")

    # 2. Dominant mode match
    if active_v['dominant_mode'] == distrust_v['dominant_mode']:
        score += 15
        reasons.append(f"same failure mode ({active_v['dominant_mode']})")

    # 3. n_chronic magnitude
    a_n, d_n = active_v['n_chronic'], distrust_v['n_chronic']
    if d_n > 0:
        ratio = min(a_n, d_n) / max(a_n, d_n)
        score += ratio * 15
        if ratio > 0.7:
            reasons.append(f"similar chronic class count ({a_n} vs {d_n})")

    # 4. Self-report rate
    diff = abs(active_v['self_pct'] - distrust_v['self_pct'])
    self_sim = max(0, 1 - diff / 100)
    score += self_sim * 15
    if self_sim > 0.8:
        reasons.append(
            f"similar detection posture ({active_v['self_pct']:.0f}% vs {distrust_v['self_pct']:.0f}%)")

    # 5. Acceleration direction
    a_acc, d_acc = active_v['accel'], distrust_v['accel']
    if (a_acc > 1.2 and d_acc > 1.2) or (a_acc < 0.8 and d_acc < 0.8):
        score += 10
        reasons.append("accelerating" if a_acc > 1.2 else "decelerating")

    # 6. Years active
    a_y, d_y = active_v['years_active'], distrust_v['years_active']
    if d_y > 0:
        score += min(a_y, d_y) / max(a_y, d_y) * 10

    return {'score': round(score, 1), 'reasons': reasons}


def main():
    print("[compute_comparable_cases] Loading data...")

    als = load_json(DATA_DIR / "als_scores.json") or {}
    scores_list = als.get('scores', [])
    if not scores_list:
        print("[compute_comparable_cases] No ALS scores — run compute_als.py first")
        return

    active    = [r for r in scores_list if r.get('population') == 'active']
    distrusted = [r for r in scores_list if r.get('population') == 'distrusted']
    print(f"[compute_comparable_cases] {len(active)} active, {len(distrusted)} distrusted")

    if not distrusted:
        print("[compute_comparable_cases] No distrusted CAs in ALS")
        return

    # Build distrust profile vectors
    distrust_profiles = []
    for r in distrusted:
        sig, sc = r.get('signals', {}), r.get('scores', {})
        if not sig:
            continue
        de = r.get('distrust_event', {}) or {}
        sig_years = sig.get('years', [None, None])
        distrust_profiles.append({
            'ca':           r['ca'],
            'pathway':      de.get('pathway', de.get('distrust_pathway', 'unknown')),
            'posture':      de.get('posture', ''),
            'last_year':    sig_years[1] if sig_years else None,
            'vector':       profile_vector(sig, sc),
            'als_total':    sc.get('total', 0),
            'n':            sig.get('n', 0),
        })

    results = []
    for r in active:
        sig, sc = r.get('signals', {}), r.get('scores', {})
        if not sig:
            continue
        active_v = profile_vector(sig, sc)
        if active_v['n_chronic'] == 0:
            continue

        comparisons = []
        for dp in distrust_profiles:
            if dp['n'] < 5:
                continue
            sim = similarity(active_v, dp['vector'])
            if sim['score'] > 10:
                comparisons.append({
                    'comparable_ca':         dp['ca'],
                    'distrust_pathway':      dp['pathway'],
                    'distrust_posture':      dp['posture'],
                    'distrust_last_year':    dp['last_year'],
                    'similarity_score':      sim['score'],
                    'similarity_reasons':    sim['reasons'],
                    'comparable_n_chronic':  dp['vector']['n_chronic'],
                    'comparable_als':        dp['als_total'],
                })

        if not comparisons:
            continue

        comparisons.sort(key=lambda x: x['similarity_score'], reverse=True)
        results.append({
            'ca':             r['ca'],
            'als_total':      sc.get('total', 0),
            'n_chronic':      sig.get('n_chronic', 0),
            'n_solo_chronic': sig.get('n_solo_chronic', 0),
            'dominant_mode':  sc.get('dominant_mode', 'B'),
            'best_comparable': comparisons[0],
            'top_comparables': comparisons[:3],
        })

    results.sort(key=lambda x: x['als_total'], reverse=True)

    output = {
        'generated_at': now_utc().isoformat(),
        'methodology': (
            'Similarity scored on: chronic class overlap (Jaccard, 35pts), '
            'dominant mode match (15pts), n_chronic magnitude (15pts), '
            'self-report rate (15pts), acceleration direction (10pts), '
            'years active (10pts). Min similarity score 10 to appear.'
        ),
        'n_active_with_comparables': len(results),
        'n_distrusted_profiles':     len(distrust_profiles),
        'results': results,
    }

    save_json(DATA_DIR / "comparable_cases.json", output)
    print(f"[compute_comparable_cases] Wrote comparable_cases.json")
    print(f"[compute_comparable_cases] {len(results)} active CAs matched")

    print("\n=== TOP COMPARABLE CASE MATCHES ===")
    for r in results[:12]:
        b = r['best_comparable']
        print(f"  {r['ca'][:30]:<30}  ALS={r['als_total']:>5.1f}"
              f"  → {b['comparable_ca'][:22]:<22}"
              f"  ({b['distrust_pathway']}, {b.get('distrust_last_year','?')})"
              f"  sim={b['similarity_score']:.0f}")
        if b['similarity_reasons']:
            print(f"  {'':30}    {'; '.join(b['similarity_reasons'][:2])}")


if __name__ == "__main__":
    main()
