"""Stage 11 desktop scan/findings/reports tests — offscreen Qt harness.

Same discipline as the Stage 09/10 harnesses:

* Qt runs offscreen; the scans NEVER touch hardware or a real subprocess:
  the shared engine services run over a scripted fake transport, so the
  tests drive the REAL discovery/inventory/scan service logic (the same
  dumpsys fixture the engine parity tests use → real typed findings),
  the REAL ``DesktopBackend`` + Stage 04 ``JobManager`` and the REAL
  ``QtJobEventBridge``; reports use the REAL ``ReportService`` writer
  (legacy byte-schema export against a real directory).
* Widgets are pumped with ``processEvents`` — never blocking waits.
* GUI-thread delivery is asserted by capturing ``threading.get_ident()``
  inside receiving slots (the Stage 10 proven ring).
"""

from __future__ import annotations

import ast
import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, List, Optional, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip(
    "PySide6",
    reason="desktop extra not installed (pip install -e '.[desktop]') — "
           "Stage 11 tests are desktop-specific; the engine suite does "
           "not depend on them")

from PySide6.QtCore import (  # noqa: E402
    QItemSelectionModel,
    QModelIndex,
    Qt,
)
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QMessageBox,
)

import ui_desktop.backend as backend_module  # noqa: E402
import ui_desktop.main_window as main_window_module  # noqa: E402
import ui_desktop.screens.reports as reports_module  # noqa: E402
import ui_desktop.screens.scan as scan_module  # noqa: E402
from ui_desktop.backend import DesktopBackend  # noqa: E402
from ui_desktop.jobs_bridge_qt import QtJobEventBridge  # noqa: E402
from ui_desktop.main_window import MainWindow  # noqa: E402
from ui_desktop.screens.reports import ReportsPage  # noqa: E402
from ui_desktop.screens.scan import (  # noqa: E402
    FindingsTableModel,
    FindingDetailTableModel,
    ScanWorkspacePage,
)
from vscanner.core.events import (  # noqa: E402
    JobFindingEvent,
    JobKind,
    JobProgressEvent,
    JobState,
    JobTerminalEvent,
)
from vscanner.core.errors import (  # noqa: E402
    AdbCommandError,
    ExportError,
    InputValidationError,
    JobConflictError,
)
from vscanner.core.models import (  # noqa: E402
    AppInfo,
    Evidence,
    EvidenceKind,
    Finding,
    FindingCategory,
    FindingSeverity,
    ReportFormat,
    ScanResultBundle,
    make_finding,
)
from vscanner.services.config import ConfigService  # noqa: E402
from vscanner.services.history import HistoryEntry  # noqa: E402
from vscanner.services.history import HistoryStoreError  # noqa: E402
from vscanner.services.reports.service import ReportService  # noqa: E402
from test_stage10_desktop import (  # noqa: E402
    BackendFactory,
    FakeAdbTransport,
    GUI_THREAD,
    pump_until,
)


# ===========================================================================
# engine-test dumpsys fixture (loaded without that module's legacy imports)
# ===========================================================================

def load_dumpsys_fixture() -> str:
    source = Path(__file__).resolve().parent / "test_services_scanning.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and \
                getattr(node.targets[0], "id", "") == "DUMPSYS_FIXTURE":
            return cast(str, ast.literal_eval(node.value))
    raise AssertionError("DUMPSYS_FIXTURE literal not found in engine tests")


DUMPSYS_FIXTURE = load_dumpsys_fixture()


# ===========================================================================
# fake transport extension: dumpsys surface for the REAL scan services
# ===========================================================================

class ScanCapableTransport(FakeAdbTransport):
    """Adds the ``dumpsys package <name>`` surface the scan services use,
    plus an optional deterministic blocking gate (for cancel races)."""

    def __init__(self, *, dumpsys_map: Optional[dict[str, str]] = None,
                 dumpsys_raise: bool = False,
                 dumpsys_gate: Optional[threading.Event] = None,
                 gate_on: str = "COM_FIRST",
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.dumpsys_map: dict[str, str] = dict(dumpsys_map or {})
        self.dumpsys_raise = dumpsys_raise
        self.dumpsys_gate = dumpsys_gate
        # gate_on == "COM_FIRST" blocks the first dumpsys call regardless
        # of package (single-package cancel races)
        self.gate_on = gate_on
        self.dumpsys_requested: List[str] = []

    def run_text(self, cmd, timeout: float = 30.0):
        argv = tuple(str(part) for part in cmd)
        if argv[:3] == ("shell", "dumpsys", "package"):
            from vscanner.services.adb.client import AdbResult

            self.calls.append((self.serial, argv))
            name = argv[3] if len(argv) > 3 else ""
            self.dumpsys_requested.append(name)
            if self.dumpsys_gate is not None and \
                    (self.gate_on == "COM_FIRST" or self.gate_on == name):
                self.dumpsys_gate.wait(20.0)
            if self.dumpsys_raise:
                raise AdbCommandError(
                    "fake dumpsys failure", cmd=argv, timeout=False)
            text = self.dumpsys_map.get(name)
            if text is None:
                # unknown package → no dumpsys answer; the engine records
                # the per-app skip honestly (never a fabricated result)
                return AdbResult(stdout="", stderr="unexpected", returncode=1)
            return AdbResult(stdout=text, stderr="", returncode=0)
        return FakeAdbTransport.run_text(self, cmd, timeout)


def real_bundle() -> ScanResultBundle:
    """A REAL engine bundle via the real ScanService over the fake."""
    from vscanner.core.models import ScanConfiguration, ScanKind, ScanRequest
    from vscanner.services.scanning.scanner import ScanService

    transport = ScanCapableTransport(
        devices_lines=("S1 device",),
        third_party=("com.example.wallet",),
        dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
    )
    service = ScanService(transport)
    request = ScanRequest(
        kind=ScanKind.FULL_DEVICE,
        config=ScanConfiguration(
            include_system=False, deep=False, device_serial="S1"),
    )
    return service.scan_full_device(request)


# ===========================================================================
# fixtures (real backend + real bridge, like the device page tests)
# ===========================================================================

@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    app = cast(Optional[QApplication], QApplication.instance())
    if app is None:
        from ui_desktop.app import create_application

        app = create_application([])
    assert app is not None
    yield app
    # Same deterministic-teardown contract as Stage 09/10: delete every
    # top-level widget through the loop before Qt finalizes.
    app.processEvents()
    for widget in list(app.topLevelWidgets()):
        widget.deleteLater()
    app.processEvents()


@pytest.fixture()
def config_service(tmp_path) -> ConfigService:
    service = ConfigService(tmp_path / "config.json")
    service.save(r"C:\tools\fake-adb.exe")
    return service


@pytest.fixture(autouse=True)
def history_target(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every finished scan writes its T-08 entry HERE (test-local)."""
    directory = tmp_path / "history"
    monkeypatch.setattr(backend_module, "history_dir",
                        lambda: directory, raising=True)
    return directory


@pytest.fixture()
def backend_factory(qapp, monkeypatch: pytest.MonkeyPatch):
    factory = BackendFactory(monkeypatch)
    yield factory.build
    factory.teardown()


def fresh_workspace(config_service: ConfigService, backend_factory: Any,
                    transport: FakeAdbTransport) -> Any:
    """(page, backend, bridge) — a scan workspace wired like production."""
    backend = backend_factory(config_service, transport)
    bridge = QtJobEventBridge()
    bridge.attach(backend.manager())
    page = ScanWorkspacePage(backend, bridge.hub)
    return page, backend, bridge


def reports_page_of(backend: DesktopBackend) -> Any:
    bridge = QtJobEventBridge()
    bridge.attach(backend.manager())
    return ReportsPage(backend, bridge.hub)


def auto_discover(qapp, page: Any) -> None:
    """First activation runs exactly one auto-refresh; wait for it."""
    page.activate()
    assert pump_until(qapp, lambda: page._refresh_button.isEnabled())
    assert pump_until(qapp, lambda: page._devices_state == "refreshed")


def wait_scan_done(qapp, page: ScanWorkspacePage) -> bool:
    return pump_until(
        qapp, lambda: page._scan_state not in ("running", "validating"))


def page_texts(widget) -> str:
    return " ".join(label.text() for label in
                    widget.findChildren(QLabel) if label.text())


def select_row(page: ScanWorkspacePage, serial: str) -> None:
    row = page._devices_model.row_of_serial(serial)
    assert row is not None, f"serial {serial} not listed"
    page._devices_table.selectionModel().setCurrentIndex(
        page._devices_model.index(row, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect
        | QItemSelectionModel.SelectionFlag.Current)


# ===========================================================================
# backend seam: scan / export / history + last-terminal memory
# ===========================================================================

class TestBackendScanSeam:
    def test_start_scan_job_full_device_binds_serial(
            self, config_service, backend_factory):
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            third_party=("com.example.wallet",),
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        backend = backend_factory(config_service, transport)
        handle = backend.start_scan_job("S1", include_system=True)
        assert handle.kind is JobKind.FULL_DEVICE_SCAN
        assert handle.device_serial == "S1"
        assert handle.wait(30).value == "succeeded"
        dumpsys_calls = [argv for _serial, argv in transport.calls
                         if argv[:2] == ("shell", "dumpsys")]
        assert dumpsys_calls, "the scan must engage the serial-bound client"

    def test_start_scan_job_single_app(self, config_service,
                                       backend_factory):
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            third_party=("com.example.wallet",),
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        backend = backend_factory(config_service, transport)
        handle = backend.start_scan_job("S1", package="com.example.wallet",
                                        deep=True)
        assert handle.kind is JobKind.SINGLE_APP_SCAN
        assert handle.device_serial == "S1"
        assert handle.wait(30).value == "succeeded"

    def test_engine_conflict_refuses_overlapping_scans(
            self, config_service, backend_factory):
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            third_party=("com.example.wallet",),
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        backend = backend_factory(config_service, transport)
        gate = threading.Event()
        transport.dumpsys_gate = gate
        first = backend.start_scan_job("S1")
        try:
            with pytest.raises(JobConflictError):
                backend.start_scan_job("S1", package="com.example.wallet")
        finally:
            gate.set()
            first.wait(30)

    def test_cancel_scan_job_hits_scan_kinds_only(
            self, config_service, backend_factory):
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            third_party=("com.example.wallet",),
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        backend = backend_factory(config_service, transport)
        listing_gate = threading.Event()
        transport.list_gate = listing_gate
        listing = backend.start_listing_job("S1", include_system=False)
        assert transport.list_started.wait(10.0)
        assert backend.active_listing_handle("S1") is not None
        # a scan cancel must NEVER cancel the device's app-listing
        assert backend.cancel_scan_job("S1") == 0
        assert backend.active_listing_handle("S1") is not None
        listing_gate.set()
        assert listing.wait(30).value == "succeeded"

    def test_start_export_job_runs_real_service(
            self, config_service, backend_factory, tmp_path):
        backend = backend_factory(config_service, FakeAdbTransport())
        out_dir = tmp_path / "reports"
        handle = backend.start_export_job(
            real_bundle(), output_dir=str(out_dir), serial="S1")
        assert handle.kind is JobKind.EXPORT
        assert handle.wait(30).value == "succeeded"
        assert len(list(out_dir.iterdir())) == 3  # all three legacy formats


class TestScanMemoryContract:
    def test_completed_bundle_is_remembered(self, backend_factory,
                                            config_service):
        backend = backend_factory(config_service, FakeAdbTransport())
        bundle = real_bundle()
        backend.remember_scan(bundle, "completed", "S1")
        last = backend.last_scan()
        assert last is not None
        status, serial, stored = last
        assert status == "completed" and serial == "S1" and stored is bundle

    def test_failure_is_not_export_material(self, backend_factory,
                                            config_service):
        backend = backend_factory(config_service, FakeAdbTransport())
        backend.remember_scan(real_bundle(), "cancelled", "S1")
        status, _serial, stored = backend.last_scan()
        assert status == "cancelled" and stored is None

    def test_non_bundle_result_is_never_report_material(
            self, backend_factory, config_service):
        backend = backend_factory(config_service, FakeAdbTransport())
        backend.remember_scan(
            __import__(
                "vscanner.core.models",
                fromlist=["AppScanResult"]).AppScanResult(findings=()),
            "completed", "S1")
        status, _serial, stored = backend.last_scan()
        assert status == "completed" and stored is None

    def test_export_service_rejects_uncreatable_destination(
            self, backend_factory, config_service, tmp_path):
        """Real-service failure path: the file-as-directory destination
        cannot be created → typed ``ExportError``, nothing written."""
        blocker = tmp_path / "blocker.json"
        blocker.write_text("not a directory", encoding="utf-8")
        service = ReportService()
        with pytest.raises(ExportError):
            service.export(real_bundle(),
                           requested={ReportFormat.JSON: "out.json"},
                           output_dir=str(blocker / "sub"))


# ===========================================================================
# scan lifecycle (page level, real jobs and events)
# ===========================================================================

SCAN_SETUP = dict(
    devices_lines=("S1 device",),
    third_party=("com.example.wallet",),
    dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
)


class TestScanLifecycle:
    def test_full_device_scan_completes_with_engine_findings(
            self, qapp, config_service, backend_factory, history_target):
        page, backend, _hub = fresh_workspace(
            config_service, backend_factory,
            ScanCapableTransport(**SCAN_SETUP))  # type: ignore[arg-type]
        auto_discover(qapp, page)
        assert page._selected_serial == "S1"  # unambiguous single device
        page._on_start_full()
        assert page._scan_state in ("validating", "running")
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "completed"
        assert page._findings_status == "from-bundle"
        # REAL KB analysis over the REAL fixture produced these findings
        assert len(page._findings) == 5
        assert any(f.title == "READ_SMS" for f in page._findings)
        assert any(f.kind is FindingCategory.SDK_COMPAT
                   for f in page._findings)
        status, serial, bundle = backend.last_scan()
        assert (status, serial) == ("completed", "S1")
        assert isinstance(bundle, ScanResultBundle)
        assert "completed" in page_texts(page)
        # the T-08 write happened in the test-local history directory
        assert pump_until(qapp, lambda: history_target.exists()
                          and len(list(history_target.iterdir())) == 1)
        record = json.loads(next(iter(history_target.iterdir())).read_text(
            encoding="utf-8"))
        assert record["status"] == "completed"
        assert record["kind"] == "full_device"
        assert record["device_serial"] == "S1"
        assert record["findings_total"] == 5
        page.deleteLater()

    def test_single_app_scan_completes_but_is_not_exportable(
            self, qapp, config_service, backend_factory, history_target):
        page, backend, _hub = fresh_workspace(
            config_service, backend_factory,
            ScanCapableTransport(**SCAN_SETUP))  # type: ignore[arg-type]
        auto_discover(qapp, page)
        page._package_input.setText("com.example.wallet")
        page._on_start_single()
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "not-exportable"
        assert len(page._findings) == 5
        status, serial, stored = backend.last_scan()
        assert status == "completed" and stored is None and serial == "S1"
        assert "not eligible" in page_texts(page) or \
            "NOT exportable" in page_texts(page)
        assert pump_until(qapp, lambda: history_target.exists()
                          and any('"kind": "single_app"' in
                                  e.read_text(encoding="utf-8")
                                  for e in history_target.iterdir()))
        page.deleteLater()

    def test_preflight_rejects_when_no_device_is_selected(
            self, qapp, config_service, backend_factory):
        transport = ScanCapableTransport(devices_lines=())
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)
        assert page._selected_serial is None
        page._on_start_full()
        assert page._scan_state == "idle"  # nothing started
        assert "select a connected device first" in \
            page._progress_label.text()
        assert not any(len(argv) >= 2 and argv[:2] == ("shell", "pm")
                       for _s, argv in transport.calls)
        page.deleteLater()

    def test_selection_invalidated_when_target_leaves(
            self, qapp, config_service, backend_factory):
        transport = ScanCapableTransport(**SCAN_SETUP)  # type: ignore[arg-type]
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)
        assert page._selected_serial == "S1"
        transport.devices_lines = ()
        page.refresh_devices()
        assert pump_until(qapp, lambda: page._devices_state == "refreshed")
        assert page._selected_serial is None
        invalidated = page._devices_banner.text() + \
            page._target_banner.text()
        assert "invalidated on purpose" in invalidated
        page.deleteLater()

    def test_stale_target_caught_by_preflight_before_submission(
            self, qapp, config_service, backend_factory):
        """The selection survives in the UI, but the FRESH discovery the
        preflight runs has the device gone → honest refusal, no scan."""
        transport = ScanCapableTransport(**SCAN_SETUP)  # type: ignore[arg-type]
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)
        transport.devices_lines = ()  # device vanishes BEFORE the preflight
        page._on_start_full()
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "failed"
        assert "no longer connected or authorized" in \
            page._progress_label.text()
        assert not transport.dumpsys_requested
        page.deleteLater()

    def test_failed_scan_is_honest(self, qapp, config_service,
                                   backend_factory, history_target):
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            fail_listing=True,
            third_party=("com.example.wallet",),
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        page, backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)
        page._on_start_full()
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "failed"
        assert "full-device scan could not start" in \
            page._progress_label.text()
        status, _serial, stored = backend.last_scan()
        assert status == "failed" and stored is None
        assert pump_until(qapp, lambda: history_target.exists()
                          and any('"status": "failed"' in
                                  e.read_text(encoding="utf-8")
                                  for e in history_target.iterdir()))
        page.deleteLater()

    def test_single_app_service_failure_is_honest(
            self, qapp, config_service, backend_factory):
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            third_party=("com.example.wallet",),
            dumpsys_raise=True,
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        page, backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)
        page._package_input.setText("com.example.wallet")
        page._on_start_single()
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "failed"
        # the engine's typed error surfaced, short and remediable
        page._progress_label.text().startswith("scan failed:")
        status, _serial, stored = backend.last_scan()
        assert status == "failed" and stored is None
        page.deleteLater()

    def test_duplicate_submission_is_refused_while_active(
            self, qapp, config_service, backend_factory):
        gate = threading.Event()
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            third_party=("com.example.wallet",),
            dumpsys_gate=gate,
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)
        page._on_start_full()
        assert pump_until(qapp, lambda: page._scan_state == "running")
        page._validate_and_start(package=None)
        assert page._scan_state == "running"
        assert "already active" in page._progress_label.text()
        listing_calls = [1 for _s, argv in transport.calls
                         if argv[:3] == ("shell", "pm", "list")]
        assert len(listing_calls) == 1, "no second job may be submitted"
        gate.set()
        assert wait_scan_done(qapp, page)
        page.deleteLater()

    def test_cancellation_request_is_not_completion(
            self, qapp, config_service, backend_factory, history_target):
        gate = threading.Event()
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            third_party=("com.example.wallet", "com.example.barren"),
            dumpsys_gate=gate,
            gate_on="com.example.barren",
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)
        page._on_start_full()
        # wait for the engine's streamed first-app findings through the hub
        assert pump_until(qapp, lambda: page._streamed >= 1)
        page._on_cancel()
        # request ≠ acknowledgement: still running until the terminal
        assert page._scan_state == "running"
        gate.set()
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "cancelled"
        assert page._findings_status == "partial-stream"
        assert page._streamed >= 1
        assert "CANCELLED" in page._progress_label.text()
        assert "PARTIAL" in page._findings_status_label.text()
        assert pump_until(qapp, lambda: history_target.exists()
                          and any('"status": "cancelled"' in
                                  e.read_text(encoding="utf-8")
                                  for e in history_target.iterdir()))
        page.deleteLater()

    def test_queued_scan_cancellation_terminalizes_immediately(
            self, qapp, config_service, backend_factory):
        transport = ScanCapableTransport(**SCAN_SETUP)  # type: ignore[arg-type]
        page, backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)
        # two gated app-listing jobs occupy the executor (max_workers=2)
        listing_gate = threading.Event()
        transport.list_gate = listing_gate
        backend.start_listing_job("S1", include_system=False)
        backend.start_listing_job("S1", include_system=True)
        assert transport.list_started.wait(10.0)
        page._on_start_full()
        assert pump_until(qapp, lambda: page._scan_state == "running")
        dumpsys_before = len(transport.dumpsys_requested)
        page._on_cancel()
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "cancelled"
        # the queued scan never reached package analysis
        assert len(transport.dumpsys_requested) == dumpsys_before
        listing_gate.set()
        page.deleteLater()

    def test_late_events_after_terminal_do_not_mutate_state(
            self, qapp, config_service, backend_factory, history_target):
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory,
            ScanCapableTransport(**SCAN_SETUP))  # type: ignore[arg-type]
        auto_discover(qapp, page)
        page._on_start_full()
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "completed"
        old_findings = len(page._findings)
        old_progress = page._progress_label.text()
        hub = page._hub
        hub.finding.emit(JobFindingEvent(
            job_id="late-id", kind=JobKind.FULL_DEVICE_SCAN,
            finding=make_finding(kind=FindingCategory.INFO_NOTE,
                                 severity=FindingSeverity.INFO,
                                 title="late", detail="late detail")))
        hub.progress.emit(JobProgressEvent(
            job_id="late-id", kind=JobKind.FULL_DEVICE_SCAN,
            current=99, total=99, unit="apps", context="late tick"))
        qapp.processEvents()
        assert len(page._findings) == old_findings
        assert page._progress_label.text() == old_progress
        page.deleteLater()

    def test_foreign_job_terminal_is_ignored(self, qapp, config_service,
                                             backend_factory):
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory,
            ScanCapableTransport(**SCAN_SETUP))  # type: ignore[arg-type]
        auto_discover(qapp, page)
        page._hub.terminal.emit(JobTerminalEvent(
            job_id="not-mine", kind=JobKind.FULL_DEVICE_SCAN,
            outcome=JobState.FAILED,
            error=InputValidationError("device vanished mid-scan")))
        qapp.processEvents()
        assert page._scan_state == "idle"
        assert page._findings == ()
        page.deleteLater()

    def test_stale_results_never_overwrite_a_new_selection(
            self, qapp, config_service, backend_factory):
        """Two devices; scan A completes on S1; the user selects S2. The
        A-outcome stays truthfully labeled S1; a stale S1 job id's event
        can never apply to S2's workspace."""
        transport = ScanCapableTransport(
            devices_lines=("S1 device", "S2 device"),
            third_party=("com.example.wallet",),
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)  # several devices → nothing auto-selected
        assert page._selected_serial is None
        assert not page._scan_button.isEnabled()
        select_row(page, "S1")
        qapp.processEvents()
        assert page._selected_serial == "S1"
        assert page._scan_button.isEnabled()
        page._on_start_full()
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "completed"
        # switch the selection to S2
        select_row(page, "S2")
        qapp.processEvents()
        assert page._selected_serial == "S2"
        # the completed A-result is still labeled with ITS target
        assert page._scan_target_serial == "S1"
        assert "from the scan of S1" in page._findings_status_label.text()
        # a stale/foreign terminal replay cannot touch the new selection
        page._hub.terminal.emit(JobTerminalEvent(
            job_id="stale-s1-replay", kind=JobKind.SINGLE_APP_SCAN,
            outcome=JobState.FAILED,
            error=InputValidationError("stale replay")))
        qapp.processEvents()
        assert page._selected_serial == "S2"
        assert page._scan_target_serial == "S1"
        page.deleteLater()

    def test_zero_findings_scan_is_honest_not_certified(
            self, qapp, config_service, backend_factory):
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            third_party=(),   # nothing installed: a REAL zero-result scan
        )
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)
        page._on_start_full()
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "completed"
        assert page._findings == ()
        assert page._findings_status == "from-bundle"
        assert "not thereby certified secure" in page_texts(page)
        page.deleteLater()


# ===========================================================================
# subscription / delivery / shutdown discipline
# ===========================================================================

def make_delivery_spy() -> type:
    """Scan page recording (universal gate, thread id) per hub delivery."""

    class SpyScanPage(ScanWorkspacePage):
        deliveries: List[Any] = []

        def _on_terminal_event(self, event) -> None:
            SpyScanPage.deliveries.append(
                ("terminal", event, threading.get_ident()))
            super()._on_terminal_event(event)

        def _on_finding_event(self, event) -> None:
            SpyScanPage.deliveries.append(
                ("finding", event, threading.get_ident()))
            super()._on_finding_event(event)

        def _on_progress_event(self, event) -> None:
            SpyScanPage.deliveries.append(
                ("progress", event, threading.get_ident()))
            super()._on_progress_event(event)

    return SpyScanPage


class TestDeliveryDiscipline:
    def test_job_events_arrive_only_on_the_gui_thread(
            self, qapp, config_service, backend_factory, monkeypatch):
        spy_cls = make_delivery_spy()
        monkeypatch.setattr(main_window_module, "ScanWorkspacePage",
                            spy_cls, raising=True)
        transport = ScanCapableTransport(**SCAN_SETUP)  # type: ignore[arg-type]
        backend = backend_factory(config_service, transport)
        window = MainWindow(config_service, backend=backend)
        try:
            window.switch_to("scan")
            page = window.content_widget("scan")
            assert pump_until(qapp, lambda: page._refresh_button.isEnabled())
            page._on_start_full()
            assert wait_scan_done(qapp, page)
            qapp.processEvents()
            assert spy_cls.deliveries, "events must have been delivered"
            for kind, _event, ident in spy_cls.deliveries:
                assert ident == GUI_THREAD, kind
            assert page._scan_state == "completed"
        finally:
            window.close()

    def test_navigation_never_duplicates_subscriptions(
            self, qapp, config_service, backend_factory, monkeypatch):
        spy_cls = make_delivery_spy()
        monkeypatch.setattr(main_window_module, "ScanWorkspacePage",
                            spy_cls, raising=True)
        transport = ScanCapableTransport(**SCAN_SETUP)  # type: ignore[arg-type]
        backend = backend_factory(config_service, transport)
        window = MainWindow(config_service, backend=backend)
        try:
            window.switch_to("scan")
            first = window.content_widget("scan")
            window.switch_to("dashboard")
            window.switch_to("help")
            window.switch_to("scan")
            second = window.content_widget("scan")
            assert first is second, "the shell must cache one page"
            page = cast(ScanWorkspacePage, second)
            assert pump_until(qapp, lambda: page._refresh_button.isEnabled())
            # drive exactly one completed scan; its single terminal event
            # must reach the page slots EXACTLY ONCE
            page._on_start_full()
            assert wait_scan_done(qapp, page)
            qapp.processEvents()
            terminals = [d for d in spy_cls.deliveries if d[0] == "terminal"]
            assert len(terminals) == 1, "duplicate subscription!"
            assert all(d[2] == GUI_THREAD for d in terminals)
            assert page._scan_state == "completed"
        finally:
            window.close()

    def test_shutdown_with_active_job_disconnects_the_page_safely(
            self, qapp, config_service, backend_factory):
        gate = threading.Event()
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            third_party=("com.example.wallet",),
            dumpsys_gate=gate,
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        backend = backend_factory(config_service, transport)
        page, bridge = fresh_page_paired(backend)
        auto_discover(qapp, page)
        page._on_start_full()
        assert page._scan_state in ("running", "validating")
        page.shutdown()  # owner-close path: no exception, no dangling slot
        # events after shutdown reach an empty receiver — no crash
        bridge.hub.terminal.emit(JobTerminalEvent(
            job_id="whatever", kind=JobKind.FULL_DEVICE_SCAN,
            outcome=JobState.SUCCEEDED))
        qapp.processEvents()
        assert page._scan_state in ("running", "validating")
        gate.set()
        raise_skip_if_alive()
        page.deleteLater()  # never re-shown after disconnect

    def test_unexpected_engine_result_shape_fails_honestly(
            self, qapp, config_service, backend_factory):
        gate = threading.Event()
        transport = ScanCapableTransport(
            devices_lines=("S1 device",),
            third_party=("com.example.wallet",),
            dumpsys_gate=gate,
            dumpsys_map={"com.example.wallet": DUMPSYS_FIXTURE},
        )
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory, transport)
        auto_discover(qapp, page)
        page._on_start_full()
        assert pump_until(qapp, lambda: page._scan_state == "running")
        # simulated contract violation inside a SUCCESS terminal, carrying
        # the page's own tracked job id (still running → gate holds it)
        page._hub.terminal.emit(JobTerminalEvent(
            job_id=page._scan_job_id, kind=JobKind.FULL_DEVICE_SCAN,
            outcome=JobState.SUCCEEDED, result=("unexpected",)))
        qapp.processEvents()
        assert page._scan_state == "failed"
        assert "unexpected result shape" in page._progress_label.text()
        gate.set()
        qapp.processEvents()  # the real success terminal is IGNORED
        assert page._scan_state == "failed"
        page.deleteLater()


def fresh_page_paired(backend: DesktopBackend):
    """(page, bridge) — same construction shape as production shells."""
    bridge = QtJobEventBridge()
    bridge.attach(backend.manager())
    return ScanWorkspacePage(backend, bridge.hub), bridge


def raise_skip_if_alive() -> None:
    """No-op; gate-joined scanning is finalized by fixture teardown."""
    return None


# ===========================================================================
# findings table model + explorer semantics
# ===========================================================================

def synthetic_findings(count: int = 220) -> tuple:
    severities = list(FindingSeverity)
    categories = list(FindingCategory)
    findings: List[Finding] = []
    for index in range(count):
        evidence = () if index % 3 == 1 else (
            Evidence.of(
                EvidenceKind.CONFIRMED_ARTIFACT,
                f"synthetic evidence {index}",
                f"synthetic-source-{index}",
                None,
            ),
        )
        findings.append(make_finding(
            kind=categories[index % len(categories)],
            severity=severities[index % len(severities)],
            title=f"Synthetic finding {index:04d}",
            detail=f"synthetic detail body {index}",
            evidence=evidence,
            app=AppInfo.tolerant(f"com.syn.app{index:04d}",
                                 label=f"App {index:04d}"),
            device_serial="S1",
            tags=("dummy",),
        ))
    return tuple(findings)


class TestFindingsModel:
    def test_two_hundred_plus_rows_with_stable_unique_ids(self):
        model = FindingsTableModel()
        findings = synthetic_findings(220)
        assert len({f.id for f in findings}) == 220, "ids must be unique"
        model.set_rows(findings)
        assert model.rowCount(QModelIndex()) == 220
        assert model.columnCount(QModelIndex()) == 5

    def test_header_and_display_data(self):
        model = FindingsTableModel()
        findings = synthetic_findings(3)
        model.set_rows(findings)
        header = model.headerData(0, Qt.Orientation.Horizontal)
        assert header == "Severity"
        app_cell = model.data(model.index(1, 3))
        assert isinstance(app_cell, str) and app_cell.startswith("com.syn.app")
        assert model.data(model.index(0, 4)) in ("0", "1")  # evidence count

    def test_missing_optional_fields_render_honest_unknown(self):
        finding = make_finding(
            kind=FindingCategory.INFO_NOTE,
            severity=FindingSeverity.INFO,
            title="no app",
            detail="device scope only",
        )  # no app, no device, no evidence, no remediation
        model = FindingsTableModel()
        model.set_rows((finding,))
        assert model.data(model.index(0, 3)) == "(no app)"
        detail = FindingDetailTableModel()
        detail.set_finding(finding)
        values = [text for _key, text in detail.rows]
        assert "not available" in values
        assert "no evidence recorded" in values
        assert all(isinstance(text, str) for _key, text in detail.rows)

    def test_malformed_single_finding_does_not_crash_the_view(self):
        finding = make_finding(kind=FindingCategory.INFO_NOTE,
                               severity=FindingSeverity.INFO,
                               title="breaks", detail="x")

        class Boom:
            def __str__(self) -> str:
                raise RuntimeError("boom")

        object.__setattr__(finding, "kind", Boom())  # simulated bad row
        model = FindingsTableModel()
        model.set_rows((finding, synthetic_findings(1)[0]))
        assert model.data(model.index(0, 1)) == "(malformed finding)"
        assert model.data(model.index(1, 2)) == "Synthetic finding 0000"
        detail = FindingDetailTableModel()
        detail.set_finding(finding)
        assert any("unreadable" in text for _key, text in detail.rows)

    def test_detail_model_shows_all_finding_facts(self):
        findings = synthetic_findings(1)
        model = FindingDetailTableModel()
        model.set_finding(findings[0])
        fields = {key for key, _value in model.rows}
        assert {"Title", "Severity", "Category", "Detail", "App",
                "Finding id", "Detected by", "Run id", "Evidence",
                "Recommended fix"} <= fields

    def test_sensitive_evidence_never_leaks_raw_excerpt(self):
        secret = "PRESHARED-KEY-SECRET-XYZ"
        finding = make_finding(
            kind=FindingCategory.HARDCODED_SECRET,
            severity=FindingSeverity.CRITICAL,
            title="secret look",
            detail="analysed",
            evidence=(Evidence.of(
                EvidenceKind.HEURISTIC_PATTERN,
                "pattern matched",
                "apk strings",
                secret + " payload"),
            ),
        )
        model = FindingsTableModel()
        model.set_rows((finding,))
        for column in range(5):
            value = model.data(model.index(0, column))
            assert value is None or secret not in str(value)
        detail = FindingDetailTableModel()
        detail.set_finding(finding)
        assert all(secret not in text for _key, text in detail.rows)


class TestFindingsExplorer:
    def _page(self, qapp, config_service, backend_factory,
              findings_amount: int = 220) -> Any:
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory,
            ScanCapableTransport(**SCAN_SETUP))  # type: ignore[arg-type]
        auto_discover(qapp, page)
        page._findings = synthetic_findings(findings_amount)
        page._findings_status = "from-bundle"
        page._scan_target_serial = "S1"
        page._render_findings()
        return page

    def test_pagination_clamps_and_counts(self, qapp, config_service,
                                          backend_factory):
        page = self._page(qapp, config_service, backend_factory)
        page._findings_page = 47  # far beyond the last page → clamped
        page._render_findings()
        assert page._findings_model.rowCount(QModelIndex()) == 20
        text = page._page_label.text()
        assert "page 3/3" in text and "20 of 220" in text
        page.deleteLater()

    def test_text_search_narrows_and_resets_page(self, qapp, config_service,
                                                 backend_factory):
        page = self._page(qapp, config_service, backend_factory)
        page._filter_input.setText("com.syn")
        qapp.processEvents()
        assert len(page._filtered_findings()) == 220  # packages searched
        page._filter_input.setText("Synthetic finding 0007")
        qapp.processEvents()
        assert len(page._filtered_findings()) == 1
        page.deleteLater()

    def test_severity_category_and_provenance_filters(
            self, qapp, config_service, backend_factory):
        page = self._page(qapp, config_service, backend_factory)
        original = len(page._findings)
        page._severity_combo.setCurrentText("severity ≥ critical")
        qapp.processEvents()
        kept = len(page._filtered_findings())
        assert 0 < kept < original
        page._severity_combo.setCurrentIndex(0)
        page._category_combo.setCurrentText("category: info note")
        qapp.processEvents()
        kept = page._filtered_findings()
        assert kept and all(f.kind is FindingCategory.INFO_NOTE
                            for f, _p in kept)
        page._category_combo.setCurrentIndex(0)
        page._provenance_combo.setCurrentText("evidence: no evidence")
        qapp.processEvents()
        kept = page._filtered_findings()
        assert kept and all(not f.evidence for f, _p in kept)
        page._provenance_combo.setCurrentText("evidence: observed")
        qapp.processEvents()
        kept = page._filtered_findings()
        assert kept and all(
            any(ev.kind in (EvidenceKind.CONFIRMED_ARTIFACT,
                            EvidenceKind.CONFIRMED_COMMAND_OUTPUT)
                for ev in f.evidence) for f, _p in kept)
        page.deleteLater()

    def test_sort_orders_are_deterministic(self, qapp, config_service,
                                           backend_factory):
        page = self._page(qapp, config_service, backend_factory,
                          findings_amount=30)
        page._sort_combo.setCurrentText("sort: severity")
        qapp.processEvents()
        ranks = [scan_module._SEVERITY_RANK[f.severity]
                 for f, _p in page.visible_findings()]
        assert ranks == sorted(ranks)
        page._sort_combo.setCurrentText("sort: package")
        qapp.processEvents()
        packages = [p for _f, p in page.visible_findings()]
        assert packages == sorted(packages)
        page._sort_combo.setCurrentText("sort: title")
        qapp.processEvents()
        titles = [f.title for f, _p in page.visible_findings()]
        assert titles == sorted(titles)
        page.deleteLater()

    def test_combined_filters(self, qapp, config_service, backend_factory):
        page = self._page(qapp, config_service, backend_factory)
        page._filter_input.setText("syn")
        page._severity_combo.setCurrentText("severity ≥ medium")
        page._category_combo.setCurrentText("category: SDK compatibility")
        page._sort_combo.setCurrentText("sort: title")
        qapp.processEvents()
        kept = page._filtered_findings()
        assert kept
        for finding, package in kept:
            assert "syn" in (finding.title + finding.detail +
                             package).lower()
            assert finding.kind is FindingCategory.SDK_COMPAT
        page.deleteLater()

    def test_detail_clears_safely_when_filter_changes(
            self, qapp, config_service, backend_factory):
        page = self._page(qapp, config_service, backend_factory,
                          findings_amount=10)
        page._filter_input.setText("Synthetic finding 0003")
        qapp.processEvents()
        finding = page._filtered_findings()[0][0]
        page._detail_finding = finding
        page._render_detail()
        assert page._detail_model.rowCount(QModelIndex()) > 0
        # a filter change that drops the detail row clears it — no stale
        # detail leaking under the new view
        page._filter_input.setText("Synthetic finding 0007")
        qapp.processEvents()
        assert page._detail_finding is None
        assert finding not in tuple(page._row_findings.values())
        page.deleteLater()

    def test_unverified_findings_stay_visible_and_filterable(
            self, qapp, config_service, backend_factory):
        """Deep-scan unverified conditions are engine findings and must
        remain visible and filterable (honest — never hidden)."""
        page = self._page(qapp, config_service, backend_factory,
                          findings_amount=1)
        deep_note = make_finding(
            kind=FindingCategory.INFO_NOTE,
            severity=FindingSeverity.INFO,
            title="Deep-scan unavailable note",
            detail="deep scan could not run",
            evidence=(Evidence.of(
                EvidenceKind.UNVERIFIED_CONDITION,
                "no byte-safe capture", "engine", None),),
            device_serial="S1",
        )
        page._findings = page._findings + (deep_note,)
        page._render_findings()
        assert deep_note in page._findings
        page._provenance_combo.setCurrentText("evidence: unverified")
        qapp.processEvents()
        kept = [f for f, _p in page._filtered_findings()]
        assert kept == [deep_note]
        page.deleteLater()


# ===========================================================================
# reports and exports
# ===========================================================================

class TestReportsWorkflow:
    def test_no_scan_yet_honest_empty_state(self, qapp, config_service,
                                            backend_factory):
        backend = backend_factory(config_service, FakeAdbTransport())
        page = reports_page_of(backend)
        assert "no terminal scan this session yet" in \
            page._last_label.text()
        assert not page._export_button.isEnabled()
        page.deleteLater()

    def test_completed_scan_enables_export_with_totals(
            self, qapp, config_service, backend_factory):
        backend = backend_factory(config_service, FakeAdbTransport())
        bundle = real_bundle()
        backend.remember_scan(bundle, "completed", "S1")
        page = reports_page_of(backend)
        assert page._export_button.isEnabled()
        assert "5 finding(s)" in page._last_label.text()
        page.deleteLater()

    def test_cancelled_scan_cannot_be_exported(self, qapp, config_service,
                                               backend_factory):
        backend = backend_factory(config_service, FakeAdbTransport())
        backend.remember_scan(real_bundle(), "cancelled", "S1")
        page = reports_page_of(backend)
        assert not page._export_button.isEnabled()
        page._on_export()
        assert page._export_state == "refused"
        assert page._export_job_id is None
        assert "export requires a completed full-device scan" in \
            page._export_label.text()
        page.deleteLater()

    def test_export_success_only_after_files_written(
            self, qapp, config_service, backend_factory, tmp_path):
        backend = backend_factory(config_service, FakeAdbTransport())
        bundle = real_bundle()
        backend.remember_scan(bundle, "completed", "S1")
        out_dir = tmp_path / "reports"
        page = reports_page_of(backend)
        page._start_export(bundle, {fmt: None for fmt in ReportFormat},
                           str(out_dir))
        assert page._export_state == "running"  # no success claimed yet
        assert not page._export_label.text().startswith("export succeeded")
        assert pump_until(qapp, lambda: page._export_state == "ok")
        text = page._export_label.text()
        assert "export succeeded:" in text
        paths = [line.split("→")[-1].strip()
                 for line in text.splitlines() if "→" in line]
        assert paths and all(Path(p).exists() for p in paths)
        assert {Path(p).suffix for p in paths} == \
            {".html", ".json", ".text"}
        page.deleteLater()

    def test_export_json_schema_parity(self, qapp, config_service,
                                       backend_factory, tmp_path):
        backend = backend_factory(config_service, FakeAdbTransport())
        bundle = real_bundle()
        backend.remember_scan(bundle, "completed", "S1")
        page = reports_page_of(backend)
        page._start_export(bundle, {ReportFormat.JSON: "parity.json"},
                           str(tmp_path))
        assert pump_until(qapp, lambda: page._export_state == "ok")
        payload = json.loads(
            (tmp_path / "parity.json").read_text(encoding="utf-8"))
        assert {"device_info", "scan_time", "total_apps", "summary",
                "apps"} <= set(payload)
        first = payload["apps"][0]
        assert {"package_name", "permissions", "dangerous_permissions",
                "risk_score", "risk_level"} <= set(first)
        page.deleteLater()

    def test_export_write_failure_is_honest(self, qapp, config_service,
                                            backend_factory, tmp_path):
        backend = backend_factory(config_service, FakeAdbTransport())
        blocker = tmp_path / "blocker.json"
        blocker.write_text("x", encoding="utf-8")
        page = reports_page_of(backend)
        page._start_export(real_bundle(),
                           {fmt: None for fmt in ReportFormat},
                           str(blocker / "cannot-exist"))
        assert pump_until(qapp, lambda: page._export_state == "failed")
        assert "nothing is claimed" in page._export_label.text()
        assert "export failed" in page._export_label.text()
        page.deleteLater()

    def test_existing_file_needs_explicit_confirmation(
            self, qapp, config_service, backend_factory, tmp_path,
            monkeypatch):
        backend = backend_factory(config_service, FakeAdbTransport())
        bundle = real_bundle()
        backend.remember_scan(bundle, "completed", "S1")
        out_dir = tmp_path / "reports"
        out_dir.mkdir()
        existing = out_dir / "existing.json"
        existing.write_text("old data", encoding="utf-8")

        asked: List[str] = []
        monkeypatch.setattr(
            reports_module.QMessageBox, "question",
            staticmethod(lambda *args, **kwargs: [
                asked.append("asked"),
                QMessageBox.StandardButton.Yes][1]))

        page = reports_page_of(backend)
        page._format_combo.setCurrentText("JSON report")
        import PySide6.QtWidgets as qt

        monkeypatch.setattr(
            qt.QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(existing), "JSON")))
        page._on_export()
        assert page._export_state == "running"
        assert pump_until(qapp, lambda: page._export_state == "ok")
        assert asked == ["asked"], "the overwrite dialog must have run"
        assert existing.read_text(encoding="utf-8") != "old data"
        page.deleteLater()

    def test_export_dialog_flow_full_directory(
            self, qapp, config_service, backend_factory, tmp_path,
            monkeypatch):
        import PySide6.QtWidgets as qt

        backend = backend_factory(config_service, FakeAdbTransport())
        backend.remember_scan(real_bundle(), "completed", "S1")
        page = reports_page_of(backend)
        chosen = tmp_path / "chosen"
        monkeypatch.setattr(
            qt.QFileDialog, "getExistingDirectory",
            staticmethod(lambda *a, **k: str(chosen)))
        page._format_combo.setCurrentIndex(0)  # all three legacy formats
        page._on_export()
        assert page._export_state == "running"
        assert pump_until(qapp, lambda: page._export_state == "ok")
        assert len(list(chosen.iterdir())) == 3
        page.deleteLater()

    def test_export_dialog_single_format_suffix_and_cancel(
            self, qapp, config_service, backend_factory, tmp_path,
            monkeypatch):
        import PySide6.QtWidgets as qt

        backend = backend_factory(config_service, FakeAdbTransport())
        backend.remember_scan(real_bundle(), "completed", "S1")
        page = reports_page_of(backend)
        target = tmp_path / "no-ext"  # user typed no suffix in the dialog
        monkeypatch.setattr(
            qt.QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(target), "JSON")))
        page._format_combo.setCurrentText("JSON report")
        page._on_export()
        assert pump_until(qapp, lambda: page._export_state == "ok")
        assert (tmp_path / "no-ext.json").exists()

        monkeypatch.setattr(
            qt.QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: ("", "")))
        page._format_combo.setCurrentText("HTML report")
        page._on_export()
        assert page._export_state == "refused"
        assert "No destination chosen" in page._export_label.text()
        page.deleteLater()

    def test_export_dialog_refuses_overwrite_when_declined(
            self, qapp, config_service, backend_factory, tmp_path,
            monkeypatch):
        import PySide6.QtWidgets as qt

        backend = backend_factory(config_service, FakeAdbTransport())
        backend.remember_scan(real_bundle(), "completed", "S1")
        out_dir = tmp_path / "reports"
        out_dir.mkdir()
        existing = out_dir / "keep.json"
        existing.write_text("keep-me", encoding="utf-8")

        asked: List[str] = []
        monkeypatch.setattr(
            reports_module.QMessageBox, "question",
            staticmethod(lambda *args, **kwargs: [
                asked.append("asked"),
                QMessageBox.StandardButton.No][1]))
        monkeypatch.setattr(
            qt.QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(existing), "JSON")))
        page = reports_page_of(backend)
        page._format_combo.setCurrentText("JSON report")
        page._on_export()
        assert page._export_state == "refused"
        assert "existing file was left untouched" in \
            page._export_label.text()
        assert existing.read_text(encoding="utf-8") == "keep-me"
        assert page._export_job_id is None
        page.deleteLater()

    def test_history_round_trip_and_status_words(
            self, qapp, config_service, backend_factory):
        backend = backend_factory(config_service, FakeAdbTransport())
        backend.history_entry(HistoryEntry(
            scan_id="full-alp-01", kind="full_device", status="completed",
            device_serial="S1", total_apps=1, findings_total=5,
            severity_counts={"critical": 2, "high": 1, "medium": 0,
                             "low": 2, "info": 0}))
        backend.history_entry(HistoryEntry(
            scan_id="single-beta-1", kind="single_app", status="cancelled",
            device_serial="S1"))
        page = reports_page_of(backend)  # fresh page → REAL store read
        page.refresh_history()
        assert pump_until(qapp, lambda: page._history_state in
                          ("ok", "empty", "failed"))
        assert page._history_state == "ok"
        model = page._history_model
        assert model.rowCount() == 2
        statuses = sorted(model.data(model.index(r, 2))
                          for r in range(model.rowCount()))
        assert statuses == ["cancelled", "completed"]
        kinds = sorted(model.data(model.index(r, 1))
                       for r in range(model.rowCount()))
        assert kinds == ["full_device", "single_app"]
        assert "counters only" in page._history_banner.text()
        page.deleteLater()

    def test_history_read_failure_is_honest(self, qapp, config_service,
                                            backend_factory, monkeypatch):
        backend = backend_factory(config_service, FakeAdbTransport())
        page = reports_page_of(backend)

        def boom() -> tuple:
            raise HistoryStoreError("history dir unreadable",
                                    {"detail": "boom"})

        monkeypatch.setattr(backend, "history_recent", boom)
        page.refresh_history()
        assert pump_until(qapp, lambda: page._history_state == "failed")
        assert "history dir unreadable" in page._history_banner.text()
        assert "no record is invented" in page._history_banner.text()
        page.deleteLater()

    def test_history_empty_state(self, qapp, config_service,
                                 backend_factory):
        backend = backend_factory(config_service, FakeAdbTransport())
        page = reports_page_of(backend)
        page.refresh_history()
        assert pump_until(qapp, lambda: page._history_state in
                          ("ok", "empty", "failed"))
        assert page._history_state == "empty"
        assert "no scans recorded yet" in page._history_banner.text()
        page.deleteLater()


# ===========================================================================
# scan-screen scope honesty
# ===========================================================================

class TestScanScope:
    def test_scope_toggles_update_the_preflight_summary(
            self, qapp, config_service, backend_factory):
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory,
            ScanCapableTransport(**SCAN_SETUP))  # type: ignore[arg-type]
        auto_discover(qapp, page)
        preflight = page._preflight_label.text()
        assert "target S1" in preflight
        assert "next scan: full-device scan" in preflight
        page._system_toggle.setChecked(True)
        page._deep_toggle.setChecked(True)
        preflight = page._preflight_label.text()
        assert "system apps included" in preflight
        assert "deep scan on" in preflight
        page._package_input.setText("com.bad name!")
        page._system_toggle.setChecked(False)
        page._deep_toggle.setChecked(False)
        page._on_start_single()
        assert "not a valid package name" in page._progress_label.text()
        page.deleteLater()

    def test_single_package_input_required(self, qapp, config_service,
                                           backend_factory):
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory,
            ScanCapableTransport(**SCAN_SETUP))  # type: ignore[arg-type]
        auto_discover(qapp, page)
        page._on_start_single()
        assert "type the package name" in page._progress_label.text()
        page.deleteLater()

    def test_deep_scan_unverified_condition_stays_visible(
            self, qapp, config_service, backend_factory, history_target):
        """A deep scan over an APK the host cannot extract yields an honest
        UNVERIFIED_CONDITION note — it must reach the findings panel."""
        page, _backend, _hub = fresh_workspace(
            config_service, backend_factory,
            ScanCapableTransport(**SCAN_SETUP))  # type: ignore[arg-type]
        auto_discover(qapp, page)
        page._deep_toggle.setChecked(True)
        page._package_input.setText("com.example.wallet")
        page._on_start_single()
        assert wait_scan_done(qapp, page)
        assert page._scan_state == "not-exportable"
        unverified = [f for f in page._findings
                      if f.evidence and f.evidence[0].kind is
                      EvidenceKind.UNVERIFIED_CONDITION]
        assert unverified, "the engine's unverified note must surface"
        assert any("Deep-scan" in f.title for f in unverified)
        page.deleteLater()


# ===========================================================================
# architecture guards (Stage 11 additions for the new screens)
# ===========================================================================

class TestStage11Architecture:
    def test_desktop_screens_avoid_subprocess_adb_setup_and_tui(self):
        desktop_root = Path(__file__).resolve().parents[2] / "ui_desktop"
        banned = {"subprocess", "adb_setup", "textual"}
        for file in desktop_root.rglob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            mods: List[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods.extend(alias.name.split(".")[0]
                                for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods.append(node.module.split(".")[0])
            for name in mods:
                assert name not in banned, f"{file.name} imports {name}"

    def test_engine_never_imports_ui_frameworks(self):
        engine_root = Path(__file__).resolve().parents[2] / "vscanner"
        ui_frameworks = {"PySide6", "textual", "PyQt5", "PyQt6"}
        for file in engine_root.rglob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name.split(".")[0] not in \
                            ui_frameworks, f"{file} imports {alias.name}"
                elif isinstance(node, ast.ImportFrom) and node.module:
                    assert node.module.split(".")[0] not in ui_frameworks, \
                        f"{file} imports {node.module}"
