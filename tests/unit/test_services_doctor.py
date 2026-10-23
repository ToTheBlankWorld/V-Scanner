"""Doctor-service tests (Stage 03, SC-11 / R-14): report-only semantics."""

from __future__ import annotations

import pytest

from vscanner.core.models import ToolId, ToolState, ToolStatusReflected
from vscanner.services.doctor import (
    DESKTOP_REQUIRED_PACKAGES,
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


class TestFrozenRuntimeHonesty:
    """F-1: in a packaged (frozen) build ``find_spec`` can report absent
    for packages compiled into the executable (no importlib metadata for
    the frozen importer); the frozen probe must go through the real
    import machinery and the report must make the frozen state explicit."""

    def test_source_runs_are_not_frozen(self):
        # pytest always executes from source; this pins the source-mode
        # probe semantics (find_spec) existence of the frozen branch.
        from vscanner.services.doctor import is_frozen

        assert is_frozen() is False

    def test_desktop_required_packages_matches_engine_truth(self):
        # F-1 truth embed: the desktop packaged surface's only third-party
        # runtime import is jinja2 (reports); rich/click serve the CLI.
        assert DESKTOP_REQUIRED_PACKAGES == ("jinja2",)

    def test_frozen_probe_uses_the_real_import_machinery(
            self, monkeypatch):
        import importlib

        import vscanner.services.doctor as doctor_mod
        probed: list = []
        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            probed.append(name)
            if name in ("rich", "click"):
                # simulated Nuitka frozen importer: not compiled into the
                # desktop executable at all
                raise ModuleNotFoundError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        monkeypatch.setattr(doctor_mod, "is_frozen", lambda: True)
        report = collect_dependency_report()
        # the frozen probe went through the import machinery, not find_spec
        assert set(probed) == set(RUNTIME_PACKAGES)
        by_name = {p.name: p.installed for p in report.packages}
        assert by_name == {"rich": False, "click": False, "jinja2": True}

    def test_frozen_report_explicitly_names_the_frozen_state(
            self, monkeypatch):
        import vscanner.services.doctor as doctor_mod

        monkeypatch.setattr(doctor_mod, "is_frozen", lambda: True)
        report = collect_dependency_report()
        frozen_notes = [n for n in report.notes if "frozen" in n]
        assert frozen_notes, report.notes

    def test_frozen_mode_stays_report_only(self, monkeypatch):
        # R-14 marker must survive every mode; no install side effects.
        import vscanner.services.doctor as doctor_mod

        monkeypatch.setattr(doctor_mod, "is_frozen", lambda: True)
        report = collect_dependency_report()
        assert any("report-only" in note for note in report.notes)


class _FakeToolService:
    def __init__(self, status):
        self._status = status

    def tool_status(self, tool):
        return self._status


class _ExplodingToolService:
    def tool_status(self, tool):
        raise RuntimeError("boom")
