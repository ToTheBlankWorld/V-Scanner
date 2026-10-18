"""Subprocess adapter for ADB (SC-7 client half, R-07 binary groundwork).

Policy (R-10):
* Every invocation is an argument LIST; ``shell=True`` never appears here.
* Timeouts are mandatory parameters with sane defaults; a timeout raises
  :class:`AdbCommandError` with ``timeout=True`` so UIs can distinguish a
  hung command from a fast failure.
* Non-zero return codes are carried in :class:`AdbResult` for ``run_text`` —
  callers decide what a failure means (device shells legitimately return
  non-zero). ``run_bytes`` (exec-out) is stricter: byte-safety is only
  meaningful when the process succeeded, so non-zero raises.
* ``FileNotFoundError`` surfaces as :class:`AdbNotAvailable`, never as
  ``None`` results (silent downgrades are banned by the error taxonomy).

Test ergonomics: services accept any object implementing
``AdbClientProtocol``; unit tests inject fakes and never touch a real adb.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

from vscanner.core.errors import AdbCommandError, AdbNotAvailable

__all__ = [
    "AdbResult",
    "AdbClientProtocol",
    "SubprocessAdbClient",
    "DEFAULT_TIMEOUT",
    "build_adb_command",
]

DEFAULT_TIMEOUT: float = 30.0


@dataclass(frozen=True, slots=True)
class AdbResult:
    stdout: str
    stderr: str
    returncode: int


class AdbClientProtocol(Protocol):
    """Structural interface for ADB execution (injectable/mockable)."""

    def run_text(self, cmd: Sequence[str], timeout: float = DEFAULT_TIMEOUT) -> AdbResult:
        """Run a device/host ADB command, returning text output."""
        ...

    def run_bytes(self, cmd: Sequence[str], timeout: float = DEFAULT_TIMEOUT) -> bytes:
        """Byte-safe execution (``adb exec-out`` shape; no text decoding)."""
        ...


class SubprocessAdbClient(AdbClientProtocol):
    """Argument-list ADB subprocess adapter (the production transport)."""

    def __init__(self, adb_path: str, serial: Optional[str] = None) -> None:
        self.adb_path = str(adb_path)
        self.serial = serial

    def _full(self, cmd: Sequence[str]) -> list:
        argv = [self.adb_path]
        if self.serial:
            argv.extend(["-s", self.serial])
        argv.extend(str(part) for part in cmd)
        return argv

    def run_text(self, cmd: Sequence[str], timeout: float = DEFAULT_TIMEOUT) -> AdbResult:
        argv = self._full(cmd)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",  # device streams may contain garbage bytes
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AdbNotAvailable(
                f"ADB executable not found or not launchable: {self.adb_path}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbCommandError(
                f"ADB command timed out after {timeout}s: {' '.join(argv[1:])}",
                cmd=tuple(argv[1:]),
                timeout=True,
            ) from exc
        return AdbResult(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
        )

    def run_bytes(self, cmd: Sequence[str], timeout: float = DEFAULT_TIMEOUT) -> bytes:
        # Byte-safe mode: stdout captured raw (no decoding → no byte loss).
        argv = self._full(cmd)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AdbNotAvailable(
                f"ADB executable not found or not launchable: {self.adb_path}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbCommandError(
                f"ADB command timed out after {timeout}s: {' '.join(argv[1:])}",
                cmd=tuple(argv[1:]),
                timeout=True,
            ) from exc
        if completed.returncode != 0:
            raise AdbCommandError(
                f"exec-out command failed (rc={completed.returncode})",
                cmd=tuple(argv[1:]),
                returncode=completed.returncode,
                stderr_excerpt=(completed.stderr or b"").decode("utf-8", errors="replace"),
            )
        return completed.stdout or b""


def build_adb_command(adb_path: str, cmd: Sequence[str], serial: Optional[str] = None) -> list:
    """Utility for call-sites and tests that need the exact argv list."""
    argv = [str(adb_path)]
    if serial:
        argv.extend(["-s", str(serial)])
    argv.extend(str(part) for part in cmd)
    return argv
