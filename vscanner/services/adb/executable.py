"""ADB executable validation and path resolution (SC-7 + R-02 single path).

One authoritative implementation of "is this adb executable?" gathers here —
both the new engine (config service) and the legacy ``adb_setup`` adapter
delegate to these functions, eliminating the previously-shadowed duplicates.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional, Protocol

from vscanner.core.errors import AdbNotAvailable

__all__ = [
    "check_adb_valid",
    "resolve_adb_path",
    "SYSTEM_ADB_NAME",
]

SYSTEM_ADB_NAME = "adb"
_VALIDATION_TIMEOUT: float = 5.0
_VERSION_ARG = "version"


class _Saver(Protocol):
    def __call__(self, adb_path: str) -> None:
        ...


class _Checker(Protocol):
    def __call__(self) -> str:
        """Legacy facade callable returning the installed-on-disk adb path (str if it exists)."""
        ...


def check_adb_valid(adb_path: str) -> bool:
    """Verify the given path points at a launchable ADB executable.

    Mirrors the legacy ``adb -version`` probe exactly (5 s timeout, list
    arguments, zero return code) — the legacy adapter delegates here so there
    is only one implementation to audit for R-02.
    """
    if not adb_path:
        return False
    if not Path(adb_path).exists():
        return False
    try:
        result = subprocess.run(
            [adb_path, _VERSION_ARG],
            capture_output=True,
            timeout=_VALIDATION_TIMEOUT,
            check=False,
        )
    except Exception:
        # typed-honest probe failure: launch-side errors mean "not valid adb"
        return False
    return result.returncode == 0


def check_system_adb() -> bool:
    """Is plain ``adb`` on PATH? (launch probe, not shutil discovery)."""
    resolved = shutil.which(SYSTEM_ADB_NAME)
    if not resolved:
        return False
    return check_adb_valid(SYSTEM_ADB_NAME)


def resolve_adb_path(
    validated_saved_path: Optional[str],
    installed_tool_path: Optional[str],
    save: Optional[_Saver] = None,
) -> Optional[str]:
    """Resolve the fallback chain used everywhere ADB is located:

    1. validated saved config path (already validated by the config loader),
    2. the browser-deployed tools-dir adb (validation applies here too),
    3. system adb on PATH.

    ``save`` records the resolution so the next start uses it (legacy
    behavior preserved; new engine writes through the config service).
    Raises ``AdbNotAvailable`` on total failure — silent ``None`` downgrades
    are banned by the data error contract; callers translate if needed.
    """
    if validated_saved_path:
        return validated_saved_path

    if installed_tool_path and check_adb_valid(installed_tool_path):
        if save is not None:
            save(installed_tool_path)
        return installed_tool_path

    if check_system_adb():
        if save is not None:
            save(SYSTEM_ADB_NAME)
        return SYSTEM_ADB_NAME

    raise AdbNotAvailable("ADB binary not found in config, tools dir, or system PATH")
