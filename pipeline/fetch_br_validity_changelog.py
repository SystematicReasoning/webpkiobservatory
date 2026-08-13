#!/usr/bin/env python3
"""
BR Validity Changelog — tracks CA certificate usage period history.

Maintains a persistent record of when CAs entered/exited BR validity
violation status. This prevents fixes from wiping the historical record:
a CA that violated the 200-day limit and then fixed it still shows the
violation event with its resolution date.

Output: data/br_validity_changelog.json
Schema:
  {
    "generated_at": "ISO timestamp",
    "thresholds": { "current": 200, "2027": 100, "2029": 47 },
    "cas": {
      "<ca_owner>": {
        "current_use_days": 45,
        "current_status": "compliant",
        "first_seen": "2026-03-16",
        "last_updated": "2026-03-16",
        "history": [
          {
            "date": "2026-03-01",
            "use_days": 270,
            "status": "violation",
            "unexpired_certs": 280000
          },
          ...
        ],
        "violations": [
          {
            "threshold": 200,
            "first_observed": "2026-01-15",
            "resolved": "2026-04-01",   // null if still active
            "peak_use_days": 309,
            "peak_date": "2026-02-01"
          }
        ]
      }
    }
  }
"""

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
OUTPUT_DIR = PIPELINE_DIR.parent / "data"
CHANGELOG_PATH = OUTPUT_DIR / "br_validity_changelog.json"

# Minimum unexpired certs to consider a CA "actively issuing TLS"
# Below this threshold UseDays reflects legacy non-TLS cert populations
ACTIVE_TLS_MIN_CERTS = 1000

# A CA is considered "resolved" when it has been below the threshold
# for this many consecutive days (avoids flip-flopping on noise)
RESOLUTION_GRACE_DAYS = 30

THRESHOLDS = [
    {"days": 200, "deadline": "Mar 2026", "label": "current"},
    {"days": 100, "deadline": "Mar 2027", "label": "2027"},
    {"days": 47,  "deadline": "Mar 2029", "label": "2029"},
]


def compute_status(use_days: int) -> str:
    if use_days > 200: return "subscriber_risk"
    if use_days > 100: return "risk_2027"
    if use_days > 47:  return "risk_2029"
    return "compliant"


def load_changelog() -> dict:
    if CHANGELOG_PATH.exists():
        try:
            return json.loads(CHANGELOG_PATH.read_text())
        except Exception as e:
            print(f"  WARNING: could not load existing changelog: {e}")
    return {"cas": {}}


def update_changelog(market_data: list, today: str) -> dict:
    changelog = load_changelog()
    cas = changelog.setdefault("cas", {})

    updated = 0
    new_violations = 0
    resolved = 0

    for ca in market_data:
        name = ca["ca_owner"]
        all_time = ca.get("all_precerts") or ca.get("all_certs") or 0
        unexpired = ca.get("unexpired_certs") or 0
        tls = ca.get("tls_capable", False)
        trusted = any(ca.get("trusted_by", {}).values())
        br_status = ca.get("br_status")

        # Only track active TLS issuers — skip not_applicable
        if br_status == "not_applicable" or not tls or unexpired < ACTIVE_TLS_MIN_CERTS or not trusted:
            continue

        # Compute use_days if not already provided by fetch_and_join.py
        use_days = ca.get("use_days")
        if not use_days:
            if all_time > 0 and unexpired > 0:
                use_days = round(365 / (all_time / unexpired))
            else:
                continue

        status = compute_status(use_days)

        if name not in cas:
            cas[name] = {
                "first_seen": today,
                "last_updated": today,
                "current_use_days": use_days,
                "current_status": status,
                "history": [],
                "violations": [],
            }

        entry = cas[name]

        # Append to history if changed or first entry
        last = entry["history"][-1] if entry["history"] else None
        if not last or last["use_days"] != use_days or last["status"] != status:
            entry["history"].append({
                "date": today,
                "use_days": use_days,
                "status": status,
                "unexpired_certs": unexpired,
            })
            updated += 1

        # Track violation events per threshold
        for t in THRESHOLDS:
            threshold = t["days"]
            is_violating = use_days > threshold

            # Find open violation for this threshold
            open_v = next(
                (v for v in entry["violations"]
                 if v["threshold"] == threshold and v["resolved"] is None),
                None
            )

            if is_violating and not open_v:
                # New violation
                entry["violations"].append({
                    "threshold": threshold,
                    "deadline": t["deadline"],
                    "first_observed": today,
                    "resolved": None,
                    "peak_use_days": use_days,
                    "peak_date": today,
                })
                new_violations += 1

            elif is_violating and open_v:
                # Update peak
                if use_days > open_v["peak_use_days"]:
                    open_v["peak_use_days"] = use_days
                    open_v["peak_date"] = today

            elif not is_violating and open_v:
                # Potentially resolved — check grace period
                from datetime import datetime as dt
                first_ok = next(
                    (h["date"] for h in reversed(entry["history"])
                     if h["use_days"] <= threshold),
                    today
                )
                try:
                    days_ok = (dt.fromisoformat(today) - dt.fromisoformat(first_ok)).days
                except Exception:
                    days_ok = 0

                if days_ok >= RESOLUTION_GRACE_DAYS:
                    open_v["resolved"] = today
                    resolved += 1

        entry["current_use_days"] = use_days
        entry["current_status"] = status
        entry["last_updated"] = today

    print(f"  Updated {updated} CA entries, {new_violations} new violations, {resolved} resolved")

    # Build summary
    active_violations = {
        t["days"]: [
            name for name, e in cas.items()
            if any(v["threshold"] == t["days"] and v["resolved"] is None
                   for v in e.get("violations", []))
        ]
        for t in THRESHOLDS
    }

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": {t["label"]: t["days"] for t in THRESHOLDS},
        "summary": {
            "active_violations_200d": len(active_violations[200]),
            "active_violations_100d": len(active_violations[100]),
            "active_violations_47d":  len(active_violations[47]),
            "cas_with_current_violation": active_violations[200],
            "cas_approaching_2027":       active_violations[100],
        },
        "cas": dict(sorted(cas.items())),
    }

    CHANGELOG_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"  Wrote {CHANGELOG_PATH}")
    return result


def main():
    print("=" * 60)
    print("BR Validity Changelog")
    print("=" * 60)

    market_path = OUTPUT_DIR / "market_share.json"
    if not market_path.exists():
        print("ERROR: market_share.json not found. Run fetch_and_join.py first.")
        sys.exit(1)

    market_data = json.loads(market_path.read_text())
    today = date.today().isoformat()
    print(f"  Processing {len(market_data)} CAs for {today}")

    result = update_changelog(market_data, today)

    print(f"\n  Summary:")
    s = result["summary"]
    print(f"    Active 200d violations: {s['active_violations_200d']} — {s['cas_with_current_violation']}")
    print(f"    Active 100d violations: {s['active_violations_100d']}")
    print(f"    Active 47d violations:  {s['active_violations_47d']}")


if __name__ == "__main__":
    main()
