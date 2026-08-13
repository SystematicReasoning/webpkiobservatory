"""
utils.py — Shared utilities for WebPKI Observatory pipeline scripts.

Centralises functions that were previously copy-pasted across multiple
scripts: JSON I/O, HTTP fetch with retry, logging helpers.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


# ── Date helpers ──────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Replaces datetime.utcnow() which is deprecated in Python 3.12+ and returns
    a naive datetime that silently loses timezone information.
    """
    return datetime.now(timezone.utc)


def parse_ccadb_date(s: str) -> datetime | None:
    """Parse a CCADB 'Valid To (GMT)' date string to a timezone-aware UTC datetime.

    CCADB consistently uses '%Y.%m.%d' (e.g. '2029.06.30').  Returns None if
    the string is absent or does not match that format — callers must decide
    what a missing date means for their logic (see note below).

    Conservative default for expiry checks: treat None as NOT expired so that
    a cert with an unparseable date is included rather than silently dropped.
    This is the existing behaviour; callers that want the opposite (exclude on
    unknown) should check for None explicitly.

    Note: all currently-included roots in CCADB use '%Y.%m.%d' consistently.
    If CCADB ever changes the format, the parse will return None and the caller's
    default will apply — no silent wrong answer.
    """
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y.%m.%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ── JSON I/O ──────────────────────────────────────────────────────────────────

def load_json(path, default=None):
    """Load JSON from path, returning default on missing file or parse error."""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        print(f"  WARNING: JSON decode error in {path}: {e}", file=sys.stderr)
        return default


def save_json(path, data, indent=2):
    """Write data as JSON to path, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent, default=str, ensure_ascii=False)


def load_json_dir(directory, filename, default=None):
    """Load JSON from directory/filename — matches old export script signature."""
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        print(f"  WARNING: {path} not found")
        return default
    return load_json(path, default)


# ── HTTP ──────────────────────────────────────────────────────────────────────

def fetch_json(url, retries=3, backoff=2.0, timeout=30, headers=None):
    """
    Fetch JSON from URL with retry and exponential backoff.
    Returns parsed dict/list or None on failure.
    """
    req_headers = {'Accept': 'application/json', 'User-Agent': 'WebPKI-Observatory/1.0'}
    if headers:
        req_headers.update(headers)

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = backoff * (2 ** attempt)
                print(f"  Rate limited — waiting {wait:.0f}s")
                time.sleep(wait)
            elif e.code in (404, 410):
                return None  # Not found — don't retry
            else:
                print(f"  HTTP {e.code} fetching {url} (attempt {attempt+1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(backoff)
        except Exception as e:  # noqa: BLE001
            print(f"  Error fetching {url}: {e} (attempt {attempt+1}/{retries})")
            if attempt < retries - 1:
                time.sleep(backoff)

    return None


# ── Misc ──────────────────────────────────────────────────────────────────────

def slugify(name):
    """Convert name to URL-safe slug."""
    import re
    return re.sub(r'(^-|-$)', '', re.sub(r'[^a-z0-9]+', '-', (name or '').lower()))


# ── Anthropic API ─────────────────────────────────────────────────────────────

ANTHROPIC_URL     = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL   = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"


def _strip_llm_fences(text: str) -> str:
    """Remove markdown code fences from LLM response text."""
    import re as _re
    s = text.strip()
    if s.startswith("```"):
        s = _re.sub(r"^```[a-z]*\n?", "", s)
        s = _re.sub(r"\n?```$", "", s)
    return s.strip()


def call_llm(prompt: str, api_key: str, *,
             max_tokens: int = 1000,
             timeout: int = 60,
             model: str = None) -> object:
    """
    Call the Anthropic messages API and return parsed JSON.

    Centralises request construction, response extraction, and markdown fence
    stripping. Raises urllib.error.HTTPError, urllib.error.URLError, or
    json.JSONDecodeError so callers keep their own error handling context.

    Parameters
    ----------
    prompt      : full prompt string (system + user combined)
    api_key     : Anthropic API key
    max_tokens  : response token budget (default 1000)
    timeout     : HTTP timeout in seconds (default 60)
    model       : model name; defaults to ANTHROPIC_MODEL (haiku)
    """
    import json as _json
    body = _json.dumps({
        "model": model or ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = _json.loads(resp.read())

    # Join all text blocks — handles multi-block responses correctly
    raw = "".join(
        block["text"] for block in result.get("content", [])
        if block.get("type") == "text"
    )
    return _json.loads(_strip_llm_fences(raw))
