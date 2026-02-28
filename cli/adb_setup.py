#!/usr/bin/env python3
"""
Automated ADB Setup Module
Automatically downloads and configures Android Debug Bridge (ADB)
"""

import os
import sys
import json
import subprocess
import platform
import zipfile
import shutil
from pathlib import Path
from typing import Optional, Tuple
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, DownloadColumn, BarColumn, TransferSpeedColumn
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "adb_config.json")
PLATFORM_TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "platform-tools")


def get_platform_tools_url() -> Tuple[str, str]:
    """
    Get the appropriate platform-tools download URL based on OS.
    Returns (url, filename)
    """
    system = platform.system()
    
    # Note: These are examples - you'd need to get the actual latest URLs from Google
    urls = {
        "Windows": ("https://dl.google.com/android/repository/platform-tools-latest-windows.zip", 
                   "platform-tools-windows.zip"),
        "Darwin": ("https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
                  "platform-tools-darwin.zip"),
        "Linux": ("https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
                 "platform-tools-linux.zip"),
    }
    
    if system not in urls:
        console.print(f"[red]Unsupported OS: {system}[/red]")
        return None, None
    
    return urls[system]


def get_adb_executable_name() -> str:
    """Get the ADB executable name based on OS."""
    if platform.system() == "Windows":
        return "adb.exe"
    return "adb"


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


def find_existing_adb() -> Optional[str]:
    """Find ADB in system PATH."""
    try:
        result = subprocess.run(
            ["adb", "version"],
            capture_output=True,
            timeout=5,
            text=True
        )
        if result.returncode == 0:
            # Found in PATH, return 'adb'
            return "adb"
    except FileNotFoundError:
        pass
    
    return None


def setup_adb_automatic() -> Optional[str]:
    """
    Automatically setup ADB:
    1. Check if ADB exists in PATH
    2. Check if local platform-tools exist
    3. If not, download platform-tools
    """
    
    console.print(Panel(
        "[bold cyan]🤖 Automated ADB Setup[/bold cyan]\n"
        "Checking for Android Debug Bridge...",
        border_style="cyan"
    ))
    
    # Step 1: Check if ADB is already in PATH
    existing_adb = find_existing_adb()
    if existing_adb:
        console.print("[green]✓ Found ADB in system PATH[/green]")
        save_adb_config("adb")
        return "adb"
    
    # Step 2: Check if local platform-tools exist
    adb_executable = get_adb_executable_name()
    local_adb_path = os.path.join(PLATFORM_TOOLS_DIR, adb_executable)
    
    if check_adb_valid(local_adb_path):
        console.print(f"[green]✓ Found local ADB at {local_adb_path}[/green]")
        save_adb_config(local_adb_path)
        return local_adb_path
    
    # Step 3: Download platform-tools
    console.print("\n[yellow]ADB not found. Downloading platform-tools...[/yellow]")
    
    try:
        downloaded_adb = download_and_setup_platform_tools()
        if downloaded_adb:
            console.print(f"[green]✓ ADB successfully installed at {downloaded_adb}[/green]")
            return downloaded_adb
    except Exception as e:
        console.print(f"[red]✗ Failed to download platform-tools: {e}[/red]")
    
    # Fallback: Ask user to provide path
    console.print("\n[yellow]Could not automatically setup ADB. Please provide the path manually.[/yellow]")
    return None


def download_and_setup_platform_tools() -> Optional[str]:
    """
    Download and setup platform-tools automatically.
    Returns the path to ADB executable if successful.
    """
    import urllib.request
    
    url, filename = get_platform_tools_url()
    if not url:
        return None
    
    os.makedirs(PLATFORM_TOOLS_DIR, exist_ok=True)
    zip_path = os.path.join(PLATFORM_TOOLS_DIR, filename)
    
    try:
        console.print(f"\n[cyan]Downloading platform-tools for {platform.system()}...[/cyan]")
        
        # Download with progress bar
        def download_progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(100, (downloaded / total_size) * 100)
                sys.stdout.write(f'\r[{"█" * int(percent/2)}{"░" * (50-int(percent/2))}] {percent:.1f}%')
        
        urllib.request.urlretrieve(url, zip_path, download_progress)
        sys.stdout.write('\n')
        
        console.print("[green]✓ Download complete[/green]")
        
        # Extract
        console.print("\n[cyan]Extracting platform-tools...[/cyan]")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(os.path.dirname(PLATFORM_TOOLS_DIR))
        
        console.print("[green]✓ Extraction complete[/green]")
        
        # Clean up zip
        os.remove(zip_path)
        
        # Verify ADB
        adb_executable = get_adb_executable_name()
        adb_path = os.path.join(PLATFORM_TOOLS_DIR, adb_executable)
        
        if check_adb_valid(adb_path):
            console.print(f"[green]✓ ADB ready: {adb_path}[/green]")
            save_adb_config(adb_path)
            return adb_path
        else:
            console.print(f"[red]✗ ADB verification failed[/red]")
            return None
            
    except Exception as e:
        console.print(f"[red]✗ Setup failed: {e}[/red]")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        return None


def save_adb_config(adb_path: str):
    """Save ADB path to config file."""
    try:
        config = {"adb_path": adb_path}
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        # console.print(f"[green]✓ Config saved[/green]")
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


def interactive_adb_setup() -> Optional[str]:
    """
    Interactive ADB setup with multiple options.
    """
    while True:
        console.print(Panel(
            "[bold cyan]⚙️  ADB Configuration[/bold cyan]\n\n"
            "[1] Auto-setup (recommended)\n"
            "[2] Download platform-tools\n"
            "[3] Provide custom path\n"
            "[4] Cancel",
            title="Setup Option",
            border_style="cyan"
        ))
        
        choice = console.input("[bold]Select option (1-4): [/bold]")
        
        if choice == "1":
            return setup_adb_automatic()
        
        elif choice == "2":
            return download_and_setup_platform_tools()
        
        elif choice == "3":
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
        
        elif choice == "4":
            return None
        
        else:
            console.print("[red]Invalid choice[/red]")


def get_adb_path() -> Optional[str]:
    """
    Get ADB path - tries automatic setup first, then interactive.
    """
    # First try to load from config
    saved_path = load_adb_config()
    if saved_path:
        return saved_path
    
    # Try automatic setup
    adb_path = setup_adb_automatic()
    if adb_path:
        return adb_path
    
    # Fall back to interactive
    console.print("\n[yellow]Automatic setup failed. Please configure manually.[/yellow]\n")
    return interactive_adb_setup()
