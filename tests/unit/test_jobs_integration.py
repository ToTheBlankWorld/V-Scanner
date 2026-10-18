"""Stage 04 integration tests — job system around Stage 03 services.

Device-free: the ADB transport, downloads and the report output directory are
faked/tmp. Verifies that the JobManager + orchestration seam preserves the
Stage 03 result contracts (result/schema parity), streams the documented
events, and honors the documented cancellation boundaries — without touching
the legacy CLI (backward-compat guard at the bottom).
"""

from __future__ import annotations

import ast
import io
import json
import threading
import zipfile
from pathlib import Path

import pytest

from vscanner.core.errors import JobConflictError
from vscanner.core.events import (
    JobFindingEvent,
    JobKind,
    JobLogChunkEvent,
    JobProgressEvent,
    JobStartedEvent,
    JobState,
    JobTerminalEvent,
)
from vscanner.core.models import (
    Finding,
    ScanConfiguration,
    ScanKind,
    ScanRequest,
    ToolId,
    ToolState,
)
from vscanner.services.jobs import JobManager
from vscanner.services.orchestration import (
    app_listing_plan,
    export_reports_plan,
    full_device_scan_plan,
    single_app_scan_plan,
    tool_provisioning_plan,
)
from vscanner.services.reports.service import ReportService
from vscanner.services.scanning.scanner import ScanService
from vscanner.services.tools import provisioning as provisioning_module
from vscanner.services.tools.manifest import ToolManifest, ToolSpec
from vscanner.services.tools.provisioning import ToolProvisioningService


# ---------------------------------------------------------------------------
# fake transports (same shape the Stage 03 suite uses)
# ---------------------------------------------------------------------------

class _Result:
    def __init__(self, stdout: str = "", stderr: str = "", code: int = 0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, code


class FakeTransport:
    """Replays (stdout, stderr, code) tuples; the last entry repeats."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.commands: list[list[str]] = []

    def run_text(self, cmd, timeout=30.0):
        self.commands.append(list(cmd))
        if len(self._responses) > 1:
            stdout, stderr, code = self._responses.pop(0)
        else:
            stdout, stderr, code = self._responses[0]
        return _Result(stdout, stderr, code)


DUMPSYS = (
    "Package [com.example.wallet] (1fd2...):\n"
    "  versionName=2.1.0\n  versionCode=210\n  targetSdk=28\n  minSdk=23\n"
    "  requested permissions:\n"
    "    android.permission.INTERNET\n"
    "    android.permission.READ_SMS\n"
)

_LISTING = "package:com.a\npackage:com.b"


def _scan_service(responses=None) -> ScanService:
    if responses is None:
        responses = [
            (_LISTING, "", 0),
            (DUMPSYS, "", 0),
            ("", "", 0),
        ]
    return ScanService(FakeTransport(responses))


def _request() -> ScanRequest:
    return ScanRequest(
        kind=ScanKind.FULL_DEVICE,
        config=ScanConfiguration(device_serial="demo"),
    )


# ---------------------------------------------------------------------------
# full-device scan through the job system
# ---------------------------------------------------------------------------

class TestScanThroughJobs:
    def test_scan_job_success_stream_and_result_parity(self):
        events: list = []
        mgr = JobManager()
        mgr.subscribe(events.append)

        svc = _scan_service()
        request = _request()
        handle = mgr.submit(
            JobKind.FULL_DEVICE_SCAN,
            device_serial="demo",
            plan=full_device_scan_plan(svc, request),
        )
        assert handle.wait(10) is JobState.SUCCEEDED

        started = [e for e in events if isinstance(e, JobStartedEvent)]
        assert started and started[0].device_serial == "demo"
        progresses = [e for e in events if isinstance(e, JobProgressEvent)]
        assert [p.current for p in progresses] == [1, 2]
        assert all(p.total == 2 for p in progresses)
        assert all(p.unit == "apps" for p in progresses)
        assert [p.context for p in progresses] == ["com.a", "com.b"]
        findings = [e for e in events if isinstance(e, JobFindingEvent)]
        assert len(findings) == 3  # 1 READ_SMS + SDK baseline per app bundle
        terminals = [e for e in events if isinstance(e, JobTerminalEvent)]
        assert len(terminals) == 1
        bundle = terminals[0].result
        assert [r.app.package_name for r in bundle.apps] == ["com.a", "com.b"]
        assert bundle.high_risk_apps == 1
        # Log-lane subprocess note recorded (context.log from the service)
        logs = [e for e in events if isinstance(e, JobLogChunkEvent)]
        assert logs and logs[0].level == "info"

    def test_scan_job_result_matches_direct_service_call(self):
        request = _request()
        direct_bundle = _scan_service().scan_full_device(request)

        holder: dict = {}
        mgr = JobManager()

        def sink(event):
            if isinstance(event, JobTerminalEvent) and event.outcome is JobState.SUCCEEDED:
                holder["result"] = event.result

        mgr.subscribe(sink)
        handle = mgr.submit(
            JobKind.FULL_DEVICE_SCAN,
            device_serial="demo",
            plan=full_device_scan_plan(_scan_service(), request),
        )
        handle.wait(10)
        job_bundle = holder["result"]
        # Schema/result parity (timestamps legitimately differ):
        assert [r.app.package_name for r in job_bundle.apps] == \
               [r.app.package_name for r in direct_bundle.apps]
        for job_res, direct_res in zip(job_bundle.apps, direct_bundle.apps):
            assert job_res.app.package_name == direct_res.app.package_name
            assert [f.title for f in job_res.findings] == \
                   [f.title for f in direct_res.findings]
            assert [(f.title, f.severity) for f in job_res.findings] == \
                   [(f.title, f.severity) for f in direct_res.findings]
            assert job_res.scan_skipped_reason == direct_res.scan_skipped_reason
        # summary parity (counts; timing fields legitimately differ)
        assert job_bundle.summary.total_apps == direct_bundle.summary.total_apps
        assert job_bundle.summary.high_risk == direct_bundle.summary.high_risk
        assert job_bundle.summary.findings_total == direct_bundle.summary.findings_total
        assert job_bundle.summary.skipped_apps == direct_bundle.summary.skipped_apps

    def test_finding_events_carry_immutable_typed_findings(self):
        events: list = []
        mgr = JobManager()
        mgr.subscribe(events.append)
        svc = _scan_service()
        handle = mgr.submit(
            JobKind.FULL_DEVICE_SCAN, device_serial="demo",
            plan=full_device_scan_plan(svc, _request()),
        )
        handle.wait(10)
        for event in (e for e in events if isinstance(e, JobFindingEvent)):
            assert isinstance(event.finding, Finding)
            with pytest.raises(Exception):
                event.finding.title = "mutated"

    def test_cancel_between_apps_never_reports_completeness(self):
        """Deterministic cancellation: the FIRST finding event delivery
        requests cancellation; the very next checkpoint
        (``after_progress_emit``) stops the plan — mid-scan, so no
        "all apps done" claim can ever surface."""
        events: list = []
        mgr = JobManager()
        mgr.subscribe(events.append)
        svc = _scan_service()
        handle_holder: dict = {}

        def canceller(event):
            if isinstance(event, JobFindingEvent):
                handle_holder["h"].cancel()

        mgr.subscribe(canceller)
        handle = mgr.submit(
            JobKind.FULL_DEVICE_SCAN, device_serial="demo",
            plan=full_device_scan_plan(svc, _request()),
        )
        handle_holder["h"] = handle
        assert handle.wait(10) is JobState.CANCELLED
        terminals = [e for e in events if isinstance(e, JobTerminalEvent)]
        assert len(terminals) == 1
        terminal = terminals[0]
        assert terminal.outcome is JobState.CANCELLED
        assert terminal.at_cancellation_point == "after_progress_emit"
        assert terminal.result is None  # partial work is not a result
        # The scan never emitted a terminal SUCCEEDED anywhere.
        assert all(e.outcome is not JobState.SUCCEEDED for e in terminals)

    def test_transport_timeout_mid_scan_is_honest_skips_not_success_lies(self):
        """Per-app ADB timeout mid-scan (the fake transport replaces the
        in-flight subprocess per contract §6): the app-level failure becomes
        a recorded skip — never a fabricated "clean" result and never a
        crash into FAILED (per-app isolation, Stage 03 semantics preserved
        under the job layer)."""
        from vscanner.core.errors import AdbCommandError

        events: list = []
        mgr = JobManager()
        mgr.subscribe(events.append)

        class _Transport(FakeTransport):
            def run_text(self, cmd, timeout=30.0):
                if any(a == "dumpsys" for a in cmd):
                    raise AdbCommandError("command timed out", timeout=True)
                return super().run_text(cmd, timeout)

        svc = ScanService(_Transport([(_LISTING, "", 0), ("", "", 0)]))
        handle = mgr.submit(
            JobKind.FULL_DEVICE_SCAN, device_serial="demo",
            plan=full_device_scan_plan(svc, _request()),
        )
        assert handle.wait(10) is JobState.SUCCEEDED
        terminals = [e for e in events if isinstance(e, JobTerminalEvent)]
        bundle = terminals[-1].result
        assert [r.app.package_name for r in bundle.apps] == ["com.a", "com.b"]
        assert all(r.scan_skipped_reason for r in bundle.apps)
        assert all("timed out" in r.scan_skipped_reason for r in bundle.apps)
        assert bundle.summary.skipped_apps and bundle.summary.findings_total == 0
        assert not [e for e in events if isinstance(e, JobFindingEvent)]

    def test_listing_and_single_app_plans(self):
        mgr = JobManager()
        listing = mgr.submit(
            JobKind.APP_LISTING, device_serial="demo",
            plan=app_listing_plan(
                _scan_service([(_LISTING, "", 0)]).inventory, include_system=False
            ),
        )
        state = listing.wait(10)
        assert state is JobState.SUCCEEDED
        # Direct result retrieval via the terminal event payload.
        events: list = []
        mgr.subscribe(events.append)
        single = mgr.submit(
            JobKind.SINGLE_APP_SCAN, device_serial="demo",
            plan=single_app_scan_plan(_scan_service([(DUMPSYS, "", 0)]), "com.example.wallet"),
        )
        assert single.wait(10) is JobState.SUCCEEDED
        terminal = [e for e in events if isinstance(e, JobTerminalEvent)][-1]
        assert terminal.result.app.package_name == "com.example.wallet"


# ---------------------------------------------------------------------------
# tool provisioning through the job system
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: bytes, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def read(self, size=-1):
        if size == -1:
            data, self._payload = self._payload, b""
        else:
            data, self._payload = self._payload[:size], self._payload[size:]
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


SCRCPY_MANIFEST = ToolManifest(entries=(
    ToolSpec(tool=ToolId.SCRCPY, platform_os="windows", arch=None,
             download_url=None, sha256=None, archive_format="zip"),
))


def _zip_bytes(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, blob in members.items():
            zf.writestr(name, blob)
    return buf.getvalue()


def _api_response(asset="scrcpy-9.0-win64.zip"):
    release = json.dumps({"assets": [{"name": asset,
                                      "browser_download_url": f"https://example.invalid/{asset}"}]})
    return ({}, release.encode("utf-8"))


def _provisioning_service(tools_dir: Path, responses):
    calls = []

    def opener(url, timeout):
        calls.append(url)
        payload_type, payload = responses.pop(0)
        headers = payload_type.get("headers") if isinstance(payload_type, dict) else None
        return _FakeResponse(payload, headers=headers)

    service = ToolProvisioningService(
        tools_dir=tools_dir, manifest=SCRCPY_MANIFEST,
        url_opener=opener, platform_system="Windows",
        platform_arch="AMD64",
    )
    service.calls = calls  # type: ignore[attr-defined]
    return service


class TestProvisioningThroughJobs:
    def test_provisioning_job_success_with_byte_progress(self, tmp_path):
        events: list = []
        mgr = JobManager()
        mgr.subscribe(events.append)
        tools = tmp_path / "tools"
        svc = _provisioning_service(tools, [
            _api_response(),
            ("bin", _zip_bytes({"scrcpy-9.0/scrcpy.exe": b"MZ fake"})),
        ])
        handle = mgr.submit(
            JobKind.TOOL_PROVISIONING, plan=tool_provisioning_plan(svc, ToolId.SCRCPY),
        )
        assert handle.wait(15) is JobState.SUCCEEDED
        progresses = [e for e in events if isinstance(e, JobProgressEvent)]
        assert progresses and progresses[-1].unit == "bytes"
        assert progresses[-1].current > 0
        terminals = [e for e in events if isinstance(e, JobTerminalEvent)]
        assert terminals[-1].result.state in (ToolState.FOUND_UNVALIDATED, ToolState.VALIDATED)
        assert (tools / "scrcpy" / "scrcpy.exe").exists()
        staging = tools / ".staging"
        assert not any(staging.iterdir())  # staged artifacts drained

    def test_cancel_mid_download_discards_staging_and_reports_cancelled(self, tmp_path):
        events: list = []
        mgr = JobManager()
        mgr.subscribe(events.append)
        tools = tmp_path / "tools"
        # > 2 download chunks, so the cancel request (fired from the first
        # progress event) lands at a chunk-boundary checkpoint.
        filler = b"A" * (2 * provisioning_module.CHUNK_SIZE + 1024)
        svc = _provisioning_service(tools, [
            _api_response(),
            ("bin", _zip_bytes({"scrcpy-9.0/scrcpy.exe": filler})),
        ])
        hold: dict = {}

        def canceller(event):
            if isinstance(event, JobProgressEvent) and event.unit == "bytes":
                hold["h"].cancel()  # request arrives between chunks

        mgr.subscribe(canceller)
        handle = mgr.submit(
            JobKind.TOOL_PROVISIONING,
            plan=tool_provisioning_plan(svc, ToolId.SCRCPY),
        )
        hold["h"] = handle
        assert handle.wait(15) is JobState.CANCELLED
        terminals = [e for e in events if isinstance(e, JobTerminalEvent)]
        assert len(terminals) == 1
        terminal = terminals[0]
        assert terminal.outcome is JobState.CANCELLED
        assert terminal.at_cancellation_point == "during_download"
        assert terminal.result is None
        # Staged archive discarded by the cleanup (honest partial state).
        staging = tools / ".staging"
        assert not any(staging.iterdir())
        assert not (tools / "scrcpy").exists()  # nothing installed

    def test_provisioning_conflict_blocks_second_job(self, tmp_path):
        mgr = JobManager(max_workers=1)
        gate = threading.Event()
        tools = tmp_path / "tools"
        svc = _provisioning_service(tools, [
            _api_response(),
            ("bin", _zip_bytes({"scrcpy-9.0/scrcpy.exe": b"MZ"})),
        ])

        def plan(context):
            gate.wait(15)
            return tool_provisioning_plan(svc, ToolId.SCRCPY)(context)

        first = mgr.submit(JobKind.TOOL_PROVISIONING, plan=plan)
        with pytest.raises(JobConflictError):
            mgr.submit(
                JobKind.TOOL_PROVISIONING,
                plan=tool_provisioning_plan(svc, ToolId.SCRCPY),
            )
        gate.set()
        assert first.wait(15) is JobState.SUCCEEDED


# ---------------------------------------------------------------------------
# export jobs
# ---------------------------------------------------------------------------

class TestExportThroughJobs:
    def test_export_job_preserves_report_schema_and_files(self, tmp_path):
        events: list = []
        mgr = JobManager()
        mgr.subscribe(events.append)
        svc = _scan_service()
        bundle = svc.scan_full_device(_request())
        reports = ReportService(output_dir=str(tmp_path / "out"))
        handle = mgr.submit(
            JobKind.EXPORT,
            plan=export_reports_plan(reports, bundle),
        )
        assert handle.wait(15) is JobState.SUCCEEDED
        out = tmp_path / "out"
        files = sorted(p.name for p in out.iterdir())
        assert any(n.startswith("security_report_") and n.endswith(".html") for n in files)
        assert any(n.startswith("security_report_") and n.endswith(".json") for n in files)
        assert any(n.startswith("security_report_") and n.endswith(".text") for n in files)
        terminals = [e for e in events if isinstance(e, JobTerminalEvent)]
        assert terminals[-1].result.ok is True
        assert sorted(terminals[-1].result.formats_written) == [
            "HTML", "JSON", "TEXT"
        ]
        for written in terminals[-1].result.formats_written.values():
            assert (tmp_path / "out" / Path(written).name).exists()


# ---------------------------------------------------------------------------
# layering/architecture guards (job layer adoption is optional downstream)
# ---------------------------------------------------------------------------

VSCANNER_ROOT = Path(__file__).resolve().parents[2] / "vscanner"
CLI_ROOT = Path(__file__).resolve().parents[2] / "cli"
UI_ROOTS = [
    Path(__file__).resolve().parents[2] / "ui_terminal",
    Path(__file__).resolve().parents[2] / "ui_desktop",
]


def _iter_py(root: Path):
    for path in sorted(root.rglob("*.py")):
        yield path


class TestLayering:
    def test_legacy_cli_never_imports_the_job_layer(self):
        """Backward-compat guard: the legacy CLI keeps its direct service
        calls; adoption of the job layer is the Stage 05+ UI decision."""
        forbidden = {"vscanner.services.jobs", "vscanner.services.orchestration"}
        for path in _iter_py(CLI_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = set()
                if isinstance(node, ast.Import):
                    names = {alias.name for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = {node.module}
                assert not (names & forbidden), \
                    f"{path.name} must not import {names & forbidden}"

    def test_ui_packages_are_not_reachable_from_the_engine(self):
        """The interfaces layer consumes the engine — never the reverse."""
        for path in _iter_py(VSCANNER_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    text = (node.module or "") if isinstance(node, ast.ImportFrom) else ""
                    if isinstance(node, ast.Import):
                        text = " ".join(alias.name for alias in node.names)
                    assert "ui_terminal" not in text and "ui_desktop" not in text, path

    def test_bridge_stubs_import_no_gui_frameworks(self):
        """Stage 04 layering evolution (Stage 05): ui_terminal may import
        Textual/Rich (its documented presentation frameworks, A-03); the qt
        bridge stub (ui_desktop) and every UI package must stay clear of
        other cross-platform GUI frameworks."""
        forbidden_everywhere = ("PySide6", "tkinter", "streamlit", "flask")
        forbidden_in_desktop = forbidden_everywhere + ("textual", "rich")
        desktop_root = UI_ROOTS[1]
        for root in UI_ROOTS:
            forbidden = forbidden_in_desktop if root == desktop_root else forbidden_everywhere
            for path in _iter_py(root):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            assert alias.name.split(".")[0] not in forbidden, \
                                f"{path.name} imports forbidden framework"
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        assert node.module.split(".")[0] not in forbidden, \
                            f"{path.name} imports forbidden framework"
