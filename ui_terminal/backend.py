"""Production UI→engine adapter for the Stage 06 device workspace.

Single seam between the Textual layer and the shared engine: widgets never
build transports, never run subprocesses, and never parse ADB output. The
backend composes everything the workspace needs from the existing Stage 03
engine pieces (:class:`~vscanner.services.registry.ServiceRegistry`,
:class:`~vscanner.services.jobs.JobManager` + the Stage 04
:class:`~ui_terminal.jobs_bridge_async.AsyncJobBridge`), driven by the saved
configuration (:class:`~vscanner.services.config.ConfigService`).

Call discipline (mission §5/§6, SERVICE_CONTRACTS §SC-1/SC-2/SC-4):

* ``list_devices`` / ``profile`` are blocking subprocess surfaced calls —
  they must only be invoked from background threads (Textual workers).
* ``adb_path_saved`` only reads the config file (cheap, UI-thread safe).
* Listing runs as an APP_LISTING *job* (cancellable, event-driven). The
  pump marshals JobManager events from worker threads onto the app loop;
  the app forwards them to the current workspace screen.
* No scan, no destructive operation, no on-disk device-data persistence:
  this adapter only reads device facts for display.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional, Protocol, Tuple

from vscanner.core.errors import AdbNotAvailable
from vscanner.core.events import JobEvent, JobKind
from vscanner.core.models import ConnectionInfo, DeviceProfile
from vscanner.services.config import ConfigService
from vscanner.services.jobs import JobHandle, JobManager
from vscanner.services.orchestration import app_listing_rows_plan
from vscanner.services.registry import ServiceRegistry
from vscanner.services.scanning.app_inventory import PackageInventoryService

from ui_terminal.jobs_bridge_async import AsyncJobBridge

__all__ = ["WorkspaceBackend", "DeviceBackend"]


class DeviceBackend(Protocol):
    """Structural seam the workspace consumes (production + test fakes).

    Blocking methods (``list_devices``/``profile``) are documented as
    worker-thread-only; the protocol exists so widgets depend on the shape,
    never on a concrete class."""

    def adb_path_saved(self) -> Optional[str]: ...

    def list_devices(self) -> Tuple[ConnectionInfo, ...]: ...

    def profile(self, serial: str) -> DeviceProfile: ...

    def start_listing_job(self, serial: str, include_system: bool) -> JobHandle: ...

    def cancel_listing_job(self, serial: str) -> None: ...

    def active_listing_handle(self, serial: str) -> Optional[JobHandle]: ...

    def shutdown_jobs(self) -> None: ...

    def start_pump(self, sink: Callable[[JobEvent], None]) -> None: ...

    def stop_pump(self) -> None: ...


class WorkspaceBackend:
    """Session-scoped engine access for the device workspace screen."""

    def __init__(self, config_service: ConfigService) -> None:
        self._config = config_service
        self._registry_obj: Optional[ServiceRegistry] = None
        self._registry_adb_path: Optional[str] = None
        self._manager_obj: Optional[JobManager] = None
        self._bridge: Optional[AsyncJobBridge] = None
        self._pump_task: Optional[asyncio.Task] = None

    # -- cheap config surface (UI-thread safe) ------------------------------ #

    def adb_path_saved(self) -> Optional[str]:
        """The saved bridge executable path, or ``None`` when unset.

        Read-only: no probing, no launching, no directory writes."""
        snapshot = self._config.load()
        return snapshot.adb_path if snapshot.has_path else None

    # -- blocking engine calls (worker threads ONLY) ------------------------ #

    def _registry(self) -> ServiceRegistry:
        snapshot = self._config.load()
        path = snapshot.adb_path
        if not path:
            raise AdbNotAvailable(
                "no bridge path saved (first run) — set the ADB executable "
                "path in Settings (press s), save, then refresh (r)"
            )
        if self._registry_obj is None or self._registry_adb_path != path:
            # One registry per resolved path; rebuilt only when the user
            # saves a different path — never per call.
            self._registry_obj = ServiceRegistry(path)
            self._registry_adb_path = path
        return self._registry_obj

    def list_devices(self, timeout: float = 10.0) -> tuple:
        """SC-1: one ``adb devices`` invocation (honest empty tuple)."""
        return tuple(self._registry().discovery().list_devices(timeout=timeout))

    def profile(self, serial: str) -> DeviceProfile:
        """SC-4 basic profile for an explicitly selected device."""
        return self._registry().device_info(serial).get_basic_profile()

    # -- jobs (SC-2 app listing) -------------------------------------------- #

    def _manager(self) -> JobManager:
        if self._manager_obj is None:
            self._manager_obj = JobManager(max_workers=2)
        return self._manager_obj

    def start_listing_job(self, serial: str, include_system: bool) -> JobHandle:
        """Submit the cancellable APP_LISTING job for one device.

        The inventory service is built with a serial-bound client — the
        workspace's own explicit selection; no registry-global state is
        touched (no cross-device race when several devices are present)."""
        plan = app_listing_rows_plan(
            PackageInventoryService(self._registry().client(serial)),
            include_system=include_system,
        )
        return self._manager().submit(
            JobKind.APP_LISTING,
            device_serial=serial,
            plan=plan,
            params_summary={"device": serial},
        )

    def cancel_listing_job(self, serial: str) -> None:
        self._manager().cancel_device_work(serial)

    def active_listing_handle(self, serial: str) -> Optional[JobHandle]:
        """Running APP_LISTING job for a device, if any (for honest resume)."""
        handles = self._manager().active_for_device(serial)
        for handle in reversed(handles):
            if handle.kind is JobKind.APP_LISTING:
                return handle
        return None

    def shutdown_jobs(self) -> None:
        """App-quit hook: stop streaming and give workers the grace period."""
        self.stop_pump()
        if self._manager_obj is not None:
            self._manager_obj.shutdown()
            self._manager_obj = None

    # -- event pump (one per app; marshalled onto the loop) ----------------- #

    def start_pump(self, sink: Callable[[JobEvent], None]) -> None:
        """Start streaming engine job events to ``sink`` (loop thread).

        Idempotent: the pump survives workspace-screen mount cycles, so a
        job started before navigation keeps one subscription (no duplicates)."""
        if self._pump_task is not None:
            return
        self._bridge = AsyncJobBridge()
        self._bridge.attach(self._manager())
        self._pump_task = asyncio.get_running_loop().create_task(
            self._bridge.pump(sink)
        )

    def stop_pump(self) -> None:
        if self._bridge is not None:
            self._bridge.stop()
            self._bridge = None
        task = self._pump_task
        self._pump_task = None
        if task is not None:
            task.cancel()
