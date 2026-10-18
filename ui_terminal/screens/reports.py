"""Reports & scan history (Stage 07): export through SC-9, T-08 history.

Export behavior (SC-9, no TUI-side serialization):

* the export always runs the EXISTING ``ReportService`` through the Stage
  04 EXPORT plan — the TUI never reimplements a single format;
* the last completed scan bundle of this session is the source (a
  cancelled or failed scan has no bundle and cannot be exported — the
  panel says so instead of pretending);
* default names/directory follow the legacy conventions (generated
  timestamped names in ``reports``), so accidental overwrites are
  impossible through this flow; an explicit directory is honored by the
  service (created when missing);
* success is only claimed for what really happened: every shown path
  comes from the service's ``ExportResult.formats_written``;
* the scan-history table reads the T-08 store (plain JSON files, capped,
  no secret material) and says when entries could not be read.
"""

from __future__ import annotations

from typing import Optional, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label

from vscanner.core.events import JobTerminalEvent

from ui_terminal.backend import DeviceBackend
from ui_terminal.screens.shell import ShellScreen

__all__ = ["ReportsScreen"]

_STATUS_WORDS = {
    "completed": "completed",
    "cancelled": "cancelled",
    "failed": "failed",
    "unknown": "unknown",
}


class ReportsScreen(ShellScreen):
    """Report export entry point + local scan history (T-08)."""

    SECTION_ID = "reports"

    BINDINGS = [
        Binding("r", "refresh_history", "Refresh history"),
        Binding("x", "export_last", "Export last completed scan"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._history: tuple = ()
        self._history_state = "idle"   # idle | loading | ok | failed | empty
        self._history_error: Optional[str] = None
        self._export_job_id: Optional[str] = None
        self._export_state = "none"    # none | running | ok | failed
        self._export_lines: list = []
        self._export_error: Optional[str] = None

    @property
    def backend(self) -> DeviceBackend:
        return cast(DeviceBackend, getattr(self.app, "backend"))

    # -- composition ----------------------------------------------------------- #

    def inner_body(self) -> ComposeResult:
        with Vertical(id="rp-body"):
            yield Label(
                "All three legacy formats (HTML/JSON/text) are produced by "
                "the shared report service; nothing is serialized here. The "
                "default directory keeps the legacy convention "
                "(``reports`` next to the working directory).",
                id="rp-explain", classes="status-muted",
            )
            yield Label("", id="rp-banner", classes="status-muted")
            with Horizontal(id="rp-input-row"):
                yield Button("Export last scan · x", id="rp-export-btn",
                             flat=True, compact=True)
                yield Input(
                    placeholder="output directory (empty = legacy reports)",
                    id="rp-output-dir",
                )
            yield Label("", id="rp-last-scan", classes="status-muted")
            yield Label(
                "local scan history (T-08 JSON store; counters only — no "
                "findings content or secret material is stored)",
                id="rp-history-note", classes="status-muted",
            )
            yield DataTable(id="rp-history", show_cursor=False)
            yield Label("", id="rp-export-result", classes="status-muted")

    def on_mount(self) -> None:
        super().on_mount()
        table = self.query_one("#rp-history", DataTable)
        table.add_columns(
            "Finished (UTC)", "Kind", "Status", "Device", "Apps", "Findings")
        self._apply_all()
        self.action_refresh_history()

    # -- status ------------------------------------------------------------------ #

    def status_hint(self) -> str:
        if self._export_state == "running":
            return "reports · export in progress …"
        if self._export_state == "ok":
            return "reports · last export succeeded — paths on screen"
        if self._export_state == "failed":
            return "reports · last export FAILED — nothing was falsely claimed"
        return "reports · r refresh history · x export the last completed scan"

    def _render_last_scan(self) -> None:
        label = self.query_one("#rp-last-scan", Label)
        label.set_classes("status-muted")
        last = self._safe_last()
        if last is None:
            label.update(
                "no completed scan this session yet — run one on the "
                "scanning screen (f); a cancelled or failed scan has no "
                "bundle and cannot be exported")
            return
        status_word = _STATUS_WORDS.get(last[0], last[0])
        if status_word != "completed":
            label.update(
                f"the last terminal scan is {status_word} — partial states "
                "are not exportable; run a complete scan (f) to enable export")
            label.set_classes("status-warn")
            return
        bundle = last[2]
        summary = bundle.summary
        label.update(
            f"last completed scan · target {last[1] or 'unknown'} · "
            f"{summary.total_apps} app(s) · {summary.findings_total} "
            f"finding(s) · ready to export (x)")

    def _render_export(self) -> None:
        result = self.query_one("#rp-export-result", Label)
        result.set_classes("status-muted")
        if self._export_state == "running":
            result.update("export running … (atomic service write)")
        elif self._export_state == "ok":
            result.update("\n".join(self._export_lines))
            result.set_classes("status-ok")
        elif self._export_state == "failed":
            result.update(f"export failed: {self._export_error} — nothing "
                          "is claimed as saved")
            result.set_classes("status-error")
        else:
            result.update("")

    def _apply_all(self) -> None:
        self._render_banner()
        self._render_last_scan()
        self._render_export()
        self.refresh_status()

    # -- history ----------------------------------------------------------------- #

    def action_refresh_history(self) -> None:
        self._history_state = "loading"
        self._render_banner()
        backend = self.backend

        def work() -> None:
            try:
                entries = backend.history_recent()
            except Exception as exc:
                self.app.call_from_thread(
                    self._apply_history, (),
                    f"history read failed ({type(exc).__name__})")
            else:
                self.app.call_from_thread(self._apply_history, entries, None)

        self.app.run_worker(
            work, group="rp-history", exclusive=True, thread=True,
            exit_on_error=False, description="scan history read",
        )

    def _apply_history(self, entries: tuple,
                       failure: Optional[str]) -> None:
        self._history = tuple(entries)
        table = self.query_one("#rp-history", DataTable)
        table.clear()
        if failure is not None:
            self._history_state = "failed"
            self._history_error = failure
        elif not entries:
            self._history_state = "empty"
        else:
            self._history_state = "ok"
            self._history_error = None
        for entry in entries:
            table.add_row(
                entry.finished_at_utc or "unknown time",
                entry.kind,
                _STATUS_WORDS.get(entry.status, entry.status),
                entry.device_serial or "—",
                str(entry.total_apps),
                str(entry.findings_total),
            )
        self._render_banner()
        self.refresh_status()

    def _render_banner(self) -> None:
        banner = self.query_one("#rp-banner", Label)
        banner.set_classes("status-muted")
        if self._history_state == "loading":
            banner.update("reading local scan history …")
        elif self._history_state == "failed":
            banner.update(f"scan history unavailable: {self._history_error}")
            banner.set_classes("status-warn")
        elif self._history_state == "empty":
            banner.update(
                "no scans recorded yet — every completed, cancelled or "
                "failed scan appends one honest entry here")
        elif self._history_state == "ok":
            banner.update(f"{len(self._history)} recorded scan(s) — read "
                          "with the service that wrote them")

    # -- export job ---------------------------------------------------------------- #

    def action_export_last(self) -> None:
        if self._export_state == "running":
            self.notify(
                "an export is already running — it is atomic and fast",
                title="Report export", severity="information",
            )
            return
        backend = self.backend
        last = self._safe_last()
        if last is None:
            self.notify(
                "no completed scan this session — run a scan first (f)",
                title="Report export", severity="warning",
            )
            return
        status_word, serial, bundle = last
        if status_word != "completed":
            self.notify(
                f"the last scan is {status_word} — export is only offered "
                "for complete scans; partial outcome stays in the history",
                title="Report export", severity="warning",
            )
            return
        directory = self.query_one("#rp-output-dir", Input).value.strip()
        self._export_state = "running"
        self._export_error = None
        self._export_lines = []
        self._render_export()
        try:
            handle = backend.start_export_job(
                bundle, output_dir=directory or None, serial=serial)
        except Exception as exc:
            self._export_state = "failed"
            self._export_error = (
                f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"
            )
            self._render_export()
            return
        self._export_job_id = handle.id

    def _safe_last(self):
        try:
            return self.backend.last_scan()
        except Exception:
            return None

    # -- job events ------------------------------------------------------------------ #

    def on_job_event(self, event) -> None:
        if event.job_id != self._export_job_id:
            return
        if not isinstance(event, JobTerminalEvent):
            return
        self._export_job_id = None
        if event.outcome.value == "succeeded":
            export = cast("object", event.result)
            formats = getattr(export, "formats_written", None) or {}
            ok = bool(getattr(export, "ok", False))
            if ok and formats:
                lines = ["export succeeded:"]
                for fmt, path in formats.items():
                    lines.append(f"  {fmt} → {path}")
                self._export_state = "ok"
                self._export_lines = lines
            else:
                self._export_state = "failed"
                self._export_error = (
                    "the export service reported failure: "
                    + (str(getattr(export, "error", None)) or
                       "no detail provided")
                )
        else:
            self._export_state = "failed"
            self._export_error = (
                event.error.message if event.error is not None
                else "the export job failed (no detail provided)"
            )
        self._render_export()
        self.refresh_status()
