"""Demo dataset (Stage 08, SC-10): deterministic sample findings.

The demo bundle comes from :class:`vscanner.services.demo.DemoService` —
a deterministic three-app fixture whose findings are all INFO with
``[DEMO]`` titles. NO device is contacted: this screen is pure
presentation over in-process data (UI-thread safe by construction) and
the banner says so unmissably. It exists so reviewers and trainers can
present the findings workflows without buying or flashing hardware.
"""

from __future__ import annotations

from typing import Optional, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Label

from ui_terminal.backend import DeviceBackend
from ui_terminal.screens.shell import ShellScreen

__all__ = ["DemoScreen"]


class DemoScreen(ShellScreen):
    """Deterministic demo findings — clearly labeled, never device data."""

    SECTION_ID = "demo"

    BINDINGS = [
        Binding("r", "regenerate", "Rebuild the demo bundle"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._demo_state = "idle"   # idle | ready | failed
        self._demo_error: Optional[str] = None
        self._bundle = None
        self._summary = None

    @property
    def backend(self) -> DeviceBackend:
        return cast(DeviceBackend, getattr(self.app, "backend"))

    def inner_body(self) -> ComposeResult:
        with Vertical(id="demo-body"):
            yield Label(
                "DEMO DATA — this table is a DETERMINISTIC FIXTURE built in "
                "memory; no device was contacted and nothing here is real "
                "scan output. Every row exists to rehearse the findings "
                "workflow (SC-10).",
                id="demo-banner", classes="status-warn",
            )
            yield Label("", id="demo-summary", classes="status-muted")
            yield DataTable(id="demo-findings", cursor_type="row")

    def on_mount(self) -> None:
        super().on_mount()
        findings = self.query_one("#demo-findings", DataTable)
        findings.add_columns("Severity", "Category", "App", "Finding")
        self.action_regenerate()

    def status_hint(self) -> str:
        if self._demo_state == "failed":
            return f"demo · fixture build failed ({self._demo_error})"
        return ("demo · deterministic fixture, no device contact · "
                "r rebuilds the same dataset (it is deterministic by design)")

    def _apply_all(self) -> None:
        self._render_summary()
        self._render_findings()
        self.refresh_status()

    def action_regenerate(self) -> None:
        # Safe on the UI thread: SC-10 builds its fixture in-process, no
        # subprocess/transport is touched.
        try:
            bundle = self.backend.demo_bundle()
        except Exception as exc:
            self._demo_state = "failed"
            self._demo_error = (
                f"{type(exc).__name__}: {getattr(exc, 'message', exc)}")
            self._apply_all()
            return
        self._bundle = bundle
        self._summary = getattr(bundle, "summary", None)
        self._demo_state = "ready"
        self._apply_all()

    def _render_summary(self) -> None:
        label = self.query_one("#demo-summary", Label)
        summary = self._summary
        if summary is None:
            label.update("no demo bundle yet")
            return
        apps = getattr(summary, "total_apps", None)
        run = getattr(summary, "run", None)
        run_id = getattr(run, "run_id", "") if run is not None else ""
        demo_flag = getattr(summary, "demo", False)
        label.update(
            f"{apps} fixture app(s) · demo flag: {demo_flag} · "
            f"fixture run id: {run_id}")

    def _render_findings(self) -> None:
        table = self.query_one("#demo-findings", DataTable)
        table.clear()
        if self._demo_state == "failed":
            table.add_row("—", "fixture build failed", "—",
                          self._demo_error or "")
            return
        bundle = self._bundle
        if bundle is None:
            table.add_row("—", "—", "—", "no demo bundle yet")
            return
        # findings are computed per app by the fixture itself
        rows = []
        for app_result in getattr(bundle, "apps", ()):
            app_name = getattr(app_result, "package", "") or _app_label(app_result)
            for finding in getattr(app_result, "findings", ()):
                rows.append((
                    str(getattr(finding, "severity", "")).replace(
                        "FindingSeverity.", ""),
                    str(getattr(finding, "kind", "")).replace(
                        "FindingCategory.", ""),
                    app_name,
                    getattr(finding, "title", ""),
                ))
        if not rows:
            table.add_row("—", "—", "—", "fixture produced no findings")
            return
        for row in rows:
            table.add_row(*row)


def _app_label(app_result) -> str:
    app_info = getattr(app_result, "app", None)
    if app_info is None:
        return "device-scope"
    return getattr(app_info, "label", "") or getattr(app_info, "package", "")
