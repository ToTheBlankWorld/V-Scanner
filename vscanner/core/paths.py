"""Storage-path resolution for the V-Scanner 3.0 engine.

Conventions (ARCHITECTURE_DECISIONS A-07):

* Windows (production): everything under ``%LOCALAPPDATA%\\vscanner``.
* Dev-repo mode: setting ``VSCANNER_LOCAL=1`` keeps every artifact inside
  the repository itself (``<repo>/.vscanner``), preserving today's
  "nothing outside the repo" behavior during development; an explicit
  directory path in the variable points elsewhere (tests use ``tmp_path``).
* Non-Windows without the variable (or Windows with a missing/corrupt
  ``LOCALAPPDATA``): ``~/.vscanner``.
* A master override ``VSCANNER_DATA_DIR`` always wins (deployment hook).

Resolution is pure with respect to the environment snapshot: tests pass a
mapping in, so no test touches the developer's real profile directories. No
directory is created at import time — creation is explicit (``ensure_dir``),
keeping imports side-effect free.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

__all__ = [
    "app_data_root", "config_dir", "tools_dir", "reports_dir", "history_dir",
    "ensure_dir", "ENV_OVERRIDE", "ENV_DATA_DIR",
]

ENV_OVERRIDE = "VSCANNER_LOCAL"        # 1 | <path>  → dev-repo/explicit mode
ENV_DATA_DIR = "VSCANNER_DATA_DIR"     # master override, wins over everything
_PROD_DIRNAME = "vscanner"


def _home_fallback() -> Path:
    return (Path.home() / _PROD_DIRNAME).resolve()


def app_data_root(env: Optional[Mapping[str, str]] = None) -> Path:
    """Resolve the engine's data root for the given environment snapshot.

    Precedence: ``VSCANNER_DATA_DIR`` > ``VSCANNER_LOCAL`` (1 → repo-local
    ``.vscanner``; path → that path) > ``%LOCALAPPDATA%/vscanner`` > home
    fallback. Never returns ``None``; never creates directories.
    """
    env_map = os.environ if env is None else env

    master = env_map.get(ENV_DATA_DIR, "").strip()
    if master:
        return Path(master).expanduser()

    override = env_map.get(ENV_OVERRIDE, "").strip()
    if override:
        if override.lower() in ("1", "true", "yes", "on"):
            repo_root = Path(__file__).resolve().parents[2]
            return repo_root / ".vscanner"
        return Path(override).expanduser()

    local_app_data = env_map.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data).expanduser() / _PROD_DIRNAME
    return _home_fallback()


def config_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return app_data_root(env) / "config"


def tools_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return app_data_root(env) / "tools"


def reports_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return app_data_root(env) / "reports"


def history_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    """T-08 scan-history location (Stage 07): ``<root>/history``.

    Same A-07 rules as every other data area: the dev-repo override keeps
    it inside the repo; no directory is created here (creation is the
    store's explicit job)."""
    return app_data_root(env) / "history"


def cases_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    """Forensics case-store location (Stage 08 path-migration approval):
    ``<root>/forensics_cases`` — the legacy ``cli/forensics_cases/`` default
    moves to the A-07 app-data root so extracted device data never lands in
    the repository worktree. No directory is created here (creation is the
    case store's explicit job)."""
    return app_data_root(env) / "forensics_cases"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if absent; returns it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
