"""Artifact validation (Stage 14): staged tree, distribution, and launch.

A successful compiler exit code alone is *not* sufficient (stage brief §6):
every stage and distribution is inspected against the release policy and
against the runtime's actual native closure (Python DLL, Qt6 DLLs, the
Windows platform plugin ``qwindows.dll``, PySide6 bindings) before the
distribution is considered installable. The final gate is a process-level
launch of the packaged executable in ``--smoke`` mode from an
outside-the-repository working directory (with a deliberate space in the
path) under a deliberately clean environment.

All failures raise :class:`ValidationError` with actionable text.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from packaging_windows import (
    APP_FILE_DESCRIPTION,
    EXECUTABLE_NAME,
)

__all__ = [
    "ValidationError",
    "REQUIRED_STAGE_FILES",
    "FORBIDDEN_DIR_NAMES",
    "FORBIDDEN_FILE_PATTERNS",
    "REQUIRED_DIST_DLLS",
    "validate_staged_tree",
    "validate_distribution",
    "smoke_launch",
    "validate_icon_file",
    "icon_entry_sizes",
]

# Reuses the staging policy constants by value (a copy here prevents an
# import cycle where staging imports validation for the deny lists).
REQUIRED_STAGE_FILES: "tuple[str, ...]" = (
    "vscanner/__init__.py",
    "ui_desktop/__init__.py",
    "ui_desktop/app.py",
    "vscanner_desktop.py",
)

FORBIDDEN_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "tests",
        "cli",
        "android",
        "docs",
        "node_modules",
    }
)

FORBIDDEN_FILE_PATTERNS = frozenset(
    {
        "*.pyc",
        "*.pyo",
        "*.pem",
        "*.key",
        "*.pfx",
        "*.p12",
        ".env",
        "adb_config.json",
        "config.json",
        "settings.json",
        "test_*.py",
    }
)

#: DLLs whose absence breaks standalone startup or a Windows GUI.
REQUIRED_DIST_DLLS: "tuple[str, ...]" = (
    "python3*.dll",  # CPython runtime shipped by the standalone build
    "Qt6Core.dll",
    "Qt6Gui.dll",
    "Qt6Widgets.dll",
    "qwindows.dll",  # the platform plugin a Windows GUI session requires
)


class ValidationError(RuntimeError):
    """Raised with actionable text when an artifact violates policy."""


def _find_forbidden(root: Path) -> "list[str]":
    """Relative paths of anything violating the release policy under *root*."""
    violations: list[str] = []
    if not root.is_dir():
        raise ValidationError(f"directory to validate does not exist: {root}")
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        parts = {part.lower() for part in relative.parts[:-1]}
        if parts & FORBIDDEN_DIR_NAMES:
            violations.append(str(relative))
            continue
        if path.is_dir() and path.name.lower() in FORBIDDEN_DIR_NAMES:
            violations.append(str(relative))
            continue
        if path.is_file():
            name = path.name.lower()
            if any(fnmatch.fnmatchcase(name, pattern)
                   for pattern in FORBIDDEN_FILE_PATTERNS):
                violations.append(str(relative))
    return sorted(set(violations))


# ---------------------------------------------------------------------------
# Staged tree (source layout) validation
# ---------------------------------------------------------------------------


def validate_staged_tree(
    stage_root: Path,
    *,
    required_files: "Sequence[str]" = REQUIRED_STAGE_FILES,
) -> "list[str]":
    """Validate the staged, not-yet-compiled source tree.

    Requires every file in *required_files*, forbids release-policy
    violations (tests, machine-local config, secrets, caches, bytecode,
    ``ui_terminal`` — the optional TUI interface must stay out of the
    desktop distribution), and forbids ``pyproject.toml``/``pyvenv.cfg`/
    development metadata from entering the release staging.
    """
    stage_root = Path(stage_root)
    if not stage_root.is_dir():
        raise ValidationError(f"staging directory does not exist: {stage_root}")

    for required in required_files:
        if not (stage_root / required).is_file():
            raise ValidationError(
                f"staged tree is missing required file: {required}"
            )

    violations = _find_forbidden(stage_root)
    if violations:
        raise ValidationError(
            "staged tree contains forbidden content "
            f"({len(violations)} entries, first: {violations[0]})"
        )

    if (stage_root / "pyproject.toml").exists():
        raise ValidationError(
            "pyproject.toml must not be staged (version authority is read "
            "from the repository at build time)"
        )
    if (stage_root / "ui_terminal").exists():
        raise ValidationError(
            "ui_terminal must not be staged: the desktop distribution "
            "consumes ui_desktop only"
        )
    return []  # the absence of violations


# ---------------------------------------------------------------------------
# Compiled distribution validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DistReport:
    executable: Path
    dlls_found: dict[str, Path]
    files: int
    total_bytes: int


def _first_match(root: Path, pattern: str) -> Optional[Path]:
    for path in root.rglob(pattern):
        return path  # any node type: callers verify dir/file expectations
    return None


def validate_distribution(
    dist_root: Path,
    *,
    executable_name: str = EXECUTABLE_NAME,
) -> DistReport:
    """Validate a compiled (or expected) standalone distribution.

    Checks: the executable exists, the executable is a PE binary (MZ
    header), the standalone Python runtime DLL is present, the Qt6 core
    GUI DLLs are present (including the ``qwindows.dll`` platform plugin),
    the PySide6 bindings directory exists, and no release-policy content
    leaks into the result.
    """
    dist_root = Path(dist_root)
    if not dist_root.is_dir():
        raise ValidationError(f"distribution directory does not exist: {dist_root}")

    executable = dist_root / executable_name
    if not executable.is_file():
        raise ValidationError(f"executable is missing: {executable}")
    if executable.read_bytes()[:2] != b"MZ":
        raise ValidationError(f"executable is not a PE binary: {executable}")

    pyside_dir = _first_match(dist_root, "PySide6")
    if pyside_dir is None or not pyside_dir.is_dir():
        raise ValidationError(
            f"PySide6 bindings directory is missing from {dist_root}"
        )

    dlls_found: dict[str, Path] = {}
    for pattern in REQUIRED_DIST_DLLS:
        found = _first_match(dist_root, pattern)
        if found is None:
            raise ValidationError(
                f"required DLL matching {pattern!r} is missing from {dist_root} "
                "(standalone runtime closure is incomplete)"
            )
        dlls_found[pattern] = found

    files = [path for path in dist_root.rglob("*") if path.is_file()]
    violations = _find_forbidden(dist_root)
    if violations:
        raise ValidationError(
            "distribution contains forbidden content "
            f"({len(violations)} entries, first: {violations[0]})"
        )

    return DistReport(
        executable=executable,
        dlls_found=dlls_found,
        files=len(files),
        total_bytes=sum(path.stat().st_size for path in files),
    )


# ---------------------------------------------------------------------------
# Environment-controlled smoke launch of the packaged executable
# ---------------------------------------------------------------------------


def clean_gui_environment(
    base: "Optional[Mapping[str, str]]" = None,
) -> "dict[str, str]":
    """Environment for launching the packaged app in validation.

    Keeps only the OS-level variables that a GUI process needs and drops
    every engine-path override: a packaged build must use its production
    conventions (``%LOCALAPPDATA%\\vscanner``, A-07) and never inherit
    development-mode data redirection (``VSCANNER_LOCAL``,
    ``VSCANNER_DATA_DIR``). ``QT_QPA_PLATFORM`` is forced offscreen for the
    automated smoke so no real window flashes on a user's desktop.
    """
    source = dict(os.environ if base is None else base)
    keep = (
        "SystemRoot", "SystemDrive", "windir", "TEMP", "TMP",
        "LOCALAPPDATA", "APPDATA", "HOMEDRIVE", "HOMEPATH", "ComSpec",
        "PATHEXT", "PATH", "USERNAME", "USERDOMAIN",
    )
    env = {name: source[name] for name in keep if name in source}
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("VSCANNER_LOCAL", None)
    env.pop("VSCANNER_DATA_DIR", None)
    env.pop("PYTHONPATH", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    return env


def smoke_launch(
    executable: Path,
    cwd: Path,
    *,
    timeout_s: float = 180.0,
    require_smoke_line: bool = True,
    extra_env: "Optional[Mapping[str, str]]" = None,
) -> str:
    """Launch the packaged executable with ``--smoke`` and check the result.

    Returns the process stdout on success. Raises :class:`ValidationError`
    on nonzero exit, timeout, or a missing ``DESKTOP_SMOKE_OK`` marker
    when *require_smoke_line* is set.
    """
    executable = Path(executable)
    cwd = Path(cwd)
    if not executable.is_file():
        raise ValidationError(f"executable to smoke-launch is missing: {executable}")
    if not cwd.is_dir():
        raise ValidationError(f"working directory is missing: {cwd}")
    env = clean_gui_environment()
    if extra_env:
        env.update(extra_env)

    try:
        proc = subprocess.run(
            [str(executable), "--smoke"],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationError(
            f"packaged executable did not exit within {timeout_s:.0f} s "
            f"(output so far: {(exc.stdout or b'')[:2000]!r})"
        ) from exc
    if proc.returncode != 0:
        raise ValidationError(
            f"packaged executable exited {proc.returncode} during smoke "
            f"(stdout={proc.stdout!r}, stderr={proc.stderr!r})"
        )
    stdout = proc.stdout if proc.stdout else ""
    if require_smoke_line and "DESKTOP_SMOKE_OK" not in stdout:
        raise ValidationError(
            "packaged executable exited 0 but did not report DESKTOP_SMOKE_OK "
            f"(stdout={stdout!r}, stderr={proc.stderr!r})"
        )
    return stdout


# ---------------------------------------------------------------------------
# Icon file validation (bytes-level ICO container + Qt load-back)
# ---------------------------------------------------------------------------


def icon_entry_sizes(icon_path: Path) -> "list[int]":
    """Parse the ICO directory and return the contained entry sizes.

    Raises :class:`ValidationError` for structural problems (bad header,
    truncated directory, zero entries).
    """
    data = Path(icon_path).read_bytes()
    if len(data) < 6:
        raise ValidationError(f"ICO file is too small: {icon_path}")
    reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or icon_type != 1:
        raise ValidationError(
            f"not an ICO container (reserved={reserved}, type={icon_type}): "
            f"{icon_path}"
        )
    if count == 0:
        raise ValidationError(f"ICO container holds zero entries: {icon_path}")
    entries_start = 6
    sizes: list[int] = []
    for index in range(count):
        entry = entries_start + index * 16
        width, height, _colors, _res, _planes, _bits, size, _pos = (
            struct.unpack_from("<BBBBHHII", data, entry)
        )
        width = width if width else 256
        height = height if height else 256
        if width != height:
            raise ValidationError(
                f"ICO entry {index} is not square ({width}x{height}): {icon_path}"
            )
        if size <= 0 or entry + 16 + size > len(data):
            raise ValidationError(
                f"ICO entry {index} payload overruns the file: {icon_path}"
            )
        sizes.append(width)
    return sizes


def validate_icon_file(
    icon_path: Path,
    *,
    expected_sizes: "Sequence[int]" = (16, 24, 32, 48, 64, 128, 256),
) -> "list[int]":
    """Structural + Qt load-back validation of the application icon.

    The ICO directory must contain exactly one square entry per expected
    size, every payload must lie inside the file, and QImage must decode
    the icon. (PySide6 is expected in the packaging environment.)
    """
    sizes = icon_entry_sizes(icon_path)
    if sorted(sizes) != sorted(expected_sizes):
        raise ValidationError(
            f"ICO entries {sizes} do not match the expected sizes {list(expected_sizes)}"
        )
    from PySide6.QtGui import QImage

    image = QImage(str(icon_path))
    if image.isNull():
        raise ValidationError(f"Qt could not decode the icon: {icon_path}")
    return sizes
