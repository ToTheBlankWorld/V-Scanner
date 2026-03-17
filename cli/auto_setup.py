#!/usr/bin/env python3
"""
Auto Setup Module for V Scanner
Automatically downloads and manages ADB and scrcpy in tools folder
"""

from tools_manager import ensure_tools, get_adb_path, get_scrcpy_path, check_tool_exists
from rich.console import Console
from rich.table import Table

console = Console()


def check_and_setup() -> bool:
    """
    Check all required tools and ensure they are available.
    Downloads them if missing.
    Returns True if all essential tools are available.
    """
    # Ensure tools are downloaded and ready
    return ensure_tools()


def check_tool_status():
    """Display tool status."""
    console.print("\n[bold cyan]Tool Status[/bold cyan]\n")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Tool", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Path", style="dim")

    # Check ADB
    adb_exists = check_tool_exists("adb")
    table.add_row(
        "ADB (Android Debug Bridge)",
        "[green]✓ Available[/green]" if adb_exists else "[red]✗ Missing[/red]",
        get_adb_path() if adb_exists else "Not found"
    )

    # Check scrcpy
    scrcpy_exists = check_tool_exists("scrcpy")
    table.add_row(
        "scrcpy (Screen Mirroring)",
        "[green]✓ Available[/green]" if scrcpy_exists else "[yellow]⚠ Missing[/yellow]",
        get_scrcpy_path() if scrcpy_exists else "Not found"
    )

    console.print(table)
    console.print()


def interactive_tool_setup():
    """Interactive menu for tool setup."""
    while True:
        console.print("\n[bold cyan]Tool Setup Menu[/bold cyan]\n")
        console.print("[1] Check tool status")
        console.print("[2] Setup tools now")
        console.print("[3] Back to main menu")

        choice = console.input("\n[bold]Select option: [/bold]").strip()

        if choice == "1":
            check_tool_status()
        elif choice == "2":
            ensure_tools()
        elif choice == "3":
            break
        else:
            console.print("[red]Invalid choice[/red]")


if __name__ == "__main__":
    check_and_setup()
