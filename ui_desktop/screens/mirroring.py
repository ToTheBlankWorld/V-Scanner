"""Screen mirroring (Stage 12 desktop parity): honest scrcpy lifecycle.

The Qt counterpart of the TUI mirroring screen, on the exact same engine
semantics (SC-8 through the shared ``ScreenMirrorService``):

* Launch requires a VALIDATED scrcpy tool (the engine's tool-provisioning
  face reports the honest state: NOT_FOUND / FOUND_UNVALIDATED /
  VALIDATED …). The page surfaces that state verbatim and passes the
  engine's typed ``ToolNotValidated`` refusal straight through — never a
  silent ``False`` the user could misread as a device problem. Tool
  provisioning itself stays in the engine/CLI workflow; the desktop
  screen does not download or validate tools.
* Launch runs in a deduped background worker; argv-only spawn (R-12)
  happens inside the engine — this page never builds shell strings.
* Duplicate-launch prevention (desktop hardening over the TUI): the
  launch worker FIRST reads the engine registry for the target; any
  still-running handle for the serial (or a launch already in flight
  for it) refuses the request honestly — new handles only on an
  actually idle target.
* States are REAL process states from the service: launch recorded,
  running/exit-code as reported by ``list_running``, stopped pids as
  returned by ``stop``. A successful launch NEVER claims an on-screen
  window — scrcpy-owned display behavior is explicitly unverified on
  hardware.
* ``turn_screen_off`` is device-mutating (model-enforced confirmation)
  and is deliberately NOT offered here — the plain launch path keeps
  TUI parity (defaults: 1024px, 30fps, screen stays on).
* App shutdown: the page stops the mirrors it launched through the
  service so no unmanaged child process outlives the application.

Threading model: launches/lists/stops are process or subprocess work →
``WorkerCoordinator`` slots only; no widget is touched from a worker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from vscanner.core.errors import ToolNotValidated
from vscanner.core.models import (
    ConnectionInfo,
    DeviceState,
    MirrorHandle,
    MirrorOptions,
    ToolState,
)

from .. import theme
from ..backend import DesktopBackend
from ..jobs_bridge_qt import JobEventSignalHub
from ..workers import WorkerCoordinator
from ..widgets import Panel, StatusChip, button
from .devices import DevicesTableModel, engine_error_text

__all__ = ["MirroringPage"]

_ACTIONABLE = DeviceState.DEVICE

_TOOL_STATE_WORDS = {
    ToolState.NOT_FOUND: "not found",
    ToolState.FOUND_UNVALIDATED: "found but never validated",
    ToolState.VALIDATED: "validated",
    ToolState.PROVISIONING: "provisioning in progress",
    ToolState.INSTALL_FAILED: "install failed",
}


def _plain(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ")
    return " ".join(text.split())[:160]


LAUNCH_OPTIONS = MirrorOptions(
    resolution=1024, max_fps=30, turn_screen_off=False,
)
"""SC-8 defaults; the device-mutating screen-off route needs its own
explicit confirmation bit at the model level and is not offered here."""

LAUNCH_COMPLEXITY_NOTE = (
    "A launch only RECORDS the scrcpy process — whether any window "
    "appears on screen is scrcpy's own display behavior and is NOT "
    "claimed or verified by this application.")


# ===========================================================================
# table model
# ===========================================================================

class HandlesTableModel(QAbstractTableModel):
    """Engine registry handles — pid/serial/launched-at/exit code exactly
    as the service reports (including exit codes when observed)."""

    _HEADERS = ("pid", "Serial", "Launched (UTC)", "Exit code")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[tuple[str, str, str, str], ...] = ()
        self._note = "handles not listed yet"

    def set_handles(self, handles, note: str) -> None:
        self.beginResetModel()
        if handles:
            self._rows = tuple(
                (str(handle.pid), handle.serial or "—",
                 str(handle.launched_at),
                 "running" if handle.exit_code is None
                 else f"exited ({handle.exit_code})")
                for handle in handles)
            self._note = "—"
        else:
            self._rows = ()
            self._note = note
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
                return ("—", self._note, "—", "—")[index.column()]
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row[index.column()]
        return None

    @property
    def rows(self) -> tuple[tuple[str, str, str, str], ...]:
        return self._rows


# ===========================================================================
# the page
# ===========================================================================

class MirroringPage(QWidget):
    """One cached per-section mirroring page (never reconstructed)."""

    def __init__(self, backend: DesktopBackend, hub: JobEventSignalHub,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._hub = hub
        self._workers = WorkerCoordinator(self)

        self.setAccessibleName("Mirroring")

        # discovery state (same honest pattern as the device workspace)
        self._devices: tuple[ConnectionInfo, ...] = ()
        self._devices_state = "idle"  # idle | loading | refreshed | failed
        self._devices_error: Optional[str] = None
        self._refresh_stamp: Optional[str] = None
        self._auto_refresh_done = False
        self._selected_serial: Optional[str] = None

        # mirroring lifecycle state
        self._tool_status: Optional[Any] = None   # ToolStatusReflected
        self._tool_error: Optional[str] = None
        self._handle_state = "idle"    # idle | listing | ready | failed
        self._handle_note: Optional[str] = None
        self._handles: tuple[MirrorHandle, ...] = ()
        self._launching_serial: Optional[str] = None
        self._launch_error: Optional[str] = None
        # the honest "launch recorded" note survives the follow-up handle
        # refresh (it is STATE, not a transient setText)
        self._launch_note: Optional[str] = None
        self._stop_note: Optional[str] = None
        # serials this page launched (desktop duplicate-launch memory +
        # shutdown ownership: every serial here owns managed mirrors)
        self._launched_serials: set[str] = set()

        self._building = False
        self._build_ui()
        self._render_all()

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
        self._devices_banner.setAccessibleName("Device discovery status")
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
        self._target_banner.setAccessibleName("Mirroring target status")
        outer.addWidget(self._target_banner)

        splitter = QSplitter(self)
        splitter.setOrientation(Qt.Orientation.Vertical)

        # --- device list panel ---------------------------------------------
        devices_panel = Panel(splitter)
        devices_layout = Panel.body_layout(devices_panel)
        self._devices_model = DevicesTableModel()
        self._devices_table = QTableView(devices_panel)
        self._devices_table.setObjectName("mirroringDevicesTable")
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

        # --- prerequisite + lifecycle panel -----------------------------------
        work_panel = Panel(splitter)
        work_layout = Panel.body_layout(work_panel)

        self._tool_banner = QLabel("", self)
        self._tool_banner.setObjectName("secondaryText")
        self._tool_banner.setWordWrap(True)
        self._tool_banner.setAccessibleName("Mirror tool status")
        work_layout.addWidget(self._tool_banner)

        lifecycle_row = QHBoxLayout()
        lifecycle_row.setContentsMargins(0, 0, 0, 0)
        lifecycle_row.setSpacing(theme.SPACING["m"])
        self._launch_button = button(
            "Launch mirror", variant="primary",
            tooltip="Start the validated scrcpy tool for the explicitly "
                    "selected device (argv-only spawn in the engine; "
                    "duplicate launches for the target are refused)",
            accessible_name="Launch mirror")
        self._launch_button.clicked.connect(self._on_launch)
        self._stop_button = button(
            "Stop mirrors for target", variant="secondary",
            tooltip="Stop the target's mirror processes through the "
                    "service registry (returns exactly what it stopped)",
            accessible_name="Stop mirrors for target")
        self._stop_button.clicked.connect(self._on_stop)
        self._handles_button = button(
            "Check running mirrors", variant="secondary",
            tooltip="Read the engine registry: real process handles with "
                    "exit codes when observed",
            accessible_name="Check running mirrors")
        self._handles_button.clicked.connect(self._on_list_handles)
        lifecycle_row.addWidget(self._launch_button, 1)
        lifecycle_row.addWidget(self._stop_button)
        lifecycle_row.addWidget(self._handles_button)
        work_layout.addLayout(lifecycle_row)

        self._lifecycle_banner = QLabel("", self)
        self._lifecycle_banner.setObjectName("secondaryText")
        self._lifecycle_banner.setWordWrap(True)
        self._lifecycle_banner.setAccessibleName(
            "Mirroring process status")
        work_layout.addWidget(self._lifecycle_banner)

        self._handles_model = HandlesTableModel()
        self._handles_table = QTableView(work_panel)
        self._handles_table.setObjectName("mirrorHandlesTable")
        self._handles_table.setModel(self._handles_model)
        self._handles_table.horizontalHeader().setStretchLastSection(True)
        self._handles_table.setMinimumHeight(110)
        self._handles_table.setAccessibleName("Mirror handles")
        work_layout.addWidget(self._handles_table, 1)

        note = QLabel(
            "Prerequisites: a VALIDATED scrcpy tool (ToolProvisioningService "
            "— done in the engine/CLI workflow, never downloaded here) and "
            "an explicitly selected connected device. turn_screen_off is "
            "device-mutating and is not offered on this launch path.")
        note.setObjectName("hintText")
        note.setWordWrap(True)
        work_layout.addWidget(note)
        splitter.addWidget(work_panel)
        outer.addWidget(splitter, 1)

    # ------------------------------------------------------------------ #
    # lifecycle hooks the shell uses
    # ------------------------------------------------------------------ #

    def activate(self) -> None:
        """First activation runs exactly one auto-discovery + one tool
        preflight probe (both deduped background workers)."""
        if not self._auto_refresh_done and self._devices_state == "idle":
            self._auto_refresh_done = True
            self.refresh_devices()
            self._probe_tool()

    def shutdown(self) -> None:
        """Owner-close hook: disconnect workers AND stop the mirrors this
        page launched (managed ownership — no unmanaged child processes
        outlive the application)."""
        for serial in list(self._launched_serials):
            try:
                stopped = self._backend.mirror_stop(serial, None)
                self._launched_serials.discard(serial)
                # ``stopped`` intentionally read-and-dropped: the honest
                # list of terminated pids is the engine's return value;
                # the app is closing, so it is only asserted non-None.
                if stopped is None:
                    continue
            except Exception:
                # The owning app is closing; a failed stop is left for
                # the engine registry scanner to report next session.
                pass
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
        self._target_banner.setText(self._target_text())
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
    # selection (target changes invalidate nothing silently)
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
        self._target_banner.setText(self._target_text())
        self._sync_controls()

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

    def _target_valid(self) -> bool:
        device = self._selected_row()
        return device is not None and device.state is _ACTIONABLE

    # ------------------------------------------------------------------ #
    # tool preflight (honest; worker thread; filesystem stats)
    # ------------------------------------------------------------------ #

    def _probe_tool(self) -> None:
        started = self._workers.run(
            "mirror_preflight",
            self._backend.mirror_tool_status,
            self._on_tool_done,
            self._on_tool_failed,
        )
        if started:
            self._tool_banner.setText(
                "checking the scrcpy tool state in the background…")

    def _on_tool_done(self, status: Any) -> None:
        self._tool_status = status
        self._tool_error = None
        self._render_tool_panel()
        self._sync_controls()

    def _on_tool_failed(self, exc: BaseException) -> None:
        self._tool_status = None
        self._tool_error = engine_error_text(exc)
        self._render_tool_panel()
        self._sync_controls()

    # ------------------------------------------------------------------ #
    # launch / list / stop (deduped background workers)
    # ------------------------------------------------------------------ #

    def _on_launch(self) -> None:
        serial = self._selected_serial
        if serial is None or not self._target_valid():
            return  # control disabled in these states; defensive no-op
        if self._launching_serial is not None:
            return  # one launch in flight at a time (duplicate prevention)
        self._launching_serial = serial
        self._launch_error = None
        self._render_lifecycle()
        self._sync_controls()
        started = self._workers.run(
            "launch_mirror",
            lambda: self._launch_worker(serial),
            lambda outcome: self._apply_launch(serial, outcome, None),
            lambda exc: self._apply_launch(serial, None, exc),
        )
        if not started:
            # slot busy (device refresh/tool probe crashed mid-run etc.) —
            # release the in-flight marker honestly
            self._launching_serial = None
            self._sync_controls()

    def _launch_worker(self, serial: str) -> Any:
        """Worker-side duplicate check + launch (all off the GUI thread).

        Returns ('launched', handle) | ('duplicate', handles) — the page
        renders either honestly; the engine service stays the launch
        authority (argv-only spawn, tool gate)."""
        running = tuple(
            handle for handle in self._backend.mirror_list(serial)
            if handle.exit_code is None)
        if running:
            return "duplicate", running
        return "launched", self._backend.mirror_launch(serial, LAUNCH_OPTIONS)

    def _apply_launch(self, serial: str, outcome: Any,
                      exc: Optional[BaseException]) -> None:
        if self._launching_serial != serial:
            return  # superseded launch attempt — never touch state
        self._launching_serial = None
        if exc is not None:
            failure_text = engine_error_text(exc)
            self._launch_error = (
                f"launch refused: {failure_text}"
                if isinstance(exc, ToolNotValidated) else
                f"launch failed: {failure_text}")
            self._handle_state = "failed"
            self._handle_note = failure_text
        elif outcome[0] == "launched":
            handle = outcome[1]
            self._launched_serials.add(handle.serial or serial)
            self._launch_error = None
            self._launch_note = (
                f"launch recorded: pid {handle.pid} for "
                f"{handle.serial or serial} — {LAUNCH_COMPLEXITY_NOTE}")
            # release the in-flight marker on the controls TOO (the user
            # must be able to issue the next launch/list/stop right away),
            # THEN refresh handles below to show real registry state
            self._render_lifecycle()
            self._sync_controls()
            self._on_list_handles()
        else:  # duplicate
            self._launch_error = (
                "a mirror is already running for "
                f"{serial} (pid(s) "
                + ", ".join(str(h.pid) for h in outcome[1])
                + ") — duplicate launches are refused")
            self._launch_note = None
        self._render_lifecycle()
        self._sync_controls()

    def _on_list_handles(self) -> None:
        serial = self._selected_serial
        if serial is None or self._launching_serial is not None:
            return
        started = self._workers.run(
            "mirror_handles",
            lambda: self._backend.mirror_list(serial),
            lambda handles: self._apply_handles(serial, tuple(handles), None),
            lambda exc: self._apply_handles(serial, (), exc),
        )
        if not started:
            return  # same-slot listing pending
        self._handle_state = "listing"
        self._render_lifecycle()

    def _apply_handles(self, serial: str, handles: tuple,
                       exc: Optional[BaseException]) -> None:
        if self._launching_serial is not None:
            return  # never clobber an in-flight launch's honest state
        if exc is not None:
            self._handle_state = "failed"
            self._handle_note = engine_error_text(exc)
        else:
            self._handles = handles
            self._handle_state = "ready"
            self._handle_note = None
        self._render_handles()
        self._render_lifecycle()
        self._sync_controls()

    def _on_stop(self) -> None:
        serial = self._selected_serial
        if serial is None or not self._target_valid():
            return  # control disabled in these states; defensive no-op
        started = self._workers.run(
            "mirror_stop",
            lambda: self._backend.mirror_stop(serial, None),
            lambda stopped: self._apply_stop(serial, tuple(stopped), None),
            lambda exc: self._apply_stop(serial, (), exc),
        )
        if not started:
            return  # same-slot stop pending
        self._stop_note = "stopping mirrors…"
        self._render_lifecycle()

    def _apply_stop(self, serial: str, stopped: tuple,
                    exc: Optional[BaseException]) -> None:
        if exc is not None:
            self._stop_note = f"stop failed: {engine_error_text(exc)}"
        else:
            self._stop_note = (
                "stop done: "
                + (", ".join(str(pid) for pid in stopped) if stopped
                   else "nothing was running"))
            self._launched_serials.discard(serial)
            self._launch_note = None  # the stop outcome replaces it
        self._render_lifecycle()
        self._sync_controls()
        self._on_list_handles()

    # ------------------------------------------------------------------ #
    # rendering + control enablement (GUI thread only)
    # ------------------------------------------------------------------ #

    def _render_all(self) -> None:
        self._render_devices_banner()
        self._target_banner.setText(self._target_text())
        self._render_tool_panel()
        self._render_lifecycle()
        self._render_handles()

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
            return ("no device selected — launching and stopping mirrors "
                    "need an explicitly selected connected device")
        state = device.state.value if device is not None else "unknown"
        return f"selected target: {self._selected_serial} (state: {state})"

    def _render_tool_panel(self) -> None:
        if self._tool_status is not None:
            status = self._tool_status
            word = _TOOL_STATE_WORDS[status.state]
            path = f" (path: {status.path})" if status.path else ""
            ok = status.state is ToolState.VALIDATED
            self._tool_banner.setText(
                f"scrcpy tool state: {word}{path} — "
                + ("launches are allowed when a device is selected."
                   if ok else
                   "launches are REFUSED until the tool is validated "
                   "(engine ToolProvisioningService workflow; the desktop "
                   "screen does not provision tools)."))
        elif self._tool_error is not None:
            self._tool_banner.setText(
                f"tool state check failed: {self._tool_error} — nothing is "
                "claimed; the engine re-checks at launch time.")
        else:
            self._tool_banner.setText(
                "scrcpy tool state not fetched yet — the engine checks it "
                "again at launch time regardless.")

    def _lifecycle_text(self) -> str:
        if self._launching_serial is not None:
            return f"launching scrcpy for {self._launching_serial}…"
        if self._launch_error is not None:
            return self._launch_error
        if self._launch_note is not None:
            return self._launch_note
        if self._stop_note is not None:
            return self._stop_note
        if self._handle_state == "listing":
            return "reading the mirror registry…"
        if self._handle_state == "failed" and self._handle_note:
            return f"registry read failed: {self._handle_note}"
        return ("no launch in flight — Launch mirror only records a real "
                "scrcpy process; window visibility is never claimed.")

    def _render_lifecycle(self) -> None:
        self._lifecycle_banner.setText(self._lifecycle_text())

    def _render_handles(self) -> None:
        self._handles_model.set_handles(
            self._handles,
            self._handle_note or "no mirrors running for the target")

    def _sync_controls(self) -> None:
        reason: Optional[str] = None
        device = self._selected_row()
        if device is None:
            reason = ("no device selected — select one in the device list"
                      if self._devices else
                      "no devices discovered yet — refresh first")
        elif device.state is not _ACTIONABLE:
            reason = (f"selected device is {device.state.value}; mirroring "
                      "needs a connected, authorized device")
        launching = self._launching_serial is not None
        self._launch_button.setEnabled(reason is None and not launching)
        self._stop_button.setEnabled(
            reason is None and self._launching_serial is None)
        self._handles_button.setEnabled(
            reason is None and self._launching_serial is None)
        for widget in (self._launch_button, self._stop_button,
                       self._handles_button):
            if reason is not None:
                widget.setToolTip(reason)
        if launching:
            self._launch_button.setToolTip(
                f"a launch is already in flight for {self._launching_serial} "
                "— duplicate launches are refused")


def _now_stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")
