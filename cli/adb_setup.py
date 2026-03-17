#!/usr/bin/env python3
"""
ADB Setup Module
Uses tools_manager to get local ADB or system ADB
"""

import os
import json
import subprocess
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from tools_manager import get_adb_path as get_local_adb_path, check_tool_exists as check_local_tool

console = Console()

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "adb_config.json")


def check_adb_valid(adb_path: str) -> bool:
    """Verify that the given path is a valid ADB executable."""
    if not os.path.exists(adb_path):
        return False

    try:
        result = subprocess.run(
            [adb_path, "version"],
            capture_output=True,
            timeout=5,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def save_adb_config(adb_path: str):
    """Save ADB path to config file."""
    try:
        config = {"adb_path": adb_path}
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not save ADB config: {e}[/yellow]")


def load_adb_config() -> Optional[str]:
    """Load saved ADB path from config file."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                saved_path = config.get("adb_path")

                # Verify the saved path is still valid
                if saved_path and check_adb_valid(saved_path):
                    return saved_path
    except Exception:
        pass

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

