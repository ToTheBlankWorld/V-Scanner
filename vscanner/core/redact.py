"""Redaction engine (Stage 03 groundwork for R-12).

``redact_text`` is applied at trust boundaries where untrusted device output
could otherwise leak credentials into errors, evidence excerpts or logs:

* WiFi pre-shared keys (``psk=`` / ``preshared_key=``)
* bearer-style keys/secrets/tokens/passwords (``keyword=value`` or
  ``keyword: value`` forms, optionally quoted)
* IMEI/IMSI/MEID digit runs introduced by their standard labels
* phone-number-like digit sequences (10–15 digits, separators tolerated)

``RedactionPreset`` keeps the preset concept from DATA_MODELS §10; Stage 03
always uses LOGCONSOLE semantics (the safe default). FULL exists only as the
explicit-export concept and is deliberately not wired to an unredacted path
in the engine yet.

Functions are pure and deterministic — same input, same output, no runtime
variance — so redaction inside error paths stays reproducible in tests.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

__all__ = ["RedactionPreset", "REDACTED_MARKER", "redact_text", "redact_excerpt"]

REDACTED_MARKER = "<redacted>"


class RedactionPreset(Enum):
    """Redaction strength presets (DATA_MODELS §10)."""

    LOGCONSOLE = 0  # safe default: mask credentials, device identifiers, phone numbers
    FULL = 1        # unredacted export — requires explicit user action at the boundary


# keyword = "secret"  |  keyword=secret  |  keyword: secret
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(psk|preshared|preshared_key|password|passwd|api[_-]?key|secret|token|authorization)\b"
    r"(\s*[:=]\s*)(['\"]?)[^\s'\"]+(\3)"
)

# labeled device identifiers:  imei 867123456789012, IMSI=123456..., MEID a1b2...
_LABELED_DEVICE_ID = re.compile(
    r"(?i)\b(imei|imsi|meid)\b([\s:=#]{1,6})([0-9][0-9 \-\.]{7,24}[0-9a-fA-F])"
)

# phone-number-like sequences: 10–15 digits with optional separators
_PHONE_LIKE = re.compile(
    r"(?<![\w])\+?[0-9][0-9 \-\.]{8,14}[0-9](?![\w])"
)


def redact_text(text: Optional[str], preset: RedactionPreset = RedactionPreset.LOGCONSOLE) -> str:
    """Return ``text`` with password/credential/identifier material masked.

    ``FULL`` returns the input unchanged; every other preset applies the same
    LOGCONSOLE rule set. Storage of unredacted text is a Stage 04+ concern
    gated behind explicit user action (SECURITY_AND_REMEDIATION_PLAN R-12).
    """
    if not text:
        return ""
    if preset is RedactionPreset.FULL:
        return text

    redacted = _SECRET_ASSIGNMENT.sub(r"\1\2" + REDACTED_MARKER, text)
    redacted = _LABELED_DEVICE_ID.sub(r"\1\2" + REDACTED_MARKER, redacted)
    redacted = _PHONE_LIKE.sub(REDACTED_MARKER, redacted)
    return redacted


def redact_excerpt(text: Optional[str], max_len: int = 2048) -> str:
    """Cap ``text`` at ``max_len`` characters and redaction-apply it.

    The single shape every ``Evidence.raw_excerpt`` insertion and error
    excerpt uses: bounded size + LOGCONSOLE redaction in one call.
    """
    if not text:
        return ""
    return redact_text(text[:max_len])
