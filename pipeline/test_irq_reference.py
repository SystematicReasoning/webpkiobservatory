#!/usr/bin/env python3
"""
test_irq_reference.py — Score IRQ reference dataset and print results.

Fetches comments for 7 labeled reference bugs, scores each via Haiku,
compares against expected values, and prints a summary.

Usage:
  ANTHROPIC_API_KEY=sk-ant-... python3 pipeline/test_irq_reference.py

Reference set (hand-labeled from reading threads):
  Ecommerce 1815534  — EXPECT arc=escalating, pc=ignored
  Ecommerce 1862004  — EXPECT arc=escalating, pc=ignored
  Camerfirma 1623384 — EXPECT arc=stalled,    pc=deflected
  Camerfirma 1609828 — EXPECT arc=stalled
  Entrust 1890123    — EXPECT arc=stalled
  Entrust 1901270    — EXPECT arc=stalled
  ISRG 1319609       — EXPECT arc=healthy
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
sys.path.insert(0, str(PIPELINE_DIR))
from utils import ANTHROPIC_URL, ANTHROPIC_VERSION

HAIKU_MODEL   = "claude-haiku-4-5-20251001"
CACHE_PATH    = PIPELINE_DIR / "ops_cache" / "irq_comment_cache.json"

# ── Reference dataset ──────────────────────────────────────────────────────
REFERENCE = [
    {
        "bug_id":          1815534,
        "ca":              "Ecommerce Monitoring",
        "label":           "precert serial/SCT — 42-comment thread",
        "expected_arc":    "escalating",
        "expected_pc":     "ignored",    # Aaron Gable raised pattern; CA asked to close
        "expected_patterns": ["evasive_response"],
    },
    {
        "bug_id":          1862004,
        "ca":              "Ecommerce Monitoring",
        "label":           "delayed revocation follow-up",
        "expected_arc":    "escalating",
        "expected_pc":     "ignored",
        "expected_patterns": ["customer_disruption"],
    },
    {
        "bug_id":          1623384,
        "ca":              "Camerfirma",
        "label":           "recurrent authorityKeyIdentifier",
        "expected_arc":    "stalled",
        "expected_pc":     "deflected",  # Wayne said "recurrence" — CA gave partial
        "expected_patterns": [],
    },
    {
        "bug_id":          1609828,
        "ca":              "Camerfirma",
        "label":           "decision not to revoke",
        "expected_arc":    "stalled",
        "expected_pc":     None,         # only 3 comments, no pattern connection
        "expected_patterns": ["customer_disruption"],
    },
    {
        "bug_id":          1890123,
        "ca":              "Entrust",
        "label":           "failed preliminary incident report",
        "expected_arc":    "stalled",
        "expected_pc":     None,
        "expected_patterns": [],         # formulaic boilerplate, but no explicit pattern
    },
    {
        "bug_id":          1901270,
        "ca":              "Entrust",
        "label":           "action items from June 2024 report",
        "expected_arc":    "stalled",
        "expected_pc":     None,
        "expected_patterns": [],
    },
    {
        "bug_id":          1319609,
        "ca":              "ISRG / Let's Encrypt",
        "label":           "certs contrary to CPS",
        "expected_arc":    "healthy",
        "expected_pc":     None,
        "expected_patterns": [],
    },
]

# ── Known participants for author classification ────────────────────────────
KNOWN_RP = {
    "ben wilson", "bwilson", "chrome-root-program", "chris clements",
    "cclements", "ryan sleevi", "dustin hollenback", "clint wilson",
}
KNOWN_COMMUNITY = {
    "andrew ayer", "agwa", "rob stradling", "wayne thayer", "wthayer",
    "amir omidi", "aaron gable", "ryan hurst", "ryan_hurst",
}
RP_DOMAINS = {
    "mozilla.com", "mozilla.org", "google.com", "apple.com",
    "fastly.com", "chromium.org",
}

def classify_author(author: str) -> str:
    lower = author.lower()
    name  = lower.split("@")[0].replace(".", " ").replace("-", " ")
    if any(k in name or k in lower for k in KNOWN_RP):        return "[RP]"
    if any(k in name or k in lower for k in KNOWN_COMMUNITY): return "[COM]"
    domain = lower.split("@")[1] if "@" in lower else ""
    if any(d in domain for d in RP_DOMAINS):                   return "[RP]"
    return "[CA]"


def fetch_comments(bug_id: int) -> list[dict]:
    url = f"https://bugzilla.mozilla.org/rest/bug/{bug_id}/comment"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "WebPKI-Observatory/1.0")
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    comments = data.get("bugs", {}).get(str(bug_id), {}).get("comments", [])
    return [
        {
            "author": c.get("creator", ""),
            "time":   c.get("creation_time", "")[:10],
            "text":   c.get("text", "")[:1400],
        }
        for c in comments
    ]


def format_thread(comments: list[dict], max_chars: int = 5500) -> str:
    lines, total = [], 0
    for i, c in enumerate(comments):
        role = classify_author(c["author"])
        line = f"[{i}]{role} {c['time']} {c['author']}: {c['text']}"
        if total + len(line) > max_chars:
            lines.append(f"[... {len(comments)-i} more comments not shown ...]")
            break
        lines.append(line)
        total += len(line)
    return "\n\n".join(lines)


PROMPT = """You are analyzing a Mozilla Bugzilla CA Certificate Compliance incident thread.

Bug: {summary}
Thread ({n} comments, filed {filed}):

{thread}

---

Return ONLY a JSON object with these exact fields:

{{
  "thread_health_arc": "healthy | stalled | escalating | cascade",
  "arc_rationale": "one sentence",
  "defensive_patterns": [],
  "accountability_debt": {{
    "unanswered_rp_questions": 0,
    "template_corrections": 0,
    "commitment_probe_repeated": 0
  }},
  "pattern_connection": {{
    "present": false,
    "made_by": "root_program | community | null",
    "ca_response": "acknowledged | deflected | ignored | null"
  }},
  "spawned_bugs": 0,
  "confidence": "high | medium | low"
}}

DEFINITIONS:

Arc:
  healthy    = Self-reported or prompt ack, clear RCA accepted, clean closure.
  stalled    = Incomplete report, template corrections, slow/repeated responses, loop.
  escalating = Defensive response, CA pushes back on requirements, trust discussion.
  cascade    = Single incident spawns multiple new bugs during investigation.

Defensive patterns (CA's own comments only — must be explicit):
  not_a_compliance_issue  — claims behavior isn't prohibited
  customer_disruption     — declines to revoke citing subscriber/business harm
  no_security_impact      — minimizes severity of the compliance failure
  evasive_response        — answers adjacent questions, not the one asked
  changing_positions      — shifts explanation between comments
  non_responsive          — no answer within expected timeframe
  not_required_detail     — argues requested specificity is voluntary
  legal_threat            — explicit or implied legal action
  coordinated_cpr_claim   — characterizes problem reports as coordinated attack
  based_on_root_program_feedback — cites prior conversations as authorization

Pattern connection:
  A commenter explicitly links THIS incident to prior incidents of the same class
  from this CA. Examples: "this is the Nth time you've filed this class",
  "you committed to fixing this in bug X", "this same failure appeared in 2021".
  [RP] = root program, [COM] = community researcher, [CA] = CA operator.
  ca_response:
    acknowledged = CA explicitly accepts the systemic/recurring nature
    deflected    = CA responds but treats it as a one-off or argues context differs
    ignored      = CA does not address the pattern connection in subsequent comments"""


def score_bug(ref: dict, comments: list[dict], api_key: str) -> dict:
    thread = format_thread(comments)
    prompt = PROMPT.format(
        summary=ref["label"],
        n=len(comments),
        filed=comments[0]["time"] if comments else "?",
        thread=thread,
    )
    body = json.dumps({
        "model":    HAIKU_MODEL,
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_URL, data=body, method="POST",
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    text = "".join(
        b["text"] for b in result.get("content", []) if b.get("type") == "text"
    ).strip()
    if text.startswith("```"):
        text = "\n".join(l for l in text.split("\n") if not l.strip().startswith("```"))
    return json.loads(text.strip())


# ── ANSI colours ───────────────────────────────────────────────────────────
G = "\033[92m"   # green
R = "\033[91m"   # red
Y = "\033[93m"   # yellow
B = "\033[94m"   # blue
D = "\033[2m"    # dim
RESET = "\033[0m"


def coloured_arc(arc: str) -> str:
    colours = {
        "healthy":    "\033[92m",
        "stalled":    "\033[93m",
        "escalating": "\033[91m",
        "cascade":    "\033[95m",
    }
    return f"{colours.get(arc, '')}{arc}{RESET}"


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print(f"{R}ERROR: ANTHROPIC_API_KEY not set{RESET}")
        sys.exit(1)

    # Load comment cache
    cache: dict = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text())
        print(f"{D}Loaded {len(cache)} cached comment threads{RESET}\n")

    arc_correct    = 0
    arc_total      = 0
    pc_correct     = 0
    pc_total       = 0
    pat_tp         = 0   # expected pattern present and found
    pat_fn         = 0   # expected pattern not found
    all_results    = []

    print("=" * 80)
    print("IRQ REFERENCE DATASET — LIVE SCORING")
    print(f"Model: {HAIKU_MODEL}")
    print("=" * 80)

    for ref in REFERENCE:
        bid  = str(ref["bug_id"])
        print(f"\n{B}[{ref['bug_id']}]{RESET} {ref['ca']} — {ref['label']}")

        # Fetch or use cache
        if bid not in cache:
            print(f"  {D}Fetching comments...{RESET}", end="", flush=True)
            try:
                comments = fetch_comments(ref["bug_id"])
                cache[bid] = comments
                CACHE_PATH.write_text(json.dumps(cache))
                print(f" {len(comments)} comments")
            except Exception as e:
                print(f"\n  {R}Fetch error: {e}{RESET}")
                continue
        else:
            comments = cache[bid]
            print(f"  {D}Using cached {len(comments)} comments{RESET}")

        if len(comments) < 2:
            print(f"  {Y}Too few comments to score (<2){RESET}")
            continue

        # Score
        print(f"  {D}Scoring via Haiku...{RESET}", end="", flush=True)
        try:
            result = score_bug(ref, comments, api_key)
            time.sleep(0.3)
        except Exception as e:
            print(f"\n  {R}Score error: {e}{RESET}")
            continue
        print(" done")

        arc    = result.get("thread_health_arc", "?")
        rationale = result.get("arc_rationale", "")
        patterns  = result.get("defensive_patterns", [])
        pc        = result.get("pattern_connection", {})
        debt      = result.get("accountability_debt", {})
        conf      = result.get("confidence", "?")

        # Arc check
        arc_total += 1
        arc_ok = arc == ref["expected_arc"]
        if arc_ok: arc_correct += 1
        arc_sym = f"{G}✓{RESET}" if arc_ok else f"{R}✗{RESET}"

        print(f"  Arc:      {coloured_arc(arc)} {arc_sym}  (expected: {ref['expected_arc']})")
        print(f"  Rationale:{D} {rationale}{RESET}")
        print(f"  Conf:     {conf}")

        # Defensive patterns
        if patterns:
            print(f"  Patterns: {Y}{', '.join(patterns)}{RESET}")
        else:
            print(f"  Patterns: {D}none{RESET}")

        for exp_pat in ref.get("expected_patterns", []):
            if exp_pat in patterns:
                print(f"  {G}  ✓ expected pattern found: {exp_pat}{RESET}")
                pat_tp += 1
            else:
                print(f"  {R}  ✗ expected pattern MISSING: {exp_pat}{RESET}")
                pat_fn += 1

        # Accountability debt
        u = debt.get("unanswered_rp_questions", 0)
        t = debt.get("template_corrections", 0)
        r = debt.get("commitment_probe_repeated", 0)
        if u or t or r:
            print(f"  Debt:     unanswered_rp={u}  template_fixes={t}  repeated={r}")

        # Pattern connection — the key signal
        if pc.get("present"):
            ca_resp = pc.get("ca_response", "?")
            made_by = pc.get("made_by", "?")
            resp_colour = {"acknowledged": G, "deflected": Y, "ignored": R}.get(ca_resp, "")
            print(f"  PatConn:  raised by {made_by} → CA {resp_colour}{ca_resp}{RESET}", end="")
            if ref["expected_pc"] is not None:
                pc_total += 1
                pc_ok = ca_resp == ref["expected_pc"]
                if pc_ok: pc_correct += 1
                pc_sym = f"{G}✓{RESET}" if pc_ok else f"{R}✗{RESET}"
                print(f"  {pc_sym} (expected: {ref['expected_pc']})")
            else:
                print()
        else:
            print(f"  PatConn:  {D}not present{RESET}", end="")
            if ref["expected_pc"] is not None:
                print(f"  {R}✗ expected pattern connection was NOT detected{RESET}")
                pc_total += 1
            else:
                print()

        all_results.append({"ref": ref, "result": result, "arc_ok": arc_ok})

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    arc_pct = arc_correct / arc_total * 100 if arc_total else 0
    arc_col = G if arc_pct >= 80 else (Y if arc_pct >= 60 else R)
    print(f"Arc classification:          {arc_col}{arc_correct}/{arc_total} = {arc_pct:.0f}%{RESET}")

    if pc_total:
        pc_pct = pc_correct / pc_total * 100
        pc_col = G if pc_pct >= 70 else (Y if pc_pct >= 50 else R)
        print(f"Pattern connection response: {pc_col}{pc_correct}/{pc_total} = {pc_pct:.0f}%{RESET}")
    else:
        print(f"Pattern connection response: {D}no labeled cases triggered{RESET}")

    if pat_tp + pat_fn:
        pat_pct = pat_tp / (pat_tp + pat_fn) * 100
        pat_col = G if pat_pct >= 70 else (Y if pat_pct >= 50 else R)
        print(f"Defensive pattern recall:    {pat_col}{pat_tp}/{pat_tp+pat_fn} = {pat_pct:.0f}%{RESET}")

    print()

    # Per-CA summary
    ca_scores: dict[str, dict] = {}
    for r in all_results:
        ca = r["ref"]["ca"]
        arc = r["result"].get("thread_health_arc", "?")
        if ca not in ca_scores:
            ca_scores[ca] = {"arcs": [], "patterns": [], "pc_responses": []}
        ca_scores[ca]["arcs"].append(arc)
        ca_scores[ca]["patterns"].extend(r["result"].get("defensive_patterns", []))
        pc = r["result"].get("pattern_connection", {})
        if pc.get("present") and pc.get("ca_response"):
            ca_scores[ca]["pc_responses"].append(pc["ca_response"])

    print("PER-CA PROFILE:")
    for ca, s in ca_scores.items():
        from collections import Counter
        arc_dist = Counter(s["arcs"])
        pat_dist = Counter(s["patterns"])
        dominant_arc = arc_dist.most_common(1)[0][0] if arc_dist else "?"
        print(f"  {ca}")
        print(f"    Arcs:     {dict(arc_dist)}  → dominant: {coloured_arc(dominant_arc)}")
        if pat_dist:
            print(f"    Patterns: {dict(pat_dist)}")
        if s["pc_responses"]:
            print(f"    PC resp:  {s['pc_responses']}")

    print()
    if arc_pct >= 80:
        print(f"{G}Model is performing well on arc classification (≥80%).{RESET}")
        print("Ready to run full corpus once API key is available in CI.")
    elif arc_pct >= 60:
        print(f"{Y}Arc classification is acceptable (≥60%) but could be improved.{RESET}")
        print("Review misclassified bugs and consider prompt tuning.")
    else:
        print(f"{R}Arc classification below threshold (<60%). Prompt needs work.{RESET}")


if __name__ == "__main__":
    main()
