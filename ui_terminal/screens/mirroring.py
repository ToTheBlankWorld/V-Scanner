"""Screen mirroring (Stage 08, SC-8): honest scrcpy lifecycle.

* Launch requires a VALIDATED scrcpy tool (provisioning probe); running
  with a tool that was never validated, or failed validation, is refused
  with the typed honest message — the screen surfaces the refusal verbatim
  and never pretends a mirror started.
* The launch itself is scrcpy's own window (a real subprocess); this screen
  only commands the lifecycle (launch / list / stop) on worker threads.
* ``turn_screen_off`` is device-mutating: the checkbox route refuses it
  unless the explicit confirmation bit is set (model-enforced, SC-8).
* Handles shown are engine registry state including exit codes when
  observed; stopping by pid returns exactly what the service stopped.
"""

from __future__ import annotations

from typing import Optional, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Label

from vscanner.core.errors import ToolNotValidated
from vscanner.core.models import MirrorOptions

from ui_terminal.backend import DeviceBackend
from ui_terminal.screens.shell import ShellScreen

__all__ = ["MirroringScreen"]


class MirroringScreen(ShellScreen):
    """scrcpy mirror lifecycle: launch, list, stop (honest refusals)."""

    SECTION_ID = "mirroring"

    BINDINGS = [
        Binding("l", "launch", "Launch mirror"),
        Binding("r", "refresh_handles", "Show running mirrors"),
        Binding("k", "stop_all", "Stop mirrors (all for target)"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._selected_serial: Optional[str] = None
        self._devices: tuple = ()
        self._mirror_state = "idle"  # idle | launching | listing | refused | error
        self._mirror_note: Optional[str] = None
        self._handles: tuple = ()

    @property
    def backend(self) -> DeviceBackend:
        return cast(DeviceBackend, getattr(self.app, "backend"))

    # -- composition ----------------------------------------------------------- #

    def inner_body(self) -> ComposeResult:
        with Vertical(id="mr-body"):
            yield Label(
                "mirroring launches the validated scrcpy tool against the "
                "selected device (engine SC-8); a tool that was never "
                "validated or failed its probe is honestly refused",
                id="mr-explain", classes="status-muted",
            )
            yield DataTable(id="mr-devices", cursor_type="row")
            yield Label("", id="mirror-status", classes="status-muted")
            yield Label(
                "mirror handles (stop() with a pid returns only what it "
                "actually stopped; exit codes shown when observed)",
                id="mr-handles-note", classes="status-muted",
            )
            yield DataTable(id="mr-handles", show_cursor=False)

    def on_mount(self) -> None:
        super().on_mount()
        devices = self.query_one("#mr-devices", DataTable)
        devices.add_columns("Serial", "State", "Model")
        handles = self.query_one("#mr-handles", DataTable)
        handles.add_columns("pid", "Serial", "Launched (UTC)", "Exit code")
        self.action_refresh_devices()
        self.action_refresh_handles()

    def status_hint(self) -> str:
        if self._mirror_state == "launching":
            return "mirroring · launch in progress (worker thread)"
        if self._mirror_state == "refused":
            return ("mirroring · launch refused — validate scrcpy first "
                    "(Settings / Doctor), then retry")
        return "mirroring · l launch · r list handles · k stop"

    # -- devices ---------------------------------------------------------------- #

    def action_refresh_devices(self) -> None:
        backend = self.backend
        try:
            if backend.adb_path_saved() is None:
                self._render_devices(())
                return
        except Exception:
            self._render_devices(())
            return

        def work() -> None:
            try:
                devices = backend.list_devices()
            except Exception:
                self.app.call_from_thread(self._render_devices, ())
            else:
                self.app.call_from_thread(self._render_devices, tuple(devices))

        self.app.run_worker(
            work, group="mr-devices", exclusive=True, thread=True,
            exit_on_error=False, description="mirroring device discovery",
        )

    def _render_devices(self, devices: tuple) -> None:
        table = self.query_one("#mr-devices", DataTable)
        table.clear()
        self._devices = tuple(devices)
        actionable = [d.serial for d in self._devices
                      if d.state.value == "device"]
        if self._selected_serial is None and actionable:
            self._selected_serial = actionable[0]
        for info in self._devices:
            table.add_row(
                info.serial, info.state.value,
                _plain(info.usb_props.get("model")),
                key=info.serial,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "mr-devices":
            serial = event.row_key.value
            if serial:
                self._selected_serial = serial
                self.refresh_status()

    # -- lifecycle ---------------------------------------------------------------- #

    def action_launch(self) -> None:
        if self._selected_serial is None:
            self.notify(
                "select a device first", title="Mirroring", severity="warning")
            return
        # SC-8 defaults; screen-off needs its explicit confirmation and is
        # intentionally not offered through this plain launch path.
        options = MirrorOptions(
            resolution=1024, max_fps=30, turn_screen_off=False,
        )
        serial = self._selected_serial
        self._mirror_state = "launching"
        self._render_status()
        backend = self.backend

        def work() -> None:
            try:
                handle = backend.mirror_launch(serial, options)
            except ToolNotValidated as exc:
                self.app.call_from_thread(
                    self._apply_launch, None, f"ToolNotValidated: {_plain(exc)}")
            except Exception as exc:
                self.app.call_from_thread(
                    self._apply_launch, None, _plain(f"{type(exc).__name__}: {exc}"))
            else:
                self.app.call_from_thread(self._apply_launch, handle, None)

        self.app.run_worker(
            work, group="mr-launch", exclusive=True, thread=True,
            exit_on_error=False, description="scrcpy launch",
        )

    def _apply_launch(self, handle, failure: Optional[str]) -> None:
        if failure is not None:
            self._mirror_state = "refused" if "ToolNotValidated" in failure \
                else "error"
            self._mirror_note = failure
            self._render_status()
            self.refresh_status()
            return
        self._mirror_state = "idle"
        self._mirror_note = (
            f"mirror launched (pid {handle.pid}, serial "
            f"{handle.serial or '—'}); if no window appears, check the "
            "tool validation state in Settings / Doctor")
        self._render_status()
        self.action_refresh_handles()

    def action_refresh_handles(self) -> None:
        if self._mirror_state == "launching":
            return
        serial = self._selected_serial
        self._mirror_state = "listing"
        self._render_status()
        backend = self.backend

        def work() -> None:
            try:
                handles = backend.mirror_list(serial)
            except Exception as exc:
                self.app.call_from_thread(
                    self._apply_handles, (), _plain(f"{type(exc).__name__}: {exc}"))
            else:
                self.app.call_from_thread(self._apply_handles, tuple(handles), None)

        self.app.run_worker(
            work, group="mr-handles", exclusive=True, thread=True,
            exit_on_error=False, description="mirror handle list",
        )

    def _apply_handles(self, handles, failure: Optional[str]) -> None:
        if failure is not None:
            self._mirror_state = "error"
            self._mirror_note = failure
        else:
            self._mirror_state = "idle"
            self._handles = handles
        table = self.query_one("#mr-handles", DataTable)
        table.clear()
        if not failure:
            if not self._handles:
                table.add_row("—", "no mirrors running", "—", "—")
            for handle in self._handles:
                table.add_row(
                    str(handle.pid), handle.serial or "—",
                    handle.launched_at,
                    "running" if handle.exit_code is None
                    else f"exited ({handle.exit_code})",
                )
        self._render_status()
        self.refresh_status()

    def action_stop_all(self) -> None:
        if self._selected_serial is None:
            self.notify(
                "select a device first", title="Mirroring", severity="warning")
            return
        serial = self._selected_serial
        backend = self.backend

        def work() -> None:
            try:
                stopped = backend.mirror_stop(serial, None)
            except Exception as exc:
                self.app.call_from_thread(
                    self._apply_stop, (), _plain(f"{type(exc).__name__}: {exc}"))
            else:
                self.app.call_from_thread(self._apply_stop, tuple(stopped), None)

        self.app.run_worker(
            work, group="mr-stop", exclusive=True, thread=True,
            exit_on_error=False, description="mirror stop",
        )

    def _apply_stop(self, stopped: tuple, failure: Optional[str]) -> None:
        if failure is None:
            pids = ", ".join(str(pid) for pid in stopped) if stopped \
                else "nothing was running"
            self._mirror_note = f"stop done: {pids}"
        self._mirror_state = "idle" if failure is None else "error"
        self._mirror_note = self._mirror_note or failure
        self.action_refresh_handles()

    def _render_status(self) -> None:
        label = self.query_one("#mirror-status", Label)
        label.set_classes("status-muted")
        if self._mirror_state == "launching":
            label.update("launching scrcpy…")
            label.set_classes("status-ok")
        elif self._mirror_state == "refused":
            label.update(f"REFUSED: {self._mirror_note}")
            label.set_classes("status-error")
        elif self._mirror_state == "error":
            label.update(f"error: {self._mirror_note}")
            label.set_classes("status-error")
        elif self._mirror_state == "listing":
            label.update("listing mirror handles…")
        elif self._mirror_note:
            label.update(self._mirror_note)
        else:
            label.update("idle — l launches the mirror for the selected device")


def _plain(value: object) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ")
    return " ".join(text.split())[:160]
