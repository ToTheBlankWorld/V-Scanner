"""Stage 10 desktop device-workspace tests — offscreen Qt harness.

Requires the ``desktop`` extra (PySide6); skipped with a documented reason
otherwise (engine-only environments keep the suite green).

Cross-cutting discipline (mirrors the Stage 09 harness rules):

* Qt runs on the ``offscreen`` platform unless the caller chose one; tests
  need no display server. ADB is NEVER a real subprocess: the shared
  engine services run over a fully scripted fake transport, so the tests
  exercise REAL parsing/discovery/root/device-info/inventory logic without
  physical hardware, devices, root, or network.
* Long-running calls go through the REAL ``DesktopBackend`` + REAL Stage 04
  ``JobManager`` + the REAL ``QtJobEventBridge``; GUI-thread delivery is
  asserted by capturing ``threading.get_ident()`` inside receiving slots.
* Widgets are pumped with ``processEvents`` — never by blocking ``wait()``
  on the GUI thread (the UI rule itself being tested).
* Window-level screens are reached through the shell so dedup, activation
  and cleanup rules are exercised exactly as in production.
"""

from __future__ import annotations

import ast
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, List, Optional, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip(
    "PySide6",
    reason="desktop extra not installed (pip install -e '.[desktop]') — "
           "Stage 10 tests are desktop-specific; the engine suite does not "
           "depend on them")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

import ui_desktop.backend as backend_module  # noqa: E402
from ui_desktop import sections as reg  # noqa: E402
from ui_desktop.backend import DesktopBackend  # noqa: E402
from ui_desktop.jobs_bridge_qt import QtJobEventBridge  # noqa: E402
from ui_desktop.main_window import MainWindow  # noqa: E402
from ui_desktop.screens.devices import (  # noqa: E402
    PAGE_SIZE,
    DeviceWorkspacePage,
    engine_error_text,
)
from ui_desktop.settings_dialog import SettingsDialog  # noqa: E402
from ui_desktop.widgets import ErrorState  # noqa: E402
from ui_desktop.workers import WorkerCoordinator  # noqa: E402
from vscanner.core.events import (  # noqa: E402
    JobKind,
    JobState,
    JobTerminalEvent,
)
from vscanner.core.errors import (  # noqa: E402
    AdbCommandError,
    AdbNotAvailable,
)
from vscanner.core.models import (  # noqa: E402
    AppInfo,
    AppLabelSource,
    DeviceState,
    RootStatus,
)
from vscanner.services.adb.client import AdbResult  # noqa: E402
from vscanner.services.adb.device_info import DeviceInfoService  # noqa: E402
from vscanner.services.adb.devices import DeviceDiscoveryService  # noqa: E402
from vscanner.services.adb.root_probe import RootStatusService  # noqa: E402
from vscanner.services.config import ConfigService  # noqa: E402

GUI_THREAD = threading.get_ident()


# ===========================================================================
# helpers: deterministic pumping + widget search
# ===========================================================================

def pump_until(qapp: QApplication, predicate, timeout_s: float = 5.0) -> bool:
    """Process events until ``predicate()`` holds (never blocks the loop)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            qapp.processEvents()
            return True
        time.sleep(0.01)
    return False


def texts_of(widget) -> List[str]:
    return [label.text() for label in
            widget.findChildren(QLabel) if label.text()]


def joined_texts(widget) -> str:
    return " ".join(texts_of(widget))


def button_of(widget, text: str) -> Optional[QPushButton]:
    for button in widget.findChildren(QPushButton):
        if text in button.text():
            return button
    return None


def wait_refresh_done(qapp, page: DeviceWorkspacePage) -> bool:
    """True once the refresh control is enabled again (result settled)."""
    return pump_until(qapp, lambda: page._refresh_button.isEnabled())


def probe_calls(transport: "FakeAdbTransport") -> int:
    return sum(1 for _serial, argv in transport.calls
               if argv[:1] == ("devices",))


def make_terminal_spy() -> type:
    """A page subclass recording one entry per terminal delivery.

    The recorded second element is ``threading.get_ident()`` of the slot —
    it must be the GUI thread (the ring being proven). Class subclassing
    keeps Qt's connection bound to the natural receiver (no monkeypatched
    class attribute surviving interpreter shutdown)."""

    class SpyPage(DeviceWorkspacePage):
        deliveries: List[Any] = []

        def _on_terminal_event(self, event) -> None:
            SpyPage.deliveries.append((event, threading.get_ident()))
            super()._on_terminal_event(event)

    return SpyPage


# ===========================================================================
# fake ADB transport + fake registry (engine integration without hardware)
# ===========================================================================

class FakeAdbTransport:
    """Scripted ``run_text`` transport the shared engine services consume.

    Responds to the exact commands those services issue:

    * ``devices``                          — scripted rows (discovery parses)
    * ``shell getprop <key>``              — scripted props (device-info runs)
    * ``shell uname -r``                   — scripted kernel
    * ``shell su -c id`` / ``command -v su`` / package probe — root modes
    * ``shell pm list packages [-3|-s]``   — scripted packages (inventory runs)
    """

    def __init__(
        self,
        *,
        devices_lines: tuple[str, ...] = (),
        getprops: Optional[dict[str, str]] = None,
        kernel: str = "6.1.0-test",
        third_party: tuple[str, ...] = (),
        system: tuple[str, ...] = (),
        root_mode: str = "not_rooted",  # not_rooted | rooted | unknown
        fail_devices_after: Optional[int] = None,  # N good calls → raise
        fail_listing: bool = False,
        list_gate: Optional[threading.Event] = None,
    ) -> None:
        self.serial: Optional[str] = None  # set by _SerialBoundClient
        self.calls: list[tuple[Optional[str], tuple]] = []
        self.devices_lines = devices_lines
        self.getprops = dict(getprops or {})
        self.kernel = kernel
        self.third_party = third_party
        self.system = system
        self.root_mode = root_mode
        self.fail_devices_after = fail_devices_after
        self._devices_calls = 0
        self.fail_listing = fail_listing
        self.list_gate = list_gate
        self.list_started = threading.Event()

    def run_text(self, cmd, timeout: float = 30.0) -> AdbResult:
        argv = tuple(str(part) for part in cmd)
        self.calls.append((self.serial, argv))
        if argv[:1] == ("devices",):
            self._devices_calls += 1
            if self.fail_devices_after is not None and \
                    self._devices_calls > self.fail_devices_after:
                raise AdbCommandError(
                    "adb devices timed out", cmd=argv, timeout=True)
            return AdbResult(
                stdout="List of devices attached\n" +
                       "\n".join(self.devices_lines) + "\n",
                stderr="", returncode=0)
        if argv[:1] == ("shell",):
            payload = argv[1:]
            if len(payload) == 2 and payload[0] == "getprop":
                key = payload[1]
                return AdbResult(
                    stdout=self.getprops.get(key, ""), stderr="",
                    returncode=0)
            if payload[:1] == ("uname",):
                return AdbResult(stdout=self.kernel, stderr="", returncode=0)
            if payload[:3] == ("pm", "list", "packages"):
                self.list_started.set()
                if self.list_gate is not None:
                    self.list_gate.wait(10.0)
                if self.fail_listing:
                    raise AdbCommandError(
                        "pm list packages timed out after 30s",
                        cmd=argv, timeout=True)
                flags = payload[3:]
                if "-3" in flags:
                    return AdbResult(
                        stdout="".join(
                            f"package:{n}\n" for n in self.third_party),
                        stderr="", returncode=0)
                if "-s" in flags:
                    return AdbResult(
                        stdout="".join(
                            f"package:{n}\n" for n in self.system),
                        stderr="", returncode=0)
                names = self.third_party + self.system
                return AdbResult(
                    stdout="".join(f"package:{n}\n" for n in names),
                    stderr="", returncode=0)
            if payload[:2] == ("su", "-c"):
                if self.root_mode == "rooted":
                    return AdbResult(
                        stdout="uid=0(root) gid=0(root) groups=0(root)",
                        stderr="", returncode=0)
                if self.root_mode == "unknown":
                    raise AdbCommandError(
                        "su probe blew up", cmd=argv, timeout=False)
                return AdbResult(stdout="", stderr="denied", returncode=1)
            if payload[:2] == ("command", "-v"):
                # su NOT visible from ADB shell in the "not_rooted" script;
                # the not-rooted verdict then needs the package probe below.
                return AdbResult(stdout="", stderr="", returncode=1)
        raise AdbCommandError("fake transport: unknown command",
                              cmd=argv, timeout=False)


class _SerialBoundClient:
    """Client wrapper marking the transport's serial for the call duration."""

    def __init__(self, transport: FakeAdbTransport,
                 serial: Optional[str]) -> None:
        self._transport = transport
        self.serial = serial

    def run_text(self, cmd, timeout: float = 30.0) -> AdbResult:
        previous = self._transport.serial
        self._transport.serial = self.serial
        try:
            return self._transport.run_text(cmd, timeout=timeout)
        finally:
            self._transport.serial = previous


class FakeRegistry:
    """Same call surface the backend uses on the real ``ServiceRegistry``.

    ``device_info_error`` lets tests poison the detail probe deterministically
    (a transport-level failure that engine code cannot swallow)."""

    adb_path = "C:/fake/adb.exe"

    def __init__(self, transport: FakeAdbTransport) -> None:
        self._transport = transport
        self.device_info_error: Optional[BaseException] = None

    def discovery(self) -> DeviceDiscoveryService:
        return DeviceDiscoveryService(self._transport)

    def device_info(self, serial: Optional[str]) -> DeviceInfoService:
        if self.device_info_error is not None:
            raise self.device_info_error
        return DeviceInfoService(self._transport)

    def root_status(self, serial: Optional[str]) -> RootStatusService:
        return RootStatusService(self._transport)

    def client(self, serial: Optional[str] = None) -> _SerialBoundClient:
        return _SerialBoundClient(self._transport, serial)


class BackendFactory:
    """Real ``DesktopBackend``s whose ``ServiceRegistry`` resolves to fakes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self._created: list[DesktopBackend] = []

    def build(self, config_service: ConfigService,
              transport: FakeAdbTransport) -> DesktopBackend:
        fake = FakeRegistry(transport)
        self._monkeypatch.setattr(
            backend_module, "ServiceRegistry", lambda _path: fake,
            raising=True)
        backend = DesktopBackend(config_service)
        self._created.append(backend)
        return backend

    def teardown(self) -> None:
        for backend in self._created:
            backend.shutdown_jobs()
        self._created.clear()


# ===========================================================================
# fixtures
# ===========================================================================

@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    app = cast(Optional[QApplication], QApplication.instance())
    if app is None:
        from ui_desktop.app import create_application
        app = create_application([])
    assert app is not None
    yield app
    # Deterministic teardown BEFORE interpreter shutdown: PySide6's static
    # Qt cleanup aborts nondeterministically (0xC0000409 / 0xC0000005) when
    # leftover top-level QObjects are destroyed during finalization.
    # Deleting every remaining top-level widget through the event loop here
    # keeps the process exit clean and deterministic (verified 8/8 runs).
    app.processEvents()
    for widget in list(app.topLevelWidgets()):
        widget.deleteLater()
    app.processEvents()


@pytest.fixture()
def config_service(tmp_path) -> ConfigService:
    service = ConfigService(tmp_path / "config.json")
    service.save(r"C:\tools\fake-adb.exe")
    return service


@pytest.fixture()
def backend_factory(qapp, monkeypatch: pytest.MonkeyPatch):
    factory = BackendFactory(monkeypatch)
    yield factory.build
    factory.teardown()


@pytest.fixture()
def shell(qapp, config_service) -> Iterator[MainWindow]:
    """Shell WITHOUT a wired backend (no-config scenario)."""
    window = MainWindow(config_service)
    yield window
    window.close()


def wired_page(qapp, config_service, backend_factory,
               transport: FakeAdbTransport,
               with_bridge: bool = True) -> tuple:
    """(page, backend[, bridge]) — the workspace built like production."""
    backend = backend_factory(config_service, transport)
    if not with_bridge:
        return page_build(backend), backend
    bridge = QtJobEventBridge()
    bridge.attach(backend.manager())
    return page_build(backend, bridge.hub), backend, bridge


def page_build(backend: DesktopBackend, hub: Any = None) -> Any:
    if hub is None:
        from ui_desktop.jobs_bridge_qt import JobEventSignalHub
        hub = JobEventSignalHub()
    return DeviceWorkspacePage(backend, hub)


# ===========================================================================
# WorkerCoordinator (the one-shot Qt thread adapter)
# ===========================================================================

class TestWorkerCoordinator:
    def test_delivers_result_and_runs_slot_on_gui_thread(self, qapp):
        coordinator = WorkerCoordinator()
        seen: list[tuple] = []
        assert coordinator.run(
            "slot", threading.get_ident,
            lambda produced: seen.append((produced, threading.get_ident())),
            lambda exc: seen.append(("failed", exc)),
        ) is True
        assert pump_until(qapp, lambda: bool(seen))
        produced, delivered_on = seen[0]
        assert produced != GUI_THREAD  # the callable itself ran OFF the GUI thread
        assert delivered_on == GUI_THREAD  # the delivery ran ON the GUI thread

    def test_delivers_the_exception_instance_on_failure(self, qapp):
        coordinator = WorkerCoordinator()
        failures: list[BaseException] = []

        def boom() -> None:
            raise AdbNotAvailable("not launchable")

        assert coordinator.run("slot", boom, lambda r: None,
                               failures.append)
        assert pump_until(qapp, lambda: bool(failures))
        assert isinstance(failures[0], AdbNotAvailable)
        assert failures[0].message == "not launchable"

    def test_same_slot_is_single_flight(self, qapp):
        coordinator = WorkerCoordinator()
        results: list[int] = []
        release = threading.Event()
        started = threading.Event()

        def slow() -> int:
            started.set()
            release.wait(5.0)
            return 42

        assert coordinator.run("slot", slow, results.append, lambda e: None)
        assert started.wait(2.0)
        assert coordinator.is_pending("slot")
        assert coordinator.run("slot", slow, results.append,
                               lambda e: None) is False
        assert coordinator.pending_slots() == ("slot",)
        release.set()
        assert pump_until(qapp, lambda: bool(results))
        assert results == [42]
        assert not coordinator.is_pending("slot")
        assert coordinator.pending_slots() == ()

    def test_close_reports_alive_threads_and_clears_state(self, qapp):
        coordinator = WorkerCoordinator()
        release = threading.Event()

        def slow() -> None:
            release.wait(5.0)

        assert coordinator.run("slot", slow, lambda r: None, lambda e: None)
        abandoned = coordinator.close(join_timeout=0.05)
        assert abandoned == ("slot",)  # still running at close time
        release.set()
        assert coordinator.close(join_timeout=5.0) == ()

    def test_repeated_sequential_runs_leave_no_residue(self, qapp):
        coordinator = WorkerCoordinator()
        results: list[int] = []

        def unit() -> int:
            return 7

        for _ in range(3):
            results.clear()
            assert coordinator.run("slot", unit, results.append,
                                   lambda e: None)
            assert pump_until(qapp, lambda: bool(results))
        assert coordinator._pending == {}
        assert coordinator._live_threads == {}


# ===========================================================================
# registry / section honesty
# ===========================================================================

class TestRegistryState:
    def test_devices_is_now_a_live_section(self, shell):
        section = reg.get_section("devices")
        assert section.kind == "live"
        assert section.owner_stage == ""

    def test_remaining_future_sections_are_unchanged(self, shell):
        # Stage 11 moved "scan" and "reports" to live; Stage 12 moved the
        # monitoring/forensics/mirroring/demo set to live as well. No
        # future rows remain (asserted here to keep the registry honest
        # against accidental creep).
        assert reg.future_sections() == ()
        assert reg.get_section("scan").kind == "live"
        assert reg.get_section("reports").kind == "live"
        for section_id in ("monitoring", "forensics", "mirroring", "demo"):
            assert reg.get_section(section_id).kind == "live"

    def test_devices_renders_honest_unavailable_state_without_backend(
            self, shell):
        shell.switch_to("devices")
        page = shell.content_widget("devices")
        assert isinstance(page, ErrorState)
        assert "No engine configuration is wired" in joined_texts(page)

    def test_devices_page_builds_once_per_shell(self, qapp, config_service,
                                                backend_factory):
        transport = FakeAdbTransport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        window = MainWindow(config_service, backend=backend)
        try:
            window.switch_to("devices")
            first = window.content_widget("devices")
            window.switch_to("help")
            window.switch_to("devices")
            second = window.content_widget("devices")
            assert first is second
            assert isinstance(second, DeviceWorkspacePage)
        finally:
            window.close()


# ===========================================================================
# backend (engine seam)
# ===========================================================================

class TestBackendSeam:
    def test_adb_path_saved_reflects_config(self, config_service,
                                            backend_factory):
        backend = backend_factory(config_service, FakeAdbTransport())
        assert backend.adb_path_saved() == r"C:\tools\fake-adb.exe"

    def test_adb_path_saved_none_when_unset(self, tmp_path, backend_factory):
        backend = backend_factory(ConfigService(tmp_path / "none.json"),
                                  FakeAdbTransport())
        assert backend.adb_path_saved() is None

    def test_list_devices_runs_the_real_discovery_parser(
            self, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("ABC123 device model:Pixel", "XYZ offline"))
        backend = backend_factory(config_service, transport)
        rows = backend.list_devices()
        assert [d.serial for d in rows] == ["ABC123", "XYZ"]
        assert rows[0].state is DeviceState.DEVICE
        assert rows[1].state is DeviceState.OFFLINE

    def test_no_saved_path_is_a_typed_refusal(self, tmp_path,
                                              backend_factory):
        config = ConfigService(tmp_path / "none.json")
        backend = backend_factory(config, FakeAdbTransport())
        with pytest.raises(AdbNotAvailable):
            backend.list_devices()

    def test_listing_job_terminalizes_with_synthetic_rows(
            self, qapp, config_service, backend_factory):
        packages = tuple(f"com.vscanner.mock{i:03d}" for i in range(160))
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=packages)
        backend = backend_factory(config_service, transport)
        handle = backend.start_listing_job("SER1", include_system=False)
        assert handle.kind is JobKind.APP_LISTING
        assert pump_until(qapp, lambda: handle.state is JobState.SUCCEEDED)
        assert any(call[0] == "SER1" for call in transport.calls)

    def test_conflicting_submission_is_refused_by_the_workspace_not_the_manager(
            self, qapp, config_service, backend_factory):
        # Stage 04 truth: APP_LISTING is NOT mutex-grouped (TUI parity);
        # overlap prevention lives in the workspace (loading state disables
        # the start control — covered by the busy-listing test there).
        release = threading.Event()
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=("app.example",),
            list_gate=release)
        backend = backend_factory(config_service, transport)
        handle = backend.start_listing_job("SER1", include_system=False)
        assert pump_until(qapp, lambda: transport.list_started.is_set())
        # a second submit would NOT be typ refused by the manager —
        # exactly why the workspace disables its control while loading
        second = backend.start_listing_job("SER1", include_system=False)
        assert second.kind is JobKind.APP_LISTING
        release.set()
        assert pump_until(qapp, lambda: handle.state is JobState.SUCCEEDED)

    def test_active_handle_lifecycle(self, qapp, config_service,
                                     backend_factory):
        release = threading.Event()
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=("app.example",),
            list_gate=release)
        backend = backend_factory(config_service, transport)
        assert backend.active_listing_handle("SER1") is None
        handle = backend.start_listing_job("SER1", include_system=False)
        assert pump_until(qapp, lambda: transport.list_started.is_set())
        active = backend.active_listing_handle("SER1")
        assert active is not None and active.id == handle.id
        release.set()
        assert pump_until(qapp, lambda: handle.state is JobState.SUCCEEDED)
        assert backend.active_listing_handle("SER1") is None

    def test_listing_timeout_surfaces_as_failure_state(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=("app.example",),
            fail_listing=True)
        backend = backend_factory(config_service, transport)
        handle = backend.start_listing_job("SER1", include_system=False)
        assert pump_until(qapp, lambda: handle.state is JobState.FAILED)

    def test_shutdown_without_jobs_is_safe(self, config_service,
                                           backend_factory):
        backend = backend_factory(config_service, FakeAdbTransport())
        backend.shutdown_jobs()
        backend.shutdown_jobs()  # idempotent


# ===========================================================================
# dashboard
# ===========================================================================

class TestDashboard:
    def test_first_run_is_honest_and_has_no_check_control(
            self, qapp, tmp_path):
        from ui_desktop.screens.dashboard import build_dashboard
        config = ConfigService(tmp_path / "empty.json")
        page = build_dashboard(config, adb_probe=lambda path: True)
        assert "not checked — no ADB path is configured" in joined_texts(page)
        buttons = [button.text() for button in page.findChildren(QPushButton)]
        assert not any("Check" in text for text in buttons)
        assert not any("Open Device workspace" in text for text in buttons)

    def test_saved_path_starts_untested_with_a_check_control(
            self, qapp, config_service):
        from ui_desktop.screens.dashboard import build_dashboard
        page = build_dashboard(config_service, adb_probe=lambda p: True)
        assert "not checked" in joined_texts(page)
        buttons = [button.text() for button in page.findChildren(QPushButton)]
        assert any("Check ADB availability" in text for text in buttons)

    def test_probe_success_updates_to_validated(self, qapp, config_service):
        from ui_desktop.screens.dashboard import build_dashboard
        page = build_dashboard(config_service, adb_probe=lambda p: True)
        check_button = button_of(page, "Check ADB availability")
        assert check_button is not None
        check_button.click()
        assert pump_until(
            qapp, lambda: "validated — the saved executable launches"
            in joined_texts(page) and
            "not checked" not in joined_texts(page))

    def test_probe_failure_updates_to_invalid(self, qapp, config_service):
        from ui_desktop.screens.dashboard import build_dashboard
        page = build_dashboard(config_service, adb_probe=lambda p: False)
        check_button = button_of(page, "Check ADB availability")
        assert check_button is not None
        check_button.click()
        assert pump_until(
            qapp, lambda: "invalid — the saved path did not launch"
            in joined_texts(page))

    def test_probe_error_does_not_crash_and_shows_invalid(
            self, qapp, config_service):
        from ui_desktop.screens.dashboard import build_dashboard

        def crashed(_path: str) -> bool:
            raise OSError("probe blew up")

        page = build_dashboard(config_service, adb_probe=crashed)
        check_button = button_of(page, "Check ADB availability")
        assert check_button is not None
        check_button.click()
        assert pump_until(
            qapp, lambda: "invalid — the saved path did not launch"
            in joined_texts(page))

    def test_unreadable_config_is_surfaced_truthfully(self, qapp, tmp_path):
        from ui_desktop.screens.dashboard import build_dashboard
        bad = tmp_path / "config.json"
        bad.write_text("{ not json", encoding="utf-8")
        page = build_dashboard(ConfigService(bad))
        assert "Configuration could not be read" in joined_texts(page)

    def test_open_devices_routes_to_the_workspace(self, qapp, config_service,
                                                  backend_factory):
        backend = backend_factory(config_service, FakeAdbTransport())
        window = MainWindow(config_service, backend=backend)
        try:
            open_button = button_of(
                window.content_widget("dashboard"), "Open Device workspace")
            assert open_button is not None
            open_button.click()
            assert window.current_section_id == "devices"
        finally:
            window.close()

    def test_startup_probes_nothing(self, qapp, config_service,
                                    backend_factory):
        transport = FakeAdbTransport(devices_lines=("S1 device",))
        backend = backend_factory(config_service, transport)
        window = MainWindow(config_service, backend=backend)
        try:
            assert window.current_section_id == "dashboard"
            assert probe_calls(transport) == 0
        finally:
            window.close()

    def test_dashboard_never_fabricates_devices_or_scans(
            self, qapp, config_service, backend_factory):
        backend = backend_factory(config_service, FakeAdbTransport())
        window = MainWindow(config_service, backend=backend)
        try:
            texts = joined_texts(window.content_widget("dashboard"))
            assert "devices found" not in texts
            assert "scan history" not in texts
            assert "security score" not in texts
        finally:
            window.close()


# ===========================================================================
# device workspace — discovery
# ===========================================================================

class TestDeviceDiscovery:
    def test_idle_state_probes_nothing(self, qapp, config_service,
                                       backend_factory):
        transport = FakeAdbTransport(devices_lines=("S1 device",))
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        assert probe_calls(transport) == 0
        assert "discovery has not run yet" in page._devices_banner.text()
        page.shutdown()

    def test_activation_runs_exactly_one_auto_discovery(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(devices_lines=("S1 device",))
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        assert page._devices_model.rowCount() == 1
        assert page._devices_model.serial_at(0) == "S1"
        assert probe_calls(transport) == 1
        page.activate()
        page.activate()
        assert probe_calls(transport) == 1  # never a polling loop
        page.shutdown()

    def test_zero_devices_is_a_distinct_honest_state(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(devices_lines=())
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        assert page._devices_state == "refreshed"
        assert "0 device(s) reported" in page._devices_banner.text()
        assert page._apps_button.isEnabled() is False
        page.shutdown()

    def test_refresh_failure_keeps_last_result_marked_stale(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("S1 device",), fail_devices_after=1)
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        assert page._devices_model.rowCount() == 1
        page.refresh_devices()
        assert wait_refresh_done(qapp, page)
        assert page._devices_state == "failed"
        assert page._devices_stale is True
        banner = page._devices_banner.text()
        assert "discovery failed" in banner
        assert "LAST successful result" in banner
        assert "do NOT prove the devices are still connected" in banner
        assert page._devices_model.rowCount() == 1  # last-good rows kept
        assert page._apps_button.isEnabled() is False  # stale → disabled
        page.shutdown()

    def test_refresh_failure_without_previous_result_is_honest_error(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(devices_lines=(), fail_devices_after=0)
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        page.refresh_devices()
        assert wait_refresh_done(qapp, page)
        assert page._devices_state == "failed"
        assert page._devices_stale is False
        assert "discovery failed" in page._devices_banner.text()
        assert page._devices_model.rowCount() == 0
        page.shutdown()

    def test_offline_and_unauthorized_render_verbatim(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("S1 device", "S2 offline", "S3 unauthorized"))
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        model = page._devices_model
        states = [model.index(i, 1).data() for i in range(model.rowCount())]
        assert states == ["device", "offline", "unauthorized"]
        page.shutdown()

    def test_overlapping_refresh_is_refused(self, qapp, config_service,
                                            backend_factory):
        release = threading.Event()
        transport = FakeAdbTransport(devices_lines=("S1 device",))
        original = transport.run_text
        held = threading.Event()
        wrapper_devices_calls = 0

        def held_run_text(cmd, timeout=30.0):
            nonlocal wrapper_devices_calls
            argv = tuple(str(p) for p in cmd)
            if argv[:1] == ("devices",):
                wrapper_devices_calls += 1
                if wrapper_devices_calls == 1:
                    held.set()
                    release.wait(5.0)
            return original(cmd, timeout=timeout)

        transport.run_text = held_run_text  # type: ignore[method-assign]
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        page.refresh_devices()
        assert pump_until(qapp, lambda: held.is_set())
        assert not page._refresh_button.isEnabled()
        page.refresh_devices()  # second press while pending: cannot stack
        release.set()
        assert wait_refresh_done(qapp, page)
        assert probe_calls(transport) == 1
        page.shutdown()


# ===========================================================================
# device workspace — selection
# ===========================================================================

class TestDeviceSelection:
    def _page(self, qapp, config_service, backend_factory, transport):
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        return page

    def test_single_device_is_preselected_unambiguously(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(devices_lines=("S1 device",))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        assert page.selected_serial == "S1"
        assert "selected target: S1" in page._target_banner.text()
        page.shutdown()

    def test_multiple_devices_select_nothing_implicitly(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("S1 device", "S2 device"))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        assert page.selected_serial is None
        assert page._target_banner.text() == ""
        page.shutdown()

    def test_selection_preserved_when_same_serial_remains(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("S1 device", "S2 device"))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._devices_table.selectRow(0)  # explicit user selection: S1
        assert page.selected_serial == "S1"
        page.refresh_devices()
        assert wait_refresh_done(qapp, page)
        assert page.selected_serial == "S1"  # preserved, never switched
        page.shutdown()

    def test_disappeared_device_invalidates_selection_with_truthful_note(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(devices_lines=("S1 device",))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        assert page.selected_serial == "S1"
        transport.devices_lines = ()  # the device vanished
        page.refresh_devices()
        assert wait_refresh_done(qapp, page)
        assert page.selected_serial is None
        banner = page._target_banner.text()
        assert "S1 is gone after the last refresh" in banner
        assert "nothing is auto-switched" in banner
        assert page._apps_button.isEnabled() is False
        page.shutdown()

    def test_selection_never_silently_switches_to_another_device(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("S1 device", "S2 device"))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._devices_table.selectRow(0)  # S1
        transport.devices_lines = ("S2 device",)  # S1 gone, S2 remains
        page.refresh_devices()
        assert wait_refresh_done(qapp, page)
        assert page.selected_serial is None  # invalidated, NOT switched
        page.shutdown()


# ===========================================================================
# device workspace — details (verified root tri-state)
# ===========================================================================

_GETPROPS = {
    "ro.product.manufacturer": "Google",
    "ro.product.model": "Pixel Test",
    "ro.product.brand": "google",
    "ro.build.version.release": "14",
    "ro.build.version.sdk": "34",
}


class TestDeviceDetails:
    def _page(self, qapp, config_service, backend_factory, transport):
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        return page

    def test_full_profile_renders_row_fields_and_not_rooted_verdict(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("S1 device",), getprops=dict(_GETPROPS),
            root_mode="not_rooted")
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        assert page._details_button.isEnabled()
        page._details_button.click()
        assert pump_until(qapp, lambda: page._details_model.rowCount() > 0)
        rows = {key: value for key, value in page._details_model.rows}
        assert rows["Root status"] == RootStatus.NOT_ROOTED.name
        assert rows["Model"] == "Pixel Test"
        assert rows["SDK level"] == "34"
        page.shutdown()

    def test_rooted_device_reports_verified_rooted(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("S1 device",), getprops=dict(_GETPROPS),
            root_mode="rooted")
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._details_button.click()
        assert pump_until(qapp, lambda: page._details_model.rowCount() > 0)
        rows = {key: value for key, value in page._details_model.rows}
        assert rows["Root status"] == RootStatus.ROOTED.name
        page.shutdown()

    def test_root_probe_refusal_stays_UNKNOWN_never_a_false_verdict(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("S1 device",), getprops=dict(_GETPROPS),
            root_mode="unknown")
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._details_button.click()
        assert pump_until(qapp, lambda: page._details_model.rowCount() > 0)
        rows = {key: value for key, value in page._details_model.rows}
        assert rows["Root status"] == RootStatus.UNKNOWN.name
        page.shutdown()

    def test_details_failure_is_honest_and_never_a_root_verdict(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(devices_lines=("S1 device",))
        page, backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)  # this built the registry entry
        registry = backend._registry_obj
        assert registry is not None
        registry.device_info_error = AdbCommandError(
            "device disconnected", cmd=("dumpsys",))
        page._details_button.click()
        assert pump_until(qapp, lambda: page._details_error is not None)
        banner = page._details_banner.text()
        assert "details read failed" in banner
        assert "device disconnected" in banner
        assert page._details_model.rowCount() == 0
        assert page._details_button.isEnabled()  # retry remains possible
        page.shutdown()

    def test_superseded_details_probe_is_ignored(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("S1 device", "S2 device"),
            getprops=dict(_GETPROPS))
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        held_started = threading.Event()
        release = threading.Event()
        original = transport.run_text

        def held(cmd, timeout=30.0):
            argv = tuple(str(p) for p in cmd)
            if argv[:2] == ("shell", "getprop") and not release.is_set():
                held_started.set()
                release.wait(5.0)
            return original(cmd, timeout=timeout)

        transport.run_text = held  # type: ignore[method-assign]
        page._devices_table.selectRow(0)  # S1
        assert page.selected_serial == "S1"
        page._details_button.click()
        assert pump_until(qapp, lambda: held_started.is_set())
        page._devices_table.selectRow(1)  # the user switches to S2
        assert page.selected_serial == "S2"
        release.set()  # S1's profile completes AFTER the switch
        assert pump_until(
            qapp, lambda: not page._workers.is_pending("load_details"))
        # S1's facts were NEVER applied — the target owns the panel now
        assert page._profile_serial is None
        assert page._details_model.rowCount() == 0
        page.shutdown()


# ===========================================================================
# device workspace — installed-app inventory
# ===========================================================================

def synthetic_packages(count: int) -> tuple[str, ...]:
    return tuple(f"com.vscanner.mock{i:03d}" for i in range(count))


class TestAppInventory:
    def _page(self, qapp, config_service, backend_factory, transport):
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        return page

    def test_no_selected_device_leaves_listing_disabled(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("S1 device", "S2 device"))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        assert page.selected_serial is None
        assert page._apps_button.isEnabled() is False
        page.shutdown()

    def test_offline_target_cannot_start_listing(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(devices_lines=("S1 offline",))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        assert page.selected_serial is None  # offline is never auto-target
        assert page._apps_button.isEnabled() is False
        page.shutdown()

    def test_listing_success_fills_the_model_with_service_rows(
            self, qapp, config_service, backend_factory):
        packages = synthetic_packages(160)
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=packages)
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        assert pump_until(
            qapp, lambda: page._apps_state == "result" and
            page._apps_model.rowCount() == PAGE_SIZE)
        banner = page._apps_banner.text()
        assert "160 apps" in banner
        # the inventory is EXACTLY what the shared service returned
        assert len(page._apps_rows) == 160
        assert page._apps_rows[0].package_name == packages[0]
        page.shutdown()

    def test_listing_rows_carry_honest_inferred_provenance(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",),
            third_party=("com.example.notes", "com.example.gallery"))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        assert pump_until(qapp, lambda: page._apps_state == "result")
        row0 = page._apps_rows[0]
        assert row0.label_source is AppLabelSource.HEURISTIC
        provenance = page._apps_model.index(0, 2).data()
        assert provenance == "inferred (derived)"
        assert "verified" not in joined_texts(page)  # no EXACT badge claim
        page.shutdown()

    def test_include_system_toggle_feeds_the_next_listing(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",),
            third_party=("com.example.notes",),
            system=("com.android.systemui",))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        assert pump_until(qapp, lambda: page._apps_state == "result")
        assert len(page._apps_rows) == 1  # third-party only
        assert page._apps_model.index(0, 4).data() == "3rd party"
        page._apps_system_toggle.setChecked(True)
        page._apps_button.click()
        assert pump_until(qapp, lambda: len(page._apps_rows) == 2)
        assert page._apps_rows[1].is_system is True
        assert page._apps_model.index(1, 4).data() == "system"
        page.shutdown()

    def test_search_filter_is_non_mutating_and_deterministic(
            self, qapp, config_service, backend_factory):
        packages = synthetic_packages(150)
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=packages)
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        assert pump_until(
            qapp, lambda: page._apps_state == "result" and
            page._apps_model.rowCount() == PAGE_SIZE)
        original_inventory = page._apps_rows
        page._apps_filter_input.setText("mock042")
        assert len(page.matched_rows()) == 1
        assert page.matched_rows()[0].package_name == "com.vscanner.mock042"
        assert page._apps_rows == original_inventory  # never mutated
        page._apps_filter_input.setText("does-not-match-anything")
        assert page.matched_rows() == ()
        assert "no packages match the filter" in page._apps_banner.text()
        page._apps_filter_input.clear()
        assert page._apps_model.rowCount() == PAGE_SIZE  # restored
        page.shutdown()

    def test_search_matches_labels_too(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",),
            third_party=("com.example.notes",))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        assert pump_until(qapp, lambda: page._apps_state == "result")
        label = page._apps_rows[0].label  # the derived label has tokens
        page._apps_filter_input.setText(label)
        assert len(page.matched_rows()) == 1
        page.shutdown()

    def test_pagination_boundaries_at_150_rows(
            self, qapp, config_service, backend_factory):
        packages = synthetic_packages(150)
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=packages)
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        assert pump_until(
            qapp, lambda: page._apps_state == "result" and
            page._apps_model.rowCount() == PAGE_SIZE)
        assert page._apps_model.rows[0].package_name == packages[0]
        assert page._prev_button.isEnabled() is False
        assert page._next_button.isEnabled() is True
        page._next_button.click()
        assert pump_until(qapp, lambda: page._apps_model.rowCount() == 50)
        assert page._apps_model.rows[0].package_name == packages[100]
        assert page._prev_button.isEnabled() is True
        assert page._next_button.isEnabled() is False  # last page
        page._prev_button.click()
        assert pump_until(
            qapp, lambda: page._apps_model.rowCount() == PAGE_SIZE)
        page.shutdown()

    def test_listing_failure_is_honest_with_typed_message(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=("app.example",),
            fail_listing=True)
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        assert pump_until(qapp, lambda: page._apps_state == "failed")
        assert "listing failed" in page._apps_banner.text()
        assert "timed out" in page._apps_banner.text()
        assert page._apps_model.rowCount() == 0  # no fabricated rows
        page.shutdown()

    def test_cancelled_listing_leaves_no_partial_rows(
            self, qapp, config_service, backend_factory):
        release = threading.Event()
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",),
            third_party=synthetic_packages(150),
            list_gate=release)
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        assert transport.list_started.wait(5.0)
        assert not page._cancel_button.isHidden()  # visible while running
        page._cancel_button.click()  # request recorded before the release
        release.set()
        # the plan's after-listing checkpoint acknowledges the request →
        # the job terminalizes CANCELLED deterministically
        assert pump_until(qapp, lambda: page._apps_state == "cancelled")
        banner = page._apps_banner.text()
        assert "cancelled" in banner.lower()
        assert "no partial rows" in banner
        assert page._apps_model.rowCount() == 0
        page.shutdown()

    def test_busy_listing_disables_the_start_control(
            self, qapp, config_service, backend_factory):
        release = threading.Event()
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=("app.example",),
            list_gate=release)
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        assert transport.list_started.wait(5.0)
        assert page._apps_state == "loading"
        assert page._apps_button.isEnabled() is False  # no stacked submit
        release.set()
        assert pump_until(qapp, lambda: page._apps_state == "result")
        assert page._apps_button.isEnabled() is True
        page.shutdown()

    def test_late_event_from_superseded_job_is_ignored(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=("app.example",))
        page = self._page(qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_job_id = "tracked-job"
        page._apps_job_serial = "SER1"
        stale = JobTerminalEvent(
            job_id="superseded-job", kind=JobKind.APP_LISTING,
            outcome=JobState.FAILED)
        page._on_terminal_event(stale)
        assert page._apps_state != "failed"  # foreign id: state untouched
        # a delivery whose ids match the CURRENT tracked job still applies
        fresh = JobTerminalEvent(
            job_id="tracked-job", kind=JobKind.APP_LISTING,
            outcome=JobState.SUCCEEDED,
            result=(AppInfo(package_name="com.example.app"),))
        page._on_terminal_event(fresh)
        assert page._apps_state == "result"
        assert page._apps_model.rowCount() == 1
        page.shutdown()

    def test_delivery_from_the_hub_updates_the_page_exactly_once(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",), third_party=("app.example",))
        backend = backend_factory(config_service, transport)
        bridge = QtJobEventBridge()
        bridge.attach(backend.manager())
        spy_page = make_terminal_spy()
        page = spy_page(backend, bridge.hub)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        deliveries = spy_page.deliveries
        assert pump_until(
            qapp, lambda: len(deliveries) == 1 and
            page._apps_state == "result")
        assert len(deliveries) == 1  # one job → exactly one GUI delivery
        event, delivered_on = deliveries[0]
        assert event.kind is JobKind.APP_LISTING
        assert delivered_on == GUI_THREAD  # the slot ran on the GUI thread
        page.shutdown()

    def test_window_close_detaches_bridge_and_shuts_the_manager_down(
            self, qapp, config_service, backend_factory):
        release = threading.Event()
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",),
            third_party=synthetic_packages(150),
            list_gate=release)
        backend = backend_factory(config_service, transport)
        window = MainWindow(config_service, backend=backend)
        bridge = window._job_bridge
        assert bridge is not None and bridge.attached
        window.switch_to("devices")
        page = window.content_widget("devices")
        assert isinstance(page, DeviceWorkspacePage)
        assert wait_refresh_done(qapp, page)  # discovery → S1 auto-selected
        page._apps_button.click()
        assert transport.list_started.wait(5.0)  # job held RUNNING
        handle = backend.active_listing_handle("SER1")
        assert handle is not None
        release.set()  # job terminalizes normally; no gate-dangling close
        assert pump_until(qapp, lambda: handle.state is not JobState.RUNNING)
        window.close()  # closeEvent: detach + section shutdown + shutdown
        assert bridge.attached is False
        assert window._job_bridge is None
        assert backend._manager_obj is None  # manager shut down + released

    def test_gui_thread_stays_responsive_during_listing(
            self, qapp, config_service, backend_factory):
        transport = FakeAdbTransport(
            devices_lines=("SER1 device",),
            third_party=synthetic_packages(160))
        page, _backend, _bridge = wired_page(
            qapp, config_service, backend_factory, transport)
        page.activate()
        assert wait_refresh_done(qapp, page)
        page._apps_button.click()
        heartbeats = 0
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            qapp.processEvents()
            heartbeats += 1
            time.sleep(0.02)
        assert heartbeats > 10  # the loop never starved
        assert pump_until(qapp, lambda: page._apps_state == "result")
        page.shutdown()


# ===========================================================================
# settings — Stage 10 ADB validation
# ===========================================================================

class TestSettingsValidation:
    def _dialog(self, config_service, *, adb_probe=None) -> SettingsDialog:
        return SettingsDialog(config_service, adb_probe=adb_probe)

    def test_validate_button_reports_a_valid_path(
            self, qapp, config_service):
        dialog = self._dialog(config_service, adb_probe=lambda p: True)
        assert dialog.editor_adb_path()  # prefilled from the saved config
        dialog._validate()
        assert pump_until(
            qapp, lambda: "path is valid" in dialog._validate_status.text())

    def test_validate_failure_reports_honest_failure(
            self, qapp, config_service):
        dialog = self._dialog(config_service, adb_probe=lambda p: False)
        dialog._validate()
        assert pump_until(
            qapp, lambda: "NOT" in dialog._validate_status.text())
        assert "path is NOT a launchable adb executable" in \
            dialog._validate_status.text()

    def test_empty_path_is_reported_and_never_probed(
            self, qapp, config_service):
        probed: list[str] = []

        def probe(path: str) -> bool:
            probed.append(path)
            return True

        dialog = self._dialog(config_service, adb_probe=probe)
        dialog._adb_edit.clear()
        dialog._validate()
        assert "No path entered" in dialog._validate_status.text()
        assert probed == []

    def test_probe_while_pending_is_refused_honestly(
            self, qapp, config_service):
        release = threading.Event()
        started = threading.Event()

        def blocked(_path: str) -> bool:
            started.set()
            release.wait(5.0)
            return True

        dialog = self._dialog(config_service, adb_probe=blocked)
        dialog._validate()
        assert started.wait(2.0)
        dialog._validate()  # second press while the first runs
        assert "already running" in dialog._validate_status.text()
        release.set()
        assert pump_until(
            qapp, lambda: "path is valid" in dialog._validate_status.text())
        dialog.close()


# ===========================================================================
# error translation + architecture borders
# ===========================================================================

class TestErrorTextAndArchitecture:
    def test_engine_error_text_is_concise_and_honest(self):
        err = AdbCommandError("adb devices timed out", cmd=("devices",),
                              timeout=True)
        assert engine_error_text(err) == "adb devices timed out"

    def test_unexpected_exception_is_named_not_dumped(self):
        text = engine_error_text(RuntimeError("boom-explosion"))
        assert text.startswith("RuntimeError: ")
        assert text.endswith("boom-explosion")
        assert "Traceback" not in text

    def test_desktop_screens_never_import_subprocess(self):
        desktop_root = Path(__file__).resolve().parents[2] / "ui_desktop"
        banned = {"subprocess", "adb_setup"}
        for file in desktop_root.rglob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name.split(".")[0] not in banned, \
                            f"{file.name} imports {alias.name}"
                elif isinstance(node, ast.ImportFrom) and node.module:
                    assert node.module.split(".")[0] not in banned, \
                        f"{file.name} imports {node.module}"

    def test_desktop_never_imports_the_tui(self):
        desktop_root = Path(__file__).resolve().parents[2] / "ui_desktop"
        for file in desktop_root.rglob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("ui_terminal"), \
                        f"{file.name} imports {node.module}"
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("ui_terminal"), \
                            f"{file.name} imports {alias.name}"
