"""Device workspace (Stage 10): discovery, selection, details, inventory.

Real Android device management in the desktop shell — the Qt counterpart
of the Stage 06/08 TUI workspace, built on the exact same service contracts
and behaviors:

* Discovery is on-demand: opening the page runs EXACTLY ONE auto-refresh
  (``adb devices`` in a background worker, deduped); repeated activations
  do not re-probe, only the explicit Refresh control does. Startup never
  blocks on it (the worker delivers through a queued connection).
* Only fields the typed models actually provide are shown (serial,
  connection state, transport, model reported by usb_props). Offline and
  unauthorized devices render exactly as reported — never reinterpreted.
* Selection is explicit, stale-safe and ambiguity-safe: a single
  discovered device may be preselected only when unambiguous (same rule
  as the TUI); with several devices NOTHING is auto-selected. Refresh
  preserves the selection while the same serial remains; a disappeared
  selected device invalidates the selection with a truthful explanation —
  the target is never silently switched to another device.
* Details come from the shared device-info + root-status services through
  the backend (full profile on explicit action). Root status preserves
  the honest R-05 tri-state (ROOTED / NOT_ROOTED / UNKNOWN): a transport
  error never becomes a root verdict.
* Administration (Stage 12, R-13): the engine-supported device-side
  operations (launch / force-stop / uninstall) dispatch through an
  operation-specific double gate — the exact package is re-typed in the
  dialog, the confirmation token is only minted after it, and the
  target device is freshly revalidated immediately before the ADMIN_OP
  job reaches the service's own OperationConfirmation gate. Cancel
  dispatches nothing; duplicates are refused; results distinguish the
  accepted dispatch from the device's reported return code.
* The app inventory browser uses the SAME Stage 04 job contracts as the
  TUI (cancellable ``APP_LISTING`` job through ``app_listing_rows_plan``,
  100-per-page pagination, filtering that never mutates the underlying
  list) and honest provenance: listing rows carry derived HEURISTIC
  labels badged "inferred (derived)" — never "verified".
* Last-good results survive a failed refresh but are visibly marked
  stale; stale data does not prove a device is still connected.
* Everything blocking runs outside the GUI thread through the backend;
  job events arrive via the shell's ``QtJobEventBridge`` hub (queued to
  GUI-thread slots). Job events from a superseded target or a finished
  screen are ignored — never rendered against a newer selection.

Threading model: this file contains ZERO subprocess and ZERO ADB imports.
All engine calls are methods on :class:`~ui_desktop.backend.DesktopBackend`
invoked inside ``ui_desktop.workers.WorkerCoordinator`` slots (or the job
system). No widget is touched from a worker thread.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from PySide6.QtCore import (
    QAbstractTableModel,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from vscanner.core.errors import VScannerError
from vscanner.core.events import (
    JobKind,
    JobState,
    JobTerminalEvent,
    OperationConfirmation,
)
from vscanner.core.models import (
    AppInfo,
    AppLabelSource,
    ConnectionInfo,
    DeviceProfile,
    DeviceState,
    OperationResult,
)

from .. import theme
from ..backend import DesktopBackend
from ..jobs_bridge_qt import JobEventSignalHub
from ..workers import WorkerCoordinator
from ..widgets import Panel, StatusChip, button

__all__ = ["DeviceWorkspacePage", "PAGE_SIZE"]

PAGE_SIZE = 100
"""Inventory page size — the documented TUI contract (Stage 06)."""


def engine_error_text(exc: BaseException) -> str:
    """Translate an engine exception into concise, truthful UI text.

    Never renders raw tracebacks; ``VScannerError.message`` is already
    redaction-applied by the engine boundary. Unexpected exceptions get an
    honest generic line (type + message), nothing more.
    """
    if isinstance(exc, VScannerError):
        return exc.message
    return f"{type(exc).__name__}: {exc}"


# ===========================================================================
# Qt table models (model/view surfaces — never hundreds of row widgets)
# ===========================================================================

class DevicesTableModel(QAbstractTableModel):
    """One row per discovered device — Serial / State / Transport / Model.

    Data comes exclusively from typed ``ConnectionInfo`` rows; unknown
    metadata renders as "—", never invented. Offline / unauthorized /
    recovery states are shown verbatim (honest ™ — the raw adb token is
    still visible through the tooltip).
    """

    _HEADERS = ("Serial", "State", "Transport", "Model")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[ConnectionInfo, ...] = ()

    def set_rows(self, rows: Sequence[ConnectionInfo]) -> None:
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
        row = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return row.serial
            if column == 1:
                return row.state.value
            if column == 2:
                return row.transport.value
            if column == 3:
                return row.usb_props.get("model") or "—"
        elif role == Qt.ItemDataRole.ToolTipRole:
            raw = row.usb_props.get("raw_state")
            if raw:
                return f"raw adb state token: {raw}"
        return None

    def serial_at(self, row: int) -> Optional[str]:
        if 0 <= row < len(self._rows):
            return self._rows[row].serial
        return None

    def row_of_serial(self, serial: str) -> Optional[int]:
        for i, device in enumerate(self._rows):
            if device.serial == serial:
                return i
        return None

    @property
    def rows(self) -> tuple[ConnectionInfo, ...]:
        return self._rows


class DeviceDetailsTableModel(QAbstractTableModel):
    """Field/Value rows from one typed ``DeviceProfile``.

    ``None`` profile facts render as "not reported" (honest absence —
    distinguishes unknown from a confirmed negative) and the root row
    preserves the R-05 tri-state words exactly.
    """

    _HEADERS = ("Field", "Value")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[tuple[str, str], ...] = ()

    def set_profile(self, serial: str,
                    profile: Optional[DeviceProfile]) -> None:
        self.beginResetModel()
        self._rows = () if profile is None else tuple(self._profile_rows(serial, profile))
        self.endResetModel()

    @staticmethod
    def _profile_rows(serial: str,
                      profile: DeviceProfile) -> tuple[tuple[str, str], ...]:
        def value(text: Optional[str]) -> str:
            return text if text else "not reported"

        return (
            ("Serial", value(profile.serial or serial)),
            ("Manufacturer", value(profile.mfr)),
            ("Model", value(profile.model)),
            ("Brand", value(profile.brand)),
            ("Android version", value(profile.android)),
            ("SDK level", str(profile.sdk_int) if profile.sdk_int
             else "not reported"),
            ("Security patch", value(profile.patch)),
            ("Build ID", value(profile.build_id)),
            ("Kernel", value(profile.kernel)),
            ("Bootloader", value(profile.bootloader)),
            ("Build fingerprint", value(profile.fingerprint)),
            ("Locale", value(profile.locale)),
            ("Time zone", value(profile.timezone)),
            ("IP address", value(profile.ip)),
            ("Root status", profile.root_status.name),
        )

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


PROVENANCE_TEXT = {
    AppLabelSource.EXACT: "verified",
    AppLabelSource.HEURISTIC: "inferred (derived)",
    AppLabelSource.UNKNOWN: "unknown source",
}


class AppsTableModel(QAbstractTableModel):
    """Installed-app inventory rows — Package / Label / Provenance /
    Version / Kind. Data is exactly what the service returned; a missing
    label is never replaced with a fabricated human-readable name."""

    _HEADERS = ("Package", "Label", "Provenance", "Version", "Kind")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[AppInfo, ...] = ()

    def set_rows(self, rows: Sequence[AppInfo]) -> None:
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
        app = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return app.package_name
            if column == 1:
                return app.label if app.label else "(no label)"
            if column == 2:
                return PROVENANCE_TEXT[app.label_source]
            if column == 3:
                return app.version_name if app.version_name else "—"
            if column == 4:
                return "system" if app.is_system else "3rd party"
        return None

    @property
    def rows(self) -> tuple[AppInfo, ...]:
        return self._rows


# ===========================================================================
# Administration confirmations (R-13 desktop gate — Stage 12)
# ===========================================================================

_ADMIN_OP_WORDS = {
    "launch_app": "launch",
    "force_stop_app": "force-stop",
    "uninstall_app": "uninstall",
}
_ADMIN_OP_IMPACT = {
    "launch_app": "Starts the package's main launcher activity on the "
                  "device (two-step: query the launcher activity, then "
                  "am start).",
    "force_stop_app": "Stops the package's processes on the device "
                      "(am force-stop) — unsaved app state is lost.",
    "uninstall_app": "Removes the package and its data from the device "
                     "(adb uninstall) — this is a REAL device-side "
                     "removal, not a preview.",
}


class AdminConfirmDialog(QDialog):
    """Operation-specific R-13 double-confirm (desktop, TUI parity).

    The dialog shows the EXACT operation, package, and target serial, is
    operation-specific (never a generic "Are you sure?"), and the
    Proceed action stays disabled until the full package name is typed
    back exactly. Cancel is a real action: dismissing by any means mints
    NO confirmation token and dispatches NOTHING.
    """

    def __init__(self, op: str, package: str, serial: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._package = package
        op_word = _ADMIN_OP_WORDS.get(op, op)
        self.setWindowTitle(f"{op_word} — confirm")
        self.setModal(True)
        self.setAccessibleName(f"Confirm {op_word} operation")
        self.setFixedWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACING["s"])

        warning = QLabel(
            f"{op_word.upper()} {package} on {serial}?\n"
            "Impact: " + _ADMIN_OP_IMPACT.get(op, "device-side change."),
            self)
        warning.setObjectName("bodyText")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        gate_note = QLabel(
            "This runs as an ADMIN_OP job against the engine's "
            "AdministrationService; the operation reaches the device "
            "only after the service re-validates the confirmation token "
            "itself (R-13).", self)
        gate_note.setObjectName("secondaryText")
        gate_note.setWordWrap(True)
        layout.addWidget(gate_note)

        prompt = QLabel(
            "Type the full package name exactly to proceed — Cancel "
            "(or closing this dialog) dispatches nothing:", self)
        prompt.setObjectName("secondaryText")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        self._input = QLineEdit(self)
        self._input.setPlaceholderText(package)
        self._input.setAccessibleName("Exact package name confirmation")
        layout.addWidget(self._input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        proceed = buttons.button(QDialogButtonBox.StandardButton.Ok)
        proceed.setText("Proceed")
        proceed.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._proceed = proceed
        self._input.textChanged.connect(self._sync_proceed)
        layout.addWidget(buttons)

    def _sync_proceed(self, text: str) -> None:
        # Exact-match binding: the dispatched operation can only reach
        # the service FOR the package the user re-typed byte for byte.
        self._proceed.setEnabled(text.strip() == self._package)

    def typed_package(self) -> str:
        return self._input.text().strip()


# ===========================================================================
# The workspace page
# ===========================================================================

_ACTIONABLE = DeviceState.DEVICE


class DeviceWorkspacePage(QWidget):
    """One cached per-section workspace widget (never reconstructed)."""

    def __init__(self, backend: DesktopBackend, hub: JobEventSignalHub,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._hub = hub
        self._workers = WorkerCoordinator(self)

        self.setAccessibleName("Device workspace")

        # honest device-discovery state ------------------------------------
        self._devices: tuple[ConnectionInfo, ...] = ()
        self._devices_state = "idle"          # idle | loading | refreshed | failed
        self._devices_stale = False           # last refresh failed; rows are last-good
        self._devices_error: Optional[str] = None
        self._refresh_stamp: Optional[str] = None
        self._auto_refresh_done = False
        self._selected_serial: Optional[str] = None
        self._invalidation_note: Optional[str] = None

        # device details state ----------------------------------------------
        self._profile: Optional[DeviceProfile] = None
        self._profile_serial: Optional[str] = None
        self._details_error: Optional[str] = None
        self._details_stamp: Optional[str] = None

        # installed-apps state -----------------------------------------------
        self._apps_rows: tuple[AppInfo, ...] = ()
        self._apps_job_id: Optional[str] = None
        self._apps_job_serial: Optional[str] = None
        self._apps_state = "idle"             # idle | loading | result | failed | cancelled
        self._apps_error: Optional[str] = None
        self._apps_stamp: Optional[str] = None
        self._apps_page = 0

        # administration state (Stage 12, R-13) ---------------------------------
        self._admin_state = "idle"  # idle | revalidating | running | refused | done | failed | cancelled
        self._admin_note: Optional[str] = None
        self._admin_job_id: Optional[str] = None
        self._admin_op: Optional[str] = None
        self._admin_package: Optional[str] = None
        self._admin_serial: Optional[str] = None

        self._building = False
        self._build_ui()
        # Truthful initial render for every panel (idle, nothing probed).
        self._render_devices_panel()
        self._render_details_panel()
        self._render_apps_panel()
        self._render_admin()
        self._sync_device_controls()
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

        # Banner strip: chip + explanatory text + explicit refresh control
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
        self._devices_table.setObjectName("devicesTable")
        self._devices_table.setModel(self._devices_model)
        self._devices_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._devices_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._devices_table.horizontalHeader().setStretchLastSection(True)
        self._devices_table.setMinimumHeight(120)
        self._devices_table.setAccessibleName("Discovered devices")
        self._devices_table.selectionModel().currentRowChanged.connect(
            self._on_selection_changed)
        devices_layout.addWidget(self._devices_table)
        splitter.addWidget(devices_panel)

        # --- details / apps tabs --------------------------------------------
        self._tabs = QTabWidget(splitter)

        # Details
        details_page = QWidget(self._tabs)
        details_layout = QVBoxLayout(details_page)
        details_layout.setContentsMargins(
            theme.SPACING["l"], theme.SPACING["m"],
            theme.SPACING["l"], theme.SPACING["l"])
        details_layout.setSpacing(theme.SPACING["s"])

        self._details_banner = QLabel("", self)
        self._details_banner.setObjectName("secondaryText")
        self._details_banner.setWordWrap(True)
        details_layout.addWidget(self._details_banner)

        self._details_model = DeviceDetailsTableModel()
        self._details_table = QTableView(details_page)
        self._details_table.setObjectName("detailsTable")
        self._details_table.setModel(self._details_model)
        self._details_table.horizontalHeader().setStretchLastSection(True)
        self._details_table.setAccessibleName("Device details")
        details_layout.addWidget(self._details_table, 1)

        self._details_button = button(
            "Load full profile", variant="primary",
            tooltip="Read the full device profile; root status comes only "
                    "from the verified root probe (honest tri-state)",
            accessible_name="Load full device profile")
        self._details_button.clicked.connect(self._on_load_details)
        details_layout.addWidget(self._details_button)
        self._tabs.addTab(details_page, "Device details")

        # Apps
        apps_page = QWidget(self._tabs)
        apps_layout = QVBoxLayout(apps_page)
        apps_layout.setContentsMargins(
            theme.SPACING["l"], theme.SPACING["m"],
            theme.SPACING["l"], theme.SPACING["l"])
        apps_layout.setSpacing(theme.SPACING["s"])

        self._apps_banner = QLabel("", self)
        self._apps_banner.setObjectName("secondaryText")
        self._apps_banner.setWordWrap(True)
        apps_layout.addWidget(self._apps_banner)

        self._apps_model = AppsTableModel()
        self._apps_table = QTableView(apps_page)
        self._apps_table.setObjectName("appsTable")
        self._apps_table.setModel(self._apps_model)
        self._apps_table.horizontalHeader().setStretchLastSection(True)
        self._apps_table.setAccessibleName("Installed applications")
        apps_layout.addWidget(self._apps_table, 1)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(theme.SPACING["m"])
        filter_label = QLabel("&Filter:")
        filter_label.setObjectName("secondaryText")
        self._apps_filter_input = QLineEdit(apps_page)
        self._apps_filter_input.setPlaceholderText(
            "match by package or label")
        self._apps_filter_input.setClearButtonEnabled(True)
        self._apps_filter_input.setAccessibleName("App inventory filter")
        self._apps_filter_input.textChanged.connect(self._on_filter_changed)

        self._apps_system_toggle = QCheckBox("Include system apps", apps_page)
        self._apps_system_toggle.setAccessibleName("Include system apps")
        self._apps_system_toggle.setToolTip(
            "Include system packages on the NEXT listing run (the current "
            "inventory is not refetched automatically).")

        self._apps_button = button(
            "List apps", variant="primary",
            tooltip="Start the cancellable package-listing job for the "
                    "selected device",
            accessible_name="List installed apps")
        self._apps_button.clicked.connect(self._on_list_apps)

        self._cancel_button = button(
            "Cancel", variant="secondary",
            tooltip="Cancel the running package-listing job",
            accessible_name="Cancel app listing")
        self._cancel_button.clicked.connect(self._on_cancel_listing)
        self._cancel_button.hide()

        controls_row.addWidget(filter_label)
        controls_row.addWidget(self._apps_filter_input, 1)
        controls_row.addWidget(self._apps_system_toggle)
        controls_row.addWidget(self._apps_button)
        controls_row.addWidget(self._cancel_button)
        apps_layout.addLayout(controls_row)

        page_row = QHBoxLayout()
        page_row.setContentsMargins(0, 0, 0, 0)
        page_row.setSpacing(theme.SPACING["m"])
        self._page_label = QLabel("", self)
        self._page_label.setObjectName("secondaryText")
        self._prev_button = button("Previous page", variant="secondary",
                                   accessible_name="Previous apps page")
        self._prev_button.clicked.connect(
            lambda: self._change_page(self._apps_page - 1))
        self._next_button = button("Next page", variant="secondary",
                                   accessible_name="Next apps page")
        self._next_button.clicked.connect(
            lambda: self._change_page(self._apps_page + 1))
        page_row.addWidget(self._page_label, 1)
        page_row.addWidget(self._prev_button)
        page_row.addWidget(self._next_button)
        apps_layout.addLayout(page_row)
        self._tabs.addTab(apps_page, "Installed apps")

        # Administration (Stage 12, R-13): device-side op dispatch gate
        admin_page = QWidget(self._tabs)
        admin_layout = QVBoxLayout(admin_page)
        admin_layout.setContentsMargins(
            theme.SPACING["l"], theme.SPACING["m"],
            theme.SPACING["l"], theme.SPACING["l"])
        admin_layout.setSpacing(theme.SPACING["s"])

        self._admin_gate_banner = QLabel(
            "Only the engine-supported administration operations are "
            "shown. Each one is doubly gated: an operation-specific "
            "confirmation (the exact package name is re-typed there — "
            "Cancel dispatches nothing) and the service's own "
            "OperationConfirmation validation. The target device is "
            "revalidated immediately before dispatch, and the device is "
            "NEVER selected automatically.", self)
        self._admin_gate_banner.setObjectName("hintText")
        self._admin_gate_banner.setWordWrap(True)
        admin_layout.addWidget(self._admin_gate_banner)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACING["m"])
        package_label = QLabel("&Package:")
        package_label.setObjectName("secondaryText")
        self._admin_package_input = QLineEdit(admin_page)
        self._admin_package_input.setPlaceholderText(
            "exact package name (typed by you; never auto-filled)")
        self._admin_package_input.setAccessibleName(
            "Administration target package")
        self._admin_package_input.textChanged.connect(
            lambda _text: self._sync_device_controls())
        row.addWidget(package_label)
        row.addWidget(self._admin_package_input, 1)

        admin_buttons = QVBoxLayout()
        admin_buttons.setContentsMargins(0, 0, 0, 0)
        admin_buttons.setSpacing(theme.SPACING["xs"])
        self._admin_buttons: dict[str, QPushButton] = {}
        for op in ("launch_app", "force_stop_app", "uninstall_app"):
            op_word = _ADMIN_OP_WORDS[op]
            op_button = button(
                f"{op_word.capitalize()} app", variant="secondary",
                tooltip=f"Impact: {_ADMIN_OP_IMPACT[op]}",
                accessible_name=f"{op_word} application on the selected device")
            op_button.clicked.connect(
                lambda _=False, op=op: self._on_admin_op(op))
            self._admin_buttons[op] = op_button
            admin_buttons.addWidget(op_button)
        row.addLayout(admin_buttons)
        admin_layout.addLayout(row)

        self._admin_status = QLabel("", self)
        self._admin_status.setObjectName("secondaryText")
        self._admin_status.setWordWrap(True)
        admin_layout.addWidget(self._admin_status)

        admin_layout.addStretch(1)
        self._tabs.addTab(admin_page, "Administration")

        splitter.addWidget(self._tabs)
        outer.addWidget(splitter, 1)

    # ------------------------------------------------------------------ #
    # lifecycle hooks the shell uses
    # ------------------------------------------------------------------ #

    def activate(self) -> None:
        """First activation runs exactly ONE auto-discovery (TUI parity).

        Later activations are honest no-ops — discovery is on-demand, never
        a polling loop."""
        if not self._auto_refresh_done and self._devices_state == "idle":
            self._auto_refresh_done = True
            self.refresh_devices()

    def shutdown(self) -> None:
        """Owner-close hook: stop worker threads + disconnect the hub.

        The shell calls this in ``closeEvent`` for every built section that
        owns background resources (explicit ownership/shutdown rule)."""
        try:
            self._hub.terminal.disconnect(self._on_terminal_event)
        except RuntimeError:
            pass  # already disconnected or the hub was destroyed
        self._workers.close()

    # ------------------------------------------------------------------ #
    # job-event delivery (shared shell hub; worker thread → queued slot)
    # ------------------------------------------------------------------ #

    def _on_terminal_event(self, event: JobTerminalEvent) -> None:
        if event.kind is JobKind.ADMIN_OP:
            self._on_admin_terminal(event)
            return
        if event.kind is not JobKind.APP_LISTING:
            return
        # NOTE: JobTerminalEvent carries job_id but NO device_serial —
        # identity is the tracked job id (TUI workspace parity).
        if event.job_id != self._apps_job_id:
            return  # late event from a superseded job — never touch state
        self._apps_job_id = None
        self._apps_job_serial = None
        if event.outcome is JobState.SUCCEEDED:
            rows = tuple(event.result or ())
            self._apps_rows = rows
            self._apps_state = "result"
            self._apps_error = None
            self._apps_stamp = _now_stamp()
            self._apps_page = 0
        elif event.outcome is JobState.CANCELLED:
            self._apps_rows = ()
            self._apps_state = "cancelled"
            self._apps_error = None
        else:
            self._apps_rows = ()
            self._apps_state = "failed"
            self._apps_error = (
                "listing failed" if event.error is None
                else engine_error_text(event.error))
        self._render_apps_panel()
        self._sync_device_controls()

    # ------------------------------------------------------------------ #
    # device discovery
    # ------------------------------------------------------------------ #

    def refresh_devices(self) -> None:
        """One ``adb devices`` probe in a background worker (deduped).

        While a refresh is pending the control stays disabled — the
        coordinator refuses duplicate slots, so overlapping discovery is
        impossible by construction."""
        self._refresh_button.setEnabled(False)
        started = self._workers.run(
            "refresh_devices",
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
        self._sync_device_controls()

    def _on_devices_failed(self, exc: BaseException) -> None:
        if self._devices:
            # Last successful result survives, visibly marked stale.
            self._devices_stale = True
            self._devices_state = "failed"
        else:
            self._devices_state = "failed"
        self._devices_error = engine_error_text(exc)
        self._refresh_button.setEnabled(True)
        self._render_devices_panel()
        self._sync_device_controls()

    def _apply_devices(self, rows: tuple[ConnectionInfo, ...]) -> None:
        self._devices = rows
        self._devices_state = "refreshed"
        self._devices_stale = False
        self._devices_error = None
        self._refresh_stamp = _now_stamp()
        self._devices_model.set_rows(rows)
        self._reconcile_selection()

    def _reconcile_selection(self) -> None:
        """Refresh-time selection reconciliation (TUI Stage 06 contract).

        * Preserve the selected device if the same serial is still present.
        * Invalidate honestly when it disappeared (never switch targets
          implicitly, never keep acting on a ghost device).
        * Auto-preselect ONLY when exactly one device is present and
          nothing is selected (the unambiguous case); with several devices
          NOTHING is auto-selected."""
        selection = self._devices_table.selectionModel()
        if self._selected_serial is not None:
            row = self._devices_model.row_of_serial(self._selected_serial)
            if row is not None:
                self._invalidation_note = None
                selection.setCurrentIndex(
                    self._devices_model.index(row, 0),
                    self._clear_and_select_flags())
                return
            self._invalidate_selection(
                f"The selected device {self._selected_serial} is gone after "
                "the last refresh — the target was invalidated on purpose "
                "(nothing is auto-switched).")
            return
        # nothing selected yet: the unambiguous single-device case only
        actionable = [d for d in self._devices if d.state is _ACTIONABLE]
        if len(actionable) == 1:
            row = self._devices_model.row_of_serial(actionable[0].serial)
            if row is not None:
                selection.setCurrentIndex(
                    self._devices_model.index(row, 0),
                    self._clear_and_select_flags())

    def _invalidate_selection(self, note: str) -> None:
        self._selected_serial = None
        self._invalidation_note = note
        self._profile = None
        self._profile_serial = None
        self._details_error = None
        self._details_stamp = None
        self._details_model.set_profile("", None)
        self._apps_rows = ()
        self._apps_state = "idle"
        self._apps_error = None
        self._apps_stamp = None
        self._apps_page = 0
        self._invalidate_pending_admin_selection(note)

    def _invalidate_pending_admin_selection(self, note: str) -> None:
        """A vanished/changed target while an admin op is pending
        refuses the dispatch honestly — nothing is sent to a ghost."""
        if self._admin_state in ("revalidating", "running"):
            self._admin_state = "refused"
            self._admin_note = (
                f"the target changed ({note}) — nothing was dispatched")
            self._reset_admin_target()
            self._render_admin()
        self._sync_device_controls()

    @staticmethod
    def _clear_and_select_flags():
        return (QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Current)

    def _on_selection_changed(self, current, _previous) -> None:
        """User-driven selection (also fires for programmatic re-selection);
        the target banner always mirrors the truth."""
        serial = self._devices_model.serial_at(current.row()) \
            if current is not None and current.isValid() else None
        if serial is not None:
            if serial != self._selected_serial:
                self._on_admin_target_changed()
            self._selected_serial = serial
            self._invalidation_note = None
            self._profile = None
            self._profile_serial = None
            self._details_error = None
            self._details_stamp = None
            self._details_model.set_profile(serial, None)
            self._apps_rows = ()
            self._apps_state = "idle"
            self._apps_error = None
            self._apps_stamp = None
            self._apps_page = 0
        self._sync_device_controls()

    def _on_admin_target_changed(self) -> None:
        """Selection moved while an admin op was pending (never auto-
        selected): the pending dispatch is refused honestly."""
        if self._admin_state in ("revalidating", "running"):
            self._admin_state = "refused"
            self._admin_note = (
                "the selected target changed during confirmation — "
                "nothing was dispatched")
            self._reset_admin_target()
            self._render_admin()

    @property
    def selected_serial(self) -> Optional[str]:
        return self._selected_serial

    def _selected_row(self) -> Optional[ConnectionInfo]:
        if self._selected_serial is None:
            return None
        for device in self._devices:
            if device.serial == self._selected_serial:
                return device
        return None

    # ------------------------------------------------------------------ #
    # device details
    # ------------------------------------------------------------------ #

    def _on_load_details(self) -> None:
        device = self._selected_row()
        if device is None or device.state is not _ACTIONABLE:
            return  # control disabled in these states; defensive no-op
        serial = device.serial
        started = self._workers.run(
            "load_details",
            lambda: self._backend.full_profile(serial),
            lambda profile: self._on_details_done(serial, profile),
            lambda exc: self._on_details_failed(serial, exc),
        )
        if not started:
            return  # same-slot probe pending: it finishes and re-enables
        self._details_banner.setText(
            f"Reading the full device profile for {serial} …")

    def _on_details_done(self, serial: str, profile: DeviceProfile) -> None:
        if serial != self._selected_serial:
            return  # superseded probe — never fill stale facts
        self._profile = profile
        self._profile_serial = serial
        self._details_error = None
        self._details_stamp = _now_stamp()
        self._details_model.set_profile(serial, profile)
        self._render_details_panel()

    def _on_details_failed(self, serial: str, exc: BaseException) -> None:
        if serial != self._selected_serial:
            return  # superseded probe — a transport error is not a verdict
        self._profile = None
        self._profile_serial = None
        self._details_error = engine_error_text(exc)
        self._details_stamp = None
        self._details_model.set_profile(serial, None)
        self._render_details_panel()

    def _render_details_panel(self) -> None:
        lines: list[str] = []
        if self._details_error is not None:
            lines.append(f"details read failed: {self._details_error}")
        if self._profile is not None and self._details_stamp:
            root = "known" \
                if self._profile.root_status.name != "UNKNOWN" else "UNKNOWN"
            lines.append(
                f"full profile for {self._profile_serial} read at "
                f"{self._details_stamp}; root status: {root}")
        elif self._details_error is None:
            device = self._selected_row()
            if device is not None and device.state is _ACTIONABLE:
                lines.append(
                    "Full profile not read yet — press Load full profile "
                    "(facts read from the device; root stays UNKNOWN "
                    "until the verified probe succeeds).")
        self._details_banner.setText(" ".join(lines))

    # ------------------------------------------------------------------ #
    # app inventory (cancellable APP_LISTING job via the Stage 04 system)
    # ------------------------------------------------------------------ #

    def _on_list_apps(self) -> None:
        device = self._selected_row()
        if device is None or device.state is not _ACTIONABLE:
            return  # control disabled in these states; defensive no-op
        serial = device.serial
        include_system = self._apps_system_toggle.isChecked()
        try:
            handle = self._backend.start_listing_job(
                serial, include_system=include_system)
        except Exception as exc:
            # JobConflictError / AdbNotAvailable — honest inline message
            self._apps_state = "failed"
            self._apps_error = engine_error_text(exc)
            self._render_apps_panel()
            return
        self._apps_job_id = handle.id
        self._apps_job_serial = serial
        self._apps_state = "loading"
        self._apps_rows = ()
        self._apps_error = None
        self._apps_page = 0
        self._render_apps_panel()
        self._sync_device_controls()

    def _on_cancel_listing(self) -> None:
        if self._apps_job_serial is None:
            return
        self._backend.cancel_listing_job(self._apps_job_serial)

    # ------------------------------------------------------------------ #
    # administration ops (Stage 12, R-13 — double-gated, never auto-target)
    # ------------------------------------------------------------------ #

    def _on_admin_op(self, op: str) -> None:
        """Open the operation-specific confirm dialog for one op.

        Guards: an explicitly selected, currently DEVICE-state target;
        a non-empty user-typed package; NO other admin operation pending.
        Nothing is dispatched here yet — the dialog's Proceed is what
        moves the flow forward, and only its exact re-typed package
        passes."""
        if self._admin_state in ("revalidating", "running"):
            return  # duplicate submissions are refused, never stacked
        device = self._selected_row()
        if device is None or device.state is not _ACTIONABLE:
            return  # controls disabled in these states; defensive no-op
        package = self._admin_package_input.text().strip()
        if not package:
            self._admin_state = "refused"
            self._admin_note = (
                "no package typed — type the exact package name first; "
                "nothing was dispatched")
            self._render_admin()
            return
        serial = device.serial
        dialog = AdminConfirmDialog(op, package, serial, self)
        outcome = dialog.exec()
        typed = dialog.typed_package() \
            if outcome == int(dialog.DialogCode.Accepted) else None
        # Cancel / dismiss / mismatch (Proceed stays disabled until the
        # input matches) → NO token is minted and NOTHING is dispatched.
        if typed != package:
            self._render_admin()
            return
        self._admin_op = op
        self._admin_package = typed
        self._admin_serial = serial
        self._admin_state = "revalidating"
        self._admin_note = "revalidating the target immediately before dispatch…"
        self._render_admin()
        self._sync_device_controls()
        started = self._workers.run(
            "admin_revalidate",
            lambda: tuple(self._backend.list_devices()),
            lambda rows: self._on_admin_revalidated(typed, serial, rows, None),
            lambda exc: self._on_admin_revalidated(typed, serial, (), exc),
        )
        if not started:
            # revalidation slot busy — refuse honestly, nothing dispatched
            self._admin_state = "refused"
            self._admin_note = (
                "target revalidation is still busy — nothing was "
                "dispatched; retry once it completes")
            self._render_admin()

    def _on_admin_revalidated(self, package: str, serial: str,
                              rows: tuple,
                              exc: Optional[BaseException]) -> None:
        """Fresh target validation immediately before execution.

        The device must STILL be present in a fresh, DEVICE-state listing
        and still be the selected target — a vanished, unauthorized, or
        re-targeted selection refuses the operation (nothing is sent).
        Only then is the OperationConfirmation minted (exact
        ``admin:<op>:<package>`` reference, tz-aware UTC) and the ADMIN_OP
        job submitted through the AdministrationService gate."""
        if self._admin_state != "revalidating" or \
                self._admin_package != package or \
                self._admin_serial != serial:
            return  # superseded attempt — never dispatch across states
        if exc is not None:
            self._admin_state = "refused"
            self._admin_note = (
                f"target revalidation failed: {engine_error_text(exc)} — "
                "nothing was dispatched")
            self._reset_admin_target()
            self._render_admin()
            self._sync_device_controls()
            return
        fresh = any(
            row.serial == serial and row.state is _ACTIONABLE
            for row in rows)
        if not fresh or serial != self._selected_serial:
            self._admin_state = "refused"
            self._admin_note = (
                f"the target {serial} was not revalidated as a connected, "
                "authorized device — nothing was dispatched")
            self._reset_admin_target()
            self._render_admin()
            self._sync_device_controls()
            return
        op = self._admin_op
        if op is None:
            return
        confirmation = OperationConfirmation(
            reference=f"admin:{op}:{package}",
            confirmed_at=datetime.now(timezone.utc),
        )
        try:
            handle = self._backend.start_admin_job(
                serial, op, package, confirmation)
        except Exception as admin_exc:
            self._admin_state = "refused"
            self._admin_note = (
                f"operation refused before dispatch: "
                f"{engine_error_text(admin_exc)}")
            self._reset_admin_target()
            self._render_admin()
            self._sync_device_controls()
            return
        self._admin_job_id = handle.id
        self._admin_state = "running"
        self._admin_note = (
            f"{_ADMIN_OP_WORDS.get(op, op)} {package} on {serial} "
            "dispatched through the service gate — running…")
        self._render_admin()
        self._sync_device_controls()

    def _reset_admin_target(self) -> None:
        self._admin_op = None
        self._admin_package = None
        self._admin_serial = None

    def _on_admin_terminal(self, event: JobTerminalEvent) -> None:
        """Honest ADMIN_OP reconciliation (tracked job id only — terminal
        events carry no device serial)."""
        if event.job_id != self._admin_job_id:
            return  # late event from a superseded op — never touch state
        self._admin_job_id = None
        op = self._admin_op
        package = self._admin_package
        serial = self._admin_serial
        if event.outcome is JobState.SUCCEEDED:
            result = event.result
            if isinstance(result, OperationResult):
                code = result.adb_returncode
                self._admin_state = "done" if result.ok else "failed"
                self._admin_note = (
                    f"{_ADMIN_OP_WORDS.get(op or '', op or '')} {package} "
                    f"on {serial}: device reported "
                    f"return code {code}"
                    + (f" — {result.message}"
                       if result.message else "")
                    + (" — the device acknowledged the dispatch; the "
                       "engine does not re-verify the effect beyond "
                       "this reported code"))
            else:
                self._admin_state = "done"
                self._admin_note = f"operation finished ({op or 'op'})"
        elif event.outcome is JobState.CANCELLED:
            self._admin_state = "cancelled"
            self._admin_note = (
                f"{_ADMIN_OP_WORDS.get(op or '', op or '')} {package} on "
                f"{serial}: cancelled — the engine's job was aborted "
                "(the dispatch itself may or may not have completed "
                "device-side; the job's terminal state is what is "
                "known)")
        else:
            self._admin_state = "failed"
            self._admin_note = (
                f"operation failed: "
                + ("unknown failure" if event.error is None
                   else engine_error_text(event.error)))
        self._reset_admin_target()
        self._render_admin()
        self._sync_device_controls()

    def _render_admin(self) -> None:
        label = self._admin_status
        if self._admin_state == "idle":
            label.setText(
                "idle — type the exact package name, then press one "
                "operation (each opens its own confirmation)")
        elif self._admin_state == "revalidating":
            label.setText(self._admin_note or "revalidating the target…")
        elif self._admin_state == "running":
            label.setText(self._admin_note or "operation running…")
        elif self._admin_state == "refused":
            label.setText(f"REFUSED: {self._admin_note}")
        elif self._admin_state == "done":
            label.setText(f"completed: {self._admin_note}")
        elif self._admin_state == "cancelled":
            label.setText(f"cancelled: {self._admin_note}")
        else:  # failed
            label.setText(f"FAILED: {self._admin_note}")


    def _on_filter_changed(self, text: str) -> None:
        self._apps_page = 0
        self._render_apps_panel()

    def matched_rows(self) -> tuple[AppInfo, ...]:
        """Filter over the immutable inventory (list never mutated)."""
        query = self._apps_filter_input.text().strip().lower()
        if not query:
            return self._apps_rows
        return tuple(
            app for app in self._apps_rows
            if query in app.package_name.lower()
            or query in (app.label or "").lower())

    def _page_bounds(self, total: int) -> tuple[int, int]:
        last_page = max(0, -(-total // PAGE_SIZE) - 1)
        page = min(self._apps_page, last_page)
        return page, last_page

    def _change_page(self, page: int) -> None:
        total = len(self.matched_rows())
        _current, last_page = self._page_bounds(total)
        self._apps_page = max(0, min(page, last_page))
        self._render_apps_panel()

    def visible_rows(self) -> tuple[AppInfo, ...]:
        total = len(self.matched_rows())
        page, _last = self._page_bounds(total)
        start = page * PAGE_SIZE
        return self.matched_rows()[start:start + PAGE_SIZE]

    def _render_apps_panel(self) -> None:
        self._apps_model.set_rows(self.visible_rows())
        total = len(self.matched_rows())
        page, last_page = self._page_bounds(total)
        filter_active = bool(self._apps_filter_input.text().strip())

        if self._apps_state == "loading":
            self._apps_banner.setText(
                "Listing installed packages — a cancellable job is running "
                "in the background (no percentage is fabricated).")
        elif self._apps_state == "cancelled":
            self._apps_banner.setText(
                "Listing cancelled by your request — no partial rows kept.")
        elif self._apps_state == "failed":
            message = self._apps_error or "the listing failed"
            self._apps_banner.setText(f"listing failed: {message}")
        elif total == 0:
            self._apps_banner.setText(
                "no packages match the filter"
                if filter_active else
                "no packages reported")
        else:
            stamp = f" — received at {self._apps_stamp}" if self._apps_stamp else ""
            self._apps_banner.setText(
                f"{total} apps match"
                f"{' the filter' if filter_active else ''}"
                f"{stamp}; labels are derived (provenance column states "
                "their source).")

        if total:
            self._page_label.setText(
                f"page {page + 1}/{last_page + 1} — {PAGE_SIZE} per page — "
                f"{total} rows")
        else:
            self._page_label.setText("no rows")
        self._prev_button.setEnabled(page > 0)
        self._next_button.setEnabled(page < last_page)

    # ------------------------------------------------------------------ #
    # rendering + control enablement (GUI thread only)
    # ------------------------------------------------------------------ #

    def _render_devices_panel(self) -> None:
        banner = self._devices_banner
        chip = self._devices_chip
        stamp = f" at {self._refresh_stamp}" if self._refresh_stamp else ""
        if self._devices_state == "idle":
            chip.set_status("neutral")
            banner.setText("discovery has not run yet — nothing probed "
                           "while idle; Refresh devices runs one probe.")
        elif self._devices_state == "loading":
            chip.set_status("info")
            banner.setText("discovery request running in the background…")
        elif self._devices_state == "refreshed":
            if self._devices:
                chip.set_status("ok")
            else:
                chip.set_status("neutral")
            banner.setText(
                f"{len(self._devices)} device(s) reported{stamp}.")
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

        # device rows honesty note (selection of OFFLINE etc.)
        self._target_banner.setText(self._target_text())

    def _target_text(self) -> str:
        parts: list[str] = []
        if self._selected_serial is not None:
            device = self._selected_row()
            state = device.state.value if device is not None else "unknown"
            parts.append(f"selected target: {self._selected_serial} "
                         f"(state: {state})")
        if self._invalidation_note:
            parts.append(self._invalidation_note)
        return " — ".join(parts)

    def _sync_device_controls(self) -> None:
        """Enable/disable target-dependent controls honestly.

        Load/List actions need an explicitly selected, currently listed
        DEVICE-state row; anything less is disabled with a truthful tip."""
        reason: Optional[str] = None
        device = self._selected_row()
        if device is None:
            reason = ("no device selected — select one in the device list"
                      if self._devices else
                      "no devices discovered yet — refresh first")
        elif device.state is not _ACTIONABLE:
            reason = (f"selected device is {device.state.value}; operations "
                      "that need a connected device are disabled until it "
                      "is connected and authorized")
        elif self._devices_stale:
            reason = ("last refresh FAILED: the device list is stale; "
                      "refresh successfully before targeting a device")

        details_enabled = reason is None
        apps_enabled = details_enabled

        self._details_button.setEnabled(details_enabled)
        self._apps_button.setEnabled(apps_enabled)
        listing_running = self._apps_state == "loading"
        self._cancel_button.setVisible(listing_running)
        self._cancel_button.setEnabled(listing_running)
        self._apps_button.setEnabled(apps_enabled and not listing_running)

        # Administration (Stage 12): device required; one operation at a
        # time; the package must be user-typed before dispatching.
        admin_busy = self._admin_state in ("revalidating", "running")
        admin_reason = reason
        if admin_reason is None and admin_busy:
            admin_reason = "another administration operation is active"
        elif admin_reason is None and \
                not self._admin_package_input.text().strip():
            admin_reason = "type the exact package name first"
        for op, op_button in self._admin_buttons.items():
            op_button.setEnabled(admin_reason is None)
            if admin_reason is not None:
                op_button.setToolTip(admin_reason)

        tips = {
            self._details_button: "Operations need an explicitly selected, "
                                  "currently connected device.",
            self._apps_button: "Operations need an explicitly selected, "
                               "currently connected device.",
        }
        for widget, tip in tips.items():
            widget.setToolTip(tip if reason is None else reason)


def _now_stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")
