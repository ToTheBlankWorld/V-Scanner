"""Doctor — report-only environment screen (SC-11, R-14 semantic).

Renders the engine's :class:`vscanner.services.doctor.DependencyReport` as
a table. Report means report: this screen never installs anything and makes
no network calls; package checks are import-probes only. ADB executable
validation is a *user-initiated* action available on the Settings screen
(behind an explicit button — never at startup).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label
from typing_extensions import cast

from vscanner.services.doctor import DependencyReport, collect_dependency_report

from ui_terminal.screens.shell import ShellScreen

if TYPE_CHECKING:
    from ui_terminal.app import VScannerApp


class DoctorScreen(ShellScreen):
    """Environment report — honest absence states included."""

    SECTION_ID = "doctor"

    def __init__(self) -> None:
        super().__init__()
        self._report: DependencyReport | None = None
        self._error: str | None = None

    def inner_body(self) -> ComposeResult:
        table: DataTable
        table = DataTable(id="doctor-table", show_cursor=False)
        table.add_columns("Component", "State", "Note")
        with Vertical(id="doctor-body"):
            yield Label("", id="doctor-python")
            yield table
            yield Label(
                "doctor is report-only: installs happen only by explicit user action",
                id="doctor-note",
            )
            yield Label("", id="doctor-error", classes="status-error")

    def on_mount(self) -> None:
        super().on_mount()
        self.refresh_doctor()

    def refresh_doctor(self) -> None:
        """Rebuild the table from a fresh engine report (no side effects)."""
        try:
            self._report = collect_dependency_report(tools_service=None)
            self._error = None
        except Exception as exc:  # report building must never crash the TUI
            self._report = None
            self._error = f"environment report failed: {type(exc).__name__}"
        self._render_table()
        self.refresh_status()

    def _render_table(self) -> None:
        table = self.query_one("#doctor-table", DataTable)
        table.clear()
        report = self._report
        if report is None:
            self.query_one("#doctor-python", Label).update("")
            table.add_row("environment report", "unavailable", self._error or "")
            return
        self.query_one("#doctor-python", Label).update(
            f"Python: {report.python_version}"
        )
        for package in report.packages:
            table.add_row(
                f"package {package.name}",
                "installed" if package.installed else "missing",
                import_probe_note(package.installed),
            )
        self.query_one("#doctor-error", Label).update("")

    def _doctor_summary(self) -> str:
        if self._error:
            return self._error
        report = self._report
        if report is None:
            return "not run yet"
        missing = report.missing_packages()
        if missing:
            return f"report-ready · packages missing: {', '.join(missing)}"
        return "report-ready · all runtime packages present"

    def status_hint(self) -> str:
        return self._doctor_summary()

    def refresh_status(self) -> None:
        base = self.status_hint()
        self.query_one("#status-line", Label).update(base)
        vscanner_app = cast("VScannerApp", self.app)
        vscanner_app.last_doctor_summary = base


def import_probe_note(installed: bool) -> str:
    """Unambiguous per-row note (status never relies on color alone)."""
    if installed:
        return "import-probe present"
    return "not importable in this environment"
