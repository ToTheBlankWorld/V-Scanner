"""Doctor-service tests (Stage 03, SC-11 / R-14): report-only semantics."""

from __future__ import annotations

import pytest

from vscanner.core.models import ToolId, ToolState, ToolStatusReflected
from vscanner.services.doctor import (
    RUNTIME_PACKAGES,
    PackageStatus,
    check_tool_status,
    collect_dependency_report,
)


class TestRuntimePackages:
    def test_exactly_three_proven_runtime_packages(self):
        """The doctor's dependency table matches the three grep-verified
        runtime deps (no pip aside, no invented entries)."""
        assert RUNTIME_PACKAGES == ("rich", "click", "jinja2")

    def test_report_shows_real_environment(self):
        report = collect_dependency_report()
        assert report.python_version
        assert report.all_packages_present is True  # test env has all three
        assert report.missing_packages() == ()

    def test_missing_package_reported_not_installed(self, monkeypatch):
        monkeypatch.setattr(
            "vscanner.services.doctor._package_installed",
            lambda name: name != "jinja2",
        )
        report = collect_dependency_report()
        assert report.all_packages_present is False
        assert report.missing_packages() == ("jinja2",)
        probed = [p for p in report.packages if p.name == "jinja2"][0]
        assert probed.installed is False
        assert isinstance(probed, PackageStatus)

    def test_report_only_note_always_present(self):
        """R-14 marker: the doctor reports, it never installs."""
        report = collect_dependency_report()
        assert any("report-only" in note for note in report.notes)


class TestToolStatusReflection:
    def test_passthrough_when_service_healthy(self):
        expected = ToolStatusReflected(tool=ToolId.ADB, state=ToolState.VALIDATED,
                                       path="C:/tools/platform-tools/adb.exe")
        assert check_tool_status(ToolId.ADB, _FakeToolService(expected)) is expected

    def test_failing_probe_never_crashes_doctor(self):
        status = check_tool_status(ToolId.ADB, _ExplodingToolService())
        assert status.state is ToolState.NOT_FOUND
        assert any("probe failed" in note for note in status.notes)

    def test_doctor_without_tools_service_still_builds(self):
        report = collect_dependency_report(tools_service=None)
        assert report.tools == ()
        assert report.all_packages_present


class _FakeToolService:
    def __init__(self, status):
        self._status = status

    def tool_status(self, tool):
        return self._status


class _ExplodingToolService:
    def tool_status(self, tool):
        raise RuntimeError("boom")
