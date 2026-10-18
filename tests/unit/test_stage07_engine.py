"""Stage 07 engine additions: T-08 scan history + scan jobs through the
real Stage 04 pipeline (demo dataset, cancellation, conflicts, export).

Deterministic demo-scan evidence (ROADMAP Stage 07): a fully faked
transport replays the Stage 03 dumpsys fixture; the typed findings that
stream through the job events must match the final bundle exactly, and a
mid-scan cancellation must produce exactly one CANCELLED terminal with
honest partial streaming. No real device, root, or network is touched.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from vscanner.core.errors import ExportError, InputValidationError
from vscanner.core.events import (
    JobFindingEvent,
    JobKind,
    JobProgressEvent,
    JobState,
    JobTerminalEvent,
)
from vscanner.core.models import (
    AppScanResult,
    ExportResult,
    ReportFormat,
    ScanConfiguration,
    ScanKind,
    ScanRequest,
)
from vscanner.services.history import (
    CAP,
    HistoryEntry,
    HistoryStoreError,
    ScanHistoryStore,
)
from vscanner.services.jobs import JobManager
from vscanner.services.orchestration import (
    export_reports_plan,
    full_device_scan_plan,
    single_app_scan_plan,
)
from vscanner.services.reports.service import ReportService
from vscanner.services.scanning.scanner import ScanService, validate_package_name

import test_services_scanning  # sibling test module (shares the golden fixture)

DUMPSYS_FIXTURE = test_services_scanning.DUMPSYS_FIXTURE


class _Result:
    def __init__(self, stdout: str = "", stderr: str = "",
                 returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class _FakeTransport:
    """run_text-shaped transport faking the engine's only ADB seam."""

    def __init__(self, packages: dict,
                 block_first_dumpsys: threading.Event | None = None):
        self.packages = dict(packages)
        self.blocker = block_first_dumpsys
        self.blocked_seen = threading.Event()
        self.calls: list = []

    def run_text(self, cmd, timeout: float = 30.0):
        key = " ".join(str(c) for c in cmd)
        self.calls.append(key)
        if "pm list packages" in key:
            names = set(self.packages)
            return _Result("\n".join(f"package:{p}" for p in names) + "\n")
        if key.startswith("shell dumpsys package "):
            pkg = key.rsplit(" ", 1)[1]
            if self.blocker is not None and pkg in self.packages:
                self.packages.pop(pkg)  # one-shot: only the FIRST dump blocks
                self.blocked_seen.set()
                self.blocker.wait(timeout=2.0)
            return _Result(self.packages.get(pkg, "no useful lines here"))
        return _Result("")


def _demo_request(serial: str = "SER1"):
    return ScanRequest(
        kind=ScanKind.FULL_DEVICE,
        config=ScanConfiguration(
            include_system=False, device_serial=serial,
        ),
    )


def _run_bundle_scan(service: ScanService, serial: str = "SER1"):
    """Submit the FULL_DEVICE_SCAN plan; return (handle, events)."""
    events: list = []
    manager = JobManager()
    manager.subscribe(events.append)
    handle = manager.submit(
        JobKind.FULL_DEVICE_SCAN,
        device_serial=serial,
        plan=full_device_scan_plan(service, _demo_request(serial)),
    )
    handle.wait(5)
    manager.shutdown()
    return handle, events


class TestScanThroughJobPipeline:
    def test_demo_dataset_streams_findings_matching_stage03_fixture(self):
        """AC [T]: a faked demo scan produces typed Findings identical to
        the Stage 03 fixtures through the job pipeline."""
        transport = _FakeTransport({"com.example.wallet": DUMPSYS_FIXTURE})
        service = ScanService(transport)
        handle, events = _run_bundle_scan(service)
        assert handle.state is JobState.SUCCEEDED
        terminals = [e for e in events if isinstance(e, JobTerminalEvent)]
        assert len(terminals) == 1
        assert terminals[0].outcome is JobState.SUCCEEDED
        bundle = terminals[0].result
        live_stream = [e.finding for e in events if isinstance(e, JobFindingEvent)]
        bundle_findings = [
            f for result in bundle.apps for f in result.findings
        ]
        assert [f.id for f in live_stream] == [f.id for f in bundle_findings], \
            "the streamed findings must be exactly the bundle's findings"
        # The golden fixture's typed shape (Stage 03 anchor values):
        assert any(
            finding.kind.value == "permission_excess"
            and finding.severity.value == "CRITICAL"
            and "READ_SMS" in finding.title
            for finding in bundle_findings
        )
        assert any(
            finding.kind.value == "sdk_compat"
            and "SDK advisory" in finding.title
            for finding in bundle_findings
        )

    def test_progress_events_reflect_engine_truth(self):
        transport = _FakeTransport({"com.example.wallet": DUMPSYS_FIXTURE})
        service = ScanService(transport)
        handle, events = _run_bundle_scan(service)
        progress = [e for e in events if isinstance(e, JobProgressEvent)]
        assert progress
        last = progress[-1]
        assert (last.current, last.total, last.unit) == (1, 1, "apps")
        assert last.context == "com.example.wallet"
        assert handle.state is JobState.SUCCEEDED

    def test_cancellation_mid_scan_is_honoured_with_honest_partial_stream(self):
        """AC [T]: cancel mid-scan works; terminal truth is exactly one
        CANCELLED event and the plan never reports success."""
        gate = threading.Event()        # holds the first dumpsys
        blocked_seen = threading.Event()
        packages = {"com.example.wallet": DUMPSYS_FIXTURE}

        events: list = []
        manager = JobManager()
        manager.subscribe(events.append)

        def transport_run(cmd, timeout: float = 30.0):
            key = " ".join(str(c) for c in cmd)
            if "pm list packages" in key:
                return _Result("\n".join(f"package:{p}" for p in packages) + "\n")
            if key.startswith("shell dumpsys package "):
                blocked_seen.set()
                gate.wait(timeout=2.0)  # deterministic hold point
                pkg = key.rsplit(" ", 1)[1]
                return _Result(packages.get(pkg, "no useful lines here"))
            return _Result("")

        class _Transport:
            run_text = staticmethod(transport_run)

        handle = manager.submit(
            JobKind.FULL_DEVICE_SCAN,
            device_serial="SER1",
            plan=full_device_scan_plan(
                ScanService(_Transport()), _demo_request()),
        )
        try:
            assert blocked_seen.wait(5), "first dumpsys never started"
            handle.cancel()  # REQUEST armed while the command is in flight
            gate.set()       # the engine's next checkpoint acknowledges it
            state = handle.wait(5)
            assert state is JobState.CANCELLED
            terminals = [e for e in events if isinstance(e, JobTerminalEvent)]
            assert len(terminals) == 1
            assert terminals[0].outcome is JobState.CANCELLED
            assert terminals[0].at_cancellation_point in (
                "between_apps", "after_progress_emit")
            assert not [e for e in terminals
                        if e.outcome is JobState.SUCCEEDED]
            # partial honesty: everything streamed before the stop was real;
            # for this single-app dataset the full app streamed before the
            # between-apps checkpoint stopped the scan
            streamed = [e.finding for e in events
                        if isinstance(e, JobFindingEvent)]
            streamed_ids = [f.id[:8] for f in streamed]
            assert streamed_ids == [
                "a0af51ee", "1256caf8", "ea90175a", "a0af51ee", "c848e8e8",
            ], streamed_ids
        finally:
            gate.set()
            manager.shutdown()

    def test_overlapping_scan_on_one_device_is_refused(self):
        gate = threading.Event()
        _events: list = []
        manager = JobManager()
        manager.subscribe(_events.append)
        try:
            manager.submit(
                JobKind.FULL_DEVICE_SCAN,
                device_serial="SER1",
                plan=lambda ctx: gate.wait(5),
            )
            time.sleep(0.05)
            with pytest.raises(Exception) as excinfo:
                manager.submit(
                    JobKind.FULL_DEVICE_SCAN,
                    device_serial="SER1",
                    plan=lambda ctx: "never",
                )
            assert "conflict" in str(excinfo.value).lower()
        finally:
            gate.set()
            manager.shutdown()

    def test_bad_package_name_is_rejected_before_the_device_is_touched(self):
        with pytest.raises(InputValidationError):
            validate_package_name("bad name!")


class TestSingleAppJob:
    def test_single_app_plan_returns_a_typed_result(self):
        transport = _FakeTransport({"com.example.wallet": DUMPSYS_FIXTURE})
        service = ScanService(transport)
        events: list = []
        manager = JobManager()
        manager.subscribe(events.append)
        handle = manager.submit(
            JobKind.SINGLE_APP_SCAN,
            device_serial="SER1",
            plan=single_app_scan_plan(
                service, "com.example.wallet",
                config=ScanConfiguration(device_serial="SER1"),
            ),
        )
        try:
            assert handle.wait(5) is JobState.SUCCEEDED
            terminal = [e for e in events
                        if isinstance(e, JobTerminalEvent)][0]
            result = terminal.result
            assert isinstance(result, AppScanResult)
            assert result.app is not None and result.findings
            # single-app analysis has NO intermediate progress (documented);
            # the UI must never fabricate one from nothing.
            assert not [e for e in events if isinstance(e, JobProgressEvent)]
        finally:
            manager.shutdown()

    def test_unwritable_package_name_reaches_a_failed_terminal(self):
        transport = _FakeTransport({"com.example.wallet": DUMPSYS_FIXTURE})
        service = ScanService(transport)
        events: list = []
        manager = JobManager()
        manager.subscribe(events.append)
        handle = manager.submit(
            JobKind.SINGLE_APP_SCAN,
            device_serial="SER1",
            plan=single_app_scan_plan(service, "not valid!!"),
        )
        try:
            assert handle.wait(5) is JobState.FAILED
            terminal = [e for e in events
                        if isinstance(e, JobTerminalEvent)][0]
            assert terminal.error is not None
            assert "package" in terminal.error.message.lower()
        finally:
            manager.shutdown()


class TestScanHistoryStore:
    def test_roundtrip_writes_schema_fields_and_reads_back(self, tmp_path):
        store = ScanHistoryStore(tmp_path / "history")
        path = store.append(HistoryEntry(
            scan_id="a" * 32,
            kind="full_device",
            status="completed",
            device_serial="SER1",
            total_apps=2,
            findings_total=5,
            severity_counts={"critical": 2, "high": 1},
        ))
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["created_by"].startswith("vscanner/")
        assert payload["scan_id"] == "a" * 32
        recent = store.recent()
        assert len(recent) == 1
        assert recent[0].kind == "full_device"
        assert recent[0].severity_counts_complete()["critical"] == 2

    def test_retention_cap_prunes_oldest_records(self, tmp_path):
        store = ScanHistoryStore(tmp_path / "history")
        for index in range(CAP + 4):
            store.append(HistoryEntry(
                scan_id=f"{index:032d}",
                kind="full_device",
                status="completed",
                finished_at_utc=f"2026-01-01T00:00:{index:02d}Z",
            ))
        entries = store.recent(limit=100)
        assert len(entries) == CAP
        pruned = {f"{index:032d}" for index in range(4)}
        assert {e.scan_id for e in entries}.isdisjoint(pruned)

    def test_read_tolerates_corrupt_files(self, tmp_path):
        store = ScanHistoryStore(tmp_path / "history")
        store.append(HistoryEntry(
            scan_id="b" * 32, kind="full_device", status="completed"))
        (tmp_path / "history" / "garbage.json").write_text(
            "{definitely not json", encoding="utf-8")
        entries = store.recent()
        assert len(entries) == 1 and entries[0].scan_id == "b" * 32

    def test_unwritable_location_raises_a_typed_error(self, tmp_path):
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("I am a file", encoding="utf-8")
        store = ScanHistoryStore(blocker / "history")
        with pytest.raises(HistoryStoreError):
            store.append(HistoryEntry(
                scan_id="c" * 32, kind="full_device", status="completed"))

    def test_records_carry_no_finding_text_or_secret_material(self, tmp_path):
        """T-08 [T]: the persisted record shape is counters/ids only."""
        store = ScanHistoryStore(tmp_path / "history")
        path = store.append(HistoryEntry(
            scan_id="d" * 32, kind="single_app", status="cancelled",
            device_serial="SER1", findings_total=3,
        ))
        payload = json.loads(path.read_text(encoding="utf-8"))
        flat = json.dumps(payload).lower()
        for word in ("findings", "evidence", "raw_excerpt", "detail",
                     "permission", "psk", "password", "token", "secret"):
            assert f'"{word}"' not in flat, \
                f"history must not store '{word}' material"


class TestExportIntegration:
    @staticmethod
    def _golden_bundle():
        transport = _FakeTransport({"com.example.wallet": DUMPSYS_FIXTURE})
        service = ScanService(transport)
        handle, events = _run_bundle_scan(service)
        terminal = [e for e in events if isinstance(e, JobTerminalEvent)][0]
        return terminal.result

    def test_export_plan_writes_all_three_formats_through_the_service(
        self, tmp_path,
    ) -> None:
        bundle = self._golden_bundle()
        out_dir = tmp_path / "exported"
        events: list = []
        manager = JobManager()
        manager.subscribe(events.append)
        manager.submit(
            JobKind.EXPORT,
            plan=export_reports_plan(ReportService(str(out_dir)), bundle),
        ).wait(5)
        terminal = [e for e in events if isinstance(e, JobTerminalEvent)][0]
        assert terminal.outcome is JobState.SUCCEEDED
        export = terminal.result
        assert isinstance(export, ExportResult)
        assert export.ok is True
        assert set(export.formats_written) == {"HTML", "JSON", "TEXT"}
        for path in export.formats_written.values():
            assert Path(path).exists() and Path(path).stat().st_size > 0

    def test_export_bytes_are_identical_to_a_direct_service_export(
        self, tmp_path,
    ) -> None:
        """ROADMAP Stage 07: byte-identical to the legacy-format report for
        the same input — the TUI path adds no serialization of its own."""
        bundle = self._golden_bundle()
        via_service = tmp_path / "via_service"
        direct = tmp_path / "direct"
        base = datetime.now().strftime("%Y%m%d_%H%M%S_test")
        direct_result = ReportService(str(direct)).export(
            bundle,
            requested={fmt: f"{base}.{fmt.suffix}" for fmt in ReportFormat},
        )
        assert direct_result.ok
        events: list = []
        manager = JobManager()
        manager.subscribe(events.append)
        manager.submit(
            JobKind.EXPORT,
            plan=export_reports_plan(
                ReportService(str(via_service)), bundle,
                requested={fmt: None for fmt in ReportFormat},
            ),
        ).wait(5)
        terminal = [e for e in events if isinstance(e, JobTerminalEvent)][0]
        assert terminal.outcome is JobState.SUCCEEDED
        json_via = next(
            p for p in via_service.iterdir() if p.suffix == ".json")
        json_direct = Path(direct_result.formats_written["JSON"])
        assert json_via.read_bytes() == json_direct.read_bytes()

    def test_unwritable_destination_never_reports_success(self, tmp_path):
        destination = tmp_path / "blocked"
        destination.write_text("this is a file", encoding="utf-8")
        bundle = self._golden_bundle()
        events: list = []
        manager = JobManager()
        manager.subscribe(events.append)
        manager.submit(
            JobKind.EXPORT,
            plan=export_reports_plan(
                ReportService(str(destination / "x")), bundle),
        ).wait(5)
        terminal = [e for e in events if isinstance(e, JobTerminalEvent)][0]
        assert terminal.outcome is JobState.FAILED
        assert terminal.error is not None and terminal.error.message
        with pytest.raises(ExportError):
            ReportService(str(destination / "y")).export(bundle)
