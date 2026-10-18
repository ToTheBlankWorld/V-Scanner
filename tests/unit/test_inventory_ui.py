"""App-inventory integration through the real job pipeline (Stage 06).

The FULL production path is exercised with only the ADB subprocess faked
(monkeypatched ``SubprocessAdbClient`` in the registry module — never a
real device, network, or root):

    DeviceWorkspaceScreen → WorkspaceBackend → ServiceRegistry
    → PackageInventoryService.list_app_rows → app_listing_rows_plan
    → JobManager (thread) → AsyncJobBridge → app dispatch → screen

Determinism: the listing command gate opens from the test; the cancel
path cancels while the command is blocked and relies on the plan's
post-listing checkpoint to acknowledge cancellation (request ⇒ ack).
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Optional

import pytest
from textual.widgets import DataTable, Label

from ui_terminal.app import VScannerApp
from ui_terminal.backend import WorkspaceBackend
from ui_terminal.screens.workspace import DeviceWorkspaceScreen, PAGE_SIZE
from vscanner.services.adb.device_info import GETPROP_KEYS
from vscanner.services.config import ConfigService


async def _until(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met within the timeout")


def _plain(label):
    """Plain text of a Label (unannotated body: mypy stays off it)."""
    return str(label.render().plain)


def _listing_banner_text(screen) -> str:
    return _plain(screen.query_one("#ws-listing-banner", Label))


@dataclass
class _Result:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class _State:
    def __init__(self) -> None:
        self.results: dict = {}
        self.received: list = []
        self.block_listing: Optional[threading.Event] = None
        self.clients: list = []


class FakeAdbClient:
    """Serial-carrying stand-in for the real client (registry seam)."""

    STATE = _State()

    def __init__(self, adb_path, serial: Optional[str] = None):
        self.serial = serial
        FakeAdbClient.STATE.clients.append(self)

    def run_text(self, cmd, timeout: float = 30.0):
        joined = " ".join(str(p) for p in cmd)
        state = FakeAdbClient.STATE
        state.received.append((joined, self.serial))
        if state.block_listing is not None and "pm list" in joined:
            state.block_listing.wait(timeout=2.0)
        return state.results[joined]

    def run_bytes(self, cmd, timeout: float = 30.0):  # pragma: no cover
        raise AssertionError("byte mode is not used in Stage 06 flows")



def _base_results(listing_stdout: str) -> dict:
    results = {
        "devices": _Result(
            stdout="List of devices attached\n"
                   "SER1\tdevice usb:1-3 product:p model:Pixel_2\n"),
        "shell pm list packages -3": _Result(stdout=listing_stdout),
        "shell uname -r": _Result(),
    }
    for key, _attr in GETPROP_KEYS:
        results[f"shell getprop {key}"] = _Result()
    return results


class TestFullListingPipeline:
    async def test_listing_reaches_screen_through_the_event_pipeline(
        self, monkeypatch, tmp_path,
    ) -> None:
        monkeypatch.setattr(
            "vscanner.services.registry.SubprocessAdbClient", FakeAdbClient)
        FakeAdbClient.STATE = _State()
        FakeAdbClient.STATE.results = _base_results(
            "\n".join(f"package:com.stage06.app{i}" for i in range(200)) + "\n")

        config = ConfigService(tmp_path / "config.json")
        config.save(adb_path="C:/fake/adb.exe")
        backend = WorkspaceBackend(config)
        app = VScannerApp(config_service=config, backend=backend)
        try:
            async with app.run_test() as pilot:
                await pilot.press("w")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, DeviceWorkspaceScreen)
                await _until(lambda: screen._discovery_state == "ok")
                await _until(lambda: screen._selected_serial == "SER1")
                # serial-bound listing: the job client carries the serial
                screen.action_list_apps()
                await _until(lambda: screen._listing_state == "ok")
                table = screen.query_one("#ws-apps", DataTable)
                assert table.row_count == PAGE_SIZE  # 100 per page
                text = _listing_banner_text(screen)
                assert "200 apps" in text
                assert "page 1/2" in text
                # second page through the explicit pagination
                await pilot.press("]")
                await pilot.pause()
                assert table.row_count == 100
                text = _listing_banner_text(screen)
                assert "page 2/2" in text
                # reconciliation: delivered results survive a re-entry cycle
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("w")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, DeviceWorkspaceScreen)
                assert screen._listing_state == "ok"
                # the pump is one object across screen mount cycles
                assert backend._pump_task is not None
        finally:
            backend.shutdown_jobs()

    async def test_listing_client_is_bound_to_the_selected_serial(
        self, monkeypatch, tmp_path,
    ) -> None:
        monkeypatch.setattr(
            "vscanner.services.registry.SubprocessAdbClient", FakeAdbClient)
        FakeAdbClient.STATE = _State()
        FakeAdbClient.STATE.results = _base_results("package:com.only.one\n")

        config = ConfigService(tmp_path / "config.json")
        config.save(adb_path="C:/fake/adb.exe")
        backend = WorkspaceBackend(config)
        app = VScannerApp(config_service=config, backend=backend)
        try:
            async with app.run_test() as pilot:
                await pilot.press("w")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, DeviceWorkspaceScreen)
                await _until(lambda: screen._discovery_state == "ok")
                await _until(lambda: screen._selected_serial == "SER1")
                screen.action_list_apps()
                await _until(lambda: screen._listing_state == "ok")
                bound = [
                    c for c in FakeAdbClient.STATE.clients if c.serial == "SER1"]
                assert bound, "listing must run through a serial-bound client"
        finally:
            backend.shutdown_jobs()

    async def test_cancellation_mid_listing_is_honoured(
        self, monkeypatch, tmp_path,
    ) -> None:
        monkeypatch.setattr(
            "vscanner.services.registry.SubprocessAdbClient", FakeAdbClient)
        gate = threading.Event()
        FakeAdbClient.STATE = _State()
        FakeAdbClient.STATE.block_listing = gate
        FakeAdbClient.STATE.results = _base_results(
            "\n".join(f"package:com.c{i}" for i in range(150)) + "\n")

        config = ConfigService(tmp_path / "config.json")
        config.save(adb_path="C:/fake/adb.exe")
        backend = WorkspaceBackend(config)
        app = VScannerApp(config_service=config, backend=backend)
        try:
            async with app.run_test() as pilot:
                await pilot.press("w")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, DeviceWorkspaceScreen)
                await _until(lambda: screen._discovery_state == "ok")
                await _until(lambda: screen._selected_serial == "SER1")
                screen.action_list_apps()
                await _until(lambda: screen._listing_state == "running")
                await _until(lambda: any(
                    "pm list" in pair[0]
                    for pair in FakeAdbClient.STATE.received))
                # cancel while the listing command is still blocked
                screen.action_cancel_listing()
                await _until(lambda: screen._listing_state == "cancelled")
                text = _listing_banner_text(screen)
                assert "cancelled" in text
                gate.set()  # unblock the worker; terminal stays cancelled
        finally:
            backend.shutdown_jobs()

    async def test_listing_failure_delivers_typed_message(
        self, monkeypatch, tmp_path,
    ) -> None:
        monkeypatch.setattr(
            "vscanner.services.registry.SubprocessAdbClient", FakeAdbClient)
        FakeAdbClient.STATE = _State()
        FakeAdbClient.STATE.results = _base_results("")
        FakeAdbClient.STATE.results["shell pm list packages -3"] = _Result(
            stdout="", stderr="pm: boom", returncode=1)

        config = ConfigService(tmp_path / "config.json")
        config.save(adb_path="C:/fake/adb.exe")
        backend = WorkspaceBackend(config)
        app = VScannerApp(config_service=config, backend=backend)
        try:
            async with app.run_test() as pilot:
                await pilot.press("w")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, DeviceWorkspaceScreen)
                await _until(lambda: screen._discovery_state == "ok")
                await _until(lambda: screen._selected_serial == "SER1")
                screen.action_list_apps()
                await _until(lambda: screen._listing_state == "failed")
                text = _listing_banner_text(screen)
                assert "app listing failed" in text
        finally:
            backend.shutdown_jobs()
