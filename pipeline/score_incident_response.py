#!/usr/bin/env python3
"""
score_incident_response.py — Incident Response Quality (IRQ) pipeline

Scores each Bugzilla incident thread using ForgeIQ's empirical framework:

  THREAD HEALTH ARC (per bug):
    healthy, accountability_pressure, stalled, escalating, cascade

  INTEGRITY DIMENSIONS (per bug — each good|partial|poor):
    candor               — are disclosures accurate and complete from the start?
    accountability       — does the CA own the failure or deflect to tools/policy?
    obligation_understanding — does the CA grasp what requirement was violated?

  RCA DEPTH (per bug, 1–4):
    1 = no root cause / incoherent
    2 = proximate cause only (what, not why)
    3 = systemic cause identified but not fully accepted
    4 = complete systemic RCA accepted by root program

  COMMITMENTS (per bug — each graded A–F):
    A = specific + verifiable + timeline + addresses systemic cause
    B = specific + verifiable, instance-scoped or missing timeline
    C = action identified but vague outcome or timeline
    D = restatement of prior commitment or BR obligation
    F = no commitment made
    is_restatement = true if CA made same commitment in a prior bug and it didn't hold

  CA DEFENSIVE PATTERNS (per bug):
    not_a_compliance_issue, customer_disruption, no_security_impact,
    evasive_response, changing_positions, non_responsive,
    not_required_detail, legal_threat, coordinated_cpr_claim,
    based_on_root_program_feedback

  ACCOUNTABILITY DEBT (per bug):
    unanswered_rp_questions, template_corrections, commitment_probe_repeated

  PATTERN CONNECTION RESPONSE (per bug):
    acknowledged | deflected | ignored

  TIMELINESS (deterministic from timestamps, no LLM):
    avg_thread_days, max_silence_gap, avg_rp_lag_days, avg_ca_ratio

  LONGITUDINAL ARC TREND (per CA):
    worsening | stable | improving

IRQ FAILURE (0-30):
  arc_failure*8 + integrity*6 + rca_depth*4 + commitment_quality*4
  + pattern_connection_response*4 + accountability_debt*2 + cascade*2
  + 20% boost if >30% escalating arcs
  + 10% boost if arc trend is worsening

Reads:  data/bugs_by_ca.json, data/bugs_by_ca_distrusted.json
Writes: data/irq_scores.json
Cache:  ops_cache/irq_comment_cache.json, ops_cache/irq_score_cache.json

Uses Claude Haiku (~$7 for full rescore of 1,615-bug corpus).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
DATA_DIR     = PIPELINE_DIR.parent / "data"
CACHE_DIR    = PIPELINE_DIR / "ops_cache"

sys.path.insert(0, str(PIPELINE_DIR))
from utils import load_json, save_json, now_utc, ANTHROPIC_URL, ANTHROPIC_MODEL, ANTHROPIC_VERSION

COMMENT_CACHE_PATH = CACHE_DIR / "irq_comment_cache.json"
SCORE_CACHE_PATH   = CACHE_DIR / "irq_score_cache.json"

HAIKU_MODEL  = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-5"

# ── Known participant roles (from ForgeIQ commenter_roles.json) ───────────────
# Used to classify comment authors without domain matching
KNOWN_PARTICIPANTS = {
    # Root program — Mozilla
    "ben wilson":            "root_program",
    "kathleen wilson":       "root_program",
    "bwilson":               "root_program",
    # Root program — Chrome
    "chrome-root-program":   "root_program",
    "chris clements":        "root_program",
    "ryan dickson":          "root_program",
    "ryan sleevi":           "root_program",
    "cclements":             "root_program",
    # Root program — Apple
    "dustin hollenback":     "root_program",
    "clint wilson":          "root_program",
    # Community researchers (weighted)
    "andrew ayer":           "community",
    "agwa":                  "community",
    "rob stradling":         "community",
    "wayne thayer":          "community",
    "wthayer":               "community",
    "amir omidi":            "community",
    "aaron gable":           "community",
    "ryan hurst":            "community",
    "ryan_hurst":            "community",
    "jeremy rowley":         "community",
    "tim callan":            "community",
}

# ── Scoring prompt ────────────────────────────────────────────────────────────

SCORE_PROMPT = """You are analyzing a Mozilla Bugzilla CA Certificate Compliance incident thread.
[RP] = root program staff. [COM] = community researcher. [CA] = CA operator.

CA POSTURE CONTEXT (from full incident history):
{ca_profile}

THREAD SUMMARY (from full thread analysis):
{thread_summary}

Bug: {summary}
Tags: {tags}
Filed: {filed} | Total comments: {n_comments}
Structural flags: {meta}

Thread (showing first 3 + most recent comments):

{thread}

---

Return ONLY valid JSON — no markdown fences, no extra text:

{{
  "thread_health_arc": "healthy",
  "arc_rationale": "one sentence",

  "rca_depth": 1,

  "integrity": {{
    "candor": "good",
    "accountability": "good",
    "obligation_understanding": "good"
  }},

  "commitments": [],

  "defensive_patterns": [],
  "accountability_debt": {{
    "unanswered_rp_questions": 0,
    "template_corrections": 0,
    "commitment_probe_repeated": 0
  }},
  "pattern_connection": {{
    "present": false,
    "made_by": null,
    "ca_response": null
  }},
  "spawned_bugs": 0,
  "confidence": "high"
}}

═══ ARC DEFINITIONS ═══
healthy                = Self-reported OR prompt acknowledgment. Clear systemic RCA accepted by [RP].
                         Action items complete with evidence. Clean closure. Typically 4-8 weeks.
accountability_pressure = CA accepts the obligation but hasn't met the bar — being pushed to do so.
                         Questions arise because response was incomplete/shallow, not because CA
                         contests requirements. Most common pattern.
stalled                = External discovery. Incomplete report, template corrections needed.
                         Formulaic responses ("no updates", "will continue to monitor") loop
                         without progress. 3-12 months before forced resolution.
escalating             = CA ACTIVELY contests requirements: argues obligations don't apply, claims
                         subscriber interests override mandatory action, treats compliance as
                         negotiable. CA argues against oversight itself.
cascade                = Single incident spawns multiple new bugs during investigation.

KEY DISTINCTION: accountability_pressure = CA accepts obligation but fails to execute.
escalating = CA contests the obligation itself. Ask: slow/shallow, or arguing back?

CRITICAL: Arc reflects the FINAL STATE of the thread, not the process to get there.
If the thread CLOSED with all action items complete and RP satisfied — even if pressure
was needed along the way — the arc is "healthy". Accountability_pressure applies only
when the thread is STILL OPEN or closed with items genuinely incomplete.
Ask: how did the thread END, not what happened in the middle?

═══ RCA DEPTH (1–4) ═══
1 = No root cause, or incoherent ("reviewing our processes", "linter didn't catch it",
    blaming external tools without explaining why the CA's controls failed)
2 = Proximate cause only — describes WHAT happened but not WHY the system allowed it.
    "We issued a certificate with the wrong field" without explaining the systemic gap.
3 = Systemic cause identified — explains the underlying control failure — but not fully
    accepted/verified by root program, or missing complete action item traceability.
4 = Complete systemic RCA accepted by root program. Action items trace to stated causes.
    Community/RP explicitly agrees the analysis is adequate.

═══ INTEGRITY (each field: good | partial | poor) ═══
candor:
  good    = Disclosures accurate and complete from the start; no facts emerge only under
            direct questioning; timeline is honest even when unflattering.
  partial = Accurate but incomplete; scope understated initially; additional facts emerge
            only after RP/community questioning.
  poor    = Inaccurate, misleading, or selectively disclosed. CA's framing contradicted
            by evidence. Facts omitted that only surface under repeated challenge.

accountability:
  good    = CA clearly owns the failure. No deflection to tools, auditors, subscribers,
            or policy ambiguity. "We failed to..." not "The linter failed to..."
  partial = Accepts responsibility for the specific violation but attributes contributing
            factors to tools, policy ambiguity, third parties, or prior guidance.
  poor    = Deflects ownership. Blames linters/tools as primary cause, argues policy
            ambiguity excuses the behavior, attributes to subscriber requests.

obligation_understanding:
  good    = CA demonstrates clear understanding of what requirement was violated and why
            from the first substantive response.
  partial = Understands the violation occurred but initially misunderstands scope,
            implications, or which specific requirement applies. Corrected under questioning.
  poor    = Fundamental misunderstanding. "RFC doesn't require X" when it does. Believing
            subscriber interest overrides mandatory revocation. Not knowing the 5-day window
            applies. Requires multiple rounds to reach basic factual agreement.

═══ COMMITMENTS (array — include ALL commitments CA makes) ═══
Each commitment: {{"text": "brief description", "scope": "instance|class|architectural", "grade": "A|B|C|D|F", "is_restatement": false}}

scope:
  instance     = addresses only this specific certificate/system/event
  class        = addresses this failure type going forward across all issuance
  architectural = changes the underlying process, system, or control structure

grade:
  A = Specific action + verifiable outcome + timeline + addresses systemic cause.
      "We will implement pre-issuance linting covering all BR profile fields by 2024-Q3,
       with lint results logged in our incident tracking system."
  B = Specific + verifiable, but instance-scoped OR missing timeline.
      "We have revoked all affected certificates and implemented a check for this field."
  C = Action identified but vague: missing timeline, unmeasurable outcome, or vague
      action. "We will improve our monitoring processes."
  D = Restatement of a BR obligation ("we will comply with section 4.9.1.1") or
      restatement of a prior commitment from an earlier bug that wasn't fulfilled.
  F = No commitment, or counterproductive response (asking to close without action items,
      committing to nothing despite clear open questions).

is_restatement = true if CA made this same commitment in a prior bug and it evidently
didn't hold (prior bug was closed but same failure class reappeared).

If no commitments were made: "commitments": []
If the CA only restated BRs without adding anything new: one entry grade D.

═══ DEFENSIVE PATTERNS (CA's own comments only — must be explicit) ═══
not_a_compliance_issue, customer_disruption, no_security_impact, evasive_response,
changing_positions, non_responsive, not_required_detail, legal_threat,
coordinated_cpr_claim, based_on_root_program_feedback

═══ PATTERN CONNECTION (most diagnostic behavioral signal) ═══
present=true if ANYONE explicitly or implicitly links this incident to prior incidents
of the same class. ca_response: acknowledged=CA accepts systemic framing |
deflected=avoids systemic framing | ignored=CA does not address the connection"""




# ── CA posture profile (Improvement 1) ───────────────────────────────────────
# Built once per CA before scoring its bugs. Passed as context to each bug
# prompt so the model can place individual threads in their full history.

CA_PROFILE_PROMPT = """Summarize this CA's compliance posture for use as context when scoring individual incident threads. Be factual, not speculative.

CA: {ca_name}
Bugs: {n_bugs} over {year_span} ({year_start}–{year_end})
Self-report rate: {self_pct:.0f}%
Chronic classes (same tag 3+ distinct years): {chronic}
Posture label (if in distrust record): {posture}

Return ONLY: {{"profile": "2-3 sentence factual summary"}}"""


# ── Two-pass: thread summary (Improvement 2) ─────────────────────────────────
# Pass 1: Summarize the FULL thread (all comments, no char limit).
# Pass 2: Score against summary + tail excerpt.
# This ensures nothing is lost in truncation.

THREAD_SUMMARY_PROMPT = """Summarize this Mozilla Bugzilla CA compliance incident thread.
[RP]=root program [COM]=community researcher [CA]=CA operator.

Bug: {summary}
{n} total comments:

{thread}

---

Return ONLY valid JSON:
{{
  "incident_class": "misissuance | infrastructure | disclosure | governance | security",
  "discovery": "self | external",
  "ca_initial_position": "one sentence",
  "rp_key_questions": [],
  "ca_answered_all": true,
  "unresolved_at_close": [],
  "pattern_connections_made": [],
  "pattern_connection_ca_response": null,
  "ca_contested_requirements": false,
  "closure_type": "accepted | forced | pending",
  "thread_months": 0
}}

pattern_connections_made: list any comments where [RP] or [COM] explicitly noted this
failure class has recurred or matches a prior incident pattern.

pattern_connection_ca_response: if a pattern connection was raised, how did the CA respond?
  "acknowledged" = CA explicitly agreed this is a recurring pattern and addressed it
  "deflected"    = CA acknowledged the comment but minimised/redirected without engaging
  "ignored"      = CA made no substantive response to the pattern connection comment
  null           = no pattern connection was raised"""


def build_ca_profile(ca_name: str, bugs: list[dict], distrust_event: dict | None,
                     api_key: str) -> str | None:
    """
    Build a 2-3 sentence posture summary for a CA from its full bug history.
    Called once per CA before scoring its individual bugs.
    Returns a plain-text profile string, or None if API call fails.
    """
    if not bugs or not api_key:
        return None

    import re as _re
    from collections import defaultdict as _dd, Counter as _Counter

    # Compute signals from bug history
    by_year_tag: dict = _dd(set)
    years_list = []
    self_count = 0

    for b in bugs:
        filed = b.get("filed", "")
        year  = int(filed[:4]) if filed and len(filed) >= 4 else None
        if year:
            years_list.append(year)
            tags = [t for t in _re.findall(r'\[([^\]]+)\]', b.get("whiteboard", ""))
                    if t not in ("ca-compliance", "ca-verified", "", "uncategorized", "audit-finding")]
            for t in tags:
                by_year_tag[t].add(year)
        if b.get("self_reported"):
            self_count += 1

    n = len(bugs)
    self_pct = self_count / n * 100 if n else 0
    years_list = sorted(set(years_list))
    year_span = f"{years_list[0]}–{years_list[-1]}" if len(years_list) >= 2 else (str(years_list[0]) if years_list else "unknown")

    chronic = [t for t, yrs in by_year_tag.items() if len(yrs) >= 3]
    posture = distrust_event.get("compliance_posture", "none") if distrust_event else "none"

    prompt = CA_PROFILE_PROMPT.format(
        ca_name=ca_name,
        n_bugs=n,
        year_span=year_span,
        year_start=years_list[0] if years_list else "?",
        year_end=years_list[-1] if years_list else "?",
        self_pct=self_pct,
        chronic=", ".join(chronic[:8]) or "none",
        posture=posture,
    )

    try:
        import json as _json, urllib.request as _req
        body = _json.dumps({
            "model":    HAIKU_MODEL,
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = _req.Request(
            ANTHROPIC_URL, data=body, method="POST",
            headers={"Content-Type": "application/json", "x-api-key": api_key,
                     "anthropic-version": ANTHROPIC_VERSION},
        )
        with _req.urlopen(req, timeout=20) as resp:
            result = _json.loads(resp.read())
        text = result["content"][0]["text"]
        m = _re.search(r'\{.*\}', text, _re.DOTALL)
        if m:
            return _json.loads(m.group()).get("profile", "")
    except Exception as e:
        print(f"  [profile] {ca_name}: {e}", file=__import__("sys").stderr)
    return None


def summarize_thread(bug: dict, comments: list[dict], api_key: str) -> dict | None:
    """
    Pass 1: summarize the FULL comment thread, no truncation.
    Returns a structured summary dict used by score_bug_with_summary().
    """
    if len(comments) < 2 or not api_key:
        return None

    # Format ALL comments — no char limit in summary pass
    lines = []
    for i, c in enumerate(comments):
        role = classify_author(c["author"])
        tag  = {"root_program": "[RP]", "community": "[COM]", "ca": "[CA]"}.get(role, "[?]")
        # Trim individual comments to 800 chars but include all of them
        lines.append(f"[{i}]{tag} {c['time']} {c['author']}: {c['text'][:800]}")
    full_thread = "\n\n".join(lines)

    prompt = THREAD_SUMMARY_PROMPT.format(
        summary=bug.get("summary", "")[:200],
        n=len(comments),
        thread=full_thread,
    )

    import json as _json, urllib.request as _req, re as _re
    try:
        body = _json.dumps({
            "model":    HAIKU_MODEL,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = _req.Request(
            ANTHROPIC_URL, data=body, method="POST",
            headers={"Content-Type": "application/json", "x-api-key": api_key,
                     "anthropic-version": ANTHROPIC_VERSION},
        )
        with _req.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read())
        text = result["content"][0]["text"]
        m = _re.search(r'\{.*\}', text, _re.DOTALL)
        return _json.loads(m.group()) if m else None
    except Exception as e:
        print(f"  [summary] Bug {bug.get('id')}: {e}", file=__import__("sys").stderr)
        return None



# ── Bugzilla fetch ────────────────────────────────────────────────────────────

def fetch_comments(bug_id: int) -> list[dict]:
    url = f"https://bugzilla.mozilla.org/rest/bug/{bug_id}/comment"
    try:
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "WebPKI-Observatory/1.0")
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        comments = data.get("bugs", {}).get(str(bug_id), {}).get("comments", [])
        return [
            {
                "author": c.get("creator", ""),
                "time":   c.get("creation_time", "")[:10],
                "text":   c.get("text", "")[:1500],
            }
            for c in comments
        ]
    except Exception as e:
        print(f"  [fetch] Bug {bug_id}: {e}", file=sys.stderr)
        return []


def classify_author(author: str) -> str:
    """Classify comment author as root_program, community, or ca."""
    name_lower = author.split("@")[0].lower().replace(".", " ").replace("-", " ")
    for pattern, role in KNOWN_PARTICIPANTS.items():
        if pattern in name_lower or pattern in author.lower():
            return role
    # Domain-based fallback
    domain = author.split("@")[1].lower() if "@" in author else ""
    rp_domains = ["mozilla.com", "mozilla.org", "google.com", "apple.com",
                  "microsoft.com", "fastly.com", "chromium.org"]
    if any(d in domain for d in rp_domains):
        return "root_program"
    return "ca"  # default assumption for unknown authors on their own bugs


def format_thread(comments: list[dict], max_chars: int = 9000) -> tuple[str, dict]:
    """
    Format thread for LLM with structural pre-summary + tail-weighted window.

    Returns (formatted_thread, metadata) where metadata contains structural
    signals computed before truncation: boilerplate count, response delay,
    etc. that the model should know even if those comments aren't shown.
    """
    # ── Compute structural metadata across ALL comments ───────────────────
    boilerplate_phrases = [
        "we have no updates",
        "will continue to monitor",
        "no further updates",
        "no updates for this week",
        "no updates and will continue",
        "kindly request closing",
        "request this bug be closed",
    ]
    boilerplate_count = 0
    ca_first_response_idx = None
    rp_unanswered = 0
    last_rp_question_idx = None

    for i, c in enumerate(comments):
        role = classify_author(c["author"])
        text_lower = c["text"].lower()
        if role == "ca":
            if ca_first_response_idx is None and i > 0:
                ca_first_response_idx = i
            for phrase in boilerplate_phrases:
                if phrase in text_lower:
                    boilerplate_count += 1
                    break
        elif role in ("root_program", "community"):
            if "?" in c["text"]:
                last_rp_question_idx = i

    # Count unanswered: if last RP question is after last CA comment, it's unanswered
    last_ca_idx = max((i for i,c in enumerate(comments) if classify_author(c["author"]) == "ca"), default=-1)
    if last_rp_question_idx is not None and last_rp_question_idx > last_ca_idx:
        rp_unanswered = 1

    # Days from filing to first CA response
    response_delay_days = None
    if ca_first_response_idx and ca_first_response_idx > 0:
        try:
            from datetime import datetime
            t0 = datetime.fromisoformat(comments[0]["time"])
            t1 = datetime.fromisoformat(comments[ca_first_response_idx]["time"])
            response_delay_days = (t1 - t0).days
        except Exception:
            pass

    metadata = {
        "total_comments": len(comments),
        "boilerplate_count": boilerplate_count,
        "ca_response_delay_days": response_delay_days,
        "rp_questions_after_last_ca": rp_unanswered,
    }

    # ── Build structural preamble ─────────────────────────────────────────
    preamble_parts = []
    if boilerplate_count >= 2:
        preamble_parts.append(
            f"⚠ CA posted boilerplate 'no updates'/'request to close' language {boilerplate_count} times across thread"
        )
    if response_delay_days is not None and response_delay_days > 5:
        preamble_parts.append(
            f"⚠ CA first responded {response_delay_days} days after filing"
        )
    if len(comments) > 15:
        preamble_parts.append(
            f"ℹ Thread has {len(comments)} total comments — showing first 3 and last {max_chars//400} for context"
        )

    preamble = "\n".join(preamble_parts)

    # ── Tail-weighted window: show first 3 comments + as many recent ones as fit ──
    # This ensures we see the initial filing AND the most recent (often most diagnostic) content
    head_comments = comments[:3]
    tail_comments = list(reversed(comments[3:]))  # most recent first

    head_lines = []
    for i, c in enumerate(head_comments):
        role = classify_author(c["author"])
        tag = {"root_program": "[RP]", "community": "[COM]", "ca": "[CA]"}.get(role, "[?]")
        head_lines.append(f"[{i}]{tag} {c['time']} {c['author']}: {c['text']}")

    head_str = "\n\n".join(head_lines)
    remaining_chars = max_chars - len(head_str) - len(preamble) - 200

    tail_lines = []
    tail_chars = 0
    skipped = 0
    for c in tail_comments:
        real_idx = comments.index(c)
        role = classify_author(c["author"])
        tag = {"root_program": "[RP]", "community": "[COM]", "ca": "[CA]"}.get(role, "[?]")
        line = f"[{real_idx}]{tag} {c['time']} {c['author']}: {c['text']}"
        if tail_chars + len(line) > remaining_chars:
            skipped += 1
            continue
        tail_lines.append(line)
        tail_chars += len(line)

    tail_lines.reverse()  # restore chronological order

    parts = []
    if preamble:
        parts.append(preamble)
        parts.append("---")
    parts.extend(head_lines)
    if skipped:
        parts.append(f"\n[... {skipped} middle comments not shown ...]\n")
    parts.extend(tail_lines)

    return "\n\n".join(parts), metadata


# ── LLM scoring ───────────────────────────────────────────────────────────────

def score_bug(bug: dict, comments: list[dict], ca_profile: str | None = None) -> dict | None:
    """Score a single bug thread via Haiku."""
    if not comments or len(comments) < 2:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    thread, meta = format_thread(comments)

    # Build metadata note for prompt
    meta_notes = []
    if meta["boilerplate_count"] >= 2:
        meta_notes.append(f"CA posted boilerplate 'no updates' language {meta['boilerplate_count']} times")
    if meta["ca_response_delay_days"] and meta["ca_response_delay_days"] > 5:
        meta_notes.append(f"CA first responded {meta['ca_response_delay_days']} days after filing")
    if meta["rp_questions_after_last_ca"]:
        meta_notes.append("Root program questions remain unanswered after last CA comment")
    meta_str = " | ".join(meta_notes) if meta_notes else "no structural flags"

    # Pass 1: summarize full thread (addresses truncation problem)
    thread_summ = summarize_thread(bug, comments, api_key)
    thread_summary_str = "none available"
    if thread_summ:
        import json as _jj
        pc_response_from_summary = thread_summ.get('pattern_connection_ca_response')
        thread_summary_str = (
            f"incident_class={thread_summ.get('incident_class','?')} | "
            f"discovery={thread_summ.get('discovery','?')} | "
            f"ca_contested={thread_summ.get('ca_contested_requirements',False)} | "
            f"closure={thread_summ.get('closure_type','?')} | "
            f"duration={thread_summ.get('thread_months','?')}mo | "
            f"unresolved={thread_summ.get('unresolved_at_close',[])} | "
            f"patterns_raised={thread_summ.get('pattern_connections_made',[])} | "
            f"pattern_ca_response={pc_response_from_summary} | "
            f"ca_answered_all={thread_summ.get('ca_answered_all',True)}"
        )
    else:
        pc_response_from_summary = None

    prompt = SCORE_PROMPT.format(
        ca_profile=ca_profile or "no prior history available",
        thread_summary=thread_summary_str,
        summary=bug.get("summary", "")[:200],
        tags=bug.get("whiteboard", ""),
        n_comments=meta["total_comments"],
        filed=bug.get("filed", "?"),
        meta=meta_str,
        thread=thread,
    )

    try:
        body = json.dumps({
            "model":      SONNET_MODEL,   # Sonnet for better arc calibration
            "max_tokens": 1100,
            "messages":   [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=body,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        text = "".join(
            b["text"] for b in result.get("content", []) if b.get("type") == "text"
        ).strip()

        # Extract JSON object — handles markdown fences and trailing content
        import re as _re
        m = _re.search(r'\{.*\}', text, _re.DOTALL)
        if not m:
            print(f"  [score] No JSON object in response", file=sys.stderr)
            return None
        scored = json.loads(m.group())

        # Pattern connection: Pass 2 may miss the CA's response if it was in a
        # middle comment truncated from the window. Use Pass 1 (full thread) as
        # authoritative when Pass 2 returns null for ca_response.
        pc_scored = scored.get("pattern_connection", {"present": False})
        if isinstance(pc_scored, dict):
            patterns_raised = (thread_summ or {}).get("pattern_connections_made", [])
            if patterns_raised and not pc_scored.get("ca_response") and pc_response_from_summary:
                pc_scored = {
                    "present":     True,
                    "made_by":     pc_scored.get("made_by"),
                    "ca_response": pc_response_from_summary,
                    "rationale":   "determined from full-thread summary (Pass 1)",
                }

        return {
            "thread_health_arc":   scored.get("thread_health_arc", "stalled"),
            "arc_rationale":       scored.get("arc_rationale", ""),
            "rca_depth":           int(scored.get("rca_depth", 2)),
            "integrity":           scored.get("integrity", {
                                       "candor": "partial",
                                       "accountability": "partial",
                                       "obligation_understanding": "partial",
                                   }),
            "commitments":         scored.get("commitments", []),
            "defensive_patterns":  scored.get("defensive_patterns", []),
            "accountability_debt": scored.get("accountability_debt", {}),
            "pattern_connection":  pc_scored,
            "spawned_bugs":        int(scored.get("spawned_bugs", 0)),
            "confidence":          scored.get("confidence", "medium"),
            "filed_year":          int(bug.get("filed", "2000")[:4]),
            "bug_id":              str(bug.get("id", "")),
        }

    except Exception as e:
        print(f"  [score] LLM error: {e}", file=sys.stderr)
        return None


# ── Per-CA aggregation ────────────────────────────────────────────────────────

ARC_FAILURE_WEIGHT = {
    "healthy":                 0,
    "accountability_pressure": 1,   # CA has homework but not contesting obligations
    "stalled":                 1,
    "escalating":              2,
    "cascade":                 1,
}

PATTERN_SEVERITY = {
    "not_a_compliance_issue":           3,
    "legal_threat":                     3,
    "coordinated_cpr_claim":            3,
    "customer_disruption":              2,
    "evasive_response":                 2,
    "changing_positions":               2,
    "no_security_impact":               1,
    "non_responsive":                   1,
    "not_required_detail":              1,
    "based_on_root_program_feedback":   1,
}


def aggregate_ca_irq(bug_scores: list[dict], n_bugs_total: int,
                     comment_threads: dict | None = None) -> dict:
    """Aggregate per-bug scores to per-CA IRQ.

    comment_threads: optional {bug_id_str: [comments]} for timeliness signals.
    """
    if not bug_scores:
        return {"irq_failure": None, "n_scored": 0, "n_bugs_total": n_bugs_total}

    n = len(bug_scores)

    # ── Arc distribution ──────────────────────────────────────────────────────
    arc_counts = defaultdict(int)
    for s in bug_scores:
        arc_counts[s["thread_health_arc"]] += 1

    arc_failure_rate = sum(
        ARC_FAILURE_WEIGHT.get(s["thread_health_arc"], 0) for s in bug_scores
    ) / (n * 2)

    # ── Defensive pattern severity ────────────────────────────────────────────
    all_patterns = []
    for s in bug_scores:
        all_patterns.extend(s.get("defensive_patterns", []))
    pattern_counts = defaultdict(int)
    for p in all_patterns:
        pattern_counts[p] += 1
    pattern_severity_total = sum(PATTERN_SEVERITY.get(p, 1) * c for p, c in pattern_counts.items())
    pattern_score = min(pattern_severity_total / 20, 1.0)

    # ── Accountability debt ───────────────────────────────────────────────────
    total_unanswered  = sum(s.get("accountability_debt", {}).get("unanswered_rp_questions", 0) for s in bug_scores)
    total_corrections = sum(s.get("accountability_debt", {}).get("template_corrections", 0)    for s in bug_scores)
    total_repeated    = sum(s.get("accountability_debt", {}).get("commitment_probe_repeated", 0) for s in bug_scores)
    debt_score = min((total_unanswered + total_corrections * 0.5 + total_repeated) / 10, 1.0)

    # ── RCA depth (1=none → 4=complete+accepted) ──────────────────────────────
    rca_depths = [s["rca_depth"] for s in bug_scores if s.get("rca_depth")]
    avg_rca_depth   = sum(rca_depths) / len(rca_depths) if rca_depths else 2.0
    rca_fail_score  = (4 - avg_rca_depth) / 3          # 0 (depth=4) to 1 (depth=1)
    n_rca_insufficient    = sum(1 for d in rca_depths if d <= 1)
    n_rca_proximate_only  = sum(1 for d in rca_depths if d == 2)

    # ── Integrity dimensions (good=0, partial=1, poor=2) ─────────────────────
    INTEG = {"good": 0, "partial": 1, "poor": 2}
    candor_s, acct_s, oblig_s = [], [], []
    for s in bug_scores:
        integ = s.get("integrity", {})
        if not isinstance(integ, dict):
            continue
        if integ.get("candor")                    in INTEG: candor_s.append(INTEG[integ["candor"]])
        if integ.get("accountability")             in INTEG: acct_s.append(INTEG[integ["accountability"]])
        if integ.get("obligation_understanding")   in INTEG: oblig_s.append(INTEG[integ["obligation_understanding"]])

    def avg_norm(lst): return (sum(lst) / len(lst) / 2) if lst else 0.0

    candor_fail = avg_norm(candor_s)
    acct_fail   = avg_norm(acct_s)
    oblig_fail  = avg_norm(oblig_s)
    integrity_fail = candor_fail * 0.30 + acct_fail * 0.35 + oblig_fail * 0.35

    n_poor_candor = sum(1 for x in candor_s if x == 2)
    n_poor_acct   = sum(1 for x in acct_s   if x == 2)
    n_poor_oblig  = sum(1 for x in oblig_s  if x == 2)

    # ── Commitment quality ────────────────────────────────────────────────────
    GRADE = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
    all_comms = [c for s in bug_scores for c in s.get("commitments", []) if isinstance(c, dict)]
    n_comms = len(all_comms)
    if n_comms > 0:
        grade_scores = [GRADE.get(c.get("grade", "C"), 2) for c in all_comms]
        commit_fail  = sum(grade_scores) / len(grade_scores) / 4
        n_grade_A    = sum(1 for g in grade_scores if g == 0)
        n_grade_DF   = sum(1 for g in grade_scores if g >= 3)
        n_restate    = sum(1 for c in all_comms if c.get("is_restatement"))
        n_arch       = sum(1 for c in all_comms if c.get("scope") == "architectural")
        n_cls        = sum(1 for c in all_comms if c.get("scope") == "class")
        restate_frac = n_restate / n_comms
    else:
        commit_fail = 0.5   # no commitments made — moderately concerning
        n_grade_A = n_grade_DF = n_restate = n_arch = n_cls = 0
        restate_frac = 0.0

    # ── Pattern connection response ───────────────────────────────────────────
    pc_map = {"acknowledged": 0, "deflected": 1, "ignored": 2}
    pc_scores = []
    for s in bug_scores:
        pc = s.get("pattern_connection", {})
        if isinstance(pc, dict) and pc.get("present") and pc.get("ca_response") in pc_map:
            pc_scores.append(pc_map[pc["ca_response"]])
    if pc_scores:
        pc_score       = sum(pc_scores) / len(pc_scores) / 2
        n_pc_raised    = len(pc_scores)
        n_pc_ignored   = sum(1 for x in pc_scores if x == 2)
        n_pc_deflected = sum(1 for x in pc_scores if x == 1)
    else:
        pc_score = n_pc_raised = n_pc_ignored = n_pc_deflected = 0

    # pc_ignored_rate: proportion of ALL bugs where community raised a pattern
    # connection and the CA ignored it. Captures "incompetence" on a per-CA basis
    # regardless of how many pattern connections were raised. A CA ignoring 33%
    # of its bugs' pattern connections is a different signal from one ignoring 10%.
    pc_ignored_rate = n_pc_ignored / max(n_bugs_total, 1)

    # ── Timeliness signals (deterministic from comment timestamps) ────────────
    timeliness = {}
    if comment_threads:
        from datetime import datetime as _dt
        td_list, lag_list, gap_list, ratio_list = [], [], [], []
        for s in bug_scores:
            bid      = str(s.get("bug_id", ""))
            comments = comment_threads.get(bid, [])
            if len(comments) < 2:
                continue
            times = []
            for c in comments:
                try:    times.append(_dt.strptime(c["time"][:10], "%Y-%m-%d"))
                except: times.append(None)
            roles = [classify_author(c["author"]) for c in comments]
            vt    = [(i,t) for i,t in enumerate(times) if t]
            if len(vt) < 2: continue
            td_list.append((vt[-1][1] - vt[0][1]).days)
            gaps = [(vt[i+1][1] - vt[i][1]).days for i in range(len(vt)-1)]
            if gaps: gap_list.append(max(gaps))
            ratio_list.append(sum(1 for r in roles if r == "ca") / len(comments))
            for i, (role, t) in enumerate(zip(roles, times)):
                if role == "root_program" and t:
                    for j in range(i+1, len(comments)):
                        if roles[j] == "ca" and times[j]:
                            lag_list.append((times[j] - t).days); break
        def sa(lst): return round(sum(lst)/len(lst)) if lst else None
        timeliness = {
            "avg_thread_days": sa(td_list),
            "max_silence_gap": max(gap_list) if gap_list else None,
            "avg_rp_lag_days": sa(lag_list),
            "avg_ca_ratio":    round(sum(ratio_list)/len(ratio_list), 2) if ratio_list else None,
        }

    # ── Longitudinal arc trend ────────────────────────────────────────────────
    years = sorted(set(s.get("filed_year", 2020) for s in bug_scores))
    arc_trend = "stable"
    if len(years) >= 4:
        mid = years[len(years)//2]
        early  = [s for s in bug_scores if s.get("filed_year", 2020) <  mid]
        recent = [s for s in bug_scores if s.get("filed_year", 2020) >= mid]
        if early and recent:
            ef = sum(ARC_FAILURE_WEIGHT.get(s["thread_health_arc"], 0) for s in early)  / (len(early)*2)
            rf = sum(ARC_FAILURE_WEIGHT.get(s["thread_health_arc"], 0) for s in recent) / (len(recent)*2)
            if   rf > ef + 0.2: arc_trend = "worsening"
            elif rf < ef - 0.2: arc_trend = "improving"

    cascade_score = min(sum(s.get("spawned_bugs", 0) for s in bug_scores) / 5, 1.0)

    # ── IRQ failure (0-30) ────────────────────────────────────────────────────
    # Arc failure:         0-8  (overall response pattern)
    # Integrity:           0-6  (candor + accountability + obligation understanding)
    # RCA depth:           0-4  (quality of root cause analysis)
    # Commitment quality:  0-4  (specificity, scope, restatement rate)
    # Pattern connection:  0-3  (response quality when told "this is a pattern")
    # PC ignored rate:     0-2  (proportion of ALL bugs where pattern was ignored)
    # Accountability debt: 0-2  (quantitative gaps)
    # Cascade:             0-1  (operational breadth)
    irq_failure = round(
        arc_failure_rate * 8
        + integrity_fail * 6
        + rca_fail_score * 4
        + commit_fail    * 4
        + pc_score       * 3
        + min(pc_ignored_rate / 0.3, 1.0) * 2   # saturates at 30% ignored rate
        + debt_score     * 2
        + cascade_score  * 1,
        1
    )

    escalating_frac = arc_counts.get("escalating", 0) / n
    if escalating_frac > 0.3:
        irq_failure = min(irq_failure * 1.2, 30)
        irq_failure = round(irq_failure, 1)
    if arc_trend == "worsening":
        irq_failure = min(irq_failure * 1.1, 30)
        irq_failure = round(irq_failure, 1)

    result = {
        "irq_failure":              irq_failure,
        "n_scored":                 n,
        "n_bugs_total":             n_bugs_total,
        # Arc
        "arc_distribution":             dict(arc_counts),
        "escalating_fraction":          round(escalating_frac, 2),
        "accountability_pressure_frac": round(arc_counts.get("accountability_pressure", 0) / n, 2),
        "stalled_fraction":             round(arc_counts.get("stalled", 0) / n, 2),
        "arc_trend":                    arc_trend,
        # Integrity
        "avg_rca_depth":            round(avg_rca_depth, 1),
        "n_rca_insufficient":       n_rca_insufficient,
        "n_rca_proximate_only":     n_rca_proximate_only,
        "candor_failure_rate":      round(sum(1 for x in candor_s if x >= 1) / len(candor_s), 2) if candor_s else 0,
        "acct_failure_rate":        round(sum(1 for x in acct_s   if x >= 1) / len(acct_s),   2) if acct_s   else 0,
        "oblig_failure_rate":       round(sum(1 for x in oblig_s  if x >= 1) / len(oblig_s),  2) if oblig_s  else 0,
        "n_poor_candor":            n_poor_candor,
        "n_poor_accountability":    n_poor_acct,
        "n_poor_obligation":        n_poor_oblig,
        # Commitments
        "n_commitments":            n_comms,
        "n_commitments_grade_A":    n_grade_A,
        "n_commitments_grade_DF":   n_grade_DF,
        "n_restatements":           n_restate,
        "restatement_fraction":     round(restate_frac, 2),
        "n_architectural_scope":    n_arch,
        "n_class_scope":            n_cls,
        # Patterns & debt
        "defensive_patterns":       dict(pattern_counts),
        "total_unanswered_rp":      total_unanswered,
        "total_template_fixes":     total_corrections,
        "total_repeated_asks":      total_repeated,
        "total_spawned_bugs":       sum(s.get("spawned_bugs", 0) for s in bug_scores),
        # Pattern connection
        "pattern_connections_raised":    n_pc_raised,
        "pattern_connections_ignored":   n_pc_ignored,
        "pattern_connections_deflected": n_pc_deflected,
        "pc_ignored_rate":               round(pc_ignored_rate, 3),
    }
    if timeliness:
        result["timeliness"] = timeliness
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    max_bugs = int(os.environ.get("IRQ_MAX_BUGS", "9999"))
    dry_run  = os.environ.get("IRQ_DRY_RUN", "").lower() in ("1", "true", "yes")

    print(f"[score_irq] {'DRY RUN — ' if dry_run else ''}Loading data...")

    bugs_active     = load_json(DATA_DIR / "bugs_by_ca.json")            or {}
    bugs_distrusted = load_json(DATA_DIR / "bugs_by_ca_distrusted.json") or {}

    # Load caches
    comment_cache: dict = {}
    if COMMENT_CACHE_PATH.exists():
        comment_cache = json.loads(COMMENT_CACHE_PATH.read_text())
        print(f"[score_irq] Loaded {len(comment_cache)} cached comment threads")

    score_cache: dict = {}
    if SCORE_CACHE_PATH.exists():
        score_cache = json.loads(SCORE_CACHE_PATH.read_text())
        print(f"[score_irq] Loaded {len(score_cache)} cached scores")

    all_cas: dict[str, tuple[str, list]] = {}
    for ca, bugs in bugs_active.items():
        if isinstance(bugs, list): all_cas[ca] = ("active", bugs)
    for ca, bugs in bugs_distrusted.items():
        if isinstance(bugs, list): all_cas[ca] = ("distrusted", bugs)

    # ── Phase 1: Fetch missing comments ──────────────────────────────────────
    fetched = 0
    for ca, (pop, bugs) in all_cas.items():
        for bug in bugs:
            bid = str(bug["id"])
            if bid in comment_cache or fetched >= max_bugs:
                continue
            if dry_run:
                comment_cache[bid] = []
                continue
            comment_cache[bid] = fetch_comments(int(bid))
            fetched += 1
            time.sleep(0.2)
        if fetched >= max_bugs:
            break

    if fetched > 0 and not dry_run:
        COMMENT_CACHE_PATH.write_text(json.dumps(comment_cache))
        print(f"[score_irq] Fetched {fetched} new comment threads")

    # ── Build CA posture profiles (Improvement 1) ──────────────────────────────
    api_key_env = os.environ.get("ANTHROPIC_API_KEY", "")
    ca_profiles: dict[str, str] = {}
    if api_key_env and not dry_run:
        # Load distrust events for posture labels
        distrust_data = load_json(DATA_DIR / "distrust_data.json") or {}
        distrust_events = {e["ca"]: e for e in distrust_data.get("events", [])}

        ca_profile_cache_path = CACHE_DIR / "irq_ca_profiles.json"
        if ca_profile_cache_path.exists():
            ca_profiles = json.loads(ca_profile_cache_path.read_text())
            print(f"[score_irq] Loaded {len(ca_profiles)} cached CA profiles")

        profiles_built = 0
        for ca, (pop, bugs) in all_cas.items():
            if ca in ca_profiles:
                continue
            # Find matching distrust event
            de = next((distrust_events[k] for k in distrust_events
                       if ca.lower() in k.lower() or k.lower() in ca.lower()), None)
            profile = build_ca_profile(ca, bugs, de, api_key_env)
            ca_profiles[ca] = profile or ""
            profiles_built += 1
            time.sleep(0.1)

        if profiles_built > 0:
            ca_profile_cache_path.write_text(json.dumps(ca_profiles))
            print(f"[score_irq] Built {profiles_built} new CA profiles")

    # ── Phase 2: Score missing bugs (parallel) ──────────────────────────────
    import threading as _threading

    WORKERS       = 8      # concurrent API calls — Haiku handles this fine
    CHECKPOINT_EVERY = 50  # persist cache every N completions

    # Build work queue: (ca, bug) pairs not yet scored
    work_queue = []
    for ca, (pop, bugs) in all_cas.items():
        for bug in bugs:
            bid = str(bug["id"])
            if bid in score_cache and score_cache[bid] is not None:
                continue
            comments = comment_cache.get(bid, [])
            if len(comments) < 2:
                score_cache[bid] = None
                continue
            if dry_run:
                score_cache[bid] = {
                    "thread_health_arc": "stalled", "arc_rationale": "dry run",
                    "defensive_patterns": [], "accountability_debt": {},
                    "pattern_connection": {"present": False},
                    "spawned_bugs": 0, "confidence": "low",
                    "filed_year": int(bug.get("filed", "2000")[:4]),
                }
                continue
            work_queue.append((ca, bug))
            if len(work_queue) >= max_bugs:
                break
        if len(work_queue) >= max_bugs:
            break

    scored_count = 0
    lock = _threading.Lock()

    def score_worker(item):
        nonlocal scored_count
        ca, bug = item
        bid = str(bug["id"])
        comments = comment_cache.get(bid, [])
        result = score_bug(bug, comments, ca_profiles.get(ca))
        with lock:
            score_cache[bid] = result
            scored_count += 1
            if scored_count % CHECKPOINT_EVERY == 0 and not dry_run:
                SCORE_CACHE_PATH.write_text(json.dumps(score_cache))
                print(f"[score_irq] Checkpoint: {scored_count} scored so far", flush=True)

    if work_queue and not dry_run:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = [executor.submit(score_worker, item) for item in work_queue]
            for _ in as_completed(futures):
                pass  # progress tracked inside score_worker

    if scored_count > 0 and not dry_run:
        SCORE_CACHE_PATH.write_text(json.dumps(score_cache))
        print(f"[score_irq] Scored {scored_count} new bugs")

    # ── Phase 3: Aggregate per CA ─────────────────────────────────────────────
    results = []
    for ca, (pop, bugs) in all_cas.items():
        bug_detail = []
        bug_scores_valid = []
        for bug in bugs:
            bid = str(bug["id"])
            s = score_cache.get(bid)
            if s:
                bug_scores_valid.append(s)
                bug_detail.append({
                    "bug_id":  bug["id"],
                    "filed":   bug.get("filed", ""),
                    "summary": bug.get("summary", "")[:80],
                    **s,
                })

        agg = aggregate_ca_irq(bug_scores_valid, len(bugs), comment_cache)
        results.append({
            "ca":         ca,
            "population": pop,
            "scores":     agg,
            "bugs":       bug_detail,
        })

    results.sort(key=lambda r: r["scores"].get("irq_failure") or 0, reverse=True)

    output = {
        "generated_at":  now_utc().isoformat(),
        "model":         HAIKU_MODEL,
        "framework":     "ForgeIQ thread health arc + defensive pattern + pattern connection response",
        "arc_types": {
            "healthy":    "Prompt acknowledgment, clear RCA, clean closure",
            "stalled":    "Incomplete report, repeated questions, slow/looping",
            "escalating": "Defensive response, pushback on requirements, pattern connections",
            "cascade":    "Single incident spawns multiple new bugs",
        },
        "pattern_connection_responses": {
            "acknowledged": "CA accepts systemic framing — lowest concern",
            "deflected":    "CA responds but avoids systemic framing — moderate concern",
            "ignored":      "CA does not address pattern connection — highest concern",
        },
        "irq_failure_scale": "0-30, higher = more concerning (for ALS integration)",
        "score_components": {
            "arc_failure_rate": "0-12 (overall response pattern)",
            "pattern_severity": "0-6 (deliberate evasion signals)",
            "accountability_debt": "0-4 (unanswered questions + template corrections)",
            "pattern_connection_response": "0-6 (how CA responds when told it has a pattern)",
            "cascade": "0-2 (spawned bug breadth)",
            "escalating_boost": "+20% if >30% of bugs are escalating arc",
            "worsening_trend_boost": "+10% if arc failure rate worsening over time",
        },
        "results": results,
    }

    save_json(DATA_DIR / "irq_scores.json", output)

    scored_cas = [r for r in results if r["scores"].get("n_scored", 0) > 0]
    print(f"[score_irq] Wrote irq_scores.json")
    print(f"[score_irq] {len(scored_cas)} CAs with scored bugs")
    if scored_cas:
        failures = [r["scores"]["irq_failure"] for r in scored_cas
                    if r["scores"]["irq_failure"] is not None]
        if failures:
            print(f"[score_irq] IRQ failure range: {min(failures):.1f} – {max(failures):.1f}")
    print(f"[score_irq] Bugs cached: {len(comment_cache)}, scored: {len(score_cache)}")


if __name__ == "__main__":
    main()
