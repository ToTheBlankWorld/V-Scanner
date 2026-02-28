#!/usr/bin/env python3
"""
V Scanner - Main Interactive CLI
Automatically detects connected devices and provides an interactive menu
GEMINI-Style beautiful terminal UI with automated ADB setup
"""

import os
import sys
import subprocess
import json
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from scanner import ADBInterface, VulnerabilityScanner
from report_generator import ReportGenerator
from adb_setup import get_adb_path, load_adb_config, save_adb_config, check_adb_valid
from ui_styles import (
    print_gradient_banner, print_startup_animation, print_main_menu,
    print_device_selector_animation, print_success_message, print_error_message,
    print_warning_message, print_info_message, print_footer, print_scan_complete_animation
)

console = Console()

# Store ADB path globally
ADB_PATH = None
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "adb_config.json")


def load_adb_config() -> Optional[str]:
    """Load saved ADB path from config file."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                saved_path = config.get("adb_path")
                
                # Verify the saved path still exists and is valid
                if saved_path and check_adb_valid(saved_path):
                    return saved_path
    except:
        pass
    
    return None


def save_adb_config(adb_path: str):
    """Save ADB path to config file."""
    try:
        config = {"adb_path": adb_path}
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not save ADB config: {e}[/yellow]")

# Store ADB path globally
ADB_PATH = None


def find_adb() -> Optional[str]:
    """
    Find or setup ADB executable.
    Uses automatic setup from adb_setup module.
    """
    global ADB_PATH
    
    # Try to load saved config first
    saved_path = load_adb_config()
    if saved_path:
        console.print(f"[green]✓ Using saved ADB configuration[/green]")
        ADB_PATH = saved_path
        return saved_path
    
    # Use automated setup
    from adb_setup import get_adb_path as automated_get_adb
    adb_path = automated_get_adb()
    
    if adb_path:
        ADB_PATH = adb_path
        return adb_path
    
    console.print("[red]✗ Failed to setup ADB[/red]")
    return None


def get_adb_interface(device: str = None) -> ADBInterface:
    """Get ADBInterface with configured ADB path."""
    adb = ADBInterface(device)
    if ADB_PATH:
        adb.adb_cmd = [ADB_PATH]
        if device:
            adb.adb_cmd.extend(["-s", device])
    return adb


def get_available_devices() -> list:
    """Get list of all connected ADB devices."""
    try:
        adb = get_adb_interface()
        stdout, stderr, code = adb._run_cmd(["devices"])
        
        if code != 0 or "not found" in stderr.lower():
            return []
        
        devices = []
        lines = stdout.strip().split('\n')[1:]  # Skip header
        
        for line in lines:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        
        return devices
    except Exception as e:
        console.print(f"[red]Error getting devices: {e}[/red]")
        return []


def select_device() -> Optional[str]:
    """Display available devices and let user select one."""
    devices = get_available_devices()
    
    if not devices:
        print_error_message(
            "❌ No Devices Found",
            "Please ensure:\n"
            "• USB debugging is enabled on your device\n"
            "• Device is connected via USB cable\n"
            "• Tap 'Allow' when prompted on device\n"
            "• ADB is properly configured"
        )
        
        console.print("[yellow]Would you like to reconfigure ADB path?[/yellow]")
        console.print("[1] Yes, reconfigure ADB")
        console.print("[2] No, go back to menu")
        choice = console.input("\n[bold]Select: [/bold]")
        
        if choice == "1":
            find_adb()
            # Try again
            return select_device()
        
        return None
    
    if len(devices) == 1:
        console.print(f"[green]✓ Device found: {devices[0]}[/green]")
        return devices[0]
    
    # Multiple devices - show animated selection
    print_device_selector_animation(devices)
    
    while True:
        try:
            choice = int(console.input("\n[bold cyan]Select device (enter number): [/bold cyan]"))
            if 1 <= choice <= len(devices):
                return devices[choice - 1]
            else:
                console.print("[red]❌ Invalid selection![/red]")
        except ValueError:
            console.print("[red]❌ Please enter a valid number[/red]")


def display_device_info(device: str):
    """Display information about the selected device."""
    adb = get_adb_interface(device)
    info = adb.get_device_info()
    
    console.print(Panel(
        f"[bold]Device ID:[/bold] {device}\n"
        f"[bold]Manufacturer:[/bold] {info.get('manufacturer', 'Unknown')}\n"
        f"[bold]Model:[/bold] {info.get('model', 'Unknown')}\n"
        f"[bold]Android Version:[/bold] {info.get('android_version', 'Unknown')}\n"
        f"[bold]SDK Level:[/bold] {info.get('sdk_version', 'Unknown')}\n"
        f"[bold]Security Patch:[/bold] {info.get('security_patch', 'Unknown')}",
        title="📱 Device Information",
        border_style="cyan"
    ))


def list_apps_menu(device: str):
    """Menu to list installed apps."""
    adb = get_adb_interface(device)
    
    console.print("\n[bold]Include system apps?[/bold]")
    console.print("[1] No (third-party apps only)")
    console.print("[2] Yes (all apps)")
    
    while True:
        choice = console.input("\n[bold]Select (1 or 2): [/bold]")
        if choice in ["1", "2"]:
            include_system = choice == "2"
            break
        console.print("[red]Invalid choice[/red]")
    
    console.print("\n[cyan]📲 Fetching installed apps...[/cyan]\n")
    
    packages = adb.list_packages(include_system)
    
    if not packages:
        console.print("[yellow]No apps found[/yellow]")
        return
    
    table = Table(title="Installed Applications", box=box.ROUNDED)
    table.add_column("#", style="dim", width=4)
    table.add_column("Package Name", style="cyan")
    table.add_column("App Name", style="green")
    
    for i, pkg in enumerate(packages, 1):
        app_name = adb.get_app_label(pkg)
        table.add_row(str(i), pkg, app_name)
    
    console.print(table)
    console.print(f"\n[bold cyan]Total: {len(packages)} apps[/bold cyan]")


def analyze_app_menu(device: str):
    """Menu to analyze a specific app."""
    adb = get_adb_interface(device)
    
    package = console.input("[bold]Enter package name to analyze: [/bold]")
    
    if not package.strip():
        console.print("[red]No package specified[/red]")
        return
    
    console.print("\n[yellow]Enable deep APK analysis? (slower)[/yellow]")
    console.print("[1] No (quick analysis)")
    console.print("[2] Yes (search for URLs and hardcoded values)")
    
    while True:
        choice = console.input("\n[bold]Select (1 or 2): [/bold]")
        if choice in ["1", "2"]:
            deep_scan = choice == "2"
            break
        console.print("[red]Invalid choice[/red]")
    
    console.print(f"\n[cyan]🔍 Analyzing {package}...[/cyan]\n")
    
    scanner = VulnerabilityScanner(adb)
    report = scanner.scan_app(package, deep_scan)
    
    if not report:
        console.print(f"[red]❌ Could not analyze {package}. Is it installed?[/red]")
        return
    
    # Display results
    _display_app_report(report)


def full_scan_menu(device: str):
    """Menu to perform full device scan."""
    console.print("\n[bold cyan]Configure scan options:[/bold cyan]\n")
    
    # System apps
    console.print("[1] Include system apps?")
    console.print("  [a] No (third-party only)")
    console.print("  [b] Yes (all apps)")
    while True:
        choice = console.input("[bold]Select (a or b): [/bold]")
        if choice in ["a", "b"]:
            include_system = choice == "b"
            break
        console.print("[red]Invalid choice[/red]")
    
    # Deep scan
    console.print("\n[2] Deep APK analysis?")
    console.print("  [a] No (faster)")
    console.print("  [b] Yes (finds URLs, slower)")
    while True:
        choice = console.input("[bold]Select (a or b): [/bold]")
        if choice in ["a", "b"]:
            deep_scan = choice == "b"
            break
        console.print("[red]Invalid choice[/red]")
    
    # Report format
    console.print("\n[3] Report format?")
    console.print("  [1] Console (display only)")
    console.print("  [2] HTML (interactive webpage)")
    console.print("  [3] JSON (for automation)")
    console.print("  [4] Text (plain text)")
    console.print("  [5] All formats")
    while True:
        choice = console.input("[bold]Select (1-5): [/bold]")
        if choice in ["1", "2", "3", "4", "5"]:
            format_choice = choice
            break
        console.print("[red]Invalid choice[/red]")
    
    format_map = {
        "1": "console",
        "2": "html",
        "3": "json",
        "4": "text",
        "5": "all"
    }
    output_format = format_map[format_choice]
    
    # Output directory
    output_dir = None
    if output_format != "console":
        output_dir = console.input("[bold]Output directory (default: ./reports): [/bold]") or "./reports"
    
    # Start scan
    console.print(f"\n[bold cyan]🔒 Starting Security Scan...[/bold cyan]")
    if deep_scan:
        console.print("[yellow]Deep scan enabled - this may take longer[/yellow]")
    if include_system:
        console.print("[yellow]Including system apps[/yellow]")
    console.print()
    
    adb = get_adb_interface(device)
    scanner = VulnerabilityScanner(adb, include_system)
    
    results = scanner.scan_all_apps(deep_scan)
    full_report = scanner.get_full_report()
    
    # Display summary
    _display_scan_summary(full_report)
    
    # Generate reports
    if output_format != "console":
        os.makedirs(output_dir, exist_ok=True)
        generator = ReportGenerator(output_dir)
        
        console.print(f"\n[bold cyan]📄 Generating reports in {output_dir}...[/bold cyan]\n")
        
        if output_format == "all":
            try:
                files = generator.generate_all(full_report)
                for fmt, path in files.items():
                    console.print(f"  ✓ {fmt.upper()}: {path}")
                console.print(f"\n[green]✓ Reports saved to {output_dir}[/green]")
            except Exception as e:
                console.print(f"[red]Error generating reports: {e}[/red]")
        elif output_format == "html":
            try:
                path = generator.generate_html(full_report)
                console.print(f"  ✓ HTML: {path}")
                console.print(f"\n[green]✓ Report saved[/green]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
        elif output_format == "json":
            try:
                path = generator.generate_json(full_report)
                console.print(f"  ✓ JSON: {path}")
                console.print(f"\n[green]✓ Report saved[/green]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
        elif output_format == "text":
            try:
                path = generator.generate_text(full_report)
                console.print(f"  ✓ Text: {path}")
                console.print(f"\n[green]✓ Report saved[/green]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
    
    # Show high-risk apps
    if output_format == "console":
        _display_high_risk_apps(full_report)


def demo_mode():
    """Run demo with sample data."""
    console.print(Panel(
        "[bold cyan]📱 V Scanner - Demo Mode[/bold cyan]\n\n"
        "This demonstrates the scanner output using sample data.\n"
        "Connect a real Android device to scan your apps.",
        title="Demo Mode"
    ))
    
    # Create sample data
    from report_generator import AppSecurityReport, RiskLevel
    
    sample_apps = [
        {
            "package_name": "com.social.app",
            "app_name": "Social Media App",
            "version": "1.2.3",
            "target_sdk": 31,
            "dangerous_perms": ["CAMERA", "RECORD_AUDIO", "ACCESS_FINE_LOCATION"],
            "risk": RiskLevel.MEDIUM
        },
        {
            "package_name": "com.flashlight.free",
            "app_name": "Flashlight Pro",
            "version": "2.1.0",
            "target_sdk": 28,
            "dangerous_perms": ["CAMERA", "ACCESS_FINE_LOCATION", "READ_CONTACTS", "RECORD_AUDIO"],
            "risk": RiskLevel.HIGH
        },
        {
            "package_name": "com.game.casual",
            "app_name": "Casual Game",
            "version": "3.0.1",
            "target_sdk": 33,
            "dangerous_perms": [],
            "risk": RiskLevel.LOW
        }
    ]
    
    console.print("\n[cyan]Sample apps analyzed:[/cyan]\n")
    table = Table(box=box.ROUNDED)
    table.add_column("App", style="cyan")
    table.add_column("SDK", style="green")
    table.add_column("Risk", style="yellow")
    
    for app in sample_apps:
        risk_color = {
            RiskLevel.LOW: "green",
            RiskLevel.MEDIUM: "yellow",
            RiskLevel.HIGH: "red"
        }.get(app["risk"], "white")
        
        risk_str = f"[{risk_color}]{app['risk'].value}[/{risk_color}]"
        table.add_row(app["app_name"], str(app["target_sdk"]), risk_str)
    
    console.print(table)
    console.print("\n[green]✓ Demo complete! Connect a device to scan real apps.[/green]")


def select_app_for_admin_op(device: str):
    """Select an app from the list for admin operations."""
    adb = get_adb_interface(device)
    packages = adb.list_packages(include_system=False)
    
    if not packages:
        console.print("[yellow]No apps found.[/yellow]")
        return None
    
    table = Table(title="Installed Applications", box=box.ROUNDED)
    table.add_column("#", style="dim", width=4)
    table.add_column("App Name", style="green")
    table.add_column("Package Name", style="cyan")
    
    for i, pkg in enumerate(packages, 1):
        app_name = adb.get_app_label(pkg)
        table.add_row(str(i), app_name, pkg)
        if i >= 50:  # Limit display
            table.add_row("[dim]...more[/dim]", "[dim]...[/dim]", "[dim]...[/dim]")
            break
    
    console.print(table)
    console.print(f"\n[bold]Total: {len(packages)} apps[/bold]")
    
    try:
        choice = int(console.input("\nSelect app number (or enter package name directly): ").strip())
        if 1 <= choice <= len(packages):
            return packages[choice - 1]
    except ValueError:
        pass
    
    # Assume user entered package name directly
    package_input = console.input("Enter package name: ").strip()
    if package_input in packages:
        return package_input
    
    console.print("[red]Invalid selection.[/red]")
    return None


def admin_operations_menu(device: str):
    """Admin operations submenu."""
    while True:
        console.print("\n" + "="*50)
        console.print("[bold cyan]⚙️  Admin Operations[/bold cyan]")
        console.print("="*50 + "\n")
        
        console.print("[1] 🗑️  Uninstall App")
        console.print("[2] ▶️  Open/Launch App")
        console.print("[3] ⏹️  Force Stop App")
        console.print("[4] 🔙 Back to Main Menu")
        
        choice = console.input("\n[bold]Select option (1-4): [/bold]")
        
        if choice == '1':
            package = select_app_for_admin_op(device)
            if package:
                adb = get_adb_interface(device)
                console.print(f"\n[bold cyan]🗑️  Uninstalling {package}...[/bold cyan]")
                if adb.uninstall_app(package):
                    console.print(f"[bold green]✓ Successfully uninstalled {package}[/bold green]")
                else:
                    console.print(f"[bold red]✗ Failed to uninstall {package}[/bold red]")
        
        elif choice == '2':
            package = select_app_for_admin_op(device)
            if package:
                adb = get_adb_interface(device)
                console.print(f"\n[bold cyan]▶️  Opening {package}...[/bold cyan]")
                if adb.open_app(package):
                    console.print(f"[bold green]✓ Successfully opened {package}[/bold green]")
                else:
                    console.print(f"[bold red]✗ Failed to open {package}. Is it installed?[/bold red]")
        
        elif choice == '3':
            package = select_app_for_admin_op(device)
            if package:
                adb = get_adb_interface(device)
                console.print(f"\n[bold cyan]⏹️  Force stopping {package}...[/bold cyan]")
                if adb.force_stop_app(package):
                    console.print(f"[bold green]✓ Successfully force stopped {package}[/bold green]")
                else:
                    console.print(f"[bold red]✗ Failed to force stop {package}[/bold red]")
        
        elif choice == '4':
            break
        
        else:
            console.print("[red]Invalid option.[/red]")


def display_device_info_panel(device: str):
    """Display comprehensive device information in panels."""
    adb = get_adb_interface(device)
    
    console.print("\n[bold cyan]📱 Device Information[/bold cyan]\n")
    
    try:
        device_info = adb.get_comprehensive_device_info()
        
        console.print(Panel(
            f"[bold cyan]Device Details[/bold cyan]\n"
            f"[bold]Model:[/bold] {device_info['device_model']}\n"
            f"[bold]Manufacturer:[/bold] {device_info['manufacturer']}\n"
            f"[bold]Brand:[/bold] {device_info['brand']}\n"
            f"[bold]Board:[/bold] {device_info['board']}\n"
            f"[bold]Hardware:[/bold] {device_info['hardware']}\n"
            f"[bold]Build ID:[/bold] {device_info['build_id']}",
            title="🔧 Device Hardware",
            border_style="cyan"
        ))
        
        console.print(Panel(
            f"[bold]Android Version:[/bold] {device_info['android_version']}\n"
            f"[bold]API Level:[/bold] {device_info['api_level']}\n"
            f"[bold]Kernel Version:[/bold] {device_info['kernel_version']}\n"
            f"[bold]Security Patch:[/bold] {device_info['security_patch']}\n"
            f"[bold]Root Status:[/bold] {device_info['is_rooted']}",
            title="🔐 System Information",
            border_style="blue"
        ))
        
        console.print(Panel(
            f"[bold]Total RAM:[/bold] {device_info['total_ram']}\n"
            f"[bold]Available RAM:[/bold] {device_info['available_ram']}\n"
            f"[bold]Internal Storage:[/bold] {device_info['internal_storage']}\n"
            f"[bold]External Storage:[/bold] {device_info['external_storage']}",
            title="💾 Memory & Storage",
            border_style="yellow"
        ))
        
    except Exception as e:
        console.print(f"[yellow]⚠️ Some device information unavailable: {str(e)[:75]}[/yellow]")


def display_full_device_info(device: str):
    """Display complete device information including network, identifiers, etc."""
    adb = get_adb_interface(device)
    
    console.print("\n[bold cyan]📱 Complete Device Information[/bold cyan]\n")
    
    try:
        # Get basic info
        basic_info = adb.get_comprehensive_device_info()
        
        # Display Hardware
        console.print(Panel(
            f"[bold]Model:[/bold] {basic_info['device_model']}\n"
            f"[bold]Manufacturer:[/bold] {basic_info['manufacturer']}\n"
            f"[bold]Brand:[/bold] {basic_info['brand']}\n"
            f"[bold]Board:[/bold] {basic_info['board']}\n"
            f"[bold]Hardware:[/bold] {basic_info['hardware']}\n"
            f"[bold]Build ID:[/bold] {basic_info['build_id']}",
            title="🔧 Device Hardware",
            border_style="cyan"
        ))
        
        # Display System Info
        console.print(Panel(
            f"[bold]Android Version:[/bold] {basic_info['android_version']}\n"
            f"[bold]API Level:[/bold] {basic_info['api_level']}\n"
            f"[bold]Kernel Version:[/bold] {basic_info['kernel_version']}\n"
            f"[bold]Security Patch:[/bold] {basic_info['security_patch']}\n"
            f"[bold]Root Status:[/bold] {basic_info['is_rooted']}",
            title="🔐 System Information",
            border_style="blue"
        ))
        
        # Display Memory & Storage
        console.print(Panel(
            f"[bold]Total RAM:[/bold] {basic_info['total_ram']}\n"
            f"[bold]Available RAM:[/bold] {basic_info['available_ram']}\n"
            f"[bold]Internal Storage:[/bold] {basic_info['internal_storage']}\n"
            f"[bold]External Storage:[/bold] {basic_info['external_storage']}",
            title="💾 Memory & Storage",
            border_style="yellow"
        ))
        
        # Get full device info
        full_info = adb.get_full_device_info()
        
        # Display Network & Connectivity
        console.print(Panel(
            f"[bold]IP Address:[/bold] {full_info.get('ip_address', 'N/A')}\n"
            f"[bold]MAC Address:[/bold] {full_info.get('mac_address', 'N/A')}\n"
            f"[bold]Bluetooth Name:[/bold] {full_info.get('bluetooth_name', 'N/A')}\n"
            f"[bold]Bluetooth Address:[/bold] {full_info.get('bluetooth_address', 'N/A')}",
            title="🌐 Network & Connectivity",
            border_style="magenta"
        ))
        
        # Display Identifiers
        console.print(Panel(
            f"[bold]IMEI:[/bold] {full_info.get('imei', 'N/A')}\n"
            f"[bold]Serial Number:[/bold] {full_info.get('device_name', 'N/A')}\n"
            f"[bold]Phone Number:[/bold] {full_info.get('phone_number', 'N/A')}\n"
            f"[bold]IMSI:[/bold] {full_info.get('imsi', 'N/A')}",
            title="🔑 Device Identifiers",
            border_style="green"
        ))
        
        # Display Build & Version Info
        console.print(Panel(
            f"[bold]Build Fingerprint:[/bold] {full_info.get('build_fingerprint', 'N/A')}\n"
            f"[bold]Display ID:[/bold] {full_info.get('display_id', 'N/A')}\n"
            f"[bold]Bootloader:[/bold] {full_info.get('bootloader', 'N/A')}",
            title="🔨 Build Information",
            border_style="red"
        ))
        
        # Display Locale & Time
        console.print(Panel(
            f"[bold]Timezone:[/bold] {full_info.get('timezone', 'N/A')}\n"
            f"[bold]Locale:[/bold] {full_info.get('locale', 'N/A')}",
            title="🌍 Locale & Time",
            border_style="cyan"
        ))
        
        console.print("\n[dim]Press Enter to return to main menu...[/dim]")
        console.input()
        
    except Exception as e:
        console.print(f"[red]❌ Error getting device information: {str(e)[:100]}[/red]")
        console.input("[dim]Press Enter to continue...[/dim]")


def sensors_menu(device: str):
    """Sensors monitoring submenu."""
    
    # Now show the sensors menu
    while True:
        console.print("\n" + "="*50)
        console.print("[bold cyan]📡 Sensor Monitoring[/bold cyan]")
        console.print("="*50 + "\n")
        
        console.print("[1] 🔴 Live Hardware Usage")
        console.print("    (Camera, Microphone, Location, etc.)")
        console.print("[2] 📊 All Sensor Values")
        console.print("    (Accelerometer, Magnetometer, Gyroscope, etc.)")
        console.print("[3] 🔙 Back to Main Menu")
        
        choice = console.input("\n[bold]Select option (1-3): [/bold]")
        
        if choice == '1':
            display_live_sensors(device)
        
        elif choice == '2':
            display_all_sensors(device)
        
        elif choice == '3':
            break
        
        else:
            console.print("[red]Invalid option.[/red]")


def display_live_sensors(device: str):
    """Display ACTIVE hardware usage in real-time - continuously updates until user stops."""
    adb = get_adb_interface(device)
    
    console.print("\n[bold cyan]🔴 Live Hardware Usage Monitor[/bold cyan]")
    console.print("[dim cyan]Press Ctrl+C or type 'q' to exit | Real-time continuous monitoring[/dim cyan]\n")
    
    import time
    import os
    
    try:
        while True:
            # Clear previous output (optional - comment out if you want scrolling)
            # os.system('cls' if os.name == 'nt' else 'clear')
            
            console.print("\n[bold cyan]🔴 Live Hardware Usage Monitor[/bold cyan]")
            console.print("[dim cyan]Real-time detection of active hardware access...[/dim cyan]")
            console.print("[dim]Last update: " + time.strftime("%H:%M:%S") + "[/dim]\n")
            
            # Get current foreground app
            stdout, _, _ = adb._run_cmd(["shell", "dumpsys", "window", "windows"], timeout=5)
            current_app = None
            current_app_name = None
            
            if stdout:
                lines = stdout.split('\n')
                for line in lines:
                    if 'mCurrentFocus' in line or 'mFocusedApp' in line:
                        parts = line.split('/')
                        if len(parts) >= 1:
                            pkg_part = parts[0].split()[-1]
                            if '{' in pkg_part:
                                current_app = pkg_part.split('{')[-1]
                            elif ' ' in pkg_part:
                                current_app = pkg_part.split()[-1]
                            else:
                                current_app = pkg_part
                            
                            if current_app:
                                try:
                                    current_app_name = adb.get_app_label(current_app)
                                except:
                                    current_app_name = current_app
                                break
            
            # Display current foreground app
            if current_app:
                console.print(Panel(
                    f"[bold cyan]🎯 App in Focus: [/bold cyan][bold yellow]{current_app_name}[/bold yellow]\n"
                    f"[dim]({current_app})[/dim]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
            else:
                console.print(Panel(
                    "[yellow]⚠️ Unable to determine current app[/yellow]",
                    border_style="yellow",
                    padding=(1, 1)
                ))
            
            console.print()
            
            # ===== DETECT ACTIVE CAMERA USAGE =====
            console.print("[bold magenta]📹 Camera Status[/bold magenta]")
            
            camera_apps = []
            try:
                stdout, _, _ = adb._run_cmd(["shell", "dumpsys", "camera"], timeout=5)
                if stdout:
                    lines = stdout.split('\n')
                    for line in lines:
                        line_lower = line.lower()
                        # Look for camera in use indicators
                        if any(keyword in line_lower for keyword in ['in use', 'owner', 'client', 'recording', 'preview']):
                            # Extract package name - look for com.xxx.xxx pattern
                            import re
                            matches = re.findall(r'([a-z0-9][a-z0-9\._]*[a-z0-9])', line_lower)
                            for match in matches:
                                if match.count('.') >= 2 and not any(x in match for x in ['camera', 'hal', 'api', 'v']):
                                    if match not in camera_apps and match != 'com.android':
                                        camera_apps.append(match)
            except Exception as e:
                pass
            
            # Additional check: look for camera process via ps
            if not camera_apps:
                try:
                    stdout, _, _ = adb._run_cmd(["shell", "ps", "-A"], timeout=5)
                    if stdout and 'camera' in stdout.lower():
                        lines = stdout.split('\n')
                        for line in lines:
                            if 'camera' in line.lower():
                                import re
                                matches = re.findall(r'([a-z0-9][a-z0-9\._]*camera[a-z0-9\._]*)', line.lower())
                                for match in matches:
                                    if match.count('.') >= 1:
                                        camera_apps.append(match)
                except:
                    pass
            
            # Check lsof for camera access
            if not camera_apps:
                try:
                    stdout, _, _ = adb._run_cmd(["shell", "lsof", "/dev/video*"], timeout=5)
                    if stdout:
                        lines = stdout.split('\n')
                        for line in lines:
                            import re
                            matches = re.findall(r'([a-z0-9][a-z0-9\._]*\.camera[a-z0-9]*)', line.lower())
                            for match in matches:
                                if match not in camera_apps:
                                    camera_apps.append(match)
                except:
                    pass
            
            if camera_apps:
                for pkg in camera_apps[:5]:
                    try:
                        # Clean package name
                        pkg = pkg.strip('.')
                        app_name = adb.get_app_label(pkg)
                        console.print(f"  [bold red]🔴 ACTIVE[/bold red] {app_name} [dim]({pkg})[/dim]")
                    except:
                        pass
            else:
                console.print("  [dim]⚪ No active camera usage[/dim]")
            
            console.print()
            
            # ===== DETECT ACTIVE MICROPHONE USAGE =====
            console.print("[bold magenta]🎤 Microphone Status[/bold magenta]")
            
            mic_apps = []
            try:
                stdout, _, _ = adb._run_cmd(["shell", "dumpsys", "audio"], timeout=5)
                if stdout:
                    lines = stdout.split('\n')
                    for line in lines:
                        line_lower = line.lower()
                        if any(keyword in line_lower for keyword in ['focus holder', 'mixin', 'record', 'stream in', 'active', 'recorder']):
                            # Extract package
                            import re
                            matches = re.findall(r'([a-z0-9][a-z0-9\._]*[a-z0-9](?:\.voice|\.record|\.audio)?)', line_lower)
                            for match in matches:
                                if match.count('.') >= 1 and len(match) > 5:
                                    if match not in mic_apps and not any(x in match for x in ['system', 'media', 'api']):
                                        mic_apps.append(match)
            except:
                pass
            
            if mic_apps:
                for pkg in mic_apps[:5]:
                    try:
                        pkg = pkg.strip('.')
                        app_name = adb.get_app_label(pkg)
                        console.print(f"  [bold red]🔴 ACTIVE[/bold red] {app_name} [dim]({pkg})[/dim]")
                    except:
                        pass
            else:
                console.print("  [dim]⚪ No active microphone usage[/dim]")
            
            console.print()
            
            # ===== DETECT ACTIVE GPS/LOCATION USAGE =====
            console.print("[bold magenta]📍 Location (GPS) Status[/bold magenta]")
            
            gps_apps = []
            try:
                stdout, _, _ = adb._run_cmd(["shell", "dumpsys", "location"], timeout=5)
                if stdout:
                    lines = stdout.split('\n')
                    for line in lines:
                        line_lower = line.lower()
                        if any(keyword in line_lower for keyword in ['gps', 'location', 'fix', 'request', 'active']):
                            import re
                            matches = re.findall(r'([a-z0-9][a-z0-9\._]*[a-z0-9])', line_lower)
                            for match in matches:
                                if match.count('.') >= 2 and 'location' not in match and 'gps' not in match:
                                    if match not in gps_apps:
                                        gps_apps.append(match)
            except:
                pass
            
            if gps_apps:
                for pkg in gps_apps[:5]:
                    try:
                        pkg = pkg.strip('.')
                        app_name = adb.get_app_label(pkg)
                        console.print(f"  [bold red]🔴 ACTIVE[/bold red] {app_name} [dim]({pkg})[/dim]")
                    except:
                        pass
            else:
                console.print("  [dim]⚪ No active location usage[/dim]")
            
            console.print()
            console.print("[bold cyan]📊 Summary[/bold cyan]")
            console.print(f"  Camera apps: {len(camera_apps)} active")
            console.print(f"  Mic apps: {len(mic_apps)} active")
            console.print(f"  GPS apps: {len(gps_apps)} active")
            
            if not (camera_apps or mic_apps or gps_apps):
                console.print("\n[green]✓ No suspicious hardware access detected[/green]")
            else:
                console.print("\n[yellow]⚠️ Apps are actively using hardware[/yellow]")
            
            console.print("\n[dim][Press Ctrl+C to exit][/dim]")
            
            # Wait before next update
            time.sleep(2)
    
    except KeyboardInterrupt:
        console.print("\n\n[bold cyan]✓ Monitoring stopped[/bold cyan]")
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)[:100]}[/red]")
        console.print("[dim]Ensure ADB connection is active.[/dim]")



def display_all_sensors(device: str):
    """Display all sensor values like CPU-Z (Accelerometer, Magnetometer, Gyroscope, etc)."""
    adb = get_adb_interface(device)
    
    console.print("\n[bold cyan]📊 All Sensor Values (CPU-Z Style)[/bold cyan]\n")
    
    try:
        sensor_values = adb.get_sensor_values_live()
        
        if not sensor_values:
            console.print("[yellow]⚠️ No sensor data available[/yellow]")
            console.print("[dim]Try moving the device to trigger sensor readings[/dim]")
            return
        
        console.print(f"[bold cyan]Found {len(sensor_values)} sensors[/bold cyan]\n")
        
        # Display sensors in organized table format
        table = Table(box=box.ROUNDED, border_style="cyan")
        table.add_column("Sensor Type", style="magenta", width=30)
        table.add_column("Values", style="green")
        
        for sensor_name, values in sensor_values.items():
            if values:  # Only show if has values
                value_str = '\n'.join(values[:3]) if values else "No data"
                table.add_row(sensor_name, value_str)
        
        console.print(table)
        
        console.print("\n[dim cyan]Note: Sensor values are continuously read from device.[/dim cyan]")
        console.print("[dim cyan]Move your device to see accelerometer, gyroscope, and magnetometer updates.[/dim cyan]")
    
    except Exception as e:
        console.print(f"[red]❌ Error getting sensor values: {str(e)[:100]}[/red]")
        console.print("[dim]Ensure ADB connection is active and device has sensors.[/dim]")


def admin_operations_menu(device: str):
    """Admin operations submenu."""
    while True:
        console.print("\n" + "="*50)
        console.print("[bold cyan]⚙️  Admin Operations[/bold cyan]")
        console.print("="*50 + "\n")
        
        console.print("[1] 🗑️  Uninstall App")
        console.print("[2] ▶️  Open/Launch App")
        console.print("[3] ⏹️  Force Stop App")
        console.print("[4] 🔙 Back to Main Menu")
        
        choice = console.input("\n[bold]Select option (1-4): [/bold]")
        
        if choice == '1':
            package = select_app_for_admin_op(device)
            if package:
                adb = get_adb_interface(device)
                console.print(f"\n[bold cyan]🗑️  Uninstalling {package}...[/bold cyan]")
                if adb.uninstall_app(package):
                    console.print(f"[bold green]✓ Successfully uninstalled {package}[/bold green]")
                else:
                    console.print(f"[bold red]✗ Failed to uninstall {package}[/bold red]")
        
        elif choice == '2':
            package = select_app_for_admin_op(device)
            if package:
                adb = get_adb_interface(device)
                console.print(f"\n[bold cyan]▶️  Opening {package}...[/bold cyan]")
                if adb.open_app(package):
                    console.print(f"[bold green]✓ Successfully opened {package}[/bold green]")
                else:
                    console.print(f"[bold red]✗ Failed to open {package}. Is it installed?[/bold red]")
        
        elif choice == '3':
            package = select_app_for_admin_op(device)
            if package:
                adb = get_adb_interface(device)
                console.print(f"\n[bold cyan]⏹️  Force stopping {package}...[/bold cyan]")
                if adb.force_stop_app(package):
                    console.print(f"[bold green]✓ Successfully force stopped {package}[/bold green]")
                else:
                    console.print(f"[bold red]✗ Failed to force stop {package}[/bold red]")
        
        elif choice == '4':
            break
        
        else:
            console.print("[red]Invalid option.[/red]")


def main_menu():
    """Display main interactive menu."""
    while True:
        print_main_menu()
        
        choice = console.input("[bold cyan]Select option (1-10): [/bold cyan]")
        
        if choice == "1":
            return "list"
        
        elif choice == "2":
            return "analyze"
        
        elif choice == "3":
            return "scan"
        
        elif choice == "4":
            return "admin"
        
        elif choice == "5":
            return "sensors"
        
        elif choice == "6":
            return "full_device_info"
        
        elif choice == "7":
            demo_mode()
        
        elif choice == "8":
            return "change_device"
        
        elif choice == "9":
            console.print("\n[cyan]Reconfiguring ADB path...[/cyan]")
            from adb_setup import interactive_adb_setup
            interactive_adb_setup()
        
        elif choice == "10":
            print_footer()
            sys.exit(0)
        
        else:
            console.print("[red]❌ Invalid choice. Please select 1-10.[/red]")
            console.input("[dim]Press Enter to continue...[/dim]")


def _display_app_report(report):
    """Display a single app security report."""
    console.print(Panel(
        f"[bold cyan]📊 Security Analysis: {report.app_name}[/bold cyan]",
        border_style="cyan"
    ))
    
    console.print(f"\n[bold]Package:[/bold] {report.package_name}")
    console.print(f"[bold]Version:[/bold] {report.version_name} (Code: {report.version_code})")
    console.print(f"[bold]Target SDK:[/bold] {report.target_sdk}")
    console.print(f"[bold]Min SDK:[/bold] {report.min_sdk}")
    
    # Permissions
    if report.dangerous_permissions:
        console.print(f"\n[bold red]🔴 DANGEROUS PERMISSIONS ({len(report.dangerous_permissions)}):[/bold red]")
        for perm in report.dangerous_permissions:
            if isinstance(perm, dict):
                console.print(f"  • {perm.get('permission', 'Unknown')} - {perm.get('description', '')}")
            else:
                # It's an object with attributes
                try:
                    console.print(f"  • {perm.permission} - {perm.description}")
                except AttributeError:
                    console.print(f"  • {str(perm)}")
    else:
        console.print("\n[bold green]✓ No dangerous permissions detected[/bold green]")
    
    # SDK Issues
    if hasattr(report, 'sdk_issues') and report.sdk_issues:
        console.print(f"\n[bold yellow]⚠️ SDK Issues:[/bold yellow]")
        for issue in report.sdk_issues:
            console.print(f"  • {issue}")
    
    # Risk level
    risk_color = {
        "HIGH": "red",
        "MEDIUM": "yellow",
        "LOW": "green"
    }.get(report.risk_level, "white")
    
    console.print(f"\n[bold {risk_color}]⚠️ RISK LEVEL: {report.risk_level} (Score: {report.risk_score}/100)[/bold {risk_color}]")
    
    if report.insecure_urls:
        console.print(f"\n[bold red]⚠️ INSECURE URLs ({len(report.insecure_urls)}):[/bold red]")
        for url in report.insecure_urls[:10]:
            console.print(f"  • {url}")
    
    # Recommendations
    if hasattr(report, 'recommendations') and report.recommendations:
        console.print(f"\n[bold cyan]💡 Recommendations:[/bold cyan]")
        for rec in report.recommendations:
            console.print(f"  • {rec}")


def _display_scan_summary(full_report):
    """Display scan summary."""
    # Calculate security score (inverse of risk percentage)
    if full_report.total_apps > 0:
        high_risk_pct = (full_report.high_risk_apps / full_report.total_apps) * 100
        security_score = max(0, 100 - int(high_risk_pct * 1.5))
    else:
        security_score = 0
    
    console.print(Panel(
        f"[bold cyan]📊 Scan Summary[/bold cyan]\n"
        f"[bold]Total Apps Scanned:[/bold] {full_report.total_apps}\n"
        f"[bold red]High Risk:[/bold red] {full_report.high_risk_apps}\n"
        f"[bold yellow]Medium Risk:[/bold yellow] {full_report.medium_risk_apps}\n"
        f"[bold green]Low Risk:[/bold green] {full_report.low_risk_apps}\n\n"
        f"[bold]Device Security Score:[/bold] {security_score}/100",
        border_style="cyan"
    ))


def _display_high_risk_apps(full_report):
    """Display high-risk apps."""
    high_risk = [a for a in full_report.apps if a.risk_level == "HIGH"]
    
    if high_risk:
        console.print(f"\n[bold red]⚠️ HIGH RISK APPS ({len(high_risk)}):[/bold red]\n")
        table = Table(box=box.ROUNDED)
        table.add_column("App", style="cyan")
        table.add_column("Package", style="green")
        table.add_column("Risk Score", style="red")
        
        for app in high_risk[:10]:
            table.add_row(
                app.app_name,
                app.package_name,
                str(app.risk_score)
            )
        
        console.print(table)
    else:
        console.print(f"\n[green]✓ No high-risk apps detected[/green]")


def main():
    """Main entry point."""
    # Display beautiful banner
    print_gradient_banner()
    
    # Run startup animation
    print_startup_animation()
    
    # Configure ADB
    console.print("\n[cyan]⚙️  Configuring Android Debug Bridge...[/cyan]")
    adb_result = find_adb()
    
    if not adb_result:
        print_error_message("❌ ADB Configuration Failed", "Could not setup or find ADB")
        sys.exit(1)
    
    console.print(f"[green]✓ ADB ready: {adb_result}[/green]")
    
    console.print("\n[cyan]🔍 Scanning for Android devices...[/cyan]\n")
    
    devices = get_available_devices()
    
    if not devices:
        print_warning_message(
            "⚠️ No Devices Detected",
            "Please ensure:\n"
            "• USB debugging is enabled on your device\n"
            "• Device is physically connected via USB\n"
            "• Tap 'Allow' when prompted on device\n"
            "• ADB is properly installed\n\n"
            "You can still use Demo Mode to see how the scanner works"
        )
        current_device = None
    elif len(devices) == 1:
        # Auto-select if only one device
        current_device = devices[0]
        console.print(f"[green]✓ Auto-selected device: {current_device}[/green]\n")
    else:
        # Ask user to select if multiple devices
        console.print(f"[green]✓ Found {len(devices)} device(s)[/green]\n")
        current_device = select_device()
        if not current_device:
            current_device = None
    
    device_info_shown = False
    
    while True:
        if current_device:
            console.print(f"\n[bold green]📱 Device: {current_device}[/bold green]\n")
            
            # Display device info only once when device is first selected
            if not device_info_shown:
                display_device_info_panel(current_device)
                device_info_shown = True
        
        menu_choice = main_menu()
        
        if menu_choice == "list":
            if not current_device:
                console.print("[yellow]⚠️ No device selected. Please select a device.[/yellow]")
                current_device = select_device()
                if not current_device:
                    continue
                device_info_shown = False
            list_apps_menu(current_device)
        
        elif menu_choice == "analyze":
            if not current_device:
                console.print("[yellow]⚠️ No device selected. Please select a device.[/yellow]")
                current_device = select_device()
                if not current_device:
                    continue
                device_info_shown = False
            analyze_app_menu(current_device)
        
        elif menu_choice == "scan":
            if not current_device:
                current_device = select_device()
                if not current_device:
                    continue
                device_info_shown = False
            full_scan_menu(current_device)
        
        elif menu_choice == "admin":
            if not current_device:
                current_device = select_device()
                if not current_device:
                    continue
                device_info_shown = False
            admin_operations_menu(current_device)
        
        elif menu_choice == "sensors":
            if not current_device:
                current_device = select_device()
                if not current_device:
                    continue
                device_info_shown = False
            sensors_menu(current_device)
        
        elif menu_choice == "full_device_info":
            if not current_device:
                console.print("[yellow]⚠️ No device selected. Please select a device.[/yellow]")
                current_device = select_device()
                if not current_device:
                    continue
                device_info_shown = False
            display_full_device_info(current_device)
        
        elif menu_choice == "change_device":
            devices = get_available_devices()
            if not devices:
                console.print("[yellow]⚠️ No devices available[/yellow]")
            else:
                new_device = select_device()
                if new_device:
                    current_device = new_device
                    device_info_shown = False


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️ Interrupted by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
        sys.exit(1)
