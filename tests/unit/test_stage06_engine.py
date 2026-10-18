"""Stage 06 engine additions (narrow, contract-compatible).

* ``PackageInventoryService.list_app_rows`` — SC-2 row shape with recorded
  honest ``label_source``, without one dumpsys per package.
* ``app_listing_rows_plan`` — job plan over those rows; progress event;
  cancellation boundary before the listing command.
* ``ServiceRegistry.device_info`` — narrow SC-4 accessor composition.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vscanner.core.errors import AdbCommandError  # noqa: E402
from vscanner.core.models import AppLabelSource, DeviceState  # noqa: E402
from vscanner.core.events import JobKind, JobState  # noqa: E402
from vscanner.services.jobs import JobManager  # noqa: E402
from vscanner.services.orchestration import app_listing_rows_plan  # noqa: E402
from vscanner.services.scanning.app_inventory import (  # noqa: E402
    PackageInventoryService,
)


class FakeTransport:
    """Replays scripted ADB results keyed by the joined command tail."""

    def __init__(self, responses: dict) -> None:
        self.received: list = []
        self._responses = responses

    def run_bytes(self, cmd, timeout: float = 30.0) -> bytes:  # pragma: no cover
        raise AssertionError("byte mode is not used by Stage 06 flows")

    def run_text(self, cmd, timeout: float = 30.0):
        self.received.append(tuple(str(part) for part in cmd))
        key = " ".join(str(part) for part in cmd)
        handler = self._responses[key]
        if isinstance(handler, Exception):
            raise handler
        return handler


@dataclass
class _RESULT:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

THIRD_PARTY = "package:com.example.alpha\npackage:org.fdroid.fdroid\npackage:net.b2.b3\n"
SYSTEM = "package:com.android.systemui\npackage:android\n"
ALL = SYSTEM + THIRD_PARTY


def _fixture(responses: dict):
    transport = FakeTransport(responses)
    return PackageInventoryService(transport), transport


class TestListAppRows:
    def test_third_party_rows_are_heuristic_sourced(self) -> None:
        service, transport = _fixture({"shell pm list packages -3": _RESULT(
            stdout=THIRD_PARTY, stderr="", returncode=0)})
        rows = service.list_app_rows(include_system=False)
        assert [r.package_name for r in rows] == [
            "com.example.alpha", "org.fdroid.fdroid", "net.b2.b3",
        ]
        for row in rows:
            assert row.label_source is AppLabelSource.HEURISTIC
            assert row.label == row.package_name.split(".")[-1].title()
        # never one dumpsys per package: exactly one command was run
        assert len(transport.received) == 1

    def test_non_canonical_framework_name_is_listed_not_dropped(self) -> None:
        """Real devices report ``package:android``; the strict AppInfo
        validator rejects it. The listing reflects reality (tolerant row)
        instead of crashing or silently hiding it."""
        service, transport = _fixture({
            "shell pm list packages": _RESULT(stdout=ALL, stderr="", returncode=0),
            "shell pm list packages -s": _RESULT(stdout=SYSTEM, stderr="", returncode=0),
        })
        rows = service.list_app_rows(include_system=True)
        names = [r.package_name for r in rows]
        assert "android" in names

    def test_include_system_marks_system_rows_from_the_s_set(self) -> None:
        service, transport = _fixture({
            "shell pm list packages": _RESULT(stdout=ALL, stderr="", returncode=0),
            "shell pm list packages -s": _RESULT(stdout=SYSTEM, stderr="", returncode=0),
        })
        rows = service.list_app_rows(include_system=True)
        systems = {r.package_name for r in rows if r.is_system}
        assert systems == {"com.android.systemui", "android"}
        third = {r.package_name for r in rows if not r.is_system}
        assert "com.example.alpha" in third

    def test_command_failure_raises_typed_error(self) -> None:
        service, transport = _fixture({"shell pm list packages -3": _RESULT(
            stdout="", stderr="boom (secret)", returncode=1)})
        with pytest.raises(AdbCommandError) as excinfo:
            service.list_app_rows()
        # redaction applied at the engine boundary, never fabricated success
        assert "boom" in (excinfo.value.stderr_excerpt or excinfo.value.message) or \
            excinfo.value.returncode == 1

    def test_empty_listing_is_honest_empty(self) -> None:
        service, transport = _fixture({"shell pm list packages -3": _RESULT(
            stdout="list of devices attached\n", stderr="", returncode=0)})
        rows = service.list_app_rows()
        assert rows == ()

    def test_exact_first_mode_does_not_claim_exact_labels(self) -> None:
        service, transport = _fixture({"shell pm list packages -3": _RESULT(
            stdout=THIRD_PARTY, stderr="", returncode=0)})
        rows = service.list_app_rows(label_mode="exact-first")
        assert all(r.label_source is AppLabelSource.HEURISTIC for r in rows)


class TestListingRowsPlan:
    def test_plan_returns_rows_and_emits_one_honest_progress(self) -> None:
        service, transport = _fixture({"shell pm list packages -3": _RESULT(
            stdout=THIRD_PARTY, stderr="", returncode=0)})
        plan = app_listing_rows_plan(service, include_system=False)

        seen: dict = {}
        manager = JobManager(max_workers=1)

        def subscriber(event):
            from vscanner.core.events import (
                JobProgressEvent, JobTerminalEvent,
            )
            if isinstance(event, JobProgressEvent):
                seen.setdefault("progress", []).append(event)
            if isinstance(event, JobTerminalEvent):
                seen["terminal"] = event

        stop = manager.subscribe(subscriber)
        try:
            handle = manager.submit(JobKind.APP_LISTING, device_serial="fake",
                                    plan=plan)
            final = handle.wait(timeout=5.0)
            assert final is JobState.SUCCEEDED
            result_rows = seen["terminal"].result
            assert len(result_rows) == 3
            assert [r.package_name for r in result_rows] == [
                "com.example.alpha", "org.fdroid.fdroid", "net.b2.b3",
            ]
            progress = seen.get("progress", [])
            assert any(p.unit == "apps" and p.current == 3 for p in progress)
        finally:
            stop()
            manager.shutdown()

    def test_cancel_before_listing_means_cancelled_terminal(self) -> None:
        service, transport = _fixture({"shell pm list packages -3": _RESULT(
            stdout=THIRD_PARTY, stderr="", returncode=0)})
        plan = app_listing_rows_plan(service, include_system=False)
        manager = JobManager(max_workers=1)
        try:
            handle = manager.submit(JobKind.APP_LISTING, device_serial="fake",
                                    plan=plan)
            handle.cancel()
            final = handle.wait(timeout=5.0)
            assert final is JobState.CANCELLED
            # the listing command never ran (cancellation before the command)
            assert transport.received == []
        finally:
            manager.shutdown()


class TestRegistryDeviceInfo:
    def test_device_info_is_bound_to_the_requested_serial(self) -> None:
        from vscanner.services.registry import ServiceRegistry
        from vscanner.services.adb.device_info import DeviceInfoService

        registry = ServiceRegistry("C:/fake/adb.exe")
        probe = registry.device_info("dev1")
        assert isinstance(probe, DeviceInfoService)
        assert registry.client("dev1").serial == "dev1"

    def test_registry_rejects_unusable_state_on_select(self) -> None:
        from vscanner.services.registry import ServiceRegistry
        from vscanner.services.adb.devices import DeviceDiscoveryService

        offline = (
            "list of devices attached\n"
            "serialA offline\n"
            "serialB device\n"
        )
        registry = ServiceRegistry("C:/fake/adb.exe")
        fake = FakeTransport({"devices": _RESULT(
            stdout=offline, stderr="", returncode=0)})
        registry._discovery = DeviceDiscoveryService(fake)
        with pytest.raises(Exception) as excinfo:
            registry.select_device("serialA")
        assert getattr(excinfo.value, "details", {}).get("serial") == "serialA"
        identity = registry.select_device("serialB")
        assert identity.serial == "serialB"
        assert registry.selected_serial == "serialB"
        assert registry.client().serial == "serialB"
        # the state word for an offline device stays honestly offline
        devices = registry.list_devices()
        states = {d.serial: d.state for d in devices}
        assert states["serialA"] is DeviceState.OFFLINE
