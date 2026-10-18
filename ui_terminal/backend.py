"""Production UI→engine adapter for the Stage 06 workspace + Stage 07
scanning/findings/reports workflows.

Single seam between the Textual layer and the shared engine: widgets never
build transports, never run subprocesses, and never parse ADB output. The
backend composes everything the screens need from the existing engine pieces
(:class:`~vscanner.services.registry.ServiceRegistry`,
:class:`~vscanner.services.jobs.JobManager` + the Stage 04
:class:`~ui_terminal.jobs_bridge_async.AsyncJobBridge`), driven by the saved
configuration (:class:`~vscanner.services.config.ConfigService`).

Call discipline (mission §5/§6, SERVICE_CONTRACTS §SC-1/SC-2/SC-3/SC-4/SC-9):

* ``list_devices`` / ``profile`` are blocking subprocess surfaced calls —
  they must only be invoked from background threads (Textual workers).
* ``adb_path_saved`` only reads the config file (cheap, UI-thread safe).
* Listing/scanning/export run as *jobs* (cancellable where the contract
  defines boundaries; export is atomic and exempt by contract). The pump
  marshals JobManager events from worker threads onto the app loop; the
  app forwards them to the CURRENT screen only.
* The scan history store (T-08) appends are small local JSON writes — the
  UI still performs them on worker threads, never on the event loop.
* No destructive operation exists on this seam, and no on-disk device-data
  persistence beyond the T-08 scan summaries (which hold no secret
  material by construction).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Optional, Protocol, Tuple

from vscanner.core.errors import AdbNotAvailable
from vscanner.core.events import JobEvent, JobKind
from vscanner.core.models import (
    ConnectionInfo,
    DeviceProfile,
    ScanConfiguration,
    ScanKind,
    ScanRequest,
    ScanResultBundle,
)
from vscanner.services.config import ConfigService
from vscanner.services.history import HistoryEntry, ScanHistoryStore
from vscanner.services.jobs import JobHandle, JobManager
from vscanner.services.orchestration import (
    app_listing_rows_plan,
    export_reports_plan,
    full_device_scan_plan,
    single_app_scan_plan,
)
from vscanner.services.registry import ServiceRegistry
from vscanner.services.reports.service import ReportService
from vscanner.services.scanning.app_inventory import PackageInventoryService
from vscanner.services.scanning.scanner import ScanService

from ui_terminal.jobs_bridge_async import AsyncJobBridge

__all__ = ["WorkspaceBackend", "DeviceBackend"]


class DeviceBackend(Protocol):
    """Structural seam the screens consume (production + test fakes).

    Blocking methods (``list_devices``/``profile``) are documented as
    worker-thread-only; the protocol exists so widgets depend on the shape,
    never on a concrete class."""

    def adb_path_saved(self) -> Optional[str]: ...

    def list_devices(self) -> Tuple[ConnectionInfo, ...]: ...

    def profile(self, serial: str) -> DeviceProfile: ...

    def start_listing_job(self, serial: str, include_system: bool) -> JobHandle: ...

    def cancel_listing_job(self, serial: str) -> None: ...

    def active_listing_handle(self, serial: str) -> Optional[JobHandle]: ...

    # -- Stage 07 scanning / findings / reports ------------------------------ #

    def start_scan_job(
        self, serial: str, include_system: bool, deep: bool,
        package: Optional[str],
    ) -> JobHandle: ...

    def cancel_scan_job(self, serial: str) -> None: ...

    def active_scan_handle(self, serial: str) -> Optional[JobHandle]: ...

    def remember_scan(self, bundle: ScanResultBundle, status: str,
                      serial: Optional[str]) -> None: ...

    def last_scan(self) -> Optional[Tuple[str, Optional[str], ScanResultBundle]]: ...

    def start_export_job(self, bundle: ScanResultBundle,
                         output_dir: Optional[str],
                         serial: Optional[str]) -> JobHandle: ...

    def history_entry(self, entry: HistoryEntry) -> Path: ...

    def history_recent(self) -> Tuple[HistoryEntry, ...]: ...

    def shutdown_jobs(self) -> None: ...

    def start_pump(self, sink: Callable[[JobEvent], None]) -> None: ...

    def stop_pump(self) -> None: ...


class WorkspaceBackend:
    """Session-scoped engine access for the TUI screens (Stage 06/07)."""

    def __init__(
        self,
        config_service: ConfigService,
        history: Optional[ScanHistoryStore] = None,
    ) -> None:
        self._config = config_service
        self._registry_obj: Optional[ServiceRegistry] = None
        self._registry_adb_path: Optional[str] = None
        self._manager_obj: Optional[JobManager] = None
        self._bridge: Optional[AsyncJobBridge] = None
        self._pump_task: Optional[asyncio.Task] = None
        self._history = history  # lazily built when None (repo paths)
        self._scan_memory: Optional[tuple] = None
        """Last terminal scan the user can still work with: the finished
        bundle + its honest status word + target serial (in-memory only;
        the durable T-08 history lives in the store)."""

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

    # -- jobs (SC-3 scanning — Stage 07) ------------------------------------- #

    def start_scan_job(
        self, serial: str, include_system: bool = False, deep: bool = False,
        package: Optional[str] = None,
    ) -> JobHandle:
        """Submit a SINGLE_APP_SCAN or FULL_DEVICE_SCAN job for one device.

        The scanner is built with a serial-bound client — the screen's own
        explicit selection; no registry-global state is touched. Overlapping
        scan work is impossible at the engine layer: both kinds share the
        per-device ``scan`` mutex group (submit raises JobConflictError)."""
        scan_service = ScanService(self._registry().client(serial))
        if package is None:
            request = ScanRequest(
                kind=ScanKind.FULL_DEVICE,
                config=ScanConfiguration(
                    include_system=include_system,
                    deep=deep,
                    device_serial=serial,
                ),
            )
            plan = full_device_scan_plan(scan_service, request)
            kind = JobKind.FULL_DEVICE_SCAN
            summary = {"device": serial, "scope": "full-device"}
            if include_system:
                summary["system_apps"] = "included"
            if deep:
                summary["depth"] = "deep"
        else:
            config = ScanConfiguration(
                include_system=include_system,
                deep=deep,
                device_serial=serial,
            )
            plan = single_app_scan_plan(scan_service, package, config=config)
            kind = JobKind.SINGLE_APP_SCAN
            summary = {"device": serial, "package": package}
            if deep:
                summary["depth"] = "deep"
        return self._manager().submit(
            kind, device_serial=serial, plan=plan,
            params_summary=summary,
        )

    def cancel_scan_job(self, serial: str) -> None:
        self._manager().cancel_device_work(serial)

    def active_scan_handle(self, serial: str) -> Optional[JobHandle]:
        """Running/queued scan job for a device, if any (honest resume)."""
        handles = self._manager().active_for_device(serial)
        for handle in reversed(handles):
            if handle.kind in (JobKind.FULL_DEVICE_SCAN, JobKind.SINGLE_APP_SCAN):
                return handle
        return None

    # -- last-terminal scan memory (reports section) -------------------------- #

    def remember_scan(self, bundle: ScanResultBundle, status: str,
                      serial: Optional[str]) -> None:
        """Keep the finished bundle for the reports screen (in-memory; the
        T-08 on-disk history holds only counters, never findings text)."""
        self._scan_memory = (status, serial, bundle)

    def last_scan(self) -> Optional[tuple]:
        return self._scan_memory

    # -- jobs (SC-9 export) ----------------------------------------------------- #

    def start_export_job(self, bundle: ScanResultBundle,
                         output_dir: Optional[str],
                         serial: Optional[str]) -> JobHandle:
        """EXPORT job through the Stage 04 plan (fast, atomic, exempt from
        cancellation by contract). ``output_dir`` keeps the legacy default
        (``reports`` relative directory) when not requested; ``serial``
        binds the job to the scan's device for device-scoped observation."""
        report_service = ReportService(output_dir=output_dir or "reports")
        return self._manager().submit(
            JobKind.EXPORT,
            device_serial=serial,
            plan=export_reports_plan(report_service, bundle),
            params_summary={"target": "finished scan bundle"},
        )

    # -- scan history (T-08) ---------------------------------------------------- #

    def history_entry(self, entry: HistoryEntry) -> Path:
        if self._history is None:
            from vscanner.core.paths import history_dir

            self._history = ScanHistoryStore(history_dir())
        return self._history.append(entry)

    def history_recent(self) -> Tuple[HistoryEntry, ...]:
        if self._history is None:
            from vscanner.core.paths import history_dir

            self._history = ScanHistoryStore(history_dir())
        return self._history.recent()

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
