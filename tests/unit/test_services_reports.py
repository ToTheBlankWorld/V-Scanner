"""Report-service tests (Stage 03, SC-9) — byte parity against legacy writers.

Parity mechanism (see vscanner/services/reports/service.py): both sides run
the same verbatim templates and the same pure KB functions; the clock is
pinned on both sides through their natural seams (legacy values are set via
``dataclasses.replace``, the engine's ``ScanRun.started_at`` and the
``Evidence`` timestamps accept fixed datetimes), so the comparison is fully
deterministic and requires no monkeypatching of production code paths.
"""

from __future__ import annotations

import dataclasses
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

import report_generator as legacy_rgen  # noqa: E402
import scanner as legacy_scanner  # noqa: E402

import permissions as legacy_permissions  # noqa: E402
from vscanner.core import models as core_models  # noqa: E402
from vscanner.core.errors import ExportError  # noqa: E402
from vscanner.core.kb.permissions import get_sdk_risk  # noqa: E402
from vscanner.core.models import (  # noqa: E402
    ReportFormat,
    ScanConfiguration,
    ScanKind,
    ScanRequest,
    ScanRun,
    ScanSummary,
    ScanResultBundle,
)
from vscanner.services.scanning.scanner import ScanService  # noqa: E402
from vscanner.services.reports.service import ReportService  # noqa: E402

FIXED_AWARE = datetime(2026, 1, 1, 12, 30, 45, tzinfo=timezone.utc)
FIXED_APP_ISO = FIXED_AWARE.isoformat()          # 2026-01-01T12:30:45+00:00
FIXED_REPORT_TS = "2026-01-01 12:30:45"
FIXED_FILENAMES = {
    ReportFormat.JSON: "parity.json",
    ReportFormat.HTML: "parity.html",
    ReportFormat.TEXT: "parity.text",
}

DEVICE_INFO = {
    "brand": "samsung",
    "model": "SM-G990B",
    "android_version": "13",
    "sdk_version": "33",
    "serial": "demo123",
}

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


class _FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)

    def run_text(self, cmd, timeout=30.0):
        if len(self._responses) > 1:
            stdout, stderr, code = self._responses.pop(0)
        else:
            stdout, stderr, code = self._responses[0]

        class _R:
            def __init__(self, o, e, c):
                self.stdout, self.stderr, self.returncode = o, e, c

        return _R(stdout, stderr, code)


class _LegacyCapture:
    """Silence legacy prints (rich console writes to its own Console)."""

    def __enter__(self):
        import contextlib
        import io

        self._buf = io.StringIO()
        self._ctx = contextlib.redirect_stdout(self._buf)
        self._ctx.__enter__()
        return self

    def __exit__(self, *exc):
        self._ctx.__exit__(*exc)
        return False


def _legacy_pipeline(tmp_path: Path) -> Path:
    """Run the exact legacy scan→report path, with clocks pinned."""
    interface = legacy_scanner.ADBInterface.__new__(legacy_scanner.ADBInterface)
    interface.adb_path = "adb"  # type: ignore[attr-defined]
    interface.device_serial = None  # type: ignore[attr-defined]
    interface._run_cmd = lambda cmd, timeout=30: (DUMPSYS_FIXTURE, "", 0)  # type: ignore[method-assign]
    info = interface.get_package_info("com.example.wallet")

    perm_analysis = legacy_permissions.analyze_permissions(info["permissions"])
    sdk_analysis = get_sdk_risk(info["target_sdk"], info["min_sdk"])

    app_rep = legacy_rgen.create_app_report(
        package_name="com.example.wallet",
        app_name=info["app_name"],
        version_name=info["version_name"],
        version_code=info["version_code"],
        target_sdk=info["target_sdk"],
        min_sdk=info["min_sdk"],
        permissions=info["permissions"],
        permission_analysis=perm_analysis,
        sdk_analysis=sdk_analysis,
    )
    app_rep = dataclasses.replace(app_rep, scan_time=FIXED_APP_ISO)
    full = legacy_rgen.create_full_report(dict(DEVICE_INFO), [app_rep])
    full = dataclasses.replace(full, scan_time=FIXED_REPORT_TS)

    out_dir = tmp_path / "legacy"
    with _LegacyCapture():
        gen = legacy_rgen.ReportGenerator(output_dir=str(out_dir))
        gen.generate_json(full, FIXED_FILENAMES[ReportFormat.JSON])
        gen.generate_html(full, FIXED_FILENAMES[ReportFormat.HTML])
        gen.generate_text(full, FIXED_FILENAMES[ReportFormat.TEXT])
    return out_dir


def _engine_bundle(monkeypatch) -> ScanResultBundle:
    """Run the exact engine scan path, with the clock pinned at the seam."""
    monkeypatch.setattr(core_models, "_utcnow", lambda: FIXED_AWARE)
    transport = _FakeTransport([(DUMPSYS_FIXTURE, "", 0)])
    service = ScanService(transport)
    result = service.analyze_single_app("com.example.wallet")
    request = ScanRequest(kind=ScanKind.SINGLE_APP,
                          config=ScanConfiguration(device_serial=None))
    run = ScanRun(request=request, state=run_state_done(),
                  started_at=FIXED_AWARE, finished_at=FIXED_AWARE)
    summary = ScanSummary(run=run, total_apps=1)
    return ScanResultBundle(summary=summary, apps=(result,))


def run_state_done():
    from vscanner.core.models import ScanLifecycleState

    return ScanLifecycleState.COMPLETED


class TestByteParity:
    def test_all_three_formats_byte_identical(self, tmp_path, monkeypatch):
        legacy_dir = _legacy_pipeline(tmp_path)
        bundle = _engine_bundle(monkeypatch)

        engine_dir = tmp_path / "engine"
        service = ReportService(output_dir=str(engine_dir))
        result = service.export(
            bundle,
            requested={fmt: FIXED_FILENAMES[fmt] for fmt in ReportFormat},
            device_info=DEVICE_INFO,
        )
        assert result.ok is True
        assert result.error is None
        for fmt, name in FIXED_FILENAMES.items():
            assert (engine_dir / name).suffix.lstrip(".") == fmt.suffix
            legacy_bytes = (legacy_dir / name).read_bytes()
            engine_bytes = (engine_dir / name).read_bytes()
            assert legacy_bytes == engine_bytes, f"{fmt.name} output diverged"

    def test_json_structure_matches_legacy_keys(self, tmp_path, monkeypatch):
        import json

        legacy_dir = _legacy_pipeline(tmp_path)
        bundle = _engine_bundle(monkeypatch)
        engine_dir = tmp_path / "engine2"
        ReportService(output_dir=str(engine_dir)).export(
            bundle, requested={ReportFormat.JSON: FIXED_FILENAMES[ReportFormat.JSON]},
            device_info=DEVICE_INFO,
        )
        legacy_doc = json.loads((legacy_dir / "parity.json").read_text(encoding="utf-8"))
        engine_doc = json.loads((engine_dir / "parity.json").read_text(encoding="utf-8"))
        assert list(legacy_doc) == list(engine_doc)
        assert list(legacy_doc["summary"]) == list(engine_doc["summary"])
        assert legacy_doc["high_risk_apps"] == engine_doc["high_risk_apps"]
        legacy_app = legacy_doc["apps"][0]
        engine_app = engine_doc["apps"][0]
        assert list(legacy_app) == list(engine_app)
        assert legacy_app["dangerous_permissions"] == engine_app["dangerous_permissions"]


class TestDefaultNaming:
    def test_default_report_filename_follows_legacy_convention(self, monkeypatch):
        monkeypatch.setattr(time, "strftime",
                            lambda fmt, *_a, **_k: "20260101_123045")
        from vscanner.services.reports.service import default_report_filename

        assert default_report_filename() == "security_report_20260101_123045.json"
        assert default_report_filename("custom", ".html") == "custom.html"
        assert default_report_filename("custom.html", ".html") == "custom.html"

    def test_export_shared_timestamp_base(self, tmp_path, monkeypatch):
        """None-filenames in one export share a single generated base (legacy
        ``generate_all`` semantics) rather than three racing clock reads."""
        monkeypatch.setattr("vscanner.services.reports.service.datetime",
                            _FrozenDatetime)
        bundle = _MinimalBundleFactory.bundle()
        service = ReportService(output_dir=str(tmp_path / "out"))
        result = service.export(bundle, requested={fmt: None for fmt in ReportFormat})
        assert result.ok is True
        stems = {Path(p).stem for p in result.formats_written.values()}
        # One shared "security_report_<ts>" base across all three formats.
        assert len(stems) == 1


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_AWARE


class _MinimalBundleFactory:
    @staticmethod
    def bundle() -> ScanResultBundle:
        from vscanner.core.models import AppInfo, AppScanResult, ScanLifecycleState

        request = ScanRequest(kind=ScanKind.SINGLE_APP)
        run = ScanRun(request=request, state=ScanLifecycleState.COMPLETED,
                      started_at=FIXED_AWARE)
        session = ScanSummary(run=run, total_apps=1)
        return ScanResultBundle(
            summary=session,
            apps=(AppScanResult(app=AppInfo(package_name="com.a")),),
        )


class TestExportFailureHonesty:
    def test_unwritable_directory_raises_export_error(self, tmp_path):
        bundle = _MinimalBundleFactory.bundle()
        blocker = tmp_path / "parity.json"
        blocker.write_text("pretend directory", encoding="utf-8")
        # A *file* occupies the path where the report directory would be:
        requested = {ReportFormat.JSON: "not_used.json"}
        wrong = ReportService(output_dir=str(blocker))
        with pytest.raises(ExportError):
            wrong.export(bundle, requested=requested, output_dir=str(blocker / "sub"))

    def test_partial_failure_reports_what_was_written(self, tmp_path, monkeypatch):
        bundle = _MinimalBundleFactory.bundle()
        out = tmp_path / "out"
        out.mkdir()
        # Occupy one target filename as a directory → that write must fail,
        # the other two must still be produced and reported honestly.
        (out / "clash.html").mkdir()
        service = ReportService(output_dir=str(out))
        result = service.export(bundle, requested={
            ReportFormat.JSON: "good.json",
            ReportFormat.HTML: "clash.html",
            ReportFormat.TEXT: "good.text",
        })
        assert result.ok is True
        assert "HTML" in result.error
        assert set(result.formats_written) == {"JSON", "TEXT"}

    def test_total_failure_raises(self, tmp_path):
        bundle = _MinimalBundleFactory.bundle()
        (tmp_path / "a.json").mkdir()
        (tmp_path / "b.text").mkdir()
        service = ReportService(output_dir=str(tmp_path))
        with pytest.raises(ExportError):
            service.export(bundle, requested={
                ReportFormat.JSON: "a.json",
                ReportFormat.TEXT: "b.text",
            })
