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

REQUIRED_PACKAGES = [
    'adb-shell',
    'rich',
    'click',
    'jinja2',
    'requests',
    'pyyaml',
    'colorama',
    'tabulate'
]

# Map pip package names to their import names (some differ)
PACKAGE_IMPORT_MAP = {
    'adb-shell': 'adb_shell',
    'pyyaml': 'yaml',
    'jinja2': 'jinja2',
    'colorama': 'colorama',
    'tabulate': 'tabulate',
    'rich': 'rich',
    'click': 'click',
    'requests': 'requests'
}


def check_python_packages():
    """Check if required Python packages are installed."""
    missing_packages = []
    
    for package in REQUIRED_PACKAGES:
        # Get the import name (may differ from package name)
        import_name = PACKAGE_IMPORT_MAP.get(package, package.replace('-', '_'))
        
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package)
    
    return missing_packages


def check_scrcpy():
    """Check if scrcpy is installed."""
    try:
        from tools_manager import check_tool_exists
        return check_tool_exists('scrcpy')
    except:
        # Fallback to system check
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


def check_all_dependencies():
    """Check all dependencies and display status."""
    console.print("\n[bold cyan]🔍 Checking Dependencies...[/bold cyan]\n")
    
    # Create status table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="white")
    
    status = {
        'python_packages': True,
        'adb': True,
        'scrcpy': True
    }
    
    # Check Python packages
    missing_packages = check_python_packages()
    status['python_packages'] = len(missing_packages) == 0
    table.add_row(
        "Python Packages",
        "[green]✓ All installed[/green]" if status['python_packages'] else f"[red]✗ Missing: {', '.join(missing_packages)}[/red]"
    )
    
    # Check ADB (Required)
    adb_ok = check_adb()
    status['adb'] = adb_ok
    table.add_row(
        "ADB (Android Debug Bridge)",
        "[green]✓ Available[/green]" if adb_ok else "[yellow]⚠ Not found[/yellow]"
    )
    
    # Check scrcpy (Required for Screen Share)
    scrcpy_ok = check_scrcpy()
    status['scrcpy'] = scrcpy_ok
    table.add_row(
        "scrcpy (Screen Mirroring)",
        "[green]✓ Installed[/green]" if scrcpy_ok else "[red]✗ Not installed[/red]"
    )
    
    console.print(table)
    
    # Check if all required components are ok
    all_ok = all(status.values())
    
    if all_ok:
        console.print("\n[bold green]✓ All dependencies are ready![/bold green]\n")
    else:
        missing = [k for k, v in status.items() if not v]
        console.print(f"\n[bold yellow]⚠️  Some required components are missing: {', '.join(missing)}[/bold yellow]\n")
    
    return all_ok


if __name__ == '__main__':
    check_all_dependencies()
