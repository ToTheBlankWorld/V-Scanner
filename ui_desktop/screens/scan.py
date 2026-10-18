"""Scanning & findings workspace (Stage 11): the Qt counterpart of the
TUI Stage 07 scan screen, built on the exact same service contracts:

* the scan target is an EXPLICIT selection on this screen's own device
  table (one unambiguous device is preselected, several are never); the
  target is REVALIDATED with a fresh discovery before every submission —
  a cached selection is never trusted (stale-target safety);
* a preflight summary (target + scope + honest limitations) is always
  visible before execution; starting requires a currently listed,
  DEVICE-state selection — anything else is refused with actionable text;
* scans run as FULL_DEVICE_SCAN / SINGLE_APP_SCAN Stage 04 jobs through
  the existing JobManager (per-device ``scan`` mutex group). Duplicate
  submission is refused at the surface (busy controls) AND at the engine
  (``JobConflictError`` — surfaced honestly, never retried blindly);
* engine semantics are preserved untouched: cancellable via token
  checkpoints, streamed ``JobFindingEvent`` rows, honest progress text
  (no fabricated percentages), terminal outcomes distinguished as
  completed / cancelled / failed. A cancellation request is NOT a
  completion: only the CANCELLED terminal event closes the state;
* terminal events are reconciled BY TRACKED JOB ID (JobTerminalEvent
  carries no device_serial — Stage 10 truth). Late events, foreign jobs
  and superseded targets never mutate the workspace;
* findings stay exactly the typed engine findings: filters narrow the
  rendered VIEW and never mutate the underlying results; sorting is
  deterministic; row identity is the view position (the legacy stable-id
  quirk can legitimately emit one id twice — TUI parity);
* single-app terminal results are typed ``AppScanResult`` objects: they
  show findings and record history, but are NOT eligible for the legacy
  full-report export (the report service contract takes a
  ``ScanResultBundle``; nothing is fabricated to fill that gap);
* history is the T-08 counters-only store through the backend (written
  on a worker thread; no findings text, no secret material).

Threading model: ZERO subprocess/ADB code here — engine calls live in
``ui_desktop.workers.WorkerCoordinator`` slots or Stage 04 job threads;
job events arrive through the shell's ``QtJobEventBridge`` hub (queued
to GUI-thread slots).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, Sequence

from PySide6.QtCore import (
    QAbstractTableModel,
    QItemSelectionModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from vscanner.core.events import (
    JobFindingEvent,
    JobKind,
    JobProgressEvent,
    JobState,
    JobTerminalEvent,
)
from vscanner.core.models import (
    AppScanResult,
    ConnectionInfo,
    DeviceState,
    EvidenceKind,
    Finding,
    FindingCategory,
    FindingSeverity,
    ScanResultBundle,
)
from vscanner.services.history import HistoryEntry

from .. import theme
from ..backend import DesktopBackend
from ..jobs_bridge_qt import JobEventSignalHub
from ..workers import WorkerCoordinator
from ..widgets import Panel, StatusChip, button
from .devices import DevicesTableModel, engine_error_text

from vscanner.services.scanning.scanner import validate_package_name  # noqa: E402

__all__ = ["ScanWorkspacePage", "PAGE_SIZE"]

PAGE_SIZE = 100
"""Same explicit pagination contract as the device inventory."""

_ACTIONABLE = DeviceState.DEVICE

_SEVERITY_RANK = {
    FindingSeverity.CRITICAL: 0,
    FindingSeverity.HIGH: 1,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.LOW: 3,
    FindingSeverity.INFO: 4,
}

_SEVERITY_LABEL = {
    FindingSeverity.CRITICAL: "critical",
    FindingSeverity.HIGH: "high",
    FindingSeverity.MEDIUM: "medium",
    FindingSeverity.LOW: "low",
    FindingSeverity.INFO: "info",
}

_CATEGORY_LABEL = {
    FindingCategory.PERMISSION_EXCESS: "permission excess",
    FindingCategory.SDK_COMPAT: "SDK compatibility",
    FindingCategory.INSECURE_URL: "insecure URL",
    FindingCategory.HARDCODED_SECRET: "hardcoded secret",
    FindingCategory.DEVICE_EXPOSURE: "device exposure",
    FindingCategory.FORENSICS_ARTIFACT: "forensics artifact",
    FindingCategory.INFO_NOTE: "info note",
}

_EVIDENCE_WORDS = {
    EvidenceKind.CONFIRMED_ARTIFACT: "observed",
    EvidenceKind.CONFIRMED_COMMAND_OUTPUT: "observed (command output)",
    EvidenceKind.HEURISTIC_PATTERN: "heuristic",
    EvidenceKind.INFORMATIONAL: "informational",
    EvidenceKind.UNVERIFIED_CONDITION: "unverified",
}

# Evidence-confidence buckets (the engine's honest provenance words).
_PROVENANCE_BUCKETS: tuple[str, ...] = (
    "observed", "informational", "heuristic", "unverified", "no evidence",
)

_PROVENANCE_SET: dict[str, frozenset[EvidenceKind]] = {
    "observed": frozenset((
        EvidenceKind.CONFIRMED_ARTIFACT,
        EvidenceKind.CONFIRMED_COMMAND_OUTPUT,
    )),
    "informational": frozenset((EvidenceKind.INFORMATIONAL,)),
    "heuristic": frozenset((EvidenceKind.HEURISTIC_PATTERN,)),
    "unverified": frozenset((EvidenceKind.UNVERIFIED_CONDITION,)),
}


def _honest(value: Any, word: str = "unknown") -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return word
    return str(value)


def _package_of(finding: Finding) -> str:
    return finding.app.package_name if finding.app is not None else ""


# ===========================================================================
# Findings table model
# ===========================================================================

class FindingsTableModel(QAbstractTableModel):
    """One row per engine finding — Severity / Category / Title / App /
    Evidence. Data is exclusively what the engine returned; identity is
    the view position (stable ids may repeat legitimately)."""

    _HEADERS = ("Severity", "Category", "Title", "App", "Evidence")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[Finding, ...] = ()

    def set_rows(self, rows: Sequence[Finding]) -> None:
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
        """Render defensively: one unexpected/malformed field renders as
        "unknown" instead of crashing the view (no fabricated values)."""
        if not index.isValid():
            return None
        try:
            finding = self._rows[index.row()]
            column = index.column()
            if role == Qt.ItemDataRole.DisplayRole:
                if column == 0:
                    return _SEVERITY_LABEL.get(
                        finding.severity, _honest(finding.severity))
                if column == 1:
                    return _CATEGORY_LABEL.get(
                        finding.kind, _honest(finding.kind))
                if column == 2:
                    return _honest(finding.title, "untitled")
                if column == 3:
                    return _package_of(finding) or (
                        "device scope" if finding.device_serial
                        else "(no app)")
                if column == 4:
                    return str(len(finding.evidence))
            elif role == Qt.ItemDataRole.ToolTipRole and column == 4:
                words = ", ".join(sorted({
                    _EVIDENCE_WORDS.get(evidence.kind, evidence.kind.value)
                    for evidence in finding.evidence}) or {"none"})
                return f"evidence kinds: {words}"
        except Exception:  # a malformed engine finding must not crash the view
            return "(malformed finding)" if role == Qt.ItemDataRole.DisplayRole \
                else None
        return None

    @property
    def rows(self) -> tuple[Finding, ...]:
        return self._rows


class FindingDetailTableModel(QAbstractTableModel):
    """Field/Value rows for one finding's detail view (explicit "not
    available" for absent optional data — never a fabricated fallback)."""

    _HEADERS = ("Field", "Value")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[tuple[str, str], ...] = ()

    def set_finding(self, finding: Optional[Finding]) -> None:
        self.beginResetModel()
        self._rows = () if finding is None else self._detail_rows(finding)
        self.endResetModel()

    @staticmethod
    def _detail_rows(finding: Finding) -> tuple[tuple[str, str], ...]:
        def safe(fn) -> str:
            try:
                return _honest(fn(), "not available")
            except Exception:
                return "(unreadable field)"

        rows: list[tuple[str, str]] = []
        try:
            rows.append(("Title", _honest(finding.title, "untitled")))
        except Exception:
            rows.append(("Title", "(unreadable field)"))
        try:
            rows.append(("Severity", _SEVERITY_LABEL.get(
                finding.severity, _honest(finding.severity))))
            rows.append(("Category", _CATEGORY_LABEL.get(
                finding.kind, _honest(finding.kind))))
        except Exception:
            rows.append(("Severity", "(unreadable field)"))
        rows.append(("Detail", safe(lambda: finding.detail)))
        try:
            package = _package_of(finding)
            rows.append(("App", package if package else "not available"))
            if not package and finding.device_serial:
                rows.append(("Device scope", finding.device_serial))
        except Exception:
            rows.append(("App", "(unreadable field)"))
        try:
            rows.append(("Finding id",
                         _honest(finding.id, "not assigned by the engine")))
            rows.append(("Detected by", _honest(finding.detected_by)))
        except Exception:
            rows.append(("Finding id", "(unreadable field)"))
        rows.append(("Run id", safe(lambda: finding.run_id or "not available")))
        try:
            lines = [
                f"({_EVIDENCE_WORDS.get(ev.kind, ev.kind.value)}) "
                f"{_honest(ev.source, 'no source recorded')} — "
                f"{_honest(ev.description, 'no description recorded')}"
                for ev in finding.evidence
            ]
            rows.append(("Evidence", "\n".join(lines) or "no evidence recorded"))
        except Exception:
            rows.append(("Evidence", "(unreadable field)"))
        try:
            recs = [
                f"({rem.category.value}) {rem.recommendation}"
                for rem in finding.remediation
                if rem.recommendation
            ]
            rows.append(("Recommended fix",
                         "\n".join(recs) or "none provided by the engine"))
        except Exception:
            rows.append(("Recommended fix", "(unreadable field)"))
        return tuple(rows)

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
        if role == Qt.ItemDataRole.DisplayRole:
            key, text = self._rows[index.row()]
            return text if index.column() == 1 else key
        return None

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        return self._rows


def _now_stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ===========================================================================
# The workspace page
# ===========================================================================

class ScanWorkspacePage(QWidget):
    """One cached per-section workspace widget (never reconstructed)."""

    def __init__(self, backend: DesktopBackend, hub: JobEventSignalHub,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._hub = hub
        self._workers = WorkerCoordinator(self)

        self.setAccessibleName("Scanning and findings workspace")

        # honest device-discovery state (same contract as the device page) --
        self._devices: tuple[ConnectionInfo, ...] = ()
        self._devices_state = "idle"          # idle | loading | refreshed | failed
        self._devices_stale = False
        self._devices_error: Optional[str] = None
        self._refresh_stamp: Optional[str] = None
        self._auto_refresh_done = False
        self._selected_serial: Optional[str] = None
        self._invalidation_note: Optional[str] = None

        # scope --------------------------------------------------------------
        self._include_system = False
        self._deep = False

        # scan lifecycle -------------------------------------------------------
        self._scan_state = "idle"   # idle | validating | running | completed |
        #                             cancelled | failed | away | not-exportable
        self._scan_error: Optional[str] = None
        self._scan_job_id: Optional[str] = None
        self._scan_target_serial: Optional[str] = None
        self._scan_kind_word = ""
        self._scan_result_kind = ""  # bundle | single_app | unexpected
        self._progress_text = ""
        self._terminal_stamp: Optional[str] = None
        self._exportable = False

        # findings ---------------------------------------------------------------
        self._findings: tuple[Finding, ...] = ()
        self._findings_status = "none"   # none | streaming | complete |
        #                                  | partial-stream | from-bundle
        self._streamed = 0
        self._text_filter = ""
        self._severity_min: Optional[FindingSeverity] = None
        self._category: Optional[FindingCategory] = None
        self._provenance: Optional[str] = None
        self._sort_key = "severity"
        self._findings_page = 0
        self._detail_finding: Optional[Finding] = None
        self._row_findings: dict[int, Finding] = {}

        # history ---------------------------------------------------------------
        self._history_queue: list[HistoryEntry] = []
        self._history_failed: Optional[str] = None

        self._build_ui()
        # Truthful initial render for every panel.
        self._render_devices_panel()
        self._render_preflight()
        self._render_scan_state()
        self._render_findings()
        self._render_detail()
        self._sync_controls()
        # Subscribe ONCE — the shell caches one widget per section, so
        # repeated navigation cannot create duplicate subscriptions.
        self._hub.progress.connect(self._on_progress_event)
        self._hub.finding.connect(self._on_finding_event)
        self._hub.terminal.connect(self._on_terminal_event)

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACING["s"])

        # banner row: chip + explanation + refresh
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(theme.SPACING["m"])
        self._devices_chip = StatusChip("neutral", self)
        self._devices_banner = QLabel("", self)
        self._devices_banner.setObjectName("secondaryText")
        self._devices_banner.setWordWrap(True)
        self._refresh_button = button(
            "Refresh devices", variant="primary",
            tooltip="Run one adb devices discovery (background worker; "
                    "overlapping refreshes are refused)",
            accessible_name="Refresh devices")
        self._refresh_button.clicked.connect(self.refresh_devices)
        banner_row.addWidget(self._devices_chip)
        banner_row.addWidget(self._devices_banner, 1)
        banner_row.addWidget(self._refresh_button)
        outer.addLayout(banner_row)

        splitter = QSplitter(self)
        splitter.setOrientation(Qt.Orientation.Vertical)

        # --- device list panel (explicit scan target) -----------------------
        devices_panel = Panel(splitter)
        devices_layout = Panel.body_layout(devices_panel)
        self._devices_model = DevicesTableModel()
        self._devices_table = QTableView(devices_panel)
        self._devices_table.setObjectName("scanDevicesTable")
        self._devices_table.setModel(self._devices_model)
        self._devices_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._devices_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._devices_table.horizontalHeader().setStretchLastSection(True)
        self._devices_table.setMinimumHeight(110)
        self._devices_table.setAccessibleName("Scan targets")
        self._devices_table.selectionModel().currentRowChanged.connect(
            self._on_selection_changed)
        devices_layout.addWidget(self._devices_table)
        target_banner = QLabel("", devices_panel)
        target_banner.setObjectName("bodyText")
        target_banner.setWordWrap(True)
        self._target_banner = target_banner
        devices_layout.addWidget(target_banner)
        splitter.addWidget(devices_panel)

        # --- scan execution panel --------------------------------------------
        scan_panel = Panel(splitter)
        scan_layout = Panel.body_layout(scan_panel)
        self._preflight_label = QLabel("", scan_panel)
        self._preflight_label.setObjectName("bodyText")
        self._preflight_label.setWordWrap(True)
        scan_layout.addWidget(self._preflight_label)

        scope_row = QHBoxLayout()
        scope_row.setContentsMargins(0, 0, 0, 0)
        scope_row.setSpacing(theme.SPACING["m"])
        self._system_toggle = QCheckBox("Include system apps", scan_panel)
        self._system_toggle.setAccessibleName("Include system apps")
        self._system_toggle.toggled.connect(self._on_scope_changed)
        self._deep_toggle = QCheckBox("Deep scan (APK analysis)", scan_panel)
        self._deep_toggle.setAccessibleName("Deep scan toggle")
        self._deep_toggle.toggled.connect(self._on_scope_changed)
        scope_row.addWidget(self._system_toggle)
        scope_row.addWidget(self._deep_toggle)
        scope_row.addStretch(1)
        scan_layout.addLayout(scope_row)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(theme.SPACING["m"])
        self._package_input = QLineEdit(scan_panel)
        self._package_input.setPlaceholderText(
            "package to analyze (single-app scan)")
        self._package_input.setClearButtonEnabled(True)
        self._package_input.setAccessibleName("Single-app package name")
        self._package_input.textChanged.connect(
            lambda *_args: self._sync_controls())
        self._scan_button = button(
            "Scan device", variant="primary",
            tooltip="Start a full-device scan against the selected device "
                    "(revalidated first; never runs on the GUI thread)",
            accessible_name="Start full-device scan")
        self._scan_button.clicked.connect(self._on_start_full)
        self._scan_one_button = button(
            "Scan one app", variant="secondary",
            tooltip="Start a single-app scan for the typed package",
            accessible_name="Start single-app scan")
        self._scan_one_button.clicked.connect(self._on_start_single)
        self._cancel_button = button(
            "Cancel scan", variant="secondary",
            tooltip="Request cancellation — it completes at the engine's "
                    "next checkpoint",
            accessible_name="Cancel running scan")
        self._cancel_button.clicked.connect(self._on_cancel)
        action_row.addWidget(self._package_input, 1)
        action_row.addWidget(self._scan_one_button)
        action_row.addWidget(self._scan_button)
        action_row.addWidget(self._cancel_button)
        scan_layout.addLayout(action_row)

        self._progress_label = QLabel("", scan_panel)
        self._progress_label.setObjectName("secondaryText")
        self._progress_label.setWordWrap(True)
        scan_layout.addWidget(self._progress_label)
        splitter.addWidget(scan_panel)

        # --- findings explorer -------------------------------------------------
        findings_panel = Panel(splitter)
        findings_layout = Panel.body_layout(findings_panel)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(theme.SPACING["m"])
        self._filter_input = QLineEdit(findings_panel)
        self._filter_input.setPlaceholderText("search findings (text)")
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.setAccessibleName("Findings text search")
        self._filter_input.textChanged.connect(self._on_findings_filter_changed)
        self._severity_combo = QComboBox(findings_panel)
        self._severity_combo.setAccessibleName("Minimum severity filter")
        self._severity_combo.addItem("severity ≥ any · all", userData=None)
        for severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH,
                         FindingSeverity.MEDIUM, FindingSeverity.LOW,
                         FindingSeverity.INFO):
            label = _SEVERITY_LABEL[severity]
            self._severity_combo.addItem(f"severity ≥ {label}",
                                         userData=severity)
        self._severity_combo.currentIndexChanged.connect(
            self._on_findings_filter_changed)
        self._category_combo = QComboBox(findings_panel)
        self._category_combo.setAccessibleName("Category filter")
        self._category_combo.addItem("category: any", userData=None)
        for category in FindingCategory:
            self._category_combo.addItem(
                f"category: {_CATEGORY_LABEL[category]}", userData=category)
        self._category_combo.currentIndexChanged.connect(
            self._on_findings_filter_changed)
        self._provenance_combo = QComboBox(findings_panel)
        self._provenance_combo.setAccessibleName("Evidence confidence filter")
        self._provenance_combo.addItem("evidence: any", userData=None)
        for word in _PROVENANCE_BUCKETS:
            self._provenance_combo.addItem(f"evidence: {word}", userData=word)
        self._provenance_combo.currentIndexChanged.connect(
            self._on_findings_filter_changed)
        self._sort_combo = QComboBox(findings_panel)
        self._sort_combo.setAccessibleName("Findings sort order")
        for key, label in (
            ("severity", "sort: severity"), ("category", "sort: category"),
            ("package", "sort: package"), ("title", "sort: title"),
        ):
            self._sort_combo.addItem(label, userData=key)
        self._sort_combo.currentIndexChanged.connect(
            self._on_sort_changed)
        filter_row.addWidget(self._filter_input, 1)
        filter_row.addWidget(self._severity_combo)
        filter_row.addWidget(self._category_combo)
        filter_row.addWidget(self._provenance_combo)
        filter_row.addWidget(self._sort_combo)
        findings_layout.addLayout(filter_row)

        self._findings_status_label = QLabel("", findings_panel)
        self._findings_status_label.setObjectName("secondaryText")
        self._findings_status_label.setWordWrap(True)
        findings_layout.addWidget(self._findings_status_label)

        self._findings_model = FindingsTableModel()
        self._findings_table = QTableView(findings_panel)
        self._findings_table.setObjectName("findingsTable")
        self._findings_table.setModel(self._findings_model)
        self._findings_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._findings_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._findings_table.setSortingEnabled(False)  # explicit sort combo
        self._findings_table.horizontalHeader().setStretchLastSection(True)
        self._findings_table.setAccessibleName("Scan findings")
        self._findings_table.selectionModel().currentRowChanged.connect(
            self._on_finding_selected)
        findings_layout.addWidget(self._findings_table, 1)

        page_row = QHBoxLayout()
        page_row.setContentsMargins(0, 0, 0, 0)
        page_row.setSpacing(theme.SPACING["m"])
        self._page_label = QLabel("", findings_panel)
        self._page_label.setObjectName("secondaryText")
        self._prev_button = button("Previous page", variant="secondary",
                                   accessible_name="Previous findings page")
        self._prev_button.clicked.connect(
            lambda: self._change_page(self._findings_page - 1))
        self._next_button = button("Next page", variant="secondary",
                                   accessible_name="Next findings page")
        self._next_button.clicked.connect(
            lambda: self._change_page(self._findings_page + 1))
        page_row.addWidget(self._page_label, 1)
        page_row.addWidget(self._prev_button)
        page_row.addWidget(self._next_button)
        findings_layout.addLayout(page_row)

        self._detail_model = FindingDetailTableModel()
        self._detail_table = QTableView(findings_panel)
        self._detail_table.setObjectName("findingDetailTable")
        self._detail_table.setModel(self._detail_model)
        self._detail_table.horizontalHeader().setStretchLastSection(True)
        self._detail_table.setMinimumHeight(120)
        self._detail_table.setAccessibleName("Finding details")
        findings_layout.addWidget(self._detail_table)

        honesty = QLabel(
            "Finding severity is qualitative evidence-based judgement, not a "
            "measurement. Zero findings means the engine's host-side checks "
            "found nothing to report — the device is not thereby certified "
            "secure, and checks that could not run are not reported as "
            "passed. Evidence excerpts are redacted by the engine boundary.",
            findings_panel)
        honesty.setObjectName("hintText")
        honesty.setWordWrap(True)
        findings_layout.addWidget(honesty)
        splitter.addWidget(findings_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter, 1)

    # ------------------------------------------------------------------ #
    # lifecycle hooks the shell uses
    # ------------------------------------------------------------------ #

    def activate(self) -> None:
        """First activation runs exactly ONE auto-discovery (TUI parity)."""
        if not self._auto_refresh_done and self._devices_state == "idle":
            self._auto_refresh_done = True
            self.refresh_devices()

    def shutdown(self) -> None:
        """Owner-close hook: stop worker threads + disconnect the hub."""
        for signal_name in ("progress", "finding", "terminal"):
            try:
                getattr(self._hub, signal_name).disconnect(
                    getattr(self, f"_on_{signal_name}_event"))
            except RuntimeError:
                pass  # already disconnected or the hub was destroyed
        self._workers.close()

    # ------------------------------------------------------------------ #
    # device discovery (identical honesty contract to the device workspace)
    # ------------------------------------------------------------------ #

    def refresh_devices(self) -> None:
        self._refresh_button.setEnabled(False)
        started = self._workers.run(
            "scan_refresh_devices",
            self._backend.list_devices,
            self._on_devices_done,
            self._on_devices_failed,
        )
        if started:
            self._devices_state = "loading"
        self._render_devices_panel()

    def _on_devices_done(self, rows: tuple) -> None:
        self._apply_devices(tuple(rows))
        self._refresh_button.setEnabled(True)
        self._render_devices_panel()
        self._sync_controls()

    def _on_devices_failed(self, exc: BaseException) -> None:
        if self._devices:
            # Last successful result survives, visibly marked stale.
            self._devices_stale = True
        self._devices_state = "failed"
        self._devices_error = engine_error_text(exc)
        self._refresh_button.setEnabled(True)
        self._render_devices_panel()
        self._sync_controls()

    def _apply_devices(self, rows: tuple[ConnectionInfo, ...]) -> None:
        self._devices = rows
        self._devices_state = "refreshed"
        self._devices_stale = False
        self._devices_error = None
        self._refresh_stamp = _now_stamp()
        self._devices_model.set_rows(rows)
        self._reconcile_selection()

    def _reconcile_selection(self) -> None:
        """Preserve the same serial if still listed; invalidate honestly
        when gone; auto-preselect ONLY the unambiguous single device."""
        selection = self._devices_table.selectionModel()
        if self._selected_serial is not None:
            row = self._devices_model.row_of_serial(self._selected_serial)
            if row is not None:
                self._invalidation_note = None
                selection.setCurrentIndex(
                    self._devices_model.index(row, 0),
                    self._clear_and_select_flags())
                return
            self._invalidate_target(
                f"The scan target {self._selected_serial} is gone after the "
                "last refresh — the selection was invalidated on purpose "
                "(nothing is auto-switched).")
            return
        actionable = [d for d in self._devices if d.state is _ACTIONABLE]
        if len(actionable) == 1:
            row = self._devices_model.row_of_serial(actionable[0].serial)
            if row is not None:
                selection.setCurrentIndex(
                    self._devices_model.index(row, 0),
                    self._clear_and_select_flags())

    @staticmethod
    def _clear_and_select_flags():
        return (QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Current)

    def _on_selection_changed(self, current, _previous) -> None:
        serial = self._devices_model.serial_at(current.row()) \
            if current is not None and current.isValid() else None
        if serial is not None and serial != self._selected_serial:
            self._selected_serial = serial
            self._invalidation_note = None
        self._render_preflight()
        self._sync_controls()

    def _invalidate_target(self, note: str) -> None:
        self._selected_serial = None
        self._invalidation_note = note
        self._target_banner.setText(note)
        self._sync_controls()

    def _selected_row(self) -> Optional[ConnectionInfo]:
        if self._selected_serial is None:
            return None
        for device in self._devices:
            if device.serial == self._selected_serial:
                return device
        return None

    # ------------------------------------------------------------------ #
    # preflight
    # ------------------------------------------------------------------ #

    def _render_preflight(self) -> None:
        """Honest preflight summary: target, scope, prerequisites, limits."""
        device = self._selected_row()
        if device is None:
            target_word = "no device selected — select a row in the device list"
        elif device.state is not _ACTIONABLE:
            target_word = (f"target {device.serial} is {device.state.value} —"
                           " scans need a connected, authorized device")
        else:
            target_word = f"target {device.serial} (state: {device.state.value})"
        package = self._package_input.text().strip()
        mode = "single-app analysis" if package else "full-device scan"
        if self._scan_state in ("running", "validating"):
            mode_word = (f"{mode} — a scan is ACTIVE; starting another one "
                         "is refused")
        else:
            mode_word = f"next scan: {mode}"
        scope_word = (f"system apps {'included' if self._include_system else 'excluded'}"
                      f" · deep scan {'on' if self._deep else 'off'}"
                      + (f" · package {package}" if package else ""))
        self._preflight_label.setText(
            f"{target_word}. {mode_word}. scope: {scope_word}. "
            "The engine alone reports progress and findings; full-device "
            "analysis reads installed apps and their declared permissions "
            "and runs NO destructive operation. A cancellation request is "
            "not a completion: the scan ends only at its terminal outcome.")

    # ------------------------------------------------------------------ #
    # scan lifecycle
    # ------------------------------------------------------------------ #

    def _on_scope_changed(self) -> None:
        self._include_system = self._system_toggle.isChecked()
        self._deep = self._deep_toggle.isChecked()
        self._render_preflight()

    def _on_start_full(self) -> None:
        self._validate_and_start(package=None)

    def _on_start_single(self) -> None:
        package = self._package_input.text().strip()
        if not package:
            self._refuse("type the package name to analyze first "
                         "(single-app scan)")
            return
        try:
            package = validate_package_name(package)
        except Exception as exc:
            self._refuse(
                f"not a valid package name: {getattr(exc, 'message', exc)}")
            return
        self._validate_and_start(package=package)

    def _validate_and_start(self, package: Optional[str]) -> None:
        """Preflight: refuse duplicates, then REVALIDATE the target against
        a fresh discovery (a cached selection is never trusted)."""
        backend = self._backend
        if self._scan_state in ("running", "validating"):
            self._refuse(
                "A scan is already active — cancel it or wait for its "
                "terminal outcome before starting another one.")
            return
        device = self._selected_row()
        if device is None or device.state is not _ACTIONABLE:
            self._refuse(
                "select a connected device first — scans require an "
                "explicitly selected, currently listed device")
            return
        if self._devices_stale:
            self._refuse(
                "the device list is stale (the last refresh failed) — "
                "refresh successfully before targeting a device")
            return
        serial = device.serial
        self._scan_state = "validating"
        self._scan_error = None
        self._render_preflight()
        self._render_scan_state()
        self._sync_controls()

        def work() -> tuple:
            return tuple(backend.list_devices())

        started = self._workers.run(
            "scan_preflight",
            work,
            lambda rows: self._apply_preflight(serial, package, rows),
            lambda exc: self._preflight_failed(serial, engine_error_text(exc)),
        )
        if not started:
            return  # a preflight is pending; the busy controls already say so

    def _apply_preflight(self, serial: str, package: Optional[str],
                         devices: tuple) -> None:
        if self._selected_serial != serial:
            return  # superseded preflight — never act on a stale target
        still = any(d.serial == serial and d.state is _ACTIONABLE
                    for d in devices)
        if not still:
            self._fail_scan(
                f"the selected device {serial} is no longer connected or "
                "authorized — refresh and select an available one (nothing "
                "was scanned, no other device was chosen)")
            return
        self._begin_scan_job(serial, package)

    def _preflight_failed(self, serial: str, message: str) -> None:
        if self._selected_serial != serial:
            return
        self._fail_scan(f"discovery failed before the scan: {message}")

    def _begin_scan_job(self, serial: str, package: Optional[str]) -> None:
        """Submit the scan job after the preflight passed (GUI thread)."""
        if self._selected_serial != serial:
            return
        if self._scan_state == "running":
            return  # a job is already in flight; this preflight is stale
        try:
            handle = self._backend.start_scan_job(
                serial,
                include_system=self._include_system,
                deep=self._deep,
                package=package,
            )
        except Exception as exc:
            self._fail_scan(engine_error_text(exc))
            return
        self._scan_state = "running"
        self._scan_error = None
        self._scan_job_id = handle.id
        self._scan_target_serial = serial
        self._scan_kind_word = "single_app" if package else "full_device"
        self._scan_result_kind = ""
        self._progress_text = ""
        self._streamed = 0
        self._history_failed = None
        self._replace_findings((), "streaming")
        self._render_preflight()
        self._render_scan_state()
        self._render_findings()
        self._sync_controls()

    def _refuse(self, message: str) -> None:
        """Honest refusal before anything started (state stays idle)."""
        self._progress_label.setText(message)

    def _scan_target_word(self) -> str:
        if self._scan_target_serial:
            return f" from the scan of {self._scan_target_serial}"
        return ""

    def _fail_scan(self, message: str) -> None:
        self._scan_state = "failed"
        self._scan_error = message
        self._progress_text = ""
        self._render_preflight()
        self._render_scan_state()
        self._sync_controls()

    def _on_cancel(self) -> None:
        if self._scan_state != "running" or self._scan_target_serial is None:
            return  # control disabled; defensive no-op
        # request ≠ acknowledgement: the CANCELLED terminal event closes it
        shared = self._backend.cancel_scan_job(self._scan_target_serial)
        self._progress_label.setText(
            "Cancellation requested" + (
                "" if shared == 1 else f" ({shared} scan jobs affected)"
            ) + " — the engine stops at its next checkpoint (between apps "
            "/ analysis boundary); the CANCELLED terminal event is the "
            "acknowledgement.")

    # ------------------------------------------------------------------ #
    # status / rendering (GUI thread only)
    # ------------------------------------------------------------------ #

    def _render_scan_state(self) -> None:
        label = self._progress_label
        target = self._scan_target_serial or self._selected_serial or "—"
        if self._scan_state == "validating":
            label.setText("checking that the selected device is still "
                          "connected …")
        elif self._scan_state == "running":
            label.setText(self._progress_text or
                          f"scan started on {target} … (cancel available)")
        elif self._scan_state == "completed":
            mode_word = {
                "bundle": "full-device scan",
                "single_app": "single-app scan",
            }.get(self._scan_result_kind, "scan")
            label.setText(
                f"{mode_word} completed on {target} at {self._terminal_stamp} · "
                + self._findings_totals_word())
        elif self._scan_state == "cancelled":
            label.setText(
                f"scan CANCELLED (requested by you) — findings streamed "
                f"before the stop remain labeled PARTIAL · {target}")
        elif self._scan_state == "failed":
            label.setText(f"scan failed: {self._scan_error}")
        elif self._scan_state == "not-exportable":
            label.setText(
                f"single-app scan completed on {target} at "
                f"{self._terminal_stamp} · findings below · NOT exportable: "
                "the report service contract takes a full-device bundle "
                "(nothing was fabricated to fill the gap)")
        else:
            label.setText("no scan yet for this session")

    def _findings_totals_word(self) -> str:
        if self._findings_status == "from-bundle" or \
                self._scan_result_kind == "bundle":
            return f"{len(self._findings)} finding(s) shown from the completed scan"
        return f"{len(self._findings)} finding(s) streamed"

    def _render_devices_panel(self) -> None:
        banner = self._devices_banner
        chip = self._devices_chip
        stamp = f" at {self._refresh_stamp}" if self._refresh_stamp else ""
        if self._devices_state == "idle":
            chip.set_status("neutral")
            banner.setText("discovery has not run yet — Refresh devices "
                           "runs one probe.")
        elif self._devices_state == "loading":
            chip.set_status("info")
            banner.setText("discovery request running in the background…")
        elif self._devices_state == "refreshed":
            chip.set_status("ok" if self._devices else "neutral")
            banner.setText(f"{len(self._devices)} device(s) reported{stamp}.")
        else:  # failed
            message = self._devices_error or "discovery failed"
            if self._devices:
                chip.set_status("error")
                banner.setText(
                    f"discovery failed: {message} — showing the LAST "
                    f"successful result{stamp}; rows are stale and do NOT "
                    "prove the devices are still connected.")
            else:
                chip.set_status("error")
                banner.setText(f"discovery failed: {message}")

        parts: list[str] = []
        if self._selected_serial is not None:
            device = self._selected_row()
            state = device.state.value if device is not None else "unknown"
            parts.append(f"selected scan target: {self._selected_serial} "
                         f"(state: {state})")
        if self._invalidation_note:
            parts.append(self._invalidation_note)
        self._target_banner.setText(" — ".join(parts))

    # ------------------------------------------------------------------ #
    # findings view model (GUI thread only)
    # ------------------------------------------------------------------ #

    def _on_finding_selected(self, current, _previous) -> None:
        if current is None or not current.isValid():
            return
        finding = self._row_findings.get(current.row())
        if finding is None:
            self._detail_finding = None
        else:
            self._detail_finding = finding
        self._render_detail()

    def _filtered_findings(self) -> list[tuple[Finding, str]]:
        """Honest filtered VIEW over the immutable underlying findings."""
        needle = self._text_filter.strip().lower()
        rows: list[tuple[Finding, str]] = []
        for finding in self._findings:
            if self._severity_min is not None:
                rank = _SEVERITY_RANK.get(finding.severity)
                if rank is None or rank > _SEVERITY_RANK[self._severity_min]:
                    continue
            if self._category is not None and finding.kind != self._category:
                continue
            if self._provenance is not None:
                if self._provenance == "no evidence":
                    if finding.evidence:
                        continue
                else:
                    wanted = _PROVENANCE_SET[self._provenance]
                    if not any(ev.kind in wanted for ev in finding.evidence):
                        continue
            if needle:
                try:
                    hay = " ".join((
                        _honest(finding.title, "").lower(),
                        _honest(finding.detail, "").lower(),
                        _honest(finding.kind.value, "").lower(),
                        _package_of(finding).lower(),
                    ))
                except Exception:
                    continue
                if needle not in hay:
                    continue
            rows.append((finding, _package_of(finding)))
        return self._sorted(rows)

    def _sorted(self, rows: list[tuple[Finding, str]]) -> list[tuple[Finding, str]]:
        key = self._sort_key

        def sort_key(pair: tuple[Finding, str]):
            finding, package = pair
            severity = getattr(finding, "severity", None)
            rank = _SEVERITY_RANK.get(severity, 99) \
                if isinstance(severity, FindingSeverity) else 99
            if key == "severity":
                return (rank, finding.kind.value, package.lower(), finding.id)
            if key == "category":
                return (finding.kind.value, rank, package.lower(), finding.id)
            if key == "package":
                return (package.lower(), rank, finding.kind.value, finding.id)
            return (finding.title.lower(), rank, package.lower(), finding.id)

        return sorted(rows, key=sort_key)

    def _page_bounds(self, total: int) -> tuple[int, int]:
        last_page = max(0, -(-total // PAGE_SIZE) - 1)
        page = min(self._findings_page, last_page)
        return page, last_page

    def _change_page(self, page: int) -> None:
        total = len(self._filtered_findings())
        _current, last_page = self._page_bounds(total)
        self._findings_page = max(0, min(page, last_page))
        self._render_findings()

    def visible_findings(self) -> tuple[tuple[Finding, str], ...]:
        total = len(self._filtered_findings())
        page, _last = self._page_bounds(total)
        start = page * PAGE_SIZE
        return tuple(self._filtered_findings()[start:start + PAGE_SIZE])

    def _on_findings_filter_changed(self, *_args: Any) -> None:
        self._text_filter = self._filter_input.text()
        self._severity_min = self._severity_combo.currentData()
        self._category = self._category_combo.currentData()
        self._provenance = self._provenance_combo.currentData()
        self._findings_page = 0
        self._render_findings()

    def _on_sort_changed(self, *_args: Any) -> None:
        self._sort_key = self._sort_combo.currentData() or "severity"
        self._render_findings()

    def _replace_findings(self, findings: Sequence[Finding],
                          status: str) -> None:
        self._findings = tuple(findings)
        self._findings_status = status
        self._findings_page = 0
        self._detail_finding = None
        self._row_findings = {}
        self._render_findings()

    def _render_findings(self) -> None:
        rows = self.visible_findings()
        self._row_findings = {}
        offset = self._findings_page * PAGE_SIZE
        for index, (finding, _package) in enumerate(rows):
            self._row_findings[offset + index] = finding
        self._findings_model.set_rows(tuple(f for f, _p in rows))
        # keep the detail table in sync with pagination/filter changes —
        # a detail row that left the current view is honestly cleared
        if self._detail_finding is not None and \
                self._detail_finding not in self._row_findings.values():
            self._detail_finding = None
            self._render_detail()

        total = len(self._findings)
        shown = len(self._filtered_findings())
        page, last_page = self._page_bounds(shown)
        if shown:
            self._page_label.setText(
                f"page {page + 1}/{last_page + 1} — {PAGE_SIZE}/page — "
                f"{shown} of {total} finding(s)")
        else:
            self._page_label.setText("no findings match")
        self._prev_button.setEnabled(page > 0)
        self._next_button.setEnabled(page < last_page)

        header = self._findings_status_label
        header.setWordWrap(True)
        self._findings_header_word(header, self._scan_target_word())

    def _findings_header_word(self, header: QLabel, target_word: str) -> None:
        status = self._findings_status
        text = {
            "none":
                "no scan has produced findings yet — findings appear here "
                "as the engine reports them",
            "streaming":
                f"scan in progress — {self._streamed} finding(s) streamed "
                "so far (engine events only)",
            "partial-stream":
                f"PARTIAL result{target_word} — findings streamed before "
                "the engine stopped; the scan did not complete",
            "from-bundle":
                f"complete scan result{target_word} — as reported by the "
                "engine",
            "complete":
                f"single-app result{target_word} — as reported by the "
                "engine (not eligible for report export)",
        }.get(status, status)
        payload = text
        header.setText(payload)
        severity_counts = self._severity_counts_word()
        if severity_counts:
            header.setText(f"{payload} · {severity_counts}")

    def _severity_counts_word(self) -> str:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for finding in self._findings:
            word = _SEVERITY_LABEL.get(finding.severity)
            if word in counts:
                counts[word] += 1
        total = sum(counts.values())
        if total == 0:
            return ""
        return (f"critical {counts['critical']} · high {counts['high']} · "
                f"medium {counts['medium']} · low {counts['low']} · "
                f"info {counts['info']}")

    def _render_detail(self) -> None:
        self._detail_model.set_finding(self._detail_finding)

    # ------------------------------------------------------------------ #
    # verify/skip records
    # ------------------------------------------------------------------ #

    def _sync_controls(self) -> None:
        """Enable/disable controls honestly (target-dependent)."""
        reason: Optional[str] = None
        device = self._selected_row()
        if device is None:
            reason = ("no device selected — select a row in the device list"
                      if self._devices else
                      "no devices known yet — refresh first")
        elif device.state is not _ACTIONABLE:
            reason = (f"selected device is {device.state.value}; scans need "
                      "a connected, authorized device")
        elif self._devices_stale:
            reason = ("last refresh FAILED: the device list is stale — "
                      "refresh successfully before scanning")
        busy = self._scan_state in ("running", "validating")
        self._scan_button.setEnabled(reason is None and not busy)
        self._scan_one_button.setEnabled(
            reason is None and not busy and
            bool(self._package_input.text().strip()))
        self._cancel_button.setVisible(self._scan_state == "running")
        self._cancel_button.setEnabled(self._scan_state == "running")
        tips = (
            (self._scan_button, "Requires an explicitly selected, currently "
                                "connected device."),
            (self._scan_one_button, "Requires an explicitly selected, "
                                    "currently connected device."),
        )
        for widget, tip in tips:
            widget.setToolTip(reason or tip)

    # ------------------------------------------------------------------ #
    # job-event delivery (shared shell hub; worker thread → queued slot)
    # ------------------------------------------------------------------ #

    def _on_progress_event(self, event: Any) -> None:
        if not isinstance(event, JobProgressEvent):
            return
        if event.job_id != self._scan_job_id:
            return
        total = event.total if event.total is not None else "…"
        context = event.context or ""
        self._progress_text = (
            f"running · {event.current}/{total} {event.unit}"
            + (f" · current: {context}" if context else "")
            + f" · findings so far: {self._streamed}")
        self._render_scan_state()

    def _on_finding_event(self, event: Any) -> None:
        if not isinstance(event, JobFindingEvent):
            return
        if event.job_id != self._scan_job_id:
            return
        if event.finding is None:
            return  # malformed stream row — never fabricated into a finding
        self._findings = self._findings + (event.finding,)
        self._streamed += 1
        self._findings_status = "partial-stream" \
            if self._scan_state != "running" else "streaming"
        self._render_findings()
        if self._scan_state == "running":
            self._render_scan_state()

    def _on_terminal_event(self, event: Any) -> None:
        if not isinstance(event, JobTerminalEvent):
            return
        if event.kind not in (JobKind.FULL_DEVICE_SCAN, JobKind.SINGLE_APP_SCAN):
            return
        # Identity is the TRACKED JOB ID (JobTerminalEvent has no serial).
        if event.job_id != self._scan_job_id:
            return  # late event from a superseded job — never touch state
        self._scan_job_id = None
        self._terminal_stamp = _now_stamp()
        self._scan_target_serial = self._scan_target_serial
        if event.outcome is JobState.SUCCEEDED:
            result = event.result
            if isinstance(result, ScanResultBundle):
                self._apply_bundle(result)
            elif isinstance(result, AppScanResult):
                self._apply_single_app(result)
            else:
                self._apply_unexpected_result(result)
            self._render_scan_state()
            self._render_findings()
            self._sync_controls()
            return
        if event.outcome is JobState.CANCELLED:
            self._scan_state = "cancelled"
            self._findings_status = "partial-stream" \
                if self._findings else "none"
            # the honest terminal word lands in the reports memory too
            # (a cancelled scan is never export material there)
            self._backend.remember_scan(None, "cancelled",
                                        self._scan_target_serial)
            self._record_history("cancelled", None, self._streamed)
        else:  # FAILED (conservative default in the engine is FAILED)
            self._scan_state = "failed"
            self._scan_error = engine_error_text(event.error) \
                if event.error is not None else (
                "the scan job failed (no detail provided)")
            self._findings_status = "partial-stream" \
                if self._findings else "none"
            self._backend.remember_scan(None, "failed",
                                        self._scan_target_serial)
            self._record_history("failed", None, self._streamed)
        self._render_scan_state()
        self._render_findings()
        self._sync_controls()

    def _apply_bundle(self, bundle: ScanResultBundle) -> None:
        """Terminal success for a full-device scan: the engine's own bundle
        is authoritative; findings come from it only."""
        findings: list[Finding] = []
        for result in bundle.apps:
            findings.extend(result.findings)
        self._scan_state = "completed"
        self._scan_result_kind = "bundle"
        self._exportable = True
        self._replace_findings(findings, "from-bundle")
        self._backend.remember_scan(bundle, "completed",
                                    self._scan_target_serial)
        self._record_history("completed", bundle, None)

    def _apply_single_app(self, result: Any) -> None:
        """Single-app terminal result (typed ``AppScanResult``).

        Recorded honestly as a completed scan, but NOT exportable: the
        legacy report schema needs a ``ScanResultBundle`` the engine did
        not produce for this kind (nothing is fabricated)."""
        findings: list[Finding] = list(result.findings)
        self._scan_state = "not-exportable"
        self._scan_result_kind = "single_app"
        self._exportable = False
        self._replace_findings(findings, "complete")
        self._backend.remember_scan(None, "completed",
                                    self._scan_target_serial)
        self._record_history(
            "completed", None, max(len(findings), self._streamed))

    def _apply_unexpected_result(self, result: Any) -> None:
        """An engine contract violation must not crash the UI; state it."""
        self._scan_state = "failed"
        self._scan_error = (
            "the scan finished but the engine returned an unexpected result "
            f"shape ({type(result).__name__}) — nothing is shown as findings")
        self._findings_status = "none" if not self._findings \
            else "partial-stream"
        self._render_scan_state()
        self._sync_controls()

    # ------------------------------------------------------------------ #
    # T-08 history (counters only, written on a worker thread)
    # ------------------------------------------------------------------ #

    def _record_history(self, status: str, bundle: Optional[ScanResultBundle],
                        streamed: Optional[int]) -> None:
        """Queue one honest counters entry and pump the write worker.

        Writes are serialized through the ``scan_history_write`` slot; a
        write that is still in flight does NOT silently swallow the next
        entry — completion pumps the queue again. A failed write is
        dropped loudly (never a silently missing entry claimed recorded).
        """
        try:
            entry = self._history_entry(status, bundle, streamed)
        except Exception:
            return  # building the entry must never take the UI down
        self._history_queue.append(entry)
        self._pump_history()

    def _pump_history(self) -> None:
        if not self._history_queue:
            return
        entry = self._history_queue[0]
        backend = self._backend

        def work() -> None:
            backend.history_entry(entry)

        started = self._workers.run(
            "scan_history_write", work, self._on_history_written,
            self._on_history_write_failed)
        if not started:
            return  # the running write pumps the queue when it completes

    def _on_history_written(self, _result: Any) -> None:
        if self._history_queue:
            self._history_queue.pop(0)
        self._history_failed = None
        self._pump_history()

    def _on_history_write_failed(self, exc: BaseException) -> None:
        if self._history_queue:
            self._history_queue.pop(0)
        self._history_failed = (
            f"the local scan history could not be written "
            f"({engine_error_text(exc)}) — the scan outcome in the panels "
            "above is real and unaffected")
        self._render_scan_state()

    def _history_entry(self, status: str, bundle: Optional[ScanResultBundle],
                       streamed: Optional[int]) -> HistoryEntry:
        scan_id = uuid.uuid4().hex
        total_apps = 0
        if bundle is not None:
            try:
                scan_id = bundle.summary.run.request.id
            except Exception:
                pass
            total_apps = bundle.summary.total_apps
        severity_counts = {key: 0 for key in
                           ("critical", "high", "medium", "low", "info")}
        for finding in self._findings:
            word = _SEVERITY_LABEL.get(finding.severity)
            if word in severity_counts:
                severity_counts[word] += 1
        return HistoryEntry(
            scan_id=scan_id,
            kind=self._scan_kind_word or "unknown",
            status=status,
            device_serial=self._scan_target_serial,
            total_apps=total_apps,
            findings_total=(
                streamed if (streamed is not None and bundle is None)
                else sum(
                    len(result.findings) for result in
                    (bundle.apps if bundle is not None else ()))),
            severity_counts=severity_counts,
        )
