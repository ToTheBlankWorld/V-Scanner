"""ADB service tests (Stage 03, SC-1/SC-7 + R-07/R-10 groundwork evidence)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap

import pytest

from vscanner.core.errors import AdbCommandError, AdbNotAvailable, DeviceNotConnected, DeviceUnauthorized
from vscanner.core.models import DeviceState
from vscanner.services.adb.client import SubprocessAdbClient, build_adb_command
from vscanner.services.adb.devices import parse_adb_devices_output, actionable_serials, DeviceDiscoveryService
from vscanner.services.adb.device_info import DeviceInfoService
from vscanner.services.adb.executable import check_adb_valid, resolve_adb_launch_path
from vscanner.services.registry import ServiceRegistry


ADB_DEVICES_OK = (
    "List of devices attached\n"
    "demo123=device\n"
    "demo456\toffline\n"
    "demo789\tunauthorized\n"
    "\n"
)


class TestDevicesParsing:
    def test_header_and_noise_skipped(self):
        devices = parse_adb_devices_output(ADB_DEVICES_OK)
        assert [d.serial for d in devices] == ["demo123", "demo456", "demo789"]

    def test_state_tokens_mapped(self):
        devices = parse_adb_devices_output(ADB_DEVICES_OK)
        by_serial = {d.serial: d for d in devices}
        assert by_serial["demo123"].state is DeviceState.DEVICE
        assert by_serial["demo456"].state is DeviceState.OFFLINE
        assert by_serial["demo789"].state is DeviceState.UNAUTHORIZED

    def test_unknown_state_token_maps_to_absent_not_device(self):
        output = "List of devices attached\nweirdserial  sideload\n"
        devices = parse_adb_devices_output(output)
        assert devices[0].state is DeviceState.ABSENT
        assert devices[0].raw_state == "sideload"

    def test_transport_unknown_when_plain_listing(self):
        (device,) = parse_adb_devices_output("List of devices attached\ns1\tdevice\n")
        assert device.transport.value == "unknown"

    def test_empty_output(self):
        assert parse_adb_devices_output("") == ()

    def test_actionable_serials_filter(self):
        devices = parse_adb_devices_output(ADB_DEVICES_OK)
        assert actionable_serials(devices) == ("demo123",)


class TestSubprocessAdbClientByteSafety:
    """R-07 groundwork: the binary-safe adapter plumbing, proven against a
    real python child process (no adb binary involved, no device needed)."""

    @staticmethod
    def _py_client() -> SubprocessAdbClient:
        return SubprocessAdbClient(adb_path=sys.executable)

    def test_run_bytes_preserves_binary_payload(self):
        script = "import sys; sys.stdout.buffer.write(b'SQLite\\x00\\x89PNG\\xff\\xfe tail')"
        client = self._py_client()
        payload = client.run_bytes(["-c", script])
        assert payload == b"SQLite\x00\x89PNG\xff\xfe tail"

    def test_run_text_replaces_invalid_bytes(self):
        script = "import sys; sys.stdout.buffer.write(b'OK\\xff\\xfe-end')"
        client = self._py_client()
        result = client.run_text(["-c", script])
        assert result.returncode == 0
        assert "OK" in result.stdout
        assert "\ufffd" in result.stdout  # U+FFFD documents lost bytes
        assert result.stdout.rstrip().endswith("end")

    def test_commands_by_argument_list_with_serial(self):
        argv = build_adb_command("adb", ["shell", "getprop"], serial="S1")
        assert argv == ["adb", "-s", "S1", "shell", "getprop"]
        assert isinstance(argv, list)  # never a single shell string (R-10)

    def test_nonzero_text_result_carried_not_raised(self):
        script = "import sys; sys.exit(3)"
        client = self._py_client()
        result = client.run_text(["-c", script])
        assert result.returncode == 3

    def test_nonzero_bytes_raises_typed(self):
        script = "import sys; sys.stderr.write('bad'); sys.exit(2)"
        client = self._py_client()
        with pytest.raises(AdbCommandError) as exc_info:
            client.run_bytes(["-c", script])
        assert exc_info.value.returncode == 2
        assert "bad" in exc_info.value.stderr_excerpt

    def test_missing_executable_maps_to_adb_not_available(self, monkeypatch):
        def boom(*args, **kwargs):
            raise FileNotFoundError("nope")

        monkeypatch.setattr(subprocess, "run", boom)
        client = SubprocessAdbClient(adb_path="definitely/not/adb")
        with pytest.raises(AdbNotAvailable):
            client.run_text(["devices"])

    def test_timeout_maps_to_typed_command_error(self, monkeypatch):
        def boom(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="adb devices", timeout=0.01)

        monkeypatch.setattr(subprocess, "run", boom)
        client = SubprocessAdbClient(adb_path="adb")
        with pytest.raises(AdbCommandError) as exc_info:
            client.run_text(["devices"], timeout=0.01)
        assert exc_info.value.timeout is True

    def test_stderr_excerpt_redacted_in_command_error(self):
        from vscanner.core.errors import AdbCommandError as ACE

        err = ACE(cmd=("getprop",), stderr_excerpt="psk=hunter2 leaked")
        assert "hunter2" not in err.stderr_excerpt


class TestDirectoryShapedAdbPath:
    """F-2 regression: the saved path may be the *platform-tools directory*
    containing the executable (the exact user input that reached the packaged
    app). Windows refuses to CreateProcess a directory — PermissionError
    [WinError 5] "Access is denied" — which made discovery fail and the
    dashboard probe report the honest-but-not-launchable state. Every launch
    path now resolves a directory to its platform adb executable first.
    """

    def _tools_dir(self, tmp_path, with_executable: bool):
        tools = tmp_path / "platform-tools"
        tools.mkdir()
        if with_executable:
            shutil.copyfile(sys.executable, tools / self._exe_name())
        return tools

    @staticmethod
    def _exe_name() -> str:
        return "adb.exe" if os.name == "nt" else "adb"

    def test_resolve_semantics(self, tmp_path):
        tools = self._tools_dir(tmp_path, with_executable=False)
        # directory-shaped: resolves to the platform executable name inside
        assert resolve_adb_launch_path(str(tools)) == str(tools / self._exe_name())
        # file-shaped or absent: passes through unchanged (honest failures
        # downstream stay exactly as they were)
        probe_file = tmp_path / "somefile"
        probe_file.touch()
        assert resolve_adb_launch_path(str(probe_file)) == str(probe_file)
        assert resolve_adb_launch_path(
            "definitely/not/adb") == "definitely/not/adb"

    def test_validation_probe_resolves_directory_before_spawning(
            self, tmp_path, monkeypatch):
        # the exe file must exist so the pre-spawn check passes; its bytes
        # are irrelevant because the subprocess itself is faked
        tools = self._tools_dir(tmp_path, with_executable=True)
        captured: dict = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert check_adb_valid(str(tools)) is True
        assert captured["argv"][0] == str(tools / self._exe_name())

    def test_validation_missing_executable_still_false(self, tmp_path):
        tools = self._tools_dir(tmp_path, with_executable=False)
        # the directory exists but contains no adb executable — the probe
        # targets the (non-existent) resolved launch path → honest False
        assert check_adb_valid(str(tools)) is False
        assert check_adb_valid(str(tmp_path / "no-such-path")) is False
        assert check_adb_valid("") is False

    def test_client_launches_the_resolved_executable_for_real(
            self, tmp_path):
        # REAL child process: a directory-shaped path whose adb.exe is a
        # genuine (copied) interpreter proves the resolution end-to-end
        tools = self._tools_dir(tmp_path, with_executable=True)
        client = SubprocessAdbClient(adb_path=str(tools))
        assert client.adb_path == str(tools / self._exe_name())
        result = client.run_text(["-c", "import sys; sys.exit(0)"])
        assert result.returncode == 0

    def test_spaced_and_non_ascii_directory_launches(self, tmp_path):
        tools = tmp_path / "ADB Tools — café élex 平台工具"
        tools.mkdir()
        shutil.copyfile(sys.executable, tools / self._exe_name())
        client = SubprocessAdbClient(adb_path=str(tools))
        assert client.run_text(
            ["-c", "import sys; sys.exit(0)"]).returncode == 0

    def test_directory_without_executable_failure_is_typed_not_raw(
            self, tmp_path):
        # the raw behavior before the fix: real CreateProcess on the
        # directory raises PermissionError [WinError 5] that reached UI
        # banners verbatim; now it maps to the typed honest failure
        tools = self._tools_dir(tmp_path, with_executable=False)
        client = SubprocessAdbClient(adb_path=str(tools))
        with pytest.raises(AdbNotAvailable):
            client.run_text(["devices"])
        with pytest.raises(AdbNotAvailable):
            client.run_bytes(["version"])

    def test_permission_error_maps_to_typed_not_available(
            self, monkeypatch):
        def boom(*args, **kwargs):
            raise PermissionError(5, "Access is denied")

        monkeypatch.setattr(subprocess, "run", boom)
        client = SubprocessAdbClient(adb_path="some/locked/adb.exe")
        with pytest.raises(AdbNotAvailable):
            client.run_text(["devices"])
        with pytest.raises(AdbNotAvailable):
            client.run_bytes(["version"])

    def test_build_adb_command_resolves_directory(self, tmp_path):
        tools = tmp_path / "platform-tools"
        tools.mkdir()
        assert build_adb_command(
            str(tools), ["devices"]) == [str(tools / self._exe_name()), "devices"]


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def run_text(self, cmd, timeout=30.0):
        self.calls.append(cmd)
        if len(self._responses) > 1:
            stdout, stderr, code = self._responses.pop(0)
        else:
            stdout, stderr, code = self._responses[0]
        return subprocess.CompletedProcess(args=cmd, returncode=code, stdout=stdout, stderr=stderr)


class TestDeviceInfoService:
    def test_profile_fields_from_getprop(self):
        transport = FakeTransport([
            ("Samsung", "", 0), ("SM-G990B", "", 0), ("generic", "", 0),
        ] + [("", "", 0)] * 20)
        service = DeviceInfoService(transport)
        profile = service.get_basic_profile()
        assert profile.model == "SM-G990B"
        assert profile.mfr == "Samsung"
        assert profile.root_status is profile.root_status.UNKNOWN

    def test_every_probe_failure_degrades_to_none(self):
        class DeadTransport:
            def run_text(self, cmd, timeout=30.0):
                raise RuntimeError("device gone")

        profile = DeviceInfoService(DeadTransport()).get_basic_profile()
        assert profile.model is None
        assert profile.android is None
        assert profile.kernel is None
        assert profile.root_status.value == "unknown"  # R-05: no probe → no lie


class TestRegistrySelection:
    def _registry(self, transport):
        registry = ServiceRegistry.__new__(ServiceRegistry)
        registry.adb_path = "adb"
        registry._client = transport
        registry._discovery = DeviceDiscoveryService(transport)
        registry.reports = None
        registry.selected_serial = None
        registry.selected_identity = None
        return registry

    def test_select_unauthorized_raises(self):
        transport = FakeTransport([(ADB_DEVICES_OK, "", 0)] * 3)
        registry = self._registry(transport)
        with pytest.raises(DeviceUnauthorized):
            registry.select_device("demo789")

    def test_select_offline_raises_not_connected(self):
        transport = FakeTransport([(ADB_DEVICES_OK, "", 0)] * 3)
        registry = self._registry(transport)
        with pytest.raises(DeviceNotConnected) as exc:
            registry.select_device("demo456")
        assert exc.value.details["serial"] == "demo456"

    def test_select_device_sets_binding(self):
        transport = FakeTransport([(ADB_DEVICES_OK, "", 0)] * 3)
        registry = self._registry(transport)
        identity = registry.select_device("demo123")
        assert registry.selected_serial == "demo123"
        assert identity.serial == "demo123"

    def test_select_unknown_serial_raises(self):
        transport = FakeTransport([(ADB_DEVICES_OK, "", 0)] * 3)
        registry = self._registry(transport)
        with pytest.raises(DeviceNotConnected):
            registry.select_device("ghost")
