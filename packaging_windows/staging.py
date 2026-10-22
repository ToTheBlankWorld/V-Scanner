"""Release staging (Stage 14): allowlist copy into a clean workspace.

The repository working tree is never packaged wholesale (T-05). Only the
entries in :data:`STAGE_ENTRIES` — the two runtime packages plus the thin
launcher — are copied into ``<stage root>``; everything else (docs, tests,
legacy ``cli`` tree, ``android/``, user data, caches, VCS state) never
enters the distribution. The stager is *non-destructive by construction*:
it only creates/copies, never deletes, and refuses a non-empty destination
so no caller can silently merge stale files into a release tree.

This module is dependency-free (standard library only) so the build
pipeline and the unit tests enforce exactly the same policy.
"""

from __future__ import annotations

import fnmatch
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

__all__ = [
    "STAGE_PACKAGES",
    "LAUNCHER_NAME",
    "EXCLUDED_DIR_NAMES",
    "EXCLUDED_FILE_PATTERNS",
    "StagingReport",
    "stage_release_tree",
    "first_link_entry",
]

#: Runtime source trees copied into the distribution.
STAGE_PACKAGES: tuple[str, ...] = ("vscanner", "ui_desktop")

#: The thin launcher copied from ``packaging_windows/`` into the stage root
#: and compiled as the executable main module (delegates to the real
#: ``ui_desktop.app:main`` — verified pure by test).
LAUNCHER_NAME = "vscanner_desktop.py"

#: Directory names that must never enter a staged tree (infrastructure,
#: caches, development-only artifacts). Matched against each relative
#: directory name while copying.
EXCLUDED_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "build",
        "dist",
        "node_modules",
        ".idea",
        ".vscode",
    }
)

#: File-name patterns (fnmatch, case-insensitive) that must never enter a
#: staged tree: machine-local state, secrets, bytecode. Normal source files
#: never carry these names.
EXCLUDED_FILE_PATTERNS = frozenset(
    {
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "*.so",
        "*.exe",
        "*.dll",
        "*.ico",  # committed single-icon input lives only under packaging_windows/
        "*.png",  # no runtime image assets exist in the package trees
        "*.pem",
        "*.key",
        "*.pfx",
        "*.p12",
        ".env",
        "adb_config.json",  # machine-local ADB configuration (R-08/R-15)
        "config.json",  # user-local configuration snapshot
        "settings.json",
    }
)


def _ignored_names(
    directory: str, names: "Iterable[str]"
) -> "list[str]":  # pragma: no cover - trivial glue over constants
    """Build the ``shutil.copytree``/``ignore`` callable argument list."""
    dir_names = set(EXCLUDED_DIR_NAMES)
    file_globs = tuple(EXCLUDED_FILE_PATTERNS)
    ignored: list[str] = []
    for name in names:
        lower = name.lower()
        if lower.endswith(".egg-info") or name in dir_names:
            ignored.append(name)
            continue
        if any(fnmatch.fnmatchcase(lower, pattern) for pattern in file_globs):
            ignored.append(name)
    return ignored


def _is_link(path: Path) -> bool:
    """True for symlinks always, and for NTFS junctions on Python 3.12+."""
    if path.is_symlink():
        return True
    junction_probe = getattr(Path, "is_junction", None)
    if junction_probe is None:
        return False
    return bool(junction_probe(path))


def first_link_entry(source_root: Path) -> "Optional[Path]":
    """First symlink/junction entry under *source_root* (``None`` if none).

    A link is refused, never followed: ``shutil.copytree(symlinks=False)``
    would transparently materialize the *target's content* into the release
    tree, so a link planted inside a package tree could smuggle machine-local
    files (secrets, user data) into a distribution that policy says cannot
    contain them. Path traversal cannot escape the staging root in the other
    direction — destinations are built from the real tree's relative parts —
    but walking *into* foreign content is a silent policy break, so Stage 15
    forbids it at the source. (NTFS junctions need ``Path.is_junction`` which
    exists from Python 3.12; older interpreters only see ``is_symlink``.)
    """
    for path in Path(source_root).rglob("*"):
        if _is_link(path):
            return path
    return None


@dataclass(frozen=True)
class StagingReport:
    """Facts from one staging run (for validation and the build log)."""

    stage_root: Path
    launcher_path: Path
    copied_files: int = 0
    per_package: dict[str, int] = field(default_factory=dict)


def stage_release_tree(
    repo_root: Path,
    stage_root: Path,
    *,
    packages: "Iterable[str]" = STAGE_PACKAGES,
) -> StagingReport:
    """Copy the release policy's entries into *stage_root*.

    * Copies every package directory named in *packages* (default: the two
      runtime trees) whose contents are filtered by
      :data:`EXCLUDED_DIR_NAMES` / :data:`EXCLUDED_FILE_PATTERNS`.
    * Copies the thin launcher (``packaging_windows/<LAUNCHER_NAME>``) to
      ``(stage_root / LAUNCHER_NAME)``.
    * ``pyproject.toml`` is NOT staged: the version authority is read from
      the repository at build time and shipped as compiled metadata.
    * Non-destructive: refuses to touch anything when the destination is
      non-empty; never deletes source files.
    """
    repo_root = Path(repo_root).resolve()
    stage_root = Path(stage_root).resolve()
    if not repo_root.is_dir():
        raise ValueError(f"repository root does not exist: {repo_root}")
    if stage_root == repo_root or repo_root in stage_root.parents:
        raise ValueError(
            f"stage root must live outside the repository root ({repo_root}); "
            f"got {stage_root}"
        )

    if stage_root.exists() and any(stage_root.iterdir()):
        raise ValueError(
            f"staging destination is not empty: {stage_root} — move it away or "
            "let build_windows.py recreate its own work directory"
        )
    stage_root.mkdir(parents=True, exist_ok=True)

    per_package: dict[str, int] = {}
    for package in packages:
        source = repo_root / package
        if not source.is_dir():
            raise FileNotFoundError(
                f"required runtime package is missing: {source}"
            )
        smuggler = first_link_entry(source)
        if smuggler is not None:
            raise ValueError(
                f"refusing to stage {source}: symlink/junction entry found at "
                f"{smuggler} - release staging follows no links, because a "
                "planted link could silently pull foreign content (secrets, "
                "user data, build-tree state) into the distribution"
            )
        destination = stage_root / package
        shutil.copytree(
            source,
            destination,
            ignore=_ignored_names,  # type: ignore[arg-type]
            dirs_exist_ok=False,
        )
        per_package[package] = sum(
            1 for path in destination.rglob("*") if path.is_file()
        )

    launcher_source = repo_root / "packaging_windows" / LAUNCHER_NAME
    if not launcher_source.is_file():
        raise FileNotFoundError(
            f"thin launcher is missing: {launcher_source}"
        )
    if _is_link(launcher_source):
        raise ValueError(
            "thin launcher must be a regular file, not a link: "
            f"{launcher_source}"
        )
    shutil.copy2(launcher_source, stage_root / LAUNCHER_NAME)

    return StagingReport(
        stage_root=stage_root,
        launcher_path=stage_root / LAUNCHER_NAME,
        copied_files=sum(per_package.values()) + 1,
        per_package=per_package,
    )
