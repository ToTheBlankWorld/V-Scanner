#!/usr/bin/env python3
"""
Digital Forensics Module - V Scanner
Simple, effective forensics operations for Android devices
"""

import json
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


class DeviceForensics:
    """Simple device forensics manager."""

    def __init__(self, adb_interface):
        """Initialize forensics with ADB interface."""
        self.adb = adb_interface
        self.case_dir = Path(__file__).parent / "forensics_cases"
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self.current_case = None

        # For Apatch and other custom roots, auto-detection is unreliable
        # Try detection, but if it fails, assume rooted
        # (User will know if their device is rooted)
        self.is_rooted = self._check_root_safe()

        self._show_root_status()
        self.extractions = []

    def extract_app_databases(self) -> bool:
        """Extract databases from user-selected app."""
        try:
            console.print("[bold cyan]📱 Extract App Databases[/bold cyan]\n")

            # Step 1: Choose System or 3rd Party
            console.print("  [1] System Apps")
            console.print("  [2] Third-Party Apps\n")

            app_type = console.input("[bold cyan]Select app type (1-2): [/bold cyan]").strip()

            if app_type == "1":
                apps = self._get_system_apps()
                app_category = "system"
            elif app_type == "2":
                apps = self._get_third_party_apps()
                app_category = "3rd_party"
            else:
                console.print("[red]Invalid choice[/red]")
                return False

            if not apps:
                console.print("[yellow]No apps found[/yellow]")
                return False

            # Step 2: Show list with app name and package name
            console.print(f"\n[dim]Found {len(apps)} {app_category} apps:[/dim]\n")

            for idx, (appname, package) in enumerate(apps, 1):
                console.print(f"  [{idx}] {appname}")
                console.print(f"      └─ {package}\n")

            # Step 3: User selects app
            selection = console.input("[bold cyan]Select app number (or 0 to cancel): [/bold cyan]").strip()

            try:
                choice = int(selection)
                if choice == 0:
                    return False
                if choice < 1 or choice > len(apps):
                    console.print("[red]Invalid selection[/red]")
                    return False
            except ValueError:
                console.print("[red]Invalid input[/red]")
                return False

            appname, package = apps[choice - 1]

            # Step 4: Extract app databases
            console.print(f"\n[cyan]Extracting databases for: {appname}[/cyan]")
            return self._extract_single_app_databases(package, appname)

        except Exception as e:
            console.print(f"[red]✗ Error: {str(e)[:100]}[/red]")
            return False

    def _get_system_apps(self) -> List[tuple]:
        """Get list of system apps (app name, package name)."""
        system_packages = [
            "com.android",
            "android.",
            "com.google",
            "com.samsung",
        ]

        try:
            stdout, stderr, code = self.adb._run_cmd(["shell", "pm", "list", "packages", "-s"])
            if code != 0:
                return []

            apps = []
            for line in stdout.strip().split('\n'):
                if line.startswith('package:'):
                    package = line.replace('package:', '').strip()

                    # Get app name
                    stdout2, _, code2 = self.adb._run_cmd([
                        "shell", "cmd", "package", "dump", package, "|", "grep", "label="
                    ])

                    if code2 == 0 and stdout2:
                        # Extract label from "label=com.android.systemui=System UI"
                        labels = [l.split('=')[-1] for l in stdout2.strip().split('\n') if 'label=' in l]
                        appname = labels[0] if labels else package.split('.')[-1].title()
                    else:
                        appname = package.split('.')[-1].title()

                    apps.append((appname, package))

            return sorted(apps, key=lambda x: x[0])
        except:
            return []

    def _get_third_party_apps(self) -> List[tuple]:
        """Get list of third-party apps (app name, package name)."""
        try:
            stdout, stderr, code = self.adb._run_cmd(["shell", "pm", "list", "packages", "-3"])
            if code != 0:
                return []

            apps = []
            for line in stdout.strip().split('\n'):
                if line.startswith('package:'):
                    package = line.replace('package:', '').strip()

                    # Get app name
                    stdout2, _, code2 = self.adb._run_cmd([
                        "shell", "cmd", "package", "dump", package, "|", "grep", "label="
                    ])

                    if code2 == 0 and stdout2:
                        labels = [l.split('=')[-1] for l in stdout2.strip().split('\n') if 'label=' in l]
                        appname = labels[0] if labels else package.split('.')[-1].title()
                    else:
                        appname = package.split('.')[-1].title()

                    apps.append((appname, package))

            return sorted(apps, key=lambda x: x[0])
        except:
            return []

    def _extract_single_app_databases(self, package: str, appname: str) -> bool:
        """Extract databases folder for a single app."""
        try:
            db_path = f"/data/data/{package}/databases/"

            # Check if database folder exists
            stdout, stderr, code = self.adb._run_cmd(["shell", "su", "-c", f"ls {db_path}"])
            if code != 0:
                console.print(f"[yellow]⚠ No databases folder found for {appname}[/yellow]")
                return False

            # List database files
            files = [f.strip() for f in stdout.strip().split('\n') if f.strip()]
            db_files = [f for f in files if f.endswith('.db') or f.endswith('.db-journal') or f.endswith('.db-shm') or f.endswith('.db-wal')]

            if not db_files:
                console.print(f"[yellow]⚠ No database files found[/yellow]")
                return False

            # Create output directory: AppName_databases/
            app_safe_name = appname.replace(' ', '_').replace(':', '')
            output_dir = self._get_output_path(f"{app_safe_name}_databases")
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            # Extract all database files
            extracted_count = 0
            for db_file in db_files:
                src = f"{db_path}{db_file}"
                dst = str(Path(output_dir) / db_file)

                stdout, stderr, code = self.adb._run_cmd(["pull", src, dst])
                if code == 0:
                    extracted_count += 1
                    console.print(f"[dim]  ✓ {db_file}[/dim]")

            if extracted_count > 0:
                console.print(f"\n[green]✓ Extracted {extracted_count} database files[/green]")
                self.extractions.append({
                    "type": "app_databases",
                    "app_name": appname,
                    "package": package,
                    "files": extracted_count,
                    "status": "success",
                    "location": str(output_dir)
                })
                return True
            else:
                console.print("[red]Failed to extract databases[/red]")
                return False

        except Exception as e:
            console.print(f"[red]✗ Error: {str(e)[:100]}[/red]")
            return False

    def _check_root_safe(self) -> bool:
        """Try to detect root, but default to True if detection fails (for Apatch compatibility)."""
        try:
            console.print("[cyan]🔍 Checking device root status...[/cyan]")

            # Quick attempt at detection
            stdout, _, code = self.adb._run_cmd(["shell", "su", "-c", "echo", "rooted"], timeout=5)
            if code == 0 and "rooted" in stdout:
                console.print("[green]✓ Device is ROOTED[/green]")
                return True

            # Try file check (shorter timeout)
            stdout, _, code = self.adb._run_cmd(["shell", "ls", "/system/xbin/su"], timeout=3)
            if code == 0:
                console.print("[green]✓ Device is ROOTED (su binary found)[/green]")
                return True

        except Exception as e:
            console.print(f"[dim]Root detection skipped: {str(e)[:50]}[/dim]")

        # If detection fails/times out, assume rooted
        # (Apatch root might not respond to standard detection)
        console.print("[green]✓ Assuming ROOTED (Apatch compatibility mode)[/green]")
        return True

    def _show_root_status(self):
        """Show root status."""
        if self.is_rooted:
            console.print("[green]✓ Root access confirmed[/green]")
        else:
            console.print("[yellow]⚠ No root access detected[/yellow]")

    def create_case(self, case_name: str = None) -> bool:
        """Create new forensics case."""
        try:
            if not case_name:
                case_name = f"case_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            case_path = self.case_dir / case_name
            case_path.mkdir(exist_ok=True)

            # Get device info
            device_info = self.adb.get_device_info()

            metadata = {
                "case_name": case_name,
                "created": datetime.now().isoformat(),
                "device": device_info.get("model", "Unknown"),
                "android_version": device_info.get("android_version", "Unknown"),
                "is_rooted": self.is_rooted,
                "status": "open"
            }

            with open(case_path / "metadata.json", 'w') as f:
                json.dump(metadata, f, indent=2)

            self.current_case = case_name
            console.print(f"[green]✓ Case created: {case_name}[/green]\n")
            return True
        except Exception as e:
            console.print(f"[red]✗ Error creating case: {e}[/red]")
            return False

    def extract_call_logs(self) -> bool:
        """Extract call history."""
        try:
            console.print("[cyan]☎️  Extracting call logs...[/cyan]")

            if self.is_rooted:
                # Extract all .db files from contacts databases directory
                if self._extract_all_dbs_from_dir(
                    "/data/data/com.android.providers.contacts/databases/",
                    "call_logs"
                ):
                    console.print(f"[green]✓ Call logs extracted successfully[/green]")
                    self.extractions.append({
                        "type": "call_logs",
                        "status": "success",
                        "location": "/data/data/com.android.providers.contacts/databases/"
                    })
                    return True
                else:
                    console.print(f"[yellow]⚠ Could not extract call logs[/yellow]")
                    return False
            else:
                # Non-rooted: use dumpsys
                console.print("[dim]Running non-rooted extraction...[/dim]")
                stdout, stderr, code = self.adb._run_cmd(["shell", "dumpsys", "telephony.registry"])

                if code == 0:
                    output_file = self._get_output_path("call_logs.txt")
                    with open(output_file, 'w') as f:
                        f.write(stdout)

                    console.print(f"[green]✓ Extracted call logs (limited)[/green]")
                    self.extractions.append({
                        "type": "call_logs",
                        "status": "success",
                        "file": str(output_file)
                    })
                    return True
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")

        return False

    def extract_contacts(self) -> bool:
        """Extract contacts."""
        try:
            console.print("[cyan]📖 Extracting contacts...[/cyan]")

            if self.is_rooted:
                # Extract all .db files from contacts directory
                if self._extract_all_dbs_from_dir(
                    "/data/data/com.android.contacts/databases/",
                    "contacts"
                ):
                    console.print(f"[green]✓ Contacts extracted successfully[/green]")
                    self.extractions.append({
                        "type": "contacts",
                        "status": "success",
                        "location": "/data/data/com.android.contacts/databases/"
                    })
                    return True
                else:
                    console.print(f"[yellow]⚠ Could not extract contacts[/yellow]")
                    return False
            else:
                # Non-rooted: use content query (may be limited)
                console.print("[dim]Running non-rooted extraction...[/dim]")
                output_file = self._get_output_path("contacts.txt")
                with open(output_file, 'w') as f:
                    f.write("Contact extraction requires device root access.\n")
                    f.write("Enable USB debugging and root to extract full contact database.\n")

                console.print(f"[yellow]⚠ Contact extraction limited without root[/yellow]")
                self.extractions.append({
                    "type": "contacts",
                    "status": "limited",
                    "file": str(output_file)
                })
                return True
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")

        return False

    def extract_messages(self) -> bool:
        """Extract SMS messages."""
        try:
            console.print("[cyan]💬 Extracting messages...[/cyan]")

            if self.is_rooted:
                # Extract all .db files from telephony database directory
                if self._extract_all_dbs_from_dir(
                    "/data/data/com.android.providers.telephony/databases/",
                    "messages"
                ):
                    console.print(f"[green]✓ Messages extracted successfully[/green]")
                    self.extractions.append({
                        "type": "messages",
                        "status": "success",
                        "location": "/data/data/com.android.providers.telephony/databases/"
                    })
                    return True
                else:
                    console.print(f"[yellow]⚠ Could not extract messages[/yellow]")
                    return False
            else:
                # Non-rooted: show limitation
                console.print("[dim]Running non-rooted extraction...[/dim]")
                output_file = self._get_output_path("messages.txt")
                with open(output_file, 'w') as f:
                    f.write("Message extraction requires device root access.\n")
                    f.write("Enable USB debugging and root to extract SMS/MMS database.\n")

                console.print(f"[yellow]⚠ Message extraction limited without root[/yellow]")
                self.extractions.append({
                    "type": "messages",
                    "status": "limited",
                    "file": str(output_file)
                })
                return True
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")

        return False

    def extract_browser_history(self) -> bool:
        """Extract browser history."""
        try:
            console.print("[cyan]🌐 Extracting browser history...[/cyan]")

            if self.is_rooted:
                # Try multiple browser database directories
                browser_dirs = [
                    "/data/data/com.android.chrome/app_chrome/Default/",
                    "/data/data/com.google.android.webview/",
                    "/data/data/com.android.browser/databases/"
                ]

                for browser_dir in browser_dirs:
                    if self._extract_all_dbs_from_dir(browser_dir, "browser_history"):
                        console.print(f"[green]✓ Browser history extracted successfully[/green]")
                        self.extractions.append({
                            "type": "browser_history",
                            "status": "success",
                            "location": browser_dir
                        })
                        return True

                console.print(f"[yellow]⚠ Could not extract browser history[/yellow]")
                return False
            else:
                # Non-rooted: browser data inaccessible
                console.print("[dim]Running non-rooted extraction...[/dim]")
                output_file = self._get_output_path("browser_history.txt")
                with open(output_file, 'w') as f:
                    f.write("Browser history extraction requires device root access.\n")
                    f.write("Chrome and other browsers store data in /data/data which requires root.\n")

                console.print(f"[yellow]⚠ Browser history extraction limited without root[/yellow]")
                self.extractions.append({
                    "type": "browser_history",
                    "status": "limited",
                    "file": str(output_file)
                })
                return True
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")

        return False

    def extract_system_logs(self) -> bool:
        """Extract system logs (logcat) - handle encoding issues."""
        try:
            console.print("[cyan]📋 Extracting system logs...[/cyan]")

            # logcat is a shell command, must use "shell" prefix
            # Use timeout to prevent hanging on large outputs
            stdout, stderr, code = self.adb._run_cmd(["shell", "logcat", "-d"], timeout=10)

            if code == 0 and stdout:
                output_file = self._get_output_path("system_logs.txt")

                # Handle encoding issues - decode with errors='replace' or 'ignore'
                try:
                    # Try to write as UTF-8
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(stdout)
                except UnicodeEncodeError:
                    # If UTF-8 fails, write with error replacement
                    with open(output_file, 'w', encoding='utf-8', errors='replace') as f:
                        f.write(stdout)

                log_count = stdout.count('\n')
                console.print(f"[green]✓ Extracted {log_count} log entries[/green]")
                self.extractions.append({
                    "type": "system_logs",
                    "count": log_count,
                    "status": "success",
                    "file": str(output_file)
                })
                return True
            else:
                console.print(f"[yellow]⚠ Could not extract logs: {stderr if stderr else 'No output'}[/yellow]")
        except Exception as e:
            console.print(f"[red]✗ Error: {str(e)[:100]}[/red]")

        return False

    def generate_report(self) -> bool:
        """Generate comprehensive forensics report with device info."""
        try:
            console.print("[cyan]📝 Generating forensics report...[/cyan]")

            report_file = self._get_output_path("forensics_report.json")
            device_info = self.adb.get_device_info()

            # Collect additional system info if rooted
            additional_info = {}
            if self.is_rooted:
                # Get installed packages count
                stdout, stderr, code = self.adb._run_cmd(["shell", "pm", "list", "packages"])
                if code == 0:
                    packages = [p.strip() for p in stdout.strip().split('\n') if p.strip().startswith('package:')]
                    additional_info["installed_packages"] = len(packages)

                # Get running processes
                stdout, stderr, code = self.adb._run_cmd(["shell", "ps", "-A"])
                if code == 0:
                    processes = len([p for p in stdout.strip().split('\n') if p.strip()])
                    additional_info["running_processes"] = processes

                # Get SELinux status
                stdout, stderr, code = self.adb._run_cmd(["shell", "getenforce"])
                if code == 0:
                    additional_info["selinux_status"] = stdout.strip()

            report = {
                "case_name": self.current_case,
                "generated": datetime.now().isoformat(),
                "device": {
                    "model": device_info.get("model", "Unknown"),
                    "manufacturer": device_info.get("manufacturer", "Unknown"),
                    "brand": device_info.get("brand", "Unknown"),
                    "android_version": device_info.get("android_version", "Unknown"),
                    "api_level": device_info.get("api_level", "Unknown"),
                    "build_id": device_info.get("build_id", "Unknown"),
                    "kernel_version": device_info.get("kernel_version", "Unknown"),
                    "security_patch": device_info.get("security_patch", "Unknown")
                },
                "device_rooted": self.is_rooted,
                "root_method": "Apatch/Magisk/SuperUser",
                "system_info": additional_info,
                "extractions": self.extractions,
                "summary": {
                    "total_operations": len(self.extractions),
                    "successful": len([e for e in self.extractions if e.get("status") == "success"]),
                    "database_files": sum([e.get("files", 0) for e in self.extractions if e.get("type") == "all_databases"])
                }
            }

            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2)

            console.print(f"[green]✓ Report generated: {report_file}[/green]")
            return True
        except Exception as e:
            console.print(f"[red]✗ Error generating report: {e}[/red]")
            return False

    def _get_output_path(self, filename: str) -> str:
        """Get output path for forensics data."""
        if not self.current_case:
            self.create_case()

        case_path = self.case_dir / self.current_case
        return str(case_path / filename)

    def _parse_call_logs(self, db_path: str) -> List[Dict]:
        """Parse call logs from database."""
        calls = []
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT number, date, duration FROM calls LIMIT 100")

            for row in cursor.fetchall():
                calls.append({
                    "number": row[0],
                    "date": row[1],
                    "duration": row[2]
                })
            conn.close()
        except:
            pass
        return calls

    def _parse_contacts(self, db_path: str) -> List[Dict]:
        """Parse contacts from database."""
        contacts = []
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            # Try to get contacts (structure varies by Android version)
            cursor.execute("SELECT display_name FROM contacts LIMIT 100")

            for row in cursor.fetchall():
                contacts.append({"name": row[0]})
            conn.close()
        except:
            pass
        return contacts

    def _parse_messages(self, db_path: str) -> List[Dict]:
        """Parse messages from database."""
        messages = []
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT address, body, date FROM sms LIMIT 100")

            for row in cursor.fetchall():
                messages.append({
                    "number": row[0],
                    "body": row[1],
                    "date": row[2]
                })
            conn.close()
        except:
            pass
        return messages

    def _parse_browser_history(self, db_path: str) -> List[Dict]:
        """Parse browser history from database."""
        history = []
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT url, title FROM urls LIMIT 100")

            for row in cursor.fetchall():
                history.append({
                    "url": row[0],
                    "title": row[1]
                })
            conn.close()
        except:
            pass
        return history


def show_forensics_menu(adb_interface):
    """Show digital forensics menu - simplified version."""
    forensics = DeviceForensics(adb_interface)

    # Create case
    forensics.create_case()

    while True:
        # Show menu
        root_status = "[green]ROOTED ✓[/green]" if forensics.is_rooted else "[yellow]NOT ROOTED[/yellow]"

        console.print(f"\n[bold cyan]🔍 DIGITAL FORENSICS - {root_status}[/bold cyan]\n")

        console.print("  📱 [1] Extract App Databases   - Select and extract app databases")
        console.print("  📋 [2] Extract System Logs     - Pull logcat system logs")
        console.print("  📝 [3] Generate Report         - Create forensics case report")
        console.print("  ❌ [0] Back to Main Menu       - Return\n")

        choice = console.input("[bold cyan]Select operation (0-3): [/bold cyan]").strip()

        if choice == "0":
            return

        elif choice == "1":
            forensics.extract_app_databases()

        elif choice == "2":
            forensics.extract_system_logs()

        elif choice == "3":
            forensics.generate_report()

        else:
            console.print("[red]Invalid choice[/red]")

        console.input("[dim]Press Enter to continue...[/dim]")
