"""Stage 08 engine-service tests (R-03..R-07, SC-5/6/8/10 contracts).

These directly exercise the engine services the TUI surfaces are built on:

* ``RootStatusService`` — verified root tri-state (R-05);
* ``MonitoringService`` — honest sensor rows + count-aware usage (R-04);
* ``DeepScanService`` — host-side strings/URL/credential extraction (R-06)
  plus the honest ``UNVERIFIED_CONDITION`` translation (never "clean");
* ``AdministrationService`` — service-side confirmation gate (R-13/SC-5);
* ``ForensicsService`` — case store, byte-exact extraction (R-07),
  WiFi redaction default (R-12), legacy report fields (R-05);
* ``ScreenMirrorService`` — validated-tool precondition + handle registry;
* ``DemoService`` — deterministic no-device fixture (SC-10);
* orchestration plans — cancel checkpoints, honest abort, typed snapshots;
* ``JobContext.emit_snapshot`` — typed monitor-lane payloads only.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

import pytest

from conftest import FakeAdb  # noqa: E402

from vscanner.core.errors import (
    ConfirmationInvalid,
    ConfirmationRequired,
    DeepScanUnavailable,
    ForensicsError,
    InputValidationError,
    JobCancelRequested,
    ToolNotValidated,
)
from vscanner.core.events import (
    JobEvent,
    JobSnapshotStreamEvent,
    JobState,
    OperationConfirmation,
)
from vscanner.core.models import (
    AppInfo,
    FindingCategory,
    FindingSeverity,
    HardwareUsageSnapshot,
    ObservationState,
    ScanConfiguration,
    SensorStatus,
    ToolState,
)
from vscanner.services.adb.root_probe import RootStatusService
from vscanner.services.admin import AdministrationService
from vscanner.services.demo import DemoService
from vscanner.services.forensics import ForensicsService
from vscanner.services.jobs import CancellationToken, JobKind, JobManager
from vscanner.services.mirroring import ScreenMirrorService
from vscanner.services.monitoring import MonitoringService
from vscanner.services.orchestration import (
    admin_op_plan,
    demo_scan_plan,
    forensics_job_plan,
    monitoring_session_plan,
)
from vscanner.services.scanning.deep_scan import (
    CredentialHit,
    DeepScanResult,
    DeepScanService,
    deep_scan_findings,
    extract_printable_strings,
    find_credential_matches,
    find_insecure_urls,
    redact_secret_snippet,
)
from vscanner.services.scanning.scanner import ScanService


def _confirmation(ref: str = "op", age_s: float = 0.0) -> OperationConfirmation:
    return OperationConfirmation(
        reference=ref,
        confirmed_at=datetime.now(timezone.utc) - timedelta(seconds=age_s),
    )


# --------------------------------------------------------------------------- #
# R-05 root probe
# --------------------------------------------------------------------------- #


class TestRootProbe:
    def test_confirmed_uid0_is_rooted(self) -> None:
        adb = FakeAdb(responses=[("uid=0(root) gid=0(root)", "", 0)])
        status, evidence = RootStatusService(adb).probe_evidence()
        assert status.value == "rooted"
        assert any("uid=0" in line for line in evidence)

    def test_su_visibility_without_uid0_is_unknown(self) -> None:
        adb = FakeAdb(responses=[
            ("", "permission denied", 1),   # su -c id refused
            ("/system/xbin/su", "", 0),     # su binary visible
        ])
        status, evidence = RootStatusService(adb).probe_evidence()
        assert status.value == "unknown"
        assert any("not confirmed" in line for line in evidence)

    def test_no_su_no_manager_is_not_rooted(self) -> None:
        adb = FakeAdb(responses=[
            ("", "not found", 1),           # su -c id fails
            ("", "", 1),                    # command -v su: absent
            ("package:com.android.settings", "", 0),
        ])
        status, _ = RootStatusService(adb).probe_evidence()
        assert status.value == "not_rooted"

    def test_not_rooted_evidence_records_adb_context(self) -> None:
        adb = FakeAdb(responses=[
            ("", "not found", 1),
            ("", "", 1),
            ("package:com.android.settings", "", 0),
        ])
        status, evidence = RootStatusService(adb).probe_evidence()
        assert status.value == "not_rooted"
        assert "adb" in " ".join(evidence).lower()

    def test_manager_package_keeps_unknown(self) -> None:
        adb = FakeAdb(responses=[
            ("", "not found", 1),
            ("", "", 1),
            ("package:com.topjohnwu.magisk\npackage:com.android.settings",
             "", 0),
        ])
        status, evidence = RootStatusService(adb).probe_evidence()
        assert status.value == "unknown"
        assert any("magisk" in line for line in evidence)

    def test_probe_exception_is_unknown(self) -> None:
        class Exploding:
            def run_text(self, cmd, timeout: float = 30.0):
                raise OSError("transport gone")

        status, evidence = RootStatusService(Exploding()).probe_evidence()
        assert status.value == "unknown"
        assert any("OSError" in line for line in evidence)

    def test_pm_failure_cannot_confirm_absence(self) -> None:
        adb = FakeAdb(responses=[
            ("", "not found", 1),
            ("", "", 1),
            ("", "boom", 26),
        ])
        assert RootStatusService(adb).probe().value == "unknown"

    def test_evidence_words_are_hyphenated_and_short(self) -> None:
        adb = FakeAdb(responses=[
            ("", "not found", 1),
            ("", "", 1),
            ("package:com.android.settings", "", 0),
        ])
        word, evidence = RootStatusService(adb).probe_evidence_words()
        assert word == "not-rooted"
        assert evidence and all("\n" not in line for line in evidence)


# --------------------------------------------------------------------------- #
# R-04 monitoring honesty
# --------------------------------------------------------------------------- #


class TestMonitoringSensors:
    def test_value_rows_and_detection_rows_are_device_only(self) -> None:
        adb = FakeAdb(responses=[(
            "Accelerometer: 0.001 -2.31 9.81\n"
            "Proximity Sensor detected and available\n",
            "", 0,
        )])
        readings = MonitoringService(adb).read_sensor_values_once()
        accel = [r for r in readings if r.name == "Accelerometer"][0]
        assert accel.status is SensorStatus.AVAILABLE
        assert accel.values == ("0.001 -2.31 9.81",)
        prox = [r for r in readings if r.name == "Proximity Sensor"][0]
        assert prox.values == ("Detected and available",)
        assert all(r.name for r in readings)

    def test_unparseable_output_is_one_honest_unavailable_row(self) -> None:
        adb = FakeAdb(responses=[("SensorService 1.0 bogus line\n", "", 0)])
        readings = MonitoringService(adb).read_sensor_values_once()
        assert len(readings) == 1
        row = readings[0]
        assert row.status is SensorStatus.UNAVAILABLE
        assert row.reason

    def test_transport_failure_is_honest_unavailable(self) -> None:
        class Exploding:
            def run_text(self, cmd, timeout: float = 30.0):
                raise OSError("lost")

        readings = MonitoringService(Exploding()).read_sensor_values_once()
        assert len(readings) == 1
        assert "OSError" in (readings[0].reason or "")

    def test_empty_capabilities_never_claims_nonexistence(self) -> None:
        adb = FakeAdb(responses=[("", "", 0)])
        assert MonitoringService(adb).list_sensor_capabilities() == ()


class TestMonitoringUsage:
    def test_active_camera_is_observed_with_evidence(self) -> None:
        adb = FakeAdb(responses=[
            ("Device 1 is open, client com.cam(", "", 0),
            ("Recording sessions: 0", "", 0),
            ("Active listeners: 0", "", 0),
        ])
        snap = MonitoringService(adb).read_hardware_usage_once("SER1")
        assert snap.camera is ObservationState.OBSERVED_ACTIVE
        assert snap.microphone is ObservationState.NOT_OBSERVED
        assert snap.location is ObservationState.NOT_OBSERVED
        assert snap.evidence and snap.evidence[0][0] == "camera"
        assert "Device 1 is open" in snap.evidence[0][1]
        assert snap.serial == "SER1"
        assert snap.failures == ()

    def test_count_zero_never_counts_as_activity(self) -> None:
        adb = FakeAdb(responses=[
            ("no open devices", "", 0),
            ("Recording sessions: 0", "", 0),
            ("Active listeners: 2", "", 0),
        ])
        snap = MonitoringService(adb).read_hardware_usage_once()
        assert snap.location is ObservationState.OBSERVED_ACTIVE
        evidence = dict((c, line) for c, line in snap.evidence)
        assert "Active listeners: 2" in evidence["location"]
        assert "camera" not in evidence

    def test_failed_probe_is_unknown_in_failures(self) -> None:
        class HalfBroken:
            def run_text(self, cmd, timeout: float = 30.0):
                if cmd[2] == "media.camera":
                    raise OSError("dumpsys crashed")
                stdout = "Active listeners: 1" if "location" in cmd else "ok"
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=stdout, stderr="")

        snap = MonitoringService(HalfBroken()).read_hardware_usage_once()
        assert snap.camera is ObservationState.UNKNOWN
        assert snap.location is ObservationState.OBSERVED_ACTIVE
        assert snap.failures and "camera" in snap.failures[0]


# --------------------------------------------------------------------------- #
# R-06 deep scan
# --------------------------------------------------------------------------- #


class TestDeepScanExtraction:
    def test_printable_run_extraction_is_binary_safe(self) -> None:
        payload = (b"AB\x01\x02http://files.example.org/x\x00"
                   b'password="s3cr3tTOP"\xffz')
        text = extract_printable_strings(payload)
        assert "http://files.example.org/x" in text
        assert 'password="s3cr3tTOP"' in text
        for run in text.splitlines():
            assert len(run) >= 4

    def test_urls_dedup_capped(self) -> None:
        text = " ".join(
            f"http://host{n}.example.com/a?b={n}" for n in range(30))
        urls = find_insecure_urls(text)
        assert len(urls) == 20
        assert urls[0] == "http://host0.example.com/a?b=0"

    def test_local_addresses_never_flagged(self) -> None:
        text = ("http://localhost:8080/ http://127.0.0.1/x"
                " http://192.168.1.2/y http://10.0.0.3/z")
        assert find_insecure_urls(text) == ()

    def test_credential_hits_are_redacted(self) -> None:
        text = 'config api_key="sk-9999SECRETVALUE" ok password="Hunter2Long"'
        hits = find_credential_matches(text)
        assert {"api_key", "password"} <= {h.pattern_name for h in hits}
        for hit in hits:
            assert isinstance(hit, CredentialHit)
            assert hit.value_len > 0
            assert "s3cr3t" not in hit.snippet
            assert "Hunter2" not in hit.snippet
            assert "<redacted, value length" in hit.snippet

    def test_bare_identifier_keeps_no_value_claim(self) -> None:
        hits = find_credential_matches("build uses aws_secret_key in CI")
        assert hits[0].value_len == 0
        assert "no embedded value" in hits[0].snippet


class TestDeepScanService:
    def test_scan_resolves_base_apk_and_runs_patterns(self) -> None:
        apk_text = ("PAD junk\x01http://api.evil-url.example.com/leak\x00"
                    'password="s3cr3tVALUE123"')
        adb = FakeAdb(responses=[
            ("package:/data/app/com.foo/base.apk\n"
             "package:/data/app/com.foo/split.config.apk", "", 0),
            (apk_text, "", 0),
        ])
        result = DeepScanService(adb).scan("com.foo")
        assert result.apk_path.endswith("base.apk")
        assert result.urls == ("http://api.evil-url.example.com/leak",)
        assert result.credentials
        assert all("<redacted" in c.snippet or c.value_len == 0
                   for c in result.credentials)

    def test_no_apk_path_is_unavailable(self) -> None:
        adb = FakeAdb(responses=[("not-installed", "", 0)])
        with pytest.raises(DeepScanUnavailable):
            DeepScanService(adb).scan("com.gone")

    def test_unsafe_apk_path_refused(self) -> None:
        adb = FakeAdb(responses=[("package:/data/app/mi';e.apk", "", 0)])
        with pytest.raises(DeepScanUnavailable):
            DeepScanService(adb).scan("com.foo")


class TestDeepScanFindingsMapping:
    def _app(self) -> AppInfo:
        return AppInfo(
            package_name="com.foo", label="Foo",
            requested_permissions=("android.permission.INTERNET",),
        )

    def test_url_classes_map_to_documented_severities(self) -> None:
        result = DeepScanResult(
            apk_path="/data/app/com.foo/base.apk",
            string_count=2,
            urls=("http://realhost.example.net/a",),
            credentials=(),
            test_domain_refs=("http://testsuite.example.",),
        )
        findings = deep_scan_findings(self._app(), "S1", result)
        url_findings = [
            f for f in findings if "Cleartext external" in f.title]
        assert url_findings
        assert url_findings[0].severity is FindingSeverity.MEDIUM
        assert any(
            f.severity is FindingSeverity.INFO and "test" in f.title.lower()
            for f in findings)

    def test_credential_findings_are_high_and_redacted(self) -> None:
        hit = redact_secret_snippet('password="s3cr3tVALUE99"', "password")
        result = DeepScanResult(
            apk_path="/x", string_count=1, urls=(), credentials=(hit,),
            test_domain_refs=(),
        )
        findings = deep_scan_findings(self._app(), None, result)
        secret = [f for f in findings
                  if f.kind is FindingCategory.HARDCODED_SECRET]
        assert secret and secret[0].severity is FindingSeverity.HIGH
        assert all("s3cr3t" not in f.detail for f in secret)

    def test_zero_hits_contributes_no_findings(self) -> None:
        result = DeepScanResult(
            apk_path="/x", string_count=0, urls=(), credentials=(),
            test_domain_refs=(),
        )
        assert deep_scan_findings(self._app(), None, result) == ()


_DUMP_BASE = (
    "Package [com.example.deep] (abc):\n"
    "  codePath=/data/app/com.example.deep/base.apk\n"
    "  versionName=1.2.3 versionCode=3\n"
    "  targetSdk=29 minSdk=21\n"
    "  requested permissions:\n"
    "      android.permission.INTERNET\n"
    "      android.permission.WRITE_EXTERNAL_STORAGE\n"
)


class TestDeepScanScanIntegration:
    """R-06 integration: ScanService deep=true runs the byte-safe chain and
    translates unavailability into an honest UNVERIFIED_CONDITION finding."""

    def test_deep_scan_produces_url_and_secret_findings(self) -> None:
        payload = ("~JUNK\x01http://api.deepscan-host.example.net/leak\x00"
                   'password="deepSecretV4lue"')
        adb = FakeAdb(responses=[
            (_DUMP_BASE, "", 0),
            ("package:/data/app/com.example.deep/base.apk", "", 0),
            (payload, "", 0),
        ])
        result = ScanService(adb).analyze_single_app(
            "com.example.deep", config=ScanConfiguration(deep=True))
        assert result.app is not None
        secrets = [f for f in result.findings
                   if f.kind is FindingCategory.HARDCODED_SECRET]
        assert secrets and secrets[0].severity is FindingSeverity.HIGH
        assert all("deepSecretV4lue" not in f.detail for f in secrets)
        urls = [f for f in result.findings
                if f.kind is FindingCategory.INSECURE_URL
                and f.severity is FindingSeverity.MEDIUM]
        assert urls
        # the byte-safe transport was actually used (exec-out on the APK)
        assert any(call[0] == "exec-out" for call in adb.calls)

    def test_deep_scan_unavailable_is_unverified_condition(self) -> None:
        adb = FakeAdb(responses=[
            (_DUMP_BASE, "", 0),
            ("", "not installed", 0),   # pm path produced no package: lines
        ])
        result = ScanService(adb).analyze_single_app(
            "com.example.deep", config=ScanConfiguration(deep=True))
        unverified = [f for f in result.findings
                      if f.severity is FindingSeverity.INFO
                      and "unavailable" in f.title.lower()]
        assert unverified
        assert any(getattr(ev, "kind", None) is not None
                   for f in unverified for ev in f.evidence)

    def test_deep_scan_off_polls_nothing_from_bytes(self) -> None:
        adb = FakeAdb(responses=[(_DUMP_BASE, "", 0)])
        ScanService(adb).analyze_single_app(
            "com.example.deep", config=ScanConfiguration())
        assert all(call[0] != "exec-out" for call in adb.calls)


# --------------------------------------------------------------------------- #
# R-13 / SC-5 admin confirmation gate
# --------------------------------------------------------------------------- #


class TestAdminConfirmationGate:
    def test_missing_confirmation_is_required_for_every_op(self) -> None:
        adb = FakeAdb(responses=[])
        service = AdministrationService(adb)
        with pytest.raises(ConfirmationRequired):
            service.uninstall_app("com.foo", None)
        with pytest.raises(ConfirmationRequired):
            service.launch_app("com.foo", None)
        with pytest.raises(ConfirmationRequired):
            service.force_stop_app("com.foo", None)
        assert adb.calls == []   # gated BEFORE any device contact

    def test_naive_timestamp_refused(self) -> None:
        adb = FakeAdb(responses=[])
        naive = OperationConfirmation(
            reference="uninstall:com.foo",
            confirmed_at=datetime.now(),  # naive on purpose
        )
        with pytest.raises(ConfirmationInvalid):
            AdministrationService(adb).uninstall_app("com.foo", naive)
        assert adb.calls == []

    def test_ttl_window_accepts_recent_and_refuses_stale(self) -> None:
        adb = FakeAdb(responses=[("Success", "", 0)])
        service = AdministrationService(adb)
        result = service.uninstall_app(
            "com.foo", _confirmation("uninstall:com.foo", age_s=100.0))
        assert result.ok is True
        too_old = _confirmation("uninstall:com.foo", age_s=5400.0)
        with pytest.raises(ConfirmationInvalid):
            service.uninstall_app("com.bar", too_old)

    def test_uninstall_success_and_device_truth(self) -> None:
        adb = FakeAdb(responses=[("Success", "", 0)])
        result = AdministrationService(adb).uninstall_app(
            "com.foo", _confirmation("uninstall:com.foo"))
        assert result.ok is True and result.adb_returncode == 0
        assert result.message == "Success"
        assert adb.calls == [["uninstall", "com.foo"]]

    def test_uninstall_failure_reports_device_explanation(self) -> None:
        adb = FakeAdb(responses=[("Failure [not installed for 0]", "", 1)])
        result = AdministrationService(adb).uninstall_app(
            "com.foo", _confirmation("uninstall:com.foo"))
        assert result.ok is False
        assert "Failure" in result.message

    def test_launch_two_step_keeps_activity_verbatim(self) -> None:
        adb = FakeAdb(responses=[
            ("priority=0 match=0x108000\n  com.foo/.MainActivity", "", 0),
            ("Starting: Intent { cmp=com.foo/.MainActivity }", "", 0),
        ])
        result = AdministrationService(adb).launch_app(
            "com.foo", _confirmation("launch:com.foo"))
        assert result.ok is True
        assert adb.calls[1] == [
            "shell", "am", "start", "-n", "com.foo/.MainActivity"]

    def test_launch_without_activity_is_honest_refusal(self) -> None:
        adb = FakeAdb(responses=[("", "no activities", 1)])
        result = AdministrationService(adb).launch_app(
            "com.foo", _confirmation("launch:com.foo"))
        assert result.ok is False
        assert "no launcher activity" in result.message
        assert adb.calls and adb.calls[0][1] == "cmd"

    def test_force_stop_shape_and_result(self) -> None:
        adb = FakeAdb(responses=[("", "", 0)])
        result = AdministrationService(adb).force_stop_app(
            "com.foo", _confirmation("force_stop:com.foo"))
        assert result.ok is True
        assert adb.calls == [["shell", "am", "force-stop", "com.foo"]]

    def test_bad_package_input_refused_before_confirmation(self) -> None:
        adb = FakeAdb(responses=[])
        with pytest.raises(InputValidationError):
            AdministrationService(adb).uninstall_app(
                "com bad; rm", _confirmation())
        assert adb.calls == []


# --------------------------------------------------------------------------- #
# R-07 / R-12 forensics
# --------------------------------------------------------------------------- #


class TestForensicsCaseStore:
    def test_create_case_records_verified_root_tri_state(
            self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[("uid=0(root) gid=0(root)", "", 0)])
        svc = ForensicsService(adb, base_dir=tmp_path / "cases")
        manifest = svc.create_case(
            "SER1", case_name="case_a", device_model="Pixel 5",
            android_version="13")
        assert manifest.root_status == "rooted"
        assert manifest.is_rooted is True
        assert manifest.redaction_preset == "default-redacted"

    def test_create_case_unknown_root_is_never_claimed_rooted(
            self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[("", "permission denied", 1)])
        svc = ForensicsService(adb, base_dir=tmp_path / "cases")
        manifest = svc.create_case("SER1", case_name="case_b")
        assert manifest.root_status == "unknown"
        assert manifest.is_rooted is False   # R-05: TRUE only when CONFIRMED

    def test_invalid_case_name_refused(self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[])
        svc = ForensicsService(adb, base_dir=tmp_path / "cases")
        with pytest.raises(InputValidationError):
            svc.create_case("SER", case_name="evil/../case")

    def test_load_case_round_trips_manifest(self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[("uid=0(root)", "", 0)])
        svc = ForensicsService(adb, base_dir=tmp_path / "cases")
        created = svc.create_case(
            "SER9", case_name="case_rt", note="test")
        loaded = svc.load_case("case_rt")
        assert loaded == created

    def test_duplicate_case_refused(self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[("uid=0(root)", "", 0)])
        svc = ForensicsService(adb, base_dir=tmp_path / "cases")
        svc.create_case("SER", case_name="case_c")
        with pytest.raises(ForensicsError):
            svc.create_case("SER", case_name="case_c")


class TestForensicsExtraction:
    def _mk(self, adb: FakeAdb, tmp_path: Path,
            name: str = "case_x") -> tuple:
        service = ForensicsService(adb, base_dir=tmp_path / "cases")
        adb.responses = [("uid=0(root)", "", 0)]
        manifest = service.create_case("SER1", case_name=name)
        return service, manifest

    def test_app_data_extraction_is_byte_exact_with_hashes(
            self, tmp_path: Path) -> None:
        import hashlib

        adb = FakeAdb(responses=[])
        service, manifest = self._mk(adb, tmp_path)
        adb.responses = [
            ("notes.db\nempty.bin", "", 0),      # ls databases
            ("db-bytespayload", "", 0),          # cat notes.db
            ("", "", 0),                         # cat empty.bin (legal 0-byte)
        ]
        updated = service.extract_app_data_files(
            "com.example.d", sources=("databases",), manifest=manifest)
        paths = {
            f.case_relative_path.replace("\\", "/") for f in updated.files}
        assert "com.example.d_databases/databases/notes.db" in paths
        for record in updated.files:
            data = (tmp_path / "cases" / "case_x"
                    / record.case_relative_path).read_bytes()
            assert hashlib.sha256(data).hexdigest() == record.sha256
        assert any(r.byte_count == len("db-bytespayload")
                   for r in updated.files)
        assert any(r.byte_count == 0 for r in updated.files)
        notes = dict(updated.extractions)
        assert any("2/2 files copied" in msg for msg in notes.values())

    def test_unsafe_listing_refused_not_silently_emptied(
            self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[])
        service, manifest = self._mk(adb, tmp_path, name="case_unsafe")
        adb.responses = [("../evil\nok.txt", "", 0)]
        updated = service.extract_app_data_files(
            "com.example.d", sources=("databases",), manifest=manifest)
        assert updated.files == ()
        notes = dict(updated.extractions)
        assert any("unsafe listing" in msg for msg in notes.values())

    def test_unknown_source_refused(self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[])
        service, manifest = self._mk(adb, tmp_path, name="case_src")
        with pytest.raises(InputValidationError):
            service.extract_app_data_files(
                "com.example.d", sources=("prefs",), manifest=manifest)


class TestForensicsWifiAndReport:
    _PSK_DUMP = (
        'network={\n  ssid="Home"\n  psk="s3cretwifiPlain"\n'
        '  key_mgmt=WPA-PSK\n}\n'
    )

    def _mk(self, adb: FakeAdb, tmp_path: Path, name: str) -> Any:
        service = ForensicsService(adb, base_dir=tmp_path / "cases")
        adb.responses = [("uid=0(root)", "", 0)]
        manifest = service.create_case("SER1", case_name=name)
        return service, manifest

    def test_default_wifi_write_is_redacted(self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[])
        service, manifest = self._mk(adb, tmp_path, "case_wifi")
        adb.responses = [(self._PSK_DUMP, "", 0)]
        updated = service.extract_wifi_networks(manifest)
        text = (tmp_path / "cases" / "case_wifi" / "wifi_networks.txt"
                ).read_text(encoding="utf-8")
        assert "s3cretwifiPlain" not in text
        assert "<redacted, length 15>" in text
        assert updated.redaction_preset == "default-redacted"

    def test_no_confirmation_means_redacted_only_no_cleartext_file(
            self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[])
        service, manifest = self._mk(adb, tmp_path, "case_wifi2")
        adb.responses = [(self._PSK_DUMP, "", 0)]
        service.extract_wifi_networks(manifest)
        assert not (tmp_path / "cases" / "case_wifi2"
                    / "wifi_networks_cleartext.txt").exists()

    def test_stale_cleartext_confirmation_refused(
            self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[])
        service, manifest = self._mk(adb, tmp_path, "case_wifi4")
        stale = _confirmation("wifi_cleartext_psk", age_s=99999)
        with pytest.raises(ConfirmationInvalid):
            service.extract_wifi_networks(
                manifest, acknowledge_cleartext_psk=stale)

    def test_confirmed_cleartext_writes_raw_with_recorded_preset(
            self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[])
        service, manifest = self._mk(adb, tmp_path, "case_wifi3")
        adb.responses = [(self._PSK_DUMP, "", 0)]
        updated = service.extract_wifi_networks(
            manifest,
            acknowledge_cleartext_psk=_confirmation("wifi_cleartext_psk"))
        raw = (tmp_path / "cases" / "case_wifi3"
               / "wifi_networks_cleartext.txt").read_text(encoding="utf-8")
        assert "s3cretwifiPlain" in raw
        assert updated.redaction_preset == "explicit-unredacted"

    def test_report_keeps_legacy_fields_and_honest_root(
            self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[])
        service, manifest = self._mk(adb, tmp_path, "case_rep")
        manifest = type(manifest)(
            case_id=manifest.case_id, created_at=manifest.created_at,
            device_serial=manifest.device_serial, device_model="Pixel 5",
            android="13", is_rooted=manifest.is_rooted,
            root_status=manifest.root_status,
            redaction_preset=manifest.redaction_preset,
            files=manifest.files, extractions=manifest.extractions,
            note=manifest.note)
        report_path = service.generate_report(manifest)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for legacy in ("case_name", "created", "device",
                       "android_version", "is_rooted"):
            assert legacy in report
        assert report["case_name"] == "case_rep"
        assert report["device"] == "Pixel 5"
        assert report["is_rooted"] is True
        assert report["root_status"] == "rooted"


class TestForensicsTextOps:
    def test_logs_packages_processes_write_honest_rows(
            self, tmp_path: Path) -> None:
        adb = FakeAdb(responses=[("uid=0(root)", "", 0)])
        service = ForensicsService(adb, base_dir=tmp_path / "cases")
        manifest = service.create_case("SER1", case_name="case_txt")
        adb.responses = [
            ("log line one\nlog line two", "", 0),
            ("package:com.a\npackage:com.b", "", 0),
            ("ps aux output", "", 0),
        ]
        manifest = service.extract_system_logs(manifest)
        manifest = service.extract_installed_packages(manifest)
        manifest = service.extract_running_processes(manifest)
        notes = dict(manifest.extractions)
        assert any("success (2 lines)" in msg for msg in notes.values())
        for name in ("system_logs.txt", "installed_packages.txt",
                     "running_processes.txt"):
            assert (tmp_path / "cases" / "case_txt" / name).exists()


# --------------------------------------------------------------------------- #
# SC-8 mirroring / SC-10 demo
# --------------------------------------------------------------------------- #


class FakeToolStatus:
    def __init__(self, state: ToolState) -> None:
        self.state = state
        self.path = "C:/fake/scrcpy.exe"


class TestScreenMirrorService:
    def _service(self) -> ScreenMirrorService:
        return ScreenMirrorService(
            adb_path=lambda: "C:/fake/adb.exe",
            scrcpy_path=lambda: "C:/fake/scrcpy.exe",
            tool_status=lambda: FakeToolStatus(ToolState.VALIDATED),
        )

    def test_launch_without_validated_tool_is_typed_refusal(self) -> None:
        service = ScreenMirrorService(
            adb_path=lambda: "adb",
            scrcpy_path=lambda: "scrcpy",
            tool_status=lambda: FakeToolStatus(ToolState.FOUND_UNVALIDATED),
        )
        with pytest.raises(ToolNotValidated):
            service.launch()

    def test_launch_is_argv_only_and_registered(self, monkeypatch) -> None:
        spawned: List[List[str]] = []

        class FakeProc:
            def __init__(self, cmd: List[str], **kwargs: Any) -> None:
                spawned.append(list(cmd))
                self.pid = 4242
                self._rc: Optional[int] = None

            def poll(self) -> Optional[int]:
                return self._rc

            def terminate(self) -> None:
                self._rc = 0

        monkeypatch.setattr(
            "vscanner.services.mirroring.subprocess.Popen", FakeProc)
        service = self._service()
        handle = service.launch()
        assert handle.pid == 4242
        assert handle.command[0] == "C:/fake/scrcpy.exe"
        assert spawned and all(
            isinstance(part, str) for part in spawned[0])
        assert len(service.list_running()) == 1

    def test_stop_returns_terminated_pids(self, monkeypatch) -> None:
        class FakeProc:
            def __init__(self, cmd: List[str], **kwargs: Any) -> None:
                self.pid = 777
                self._rc: Optional[int] = None

            def poll(self) -> Optional[int]:
                return self._rc

            def terminate(self) -> None:
                self._rc = 0

        monkeypatch.setattr(
            "vscanner.services.mirroring.subprocess.Popen", FakeProc)
        service = self._service()
        service.launch()
        assert service.stop() == (777,)
        assert service.stop() == ()   # gone after termination


class TestDemoService:
    def test_bundle_is_deterministic_and_honest(self) -> None:
        first = DemoService().scan()
        second = DemoService().scan()
        assert first.summary.demo is True
        assert second.summary.demo is True
        assert second.summary.findings_total == first.summary.findings_total
        assert [r.app.package_name for r in second.apps if r.app] == \
               [r.app.package_name for r in first.apps if r.app]
        assert first.summary.total_apps == 3
        for app_result in first.apps:
            assert app_result.scan_skipped_reason is None
            for finding in app_result.findings:
                assert finding.severity is FindingSeverity.INFO
                assert "DEMO" in finding.title


# --------------------------------------------------------------------------- #
# orchestration plans + monitor-lane typing
# --------------------------------------------------------------------------- #


class PlanContext:
    """Minimal JobContext stand-in for plan execution."""

    def __init__(self) -> None:
        self.cancel_token = CancellationToken()
        self.logs: List[tuple] = []
        self.snapshots: List[Any] = []

    def emit_snapshot(self, payload: object) -> bool:
        if not isinstance(
                payload, (HardwareUsageSnapshot, object)):
            raise InputValidationError(
                "unreachable guard", {"field": "payload"})
        self.snapshots.append(payload)
        return True

    def log(self, level: str, message: str) -> bool:
        self.logs.append((level, message))
        return True

    def progress(self, current: int, total: Optional[int] = None,
                 unit: str = "steps", context: str = "") -> bool:
        return True

    def emit_finding(self, finding: object) -> bool:
        return True


class FlakyMonitor:
    """read_hardware_usage_once succeeds N times, then raises forever."""
    """read_hardware_usage_once succeeds N times, then raises forever."""

    def __init__(self, good_calls: int) -> None:
        self._good = good_calls

    def read_hardware_usage_once(
            self, serial: Optional[str] = None) -> HardwareUsageSnapshot:
        if self._good > 0:
            self._good -= 1
            return HardwareUsageSnapshot(
                camera=ObservationState.NOT_OBSERVED,
                microphone=ObservationState.NOT_OBSERVED,
                location=ObservationState.NOT_OBSERVED,
                evidence=(), failures=(),
                serial=serial, captured_at=datetime.now(timezone.utc))
        raise OSError("adb blip")


class TestMonitoringSessionPlan:
    def test_aborts_after_consecutive_failures(self) -> None:
        context = PlanContext()
        plan = monitoring_session_plan(
            FlakyMonitor(good_calls=2), "SER1", interval_s=0.0,
            max_consecutive_failures=3)
        result = plan(context)
        assert result["status"] == "aborted"
        assert result["polls_completed"] == 2
        assert len(context.snapshots) == 2
        assert any("3/3" in msg for level, msg in context.logs
                   if level == "error")
        assert context.cancel_token.is_cancelled is False

    def test_cancel_checkpoint_stops_between_polls(self) -> None:
        context = PlanContext()
        context.cancel_token.request()
        plan = monitoring_session_plan(
            FlakyMonitor(good_calls=99), "SER", interval_s=0.0,
            max_consecutive_failures=2)
        with pytest.raises(JobCancelRequested):
            plan(context)
        assert context.snapshots == []


class TestAdminOpPlan:
    def test_service_gates_itself_plan_delegates(self) -> None:
        context = PlanContext()
        from types import SimpleNamespace

        seen: dict = {}

        class FakeAdmin:
            def uninstall_app(self, package: str, confirmation: Any):
                seen["package"] = package
                seen["confirmation"] = confirmation
                return SimpleNamespace(
                    message="uninstall completed", ok=True)

        token = _confirmation("uninstall:com.foo")
        plan = admin_op_plan(FakeAdmin(), "uninstall_app", "com.foo", token)
        result = plan(context)
        assert result.ok is True
        assert any("uninstall completed" in msg
                   for _l, msg in context.logs)
        assert seen == {"package": "com.foo", "confirmation": token}
        assert any("uninstall_app" in msg for _l, msg in context.logs)


class TestForensicsAndDemoPlans:
    def test_forensics_job_plan_unwraps_manifest(self) -> None:
        context = PlanContext()

        class Manifest:
            files = (1, 2)

        manifest, report = Manifest(), "report.json"
        plan = forensics_job_plan(
            lambda ctx: (manifest, report), "wifi extraction")
        assert plan(context) is manifest
        assert any("wifi extraction" in msg for _l, msg in context.logs)

    def test_demo_scan_plan_uses_no_device(self) -> None:
        context = PlanContext()
        plan = demo_scan_plan(DemoService())
        bundle = plan(context)
        assert bundle.summary.demo is True
        assert any("no device contacted" in msg
                   for _l, msg in context.logs)


class TestJobContextSnapshotLane:
    def _manager_events(self, plan) -> tuple:
        mgr = JobManager()
        collected: List[JobEvent] = []
        mgr.subscribe(collected.append)
        handle = mgr.submit(JobKind.OTHER, device_serial="s", plan=plan)
        return handle.wait(5), collected

    def test_valid_snapshot_streams_as_typed_event(self) -> None:
        snapshot = HardwareUsageSnapshot(
            camera=ObservationState.NOT_OBSERVED,
            microphone=ObservationState.NOT_OBSERVED,
            location=ObservationState.OBSERVED_ACTIVE,
            evidence=(("location", "Active listeners: 1"),),
            failures=(), serial="SER", captured_at=datetime.now(timezone.utc),
        )

        def plan(ctx: Any) -> object:
            return ctx.emit_snapshot(snapshot)

        state, events = self._manager_events(plan)
        assert state is JobState.SUCCEEDED
        streams = [e for e in events if isinstance(e, JobSnapshotStreamEvent)]
        assert len(streams) == 1
        assert streams[0].payload.location is ObservationState.OBSERVED_ACTIVE

    def test_free_text_status_never_smuggles_into_snapshot_lane(self) -> None:
        def plan(ctx: Any) -> object:
            return ctx.emit_snapshot("everything is fine")

        state, events = self._manager_events(plan)
        assert state is JobState.FAILED
        assert all(not isinstance(e, JobSnapshotStreamEvent) for e in events)


# --------------------------------------------------------------------------- #
# §9 event bridge: pump containment semantics (JOB_AND_EVENT_CONTRACTS)
# --------------------------------------------------------------------------- #


class TestAsyncJobBridgePumpContainment:
    def test_sink_failure_is_contained_and_recorded(self) -> None:
        from ui_terminal.jobs_bridge_async import AsyncJobBridge

        class Sink:
            def __init__(self) -> None:
                self.raised = False
                self.names: List[str] = []

            def __call__(self, event: Any) -> None:
                if not self.raised:
                    # first delivery blows up — containment must survive it
                    self.raised = True
                    raise ValueError("sink exploded")
                self.names.append(type(event).__name__)

        sink = Sink()

        async def scenario() -> Any:
            bridge = AsyncJobBridge()
            mgr = JobManager()
            bridge.attach(mgr)
            handle = mgr.submit(JobKind.OTHER, device_serial="s",
                                plan=lambda ctx: "val")
            await asyncio.to_thread(handle.wait, 5)
            pump_task = asyncio.create_task(bridge.pump(sink))
            deadline = datetime.now(timezone.utc) + timedelta(seconds=10)
            while datetime.now(timezone.utc) < deadline:
                if "JobTerminalEvent" in sink.names:
                    break
                await asyncio.sleep(0.005)
            bridge.stop()
            await asyncio.wait_for(pump_task, timeout=5.0)
            return bridge

        bridge = asyncio.run(scenario())
        # containment: the crashed first delivery did NOT drop the terminal;
        # remaining queue kept flowing (contract §12: no silent loss)
        assert "JobStartedEvent" not in sink.names
        assert "JobTerminalEvent" in sink.names
        assert bridge.last_sink_error is not None

    def test_stop_drains_queued_events_before_the_sentinel(self) -> None:
        from ui_terminal.jobs_bridge_async import AsyncJobBridge

        collected: List[str] = []

        def sink(event: Any) -> None:
            collected.append(type(event).__name__)

        async def scenario() -> None:
            bridge = AsyncJobBridge()
            mgr = JobManager()
            bridge.attach(mgr)
            handle = mgr.submit(JobKind.OTHER, device_serial="s",
                                plan=lambda ctx: "val")
            await asyncio.to_thread(handle.wait, 5)
            bridge.stop()          # sentinel enqueued AFTER real events
            pump_task = asyncio.create_task(bridge.pump(sink))
            await asyncio.wait_for(pump_task, timeout=5.0)

        asyncio.run(scenario())
        # events enqueued before stop() are delivered, then the pump ends
        assert "JobStartedEvent" in collected
        assert "JobTerminalEvent" in collected
        assert collected[-1] == "JobTerminalEvent"

    def test_pump_cancellation_propagates_and_is_not_recorded(
            self) -> None:
        from ui_terminal.jobs_bridge_async import AsyncJobBridge

        async def scenario() -> None:
            bridge = AsyncJobBridge()
            mgr = JobManager()
            bridge.attach(mgr)
            pump_task = asyncio.create_task(bridge.pump(lambda e: None))
            await asyncio.sleep(0.05)
            pump_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pump_task

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(scenario())
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
        assert AsyncJobBridge().last_sink_error is None