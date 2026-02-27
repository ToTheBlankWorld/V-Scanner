#!/usr/bin/env python3
"""
Mobile App Vulnerability Scanner - CLI Tool

A cross-platform command-line tool that scans installed Android apps
for security vulnerabilities, excessive permissions, outdated SDKs,
and insecure configurations.

Usage:
    python scanner.py scan [OPTIONS]
    python scanner.py list-apps
    python scanner.py analyze <package_name>
    python scanner.py report [--format html|json|text]
"""

import re
import sys
import subprocess
import json
import click
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.text import Text
from rich import box

from permissions import (
    analyze_permissions, 
    get_sdk_risk, 
    DANGEROUS_PERMISSIONS,
    INSECURE_URL_PATTERNS,
    RiskLevel
)
from report_generator import (
    ReportGenerator, 
    create_app_report, 
    create_full_report,
    AppSecurityReport,
    FullScanReport
)


console = Console()


class ADBInterface:
    """Interface for Android Debug Bridge (ADB) commands."""
    
    def __init__(self, device: str = None):
        self.device = device
        self.adb_cmd = ["adb"]
        if device:
            self.adb_cmd.extend(["-s", device])
    
    def _run_cmd(self, cmd: List[str], timeout: int = 30) -> Tuple[str, str, int]:
        """Execute an ADB command and return stdout, stderr, return code."""
        full_cmd = self.adb_cmd + cmd
        try:
            result = subprocess.run(
                full_cmd, 
                capture_output=True, 
                text=True, 
                timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", "Command timed out", 1
        except FileNotFoundError:
            return "", "ADB not found. Please install Android SDK Platform Tools.", 1
    
    def check_connection(self) -> bool:
        """Check if ADB is available and a device is connected."""
        stdout, stderr, code = self._run_cmd(["devices"])
        if code != 0:
            return False
        
        lines = stdout.strip().split('\n')
        # Check if any device is connected (excluding header)
        devices = [l for l in lines[1:] if l.strip() and 'device' in l]
        return len(devices) > 0
    
    def get_device_info(self) -> Dict:
        """Get connected device information."""
        info = {}
        
        props = [
            ("model", "ro.product.model"),
            ("manufacturer", "ro.product.manufacturer"),
            ("android_version", "ro.build.version.release"),
            ("sdk_version", "ro.build.version.sdk"),
            ("security_patch", "ro.build.version.security_patch"),
            ("device", "ro.product.device"),
            ("build_id", "ro.build.id"),
        ]
        
        for key, prop in props:
            stdout, _, code = self._run_cmd(["shell", "getprop", prop])
            if code == 0:
                info[key] = stdout.strip()
        
        return info
    
    def get_comprehensive_device_info(self) -> Dict:
        """Get comprehensive device information (model, hardware, screen, RAM, storage, etc)."""
        device_info = {
            "device_model": "Unknown",
            "manufacturer": "Unknown",
            "brand": "Unknown",
            "board": "Unknown",
            "hardware": "Unknown",
            "screen_size": "Unknown",
            "screen_resolution": "Unknown",
            "total_ram": "Unknown",
            "available_ram": "Unknown",
            "internal_storage": "Unknown",
            "external_storage": "Unknown",
            "android_version": "Unknown",
            "api_level": "Unknown",
            "kernel_version": "Unknown",
            "is_rooted": "Checking...",
            "build_id": "Unknown",
            "security_patch": "Unknown"
        }
        
        # Get basic device properties
        props = {
            "device_model": "ro.product.model",
            "manufacturer": "ro.product.manufacturer",
            "brand": "ro.product.brand",
            "board": "ro.product.board",
            "hardware": "ro.hardware",
            "android_version": "ro.build.version.release",
            "api_level": "ro.build.version.sdk",
            "build_id": "ro.build.id",
            "security_patch": "ro.build.version.security_patch",
        }
        
        for key, prop in props.items():
            stdout, _, code = self._run_cmd(["shell", "getprop", prop])
            if code == 0 and stdout.strip():
                device_info[key] = stdout.strip()
        
        # Get screen size
        stdout, _, code = self._run_cmd(["shell", "dumpsys", "display"])
        if code == 0:
            for line in stdout.split('\n'):
                if 'mScreenWidth' in line or 'PhysicalDisplayInfo' in line:
                    device_info["screen_resolution"] = line.strip()
                    break
        
        # Get RAM information
        stdout, _, code = self._run_cmd(["shell", "cat", "/proc/meminfo"])
        if code == 0:
            for line in stdout.split('\n'):
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                    total_gb = total_kb / (1024 * 1024)
                    device_info["total_ram"] = f"{total_gb:.2f} GB"
                elif line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
                    avail_gb = avail_kb / (1024 * 1024)
                    device_info["available_ram"] = f"{avail_gb:.2f} GB"
        
        # Get internal storage
        stdout, _, code = self._run_cmd(["shell", "df", "-h"])
        if code == 0:
            lines = stdout.split('\n')
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 4:
                    device_info["internal_storage"] = f"Total: {parts[1]}, Used: {parts[2]}, Free: {parts[3]}"
        
        # Get external storage (SD card)
        stdout, _, code = self._run_cmd(["shell", "df", "-h", "/storage/emulated"])
        if code == 0:
            lines = stdout.split('\n')
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 4:
                    device_info["external_storage"] = f"Total: {parts[1]}, Used: {parts[2]}, Free: {parts[3]}"
        else:
            device_info["external_storage"] = "Not available"
        
        # Get kernel version
        stdout, _, code = self._run_cmd(["shell", "uname", "-r"])
        if code == 0:
            device_info["kernel_version"] = stdout.strip()
        
        # Check if device is rooted
        stdout, _, code = self._run_cmd(["shell", "su", "-c", "echo", "rooted"])
        if code == 0 and "rooted" in stdout:
            device_info["is_rooted"] = "Yes ⚠️"
        else:
            device_info["is_rooted"] = "No"
        
        return device_info
    
    def list_packages(self, include_system: bool = False) -> List[str]:
        """List all installed packages."""
        cmd = ["shell", "pm", "list", "packages"]
        if not include_system:
            cmd.append("-3")  # Third-party apps only
        
        stdout, _, code = self._run_cmd(cmd)
        if code != 0:
            return []
        
        packages = []
        for line in stdout.strip().split('\n'):
            if line.startswith("package:"):
                packages.append(line[8:])
        
        return packages
    
    def get_package_info(self, package: str) -> Dict:
        """Get detailed information about a package."""
        info = {
            "package_name": package,
            "app_name": package.split('.')[-1].title(),
            "version_name": "Unknown",
            "version_code": 0,
            "target_sdk": 0,
            "min_sdk": 0,
            "permissions": [],
            "install_time": "",
            "update_time": "",
            "apk_path": ""
        }
        
        # Get package dump
        stdout, _, code = self._run_cmd(["shell", "dumpsys", "package", package])
        if code != 0:
            return info
        
        # Parse package info
        lines = stdout.split('\n')
        in_permissions = False
        permissions = []
        
        for line in lines:
            line = line.strip()
            
            # Version info
            if "versionName=" in line:
                match = re.search(r'versionName=([^\s]+)', line)
                if match:
                    info["version_name"] = match.group(1)
            
            if "versionCode=" in line:
                match = re.search(r'versionCode=(\d+)', line)
                if match:
                    info["version_code"] = int(match.group(1))
            
            # SDK versions
            if "targetSdk=" in line or "targetSdkVersion=" in line:
                match = re.search(r'targetSdk(?:Version)?=(\d+)', line)
                if match:
                    info["target_sdk"] = int(match.group(1))
            
            if "minSdk=" in line or "minSdkVersion=" in line:
                match = re.search(r'minSdk(?:Version)?=(\d+)', line)
                if match:
                    info["min_sdk"] = int(match.group(1))
            
            # APK path
            if "codePath=" in line:
                match = re.search(r'codePath=(.+)', line)
                if match:
                    info["apk_path"] = match.group(1).strip()
            
            # Timestamps
            if "firstInstallTime=" in line:
                match = re.search(r'firstInstallTime=(.+)', line)
                if match:
                    info["install_time"] = match.group(1).strip()
            
            if "lastUpdateTime=" in line:
                match = re.search(r'lastUpdateTime=(.+)', line)
                if match:
                    info["update_time"] = match.group(1).strip()
            
            # Permissions section
            if "requested permissions:" in line.lower():
                in_permissions = True
                continue
            
            if in_permissions:
                if line.startswith("android.permission.") or line.startswith("com."):
                    # Extract just the permission name
                    perm = line.split(':')[0].split()[0]
                    permissions.append(perm)
                elif line and not line.startswith(" ") and "permission" not in line.lower():
                    in_permissions = False
        
        info["permissions"] = permissions
        
        # Try to get app label
        stdout, _, code = self._run_cmd([
            "shell", "pm", "dump", package, "|", "grep", "-m1", "labelRes"
        ])
        
        return info
    
    def get_app_label(self, package: str) -> str:
        """Try to get the human-readable app label."""
        stdout, _, code = self._run_cmd([
            "shell", "cmd", "package", "query-activities", 
            "--brief", "-a", "android.intent.action.MAIN", 
            "-c", "android.intent.category.LAUNCHER", package
        ])
        
        if code == 0 and stdout.strip():
            return stdout.strip().split('/')[-1] or package
        
        return package.split('.')[-1].replace('_', ' ').title()
    
    def pull_apk(self, package: str, output_path: str) -> bool:
        """Pull APK file from device for analysis."""
        # Get APK path
        stdout, _, code = self._run_cmd(["shell", "pm", "path", package])
        if code != 0:
            return False
        
        apk_path = stdout.strip().replace("package:", "")
        
        # Pull the APK
        _, _, code = self._run_cmd(["pull", apk_path, output_path])
        return code == 0
    
    def search_apk_for_urls(self, package: str) -> List[str]:
        """Search APK for potentially insecure URLs (basic check)."""
        insecure_urls = []
        
        # Use grep on device to search for http:// URLs
        stdout, _, code = self._run_cmd([
            "shell", "strings", f"/data/app/*{package}*/base.apk",
            "|", "grep", "-E", "'https?://'"
        ], timeout=60)
        
        # Fallback: try searching in a simpler way
        if code != 0:
            pkg_info = self.get_package_info(package)
            apk_path = pkg_info.get("apk_path", "")
            if apk_path:
                stdout, _, code = self._run_cmd([
                    "shell", "cat", f"{apk_path}/base.apk",
                    "|", "strings", "|", "grep", "-oE", "'https?://[^\"\\s]+'"
                ], timeout=60)
        
        if code == 0 and stdout:
            urls = re.findall(r'https?://[^\s"\'<>]+', stdout)
            for url in urls:
                # Check against insecure patterns
                if url.startswith("http://") and not any(
                    safe in url for safe in ["localhost", "127.0.0.1", "10.", "192.168."]
                ):
                    insecure_urls.append(url)
        
        return list(set(insecure_urls))[:20]  # Limit to 20 unique URLs
    
    def uninstall_app(self, package: str) -> bool:
        """Uninstall an app from the device."""
        _, _, code = self._run_cmd(["uninstall", package])
        return code == 0
    
    def open_app(self, package: str) -> bool:
        """Open/launch an app on the device."""
        # Get the main activity for the app
        stdout, _, code = self._run_cmd([
            "shell", "cmd", "package", "query-activities",
            "--brief", "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER", package
        ])
        
        if code != 0 or not stdout.strip():
            return False
        
        # Extract the activity name
        activity = stdout.strip().split('/')[-1]
        if not activity:
            return False
        
        # Launch the activity
        full_activity = f"{package}/{activity}"
        _, _, code = self._run_cmd(["shell", "am", "start", "-n", full_activity])
        return code == 0
    
    def force_stop_app(self, package: str) -> bool:
        """Force stop an app."""
        _, _, code = self._run_cmd(["shell", "am", "force-stop", package])
        return code == 0
    
    def get_cpu_info(self) -> Dict:
        """Get CPU information and usage."""
        cpu_info = {"model": "Unknown", "cores": "Unknown", "usage": "N/A"}
        
        # Get CPU model
        stdout, _, _ = self._run_cmd(["shell", "getprop", "ro.hardware"])
        if stdout.strip():
            cpu_info["model"] = stdout.strip()
        
        # Get number of processors
        stdout, _, code = self._run_cmd(["shell", "cat", "/proc/cpuinfo"])
        if code == 0:
            cores = len([line for line in stdout.split('\n') if line.startswith('processor')])
            cpu_info["cores"] = str(cores) if cores > 0 else "Unknown"
        
        # Get CPU usage
        stdout, _, code = self._run_cmd(["shell", "top", "-n", "1"])
        if code == 0 and "CPU" in stdout:
            for line in stdout.split('\n'):
                if "CPU" in line and "%" in line:
                    cpu_info["usage"] = line.strip()
                    break
        
        return cpu_info
    
    def get_memory_info(self) -> Dict:
        """Get RAM and memory information."""
        memory_info = {"total": "Unknown", "available": "Unknown", "used": "Unknown", "percentage": "N/A"}
        
        stdout, _, code = self._run_cmd(["shell", "cat", "/proc/meminfo"])
        
        if code == 0:
            mem_total = 0
            mem_available = 0
            
            for line in stdout.split('\n'):
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) // 1024  # Convert to MB
                    memory_info["total"] = f"{mem_total} MB"
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) // 1024  # Convert to MB
                    memory_info["available"] = f"{mem_available} MB"
            
            if mem_total > 0 and mem_available > 0:
                mem_used = mem_total - mem_available
                percentage = (mem_used / mem_total) * 100
                memory_info["used"] = f"{mem_used} MB"
                memory_info["percentage"] = f"{percentage:.1f}%"
        
        return memory_info
    
    def get_battery_info(self) -> Dict:
        """Get battery status and information."""
        battery_info = {
            "level": "Unknown",
            "status": "Unknown",
            "health": "Unknown",
            "temperature": "Unknown",
            "voltage": "Unknown",
            "technology": "Unknown"
        }
        
        stdout, _, code = self._run_cmd(["shell", "dumpsys", "batterymanager"])
        
        if code == 0:
            for line in stdout.split('\n'):
                line = line.strip()
                
                if line.startswith("level:"):
                    battery_info["level"] = line.split(":")[-1].strip() + "%"
                elif line.startswith("status:"):
                    battery_info["status"] = line.split(":")[-1].strip()
                elif line.startswith("health:"):
                    battery_info["health"] = line.split(":")[-1].strip()
                elif line.startswith("temperature:"):
                    temp = line.split(":")[-1].strip()
                    battery_info["temperature"] = f"{int(temp)//10}°C" if temp.isdigit() else temp
                elif line.startswith("voltage:"):
                    battery_info["voltage"] = line.split(":")[-1].strip() + " mV"
                elif line.startswith("technology:"):
                    battery_info["technology"] = line.split(":")[-1].strip()
        
        return battery_info
    
    def get_storage_info(self) -> Dict:
        """Get storage and disk space information."""
        storage_info = {"total": "Unknown", "available": "Unknown", "used": "Unknown"}
        
        stdout, _, code = self._run_cmd(["shell", "df", "-h"])
        
        if code == 0:
            lines = stdout.split('\n')
            if len(lines) > 1:
                # Get data from first data line
                parts = lines[1].split()
                if len(parts) >= 4:
                    storage_info["total"] = parts[1]
                    storage_info["used"] = parts[2]
                    storage_info["available"] = parts[3]
        
        return storage_info
    
    def get_system_monitoring(self) -> Dict:
        """Get comprehensive system monitoring data (CPU-Z style)."""
        monitoring = {
            "cpu": self.get_cpu_info(),
            "memory": self.get_memory_info(),
            "battery": self.get_battery_info(),
            "storage": self.get_storage_info(),
            "uptime": self.get_device_uptime(),
            "temperature": self.get_device_temperature()
        }
        return monitoring
    
    def get_device_uptime(self) -> str:
        """Get device uptime."""
        stdout, _, code = self._run_cmd(["shell", "uptime"])
        
        if code == 0:
            return stdout.strip()
        return "Unknown"
    
    def get_device_temperature(self) -> Dict:
        """Get device temperature information."""
        temps = {}
        
        # Try common temperature sensor paths
        temp_paths = {
            "CPU": "/sys/class/thermal/thermal_zone0/temp",
            "Battery": "/sys/class/power_supply/battery/temp",
            "Core": "/proc/stat"
        }
        
        for name, path in temp_paths.items():
            stdout, _, code = self._run_cmd(["shell", "cat", path])
            if code == 0 and stdout.strip():
                try:
                    temp_val = int(stdout.strip().split()[0])
                    # Convert from millidegrees to degrees if needed
                    if temp_val > 200:
                        temp_val = temp_val // 1000
                    temps[name] = f"{temp_val}°C"
                except (ValueError, IndexError):
                    pass
        
        return temps if temps else {"Status": "Temperature data unavailable"}
    
    def get_all_sensors(self) -> List[Dict]:
        """Get list of all physical sensors on the device."""
        sensors = []
        
        # Use dumpsys to get sensor information
        stdout, _, code = self._run_cmd(["shell", "dumpsys", "sensormanager"])
        
        if code != 0 or not stdout:
            return sensors
        
        lines = stdout.split('\n')
        current_sensor = {}
        
        for line in lines:
            line = line.strip()
            
            # Parse sensor information
            if line.startswith("Sensor:"):
                if current_sensor:
                    sensors.append(current_sensor)
                current_sensor = {"name": line.replace("Sensor:", "").strip(), "details": {}}
            
            # Extract sensor details
            if ":" in line and current_sensor:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip().lower()
                    value = parts[1].strip()
                    
                    # Only collect relevant keys
                    if any(k in key for k in ["vendor", "type", "power", "max_range", "resolution", "min_delay", "max_delay"]):
                        current_sensor["details"][key] = value
        
        if current_sensor:
            sensors.append(current_sensor)
        
        return sensors
    
    def get_current_sensor_data(self) -> Dict:
        """Get current sensor readings from active sensors (now returns system monitoring data)."""
        # This is now replaced by get_system_monitoring for better data
        return self.get_system_monitoring()
    
    def get_live_sensor_readings(self) -> List[Dict]:
        """Get live sensor readings with current values (Accelerometer, Gyroscope, Magnetometer, etc)."""
        sensors = []
        
        # Use dumpsys sensormanager to get sensor list and try to get events
        stdout, _, code = self._run_cmd(["shell", "dumpsys", "sensormanager"])
        
        if code != 0 or not stdout:
            return sensors
        
        lines = stdout.split('\n')
        
        # Parse sensor information with events/values
        current_sensor = None
        
        for line in lines:
            line_stripped = line.strip()
            
            # Look for sensor lines like "Sensor:" or sensor names
            if 'Sensor:' in line_stripped or any(sensor_type in line_stripped for sensor_type in 
                ['Accelerometer', 'Gyroscope', 'Magnetometer', 'Light Sensor', 'Proximity', 'Barometer', 
                 'Thermometer', 'Heart Rate', 'Tilt Detector', 'Wake Gesture', 'Glance']):
                
                # Extract sensor name and wakeup status
                if 'Sensor:' in line_stripped:
                    sensor_name = line_stripped.replace('Sensor:', '').strip()
                else:
                    sensor_name = line_stripped
                
                # Determine wakeup status
                wakeup_status = "Wakeup" if "Wakeup" in line_stripped else "Non-wakeup"
                
                if sensor_name:
                    current_sensor = {
                        "name": sensor_name,
                        "full_name": f"{sensor_name} {wakeup_status}",
                        "values": [],
                        "raw_line": line_stripped
                    }
                    sensors.append(current_sensor)
            
            # Look for sensor event values (X=, Y=, Z=, or just numeric values)
            elif current_sensor and any(x in line_stripped for x in ['=', 'µT', 'lux', 'cm', 'rad/s', 'm/s²', 'mPa']):
                # This could be a value line
                current_sensor["values"].append(line_stripped)
        
        # If dumpsys didn't give us much, try alternative method using sensor framework
        if len(sensors) < 5:
            sensors = self._get_sensor_readings_alternative()
        
        return sensors
    
    def _get_sensor_readings_alternative(self) -> List[Dict]:
        """Alternative method to get sensor readings if dumpsys doesn't provide enough data."""
        sensors = []
        
        # Try using logcat to capture sensor events (requires sensor activity)
        # This is a fallback that attempts to get data from system logs
        stdout, _, code = self._run_cmd(["shell", "dumpsys", "sensorservice"], timeout=5)
        
        if code == 0 and stdout:
            # Parse alternative dumpsys output
            lines = stdout.split('\n')
            for line in lines:
                line = line.strip()
                if line and any(x in line for x in ['Sampling Rate:', 'Buffer:', 'Event:', 'Flush:']):
                    if not any(s['name'] in line for s in sensors):
                        sensor_entry = {
                            "name": line[:50],
                            "full_name": line,
                            "values": [],
                            "raw_line": line
                        }
                        sensors.append(sensor_entry)
        
        return sensors


class VulnerabilityScanner:
    """Main vulnerability scanner class."""
    
    def __init__(self, adb: ADBInterface, include_system: bool = False):
        self.adb = adb
        self.include_system = include_system
        self.scan_results: List[AppSecurityReport] = []
    
    def scan_all_apps(self, deep_scan: bool = False) -> List[AppSecurityReport]:
        """Scan all installed apps."""
        packages = self.adb.list_packages(self.include_system)
        
        console.print(f"\n[bold cyan]Found {len(packages)} apps to scan[/bold cyan]\n")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Scanning apps...", total=len(packages))
            
            for package in packages:
                progress.update(task, description=f"Scanning {package[:40]}...")
                report = self.scan_app(package, deep_scan)
                if report:
                    self.scan_results.append(report)
                progress.advance(task)
        
        return self.scan_results
    
    def scan_app(self, package: str, deep_scan: bool = False) -> Optional[AppSecurityReport]:
        """Scan a single app for vulnerabilities."""
        try:
            pkg_info = self.adb.get_package_info(package)
            
            if not pkg_info.get("permissions"):
                # Skip apps with no accessible info
                return None
            
            # Analyze permissions
            perm_analysis = analyze_permissions(pkg_info["permissions"])
            
            # Analyze SDK versions
            sdk_analysis = get_sdk_risk(
                pkg_info.get("target_sdk", 0),
                pkg_info.get("min_sdk", 0)
            )
            
            # Check for insecure URLs (only in deep scan)
            insecure_urls = []
            if deep_scan:
                insecure_urls = self.adb.search_apk_for_urls(package)
            
            # Create report
            report = create_app_report(
                package_name=package,
                app_name=self.adb.get_app_label(package),
                version_name=pkg_info.get("version_name", "Unknown"),
                version_code=pkg_info.get("version_code", 0),
                target_sdk=pkg_info.get("target_sdk", 0),
                min_sdk=pkg_info.get("min_sdk", 0),
                permissions=pkg_info.get("permissions", []),
                permission_analysis=perm_analysis,
                sdk_analysis=sdk_analysis,
                insecure_urls=insecure_urls
            )
            
            return report
            
        except Exception as e:
            console.print(f"[yellow]Warning: Could not scan {package}: {e}[/yellow]")
            return None
    
    def get_full_report(self) -> FullScanReport:
        """Generate a full scan report."""
        device_info = self.adb.get_device_info()
        return create_full_report(device_info, self.scan_results)


# CLI Commands
@click.group()
@click.option('--device', '-d', help='Target device serial number')
@click.pass_context
def cli(ctx, device):
    """Mobile App Vulnerability Scanner - Scan Android apps for security issues."""
    ctx.ensure_object(dict)
    ctx.obj['device'] = device


@cli.command('list-apps')
@click.option('--system', '-s', is_flag=True, help='Include system apps')
@click.pass_context
def list_apps(ctx, system):
    """List all installed apps on the device."""
    adb = ADBInterface(ctx.obj.get('device'))
    
    if not adb.check_connection():
        console.print("[red]Error: No Android device connected. Please connect via USB and enable debugging.[/red]")
        sys.exit(1)
    
    console.print("\n[bold cyan]📱 Fetching installed apps...[/bold cyan]\n")
    
    packages = adb.list_packages(system)
    
    table = Table(title="Installed Applications", box=box.ROUNDED)
    table.add_column("#", style="dim", width=4)
    table.add_column("Package Name", style="cyan")
    table.add_column("App Name", style="green")
    
    for i, pkg in enumerate(packages, 1):
        app_name = adb.get_app_label(pkg)
        table.add_row(str(i), pkg, app_name)
    
    console.print(table)
    console.print(f"\n[bold]Total: {len(packages)} apps[/bold]")


@cli.command('analyze')
@click.argument('package')
@click.option('--deep', '-d', is_flag=True, help='Perform deep APK analysis')
@click.pass_context
def analyze_app(ctx, package, deep):
    """Analyze a specific app for security issues."""
    adb = ADBInterface(ctx.obj.get('device'))
    
    if not adb.check_connection():
        console.print("[red]Error: No Android device connected.[/red]")
        sys.exit(1)
    
    console.print(f"\n[bold cyan]🔍 Analyzing {package}...[/bold cyan]\n")
    
    scanner = VulnerabilityScanner(adb)
    report = scanner.scan_app(package, deep)
    
    if not report:
        console.print(f"[red]Could not analyze {package}. Is it installed?[/red]")
        sys.exit(1)
    
    # Display results
    _display_app_report(report)


@cli.command('uninstall')
@click.argument('package')
@click.pass_context
def uninstall_app_cmd(ctx, package):
    """Uninstall an app from the device."""
    adb = ADBInterface(ctx.obj.get('device'))
    
    if not adb.check_connection():
        console.print("[red]Error: No Android device connected.[/red]")
        sys.exit(1)
    
    console.print(f"\n[bold cyan]🗑️  Uninstalling {package}...[/bold cyan]")
    
    if adb.uninstall_app(package):
        console.print(f"[bold green]✓ Successfully uninstalled {package}[/bold green]")
    else:
        console.print(f"[bold red]✗ Failed to uninstall {package}[/bold red]")
        sys.exit(1)


@cli.command('open')
@click.argument('package')
@click.pass_context
def open_app_cmd(ctx, package):
    """Open/launch an app on the device."""
    adb = ADBInterface(ctx.obj.get('device'))
    
    if not adb.check_connection():
        console.print("[red]Error: No Android device connected.[/red]")
        sys.exit(1)
    
    console.print(f"\n[bold cyan]▶️  Opening {package}...[/bold cyan]")
    
    if adb.open_app(package):
        console.print(f"[bold green]✓ Successfully opened {package}[/bold green]")
    else:
        console.print(f"[bold red]✗ Failed to open {package}. Is it installed?[/bold red]")
        sys.exit(1)


@cli.command('force-stop')
@click.argument('package')
@click.pass_context
def force_stop_cmd(ctx, package):
    """Force stop an app."""
    adb = ADBInterface(ctx.obj.get('device'))
    
    if not adb.check_connection():
        console.print("[red]Error: No Android device connected.[/red]")
        sys.exit(1)
    
    console.print(f"\n[bold cyan]⏹️  Force stopping {package}...[/bold cyan]")
    
    if adb.force_stop_app(package):
        console.print(f"[bold green]✓ Successfully force stopped {package}[/bold green]")
    else:
        console.print(f"[bold red]✗ Failed to force stop {package}[/bold red]")
        sys.exit(1)


@cli.command('scan')
@click.option('--system', '-s', is_flag=True, help='Include system apps')
@click.option('--deep', '-d', is_flag=True, help='Deep APK analysis (slower)')
@click.option('--format', '-f', 'output_format', 
              type=click.Choice(['console', 'html', 'json', 'text', 'all']),
              default='console', help='Output format')
@click.option('--output', '-o', help='Output directory for reports')
@click.pass_context
def scan(ctx, system, deep, output_format, output):
    """Scan all installed apps for security vulnerabilities."""
    adb = ADBInterface(ctx.obj.get('device'))
    
    if not adb.check_connection():
        console.print(Panel(
            "[red]No Android device connected![/red]\n\n"
            "Please ensure:\n"
            "1. USB debugging is enabled on your device\n"
            "2. The device is connected via USB\n"
            "3. You have authorized this computer for debugging\n"
            "4. ADB is installed and in your PATH",
            title="Connection Error",
            border_style="red"
        ))
        sys.exit(1)
    
    # Display device info
    device_info = adb.get_device_info()
    console.print(Panel(
        f"[bold]Device:[/bold] {device_info.get('manufacturer', 'Unknown')} {device_info.get('model', 'Unknown')}\n"
        f"[bold]Android:[/bold] {device_info.get('android_version', 'Unknown')} (SDK {device_info.get('sdk_version', 'Unknown')})\n"
        f"[bold]Security Patch:[/bold] {device_info.get('security_patch', 'Unknown')}",
        title="📱 Connected Device",
        border_style="cyan"
    ))
    
    scanner = VulnerabilityScanner(adb, system)
    
    console.print("\n[bold cyan]🔒 Starting Security Scan...[/bold cyan]")
    if deep:
        console.print("[yellow]Deep scan enabled - this may take longer[/yellow]")
    
    results = scanner.scan_all_apps(deep)
    full_report = scanner.get_full_report()
    
    # Display summary
    _display_scan_summary(full_report)
    
    # Generate reports if requested
    if output_format != 'console':
        output_dir = output or "reports"
        generator = ReportGenerator(output_dir)
        
        console.print(f"\n[bold cyan]📄 Generating reports...[/bold cyan]")
        
        if output_format == 'all':
            files = generator.generate_all(full_report)
            for fmt, path in files.items():
                console.print(f"  ✓ {fmt.upper()}: {path}")
        elif output_format == 'html':
            path = generator.generate_html(full_report)
            console.print(f"  ✓ HTML: {path}")
        elif output_format == 'json':
            path = generator.generate_json(full_report)
            console.print(f"  ✓ JSON: {path}")
        elif output_format == 'text':
            path = generator.generate_text(full_report)
            console.print(f"  ✓ Text: {path}")
    
    # Show high-risk apps
    if output_format == 'console':
        _display_high_risk_apps(full_report)


@cli.command('demo')
def demo():
    """Run a demo scan with sample data (no device needed)."""
    console.print(Panel(
        "[bold cyan]Demo Mode[/bold cyan]\n\n"
        "This demonstrates the scanner output using sample data.\n"
        "Connect an Android device for real scanning.",
        title="📱 V Scanner Demo"
    ))
    
    # Create sample data
    sample_apps = [
        {
            "package_name": "com.social.app",
            "app_name": "Social Media App",
            "permissions": [
                "android.permission.CAMERA",
                "android.permission.RECORD_AUDIO",
                "android.permission.ACCESS_FINE_LOCATION",
                "android.permission.READ_CONTACTS",
                "android.permission.READ_SMS",
                "android.permission.INTERNET"
            ],
            "target_sdk": 31,
            "min_sdk": 21
        },
        {
            "package_name": "com.banking.app",
            "app_name": "Banking App",
            "permissions": [
                "android.permission.INTERNET",
                "android.permission.ACCESS_FINE_LOCATION",
                "android.permission.CAMERA",
                "android.permission.SYSTEM_ALERT_WINDOW"
            ],
            "target_sdk": 33,
            "min_sdk": 26
        },
        {
            "package_name": "com.game.casual",
            "app_name": "Casual Game",
            "permissions": [
                "android.permission.INTERNET",
                "android.permission.ACCESS_WIFI_STATE"
            ],
            "target_sdk": 33,
            "min_sdk": 24
        },
        {
            "package_name": "com.flashlight.free",
            "app_name": "Free Flashlight",
            "permissions": [
                "android.permission.CAMERA",
                "android.permission.ACCESS_FINE_LOCATION",
                "android.permission.READ_CONTACTS",
                "android.permission.READ_CALL_LOG",
                "android.permission.SEND_SMS",
                "android.permission.RECORD_AUDIO",
                "android.permission.INTERNET"
            ],
            "target_sdk": 28,
            "min_sdk": 19
        }
    ]
    
    reports = []
    for app in sample_apps:
        perm_analysis = analyze_permissions(app["permissions"])
        sdk_analysis = get_sdk_risk(app["target_sdk"], app["min_sdk"])
        
        report = create_app_report(
            package_name=app["package_name"],
            app_name=app["app_name"],
            version_name="1.0.0",
            version_code=1,
            target_sdk=app["target_sdk"],
            min_sdk=app["min_sdk"],
            permissions=app["permissions"],
            permission_analysis=perm_analysis,
            sdk_analysis=sdk_analysis,
            insecure_urls=["http://api.example.com/data"] if "flashlight" in app["package_name"] else []
        )
        reports.append(report)
    
    device_info = {
        "model": "Demo Device",
        "manufacturer": "Sample",
        "android_version": "13",
        "sdk_version": "33",
        "security_patch": "2024-01-01"
    }
    
    full_report = create_full_report(device_info, reports)
    
    _display_scan_summary(full_report)
    _display_high_risk_apps(full_report)
    
    # Generate sample reports
    generator = ReportGenerator("reports")
    files = generator.generate_all(full_report, "demo_report")
    
    console.print("\n[bold cyan]📄 Demo reports generated:[/bold cyan]")
    for fmt, path in files.items():
        console.print(f"  ✓ {fmt.upper()}: {path}")


def _display_app_report(report: AppSecurityReport):
    """Display detailed app report to console."""
    # Risk badge color
    risk_colors = {
        "CRITICAL": "red",
        "HIGH": "orange3",
        "MEDIUM": "yellow",
        "LOW": "green",
        "INFO": "blue"
    }
    color = risk_colors.get(report.risk_level, "white")
    
    console.print(Panel(
        f"[bold]{report.app_name}[/bold]\n"
        f"Package: [dim]{report.package_name}[/dim]\n"
        f"Version: {report.version_name} ({report.version_code})\n"
        f"Target SDK: {report.target_sdk} | Min SDK: {report.min_sdk}",
        title="📱 App Information"
    ))
    
    # Risk Score
    meter = "█" * (report.risk_score // 5) + "░" * (20 - report.risk_score // 5)
    console.print(f"\n[bold]Risk Score:[/bold] [{color}]{meter}[/{color}] {report.risk_score}/100 [{color}]{report.risk_level}[/{color}]")
    
    # Dangerous Permissions
    if report.dangerous_permissions:
        console.print(f"\n[bold red]⚠️ Dangerous Permissions ({len(report.dangerous_permissions)}):[/bold red]")
        
        table = Table(box=box.SIMPLE)
        table.add_column("Permission", style="cyan")
        table.add_column("Risk", width=10)
        table.add_column("Description")
        
        for perm in report.dangerous_permissions:
            risk_color = risk_colors.get(perm.get('risk_level', 'MEDIUM'), 'white')
            table.add_row(
                perm.get('name', 'Unknown'),
                f"[{risk_color}]{perm.get('risk_level', 'MEDIUM')}[/{risk_color}]",
                perm.get('description', '')
            )
        
        console.print(table)
    
    # SDK Issues
    if report.sdk_issues:
        console.print("\n[bold yellow]📦 SDK Issues:[/bold yellow]")
        for issue in report.sdk_issues:
            console.print(f"  ⚠ {issue}")
    
    # Insecure URLs
    if report.insecure_urls:
        console.print("\n[bold red]🔓 Insecure URLs Found:[/bold red]")
        for url in report.insecure_urls[:10]:
            console.print(f"  ✗ {url}")
    
    # Recommendations
    if report.recommendations:
        console.print("\n[bold cyan]💡 Recommendations:[/bold cyan]")
        for rec in report.recommendations[:10]:
            console.print(f"  → {rec}")


def _display_scan_summary(report: FullScanReport):
    """Display scan summary."""
    console.print("\n")
    console.print(Panel(
        f"[bold]Total Apps Scanned:[/bold] {report.total_apps}\n"
        f"[bold red]High Risk:[/bold red] {report.high_risk_apps}\n"
        f"[bold yellow]Medium Risk:[/bold yellow] {report.medium_risk_apps}\n"
        f"[bold green]Low Risk:[/bold green] {report.low_risk_apps}\n\n"
        f"[bold]Dangerous Permissions Found:[/bold] {report.summary.get('total_dangerous_permissions', 0)}\n"
        f"[bold]Apps with Insecure URLs:[/bold] {report.summary.get('apps_with_insecure_urls', 0)}",
        title="📊 Scan Summary",
        border_style="cyan"
    ))


def _display_high_risk_apps(report: FullScanReport):
    """Display high-risk apps table."""
    high_risk = [app for app in report.apps if app.risk_level in ["CRITICAL", "HIGH"]]
    
    if not high_risk:
        console.print("\n[bold green]✓ No high-risk apps found![/bold green]")
        return
    
    console.print(f"\n[bold red]⚠️ High Risk Applications ({len(high_risk)}):[/bold red]\n")
    
    table = Table(box=box.ROUNDED)
    table.add_column("App Name", style="bold")
    table.add_column("Package")
    table.add_column("Risk", width=10)
    table.add_column("Score", width=8)
    table.add_column("Issues", width=40)
    
    risk_colors = {"CRITICAL": "red", "HIGH": "orange3"}
    
    for app in high_risk[:15]:
        color = risk_colors.get(app.risk_level, "white")
        issues = []
        if app.dangerous_permissions:
            issues.append(f"{len(app.dangerous_permissions)} dangerous perms")
        if app.sdk_issues:
            issues.append(f"{len(app.sdk_issues)} SDK issues")
        if app.insecure_urls:
            issues.append(f"{len(app.insecure_urls)} insecure URLs")
        
        table.add_row(
            app.app_name[:25],
            app.package_name[:35],
            f"[{color}]{app.risk_level}[/{color}]",
            str(app.risk_score),
            ", ".join(issues) or "Review recommended"
        )
    
    console.print(table)
    
    if len(high_risk) > 15:
        console.print(f"\n[dim]... and {len(high_risk) - 15} more high-risk apps[/dim]")


if __name__ == "__main__":
    console.print(Panel(
        "[bold cyan]V Scanner[/bold cyan] - Mobile App Vulnerability Scanner\n"
        "[dim]Scan Android apps for security vulnerabilities[/dim]",
        box=box.DOUBLE
    ))
    cli()
