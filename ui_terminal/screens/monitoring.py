"""Live monitoring (Stage 08, SC-6): honest device observation.

What this screen promises (and how):

* Polling runs as a MONITORING_SESSION job on the engine worker thread —
  the loop NEVER runs on the UI thread (contract §5); each poll emits a
  typed :class:`~vscanner.core.models.HardwareUsageSnapshot` payload which
  the pump marshals here (events are ignored unless they carry this
  screen's job id — the foreign-jobs pattern shared with scan/reports).
* The usage table shows exactly the three honest observation states
  (OBSERVED_ACTIVE / NOT_OBSERVED / UNKNOWN). NOT_OBSERVED is deliberately
  rendered as "not observed in this poll" — never as "not in use" — and
  evidence lines are shown so a human can verify any active claim.
* ``v`` performs a one-shot honest sensor read (R-04): rows the device
  actually reported, with an explicit unavailable-reason row when the
  device produced nothing parseable — no invented rows, no invented
  values, ever.
* Stop semantics: ``m`` toggles the session; stopping requests
  cancellation and the screen shows the honest terminal outcome. After
  three consecutive failed polls the engine aborts the session itself and
  the abort reason is displayed verbatim.
"""

from __future__ import annotations

from typing import Optional, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Label

from vscanner.core.events import (
    JobSnapshotStreamEvent,
    JobTerminalEvent,
)
from vscanner.core.models import (
    HardwareUsageSnapshot,
    ObservationState,
    SensorReading,
    SensorStatus,
)

from ui_terminal.backend import DeviceBackend
from ui_terminal.screens.shell import ShellScreen

__all__ = ["LiveMonitoringScreen"]

_OBSERVATION_WORDS = {
    ObservationState.OBSERVED_ACTIVE: "OBSERVED ACTIVE",
    ObservationState.NOT_OBSERVED: "not observed in this poll",
    ObservationState.UNKNOWN: "unknown (probe failed)",
}

_SENSOR_STATUS_WORDS = {
    SensorStatus.AVAILABLE: "available",
    SensorStatus.UNAVAILABLE: "unavailable",
}


class LiveMonitoringScreen(ShellScreen):
    """Honest live poll of camera/mic/location + one-shot sensor rows."""

    SECTION_ID = "monitoring"

    BINDINGS = [
        Binding("r", "refresh", "Refresh devices"),
        Binding("m", "toggle_poll", "Start/stop live poll"),
        Binding("v", "sensors_once", "Read sensors once"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._devices: tuple = ()
        self._discovery_state = "idle"  # idle | no-adb | discovering | ok | empty | failed
        self._discovery_error: Optional[str] = None
        self._selected_serial: Optional[str] = None
        self._poll_job_id: Optional[str] = None
        self._poll_state = "none"       # none | running | stopped | aborted | failed
        self._poll_note: Optional[str] = None
        self._last_snapshot: Optional[HardwareUsageSnapshot] = None
        self._sensor_state = "idle"     # idle | reading | ok | failed
        self._sensor_rows: tuple = ()
        self._sensor_error: Optional[str] = None
        self._poll_count = 0

    @property
    def backend(self) -> DeviceBackend:
        return cast(DeviceBackend, getattr(self.app, "backend"))

    # -- composition ----------------------------------------------------------- #

    def inner_body(self) -> ComposeResult:
        with Vertical(id="mon-body"):
            yield Label("", id="mon-device", classes="status-muted")
            yield DataTable(id="mon-devices", cursor_type="row")
            yield Label(
                "live polls run on the engine worker thread and stream "
                "typed snapshots here; nothing touches the device besides "
                "read-only dumpsys probes",
                id="mon-explain", classes="status-muted",
            )
            yield Label("", id="mon-poll", classes="status-muted")
            yield DataTable(id="mon-usage", show_cursor=False)
            yield Label(
                "sensor rows are device-reported only; an unavailable row "
                "carries the honest reason (R-04 — nothing is invented)",
                id="mon-sensors-note", classes="status-muted",
            )
            yield DataTable(id="mon-sensors", show_cursor=False)

    def on_mount(self) -> None:
        super().on_mount()
        devices = self.query_one("#mon-devices", DataTable)
        devices.add_columns("Serial", "State", "Model")
        usage = self.query_one("#mon-usage", DataTable)
        usage.add_columns("Capability", "Observation", "Evidence (device output)")
        sensors = self.query_one("#mon-sensors", DataTable)
        sensors.add_columns("Sensor", "Status", "Values / reason")
        self._apply_all()
        self.action_refresh()

    def status_hint(self) -> str:
        if self._poll_state == "running":
            return (f"monitoring · polling {self._selected_serial or '—'} · "
                    f"{self._poll_count} poll(s) · stop with m")
        if self._poll_state == "aborted":
            return "monitoring · session aborted by the engine (repeated failures)"
        if self._poll_state == "stopped":
            return "monitoring · session stopped by request"
        if self._poll_state == "failed":
            return "monitoring · session start failed"
        return "monitoring · r refresh · m start/stop live poll · v sensors once"

    def _apply_all(self) -> None:
        self._render_devices()
        self._render_device_line()
        self._render_poll()
        self._render_usage()
        self._render_sensors()
        self.refresh_status()

    # -- device discovery (worker, scan-screen pattern) ------------------------- #

    def action_refresh(self) -> None:
        backend = self.backend
        try:
            saved = backend.adb_path_saved()
        except Exception as exc:
            self._discovery_state = "failed"
            self._discovery_error = _failure_word(exc)
            self._apply_all()
            return
        if saved is None:
            self._discovery_state = "no-adb"
            self._apply_all()
            return
        self._discovery_state = "discovering"
        self._apply_all()

        def work() -> None:
            try:
                devices = backend.list_devices()
            except Exception as exc:
                self.app.call_from_thread(
                    self._apply_discovery, (), _failure_word(exc))
            else:
                self.app.call_from_thread(
                    self._apply_discovery, tuple(devices), None)

        self.app.run_worker(
            work, group="mon-refresh", exclusive=True, thread=True,
            exit_on_error=False, description="monitoring device discovery",
        )

    def _apply_discovery(self, devices: tuple, reason: Optional[str]) -> None:
        if reason is not None:
            self._discovery_state = "failed"
            self._discovery_error = reason
            self._apply_all()
            return
        self._devices = tuple(devices)
        self._discovery_state = "ok" if devices else "empty"
        actionable = [d.serial for d in devices if d.state.value == "device"]
        if self._selected_serial is not None and not any(
                d.serial == self._selected_serial
                and d.state.value == "device" for d in devices):
            self._selected_serial = None
            self._poll_state = "none"
            self._poll_note = "target left the device list"
        elif self._selected_serial is None and actionable:
            self._selected_serial = actionable[0]
        self._apply_all()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "mon-devices":
            serial = event.row_key.value
            if serial:
                self._selected_serial = serial
                self._apply_all()

    # -- rendering ---------------------------------------------------------------- #

    def _render_devices(self) -> None:
        table = self.query_one("#mon-devices", DataTable)
        table.clear()
        for info in self._devices:
            table.add_row(
                info.serial,
                info.state.value,
                _plain(info.usb_props.get("model")),
                key=info.serial,
            )

    def _render_device_line(self) -> None:
        line = self.query_one("#mon-device", Label)
        if self._selected_serial:
            line.update(
                f"target {self._selected_serial} · poll state: "
                f"{self._poll_state}")
        else:
            line.update(
                "no device selected (enter on a device row) — polls and "
                "sensor reads need a target")

    def _render_poll(self) -> None:
        label = self.query_one("#mon-poll", Label)
        label.set_classes("status-muted")
        if self._poll_state == "running":
            label.update(
                f"live poll RUNNING · {self._poll_count} snapshot(s) "
                "streamed this session · never rendered as ground truth — "
                "read the states honestly (not-observed ≠ not in use)")
            label.set_classes("status-ok")
        elif self._poll_state == "aborted":
            label.update(
                f"session ABORTED: {self._poll_note} — shown verbatim, no "
                "quiet restart")
            label.set_classes("status-warn")
        elif self._poll_state == "stopped":
            label.update(f"session stopped by request · {self._poll_count} "
                         "poll(s) completed · snapshots below stay on screen")
        elif self._poll_state == "failed":
            label.update(f"session failed to start: {self._poll_note}")
            label.set_classes("status-error")
        else:
            label.update("no session yet — press m to start the live poll")

    def _render_usage(self) -> None:
        table = self.query_one("#mon-usage", DataTable)
        table.clear()
        snapshot = self._last_snapshot
        if snapshot is None:
            table.add_row("—", "no snapshot yet", "start the poll with m")
            return
        for capability, state in (
                ("camera", snapshot.camera),
                ("microphone", snapshot.microphone),
                ("location", snapshot.location)):
            evidence = _plain(_evidence_for(snapshot, capability))
            table.add_row(capability, _OBSERVATION_WORDS[state],
                          evidence or "—")
        for failed_capability in snapshot.failures:
            table.add_row(
                failed_capability, "unknown (probe failed)",
                "the read-only probe errored; nothing is claimed for this "
                "capability in this poll")
        captured = getattr(snapshot, "captured_at", None)
        if captured is not None:
            table.add_row("snapshot captured at (UTC)", str(captured), "—")

    def _render_sensors(self) -> None:
        table = self.query_one("#mon-sensors", DataTable)
        table.clear()
        if self._sensor_state == "idle":
            table.add_row("—", "no read yet", "press v for one honest read")
            return
        if self._sensor_state == "failed":
            table.add_row("—", "read failed", self._sensor_error or "")
            return
        for reading in self._sensor_rows:
            values = ", ".join(reading.values) if reading.values else ""
            reason = reading.reason or ""
            table.add_row(
                reading.name, _SENSOR_STATUS_WORDS[reading.status],
                values or reason or "—",
            )

    # -- poll session (job) ------------------------------------------------------- #

    def action_toggle_poll(self) -> None:
        if self._selected_serial is None:
            self.notify(
                "select a device first (enter on a device row)",
                title="Live monitoring", severity="warning",
            )
            return
        if self._poll_state == "running":
            self.backend.stop_monitoring(self._selected_serial)
            self.notify(
                "stop requested — the terminal event will confirm it",
                title="Live monitoring", severity="information",
            )
            return
        try:
            handle = self.backend.start_monitoring_session(
                self._selected_serial, interval_s=2.0)
        except Exception as exc:
            self._poll_state = "failed"
            self._poll_note = _failure_word(exc)
            self._apply_all()
            return
        self._poll_job_id = handle.id
        self._poll_state = "running"
        self._poll_note = None
        self._apply_all()

    # -- sensors once (worker) ------------------------------------------------------ #

    def action_sensors_once(self) -> None:
        if self._selected_serial is None:
            self.notify(
                "select a device first (enter on a device row)",
                title="Sensor read", severity="warning",
            )
            return
        self._sensor_state = "reading"
        self._render_sensors()
        backend = self.backend
        serial = self._selected_serial

        def work() -> None:
            try:
                rows = backend.read_sensors_once(serial)
            except Exception as exc:
                self.app.call_from_thread(
                    self._apply_sensors, (), _failure_word(exc))
            else:
                self.app.call_from_thread(self._apply_sensors, rows, None)

        self.app.run_worker(
            work, group="mon-sensors", exclusive=True, thread=True,
            exit_on_error=False, description="one-shot sensor read",
        )

    def _apply_sensors(self, rows: tuple, failure: Optional[str]) -> None:
        if failure is not None:
            self._sensor_state = "failed"
            self._sensor_error = failure
            self._sensor_rows = ()
        else:
            self._sensor_state = "ok"
            self._sensor_error = None
            self._sensor_rows = tuple(rows)
        self._render_sensors()
        self.refresh_status()

    # -- job events (foreign-id filtering; snapshot channel) ------------------------- #

    def on_job_event(self, event) -> None:
        if event.job_id != self._poll_job_id:
            return
        if isinstance(event, JobSnapshotStreamEvent):
            payload = event.payload
            if isinstance(payload, HardwareUsageSnapshot):
                self._last_snapshot = payload
                self._poll_count += 1
                self._render_usage()
                self.refresh_status()
            return
        if isinstance(event, JobTerminalEvent):
            self._poll_job_id = None
            outcome = event.outcome.value
            if outcome == "cancelled":
                self._poll_state = "stopped"
            elif outcome == "succeeded":
                self._poll_state = "aborted"
                self._poll_note = _abort_word(event.result)
            else:
                self._poll_state = "failed"
                self._poll_note = _failure_word(event.error)
            self._render_poll()
            self.refresh_status()


def _evidence_for(snapshot: HardwareUsageSnapshot, capability: str) -> str:
    for capability_name, line in snapshot.evidence:
        if capability_name == capability:
            return line
    return ""


def _abort_word(result: object) -> str:
    if isinstance(result, dict):
        reason = result.get("reason") or "unknown reason"
        polls = result.get("polls_completed", "?")
        return f"{reason} ({polls} poll(s) completed)"
    return "session aborted"


def _plain(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ")
    return " ".join(text.split())[:120]


def _failure_word(exc: object) -> str:
    if exc is None:
        return "unknown failure"
    return f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"
