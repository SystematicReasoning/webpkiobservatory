#!/usr/bin/env python3
"""Verify ui_bundle.json contains expected keys including AUDITS_DATA."""
import json, sys, os

data_dir = os.environ.get("PIPELINE_DATA_DIR", "data")
bundle_path = os.path.join(data_dir, "ui_bundle.json")

try:
    with open(bundle_path, encoding="utf-8") as f:
        d = json.load(f)
except Exception as e:
    print(f"ERROR: could not read {bundle_path}: {e}", file=sys.stderr)
    sys.exit(1)

if "AUDITS_DATA" not in d:
    print("ERROR: AUDITS_DATA missing from bundle!", file=sys.stderr)
    sys.exit(1)

ad = d["AUDITS_DATA"]
parsed = ad.get("summary", {}).get("pdf_parsed_count", 0)
profiles = ad.get("profiles", [])
profiles_count = len(profiles)

# Check that bug_retrospective data is present for CAs that have incidents.
# A bundle built from a stale audits.json (before fetch_audits.py ran) will
# have all profiles with bug_retrospective=null, breaking the CA-by-CA audit
# retrospective section entirely.
with_retro = sum(1 for p in profiles if p.get("bug_retrospective"))
if profiles_count > 0 and with_retro == 0:
    print(
        f"WARNING: AUDITS_DATA has {profiles_count} profiles but none have "
        f"bug_retrospective data. The bundle may be stale — was fetch_audits.py "
        f"run before export_ui_bundle.py?",
        file=sys.stderr,
    )
    # Don't fail the build — audits pipeline uses continue-on-error and a
    # missing retrospective is recoverable. But make it visible.

print(f"Bundle OK: {profiles_count} profiles, {parsed} parsed letters in AUDITS_DATA")
print(f"  bug_retrospective populated: {with_retro}/{profiles_count} profiles")
print(f"Bundle keys: {list(d.keys())}")
