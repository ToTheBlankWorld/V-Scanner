"""Reports & history workspace (Stage 11): the Qt counterpart of the TUI
Stage 07 reports screen, reusing the EXISTING services untouched:

* the export source is the session's LAST TERMINAL full-device scan
  bundle held by ``DesktopBackend.last_scan()``;
* the legacy ``ReportService`` (SC-9 byte-parity exporter) is the only
  serialization path — three legacy formats (HTML / JSON / text), legacy
  naming in the legacy ``reports`` directory when no destination is
  chosen; the job runs off the GUI thread through the Stage 04 EXPORT
  plan (fast, atomic, exempt from cancellation by contract);
* honest gating: a cancelled/failed scan has NO bundle and cannot be
  exported; a completed SINGLE-APP scan stores no bundle either — the
  legacy report schema is full-device and nothing is fabricated to fill
  that gap (the screen says exactly that);
* overwrite safety: the chosen single-format path is checked up front;
  an existing file is overwritten only after an explicit confirmation
  dialog (the legacy directory flow uses timestamped names, so it cannot
  silently hit the same file);
* success claims come ONLY from the service's ``ExportResult``
  (``formats_written`` paths that exist after the write); failures show
  ``engine_error_text`` — no raw traceback, no sensitive detail;
* the T-08 history table reads the counters-only store through the
  backend on a worker thread; corrupt/foreign records are skipped by the
  store itself and the panel reports honest read failures.

Threading model: dialogs + slot bodies run on the GUI thread; every
engine call runs in a worker (``WorkerCoordinator``) or a Stage 04 job.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from vscanner.core.events import JobKind, JobState, JobTerminalEvent
from vscanner.core.models import ReportFormat, ScanResultBundle
from vscanner.services.history import HistoryEntry
from vscanner.services.reports.service import default_report_filename

from .. import theme
from ..backend import DesktopBackend
from ..jobs_bridge_qt import JobEventSignalHub
from ..workers import WorkerCoordinator
from ..widgets import Panel, StatusChip, button
from .devices import engine_error_text

__all__ = ["ReportsPage"]

_STATUS_WORDS = {
    "completed": "completed",
    "cancelled": "cancelled",
    "failed": "failed",
}

_FORMAT_SUFFIX = {
    ReportFormat.HTML: ".html",
    ReportFormat.JSON: ".json",
    ReportFormat.TEXT: ".text",
}

_FORMAT_FILTER = {
    ReportFormat.HTML: "HTML report (*.html)",
    ReportFormat.JSON: "JSON report (*.json)",
    ReportFormat.TEXT: "Text report (*.text *.txt)",
}


# ===========================================================================
# History table model (counters-only T-08 rows)
# ===========================================================================

class HistoryTableModel(QAbstractTableModel):
    """One row per recorded finished scan — Finished / Kind / Status /
    Device / Apps / Findings. Rows come exclusively from the T-08 store."""

    _HEADERS = ("Finished (UTC)", "Kind", "Status", "Device", "Apps",
                "Findings")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[HistoryEntry, ...] = ()

    def set_rows(self, rows: Sequence[HistoryEntry]) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

    def rowCount(
            self, parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(
            self, parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        return len(self._HEADERS)

    def headerData(self, section, orientation,
                   role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and \
                role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def data(self, index: QModelIndex | QPersistentModelIndex,
             role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return entry.finished_at_utc or "unknown time"
            if column == 1:
                return entry.kind or "unknown"
            if column == 2:
                return _STATUS_WORDS.get(entry.status, entry.status)
            if column == 3:
                return entry.device_serial or "—"
            if column == 4:
                return str(entry.total_apps)
            if column == 5:
                return str(entry.findings_total)
        return None


# ===========================================================================
# The workspace page
# ===========================================================================

class ReportsPage(QWidget):
    """One cached per-section workspace widget (never reconstructed)."""

    def __init__(self, backend: DesktopBackend, hub: JobEventSignalHub,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._hub = hub
        self._workers = WorkerCoordinator(self)

        self.setAccessibleName("Reports and history workspace")

        # last-terminal scan summary (never fabricated)
        self._last_status: Optional[str] = None
        self._last_serial: Optional[str] = None
        self._last_bundle: Optional[ScanResultBundle] = None

        # export state: none | running | ok | failed | refused
        self._export_state = "none"
        self._export_job_id: Optional[str] = None
        self._export_lines: tuple[str, ...] = ()
        self._export_error: Optional[str] = None

        # history state: idle | loading | ok | empty | failed
        self._history_state = "idle"
        self._history_error: Optional[str] = None
        self._history_rows: tuple[HistoryEntry, ...] = ()
        self._history_stamp: Optional[str] = None

        self._build_ui()
        self._load_last_scan()
        self._render_last_scan()
        self._render_export()
        self._render_history()
        self._hub.terminal.connect(self._on_terminal_event)

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACING["s"])

        outer.addWidget(self._build_export_panel())
        outer.addWidget(self._build_history_panel(), 1)

    def _build_export_panel(self) -> Panel:
        panel = Panel(self)
        layout = Panel.body_layout(panel)
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(theme.SPACING["m"])
        self._scan_chip = StatusChip("neutral", panel)
        banner_row.addWidget(self._scan_chip)
        self._last_label = QLabel("", panel)
        self._last_label.setObjectName("secondaryText")
        self._last_label.setWordWrap(True)
        banner_row.addWidget(self._last_label, 1)
        layout.addLayout(banner_row)

        export_row = QHBoxLayout()
        export_row.setContentsMargins(0, 0, 0, 0)
        export_row.setSpacing(theme.SPACING["m"])
        self._format_combo = QComboBox(panel)
        self._format_combo.setAccessibleName("Report format")
        self._format_combo.addItem("All three legacy formats",
                                   userData="all")
        for fmt in (ReportFormat.HTML, ReportFormat.JSON, ReportFormat.TEXT):
            self._format_combo.addItem(f"{fmt.name} report", userData=fmt)
        self._export_button = button(
            "Export…", variant="primary",
            tooltip="Export the last completed full-device scan through "
                    "the legacy report service (runs off the GUI thread)",
            accessible_name="Export report")
        self._export_button.clicked.connect(self._on_export)
        export_row.addWidget(self._format_combo)
        export_row.addStretch(1)
        export_row.addWidget(self._export_button)
        layout.addLayout(export_row)

        self._export_label = QLabel("", panel)
        self._export_label.setObjectName("secondaryText")
        self._export_label.setWordWrap(True)
        layout.addWidget(self._export_label)

        honesty = QLabel(
            "Reports are produced by the same legacy-format service the CLI "
            "uses (byte-identical schema); evidence excerpts are redacted "
            "by the engine boundary. No report is claimed saved before the "
            "service confirms the file it wrote.",
            panel)
        honesty.setObjectName("hintText")
        honesty.setWordWrap(True)
        layout.addWidget(honesty)
        return panel

    def _build_history_panel(self) -> Panel:
        panel = Panel(self)
        layout = Panel.body_layout(panel)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(theme.SPACING["m"])
        heading = QLabel("Local scan history (T-08 store — counters only)",
                         panel)
        heading.setObjectName("panelHeading")
        heading.setAccessibleName("Local scan history")
        header_row.addWidget(heading, 1)
        self._history_button = button(
            "Refresh history", variant="secondary",
            tooltip="Read the local scan-history store (background worker)",
            accessible_name="Refresh scan history")
        self._history_button.clicked.connect(self.refresh_history)
        header_row.addWidget(self._history_button)
        layout.addLayout(header_row)

        self._history_banner = QLabel("", panel)
        self._history_banner.setObjectName("secondaryText")
        self._history_banner.setWordWrap(True)
        layout.addWidget(self._history_banner)

        self._history_model = HistoryTableModel()
        self._history_table = QTableView(panel)
        self._history_table.setObjectName("historyTable")
        self._history_table.setModel(self._history_model)
        self._history_table.horizontalHeader().setStretchLastSection(True)
        self._history_table.setAccessibleName(
            "Recorded scans (headers only, no findings content)")
        layout.addWidget(self._history_table, 1)
        return panel

    # ------------------------------------------------------------------ #
    # lifecycle hooks the shell uses
    # ------------------------------------------------------------------ #

    def activate(self) -> None:
        """Read the honest last-scan memory + kick one history read."""
        self._load_last_scan()
        self._render_last_scan()
        if self._history_state == "idle":
            self.refresh_history()

    def shutdown(self) -> None:
        try:
            self._hub.terminal.disconnect(self._on_terminal_event)
        except RuntimeError:
            pass
        self._workers.close()

    # ------------------------------------------------------------------ #
    # last-terminal scan summary (session memory, never fabricated)
    # ------------------------------------------------------------------ #

    def _load_last_scan(self) -> None:
        try:
            last = self._backend.last_scan()
        except Exception:
            last = None
        self._last_status = last[0] if last else None
        self._last_serial = last[1] if last else None
        self._last_bundle = last[2] if last else None

    def _render_last_scan(self) -> None:
        chip = self._scan_chip
        label = self._last_label
        if self._last_status is None:
            chip.set_status("neutral")
            label.setText(
                "no terminal scan this session yet — run a scan on the "
                "Scanning & findings section")
            self._export_button.setEnabled(False)
            self._export_button.setToolTip(
                "No completed full-device scan is available to export")
            return
        status_word = _STATUS_WORDS.get(self._last_status, self._last_status)
        if self._last_bundle is None:
            chip.set_status("warning" if status_word == "completed"
                            else "error")
            if status_word == "completed":
                label.setText(
                    f"last terminal scan: single-app result for "
                    f"{self._last_serial or '—'} — completed, but NOT "
                    "exportable through the legacy full-device report "
                    "schema (the engine did not produce a bundle; nothing "
                    "is fabricated to fill the gap)")
            else:
                label.setText(
                    f"last terminal scan: {status_word} — partial "
                    "outcomes are not exportable; run a complete scan "
                    "first")
            self._export_button.setEnabled(False)
            self._export_button.setToolTip(
                "Export requires a completed full-device scan bundle")
            return
        summary = self._last_bundle.summary
        chip.set_status("ok")
        label.setText(
            f"last completed full-device scan · target "
            f"{self._last_serial or '—'} · {summary.total_apps} app(s) · "
            f"{summary.findings_total} finding(s) · ready to export")
        self._export_button.setEnabled(True)
        self._export_button.setToolTip(
            "Ask where to save; generation and file writes run off the "
            "GUI thread")

    # ------------------------------------------------------------------ #
    # export flow (dialogs on the GUI thread; work off it)
    # ------------------------------------------------------------------ #

    def _on_export(self) -> None:
        self._load_last_scan()
        bundle = self._last_bundle
        if self._export_state == "running":
            self._export_state = "refused"
            self._export_error = None
            self._export_label.setText(
                "An export is already running — it is atomic and fast; "
                "wait for its terminal outcome.")
            self._render_export()
            return
        if self._last_status != "completed" or bundle is None:
            self._export_state = "refused"
            self._export_error = (
                "export requires a completed full-device scan — nothing "
                "was started")
            self._render_export()
            return
        choice = self._format_combo.currentData()
        requested: dict[ReportFormat, Optional[str]] = {}
        output_dir: Optional[str] = None
        if choice == "all":
            directory = QFileDialog.getExistingDirectory(
                self, "Choose the report directory (legacy generated names)")
            if not directory:
                self._export_state = "refused"
                self._export_error = None
                self._export_label.setText(
                    "No destination chosen — nothing was written.")
                self._render_export()
                return
            output_dir = directory
            for all_fmt in ReportFormat:
                requested[all_fmt] = None  # legacy generated timestamped names
        else:
            fmt = choice
            path, _filter = QFileDialog.getSaveFileName(
                self, f"Save {fmt.name} report",
                default_report_filename(ext=_FORMAT_SUFFIX[fmt]),
                _FORMAT_FILTER[fmt])
            if not path:
                self._export_state = "refused"
                self._export_error = None
                self._export_label.setText(
                    "No destination chosen — nothing was written.")
                self._render_export()
                return
            if not path.endswith((_FORMAT_SUFFIX[fmt],)):
                path = path + _FORMAT_SUFFIX[fmt]
            if os.path.exists(path) and not self._confirm_overwrite(path):
                self._export_state = "refused"
                self._export_error = None
                self._export_label.setText(
                    "Cancelled: the existing file was left untouched.")
                self._render_export()
                return
            chosen = Path(path)
            output_dir = str(chosen.parent.absolute())
            requested[fmt] = chosen.name
        self._start_export(bundle, requested, output_dir)

    def _confirm_overwrite(self, path: str) -> bool:
        """Explicit overwrite confirmation — silence would hide the write."""
        answer = QMessageBox.question(
            self, "Overwrite existing report?",
            f"{path}\nalready exists. Overwrite it with the new report?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _start_export(self, bundle: ScanResultBundle,
                      requested: dict[ReportFormat, Optional[str]],
                      output_dir: str) -> None:
        try:
            handle = self._backend.start_export_job(
                bundle, requested=requested, output_dir=output_dir,
                serial=self._last_serial)
        except Exception as exc:
            self._export_state = "failed"
            self._export_error = engine_error_text(exc)
            self._export_lines = ()
            self._render_export()
            return
        self._export_job_id = handle.id
        self._export_state = "running"
        self._export_error = None
        self._export_lines = ()
        self._render_export()

    def _render_export(self) -> None:
        label = self._export_label
        label.setWordWrap(True)
        if self._export_state == "running":
            label.setText("Export running… (legacy-format service writes "
                          "the files off the GUI thread)")
        elif self._export_state == "ok":
            label.setText("\n".join(self._export_lines))
            label.setStyleSheet(
                f"color: {theme.SUCCESS_COLOR}; background: transparent;")
        elif self._export_state == "failed":
            label.setText(
                f"export failed: {self._export_error} — nothing is claimed "
                "as saved")
            label.setStyleSheet(
                f"color: {theme.ERROR_COLOR}; background: transparent;")
        elif self._export_state == "refused":
            # a programmatic refusal carries its reason; a dialog-cancel
            # refusal set its own message on the label already
            if self._export_error:
                label.setText(f"Refused: {self._export_error}")
                label.setStyleSheet("")
        else:
            label.setText("")

    # ------------------------------------------------------------------ #
    # history (T-08 store; worker thread)
    # ------------------------------------------------------------------ #

    def refresh_history(self) -> None:
        self._history_button.setEnabled(False)
        started = self._workers.run(
            "history_read", self._backend.history_recent,
            self._on_history_done, self._on_history_failed)
        if started:
            self._history_state = "loading"
            self._render_history()

    def _on_history_done(self, entries: Sequence[Any]) -> None:
        self._history_rows = tuple(entries)
        self._history_state = "ok" if self._history_rows else "empty"
        self._history_error = None
        self._history_stamp = datetime.now().strftime("%H:%M:%S")
        self._history_button.setEnabled(True)
        self._render_history()

    def _on_history_failed(self, exc: BaseException) -> None:
        self._history_rows = ()
        self._history_state = "failed"
        self._history_error = engine_error_text(exc)
        self._history_button.setEnabled(True)
        self._render_history()

    def _render_history(self) -> None:
        self._history_model.set_rows(self._history_rows)
        banner = self._history_banner
        banner.setWordWrap(True)
        if self._history_state == "loading":
            banner.setText("reading local scan history …")
        elif self._history_state == "failed":
            banner.setText(
                f"scan history unavailable: {self._history_error} — no "
                "record is invented in its place")
        elif self._history_state == "empty":
            banner.setText(
                "no scans recorded yet — every completed, cancelled or "
                "failed scan appends one honest entry (counters only)")
        elif self._history_state == "ok":
            stamp = f", read at {self._history_stamp}" if self._history_stamp \
                else ""
            banner.setText(
                f"{len(self._history_rows)} recorded scan(s){stamp} — "
                "counters only; no findings content or secret material is "
                "stored")

    # ------------------------------------------------------------------ #
    # job-event delivery
    # ------------------------------------------------------------------ #

    def _on_terminal_event(self, event: Any) -> None:
        if not isinstance(event, JobTerminalEvent):
            return
        if event.kind is not JobKind.EXPORT:
            return
        # Identity is the tracked job id (the terminal event has no serial).
        if event.job_id != self._export_job_id:
            return  # late foreign event — never touch state
        self._export_job_id = None
        if event.outcome is JobState.SUCCEEDED:
            export = event.result
            formats = getattr(export, "formats_written", None) or {}
            ok = bool(getattr(export, "ok", False)) and bool(formats)
            if ok:
                lines = ["export succeeded:"]
                for fmt, path in formats.items():
                    lines.append(f"  {fmt} → {path}")
                self._export_state = "ok"
                self._export_lines = tuple(lines)
            else:
                self._export_state = "failed"
                self._export_error = (
                    "the export service reported failure: "
                    + (str(getattr(export, "error", None)) or
                       "no detail provided"))
                self._export_lines = ()
        else:  # caution-first mapping for non-success terminals
            self._export_state = "failed"
            self._export_error = (
                engine_error_text(event.error)
                if event.error is not None
                else f"the export job did not succeed "
                     f"({event.outcome.value}); nothing is claimed saved")
            self._export_lines = ()
        self._render_export()
