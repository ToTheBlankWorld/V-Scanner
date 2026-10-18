"""Forensics cockpit (Stage 08): the R-03/R-05/R-07/R-12 remediated surface.

What this screen implements — exactly the engine's semantics, nothing less:

* Root status is the verified TRI-STATE probe (R-05): ``rooted`` /
  ``not-rooted`` / ``unknown`` with evidence lines. The legacy "assume
  rooted" fallback is gone; ``is_rooted`` is only ever true for a
  CONFIRMED root.
* New cases run as FORENSICS_OP jobs; the manifest that comes back (and
  every subsequent op result) is rendered from the SAVED manifest — the
  screen keeps no parallel truth.
* Extract operations record per-file sha256 + byte counts (R-07); FAILED
  entries are displayed verbatim — never silently skipped.
* WiFi extraction defaults to the REDACTED preset (R-12). The cleartext
  variant requires a second, typed acknowledgement ("I ACCEPT CLEARTEXT
  PSK") and a fresh :class:`OperationConfirmation` token at submit time;
  the service re-validates the token (R-13 service-side gate).
* The report op preserves the legacy report.json field names.

The screen uses one "armed" input (type, then Enter) rather than per-op
dialogs — keys 1..7 arm their op, Escape cancels. Digits never invoke an
op while the input holds focus; the honest hint line says so.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label

from vscanner.core.events import JobTerminalEvent, OperationConfirmation
from vscanner.core.models import CaseManifest

from ui_terminal.backend import DeviceBackend
from ui_terminal.screens.shell import ShellScreen

__all__ = ["ForensicsScreen", "CleartextAckModal"]

_ACK_PHRASE = "I ACCEPT CLEARTEXT PSK"
_ARMS = {
    "1": ("extract_app_data", "extract app data — type the package name"),
    "2": ("text:system_logs", None),
    "3": ("text:installed_packages", None),
    "4": ("text:running_processes", None),
    "5": ("wifi:redacted", None),
    "7": ("report", None),
}
_OPS = {
    "2": "system_logs",
    "3": "installed_packages",
    "4": "running_processes",
    "5": "wifi_cleartext_redacted",
    "7": "report",
}


class CleartextAckModal(ModalScreen[Optional[str]]):
    """Second-confirm dialog for unredacted WiFi PSK storage (R-12)."""

    CSS = """
    CleartextAckModal { align: center middle; }
    #ack-box { width: 68; padding: 1 2; border: round $accent; }
    """

    BINDINGS = [
        Binding("escape", "dismiss_none", "Cancel", show=False),
    ]

    def __init__(self, case_id: str) -> None:
        super().__init__()
        self._case_id = case_id

    def compose(self) -> ComposeResult:
        with Vertical(id="ack-box"):
            yield Label(
                "This writes WiFi PSKs in CLEARTEXT to "
                f"'{self._case_id}/wifi_networks_cleartext.txt' on disk "
                "(secret material, unprotected). The redacted default "
                "already exists.",
                id="ack-warning",
            )
            yield Label(
                f"Type {_ACK_PHRASE} exactly (uppercase, with spaces) to "
                "proceed — anything else cancels:",
                id="ack-prompt",
            )
            yield Input(placeholder=_ACK_PHRASE, id="ack-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text == _ACK_PHRASE:
            self.dismiss(text)
        else:
            self.notify(
                "acknowledgement text did not match — nothing was written",
                title="WiFi cleartext", severity="warning",
            )
            self.dismiss(None)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class ForensicsScreen(ShellScreen):
    """Forensics cockpit: tri-state root, cases, ops, redaction default."""

    SECTION_ID = "forensics"

    BINDINGS = [
        Binding("r", "refresh", "Refresh devices"),
        Binding("n", "arm_new_case", "New case"),
        Binding("o", "arm_open", "Open case by name"),
        Binding("1", "arm_extract", "Extract app data"),
        Binding("2", "arm_logs", "System logs"),
        Binding("3", "arm_packages", "Installed packages"),
        Binding("4", "arm_processes", "Running processes"),
        Binding("5", "arm_wifi", "WiFi (redacted)"),
        Binding("6", "wifi_cleartext", "WiFi CLEARTEXT (confirm)"),
        Binding("7", "arm_report", "Write report.json"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._devices: tuple = ()
        self._discovery_state = "idle"
        self._selected_serial: Optional[str] = None
        self._root_state = "idle"    # idle | probing | probed | failed
        self._root_word: Optional[str] = None
        self._root_evidence: tuple = ()
        self._root_error: Optional[str] = None
        self._manifest: Optional[CaseManifest] = None
        self._armed_op: Optional[str] = None
        self._job_state = "idle"     # idle | running | done | failed
        self._job_note: Optional[str] = None
        self._job_id: Optional[str] = None

    @property
    def backend(self) -> DeviceBackend:
        return cast(DeviceBackend, getattr(self.app, "backend"))

    # -- composition ----------------------------------------------------------- #

    def inner_body(self) -> ComposeResult:
        with Vertical(id="fx-body"):
            yield Label("", id="fx-device", classes="status-muted")
            yield DataTable(id="fx-devices", cursor_type="row")
            yield Label("", id="fx-root", classes="status-muted")
            yield DataTable(id="fx-evidence", show_cursor=False)
            with Horizontal(id="fx-entry"):
                yield Input(placeholder="press an op digit; type; Enter",
                            id="fx-input")
            yield Label("", id="fx-case", classes="status-muted")
            yield Label("", id="fx-job", classes="status-muted")
            yield DataTable(id="fx-files", cursor_type="row")
            yield DataTable(id="fx-operations", show_cursor=False)

    def on_mount(self) -> None:
        super().on_mount()
        devices = self.query_one("#fx-devices", DataTable)
        devices.add_columns("Serial", "State", "Model")
        evidence = self.query_one("#fx-evidence", DataTable)
        evidence.add_columns("Root probe evidence")
        files = self.query_one("#fx-files", DataTable)
        files.add_columns(
            "Source path", "In case", "sha256 (12)", "Bytes", "Kind")
        operations = self.query_one("#fx-operations", DataTable)
        operations.add_columns("Operation", "Recorded status")
        self._apply_all()
        self.action_refresh()

    def status_hint(self) -> str:
        if self._job_state == "running":
            return ("forensics · operation running on the worker thread · "
                    "(case " + (self._manifest.case_id if self._manifest
                                else "—") + ")")
        if self._armed_op:
            return "forensics · op armed — type into the input, Enter runs, Esc cancels"
        return ("forensics · r refresh · n new case · 1-7 ops · 6 needs the "
                "typed cleartext confirmation")

    def _apply_all(self) -> None:
        self._render_devices()
        self._render_device_line()
        self._render_root()
        self._render_case()
        self._render_job()
        self._render_files()
        self._render_operations()
        self.refresh_status()

    # -- device discovery -------------------------------------------------------- #

    def action_refresh(self) -> None:
        backend = self.backend
        try:
            if backend.adb_path_saved() is None:
                self._discovery_state = "no-adb"
                self._apply_all()
                return
        except Exception as exc:
            self._apply_discovery((), _failure_word(exc))
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
            work, group="fx-refresh", exclusive=True, thread=True,
            exit_on_error=False, description="forensics device discovery",
        )

    def _apply_discovery(self, devices: tuple, reason: Optional[str]) -> None:
        if reason is not None:
            self._discovery_state = "failed"
            self._render_devices()
            return
        self._devices = tuple(devices)
        self._discovery_state = "ok" if devices else "empty"
        actionable = [d.serial for d in devices if d.state.value == "device"]
        if self._selected_serial is not None and self._selected_serial \
                not in actionable:
            self._selected_serial = None
            self._root_state = "idle"
        elif self._selected_serial is None and actionable:
            self._selected_serial = actionable[0]
        if self._selected_serial is not None:
            self._probe_root()
        self._apply_all()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "fx-devices":
            serial = event.row_key.value
            if serial and serial != self._selected_serial:
                self._selected_serial = serial
                self._probe_root()
                self._apply_all()

    # -- root tri-state (R-05, worker) ------------------------------------------- #

    def _probe_root(self) -> None:
        serial = self._selected_serial
        if serial is None:
            return
        self._root_state = "probing"
        self._root_word = None
        self._root_evidence = ()
        self._root_error = None
        self._render_root()
        backend = self.backend

        def work() -> None:
            try:
                word, evidence = backend.root_status_now(serial)
            except Exception as exc:
                self.app.call_from_thread(
                    self._apply_root, None, (), _failure_word(exc))
            else:
                self.app.call_from_thread(self._apply_root, word, tuple(evidence), None)

        self.app.run_worker(
            work, group="fx-root", exclusive=True, thread=True,
            exit_on_error=False, description="root status probe",
        )

    def _apply_root(self, word, evidence, failure) -> None:
        if failure is not None:
            self._root_state = "failed"
            self._root_error = failure
        else:
            self._root_state = "probed"
            self._root_word = word
            self._root_evidence = tuple(evidence)
        self._render_root()
        self.refresh_status()

    def _render_root(self) -> None:
        label = self.query_one("#fx-root", Label)
        if self._root_state == "probing":
            label.update("root status: probing (verified tri-state probe)…")
        elif self._root_state == "failed":
            label.update(
                "root status: UNKNOWN (probe failed: "
                f"{self._root_error}) — honest absence of an answer")
        elif self._root_state == "probed" and self._root_word:
            label.update(f"root status: {self._root_word} (tri-state; "
                         "evidence below — never 'assumed root')")
        else:
            label.update("root status: not probed for this target yet")
        table = self.query_one("#fx-evidence", DataTable)
        table.clear()
        for line in self._root_evidence:
            table.add_row(_plain(line))

    # -- armed input / case ops --------------------------------------------------- #

    def action_arm_open(self) -> None:
        self._armed_op = "open_case"
        self._arm_input("open case — type the case name")

    def _arm_input(self, hint: str) -> None:
        self._job_note = None
        label = self.query_one("#fx-case", Label)
        label.update(f"armed: {hint} · Esc cancels")
        inp = self.query_one("#fx-input", Input)
        inp.value = ""
        inp.placeholder = hint
        inp.focus()

    def action_arm_new_case(self) -> None:
        self._armed_op = "new_case"
        self._arm_input("new case — type the case name (letters, digits, ., -, _)")
        self._render_job()

    def action_arm_extract(self) -> None:
        if self._manifest is None:
            self._need_case()
            return
        self._armed_op = "extract_app_data"
        self._arm_input("extract app data — type the package name")

    def action_arm_logs(self) -> None:
        self._run_text_op("system_logs")

    def action_arm_packages(self) -> None:
        self._run_text_op("installed_packages")

    def action_arm_processes(self) -> None:
        self._run_text_op("running_processes")

    def action_arm_wifi(self) -> None:
        self._run_wifi_op(None)

    def action_wifi_cleartext(self) -> None:
        if self._manifest is None:
            self._need_case()
            return
        self.app.push_screen(CleartextAckModal(self._manifest.case_id),
                             self._on_cleartext_acked)

    def _on_cleartext_acked(self, typed: Optional[str]) -> None:
        if typed is None:
            self._job_note = None
            self._render_job()
            return
        confirmation = OperationConfirmation(
            reference="wifi_cleartext_psk",
            confirmed_at=datetime.now(timezone.utc),
        )
        self._run_wifi_op(confirmation)

    def action_arm_report(self) -> None:
        self._run_report_op()

    def _need_case(self) -> None:
        self.notify(
            "open or create a case first (n / o)",
            title="Forensics", severity="warning",
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "fx-input":
            return
        value = event.value.strip()
        op = self._armed_op
        self._armed_op = None
        event.input.placeholder = "press an op digit; type; Enter"
        if not value:
            # empty submit disarms: nothing runs without the argument
            self._render_case()
            return
        if op == "new_case":
            self._start_job("create_case", {
                "case_name": value,
                "device_model": self._device_model_hint(),
            })
        elif op == "open_case":
            self._open_case(value)
        elif op == "extract_app_data":
            if self._manifest is None:
                self._need_case()
                return
            self._start_job("extract_app_data", {
                "case_id": self._manifest.case_id,
                "package": value,
            })
        else:
            self._render_case()

    def _device_model_hint(self) -> Optional[str]:
        for info in self._devices:
            if info.serial == self._selected_serial:
                model = info.usb_props.get("model")
                return str(model) if model else None
        return None

    # -- case jobs ------------------------------------------------------------------ #

    def _start_job(self, op: str, kwargs: dict) -> None:
        serial = self._selected_serial
        if serial is None:
            # every engine op, including create_case (which probes root),
            # runs against the bound device transport
            self.notify(
                "select a device first", title="Forensics",
                severity="warning",
            )
            return
        self._job_state = "running"
        self._job_note = None
        self._render_job()
        backend = self.backend
        try:
            handle = backend.start_forensics_job(serial, op, kwargs)
        except Exception as exc:
            self._job_state = "failed"
            self._job_note = _failure_word(exc)
            self._render_job()
            self.refresh_status()
            return
        self._job_id = handle.id

    def _open_case(self, case_id: str) -> None:
        self._job_state = "running"
        self._job_note = None
        self._render_job()
        backend = self.backend

        def work() -> None:
            try:
                manifest = backend.forensics_load_case(case_id)
            except Exception as exc:
                self.app.call_from_thread(
                    self._apply_open, None, _failure_word(exc))
            else:
                self.app.call_from_thread(self._apply_open, manifest, None)

        self.app.run_worker(
            work, group="fx-open", exclusive=True, thread=True,
            exit_on_error=False, description="case load",
        )

    def _apply_open(self, manifest, failure: Optional[str]) -> None:
        self._job_state = "failed" if failure else "done"
        self._job_note = failure or f"case {manifest.case_id} loaded"
        if not failure:
            self._manifest = manifest
        self._render_job()
        self._render_case()
        self._render_files()
        self._render_operations()
        self.refresh_status()

    def _run_text_op(self, op: str) -> None:
        if self._manifest is None:
            self._need_case()
            return
        self._start_job(op, {"case_id": self._manifest.case_id})

    def _run_wifi_op(self, confirmation) -> None:
        if self._manifest is None:
            self._need_case()
            return
        self._start_job("wifi_cleartext", {
            "case_id": self._manifest.case_id,
            "confirmation": confirmation,
        })

    def _run_report_op(self) -> None:
        if self._manifest is None:
            self._need_case()
            return
        self._start_job("report", {"case_id": self._manifest.case_id})

    # -- job events (FORENSICS_OP) ---------------------------------------------- #

    def on_job_event(self, event) -> None:
        if event.job_id != self._job_id:
            return
        if not isinstance(event, JobTerminalEvent):
            return
        self._job_id = None
        if event.outcome.value == "succeeded":
            self._job_state = "done"
            result = event.result
            manifest = result[0] if isinstance(result, tuple) else result
            if isinstance(manifest, CaseManifest):
                self._manifest = manifest
                if isinstance(result, tuple) and result[1]:
                    self._job_note = (
                        f"report written: {result[1]}")
                else:
                    self._job_note = (
                        f"manifest updated ({len(manifest.files)} file(s))")
            else:
                self._job_note = "operation finished"
        else:
            self._job_state = "failed"
            self._job_note = _failure_word(
                event.error or event.outcome.value)
        self._render_job()
        self._render_case()
        self._render_files()
        self._render_operations()
        self.refresh_status()

    # -- rendering ------------------------------------------------------------------ #

    def _render_devices(self) -> None:
        table = self.query_one("#fx-devices", DataTable)
        table.clear()
        for info in self._devices:
            table.add_row(
                info.serial, info.state.value,
                _plain(info.usb_props.get("model")),
                key=info.serial,
            )

    def _render_device_line(self) -> None:
        line = self.query_one("#fx-device", Label)
        if self._selected_serial:
            line.update(f"target {self._selected_serial} · "
                        f"discovery: {self._discovery_state}")
        else:
            line.update("no device selected (enter on a device row)")

    def _render_case(self) -> None:
        label = self.query_one("#fx-case", Label)
        m = self._manifest
        if m is None:
            label.update(
                "no case open — n creates one (runs the verified root probe "
                "once), o opens an existing case by name")
            return
        kind = "CONFIRMED rooted" if m.root_status == "rooted" else \
            f"root: {m.root_status} (tri-state)"
        label.update(
            f"case {m.case_id} · created {m.created_at} · {kind} · "
            f"redaction preset: {m.redaction_preset} · "
            f"{len(m.files)} file(s)")

    def _render_job(self) -> None:
        label = self.query_one("#fx-job", Label)
        label.set_classes("status-muted")
        if self._job_state == "running":
            label.update("operation running on the engine worker thread…")
            label.set_classes("status-ok")
        elif self._job_state == "done":
            label.update(self._job_note or "done")
            label.set_classes("status-ok")
        elif self._job_state == "failed":
            label.update(f"operation FAILED: {self._job_note} — recorded, "
                         "never silently skipped")
            label.set_classes("status-error")
        else:
            label.update("idle — press a digit to arm an operation")

    def _render_files(self) -> None:
        table = self.query_one("#fx-files", DataTable)
        table.clear()
        m = self._manifest
        if m is None:
            table.add_row("—", "no case open", "—", "—", "—")
            return
        if not m.files:
            table.add_row("no files extracted yet", "—", "—", "—", "—")
        for record in m.files:
            table.add_row(
                _plain(record.source_path),
                _plain(record.case_relative_path),
                record.sha256[:12],
                str(record.byte_count),
                record.kind,
            )

    def _render_operations(self) -> None:
        table = self.query_one("#fx-operations", DataTable)
        table.clear()
        m = self._manifest
        if m is None or not m.extractions:
            table.add_row("—", "no operations recorded yet")
            return
        for operation, status in m.extractions:
            table.add_row(_plain(operation), _plain(status))


def _plain(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ")
    return " ".join(text.split())[:120]


def _failure_word(exc: object) -> str:
    if exc is None:
        return "unknown failure"
    return f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"
