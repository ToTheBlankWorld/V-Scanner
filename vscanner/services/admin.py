"""SC-5 AdministrationService — destructive-capable one-shot admin ops
(Stage 08 port of the legacy ``uninstall_app``/``open_app``/
``force_stop_app`` paths).

R-13 service-side gate: EVERY destructive-capable operation requires a
validated :class:`~vscanner.core.events.OperationConfirmation`. No
confirmation → :class:`~vscanner.core.errors.ConfirmationRequired`.
Stale (older than ``_CONFIRMATION_TTL``, checked against clock-skew
tolerance) or malformed → :class:`ConfirmationInvalid`. This is the seam
the acceptance criterion calls out — "destructive flows all gated through
OperationConfirmation service-side even when reached via legacy shim".

Results are honest typed :class:`~vscanner.core.models.OperationResult`
values (rc + message), never interpreted booleans, and the types of failure
(reason = not-installed vs ADB error) are passed through unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol

from vscanner.core.errors import (
    ConfirmationInvalid,
    ConfirmationRequired,
    InputValidationError,
)
from vscanner.core.events import OperationConfirmation
from vscanner.core.models import OperationResult

__all__ = ["AdministrationService", "CONFIRMATION_TTL_SECONDS"]

CONFIRMATION_TTL_SECONDS = 120.0

_PACKAGE_RE_NOTE = "validation via vscanner.services.scanning.scanner.validate_package_name"


class _AdminTransport(Protocol):
    def run_text(self, cmd, timeout: float = 30.0):
        ...


def validate_confirmation(
    confirmation: Optional[OperationConfirmation],
    action_ref: str,
) -> OperationConfirmation:
    """Shared SC-5 confirmation gate (validation only — no monkey business).

    Raises ``ConfirmationRequired`` when nothing was supplied and
    ``ConfirmationInvalid`` when the token is malformed or older than the
    TTL (with a small clock-tolerance window; naive timestamps are refused —
    DATA_MODELS §10).
    """
    if confirmation is None:
        raise ConfirmationRequired(
            "destructive-capable operation requires an explicit "
            "OperationConfirmation",
            {"action_ref": action_ref},
        )
    if not isinstance(confirmation.reference, str) or not confirmation.reference.strip():
        raise ConfirmationInvalid(
            "confirmation reference must be a non-empty string",
            {"action_ref": action_ref},
        )
    confirmed_at = confirmation.confirmed_at
    if not isinstance(confirmed_at, datetime):
        raise ConfirmationInvalid(
            "confirmation timestamp must be a datetime",
            {"action_ref": action_ref},
        )
    if confirmed_at.tzinfo is None:
        raise ConfirmationInvalid(
            "confirmation timestamp must be timezone-aware",
            {"action_ref": action_ref},
        )
    now = datetime.now(timezone.utc)
    age = (now - confirmed_at.astimezone(timezone.utc)).total_seconds()
    if age > CONFIRMATION_TTL_SECONDS + 5.0:  # 5s transport clock tolerance
        raise ConfirmationInvalid(
            "confirmation is stale (older than the TTL); re-confirm",
            {"action_ref": action_ref, "age_seconds": int(age)},
        )
    return confirmation


class AdministrationService:
    """SC-5 admin operations over one serial-bound ADB transport."""

    def __init__(self, transport: _AdminTransport) -> None:
        self._transport = transport

    def uninstall_app(
        self, package: str, confirmation: Optional[OperationConfirmation],
    ) -> OperationResult:
        """Legacy parity command shape (``adb uninstall <pkg>``), gated."""
        name = self._validate(package)
        validate_confirmation(confirmation, f"uninstall:{name}")
        result = self._transport.run_text(["uninstall", name], timeout=60.0)
        rc = getattr(result, "returncode", 1)
        # adb uninstall prints "Success" or an explanation ("Failure ...")
        out = (getattr(result, "stdout", "") or "").strip()
        msg = out or "uninstall completed (device returned no text)"
        return OperationResult(ok=False if rc != 0 else True,
                               adb_returncode=rc, message=msg)

    def launch_app(
        self, package: str, confirmation: Optional[OperationConfirmation],
    ) -> OperationResult:
        """Legacy parity two-step launch: query the launcher activity, then
        ``am start -n pkg/activity``."""
        name = self._validate(package)
        validate_confirmation(confirmation, f"launch:{name}")
        qa = self._transport.run_text([
            "shell", "cmd", "package", "query-activities", "--brief",
            "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER", name,
        ], timeout=30.0)
        qa_out = (getattr(qa, "stdout", "") or "")
        qa_rc = getattr(qa, "returncode", 1)
        activity = self._extract_activity(qa_out)
        if qa_rc != 0 or not activity:
            return OperationResult(
                ok=False, adb_returncode=qa_rc,
                message="no launcher activity found for package "
                        f"{name} (query-activities rc={qa_rc})",
            )
        start = self._transport.run_text(
            ["shell", "am", "start", "-n", f"{name}/{activity}"], timeout=30.0)
        rc = getattr(start, "returncode", 1)
        out = (getattr(start, "stdout", "") or "").strip()
        return OperationResult(ok=False if rc != 0 else True,
                               adb_returncode=rc,
                               message=out or f"am start rc={rc}")

    def force_stop_app(
        self, package: str, confirmation: Optional[OperationConfirmation],
    ) -> OperationResult:
        """Legacy parity command shape (``am force-stop <pkg>``), gated."""
        name = self._validate(package)
        validate_confirmation(confirmation, f"force_stop:{name}")
        result = self._transport.run_text(
            ["shell", "am", "force-stop", name], timeout=30.0)
        rc = getattr(result, "returncode", 1)
        msg = (getattr(result, "stderr", "") or "").strip() or f"am force-stop rc={rc}"
        return OperationResult(ok=False if rc != 0 else True,
                               adb_returncode=rc, message=msg)

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _validate(self, package: str) -> str:
        """Validate the package name with the scan pipeline validator
        (single source; typed InputValidationError on bad input)."""
        from vscanner.services.scanning.scanner import validate_package_name
        return validate_package_name(package)

    @staticmethod
    def _extract_activity(query_output: str) -> Optional[str]:
        """First launcher activity line of the ``--brief`` output.

        Legacy semantic kept exactly: the activity segment is passed
        through unchanged (``am start -n pkg/.MainActivity`` and
        ``am start -n pkg/com.example.app.MainActivity`` are both valid).
        """
        for line in (query_output or "").splitlines():
            line = line.strip()
            if not line or line.startswith("Priority"):
                continue
            if "/" not in line:
                continue
            activity = line.split("/", 1)[1].strip()
            if activity:
                return activity
        return None
