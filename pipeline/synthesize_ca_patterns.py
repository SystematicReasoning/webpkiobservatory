#!/usr/bin/env python3
"""
CA Pattern Synthesis — Pass 3 of the IRQ pipeline.

Uses Sonnet to identify recurring architectural patterns across a CA's
full commitment and incident history. Haiku classifies individual threads;
Sonnet synthesizes cross-thread patterns that Haiku cannot see.

Output: per-CA pattern chains with linked bugs, root cause descriptions,
and confidence scores. Written to data/ca_pattern_chains.json.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from collections import defaultdict

PIPELINE_DIR = Path(__file__).parent
DATA_DIR     = PIPELINE_DIR.parent / "data"
CACHE_DIR    = PIPELINE_DIR / "ops_cache"

ANTHROPIC_URL     = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
SONNET_MODEL      = "claude-sonnet-4-5"
MAX_TOKENS        = 4000

SYNTHESIS_PROMPT = """\
You are analyzing the compliance incident history of a Certificate Authority (CA)
in the WebPKI. You will be given this CA's complete record of incidents and the
commitments they made in response to each.

Your task: identify RECURRING ARCHITECTURAL PATTERNS — cases where later incidents
suggest that prior commitments addressed the specific symptom but not the underlying
root cause, and the same architectural weakness surfaced again through a different
specific mechanism.

Focus on ROOT CAUSE, not surface category. For example:
- "CAA timeout treated as pass" and "CAA fails open during network disruption" share
  root cause: validation system defaults to issuance under degraded conditions
- "Failure to revoke key-compromised certs within 24hr" (2020) and "Failure to find
  and revoke key-compromised certs within 24hr" (2021) share root cause: key compromise
  detection pipeline has reliability gaps

Do NOT flag:
- Coincidental recurrence of unrelated incidents in the same broad class
- Incidents where the prior commitment was never claimed to address the root cause
- Cases where the later incident is clearly a different system or acquired entity

For each pattern found, also assess DISCLOSURE QUALITY for the later incident(s):
Did the CA's own incident report or initial comments explicitly reference the prior
related incident(s) or acknowledge the recurrence pattern — BEFORE the community raised it?

Classify disclosure_quality as:
- "proactive": CA explicitly referenced prior bug IDs, prior commitments, or the
  recurring pattern in their own initial report or first substantive response
- "reactive": CA acknowledged the connection only after community members raised it
- "silent": CA never acknowledged the connection — the recurrence was not disclosed

This is a meaningful signal: CAs are expected to analyze and disclose related prior
incidents in their incident reports. Failure to self-reference known prior failures
on the same root cause suggests inadequate root cause analysis or selective disclosure.

For each pattern found, return:
- pattern_name: short label (e.g. "fail-open under degraded conditions")
- root_cause: one sentence describing the shared underlying weakness
- prior_bugs: list of bug IDs where commitments were made on this root cause
- later_bugs: list of bug IDs where the same root cause resurfaced
- confidence: high / medium / low
- evidence: 2-3 sentences explaining why these are the same root cause
- disclosure_quality: "proactive" | "reactive" | "silent"
- disclosure_evidence: one sentence explaining what the CA said (or did not say)
  about the prior incident in their later report

Return JSON only. No preamble. Format:
{{
  "patterns": [
    {{
      "pattern_name": "...",
      "root_cause": "...",
      "prior_bugs": ["..."],
      "later_bugs": ["..."],
      "confidence": "high|medium|low",
      "evidence": "...",
      "disclosure_quality": "proactive|reactive|silent",
      "disclosure_evidence": "..."
    }}
  ],
  "synthesis_notes": "brief overall characterization of this CA's commitment quality"
}}

If no recurring patterns are found, return {{"patterns": [], "synthesis_notes": "..."}}

CA INCIDENT AND COMMITMENT HISTORY:
{history}
"""


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def build_ca_history(ca: str, bugs: list, irq_cache: dict,
                     comment_cache: dict | None = None) -> str:
    """Build a structured history string of incidents + commitments for this CA."""
    bug_meta = {str(b['id']): b for b in bugs}
    lines = []
    for b in sorted(bugs, key=lambda x: x.get('filed', '')):
        bid = str(b['id'])
        yr  = b.get('filed', '')[:7]
        summary = b.get('summary', '')
        tags = b.get('whiteboard', '')
        score = irq_cache.get(bid)
        if not score:
            continue
        comms = [c for c in score.get('commitments', [])
                 if isinstance(c, dict) and c.get('grade') in ('A','B','C')]
        if not comms and score.get('thread_health_arc') == 'healthy':
            continue  # skip clean threads with no commitments — not informative

        lines.append(f"\n[BUG {bid}] {yr} — {summary}")
        lines.append(f"  Tags: {tags.strip()}")
        lines.append(f"  Arc: {score.get('thread_health_arc','?')}  RCA depth: {score.get('rca_depth','?')}")

        # Include first CA-authored comment for disclosure assessment.
        # This is what the CA said in their initial report — critical for
        # detecting whether they self-referenced prior related incidents.
        if comment_cache:
            thread = comment_cache.get(bid, [])
            ca_comments = [c for c in thread if _is_ca_comment(c, ca)]
            if ca_comments:
                first_ca = ca_comments[0]
                text = first_ca.get('text', '')[:400]
                lines.append(f"  CA initial report: {text}")

        if comms:
            lines.append(f"  Commitments made:")
            for c in comms:
                lines.append(f"    [{c.get('grade','?')}] ({c.get('scope','?')}) {c.get('text','')[:200]}")
        rca_text = score.get('arc_rationale', '')
        if rca_text:
            lines.append(f"  Root cause analysis: {rca_text[:300]}")

    return '\n'.join(lines)


def _is_ca_comment(comment: dict, ca: str) -> bool:
    """Return True if comment is authored by CA staff (not community/Mozilla/system)."""
    author = comment.get('author', '').lower()
    if not author or '@' not in author:
        return False
    # Always exclude known non-CA accounts
    for excluded in ['mozilla.org', 'google.com', 'letsencrypt.org',
                     'chromium.org', 'cabforum.org', 'ccadb.org',
                     'certum.pl', 'harica.gr', 'amazon.com',
                     'beanwood.com', 'bugzilla-daemon']:
        if excluded in author:
            return False
    # Positive match: author domain suggests CA affiliation
    # Use keywords from CA name to match (rough but effective)
    ca_keywords = ca.lower().replace(',','').replace('.','').split()
    # Filter common words that appear in many CA names
    noise = {'ca','certificate','authority','trust','services','llc','inc',
             'gmbh','ag','sa','sl','bv','nv','the','of','for','and','s.a',
             'krajowa','izba','rozliczeniowa','certification'}
    ca_keywords = [w for w in ca_keywords if len(w) > 3 and w not in noise]
    domain = author.split('@')[1] if '@' in author else ''
    return any(kw in domain for kw in ca_keywords) if ca_keywords else True


def call_sonnet(history: str, api_key: str) -> dict | None:
    prompt = SYNTHESIS_PROMPT.format(history=history)
    payload = json.dumps({
        "model": SONNET_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_URL, data=payload, method="POST",
        headers={
            "Content-Type":     "application/json",
            "x-api-key":        api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
        text = result["content"][0]["text"].strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split('\n', 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)
    except Exception as e:
        print(f"  [synthesis] Sonnet error: {e}", file=sys.stderr)
        return None


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[synthesize] ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Which CAs to synthesize — default all elevated + distrusted, or pass names
    rescore = '--rescore' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    target_cas = args if args else None

    print("[synthesize] Loading data...")
    bugs_active    = load_json(DATA_DIR / "bugs_by_ca.json")           or {}
    bugs_distrusted= load_json(DATA_DIR / "bugs_by_ca_distrusted.json") or {}
    irq_cache      = load_json(CACHE_DIR / "irq_score_cache.json")      or {}
    comment_cache  = load_json(CACHE_DIR / "irq_comment_cache.json")    or {}
    als_scores     = load_json(DATA_DIR / "als_scores.json")            or {}

    # Load existing results
    out_path = DATA_DIR / "ca_pattern_chains.json"
    existing = load_json(out_path) or {"results": {}}
    results  = existing.get("results", {})

    # Determine which CAs to run
    if target_cas:
        candidates = {ca: bugs_active.get(ca) or bugs_distrusted.get(ca, [])
                      for ca in target_cas}
    else:
        # Elevated active + all distrusted with sufficient bugs
        elevated = {r['ca'] for r in als_scores.get('scores', [])
                    if r['scores']['flagged'] and r['signals']['n'] >= 10}
        distrusted = {ca for ca in bugs_distrusted if len(bugs_distrusted[ca]) >= 5}
        all_targets = elevated | distrusted
        candidates = {}
        for ca in all_targets:
            bugs = bugs_active.get(ca) or bugs_distrusted.get(ca, [])
            if bugs:
                candidates[ca] = bugs

    print(f"[synthesize] {len(candidates)} CAs to synthesize")

    for ca, bugs in sorted(candidates.items()):
        if ca in results and not rescore:
            print(f"  [skip] {ca} (cached)")
            continue

        print(f"  [synthesize] {ca} ({len(bugs)} bugs)...")
        history = build_ca_history(ca, bugs, irq_cache, comment_cache=comment_cache)
        if len(history) < 200:
            print(f"  [skip] {ca} — insufficient history")
            results[ca] = {"patterns": [], "synthesis_notes": "Insufficient history for synthesis"}
            continue

        # Estimate tokens (~4 chars/token)
        est_tokens = len(history) // 4
        print(f"    history: ~{est_tokens:,} tokens")

        result = call_sonnet(history, api_key)
        if result:
            n_patterns = len(result.get('patterns', []))
            print(f"    → {n_patterns} patterns found")
            results[ca] = result
        else:
            results[ca] = {"patterns": [], "synthesis_notes": "Synthesis failed"}

        # Save after each CA
        out_path.write_text(json.dumps({"results": results}, indent=2))

    print(f"\n[synthesize] Done. {sum(len(v.get('patterns',[])) for v in results.values())} total patterns across {len(results)} CAs")
    out_path.write_text(json.dumps({"results": results}, indent=2))
    print(f"[synthesize] Wrote {out_path}")


if __name__ == '__main__':
    main()
