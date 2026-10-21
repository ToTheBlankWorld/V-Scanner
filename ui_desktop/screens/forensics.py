"""Forensics (Stage 12 desktop parity): case-first evidence extraction.

The Qt counterpart of the TUI forensics cockpit, on the exact same engine
semantics (R-03/R-05/R-07/R-12 through the shared ``ForensicsService``):

* Case-first: an operation is only ever runnable against an open case.
  "New case" runs the engine ``create_case`` op as a FORENSICS_OP job (the
  verified root tri-state is probed once by the service and recorded in
  the manifest); "Open case" reopens a saved manifest through a plain
  background worker. The screen keeps NO parallel truth — everything it
  renders comes from the SAVED manifest the jobs return.
* Extraction ops record per-file sha256 + byte counts (engine R-07);
  FAILED entries are displayed verbatim — never silently skipped.
* WiFi extraction defaults to the service's REDACTED preset (R-12). The
  cleartext variant requires the exact typed acknowledgement
  ("I ACCEPT CLEARTEXT PSK") in its own dialog; only then does the page
  mint a fresh ``OperationConfirmation(reference="wifi_cleartext_psk")``
  which the SERVICE re-validates (R-13 gate stays effective — the page
  never bypasses the service-level check, and cancel/mismatch writes
  nothing).
* Honest absence: missing or unreadable evidence is shown as what the
  engine reported (failed/unavailable with reason) — never as an
  "empty successful extraction".

Honesty boundaries: this is LOCAL, HOST-SIDE evidence extraction on an
explicitly selected device. Nothing is collected automatically, no
background surveillance exists, and no Android-side continuous monitoring
is claimed anywhere.

Threading model: extraction, case reads and subprocess-bound ops run in
the job system or ``WorkerCoordinator`` slots (never the GUI thread);
rendering happens only in queued GUI-thread slots; the tracked job id
(dead events of superseded jobs are ignored) is the only reconciliation
key — terminal events carry no device serial.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from vscanner.core.events import JobKind, JobState, JobTerminalEvent
from vscanner.core.events import OperationConfirmation
from vscanner.core.models import CaseManifest, DeviceState

from .. import theme
from ..backend import DesktopBackend
from ..jobs_bridge_qt import JobEventSignalHub
from ..workers import WorkerCoordinator
from ..widgets import Panel, StatusChip, button
from .devices import DevicesTableModel, engine_error_text

__all__ = ["ForensicsPage", "CleartextConfirmDialog", "ACK_PHRASE"]

ACK_PHRASE = "I ACCEPT CLEARTEXT PSK"
"""The exact typed acknowledgement the service contract requires."""

_ACTIONABLE = DeviceState.DEVICE

_EXTRACTION_OPS = (
    ("system_logs", "System logs", "Capture logcat text into the case"),
    ("installed_packages", "Installed packages",
     "Capture the pm package list text into the case"),
    ("running_processes", "Running processes",
     "Capture the ps process list text into the case"),
    ("wifi_redacted", "WiFi networks (redacted)",
     "Write wifi_networks.txt with psk/password redacted (default preset)"),
)


def _plain(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ")
    return " ".join(text.split())[:160]


# ===========================================================================
# table models
# ===========================================================================

class FilesTableModel(QAbstractTableModel):
    """One row per ``FileRecord`` from the saved case manifest — sha256
    (12-char prefix), byte counts and kinds exactly as recorded; FAILED
    entries show verbatim, never skipped."""

    _HEADERS = ("Source path", "In case", "sha256 (12)", "Bytes", "Kind")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[tuple[str, str, str, str, str], ...] = ()
        self._note = "no case open"

    def set_manifest(self, manifest: Optional[CaseManifest],
                     note: str = "no case open") -> None:
        self.beginResetModel()
        if manifest is None:
            self._rows = ()
            self._note = note
        else:
            if manifest.files:
                self._rows = tuple(
                    (_plain(record.source_path),
                     _plain(record.case_relative_path),
                     record.sha256[:12],
                     str(record.byte_count), record.kind)
                    for record in manifest.files)
                self._note = "—"
            else:
                self._rows = ()
                self._note = "no files extracted yet"

    def rowCount(
            self, parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        if parent.isValid():
            return 0
        return len(self._rows) if self._rows else 1

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
        if not self._rows:
            if role == Qt.ItemDataRole.DisplayRole:
                return ("—", self._note, "—", "—", "—")[index.column()]
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row[index.column()]
        return None

    @property
    def rows(self) -> tuple[tuple[str, str, str, str, str], ...]:
        return self._rows


class ExtractionsTableModel(QAbstractTableModel):
    """Operation / recorded-status pairs straight from the manifest."""

    _HEADERS = ("Operation", "Recorded status")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[tuple[str, str], ...] = ()
        self._note = "no operations recorded yet"

    def set_manifest(self, manifest: Optional[CaseManifest]) -> None:
        self.beginResetModel()
        if manifest is None or not manifest.extractions:
            self._rows = ()
            self._note = ("no operations recorded yet"
                          if manifest is None else
                          "no operations recorded in this case yet")
        else:
            self._rows = tuple(
                (_plain(operation), _plain(status))
                for operation, status in manifest.extractions)
            self._note = "—"
        self.endResetModel()

    def rowCount(
            self, parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        if parent.isValid():
            return 0
        return len(self._rows) if self._rows else 1

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
        if not self._rows:
            if role == Qt.ItemDataRole.DisplayRole:
                return ("—", self._note)[index.column()]
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row[index.column()]
        return None

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        return self._rows


# ===========================================================================
# dialogs
# ===========================================================================

class CleartextConfirmDialog(QDialog):
    """Second confirm for unredacted WiFi PSK storage (R-12).

    The dialog is PURELY input machinery: the Proceed action stays
    disabled until the exact phrase is typed, and any cancel/reject/
    close outcome simply reports ``None`` — NOTHING is written and no
    confirmation token is minted for anything but the exact phrase."""

    def __init__(self, case_id: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("WiFi clear-text confirmation")
        self.setModal(True)
        self.setAccessibleName("WiFi clear-text confirmation")
        self.setFixedWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACING["s"])

        warning = QLabel(
            "This writes WiFi PSKs in CLEARTEXT to "
            f"'{case_id}/wifi_networks_cleartext.txt' on disk (secret "
            "material, unprotected). The redacted default already exists "
            "and stays untouched.", self)
        warning.setObjectName("bodyText")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        prompt = QLabel(
            f"Type {ACK_PHRASE} exactly (uppercase, with spaces) to "
            "proceed — anything else cancels:", self)
        prompt.setObjectName("secondaryText")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        self._input = QLineEdit(self)
        self._input.setPlaceholderText(ACK_PHRASE)
        self._input.setAccessibleName("Clear-text acknowledgement phrase")
        layout.addWidget(self._input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        proceed = buttons.button(QDialogButtonBox.StandardButton.Ok)
        proceed.setText("Proceed")
        proceed.setEnabled(False)
        # Stage 13: explicit accessible names (see AdminConfirmDialog).
        proceed.setAccessibleName("Write clear-text PSKs proceed")
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setAccessibleName("Cancel — writes nothing")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._buttons = buttons
        self._input.textChanged.connect(self._sync_proceed)
        layout.addWidget(buttons)

    def _sync_proceed(self, text: str) -> None:
        proceed = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        # The service gate stays effective; the UI check mirrors it so an
        # acknowledged token can only be minted FOR the exact phrase.
        proceed.setEnabled(text.strip() == ACK_PHRASE)

    def typed_phrase(self) -> str:
        return self._input.text().strip()


# ===========================================================================
# the page
# ===========================================================================

class ForensicsPage(QWidget):
    """One cached per-section forensics page (never reconstructed)."""

    def __init__(self, backend: DesktopBackend, hub: JobEventSignalHub,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._hub = hub
        self._workers = WorkerCoordinator(self)

        self.setAccessibleName("Forensics")

        # discovery state (same honest pattern as the device workspace)
        self._devices: tuple = ()
        self._devices_state = "idle"  # idle | loading | refreshed | failed
        self._devices_error: Optional[str] = None
        self._refresh_stamp: Optional[str] = None
        self._auto_refresh_done = False
        self._selected_serial: Optional[str] = None

        # case + op state
        self._manifest: Optional[CaseManifest] = None
        self._job_id: Optional[str] = None
        self._job_op: Optional[str] = None
        self._job_state = "idle"     # idle | running | done | failed | cancelled
        self._job_note: Optional[str] = None
        self._load_serial: Optional[str] = None

        self._building = False
        self._build_ui()
        self._render_all()
        # Subscribe ONCE — the shell caches one widget per section, so
        # repeated navigation cannot create duplicate subscriptions.
        self._hub.terminal.connect(self._on_terminal_event)

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACING["s"])

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

        self._scope_banner = QLabel(
            "LOCAL, host-side evidence extraction on an explicitly "
            "selected device — nothing is collected automatically and no "
            "Android-side background monitoring exists. WiFi exports are "
            "REDACTED by default; the clear-text variant needs the exact "
            "typed acknowledgement and is service-gated.")
        self._scope_banner.setObjectName("hintText")
        self._scope_banner.setWordWrap(True)
        outer.addWidget(self._scope_banner)

        self._target_banner = QLabel("", self)
        self._target_banner.setObjectName("bodyText")
        self._target_banner.setWordWrap(True)
        outer.addWidget(self._target_banner)

        splitter = QSplitter(self)
        splitter.setOrientation(Qt.Orientation.Vertical)

        # --- device list panel ---------------------------------------------
        devices_panel = Panel(splitter)
        devices_layout = Panel.body_layout(devices_panel)
        self._devices_model = DevicesTableModel()
        self._devices_table = QTableView(devices_panel)
        self._devices_table.setObjectName("forensicsDevicesTable")
        self._devices_table.setModel(self._devices_model)
        self._devices_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._devices_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._devices_table.horizontalHeader().setStretchLastSection(True)
        self._devices_table.setMinimumHeight(100)
        self._devices_table.setAccessibleName("Discovered devices")
        self._devices_table.selectionModel().currentRowChanged.connect(
            self._on_selection_changed)
        devices_layout.addWidget(self._devices_table)
        splitter.addWidget(devices_panel)

        # --- case + operations + results panel -------------------------------
        work_panel = Panel(splitter)
        work_layout = Panel.body_layout(work_panel)

        # case controls
        case_row = QHBoxLayout()
        case_row.setContentsMargins(0, 0, 0, 0)
        case_row.setSpacing(theme.SPACING["m"])
        self._case_name_input = QLineEdit(work_panel)
        self._case_name_input.setPlaceholderText(
            "new case name (letters, digits, ., -, _)")
        self._case_name_input.setAccessibleName("New case name")
        self._create_case_button = button(
            "Create case", variant="primary",
            tooltip="Run the engine create_case op as a FORENSICS_OP job "
                    "(probes root once, records the manifest) for the "
                    "selected device; an existing case name is refused, "
                    "never overwritten",
            accessible_name="Create case")
        self._create_case_button.clicked.connect(self._on_create_case)
        self._case_id_input = QLineEdit(work_panel)
        self._case_id_input.setPlaceholderText("existing case id to open")
        self._case_id_input.setAccessibleName("Open case id")
        self._open_case_button = button(
            "Open case", variant="secondary",
            tooltip="Reopen a saved case manifest by id (background "
                    "worker; the saved manifest is the only truth)",
            accessible_name="Open case by id")
        self._open_case_button.clicked.connect(self._on_open_case)
        # typing updates control enablement honestly (the open button's
        # gate includes non-empty case id text)
        self._case_id_input.textChanged.connect(
            lambda _text: self._sync_controls())
        case_row.addWidget(self._case_name_input, 1)
        case_row.addWidget(self._create_case_button)
        case_row.addWidget(self._case_id_input, 1)
        case_row.addWidget(self._open_case_button)
        work_layout.addLayout(case_row)

        self._case_banner = QLabel("", self)
        self._case_banner.setObjectName("secondaryText")
        self._case_banner.setWordWrap(True)
        work_layout.addWidget(self._case_banner)

        # operations row 1: extract app data
        extract_row = QHBoxLayout()
        extract_row.setContentsMargins(0, 0, 0, 0)
        extract_row.setSpacing(theme.SPACING["m"])
        self._package_input = QLineEdit(work_panel)
        self._package_input.setPlaceholderText("package name to extract")
        self._package_input.setAccessibleName("Extraction source package")
        self._extract_button = button(
            "Extract app data", variant="primary",
            tooltip="Byte-exact extraction of the package's databases, "
                    "shared_prefs and files into the open case "
                    "(sha256-recorded; failed sources are recorded, "
                    "never silently skipped)",
            accessible_name="Extract app data")
        self._extract_button.clicked.connect(self._on_extract_app_data)
        # typing updates control enablement honestly (the extract
        # button's gate includes non-empty package text)
        self._package_input.textChanged.connect(
            lambda _text: self._sync_controls())
        extract_row.addWidget(self._package_input, 1)
        extract_row.addWidget(self._extract_button)
        work_layout.addLayout(extract_row)

        # operations row 2: text + wifi + report
        ops_row = QHBoxLayout()
        ops_row.setContentsMargins(0, 0, 0, 0)
        ops_row.setSpacing(theme.SPACING["m"])
        self._text_op_buttons: dict[str, QPushButton] = {}
        for op, label, tooltip in _EXTRACTION_OPS:
            op_button = button(label, variant="secondary", tooltip=tooltip,
                               accessible_name=label)
            op_button.clicked.connect(
                lambda _=False, op=op: self._on_text_op(op))
            self._text_op_buttons[op] = op_button
            ops_row.addWidget(op_button)
        self._cleartext_button = button(
            "WiFi CLEARTEXT…", variant="secondary",
            tooltip="Unredacted WiFi PSK capture — requires the exact "
                    "typed acknowledgement; service-gated (R-13)",
            accessible_name="WiFi clear-text extraction")
        self._cleartext_button.clicked.connect(self._on_wifi_cleartext)
        ops_row.addWidget(self._cleartext_button)
        self._report_button = button(
            "Generate report.json", variant="secondary",
            tooltip="Write the case's legacy report.json "
                    "(field names preserved)",
            accessible_name="Generate case report")
        self._report_button.clicked.connect(self._on_report_op)
        ops_row.addWidget(self._report_button)
        work_layout.addLayout(ops_row)

        # job banner
        self._job_banner = QLabel("", self)
        self._job_banner.setObjectName("secondaryText")
        self._job_banner.setWordWrap(True)
        work_layout.addWidget(self._job_banner)

        # results: files
        self._files_model = FilesTableModel()
        self._files_table = QTableView(work_panel)
        self._files_table.setObjectName("forensicFilesTable")
        self._files_table.setModel(self._files_model)
        self._files_table.horizontalHeader().setStretchLastSection(True)
        self._files_table.setMinimumHeight(110)
        self._files_table.setAccessibleName("Extracted files")
        work_layout.addWidget(self._files_table, 1)

        # results: extractions
        self._extractions_model = ExtractionsTableModel()
        self._extractions_table = QTableView(work_panel)
        self._extractions_table.setObjectName("forensicOpsTable")
        self._extractions_table.setModel(self._extractions_model)
        self._extractions_table.horizontalHeader().setStretchLastSection(True)
        self._extractions_table.setMinimumHeight(90)
        self._extractions_table.setAccessibleName("Recorded operations")
        work_layout.addWidget(self._extractions_table, 1)

        splitter.addWidget(work_panel)
        outer.addWidget(splitter, 1)

    # ------------------------------------------------------------------ #
    # lifecycle hooks the shell uses
    # ------------------------------------------------------------------ #

    def activate(self) -> None:
        """First activation runs exactly ONE auto-discovery."""
        if not self._auto_refresh_done and self._devices_state == "idle":
            self._auto_refresh_done = True
            self.refresh_devices()

    def shutdown(self) -> None:
        """Owner-close hook: disconnect the hub + stop worker threads."""
        try:
            self._hub.terminal.disconnect(self._on_terminal_event)
        except RuntimeError:
            pass  # already disconnected or the hub was destroyed
        self._workers.close()

    # ------------------------------------------------------------------ #
    # device discovery (deduped background worker)
    # ------------------------------------------------------------------ #

    def refresh_devices(self) -> None:
        self._refresh_button.setEnabled(False)
        started = self._workers.run(
            "refresh_devices",
            self._backend.list_devices,
            self._on_devices_done,
            self._on_devices_failed,
        )
        if started:
            self._devices_state = "loading"
        self._render_devices_banner()

    def _on_devices_done(self, rows: tuple) -> None:
        self._devices = tuple(rows)
        self._devices_state = "refreshed"
        self._devices_error = None
        self._refresh_stamp = _now_stamp()
        self._devices_model.set_rows(self._devices)
        self._refresh_button.setEnabled(True)
        self._reconcile_selection()
        self._render_devices_banner()
        self._sync_controls()

    def _on_devices_failed(self, exc: BaseException) -> None:
        self._devices_state = "failed"
        self._devices_error = engine_error_text(exc)
        self._refresh_button.setEnabled(True)
        self._render_devices_banner()
        self._sync_controls()

    def _reconcile_selection(self) -> None:
        if not self._devices:
            return
        if self._selected_serial is not None and any(
                d.serial == self._selected_serial and d.state is _ACTIONABLE
                for d in self._devices):
            return  # keep the explicit selection
        actionable = [d for d in self._devices if d.state is _ACTIONABLE]
        if len(actionable) == 1 and self._selected_serial is None:
            self._select_serial(actionable[0].serial)

    # ------------------------------------------------------------------ #
    # selection (explicit; superseded loads are dropped)
    # ------------------------------------------------------------------ #

    def _on_selection_changed(self, current, _previous) -> None:
        serial = self._devices_model.serial_at(current.row()) \
            if current is not None and current.isValid() else None
        if serial is not None:
            self._select_serial(serial)

    def _select_serial(self, serial: str) -> None:
        serial = str(serial)
        if serial == self._selected_serial:
            return
        self._selected_serial = serial
        self._render_all()
        self._sync_controls()

    @property
    def selected_serial(self) -> Optional[str]:
        return self._selected_serial

    def _selected_row(self) -> Optional[Any]:
        if self._selected_serial is None:
            return None
        for device in self._devices:
            if device.serial == self._selected_serial:
                return device
        return None

    def _target_valid(self) -> bool:
        device = self._selected_row()
        return device is not None and device.state is _ACTIONABLE

    def _device_model_hint(self) -> Optional[str]:
        for info in self._devices:
            if info.serial == self._selected_serial:
                model = info.usb_props.get("model")
                return str(model) if model else None
        return None

    # ------------------------------------------------------------------ #
    # case lifecycle
    # ------------------------------------------------------------------ #

    def _on_create_case(self) -> None:
        if not self._target_valid() or self._job_active():
            return  # controls disabled in these states; defensive no-op
        name = self._case_name_input.text().strip()
        if not name:
            self._job_state = "failed"
            self._job_note = \
                "no case name — nothing was created (type a name first)"
            self._render_case_panel()
            return
        self._start_job("create_case", {
            "case_name": name,
            "device_model": self._device_model_hint(),
        })

    def _on_open_case(self) -> None:
        if self._job_active():
            return
        case_id = self._case_id_input.text().strip()
        if not case_id:
            self._job_state = "failed"
            self._job_note = \
                "no case id — nothing was opened (type an id first)"
            self._render_case_panel()
            return
        started = self._workers.run(
            "load_case",
            lambda: self._backend.forensics_load_case(case_id),
            lambda manifest: self._apply_open_case(case_id, manifest, None),
            lambda exc: self._apply_open_case(case_id, None, exc),
        )
        if not started:
            return  # same-slot load pending: it finishes and reports
        self._job_state = "running"
        self._job_note = None
        self._render_case_panel()

    def _apply_open_case(self, case_id: str, manifest: Any,
                         exc: Optional[BaseException]) -> None:
        if self._job_state != "running":
            return  # superseded load attempt — the settled state wins
        if exc is not None:
            self._job_state = "failed"
            self._job_note = \
                f"opening case {case_id} failed: {engine_error_text(exc)}"
        else:
            self._manifest = manifest
            self._job_state = "done"
            self._job_note = f"case {manifest.case_id} loaded"
        self._render_all()
        self._sync_controls()

    def _job_active(self) -> bool:
        return self._job_id is not None or self._job_state == "running"

    # ------------------------------------------------------------------ #
    # extraction operations (FORENSICS_OP jobs)
    # ------------------------------------------------------------------ #

    def _on_extract_app_data(self) -> None:
        if self._manifest is None or not self._target_valid() or \
                self._job_active():
            return
        package = self._package_input.text().strip()
        if not package:
            self._job_state = "failed"
            self._job_note = \
                "no package — nothing was extracted (type a name first)"
            self._render_case_panel()
            return
        self._start_job("extract_app_data", {
            "case_id": self._manifest.case_id,
            "package": package,
        })

    def _on_text_op(self, op: str) -> None:
        if self._manifest is None or not self._target_valid() or \
                self._job_active():
            return
        self._start_job(op, {"case_id": self._manifest.case_id})

    def _run_wifi_op(self, confirmation: Optional[OperationConfirmation]) -> None:
        if self._manifest is None or not self._target_valid() or \
                self._job_active():
            return
        kwargs: dict[str, Any] = {"case_id": self._manifest.case_id}
        if confirmation is not None:
            kwargs["confirmation"] = confirmation
        self._start_job("wifi_cleartext", kwargs)

    def _on_report_op(self) -> None:
        if self._manifest is None or not self._target_valid() or \
                self._job_active():
            return
        self._start_job("report", {"case_id": self._manifest.case_id})

    def _start_job(self, op: str, kwargs: dict) -> None:
        """Start a FORENSICS_OP job for the open case (worker-bound).

        ``serial`` is this page's own explicit selection; the backend
        never touches a registry-global selection state."""
        serial = self._selected_serial
        if serial is None:
            self._job_state = "failed"
            self._job_note = \
                "select a connected device first — nothing was dispatched"
            self._render_case_panel()
            return
        try:
            handle = self._backend.start_forensics_job(serial, op, kwargs)
        except Exception as exc:
            self._job_state = "failed"
            self._job_note = engine_error_text(exc)
            self._render_case_panel()
            self._sync_controls()
            return
        self._job_id = handle.id
        self._job_op = op
        self._job_state = "running"
        self._job_note = None
        self._render_case_panel()
        self._sync_controls()

    # ------------------------------------------------------------------ #
    # WiFi clear-text confirmation (R-12 second confirm + R-13 token)
    # ------------------------------------------------------------------ #

    def _on_wifi_cleartext(self) -> None:
        if self._manifest is None or not self._target_valid() or \
                self._job_active():
            return
        dialog = CleartextConfirmDialog(self._manifest.case_id, self)
        outcome = dialog.exec()
        typed = dialog.typed_phrase() if outcome == \
            int(dialog.DialogCode.Accepted) else None
        # Cancel / dismiss / mismatch → NOTHING is written: no token is
        # minted and no job is submitted (the service default stays the
        # REDACTED extraction regardless of what the input held).
        if typed != ACK_PHRASE:
            return
        confirmation = OperationConfirmation(
            reference="wifi_cleartext_psk",
            confirmed_at=datetime.now(timezone.utc),
        )
        self._run_wifi_op(confirmation)

    # ------------------------------------------------------------------ #
    # job events (dead jobs of other pages are ignored via job id)
    # ------------------------------------------------------------------ #

    def _on_terminal_event(self, event: JobTerminalEvent) -> None:
        if event.kind is not JobKind.FORENSICS_OP:
            return
        if event.job_id != self._job_id:
            return  # late event from a superseded job — never touch state
        self._job_id = None
        op = self._job_op
        self._job_op = None
        if event.outcome is JobState.SUCCEEDED:
            self._job_state = "done"
            result = event.result
            manifest = result[0] if isinstance(result, tuple) else result
            if isinstance(manifest, CaseManifest):
                self._manifest = manifest
                if isinstance(result, tuple) and result[1]:
                    self._job_note = f"report written: {result[1]}"
                elif op == "report":
                    # the plan flattens (manifest, path) tuples; the report
                    # file lives at <case>/report.json — say so honestly
                    self._job_note = (
                        "report finished: report.json written into the "
                        "case folder")
                else:
                    self._job_note = (
                        f"manifest updated ({len(manifest.files)} file(s))")
            else:
                self._job_note = "operation finished"
        elif event.outcome is JobState.CANCELLED:
            self._job_state = "cancelled"
            self._job_note = ("operation cancelled by request — partial "
                              "state is whatever the engine recorded")
        else:
            self._job_state = "failed"
            self._job_note = (
                "operation failed" if event.error is None else
                engine_error_text(event.error))
        self._render_all()
        self._sync_controls()

    # ------------------------------------------------------------------ #
    # rendering + control enablement (GUI thread only)
    # ------------------------------------------------------------------ #

    def _render_all(self) -> None:
        self._case_banner.setText(self._case_text())
        self._job_banner.setText(self._job_text())
        self._files_model.set_manifest(self._manifest)
        self._extractions_model.set_manifest(self._manifest)
        self._render_devices_banner()
        self._target_banner.setText(self._target_text())

    def _render_case_panel(self) -> None:
        self._case_banner.setText(self._case_text())
        self._job_banner.setText(self._job_text())

    def _case_text(self) -> str:
        manifest = self._manifest
        if manifest is None:
            return ("no case open — Create case runs the engine create_case "
                    "op for the selected device (root is probed once, "
                    "tri-state recorded); Open case reopens a saved one")
        kind = "CONFIRMED rooted" if manifest.root_status == "rooted" \
            else f"root: {manifest.root_status} (tri-state)"
        return (f"case {manifest.case_id} · created {manifest.created_at} · "
                f"{kind} · redaction preset: {manifest.redaction_preset} · "
                f"{len(manifest.files)} file(s)")

    def _job_text(self) -> str:
        if self._job_state == "running":
            return "operation running on the engine worker thread…"
        if self._job_state == "failed":
            return (f"operation FAILED: {self._job_note} — recorded, "
                    "never silently skipped")
        if self._job_state == "cancelled":
            return f"operation cancelled — {self._job_note}"
        if self._job_state == "done":
            return self._job_note or "operation finished"
        return "idle — open or create a case to enable the operations"

    def _render_devices_banner(self) -> None:
        chip, banner = self._devices_chip, self._devices_banner
        stamp = f" at {self._refresh_stamp}" if self._refresh_stamp else ""
        if self._devices_state == "idle":
            chip.set_status("neutral")
            banner.setText(
                "discovery has not run yet — nothing probed while idle; "
                "Refresh devices runs one probe.")
        elif self._devices_state == "loading":
            chip.set_status("info")
            banner.setText("discovery request running in the background…")
        elif self._devices_state == "refreshed":
            chip.set_status("ok" if self._devices else "neutral")
            banner.setText(f"{len(self._devices)} device(s) reported{stamp}.")
        else:
            chip.set_status("error")
            message = self._devices_error or "discovery failed"
            banner.setText(f"discovery failed: {message}")

    def _target_text(self) -> str:
        device = self._selected_row()
        if self._selected_serial is None:
            return ("no device selected — every engine op, including "
                    "create_case (which probes root), runs against an "
                    "explicitly selected connected device")
        state = device.state.value if device is not None else "unknown"
        return f"selected target: {self._selected_serial} (state: {state})"

    def _sync_controls(self) -> None:
        """Enable target/case/job-dependent controls honestly."""
        reason: Optional[str] = None
        device = self._selected_row()
        if device is None:
            reason = ("no device selected — select one in the device list"
                      if self._devices else
                      "no devices discovered yet — refresh first")
        elif device.state is not _ACTIONABLE:
            reason = (f"selected device is {device.state.value}; extraction "
                      "needs a connected, authorized device")
        gate = reason or (None if self._manifest is not None else
                          "open or create a case first")
        if self._job_active():
            gate = "an operation is already running — one at a time"

        for op_button in self._text_op_buttons.values():
            op_button.setEnabled(gate is None)
            if gate is not None:
                op_button.setToolTip(gate)
        self._extract_button.setEnabled(
            gate is None and bool(self._package_input.text().strip()))
        self._cleartext_button.setEnabled(gate is None)
        self._report_button.setEnabled(gate is None)
        self._create_case_button.setEnabled(reason is None and
                                           not self._job_active())
        self._open_case_button.setEnabled(
            reason is None and not self._job_active() and
            bool(self._case_id_input.text().strip()))


def _now_stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")
