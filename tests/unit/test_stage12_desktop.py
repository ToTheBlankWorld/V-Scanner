"""Stage 12 desktop parity tests — monitoring/forensics/mirroring/demo/admin.

Same discipline as the Stage 09/10/11 harnesses:

* Qt runs offscreen; NOTHING touches hardware, a real subprocess, or the
  network. The shared engine services run over a scripted fake transport,
  so these tests drive the REAL ``MonitoringService`` / ``ForensicsService``
  / ``AdministrationService`` / ``DemoService`` (the exact Stage 08
  services), the REAL ``DesktopBackend`` + Stage 04 ``JobManager`` and the
  REAL ``QtJobEventBridge``. ``ScreenMirrorService`` is faked at the
  registry seam (spawning real scrcpy is a hardware test — explicitly out
  of scope), preserving the exact launch/list/stop contract.
* Widgets are pumped with ``processEvents`` — never blocking waits.
* GUI-thread delivery is asserted by capturing ``threading.get_ident()``
  in a hub-connected slot.
* Late events, stale targets, superseded sessions, cancel semantics and
  the exact token-mint/gate split are asserted on the pages' honest state
  words; the service-side gate itself is re-proven at this seam (stale /
  missing tokens never reach the device).
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QDialog

from test_stage10_desktop import (  # noqa: E402
    FakeAdbTransport,
    FakeRegistry,
    GUI_THREAD,
    pump_until,
    texts_of,
)

import ui_desktop.backend as backend_module  # noqa: E402
from ui_desktop.backend import DesktopBackend  # noqa: E402
import ui_desktop.sections as sections_module  # noqa: E402
from ui_desktop.jobs_bridge_qt import QtJobEventBridge  # noqa: E402
from ui_desktop.main_window import MainWindow  # noqa: E402
from ui_desktop.screens.demo import DemoPage  # noqa: E402
from ui_desktop.screens.devices import AdminConfirmDialog, DeviceWorkspacePage  # noqa: E402,E501
import ui_desktop.screens.devices as devices_module  # noqa: E402
from ui_desktop.screens.forensics import ACK_PHRASE  # noqa: E402
from ui_desktop.screens.forensics import (  # noqa: E402
    CleartextConfirmDialog,
    ForensicsPage,
)
import ui_desktop.screens.forensics as forensics_module  # noqa: E402
from ui_desktop.screens.mirroring import LAUNCH_OPTIONS  # noqa: E402
from ui_desktop.screens.mirroring import MirroringPage  # noqa: E402
from ui_desktop.screens.monitoring import MonitoringPage  # noqa: E402
from vscanner.core.errors import InputValidationError, ToolNotValidated  # noqa: E402,E501
from vscanner.core.events import (  # noqa: E402
    JobKind,
    JobSnapshotStreamEvent,
    JobState,
    JobTerminalEvent,
    OperationConfirmation,
)
from vscanner.core.models import (  # noqa: E402
    HardwareUsageSnapshot,
    MirrorHandle,
    MirrorOptions,
    ObservationState,
    SensorStatus,
    ToolId,
    ToolState,
    ToolStatusReflected,
)
from vscanner.services.adb.client import AdbCommandError, AdbResult  # noqa: E402
from vscanner.services.config import ConfigService  # noqa: E402
from vscanner.services.demo import DemoService  # noqa: E402
from vscanner.services.monitoring import MonitoringService  # noqa: E402

CONFIRMATION_TTL_SECONDS = 120.0  # documented ADMIN confirmation TTL (SC-5)


# ===========================================================================
# helpers: deterministic pumping
# ===========================================================================

def joined_texts(widget) -> str:
    return " ".join(texts_of(widget))


# ===========================================================================
# fake transport — the Stage-08 command surface over the Stage-10 base fake
# ===========================================================================

SENSOR_TEXT = (
    "Accelerometer: 0.001 -2.31 9.81\n"
    "Proximity Sensor detected and available\n"
)

USAGE_IDLE: dict[str, str] = {
    "media.camera": "Camera 0: no open devices",
    "audio": "Recording sessions: 0",
    "location": "Active listeners: 0",
}

WIFI_CONF = (
    'network={\n  ssid="home"\n  psk="secret-pass-1"\n}\n'
    'network={\n  ssid="work"\n  key_mgmt=WPA-EAP\n}\n'
)

DEFAULT_LOGCAT = (
    "01-01 00:00:00 log line 1\n01-01 00:00:01 log line 2\n"
)


class Stage12Transport(FakeAdbTransport):
    """Stage-10 fake extended with the Stage-08 command surface:

    * ``shell dumpsys <name>`` — sensorservice / media.camera / audio /
      location probes (monitoring; a missing script RAISES → the engine
      records UNKNOWN / a failure, honesty preserved)
    * ``shell logcat -d`` / ``shell ps -A`` — forensics text ops
    * ``shell su -c ls -1 '...'`` / ``su -c cat wpa_supplicant.conf`` —
      forensics listing / wifi (the bare ``su -c id`` root probe falls
      through to the base transport's root-mode script)
    * ``uninstall`` / ``shell am force-stop|start`` /
      ``shell cmd package query-activities`` — admin parity commands
    * ``exec-out su -c cat '<path>'`` (``run_bytes``) — forensics byte copy
    """

    def __init__(
        self,
        *,
        sensor_text: str = SENSOR_TEXT,
        usage: Optional[dict[str, str]] = None,
        dumpsys_raise: tuple[str, ...] = (),
        logcat_text: str = DEFAULT_LOGCAT,
        ps_text: str = "root 1 1234 com.demo.app\n",
        wifi_conf: str = WIFI_CONF,
        wifi_rc: int = 0,
        su_listing: Optional[dict[str, tuple[str, int]]] = None,
        cat_bytes: Optional[dict[str, bytes]] = None,
        uninstall_result: tuple[str, int] = ("Success", 0),
        force_stop_rc: int = 0,
        launch_activity: str = ".MainActivity",
        am_start_rc: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.sensor_text = sensor_text
        self.usage = dict(USAGE_IDLE if usage is None else usage)
        self.dumpsys_raise = dumpsys_raise
        self.logcat_text = logcat_text
        self.ps_text = ps_text
        self.wifi_conf = wifi_conf
        self.wifi_rc = wifi_rc
        self.su_listing = dict(su_listing or {})
        self.cat_bytes = dict(cat_bytes or {})
        self.uninstall_result = uninstall_result
        self.force_stop_rc = force_stop_rc
        self.launch_activity = launch_activity
        self.am_start_rc = am_start_rc

    def run_text(self, cmd, timeout: float = 30.0) -> AdbResult:
        argv = tuple(str(part) for part in cmd)
        if argv[:1] == ("shell",):
            payload = argv[1:]
            if payload[:1] == ("dumpsys",):
                self.calls.append((self.serial, argv))
                name = payload[1] if len(payload) > 1 else ""
                if name in self.dumpsys_raise:
                    raise AdbCommandError(
                        "fake probe failure", cmd=argv, timeout=False)
                if name == "sensorservice":
                    return AdbResult(
                        stdout=self.sensor_text, stderr="", returncode=0)
                text = self.usage.get(name)
                if text is None:
                    raise AdbCommandError(
                        "fake probe failure", cmd=argv, timeout=False)
                return AdbResult(stdout=text, stderr="", returncode=0)
            if payload[:1] == ("logcat",):
                self.calls.append((self.serial, argv))
                return AdbResult(
                    stdout=self.logcat_text, stderr="", returncode=0)
            if payload[:1] == ("ps",):
                self.calls.append((self.serial, argv))
                return AdbResult(stdout=self.ps_text, stderr="", returncode=0)
            if payload[:2] == ("am", "force-stop"):
                self.calls.append((self.serial, argv))
                return AdbResult(stdout="", stderr="",
                                 returncode=self.force_stop_rc)
            if payload[:2] == ("am", "start"):
                self.calls.append((self.serial, argv))
                return AdbResult(
                    stdout="Starting: Intent { cmp=com.demo.app }",
                    stderr="", returncode=self.am_start_rc)
            if payload[:1] == ("cmd",):
                self.calls.append((self.serial, argv))
                return AdbResult(
                    stdout=f"  com.demo.app/{self.launch_activity}",
                    stderr="", returncode=0)
            if payload[:2] == ("su", "-c") and len(payload) >= 3 \
                    and payload[2] != "id":
                self.calls.append((self.serial, argv))
                inner = payload[2]
                if inner.startswith("ls -1 "):
                    target = inner.split("ls -1 ", 1)[1].strip().strip("'")
                    out, rc = self.su_listing.get(target, ("", 1))
                    return AdbResult(stdout=out, stderr="", returncode=rc)
                if "wpa_supplicant" in inner:
                    return AdbResult(
                        stdout=self.wifi_conf, stderr="",
                        returncode=self.wifi_rc)
                raise AdbCommandError(
                    "fake transport: unknown su command",
                    cmd=argv, timeout=False)
        if argv[:1] == ("uninstall",):
            self.calls.append((self.serial, argv))
            out, rc = self.uninstall_result
            return AdbResult(stdout=out, stderr="", returncode=rc)
        # devices / getprop / uname / pm list packages / su -c id probe /
        # command -v — the Stage-10 base script handles (and records) them.
        return FakeAdbTransport.run_text(self, cmd, timeout=timeout)

    def run_bytes(self, cmd, timeout: float = 60.0) -> bytes:
        argv = tuple(str(part) for part in cmd)
        self.calls.append((self.serial, argv))
        if argv[:1] == ("exec-out",):
            inner = argv[-1]
            if inner.startswith("cat '") and inner.endswith("'"):
                path = inner[5:-1]
                data = self.cat_bytes.get(path)
                if data is not None:
                    return bytes(data)
            raise AdbCommandError(
                "fake transport: copy failed", cmd=argv, timeout=False)
        raise AdbCommandError(
            "fake transport: unknown exec-out", cmd=argv, timeout=False)


# ===========================================================================
# fake registry — the backend's exact face surface (mirroring faked)
# ===========================================================================

class FakeProvisioning:
    """Configurable honest tool-status face (ToolProvisioningService)."""

    def __init__(self, status: ToolStatusReflected) -> None:
        self._status = status

    def tool_status(self, tool: ToolId) -> ToolStatusReflected:
        return self._status

    def tool_path(self, tool: ToolId) -> Optional[Path]:
        if self._status.state is ToolState.VALIDATED:
            return Path(self._status.path) if self._status.path else None
        return None


class FakeMirrorService:
    """``ScreenMirrorService`` contract without spawning any process.

    Per-serial instance semantics match the real service: the handle
    registry lives on the INSTANCE (backend caches one per serial)."""

    def __init__(self, serial: Optional[str]) -> None:
        self.serial = serial
        self.launch_calls: list[Optional[MirrorOptions]] = []
        self.launch_error: Optional[BaseException] = None
        self.list_calls = 0
        self.stop_calls: list[Optional[int]] = []
        self._handles: dict[int, MirrorHandle] = {}
        self._exit_codes: dict[int, int] = {}
        self._next_pid = 4321

    def launch(self, options: Optional[MirrorOptions] = None) -> MirrorHandle:
        self.launch_calls.append(options)
        if self.launch_error is not None:
            raise self.launch_error
        self._next_pid += 1
        pid = self._next_pid
        handle = MirrorHandle(
            pid=pid, serial=self.serial,
            launched_at="2026-01-01T00:00:00+00:00",
            command=("C:/fake/scrcpy.exe", "-s", self.serial or "",
                     "-m", "1024", "--max-fps", "30"),
            exit_code=None,
        )
        self._handles[pid] = handle
        return handle

    def list_running(self) -> tuple[MirrorHandle, ...]:
        self.list_calls += 1
        return tuple(
            handle if pid not in self._exit_codes
            else replace(handle, exit_code=self._exit_codes[pid])
            for pid, handle in list(self._handles.items()))

    def stop(self, pid: Optional[int] = None) -> tuple[int, ...]:
        self.stop_calls.append(pid)
        if pid is not None:
            running = [pid] if self._exit_codes.get(pid) is None else []
        else:
            running = [p for p in self._handles
                       if self._exit_codes.get(p) is None]
        for target in running:
            self._handles.pop(target, None)
        return tuple(running)

    def mark_exited(self, pid: int, code: int) -> None:
        self._exit_codes[pid] = code


class FakeRegistry12(FakeRegistry):
    """The stage-10 fake registry plus the exact Stage-12 faces the
    backend calls, backed by the REAL Stage-08 services over the fake
    transport (``ScreenMirrorService`` faked at the seam)."""

    def __init__(self, transport: FakeAdbTransport,
                 case_root: Optional[Path] = None) -> None:
        super().__init__(transport)
        self.case_root = case_root
        self._mirrors: dict[str, FakeMirrorService] = {}
        self.tool_status = ToolStatusReflected(
            tool=ToolId.SCRCPY, state=ToolState.VALIDATED,
            path="C:/fake/scrcpy.exe")
        self.provision_error: Optional[BaseException] = None
        self.demo_builds = 0
        self.forensics_builds = 0
        self.monitor_builds = 0
        self.admin_builds = 0

    def monitor(self, serial: Optional[str] = None) -> MonitoringService:
        self.monitor_builds += 1
        return MonitoringService(self._transport)

    def admin(self, serial: Optional[str] = None) -> Any:
        from vscanner.services.admin import AdministrationService

        self.admin_builds += 1
        return AdministrationService(self._transport)

    def forensics(self, serial: Optional[str] = None, case_root=None) -> Any:
        from vscanner.services.forensics import ForensicsService

        self.forensics_builds += 1
        # every Stage-12 construction hands in a Stage12Transport (which
        # implements the byte surface the forensics protocol requires);
        # the base attribute annotation stays the stage-10 type
        transport = cast(Any, self._transport)
        return ForensicsService(
            transport,
            base_dir=case_root if case_root is not None else self.case_root,
        )

    def provisioning(self) -> FakeProvisioning:
        if self.provision_error is not None:
            raise self.provision_error
        return FakeProvisioning(self.tool_status)

    def mirror(self, serial: Optional[str] = None) -> FakeMirrorService:
        key = serial or ""
        service = self._mirrors.get(key)
        if service is None:
            service = FakeMirrorService(serial)
            self._mirrors[key] = service
        return service

    def demo(self) -> DemoService:
        self.demo_builds += 1
        return DemoService()


class BackendFactory12:
    """Real ``DesktopBackend``s whose ``ServiceRegistry`` resolves to the
    Stage-12 fake registry (forensics case store relocated per test)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self.registries: list[FakeRegistry12] = []
        self._created: list[DesktopBackend] = []

    def build(self, config_service: ConfigService,
              transport: Stage12Transport,
              case_root: Optional[Path] = None) -> DesktopBackend:
        registry = FakeRegistry12(transport, case_root)
        self.registries.append(registry)
        self._monkeypatch.setattr(
            backend_module, "ServiceRegistry", lambda _path: registry,
            raising=True)
        backend = DesktopBackend(config_service)
        self._created.append(backend)
        return backend

    def __call__(self, config_service: ConfigService,
                 transport: Stage12Transport,
                 case_root: Optional[Path] = None) -> DesktopBackend:
        return self.build(config_service, transport, case_root)

    def teardown(self) -> None:
        for backend in self._created:
            backend.shutdown_jobs()
        self._created.clear()

    def last_registry(self) -> FakeRegistry12:
        assert self.registries, "no registry built yet"
        return self.registries[-1]


# ===========================================================================
# fixtures — (page, backend, bridge) wired like production
# ===========================================================================

@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    app = cast(Optional[QApplication], QApplication.instance())
    if app is None:
        from ui_desktop.app import create_application

        app = create_application([])
    assert app is not None
    yield app
    # Same deterministic-teardown contract as Stage 09/10/11: flush queued
    # deliveries, drop top-level widgets, and leave a clean interpreter.
    app.processEvents()
    for widget in list(app.topLevelWidgets()):
        widget.deleteLater()
    app.processEvents()


@pytest.fixture()
def config_service(tmp_path: Path) -> ConfigService:
    service = ConfigService(tmp_path / "config.json")
    service.save(r"C:\tools\fake-adb.exe")
    return service


@pytest.fixture(autouse=True)
def history_target(tmp_path: Path,
                   monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stage-12 flows must never write real scan history ANYWHERE."""
    directory = tmp_path / "history"
    monkeypatch.setattr(backend_module, "history_dir",
                        (lambda: directory), raising=True)
    return directory


@pytest.fixture()
def backend_factory(
        qapp, monkeypatch: pytest.MonkeyPatch) -> Iterator[BackendFactory12]:
    factory = BackendFactory12(monkeypatch)
    yield factory
    _close_tracked_pages()
    factory.teardown()


def _bridge(backend: DesktopBackend) -> QtJobEventBridge:
    bridge = QtJobEventBridge()
    bridge.attach(backend.manager())
    return bridge


# Pages created by the fresh_* helpers, closed deterministically in the
# backend_factory teardown (Stage-11 learning: a page left with a running
# CallWorker thread aborts the process on Windows once it is collected —
# explicit owner-close for every page keeps QThread lifetimes exact).
_OPEN_PAGES: List[Any] = []


def _track_page(page: Any) -> Any:
    _OPEN_PAGES.append(page)
    return page


def _close_tracked_pages() -> None:
    for page in _OPEN_PAGES:
        try:
            if hasattr(page, "shutdown"):
                page.shutdown()
        except RuntimeError:
            pass  # Qt object already gone
    _OPEN_PAGES.clear()


def auto_discover(qapp, page) -> None:
    """First activation runs exactly one auto-discovery; wait for it."""
    page.activate()
    assert pump_until(qapp, lambda: page._refresh_button.isEnabled())
    assert pump_until(qapp, lambda: page._devices_state == "refreshed")


def select_row(qapp, page, serial: str) -> None:
    row = page._devices_model.row_of_serial(serial)
    assert row is not None, f"serial {serial} not listed"
    page._devices_table.selectionModel().setCurrentIndex(
        page._devices_model.index(row, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect
        | QItemSelectionModel.SelectionFlag.Current)
    assert pump_until(qapp, lambda: page.selected_serial == serial)


def fresh_monitoring(qapp, config_service, backend_factory,
                     transport: Stage12Transport):
    backend = backend_factory(config_service, transport)
    bridge = _bridge(backend)
    page = _track_page(MonitoringPage(backend, bridge.hub))
    return page, backend, bridge


def fresh_forensics(qapp, config_service, backend_factory,
                    transport: Stage12Transport, case_root: Path):
    backend = backend_factory(config_service, transport, case_root=case_root)
    bridge = _bridge(backend)
    page = _track_page(ForensicsPage(backend, bridge.hub))
    return page, backend, bridge


def fresh_mirroring(qapp, config_service, backend_factory,
                    transport: Stage12Transport):
    backend = backend_factory(config_service, transport)
    bridge = _bridge(backend)
    page = _track_page(MirroringPage(backend, bridge.hub))
    return page, backend, bridge


def fresh_workspace(qapp, config_service, backend_factory,
                    transport: Stage12Transport):
    backend = backend_factory(config_service, transport)
    bridge = _bridge(backend)
    page = _track_page(DeviceWorkspacePage(backend, bridge.hub))
    return page, backend, bridge


def snapshot_of(serial: str = "S1",
                camera: ObservationState = ObservationState.OBSERVED_ACTIVE,
                *, failures: tuple = (), evidence: Any = None,
                captured: Any = None) -> HardwareUsageSnapshot:
    if evidence is None:
        evidence = (()
                    if camera is not ObservationState.OBSERVED_ACTIVE else
                    (("camera", "Device 1 is open, client com.cam("),))
    return HardwareUsageSnapshot(
        serial=serial,
        camera=camera,
        microphone=ObservationState.NOT_OBSERVED,
        location=ObservationState.NOT_OBSERVED,
        evidence=evidence,
        failures=failures,
        captured_at=captured,
    )


def fresh_confirmation(reference: str = "op",
                       age_s: float = 0.0) -> OperationConfirmation:
    return OperationConfirmation(
        reference=reference,
        confirmed_at=datetime.now(timezone.utc) - timedelta(seconds=age_s),
    )


def uninstall_calls(transport: Stage12Transport) -> list[tuple]:
    return [argv for _s, argv in transport.calls
            if argv[:1] == ("uninstall",)]


# ===========================================================================
# navigation registry parity
# ===========================================================================

class TestSectionRegistryParity:
    def test_stage12_sections_are_live(self) -> None:
        for section_id in ("monitoring", "forensics", "mirroring", "demo"):
            section = sections_module.get_section(section_id)
            assert section.kind == "live", section_id
            assert section.owner_stage == "", section_id
            assert section.description.strip(), section_id

    def test_no_future_rows_remain(self) -> None:
        assert sections_module.future_sections() == ()
        live_ids = [s.section_id for s in sections_module.live_sections()]
        assert {"monitoring", "forensics", "mirroring", "demo"} \
            <= set(live_ids)

    def test_monitoring_wording_says_host_side_not_continuous(self) -> None:
        description = sections_module.get_section("monitoring").description
        assert "HOST-SIDE" in description.upper()
        assert "NOT continuous" in description
        assert "not in use" not in description.lower()

    def test_demo_wording_promises_isolation(self) -> None:
        description = sections_module.get_section("demo").description
        assert "no device is contacted" in description.lower()
        assert "no real scan data is touched" in description.lower()

    def test_mirroring_wording_states_the_refusal_honestly(self) -> None:
        description = sections_module.get_section("mirroring").description
        assert "validated" in description.lower()
        assert "not verified" in description.lower()
        assert "refused" in description.lower()


# ===========================================================================
# backend seam: monitoring (real engine services over the fake transport)
# ===========================================================================

class TestBackendMonitoringSeam:
    def test_start_monitoring_session_submits_typed_job(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        handle = backend.start_monitoring_session("S1", interval_s=2.0)
        assert handle.kind is JobKind.MONITORING_SESSION
        assert handle.device_serial == "S1"
        assert handle.state.value in ("running", "queued")
        handle.cancel()
        assert handle.wait(30).value == "cancelled"

    def test_read_sensors_once_runs_real_service_rows(
            self, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        rows = backend.read_sensors_once("S1")
        assert any(r.name == "Accelerometer" and r.status is
                   SensorStatus.AVAILABLE for r in rows)
        assert any(r.name == "Proximity Sensor" for r in rows)

    def test_read_sensors_unavailable_is_one_honest_row(
            self, config_service, backend_factory):
        transport = Stage12Transport(
            devices_lines=("S1 device",),
            sensor_text="SensorService 1.0 bogus line\n",
        )
        backend = backend_factory(config_service, transport)
        rows = backend.read_sensors_once("S1")
        assert len(rows) == 1
        assert rows[0].status is SensorStatus.UNAVAILABLE
        assert rows[0].reason

    def test_stop_monitoring_is_targeted(
            self, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        handle = backend.start_monitoring_session("S1", interval_s=2.0)
        assert backend.active_monitoring_handle("S1").id == handle.id
        assert backend.active_monitoring_handle("S2") is None
        backend.stop_monitoring("S1")
        assert handle.wait(30).value == "cancelled"

    def test_monitoring_stop_does_not_cancel_listings(
            self, config_service, backend_factory):
        transport = Stage12Transport(
            devices_lines=("S1 device",), third_party=("com.demo.app",),
            list_gate=threading.Event(),
        )
        backend = backend_factory(config_service, transport)
        listing = backend.start_listing_job("S1", include_system=False)
        assert transport.list_started.wait(10.0)
        monitor = backend.start_monitoring_session("S1", interval_s=2.0)
        backend.stop_monitoring("S1")
        assert monitor.wait(30).value == "cancelled"
        # the targeted stop must NOT have cancelled the listing job
        assert listing.state.value in ("running", "queued")
        transport.list_gate.set()
        assert listing.wait(30).value == "succeeded"


# ===========================================================================
# monitoring page: real pipeline + honest guards
# ===========================================================================

class TestMonitoringPage:
    def test_activation_runs_exactly_one_auto_refresh(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_monitoring(
            qapp, config_service, backend_factory, transport)
        page.activate()
        page.activate()
        assert pump_until(qapp, lambda: page._devices_state == "refreshed")
        device_probes = [1 for _s, argv in transport.calls
                         if argv[:1] == ("devices",)]
        assert len(device_probes) == 1

    def test_poll_session_streams_snapshots_on_gui_thread(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, backend, bridge = fresh_monitoring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        idents: List[int] = []
        bridge.hub.snapshot.connect(
            lambda event: idents.append(threading.get_ident()))
        page._poll_button.click()
        assert pump_until(qapp, lambda: page._poll_count >= 1, timeout_s=15)
        assert page._poll_state == "running"
        assert idents and set(idents) == {GUI_THREAD}, \
            "every snapshot delivery must land ONLY on the GUI thread"
        assert len(idents) == page._poll_count, \
            "bridge fan-out: one GUI-thread delivery per counted snapshot"
        rows = page._usage_model.rows
        assert rows, "usage rows must render from the typed snapshot"
        joined = " | ".join(" ".join(row) for row in rows)
        assert "not observed in this poll" in joined
        assert "not in use" not in joined
        page._poll_button.click()
        assert page._poll_state == "stopping"
        assert pump_until(qapp, lambda: page._poll_state == "stopped",
                          timeout_s=15)
        assert "stop" in (page._poll_banner.text() or "").lower()

    def test_foreign_superseded_or_mislabeled_snapshots_never_clobber(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_monitoring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        page._poll_job_id = "j-1"
        page._poll_job_serial = "S1"
        page._poll_state = "running"
        page._on_snapshot_event(JobSnapshotStreamEvent(
            payload=snapshot_of(serial="S1"), job_id="j-1",
            kind=JobKind.MONITORING_SESSION))
        assert page._poll_count == 1
        # a late snapshot from a SUPERSEDED session id is ignored
        page._on_snapshot_event(JobSnapshotStreamEvent(
            payload=snapshot_of(), job_id="j-0",
            kind=JobKind.MONITORING_SESSION))
        assert page._poll_count == 1
        # a snapshot bound to another device must pass neither lane
        page._poll_job_id = "j-2"
        page._on_snapshot_event(JobSnapshotStreamEvent(
            payload=snapshot_of(serial="OTHER"), job_id="j-2",
            kind=JobKind.MONITORING_SESSION))
        assert page._poll_count == 1
        assert page._last_snapshot.serial == "S1"
        # non-typed payloads are never rendered (honest pass-through)
        page._on_snapshot_event(JobSnapshotStreamEvent(
            payload={"camera": "free text is not a snapshot"},
            job_id="j-2", kind=JobKind.MONITORING_SESSION))
        assert page._poll_count == 1
        assert page._usage_model.rows != ()

    def test_unknown_probe_renders_the_honest_failure_row(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_monitoring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        page._poll_job_id = "j-3"
        page._poll_job_serial = "S1"
        page._poll_state = "running"
        page._on_snapshot_event(JobSnapshotStreamEvent(
            payload=snapshot_of(
                serial="S1", camera=ObservationState.UNKNOWN,
                failures=("camera: probe failed or output unparseable",)),
            job_id="j-3", kind=JobKind.MONITORING_SESSION))
        joined = " | ".join(" ".join(row) for row in page._usage_model.rows)
        assert "unknown (probe failed)" in joined
        assert "probe failed" in joined

    def test_change_target_stops_the_superseded_session(
            self, qapp, config_service, backend_factory, monkeypatch):
        transport = Stage12Transport(
            devices_lines=("S1 device", "S2 device"))
        page, backend, _bridge = fresh_monitoring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        stop_calls: List[str] = []
        monkeypatch.setattr(
            backend, "stop_monitoring",
            lambda serial: stop_calls.append(serial), raising=True)
        select_row(qapp, page, "S1")
        page._poll_job_id = "j-1"
        page._poll_job_serial = "S1"
        page._poll_state = "running"
        page._poll_count = 2
        page._last_snapshot = snapshot_of(serial="S1")
        # the user picks S2 while the S1 session streams: the page stops
        # the S1 session targeted and clears its snapshot display
        select_row(qapp, page, "S2")
        assert stop_calls == ["S1"]
        assert page._last_snapshot is None
        assert page._usage_model.rows == ()
        # a late S1 snapshot arrives after the stop request — never shown
        page._on_snapshot_event(JobSnapshotStreamEvent(
            payload=snapshot_of(serial="S1"), job_id="j-1",
            kind=JobKind.MONITORING_SESSION))
        assert page._poll_count == 2
        assert page._usage_model.rows == ()
        # the terminal for the old session may still arrive — honest note
        page._on_terminal_event(JobTerminalEvent(
            job_id="j-1", kind=JobKind.MONITORING_SESSION,
            outcome=JobState.CANCELLED))
        assert page._poll_state == "stopped"
        assert "2 poll(s)" in (page._poll_banner.text() or "")

    def test_terminal_states_surface_verbatim(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_monitoring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        page._poll_job_id = "j-9"
        page._poll_job_serial = "S1"
        page._poll_state = "running"
        page._poll_count = 4
        # engine abort (SUCCEEDED terminal carrying the abort dict)
        page._on_terminal_event(JobTerminalEvent(
            job_id="j-9", kind=JobKind.MONITORING_SESSION,
            outcome=JobState.SUCCEEDED,
            result={"status": "aborted",
                    "reason": "3 consecutive failed polls",
                    "polls_completed": 2}))
        assert page._poll_state == "aborted"
        assert "3 consecutive failed polls" in \
            (page._poll_banner.text() or "")
        assert page._poll_job_id is None
        # failed terminal
        page._poll_job_id = "j-10"
        page._poll_state = "running"
        page._on_terminal_event(JobTerminalEvent(
            job_id="j-10", kind=JobKind.MONITORING_SESSION,
            outcome=JobState.FAILED))
        assert page._poll_state == "failed"
        assert page._poll_job_id is None
        # terminal for a foreign/superseded job is NEVER routed here
        page._poll_state = "stopped"
        page._on_terminal_event(JobTerminalEvent(
            job_id="j-10", kind=JobKind.MONITORING_SESSION,
            outcome=JobState.CANCELLED))
        assert page._poll_state == "stopped"

    def test_sensor_read_show_and_superseded_drops(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_monitoring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        page._sensors_button.click()
        assert pump_until(qapp, lambda: page._sensor_state == "ok")
        row_texts = " | ".join(" ".join(r) for r in page._sensors_model.rows)
        assert "Accelerometer" in row_texts
        assert "available" in row_texts
        # a superseded read for another serial is dropped, never merged
        page._selected_serial = "S-ghost"
        page._sensor_state = "reading"
        page._on_sensors_done("S1", ())
        assert page._sensor_state == "reading"

    def test_failed_sensor_read_is_flagged_not_data(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_monitoring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        page._sensors_button.click()
        assert pump_until(qapp, lambda: page._sensor_state == "ok")
        # simulate a later failed read on the SAME target
        page._sensor_state = "reading"
        page._on_sensors_failed("S1", RuntimeError("transport gone"))
        assert page._sensor_state == "failed"
        assert "failed" in (page._sensors_banner.text() or "").lower()


# ===========================================================================
# backend seam: administration (the service gate is the ONLY authority)
# ===========================================================================

class TestBackendAdminSeam:
    def test_unsupported_op_is_refused_before_any_service_work(
            self, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        confirmation = fresh_confirmation("admin:reboot:com.demo.app")
        with pytest.raises(InputValidationError):
            backend.start_admin_job(
                "S1", "reboot_device", "com.demo.app", confirmation)
        assert uninstall_calls(transport) == []

    def test_uninstall_reaches_service_with_fresh_confirmation(
            self, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        confirmation = fresh_confirmation("admin:uninstall_app:com.demo.app")
        handle = backend.start_admin_job(
            "S1", "uninstall_app", "com.demo.app", confirmation)
        assert handle.kind is JobKind.ADMIN_OP
        assert handle.device_serial == "S1"
        assert handle.wait(30).value == "succeeded"
        assert uninstall_calls(transport) == [("uninstall", "com.demo.app")]

    def test_missing_confirmation_is_refused_by_the_service_gate(
            self, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        handle = backend.start_admin_job(
            "S1", "uninstall_app", "com.demo.app", None)
        assert handle.wait(30).value == "failed"
        assert uninstall_calls(transport) == []

    def test_stale_confirmation_is_refused_by_the_service_gate(
            self, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        stale = fresh_confirmation(
            "admin:uninstall_app:com.demo.app",
            age_s=CONFIRMATION_TTL_SECONDS + 60.0)
        handle = backend.start_admin_job(
            "S1", "uninstall_app", "com.demo.app", stale)
        assert handle.wait(30).value == "failed"
        assert uninstall_calls(transport) == []

    def test_force_stop_and_launch_reach_the_service(
            self, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        confirmation = fresh_confirmation("admin:force_stop_app:com.demo.app")
        handle = backend.start_admin_job(
            "S1", "force_stop_app", "com.demo.app", confirmation)
        assert handle.wait(30).value == "succeeded"
        assert ("shell", "am", "force-stop", "com.demo.app") in \
            [argv for _s, argv in transport.calls]
        confirmation = fresh_confirmation("admin:launch_app:com.demo.app")
        handle = backend.start_admin_job(
            "S1", "launch_app", "com.demo.app", confirmation)
        assert handle.wait(30).value == "succeeded"
        am_starts = [argv for _s, argv in transport.calls
                     if argv[:2] == ("shell", "am") and "start" in argv]
        assert am_starts, "launch must run am start through the service"


# ===========================================================================
# devices workspace: the Administration tab (R-13 on desktop)
# ===========================================================================

class ScriptedAdminDialog(QDialog):
    """Stands in for the modal (exec never opens a real event loop).

    The knobs are named ``result_accepted``/``phrase`` on PURPOSE: the
    real ``QDialog API`` reserves ``accepted`` as a signal, so the
    scripted stand-in must not shadow it."""

    result_accepted: bool = True
    phrase: str = ""
    instances: List["ScriptedAdminDialog"] = []

    def __init__(self, op: str, package: str, serial: str,
                 parent: Any = None) -> None:
        super().__init__(parent)
        self.op = op
        self.package = package
        self.serial = serial
        ScriptedAdminDialog.instances.append(self)

    def exec(self) -> int:
        return (int(QDialog.DialogCode.Accepted)
                if ScriptedAdminDialog.result_accepted
                else int(QDialog.DialogCode.Rejected))

    def typed_package(self) -> str:
        return ScriptedAdminDialog.phrase


class ScriptedCleartextDialog(QDialog):
    """Stands in for the clear-text confirm on the forensics page.

    ``result_accepted`` (not ``accepted``): ``QDialog.accepted`` is a
    Qt signal and a stand-in must not shadow it."""

    result_accepted: bool = True
    phrase: str = ACK_PHRASE
    instances: List["ScriptedCleartextDialog"] = []

    def __init__(self, case_id: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.case_id = case_id
        ScriptedCleartextDialog.instances.append(self)

    def exec(self) -> int:
        return (int(QDialog.DialogCode.Accepted)
                if ScriptedCleartextDialog.result_accepted
                else int(QDialog.DialogCode.Rejected))

    def typed_phrase(self) -> str:
        return ScriptedCleartextDialog.phrase


def admin_revalidation_spy(page: DeviceWorkspacePage,
                           monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capture the revalidation worker callback instead of racing it."""
    captured: dict = {}

    def run(slot: str, fn, on_done, on_err) -> bool:
        captured["slot"] = slot
        captured["on_done"] = on_done
        captured["on_err"] = on_err
        return True

    monkeypatch.setattr(page._workers, "run", run, raising=True)
    return captured


class TestAdminDialogExactness:
    def test_proceed_enabled_only_for_exact_retype(self, qapp) -> None:
        dialog = AdminConfirmDialog(
            "uninstall_app", "com.demo.app", "S1")
        assert not dialog._proceed.isEnabled()
        dialog._input.setText("com.demo.ap")
        assert not dialog._proceed.isEnabled()
        dialog._input.setText("com.demo.app")
        assert dialog._proceed.isEnabled()

    def test_dialog_is_operation_specific_never_generic(self, qapp) -> None:
        dialog = AdminConfirmDialog(
            "uninstall_app", "com.demo.app", "S1")
        text = joined_texts(dialog).lower()
        assert "uninstall com.demo.app on s1" in text
        assert "adb uninstall" in text
        assert "am force-stop" not in text
        assert dialog.typed_package() == ""


class TestAdminPageFlow:
    def _armed_page(self, qapp, config_service, backend_factory, monkeypatch,
                    transport: Stage12Transport):
        page, backend, _bridge = fresh_workspace(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        page._admin_package_input.setText("com.demo.app")
        monkeypatch.setattr(
            devices_module, "AdminConfirmDialog",
            ScriptedAdminDialog, raising=True)
        ScriptedAdminDialog.phrase = "com.demo.app"
        ScriptedAdminDialog.result_accepted = True
        return page, backend, transport

    def test_cancel_dispatches_nothing(
            self, qapp, config_service, backend_factory, monkeypatch):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = self._armed_page(
            qapp, config_service, backend_factory, monkeypatch, transport)
        workers = admin_revalidation_spy(page, monkeypatch)
        ScriptedAdminDialog.result_accepted = False
        try:
            page._admin_buttons["uninstall_app"].click()
        finally:
            ScriptedAdminDialog.result_accepted = True
        assert page._admin_state == "idle"
        assert "slot" not in workers, \
            "a cancelled confirm must not even begin revalidation"
        assert uninstall_calls(transport) == []

    def test_accepted_flow_binds_exact_op_target_and_runs(
            self, qapp, config_service, backend_factory, monkeypatch):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, backend, _bridge = self._armed_page(
            qapp, config_service, backend_factory, monkeypatch, transport)
        workers = admin_revalidation_spy(page, monkeypatch)
        submitted: List[tuple] = []
        real_start = backend.start_admin_job

        def spy(serial, op, package, confirmation):
            submitted.append((serial, op, package, confirmation.reference,
                              confirmation.confirmed_at))
            return real_start(serial, op, package, confirmation)

        monkeypatch.setattr(backend, "start_admin_job", spy, raising=True)
        page._admin_buttons["uninstall_app"].click()
        assert page._admin_state == "revalidating"
        # fresh device rows come from the REAL discovery service
        workers["on_done"](tuple(backend.list_devices()))
        assert pump_until(qapp, lambda: page._admin_state == "done",
                          timeout_s=15)
        (serial, op, package, reference, confirmed_at) = submitted[0]
        assert (serial, op, package) == ("S1", "uninstall_app", "com.demo.app")
        assert reference == "admin:uninstall_app:com.demo.app"
        assert confirmed_at.tzinfo is not None
        age = (datetime.now(timezone.utc)
               - confirmed_at.astimezone(timezone.utc)).total_seconds()
        assert age < 5.0, "the token is minted at submit time"
        assert uninstall_calls(transport) == [("uninstall", "com.demo.app")]
        status = page._admin_status.text() or ""
        assert "return code 0" in status
        assert "re-verify" in status

    def test_stale_target_refuses_before_dispatch(
            self, qapp, config_service, backend_factory, monkeypatch):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, backend, _bridge = self._armed_page(
            qapp, config_service, backend_factory, monkeypatch, transport)
        workers = admin_revalidation_spy(page, monkeypatch)
        page._admin_buttons["uninstall_app"].click()
        # the device vanished between confirmation and revalidation
        workers["on_done"](())  # fresh listing found NOTHING
        assert page._admin_state == "refused"
        assert page._admin_serial is None
        assert "nothing was dispatched" in \
            (page._admin_status.text() or "")
        assert uninstall_calls(transport) == []

    def test_reselection_during_revalidation_refuses(
            self, qapp, config_service, backend_factory, monkeypatch):
        transport = Stage12Transport(
            devices_lines=("S1 device", "S2 device"))
        page, backend, _bridge = self._armed_page(
            qapp, config_service, backend_factory, monkeypatch, transport)
        workers = admin_revalidation_spy(page, monkeypatch)
        page._admin_buttons["launch_app"].click()
        assert page._admin_state == "revalidating"
        # the user moves the target while revalidating
        select_row(qapp, page, "S2")
        assert page._admin_state == "refused"
        workers["on_done"](tuple(backend.list_devices()))
        assert page._admin_state == "refused"
        am_starts = [argv for _s, argv in transport.calls
                     if argv[:2] == ("shell", "am") and "start" in argv]
        assert am_starts == []

    def test_duplicate_submission_is_refused_while_active(
            self, qapp, config_service, backend_factory, monkeypatch):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = self._armed_page(
            qapp, config_service, backend_factory, monkeypatch, transport)
        admin_revalidation_spy(page, monkeypatch)
        page._admin_buttons["uninstall_app"].click()
        pending_dialogs = len(ScriptedAdminDialog.instances)
        page._admin_buttons["uninstall_app"].click()
        assert len(ScriptedAdminDialog.instances) == pending_dialogs, \
            "a second confirm must not open while one operation is active"
        assert page._admin_state == "revalidating"

    def test_empty_package_leaves_the_buttons_disabled(
            self, qapp, config_service, backend_factory, monkeypatch):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_workspace(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        page._admin_package_input.setText("   ")
        page._sync_device_controls()
        assert not page._admin_buttons["uninstall_app"].isEnabled()
        assert not page._admin_buttons["launch_app"].isEnabled()

    def test_no_selection_disables_every_admin_button(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_workspace(
            qapp, config_service, backend_factory, transport)
        page._sync_device_controls()
        for op_button in page._admin_buttons.values():
            assert not op_button.isEnabled()


# ===========================================================================
# backend seam: forensics
# ===========================================================================

class TestBackendForensicsSeam:
    def _backend(self, config_service, backend_factory, tmp_path):
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(
            config_service, transport, case_root=tmp_path / "cases")
        return backend, transport

    def test_start_forensics_job_create_case_runs_real_service(
            self, config_service, backend_factory, tmp_path):
        backend, _transport = self._backend(
            config_service, backend_factory, tmp_path)
        handle = backend.start_forensics_job("S1", "create_case", {
            "case_name": "backend_case", "device_model": "Pixel",
        })
        assert handle.kind is JobKind.FORENSICS_OP
        assert handle.device_serial == "S1"
        assert handle.wait(30).value == "succeeded"
        assert (tmp_path / "cases" / "backend_case" /
                "manifest.json").exists()

    def test_wifi_cleartext_requires_a_typed_confirmation_object(
            self, config_service, backend_factory, tmp_path):
        backend, _transport = self._backend(
            config_service, backend_factory, tmp_path)
        handle = backend.start_forensics_job("S1", "create_case", {
            "case_name": "backend_wifi"})
        assert handle.wait(30).value == "succeeded"
        typed_job = backend.start_forensics_job("S1", "wifi_cleartext", {
            "case_id": "backend_wifi",
            "confirmation": "I ACCEPT CLEARTEXT PSK",
        })
        assert typed_job.wait(30).value == "failed"

    def test_unknown_forensics_op_is_refused(
            self, config_service, backend_factory, tmp_path):
        backend, _transport = self._backend(
            config_service, backend_factory, tmp_path)
        handle = backend.start_forensics_job("S1", "steal_keys", {})
        assert handle.wait(30).value == "failed"

    def test_forensics_load_case_reads_the_saved_manifest(
            self, config_service, backend_factory, tmp_path):
        backend, _transport = self._backend(
            config_service, backend_factory, tmp_path)
        handle = backend.start_forensics_job(
            "S1", "create_case", {"case_name": "reopen_me"})
        assert handle.wait(30).value == "succeeded"
        manifest = backend.forensics_load_case("reopen_me")
        assert manifest.case_id == "reopen_me"


# ===========================================================================
# forensics page: case-first flow + R-12 redaction gating
# ===========================================================================

FORENSICS_TRANSPORT_KW: dict[str, Any] = {
    "devices_lines": ("S1 device",),
    "root_mode": "not_rooted",
    "wifi_conf": WIFI_CONF,
    "logcat_text": DEFAULT_LOGCAT,
    "ps_text": "root 1 1234 com.demo.app\n",
    "third_party": ("com.demo.app",),
    "su_listing": {
        "/data/data/com.demo.app/databases": ("db.db\nother.db", 0),
    },
    "cat_bytes": {
        "/data/data/com.demo.app/databases/db.db": b"sqlite-bytes-1",
    },
}


def wifi_calls(transport: Stage12Transport) -> list[tuple]:
    return [argv for _s, argv in transport.calls
            if any("wpa_supplicant" in part for part in argv)]


class TestForensicsPage:
    def _page(self, qapp, config_service, backend_factory, tmp_path,
              **transport_overrides: Any):
        transport = Stage12Transport(
            **{**FORENSICS_TRANSPORT_KW, **transport_overrides})
        case_root = tmp_path / "cases"
        page, backend, _bridge = fresh_forensics(
            qapp, config_service, backend_factory, transport, case_root)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        return page, case_root, transport

    def _create(self, qapp, page, name: str) -> None:
        page._case_name_input.setText(name)
        page._create_case_button.click()
        assert pump_until(
            qapp, lambda: page._manifest is not None
            and page._job_state == "done", timeout_s=15)

    def test_create_case_records_honest_root_tri_state(
            self, qapp, config_service, backend_factory, tmp_path):
        page, case_root, transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        self._create(qapp, page, "casealpha")
        manifest = page._manifest
        assert manifest is not None and manifest.case_id == "casealpha"
        # the root verdict comes from the service's tri-state probe
        assert manifest.root_status == "not-rooted"
        assert manifest.is_rooted is False
        assert any(argv[:3] == ("shell", "su", "-c")
                   for _s, argv in transport.calls)
        case_text = page._case_banner.text() or ""
        assert "root: not-rooted (tri-state)" in case_text
        assert "redaction preset: default-redacted" in case_text
        assert (case_root / "casealpha" / "manifest.json").exists()

    def test_duplicate_case_name_never_overwrites(
            self, qapp, config_service, backend_factory, tmp_path):
        page, case_root, _transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        self._create(qapp, page, "casealpha")
        first_manifest = page._manifest
        created_at = first_manifest.created_at
        page._create_case_button.click()
        assert pump_until(qapp, lambda: page._job_state == "failed",
                          timeout_s=15)
        banner = page._job_banner.text() or ""
        assert "already exists" in banner, (
            f"the overwrite refusal must be named verbatim: {banner}")
        assert page._manifest is first_manifest
        assert page._manifest.created_at == created_at
        saved = json.loads(
            (case_root / "casealpha" / "manifest.json").read_text(
                encoding="utf-8"))
        assert saved["created"] == created_at

    def test_open_case_reloads_the_saved_manifest(
            self, qapp, config_service, backend_factory, tmp_path):
        page, _case_root, _transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        self._create(qapp, page, "reopenme")
        page._manifest = None
        page._files_model.set_manifest(None)
        page._job_state = "idle"
        page._case_id_input.setText("reopenme")
        page._open_case_button.click()
        assert pump_until(qapp, lambda: page._manifest is not None,
                          timeout_s=15)
        assert page._manifest.case_id == "reopenme"
        assert page._job_state == "done"

    def test_open_unknown_case_reports_the_failure(
            self, qapp, config_service, backend_factory, tmp_path):
        page, _case_root, _transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        page._case_id_input.setText("missingcase")
        page._open_case_button.click()
        assert pump_until(qapp, lambda: page._job_state == "failed",
                          timeout_s=15)
        banner = page._job_banner.text() or ""
        assert "missingcase" in banner
        assert page._manifest is None

    def test_extract_app_data_is_byte_exact_and_honest_about_gaps(
            self, qapp, config_service, backend_factory, tmp_path):
        page, case_root, transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        self._create(qapp, page, "extractcase")
        page._package_input.setText("com.demo.app")
        page._extract_button.click()
        assert pump_until(qapp, lambda: page._job_state == "done",
                          timeout_s=15)
        manifest = page._manifest
        # only ONE file copied byte-exactly; other.db is unreadable and is
        # recorded as a failed copy — never skipped, never faked as done
        assert len(manifest.files) == 1
        record = manifest.files[0]
        assert record.source_path.endswith("db.db")
        assert record.byte_count == len(b"sqlite-bytes-1")
        extracted = (case_root / "extractcase" / "com.demo.app_databases" /
                     "databases" / "db.db")
        assert extracted.read_bytes() == b"sqlite-bytes-1"
        status_words = " | ".join(
            status for _op, status in manifest.extractions)
        assert "copy failed" in status_words
        assert "1/2 files copied" in status_words
        file_rows = page._files_model.rows
        assert len(file_rows) == 1
        assert file_rows[0][2] == record.sha256[:12]
        # shared_prefs / files listings were probed honestly for this case
        listed_dirs = [argv for _s, argv in transport.calls
                       if "shared_prefs" in " ".join(argv)]
        assert listed_dirs

    def test_traversal_package_never_reaches_the_device(
            self, qapp, config_service, backend_factory, tmp_path):
        page, _case_root, transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        self._create(qapp, page, "safecase")
        page._package_input.setText("../../etc/passwd")
        page._extract_button.click()
        assert pump_until(qapp, lambda: page._job_state == "failed",
                          timeout_s=15)
        ls_calls = [argv for _s, argv in transport.calls
                    if argv[:3] == ("shell", "su", "-c")
                    and any("ls -1" in part for part in argv)]
        assert not ls_calls, \
            "a traversing package must never produce device listings"

    def test_system_logs_text_op_records_success(
            self, qapp, config_service, backend_factory, tmp_path):
        page, case_root, _transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        self._create(qapp, page, "logcase")
        page._text_op_buttons["system_logs"].click()
        assert pump_until(qapp, lambda: page._job_state == "done",
                          timeout_s=15)
        manifest = page._manifest
        entries = [status for op, status in manifest.extractions
                   if op == "system_logs"]
        assert entries and "success (2 lines)" in entries[-1]
        saved = (case_root / "logcase" / "system_logs.txt").read_text(
            encoding="utf-8")
        assert "log line 1" in saved

    def test_wifi_defaults_to_redacted(
            self, qapp, config_service, backend_factory, tmp_path):
        page, case_root, _transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        self._create(qapp, page, "wificase")
        page._text_op_buttons["wifi_redacted"].click()
        assert pump_until(qapp, lambda: page._job_state == "done",
                          timeout_s=15)
        manifest = page._manifest
        assert manifest.redaction_preset == "default-redacted"
        saved = (case_root / "wificase" / "wifi_networks.txt").read_text(
            encoding="utf-8")
        assert "secret-pass-1" not in saved, \
            "the default export must be redacted (R-12)"
        assert not (case_root / "wificase" /
                    "wifi_networks_cleartext.txt").exists()

    def test_cleartext_cancel_or_mismatch_writes_nothing(
            self, qapp, config_service, backend_factory, tmp_path,
            monkeypatch):
        page, case_root, transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        self._create(qapp, page, "clearcase")
        monkeypatch.setattr(
            forensics_module, "CleartextConfirmDialog",
            ScriptedCleartextDialog, raising=True)
        # (a) the dialog is REJECTED → no token, no job, no write
        ScriptedCleartextDialog.result_accepted = False
        ScriptedCleartextDialog.phrase = ACK_PHRASE
        page._cleartext_button.click()
        assert page._job_state == "done"  # unchanged by the abandon
        assert wifi_calls(transport) == []
        # (b) accepted but the phrase does NOT match EXACTLY → also nothing
        ScriptedCleartextDialog.result_accepted = True
        ScriptedCleartextDialog.phrase = "i accept cleartext psk"
        page._cleartext_button.click()
        assert page._job_state == "done"
        assert wifi_calls(transport) == []
        assert page._manifest.redaction_preset == "default-redacted"
        assert not (case_root / "clearcase" /
                    "wifi_networks_cleartext.txt").exists()

    def test_cleartext_exact_phrase_runs_the_service_gated_job(
            self, qapp, config_service, backend_factory, tmp_path,
            monkeypatch):
        page, case_root, _transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        self._create(qapp, page, "grantedcase")
        monkeypatch.setattr(
            forensics_module, "CleartextConfirmDialog",
            ScriptedCleartextDialog, raising=True)
        ScriptedCleartextDialog.result_accepted = True
        ScriptedCleartextDialog.phrase = ACK_PHRASE
        submitted: List[OperationConfirmation] = []
        real_start = page._backend.start_forensics_job

        def spy(serial, op, kwargs=None):
            if op == "wifi_cleartext":
                submitted.append(kwargs.get("confirmation"))
            return real_start(serial, op, kwargs)

        monkeypatch.setattr(
            page._backend, "start_forensics_job", spy, raising=True)
        page._cleartext_button.click()
        assert pump_until(qapp, lambda: page._job_state == "done",
                          timeout_s=15)
        assert len(submitted) == 1
        confirmation = submitted[0]
        assert isinstance(confirmation, OperationConfirmation)
        assert confirmation.reference == "wifi_cleartext_psk"
        assert confirmation.confirmed_at.tzinfo is not None
        assert page._manifest.redaction_preset == "explicit-unredacted"
        cleartext = (case_root / "grantedcase" /
                     "wifi_networks_cleartext.txt").read_text(
                         encoding="utf-8")
        assert "secret-pass-1" in cleartext

    def test_cleartext_dialog_requires_exact_typing_in_real_dialog(
            self, qapp) -> None:
        from PySide6.QtWidgets import QDialogButtonBox

        dialog = CleartextConfirmDialog("somecase")
        proceed = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert not proceed.isEnabled()
        dialog._input.setText("I accept cleartext psk")
        assert not proceed.isEnabled()
        dialog._input.setText(ACK_PHRASE)
        assert proceed.isEnabled()

    def test_report_writes_the_legacy_fields(
            self, qapp, config_service, backend_factory, tmp_path):
        page, case_root, _transport = self._page(
            qapp, config_service, backend_factory, tmp_path)
        self._create(qapp, page, "reportcase")
        page._report_button.click()
        assert pump_until(qapp, lambda: page._job_state == "done",
                          timeout_s=15)
        report = json.loads(
            (case_root / "reportcase" / "report.json").read_text(
                encoding="utf-8"))
        assert report["case_name"] == "reportcase"
        assert report["created"] == page._manifest.created_at
        assert report["is_rooted"] is False
        assert report["root_status"] == "not-rooted"
        assert "report finished" in (page._job_banner.text() or "")


# ===========================================================================
# mirroring: lifecycle parity + the desktop duplicate-launch hardening
# ===========================================================================

class TestMirroringPage:
    def test_preflight_shows_the_honest_tool_state(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_mirroring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        assert pump_until(
            qapp, lambda: "scrcpy tool state: validated"
            in joined_texts(page))
        registry = backend_factory.last_registry()
        assert registry.tool_status.state is ToolState.VALIDATED

    def test_preflight_refusal_words_for_an_unprovisioned_tool(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_mirroring(
            qapp, config_service, backend_factory, transport)
        registry = backend_factory.last_registry()
        registry.tool_status = ToolStatusReflected(
            tool=ToolId.SCRCPY, state=ToolState.FOUND_UNVALIDATED)
        page.activate()
        assert pump_until(
            qapp, lambda: "REFUSED" in joined_texts(page).upper(),
            timeout_s=10)
        text = joined_texts(page)
        assert "found but never validated" in text

    def test_launch_records_a_handle_and_duplicate_launch_is_refused(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_mirroring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        registry = backend_factory.last_registry()
        service = registry.mirror("S1")
        page._launch_button.click()
        assert pump_until(qapp, lambda: page._launching_serial is None,
                          timeout_s=10)
        assert service.launch_calls == [LAUNCH_OPTIONS]
        assert page._launched_serials == {"S1"}
        banner = page._lifecycle_banner.text() or ""
        assert "launch recorded" in banner
        assert "NOT claimed" in banner
        # duplicate prevention: a second launch while one is running
        page._launch_button.click()
        assert pump_until(qapp, lambda: page._launching_serial is None,
                          timeout_s=10)
        assert service.launch_calls == [LAUNCH_OPTIONS], \
            "duplicate launches must be refused, never stacked"
        assert "duplicate launches are refused" in \
            (page._lifecycle_banner.text() or "")

    def test_handles_list_shows_running_and_exit_codes(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_mirroring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        service = backend_factory.last_registry().mirror("S1")
        page._launch_button.click()
        assert pump_until(qapp, lambda: page._launching_serial is None,
                          timeout_s=10)
        assert service.launch_calls
        page._handles_button.click()
        assert pump_until(qapp, lambda: page._handle_state == "ready",
                          timeout_s=10)
        rows = page._handles_model.rows
        assert rows and rows[0][0].isdigit() and rows[0][3] == "running"
        # an unexpected exit surfaces honestly in the SAME lifecycle view
        service.mark_exited(int(rows[0][0]), 4)
        page._handles_button.click()
        assert pump_until(
            qapp,
            lambda: "exited (4)" in " | ".join(
                " ".join(r) for r in page._handles_model.rows),
            timeout_s=10)

    def test_stop_routes_through_the_service_and_reports(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_mirroring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        page._launch_button.click()
        assert pump_until(qapp, lambda: page._launching_serial is None,
                          timeout_s=10)
        page._stop_button.click()
        assert pump_until(
            qapp, lambda: "stop done" in
            (page._lifecycle_banner.text() or ""), timeout_s=10)
        service = backend_factory.last_registry().mirror("S1")
        assert service.stop_calls == [None]
        assert page._launched_serials == set()

    def test_tool_not_validated_refusal_is_shown_verbatim(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_mirroring(
            qapp, config_service, backend_factory, transport)
        registry = backend_factory.last_registry()
        registry.tool_status = ToolStatusReflected(
            tool=ToolId.SCRCPY, state=ToolState.FOUND_UNVALIDATED)
        service = FakeMirrorService("S1")
        registry._mirrors["S1"] = service
        service.launch_error = ToolNotValidated(
            "screen mirroring requires a validated scrcpy tool; provision "
            "and validate it first",
            {"scrcpy_path": "not validated"})
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        page._launch_button.click()
        assert pump_until(qapp, lambda: page._launching_serial is None,
                          timeout_s=10)
        banner = page._lifecycle_banner.text() or ""
        assert "REFUSED" in banner.upper()
        assert "validated scrcpy tool" in banner
        assert service.launch_calls == [LAUNCH_OPTIONS]
        assert page._launched_serials == set()

    def test_launch_options_never_offer_screen_off(
            self, qapp, config_service, backend_factory):
        assert LAUNCH_OPTIONS.turn_screen_off is False
        assert LAUNCH_OPTIONS.confirm_screen_off is False
        # model-level guard stands: the device-mutating route cannot be
        # smuggled through the page's options object
        with pytest.raises(ValueError):
            MirrorOptions(turn_screen_off=True)

    def test_shutdown_stops_the_mirrors_this_page_launched(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        page, _backend, _bridge = fresh_mirroring(
            qapp, config_service, backend_factory, transport)
        auto_discover(qapp, page)
        select_row(qapp, page, "S1")
        page._launch_button.click()
        assert pump_until(qapp, lambda: page._launching_serial is None,
                          timeout_s=10)
        service = backend_factory.last_registry().mirror("S1")
        page.shutdown()
        assert service.stop_calls == [None], \
            "app shutdown must stop the mirrors it owns (no orphan children)"
        assert page._launched_serials == set()


# ===========================================================================
# demo: deterministic fixture — zero device-service access
# ===========================================================================

def fresh_demo(qapp, config_service, backend_factory,
               transport: Stage12Transport, open_live: bool = False):
    backend = backend_factory(config_service, transport)
    navigations: List[str] = []
    page = _track_page(DemoPage(
        backend,
        open_live=(lambda: navigations.append("devices"))
        if open_live else None,
    ))
    return page, backend, navigations


DEMO_TRANSPORT_KW: dict[str, Any] = {
    "devices_lines": ("S1 device",),
    "third_party": ("com.demo.app",),
}


class TestDemoPage:
    def test_builds_the_deterministic_fixture_automatically(
            self, qapp, config_service, backend_factory, history_target):
        transport = Stage12Transport(**DEMO_TRANSPORT_KW)
        page, _backend, _navigations = fresh_demo(
            qapp, config_service, backend_factory, transport)
        calls_before = list(transport.calls)
        page.activate()
        assert page._state == "ready"
        texts = joined_texts(page)
        assert texts.count("DEMO") >= 2
        assert "no device was contacted" in texts.lower()
        rows = page._model.rows
        assert rows, "the fixture must produce the [DEMO] findings table"
        assert all(row[3].startswith("[DEMO]") for row in rows)
        assert page._demo_chip is not None
        assert transport.calls == calls_before, \
            "building the demo fixture must never pass a device command"

    def test_zero_device_service_access_and_zero_history_writes(
            self, qapp, config_service, backend_factory, history_target,
            monkeypatch):
        transport = Stage12Transport(**DEMO_TRANSPORT_KW)
        page, backend, _navigations = fresh_demo(
            qapp, config_service, backend_factory, transport)
        calls_before = list(transport.calls)
        raised: List[BaseException] = []

        def spy_remember_scan(*args: Any, **kwargs: Any):
            raised.append(RuntimeError("remember_scan was called"))

        monkeypatch.setattr(
            backend, "remember_scan", spy_remember_scan, raising=True)
        page.activate()
        assert page._state == "ready"
        page.generate()
        assert page._state == "ready"
        assert transport.calls == calls_before, \
            "the demo flow must never touch the device transport"
        assert not raised, "remember_scan must never be called"
        assert not history_target.exists() or \
            list(history_target.iterdir()) == [], \
            "the demo flow must never write scan history"
        assert backend.last_scan() is None, \
            "the demo flow must never touch the scan memory"

    def test_output_is_deterministic_across_rebuilds(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(**DEMO_TRANSPORT_KW)
        page, backend, _navigations = fresh_demo(
            qapp, config_service, backend_factory, transport)
        bundle_one = backend.demo_bundle()
        bundle_two = backend.demo_bundle()
        # The deterministic ENGINE contract: static fixture content and
        # FIXED run timestamps. Two things are legitimately run-unique:
        # the ScanRequest envelope (fresh id/created_at per build) and
        # each Evidence.extracted_at (= the moment the fixture was built).
        def content(bundle) -> tuple:
            return tuple(
                (f.title, f.kind.value, f.severity.value, f.detail)
                for app in bundle.apps for f in app.findings)

        assert content(bundle_one) == content(bundle_two)
        summary = bundle_one.summary
        assert summary.demo is True
        assert summary.total_apps == 3
        assert summary.findings_total == bundle_two.summary.findings_total
        assert summary.run.started_at == bundle_two.summary.run.started_at
        assert summary.run.finished_at == bundle_two.summary.run.finished_at
        assert (summary.run.request.id
                != bundle_two.summary.run.request.id), (
            "each build gets its own scan request envelope (by design)")
        page.activate()
        first_row_set = [row[3] for row in page._model.rows]
        page.generate()
        assert page._state == "ready"
        assert [row[3] for row in page._model.rows] == first_row_set

    def test_registry_demo_face_is_the_only_engine_touch(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(**DEMO_TRANSPORT_KW)
        page, _backend, _navigations = fresh_demo(
            qapp, config_service, backend_factory, transport)
        page.activate()
        assert page._state == "ready"
        registry = backend_factory.last_registry()
        assert registry.demo_builds >= 1
        for counter_name in ("monitor_builds", "admin_builds",
                             "forensics_builds"):
            assert getattr(registry, counter_name) == 0, \
                f"the demo flow touched {counter_name}!"

    def test_back_to_live_navigation_is_provided(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(**DEMO_TRANSPORT_KW)
        page, _backend, navigations = fresh_demo(
            qapp, config_service, backend_factory, transport, open_live=True)
        page.activate()
        assert page._state == "ready"
        page._back_button.click()
        assert navigations == ["devices"], \
            "the demo page must offer an obvious exit back to live data"


# ===========================================================================
# shell navigation: the new sections build and survive round-trips
# ===========================================================================

class TestShellNavigation:
    def test_new_sections_build_stay_cached_and_refresh(
            self, qapp, config_service, backend_factory):
        transport = Stage12Transport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        window = MainWindow(config_service, backend=backend)
        try:
            for section_id, page_type in (
                    ("monitoring", MonitoringPage),
                    ("forensics", ForensicsPage),
                    ("mirroring", MirroringPage),
                    ("demo", DemoPage)):
                window.switch_to(section_id)
                page = window.content_widget(section_id)
                assert isinstance(page, page_type), section_id
                if section_id == "demo":
                    assert page._state == "ready"
            # round-trip: the cached widgets are the SAME instances
            window.switch_to("dashboard")
            window.switch_to("monitoring")
            page = window.content_widget("monitoring")
            assert isinstance(page, MonitoringPage)
            assert pump_until(qapp, lambda: page._devices_state
                              in ("refreshed", "failed"), timeout_s=10)
        finally:
            window.close()
