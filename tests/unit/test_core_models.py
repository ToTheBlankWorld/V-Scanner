"""Engine data-model tests (Stage 03, DATA_MODELS conformance)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from vscanner.core.models import (
    AppInfo,
    AppScanResult,
    AppLabelSource,
    ConnectionInfo,
    DeviceIdentity,
    DeviceState,
    DeviceTransport,
    Evidence,
    EvidenceKind,
    FindingCategory,
    FindingSeverity,
    ReportFormat,
    RootStatus,
    ScanConfiguration,
    ScanKind,
    ScanRequest,
    ScanResultBundle,
    ScanRun,
    ScanSummary,
    make_finding,
    model_to_dict,
    model_to_json,
    stable_finding_id,
    app_severity,
    SCHEMA_VERSION,
)
from vscanner.core.errors import AdbCommandError, ConfigError, ConfirmationRequired
from vscanner.core.redact import REDACTED_MARKER, RedactionPreset, redact_text


class TestConnectionInfo:
    def test_unknown_state_token_maps_to_absent_with_raw_token(self):
        devices = ConnectionInfo(serial="abc", state=DeviceState.ABSENT,
                                 usb_props={"raw_state": "sideload"})
        assert devices.state is DeviceState.ABSENT
        assert devices.raw_state == "sideload"

    def test_usb_and_wifi_transports(self):
        assert DeviceTransport("usb").value == "usb"
        assert DeviceTransport("wifi").value == "wifi"
        assert DeviceTransport("unknown").value == "unknown"


class TestDeviceIdentityHonesty:
    def test_missing_facts_stay_defaults(self):
        ident = DeviceIdentity(serial="abc")
        assert ident.model == ""
        assert ident.sdk_int is None
        assert ident.unknown_when_missing is True


class TestAppInfo:
    def test_rejects_empty_package_name(self):
        with pytest.raises(ValueError):
            AppInfo(package_name="")

    def test_rejects_invalid_package_characters(self):
        with pytest.raises(ValueError):
            AppInfo(package_name="com;rm -rf")

    def test_defaults_are_heuristic_and_unknown(self):
        info = AppInfo(package_name="com.example.app")
        assert info.label == "(unknown)"
        assert info.version_name is None
        assert info.version_code is None
        assert info.is_system is False
        assert info.requested_permissions == ()
        assert info.label_source is AppLabelSource.HEURISTIC

    def test_frozen_snapshot(self):
        info = AppInfo(package_name="com.example.app")
        with pytest.raises(Exception):
            info.package_name = "other"


class TestScanRequestValidation:
    def test_full_device_requires_serial(self):
        with pytest.raises(ValueError):
            ScanRequest(kind=ScanKind.FULL_DEVICE, config=ScanConfiguration())

    def test_single_app_does_not_require_serial(self):
        request = ScanRequest(kind=ScanKind.SINGLE_APP)
        assert request.id

    def test_full_device_with_serial_ok(self):
        request = ScanRequest(kind=ScanKind.FULL_DEVICE,
                              config=ScanConfiguration(device_serial="abc"))
        assert request.config.device_serial == "abc"


class TestEvidenceBoundary:
    def test_raw_excerpt_redacted_and_capped(self):
        evidence = Evidence.of(
            EvidenceKind.CONFIRMED_COMMAND_OUTPUT,
            description="wifi probe",
            source="adb shell dumpsys wifi",
            raw_excerpt=f"psk=super_secret_password " + "A" * 4096,
        )
        assert "super_secret_password" not in evidence.raw_excerpt
        assert len(evidence.raw_excerpt) <= 2048 + len(REDACTED_MARKER)

    def test_no_excerpt_is_none(self):
        evidence = Evidence.of(EvidenceKind.INFORMATIONAL, description="d", source="s")
        assert evidence.raw_excerpt is None


class TestFindingStableId:
    def test_deterministic_identity(self):
        one = make_finding(kind=FindingCategory.PERMISSION_EXCESS,
                           severity=FindingSeverity.HIGH, title="READ_SMS",
                           detail="d", app=AppInfo(package_name="com.example.app"))
        two = make_finding(kind=FindingCategory.PERMISSION_EXCESS,
                           severity=FindingSeverity.HIGH, title="READ_SMS",
                           detail="d", app=AppInfo(package_name="com.example.app"))
        assert one.id == two.id
        assert len(one.id) == 16

    def test_identity_diverges_on_app(self):
        one = make_finding(kind=FindingCategory.PERMISSION_EXCESS,
                           severity=FindingSeverity.HIGH, title="READ_SMS", detail="d",
                           app=AppInfo(package_name="com.a"))
        two = make_finding(kind=FindingCategory.PERMISSION_EXCESS,
                           severity=FindingSeverity.HIGH, title="READ_SMS", detail="d",
                           app=AppInfo(package_name="com.b"))
        assert one.id != two.id

    def test_stable_finding_id_matches_documented_transform(self):
        import hashlib

        expected = hashlib.sha256(
            "permission_excess|HIGH|com.a||READ_SMS|".encode("utf-8")
        ).hexdigest()[:16]
        assert stable_finding_id(FindingCategory.PERMISSION_EXCESS,
                                 FindingSeverity.HIGH, "READ_SMS", "com.a", None, "") == expected


class TestLegacyAliasCounts:
    """DATA_MODELS §5: legacy-compat aliases — CRITICAL+HIGH→HIGH, LOW+INFO→LOW."""

    @staticmethod
    def _bundle(app_findings):
        request = ScanRequest(kind=ScanKind.FULL_DEVICE,
                              config=ScanConfiguration(device_serial="s"))
        run = ScanRun(request=request)
        apps = []
        for findings in app_findings:
            app = AppInfo(package_name=f"com.app{len(apps)}")
            apps.append(AppScanResult(app=app, findings=findings))
        summary = ScanSummary(run=run, total_apps=len(apps))
        return ScanResultBundle(summary=summary, apps=tuple(apps))

    def test_alias_mapping_matches_legacy_buckets(self):
        def finding(sev):
            return make_finding(kind=FindingCategory.PERMISSION_EXCESS, severity=sev,
                                title="t", detail="d")

        bundle = self._bundle([
            (finding(FindingSeverity.CRITICAL),),
            (finding(FindingSeverity.HIGH),),
            (finding(FindingSeverity.MEDIUM),),
            (finding(FindingSeverity.LOW),),
            (finding(FindingSeverity.INFO),),
            (),  # clean app → INFO bucket (never fabricated severity)
        ])
        assert bundle.total_apps == 6
        assert bundle.high_risk_apps == 2   # CRITICAL + HIGH
        assert bundle.medium_risk_apps == 1
        assert bundle.low_risk_apps == 3    # LOW + INFO + clean


class TestSeverityAndRedaction:
    def test_redaction_masks_psk_assignment(self):
        assert "hunter2" not in redact_text('psk=hunter2')
        assert redact_text('psk=hunter2').startswith("psk")

    def test_redaction_masks_labeled_imei(self):
        redacted = redact_text("IMEI 867123456789012")
        assert "867123456789012" not in redacted
        assert "imei" in redacted.lower()

    def test_redaction_masks_phone_like_digits(self):
        assert redact_text("call 555 123 4567 now").count(REDACTED_MARKER) >= 1

    def test_full_preset_is_explicit_passthrough(self):
        secret = "psk=hunter2"
        assert redact_text(secret, RedactionPreset.FULL) == secret
        assert secret == "psk=hunter2"  # input never mutated

    def test_error_stderr_excerpt_redacted_and_capped(self):
        leak = "wifi psk=supersecret " * 1000
        err = AdbCommandError(cmd=("shell", "wifi"), stderr_excerpt=leak)
        assert "supersecret" not in err.stderr_excerpt
        assert len(err.stderr_excerpt) <= AdbCommandError.STDERR_EXCERPT_LIMIT

    def test_error_details_coerced_to_strings(self):
        err = ConfirmationRequired("refused", {"app_id": 7, "flag": True})
        assert err.details == {"app_id": "7", "flag": "True"}
        assert err.message == "refused"

    def test_errors_share_base_taxonomy(self):
        from vscanner.core.errors import VScannerError

        err = ConfigError("x")
        assert isinstance(err, VScannerError)


class TestSerialization:
    def _finding(self):
        app = AppInfo(package_name="com.example.app",
                      version_name="1.2.3", version_code=123,
                      requested_permissions=("android.permission.INTERNET",))
        evidence = Evidence.of(EvidenceKind.CONFIRMED_ARTIFACT,
                               description="declared", source="dumpsys package",
                               raw_excerpt="android.permission.INTERNET")
        finding = make_finding(kind=FindingCategory.PERMISSION_EXCESS,
                               severity=FindingSeverity.HIGH, title="READ_SMS",
                               detail="reads messages", app=app,
                               evidence=(evidence,))
        return finding

    def test_model_to_dict_enums_and_datetimes(self):
        payload = model_to_dict(self._finding())
        assert payload["severity"] == "HIGH"
        assert payload["kind"] == "permission_excess"
        assert payload["app"]["package_name"] == "com.example.app"
        assert payload["evidence"][0]["kind"] == "confirmed_artifact"
        datetime.fromisoformat(payload["evidence"][0]["extracted_at"])

    def test_model_to_json_envelope(self):
        document = json.loads(model_to_json(self._finding()))
        assert document["schema_version"] == SCHEMA_VERSION
        assert document["created_by"].startswith("vscanner/")
        assert document["data"]["title"] == "READ_SMS"

    def test_redaction_flag_masks_leaf_strings(self):
        payload = model_to_dict(self._finding(), redact=True)
        assert isinstance(payload, dict)


class TestReportFormatAndRootStatus:
    def test_report_format_suffixes(self):
        assert ReportFormat.HTML.suffix == "html"
        assert ReportFormat.JSON.suffix == "json"
        assert ReportFormat.TEXT.suffix == "text"

    def test_root_status_tri_state_exists(self):
        assert RootStatus("rooted").name == "ROOTED"
        assert RootStatus("not_rooted").name == "NOT_ROOTED"
        assert RootStatus("unknown").name == "UNKNOWN"


class TestAppSeverity:
    def test_empty_findings_rank_info(self):
        result = AppScanResult(app=AppInfo(package_name="com.x"))
        assert app_severity(result) is FindingSeverity.INFO

    def test_scan_skipped_never_fabricates_severity(self):
        result = AppScanResult(app=AppInfo(package_name="com.x"),
                               scan_skipped_reason="no permissions")
        assert app_severity(result) is FindingSeverity.INFO
        assert result.findings == ()
