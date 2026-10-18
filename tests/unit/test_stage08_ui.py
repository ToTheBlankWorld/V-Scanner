"""Stage 08 TUI screens: monitoring / forensics / mirroring / demo + the
workspace admin surface.

Deterministic headless coverage through the injected fake backend (the
Stage 06 pattern extended with the Stage 08 protocol surface — no device,
no subprocess, no config file outside ``tmp_path``). Honesty behaviors
pinned here:

* monitoring: honest observation wording (NOT_OBSERVED is never "not in
  use"), snapshot table rows, foreign-job filtering, one-shot sensor rows
  including the explicit unavailable-reason row (R-04),
* forensics: verified tri-state root with evidence (R-05), case ops as
  jobs, WiFi cleartext double-confirm with the exact typed phrase (R-12)
  whose token goes to the SERVICE gate (R-13),
* workspace admin: app-row selection, exact package re-entry modal,
  confirmation token reference, honest OperationResult rendering,
* mirroring: ToolNotValidated refusal surfaces verbatim (SC-8),
* demo: unmissable DEMO banner, deterministic rows, zero device contact.
"""

from __future__ import annotations

from typing import Optional

import pytest
from textual.widgets import Input, Label

from ui_terminal.app import VScannerApp
from ui_terminal.screens.monitoring import LiveMonitoringScreen
from ui_terminal.screens.mirroring import MirroringScreen
from ui_terminal.screens.demo import DemoScreen
from ui_terminal.screens.forensics import CleartextAckModal, ForensicsScreen
from ui_terminal.screens.workspace import DeviceWorkspaceScreen
from vscanner.core.errors import ToolNotValidated
from vscanner.core.events import (
    JobState,
    JobSnapshotStreamEvent,
    JobTerminalEvent,
)
from vscanner.core.models import (
    CaseManifest,
    DeviceProfile,
    FileRecord,
    HardwareUsageSnapshot,
    MirrorHandle,
    MirrorOptions,
    ObservationState,
    OperationResult,
    RootStatus,
    SensorReading,
    SensorStatus,
)
from vscanner.services.config import ConfigService

from test_device_workspace import (
    FakeHandle,
    _one_device,
    _table_values,
    _until,
)


class Stage08Backend:
    """Fake DeviceBackend extended with the Stage 08 surface (composed on
    the Stage 06 scripted fake pattern; flat test imports)."""

    def __init__(self) -> None:
        self.saved: Optional[str] = "C:/fake/adb.exe"
        self.devices_script: list = []
        self.profile_script: list = []
        self.refresh_calls = 0
        self.profile_calls: list = []
        self.next_job_id = 0

        # stage 08 scripted surfaces
        self.root_calls: list = []
        self.root_answers: list = []          # (word, evidence) | Exception
        self.sensor_answers: list = []        # rows tuple | Exception
        self.monitor_starts: list = []
        self.monitor_stops: list = []
        self.monitor_active: Optional[FakeHandle] = None
        self.admin_calls: list = []           # (op, package, confirmation)
        self.forensics_calls: list = []       # (op, kwargs)
        self.mirror_launch_calls: list = []
        self.mirror_launch_script: list = []
        self.mirror_stopped: list = []
        self.demo_built = 0
        self.full_info_calls: list = []
        self.full_info_script: list = []
        self._launched: list = []

    # -- shared config/discovery surface (same contract as Stage 06) ------- #

    def adb_path_saved(self):
        return self.saved

    def list_devices(self, timeout: float = 10.0):
        self.refresh_calls += 1
        outcome = self.devices_script.pop(0) if self.devices_script else \
            _one_device()
        if isinstance(outcome, Exception):
            raise outcome
        return tuple(outcome)

    def profile(self, serial: str):
        self.profile_calls.append(serial)
        outcome = self.profile_script.pop(0) if self.profile_script else \
            DeviceProfile(serial=serial)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def full_device_info(self, serial: str):
        self.full_info_calls.append(serial)
        outcome = self.full_info_script.pop(0) if self.full_info_script else \
            DeviceProfile(serial=serial, root_status=RootStatus.NOT_ROOTED)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def start_listing_job(self, serial: str, include_system: bool):
        self.next_job_id += 1
        return FakeHandle(f"job-{self.next_job_id}")

    def cancel_listing_job(self, serial: str) -> None:
        pass

    def active_listing_handle(self, serial: str):
        return None

    def shutdown_jobs(self) -> None:
        pass

    def start_pump(self, sink) -> None:
        pass

    def stop_pump(self) -> None:
        pass

    # -- stage 08 surface ---------------------------------------------------- #

    def root_status_now(self, serial: str):
        self.root_calls.append(serial)
        outcome = self.root_answers.pop(0) if self.root_answers else (
            "unknown", ("probe unavailable in fixture",))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def read_sensors_once(self, serial: str):
        outcome = self.sensor_answers.pop(0) if self.sensor_answers else ()
        if isinstance(outcome, Exception):
            raise outcome
        return tuple(outcome)

    def start_monitoring_session(self, serial: str, interval_s: float):
        self.monitor_starts.append((serial, interval_s))
        self.next_job_id += 1
        handle = FakeHandle(f"job-{self.next_job_id}")
        self.monitor_active = handle
        return handle

    def stop_monitoring(self, serial: str) -> None:
        self.monitor_stops.append(serial)
        self.monitor_active = None

    def active_monitoring_handle(self, serial: str):
        return self.monitor_active

    def start_admin_job(self, serial: str, op: str, package: str,
                        confirmation):
        self.admin_calls.append((op, package, confirmation))
        self.next_job_id += 1
        return FakeHandle(f"job-{self.next_job_id}")

    def start_forensics_job(self, serial: str, op: str, kwargs: Optional[dict]):
        self.forensics_calls.append((op, dict(kwargs or {})))
        self.next_job_id += 1
        return FakeHandle(f"job-{self.next_job_id}")

    def forensics_load_case(self, case_id: str):
        return CaseManifest(case_id=case_id)

    def start_demo_job(self):
        self.next_job_id += 1
        return FakeHandle(f"job-{self.next_job_id}")

    def demo_bundle(self):
        from vscanner.services.demo import DemoService

        self.demo_built += 1
        return DemoService().scan()

    def mirror_launch(self, serial: str, options: MirrorOptions):
        self.mirror_launch_calls.append((serial, options))
        outcome = self.mirror_launch_script.pop(0) if \
            self.mirror_launch_script else MirrorHandle(
                pid=4242, serial=serial)
        if isinstance(outcome, Exception):
            raise outcome
        self._launched.append(outcome)
        return outcome

    def mirror_list(self, serial):
        # mirrors the engine registry shape: launched handles list back
        return tuple(self._launched)

    def mirror_stop(self, serial, pid: Optional[int] = None):
        self.mirror_stopped.append((serial, pid))
        return (4242,)


def _label_text(screen, selector: str) -> str:
    label = screen.query_one(selector, Label)
    rendered = label.render()
    return str(getattr(rendered, "plain", rendered))


def _capture_notify(screen):
    """Replace notify with a captured list of first-argument messages."""
    notes: list = []
    original = screen.notify

    def capture(message, title="", severity="", **kwargs):  # type: ignore[misc]
        notes.append(str(message))
        return original(message, title=title, severity=severity, **kwargs)

    screen.notify = capture  # type: ignore[method-assign]
    return notes


@pytest.fixture
def config_service(tmp_path):
    return ConfigService(tmp_path / "config.json")


@pytest.fixture
def make_app(config_service):
    def _make(backend):
        return VScannerApp(config_service=config_service, backend=backend)
    return _make


# =============================================================================
# monitoring
# =============================================================================

class TestMonitoringScreen:
    async def test_opening_is_honest_before_any_poll(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            assert isinstance(app.screen, LiveMonitoringScreen)
            body_text = _table_values(app.screen, "#mon-usage")
            assert "no snapshot yet" in body_text
            sensor_text = _table_values(app.screen, "#mon-sensors")
            assert "one honest read" in sensor_text
            # one explicit discovery on open (same rule as the workspace)
            assert backend.refresh_calls == 1

    async def test_snapshot_rows_never_claim_inactivity(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, LiveMonitoringScreen)
            await _until(lambda: screen._selected_serial == "S1")
            # start the poll session through the honest UI trigger
            await pilot.press("m")
            await _until(lambda: screen._poll_state == "running")
            assert backend.monitor_starts == [("S1", 2.0)]
            snapshot = HardwareUsageSnapshot(
                camera=ObservationState.OBSERVED_ACTIVE,
                microphone=ObservationState.NOT_OBSERVED,
                location=ObservationState.UNKNOWN,
                evidence=(("camera", "camera client 0 active"),),
                serial="S1",
            )
            job = screen._poll_job_id
            assert job is not None
            screen.on_job_event(JobSnapshotStreamEvent(
                job_id=job, payload=snapshot))
            await _until(lambda: screen._poll_count == 1)
            usage = _table_values(screen, "#mon-usage")
            assert "OBSERVED ACTIVE" in usage
            assert "camera client 0 active" in usage
            # THE honesty rule: NOT_OBSERVED is worded as a non-claim
            assert "not observed in this poll" in usage
            assert "not in use" not in usage
            # foreign snapshot ids are ignored (stale/other jobs)
            screen.on_job_event(JobSnapshotStreamEvent(
                job_id="other", payload=snapshot))
            assert screen._poll_count == 1
            # terminal cancel -> honest stopped state
            screen.on_job_event(JobTerminalEvent(
                job_id=job, outcome=JobState.CANCELLED))
            await _until(lambda: screen._poll_state == "stopped")
            poll_label = _label_text(screen, "#mon-poll")
            assert "stopped by request" in poll_label

    async def test_failed_start_and_stop_requested_semantics(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, LiveMonitoringScreen)
            await _until(lambda: screen._selected_serial == "S1")
            notes = _capture_notify(app)
            # no device selected: honest refusal, no job
            screen._selected_serial = None
            await pilot.press("m")
            await pilot.pause()
            assert backend.monitor_starts == []
            assert any("select a device first" in note for note in notes)
            # restore and start, then stop
            screen._selected_serial = "S1"
            await pilot.press("m")
            await _until(lambda: screen._poll_state == "running")
            await pilot.press("m")     # toggle -> stop request
            await pilot.pause()
            assert backend.monitor_stops == ["S1"]

    async def test_sensors_once_shows_unavailable_reason_row(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, LiveMonitoringScreen)
            backend.sensor_answers.append((
                SensorReading(
                    name="(no sensor rows)", status=SensorStatus.UNAVAILABLE,
                    reason="device reported no parseable sensor values",
                ),
            ))
            await _until(lambda: screen._selected_serial == "S1")
            await pilot.press("v")
            await _until(lambda: screen._sensor_state == "ok")
            sensors = _table_values(screen, "#mon-sensors")
            assert "unavailable" in sensors
            assert "device reported no parseable sensor values" in sensors


# =============================================================================
# forensics
# =============================================================================

class TestForensicsScreen:
    async def test_root_tri_state_with_evidence_and_honest_no_case(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        backend.root_answers = [
            ("not-rooted", (
                "su unavailable to ADB shell and no root manager package "
                "installed → not-rooted (for the ADB-shell context)",))]
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ForensicsScreen)
            await _until(lambda: screen._root_state == "probed")
            root_label = _label_text(screen, "#fx-root")
            assert ("root status: not-rooted" in root_label)
            assert "never 'assumed root'" in root_label
            evidence = _table_values(screen, "#fx-evidence")
            assert "ADB-shell context" in evidence
            case_label = _label_text(screen, "#fx-case")
            assert "no case open" in case_label

    async def test_new_case_runs_as_job_and_manifest_renders(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("o")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ForensicsScreen)
            await _until(lambda: screen._selected_serial == "S1")
            await pilot.press("n")
            await pilot.pause()
            inp = screen.query_one("#fx-input", Input)
            inp.value = "case_one"
            await pilot.press("enter")
            await _until(lambda: screen._job_state == "running")
            op, kwargs = backend.forensics_calls[0]
            assert op == "create_case"
            assert kwargs["case_name"] == "case_one"
            manifest = CaseManifest(
                case_id="case_one",
                extractions=(("extract:app", "2/3 files copied"),),
                files=(FileRecord(
                    source_path="/data/data/app/db",
                    case_relative_path="app_databases/db",
                    sha256="ab" * 32, byte_count=99,
                ),),
            )
            job = screen._job_id
            assert job is not None

            screen.on_job_event(JobTerminalEvent(
                job_id=job, outcome=JobState.SUCCEEDED, result=manifest))
            await _until(lambda: screen._job_state == "done")
            case_label = _label_text(screen, "#fx-case")
            assert "case case_one" in case_label
            assert "1 file(s)" in case_label
            files = _table_values(screen, "#fx-files")
            assert "ab" * 6 in files and "99" in files
            ops = _table_values(screen, "#fx-operations")
            assert "2/3 files copied" in ops

    async def test_wifi_cleartext_requires_exact_typed_phrase(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("o")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ForensicsScreen)
            await _until(lambda: screen._selected_serial == "S1")
            notes = _capture_notify(app)
            # no case open yet: honest refusal without a modal
            screen.action_wifi_cleartext()
            await pilot.pause()
            assert backend.forensics_calls == []
            assert any("open or create a case first" in note
                       for note in notes)
            # create the case state, then run op 6 twice (wrong + exact)
            screen._manifest = CaseManifest(case_id="case_one")
            screen.action_wifi_cleartext()
            await _until(lambda: isinstance(app.screen, CleartextAckModal))
            await pilot.pause()
            inp = app.screen.query_one("#ack-input", Input)
            inp.value = "i accept"     # wrong casing
            await pilot.press("enter")
            await _until(lambda: not isinstance(app.screen, CleartextAckModal))
            assert backend.forensics_calls == [], \
                "a mismatched acknowledgement must dispatch nothing"
            assert any("nothing was written" in note for note in notes)

            screen.action_wifi_cleartext()
            await _until(lambda: isinstance(app.screen, CleartextAckModal))
            await pilot.pause()
            inp = app.screen.query_one("#ack-input", Input)
            inp.value = "I ACCEPT CLEARTEXT PSK"
            await pilot.press("enter")
            await _until(lambda: len(backend.forensics_calls) == 1)
            op, kwargs = backend.forensics_calls[0]
            assert op == "wifi_cleartext"
            confirmation = kwargs["confirmation"]
            assert confirmation.reference == "wifi_cleartext_psk"
            assert confirmation.confirmed_at.tzinfo is not None, \
                "R-13: the token must be timezone-aware UTC"
            # the plan's copy keeps the token; the service gate re-validates
            assert kwargs["case_id"] == "case_one"

    async def test_digit_op_without_case_refused_with_notify(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("o")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ForensicsScreen)
            notes = _capture_notify(app)
            await pilot.press("2")
            await pilot.pause()
            assert backend.forensics_calls == []
            assert any("open or create a case first" in note
                       for note in notes)

    async def test_open_case_worker_loads_saved_manifest(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("o")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ForensicsScreen)
            await pilot.press("o")
            await pilot.pause()
            inp = screen.query_one("#fx-input", Input)
            inp.value = "case_two"
            await pilot.press("enter")
            await _until(lambda: screen._manifest is not None)
            assert screen._manifest is not None
            assert screen._manifest.case_id == "case_two"


# =============================================================================
# mirroring / demo
# =============================================================================

class TestMirroringScreen:
    async def test_tool_not_validated_is_surfaced_verbatim(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        backend.mirror_launch_script = [
            ToolNotValidated(
                "scrcpy exists but its launch probe failed; "
                "re-validate in Settings before mirroring")]
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("i")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, MirroringScreen)
            await _until(lambda: screen._selected_serial == "S1")
            await pilot.press("l")
            await _until(lambda: screen._mirror_state == "refused")
            status = _label_text(screen, "#mirror-status")
            assert "REFUSED" in status
            assert "re-validate in Settings" in status

    async def test_successful_launch_lists_handles_and_stops(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("i")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, MirroringScreen)
            await _until(lambda: screen._selected_serial == "S1")
            await pilot.press("l")
            await _until(lambda: screen._mirror_state == "idle" and
                         backend.mirror_launch_calls)
            serial, options = backend.mirror_launch_calls[0]
            assert serial == "S1"
            assert options.turn_screen_off is False, \
                "the plain launch route must not mutate the device screen"
            await _until(lambda: "4242" in
                         _table_values(screen, "#mr-handles"))
            handles = _table_values(screen, "#mr-handles")
            assert "running" in handles
            await pilot.press("k")
            await _until(lambda: backend.mirror_stopped == [("S1", None)])


class TestDemoScreen:
    async def test_demo_banner_is_unmissable_and_rows_render(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DemoScreen)
            banner = _label_text(screen, "#demo-banner")
            assert "DEMO DATA" in banner
            assert "no device was contacted" in banner
            await _until(lambda: screen._demo_state == "ready")
            assert backend.demo_built == 1
            summary = _label_text(screen, "#demo-summary")
            assert "demo flag: True" in summary
            rows = _table_values(screen, "#demo-findings")
            assert "[DEMO]" in rows
            assert "INFO" in rows

    async def test_regenerate_rebuilds_the_same_fixture(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("b")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DemoScreen)
            await _until(lambda: screen._demo_state == "ready")
            await pilot.press("r")
            await pilot.pause()
            await _until(lambda: backend.demo_built == 2)
            assert screen._demo_state == "ready"


# =============================================================================
# workspace admin (u/l/k + R-13 re-entry modal)
# =============================================================================

class TestWorkspaceAdmin:
    async def test_admin_keys_require_app_row_selection(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("w")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DeviceWorkspaceScreen)
            notes = _capture_notify(app)
            screen._selected_serial = "S1"
            await pilot.press("u")
            await pilot.pause()
            assert backend.admin_calls == []
            assert any("select an app row first" in note for note in notes)

    async def test_uninstall_requires_exact_package_reentry(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("w")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DeviceWorkspaceScreen)
            screen._selected_serial = "S1"
            screen._selected_package = "com.example.app"
            # WRONG text: dispatched nothing
            screen.action_uninstall()
            await _until(lambda: type(app.screen).__name__
                         == "AdminConfirmModal")
            await pilot.pause()
            inp = app.screen.query_one("#admin-input", Input)
            inp.value = "com.example.app2"
            await pilot.press("enter")
            await _until(lambda: type(app.screen).__name__
                         != "AdminConfirmModal")
            assert backend.admin_calls == []

            # exact text: job carries a fresh timezone-aware token
            screen.action_uninstall()
            await _until(lambda: type(app.screen).__name__
                         == "AdminConfirmModal")
            await pilot.pause()
            inp = app.screen.query_one("#admin-input", Input)
            inp.value = "com.example.app"
            await pilot.press("enter")
            await _until(lambda: backend.admin_calls)
            op, package, confirmation = backend.admin_calls[0]
            assert op == "uninstall_app"
            assert package == "com.example.app"
            assert confirmation.reference == (
                "admin:uninstall_app:com.example.app")
            assert confirmation.confirmed_at.tzinfo is not None

            job = screen._admin_job_id
            assert job is not None
            screen.on_job_event(JobTerminalEvent(
                job_id=job, outcome=JobState.SUCCEEDED,
                result=OperationResult(
                    ok=True, adb_returncode=0, message="Success")))
            await _until(lambda: screen._admin_state == "ok")
            banner = _label_text(screen, "#ws-admin-banner")
            assert "ok=True" in banner

    async def test_launch_and_forcestop_map_to_service_ops(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("w")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DeviceWorkspaceScreen)
            screen._selected_serial = "S1"
            screen._selected_package = "com.example.app"

            async def typed_dispatch(action: str, text: str) -> None:
                getattr(screen, f"action_{action}")()
                await _until(lambda: type(app.screen).__name__
                             == "AdminConfirmModal")
                await pilot.pause()
                inp = app.screen.query_one("#admin-input", Input)
                inp.value = text
                await pilot.press("enter")
                await _until(lambda: type(app.screen).__name__
                             != "AdminConfirmModal")
                await pilot.pause()

            await typed_dispatch("force_stop", "com.example.app")
            assert backend.admin_calls[-1][0] == "force_stop_app"
            await typed_dispatch("launch", "com.example.app")
            assert backend.admin_calls[-1][0] == "launch_app"

    async def test_full_info_worker_fills_verified_root(
        self, make_app,
    ) -> None:
        backend = Stage08Backend()
        backend.devices_script = [_one_device()]
        backend.full_info_script = [DeviceProfile(
            serial="S1", model="Pixel 2", board="walleye",
            root_status=RootStatus.NOT_ROOTED)]
        app = make_app(backend)
        async with app.run_test() as pilot:
            await pilot.press("w")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DeviceWorkspaceScreen)
            screen._select_device("S1", announce=False)
            await _until(lambda: screen._profile_state == "ok")
            await pilot.press("f")
            await _until(lambda: screen._profile_state == "full")
            assert backend.full_info_calls == ["S1"]
            details = _table_values(screen, "#ws-details")
            assert "walleye" in details
            assert (
                "not-rooted (verified probe: no su, no manager package)"
                in details
            )
