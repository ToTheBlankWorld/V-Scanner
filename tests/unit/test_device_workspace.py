"""Device workspace tests (Stage 06).

Deterministic headless coverage of the workspace screen through the
injected :class:`FakeBackend` seam — no device, no subprocess, no config
file outside ``tmp_path``. Honesty behaviors pinned here (prompt §7):

* navigation/registry/palette contract for the new live section,
* explicit-refresh discovery: zero/one/many devices, missing ADB,
  command failure/timeout, stale-marked last-good after a failure,
* selection: single-device preselection, multi-device refusal to
  auto-select, offline/unauthorized refusal, invalidation on connect
  loss, preservation across refreshes,
* details: SC-4 fields, honest "unknown", root tri-state wording,
  probe failure, redaction of typed error text,
* inventory UI state: job-event driven states, badges, pagination,
  filter, foreign-job events ignored.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from textual.widgets import DataTable, Input, Label

from ui_terminal.app import VScannerApp
from ui_terminal.screens.workspace import PAGE_SIZE, DeviceWorkspaceScreen
from vscanner.core.errors import AdbCommandError, AdbNotAvailable
from vscanner.core.events import JobState, JobTerminalEvent, JobStartedEvent
from vscanner.core.models import (
    AppInfo, AppLabelSource, ConnectionInfo, DeviceProfile, DeviceState,
)
from vscanner.services.config import ConfigService


def _visible_text(node) -> str:
    return "\n".join(str(w.render().plain) for w in node.query(Label))


async def _until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met within the timeout")


def _device(serial: str, state: DeviceState = DeviceState.DEVICE,
            model: str | None = None) -> ConnectionInfo:
    props = {"raw_state": state.value}
    if model is not None:
        props["model"] = model
    return ConnectionInfo(serial=serial, state=state, usb_props=props)


def _one_device():
    return (_device("S1", model="Pixel 2"),)


def _table_values(screen, selector: str) -> str:
    """Concatenated cell text of one DataTable (cells are not Labels)."""
    table = screen.query_one(selector, DataTable)
    return " ".join(
        str(cell) for row in range(table.row_count)
        for cell in table.get_row_at(row)
    )

def _app(package: str) -> AppInfo:
    return AppInfo(package_name=package)


class FakeHandle:
    def __init__(self, job_id: str) -> None:
        self._id = job_id

    @property
    def id(self) -> str:
        return self._id

    def kind(self):
        from vscanner.core.events import JobKind
        return JobKind.APP_LISTING

    def state(self):
        from vscanner.services.jobs import JobState as JS
        return JS.SUCCEEDED

    def cancel(self) -> None:
        pass


class FakeBackend:
    """Scripted DeviceBackend for one-screen state tests (no threads beyond
    the app's own worker plumbing; no subprocess, no ADB)."""

    def __init__(self) -> None:
        # a usable saved path by default; the no-adb test overrides it
        self.saved: str | None = "C:/fake/adb.exe"
        self.devices_script: list = []   # tuple | Exception (consumed FIFO)
        self.profile_script: list = []
        self.refresh_calls = 0
        self.profile_calls: list = []
        self.start_listing_calls: list = []
        self.cancel_calls: list = []
        self.next_job_id = 0
        self.block_refresh: threading.Event | None = None
        self.pump_sinks: list = []

    # -- config surface ----------------------------------------------------- #

    def adb_path_saved(self):
        return self.saved

    # -- blocking engine calls ---------------------------------------------- #

    def list_devices(self, timeout: float = 10.0):
        self.refresh_calls += 1
        if self.block_refresh is not None:
            self.block_refresh.wait(timeout=5.0)
        outcome = self.devices_script.pop(0) if self.devices_script else ()
        if isinstance(outcome, Exception):
            raise outcome
        return tuple(outcome)

    def profile(self, serial: str):
        self.profile_calls.append(serial)
        outcome = self.profile_script.pop(0) if self.profile_script else \
            profile_unknown(serial)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    # -- jobs ---------------------------------------------------------------- #

    def start_listing_job(self, serial: str, include_system: bool):
        self.start_listing_calls.append((serial, include_system))
        self.next_job_id += 1
        return FakeHandle(f"job-{self.next_job_id}")

    def cancel_listing_job(self, serial: str) -> None:
        self.cancel_calls.append(serial)

    def active_listing_handle(self, serial: str):
        return None

    def shutdown_jobs(self) -> None:
        pass

    # -- pump ---------------------------------------------------------------- #

    def start_pump(self, sink) -> None:
        self.pump_sinks.append(sink)

    def stop_pump(self) -> None:
        pass


def profile_unknown(serial: str) -> DeviceProfile:
    """Every field honestly unknown; root tri-state UNKNOWN."""
    from vscanner.core.models import RootStatus
    return DeviceProfile(serial=serial, root_status=RootStatus.UNKNOWN)


@pytest.fixture
def config_service(tmp_path):
    return ConfigService(tmp_path / "config.json")


@pytest.fixture
def make_app(config_service):
    def _make(backend=None):
        if backend is None:
            backend = FakeBackend()
        app = VScannerApp(
            config_service=config_service, backend=backend)
        return app
    return _make


async def open_workspace(pilot) -> DeviceWorkspaceScreen:
    await pilot.press("w")
    await pilot.pause()
    screen = pilot.app.screen
    assert isinstance(screen, DeviceWorkspaceScreen)
    return screen


class TestNavigation:
    def test_devices_section_is_live_in_the_registry(self) -> None:
        from ui_terminal import sections as reg
        section = reg.get_section("devices")
        assert section.kind == "live"
        assert section.binding == "w"
        assert section.title == "Device workspace"
        assert "devices" not in {s.section_id for s in reg.future_sections()}

    async def test_w_binding_opens_the_workspace(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            await pilot.pause()
            assert type(app.screen).__name__ == "DeviceWorkspaceScreen"
            assert len(app.screen_stack) == 2
            # escape returns to the dashboard honestly
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.screen).__name__ == "DashboardScreen"

    async def test_workspace_is_cached_once(self, make_app) -> None:
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            await pilot.pause()
            workspace_id = id(app.screen)
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("w")
            await pilot.pause()
            assert id(app.screen) == workspace_id
            assert len(app.screen_stack) == 2

    async def test_palette_lists_the_workspace(self, make_app) -> None:
        from ui_terminal.app import VScannerCommands
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            provider = VScannerCommands(app.screen)
            hits = [hit async for hit in provider.search("workspace")]
            assert hits, "palette must surface the live device workspace"
            assert any("goto devices" in (h.text or "") for h in hits)


class TestDiscoveryHonesty:
    async def test_opening_runs_exactly_one_discovery_and_shows_empty(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "empty")
            assert backend.refresh_calls == 1
            text = _visible_text(screen)
            assert "no devices connected" in text

    async def test_no_adb_path_shows_guidance_and_runs_nothing(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.saved = None
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await pilot.pause()
            assert backend.refresh_calls == 0
            assert screen._discovery_state == "no-adb"
            text = _visible_text(screen)
            assert "Settings" in text
            # saving a path (fake) then a manual refresh proceeds
            backend.saved = "C:/fake/adb.exe"
            backend.devices_script = [_one_device()]
            screen.action_refresh()
            await _until(lambda: screen._discovery_state == "ok")
            assert backend.refresh_calls == 1

    async def test_multiple_devices_are_never_auto_selected(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.devices_script = [
            (_device("S1", model="Pixel 2"), _device("S2", model="Pixel 3"))]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "ok")
            assert screen._selected_serial is None
            table = screen.query_one("#ws-devices", DataTable)
            assert table.row_count == 2
            text = _visible_text(screen)
            assert "select one explicitly" in text or "nothing is selected" in text

    async def test_single_device_is_preselected_and_probed(
        self, make_app,
    ) -> None:
        from vscanner.core.models import RootStatus
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        known = DeviceProfile(
            serial="S1", mfr="Google", model="Pixel 2", android="14",
            root_status=RootStatus.UNKNOWN,
        )
        backend.profile_script = [known]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            assert backend.profile_calls == ["S1"]
            text = _visible_text(screen)
            assert "selected device: S1" in text
            await _until(lambda: screen._profile_state == "ok")
            values = _table_values(screen, "#ws-details")
            assert "Pixel 2" in values
            assert "not determined" in values

    async def test_missing_values_render_as_unknown(self, make_app) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        # unknown-everything profile (fixture default)
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._profile_state == "ok")
            table = screen.query_one("#ws-details", DataTable)
            values = [
                str(cell) for row in range(table.row_count)
                for cell in table.get_row_at(row)
            ]
            assert "unknown" in values
            assert "not determined" in " ".join(values)

    async def test_offline_rows_visible_refused_as_targets(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.devices_script = [
            (_device("OFF1", DeviceState.OFFLINE),
             _device("AUTH1", DeviceState.UNAUTHORIZED))]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "ok")
            table = screen.query_one("#ws-devices", DataTable)
            assert table.row_count == 2
            assert screen._selected_serial is None
            # direct selection attempt must be refused with feedback
            calls: list = []
            screen.notify = lambda *a, **k: calls.append(a[0])  # type: ignore[method-assign]
            screen._select_device("OFF1", announce=True)
            assert screen._selected_serial is None
            assert calls, "refusal needs explicit feedback"
            assert any("offline" in c for c in calls)
            screen._select_device("AUTH1", announce=True)
            assert screen._selected_serial is None
            assert any("unauthorized" in c for c in calls)

    async def test_unknown_state_token_stays_honest(self, make_app) -> None:
        weird = ConnectionInfo(
            serial="W1", state=DeviceState.ABSENT,
            usb_props={"raw_state": "sideload"},
        )
        backend = FakeBackend()
        backend.devices_script = [(weird,)]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "ok")
            table = screen.query_one("#ws-devices", DataTable)
            values = [str(c) for c in table.get_row_at(0)]
            assert values[0] == "W1"
            assert "sideload" in " ".join(values)

    async def test_missing_adb_binary_is_typed_failure_after_success(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "ok")
            stamp = screen._last_success
            # next refresh: binary gone
            backend.devices_script = [AdbNotAvailable("spawn failed")]
            screen.action_refresh()
            await _until(lambda: screen._discovery_state == "failed")
            text = _visible_text(screen)
            assert "discovery failed" in text
            assert "not launchable" in text
            # last-good rows remain, marked stale
            table = screen.query_one("#ws-devices", DataTable)
            assert table.row_count == 1
            assert "may be stale" in text
            assert screen._last_success is stamp

    async def test_timeout_failure_is_distinguished(self, make_app) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "ok")
            backend.devices_script = [AdbCommandError(
                "devices timed out", cmd=("adb", "devices"),
                returncode=None, stderr_excerpt="", timeout=True)]
            screen.action_refresh()
            await _until(lambda: screen._discovery_state == "failed")
            text = _visible_text(screen)
            assert "timed out" in text
            assert "exit code" not in text

    async def test_failed_stderr_excerpt_stays_redacted(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.devices_script = [
            AdbCommandError(
                "adb devices failed",
                cmd=("adb", "devices"), returncode=1,
                # R-12: the engine redacts at the error boundary
                stderr_excerpt="password=<redacted> token=<redacted>"),
        ]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "failed")
            text = _visible_text(screen)
            assert "hunter2" not in text
            assert "exit code 1" in text

    async def test_failure_then_success_recovers(self, make_app) -> None:
        from vscanner.core.errors import AdbCommandError
        backend = FakeBackend()
        backend.devices_script = [
            AdbCommandError(
                "adb devices failed", cmd=("adb", "devices"),
                returncode=1, stderr_excerpt="", timeout=False),
        ]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "failed")
            backend.devices_script = [_one_device()]
            screen.action_refresh()
            await _until(lambda: screen._discovery_state == "ok")
            assert screen.query_one("#ws-devices", DataTable).row_count == 1

    async def test_refresh_in_progress_gives_feedback_not_overlap(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        gate = threading.Event()
        backend.block_refresh = gate
        backend.devices_script = []
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "discovering")
            calls: list = []
            screen.notify = lambda *a, **k: calls.append(a[0])  # type: ignore[method-assign]
            screen.action_refresh()
            await pilot.pause()
            assert any("already running" in c for c in calls), \
                "second refresh must be refused with feedback"
            assert backend.refresh_calls == 1
            gate.set()
            await _until(lambda: screen._discovery_state == "empty")

    async def test_selection_preserved_across_refresh(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            backend.devices_script = [_one_device()]
            screen.action_refresh()
            await _until(lambda: screen._discovery_state == "ok")
            assert screen._selected_serial == "S1"

    async def test_vanished_device_invalidates_selection_safely(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            # simulate listing state pre-selection to verify cleanup
            screen._listing_state = "ok"
            screen._apps = (_app("com.a"),)
            backend.devices_script = []  # S1 gone
            screen.action_refresh()
            await _until(lambda: screen._selected_serial is None)
            assert screen._apps == ()
            assert screen._listing_state == "idle"
            text = _visible_text(screen)
            assert "no longer connected" in text or "no devices" in text

    async def test_device_turned_offline_invalidates_selection(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            backend.devices_script = [
                (_device("S1", DeviceState.OFFLINE),)]
            screen.action_refresh()
            await _until(lambda: screen._selected_serial is None)
            assert screen._apps == ()


class TestSelectionAndDetailsFlow:
    async def test_explicit_row_selection_via_enter(self, make_app) -> None:
        backend = FakeBackend()
        backend.devices_script = [
            (_device("DEV-A"), _device("DEV-B"))]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "ok")
            table = screen.query_one("#ws-devices", DataTable)
            table.focus()
            await pilot.pause()
            await pilot.press("enter")
            await _until(lambda: screen._selected_serial == "DEV-A")
            # move down and select B explicitly
            await pilot.press("down")
            await pilot.press("enter")
            await _until(lambda: screen._selected_serial == "DEV-B")
            assert backend.profile_calls == ["DEV-A", "DEV-B"]

    async def test_probe_failure_is_honest_unavailable(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.devices_script = [
            (_device("S1"), _device("S2"))]
        backend.profile_script = [AdbCommandError(
            "getprop failed", cmd=("getprop",), returncode=1,
            stderr_excerpt="", timeout=False)]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "ok")
            table = screen.query_one("#ws-devices", DataTable)
            table.focus()
            await pilot.press("enter")
            await _until(lambda: screen._profile_state == "failed")
            values = _table_values(screen, "#ws-details")
            assert "unavailable" in values
            # selection remains valid; the failure does not fabricate data
            assert screen._selected_serial == "S1"
            assert screen._profile is None

    async def test_details_before_selection_says_not_checked(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.devices_script = [
            (_device("S1"), _device("S2"))]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "ok")
            values = _table_values(screen, "#ws-details")
            assert "not checked" in values

    async def test_verified_profile_known_words_are_distinguished(
        self, make_app,
    ) -> None:
        """Confirmed negatives must read differently from missing data."""
        from vscanner.core.models import RootStatus
        backend = FakeBackend()
        backend.devices_script = [
            (_device("S1"), _device("S2"), _device("S3"))]
        # S1: every non-root field known; S2 covered by the other test
        backend.profile_script = [DeviceProfile(
            serial="S1", mfr="Google", model="Pixel 2", brand="google",
            device="walleye", hardware="walleye", build_id="OPMS",
            android="8.1.0", sdk_int=27, patch="2018-01-05",
            kernel="4.4.79", fingerprint="google/walleye/OPMS",
            bootloader="MGV96", locale="en-US", timezone="UTC",
            ip="192.168.0.10", mac="00:11:22:33:44:55",
            root_status=RootStatus.NOT_ROOTED,
        )]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "ok")
            table = screen.query_one("#ws-devices", DataTable)
            table.focus()
            await pilot.press("enter")
            await _until(lambda: screen._profile_state == "ok")
            details = screen.query_one("#ws-details", DataTable)
            values = [
                str(cell) for row in range(details.row_count)
                for cell in details.get_row_at(row)
            ]
            assert "not rooted (verified probe)" in " ".join(values)


class TestInventoryUi:
    async def test_list_requires_selection(self, make_app) -> None:
        backend = FakeBackend()
        backend.devices_script = [
            (_device("S1"), _device("S2"))]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._discovery_state == "ok")
            calls: list = []
            screen.notify = lambda *a, **k: calls.append(a[0])  # type: ignore[method-assign]
            screen.action_list_apps()
            await pilot.pause()
            assert backend.start_listing_calls == []
            assert any("select a device first" in c for c in calls)

    async def test_listing_job_lifecycle_on_screen(self, make_app) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            backend.profile_script = [profile_unknown("S1")]
            screen.action_list_apps()
            assert backend.start_listing_calls == [("S1", False)]
            assert screen._listing_state == "running"
            job_id = screen._listing_job_id
            assert job_id is not None
            assert job_id == "job-1"
            # started event keeps it honest
            screen.on_job_event(JobStartedEvent(job_id=job_id))
            assert screen._listing_state == "running"
            # terminal success fills honest rows + badges
            rows = tuple(
                AppInfo(
                    package_name=f"com.dev.app{i}",
                    label_source=AppLabelSource.HEURISTIC,
                )
                for i in range(3)
            )
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id, outcome=JobState.SUCCEEDED, result=rows))
            assert screen._listing_state == "ok"
            assert screen.query_one("#ws-apps", DataTable).row_count == 3
            values = _table_values(screen, "#ws-apps")
            assert "derived (heuristic)" in values
            text = _visible_text(screen)
            assert "3 apps" in text
            assert "100 per page" in text

    async def test_terminal_failed_and_cancelled_states(
        self, make_app,
    ) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            screen.action_list_apps()
            job_id = screen._listing_job_id
            assert job_id is not None
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id, outcome=JobState.CANCELLED))
            assert screen._listing_state == "cancelled"
            assert "cancelled" in _visible_text(screen)

            # next run fails with a typed error message
            screen.action_list_apps()
            job_id2 = screen._listing_job_id
            assert job_id2 is not None
            from vscanner.core.errors import AdbCommandError
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id2, outcome=JobState.FAILED,
                error=AdbCommandError(
                    "pm list failed", cmd=("pm",), returncode=1,
                    stderr_excerpt="", timeout=False)))
            assert screen._listing_state == "failed"
            text = _visible_text(screen)
            assert "app listing failed" in text
            assert "pm list failed" in text

    async def test_foreign_job_events_are_ignored(self, make_app) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            screen.on_job_event(JobTerminalEvent(
                job_id="not-my-job", outcome=JobState.SUCCEEDED,
                result=(_app("com.a"),)))
            assert screen._apps == ()
            assert screen._listing_state == "idle"

    async def test_filter_and_pagination(self, make_app) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            size = PAGE_SIZE * 2 + 50  # 3 pages
            rows = tuple(
                AppInfo(
                    package_name=(f"com.alpha.app{i}" if i % 2
                                  else f"com.beta.app{i}"),
                    label_source=AppLabelSource.HEURISTIC,
                )
                for i in range(size)
            )
            screen.action_list_apps()
            assert screen._listing_job_id is not None
            screen.on_job_event(JobTerminalEvent(
                job_id=screen._listing_job_id,
                outcome=JobState.SUCCEEDED, result=rows))
            text = _visible_text(screen)
            assert f"{size} apps" in text
            assert "page 1/3" in text
            # next page / prev page keys
            await pilot.press("]")
            await pilot.pause()
            assert "page 2/3" in _visible_text(screen)
            screen.action_next_page()
            assert "page 3/3" in _visible_text(screen)
            calls: list = []
            screen.notify = lambda *a, **k: calls.append(a[0])  # type: ignore[method-assign]
            screen.action_next_page()
            assert any("last page" in c for c in calls)
            # filter narrows and resets pagination
            screen.query_one("#ws-filter", Input).value = "alpha"
            await pilot.pause()
            assert screen._filter_text == "alpha"
            filtered = screen._filtered_apps()
            assert all("alpha" in r.package_name for r in filtered)
            assert len(filtered) < size

    async def test_system_apps_toggle_re_lists(self, make_app) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            screen.action_toggle_system()
            await pilot.pause()
            assert backend.start_listing_calls[-1] == ("S1", True)
            screen.action_toggle_system()
            await pilot.pause()
            assert backend.start_listing_calls[-1] == ("S1", False)

    async def test_cancel_binding_hits_backend(self, make_app) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            screen.action_list_apps()
            screen.action_cancel_listing()
            assert backend.cancel_calls == ["S1"]


class TestAwayReconciliation:
    async def test_lost_result_is_reported_honestly(self, make_app) -> None:
        backend = FakeBackend()
        backend.devices_script = [_one_device()]
        app = make_app(backend)
        async with app.run_test() as pilot:
            screen = await open_workspace(pilot)
            await _until(lambda: screen._selected_serial == "S1")
            screen.action_list_apps()
            assert screen._listing_state == "running"
            # leave without the terminal event ever arriving
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("w")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DeviceWorkspaceScreen)
            assert screen._listing_state == "away"
            text = _visible_text(screen)
            assert "could not be streamed here" in text
