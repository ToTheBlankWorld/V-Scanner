"""Reports & scan-history screen tests (Stage 07).

The reports screen never serializes anything itself: export must go
through the shared service (via the backend export job) and history must
come from the T-08 store through the backend. These tests pin the honest
seam behavior with the same scripted backend the scan screen uses — no
subprocess, no real device, no real filesystem writes.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import List

from textual.widgets import DataTable, Input, Label

from ui_terminal.app import VScannerApp
from ui_terminal.screens.reports import ReportsScreen
from vscanner.core.errors import InputValidationError
from vscanner.core.events import JobState, JobTerminalEvent
from vscanner.services.config import ConfigService
from vscanner.services.history import HistoryEntry

from test_scan_screen import (  # flat sibling import (no package here)
    FakeScanBackend,
    _bundle,
    _text_of,
    _until,
)


# -- helpers ------------------------------------------------------------------ #

def _entry(status: str = "completed", serial: str = "S1",
           scan_id: str = "req-1", kind: str = "full_device",
           ) -> HistoryEntry:
    return HistoryEntry(
        scan_id=scan_id, kind=kind, status=status, device_serial=serial,
        finished_at_utc="2026-10-18T00:00:00+00:00",
        total_apps=2, findings_total=2,
    )


async def open_reports(pilot, backend: FakeScanBackend) -> ReportsScreen:
    await pilot.press("h")
    await pilot.pause()
    screen = pilot.app.screen
    assert isinstance(screen, ReportsScreen)
    await _until(lambda: screen._history_state in ("ok", "empty", "failed"))
    await pilot.pause()
    return screen


def _reports_app(tmp_path, backend: FakeScanBackend) -> VScannerApp:
    service = ConfigService(tmp_path / "config.json")
    service.save(adb_path="C:/fake/adb.exe")
    return VScannerApp(config_service=service, backend=backend)


def _history_text(screen: ReportsScreen) -> str:
    return " ".join(
        str(cell)
        for row in range(
            screen.query_one("#rp-history", DataTable).row_count)
        for cell in screen.query_one("#rp-history", DataTable).get_row_at(row)
    )


# -- history table ------------------------------------------------------------- #

class TestReportsHistory:
    async def test_history_rows_render_and_refresh(self, tmp_path) -> None:
        backend = FakeScanBackend()
        backend.history_entries = [
            _entry(),
            _entry(status="cancelled", scan_id="req-2"),
        ]
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            table = screen.query_one("#rp-history", DataTable)
            assert table.row_count == 2
            cells = _history_text(screen)
            assert "S1" in cells
            assert "completed" in cells
            assert "cancelled" in cells
            assert "full_device" in cells
            # a new entry lands only after an explicit refresh (r)
            backend.history_entries.append(_entry(scan_id="req-3"))
            await pilot.press("r")
            await _until(
                lambda: screen.query_one(
                    "#rp-history", DataTable).row_count == 3)
            assert screen._history_state == "ok"

    async def test_history_read_failure_is_honest(self, tmp_path) -> None:
        backend = FakeScanBackend()
        backend.history_read_fail = True
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            assert screen._history_state == "failed"
            banner = screen.query_one("#rp-banner", Label)
            assert "unavailable" in _text_of(banner)
            # the failure says WHAT failed — no fake "0 scans" claim
            assert "history read failed (RuntimeError)" in _text_of(banner)
            assert screen.query_one(
                "#rp-history", DataTable).row_count == 0

    async def test_history_empty_state_never_fakes_rows(self, tmp_path) -> None:
        backend = FakeScanBackend()
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            assert screen._history_state == "empty"
            assert "no scans recorded yet" in _text_of(
                screen.query_one("#rp-banner", Label))
            assert screen.query_one(
                "#rp-history", DataTable).row_count == 0


# -- export gating --------------------------------------------------------------- #

class TestExportGating:
    async def test_export_without_a_completed_scan_is_refused(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            notified: List[str] = []
            screen.notify = (  # type: ignore[method-assign]
                lambda message, **kw: notified.append(str(message)))
            await pilot.press("x")
            await pilot.pause()
            assert backend.export_calls == []
            assert any(
                "no completed scan" in message for message in notified)

    async def test_cancelled_last_scan_is_not_exportable(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.scan_memory = ("cancelled", "S1", _bundle())
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            # the panel says the partial state is not exportable
            assert "not exportable" in _text_of(
                screen.query_one("#rp-last-scan", Label))
            notified: List[str] = []
            screen.notify = (  # type: ignore[method-assign]
                lambda message, **kw: notified.append(str(message)))
            await pilot.press("x")
            await pilot.pause()
            assert backend.export_calls == []
            assert any("cancelled" in message for message in notified)

    async def test_completed_last_scan_is_ready_to_export(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.scan_memory = ("completed", "S1", _bundle())
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            last = _text_of(screen.query_one("#rp-last-scan", Label))
            assert "ready to export" in last
            assert "2 app(s)" in last


# -- export execution ------------------------------------------------------------- #

class TestExportExecution:
    async def test_export_success_shows_only_service_paths(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        bundle = _bundle()
        backend.scan_memory = ("completed", "S1", bundle)
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            await pilot.press("x")
            await pilot.pause()
            # the whole bundle object went to the backend, untouched
            assert backend.export_calls == [(bundle, None, "S1")]
            assert screen._export_state == "running"
            job_id = screen._export_job_id
            assert job_id is not None
            result = SimpleNamespace(
                ok=True,
                formats_written={
                    "html": "reports/demo.html",
                    "json": "reports/demo.json",
                    "text": "reports/demo.txt",
                },
                error=None,
            )
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id, outcome=JobState.SUCCEEDED, result=result))
            await pilot.pause()
            assert screen._export_state == "ok"
            text = _text_of(screen.query_one("#rp-export-result", Label))
            assert "export succeeded" in text
            assert "reports/demo.html" in text
            assert "reports/demo.json" in text
            assert "reports/demo.txt" in text

    async def test_service_reported_failure_is_never_a_success_claim(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.scan_memory = ("completed", "S1", _bundle())
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            await pilot.press("x")
            await pilot.pause()
            job_id = screen._export_job_id
            assert job_id is not None
            result = SimpleNamespace(
                ok=False, formats_written={}, error="disk full")
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id, outcome=JobState.SUCCEEDED, result=result))
            await pilot.pause()
            assert screen._export_state == "failed"
            text = _text_of(screen.query_one("#rp-export-result", Label))
            assert "export failed" in text
            assert "disk full" in text
            assert "nothing" in text

    async def test_failed_terminal_job_is_honest(self, tmp_path) -> None:
        backend = FakeScanBackend()
        backend.scan_memory = ("completed", "S1", _bundle())
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            await pilot.press("x")
            await pilot.pause()
            job_id = screen._export_job_id
            assert job_id is not None
            error = InputValidationError("export plan refused the path")
            screen.on_job_event(JobTerminalEvent(
                job_id=job_id, outcome=JobState.FAILED, result=None,
                error=error))
            await pilot.pause()
            assert screen._export_state == "failed"
            text = _text_of(screen.query_one("#rp-export-result", Label))
            assert "export plan refused the path" in text

    async def test_output_directory_is_passed_through_untouched(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.scan_memory = ("completed", "S1", _bundle())
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            screen.query_one("#rp-output-dir", Input).value = (
                "C:/tmp/vscanner-out")
            await pilot.press("x")
            await pilot.pause()
            assert len(backend.export_calls) == 1
            assert backend.export_calls[0][1] == "C:/tmp/vscanner-out"
            assert backend.export_calls[0][2] == "S1"

    async def test_foreign_terminal_events_are_ignored(self, tmp_path) -> None:
        backend = FakeScanBackend()
        backend.scan_memory = ("completed", "S1", _bundle())
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            await pilot.press("x")
            await pilot.pause()
            assert screen._export_state == "running"
            # an unrelated job's terminal must not touch the export state
            screen.on_job_event(JobTerminalEvent(
                job_id="some-other-job", outcome=JobState.FAILED,
                result=None, error=None))
            await pilot.pause()
            assert screen._export_state == "running"
            assert screen._export_job_id is not None

    async def test_second_export_while_running_is_refused(
        self, tmp_path,
    ) -> None:
        backend = FakeScanBackend()
        backend.scan_memory = ("completed", "S1", _bundle())
        app = _reports_app(tmp_path, backend)
        async with app.run_test() as pilot:
            screen = await open_reports(pilot, backend)
            await pilot.press("x")
            await pilot.pause()
            notified: List[str] = []
            screen.notify = (  # type: ignore[method-assign]
                lambda message, **kw: notified.append(str(message)))
            await pilot.press("x")
            await pilot.pause()
            assert len(backend.export_calls) == 1
            assert any(
                "already running" in message for message in notified)
