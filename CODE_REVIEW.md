# Pipeline Code Review

This document covers the four review dimensions for every pipeline script:

1. **Maintainability** — clarity, duplication, dead code
2. **Shell-out elimination** — replace `subprocess`/`openssl` with Python libs
3. **Suppressions and fallbacks** — every `pass`, silent `except`, hardcoded fallback, and `return []` on error
4. **Methodology issues** — places where the computation may produce misleading results

Severity legend: 🔴 Fix now (produces wrong or hidden output) | 🟡 Fix soon (fragile, misleading) | 🟢 Low risk (cosmetic, minor)

---

## fetch_root_algo.py

**Shell-outs:** None. Uses `cryptography` library throughout. ✅

**Suppressions/fallbacks:**

| Line | Code | Risk | Assessment |
|------|------|------|------------|
| 90 | `WARNING: CCADB PEM fetch returned {status_code}` + `continue` | 🟡 | Correct to continue — a missing decade's PEMs means some roots won't parse, logged clearly. Acceptable. |
| 103 | `WARNING: Failed to fetch PEMs: {e}` + `continue` | 🟡 | Same as above. |
| 120–126 | `except ValueError/Exception: return {"error": ...}` | 🟡 | Parse failure returns an error dict, which is then **silently skipped** in `build_output` (line ~305: `if "error" in algo: continue`). This suppresses roots from the output without a count. Should tally and log how many roots were excluded. |
| 365–367 | Missed roots → `cache[sha256] = {"error": "not_in_ccadb"}` | 🟡 | Logged by count. Error entries suppressed silently in `build_output`. Same fix needed. |

**Methodology issues:**

- `sig_oid._name` (line ~175): `_name` is a private attribute on `ObjectIdentifier`. Should use `sig_oid.dotted_string` or a lookup table. Will silently return `"unknown"` if the attribute disappears in a future `cryptography` release.
- The `stores` field (line ~255) uses a positional string `"MCSA"` — no separator, positional encoding. This is fragile; a dict `{"mozilla": bool, ...}` would be clearer and wouldn't break if store order changes.
- `rfc5280_compliant_serial` is computed but never surfaces in the UI or output aggregates. Either use it or remove it.

**Maintainability:**

- `fetch_bulk_pems()` fetches by decade (`1990`, `2000`, `2010`, `2020`). When 2030 arrives this silently misses new roots. Should derive decade range from `datetime.now().year`.
- Date format `%Y.%m.%d` hardcoded in `not_before`/`not_after` output — consistent with other scripts but worth a shared constant.

---

## fetch_browser_share.py

**Shell-outs:** None. ✅

**Suppressions/fallbacks:**

| Line | Code | Risk | Assessment |
|------|------|------|------------|
| 48 | `fetch_from_html()` as primary (comment says CSV is unreliable) | 🟡 | Misleading comment — the function is the primary path, not a fallback. Rename to `fetch_statcounter()`. |
| 54–56 | `except URLError: return None` | 🟢 | Handled correctly — triggers the hardcoded fallback below. |
| 79–80 | `except ValueError: continue` inside regex parse | 🟢 | Correct for float conversion. |
| 137–145 | **Hardcoded fallback browser shares** | 🔴 | If StatCounter is unreachable, the pipeline silently uses 2-year-old hardcoded numbers. The web coverage percentages displayed in the dashboard become wrong without any indication. **Fix:** fail the script with a non-zero exit code so CI fails visibly. Browser share changes slowly; a stale value is worse than a build failure that forces investigation. |
| `datetime.utcnow()` | Line 32 | 🟡 | `utcnow()` is deprecated in Python 3.12+. Use `datetime.now(timezone.utc)`. |

**Methodology issues:**

- `fetch_from_html()` uses a regex to parse StatCounter's HTML table. StatCounter has changed their markup before; this will silently return `None` (triggering the hardcoded fallback) rather than raise a visible error.
- Desktop-only (`device=Desktop`) is hardcoded in the CSV URL (unused code path) but the HTML scrape fetches all-platform data. These measure different things. The methodology doc says "all platforms worldwide" — verify this is what the HTML endpoint actually returns.
- `UC Browser` and `Yandex Browser` mapped to `chrome` (Chromium-based) is correct for root store purposes but worth a comment since these browsers have their own privacy/trust stories.

---

## fetch_and_join.py

**Shell-outs:** None. ✅

**Suppressions/fallbacks:**

| Line | Code | Risk | Assessment |
|------|------|------|------------|
| 83–89 | `fetch_with_retry` returns `None` after all retries | 🔴 | Callers (`fetch_ccadb`, `fetch_crtsh`) check for `None` and... print a warning then continue with empty data. If CCADB fetch fails, the entire pipeline run produces empty/stale output silently. **Fix:** raise an exception that fails the CI job. |
| 378–383 | `except (ValueError, IndexError): pass` on root expiry date parse | 🔴 | If `valid_to` is in an unexpected format, `expired` stays `False`, and the root is **included as non-expired**. This means a cert with an unparseable validity date is treated as still valid. Should log the unparseable value and default to `expired=True` (conservative). |
| 398–402 | Same pattern for intermediate expiry | 🔴 | Same consequence: unparseable expiry = intermediate treated as non-expired and included. |
| 646–650 | Same pattern in a third location | 🔴 | Third copy of the same bug. All three should share a `parse_valid_to(s)` helper that logs and returns `None` on failure, with callers defaulting to the conservative side. |
| 1198 | `load_previous_market_data()` — crt.sh fallback | 🟡 | If crt.sh fails, the script falls back to yesterday's data. This is documented in the function name but the caller should log clearly that stale data is being used for which CAs. Currently this is silent. |

**Methodology issues:**

- The same date-parse pattern (`vt.split(".")`) appears in three separate places (lines 378, 398, 646). This is a DRY violation and a bug surface — the three copies have subtly different behavior (one checks `expired=False` default, one uses `continue`, one sets `expired=True`). Extract a single `parse_ccadb_date(s) -> Optional[date]` and use it everywhere.
- The `usage_period` (avgDays) calculation uses `unexpired_precerts` in both numerator and denominator via turnover. If `unexpired_precerts = 0` (as with PKIoverheid), `turnover = 0` and `usage_days = 0`. The downstream `brStatus` check then assigns `not_applicable`. This is correct behavior but the zero-division guard (`if unexpired > 0 and all_precerts > 0`) is correct; add a comment explaining why zero → `not_applicable`.

---

## fetch_incidents.py

**Shell-outs:** None. ✅

**Suppressions/fallbacks:**

| Line | Code | Risk | Assessment |
|------|------|------|------------|
| 104 | `is_self_reported_email()` docstring calls this a "fallback" | 🟡 | This is actually the **primary** attribution method — LLM classification is only used when available. The function name and docstring imply it's secondary. Rename to `classify_self_report_by_domain()` and update the docstring. |
| Various | `except` on Bugzilla API batch fetch | 🟡 | HTTP errors logged by batch number. Individual bug parse errors silently `continue`. Should count skipped bugs and include in output metadata. |

**Methodology issues:**

- Self-report attribution uses email domain matching (`creator.split("@")[-1]`). This is the right approach but the `CA_EMAILS` set is defined inline in the script. When a CA changes domain (e.g., acquisition) or a bug is filed by a contractor, attribution will be wrong silently. This set should live in a curated config file alongside `gov_classifications.json` so it can be updated without touching script logic.
- Discovery channel classification uses keyword matching on the first comment only. 29% "unknown" rate is documented but the keyword list is not versioned or tested. Should live in `config.py` or a dedicated JSON so additions don't require reading the script.
- `classified_total > 0` guard (line ~443) means classification fields (`categories`, `yearsByClass`, `fingerprints`) are empty arrays until the LLM cache exists. This produces a valid-looking but incomplete JSON that the UI silently handles via `DataPending`. The metadata should include `classification_available: bool` so the UI can be explicit.

---

## fetch_crl_health.py

**Shell-outs:** 🔴

| Line | Code | Risk |
|------|------|------|
| 43 | `import subprocess` | — |
| 145–148 | `subprocess.run(["openssl", "x509", "-noout", ...]` | 🔴 |

**The openssl shell-out parses the TLS endpoint's leaf certificate to extract subject DN, serial number, and expiry.** All three are available directly from the DER bytes already in `leaf_der` via the `cryptography` library:

```python
# Current (shell-out):
proc = subprocess.run(
    ["openssl", "x509", "-noout", "-subject", "-serial", "-enddate", "-inform", "DER"],
    input=leaf_der, capture_output=True, timeout=5,
)

# Correct (pure Python):
from cryptography import x509 as _x509
from cryptography.hazmat.primitives.serialization import Encoding

cert = _x509.load_der_x509_certificate(leaf_der)
subject_cn = cert.subject.get_attributes_for_oid(
    _x509.oid.NameOID.COMMON_NAME)[0].value if cert.subject else ""
serial_hex = format(cert.serial_number, "X")
cert_expired = cert.not_valid_after_utc < datetime.now(timezone.utc)
```

This is a deterministic behavior change — `openssl` subject formatting differs from `cryptography`'s DN representation (e.g., ordering, attribute name capitalization). The `cert_subject` field in `crl_health.json` will change. Before making this change: **pull current `crl_health.json` as a test vector**, confirm the values are only used for display (not for matching/keying), then replace.

**Suppressions/fallbacks:**

| Line | Code | Risk | Assessment |
|------|------|------|------------|
| 162 | `except` on hostname check → `pass` | 🟡 | SSL hostname check failure is silently swallowed. The `hostname_mismatch` flag should be set to `True` on any exception from the hostname-check block, not just the explicit mismatch case. |
| 180 | `except` on `ctx_hn.wrap_socket` → `pass` | 🟡 | Same: exceptions other than `ssl.SSLCertVerificationError` (e.g., connection reset) silently leave `hostname_mismatch` unset. |
| 339 | `except Exception: pass` on CRL parse | 🔴 | If `cryptography` raises on a malformed CRL, the parse result is silently empty — no `parse_error` flag, no count of affected CRLs. The CRL health check for that URL will show as "no data" rather than "parse failed". Should set `parse_error: "malformed_crl"`. |
| 700 | `except Exception: return {}` in batch fetch | 🟡 | Returns empty dict on network failure; caller treats this as "no CRL data". Should return `{"fetch_error": str(e)}` so the distinction between "not checked" and "failed" is preserved in the output. |

**Methodology issues:**

- The `openssl` subject format and `cryptography`'s DN representation differ for multi-valued RDNs. If `cert_subject` is ever used for matching or display comparison, this inconsistency matters. Currently it's display-only, so it's cosmetic, but it should be fixed before it becomes load-bearing.
- BR §4.9.7 compliance assessment (validity window check) is only applied to CAs in Apple/Chrome/Mozilla stores — Microsoft-only government CAs are excluded. This is documented in the script header but not in the methodology doc or the UI. Should be surfaced as a filter note.
- CRL fetch uses `ssl.CERT_NONE` intentionally (RFC 5280 §6.3: CRL distribution is unauthenticated, CRL signature is the integrity check). This is correct and documented in the header, but should also be in the methodology doc since it looks like a security mistake.

---

## fetch_audits.py

**Shell-outs:** None. Uses `pdfplumber`. ✅

**Suppressions/fallbacks:** This is the highest-suppression script (141 hits). Most are legitimately in date-parsing loops (try each format, pass on failure, return None) — this pattern is correct for multi-format date parsing. The genuinely risky ones:

| Line | Code | Risk | Assessment |
|------|------|------|------------|
| 313 | `except Exception: return None` in cache read | 🟡 | Corrupted cache entry = treated as cache miss and refetched. Correct behavior but should log the exception so corrupt cache is visible. |
| 322 | `except Exception: pass` in cache write | 🔴 | Silent cache write failure means the next run re-fetches the same PDF at API cost. Should log `WARNING: cache write failed for {url}: {e}`. |
| 343 | `except Exception: return None` on PDF fetch | 🟡 | Fetch failure = treated as unavailable. `parse_error: "fetch_failed"` is set downstream. The exception itself is silently dropped — should log it. |
| 987–995 | Date parse try-loop with `pass` + `return None` | 🟢 | Correct pattern for multi-format parsing. The duplication of this loop in 3 places (lines 227–238, 982–995, 1710–1722) is a DRY violation — extract `_parse_audit_date(s)`. |
| 2169 | `except Exception: pass` loading incidents.json | 🔴 | If `incidents.json` fails to load, `incident_map` is empty — all per-CA incident counts show as 0 in audit profiles. No warning, no output flag. Should log and set a top-level `incident_data_missing: true` flag in output. |
| 2642 | `except Exception: pass` in URL priority scoring | 🟡 | Priority scoring error silently leaves a URL at default priority. Should log. |
| 2844 | `except ValueError: pass` on PDF period end date | 🟢 | Correct — CCADB dates are well-formed; parse failure means the field is malformed, and `pdf_pend = None` is the right result. |

**Methodology issues:**

- **Three copies of `_parse_audit_date`** (lines ~227, ~982, ~1710). They differ subtly — one includes `"July %d, %Y"` in the format list, another doesn't. This means the same date string can parse in one context and fail in another. Extract one canonical function.
- **Disclosure rate uses `bugs_in_period` length as denominator** — "bugs filed while the audit period was open." This counts bugs by their Bugzilla *filing* date, not their *incident* date. For incidents that occurred in period but were filed after the period closed (e.g., discovered later), this means the bug is not in the denominator even though the auditor *should* have detected it. The methodology doc should be explicit about this: we use filing date as a proxy for incident date when no incident date is parseable.
- **`incident_disclosure_check` only covers the most recent audit period** (lines 997–1044). A CA with 10 audit letters — the bug retrospective shows coverage across all letters, but `incident_disclosure_check` (the field the UI table sorts by) only covers the current letter's window. This is correct for the "current audit" question but should be labeled clearly: "current period only."
- **Letter quality score** `score_epoch` (pre_aal / aal_v3x) affects scoring criteria but is not explained in the UI. An older letter scored under `pre_aal` criteria can look better or worse than a current letter for reasons that aren't the CA's fault. Should surface in UI.

---

## fetch_rpe.py

**Shell-outs:** None. ✅

**Suppressions/fallbacks:**

| Line | Code | Risk | Assessment |
|------|------|------|------------|
| 218–220 | `except Exception: pass` reading HTTP error body | 🟢 | The outer `HTTPError` is already caught and printed; this `pass` just means the body preview is omitted. Acceptable. |
| 1003–1004 | `except (ValueError, IndexError): pass` parsing quarter from timestamp | 🟡 | If a Bugzilla `creation_time` is malformed, the comment is silently dropped from oversight metrics. Should count and log these so the magnitude of the data quality issue is visible. |
| 1999 | String-match fallback for gov classification | 🔴 | If `gov_risk.json` fails to load (line ~1985, unshown), the script falls back to substring matching on CA owner names ("government of", "ministerio", etc.). This produces different gov CA counts than the curated `gov_classifications.json`. The fallback should not exist — if `gov_risk.json` is missing, the governance risk metrics should not be computed. Fail explicitly. |

**Methodology issues:**

- **Google `@google.com` attribution** (documented in METHODOLOGY.md) is the most consequential attribution decision in the pipeline. The individual address registry is embedded inline in `fetch_rpe.py`. It should live in a separate versioned JSON file (`pipeline/root_program_staff.json`) so changes are visible in git diffs without reading script code.
- **Substantive Oversight** uses `classify_comments.py` output from `ops_cache/comment_classifications.json`. If this cache is cold (first run, or cache was deleted), `technical` defaults to `False` for all comments, making Substantive Oversight = 0 for all programs. This is documented behavior ("makes the cold state visible") but a fresh CI environment will produce misleading zeros. The output metadata should include `comment_classification_coverage: N/total` so the reader knows whether Substantive Oversight numbers are based on full or partial data.
- **Bugzilla Coverage** counts bugs where at least one `governance=True` comment exists. The denominator is "all open CA compliance bugs." Bugs opened after a root program's last Bugzilla comment are counted against it — a program could have perfect historical coverage but be penalized for bugs filed yesterday that they haven't yet commented on. A 30-day grace window on recent bugs would be more fair.

---

## fetch_incidents.py / classify_comments.py

**Duplication:** `classify_comments.py` has its own Bugzilla comment fetch logic and its own LLM call structure. `fetch_incidents.py` has LLM classification logic for bugs. These two scripts share no code despite calling the same Anthropic API endpoint with similar prompts. The LLM call wrapper (`_call_anthropic`) should live in `utils.py` and be imported by both.

---

## utils.py / config.py

**Gaps identified across scripts that should move here:**

| What | Currently | Should be |
|------|-----------|-----------|
| `parse_ccadb_date(s)` | 3+ inline copies | `utils.py` |
| `CA_EMAILS` set (self-report domain list) | inline in `fetch_incidents.py` | `pipeline/ca_domain_map.json` |
| Root program staff address registry | inline in `fetch_rpe.py` | `pipeline/root_program_staff.json` |
| LLM API call wrapper | duplicated in 3 scripts | `utils.py` |
| `CCADB_CSV_URL` | hardcoded in each script | `config.py` |
| BR validity schedule dates | inline in `export_ui_bundle.py` | `config.py` |

---

## Summary: Items Requiring Discussion Before Fixing

These changes would alter current output (test vector risk). Need your go-ahead:

### 🔴 Regression-risk items

1. **`fetch_and_join.py` lines 378/398/646 — date parse default.** Currently: parse failure → `expired=False` (included as valid). Proposed: parse failure → `expired=True` (excluded as conservatively expired). **Impact:** any root with an unparseable `valid_to` date would be excluded. Need to check: does any currently-included root have an unparseable date? Run: `grep -c "valid_to" data/ca/*.json | sort`.

2. **`fetch_crl_health.py` line 145 — openssl → cryptography.** `cert_subject` format will change. Currently used for display only in the CRL health tab. Propose running both in parallel for one cycle and diffing.

3. **`fetch_browser_share.py` line 137 — remove hardcoded fallback.** Script would fail the CI build if StatCounter is unreachable instead of silently using stale data. Build failure is more honest but means dashboard data doesn't update on a StatCounter outage.

4. **`fetch_rpe.py` line 1999 — remove gov string-match fallback.** Script would fail if `gov_risk.json` is missing instead of silently producing different counts. This is the right behavior but is a behavioral change.

### 🟡 Non-regression fixes (safe to do now)

- Extract `parse_ccadb_date()` into `utils.py` (no output change, identical logic)
- Add `classification_available: bool` to `incidents.json` metadata
- Move `CA_EMAILS` to a config file
- Move root program staff registry to a versioned JSON
- Add `comment_classification_coverage` to RPE output metadata
- Log cache write failures in `fetch_audits.py`
- Log incidents.json load failure in `fetch_audits.py` with explicit flag
- Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` throughout
- Fix decade range in `fetch_bulk_pems()` to derive from current year
- Fix `sig_oid._name` to use `dotted_string` or a lookup

---

## Methodology Issues for Discussion

These affect what the dashboard claims, not just implementation quality:

1. **PPM denominator for non-CT issuers** (PKIoverheid, T-Systems, etc.) — decided: show rate with `†` flag. Methodology doc needs updating.

2. **Disclosure rate uses Bugzilla filing date, not incident date** — filing date is a proxy. For incidents discovered late (filed after audit period closed), the denominator undercounts. Should be explicit in methodology.

3. **`incident_disclosure_check` covers current period only** — not all-time. The UI table needs to label this clearly.

4. **Bugzilla Coverage denominator includes bugs filed yesterday** — unfair to programs that haven't yet had time to comment. Consider 30-day grace window.

5. **Microsoft CTL changelog lag** — monthly deployment notices vs. daily CCADB snapshots. A root added mid-month appears in CCADB but not in the CTL changelog for up to 30 days. Currently documented as expected; consider noting in UI.

6. **Auditor detection rate filing-date vs. incident-date problem** — same as #2 but for audit letter coverage. Documented in METHODOLOGY.md but not in the UI.

7. **`score_epoch`** (pre-AAL vs. AAL v3) affects letter quality scores but is not explained in the UI. Older letters can appear better or worse for reasons outside the CA's control.
