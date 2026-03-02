#!/usr/bin/env python3
"""
GEMINI-Style UI Module
Beautiful, modern terminal UI styling for V Scanner CLI
"""

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.align import Align
from typing import List, Dict, Tuple
import time

console = Console()


# Color schemes - GEMINI inspired
COLORS = {
    "primary": "#5E35B1",      # Deep purple
    "secondary": "#00BCD4",    # Cyan
    "accent": "#FF5722",       # Deep orange
    "success": "#4CAF50",      # Green
    "warning": "#FFC107",      # Amber
    "danger": "#F44336",       # Red
    "info": "#2196F3",         # Blue
}


def print_gradient_banner():
    """Print an impressive GEMINI-style banner."""
    banner_text = """
    ╔════════════════════════════════════════════════════════════════════╗
    ║                                                                    ║
    ║         [bold cyan]█ ▀█▀ █   █   █ █ █ █  █ █ █ ██            [/bold cyan]            ║
    ║         [bold cyan]█  █  █   █   █ █ █ █ █ █ █  █  █           [/bold cyan]            ║
    ║         [bold cyan]█  █  █   █ █ █ █ █ █ █ █   ██  █           [/bold cyan]            ║
    ║                                                                    ║
    ║         [bold magenta]MOBILE    APPLICATION     SECURITY     SCANNER[/bold magenta]      ║
    ║                                                                    ║
    ║    [bold yellow]🔐 Scan • Analyze • Protect • Defend[/bold yellow]                        ║
    ║                                                                    ║
    ║    Version 2.0 | Enterprise Security | Real-time Analysis        ║
    ║                                                                    ║
    ╚════════════════════════════════════════════════════════════════════╝
    """
    console.print(banner_text)


def print_startup_animation():
    """Print animated startup sequence."""
    steps = [
        "[bold cyan]   ▹ Initializing Security Engine[/bold cyan]",
        "[bold cyan]   ▹ Loading Vulnerability Database[/bold cyan]",
        "[bold cyan]   ▹ Connecting to Android Device[/bold cyan]",
        "[bold cyan]   ▹ Syncing Device Configuration[/bold cyan]",
        "[bold cyan]   ▹ Preparing Analysis Framework[/bold cyan]",
    ]
    
    for step in steps:
        console.print(f"   {step}", end="\r", highlight=False)
        for _ in range(3):
            time.sleep(0.1)
            console.print(".", end="", highlight=False)
        console.print(" [bold green]✓[/bold green]")
        time.sleep(0.2)
    
    console.print()


def print_main_menu(device_info: str = None):
    """Print styled main menu."""
    menu_items = [
        ("1", "📱", "List Applications", "View all installed apps"),
        ("2", "🔍", "Analyze Single App", "Deep security analysis"),
        ("3", "🔒", "Full Device Scan", "Complete security audit"),
        ("4", "⚙️ ", "Admin Operations", "App control & management"),
        ("5", "📡", "Sensor Monitoring", "Track device sensors"),
        ("6", "ℹ️ ", "Full Device Info", "Complete device details"),
        ("7", "📊", "Demo Mode", "See sample results"),
        ("8", "🔄", "Change Device", "Switch to different device"),
        ("9", "⚙️ ", "Reconfigure ADB", "Update ADB settings"),
        ("10", "❌", "Exit", "Close application"),
    ]
    
    console.print("\n[bold cyan]╔════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]         🔒 MAIN MENU - V SCANNER              [bold cyan]║[/bold cyan]")
    console.print("[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n")
    
    for num, icon, title, desc in menu_items:
        if num == "10":
            console.print()
        
        if num == "10":
            color = "red"
        elif num in ["7", "8", "9"]:
            color = "yellow"
        else:
            color = "cyan"
        
        console.print(f"  [bold {color}]{num:<2}[/bold {color}]  {icon}  [bold white]{title:<25}[/bold white]  {desc}")
    
    console.print(f"\n  [dim]─────────────────────────────────────[/dim]")


def print_device_selector_animation(devices: List[str]):
    """Print animated device selection."""
    console.print("\n[bold cyan]🔍 Scanning for Android Devices...[/bold cyan]\n")
    
    spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    
    for _ in range(5):
        for char in spinner_chars:
            console.print(f"   {char} Searching...", end="\r")
            time.sleep(0.05)
    
    console.print(f"   [bold green]✓ Found {len(devices)} device(s)[/bold green]           \n")
    time.sleep(0.3)
    
    # Display devices
    table = Table(box=box.ROUNDED, border_style="cyan")
    table.add_column("[bold cyan]#[/bold cyan]", style="yellow", width=3)
    table.add_column("[bold cyan]Device ID[/bold cyan]", style="cyan")
    table.add_column("[bold cyan]Status[/bold cyan]", style="green")
    
    for i, device in enumerate(devices, 1):
        table.add_row(str(i), device, "[bold green]●[/bold green] Connected")
    
    console.print(table)


def print_scanning_progress(current: int, total: int, app_name: str):
    """Print scanning progress with styled output."""
    percent = (current / total) * 100
    filled = int(percent / 5)
    empty = 20 - filled
    
    progress_bar = f"[bold cyan]{'█' * filled}{'░' * empty}[/bold cyan]"
    
    console.print(
        f"\n  [bold cyan]Scanning:[/bold cyan] {app_name:<30} "
        f"{progress_bar} {percent:>5.1f}%\n",
        end="\r"
    )


def print_security_score_card(score: int, total_apps: int, risk_breakdown: Dict[str, int]):
    """Print styled security score card."""
    
    # Determine color based on score
    if score >= 80:
        score_color = "green"
        emoji = "🟢"
    elif score >= 60:
        score_color = "yellow"
        emoji = "🟡"
    else:
        score_color = "red"
        emoji = "🔴"
    
    score_display = f"[bold {score_color}]{score}[/bold {score_color}]"
    
    card = f"""
[bold cyan]┌─────────────────────────────────────┐[/bold cyan]
[bold cyan]│[/bold cyan]      [bold magenta]DEVICE SECURITY SCORE[/bold magenta]          [bold cyan]│[/bold cyan]
[bold cyan]├─────────────────────────────────────┤[/bold cyan]
[bold cyan]│[/bold cyan]                                       [bold cyan]│[/bold cyan]
[bold cyan]│[/bold cyan]         {emoji} [{score_display}/100]                      [bold cyan]│[/bold cyan]
[bold cyan]│[/bold cyan]                                       [bold cyan]│[/bold cyan]
[bold cyan]├─────────────────────────────────────┤[/bold cyan]
[bold cyan]│[/bold cyan]  [bold white]Total Apps:[/bold white]    {str(total_apps):<20}  [bold cyan]│[/bold cyan]
[bold cyan]│[/bold cyan]  [bold red]🔴 High Risk:[/bold red]   {str(risk_breakdown.get('high', 0)):<20}  [bold cyan]│[/bold cyan]
[bold cyan]│[/bold cyan]  [bold yellow]🟡 Medium Risk:[/bold yellow]  {str(risk_breakdown.get('medium', 0)):<20}  [bold cyan]│[/bold cyan]
[bold cyan]│[/bold cyan]  [bold green]🟢 Low Risk:[/bold green]    {str(risk_breakdown.get('low', 0)):<20}  [bold cyan]│[/bold cyan]
[bold cyan]│[/bold cyan]                                       [bold cyan]│[/bold cyan]
[bold cyan]└─────────────────────────────────────┘[/bold cyan]
    """
    console.print(card)


def print_app_analysis_header(app_name: str, package: str):
    """Print styled app analysis header."""
    console.print("\n[bold cyan]╔════════════════════════════════════════════╗[/bold cyan]")
    console.print(f"[bold cyan]║[/bold cyan]  [bold magenta]🔎 SECURITY ANALYSIS[/bold magenta]")
    console.print("[bold cyan]║[/bold cyan]")
    console.print(f"[bold cyan]║[/bold cyan]  [bold cyan]Application:[/bold cyan] {app_name}")
    console.print(f"[bold cyan]║[/bold cyan]  [bold cyan]Package:[/bold cyan] {package}")
    console.print("[bold cyan]╚════════════════════════════════════════════╝[/bold cyan]\n")


def print_permission_alert(permission: str, risk_level: str, description: str):
    """Print styled permission alert."""
    if risk_level == "HIGH":
        icon = "🔴"
        color = "red"
    elif risk_level == "MEDIUM":
        icon = "🟡"
        color = "yellow"
    else:
        icon = "🟢"
        color = "green"
    
    risk_display = f"[bold {color}]{risk_level}[/bold {color}]"
    console.print(f"  {icon} {risk_display} [bold cyan]{permission}[/bold cyan] - {description}")


def print_loading_spinner(message: str = "Loading", duration: float = 1.0):
    """Print a loading spinner."""
    spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    start_time = time.time()
    
    while time.time() - start_time < duration:
        for char in spinner_chars:
            console.print(f"  {char} {message}...", end="\r")
            time.sleep(0.05)


def print_success_message(title: str, message: str):
    """Print a success message."""
    console.print(Panel(
        f"[bold green]{title}[/bold green]\n\n{message}",
        border_style="green",
        padding=(1, 2)
    ))


def print_error_message(title: str, message: str):
    """Print an error message."""
    console.print(Panel(
        f"[bold red]{title}[/bold red]\n\n{message}",
        border_style="red",
        padding=(1, 2)
    ))


def print_warning_message(title: str, message: str):
    """Print a warning message."""
    console.print(Panel(
        f"[bold yellow]{title}[/bold yellow]\n\n{message}",
        border_style="yellow",
        padding=(1, 2)
    ))


def print_info_message(title: str, message: str):
    """Print an info message."""
    console.print(Panel(
        f"[bold cyan]{title}[/bold cyan]\n\n{message}",
        border_style="cyan",
        padding=(1, 2)
    ))


def print_risk_summary_table(apps_by_risk: Dict[str, List]):
    """Print a summary of apps by risk level."""
    table = Table(title="[bold]Risk Analysis Summary[/bold]", box=box.ROUNDED, border_style="cyan")
    
    table.add_column("Risk Level", style="bold")
    table.add_column("Count", style="yellow")
    table.add_column("Top Apps", style="cyan")
    
    for risk, apps in apps_by_risk.items():
        if risk == "HIGH":
            risk_display = "[bold red]🔴 HIGH[/bold red]"
        elif risk == "MEDIUM":
            risk_display = "[bold yellow]🟡 MEDIUM[/bold yellow]"
        else:
            risk_display = "[bold green]🟢 LOW[/bold green]"
        
        count = len(apps)
        top_apps = ", ".join(apps[:3]) if apps else "None"
        
        table.add_row(risk_display, str(count), top_apps)
    
    console.print(table)


def print_divider(length: int = 50, style: str = "cyan"):
    """Print a styled divider."""
    console.print(f"[bold {style}]{'─' * length}[/bold {style}]")


def create_gradient_text(text: str, start_color: str = "cyan", end_color: str = "magenta") -> Text:
    """Create a gradient text effect (simplified version)."""
    # In a real implementation, you'd calculate colors between start and end
    # For now, we'll alternate
    result = Text()
    for i, char in enumerate(text):
        if i % 2 == 0:
            result.append(char, style=f"bold {start_color}")
        else:
            result.append(char, style=f"bold {end_color}")
    return result


def print_scan_complete_animation():
    """Print scan complete animation."""
    console.print("\n[bold green]")
    console.print("   ╔═══════════════════════════════╗")
    console.print("   ║   ✓ SCAN COMPLETE             ║")
    console.print("   ║                               ║")
    console.print("   ║   Analysis successful!        ║")
    console.print("   ║   Report is ready for review  ║")
    console.print("   ║                               ║")
    console.print("   ╚═══════════════════════════════╝")
    console.print("[/bold green]\n")


def print_footer():
    """Print styled footer."""
    console.print("\n[bold cyan]╔════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]     [bold yellow]V Scanner 2.0[/bold yellow] • Enterprise Security Edition")
    console.print("[bold cyan]║[/bold cyan]     [bold dim]Powered by Android Security Framework[/bold dim]")
    console.print("[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n")
