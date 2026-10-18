"""Scanning & findings screen tests (Stage 07, §10 scan/lifecycle honesty).

State-machine honesty at the screen seam with a scripted backend (no
subprocess, no real device). Job events are fed exactly the way the app
pump would deliver them (current screen only, job-id filtered). The full
engine pipeline path lives in test_stage07_engine.py.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional, Tuple

from textual.widgets import DataTable, Input, Label

from ui_terminal.app import VScannerApp
from ui_terminal.screens.scan import ScanScreen
from vscanner.core.errors import InputValidationError, JobConflictError
from vscanner.core.events import (
    JobFindingEvent,
    JobProgressEvent,
    JobStartedEvent,
    JobState,
    JobTerminalEvent,
)
from vscanner.core.models import (
    AppInfo,
    AppScanResult,
    ConnectionInfo,
    DeviceState,
    Evidence,
    EvidenceKind,
    Finding,
    FindingCategory,
    FindingSeverity,
    Remediation,
    ScanConfiguration,
    ScanKind,
    ScanRequest,
    ScanResultBundle,
    ScanRun,
    ScanSummary,
)
from vscanner.services.config import ConfigService
from vscanner.services.history import HistoryEntry


# -- helpers ------------------------------------------------------------------ #

def _visible_text(node) -> str:
    return "\n".join(str(w.render().plain) for w in node.query(Label))


def _text_of(label) -> str:
    """Text of ONE label (querying descendants of a Label yields nothing)."""
    return str(label.render().plain)


def _table_values(screen, selector: str) -> str:
    """Concatenated cell text of one DataTable (cells are not Labels)."""
    table = screen.query_one(selector, DataTable)
    return " ".join(
        str(cell) for row in range(table.row_count)
        for cell in table.get_row_at(row)
    )


async def _until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met within the timeout")


def _device(serial: str = "S1", state: DeviceState = DeviceState.DEVICE,
            model: str = "Pixel 2") -> ConnectionInfo:
    return ConnectionInfo(
        serial=serial, state=state,
        usb_props={"raw_state": state.value, "model": model},
    )


def _one(serial: str = "S1", state: DeviceState = DeviceState.DEVICE,
         ) -> Tuple[ConnectionInfo, ...]:
    """One scripted discovery answer: a TUPLE of devices (Stage 06 fake
    convention — ``list_devices`` returns ``Tuple[ConnectionInfo, ...]``)."""
    return (_device(serial, state),)


def _multi(*serials: str) -> Tuple[ConnectionInfo, ...]:
    return tuple(_device(s) for s in serials)


def _finding(
    severity: FindingSeverity = FindingSeverity.HIGH,
    title: str = "READ_SMS declared",
    category: FindingCategory = FindingCategory.PERMISSION_EXCESS,
    package: str = "com.example.wallet",
    detail: str = "Allows reading SMS messages",
) -> Finding:
    """A typed finding with a REAL engine-stable id (via make_finding)."""
    app = AppInfo(package_name=package)
    from vscanner.core.models import make_finding

    return make_finding(
        kind=category,
        severity=severity,
        title=title,
        detail=detail,
        evidence=(
            Evidence.of(
                EvidenceKind.CONFIRMED_ARTIFACT,
                f"Permission declared in dumpsys output: {title.split()[0]}",
                f"dumpsys package {package}",
            ),
        ),
        remediation=(
            Remediation("Revoke if not essential for app function", category),
        ),
        app=app,
        device_serial="S1",
    )


def _bundle() -> ScanResultBundle:
    """Hand-built typed bundle matching the engine's golden demo shape."""
    critical = _finding(severity=FindingSeverity.CRITICAL,
                        title="READ_SMS declared")
    low = _finding(severity=FindingSeverity.LOW, title="INTERNET declared",
                   detail="Allows internet access")
    app_result = AppScanResult(
        app=AppInfo(package_name="com.example.wallet"),
        findings=(critical, low))
    skipped = AppScanResult(
        app=AppInfo(package_name="com.minimal.app"),
        scan_skipped_reason="no accessible permission information")
    request = ScanRequest(
        kind=ScanKind.FULL_DEVICE,
        config=ScanConfiguration(device_serial="S1"))
    summary = ScanSummary(
        run=ScanRun(request=request),
        total_apps=2,
        high_risk=1,
        low_risk=1,
        findings_total=2,
        skipped_apps=("com.minimal.app",),
    )
    return ScanResultBundle(summary=summary,
                            apps=(app_result, skipped))


class ScanFakeHandle:
    def __init__(self, job_id: str) -> None:
        self._id = job_id

    @property
    def id(self) -> str:
        return self._id

    @property
    def state(self):
        return JobState.SUCCEEDED

    def cancel(self) -> None:
        pass


class FakeScanBackend:
    """Scripted backend for the scan screen (same seam as Stage 06 fakes)."""

    def __init__(self) -> None:
        self.saved: Optional[str] = "C:/fake/adb.exe"
        self.devices_script: list = []
        self.list_calls: int = 0
        self.start_scan_calls: list = []
        self.cancel_calls: list = []
        self.conflict_on_start: bool = False
        self.active_serial_job: Optional[str] = None
        self.history_entries: list = []
        self.history_fail: bool = False
        self.history_read_fail: bool = False
        self.scan_memory: Optional[Tuple] = None
        self.export_calls: list = []
        self.next_job_id: int = 0
        self.sinks: list = []

    def adb_path_saved(self):
        return self.saved

    def list_devices(self, timeout: float = 10.0):
        self.list_calls += 1
        return self.devices_script.pop(0) if self.devices_script else ()

    def profile(self, serial: str):
        from vscanner.core.models import DeviceProfile, RootStatus

        return DeviceProfile(serial=serial, root_status=RootStatus.UNKNOWN)

    def start_listing_job(self, serial: str, include_system: bool):
        self.next_job_id += 1
        return ScanFakeHandle(f"listing-{self.next_job_id}")

    def cancel_listing_job(self, serial: str) -> None:
        pass

    def active_listing_handle(self, serial: str):
        return None

    def start_scan_job(self, serial: str, include_system: bool,
                       deep: bool, package: Optional[str]):
        self.start_scan_calls.append((serial, include_system, deep, package))
        if self.conflict_on_start:
            raise JobConflictError(
                "a conflicting job is already active for this target",
                {"active_job_id": "job-1", "group": "scan"},
            )
        self.next_job_id += 1
        return ScanFakeHandle(f"scan-{self.next_job_id}")

    def cancel_scan_job(self, serial: str) -> None:
        self.cancel_calls.append(serial)

    def active_scan_handle(self, serial: str):
        if self.active_serial_job is not None:
            return ScanFakeHandle(self.active_serial_job)
        return None

    def remember_scan(self, bundle, status: str,
                      serial: Optional[str]) -> None:
        self.scan_memory = (status, serial, bundle)

    def last_scan(self):
        return self.scan_memory

    def start_export_job(self, bundle, output_dir: Optional[str],
                         serial: Optional[str]):
        self.export_calls.append((bundle, output_dir, serial))
        self.next_job_id += 1
        return ScanFakeHandle(f"export-{self.next_job_id}")

    def history_entry(self, entry: HistoryEntry):
        if self.history_fail:
            raise RuntimeError("disk blew up")
        self.history_entries.append(entry)
        return f"history/{entry.scan_id[:8]}.json"

    def history_recent(self):
        if self.history_read_fail:
            raise RuntimeError("history unreadable")
        return tuple(self.history_entries)

    def shutdown_jobs(self) -> None:
        pass

    def start_pump(self, sink) -> None:
        self.sinks.append(sink)

    def stop_pump(self) -> None:
        pass


async def open_scan(pilot, backend: FakeScanBackend) -> ScanScreen:
    await pilot.press("f")
    await pilot.pause()
    screen = pilot.app.screen
    assert isinstance(screen, ScanScreen)
    await _until(lambda: screen._discovery_state in ("ok", "empty"))
    await pilot.pause()
    return screen


def _explorer_app(tmp_path) -> Tuple[VScannerApp, FakeScanBackend]:
    """App + backend for explorer tests; each test owns its run_test()."""
    backend = FakeScanBackend()
    backend.devices_script = [_one()]
    service = ConfigService(tmp_path / "config.json")
    service.save(adb_path="C:/fake/adb.exe")
    app = VScannerApp(config_service=service, backend=backend)
    return app, backend


def _explorer_screen(screen) -> None:
    """Put a completed scan's findings onto the screen state deterministically."""
    bundle = _bundle()
    findings = [
        finding for result in bundle.apps for finding in result.findings]
    screen._apply_bundle(bundle)
    screen._findings = tuple(findings)
    screen._findings_status = "from-bundle"
    screen._render_findings()


class _FakeKey:
    def __init__(self, value: str) -> None:
        self.value = value


# -- execution ---------------------------------------------------------------- #

class TestScanExecution:
    async def test_opening_runs_one_discovery_and_preselects(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            assert backend.list_calls == 1
            assert screen._selected_serial == "S1"
            assert screen._scan_state == "idle"

    async def test_multiple_devices_never_auto_select(self, tmp_path) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_multi("S1", "S2")]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            assert screen._selected_serial is None
            target = _text_of(screen.query_one("#scan-target", Label))
            assert "no target selected" in target
            # explicit selection only (same rule as the workspace)
            screen._select_device("S2")
            assert screen._selected_serial == "S2"

    async def test_start_requires_selection(self, tmp_path) -> None:
        backend = FakeScanBackend()
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            await pilot.press("f")
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, ScanScreen)
            await _until(lambda: screen._discovery_state in ("ok", "empty"))
            screen.action_start_scan()
            await asyncio.sleep(0.05)
            assert backend.start_scan_calls == []
            assert screen._scan_state != "running"

    async def test_successful_scan_fills_findings_and_history(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one(), _one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            screen.action_start_scan()
            await _until(lambda: screen._scan_state == "running")
            assert backend.start_scan_calls == [("S1", False, False, None)]
            job_id = screen._scan_job_id
            assert job_id is not None
            screen.on_job_event(
                JobStartedEvent(job_id=job_id, device_serial="S1"))
            bundle = _bundle()
            critical = bundle.apps[0].findings[0]
            screen.on_job_event(
                JobFindingEvent(job_id=job_id, finding=critical))
            screen.on_job_event(JobProgressEvent(
                job_id=job_id, current=1, total=2, unit="apps",
                context="com.example.wallet"))
            progress = _text_of(
                screen.query_one("#scan-progress", Label))
            assert "1/2" in progress
            assert "com.example.wallet" in progress
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id, outcome=JobState.SUCCEEDED, result=bundle))
            await _until(lambda: screen._scan_state == "completed")
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 2
            progress = _text_of(
                screen.query_one("#scan-progress", Label))
            assert "2 app(s) analyzed (1 skipped, 2 finding(s))" in progress
            assert "export via the reports screen (h)" in progress
            assert backend.scan_memory is not None
            assert backend.scan_memory[0] == "completed"
            assert backend.scan_memory[1] == "S1"
            await _until(lambda: len(backend.history_entries) == 1)
            entry = backend.history_entries[0]
            assert entry.status == "completed"
            assert entry.kind == "full_device"
            assert entry.severity_counts_complete()["critical"] == 1
            assert entry.severity_counts_complete()["low"] == 1

    async def test_scanner_failure_terminal_is_honest(self, tmp_path) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one(), _one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            screen.action_start_scan()
            await _until(lambda: screen._scan_state == "running")
            job_id = screen._scan_job_id
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id, outcome=JobState.FAILED,
                error=InputValidationError("device vanished mid-scan")))
            await _until(lambda: screen._scan_state == "failed")
            text = _visible_text(screen)
            assert "scan failed" in text
            assert "device vanished mid-scan" in text
            assert backend.scan_memory is None, \
                "a failed scan must never be remembered as export material"

    async def test_stale_selected_device_blocks_the_scan(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            assert screen._selected_serial == "S1"
            # the preflight sees an EMPTY device list: the target vanished
            backend.devices_script = []
            screen.action_start_scan()
            await _until(lambda: screen._scan_state == "failed")
            assert backend.start_scan_calls == []
            text = _visible_text(screen)
            assert "no longer connected" in text

    async def test_repeated_start_attempts_do_not_overlap(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one(), _one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            screen.action_start_scan()
            await _until(lambda: screen._scan_state == "running")
            screen.action_start_scan()
            await asyncio.sleep(0.05)
            assert len(backend.start_scan_calls) == 1

    async def test_backend_conflict_becomes_a_typed_failure(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.conflict_on_start = True
        backend.devices_script = [_one(), _one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            screen.action_start_scan()
            await _until(lambda: screen._scan_state == "failed")
            text = _visible_text(screen)
            assert "conflicting" in text or "already active" in text

    async def test_single_app_scope_validates_before_work(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one(), _one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            screen.query_one("#scan-package", Input).value = "bad name!!"
            screen.action_start_single()
            await asyncio.sleep(0.05)
            assert backend.start_scan_calls == []
            screen.query_one("#scan-package", Input).value = "com.example.app"
            screen.action_start_single()
            await _until(
                lambda: backend.start_scan_calls
                and backend.start_scan_calls[0] == (
                    "S1", False, False, "com.example.app"))
            assert screen._scan_state == "running"

    async def test_scope_toggles_are_explicit_and_used(self, tmp_path) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one(), _one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            screen.action_toggle_system()
            screen.action_toggle_deep()
            scope = _text_of(
                screen.query_one("#scan-scope-state", Label))
            assert "system apps: included" in scope
            assert "deep scan: on" in scope
            screen.action_start_scan()
            await _until(lambda: screen._scan_state == "running")
            assert backend.start_scan_calls == [("S1", True, True, None)]


# -- cancellation & lifecycle -------------------------------------------------- #

class TestCancellationAndLifecycle:
    async def test_cancel_binding_routes_the_job_request(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one(), _one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            screen.action_start_scan()
            await _until(lambda: screen._scan_state == "running")
            await pilot.press("c")
            await pilot.pause()
            assert backend.cancel_calls == ["S1"]
            # request ≠ acknowledgement: the terminal event closes it
            assert screen._scan_state == "running"

    async def test_cancelled_terminal_keeps_partial_stream_honest(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one(), _one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            screen.action_start_scan()
            await _until(lambda: screen._scan_state == "running")
            job_id = screen._scan_job_id
            screen.on_job_event(JobFindingEvent(
                job_id=job_id,
                finding=_finding(severity=FindingSeverity.INFO,
                                 title="INTERNET declared")))
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id, outcome=JobState.CANCELLED))
            await _until(lambda: screen._scan_state == "cancelled")
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 1, "streamed findings survive a cancel"
            text = _visible_text(screen)
            assert "cancelled" in text
            assert "PARTIAL" in text
            assert backend.scan_memory is None, \
                "cancelled scans must not be presented as export material"
            await _until(lambda: len(backend.history_entries) == 1)
            entry = backend.history_entries[0]
            assert entry.status == "cancelled"
            assert entry.findings_total == 1

    async def test_failed_terminal_after_streaming_keeps_partial(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one(), _one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            screen.action_start_scan()
            await _until(lambda: screen._scan_state == "running")
            job_id = screen._scan_job_id
            screen.on_job_event(JobFindingEvent(
                job_id=job_id, finding=_finding()))
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id, outcome=JobState.FAILED,
                error=InputValidationError("device vanished mid-scan")))
            await _until(lambda: screen._scan_state == "failed")
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 1
            await _until(lambda: len(backend.history_entries) == 1)
            assert backend.history_entries[0].status == "failed"

    async def test_history_write_failure_never_fakes_the_outcome(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.history_fail = True
        backend.devices_script = [_one(), _one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            notified: list = []
            screen.notify = (  # type: ignore[method-assign]
                lambda message, **kw: notified.append(str(message)))
            screen.action_start_scan()
            await _until(lambda: screen._scan_state == "running")
            job_id = screen._scan_job_id
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id, outcome=JobState.SUCCEEDED,
                result=_bundle()))
            await _until(lambda: screen._scan_state == "completed")
            assert backend.history_entries == []
            # the scan outcome stays authoritative; a warning is surfaced
            await _until(lambda: any(
                "history" in message.lower() for message in notified))
            text = _visible_text(screen)
            assert "scan completed" in text
            assert "2 finding(s)" in text

    async def test_away_reconciliation_never_fakes_results(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            # simulate a job that ran and terminalized while invisible
            screen._scan_job_id = "gone-job"
            screen._scan_state = "running"
            screen._reconcile_scan_after_away()
            assert screen._scan_state == "away"
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, ScanScreen)
            text = _visible_text(screen)
            assert "could not be streamed here" in text

    async def test_active_job_survives_reconciliation(self, tmp_path) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            backend.active_serial_job = "scan-7"
            screen._scan_job_id = "scan-7"
            screen._scan_state = "running"
            screen._reconcile_scan_after_away()
            assert screen._scan_state == "running"

    async def test_foreign_job_events_are_ignored(self, tmp_path) -> None:
        backend = FakeScanBackend()
        backend.devices_script = [_one()]
        service = ConfigService(tmp_path / "config.json")
        service.save(adb_path="C:/fake/adb.exe")
        app = VScannerApp(config_service=service, backend=backend)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, backend)
            screen.on_job_event(JobTerminalEvent(
                job_id="not-mine", outcome=JobState.SUCCEEDED,
                result=_bundle()))
            assert screen._scan_state == "idle"
            assert screen._findings == ()
            assert backend.scan_memory is None


# -- findings explorer ---------------------------------------------------------- #

class TestFindingsExplorer:
    async def test_filters_narrow_the_view_without_mutating_results(
        self, tmp_path,
    ) -> None:
        app, _backend = _explorer_app(tmp_path)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, _backend)
            _explorer_screen(screen)
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 2
            original = tuple(screen._findings)
            # severity threshold: cycle to CRITICAL → only the critical one
            screen.action_cycle_severity()
            await pilot.pause()
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 1
            assert len(screen._findings) == 2, "filters never mutate results"
            # cycle the remaining severities (HIGH, MEDIUM, LOW, INFO) and
            # back to "any": exactly 5 more cycles from CRITICAL
            for _cycle in range(5):
                screen.action_cycle_severity()
                await pilot.pause()
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 2
            # category cycle: both findings share permission_excess; the
            # next category (sdk_compat) shows zero rows honestly
            screen.action_cycle_category()
            await pilot.pause()
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 2
            text = _text_of(
                screen.query_one("#scan-findings-count", Label))
            assert "2 of 2" in text
            screen.action_cycle_category()
            await pilot.pause()
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 0
            text = _text_of(
                screen.query_one("#scan-findings-count", Label))
            assert "0 of 2" in text
            assert tuple(screen._findings) == original

    async def test_text_filter_matches_title_and_detail(
        self, tmp_path,
    ) -> None:
        app, _backend = _explorer_app(tmp_path)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, _backend)
            _explorer_screen(screen)
            screen._text_filter = "sms"
            screen._page = 0
            screen._render_findings()
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 1
            cells = " ".join(str(c) for c in table.get_row_at(0))
            assert "READ_SMS" in cells
            screen._text_filter = "no such needle anywhere"
            screen._render_findings()
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 0

    async def test_sort_orders_are_deterministic(self, tmp_path) -> None:
        app, _backend = _explorer_app(tmp_path)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, _backend)
            _explorer_screen(screen)
            table = screen.query_one("#scan-findings", DataTable)
            # default sort severity: CRITICAL first, LOW last
            assert "READ_SMS" in str(table.get_row_at(0)[2])
            assert "INTERNET" in str(table.get_row_at(1)[2])
            screen.action_cycle_sort()  # → category
            await pilot.pause()
            screen.action_cycle_sort()  # → package
            await pilot.pause()
            screen.action_cycle_sort()  # → title
            await pilot.pause()
            table = screen.query_one("#scan-findings", DataTable)
            assert "INTERNET" in str(table.get_row_at(0)[2])
            assert "READ_SMS" in str(table.get_row_at(1)[2])

    async def test_pagination_is_explicit_and_deterministic(
        self, tmp_path,
    ) -> None:
        app, _backend = _explorer_app(tmp_path)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, _backend)
            _explorer_screen(screen)
            many = tuple(
                _finding(
                    severity=FindingSeverity.LOW,
                    title=f"finding {index:03d}",
                    detail=f"detail {index}",
                ) for index in range(150)
            )
            screen._findings = many
            screen._page = 0
            screen._render_findings()
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 100
            count = _text_of(
                screen.query_one("#scan-findings-count", Label))
            assert "150 of 150" in count and "page 1/2" in count
            screen.action_next_page()
            await pilot.pause()
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 50
            count = _text_of(
                screen.query_one("#scan-findings-count", Label))
            assert "page 2/2" in count
            screen.action_next_page()  # honest feedback at the boundary
            await pilot.pause()
            screen.action_prev_page()
            await pilot.pause()
            table = screen.query_one("#scan-findings", DataTable)
            assert table.row_count == 100

    async def test_detail_panel_shows_honest_provenance(
        self, tmp_path,
    ) -> None:
        app, _backend = _explorer_app(tmp_path)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, _backend)
            _explorer_screen(screen)
            # row keys are view positions: position 0 is the CRITICAL
            # READ_SMS finding under the default severity sort
            screen._open_detail(_FakeKey("0"))
            await pilot.pause()
            title = _text_of(
                screen.query_one("#scan-detail-title", Label))
            assert "critical" in title
            assert "permission excess" in title
            assert "READ_SMS declared" in title
            body = _text_of(screen.query_one("#scan-detail-body", Label))
            assert "app: com.example.wallet" in body
            assert "evidence (observed) from dumpsys package" in body
            assert "recommended fix (permission_excess)" in body
            assert "detected by scan-service" in body
            assert "no per-finding numeric risk score" in body

    async def test_unknown_finding_row_is_never_fabricated(
        self, tmp_path,
    ) -> None:
        app, _backend = _explorer_app(tmp_path)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, _backend)
            _explorer_screen(screen)
            screen._open_detail(_FakeKey("9999"))
            await pilot.pause()
            assert screen._detail_finding is None

    async def test_zero_findings_never_claim_security(self, tmp_path) -> None:
        app, _backend = _explorer_app(tmp_path)
        async with app.run_test() as pilot:
            screen = await open_scan(pilot, _backend)
            _explorer_screen(screen)
            screen._findings = ()
            screen._render_findings()
            text = _text_of(
                screen.query_one("#scan-findings-count", Label))
            assert "0 of 0" in text
            note = _text_of(screen.query_one("#scan-note", Label))
            assert "not thereby certified secure" in note
            assert "not reported as passed" in note
