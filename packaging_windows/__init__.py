"""V-Scanner 3.0 Windows packaging (Stage 14 — ARCHITECTURE_DECISIONS T-05).

This package is *build-time tooling*: nothing here ships inside the
application distribution. The desktop distribution stages only the
``vscanner`` and ``ui_desktop`` source trees plus the thin launcher into a
controlled workspace outside the repository, compiles the launcher with
Nuitka (standalone mode), validates the resulting distribution, and
finally compiles the Inno Setup installer.

Package-name constraint: ``packaging_windows`` (NOT ``packaging``). A
directory named ``packaging`` at the repository root would shadow the
installed PyPI ``packaging`` distribution that pytest and the surrounding
tooling import.

Entry points:

* ``build_windows.py``      — reproducible build orchestration (CLI).
* ``versioning.py``         — authoritative version parse (pyproject lockstep).
* ``staging.py``            — release-policy allowlist stager.
* ``validation.py``         — staged-tree / distribution / launch validation.
* ``icon.py``               — regeneration of the committed application icon.
* ``vscanner_desktop.py``   — the thin launcher compiled as the exe main.
* ``installer.iss``         — Inno Setup script consumed by ``build_windows.py``.
"""

from __future__ import annotations

__all__ = [
    "APP_ID",
    "APP_PUBLISHER",
    "APP_SUPPORT_URL",
    "EXECUTABLE_NAME",
    "APP_FILE_DESCRIPTION",
]

# Stable installer identity (Inno Setup AppId). This GUID must never change:
# upgrades and uninstall are keyed to it.
APP_ID = "1AB0A622-DB19-4B71-88B9-1988011A281A"

# Product identity (verified repository facts; not invented).
APP_PUBLISHER = "ToTheBlankWorld"
APP_SUPPORT_URL = "https://github.com/ToTheBlankWorld/V-Scanner"
EXECUTABLE_NAME = "V-Scanner.exe"
APP_FILE_DESCRIPTION = "V-Scanner - Android security auditing"
