"""Scanning service tests (Stage 03, SC-2/SC-3) + legacy-parity anchors."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

import scanner as legacy_scanner  # noqa: E402
import permissions as legacy_permissions  # noqa: E402

from conftest import FakeAdb  # noqa: E402

from vscanner.core.errors import InputValidationError
from vscanner.core.kb.permissions import analyze_permissions
from vscanner.core.models import (
    EvidenceKind,
    FindingCategory,
    FindingSeverity,
    ScanConfiguration,
    ScanKind,
    ScanRequest,
)
from vscanner.services.scanning.app_inventory import PackageInventoryService
from vscanner.services.scanning.package_parser import parse_package_dump, parse_pm_list_output
from vscanner.services.scanning.scanner import ScanService, validate_package_name

DUMPSYS_FIXTURE = (
    "Package [com.example.wallet] (1fd2...):\n"
    "  codePath=/data/app/com.example.wallet-base.apk\n"
    "  versionName=2.1.0\n"
    "  versionCode=210\n"
    "  targetSdk=28\n"
    "  minSdk=23\n"
    "  firstInstallTime=2024-01-02 12:34:56\n"
    "  lastUpdateTime=2024-06-01 09:00:00\n"
    "  requested permissions:\n"
    "    android.permission.INTERNET\n"
    "    android.permission.READ_SMS\n"
    "    android.permission.ACCESS_FINE_LOCATION\n"
    "    com.oem.custom.perm\n"
    "  install permissions:\n"
    "    android.permission.INTERNET: granted=true\n"
)


class TestPackageParser:
    def test_versions_and_sdks_parsed(self):
        app = parse_package_dump("com.example.wallet", DUMPSYS_FIXTURE)
        assert app.version_name == "2.1.0"
        assert app.version_code == 210
        assert app.target_sdk == 28
        assert app.min_sdk == 23

    def test_permissions_extracted_in_order(self):
        app = parse_package_dump("com.example.wallet", DUMPSYS_FIXTURE)
        # NOTE: the trailing duplicate mirrors the legacy parser verbatim —
        # the ``install permissions:`` section re-matches INTERNET because the
        # legacy termination rule only leaves the loop on a non-permission-ish
        # unindented line ("install permissions:" contains 'permission').
        # Byte-comparable scan behavior is a Stage 03 requirement, so the
        # quirk is preserved and documented (see stage report §parity).
        assert app.requested_permissions == (
            "android.permission.INTERNET",
            "android.permission.READ_SMS",
            "android.permission.ACCESS_FINE_LOCATION",
            "com.oem.custom.perm",
            "android.permission.INTERNET",
        )

    def test_timestamps_and_path(self):
        app = parse_package_dump("com.example.wallet", DUMPSYS_FIXTURE)
        assert app.apk_path == "/data/app/com.example.wallet-base.apk"
        assert app.first_install_time is not None
        assert app.last_update_time is not None

    def test_absent_fields_stay_none(self):
        app = parse_package_dump("com.example.wallet", "no useful lines here")
        assert app.version_name is None
        assert app.target_sdk is None
        assert app.requested_permissions == ()

    def test_pm_list_output(self):
        assert parse_pm_list_output(
            "package:com.a\npackage:com.b\nnoise\npackage:\n"
        ) == ("com.a", "com.b")


class TestLegacyParserParity:
    """The typed parser must agree with the legacy ADBInterface parser on the
    same raw dumpsys fixture (mission acceptance: scan-flow parity)."""

    @staticmethod
    def _legacy_info(dumpsys_stdout: str) -> dict:
        interface = legacy_scanner.ADBInterface.__new__(legacy_scanner.ADBInterface)
        interface.adb_path = "adb"  # type: ignore[attr-defined]
        interface.device_serial = None  # type: ignore[attr-defined]

        def fake_run(cmd, timeout=30):  # type: ignore[no-untyped-def]
            return (dumpsys_stdout, "", 0)

        interface._run_cmd = fake_run  # type: ignore[method-assign]
        return interface.get_package_info("com.example.wallet")

    @staticmethod
    def _typed_info(dumpsys_stdout: str):
        return parse_package_dump("com.example.wallet", dumpsys_stdout)

    def test_same_fixture_same_extracted_values(self):
        legacy = self._legacy_info(DUMPSYS_FIXTURE)
        typed = self._typed_info(DUMPSYS_FIXTURE)
        assert legacy["version_name"] == typed.version_name
        assert legacy["version_code"] == typed.version_code
        assert legacy["target_sdk"] == typed.target_sdk
        assert legacy["min_sdk"] == typed.min_sdk
        assert legacy["apk_path"] == typed.apk_path
        assert list(legacy["permissions"]) == list(typed.requested_permissions)
        # Heuristic label identical by construction (same last-segment rule):
        assert legacy["app_name"] == typed.label

    def test_legacy_placeholders_are_typed_none(self):
        """Honesty rule: legacy 'Unknown'/0 placeholders stay inside legacy
        serialization; the typed model keeps None (renderers display them)."""
        legacy = self._legacy_info("nothing useful")
        typed = self._typed_info("nothing useful")
        assert legacy["version_name"] == "Unknown"
        assert typed.version_name is None
        assert legacy["target_sdk"] == 0 and typed.target_sdk is None

    def test_same_permissions_same_risk_analysis(self):
        legacy = self._legacy_info(DUMPSYS_FIXTURE)
        typed = self._typed_info(DUMPSYS_FIXTURE)
        legacy_analysis = legacy_permissions.analyze_permissions(legacy["permissions"])
        new_analysis = analyze_permissions(list(typed.requested_permissions))
        assert legacy_analysis["risk_score"] == new_analysis["risk_score"]
        assert legacy_analysis["risk_level"] is new_analysis["risk_level"]
        assert [p.name for p in legacy_analysis["dangerous_permissions"]] == [
            p.name for p in new_analysis["dangerous_permissions"]
        ]
        # The KB returns PermissionInfo objects on both sides now that the
        # legacy module is a re-export shim for the engine module.
        assert legacy_permissions.analyze_permissions is analyze_permissions


class TestPackageValidation:
    @pytest.mark.parametrize("bad", ["", "   ", "com a; rm -rf /", "x" * 256, "pkg|ls"])
    def test_rejects_unsafe_or_malformed(self, bad):
        with pytest.raises(InputValidationError):
            validate_package_name(bad)

    def test_accepts_realistic_names(self):
        assert validate_package_name("com.example.app") == "com.example.app"
        assert validate_package_name("org.fdroid.FDroid") == "org.fdroid.FDroid"
        assert validate_package_name("d--debug.app") == "d--debug.app"  # mission:
        # deviation from ^[a-z0-9._+]+$ resolved to [A-Za-z0-9._+-] charset


class FakeTransport:
    """SC-shape fake returning queued (stdout, stderr, code) tuples."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def run_text(self, cmd, timeout=30.0):
        self.calls.append(list(cmd))
        if len(self._responses) > 1:
            stdout, stderr, code = self._responses.pop(0)
        else:
            stdout, stderr, code = self._responses[0]
        return _FakeResult(stdout, stderr, code)


class _FakeResult:
    def __init__(self, stdout, stderr, code):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = code


class TestScanServiceSingleApp:
    def _service(self, dumpsys_response):
        transport = FakeTransport([(dumpsys_response, "", 0)])
        return ScanService(transport)

    def test_dangerous_permissions_become_findings(self):
        service = self._service(DUMPSYS_FIXTURE)
        result = service.analyze_single_app("com.example.wallet")
        assert result.findings, "READ_SMS + ACCESS_FINE_LOCATION must produce findings"
        perm_findings = [f for f in result.findings
                         if f.kind is FindingCategory.PERMISSION_EXCESS]
        names = [f.title for f in perm_findings]
        assert "READ_SMS" in names
        assert "ACCESS_FINE_LOCATION" in names
        # Legacy parity: analyze_permissions lists even LOW risk entries
        # (e.g. INTERNET) under dangerous_permissions, so they become LOW
        # findings — the dedup quirk from install permissions also carries
        # over (documented; see parity notes in the stage report).
        assert "INTERNET" in names
        severity_by_name = {}
        for f in perm_findings:
            severity_by_name.setdefault(f.title, []).append(f.severity)
        assert FindingSeverity.LOW in severity_by_name["INTERNET"]
        for finding in perm_findings:
            assert finding.severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH,
                                        FindingSeverity.MEDIUM, FindingSeverity.LOW)
            assert finding.app.package_name == "com.example.wallet"
            assert finding.evidence[0].kind is EvidenceKind.CONFIRMED_ARTIFACT
            assert finding.tags and finding.tags[0]  # KB category tag

    def test_sdk_advisories_become_findings(self):
        service = self._service(DUMPSYS_FIXTURE)
        result = service.analyze_single_app("com.example.wallet")
        sdk_findings = [f for f in result.findings
                        if f.kind is FindingCategory.SDK_COMPAT]
        assert sdk_findings  # targetSdk 28/min 23 cross the legacy thresholds
        details = " | ".join(f.detail for f in sdk_findings)
        assert details  # recommendation text carried in detail

    def test_no_permissions_is_skipped_not_fabricated(self):
        service = self._service("Package [com.barren] (1234):\n  versionCode=9\n")
        result = service.analyze_single_app("com.barren")
        assert result.findings == ()
        assert result.scan_skipped_reason
        assert "no accessible permission information" in result.scan_skipped_reason

    def test_malformed_package_name_rejected_before_subprocess(self):
        transport = FakeTransport([("irrelevant", "", 0)])
        service = ScanService(transport)
        with pytest.raises(InputValidationError):
            service.analyze_single_app("com.a; reboot")
        assert transport.calls == []  # nothing executed

    def test_deep_scan_flags_unverified_condition(self):
        service = self._service(DUMPSYS_FIXTURE)
        result = service.analyze_single_app(
            "com.example.wallet",
            config=ScanConfiguration(deep=True),
        )
        deep_notes = [f for f in result.findings
                      if f.kind is FindingCategory.INSECURE_URL]
        assert len(deep_notes) == 1
        assert deep_notes[0].evidence[0].kind is EvidenceKind.UNVERIFIED_CONDITION


class TestScanServiceFullDevice:
    def _service_scan_and_assert(self, include_system=False):
        list_call = ["shell", "pm", "list", "packages"]
        if not include_system:
            list_call.append("-3")
        responses = [
            ("package:com.wallet\npackage:com.barren\npackage:com.okay", "", 0),
            (DUMPSYS_FIXTURE, "", 0),      # com.wallet: rich info
            ("  totally empty dumpsys", "", 0),  # com.barren: skip
            (
                "Package [com.okay] (1):\n  versionCode=45\n  targetSdk=35\n"
                "  minSdk=30\n  requested permissions:\n"
                "    android.permission.INTERNET\n",
                "", 0,
            ),
        ]
        transport = FakeTransport(responses)
        service = ScanService(transport)
        request = ScanRequest(
            kind=ScanKind.FULL_DEVICE,
            config=ScanConfiguration(device_serial="demo", include_system=include_system),
        )
        bundle = service.scan_full_device(request)
        assert transport.calls[0] == list_call
        return bundle

    def test_three_apps_scanned(self):
        bundle = self._service_scan_and_assert()
        assert bundle.summary.total_apps == 3
        assert [a.app.package_name for a in bundle.apps] == [
            "com.wallet", "com.barren", "com.okay",
        ]

    def test_skip_reason_recorded_honestly(self):
        bundle = self._service_scan_and_assert()
        barren = bundle.apps[1]
        assert barren.scan_skipped_reason
        assert barren.findings == ()
        assert bundle.summary.skipped_apps == ("com.barren",)

    def test_summary_counts_match_legacy_buckets(self):
        bundle = self._service_scan_and_assert()
        # com.wallet: READ_SMS (CRITICAL 25) + ACCESS_FINE_LOCATION (HIGH 15) = 40 → HIGH bucket
        # com.barren: skipped, clean → INFO/LOW bucket
        # com.okay: INTERNET only → clean → LOW bucket
        assert bundle.summary.high_risk == 1
        assert bundle.summary.medium_risk == 0
        assert bundle.summary.low_risk == 2
        assert bundle.high_risk_apps == 1
        assert bundle.low_risk_apps == 2
        assert bundle.summary.findings_total > 0

    def test_include_system_switches_pm_flag(self):
        bundle = self._service_scan_and_assert(include_system=True)
        assert bundle.summary.total_apps == 3  # same responses; call shape differs

    def test_run_lifecycle_completed(self):
        bundle = self._service_scan_and_assert()
        assert bundle.summary.run.state.value == "completed"
        assert bundle.summary.run.started_at is not None
        assert bundle.summary.run.finished_at is not None


class TestInventoryService:
    def test_list_packages_and_app_info(self):
        transport = FakeTransport([
            ("package:com.a\npackage:com.b", "", 0),
            (DUMPSYS_FIXTURE, "", 0),
        ])
        service = PackageInventoryService(transport)
        assert service.list_packages() == ("com.a", "com.b")
        app = service.get_app_info("com.example.wallet")
        assert app.version_code == 210

    def test_list_failure_raises_typed(self):
        transport = FakeTransport([("", "device not found", 1)])
        service = PackageInventoryService(transport)
        from vscanner.core.errors import AdbCommandError

        with pytest.raises(AdbCommandError):
            service.list_packages()
