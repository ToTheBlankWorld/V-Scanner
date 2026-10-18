"""Host-side deep scan — APK string extraction + pattern execution (Stage 08).

SC-3 remediation (deep-scan reliability) + R-06 (secret-pattern execution):

Legacy deep scan ran ``shell cat base.apk | strings | grep -oE 'https?://…'``
on-device. That depended on a ``strings`` binary being present on the device
(the documented SC-3 on-device dependency), and the credential-class
regexes in ``vscanner.core.kb.permissions`` were *never executed anywhere*
(R-06 defect: patterns existed in source, creating a false sense of
coverage, but were dead).

Stage 08 replaces this with a byte-safe host-side stage:

1. resolve the APK path via ``pm path`` (text);
2. stream the APK with the R-07 ``run_bytes`` foundation (``adb exec-out``,
   binary-verified) — **no text-mode subprocess ever touches the payload**;
3. extract printable strings locally (stdlib, ``strings``-compatible
   ASCII runs ≥ 4);
4. execute the documented INSECURE_URL_PATTERNS against the extracted text
   (URL logic keeps legacy semantics: http:// + non-local ⇒ insecure,
   ≤ 20 unique; test-domain references reported at INFO);
5. credential-class matches become ``HARDCODED_SECRET`` findings whose
   detail/evidence carry only a *redacted* key presentation — the raw
   matched secret value never enters description, evidence, logs, events,
   or exports (R-06/R-12 boundary).

Failures are honest: an unresolvable APK path, an empty byte stream, or a
transport error raises :class:`~vscanner.core.errors.DeepScanUnavailable`;
the scanner turns that into an ``UNVERIFIED_CONDITION`` finding — never a
silently empty result. A *completed* extraction with zero matches is a
legitimate zero (documented in the result, distinct from the failure path).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple

from vscanner.core.errors import DeepScanUnavailable
from vscanner.core.kb.permissions import INSECURE_URL_PATTERNS
from vscanner.core.models import (
    AppInfo,
    Evidence,
    EvidenceKind,
    Finding,
    FindingCategory,
    FindingSeverity,
    make_finding,
)

__all__ = ["DeepScanService", "DeepScanResult", "extract_printable_strings",
           "find_insecure_urls", "find_credential_matches", "redact_secret_snippet"]

_MIN_PRINTABLE_RUN = 4          # toybox ``strings`` default
_MAX_URLS = 20                  # legacy parity: 20 unique URLs
_MAX_STRING_CHARS = 1_000_000   # bound regex cost on huge APKs
_MAX_SECRET_FINDINGS = 10       # per-app budget for credential findings
_APK_TIMEOUT = 120.0            # large APKs over USB

# Host-side bytes transport: byte-safe exec-out (R-07 foundation).
class _BytesTransport(Protocol):
    def run_text(self, cmd, timeout: float = 30.0):  # pragma: no cover
        ...

    def run_bytes(self, cmd, timeout: float = 30.0) -> bytes:  # pragma: no cover
        ...


# Pattern indices in the documented INSECURE_URL_PATTERNS bundle.
_URL_PATTERN_INDEX = 0      # cleartext external http:// URLs
_TESTDOMAIN_PATTERN_INDEX = 1  # example/test/localhost domain references
_CREDENTIAL_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("api_key", re.compile(INSECURE_URL_PATTERNS[2], re.IGNORECASE)),
    ("password", re.compile(INSECURE_URL_PATTERNS[3], re.IGNORECASE)),
    ("secret", re.compile(INSECURE_URL_PATTERNS[4], re.IGNORECASE)),
    ("token", re.compile(INSECURE_URL_PATTERNS[5], re.IGNORECASE)),
    ("aws_key", re.compile(INSECURE_URL_PATTERNS[6], re.IGNORECASE)),
    ("firebase", re.compile(INSECURE_URL_PATTERNS[7], re.IGNORECASE)),
)

# Legacy URL semantics: cleartext http:// to non-local hosts.
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_LOCAL_SAFE = ("localhost", "127.0.0.1", "10.", "192.168.")


@dataclass(frozen=True, slots=True)
class CredentialHit:
    """One credential-pattern match. ``snippet`` is always the REDACTED
    presentation; the raw match is intentionally not stored anywhere."""

    pattern_name: str
    snippet: str        # redacted key/length presentation (never the value)
    value_len: int      # length of the matched value, for honesty about size


@dataclass(frozen=True, slots=True)
class DeepScanResult:
    """Completed deep-scan analysis of one APK. Empty tuples mean a genuine
    zero-hit extraction (distinct from the DeepScanUnavailable failure
    path, which raises instead)."""

    apk_path: str
    string_count: int
    urls: Tuple[str, ...] = ()
    credentials: Tuple[CredentialHit, ...] = ()
    test_domain_refs: Tuple[str, ...] = ()


def extract_printable_strings(data: bytes, min_run: int = _MIN_PRINTABLE_RUN) -> str:
    """``strings``-compatible printable-ASCII extraction (host-side).

    Runs of printable ASCII (0x20–0x7E) shorter than ``min_run`` are
    dropped; runs are joined with newlines. Binary payloads (NUL bytes,
    invalid UTF-8, embedded executables) never cause decode errors — bytes
    are filtered, never text-decoded.
    """
    runs: list[str] = []
    start = None
    append = runs.append
    data_len = len(data)
    limit = data_len
    for idx in range(limit):
        byte = data[idx]
        if 0x20 <= byte <= 0x7E:
            if start is None:
                start = idx
        else:
            if start is not None:
                run = data[start:idx]
                if len(run) >= min_run:
                    append(run.decode("ascii"))
                start = None
    if start is not None and (limit - start) >= min_run:
        append(data[start:limit].decode("ascii"))
    text = "\n".join(runs)
    if len(text) > _MAX_STRING_CHARS:
        text = text[:_MAX_STRING_CHARS]
    return text


def find_insecure_urls(strings_text: str) -> Tuple[str, ...]:
    """Legacy URL semantics over extracted strings (≤ 20 unique, order
    preserved by first occurrence)."""
    seen: dict[str, None] = {}
    for match in _URL_RE.findall(strings_text):
        url = match.strip().strip("()[]{}<>,;:'\"")
        if not url.startswith("http://"):
            continue
        if any(safe in url for safe in _LOCAL_SAFE):
            continue
        seen.setdefault(url, None)
        if len(seen) >= _MAX_URLS:
            break
    return tuple(seen)


def redact_secret_snippet(match_text: str, pattern_name: str) -> CredentialHit:
    """Build the honest redacted presentation of a credential match.

    Never emits the matched value in any field: quoted-value matches keep
    the key LHS (capped at 24 chars) plus the value *length* only; bare
    key-identifier matches (e.g. ``aws_secret_key`` with no '=' value) are
    shown as-is because they contain no secret value by construction.
    """
    quoted = re.match(
        r"(?i)^(?P<key>[A-Za-z0-9_.\- ]{1,24}[=:])\s*[\"']?(?P<val>[^\"']+)",
        match_text,
    )
    if quoted:
        key = quoted.group("key").strip()
        key_shown = key[:24] + ("…" if len(key) > 24 else "")
        value_len = len(quoted.group("val"))
        return CredentialHit(
            pattern_name=pattern_name,
            snippet=f'{key_shown} <redacted, value length {value_len}>',
            value_len=value_len,
        )
    # Bare identifier (aws/firebase naming patterns match the key name only)
    shown = match_text.strip()[:24]
    return CredentialHit(
        pattern_name=pattern_name,
        snippet=f"{shown} <credential identifier matched; no embedded value>",
        value_len=0,
    )


def find_credential_matches(strings_text: str) -> Tuple[CredentialHit, ...]:
    """Execute the documented credential-class regexes (R-06) over the
    extracted strings; each hit is returned REDACTED (the raw match is
    consumed by :func:`redact_secret_snippet` and never stored)."""
    hits: list[CredentialHit] = []
    seen_snippets: set[str] = set()
    for name, pattern in _CREDENTIAL_PATTERNS:
        for match in pattern.finditer(strings_text):
            hit = redact_secret_snippet(match.group(0), name)
            if hit.snippet in seen_snippets:
                continue
            seen_snippets.add(hit.snippet)
            hits.append(hit)
            if len(hits) >= _MAX_SECRET_FINDINGS:
                return tuple(hits)
    return tuple(hits)


def find_test_domain_urls(strings_text: str) -> Tuple[str, ...]:
    """Documented pattern index 1: example/test/localhost domain refs."""
    pattern = re.compile(INSECURE_URL_PATTERNS[_TESTDOMAIN_PATTERN_INDEX], re.IGNORECASE)
    seen: dict[str, None] = {}
    for match in pattern.finditer(strings_text):
        text = match.group(0).strip()
        seen.setdefault(text, None)
        if len(seen) >= _MAX_URLS:
            break
    return tuple(seen)


class DeepScanService:
    """R-06 deep-scan stage over one byte-safe transport (SC-3 remediation)."""

    def __init__(self, transport: _BytesTransport,
                 apk_timeout: float = _APK_TIMEOUT) -> None:
        self._transport = transport
        self._apk_timeout = apk_timeout

    def scan(self, package: str) -> DeepScanResult:
        """Analyze the installed APK; raises DeepScanUnavailable on any
        failure path (never returns fabricated emptiness)."""
        apk_path = self._resolve_apk_path(package)
        raw = self._fetch_apk_bytes(apk_path)
        strings_text = extract_printable_strings(raw)
        return DeepScanResult(
            apk_path=apk_path,
            string_count=len(strings_text.splitlines()),
            urls=find_insecure_urls(strings_text),
            credentials=find_credential_matches(strings_text),
            test_domain_refs=find_test_domain_urls(strings_text),
        )

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _resolve_apk_path(self, package: str) -> str:
        try:
            result = self._transport.run_text(
                ("shell", "pm", "path", package), timeout=15.0)
        except Exception as exc:
            raise DeepScanUnavailable(
                f"APK path lookup failed for {package}: {type(exc).__name__}",
                {"package": package},
            ) from exc
        # transport shape varies (AdbResult from the engine client, raw
        # string from lightweight fakes) — unwrap the stdout field first
        stdout = getattr(result, "stdout", result) or ""
        paths = [
            line.strip().removeprefix("package:").strip()
            for line in stdout.splitlines()
            if line.strip().startswith("package:")
        ]
        if not paths:
            raise DeepScanUnavailable(
                f"no APK path reported for {package} (pm path produced no "
                "'package:' lines)",
                {"package": package},
            )
        # Prefer base.apk; splits are acceptable fallbacks.
        for path in paths:
            if "base.apk" in path:
                return path
        return paths[0]

    def _fetch_apk_bytes(self, apk_path: str) -> bytes:
        """Byte-safe APK fetch via ``exec-out`` (R-07 foundation: raw bytes
        in, raw bytes out; no text-mode subprocess ever sees the payload)."""
        if "'" in apk_path or ";" in apk_path or "$" in apk_path:
            raise DeepScanUnavailable(
                "APK path contains characters that are unsafe for the "
                "device-side command (refusing extraction)",
                {"apk_path_present": True},
            )
        try:
            data = self._transport.run_bytes(
                ("exec-out", "cat", f"'{apk_path}'"), timeout=self._apk_timeout)
        except Exception as exc:
            raise DeepScanUnavailable(
                f"APK byte fetch failed: {type(exc).__name__}",
                {"apk_path_present": True},
            ) from exc
        if not data:
            raise DeepScanUnavailable(
                "APK byte fetch produced an empty stream (read-only source "
                "or transport returned nothing)",
            )
        return data


# --------------------------------------------------------------------------- #
# scanner-facing finding construction
# --------------------------------------------------------------------------- #

def deep_scan_findings(
    app: AppInfo,
    serial: Optional[str],
    result: DeepScanResult,
) -> Tuple[Finding, ...]:
    """Translate a completed :class:`DeepScanResult` into findings.

    * cleartext external URLs → ``INSECURE_URL`` / MEDIUM
      (the legacy displayed list, now a typed CONFIRMED_ARTIFACT finding);
    * test-domain references → ``INSECURE_URL`` / INFO;
    * credential-class matches → ``HARDCODED_SECRET`` / HIGH with
      *redacted* presentations only.
    A completed zero-hit result legitimately contributes no findings.
    """
    findings: list[Finding] = []
    source = f"exec-out cat '{result.apk_path}' | host-side strings extraction"

    if result.urls:
        listed = ", ".join(result.urls[:5])
        more = f" (+{len(result.urls) - 5} more)" if len(result.urls) > 5 else ""
        findings.append(make_finding(
            kind=FindingCategory.INSECURE_URL,
            severity=FindingSeverity.MEDIUM,
            title="Cleartext external URLs in APK strings",
            detail=(
                f"{len(result.urls)} cleartext http:// URL(s) to non-local "
                f"hosts were found in the APK's extracted strings; first: "
                f"{listed}{more}."
            ),
            evidence=(
                Evidence.of(
                    EvidenceKind.CONFIRMED_ARTIFACT,
                    description=f"cleartext external URL(s) found: {listed}{more}",
                    source=source,
                ),
            ),
            app=app,
            device_serial=serial,
        ))

    if result.test_domain_refs:
        listed = result.test_domain_refs[0]
        findings.append(make_finding(
            kind=FindingCategory.INSECURE_URL,
            severity=FindingSeverity.INFO,
            title="Test-domain URL referenced in APK strings",
            detail=(
                f"{len(result.test_domain_refs)} reference(s) to "
                f"example/test/localhost domains found in extracted "
                f"strings (documented pattern); first: {listed}. "
                f"Usually non-production, but verify honestly."
            ),
            evidence=(
                Evidence.of(
                    EvidenceKind.HEURISTIC_PATTERN,
                    description=f"test-domain reference: {listed}",
                    source=source,
                ),
            ),
            app=app,
            device_serial=serial,
        ))

    if result.credentials:
        by_kind: dict[str, list[CredentialHit]] = {}
        for hit in result.credentials:
            by_kind.setdefault(hit.pattern_name, []).append(hit)
        for pattern_name, hits in sorted(by_kind.items()):
            first = hits[0]
            findings.append(make_finding(
                kind=FindingCategory.HARDCODED_SECRET,
                severity=FindingSeverity.HIGH,
                title=f"Hardcoded {pattern_name} pattern in APK strings",
                detail=(
                    f"{len(hits)} match(es) of the documented "
                    f"{pattern_name} pattern in the APK's extracted "
                    f"strings. Matched value redacted: {first.snippet}. "
                    f"Static pattern evidence only — not verified "
                    f"exploitation."
                ),
                evidence=(
                    Evidence.of(
                        EvidenceKind.CONFIRMED_ARTIFACT,
                        description=(
                            f"{pattern_name} credential pattern matched "
                            f"(value withheld; length {first.value_len})"
                        ),
                        source=source,
                    ),
                ),
                app=app,
                device_serial=serial,
            ))
    return tuple(findings)
