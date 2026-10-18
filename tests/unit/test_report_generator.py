"""Characterization tests for cli/report_generator.py (Stage 02 — section B).

Report artifacts are written ONLY into pytest temp directories. Filename
format and JSON schema keys are the Stage 03 back-compat anchors.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import report_generator as rg
from permissions import RiskLevel, analyze_permissions, get_sdk_risk

# Representative demo fixture (mirrors the shipped demo data but is local to
# the suite so the demo command output can drift without failing these tests).
SPECIAL_NAME = "Ünïcode App ✓ 应用"

APP_CRITICAL = dict(
    package_name="com.example.sms",
    app_name=SPECIAL_NAME,
    version_name="2.1.0",
    version_code=210,
    target_sdk=33,
    min_sdk=23,
    permissions=["android.permission.READ_SMS", "android.permission.SEND_SMS",
                  "android.permission.CAMERA", "android.permission.INTERNET"],  # 25+25+15 = 65 → HIGH
)
APP_LOW = dict(
    package_name="com.example.util",
    app_name="Utility Tool",
    version_name="1.0",
    version_code=1,
    target_sdk=34,
    min_sdk=28,
    permissions=["android.permission.INTERNET"],
)

DEVICE_INFO = {
    "model": "Test Device",
    "manufacturer": "Pytest",
    "android_version": "13",
    "sdk_version": "33",
    "security_patch": "2026-01-05",
}


def make_full_report(app_specs) -> rg.FullScanReport:
    app_reports = []
    for spec in app_specs:
        perm_analysis = analyze_permissions(spec["permissions"])
        sdk_analysis = get_sdk_risk(spec["target_sdk"], spec["min_sdk"])
        app_reports.append(
            rg.create_app_report(
                package_name=spec["package_name"],
                app_name=spec["app_name"],
                version_name=spec["version_name"],
                version_code=spec["version_code"],
                target_sdk=spec["target_sdk"],
                min_sdk=spec["min_sdk"],
                permissions=spec["permissions"],
                permission_analysis=perm_analysis,
                sdk_analysis=sdk_analysis,
                insecure_urls=["http://app.example/call-back"] if "sms" in spec["package_name"] else [],
            )
        )
    return rg.create_full_report(DEVICE_INFO, app_reports)


@pytest.fixture
def generator(tmp_path) -> rg.ReportGenerator:
    return rg.ReportGenerator(str(tmp_path / "out"))


class TestSummaryClassification:
    def test_counts_by_risk_level(self):
        report = make_full_report([APP_CRITICAL, APP_LOW])
        assert report.total_apps == 2
        assert report.high_risk_apps == 1  # CRITICAL counts as high-risk
        assert report.low_risk_apps == 1

    def test_empty_scan_is_valid(self):
        report = make_full_report([])
        assert report.total_apps == 0
        assert report.high_risk_apps == 0
        assert report.summary["highest_risk_apps"] == []
        assert report.summary["total_dangerous_permissions"] == 0

    def test_apps_sorted_by_risk_score_desc(self):
        report = make_full_report([APP_LOW, APP_CRITICAL])
        scores = [app.risk_score for app in report.apps]
        assert scores == sorted(scores, reverse=True)

    def test_aggregate_summary_fields(self):
        report = make_full_report([APP_CRITICAL, APP_LOW])
        # INTERNET and ACCESS_WIFI_STATE are LOW-risk KB entries (score 6 → INFO).
        expected_dangerous = sum(len(a.dangerous_permissions) for a in report.apps)
        assert report.summary["total_dangerous_permissions"] == expected_dangerous
        assert expected_dangerous >= 3
        assert report.summary["apps_with_insecure_urls"] == 1
        recorded_names = {p["permission"] for p in report.summary["most_common_permissions"]}
        assert recorded_names <= {
            "READ_SMS", "SEND_SMS", "CAMERA", "INTERNET", "ACCESS_WIFI_STATE",
        }


class TestFileGeneration:
    def test_generate_all_writes_three_formats(self, generator):
        report = make_full_report([APP_CRITICAL])
        paths = generator.generate_all(report, "baseline_report")
        assert sorted(paths.keys()) == ["html", "json", "text"]
        written = [Path(p) for p in paths.values()]
        assert all(p.exists() and p.stat().st_size > 0 for p in written)
        assert {p.suffix for p in written} == {".html", ".json", ".txt"}

    def test_json_schema_keys_are_stable(self, generator, tmp_path):
        # Back-compat anchor for Stage 03 (ACCEPTANCE_CRITERIA Stage 03).
        report = make_full_report([APP_CRITICAL])
        path = Path(generator.generate_json(report, "schema_probe.json"))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data.keys()) == {
            "device_info", "scan_time", "total_apps", "high_risk_apps",
            "medium_risk_apps", "low_risk_apps", "summary", "apps",
        }
        app = data["apps"][0]
        assert app["package_name"] == APP_CRITICAL["package_name"]
        assert app["risk_level"] == "HIGH"  # score 68 (READ_SMS 25 + SEND_SMS 25 + CAMERA 15 + INTERNET 3)
        assert app["dangerous_permissions"][0]["name"] == "READ_SMS"

    def test_default_filename_pattern(self, generator):
        report = make_full_report([])
        html = generator.generate_html(report)
        assert re.fullmatch(r"security_report_\d{8}_\d{6}\.html", Path(html).name)

    def test_unicode_survives_all_formats(self, generator):
        report = make_full_report([APP_CRITICAL])
        paths = generator.generate_all(report, "unicode_report")
        json.loads(Path(paths["json"]).read_text(encoding="utf-8"))  # must not raise
        html = Path(paths["html"]).read_text(encoding="utf-8")
        assert SPECIAL_NAME in html

    def test_empty_report_all_formats_still_generated(self, generator):
        report = make_full_report([])
        paths = generator.generate_all(report, "empty_report")
        assert all(Path(p).stat().st_size > 0 for p in paths.values())
        data = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        assert data["total_apps"] == 0 and data["apps"] == []

    def test_output_directory_is_created(self, tmp_path):
        target = tmp_path / "deep" / "nested"
        rg.ReportGenerator(str(target))
        assert target.is_dir()

    def test_report_written_only_under_requested_dir(self, generator, tmp_path):
        report = make_full_report([APP_LOW])
        paths = generator.generate_all(report, "placement_check")
        for p in paths.values():
            assert str(tmp_path) in p

    def test_html_contains_app_and_score(self, generator):
        report = make_full_report([APP_CRITICAL])
        html = Path(generator.generate_html(report, "content_probe.html")).read_text(encoding="utf-8")
        assert "com.example.sms" in html
        assert "http://app.example/call-back" in html

    def test_invalid_values_do_not_crash_generation(self, generator):
        # Missing required analysis keys: factory fills safe defaults.
        report = rg.create_app_report(
            package_name="com.raw.app",
            app_name="Raw",
            version_name="",
            version_code=0,
            target_sdk=0,
            min_sdk=0,
            permissions=[],
            permission_analysis={},
            sdk_analysis={},
        )
        full = rg.create_full_report(dict(DEVICE_INFO, model=""), [report])
        paths = generator.generate_all(full, "invalid_data_report")
        assert all(Path(p).exists() for p in paths.values())
