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
import os
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
    
    def get_full_device_info(self) -> Dict:
        """Get complete device information including IP, MAC, IMEI, Bluetooth, etc."""
        full_info = {}
        
        # Get IP Address
        try:
            stdout, _, _ = self._run_cmd(["shell", "ip", "addr", "show"], timeout=5)
            if stdout:
                for line in stdout.split('\n'):
                    if 'inet ' in line and 'inet6' not in line:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            full_info['ip_address'] = parts[1].split('/')[0]
                            break
        except:
            pass
        
        if 'ip_address' not in full_info:
            full_info['ip_address'] = 'N/A'
        
        # Get MAC Address
        try:
            stdout, _, _ = self._run_cmd(["shell", "cat", "/sys/class/net/wlan0/address"], timeout=5)
            if stdout:
                full_info['mac_address'] = stdout.strip().upper()
        except:
            full_info['mac_address'] = 'N/A'
        
        # Get IMEI
        try:
            stdout, _, _ = self._run_cmd(["shell", "service", "call", "iphonesubscriptionservice", "1"], timeout=5)
            if stdout and "'" in stdout:
                # Parse IMEI from service call output
                parts = stdout.split("'")
                imei = ''.join([p for p in parts if p.isdigit()])
                if len(imei) >= 10:
                    full_info['imei'] = imei[:15]
        except:
            pass
        
        if 'imei' not in full_info:
            # Fallback to getprop
            try:
                stdout, _, _ = self._run_cmd(["shell", "getprop", "ro.serialno"], timeout=5)
                if stdout:
                    full_info['imei'] = stdout.strip()
            except:
                full_info['imei'] = 'N/A'
        
        # Get Bluetooth Info
        try:
            stdout, _, _ = self._run_cmd(["shell", "dumpsys", "bluetooth_manager"], timeout=5)
            if stdout:
                for line in stdout.split('\n'):
                    if 'mName=' in line or 'name=' in line.lower():
                        full_info['bluetooth_name'] = line.split('=')[1].strip() if '=' in line else 'Unknown'
                        break
                    if 'address:' in line.lower() or 'bluetooth address' in line.lower():
                        full_info['bluetooth_address'] = line.split(':')[1].strip() if ':' in line else 'Unknown'
        except:
            pass
        
        if 'bluetooth_name' not in full_info:
            full_info['bluetooth_name'] = 'N/A'
        if 'bluetooth_address' not in full_info:
            full_info['bluetooth_address'] = 'N/A'
        
        # Get Phone Number
        try:
            stdout, _, _ = self._run_cmd(["shell", "dumpsys", "iphonesubscriptionservice"], timeout=5)
            if stdout:
                phone = 'N/A'
                full_info['phone_number'] = phone
        except:
            full_info['phone_number'] = 'N/A'
        
        # Get Device Name/Host Name
        try:
            stdout, _, _ = self._run_cmd(["shell", "getprop", "ro.serialno"], timeout=5)
            if stdout:
                full_info['device_name'] = stdout.strip()
        except:
            full_info['device_name'] = 'N/A'
        
        # Get Build Fingerprint
        try:
            stdout, _, _ = self._run_cmd(["shell", "getprop", "ro.build.fingerprint"], timeout=5)
            if stdout:
                full_info['build_fingerprint'] = stdout.strip()
        except:
            full_info['build_fingerprint'] = 'N/A'
        
        # Get Bootloader
        try:
            stdout, _, _ = self._run_cmd(["shell", "getprop", "ro.bootloader"], timeout=5)
            if stdout:
                full_info['bootloader'] = stdout.strip()
        except:
            full_info['bootloader'] = 'N/A'
        
        # Get Display ID
        try:
            stdout, _, _ = self._run_cmd(["shell", "getprop", "ro.build.display.id"], timeout=5)
            if stdout:
                full_info['display_id'] = stdout.strip()
        except:
            full_info['display_id'] = 'N/A'
        
        # Get IMSI (not always accessible without permissions)
        try:
            stdout, _, _ = self._run_cmd(["shell", "service", "call", "iphonesubscriptionservice", "4"], timeout=5)
            if stdout:
                full_info['imsi'] = stdout.strip()[:20]
        except:
            full_info['imsi'] = 'N/A'
        
        # Get Time Zone
        try:
            stdout, _, _ = self._run_cmd(["shell", "getprop", "persist.sys.timezone"], timeout=5)
            if stdout:
                full_info['timezone'] = stdout.strip()
        except:
            full_info['timezone'] = 'N/A'
        
        # Get Locale
        try:
            stdout, _, _ = self._run_cmd(["shell", "getprop", "ro.product.locale"], timeout=5)
            if stdout:
                full_info['locale'] = stdout.strip()
        except:
            full_info['locale'] = 'N/A'
        
        return full_info
    
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
        """Get app label - simple and reliable fallback to package name parsing."""
        import re
        
        # Quick cache for known apps (most common)
        quick_labels = {
            "com.discord": "Discord",
            "org.telegram.messenger": "Telegram",
            "com.whatsapp": "WhatsApp",
            "com.facebook.katana": "Facebook",
            "com.twitter.android": "Twitter/X",
            "com.google.android.apps.messaging": "Messages",
            "com.google.android.apps.maps": "Google Maps",
            "com.spotify.music": "Spotify",
            "com.netflix.mediaclient": "Netflix",
            "com.instagram.android": "Instagram",
            "com.google.android.youtube": "YouTube",
            "com.google.android.apps.youtube.music": "YouTube Music",
            "com.google.android.gms": "Google Play Services",
            "com.android.systemui": "System UI",
            "com.android.settings": "Settings",
            "com.android.contacts": "Contacts",
            "com.android.dialer": "Phone",
            "com.android.calendar": "Calendar",
            "com.android.launcher": "Launcher",
            "android": "Android System",
        }
        
        if package in quick_labels:
            return quick_labels[package]
        
        # Strategy: Parse package name intelligently
        # com.example.app -> Example App
        # com.shazam.android -> Shazam
        # org.github.alexand.ksuwebui -> Ksuwebui
        
        parts = package.split('.')
        
        # Get meaningful part (usually 2nd or 3rd from end)
        app_name = ''
        
        # If it starts with com.google, take special care
        if parts[0] == 'com' and len(parts) > 1:
            if parts[1] == 'google':
                if len(parts) > 2:
                    # com.google.android.xxx -> Take from 'apps' onward if present
                    try:
                        apps_idx = parts.index('apps')
                        if apps_idx < len(parts) - 1:
                            app_name = parts[apps_idx + 1]
                    except:
                        # Otherwise just take the most descriptive part
                        app_name = parts[-1]
                else:
                    app_name = parts[-1]
            elif parts[1] in ['samsung', 'shazam', 'example']:
                app_name = parts[1].capitalize()
            else:
                # com.yourcompany.app -> take last 1-2 parts
                if len(parts) >= 3:
                    app_name = parts[-2] if parts[-2] not in ['mobile', 'android', 'app'] else parts[-1]
                else:
                    app_name = parts[-1]
        elif parts[0] == 'org':
            if len(parts) > 1:
                app_name = parts[1].capitalize()
        else:
            app_name = parts[-1]
        
        # Clean and format the app name
        app_name = app_name.replace('_', ' ').replace('-', ' ').strip()
        
        # Title case but preserve some special words
        words = app_name.split()
        formatted_words = []
        for word in words:
            if len(word) > 1:
                formatted_words.append(word[0].upper() + word[1:].lower())
            else:
                formatted_words.append(word.upper())
        
        result = ' '.join(formatted_words)
        
        # Safety: ensure it's not too long and looks reasonable
        if len(result) <= 2:
            result = package
        
        return result[:40]  # Max 40 chars


    def get_hardware_usage(self) -> Dict:
        """Get hardware usage (camera, mic, flashlight, etc.) and apps using them."""
        hardware_usage = {
            "camera_front": [],
            "camera_back": [],
            "microphone": [],
            "flashlight": [],
            "location": [],
            "sensors": []
        }
        
        try:
            # Get foreground app
            stdout, _, _ = self._run_cmd(["shell", "dumpsys", "window", "windows"])
            current_app = None
            if stdout:
                lines = stdout.split('\n')
                for line in lines:
                    if 'mCurrentFocus' in line:
                        # Extract package name from current focus
                        parts = line.split('/')
                        if len(parts) >= 1:
                            pkg_part = parts[0].split()[-1]
                            if '{' in pkg_part:
                                current_app = pkg_part.split('{')[-1]
            
            # Get all connected devices/sensors being accessed
            stdout, _, _ = self._run_cmd(["shell", "dumpsys", "camera"])
            if stdout and 'in use' in stdout:
                if current_app:
                    hardware_usage["camera_back"].append(current_app)
            
            # Check audio
            stdout, _, _ = self._run_cmd(["shell", "dumpsys", "audio"])
            if stdout and 'RECORD_AUDIO' in stdout and current_app:
                hardware_usage["microphone"].append(current_app)
            
            # Get dangerous permissions being used
            if current_app:
                stdout, _, _ = self._run_cmd(["shell", "dumpsys", "package", f"perms/{current_app}"])
                if 'CAMERA' in stdout:
                    hardware_usage["camera_back"].append(current_app)
                if 'RECORD_AUDIO' in stdout:
                    hardware_usage["microphone"].append(current_app)
                if 'ACCESS_FINE_LOCATION' in stdout:
                    hardware_usage["location"].append(current_app)
        
        except Exception:
            pass
        
        return hardware_usage

    def get_sensor_values_live(self) -> Dict:
        """Get current sensor values like CPU-Z (Accelerometer, Magnetometer, Gyroscope, etc)."""
        sensor_values = {}
        
        try:
            # Method 1: Try dumpsys sensorservice 
            stdout, _, code = self._run_cmd(["shell", "dumpsys", "sensorservice"], timeout=10)
            
            if code == 0 and stdout:
                lines = stdout.split('\n')
                
                for line in lines:
                    line = line.strip()
                    
                    # Look for sensor name lines
                    if 'Accelerometer' in line or 'Magnetometer' in line or 'Gyroscope' in line or \
                       'Proximity' in line or 'Light' in line or 'Barometer' in line or \
                       'Temperature' in line or 'Humidity' in line:
                        
                        # Extract sensor name and values
                        if ':' in line:
                            parts = line.split(':')
                            sensor_name = parts[0].strip()
                            sensor_data = parts[1].strip() if len(parts) > 1 else ''
                            
                            if sensor_name and sensor_data:
                                if sensor_name not in sensor_values:
                                    sensor_values[sensor_name] = []
                                sensor_values[sensor_name].append(sensor_data[:80])
        except:
            pass
        
        # Method 2: List available sensors
        if not sensor_values:
            try:
                stdout, _, code = self._run_cmd(["shell", "dumpsys", "sensormanager"], timeout=10)
                
                if code == 0 and stdout:
                    lines = stdout.split('\n')
                    
                    sensor_names = {
                        'Accelerometer': False,
                        'Magnetometer': False,
                        'Gyroscope': False,
                        'Light Sensor': False,
                        'Proximity Sensor': False,
                        'Barometer': False,
                        'Thermometer': False,
                        'Humidity Sensor': False,
                        'Step Counter': False,
                        'Tilt Detector': False,
                    }
                    
                    for line in lines:
                        for sensor_name in sensor_names:
                            if sensor_name.lower() in line.lower():
                                sensor_names[sensor_name] = True
                    
                    # Add detected sensors
                    for sensor_name, detected in sensor_names.items():
                        if detected:
                            sensor_values[sensor_name] = ["Detected and available"]
            except:
                pass
        
        # Method 3: Static sensor report for devices  
        if not sensor_values:
            try:
                # Get device info to infer sensors
                stdout, _, code = self._run_cmd(["shell", "getprop", "ro.hardware"], timeout=5)
                
                # Most Android devices have these basic sensors
                default_sensors = {
                    'Accelerometer (X, Y, Z)': ['m/s²'],
                    'Magnetometer (X, Y, Z)': ['µT'],
                    'Gyroscope (X, Y, Z)': ['°/s'],
                    'Light Sensor': ['Lux'],
                    'Proximity Sensor': ['cm'],
                }
                
                sensor_values = default_sensors
            except:
                pass
        
        return sensor_values
    
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
    
    def capture_screen(self, output_path: str = None) -> Optional[str]:
        """Capture device screen and save to local file."""
        try:
            import tempfile
            import time
            
            # Use temp directory if no output path provided
            if output_path is None:
                temp_dir = tempfile.gettempdir()
                output_path = os.path.join(temp_dir, "phone_screen.png")
            
            # Capture screenshot on device
            device_screenshot = "/sdcard/screen_capture.png"
            
            # Take screenshot
            stdout, stderr, code = self._run_cmd(["shell", "screencap", "-p", device_screenshot])
            if code != 0:
                return None
            
            time.sleep(0.5)
            
            # Pull screenshot to local machine
            stdout, stderr, code = self._run_cmd(["pull", device_screenshot, output_path])
            if code != 0:
                return None
            
            time.sleep(0.5)
            
            # Clean up device file
            self._run_cmd(["shell", "rm", device_screenshot])
            
            return output_path
        except Exception as e:
            return None
    
    def start_screen_mirroring(self) -> bool:
        """Start live screen mirroring using scrcpy."""
        try:
            # Build scrcpy command
            cmd = ["scrcpy"]
            
            # Add device if specified
            if self.device:
                cmd.extend(["-s", self.device])
            
            # Optional parameters for better experience
            cmd.extend([
                "-m", "1024",  # Limit resolution for performance
                "--max-fps", "30",  # Limit FPS
            ])
            
            # Start scrcpy process (non-blocking)
            subprocess.Popen(cmd)
            return True
        except Exception as e:
            return False
    
    def check_scrcpy_installed(self) -> bool:
        """Check if scrcpy is installed on the system."""
        try:
            result = subprocess.run(
                ["scrcpy", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False
    
    def wake_up_device(self) -> bool:
        """Wake up device screen and turn it on."""
        try:
            import time
            # Wake up the device with power button
            self._run_cmd(["shell", "input", "keyevent", "26"])
            time.sleep(1.5)
            
            # Swipe up to dismiss lockscreen if needed
            self._run_cmd(["shell", "input", "swipe", "300", "1000", "300", "500"])
            time.sleep(1)
            
            return True
        except Exception:
            return False
    
    def detect_lock_type(self) -> Optional[str]:
        """Detect device lock type (PIN, Pattern, or Password)."""
        try:
            import time
            # First wake up the device
            self.wake_up_device()
            time.sleep(1)
            
            # Check if device is locked by checking for keyguard
            stdout, _, _ = self._run_cmd(["shell", "dumpsys", "window", "policy"])
            
            if "isSecure=true" in stdout or "isSystemSecure=1" in stdout:
                # Device has security lock enabled
                
                # Try to detect lock type from settings
                stdout_lock, _, _ = self._run_cmd(["shell", "settings", "get", "secure", "lock_pattern_visible_pattern"])
                if stdout_lock.strip() and stdout_lock.strip() != "null":
                    return "pattern"
                
                # Check for lock pattern autolock
                stdout_pattern, _, _ = self._run_cmd(["shell", "settings", "get", "secure", "lock_pattern_autolock"])
                if stdout_pattern.strip() and stdout_pattern.strip() != "null":
                    return "pattern"
                
                # Check device policy for password requirements
                stdout_policy, _, _ = self._run_cmd(["shell", "dumpsys", "devicepolicy"])
                if "passwordMinimumLength" in stdout_policy or "passwordQuality" in stdout_policy:
                    return "password"
                
                # Default to PIN if secure but can't determine exactly
                return "pin"
            
            # No security lock detected
            return None
        except Exception as e:
            return None
    
    def check_is_locked(self) -> bool:
        """Check if device screen is currently locked."""
        try:
            stdout, _, _ = self._run_cmd(["shell", "dumpsys", "window", "policy"])
            # Check if locked
            return "isSecure=true" in stdout or "isSystemSecure=1" in stdout
        except Exception:
            return False
    
    def unlock_with_pin(self, pin: str, verbose: bool = True) -> bool:
        """Attempt to unlock device with PIN using direct command sequence."""
        try:
            import time
            
            debug_info = []
            
            # Wake screen
            if verbose:
                print("[*] Step 1: Pressing power button...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "keyevent", "26"])
            debug_info.append(f"Power button - Code: {code}, Stdout: {stdout.strip()}, Stderr: {stderr.strip()}")
            if verbose:
                print(f"    Return code: {code}")
                if stderr.strip():
                    print(f"    Error: {stderr.strip()}")
            time.sleep(1.5)
            
            # Swipe up to reveal input field
            if verbose:
                print("[*] Step 2: Swiping up...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "swipe", "300", "1000", "300", "500"])
            debug_info.append(f"Swipe up - Code: {code}, Stdout: {stdout.strip()}, Stderr: {stderr.strip()}")
            if verbose:
                print(f"    Return code: {code}")
                if stderr.strip():
                    print(f"    Error: {stderr.strip()}")
            time.sleep(1)
            
            # Check device state
            if verbose:
                print("[*] Step 2.5: Checking device state...")
            stdout, stderr, code = self._run_cmd(["shell", "dumpsys", "window", "policy"])
            debug_info.append(f"Device state - Code: {code}, Has 'isSecure': {'isSecure' in stdout}")
            if verbose:
                print(f"    Device secure: {'Yes' if 'isSecure=true' in stdout else 'No'}")
            
            # Enter the PIN
            if verbose:
                print(f"[*] Step 3: Entering PIN ({len(pin)} digits)...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "text", pin])
            debug_info.append(f"Enter PIN - Code: {code}, Stdout: {stdout.strip()}, Stderr: {stderr.strip()}")
            if verbose:
                print(f"    Return code: {code}")
                if stderr.strip():
                    print(f"    Error: {stderr.strip()}")
            time.sleep(0.5)
            
            # Send enter to submit
            if verbose:
                print("[*] Step 4: Pressing Enter key...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "keyevent", "66"])
            debug_info.append(f"Press Enter - Code: {code}, Stdout: {stdout.strip()}, Stderr: {stderr.strip()}")
            if verbose:
                print(f"    Return code: {code}")
                if stderr.strip():
                    print(f"    Error: {stderr.strip()}")
            time.sleep(2)
            
            # Final device state check
            if verbose:
                print("[*] Step 5: Final device state check...")
            stdout, stderr, code = self._run_cmd(["shell", "dumpsys", "window", "policy"])
            is_locked = "isSecure=true" in stdout
            debug_info.append(f"Final state - Code: {code}, Still locked: {is_locked}")
            if verbose:
                print(f"    Device still locked: {is_locked}")
            
            if verbose:
                print("\n[DEBUG] Full unlock sequence:")
                for info in debug_info:
                    print(f"  • {info}")
            
            return True
        except Exception as e:
            if verbose:
                print(f"[ERROR] Exception: {str(e)}")
            return False
    
    def unlock_with_pattern(self, pattern: str, verbose: bool = True) -> bool:
        """Attempt to unlock device with pattern (dot numbers 1-9)."""
        try:
            import time
            
            debug_info = []
            
            # Wake screen
            if verbose:
                print("[*] Step 1: Pressing power button...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "keyevent", "26"])
            debug_info.append(f"Power button - Code: {code}")
            if verbose:
                print(f"    Return code: {code}")
            time.sleep(1.5)
            
            # Swipe up to reveal pattern input
            if verbose:
                print("[*] Step 2: Swiping up...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "swipe", "300", "1000", "300", "500"])
            debug_info.append(f"Swipe up - Code: {code}")
            if verbose:
                print(f"    Return code: {code}")
            time.sleep(1)
            
            # Standard pattern grid coordinates
            coords = {
                '1': (200, 400),  '2': (400, 400),  '3': (600, 400),
                '4': (200, 600),  '5': (400, 600),  '6': (600, 600),
                '7': (200, 800),  '8': (400, 800),  '9': (600, 800)
            }
            
            if len(pattern) < 4:
                return False
            
            first_dot = pattern[0]
            if first_dot not in coords:
                return False
            
            x, y = coords[first_dot]
            time.sleep(0.3)
            
            # Perform swipe through all dots
            if verbose:
                print(f"[*] Step 3: Tracing pattern...")
            for i, dot in enumerate(pattern):
                if dot not in coords:
                    return False
                nx, ny = coords[dot]
                stdout, stderr, code = self._run_cmd(["shell", "input", "swipe", str(x), str(y), str(nx), str(ny), "200"])
                debug_info.append(f"Pattern dot {i+1} ({dot}) - Code: {code}")
                if verbose:
                    print(f"    Dot {i+1} ({dot}): Return code {code}")
                x, y = nx, ny
                time.sleep(0.2)
            
            time.sleep(1)
            
            # Send enter to confirm
            if verbose:
                print("[*] Step 4: Confirming pattern...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "keyevent", "66"])
            debug_info.append(f"Press Enter - Code: {code}")
            if verbose:
                print(f"    Return code: {code}")
            time.sleep(2)
            
            if verbose:
                print("\n[DEBUG] Full pattern sequence:")
                for info in debug_info:
                    print(f"  • {info}")
            
            return True
        except Exception as e:
            if verbose:
                print(f"[ERROR] Exception: {str(e)}")
            return False
    
    def unlock_with_password(self, password: str, verbose: bool = True) -> bool:
        """Attempt to unlock device with password using direct command sequence."""
        try:
            import time
            
            debug_info = []
            
            # Wake screen
            if verbose:
                print("[*] Step 1: Pressing power button...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "keyevent", "26"])
            debug_info.append(f"Power button - Code: {code}")
            if verbose:
                print(f"    Return code: {code}")
            time.sleep(1.5)
            
            # Swipe up to reveal input field
            if verbose:
                print("[*] Step 2: Swiping up...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "swipe", "300", "1000", "300", "500"])
            debug_info.append(f"Swipe up - Code: {code}")
            if verbose:
                print(f"    Return code: {code}")
            time.sleep(1)
            
            # Enter the password
            if verbose:
                print(f"[*] Step 3: Entering password ({len(password)} characters)...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "text", password])
            debug_info.append(f"Enter password - Code: {code}, Stdout: {stdout.strip()}, Stderr: {stderr.strip()}")
            if verbose:
                print(f"    Return code: {code}")
                if stderr.strip():
                    print(f"    Error: {stderr.strip()}")
            time.sleep(0.5)
            
            # Send enter to submit
            if verbose:
                print("[*] Step 4: Pressing Enter key...")
            stdout, stderr, code = self._run_cmd(["shell", "input", "keyevent", "66"])
            debug_info.append(f"Press Enter - Code: {code}")
            if verbose:
                print(f"    Return code: {code}")
            time.sleep(2)
            
            # Final device state check
            if verbose:
                print("[*] Step 5: Final device state check...")
            stdout, stderr, code = self._run_cmd(["shell", "dumpsys", "window", "policy"])
            is_locked = "isSecure=true" in stdout
            debug_info.append(f"Final state - Code: {code}, Still locked: {is_locked}")
            if verbose:
                print(f"    Device still locked: {is_locked}")
            
            if verbose:
                print("\n[DEBUG] Full unlock sequence:")
                for info in debug_info:
                    print(f"  • {info}")
            
            return True
        except Exception as e:
            if verbose:
                print(f"[ERROR] Exception: {str(e)}")
            return False
    
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
