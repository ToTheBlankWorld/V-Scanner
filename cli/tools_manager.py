#!/usr/bin/env python3
"""
Tools Manager for V Scanner
Downloads and manages ADB and scrcpy in local tools folder
"""

import os
import subprocess
import sys
import platform
import zipfile
import tarfile
import shutil
from pathlib import Path
from urllib.request import urlopen
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

# Get the tools directory (relative to this script)
TOOLS_DIR = Path(__file__).parent / "tools"
TOOLS_DIR.mkdir(exist_ok=True)

# Platform detection
OS_TYPE = platform.system()  # "Windows", "Darwin" (macOS), "Linux"
ARCH = platform.machine()    # "x86_64", "arm64", etc.


def get_adb_download_url() -> str:
    """Get the download URL for ADB based on OS."""
    base_url = "https://dl.google.com/android/repository"

    if OS_TYPE == "Windows":
        return f"{base_url}/platform-tools-latest-windows.zip"
    elif OS_TYPE == "Darwin":
        return f"{base_url}/platform-tools-latest-darwin.zip"
    else:  # Linux
        return f"{base_url}/platform-tools-latest-linux.zip"


def get_scrcpy_download_url() -> str:
    """Get the download URL for scrcpy based on OS.
    Fetches latest release from GitHub API to ensure correct URL."""
    try:
        import json as json_module
        from urllib.request import urlopen as url_open

        # Get latest release info from GitHub API
        api_url = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
        with url_open(api_url, timeout=10) as response:
            release_data = json_module.load(response)
            assets = release_data.get("assets", [])

            # Find the correct asset based on OS
            if OS_TYPE == "Windows":
                # Look for Windows ZIP file
                for asset in assets:
                    if "win64" in asset["name"].lower() and asset["name"].endswith(".zip"):
                        return asset["browser_download_url"]

            elif OS_TYPE == "Darwin":  # macOS
                if ARCH == "arm64":
                    # Look for ARM64 macOS
                    for asset in assets:
                        if "macos" in asset["name"].lower() and "arm64" in asset["name"].lower() and asset["name"].endswith(".tar.gz"):
                            return asset["browser_download_url"]
                else:
                    # Look for x86_64 macOS
                    for asset in assets:
                        if "macos" in asset["name"].lower() and "x86_64" in asset["name"].lower() and asset["name"].endswith(".tar.gz"):
                            return asset["browser_download_url"]

            else:  # Linux
                # Look for Linux tar.gz
                for asset in assets:
                    if "linux" in asset["name"].lower() and asset["name"].endswith(".tar.gz"):
                        return asset["browser_download_url"]
    except Exception as e:
        console.print(f"[yellow]⚠ Could not fetch latest release: {e}[/yellow]")

    # Fallback to known working version if API fails
    base_url = "https://github.com/Genymobile/scrcpy/releases/download/v2.4"

    if OS_TYPE == "Windows":
        return f"{base_url}/scrcpy-2.4-win64-v4.zip"
    elif OS_TYPE == "Darwin":
        if ARCH == "arm64":
            return f"{base_url}/scrcpy-2.4-macos-arm64-v4.tar.gz"
        else:
            return f"{base_url}/scrcpy-2.4-macos-x86_64-v4.tar.gz"
    else:  # Linux
        return f"{base_url}/scrcpy-2.4-linux-x86_64-v4.tar.gz"


def download_file(url: str, dest_path: Path) -> bool:
    """Download a file with progress bar and retry logic."""
    max_retries = 3
    retry_delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            console.print(f"[cyan]Downloading from: {url}[/cyan]")
            if attempt > 0:
                console.print(f"[yellow]Attempt {attempt + 1} of {max_retries}[/yellow]")

            with urlopen(url, timeout=30) as response:
                total_size = int(response.headers.get('Content-Length', 0))

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console
                ) as progress:
                    task = progress.add_task(f"[cyan]Downloading...", total=total_size or None)

                    with open(dest_path, 'wb') as f:
                        chunk_size = 8192
                        while True:
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            progress.advance(task, len(chunk))

            console.print(f"[green]✓ Downloaded successfully[/green]")
            return True
        except Exception as e:
            console.print(f"[yellow]✗ Download attempt {attempt + 1} failed: {e}[/yellow]")
            if attempt < max_retries - 1:
                import time
                console.print(f"[cyan]Retrying in {retry_delay} seconds...[/cyan]")
                time.sleep(retry_delay)
            else:
                console.print(f"[red]✗ Download failed after {max_retries} attempts[/red]")

    return False


def extract_windows_zip(zip_path: Path, extract_to: Path):
    """Extract Windows ZIP file."""
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)


def extract_unix_tar(tar_path: Path, extract_to: Path):
    """Extract Unix TAR.GZ file."""
    with tarfile.open(tar_path, 'r:gz') as tar_ref:
        tar_ref.extractall(extract_to)


def setup_adb() -> bool:
    """Download and setup ADB if not present."""
    adb_path = TOOLS_DIR / "platform-tools"

    # Check if ADB already exists
    if OS_TYPE == "Windows":
        adb_exe = adb_path / "adb.exe"
    else:
        adb_exe = adb_path / "adb"

    if adb_exe.exists():
        console.print(f"[green]✓ ADB already installed[/green]")
        return True

    console.print("[bold cyan]📥 Setting up ADB (Android Debug Bridge)...[/bold cyan]")

    # Download ADB
    adb_url = get_adb_download_url()
    archive_path = TOOLS_DIR / "adb.zip" if OS_TYPE == "Windows" else TOOLS_DIR / "adb.tar.gz"

    if not download_file(adb_url, archive_path):
        console.print(f"[red]✗ Failed to download ADB[/red]")
        return False

    # Extract
    try:
        if OS_TYPE == "Windows":
            console.print("[cyan]Extracting ADB...[/cyan]")
            console.print(f"[dim]Extracting to: {TOOLS_DIR}[/dim]")
            extract_windows_zip(TOOLS_DIR / "adb.zip", TOOLS_DIR)
            (TOOLS_DIR / "adb.zip").unlink()  # Clean up
        else:
            console.print("[cyan]Extracting ADB...[/cyan]")
            console.print(f"[dim]Extracting to: {TOOLS_DIR}[/dim]")
            extract_unix_tar(TOOLS_DIR / "adb.tar.gz", TOOLS_DIR)
            (TOOLS_DIR / "adb.tar.gz").unlink()  # Clean up

        # Make executable on Unix
        if OS_TYPE != "Windows":
            os.chmod(adb_exe, 0o755)

        # Verify extraction was successful
        if not adb_exe.exists():
            console.print(f"[red]✗ ADB file not found after extraction at {adb_exe}[/red]")
            console.print(f"[dim]Contents of {TOOLS_DIR}:[/dim]")
            try:
                for item in TOOLS_DIR.iterdir():
                    console.print(f"[dim]  - {item.name}[/dim]")
            except:
                pass
            return False

        console.print("[green]✓ ADB installed successfully![/green]")
        return True
    except Exception as e:
        console.print(f"[red]✗ Failed to extract ADB: {e}[/red]")
        return False


def setup_scrcpy() -> bool:
    """Download and setup scrcpy if not present."""
    if OS_TYPE == "Windows":
        scrcpy_exe = TOOLS_DIR / "scrcpy" / "scrcpy.exe"
    else:
        scrcpy_exe = TOOLS_DIR / "scrcpy" / "scrcpy"

    if scrcpy_exe.exists():
        console.print(f"[green]✓ scrcpy already installed[/green]")
        return True

    console.print("[bold cyan]📥 Setting up scrcpy (Screen Mirroring)...[/bold cyan]")

    # Download scrcpy
    scrcpy_url = get_scrcpy_download_url()
    archive_name = "scrcpy.zip" if OS_TYPE == "Windows" else "scrcpy.tar.gz"
    archive_path = TOOLS_DIR / archive_name

    if not download_file(scrcpy_url, archive_path):
        return False

    # Extract
    try:
        console.print("[cyan]Extracting scrcpy...[/cyan]")
        extract_dir = TOOLS_DIR / "scrcpy_temp"
        os.makedirs(extract_dir, exist_ok=True)

        if OS_TYPE == "Windows":
            console.print(f"[dim]Extracting ZIP to temp: {extract_dir}[/dim]")
            extract_windows_zip(archive_path, extract_dir)

            # Handle scrcpy zip which extracts to scrcpy-VERSION/
            extracted_items = list(extract_dir.glob("scrcpy-*"))
            console.print(f"[dim]Found {len(extracted_items)} extracted items[/dim]")

            if extracted_items:
                # Move contents from scrcpy-VERSION/ to scrcpy/
                src_dir = extracted_items[0]
                dst_dir = TOOLS_DIR / "scrcpy"
                console.print(f"[dim]Moving {src_dir.name} to {dst_dir}[/dim]")

                if dst_dir.exists():
                    shutil.rmtree(dst_dir)
                shutil.move(str(src_dir), str(dst_dir))
                console.print(f"[dim]Successfully moved scrcpy folder[/dim]")
            else:
                console.print(f"[yellow]⚠ No scrcpy-* folder found in {extract_dir}[/yellow]")
                console.print(f"[dim]Contents of temp folder:[/dim]")
                try:
                    for item in extract_dir.iterdir():
                        console.print(f"[dim]  - {item.name}[/dim]")
                except:
                    pass

        else:
            console.print(f"[dim]Extracting TAR.GZ to temp: {extract_dir}[/dim]")
            extract_unix_tar(archive_path, extract_dir)

            # Handle scrcpy tar.gz which extracts to scrcpy-VERSION/
            extracted_items = list(extract_dir.glob("scrcpy-*"))
            console.print(f"[dim]Found {len(extracted_items)} extracted items[/dim]")

            if extracted_items:
                # Move contents from scrcpy-VERSION/ to scrcpy/
                src_dir = extracted_items[0]
                dst_dir = TOOLS_DIR / "scrcpy"
                console.print(f"[dim]Moving {src_dir.name} to {dst_dir}[/dim]")

                if dst_dir.exists():
                    shutil.rmtree(dst_dir)
                shutil.move(str(src_dir), str(dst_dir))
                console.print(f"[dim]Successfully moved scrcpy folder[/dim]")
            else:
                console.print(f"[yellow]⚠ No scrcpy-* folder found in {extract_dir}[/yellow]")
                console.print(f"[dim]Contents of temp folder:[/dim]")
                try:
                    for item in extract_dir.iterdir():
                        console.print(f"[dim]  - {item.name}[/dim]")
                except:
                    pass

        # Clean up temp directory
        if extract_dir.exists():
            shutil.rmtree(extract_dir)

        archive_path.unlink()  # Clean up

        # Make executable on Unix
        if OS_TYPE != "Windows":
            if scrcpy_exe.exists():
                os.chmod(scrcpy_exe, 0o755)

        # Verify extraction was successful
        if not scrcpy_exe.exists():
            console.print(f"[red]✗ scrcpy file not found after extraction at {scrcpy_exe}[/red]")
            console.print(f"[dim]Contents of scrcpy folder:[/dim]")
            scrcpy_folder = TOOLS_DIR / "scrcpy"
            if scrcpy_folder.exists():
                try:
                    for item in scrcpy_folder.iterdir():
                        console.print(f"[dim]  - {item.name}[/dim]")
                except:
                    pass
            else:
                console.print(f"[dim]  scrcpy folder doesn't exist at {scrcpy_folder}[/dim]")
            return False

        console.print("[green]✓ scrcpy installed successfully![/green]")
        return True
    except Exception as e:
        console.print(f"[red]✗ Failed to extract scrcpy: {e}[/red]")
        return False


def get_adb_path() -> str:
    """Get the path to ADB executable."""
    if OS_TYPE == "Windows":
        adb_exe = TOOLS_DIR / "platform-tools" / "adb.exe"
    else:
        adb_exe = TOOLS_DIR / "platform-tools" / "adb"

    return str(adb_exe)


def get_scrcpy_path() -> str:
    """Get the path to scrcpy executable."""
    if OS_TYPE == "Windows":
        scrcpy_exe = TOOLS_DIR / "scrcpy" / "scrcpy.exe"
    else:
        scrcpy_exe = TOOLS_DIR / "scrcpy" / "scrcpy"

    return str(scrcpy_exe)


def check_tool_exists(tool_type: str) -> bool:
    """Check if a tool exists locally."""
    if tool_type == "adb":
        path = Path(get_adb_path())
        exists = path.exists()
        if not exists:
            console.print(f"[dim]DEBUG: ADB not found at {path}[/dim]")
        return exists
    elif tool_type == "scrcpy":
        path = Path(get_scrcpy_path())
        exists = path.exists()
        if not exists:
            console.print(f"[dim]DEBUG: scrcpy not found at {path}[/dim]")
        return exists
    return False


def ensure_tools():
    """Ensure both ADB and scrcpy are available."""
    console.print("\n[bold cyan]🔧 Tool Setup[/bold cyan]\n")
    console.print(f"[dim]Tools directory: {TOOLS_DIR}[/dim]")

    # Setup ADB (Essential)
    if not check_tool_exists("adb"):
        console.print("[cyan]ADB not found locally. Downloading...[/cyan]")
        if not setup_adb():
            console.print("[red]✗ Failed to setup ADB. This is required![/red]")
            return False
    else:
        console.print(f"[green]✓ ADB available at {get_adb_path()}[/green]")

    # Setup scrcpy (Optional)
    if not check_tool_exists("scrcpy"):
        console.print("[yellow]scrcpy not found locally. Downloading...[/yellow]")
        if not setup_scrcpy():
            console.print("[yellow]⚠️  scrcpy setup failed. Screen Mirroring won't work.[/yellow]")
        else:
            console.print(f"[green]✓ scrcpy available at {get_scrcpy_path()}[/green]")
    else:
        console.print(f"[green]✓ scrcpy available at {get_scrcpy_path()}[/green]")

    console.print()
    return True


if __name__ == "__main__":
    ensure_tools()
    print(f"\nADB: {get_adb_path()}")
    print(f"scrcpy: {get_scrcpy_path()}")
