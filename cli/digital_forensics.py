#!/usr/bin/env python3
"""
Digital Forensics Module - V Scanner
Simple, effective forensics operations for Android devices.

Stage 08 port: this module is now a thin legacy-UX adapter over the shared
engine ForensicsService (``vscanner/services/forensics.py``). Behavioral
changes are the *documented Stage 08 remediations*:

* R-05: root status comes from the verified tri-state probe. The legacy
  "assume ROOTED when detection fails" fallback is gone — failed
  detection now shows "root status unknown" and no longer claims root.
* R-07: app databases/prefs/files go through the byte-safe ``exec-out``
  /``adb pull`` path with per-file sha256 records; the text-mode
  decode→rewrite path that corrupted NUL bytes and non-UTF-8 payloads is
  gone.
* R-12: the WiFi extraction writes a redacted file by default
  (psk/password values withheld). No cleartext-PSK flow is exposed
  through the legacy menu (the explicit double-confirm flow belongs to
  the TUI cockpit).
* R-03: the four silent-failure phantom extractors (call logs, contacts,
  messages, browser history) and their dead sqlite parsers no longer
  exist; their menu entries were never surfaced (the menu carries the
  eight honest operations).

The console output/wording intentionally keeps the legacy labels and the
eight-item menu structure.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel

from vscanner.core.paths import cases_dir
from vscanner.services.forensics import ForensicsService

console = Console()


class DeviceForensics:
    """Legacy forensics menu face over the engine ForensicsService."""

    def __init__(self, adb_interface, case_root: Optional[Path] = None):
        """Initialize forensics with the ADB interface and a case root.

        ``case_root`` defaults to the Stage 08 approved location
        (``<app-data>/forensics_cases``); the legacy repo-local
        ``cli/forensics_cases`` default is retired (path-migration
        approval documented in SERVICE_CONTRACTS)."""
        self.adb = adb_interface
        self.case_dir = Path(case_root) if case_root is not None else cases_dir()
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self._svc = ForensicsService(self.adb, base_dir=self.case_dir)
        self.current_case = None
        self.manifest = None
        self.root_status = self._check_root_safe()
        self._show_root_status()
        self.extractions: List[Dict[str, Any]] = []

    # -- root status (R-05 verified tri-state) ------------------------------ #

    def _check_root_safe(self) -> str:
        """Verified tri-state probe (legacy call-site shape preserved).

        Returns the honest word "rooted" | "not-rooted" | "unknown";
        ``is_rooted`` (below) stays False unless the root is CONFIRMED —
        detection failure is never mapped to a claimed state (R-05)."""
        try:
            status, evidence = self._svc._root_status_word_with_evidence()
            self.root_evidence = evidence
        except Exception as exc:  # transport level failure → unknown
            self.root_evidence = (f"probe error: {type(exc).__name__}",)
            status = "unknown"
        return status

    @property
    def is_rooted(self) -> bool:
        """Legacy boolean consumer; True ONLY for confirmed root (R-05)."""
        return getattr(self, "root_status", "") == "rooted"

    def _show_root_status(self):
        """Tri-state honest wording (legacy two-state words upgraded)."""
        if self.root_status == "rooted":
            console.print("[green]\u2713 Root access confirmed (verified probe)[/green]")
        elif self.root_status == "not-rooted":
            console.print("[yellow]\u25cf No root access available to ADB (verified probe)[/yellow]")
        else:
            console.print("[yellow]\u25cf Root status unknown (detection failed or refused; "
                          "no claim made either way)[/yellow]")
        return self.root_status

    # -- case lifecycle ------------------------------------------------------ #

    def create_case(self, case_name: str = None) -> bool:
        """Create new forensics case (engine-backed, manifest.json)."""
        try:
            if not case_name:
                case_name = f"case_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            info = {}
            try:
                info = self.adb.get_device_info() or {}
            except Exception:
                info = {}
            self.manifest = self._svc.create_case(
                device_serial=getattr(self.adb, "device", None),
                case_name=case_name,
                device_model=info.get("model") or None,
                android_version=info.get("android_version") or None,
            )
            self.current_case = self.manifest.case_id
            console.print(f"[green]\u2713 Case created: {self.manifest.case_id}[/green]\n")
            return True
        except Exception as e:
            console.print(f"[red]\u2717 Error creating case: {e}[/red]")
            return False

    def _require_case(self) -> bool:
        if self.manifest is None:
            if not self.create_case():
                console.print("[red]\u2717 No active case — operation not started[/red]")
                return False
        return True

    def _get_output_path(self, filename: str) -> str:
        """Output path of the current case (legacy shape)."""
        if not self.current_case or self.manifest is None:
            self.create_case()
        return str(self.case_dir / self.current_case / filename)

    # -- app extraction (1/2/3) --------------------------------------------- #

    def extract_app_databases(self) -> bool:
        """Extract databases from user-selected app."""
        package, appname = self._select_app("App Databases")
        if not package:
            return False
        return self._extract_and_record(package, appname, "databases",
                                        "app_databases", "Device_database")

    def extract_app_shared_prefs(self) -> bool:
        """Extract shared prefs from user-selected app."""
        package, appname = self._select_app("App Shared Prefs")
        if not package:
            return False
        return self._extract_and_record(package, appname, "shared_prefs",
                                        "app_shared_prefs", "Device_shared_prefs")

    def extract_app_files(self) -> bool:
        """Extract files folder from user-selected app."""
        package, appname = self._select_app("App Files")
        if not package:
            return False
        return self._extract_and_record(package, appname, "files",
                                        "app_files", "Device_files")

    def _extract_and_record(self, package: str, appname: str, source: str,
                            legacy_type: str, legacy_root_key: str) -> bool:
        """Engine-backed byte-safe extraction of one app's folder (R-07).

        Honest console summary: counts copied files, records failure
        notes verbatim — failed or 0-file extractions are never reported
        as success."""
        if not self._require_case():
            return False
        console.print(f"[cyan]\u2192 Extracting {source} for {appname} "
                      f"({package})[/cyan]\n")
        before = len(self.manifest.files)
        try:
            self.manifest = self._svc.extract_app_data_files(
                package, (source,), self.manifest)
        except Exception as exc:
            console.print(f"[red]\u2717 Error: {str(exc)[:100]}[/red]")
            return False
        records = [f for f in self.manifest.files[before:] if f.kind == "binary"]
        notes = [e for key, e in self.manifest.extractions
                 if key.startswith(f"extract:{source}:{package}")]
        for note in notes:
            console.print(f"[dim]  {note}[/dim]")
        copied = len(set(f.case_relative_path for f in records))
        self._note_extraction(legacy_type, package, appname, copied)
        if copied > 0:
            console.print(f"\n[green]\u2713 Extracted {copied} files "
                          f"(sha256 recorded in manifest)[/green]")
            return True
        console.print(f"[red]\u2717 Failed to extract any files[/red]")
        return False

    # -- one-shot extracts (4/5/6) -------------------------------------------- #

    def extract_system_logs(self) -> bool:
        """Extract system logs (logcat) — engine documented text transform."""
        if not self._require_case():
            return False
        before = len(self.manifest.extractions)
        self.manifest = self._svc.extract_system_logs(self.manifest)
        return self._finish_text_op("system_logs", "system logs", before,
                                    "system_logs.txt")

    def extract_installed_packages(self) -> bool:
        if not self._require_case():
            return False
        before = len(self.manifest.extractions)
        self.manifest = self._svc.extract_installed_packages(self.manifest)
        return self._finish_text_op("installed_packages", "package list",
                                    before, "installed_packages.txt")

    def extract_running_processes(self) -> bool:
        if not self._require_case():
            return False
        before = len(self.manifest.extractions)
        self.manifest = self._svc.extract_running_processes(self.manifest)
        return self._finish_text_op("running_processes", "process list",
                                    before, "running_processes.txt")

    def _finish_text_op(self, op: str, label: str,
                        before: int, filename: str) -> bool:
        notes = [state for key, state in self.manifest.extractions[before:]
                 if key == op]
        state = notes[-1] if notes else "no result recorded"
        if state.startswith("success"):
            console.print(f"[green]\u2713 Extracted {label}[/green]")
            self._note_extraction(op, "", label, 0)
            return True
        console.print(f"[yellow]\u2717 Could not extract {label}: {state}[/yellow]")
        return False

    # -- WiFi (7, R-12 redaction default) ------------------------------------- #

    def extract_wifi_networks(self) -> bool:
        """Extract WiFi networks — REDACTED by default (R-12).

        Documented Stage 08 behavior change (the fix itself): the legacy
        cleartext-by-default write is gone; psk/password values are
        withheld in the stored file. The explicit cleartext-with-
        double-confirm flow belongs to the TUI forensics cockpit."""
        if not self._require_case():
            return False
        before = len(self.manifest.extractions)
        self.manifest = self._svc.extract_wifi_networks(self.manifest)
        notes = [state for key, state in self.manifest.extractions[before:]
                 if key == "wifi_networks"]
        state = notes[-1] if notes else "no result recorded"
        if "networks count" in state and "unavailable" not in state:
            console.print(f"[green]\u2713 WiFi networks extracted "
                          f"(REDACTED default — psk/password withheld, R-12)[/green]")
            console.print("[dim]  Cleartext PSK storage is only available "
                          "in the TUI cockpit behind a double confirmation.[/dim]")
            self._note_extraction("wifi_networks", "", "WiFi networks", 0)
            return True
        console.print(f"[yellow]\u2717 Could not extract WiFi networks: {state}[/yellow]")
        return False

    # -- report (8) ------------------------------------------------------------ #

    def generate_report(self) -> bool:
        """Forensics case report (legacy metadata fields + honest
        tri-state root + per-file hashes)."""
        if not self._require_case():
            return False
        try:
            report_path = self._svc.generate_report(self.manifest)
        except Exception as e:
            console.print(f"[red]\u2717 Error generating report: {e}[/red]")
            return False
        console.print(f"[green]\u2713 Report generated: {report_path}[/green]")
        console.print(Panel(
            f"Case: {self.current_case}\n"
            f"Root status: {self.manifest.root_status}\n"
            f"Files: {len(self.manifest.files)} (sha256 recorded)\n"
            f"Redaction preset: {self.manifest.redaction_preset}",
            title="case report",
        ))
        return True

    # -- internals --------------------------------------------------------------- #

    def _note_extraction(self, legacy_type: str, package: str, label: str,
                         count: int) -> None:
        self.extractions.append({
            "type": legacy_type,
            "package": package,
            "label": label,
            "files": count,
            "status": "recorded",
            "location": self._get_output_path(""),
        })

    def _select_app(self, label: str) -> Tuple[Optional[str], Optional[str]]:
        """Legacy interactive app selection (system/third-party + list)."""
        try:
            console.print(f"[bold cyan]\u2192 Extract {label}[/bold cyan]\n")
            console.print("  [1] System Apps")
            console.print("  [2] Third-Party Apps\n")
            choice = console.input("Select app category (1-2): ").strip()
            if choice != "1" and choice != "2":
                console.print("[red]Invalid choice[/red]")
                return None, None
            lines = self._pm_list(choice == "1")
            apps = []
            for line in lines:
                pkg = line.removeprefix("package:").strip()
                if pkg:
                    apps.append((pkg, pkg))
            if not apps:
                console.print("[yellow]\u25cf No apps found[/yellow]")
                return None, None
            for i, (pkg, name) in enumerate(apps[:25], start=1):
                console.print(f"  [{i}] {name}  ({pkg})")
            if len(apps) > 25:
                console.print(f"  ... and {len(apps) - 25} more")
            pick = console.input("Select app number: ").strip()
            if not pick.isdigit() or not (1 <= int(pick) <= min(25, len(apps))):
                console.print("[red]Invalid selection[/red]")
                return None, None
            pkg, name = apps[int(pick) - 1]
            return pkg, name
        except Exception as exc:
            console.print(f"[red]\u2717 Error: {str(exc)[:100]}[/red]")
            return None, None

    def _pm_list(self, system: bool) -> List[str]:
        try:
            stdout, _, code = self.adb._run_cmd(
                ["shell", "pm", "list", "packages", "-s" if system else "-3"])
        except Exception:
            stdout, code = "", 1
        if code != 0 or not stdout:
            return []
        return [line for line in stdout.splitlines() if line.strip()]


def show_forensics_menu(adb_interface):
    """Show digital forensics menu (legacy 8-op structure preserved)."""
    forensics = DeviceForensics(adb_interface)

    # Create case (legacy auto-create on menu entry)
    forensics.create_case()

    while True:
        if forensics.root_status == "rooted":
            root_status = "[green]ROOTED \u2713[/green]"
        elif forensics.root_status == "not-rooted":
            root_status = "[yellow]NOT ROOTED (verified)[/yellow]"
        else:
            root_status = "[yellow]ROOT STATUS UNKNOWN[/yellow]"

        console.print(f"\n[bold cyan]\u2192 DIGITAL FORENSICS - {root_status}[/bold cyan]\n")

        console.print("  \u2713 [1] Extract App Databases         - Select and extract app databases")
        console.print("  \u2713 [2] Extract App Shared Prefs     - Extract app configuration/settings")
        console.print("  \u2713 [3] Extract App Files             - Extract app data files folder")
        console.print("  \u2713 [4] Extract System Logs           - Pull logcat system logs")
        console.print("  \u2713 [5] Extract Installed Packages    - List all installed apps")
        console.print("  \u2713 [6] Extract Running Processes     - List running processes")
        console.print("  \u2713 [7] Extract WiFi Networks         - Pull WiFi histories (REDACTED default)")
        console.print("  \u2713 [8] Generate Report               - Create forensics case report")
        console.print("  \u2717 [0] Back to Main Menu             - Return\n")

        choice = console.input("[bold cyan]Select operation (0-8): [/bold cyan]").strip()

        if choice == "0":
            return

        elif choice == "1":
            forensics.extract_app_databases()

        elif choice == "2":
            forensics.extract_app_shared_prefs()

        elif choice == "3":
            forensics.extract_app_files()

        elif choice == "4":
            forensics.extract_system_logs()

        elif choice == "5":
            forensics.extract_installed_packages()

        elif choice == "6":
            forensics.extract_running_processes()

        elif choice == "7":
            forensics.extract_wifi_networks()

        elif choice == "8":
            forensics.generate_report()

        else:
            console.print("[red]Invalid choice[/red]")

        console.input("[dim]Press Enter to continue...[/dim]")
