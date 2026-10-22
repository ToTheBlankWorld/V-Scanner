"""Authoritative version sourcing (Stage 14; T-05 packaging decision).

Single source of truth for the application version is ``pyproject.toml``
(``[project] version``). ``ui_desktop.APP_VERSION`` is already lockstep-
tested with it (Stage 09), and this package never hardcodes a copy: the
value is parsed at build time and injected into

* Nuitka ``--product-version`` / ``--file-version`` (numeric derivation),
* the Inno Setup script via ``/DVSCANNER_VERSION=`` and
  ``/DVSCANNER_RESOURCE_VERSION=`` (the ``VSCANNER_`` prefix avoids the
  ISPP name collision root-caused during Stage 14).

The numeric derivation is required because the Windows VERSIONINFO
resource and Inno Setup's ``VersionInfoVersion`` need a plain numeric
value, while Inno's ``AppVersion`` may carry the prerelease suffix
verbatim (``3.0.0a0`` → ``AppVersion``; numeric part ``3.0.0`` → VERSIONINFO).
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "parse_pyproject_version",
    "derive_numeric_version",
    "derive_version_quad",
]

# Fallback parser for interpreters without tomllib (Python 3.10/3.11-absent):
# a standalone ``version = "..."`` line. Only [project] carries such a line
# in the authoritative pyproject.toml; ambiguity is an error, not a guess.
_VERSION_LINE_RE = re.compile(r'^\s*version\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
_NUMERIC_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)?(?:\.\d+)?)")


def parse_pyproject_version(pyproject_path: Path) -> str:
    """Return ``[project] version`` from *pyproject_path*.

    ``tomllib`` (standard library from Python 3.11) is used when available;
    otherwise a strict single-match regex parse is applied. Raises
    ``ValueError`` with actionable text when the file has no version or an
    ambiguous fallback match.
    """
    text = Path(pyproject_path).read_text(encoding="utf-8")
    try:
        import tomllib  # Python 3.11+/3.12 build environment
    except ModuleNotFoundError:  # pragma: no cover - exercised via regex path
        return _parse_version_by_regex(text)
    data = tomllib.loads(text)
    version = data.get("project", {}).get("version")
    if isinstance(version, str) and version:
        return version
    raise ValueError(
        f"pyproject.toml ({pyproject_path}) declares no [project] version; "
        "the build pipeline refuses to invent one"
    )


def _parse_version_by_regex(text: str) -> str:
    matches = _VERSION_LINE_RE.findall(text)
    if not matches:
        raise ValueError(
            "pyproject.toml has no standalone 'version = \"...\"' line; "
            "the build pipeline refuses to invent one"
        )
    if len(matches) > 1:
        raise ValueError(
            "pyproject.toml has ambiguous 'version =' lines "
            f"({matches!r}); refusing to guess"
        )
    return matches[0]


def derive_numeric_version(version: str) -> str:
    """Derive the numeric VERSIONINFO value from the full version string.

    ``3.0.0a0`` → ``3.0.0``; ``3.1.1`` stays ``3.1.1``; ``3 .4`` → ``3.4``.
    Raises ``ValueError`` when no numeric prefix exists.
    """
    match = _NUMERIC_PREFIX_RE.match(version)
    if match is None:
        raise ValueError(
            f"version {version!r} has no numeric prefix for the Windows "
            "VERSIONINFO resource"
        )
    return match.group(1)


def derive_version_quad(version: str) -> str:
    """Derive the 4-part value Windows VERSIONINFO / Inno SideBySide expect.

    ``3.0.0a0`` → ``3.0.0.0``; ``2.3`` → ``2.3.0.0``. Inno Setup's
    ``VersionInfoVersion`` (ISCC compile error observed in Stage 14) and
    the exe resource metadata take exactly four numeric components.
    """
    parts = derive_numeric_version(version).split(".")
    while len(parts) < 4:
        parts.append("0")
    if len(parts) > 4:
        raise ValueError(f"version {version!r} carries too many components")
    return ".".join(parts)
