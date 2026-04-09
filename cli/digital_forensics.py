#!/usr/bin/env python3
"""
Digital Forensics Operations Module for V Scanner
Extracts, analyzes, and documents forensic evidence from Android devices
Similar to OpenMF forensic framework capabilities
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

console = Console()


class DigitalForensicsManager:
    """Manages digital forensics operations on Android devices."""

    def __init__(self, adb_interface):
        """Initialize forensics manager with ADB interface."""
        self.adb = adb_interface
        # Create forensics_cases in the same directory as this script
        script_dir = Path(__file__).parent
        self.case_dir = script_dir / "forensics_cases"
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self.current_case = None

    def create_case(self, case_name: str, description: str = "") -> bool:
        """Create a new forensics case."""
        try:
            case_path = self.case_dir / case_name
            case_path.mkdir(exist_ok=True)

            # Create case metadata
            metadata = {
                "case_name": case_name,
                "description": description,
                "created": datetime.now().isoformat(),
                "device_serial": self.adb.get_device_info().get("serial", "Unknown"),
                "status": "open"
            }

            metadata_file = case_path / "metadata.json"
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            self.current_case = case_name
            console.print(f"[green]✓ Case '{case_name}' created successfully[/green]")
            return True
        except Exception as e:
            console.print(f"[red]✗ Failed to create case: {e}[/red]")
            return False

    def extract_contacts(self) -> Dict[str, Any]:
        """Extract contacts database from device."""
        try:
            console.print("[cyan]📖 Extracting contacts...[/cyan]")

            contacts_db = "/data/data/com.android.contacts/databases/contacts2.db"
            output_file = self._get_output_path("contacts.db")

            # Pull contacts database
            stdout, stderr, code = self.adb._run_cmd(["pull", contacts_db, str(output_file)])

            if code == 0:
                contacts = self._parse_contacts_db(str(output_file))
                console.print(f"[green]✓ Extracted {len(contacts)} contacts[/green]")
                return {
                    "type": "contacts",
                    "count": len(contacts),
                    "data": contacts,
                    "status": "success"
                }
        except Exception as e:
            console.print(f"[yellow]⚠ Could not extract contacts: {e}[/yellow]")

        return {"type": "contacts", "count": 0, "data": [], "status": "failed"}

    def extract_messages(self) -> Dict[str, Any]:
        """Extract SMS/MMS messages from device."""
        try:
            console.print("[cyan]💬 Extracting messages...[/cyan]")

            messages_db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
            output_file = self._get_output_path("messages.db")

            stdout, stderr, code = self.adb._run_cmd(["pull", messages_db, str(output_file)])

            if code == 0:
                messages = self._parse_messages_db(str(output_file))
                console.print(f"[green]✓ Extracted {len(messages)} messages[/green]")
                return {
                    "type": "messages",
                    "count": len(messages),
                    "data": messages,
                    "status": "success"
                }
        except Exception as e:
            console.print(f"[yellow]⚠ Could not extract messages: {e}[/yellow]")

        return {"type": "messages", "count": 0, "data": [], "status": "failed"}

    def extract_call_logs(self) -> Dict[str, Any]:
        """Extract call history from device."""
        try:
            console.print("[cyan]☎️  Extracting call logs...[/cyan]")

            calls_db = "/data/data/com.android.providers.contacts/databases/call_log.db"
            output_file = self._get_output_path("call_logs.db")

            stdout, stderr, code = self.adb._run_cmd(["pull", calls_db, str(output_file)])

            if code == 0:
                calls = self._parse_call_logs_db(str(output_file))
                console.print(f"[green]✓ Extracted {len(calls)} call records[/green]")
                return {
                    "type": "call_logs",
                    "count": len(calls),
                    "data": calls,
                    "status": "success"
                }
        except Exception as e:
            console.print(f"[yellow]⚠ Could not extract call logs: {e}[/yellow]")

        return {"type": "call_logs", "count": 0, "data": [], "status": "failed"}

    def extract_installed_apps(self) -> Dict[str, Any]:
        """Extract list of installed applications."""
        try:
            console.print("[cyan]📦 Extracting installed apps...[/cyan]")

            stdout, stderr, code = self.adb._run_cmd(["shell", "pm", "list", "packages", "-a"])

            if code == 0 and stdout:
                apps = [line.replace("package:", "").strip() for line in stdout.split('\n') if line.strip()]
                console.print(f"[green]✓ Found {len(apps)} installed applications[/green]")
                return {
                    "type": "installed_apps",
                    "count": len(apps),
                    "data": apps,
                    "status": "success"
                }
        except Exception as e:
            console.print(f"[yellow]⚠ Could not extract apps: {e}[/yellow]")

        return {"type": "installed_apps", "count": 0, "data": [], "status": "failed"}

    def extract_browser_history(self) -> Dict[str, Any]:
        """Extract browser history from Chrome and default browser."""
        try:
            console.print("[cyan]🌐 Extracting browser history...[/cyan]")

            history_data = []

            # Chrome browser
            chrome_db = "/data/data/com.android.chrome/app_chrome/Default/History"
            output_file = self._get_output_path("chrome_history.db")

            stdout, stderr, code = self.adb._run_cmd(["pull", chrome_db, str(output_file)])

            if code == 0:
                history = self._parse_browser_history(str(output_file))
                history_data.extend(history)

            console.print(f"[green]✓ Extracted {len(history_data)} browser history entries[/green]")
            return {
                "type": "browser_history",
                "count": len(history_data),
                "data": history_data,
                "status": "success"
            }
        except Exception as e:
            console.print(f"[yellow]⚠ Could not extract browser history: {e}[/yellow]")

        return {"type": "browser_history", "count": 0, "data": [], "status": "failed"}

    def extract_app_data(self, package_name: str) -> Dict[str, Any]:
        """Extract specific application data."""
        try:
            console.print(f"[cyan]📁 Extracting data for {package_name}...[/cyan]")

            app_dir = f"/data/data/{package_name}"
            output_dir = self._get_output_path(f"{package_name}_data")

            stdout, stderr, code = self.adb._run_cmd(["pull", app_dir, str(output_dir)])

            if code == 0:
                console.print(f"[green]✓ Extracted application data[/green]")
                return {
                    "type": "app_data",
                    "package": package_name,
                    "output": str(output_dir),
                    "status": "success"
                }
        except Exception as e:
            console.print(f"[yellow]⚠ Could not extract app data: {e}[/yellow]")

        return {"type": "app_data", "package": package_name, "status": "failed"}

    def extract_file_system(self, path: str = "/sdcard") -> Dict[str, Any]:
        """Extract file system data from specified path."""
        try:
            console.print(f"[cyan]💾 Extracting file system from {path}...[/cyan]")

            output_dir = self._get_output_path("file_system")
            Path(output_dir).mkdir(exist_ok=True)

            stdout, stderr, code = self.adb._run_cmd(["pull", path, str(output_dir)])

            if code == 0:
                console.print(f"[green]✓ File system extracted[/green]")
                return {
                    "type": "file_system",
                    "path": path,
                    "output": str(output_dir),
                    "status": "success"
                }
        except Exception as e:
            console.print(f"[yellow]⚠ Could not extract file system: {e}[/yellow]")

        return {"type": "file_system", "path": path, "status": "failed"}

    def extract_system_logs(self) -> Dict[str, Any]:
        """Extract system logs (logcat)."""
        try:
            console.print("[cyan]📋 Extracting system logs...[/cyan]")

            stdout, stderr, code = self.adb._run_cmd(["logcat", "-d", "*:V"])

            if code == 0 and stdout:
                output_file = self._get_output_path("system_logs.txt")
                with open(output_file, 'w') as f:
                    f.write(stdout)

                log_lines = stdout.count('\n')
                console.print(f"[green]✓ Extracted {log_lines} log entries[/green]")
                return {
                    "type": "system_logs",
                    "count": log_lines,
                    "file": str(output_file),
                    "status": "success"
                }
        except Exception as e:
            console.print(f"[yellow]⚠ Could not extract logs: {e}[/yellow]")

        return {"type": "system_logs", "count": 0, "status": "failed"}

    def extract_media_files(self, media_type: str = "images") -> Dict[str, Any]:
        """Extract media files (photos, videos, audio)."""
        try:
            console.print(f"[cyan]🎬 Extracting {media_type}...[/cyan]")

            media_paths = {
                "images": "/sdcard/DCIM",
                "videos": "/sdcard/Movies",
                "audio": "/sdcard/Music",
                "downloads": "/sdcard/Download"
            }

            path = media_paths.get(media_type, "/sdcard/DCIM")
            output_dir = self._get_output_path(f"{media_type}")

            stdout, stderr, code = self.adb._run_cmd(["pull", path, str(output_dir)])

            if code == 0:
                console.print(f"[green]✓ {media_type.title()} extracted successfully[/green]")
                return {
                    "type": "media",
                    "media_type": media_type,
                    "output": str(output_dir),
                    "status": "success"
                }
        except Exception as e:
            console.print(f"[yellow]⚠ Could not extract media: {e}[/yellow]")

        return {"type": "media", "media_type": media_type, "status": "failed"}

    def generate_forensics_report(self, extractions: List[Dict]) -> str:
        """Generate comprehensive forensics report from extractions."""
        try:
            console.print("[cyan]📝 Generating forensics report...[/cyan]")

            report_file = self._get_output_path("forensics_report.json")

            device_info = self.adb.get_device_info()

            report = {
                "case_name": self.current_case,
                "generated": datetime.now().isoformat(),
                "device": {
                    "serial": device_info.get("serial", "Unknown"),
                    "model": device_info.get("model", "Unknown"),
                    "android_version": device_info.get("android_version", "Unknown"),
                    "build": device_info.get("build_version", "Unknown")
                },
                "extractions": extractions,
                "summary": {
                    "total_items": sum(e.get("count", 0) for e in extractions),
                    "successful": len([e for e in extractions if e.get("status") == "success"]),
                    "failed": len([e for e in extractions if e.get("status") == "failed"])
                }
            }

            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2)

            console.print(f"[green]✓ Report generated: {report_file}[/green]")
            return str(report_file)
        except Exception as e:
            console.print(f"[red]✗ Failed to generate report: {e}[/red]")
            return ""

    def _get_output_path(self, filename: str) -> str:
        """Get output path for forensics data."""
        if not self.current_case:
            self.current_case = f"case_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.create_case(self.current_case)

        case_path = self.case_dir / self.current_case
        output_path = case_path / filename
        return str(output_path)

    def _parse_contacts_db(self, db_path: str) -> List[Dict]:
        """Parse contacts database."""
        contacts = []
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT display_name, data1 FROM view_contacts_raw WHERE mimetype_id = 1 OR mimetype_id = 2")

            for row in cursor.fetchall():
                contacts.append({
                    "name": row[0],
                    "contact": row[1]
                })
        except:
            pass
        return contacts

    def _parse_messages_db(self, db_path: str) -> List[Dict]:
        """Parse SMS/MMS messages database."""
        messages = []
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT address, body, date, type FROM sms ORDER BY date DESC LIMIT 100")

            for row in cursor.fetchall():
                messages.append({
                    "address": row[0],
                    "body": row[1],
                    "date": row[2],
                    "type": "incoming" if row[3] == 1 else "outgoing"
                })
        except:
            pass
        return messages

    def _parse_call_logs_db(self, db_path: str) -> List[Dict]:
        """Parse call logs database."""
        calls = []
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT number, date, duration, type FROM calls ORDER BY date DESC LIMIT 100")

            for row in cursor.fetchall():
                calls.append({
                    "number": row[0],
                    "date": row[1],
                    "duration": row[2],
                    "type": row[3]
                })
        except:
            pass
        return calls

    def _parse_browser_history(self, db_path: str) -> List[Dict]:
        """Parse browser history database."""
        history = []
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT url, title, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT 100")

            for row in cursor.fetchall():
                history.append({
                    "url": row[0],
                    "title": row[1],
                    "timestamp": row[2]
                })
        except:
            pass
        return history


def show_forensics_menu(adb_interface):
    """Display digital forensics operations menu."""
    forensics = DigitalForensicsManager(adb_interface)

    while True:
        console.print("\n[bold cyan]╔════════════════════════════════════════╗[/bold cyan]")
        console.print("[bold cyan]║     🔍 DIGITAL FORENSICS OPERATIONS    ║[/bold cyan]")
        console.print("[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n")

        menu_items = [
            ("1", "📁", "Create Forensics Case", "Start new investigation case"),
            ("2", "📖", "Extract Contacts", "Pull contacts database"),
            ("3", "💬", "Extract Messages", "Pull SMS/MMS database"),
            ("4", "☎️", "Extract Call Logs", "Pull call history"),
            ("5", "📦", "Extract Apps List", "Get installed applications"),
            ("6", "🌐", "Extract Browser History", "Pull browser data"),
            ("7", "📁", "Extract App Data", "Extract specific app data"),
            ("8", "💾", "Extract File System", "Pull file system data"),
            ("9", "📋", "Extract System Logs", "Pull logcat logs"),
            ("10", "🎬", "Extract Media", "Pull images/videos/audio"),
            ("11", "📝", "Generate Report", "Create forensics report"),
            ("12", "🔄", "Full Extraction", "Run complete forensics"),
            ("0", "❌", "Back to Main Menu", "Return to main menu"),
        ]

        for num, icon, title, desc in menu_items:
            console.print(f"  {icon} [{num:>2}] {title:<25} - {desc}")

        choice = console.input("\n[bold cyan]Select operation (0-12): [/bold cyan]").strip()

        if choice == "0":
            return

        elif choice == "1":
            case_name = console.input("[cyan]Enter case name: [/cyan]").strip()
            description = console.input("[cyan]Enter case description (optional): [/cyan]").strip()
            forensics.create_case(case_name, description)

        elif choice == "2":
            forensics.extract_contacts()

        elif choice == "3":
            forensics.extract_messages()

        elif choice == "4":
            forensics.extract_call_logs()

        elif choice == "5":
            forensics.extract_installed_apps()

        elif choice == "6":
            forensics.extract_browser_history()

        elif choice == "7":
            package = console.input("[cyan]Enter package name: [/cyan]").strip()
            forensics.extract_app_data(package)

        elif choice == "8":
            path = console.input("[cyan]Enter path (default /sdcard): [/cyan]").strip() or "/sdcard"
            forensics.extract_file_system(path)

        elif choice == "9":
            forensics.extract_system_logs()

        elif choice == "10":
            media_type = console.input("[cyan]Media type (images/videos/audio/downloads): [/cyan]").strip() or "images"
            forensics.extract_media_files(media_type)

        elif choice == "11":
            extractions = [
                forensics.extract_contacts(),
                forensics.extract_messages(),
                forensics.extract_call_logs(),
                forensics.extract_installed_apps()
            ]
            forensics.generate_forensics_report(extractions)

        elif choice == "12":
            console.print("[bold yellow]🔄 Running complete forensic extraction...[/bold yellow]")
            extractions = [
                forensics.extract_contacts(),
                forensics.extract_messages(),
                forensics.extract_call_logs(),
                forensics.extract_installed_apps(),
                forensics.extract_browser_history(),
                forensics.extract_system_logs(),
                forensics.extract_media_files("images")
            ]
            forensics.generate_forensics_report(extractions)
            console.print("[green]✓ Complete forensic extraction finished[/green]")

        else:
            console.print("[red]Invalid choice[/red]")

        console.input("[dim]Press Enter to continue...[/dim]")
