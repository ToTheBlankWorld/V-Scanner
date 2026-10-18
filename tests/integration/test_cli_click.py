"""Click CLI characterization tests (Stage 02 — section E).

Only non-destructive paths: registration, help output, argument validation,
and safe no-device behavior. Destructive admin commands are exercised only
enough to prove they fail safely without a device (exit without executing).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import scanner

EXPECTED_COMMANDS = {
    "list-apps", "analyze", "uninstall",
    "open", "force-stop", "scan", "demo",
}


class TestRegistration:
    def test_all_seven_commands_registered(self):
        assert set(scanner.cli.commands.keys()) == EXPECTED_COMMANDS

    def test_help_lists_commands_without_device(self):
        result = CliRunner().invoke(scanner.cli, ["--help"])
        assert result.exit_code == 0
        for name in EXPECTED_COMMANDS:
            assert name in result.output
        assert "--device" in result.output or "-d" in result.output

    def test_scan_rejects_unknown_format(self, tmp_path):
        result = CliRunner().invoke(scanner.cli, ["scan", "--format", "bogus"], obj={})
        assert result.exit_code != 0
        assert "invalid" in (result.output + (result.exception and str(result.exception) or "")).lower()


class TestNoDeviceBehavior:
    def test_list_apps_fails_cleanly_without_device(self, monkeypatch, tmp_cwd):
        def boom(args, **kwargs):
            raise FileNotFoundError(2, "adb not found")

        monkeypatch.setattr(scanner.subprocess, "run", boom)
        result = CliRunner().invoke(scanner.cli, ["list-apps"], obj={})
        assert result.exit_code == 1
        assert "No Android device connected" in result.output

    def test_analyze_fails_cleanly_without_device(self, monkeypatch, tmp_cwd):
        def boom(args, **kwargs):
            raise FileNotFoundError(2, "adb not found")

        monkeypatch.setattr(scanner.subprocess, "run", boom)
        result = CliRunner().invoke(scanner.cli, ["analyze", "com.example.app"], obj={})
        assert result.exit_code == 1

    def test_device_option_is_threaded_into_commands(self, monkeypatch, tmp_cwd):
        captured = []

        def fake_run(args, **kwargs):
            captured.append(list(args))
            if "devices" in args:
                return __import__("subprocess").CompletedProcess(
                    args=args, returncode=0, stdout="List of devices attached\nSERIAL\tdevice\n", stderr="")
            # get_app_label path: respond with a versionName-free dump
            return __import__("subprocess").CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(scanner.subprocess, "run", fake_run)
        scanner.ADBInterface(device="SERIAL")._run_cmd(["devices"])
        assert captured[0] == ["adb", "-s", "SERIAL", "devices"]


class TestDestructiveCommandsStayGated:
    """Uninstall/open/force-stop must never execute device commands when no
    device is reachable: the connection gate must fire first."""

    @pytest.mark.parametrize("command", ["uninstall", "open", "force-stop"])
    def test_admin_commands_fail_cleanly_without_device(self, monkeypatch, tmp_cwd, command):
        def boom(args, **kwargs):
            raise FileNotFoundError(2, "adb not found")

        monkeypatch.setattr(scanner.subprocess, "run", boom)
        result = CliRunner().invoke(scanner.cli, [command, "com.example.app"], obj={})
        assert result.exit_code == 1
        assert "No Android device connected" in result.output


class TestDemoMode:
    def test_demo_generates_reports_without_device(self, tmp_cwd):
        result = CliRunner().invoke(scanner.cli, ["demo"], obj={})
        assert result.exit_code == 0, result.output
        json_path = Path("reports") / "demo_report.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["total_apps"] == 4
        assert Path("reports/demo_report.html").exists()
        assert Path("reports/demo_report.txt").exists()


class TestSafePorts:
    def test_scan_help_documents_formats(self):
        result = CliRunner().invoke(scanner.cli, ["scan", "--help"])
        assert result.exit_code == 0
        for fmt in ("console", "html", "json", "text", "all"):
            assert fmt in result.output
        # --output documented; tests never trigger destructive device ops
        assert "--output" in result.output
