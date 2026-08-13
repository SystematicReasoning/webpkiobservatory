"""
fetch_crl_health.py — CRL infrastructure health monitoring

Probes every CRL URL filed in CCADB for trusted CA certificates daily.

For each URL we record:
  - Fetch reachability, latency, and HTTP status
  - TLS endpoint quality (hostname match, cert expiry) for HTTPS URLs
  - Whether an HTTPS endpoint exists for HTTP-filed URLs (port 443 probe)
  - CRL parse validity and content: issuer DN, thisUpdate, nextUpdate,
    validity window, revoked certificate count and serials
  - Issuer DN match against the CCADB cert's subject DN
    (mismatch = wrong CRL filed; CRLite/CRL Sets aggregators get bad data)
  - BR §4.9.7 compliance: validity window vs applicable limit
    (10 days for end-entity scope, 12 months for sub-CA scope;
     only assessed for BR-governed CAs — Apple/Chrome/Mozilla stores)

Produces three output files in data/:
  crl_health.json         — current snapshot per URL (read by UI)
  crl_health_history.json — rolling 365-day daily time series per URL
  crl_health_events.json  — append-only state change log

Design decisions:
  - TLS verification is intentionally skipped for CRL fetches (RFC 5280 §6.3:
    CRL distribution is unauthenticated; the CRL signature is the integrity check).
    Root CA CRL servers legitimately use their own PKI for transport security.
  - The only genuine TLS transport error is hostname_mismatch: the URL hostname
    doesn't match the server's certificate, meaning the server isn't serving the
    right content regardless of who issued the cert.
  - Microsoft-only government CAs are typically not CA/B Forum TLS BR-governed;
    we record their CRL validity windows but do not flag them as BR violations.
"""

import base64
from cryptography import x509 as _x509
import csv
import hashlib
import datetime
import io
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from pathlib import Path
from config import normalize_ca_owner
from urllib.parse import urlparse


UTC = datetime.timezone.utc
OUTPUT_DIR = Path(__file__).parent.parent / "data"


def _now_utc():
    """Current time as a timezone-aware UTC datetime."""
    return datetime.datetime.now(UTC)




HISTORY_WINDOW_DAYS = 365
MAX_EVENTS          = 10_000
MAX_WORKERS         = 32    # parallel URL probes — I/O-bound so high count is fine


def load_json(path, default):
    p = Path(path)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))


def append_history(history, url_key, date_str, entry):
    """Add today's entry for url_key, deduplicating and pruning to window."""
    if url_key not in history:
        history[url_key] = []
    history[url_key] = [e for e in history[url_key] if e.get("date") != date_str]
    history[url_key].append(entry)
    cutoff = (datetime.date.today() - datetime.timedelta(days=HISTORY_WINDOW_DAYS)).isoformat()
    history[url_key] = [e for e in history[url_key] if e.get("date", "") >= cutoff]


def record_event(events, url, ca_owner, event_type, detail, date_str):
    """Append a state-change event, capping at MAX_EVENTS."""
    events.append({"date": date_str, "url": url, "ca": ca_owner,
                   "event": event_type, "detail": detail})
    if len(events) > MAX_EVENTS:
        events[:] = events[-MAX_EVENTS:]


# ── Section 2: TLS probing ─────────────────────────────────────────────────────

def probe_tls(host, port=443, timeout=8):
    """
    Connect to host:port and inspect the TLS certificate the server presents.

    Always uses an unverified context — we want to see what the server sends
    regardless of whether it chains to a public root. Root CA CRL servers
    legitimately use their own PKI for TLS.

    Returns a dict with:
      exists          — True if port responded to TLS handshake
      hostname_ok     — True/False/None (True = cert covers this hostname)
      cert_expired    — True/False/None
      tls_error       — 'hostname_mismatch' | 'cert_expired' | None
                        Only genuine errors that affect fetchability
      cert_subject    — leaf cert subject DN string
      cert_serial     — hex serial of leaf cert (for revocation cross-check)
      tls_info        — 'verified' (public root + hostname ok) | 'ca_signed' |
                        'unreachable' | 'probe_failed'
    """
    result = {
        "exists":       False,
        "hostname_ok":  None,
        "cert_expired": None,
        "tls_error":    None,
        "cert_subject": None,
        "cert_serial":  None,
        "tls_info":     None,
    }
    try:
        # Connect and get leaf cert without verification
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                result["exists"] = True
                leaf_der = ssock.getpeercert(binary_form=True)
                if not leaf_der:
                    result["tls_info"] = "probe_failed"
                    return result

        # Parse leaf cert for subject, serial, expiry using the cryptography library.
        # This replaces a subprocess openssl call — same information, deterministic
        # behavior, no external tool dependency.
        #
        # Subject format intentionally matches OpenSSL's one-liner output
        # (e.g. "C = US, O = Example Corp, CN = crl.example.com") so that
        # existing stored values are consistent across pipeline runs.
        _OID_SHORT = {
            _x509.oid.NameOID.COMMON_NAME:              "CN",
            _x509.oid.NameOID.ORGANIZATION_NAME:        "O",
            _x509.oid.NameOID.COUNTRY_NAME:             "C",
            _x509.oid.NameOID.STATE_OR_PROVINCE_NAME:   "ST",
            _x509.oid.NameOID.LOCALITY_NAME:            "L",
            _x509.oid.NameOID.ORGANIZATIONAL_UNIT_NAME: "OU",
            _x509.oid.NameOID.EMAIL_ADDRESS:            "emailAddress",
        }
        try:
            leaf_cert = _x509.load_der_x509_certificate(leaf_der)
            result["cert_subject"] = ", ".join(
                f"{_OID_SHORT.get(a.oid, a.oid.dotted_string)} = {a.value}"
                for a in leaf_cert.subject
            )
            # Serial: uppercase hex, no leading zeros, no colons — matches prior format.
            result["cert_serial"] = format(leaf_cert.serial_number, "X")
            result["cert_expired"] = leaf_cert.not_valid_after_utc < _now_utc()
            if result["cert_expired"]:
                result["tls_error"] = "cert_expired"
        except Exception as e:
            # Cert parse failure: fields remain None. Log so we know which host failed.
            print(f"    WARNING: could not parse TLS leaf cert for {host}: {e}")

        # Check hostname match by connecting with CERT_NONE and manually inspecting
        # the cert's SANs/CN. Python 3.10+ raises ValueError if check_hostname=True
        # is combined with CERT_NONE, so we can't use that approach.
        try:
            ctx_hn = ssl.create_default_context()
            ctx_hn.check_hostname = False
            ctx_hn.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, port), timeout=timeout) as s2:
                with ctx_hn.wrap_socket(s2, server_hostname=host) as tls2:
                    peer_der = tls2.getpeercert(binary_form=True)
            if peer_der:
                from cryptography import x509 as _cx
                from cryptography.x509.oid import ExtensionOID as _EO, NameOID as _NO
                cert_obj = _cx.load_der_x509_certificate(peer_der)
                try:
                    san = cert_obj.extensions.get_extension_for_oid(_EO.SUBJECT_ALTERNATIVE_NAME)
                    dns_names = san.value.get_values_for_type(_cx.DNSName)
                except Exception:
                    dns_names = []
                if not dns_names:
                    try:
                        dns_names = [cert_obj.subject.get_attributes_for_oid(_NO.COMMON_NAME)[0].value]
                    except Exception:
                        dns_names = []
                host_lower = host.lower()
                matched = any(
                    n.lower() == host_lower or
                    (n.startswith("*.") and host_lower.endswith(n[1:].lower()))
                    for n in dns_names
                )
                result["hostname_ok"] = matched
                if not matched and not result["tls_error"]:
                    result["tls_error"] = "hostname_mismatch"
            else:
                result["hostname_ok"] = None
        except Exception:
            result["hostname_ok"] = None

        # Classify tls_info: verified = hostname ok + no error (implies public root validation
        # possible; we don't require it since root CA servers use their own PKI legitimately)
        if result["tls_error"]:
            result["tls_info"] = result["tls_error"]
        elif result["hostname_ok"] is True:
            result["tls_info"] = "verified"
        else:
            result["tls_info"] = "ca_signed"

    except (ConnectionRefusedError, OSError):
        result["tls_info"] = "unreachable"
    except Exception:
        result["tls_info"] = "probe_failed"

    return result


# ── Section 3: URL classification ─────────────────────────────────────────────

def classify_url(url):
    """
    Classify a CCADB-filed CRL URL structurally before attempting to fetch it.

    Returns:
      ok        — False if unfetchable even after inference attempts
      fetch_url — the URL to actually fetch (may have http:// prepended)
      inferred  — True if scheme was inferred (CCADB data quality issue)
      errors    — list of hard error codes (drive invalid_url status)
      info      — list of informational codes (display only, not failures)

    Empirically validated against all 315 trusted CA CRL URLs in CI:
    no_extension, root_path, encoded_spaces, query_param, cgi_endpoint
    are all valid patterns. Only no_scheme/no_hostname are hard errors.
    """
    errors = []
    info = []
    inferred = False
    fetch_url = url

    parsed = urlparse(url)

    if not parsed.scheme:
        # Try prepending http:// — catches "www.host.com/path" typos in CCADB
        candidate = "http://" + url
        cp = urlparse(candidate)
        if cp.netloc:
            fetch_url = candidate
            inferred = True
            info.append("inferred_http_scheme")
        else:
            errors.extend(["no_scheme", "no_hostname"])
    elif parsed.scheme not in ("http", "https"):
        errors.append(f"bad_scheme:{parsed.scheme}")
    elif not parsed.netloc:
        errors.append("no_hostname")

    if not errors:
        p = urlparse(fetch_url)
        path = p.path
        if not path or path == "/":
            info.append("root_path")          # e.g. reference entity x1.c.lencr.org/ — valid
        else:
            last_seg = path.rstrip("/").split("/")[-1]
            if not last_seg:
                info.append("trailing_slash")
            elif "." not in last_seg:
                info.append("no_extension")   # e.g. reference entity getLastCRL — valid
            else:
                ext = last_seg.rsplit(".", 1)[-1].lower()
                if ext == "cgi":
                    info.append("cgi_endpoint")   # e.g. reference entity index.cgi?crl=gold — valid
                elif ext not in ("crl", "der", "pem", "bin", "cer"):
                    info.append(f"ext_{ext}")
        if p.query:
            info.append("query_param")        # e.g. eMudhra ?RootCAC1.crl — valid
        if "%20" in fetch_url or " " in fetch_url:
            info.append("encoded_spaces")     # e.g. Microsoft %20 in filename — valid

    return {
        "ok":       not errors,
        "fetch_url": fetch_url,
        "inferred":  inferred,
        "errors":    errors,
        "info":      info,
    }


# ── Section 4: CRL fetching ───────────────────────────────────────────────────

def fetch_crl(url, timeout=15, prev_etag=None, prev_last_modified=None):
    """
    Fetch a CRL URL without TLS verification (RFC 5280 §6.3: CRL distribution
    is unauthenticated; the CRL signature is the integrity check).

    Supports conditional GET: if prev_etag or prev_last_modified are supplied
    (from the previous run's state), sends If-None-Match / If-Modified-Since.
    A 304 response means the CRL hasn't changed — returns ok=True, data=None,
    and not_modified=True so the caller can reuse the previous parsed state.

    For HTTPS URLs: also calls probe_tls to capture TLS metadata.

    Returns dict with keys:
      ok             — True if usable response received
      not_modified   — True if server returned 304 (content unchanged)
      status_code    — HTTP status or None
      elapsed_ms     — total round-trip time
      size_bytes     — response body size or None
      data           — raw response bytes or None (None on 304)
      error          — human-readable error string or None
      error_class    — machine-readable error class or None
      crl_hash       — SHA-256[:16] of response bytes or None
      etag           — ETag header value for next conditional GET
      last_modified  — Last-Modified header value for next conditional GET
      cache_control  — raw Cache-Control header value
      cache_max_age  — parsed max-age in seconds, or None
      tls            — dict from probe_tls if HTTPS, else None
    """
    result = {
        "ok": False, "not_modified": False,
        "status_code": None, "elapsed_ms": None,
        "size_bytes": None, "data": None,
        "error": None, "error_class": None,
        "crl_hash": None, "tls": None,
        "etag": None, "last_modified": None,
        "cache_control": None, "cache_max_age": None,
    }
    t0 = time.monotonic()

    parsed   = urlparse(url)
    is_https = parsed.scheme == "https"

    # TLS probe for HTTPS URLs (best-effort)
    if is_https:
        result["tls"] = probe_tls(parsed.hostname, parsed.port or 443)

    # Build SSL context for HTTPS (no cert verification — see docstring)
    ctx = None
    if is_https:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE

    headers = {"User-Agent": "Mozilla/5.0 (compatible; CRL-Health-Check/1.0)"}
    if prev_etag:
        headers["If-None-Match"] = prev_etag
    elif prev_last_modified:
        headers["If-Modified-Since"] = prev_last_modified

    req    = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx) if ctx else urllib.request.HTTPSHandler()
    )

    try:
        with opener.open(req, timeout=timeout) as resp:
            result["status_code"] = resp.status
            result["data"]        = resp.read()
            result["size_bytes"]  = len(result["data"])
            result["crl_hash"]    = hashlib.sha256(result["data"]).hexdigest()[:16]
            result["ok"]          = True

            # Capture validators for next conditional GET
            result["etag"]          = resp.headers.get("ETag")
            result["last_modified"] = resp.headers.get("Last-Modified")

            # Capture HTTP caching headers for freshness compliance check.
            # RFC 5019 §6.1 recommends Cache-Control: max-age matching the
            # CRL validity period. Many servers omit these headers entirely.
            cc  = resp.headers.get("Cache-Control")
            exp = resp.headers.get("Expires")
            if cc:
                result["cache_control"] = cc
                for part in cc.split(","):
                    part = part.strip().lower()
                    if part.startswith("max-age="):
                        try:
                            result["cache_max_age"] = int(part[8:].strip())
                        except ValueError:
                            pass
            elif exp:
                result["cache_control"] = f"Expires: {exp}"
                try:
                    from email.utils import parsedate_to_datetime
                    exp_dt = parsedate_to_datetime(exp)
                    delta  = (exp_dt - _now_utc()).total_seconds()
                    if delta > 0:
                        result["cache_max_age"] = int(delta)
                except Exception:
                    pass

    except urllib.error.HTTPError as e:
        if e.code == 304:
            # Not Modified — content unchanged since last fetch
            result["ok"]           = True
            result["not_modified"] = True
            result["status_code"]  = 304
        else:
            result["status_code"] = e.code
            result["error"]       = f"HTTP {e.code}"
            result["error_class"] = f"http_{e.code}"
    except urllib.error.URLError as e:
        reason = str(e.reason)
        result["error"] = f"URLError: {reason}"
        r = reason.lower()
        result["error_class"] = (
            "dns_error"        if "name or service" in r or "getaddrinfo" in r else
            "timeout"          if "timed out"        in r else
            "connection_error"
        )
    except TimeoutError:
        result["error"]       = "Timeout"
        result["error_class"] = "timeout"
    except Exception as e:
        result["error"]       = f"{type(e).__name__}: {e}"
        result["error_class"] = "unknown"
    finally:
        result["elapsed_ms"] = round((time.monotonic() - t0) * 1000)

    return result


# ── Section 5: CRL parsing ────────────────────────────────────────────────────


# RFC 5280 reason codes — maps cryptography enum names to display strings
_REASON_DISPLAY = {
    "key_compromise":          "keyCompromise",
    "ca_compromise":           "cACompromise",
    "affiliation_changed":     "affiliationChanged",
    "superseded":              "superseded",
    "cessation_of_operation":  "cessationOfOperation",
    "certificate_hold":        "certificateHold",
    "remove_from_crl":         "removeFromCRL",
    "privilege_withdrawn":     "privilegeWithdrawn",
    "aa_compromise":           "aACompromise",
    "unspecified":             "unspecified",
}


def parse_crl(data):
    """
    Parse raw CRL bytes (DER or PEM) using the cryptography library.

    Returns:
      ok                   — True if data is a valid CRL
      issuer               — issuer DN string (RFC 4514)
      last_update          — thisUpdate as ISO-8601 string
      next_update          — nextUpdate as ISO-8601 string
      next_update_iso      — nextUpdate ISO-8601 (None for sentinel 9999 dates)
      next_update_dt       — nextUpdate as timezone-aware datetime
      is_stale             — True if nextUpdate is in the past
      hours_until_expiry   — hours until nextUpdate (None for sentinel dates)
      validity_window_days — nextUpdate − thisUpdate in days (None for sentinels)
      revoked_count        — total revoked certificate entries
      revoked_serials      — set of serials (hex, no leading zeros) for
                             HTTPS endpoint revocation cross-check
      revocation_reasons   — dict of reason_display_name → count
                             includes "unspecified" for entries with no reason ext
      error                — failure classification if not ok
    """
    result = {
        "ok": False, "issuer": None,
        "last_update": None, "next_update": None,
        "next_update_iso": None, "next_update_dt": None,
        "is_stale": None, "hours_until_expiry": None,
        "validity_window_days": None,
        "revoked_count": None, "revoked_serials": set(),
        "revocation_reasons": {},
        "error": None,
    }

    if not data:
        result["error"] = "no_data"
        return result

    # Try DER first, then PEM
    crl = None
    for loader in (_x509.load_der_x509_crl, _x509.load_pem_x509_crl):
        try:
            crl = loader(data)
            break
        except Exception:
            continue

    if crl is None:
        result["error"] = _classify_parse_failure(data)
        return result

    now = _now_utc()
    result["ok"] = True
    result["issuer"] = crl.issuer.rfc4514_string()

    lu = crl.last_update_utc
    nu = crl.next_update_utc

    if lu:
        result["last_update"] = lu.strftime("%Y-%m-%dT%H:%M:%SZ")

    if nu:
        result["next_update_dt"] = nu
        result["is_stale"] = nu < now

        if nu.year >= 9000:
            # Sentinel "never expires" (e.g. 9999-12-31 in some root ARLs)
            result["next_update_iso"] = None
            result["hours_until_expiry"] = None
        else:
            result["next_update"] = nu.strftime("%Y-%m-%dT%H:%M:%SZ")
            result["next_update_iso"] = result["next_update"]
            result["hours_until_expiry"] = round((nu - now).total_seconds() / 3600, 1)

        if lu and nu.year < 9000:
            window_h = (nu - lu).total_seconds() / 3600
            result["validity_window_days"] = round(window_h / 24, 1)

    # Revoked certificate entries — extract serials and reason codes
    reasons: dict = {}
    serials: set = set()
    count = 0

    for rev in crl:
        count += 1
        serial_hex = format(rev.serial_number, "X").lstrip("0") or "0"
        serials.add(serial_hex)

        try:
            reason_ext = rev.extensions.get_extension_for_class(_x509.CRLReason)
            reason_key = reason_ext.value.reason.name.lower()
        except _x509.ExtensionNotFound:
            reason_key = "unspecified"

        display = _REASON_DISPLAY.get(reason_key, reason_key)
        reasons[display] = reasons.get(display, 0) + 1

    result["revoked_count"] = count
    result["revoked_serials"] = serials
    result["revocation_reasons"] = reasons

    return result


def _classify_parse_failure(data):
    """Classify why CRL bytes couldn't be parsed."""
    if not data:
        return "no_data"
    # Check HTML before size — short HTML error pages are still HTML, not too_small
    data_head = data[:512].lower()
    is_html = data[:5] in (b"<html", b"<HTML", b"<!DOC", b"<?xml") or b"<html" in data_head
    if is_html:
        index_keywords = (b"index", b"listing", b"directory", b"crl list", b"available crl", b"crls")
        if any(kw in data_head for kw in index_keywords):
            return "url_is_index"    # URL points to a CRL listing page, not a CRL file
        return "html_response"       # Generic web page — wrong URL or redirect
    if len(data) < 64:
        return "too_small"           # Too small to be a valid CRL
    return "not_crl_format"          # Has content but not DER or PEM CRL


# ── Section 6: Compliance checks ──────────────────────────────────────────────

def check_issuer_match(crl_issuer_dn, ca_cert_subject_dn):
    """
    Verify the CRL issuer DN matches the CA certificate subject DN.

    Both DNs must come from the same source (cryptography rfc4514_string())
    so OID representation and escaping are consistent.

    The CRL issuer may omit optional fields present in the cert subject
    (e.g. L, ST) — that is acceptable per RFC 5280. Exact match or subset
    both pass.

    A mismatch means CCADB has the wrong CRL URL for this cert.
    Consequence: CRLite (Firefox) and CRL Sets (Chrome) — which are built
    by aggregating CRLs from CCADB records — will ingest incorrect revocation
    data. Browsers fetching CDPs directly from certificate extensions are
    unaffected since they use the URL embedded in the cert, not CCADB.

    Returns (match: True|False|None, detail: str).
    """
    if not crl_issuer_dn or not ca_cert_subject_dn:
        return None, "missing_dn"

    def rfc4514_parts(dn):
        """
        Split an RFC 4514 DN string into a set of normalised attribute=value
        parts, correctly handling RFC 4514 escaped commas inside values.
        """
        parts = []
        current = []
        i = 0
        while i < len(dn):
            if dn[i] == '\\' and i + 1 < len(dn):
                current.append(dn[i:i+2])  # keep escape sequence intact
                i += 2
            elif dn[i] == ',':
                parts.append(''.join(current).strip())
                current = []
                i += 1
            else:
                current.append(dn[i])
                i += 1
        if current:
            parts.append(''.join(current).strip())
        return {p.lower() for p in parts if p}

    crl_parts  = rfc4514_parts(crl_issuer_dn)
    cert_parts = rfc4514_parts(ca_cert_subject_dn)

    if crl_parts == cert_parts:
        return True, "exact"
    if crl_parts and crl_parts.issubset(cert_parts):
        return True, f"subset+{len(cert_parts - crl_parts)}"
    missing = crl_parts - cert_parts
    return False, f"mismatch:{','.join(sorted(missing))[:80]}"


def assess_br_validity(validity_window_days, revoked_count, br_governed,
                       cert_type=None):
    """
    Assess CRL validity window against BR §4.9.7.

    BR §4.9.7 limits (as of BR 2.x / S/MIME BRs / CSBRs):
      CRL covering subordinate CAs (root-issued):  ≤ 12 months (366 days)
      CRL covering end-entity subscriber certs:    ≤ 10 days

    Scope determination (in priority order):
      1. cert_type == "Root Certificate" → CRL Distribution Point on a root
         cert covers subordinate CAs → 12-month limit.  Root CAs do not issue
         end-entity certs directly, so revoked_count is irrelevant here.
      2. cert_type == "Intermediate Certificate" → CRL may cover end-entities
         or sub-CAs.  Use revoked_count as proxy:
           > 100 revoked → likely end-entity scope → 10-day limit
           ≤ 100 revoked → likely sub-CA scope → 12-month limit
      3. cert_type unknown → fall back to revoked_count heuristic.

    BR applicability: CA/B Forum BRs apply to CAs in Apple, Chrome, or Mozilla
    trust stores. Microsoft-only government CAs are often not TLS-issuing and
    not BR-governed; their applicable standard is national PKI policy.

    Returns (ok: True|False|None, limit_days: int|None).
      True  — within limit (BR-governed)
      False — exceeds limit (BR-governed)
      None  — not BR-governed, no assessment made
    """
    if validity_window_days is None:
        return None, None
    if not br_governed:
        return None, None   # Not our place to assess

    if cert_type == "Root Certificate":
        limit = 366          # Root CDP always covers sub-CAs
    else:
        # Intermediate or unknown: infer from revoked_count
        limit = 10 if (revoked_count or 0) > 100 else 366

    return validity_window_days <= limit, limit


# ── Section 7: State change detection ─────────────────────────────────────────

def detect_transitions(prev, new, url, ca_owner, date_str, events):
    """
    Compare previous and current probe state and log meaningful transitions.

    Events logged:
      outage / recovered    — fetch_ok changed
      crl_expired           — CRL became stale (nextUpdate passed)
      crl_refreshed         — CRL was refreshed (new content hash or stale→fresh)
      issuer_mismatch       — wrong CRL URL detected
      issuer_match_restored — correct CRL URL restored
      url_changed           — cert fingerprint maps to different URL than before
      mass_revocation       — revoked count increased by ≥100 in one day
      crl_reset             — revoked count decreased by ≥100 (CRL reissued)
    """
    if not prev:
        return

    # Availability
    if prev.get("fetch_ok") != new.get("fetch_ok"):
        ok = new.get("fetch_ok")
        detail = new.get("tls", {}).get("tls_error") or new.get("error_class") or ""
        record_event(events, url, ca_owner,
                     "recovered" if ok else "outage",
                     f"fetch {'ok' if ok else 'failed'}: {detail}", date_str)

    # Issuer match
    was_match = prev.get("issuer_match")
    now_match = new.get("issuer_match")
    if was_match is not None and now_match is not None and was_match != now_match:
        record_event(events, url, ca_owner,
                     "issuer_mismatch" if not now_match else "issuer_match_restored",
                     new.get("issuer_match_detail", ""), date_str)

    # Staleness
    was_stale = prev.get("is_stale")
    now_stale = new.get("is_stale")
    if was_stale is not None and now_stale is not None:
        if not was_stale and now_stale:
            record_event(events, url, ca_owner, "crl_expired",
                         f"nextUpdate was {new.get('next_update_iso', '')}", date_str)
        elif was_stale and not now_stale:
            record_event(events, url, ca_owner, "crl_refreshed",
                         f"nextUpdate now {new.get('next_update_iso', '')}", date_str)

    # Content change (same URL, different CRL bytes)
    prev_hash = prev.get("crl_hash")
    new_hash  = new.get("crl_hash")
    if prev_hash and new_hash and prev_hash != new_hash:
        # Don't double-log if we already logged crl_refreshed for stale→fresh above
        if not (was_stale and not now_stale):
            record_event(events, url, ca_owner, "crl_refreshed",
                         f"CRL content updated ({prev_hash}→{new_hash})", date_str)

    # URL rotation (same cert fingerprint, different URL)
    prev_url = prev.get("url")
    new_url  = new.get("url")
    if prev_url and new_url and prev_url != new_url:
        record_event(events, new_url, ca_owner, "url_changed",
                     f"URL changed: {prev_url} → {new_url}", date_str)

    # Revocation count spike
    prev_rc = prev.get("revoked_count")
    new_rc  = new.get("revoked_count")
    if prev_rc is not None and new_rc is not None:
        delta = new_rc - prev_rc
        if delta >= 100:
            record_event(events, url, ca_owner, "mass_revocation",
                         f"+{delta} ({prev_rc}→{new_rc})", date_str)
        elif delta <= -100:
            record_event(events, url, ca_owner, "crl_reset",
                         f"{delta} ({prev_rc}→{new_rc})", date_str)


# ── Section 8: CCADB loading ──────────────────────────────────────────────────

def load_ccadb():
    """Fetch CCADB AllCertificateRecordsCSVFormatv4 and return records."""
    url = "https://ccadb.my.salesforce-sites.com/ccadb/AllCertificateRecordsCSVFormatv4"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(raw)))


def load_pem_cache():
    pem_path = Path(__file__).parent / "pem_cache.json"
    return json.loads(pem_path.read_text()) if pem_path.exists() else {}


def get_cert_subject(fp, pem_cache):
    """
    Return the cert subject DN as an RFC 4514 string for a SHA-256 fingerprint.

    Uses the cryptography library (same as parse_crl) so that the subject DN
    format matches exactly — same OID names, same escaping — enabling reliable
    comparison in check_issuer_match without format translation.
    """
    pem = pem_cache.get(fp.upper().replace(":", "").replace(" ", ""))
    if not pem:
        return None
    try:
        import warnings as _warnings
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            cert = _x509.load_pem_x509_certificate(pem.encode())
        return cert.subject.rfc4514_string()
    except Exception:
        return None


def build_url_meta(records):
    """
    Extract CRL URL metadata from CCADB records.

    Returns a dict: { crl_url → { ca_owner, cert_fp, cert_type,
                                   in_apple, in_chrome, in_mozilla, in_microsoft,
                                   br_governed, crl_source,
                                   all_referencing_owners } }

    One entry per unique URL. If multiple certs file the same URL, the first
    trusted active unrevoked record wins for the primary metadata fields.

    crl_source: "full" for "Full CRL Issued By This CA",
                "partitioned" for "JSON Array of Partitioned CRLs".

    all_referencing_owners: sorted list of every distinct CA owner that files
    this URL in CCADB (across all trusted active unrevoked records). Used to
    detect shared CRL infrastructure — both within-CA (multiple intermediates
    sharing one CRL endpoint) and cross-CA (distinct CA organizations pointing
    to the same URL, indicating outsourced or delegated CRL hosting).

    br_governed = CA is in Apple, Chrome, or Mozilla store.
    Microsoft-only CAs are often government PKIs not governed by CA/B Forum BRs.

    Sources:
      - "Full CRL Issued By This CA"       — one ARL/CRL per record (roots and intermediates)
      - "JSON Array of Partitioned CRLs"   — sharded end-entity CRLs (intermediates only);
                                             this is where 300k+ revocation entries live.

    CCADB status semantics differ by record type:
      - Root Certificate:          status fields use "Included" / (blank)
      - Intermediate Certificate:  status fields use "Trusted" / "Not Trusted"
    Both values are checked so that is_trusted() works for both record types.
    """
    today = datetime.date.today()

    def is_trusted(r):
        return any(r.get(f, "").strip() in ("Included", "Trusted") for f in
                   ("Apple Status", "Chrome Status", "Microsoft Status", "Mozilla Status"))

    def is_active(r):
        vt = r.get("Valid To (GMT)", "").strip()
        if not vt:
            return True
        try:
            return datetime.datetime.strptime(vt, "%Y.%m.%d").date() > today
        except ValueError:
            return True

    def is_unrevoked(r):
        return r.get("Revocation Status", "").strip().lower() not in ("revoked", "parent cert revoked")

    def record_meta(r, source):
        in_apple   = r.get("Apple Status",     "").strip() in ("Included", "Trusted")
        in_chrome  = r.get("Chrome Status",    "").strip() in ("Included", "Trusted")
        in_mozilla = r.get("Mozilla Status",   "").strip() in ("Included", "Trusted")
        in_msft    = r.get("Microsoft Status", "").strip() in ("Included", "Trusted")
        return {
            "ca_owner":     normalize_ca_owner(r.get("CA Owner", "").strip()),
            "cert_fp":      r.get("SHA-256 Fingerprint", "").replace(":", "").replace(" ", "").upper(),
            "cert_type":    r.get("Certificate Record Type", ""),
            "in_apple":     in_apple,
            "in_chrome":    in_chrome,
            "in_mozilla":   in_mozilla,
            "in_microsoft": in_msft,
            "br_governed":  in_apple or in_chrome or in_mozilla,
            "crl_source":   source,
        }

    # Two-pass approach:
    # Pass 1: collect primary meta (first-seen wins) + accumulate all referencing owners.
    # Pass 2: fold all_referencing_owners into the final meta dict.
    url_meta    = {}                          # url → primary meta dict
    url_owners  = defaultdict(set)            # url → set of all CA owners that reference it

    for r in records:
        if r.get("Certificate Record Type") not in ("Root Certificate", "Intermediate Certificate"):
            continue
        if not (is_trusted(r) and is_active(r) and is_unrevoked(r)):
            continue

        owner = normalize_ca_owner(r.get("CA Owner", "").strip())

        # ── Full CRL / ARL (one per record) ──────────────────────────────────
        crl_url = r.get("Full CRL Issued By This CA", "").strip()
        if crl_url:
            if crl_url not in url_meta:
                url_meta[crl_url] = record_meta(r, "full")
            url_owners[crl_url].add(owner)

        # ── Partitioned (sharded) end-entity CRLs ────────────────────────────
        # CCADB stores these as a JSON array of URL strings. This is the field
        # that contains the large end-entity CRLs (300k+ entries for major CAs).
        partitioned_raw = r.get("JSON Array of Partitioned CRLs", "").strip()
        if partitioned_raw and partitioned_raw != "[]":
            try:
                partitioned_urls = json.loads(partitioned_raw)
            except (json.JSONDecodeError, ValueError):
                partitioned_urls = []
            for p_url in partitioned_urls:
                p_url = p_url.strip() if isinstance(p_url, str) else ""
                if p_url:
                    if p_url not in url_meta:
                        url_meta[p_url] = record_meta(r, "partitioned")
                    url_owners[p_url].add(owner)

    # Stamp all_referencing_owners onto each entry. Sort for deterministic output.
    for url, meta in url_meta.items():
        meta["all_referencing_owners"] = sorted(url_owners[url])

    return url_meta


# ── Section 9: run() ──────────────────────────────────────────────────────────


def _probe_url(url, meta, pem_cache, prev_state=None):
    """
    Probe a single CRL URL and return its state dict.

    This is the unit of parallelism — called concurrently for all URLs.
    It is pure I/O (network fetches + cryptography library calls) with no
    shared mutable state. The caller is responsible for transition detection,
    history appending, and event recording (all of which need serialization).

    prev_state: previous run's state dict for this URL, used to send
    conditional GET headers (If-None-Match / If-Modified-Since). On 304
    the parsed CRL values are copied forward unchanged.
    """
    now_iso = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    ca = meta["ca_owner"]
    fp = meta["cert_fp"]

    url_class = classify_url(url)

    state = {
        # Identity
        "url":         url,
        "fetch_url":   url_class["fetch_url"],
        "url_inferred": url_class["inferred"],
        "url_errors":  url_class["errors"],
        "url_info":    url_class["info"],
        "ca_owner":    ca,
        "cert_fp":     fp,
        "cert_type":   meta["cert_type"],
        "probed_at":   now_iso,
        # CRL source and sharing
        "crl_source":       meta.get("crl_source"),        # "full" | "partitioned"
        "shared_crl":       None,                          # populated post-probe
        "shared_with_cas":  None,                          # populated post-probe
        # Trust store presence
        "in_apple":    meta["in_apple"],
        "in_chrome":   meta["in_chrome"],
        "in_mozilla":  meta["in_mozilla"],
        "in_microsoft": meta["in_microsoft"],
        "br_governed": meta["br_governed"],
        # Fetch
        "fetch_ok":    None,
        "status_code": None,
        "elapsed_ms":  None,
        "size_bytes":  None,
        "crl_hash":    None,
        "error":       None,
        "error_class": None,
        # Conditional GET validators (persisted across runs)
        "etag":          None,
        "last_modified": None,
        # Caching headers
        "cache_control": None,
        "cache_max_age": None,
        # TLS (HTTPS-filed URLs)
        "tls_info":    None,
        "tls_error":   None,
        # HTTPS endpoint probe (HTTP-filed URLs)
        "https_probe_exists":       None,
        "https_probe_tls_ok":       None,
        "https_probe_hostname_ok":  None,
        "https_probe_expired":      None,
        "https_probe_cert_subject": None,
        "https_probe_cert_serial":  None,
        "https_probe_revoked":      None,
        # CRL content
        "crl_b64":              None,
        "parse_ok":             None,
        "issuer":               None,
        "last_update":          None,
        "next_update":          None,
        "next_update_iso":      None,
        "is_stale":             None,
        "hours_until_expiry":   None,
        "validity_window_days": None,
        "revoked_count":        None,
        "_revoked_serials":     set(),   # temp — used for post-processing, stripped before output
        # Compliance
        "issuer_match":           None,
        "issuer_match_detail":    None,
        "br_validity_ok":         None,
        "br_validity_limit_days": None,
        # Overall
        "status": "unknown",
    }

    if not url_class["ok"]:
        state.update(fetch_ok=False, error_class="invalid_url", status="invalid_url")
        return state

    # Fetch — use conditional GET if we have validators from previous run
    prev_etag  = prev_state.get("etag")          if prev_state else None
    prev_lm    = prev_state.get("last_modified")  if prev_state else None
    fetch = fetch_crl(url_class["fetch_url"], prev_etag=prev_etag, prev_last_modified=prev_lm)

    state["fetch_ok"]    = fetch["ok"]
    state["status_code"] = fetch["status_code"]
    state["elapsed_ms"]  = fetch["elapsed_ms"]
    state["error"]       = fetch["error"]
    state["error_class"] = fetch["error_class"]

    # Persist validators for next run's conditional GET
    if fetch.get("etag"):
        state["etag"] = fetch["etag"]
    elif prev_state and prev_state.get("etag"):
        state["etag"] = prev_state["etag"]   # preserve from previous run
    if fetch.get("last_modified"):
        state["last_modified"] = fetch["last_modified"]
    elif prev_state and prev_state.get("last_modified"):
        state["last_modified"] = prev_state["last_modified"]

    if fetch.get("not_modified") and prev_state:
        # 304 — CRL content unchanged. Copy forward all parsed values from
        # previous run so the rest of the pipeline sees a complete state.
        for key in ("size_bytes", "crl_hash", "parse_ok", "issuer",
                    "last_update", "next_update", "next_update_iso",
                    "is_stale", "hours_until_expiry", "validity_window_days",
                    "revoked_count", "revocation_reasons",
                    "issuer_match", "issuer_match_detail",
                    "br_validity_ok", "br_validity_limit_days",
                    "cache_control", "cache_max_age", "cache_exceeds_window",
                    "tls_info", "tls_error",
                    "https_probe_exists", "https_probe_tls_ok",
                    "https_probe_hostname_ok", "https_probe_expired",
                    "https_probe_cert_subject", "https_probe_cert_serial"):
            if key in prev_state:
                state[key] = prev_state[key]
        # Revoked serials not stored in state — treat as empty on 304
        state["_revoked_serials"] = set()
        state["status"] = _assign_status(state)
        return state

    state["size_bytes"]    = fetch["size_bytes"]
    state["crl_hash"]      = fetch["crl_hash"]
    state["cache_control"] = fetch["cache_control"]
    state["cache_max_age"] = fetch["cache_max_age"]

    tls = fetch.get("tls") or {}
    state["tls_info"]  = tls.get("tls_info")
    state["tls_error"] = tls.get("tls_error")

    # HTTPS endpoint probe for HTTP-filed URLs
    parsed_fetch = urlparse(url_class["fetch_url"])
    if parsed_fetch.scheme == "http":
        hp = probe_tls(parsed_fetch.hostname)
        state["https_probe_exists"]       = hp["exists"]
        state["https_probe_tls_ok"]       = hp.get("hostname_ok") is True and hp.get("cert_expired") is False
        state["https_probe_hostname_ok"]  = hp.get("hostname_ok")
        state["https_probe_expired"]      = hp.get("cert_expired")
        state["https_probe_cert_subject"] = hp.get("cert_subject")
        state["https_probe_cert_serial"]  = hp.get("cert_serial")

    # Parse CRL content
    if fetch["data"]:
        if len(fetch["data"]) < 512 * 1024:
            state["crl_b64"] = base64.b64encode(fetch["data"]).decode("ascii")

        parsed = parse_crl(fetch["data"])
        state["parse_ok"]             = parsed["ok"]
        state["issuer"]               = parsed["issuer"]
        state["last_update"]          = parsed["last_update"]
        state["next_update"]          = parsed["next_update"]
        state["next_update_iso"]      = parsed["next_update_iso"]
        state["is_stale"]             = parsed["is_stale"]
        state["hours_until_expiry"]   = parsed["hours_until_expiry"]
        state["validity_window_days"] = parsed["validity_window_days"]
        state["revoked_count"]        = parsed["revoked_count"]
        state["revocation_reasons"]   = parsed["revocation_reasons"]
        state["_revoked_serials"]     = parsed["revoked_serials"]

        if parsed["ok"] and parsed["issuer"]:
            cert_subject = get_cert_subject(fp, pem_cache)
            if cert_subject:
                match, detail = check_issuer_match(parsed["issuer"], cert_subject)
                state["issuer_match"]        = match
                state["issuer_match_detail"] = detail

        br_ok, br_limit = assess_br_validity(
            parsed["validity_window_days"],
            parsed["revoked_count"],
            meta["br_governed"],
            cert_type=meta.get("cert_type"),
        )
        state["br_validity_ok"]         = br_ok
        state["br_validity_limit_days"] = br_limit

        # Cache-Control freshness check:
        # If max-age > validity window, intermediaries could serve a stale
        # cached CRL after nextUpdate has passed — defeating revocation.
        # If no Cache-Control at all, caching behaviour is undefined.
        vwd_secs = (parsed["validity_window_days"] or 0) * 86400
        max_age  = state.get("cache_max_age")
        if max_age is not None and vwd_secs > 0:
            state["cache_exceeds_window"] = max_age > vwd_secs
        else:
            state["cache_exceeds_window"] = None

    state["status"] = _assign_status(state)
    return state

def run(verbose=True):
    today = datetime.date.today().isoformat()
    now_iso = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")

    print("Loading CCADB...")
    records = load_ccadb()
    pem_cache = load_pem_cache()
    url_meta = build_url_meta(records)
    print(f"  {len(url_meta)} unique CRL URLs to probe")

    # Load market share for revocation rate computation
    market_share_path = OUTPUT_DIR / "market_share.json"
    _ca_unexpired: dict[str, int] = {}
    if market_share_path.exists():
        with open(market_share_path) as _f:
            for _m in json.load(_f):
                uc = _m.get("unexpired_certs") or 0
                if uc > 0:
                    _ca_unexpired[_m["ca_owner"]] = uc

    # Load previous run state and history
    prev_states = {}   # url → previous URLRecord (for transition detection)
    prev_by_fp  = {}   # cert_fp → previous URLRecord (stable across URL rotations)
    existing = load_json(OUTPUT_DIR / "crl_health.json", {})
    for entry in (existing.get("urls") or []):
        prev_states[entry["url"]] = entry
        if entry.get("cert_fp"):
            prev_by_fp[entry["cert_fp"]] = entry

    history = load_json(OUTPUT_DIR / "crl_health_history.json", {})
    events  = load_json(OUTPUT_DIR / "crl_health_events.json", [])
    # Purge artifact and legacy event types:
    # - tls_error_appeared/resolved: removed from taxonomy
    # - issuer_match_restored events dated before 2026-03-22: these were
    #   generated en masse when the issuer_mismatch false positive bug was
    #   fixed; 86 CAs had spurious issuer_mismatch then issuer_match_restored
    #   events logged on 2026-03-21. Not real CA operational changes.
    _legacy_types = {"tls_error_appeared", "tls_error_resolved"}
    def _is_artifact(e):
        if e.get("event") in _legacy_types:
            return True
        if e.get("event") == "issuer_match_restored" and e.get("date", "") < "2026-03-22":
            return True
        return False
    events[:] = [e for e in events if not _is_artifact(e)]

    results_by_url = {}   # url → state, populated as futures complete
    ok_count = fail_count = 0
    counter = [0]         # mutable container — avoids nonlocal for thread-safe counter
    counter_lock = threading.Lock()
    total = len(url_meta)

    # ── Parallel probe phase ──────────────────────────────────────────────────
    print(f"  Probing {total} URLs with {MAX_WORKERS} workers...")
    t_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_probe_url, url, meta, pem_cache, prev_states.get(url)): url
                   for url, meta in url_meta.items()}
        for future in as_completed(futures):
            url = futures[future]
            try:
                state = future.result()
            except Exception as exc:
                if verbose:
                    print(f"  ✗ [{url[:50]}] unexpected error: {exc}")
                continue

            results_by_url[url] = state

            with counter_lock:
                counter[0] += 1
                n = counter[0]

            if verbose:
                icon = "✓" if state["status"] == "ok" else "⚠" if state["status"] in ("stale", "issuer_mismatch") else "✗"
                print(f"  [{n:3d}/{total}] {icon} {state['ca_owner'][:28]:28s} {state['status']:<20} ({state['elapsed_ms']}ms)")

    elapsed_probe = time.monotonic() - t_start
    print(f"  Probing complete in {elapsed_probe:.1f}s")

    # ── Serial post-probe phase ───────────────────────────────────────────────
    # Preserve original URL ordering from url_meta for deterministic output.
    # detect_transitions and append_history are called serially — they mutate
    # shared state (events, history) and must not run concurrently.
    results = []
    for url in url_meta:
        state = results_by_url.get(url)
        if state is None:
            continue   # shouldn't happen, but defensive

        ca = state["ca_owner"]

        detect_transitions(prev_states.get(url), state, url, ca, today, events)

        append_history(history, url, today, {
            "date":                 today,
            "url_inferred":         state["url_inferred"],
            "fetch_ok":             state["fetch_ok"],
            "status_code":          state["status_code"],
            "elapsed_ms":           state["elapsed_ms"],
            "size_bytes":           state["size_bytes"],
            "crl_hash":             state["crl_hash"],
            "parse_ok":             state["parse_ok"],
            "is_stale":             state["is_stale"],
            "hours_until_expiry":   state["hours_until_expiry"],
            "next_update_iso":      state["next_update_iso"],
            "validity_window_days": state["validity_window_days"],
            "br_validity_ok":       state["br_validity_ok"],
            "revoked_count":        state["revoked_count"],
            "revocation_reasons":   state.get("revocation_reasons", {}),
            "issuer_match":         state["issuer_match"],
            "tls_info":             state["tls_info"],
            "tls_error":            state["tls_error"],
            "https_probe_exists":   state["https_probe_exists"],
            "status":               state["status"],
            "cache_max_age":        state.get("cache_max_age"),
            "cache_exceeds_window": state.get("cache_exceeds_window"),
        })

        if state["fetch_ok"]:
            ok_count += 1
        elif state["status"] != "unknown":
            fail_count += 1

        results.append(state)

    # ── Post-processing: HTTPS endpoint cert revocation cross-check ───────────
    # Build the complete set of revoked serials from all CRLs fetched this run,
    # then check each HTTPS-probe cert serial against it.
    # This detects the case where a CA's own CRL server has a revoked TLS cert
    # (e.g. Viking Cloud: https://crl.vikingcloud.com/STCA.crl cert is revoked).
    all_revoked_serials = set()
    for r in results:
        serials = r.pop("_revoked_serials", set())   # remove temp field
        all_revoked_serials.update(serials)

    if all_revoked_serials:
        for r in results:
            serial = r.get("https_probe_cert_serial")
            if serial and r.get("https_probe_exists"):
                clean = serial.upper().replace(":", "").replace(" ", "").lstrip("0") or "0"
                r["https_probe_revoked"] = clean in all_revoked_serials
                if r["https_probe_revoked"] and verbose:
                    print(f"  ⚠ HTTPS cert revoked: {r['ca_owner']} {r['url']}")

    # ── Post-processing: stamp shared CRL signals ─────────────────────────────
    # A URL is "shared" when more than one distinct CA owner files it in CCADB.
    # Cross-CA sharing (different orgs) is the most operationally interesting
    # case — it means a CA's revocation infrastructure is partly or fully
    # outsourced to another operator. Within-CA sharing (one org, many certs)
    # is common for large CAs with many intermediates pointing to the same shard.
    for r in results:
        url = r["url"]
        all_owners = url_meta[url].get("all_referencing_owners", [])
        other_owners = [o for o in all_owners if o != r["ca_owner"]]
        r["shared_crl"]      = len(all_owners) > 1
        r["shared_with_cas"] = sorted(other_owners) if other_owners else None

    # ── Build output ──────────────────────────────────────────────────────────
    status_counts = defaultdict(int)
    for r in results:
        status_counts[r["status"]] += 1

    ca_summary = defaultdict(lambda: {"total": 0, "ok": 0, "issues": []})
    for r in results:
        ca = r["ca_owner"]
        ca_summary[ca]["total"] += 1
        if r["status"] == "ok":
            ca_summary[ca]["ok"] += 1
        else:
            ca_summary[ca]["issues"].append({
                "url": r["url"], "status": r["status"], "error": r["error"],
            })

    # Counts for summary — use actual status not fetch_ok flag
    issue_urls  = [r for r in results if r["status"] != "ok"]
    issue_cas   = len(set(r["ca_owner"] for r in issue_urls))
    today_events = [e for e in events if e.get("date") == today]

    # Aggregate revocation reasons and total across all CRLs
    total_revoked = sum(r["revoked_count"] or 0 for r in results)
    # Cache-Control summary across all successfully fetched CRLs
    fetched = [r for r in results if r.get("fetch_ok")]
    cache_no_cc          = sum(1 for r in fetched if r.get("cache_control") is None)
    cache_exceeds_count  = sum(1 for r in fetched if r.get("cache_exceeds_window") is True)
    cache_ok_count       = sum(1 for r in fetched if r.get("cache_exceeds_window") is False)
    # Revocations per day: total revoked / sum of all CRL validity windows
    # Gives a sense of revocation velocity across the ecosystem
    total_window_days = sum(
        r["validity_window_days"] for r in results
        if r.get("validity_window_days") and r.get("revoked_count") is not None
    )
    revocations_per_day = round(total_revoked / total_window_days, 2)                           if total_window_days > 0 else None
    agg_reasons: dict = {}
    unknown_revoked = sum(1 for r in results if r.get("revoked_count") is None)
    for r in results:
        for reason, n in (r.get("revocation_reasons") or {}).items():
            agg_reasons[reason] = agg_reasons.get(reason, 0) + n

    # Revocation rate: revoked / unexpired certs from market share.
    # Only meaningful aggregated globally, and per-CA only when CRL scope
    # covers end-entity certs (revoked_count > 100 is a reasonable proxy).
    # Root ARLs covering sub-CAs have tiny revoked counts; their denominator
    # (unexpired leaf certs) is the wrong population entirely.
    _ca_revoked: dict[str, int] = {}
    for r in results:
        if r.get("revoked_count") is not None:
            ca = r["ca_owner"]
            _ca_revoked[ca] = _ca_revoked.get(ca, 0) + (r["revoked_count"] or 0)

    # Global rate: only include CAs where we have both revoked and unexpired data
    _global_rev = sum(_ca_revoked.get(ca, 0) for ca in _ca_unexpired if ca in _ca_revoked)
    _global_unexp = sum(_ca_unexpired[ca] for ca in _ca_unexpired if ca in _ca_revoked)
    global_revocation_ppm = round(_global_rev / _global_unexp * 1_000_000, 3)                             if _global_unexp > 0 else None

    # Per-CA rate — only for CAs likely issuing end-entity certs (revoked > 100)
    per_ca_rates = []
    for ca, revoked in sorted(_ca_revoked.items(), key=lambda x: -x[1]):
        unexpired = _ca_unexpired.get(ca, 0)
        if unexpired > 0 and revoked > 100:
            per_ca_rates.append({
                "ca":      ca,
                "revoked": revoked,
                "unexpired_certs": unexpired,
                "ppm":     round(revoked / unexpired * 1_000_000, 3),
            })

    # Stamp per-URL revocation_rate_ppm onto each result
    for r in results:
        ca = r["ca_owner"]
        unexpired = _ca_unexpired.get(ca, 0)
        revoked = r.get("revoked_count") or 0
        if unexpired > 0 and revoked > 0:
            r["revocation_rate_ppm"] = round(revoked / unexpired * 1_000_000, 3)
        else:
            r["revocation_rate_ppm"] = None

    # ── Shared CRL summary ────────────────────────────────────────────────────
    # Aggregate the cross-CA sharing picture for the UI.
    # cross_ca_shared: URLs where 2+ distinct CA orgs point to the same endpoint.
    # within_ca_shared: URLs where one CA has multiple certs sharing an endpoint.
    cross_ca_urls  = [r for r in results if r.get("shared_with_cas")]
    within_ca_urls = [r for r in results
                      if r["shared_crl"] and not r.get("shared_with_cas")
                      and len(url_meta[r["url"]].get("all_referencing_owners", [])) > 1]

    # Per-CA: how many of their CRL URLs are cross-CA shared?
    from urllib.parse import urlparse as _urlparse
    ca_cross_shared: dict[str, set] = defaultdict(set)
    for r in cross_ca_urls:
        ca_cross_shared[r["ca_owner"]].add(r["url"])

    # Hosting domain breakdown: which domains are used most for CRL hosting?
    domain_url_counts: dict[str, int] = defaultdict(int)
    for url in url_meta:
        try:
            domain_url_counts[_urlparse(url).netloc] += 1
        except Exception:
            pass

    shared_crl_summary = {
        "total_urls":              len(results),
        "shared_urls":             sum(1 for r in results if r["shared_crl"]),
        "cross_ca_shared_urls":    len(cross_ca_urls),
        "within_ca_shared_urls":   len(within_ca_urls),
        "cas_with_cross_shared":   len(ca_cross_shared),
        "top_hosting_domains": [
            {"domain": d, "url_count": c}
            for d, c in sorted(domain_url_counts.items(), key=lambda x: -x[1])[:20]
        ],
        "cross_ca_sharing": [
            {
                "ca_owner":    ca,
                "shared_url_count": len(urls),
                "shared_urls": sorted(urls),
            }
            for ca, urls in sorted(ca_cross_shared.items(), key=lambda x: -len(x[1]))
        ],
    }

    output = {
        "generated_at": now_iso,
        "summary": {
            "total_urls":      len(results),
            "status_counts":   dict(status_counts),
            "ok_count":        sum(1 for r in results if r["status"] == "ok"),
            "issue_count":     len(issue_urls),   # all non-ok statuses
            "fail_count":      len(issue_urls),   # backward compat alias
            "ca_count":        len(ca_summary),
            "cas_with_issues": issue_cas,
            "changes_today":   len(today_events),
            "total_revoked":   total_revoked,
            "revocation_reasons": dict(sorted(agg_reasons.items(), key=lambda x: -x[1])),
            "urls_unknown_revoked": unknown_revoked,
            "cache_no_cc":          cache_no_cc,
            "cache_exceeds_count":  cache_exceeds_count,
            "cache_ok_count":       cache_ok_count,
            "global_revocation_ppm": global_revocation_ppm,
            "revocations_per_day": revocations_per_day,
            "per_ca_revocation_rates": per_ca_rates,
        },
        "shared_crl_summary": shared_crl_summary,
        "ca_summary": [
            {"ca_owner": ca, "total_urls": v["total"],
             "ok_urls": v["ok"], "issues": v["issues"]}
            for ca, v in sorted(ca_summary.items())
        ],
        "urls": results,
    }

    save_json(OUTPUT_DIR / "crl_health.json",         output)
    save_json(OUTPUT_DIR / "crl_health_history.json", history)
    save_json(OUTPUT_DIR / "crl_health_events.json",  events)

    print(f"\nDone: {ok_count} ok, {fail_count} failed, {len(url_meta)} total")
    print(f"  Status: {dict(status_counts)}")
    print(f"  Events: {len(events)}  History entries: {sum(len(v) for v in history.values())}")

    return output


def _assign_status(state):
    """
    Determine final status for a URL record.

    Single status per URL — everything participates in filtering and aggregation.
    Priority (first match wins — most severe to least):

      Fetch failures:
        invalid_url             — URL structurally unfetchable
        dns_error               — hostname doesn't resolve
        connection_error        — server unreachable / timed out
        http_NNN                — HTTP error response (404, 403, 500, etc.)

      TLS failures on HTTPS-filed URLs:
        tls_hostname_mismatch   — cert doesn't cover this hostname
        tls_cert_expired        — TLS cert is expired

      CRL content failures:
        parse_failed            — bytes received but not a valid CRL
        stale                   — CRL nextUpdate is in the past
        issuer_mismatch         — wrong CRL filed in CCADB

      HTTPS endpoint issues on HTTP-filed URLs (probed separately):
        https_cert_revoked      — HTTPS cert serial found on a CRL we fetched
        https_cert_expired      — HTTPS endpoint cert is expired
        https_hostname_mismatch — HTTPS hostname mismatch

      Compliance:
        br_violation            — CRL validity window exceeds BR §4.9.7 limit
                                  (only for BR-governed CAs)

      Data quality:
        url_inferred            — scheme was guessed (http:// prepended)
                                  CRL may be fine but CCADB record is wrong

      ok                        — all clear
    """
    ec = state.get("error_class") or ""
    tls_err = state.get("tls_error")

    # Fetch failures
    if ec == "invalid_url":
        return "invalid_url"
    if not state.get("fetch_ok"):
        return ec if ec else "connection_error"  # should not happen; error_class always set

    # TLS errors on HTTPS endpoints (only genuine URL/cert errors)
    if tls_err:
        return f"tls_{tls_err}"

    # CRL content failures
    if state.get("parse_ok") is False:
        return "parse_failed"
    if state.get("is_stale"):
        return "stale"
    if state.get("issuer_match") is False:
        return "issuer_mismatch"

    # HTTPS endpoint probe issues (HTTP-filed URLs)
    # Note: https_hostname_mismatch is NOT flagged as an error status.
    # Most HTTP-filed CRL servers use CDN infrastructure where port 443
    # serves a wildcard CDN cert — this is expected, not a CA problem.
    # The probe data is stored for informational purposes only.
    if state.get("https_probe_revoked"):
        return "https_cert_revoked"
    if state.get("https_probe_expired"):
        return "https_cert_expired"

    # BR compliance (only for BR-governed CAs)
    if state.get("br_validity_ok") is False:
        return "br_violation"

    # Data quality — CRL works but CCADB record has issues
    if state.get("url_inferred"):
        return "url_inferred"

    return "ok"


if __name__ == "__main__":
    run(verbose=True)
