#!/usr/bin/env python3
"""
Parse revision/document history tables from CABF documents.
Produces a dated ballot timeline for all five CABF documents.

This gives us two resolution levels:
  - Fine: actual obligation counts (from git tags + PDFs, where available)
  - Coarse: ballot dates + descriptions (from revision tables, complete history)

The coarse data fills the 2021-2024 gap and covers the pre-GitHub era.
Output: data/revision_history.json
"""

import re
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUTPUT = Path(__file__).parent.parent / "data" / "revision_history.json"

DOCS = {
    "tls_br":   ("CA/B Forum TLS BR",        "https://raw.githubusercontent.com/cabforum/servercert/main/docs/BR.md"),
    "ev_g":     ("CA/B Forum EV Guidelines",  "https://raw.githubusercontent.com/cabforum/servercert/main/docs/EVG.md"),
    "ns_reqs":  ("CA/B Forum NS Reqs",        "https://raw.githubusercontent.com/cabforum/servercert/main/docs/NSR.md"),
    "smime_br": ("CA/B Forum S/MIME BR",      "https://raw.githubusercontent.com/cabforum/smime/main/SBR.md"),
    "cs_br":    ("CA/B Forum CS BR",          "https://raw.githubusercontent.com/cabforum/code-signing/main/docs/CSBR.md"),
}

# Month name → number
MONTHS = {
    'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
    'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12,
    'january':1,'february':2,'march':3,'april':4,'june':6,
    'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
}

def parse_date(raw: str) -> str | None:
    """Parse messy CABF date strings → ISO YYYY-MM-DD."""
    s = raw.strip().replace('\u2011', '-').replace('\u2010', '-').strip('*').strip()
    if not s or s in ('—', '-', 'TBD', 'n/a'):
        return None

    # YYYY-MM-DD already
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s

    # DD-Mon-YY or DD-Mon-YYYY  e.g. "3-Aug-12", "31‐Aug‐17"
    m = re.match(r'^(\d{1,2})[-–]([A-Za-z]+)[-–](\d{2,4})$', s)
    if m:
        d, mon, y = m.groups()
        month = MONTHS.get(mon.lower()[:3])
        if month:
            year = int(y) + (2000 if len(y) == 2 and int(y) < 50 else
                             1900 if len(y) == 2 else 0)
            return f"{year:04d}-{month:02d}-{int(d):02d}"

    # DD Mon YYYY  e.g. "29 May 2012"
    m = re.match(r'^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$', s)
    if m:
        d, mon, y = m.groups()
        month = MONTHS.get(mon.lower()[:3])
        if month:
            return f"{int(y):04d}-{month:02d}-{int(d):02d}"

    # Mon DD, YYYY  e.g. "Aug 3, 2012"
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$', s)
    if m:
        mon, d, y = m.groups()
        month = MONTHS.get(mon.lower()[:3])
        if month:
            return f"{int(y):04d}-{month:02d}-{int(d):02d}"

    # DD/MM/YYYY or MM/DD/YYYY — ambiguous, skip
    return None


def parse_table_rows(text: str) -> list[list[str]]:
    """Extract markdown table rows as lists of cell strings."""
    rows = []
    for line in text.split('\n'):
        line = line.strip()
        if not line.startswith('|') or re.match(r'^\|[-:\s|]+\|$', line):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        rows.append(cells)
    return rows


def find_history_table(text: str) -> list[list[str]]:
    """Find the document revision history table in any CABF markdown document."""
    # Strategy 1: find section heading then first substantial table
    heading_patterns = [
        r'#{1,4}\s+(?:\d+\.\d+\s+)?(?:Document History|Revisions?|Version History|Change History)',
    ]
    for pat in heading_patterns:
        m = re.search(pat, text, re.I)
        if m:
            chunk = text[m.start():m.start() + 30000]
            rows = parse_table_rows(chunk)
            # Must have date-like content and enough rows
            dated = [r for r in rows if any(
                re.search(r'\d{4}|\d{1,2}[-/]\d{1,2}', c) for c in r
            )]
            if len(dated) > 2:
                return rows

    # Strategy 2: find table with ballot column directly
    # Look for table header with Version + Ballot + Date columns
    m = re.search(
        r'(\|[^\n]*(?:Ver\.|Version)[^\n]*\|[^\n]*(?:Ballot|Pub)[^\n]*\|[^\n]*\n(?:\|.*\n)+)',
        text, re.I
    )
    if m:
        rows = parse_table_rows(m.group(1))
        if len(rows) > 2:
            return rows

    return []


def detect_columns(header_row: list[str]) -> dict:
    """Map column names to indices."""
    cols = {}
    for i, cell in enumerate(header_row):
        c = cell.lower().replace('*', '').replace('\\', '').strip()
        if re.search(r'ver|version', c):
            cols.setdefault('version', i)
        elif re.search(r'ballot', c):
            cols.setdefault('ballot', i)
        elif re.search(r'desc', c):
            cols.setdefault('desc', i)
        elif re.search(r'adopt', c):
            cols.setdefault('adopted', i)
        elif re.search(r'effect', c):
            cols.setdefault('effective', i)
        elif re.search(r'pub', c):
            cols.setdefault('adopted', i)
        elif re.search(r'date', c):
            cols.setdefault('adopted', i)
    return cols


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', errors='ignore')


def parse_doc(doc_key: str, label: str, url: str) -> list[dict]:
    print(f"  {label}...")
    text = fetch(url)
    rows = find_history_table(text)
    if not rows:
        print(f"    WARNING: no history table found")
        return []

    # First non-separator row is header
    header = rows[0]
    cols = detect_columns(header)
    print(f"    {len(rows)-1} rows, columns: {cols}")

    entries = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        # Skip rows that look like sub-headers or footnotes
        if row[0].startswith('*') or row[0].startswith('\\'):
            continue

        version = row[cols['version']].strip('*').strip() if 'version' in cols and cols['version'] < len(row) else ''
        ballot  = row[cols['ballot']].strip('*').strip()  if 'ballot'  in cols and cols['ballot']  < len(row) else ''
        desc    = row[cols['desc']].strip()               if 'desc'    in cols and cols['desc']    < len(row) else ''

        # Date: prefer effective, fall back to adopted
        raw_date = ''
        if 'effective' in cols and cols['effective'] < len(row):
            raw_date = row[cols['effective']].strip('*\\').strip()
        if (not raw_date or raw_date in ('—', '-', 'TBD')) and 'adopted' in cols and cols['adopted'] < len(row):
            raw_date = row[cols['adopted']].strip('*\\').strip()

        date = parse_date(raw_date)
        if not date or not version:
            continue

        entries.append({
            'doc': doc_key,
            'version': version,
            'ballot': ballot,
            'desc': desc,
            'date': date,
            'source': 'revision_table',
        })

    entries.sort(key=lambda x: x['date'])
    if entries:
        print(f"    {len(entries)} dated entries, {entries[0]['date']} → {entries[-1]['date']}")
    else:
        print(f"    0 dated entries parsed")
    return entries


def main():
    print("Parsing CABF revision history tables...")
    all_entries = {}
    for doc_key, (label, url) in DOCS.items():
        entries = parse_doc(doc_key, label, url)
        all_entries[doc_key] = entries

    # Summary stats
    print("\nSummary:")
    for doc_key, entries in all_entries.items():
        if entries:
            years = sorted({e['date'][:4] for e in entries})
            print(f"  {doc_key}: {len(entries)} ballots, {years[0]}–{years[-1]}")

    output = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'note': 'Ballot dates from document revision tables. Coarse resolution — '
                'one entry per ballot, no obligation count. Use alongside '
                'version_history (from git tags) for fine-grained counts.',
        'by_doc': all_entries,
    }

    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nWrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == '__main__':
    main()
