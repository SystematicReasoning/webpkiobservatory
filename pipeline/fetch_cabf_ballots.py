"""
fetch_cabf_ballots.py — Fetch CA/B Forum ballot data from cabforum.org.

Writes pipeline/cabforum_ballots.json — tracked in git, not in ops cache.
Run manually when ballot data is stale (a few times per year is sufficient).

Usage: python pipeline/fetch_cabf_ballots.py
"""

import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

PIPELINE_DIR = Path(__file__).parent
OUTPUT_PATH = PIPELINE_DIR / "cabforum_ballots.json"

# CA/B Forum working group ballot archive pages
WG_URLS = {
    "SC":  "https://cabforum.org/working-groups/server/ballots/",
    "CSC": "https://cabforum.org/working-groups/code-signing/ballots/",
    "SMC": "https://cabforum.org/working-groups/smime/ballots/",
    "NS":  "https://cabforum.org/working-groups/netsec/ballots/",
}

HEADERS = {"User-Agent": "WebPKI-Observatory/1.0 (https://webpki.systematicreasoning.com)"}


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_ballot_page(html: str, wg: str) -> list:
    """Extract ballot entries from a CA/B Forum WG ballot archive page."""
    ballots = []

    # Each ballot is a post entry — find all links to ballot pages
    # Pattern: href="/20XX/MM/DD/ballot-XXXX-..."
    ballot_links = re.findall(
        r'href="(https://cabforum\.org/\d{4}/\d{2}/\d{2}/ballot-[^"]+)"[^>]*>([^<]+)<',
        html
    )

    seen = set()
    for url, title in ballot_links:
        url = url.rstrip("/")
        if url in seen:
            continue
        seen.add(url)

        # Extract ballot ID from URL
        m = re.search(r'ballot-([\w-]+)/', url)
        ballot_id = m.group(1).upper() if m else ""

        # Extract proposer/endorsers from the ballot page if available in listing
        # For now capture what's in the listing
        title = title.strip()
        if not title or title.lower() in ("read more", "continue reading", ""):
            continue

        ballots.append({
            "id": ballot_id,
            "title": title,
            "url": url,
            "proposer": "",       # populated below if we fetch detail pages
            "endorsers_raw": [],
            "issuer_yes": 0,
            "issuer_no": 0,
            "issuer_abstain": 0,
            "consumer_yes": 0,
            "consumer_no": 0,
        })

    return ballots


def enrich_from_detail(ballot: dict) -> dict:
    """Fetch ballot detail page and extract proposer/endorsers."""
    try:
        html = fetch_html(ballot["url"])

        # Proposer: "Proposed by X" or "This ballot is proposed by X"
        m = re.search(
            r'[Pp]roposed\s+by\s+([A-Z][^,\.<\n]{2,60}?)(?:\s*,|\s*\.|<|\n|and\s+endorsed)',
            html
        )
        if m:
            ballot["proposer"] = m.group(1).strip()

        # Endorsers: "endorsed by X and Y" or "Endorsed by: X, Y"
        m = re.search(
            r'[Ee]ndorsed\s+by[:\s]+([^<\n]{5,200}?)(?:<|\n|\.)',
            html
        )
        if m:
            raw = m.group(1).strip()
            # Split on commas/and
            endorsers = [e.strip() for e in re.split(r',|\band\b', raw) if e.strip()]
            ballot["endorsers_raw"] = endorsers[:10]  # cap at 10

        # Vote counts: "X Issuing CAs voted YES" etc
        for pattern, field in [
            (r'(\d+)\s+[Ii]ssu(?:ing|er)\s+CA[s]?\s+voted?\s+[Yy][Ee][Ss]', "issuer_yes"),
            (r'(\d+)\s+[Ii]ssu(?:ing|er)\s+CA[s]?\s+voted?\s+[Nn][Oo]', "issuer_no"),
            (r'(\d+)\s+[Ii]ssu(?:ing|er)\s+CA[s]?\s+[Aa]bstain', "issuer_abstain"),
            (r'(\d+)\s+[Cc]onsumer[s]?\s+voted?\s+[Yy][Ee][Ss]', "consumer_yes"),
            (r'(\d+)\s+[Cc]onsumer[s]?\s+voted?\s+[Nn][Oo]', "consumer_no"),
        ]:
            m = re.search(pattern, html)
            if m:
                ballot[field] = int(m.group(1))

    except Exception as e:
        print(f"    Warning: could not enrich {ballot['url']}: {e}")

    return ballot


def main():
    print(f"fetch_cabf_ballots.py — {datetime.now(timezone.utc).isoformat()[:19]}")

    existing = {}
    if OUTPUT_PATH.exists():
        try:
            existing = json.loads(OUTPUT_PATH.read_text())
            total = sum(len(v) for v in existing.values())
            print(f"  Existing: {total} ballots across {len(existing)} WGs")
        except Exception as e:
            print(f"  WARNING: could not load existing ballot cache: {e}", file=__import__("sys").stderr)

    result = {}

    for wg, url in WG_URLS.items():
        print(f"  Fetching {wg} ballots from {url}...")
        try:
            html = fetch_html(url)
            ballots = parse_ballot_page(html, wg)
            print(f"    Found {len(ballots)} ballot links")

            # Only enrich new ballots not already in existing cache
            existing_urls = {b["url"] for b in existing.get(wg, [])}
            new_ballots = [b for b in ballots if b["url"] not in existing_urls]
            cached_ballots = [b for b in existing.get(wg, []) if b["url"] in {b2["url"] for b2 in ballots}]

            print(f"    Enriching {len(new_ballots)} new ballots...")
            enriched = []
            for i, ballot in enumerate(new_ballots):
                enriched.append(enrich_from_detail(ballot))
                if (i + 1) % 10 == 0:
                    print(f"      {i+1}/{len(new_ballots)} enriched")

            result[wg] = cached_ballots + enriched
            print(f"    {wg}: {len(result[wg])} total ballots")

        except Exception as e:
            print(f"    Error fetching {wg}: {e}")
            result[wg] = existing.get(wg, [])

    total = sum(len(v) for v in result.values())
    print(f"\n  Total: {total} ballots")
    OUTPUT_PATH.write_text(json.dumps(result, indent=2))
    print(f"  Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
