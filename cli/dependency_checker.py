"""
Dependency checker for V Scanner
Verifies all required packages, tools, and drivers are installed
"""

import subprocess
import sys
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def check_python_packages():
    """Check if required Python packages are installed."""
    required_packages = [
        'adb-shell',
        'rich',
        'click',
        'jinja2',
        'requests',
        'pyyaml',
        'colorama',
        'tabulate'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing_packages.append(package)
    
    return missing_packages


def check_scrcpy():
    """Check if scrcpy is installed."""
    try:
        result = subprocess.run(
            ['scrcpy', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False


def check_adb():
    """Check if ADB is available."""
    try:
        result = subprocess.run(
            ['adb', 'version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False


def install_python_packages(packages):
    """Install missing Python packages."""
    if not packages:
        return True
    
    console.print("\n[bold yellow]Installing missing Python packages...[/bold yellow]")
    
    try:
        for package in packages:
            console.print(f"[cyan]Installing {package}...[/cyan]", end=" ")
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', package, '-q'],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                console.print("[green]✓[/green]")
            else:
                console.print("[red]✗[/red]")
                return False
        return True
    except Exception as e:
        console.print(f"[red]Error installing packages: {str(e)}[/red]")
        return False


def install_scrcpy():
    """Install scrcpy using system package manager."""
    console.print("\n[bold yellow]Installing scrcpy...[/bold yellow]")
    
    system = sys.platform
    
    if system == 'win32':
        # Windows - use Scoop
        console.print("[cyan]Attempting installation via Scoop (Windows)...[/cyan]")
        try:
            result = subprocess.run(
                ['powershell', '-Command', 
                 'Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force; scoop install scrcpy'],
                capture_output=True,
                text=True,
                timeout=180
            )
            if result.returncode == 0:
                console.print("[green]✓ scrcpy installed successfully[/green]")
                return True
        except:
            pass
        
        # Fallback: Show manual instructions
        console.print("\n[bold red]⚠️  Could not auto-install scrcpy via Scoop[/bold red]")
        console.print("[yellow]Manual Installation Options for Windows:[/yellow]")
        console.print("[cyan]Option 1 - Scoop (recommended):[/cyan]")
        console.print("  [dim]scoop install scrcpy[/dim]")
        console.print("[cyan]Option 2 - Chocolatey:[/cyan]")
        console.print("  [dim]choco install scrcpy[/dim]")
        console.print("[cyan]Option 3 - Download from GitHub:[/cyan]")
        console.print("  [dim]https://github.com/Genymobile/scrcpy/releases[/dim]")
        return False
    
    elif system == 'darwin':
        # macOS - use Homebrew
        console.print("[cyan]Attempting installation via Homebrew (macOS)...[/cyan]")
        try:
            result = subprocess.run(
                ['brew', 'install', 'scrcpy'],
                capture_output=True,
                text=True,
                timeout=180
            )
            if result.returncode == 0:
                console.print("[green]✓ scrcpy installed successfully[/green]")
                return True
        except:
            pass
        
        console.print("\n[bold red]⚠️  Could not auto-install scrcpy via Homebrew[/bold red]")
        console.print("[yellow]Manual Installation for macOS:[/yellow]")
        console.print("  [dim]brew install scrcpy[/dim]")
        return False
    
    elif system == 'linux':
        # Linux - use apt
        console.print("[cyan]Attempting installation via apt (Linux)...[/cyan]")
        try:
            result = subprocess.run(
                ['sudo', 'apt', 'update'],
                capture_output=True,
                text=True,
                timeout=120
            )
            result = subprocess.run(
                ['sudo', 'apt', 'install', '-y', 'scrcpy'],
                capture_output=True,
                text=True,
                timeout=180
            )
            if result.returncode == 0:
                console.print("[green]✓ scrcpy installed successfully[/green]")
                return True
        except:
            pass
        
        console.print("\n[bold red]⚠️  Could not auto-install scrcpy via apt[/bold red]")
        console.print("[yellow]Manual Installation for Linux:[/yellow]")
        console.print("  [dim]sudo apt install scrcpy[/dim]")
        return False
    
    return False


def check_all_dependencies():
    """Check all dependencies and return status."""
    console.print("\n[bold cyan]🔍 Checking Dependencies...[/bold cyan]\n")
    
    # Create status table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="white")
    
    status = {
        'python_packages': True,
        'scrcpy': True,
        'adb': True
    }
    
    # Check Python packages
    missing_packages = check_python_packages()
    status['python_packages'] = len(missing_packages) == 0
    table.add_row(
        "Python Packages",
        "[green]✓ All installed[/green]" if status['python_packages'] else f"[red]✗ Missing: {', '.join(missing_packages)}[/red]"
    )
    
    # Check scrcpy
    scrcpy_ok = check_scrcpy()
    status['scrcpy'] = scrcpy_ok
    table.add_row(
        "scrcpy (Screen Mirroring)",
        "[green]✓ Installed[/green]" if scrcpy_ok else "[yellow]⚠ Not installed[/yellow]"
    )
    
    # Check ADB
    adb_ok = check_adb()
    status['adb'] = adb_ok
    table.add_row(
        "ADB (Android Debug Bridge)",
        "[green]✓ Available[/green]" if adb_ok else "[yellow]⚠ Not found[/yellow]"
    )
    
    console.print(table)
    
    # Handle missing components
    missing_items = []
    
    if not status['python_packages']:
        missing_items.append(('Python Packages', missing_packages))
    
    if not status['scrcpy']:
        missing_items.append(('scrcpy', None))
    
    if not status['adb']:
        missing_items.append(('ADB', None))
    
    if missing_items:
        console.print("\n[bold yellow]Installing missing components...[/bold yellow]")
        
        for component, details in missing_items:
            if component == 'Python Packages':
                if not install_python_packages(details):
                    console.print(f"\n[red]✗ Failed to install {component}[/red]")
                    console.print("[yellow]Try manually:[/yellow]")
                    console.print(f"  [dim]pip install {' '.join(details)}[/dim]")
            
            elif component == 'scrcpy':
                if not install_scrcpy():
                    console.print("[yellow]Install scrcpy manually and restart[/yellow]")
            
            elif component == 'ADB':
                console.print("\n[bold red]✗ ADB (Android Debug Bridge) not found[/bold red]")
                console.print("[yellow]Install Android SDK Platform Tools:[/yellow]")
                if sys.platform == 'win32':
                    console.print("  [dim]Download: https://developer.android.com/studio/releases/platform-tools[/dim]")
                    console.print("  [dim]Or: choco install android-sdk[/dim]")
                elif sys.platform == 'darwin':
                    console.print("  [dim]brew install android-platform-tools[/dim]")
                else:
                    console.print("  [dim]sudo apt install android-tools-adb[/dim]")
    
    # Final status
    all_ok = all(status.values())
    
    if all_ok:
        console.print("\n[bold green]✓ All dependencies are installed and ready![/bold green]")
        console.print("[green]The V Scanner app is ready to use.[/green]\n")
    else:
        missing = [k for k, v in status.items() if not v]
        console.print(f"\n[bold yellow]⚠️  Some components are missing: {', '.join(missing)}[/bold yellow]")
        console.print("[yellow]The app may have limited functionality until all are installed.[/yellow]\n")
    
    return all_ok


if __name__ == '__main__':
    check_all_dependencies()
