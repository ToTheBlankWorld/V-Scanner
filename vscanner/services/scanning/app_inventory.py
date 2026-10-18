"""PackageInventoryService (SC-2): device package listing + single-app info."""

from __future__ import annotations

from typing import Protocol, Tuple

from vscanner.core.errors import AdbCommandError
from vscanner.core.models import AppInfo
from vscanner.services.scanning.package_parser import (
    derived_label,
    parse_package_dump,
    parse_pm_list_output,
)

__all__ = ["PackageInventoryService"]
_LIST_TIMEOUT = 30.0
_DUMP_TIMEOUT = 30.0


class _AdbTransport(Protocol):
    def run_text(self, cmd, timeout: float = 30.0):
        ...


class PackageInventoryService:
    """SC-2 face over one serial-bound ADB transport.

    ``list_packages(include_system=True)`` lists everything; ``False`` uses
    the same third-party filter as the legacy CLI (``pm list packages -3``).
    """

    def __init__(self, transport: _AdbTransport) -> None:
        self._transport = transport

    def list_packages(self, include_system: bool = False,
                      timeout: float = _LIST_TIMEOUT) -> Tuple[str, ...]:
        result = self._transport.run_text(
            ["shell", "pm", "list", "packages"] + ([] if include_system else ["-3"]),
            timeout=timeout,
        )
        if result.returncode != 0 and not result.stdout:
            raise AdbCommandError(
                "pm list packages failed",
                cmd=tuple(["shell", "pm", "list", "packages"]),
                returncode=result.returncode,
                stderr_excerpt=result.stderr,
            )
        return parse_pm_list_output(result.stdout)

    def get_app_info(self, package: str, is_system: bool = False,
                     timeout: float = _DUMP_TIMEOUT) -> AppInfo:
        result = self._transport.run_text(
            ["shell", "dumpsys", "package", package],
            timeout=timeout,
        )
        # dumpsys exits non-zero on unknown packages with an empty-ish stdout.
        if result.returncode != 0 and not result.stdout:
            raise AdbCommandError(
                f"dumpsys package failed for {package}",
                cmd=tuple(["shell", "dumpsys", "package", package]),
                returncode=result.returncode,
                stderr_excerpt=result.stderr,
            )
        return parse_package_dump(package, result.stdout, is_system=is_system)

    def app_label(self, package: str) -> str:
        """Heuristic label only — exact labels require on-device label reads
        (deferred to Stage 06 label-source work; honesty keeps the HEURISTIC
        badge instead of pretending)."""
        return derived_label(package)
