"""Operation-error taxonomy for the V-Scanner 3.0 engine.

Implements DATA_MODELS §8. Every operation error carries a human-readable
``message`` plus a machine-readable ``details`` mapping (values are strings —
safe to log or render without formatting quirks). Services never turn a
failure into a fabricated success: they raise, and callers translate.

Subprocess fail-safety: ``AdbCommandError`` carries at most 1 KB of stderr,
redaction-applied, and a ``timeout`` flag so UIs can distinguish a hung
command from a fast failure (R-07 groundwork: redaction happens at the error
boundary, before anything reaches logs or events).
"""

from __future__ import annotations

from typing import Mapping, Optional, Union

from vscanner.core.redact import redact_text

__all__ = [
    "VScannerError",
    "AdbNotAvailable",
    "DeviceNotConnected",
    "DeviceUnauthorized",
    "AdbCommandError",
    "ScanInterrupted",
    "JobCancelRequested",
    "JobCancelled",
    "JobConflictError",
    "ConfirmationRequired",
    "ConfirmationInvalid",
    "ConfigError",
    "ConfigSchemaOutdated",
    "InputValidationError",
    "ProvisioningError",
    "ToolNotValidated",
    "ExportError",
    "ForensicsError",
    "DeepScanUnavailable",
]

# Optional scalar detail values; dataclasses.coerce strings on input.
_DETAIL_VALUE = Union[int, float, bool, str, None]


def _coerce_details(details: Optional[Mapping[str, _DETAIL_VALUE]]) -> dict:
    """Normalize error detail values to plain strings."""
    if not details:
        return {}
    return {key: "" if value is None else str(value) for key, value in details.items()}


class VScannerError(Exception):
    """Base class for every domain error raised by engine services.

    Never raised directly; never used to smuggle fabricated findings.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Mapping[str, _DETAIL_VALUE]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict = _coerce_details(details)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}(message={self.message!r}, details={self.details!r})"


class AdbNotAvailable(VScannerError):
    """No ADB binary is launchable (missing, not on PATH, or probe failed)."""


class DeviceNotConnected(VScannerError):
    """The requested device is not in the actionable device set."""

    def __init__(self, serial: Optional[str] = None, message: Optional[str] = None) -> None:
        super().__init__(
            message or f"Device not connected: {serial or '<no serial>'}",
            {"serial": serial},
        )


class DeviceUnauthorized(VScannerError):
    """Device present but in UNAUTHORIZED state — on-device approval needed."""

    def __init__(self, serial: Optional[str] = None, message: Optional[str] = None) -> None:
        super().__init__(
            message or f"Device {serial or ''} is unauthorized: approve the debugging prompt on the device",
            {"serial": serial},
        )


class AdbCommandError(VScannerError):
    """A granted ADB command failed, timed out, or produced unusable output.

    ``stderr_excerpt`` is capped at 1 KiB and redaction-applied at
    construction; ``timeout=True`` distinguishes hung commands.
    """

    STDERR_EXCERPT_LIMIT = 1024

    def __init__(
        self,
        message: Optional[str] = None,
        cmd: tuple = (),
        returncode: Optional[int] = None,
        stderr_excerpt: str = "",
        timeout: bool = False,
    ) -> None:
        super().__init__(
            message or ("command timed out" if timeout else "command failed"),
            {
                "cmd": " ".join(cmd),
                "returncode": returncode,
                "timeout": timeout,
            },
        )
        self.cmd: tuple = tuple(cmd)
        self.returncode = returncode
        self.timeout = timeout
        self.stderr_excerpt = redact_text(stderr_excerpt[: self.STDERR_EXCERPT_LIMIT])


class ScanInterrupted(VScannerError):
    """A scan failed mid-flight; ``partial`` says whether a partial result exists."""

    def __init__(self, message: str, details: Optional[Mapping[str, _DETAIL_VALUE]] = None,
                 partial: bool = False) -> None:
        merged = _coerce_details(details)
        merged["partial"] = partial
        super().__init__(message, merged)
        self.partial = partial


class JobCancelRequested(VScannerError):
    """Stage 04 boundary: a cooperative cancellation was requested."""


class JobCancelled(VScannerError):
    """Stage 04 boundary: the cancellation was accepted and applied."""


class JobConflictError(VScannerError):
    """Stage 04 boundary: an operation is already running for the same target."""


class ConfirmationRequired(VScannerError):
    """A device-mutating operation was refused for lack of a confirmation token."""


class ConfirmationInvalid(VScannerError):
    """The supplied confirmation token is wrong, stale, or belongs elsewhere."""


class ConfigError(VScannerError):
    """Configuration file missing, unreadable, malformed, or invalid."""


class ConfigSchemaOutdated(ConfigError):
    """Config file declares an unknown or too-old schema_version."""


class InputValidationError(VScannerError):
    """Arguments failed pre-flight validation (never reaches a subprocess)."""


class ProvisioningError(VScannerError):
    """Tool download/checksum/extraction failed; no partially-installed tool remains.

    ``cleanup_done`` reflects that the temp archive and staging tree were
    removed before this error was raised (R-11).
    """

    def __init__(self, message: str, details: Optional[Mapping[str, _DETAIL_VALUE]] = None,
                 cleanup_done: bool = False) -> None:
        merged = _coerce_details(details)
        merged["cleanup_done"] = cleanup_done
        super().__init__(message, merged)
        self.cleanup_done = cleanup_done


class ToolNotValidated(VScannerError):
    """A tool exists but failed its launch-probe (not safe to rely on)."""


class ExportError(VScannerError):
    """Report export failed (filesystem, template, or encoding)."""


class ForensicsError(VScannerError):
    """A forensics operation could not be completed honestly.

    Used for case-store problems, unsafe extraction paths (e.g. a source
    path that would break out of its quoting context — R-12 hardening), and
    manifest-write failures. The operation's partial state is always recorded
    in the case manifest ``extractions`` log; this error never implies a
    fabricated success.
    """

    def __init__(self, message: str, details: Optional[Mapping[str, _DETAIL_VALUE]] = None,
                 operation: str = "") -> None:
        merged = _coerce_details(details)
        merged["operation"] = operation
        super().__init__(message, merged)


class DeepScanUnavailable(VScannerError):
    """R-06 support error: the deep-scan APK byte stream is unavailable.

    Raised by the deep-scan stage when the APK cannot be fetched (missing
    path, transport failure); the scanner translates this into an honest
    ``UNVERIFIED_CONDITION`` finding — never a silently empty result.
    """
