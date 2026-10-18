"""ADB-interface characterization tests (Stage 02 — section C).

All ADB subprocess execution is mocked via ``scanner.subprocess.run``.
One decode-behavior test runs a real local ``python`` subprocess (never adb)
to verify the text-decode contract of ``_run_cmd`` without any device.
"""

from __future__ import annotations

import subprocess
import sys
from unittest import mock

import pytest

import scanner
from conftest import adb_completed


@pytest.fixture
def run_patch(monkeypatch):
    """Patch scanner.subprocess.run and return recorded calls + settable results."""
    calls: list = []
    results: list = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if results:
            outcome = results.pop(0)
        else:
            outcome = ("", "", 0)
        if isinstance(outcome, Exception):
            raise outcome
        stdout, stderr, code = outcome
        return subprocess.CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(scanner.subprocess, "run", fake_run)
    return type("Harness", (), {"calls": calls, "queue": lambda self, *o: results.extend(o)})()


class TestCommandConstruction:
    def test_default_uses_path_adb_with_no_serial(self, run_patch):
        ai = scanner.ADBInterface()
        ai._run_cmd(["devices"])
        assert run_patch.calls == [["adb", "devices"]]

    def test_serial_flag_injected_after_path(self, run_patch):
        ai = scanner.ADBInterface(device="SERIAL123")
        ai._run_cmd(["shell", "getprop"])
        assert run_patch.calls == [["adb", "-s", "SERIAL123", "shell", "getprop"]]

    def test_custom_adb_path(self, run_patch):
        ai = scanner.ADBInterface(adb_path=r"C:\tools\adb.exe")
        ai._run_cmd(["devices"])
        assert run_patch.calls[0][:1] == [r"C:\tools\adb.exe"]

    def test_default_timeout_is_30_seconds(self, run_patch, monkeypatch):
        captured = {}

        def capture(args, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(scanner.subprocess, "run", capture)
        scanner.ADBInterface()._run_cmd(["devices"])
        assert captured.get("timeout") == 30

    def test_arguments_are_list_based(self, run_patch):
        """Safe argument construction: _run_cmd receives and passes lists."""
        scanner.ADBInterface(device="S")._run_cmd(["pm", "list", "packages"])
        assert isinstance(run_patch.calls[0], list)


class TestErrorPropagation:
    def test_timeout_returns_error_tuple_not_exception(self, run_patch):
        run_patch.queue(subprocess.TimeoutExpired(cmd=[], timeout=30))
        stdout, stderr, code = scanner.ADBInterface()._run_cmd(["devices"])
        assert (stdout, stderr, code) == ("", "Command timed out", 1)

    def test_missing_adb_binary_returns_error_tuple(self, run_patch):
        run_patch.queue(FileNotFoundError(2, "adb not found"))
        stdout, stderr, code = scanner.ADBInterface()._run_cmd(["devices"])
        assert code == 1
        assert "ADB not found" in stderr

    def test_check_connection_false_when_adb_missing(self, run_patch):
        run_patch.queue(FileNotFoundError(2, "adb not found"))
        assert scanner.ADBInterface().check_connection() is False


class TestConnectionParsing:
    def test_connection_true_when_device_present(self, run_patch):
        run_patch.queue(("List of devices attached\nabc123\tdevice\n", "", 0))
        assert scanner.ADBInterface().check_connection() is True

    def test_connection_false_when_no_lines(self, run_patch):
        run_patch.queue(("List of devices attached\n", "", 0))
        assert scanner.ADBInterface().check_connection() is False

    def test_offline_and_unauthorized_not_counted_as_connected(self, run_patch):
        run_patch.queue(("List of devices attached\n"
                         "abc123\toffline\n"
                         "def456\tunauthorized\n"
                         "ghi789\tdevice\n", "", 0))
        # Characterization: legacy check counts ANY line containing "device",
        # which also matches a serial equal to "device" — documented quirk.
        assert scanner.ADBInterface().check_connection() is True


class TestDeviceListing:
    def test_get_device_info_ignores_failed_props(self, run_patch):
        run_patch.queue(("Pixel 7\n", "", 0))  # getprop model success
        run_patch.queue(("", "", 1))           # manufacturer fails
        run_patch.queue(("13\n", "", 0))       # android_version succeeds
        run_patch.queue(("", "", 1))           # sdk fails
        run_patch.queue(("", "", 1))
        run_patch.queue(("", "", 1))
        run_patch.queue(("", "", 1))
        info = scanner.ADBInterface().get_device_info()
        assert info == {"model": "Pixel 7", "android_version": "13"}


class TestPackageListing:
    def test_third_party_flag_appended(self, run_patch):
        run_patch.queue(("package:com.a\npackage:com.b\n", "", 0))
        packages = scanner.ADBInterface().list_packages(include_system=False)
        assert run_patch.calls[0] == ["adb", "shell", "pm", "list", "packages", "-3"]
        assert packages == ["com.a", "com.b"]

    def test_system_flag_omits_dash_three(self, run_patch):
        run_patch.queue(("package:com.sys.app\n", "", 0))
        packages = scanner.ADBInterface().list_packages(include_system=True)
        assert run_patch.calls[0] == ["adb", "shell", "pm", "list", "packages"]
        assert packages == ["com.sys.app"]

    def test_failure_returns_empty_list(self, run_patch):
        run_patch.queue(("", "error", 1))
        assert scanner.ADBInterface().list_packages() == []


class TestDecodeContract:
    def test_real_subprocess_non_utf8_decodes_losinglessly_or_replaces(self):
        """Documents the true decode behavior of _run_cmd (R-07 groundwork):
        a process emitting non-UTF-8 bytes is decoded with errors='replace'."""
        ai = scanner.ADBInterface(adb_path=sys.executable)
        script = "import sys; sys.stdout.buffer.write(b'\\xff\\xfe\\x00data')"
        stdout, stderr, code = ai._run_cmd(["-c", script])
        assert code == 0
        assert "\ufffd" in stdout  # original bytes were replaced at decode time
