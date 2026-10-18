"""
Permission Analysis Module — legacy re-export shim (V-Scanner 3.0, Stage 03).

The knowledge base and scoring logic now live in ``vscanner.core.kb.permissions``
(shared engine, framework-free). This module survives so every legacy import

    from permissions import RiskLevel, PermissionInfo, ...

keeps working unchanged (``cli/scanner.py``, ``cli/report_generator.py`` and the
direct ``python cli/scanner.py`` entry point). It re-exports the public surface
of the migrated module; no analysis logic lives here anymore.

Migration note: MODULE_MIGRATION_MAP row ``cli/permissions.py`` — EXTRACT with
``from permissions import ...`` legacy import preserved via this re-export shim.
"""

import sys as _sys
import pathlib as _pathlib

# Make the repository root importable so ``vscanner`` resolves when this shim
# is imported as a flat legacy module ("cli/" on sys.path, repo root not).
_REPO_ROOT = _pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

from vscanner.core.kb.permissions import *  # noqa: F401,F403
from vscanner.core.kb.permissions import (  # noqa: F401 — explicit for tooling
    DANGEROUS_PERMISSIONS,
    INSECURE_URL_PATTERNS,
    PermissionInfo,
    RiskLevel,
    SDK_SECURITY_INFO,
    analyze_permissions,
    get_permission_info,
    get_sdk_risk,
)
