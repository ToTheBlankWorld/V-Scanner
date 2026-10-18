#!/usr/bin/env python3
"""
ADB Setup Module — legacy adapter over the V-Scanner 3.0 engine (Stage 03).

The authoritative ADB-config read/write and executable-validation logic now
lives in the engine (``vscanner.services.config`` / ``vscanner.services.adb.executable``)
per R-02; this module is a thin compatibility adapter so legacy callers
(``cli/main.py``, ``auto_setup``, ``dependency_checker``... actually
``cli/main.py``) keep their exact function surface:

    ``check_adb_valid`` · ``save_adb_config`` · ``load_adb_config`` ·
    ``get_adb_path`` · ``interactive_adb_setup``

Behavior contract preserved from the legacy module, with ONE deliberate
improvement (R-02): a malformed config file can no longer fail silently —
the adapter prints a visible warning and still returns ``None`` (never a
garbage path). Typed ``ConfigError`` propagation is available through the
engine's :class:`~vscanner.services.config.ConfigService` directly.
"""

import os
import sys as _sys
import subprocess
from typing import Optional
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

# Make the repository root importable so ``vscanner`` resolves when this
# legacy module is imported as a flat module (``cli/`` on sys.path, repo
# root typically not). Tiny bootstrap — no import machinery rewrites.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

from vscanner.core.errors import ConfigError  # noqa: E402
from vscanner.services.config import ConfigService  # noqa: E402
from vscanner.services.adb.executable import check_adb_valid as _engine_check_adb_valid  # noqa: E402

from tools_manager import get_adb_path as get_local_adb_path, check_tool_exists as check_local_tool

console = Console()

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "adb_config.json")


def _config_service() -> ConfigService:
    """Build the engine's config service for the current CONFIG_FILE value.

    Read at call time so tests can point the legacy adapter at a temp path
    via ``monkeypatch.setattr(adb_setup, "CONFIG_FILE", ...)``.
    """
    return ConfigService(Path(CONFIG_FILE))


def check_adb_valid(adb_path: str) -> bool:
    """Verify that the given path is a valid ADB executable.

    Delegates to the engine's single implementation (R-02); semantics
    identical to the legacy probe (path-exists + 5 s ``adb version`` run).
    """
    return _engine_check_adb_valid(adb_path)


def save_adb_config(adb_path: str):
    """Save ADB path to config file (atomic write via the config service)."""
    try:
        _config_service().save(adb_path)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not save ADB config: {e}[/yellow]")


def load_adb_config() -> Optional[str]:
    """Load saved ADB path from config file.

    R-02 behavior upgrade over the legacy swallow-all handler: parse and
    schema problems print a visible warning; the return contract (None on
    any failure, validated path on success) is unchanged for callers.
    """
    try:
        snapshot = _config_service().load()
    except ConfigError as e:
        console.print(
            f"[bold red]✗ ADB configuration file is malformed or unreadable "
            f"({CONFIG_FILE}); re-run ADB setup.[/bold red] ({e.message})"
        )
        return None
    saved_path = snapshot.adb_path
    # Verify the saved path is still valid (legacy parity; monkeypatch seam
    # stays the module-level name for the regression suite).
    if saved_path and check_adb_valid(saved_path):
        return saved_path
    return None


def get_adb_path() -> Optional[str]:
    """
    Get ADB path with fallback:
    1. Try to load from config
    2. Try to get local ADB from tools folder
    3. Try to find system ADB
    """
    # First try to load from config
    saved_path = load_adb_config()
    if saved_path:
        return saved_path

    # Try local ADB from tools folder
    if check_local_tool('adb'):
        local_adb = get_local_adb_path()
        if check_adb_valid(local_adb):
            save_adb_config(local_adb)
            return local_adb

    # Try system ADB
    try:
        result = subprocess.run(
            ["adb", "version"],
            capture_output=True,
            timeout=5,
            text=True
        )
        if result.returncode == 0:
            save_adb_config("adb")
            return "adb"
    except FileNotFoundError:
        pass

    return None


def interactive_adb_setup() -> Optional[str]:
    """
    Interactive ADB setup with multiple options.
    """
    while True:
        console.print(Panel(
            "[bold cyan]⚙️  ADB Configuration[/bold cyan]\n\n"
            "[1] Auto-detect ADB\n"
            "[2] Provide custom path\n"
            "[3] Cancel",
            title="Setup Option",
            border_style="cyan"
        ))

        choice = console.input("[bold]Select option (1-3): [/bold]")

        if choice == "1":
            adb = get_adb_path()
            if adb:
                console.print(f"[green]✓ ADB found: {adb}[/green]")
                return adb
            else:
                console.print("[red]✗ Could not find or setup ADB[/red]")

        elif choice == "2":
            while True:
                adb_path = console.input("[bold]Enter path to adb.exe (or adb): [/bold]")
                adb_path = adb_path.strip('"\'')

                if not adb_path.strip():
                    console.print("[red]Path cannot be empty[/red]")
                    continue

                if check_adb_valid(adb_path):
                    save_adb_config(adb_path)
                    console.print(f"[green]✓ ADB configured: {adb_path}[/green]")
                    return adb_path
                else:
                    console.print(f"[red]✗ Invalid ADB executable: {adb_path}[/red]")

                    console.print("[yellow]Try again? (y/n)[/yellow]")
                    if console.input().lower() != "y":
                        break

        elif choice == "3":
            return None

        else:
            console.print("[red]Invalid choice[/red]")
