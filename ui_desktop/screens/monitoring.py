"""Live monitoring (Stage 12, SC-6 desktop parity): honest observation.

The Qt counterpart of the TUI monitoring screen, on the exact same engine
semantics:

* Polling runs as a MONITORING_SESSION job on the engine worker thread —
  the poll loop NEVER runs on the GUI thread; each poll emits a typed
  ``HardwareUsageSnapshot`` payload delivered by the shell's
  ``QtJobEventBridge`` hub (queued to GUI-thread slots). Events are
  accepted only while their job id is this page's tracked session id AND
  its serial is still the selected target — a snapshot from a finished
  session or a superseded target can never clobber the current view.
* The usage table shows exactly the engine's three observation states.
  ``NOT_OBSERVED`` renders as "not observed in this poll" — NEVER as
  "not in use" (the absence of a marker in one poll is not proof of
  inactivity). Evidence lines are shown so a human can verify any
  active claim; probe failures render as "unknown (probe failed)".
* "Read sensors once" is the honest one-shot R-04 read: rows the device
  actually reported, plus an explicit UNAVAILABLE row with the reason
  when nothing was parseable — no invented rows or values, ever.
* Stop requests cancellation through the backend (targeted — the device's
  scans/listings are never cancelled with it); the terminal event
  confirms it. After three consecutive failed polls the engine aborts
  the session itself and the abort reason is shown verbatim (no quiet
  restart).

Honesty boundary (SCOPE): this is HOST-SIDE observation via read-only
``dumpsys`` polls. It is NOT continuous Android background monitoring —
no always-on device service, no push channel exists. The page states
this distinction unmissably.

Threading model: zero subprocess and zero ADB imports here; all engine
calls go through :class:`~ui_desktop.backend.DesktopBackend` inside
``WorkerCoordinator`` slots or the job system; no widget is touched from
a worker thread.
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

from vscanner.core.events import (
    JobKind,
    JobSnapshotStreamEvent,
    JobState,
    JobTerminalEvent,
)
from vscanner.core.models import (
    ConnectionInfo,
    DeviceState,
    HardwareUsageSnapshot,
    ObservationState,
    SensorReading,
    SensorStatus,
)

from .. import theme
from ..backend import DesktopBackend
from ..jobs_bridge_qt import JobEventSignalHub
from ..workers import WorkerCoordinator
from ..widgets import Panel, StatusChip, button
from .devices import DevicesTableModel, engine_error_text

__all__ = ["MonitoringPage"]

_OBSERVATION_WORDS = {
    ObservationState.OBSERVED_ACTIVE: "OBSERVED ACTIVE",
    ObservationState.NOT_OBSERVED: "not observed in this poll",
    ObservationState.UNKNOWN: "unknown (probe failed)",
}

_SENSOR_STATUS_WORDS = {
    SensorStatus.AVAILABLE: "available",
    SensorStatus.UNAVAILABLE: "unavailable",
}

_ACTIONABLE = DeviceState.DEVICE


def _plain(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ")
    return " ".join(text.split())[:160]


def _evidence_for(snapshot: HardwareUsageSnapshot, capability: str) -> str:
    for capability_name, line in snapshot.evidence:
        if capability_name == capability:
            return line
    return ""


# ===========================================================================
# table models
# ===========================================================================

class ObservationsTableModel(QAbstractTableModel):
    """One row per capability — the exact engine observation words.

    Rows come exclusively from the last typed ``HardwareUsageSnapshot``:
    camera/microphone/location states, per-capability raw evidence, the
    engine-reported failed probes, and the capture timestamp footer. No
    count, percentage, or "in use" claim is ever invented here."""

    _HEADERS = ("Capability", "Observation", "Evidence (device output)")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[tuple[str, str, str], ...] = ()

    def set_snapshot(self, snapshot: Optional[HardwareUsageSnapshot]) -> None:
        self.beginResetModel()
        self._rows = () if snapshot is None else tuple(
            self._snapshot_rows(snapshot))
        self.endResetModel()

    @staticmethod
    def _snapshot_rows(snapshot: HardwareUsageSnapshot
                       ) -> tuple[tuple[str, str, str], ...]:
        rows: list[tuple[str, str, str]] = []
        for capability, state in (
                ("camera", snapshot.camera),
                ("microphone", snapshot.microphone),
                ("location", snapshot.location)):
            rows.append((
                capability, _OBSERVATION_WORDS[state],
                _plain(_evidence_for(snapshot, capability)) or "—",
            ))
        for failed_capability in snapshot.failures:
            rows.append((
                failed_capability, "unknown (probe failed)",
                "the read-only probe errored; nothing is claimed for this "
                "capability in this poll",
            ))
        captured = snapshot.captured_at
        if captured is not None:
            rows.append(("snapshot captured at (UTC)", str(captured), "—"))
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
        key, observation, evidence = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (key, observation, evidence)[index.column()]
        return None

    @property
    def rows(self) -> tuple[tuple[str, str, str], ...]:
        return self._rows


class SensorsTableModel(QAbstractTableModel):
    """One row per honest sensor reading (R-04): device-reported values or
    an explicit UNAVAILABLE word with its reason — never both faked.

    With no rows yet the model renders a single honest placeholder row
    (state word differentiates "no read yet" from "read failed")."""

    _HEADERS = ("Sensor", "Status", "Values / reason")

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[tuple[str, str, str], ...] = ()
        self._note = "no read yet"

    def set_rows(self, rows, note: str) -> None:
        self.beginResetModel()
        self._rows = tuple(
            (reading.name, _SENSOR_STATUS_WORDS[reading.status],
             ", ".join(reading.values) or reading.reason or "—")
            for reading in rows)
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
                return ("—", self._note, "—")[index.column()]
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row[index.column()]
        return None

    @property
    def rows(self) -> tuple[tuple[str, str, str], ...]:
        return self._rows


# ===========================================================================
# the page
# ===========================================================================

class MonitoringPage(QWidget):
    """One cached per-section monitoring page (never reconstructed)."""

    def __init__(self, backend: DesktopBackend, hub: JobEventSignalHub,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._hub = hub
        self._workers = WorkerCoordinator(self)

        self.setAccessibleName("Live monitoring")

        # discovery state (same honest pattern as the device workspace)
        self._devices: tuple[ConnectionInfo, ...] = ()
        self._devices_state = "idle"  # idle | loading | refreshed | failed
        self._devices_error: Optional[str] = None
        self._refresh_stamp: Optional[str] = None
        self._auto_refresh_done = False
        self._selected_serial: Optional[str] = None

        # poll session state
        self._poll_job_id: Optional[str] = None
        self._poll_job_serial: Optional[str] = None
        self._poll_state = "none"  # none | running | stopped | aborted | failed
        self._poll_note: Optional[str] = None
        self._poll_count = 0
        self._last_snapshot: Optional[HardwareUsageSnapshot] = None

        # one-shot sensor state
        self._sensor_state = "idle"  # idle | reading | ok | failed
        self._sensor_error: Optional[str] = None
        self._sensor_serial: Optional[str] = None

        self._building = False
        self._build_ui()
        self._render_all()
        # Subscribe ONCE — the shell caches one widget per section, so
        # repeated navigation cannot create duplicate subscriptions.
        self._hub.snapshot.connect(self._on_snapshot_event)
        self._hub.terminal.connect(self._on_terminal_event)

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACING["s"])

        # Banner strip: chip + the honesty framing + explicit refresh
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

        self._scope_banner = QLabel(
            "HOST-SIDE observation only: each poll is one read-only "
            "dumpsys snapshot the user starts and stops explicitly. This "
            "is NOT continuous Android background monitoring — no "
            "always-on device service and no push channel exists.")
        self._scope_banner.setObjectName("hintText")
        self._scope_banner.setWordWrap(True)
        self._scope_banner.setAccessibleName("Monitoring scope")
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
        self._devices_table.setObjectName("monitoringDevicesTable")
        self._devices_table.setModel(self._devices_model)
        self._devices_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._devices_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._devices_table.horizontalHeader().setStretchLastSection(True)
        self._devices_table.setMinimumHeight(110)
        self._devices_table.setAccessibleName("Discovered devices")
        self._devices_table.selectionModel().currentRowChanged.connect(
            self._on_selection_changed)
        devices_layout.addWidget(self._devices_table)
        splitter.addWidget(devices_panel)

        # --- usage / sensors panel ------------------------------------------
        usage_panel = Panel(splitter)
        usage_layout = Panel.body_layout(usage_panel)

        # live poll session
        poll_row = QHBoxLayout()
        poll_row.setContentsMargins(0, 0, 0, 0)
        poll_row.setSpacing(theme.SPACING["m"])
        self._poll_button = button(
            "Start live poll", variant="primary",
            tooltip="Start the MONITORING_SESSION job on the engine worker "
                    "thread (read-only dumpsys polls, 2 s interval) for the "
                    "explicitly selected device",
            accessible_name="Start live poll")
        self._poll_button.clicked.connect(self._on_toggle_poll)
        poll_row.addWidget(self._poll_button, 1)
        usage_layout.addLayout(poll_row)

        self._poll_banner = QLabel("", self)
        self._poll_banner.setObjectName("secondaryText")
        self._poll_banner.setWordWrap(True)
        usage_layout.addWidget(self._poll_banner)

        self._usage_model = ObservationsTableModel()
        self._usage_table = QTableView(usage_panel)
        self._usage_table.setObjectName("usageTable")
        self._usage_table.setModel(self._usage_model)
        self._usage_table.horizontalHeader().setStretchLastSection(True)
        self._usage_table.setMinimumHeight(110)
        self._usage_table.setAccessibleName("Capability observations")
        usage_layout.addWidget(self._usage_table, 1)

        # one-shot sensor read
        sensors_row = QHBoxLayout()
        sensors_row.setContentsMargins(0, 0, 0, 0)
        sensors_row.setSpacing(theme.SPACING["m"])
        self._sensors_button = button(
            "Read sensors once", variant="secondary",
            tooltip="One honest dumpsys sensorservice read in a background "
                    "worker (deduped; rows the device reported only)",
            accessible_name="Read sensors once")
        self._sensors_button.clicked.connect(self._on_read_sensors)
        sensors_row.addWidget(self._sensors_button, 1)
        usage_layout.addLayout(sensors_row)

        self._sensors_banner = QLabel("", self)
        self._sensors_banner.setObjectName("secondaryText")
        self._sensors_banner.setWordWrap(True)
        usage_layout.addWidget(self._sensors_banner)

        self._sensors_model = SensorsTableModel()
        self._sensors_table = QTableView(usage_panel)
        self._sensors_table.setObjectName("sensorsTable")
        self._sensors_table.setModel(self._sensors_model)
        self._sensors_table.horizontalHeader().setStretchLastSection(True)
        self._sensors_table.setMinimumHeight(90)
        self._sensors_table.setAccessibleName("Sensor readings")
        usage_layout.addWidget(self._sensors_table, 1)

        note = QLabel(
            "NOT_OBSERVED means the probe ran and matched nothing — it is "
            "never rendered as \"not in use\". Sensor rows are "
            "device-reported only; an unavailable row carries the honest "
            "reason (nothing is invented).")
        note.setObjectName("hintText")
        note.setWordWrap(True)
        usage_layout.addWidget(note)
        splitter.addWidget(usage_panel)
        outer.addWidget(splitter, 1)

    # ------------------------------------------------------------------ #
    # lifecycle hooks the shell uses
    # ------------------------------------------------------------------ #

    def activate(self) -> None:
        """First activation runs exactly ONE auto-discovery (desktop
        convention); later activations are honest no-ops — discovery is
        on-demand, never a polling loop."""
        if not self._auto_refresh_done and self._devices_state == "idle":
            self._auto_refresh_done = True
            self.refresh_devices()

    def shutdown(self) -> None:
        """Owner-close hook: disconnect the hub + stop worker threads."""
        for sig, handler in (
                (self._hub.snapshot, self._on_snapshot_event),
                (self._hub.terminal, self._on_terminal_event)):
            try:
                sig.disconnect(handler)
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
        """Same desktop selection contract as the device workspace:
        preserve the selection while the serial is still present; with
        exactly one actionable device and nothing selected, preselect it
        (the unambiguous case); with several devices NOTHING is
        auto-selected."""
        if not self._devices:
            return
        if self._selected_serial is not None and any(
                d.serial == self._selected_serial and d.state is _ACTIONABLE
                for d in self._devices):
            return  # keep the explicit selection
        actionable = [d for d in self._devices if d.state is _ACTIONABLE]
        if len(actionable) == 1 and self._selected_serial is None:
            self.select_serial(actionable[0].serial)

    # ------------------------------------------------------------------ #
    # selection (explicit; stale targets never keep acting)
    # ------------------------------------------------------------------ #

    def _on_selection_changed(self, current, _previous) -> None:
        serial = self._devices_model.serial_at(current.row()) \
            if current is not None and current.isValid() else None
        if serial is not None:
            self.select_serial(serial)

    def select_serial(self, serial: str) -> None:
        """Explicitly change the monitoring target.

        A running poll bound to a DIFFERENT device is stopped (targeted
        cancel); its late snapshots are dropped by the serial guard so
        they can never be shown as the new target's results. The sensor
        read is superseded the same way."""
        serial = str(serial)
        if serial == self._selected_serial:
            return
        self._selected_serial = serial
        if self._poll_job_serial is not None and \
                self._poll_job_serial != serial:
            self._backend.stop_monitoring(self._poll_job_serial)
            self._poll_note = ("stop requested for the previous target "
                               f"{self._poll_job_serial} — the terminal "
                               "event will confirm it")
        self._last_snapshot = None
        self._usage_model.set_snapshot(None)
        self._sensor_state = "idle"
        self._sensor_error = None
        self._sensors_model.set_rows((), "no read yet")
        self._render_all()
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
    # poll session (MONITORING_SESSION job)
    # ------------------------------------------------------------------ #

    def _on_toggle_poll(self) -> None:
        if self._poll_state == "running":
            if self._poll_job_serial is not None:
                self._backend.stop_monitoring(self._poll_job_serial)
                self._poll_note = ("stop requested — the terminal event "
                                   "will confirm it")
                self._poll_state = "stopping"
                self._render_poll_panel()
            return
        if not self._target_valid():
            return  # control disabled in these states; defensive no-op
        serial = str(self._selected_serial or "")
        try:
            handle = self._backend.start_monitoring_session(serial,
                                                            interval_s=2.0)
        except Exception as exc:
            self._poll_state = "failed"
            self._poll_note = engine_error_text(exc)
            self._render_poll_panel()
            return
        self._poll_job_id = handle.id
        self._poll_job_serial = serial
        self._poll_state = "running"
        self._poll_note = None
        self._poll_count = 0
        self._last_snapshot = None
        self._usage_model.set_snapshot(None)
        self._render_poll_panel()
        self._sync_controls()

    def _on_snapshot_event(self, event: JobSnapshotStreamEvent) -> None:
        """Snapshot channel — accept only THIS session's payloads while
        their serial is still the selected target (late events from a
        finished session or a changed target are dropped, never shown).
        Identity comes from the tracked job id and the typed payload's
        own serial field (events carry no separate serial lane)."""
        if self._poll_job_id is None or event.job_id != self._poll_job_id:
            return  # late event from a superseded/finished session
        payload = event.payload
        if not isinstance(payload, HardwareUsageSnapshot):
            return  # honest pass: foreign payload types are never rendered
        if payload.serial is not None and \
                payload.serial != self._selected_serial:
            return  # the user moved to another target — not ours to show
        self._last_snapshot = payload
        self._poll_count += 1
        self._usage_model.set_snapshot(payload)
        self._render_poll_panel()

    def _on_terminal_event(self, event: JobTerminalEvent) -> None:
        if event.kind is not JobKind.MONITORING_SESSION:
            return
        if event.job_id != self._poll_job_id:
            return  # late event from a superseded session — never touch state
        self._poll_job_id = None
        self._poll_job_serial = None
        if event.outcome is JobState.CANCELLED:
            self._poll_state = "stopped"
            self._poll_note = (
                f"{self._poll_count} poll(s) completed this session — "
                "snapshots below stay on screen")
        elif event.outcome is JobState.SUCCEEDED:
            result = event.result
            if isinstance(result, dict):
                reason = result.get("reason") or "unknown reason"
                polls = result.get("polls_completed", "?")
                self._poll_note = \
                    f"{reason} ({polls} poll(s) completed)"
            else:
                self._poll_note = "session aborted"
            self._poll_state = "aborted"
        else:
            self._poll_state = "failed"
            self._poll_note = (
                "session failed" if event.error is None else
                engine_error_text(event.error))
        self._render_poll_panel()
        self._sync_controls()

    # ------------------------------------------------------------------ #
    # one-shot sensors (deduped background worker; superseded reads dropped)
    # ------------------------------------------------------------------ #

    def _on_read_sensors(self) -> None:
        if not self._target_valid():
            return  # control disabled in these states; defensive no-op
        serial = str(self._selected_serial or "")
        started = self._workers.run(
            "read_sensors",
            lambda: self._backend.read_sensors_once(serial),
            lambda rows: self._on_sensors_done(serial, tuple(rows)),
            lambda exc: self._on_sensors_failed(serial, exc),
        )
        if not started:
            return  # same-slot read pending: it finishes and re-enables
        self._sensor_state = "reading"
        self._sensor_serial = serial
        self._sync_controls()
        self._render_sensors_panel()

    def _on_sensors_done(self, serial: str, rows: tuple) -> None:
        if serial != self._selected_serial:
            return  # superseded read — never fill stale rows
        self._sensor_state = "ok"
        self._sensor_error = None
        self._sensors_model.set_rows(
            rows,
            f"{len(rows)} honest row(s) — unavailable rows carry their "
            "reason, nothing invented" if rows else "no rows",
        )
        self._sync_controls()
        self._render_sensors_panel()

    def _on_sensors_failed(self, serial: str, exc: BaseException) -> None:
        if serial != self._selected_serial:
            return  # superseded read — a transport error is not a verdict
        self._sensor_state = "failed"
        self._sensor_error = engine_error_text(exc)
        self._sensors_model.set_rows((), "read failed")
        self._sync_controls()
        self._render_sensors_panel()

    # ------------------------------------------------------------------ #
    # rendering + control enablement (GUI thread only)
    # ------------------------------------------------------------------ #

    def _render_all(self) -> None:
        self._render_devices_banner()
        self._render_target()
        self._render_poll_panel()
        self._render_sensors_panel()

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
        self._render_target()

    def _render_target(self) -> None:
        self._target_banner.setText(self._target_text())

    def _target_text(self) -> str:
        device = self._selected_row()
        if self._selected_serial is None:
            return ("no device selected — polls and sensor reads need an "
                    "explicitly selected connected device")
        state = device.state.value if device is not None else "unknown"
        return (f"selected target: {self._selected_serial} "
                f"(state: {state})")

    def _render_poll_panel(self) -> None:
        banner = self._poll_banner
        if self._poll_state == "running":
            banner.setText(
                f"live poll RUNNING on {self._poll_job_serial} · "
                f"{self._poll_count} snapshot(s) streamed this session · "
                "never rendered as ground truth — read the states honestly "
                "(not-observed \u2260 not in use)")
        elif self._poll_state == "stopping":
            banner.setText(self._poll_note or "stop requested…")
        elif self._poll_state == "stopped":
            banner.setText(f"session stopped by request — {self._poll_note}")
        elif self._poll_state == "aborted":
            banner.setText(
                f"session ABORTED by the engine: {self._poll_note} — shown "
                "verbatim, no quiet restart")
        elif self._poll_state == "failed":
            banner.setText(f"session failed to start: {self._poll_note}")
        else:
            banner.setText(
                "no session yet — Start live poll opens one for the "
                "selected device (refresh/cancel are explicit).")

    def _render_sensors_panel(self) -> None:
        banner = self._sensors_banner
        if self._sensor_state == "idle":
            banner.setText("no sensor read yet — Read sensors once runs one "
                           "honest read in the background.")
        elif self._sensor_state == "reading":
            banner.setText("reading sensor values in the background…")
        elif self._sensor_state == "failed":
            banner.setText(
                f"sensor read failed: {self._sensor_error} — flagged, "
                "never shown as data")
        else:
            banner.setText(
                f"One-shot read for {self._sensor_serial} completed — "
                "rows are exactly what the device reported.")

    def _sync_controls(self) -> None:
        """Enable target-dependent controls honestly:
        a selected, currently listed DEVICE-state row is required."""
        reason: Optional[str] = None
        device = self._selected_row()
        if device is None:
            reason = ("no device selected — select one in the device list"
                      if self._devices else
                      "no devices discovered yet — refresh first")
        elif device.state is not _ACTIONABLE:
            reason = (f"selected device is {device.state.value}; monitoring "
                      "needs a connected, authorized device")
        running = self._poll_state in ("running", "stopping")
        reading = self._sensor_state == "reading"

        self._poll_button.setEnabled(
            reason is None and not (running and self._poll_state == "stopping"))
        if running:
            self._poll_button.setText(
                "Stop live poll" if self._poll_state == "running"
                else "Stopping…")
        else:
            self._poll_button.setText("Start live poll")
        self._poll_button.setToolTip(
            ("Request cancellation of the running MONITORING_SESSION "
             "(the terminal event completes the stop)")
            if self._poll_state == "running" else
            "Start the MONITORING_SESSION job on the engine worker thread "
            "(read-only dumpsys polls, 2 s interval) for the explicitly "
            "selected device")
        self._sensors_button.setEnabled(reason is None and not reading)
        for widget in (self._poll_button, self._sensors_button):
            if reason is not None:
                widget.setToolTip(reason)


def _now_stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")
