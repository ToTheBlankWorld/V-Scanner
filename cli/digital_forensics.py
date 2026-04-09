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
        self.is_rooted = self._check_root()
        self.extractions = []

    def _check_root(self) -> bool:
        """Check if device is rooted."""
        try:
            console.print("[cyan]🔍 Checking device root status...[/cyan]")
            stdout, stderr, code = self.adb._run_cmd(["shell", "su", "-c", "id"])

            is_root = code == 0 and "uid=0" in stdout

            if is_root:
                console.print("[green]✓ Device is ROOTED[/green]")
            else:
                console.print("[yellow]⚠ Device is NOT rooted (limited access)[/yellow]")

            return is_root
        except:
            return False

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
                # Rooted: pull call_log.db
                call_db = "/data/data/com.android.providers.contacts/databases/call_log.db"
                output_file = self._get_output_path("call_logs.db")

                stdout, stderr, code = self.adb._run_cmd(["pull", call_db, str(output_file)])

                if code == 0 and Path(output_file).exists():
                    calls = self._parse_call_logs(str(output_file))
                    console.print(f"[green]✓ Extracted {len(calls)} call records[/green]")
                    self.extractions.append({
                        "type": "call_logs",
                        "count": len(calls),
                        "status": "success",
                        "file": str(output_file)
                    })
                    return True
                else:
                    console.print(f"[yellow]⚠ Could not access call logs database[/yellow]")
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
                # Rooted: pull contacts database
                contacts_db = "/data/data/com.android.contacts/databases/contacts2.db"
                output_file = self._get_output_path("contacts.db")

                stdout, stderr, code = self.adb._run_cmd(["pull", contacts_db, str(output_file)])

                if code == 0 and Path(output_file).exists():
                    contacts = self._parse_contacts(str(output_file))
                    console.print(f"[green]✓ Extracted {len(contacts)} contacts[/green]")
                    self.extractions.append({
                        "type": "contacts",
                        "count": len(contacts),
                        "status": "success",
                        "file": str(output_file)
                    })
                    return True
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
                # Rooted: pull messages database
                messages_db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
                output_file = self._get_output_path("messages.db")

                stdout, stderr, code = self.adb._run_cmd(["pull", messages_db, str(output_file)])

                if code == 0 and Path(output_file).exists():
                    messages = self._parse_messages(str(output_file))
                    console.print(f"[green]✓ Extracted {len(messages)} messages[/green]")
                    self.extractions.append({
                        "type": "messages",
                        "count": len(messages),
                        "status": "success",
                        "file": str(output_file)
                    })
                    return True
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
                # Rooted: pull Chrome history
                chrome_db = "/data/data/com.android.chrome/app_chrome/Default/History"
                output_file = self._get_output_path("chrome_history.db")

                stdout, stderr, code = self.adb._run_cmd(["pull", chrome_db, str(output_file)])

                if code == 0 and Path(output_file).exists():
                    history = self._parse_browser_history(str(output_file))
                    console.print(f"[green]✓ Extracted {len(history)} history entries[/green]")
                    self.extractions.append({
                        "type": "browser_history",
                        "count": len(history),
                        "status": "success",
                        "file": str(output_file)
                    })
                    return True
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
        """Extract system logs (works without root)."""
        try:
            console.print("[cyan]📋 Extracting system logs...[/cyan]")

            # Logcat works without root
            stdout, stderr, code = self.adb._run_cmd(["logcat", "-d", "*:V"])

            if code == 0 and stdout:
                output_file = self._get_output_path("system_logs.txt")
                with open(output_file, 'w') as f:
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
                console.print(f"[yellow]⚠ Could not extract logs: {stderr}[/yellow]")
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")

        return False

    def generate_report(self) -> bool:
        """Generate forensics report."""
        try:
            console.print("[cyan]📝 Generating forensics report...[/cyan]")

            report_file = self._get_output_path("forensics_report.json")
            device_info = self.adb.get_device_info()

            report = {
                "case_name": self.current_case,
                "generated": datetime.now().isoformat(),
                "device": {
                    "model": device_info.get("model", "Unknown"),
                    "android_version": device_info.get("android_version", "Unknown"),
                    "build_id": device_info.get("build_id", "Unknown")
                },
                "device_rooted": self.is_rooted,
                "extractions": self.extractions,
                "summary": {
                    "total_operations": len(self.extractions),
                    "successful": len([e for e in self.extractions if e.get("status") == "success"]),
                    "limited": len([e for e in self.extractions if e.get("status") == "limited"])
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
    """Show digital forensics menu."""
    forensics = DeviceForensics(adb_interface)

    # Create case
    forensics.create_case()

    while True:
        # Show menu based on root status
        root_status = "[green]ROOTED ✓[/green]" if forensics.is_rooted else "[yellow]NOT ROOTED[/yellow]"

        console.print(f"\n[bold cyan]🔍 DIGITAL FORENSICS - {root_status}[/bold cyan]\n")

        if forensics.is_rooted:
            console.print("  ☎️  [1] Extract Call Logs      - Pull call history")
            console.print("  📖 [2] Extract Contacts       - Pull contacts database")
            console.print("  💬 [3] Extract Messages       - Pull SMS/MMS database")
            console.print("  🌐 [4] Extract Browser Hist   - Pull browser history")
            console.print("  📋 [5] Extract System Logs    - Pull system logs")
            console.print("  📝 [6] Generate Report        - Create forensics report")
            console.print("  ❌ [0] Back to Main Menu      - Return\n")
        else:
            console.print("  ☎️  [1] Extract Call Logs      - Limited (non-rooted)")
            console.print("  📖 [2] Extract Contacts       - Limited (requires root)")
            console.print("  💬 [3] Extract Messages       - Limited (requires root)")
            console.print("  🌐 [4] Extract Browser Hist   - Limited (requires root)")
            console.print("  📋 [5] Extract System Logs    - Works (logcat)")
            console.print("  📝 [6] Generate Report        - Create forensics report")
            console.print("  ❌ [0] Back to Main Menu      - Return\n")

        choice = console.input("[bold cyan]Select operation (0-6): [/bold cyan]").strip()

        if choice == "0":
            return

        elif choice == "1":
            forensics.extract_call_logs()

        elif choice == "2":
            forensics.extract_contacts()

        elif choice == "3":
            forensics.extract_messages()

        elif choice == "4":
            forensics.extract_browser_history()

        elif choice == "5":
            forensics.extract_system_logs()

        elif choice == "6":
            forensics.generate_report()

        else:
            console.print("[red]Invalid choice[/red]")

        console.input("[dim]Press Enter to continue...[/dim]")
