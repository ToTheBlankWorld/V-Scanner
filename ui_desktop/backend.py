"""Production desktop-engine adapter (Stage 10) — the Qt counterpart of the
TUI's ``ui_terminal/backend.py`` workspace seam.

Single seam between the Qt layer and the shared engine: widgets never build
transports, never run subprocesses, and never parse ADB output. The backend
composes the pieces the screens need from the existing engine
(:class:`~vscanner.services.registry.ServiceRegistry`,
:class:`~vscanner.services.jobs.JobManager` + the Stage 04 job plans,
driven by :class:`~vscanner.services.config.ConfigService`).

Call discipline (SERVICE_CONTRACTS SC-1/SC-2/SC-4, identical to the TUI):

* ``list_devices`` / ``profile`` / ``full_profile`` are blocking
  subprocess-surfaced calls — they must only be invoked from background
  threads (``ui_desktop.workers`` / the job system).
* ``adb_path_saved`` reads only the config file (cheap, UI-thread safe).
* App listing runs as a cancellable Stage 04 APP_LISTING job
  (``app_listing_rows_plan``); events are delivered by the
  ``JobManager`` to the desktop's ``QtJobEventBridge`` subscribers.
* One ``JobManager`` per application session (max_workers=2, like the TUI)
  — never a competing executor; the shell shuts it down on close.

The registry is rebuilt only when the saved ADB path changes — never per
call (same caching discipline as the TUI backend).
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from pathlib import Path

from vscanner.core.errors import AdbNotAvailable
from vscanner.core.models import (
    AppScanResult,
    ConnectionInfo,
    DeviceProfile,
    ScanConfiguration,
    ScanKind,
    ScanRequest,
    ScanResultBundle,
)
from vscanner.core.paths import history_dir
from vscanner.services.config import ConfigService
from vscanner.services.history import HistoryEntry, ScanHistoryStore
from vscanner.services.jobs import JobHandle, JobKind, JobManager
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

__all__ = ["DesktopBackend"]


class DesktopBackend:
    """Session-scoped engine access for the desktop screens (Stage 10/11)."""

    def __init__(self, config_service: ConfigService) -> None:
        self._config = config_service
        self._registry_obj: Optional[ServiceRegistry] = None
        self._registry_adb_path: Optional[str] = None
        self._manager_obj: Optional[JobManager] = None
        # last-terminal scan memory (reports export source); in-memory only —
        # the on-disk T-08 history carries counters, never findings text.
        self._scan_memory: Optional[Tuple[str, Optional[str], Any]] = None
        self._history_obj: Optional[ScanHistoryStore] = None

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
                "path in Settings (Ctrl+,), then refresh"
            )
        if self._registry_obj is None or self._registry_adb_path != path:
            # One registry per resolved path; rebuilt only when the user
            # saves a different path — never per call.
            self._registry_obj = ServiceRegistry(path)
            self._registry_adb_path = path
        return self._registry_obj

    def list_devices(self, timeout: float = 10.0) -> Tuple[ConnectionInfo, ...]:
        """SC-1: one ``adb devices`` invocation (honest empty tuple)."""
        return tuple(self._registry().discovery().list_devices(timeout=timeout))

    def profile(self, serial: str) -> DeviceProfile:
        """SC-4 basic profile for an explicitly selected device."""
        return self._registry().device_info(serial).get_basic_profile()

    def full_profile(self, serial: str) -> DeviceProfile:
        """Stage 08 parity: full getprop surface + the VERIFIED root
        tri-state (R-05) recorded in the returned profile — the basic
        profile keeps the honest UNKNOWN default (worker thread only;
        several shells are spent reading facts)."""
        service = self._registry().device_info(serial)
        profile = service.get_full_profile()
        status, _evidence = self._registry().root_status(serial).probe_evidence()
        return DeviceProfile(
            mfr=profile.mfr, serial=profile.serial, model=profile.model,
            brand=profile.brand, board=profile.board, device=profile.device,
            hardware=profile.hardware, build_id=profile.build_id,
            android=profile.android, sdk_int=profile.sdk_int,
            patch=profile.patch, kernel=profile.kernel,
            fingerprint=profile.fingerprint, bootloader=profile.bootloader,
            locale=profile.locale, timezone=profile.timezone,
            ip=profile.ip, mac=profile.mac, root_status=status,
        )

    # -- jobs (SC-2 app listing) -------------------------------------------- #

    def manager(self) -> JobManager:
        if self._manager_obj is None:
            self._manager_obj = JobManager(max_workers=2)
        return self._manager_obj

    def start_listing_job(self, serial: str,
                          include_system: bool) -> JobHandle:
        """Submit the cancellable APP_LISTING job for one device.

        The inventory service is built with a serial-bound client — the
        workspace's own explicit selection; no registry-global selection
        state is touched (no cross-device race when several devices are
        present). Raises ``JobConflictError`` when a listing is already
        active for this device (never stacks overlapping jobs)."""
        plan = app_listing_rows_plan(
            PackageInventoryService(self._registry().client(serial)),
            include_system=include_system,
        )
        return self.manager().submit(
            JobKind.APP_LISTING,
            device_serial=serial,
            plan=plan,
            params_summary={"device": serial},
        )

    def cancel_listing_job(self, serial: str) -> None:
        self.manager().cancel_device_work(serial)

    def active_listing_handle(self, serial: str) -> Optional[JobHandle]:
        """Running APP_LISTING job for a device, if any (honest resume)."""
        handles = self.manager().active_for_device(serial)
        for handle in reversed(handles):
            if handle.kind is JobKind.APP_LISTING:
                return handle
        return None

    # -- shutdown ------------------------------------------------------------ #

    def shutdown_jobs(self) -> None:
        """App-quit hook: give running jobs the configured grace period."""
        if self._manager_obj is not None:
            self._manager_obj.shutdown()
            self._manager_obj = None

    # -- scan jobs (SC-3, Stage 11) ------------------------------------------- #

    def _scan_service(self, serial: str) -> ScanService:
        """Serial-bound scanner: the workspace's own explicit selection;
        no registry-global selection state is touched."""
        return ScanService(self._registry().client(serial))

    def start_scan_job(
        self, serial: str, include_system: bool = False, deep: bool = False,
        package: Optional[str] = None,
    ) -> JobHandle:
        """Submit a SINGLE_APP_SCAN or FULL_DEVICE_SCAN job for one device.

        Identical call surface to the TUI backend (``ui_terminal/backend``
        Stage 07): both scan kinds share the per-device ``scan`` mutex
        group, so overlapping scan work is impossible at the engine layer
        (a second submit raises ``JobConflictError``)."""
        scan_service = self._scan_service(serial)
        config = ScanConfiguration(
            include_system=include_system, deep=deep, device_serial=serial,
        )
        if package is None:
            request = ScanRequest(kind=ScanKind.FULL_DEVICE, config=config)
            plan = full_device_scan_plan(scan_service, request)
            kind = JobKind.FULL_DEVICE_SCAN
            summary = {"device": serial, "scope": "full-device"}
            if include_system:
                summary["system_apps"] = "included"
            if deep:
                summary["depth"] = "deep"
        else:
            plan = single_app_scan_plan(scan_service, package, config=config)
            kind = JobKind.SINGLE_APP_SCAN
            summary = {"device": serial, "package": package}
            if deep:
                summary["depth"] = "deep"
        return self.manager().submit(
            kind, device_serial=serial, plan=plan, params_summary=summary,
        )

    def cancel_scan_job(self, serial: str) -> int:
        """Cancel ONLY the scan-kind job(s) bound to ``serial``.

        More precise than ``cancel_device_work`` (Stage 10 listing contract
        intact): a running APP_LISTING for the same device is never
        cancelled by a scan-screen cancel. Returns the cancelled count."""
        cancelled = 0
        for handle in self.manager().active_for_device(serial):
            if handle.kind in (JobKind.FULL_DEVICE_SCAN,
                               JobKind.SINGLE_APP_SCAN):
                handle.cancel()
                cancelled += 1
        return cancelled

    def active_scan_handle(self, serial: str) -> Optional[JobHandle]:
        """Running/queued scan job for a device, if any (honest resume)."""
        handles = self.manager().active_for_device(serial)
        for handle in reversed(handles):
            if handle.kind in (JobKind.FULL_DEVICE_SCAN,
                               JobKind.SINGLE_APP_SCAN):
                return handle
        return None

    # -- last-terminal scan memory (reports export source) -------------------- #

    def remember_scan(self, bundle: Any, status: str,
                      serial: Optional[str]) -> None:
        """Keep the finished scan outcome for the reports screen.

        Honesty rule (TUI Stage 07 parity): a failed/cancelled scan is
        remembered as such — its ``bundle`` slot stays ``None`` so a
        partial result can never be exported as a completed scan."""
        self._scan_memory = (status, serial,
                             bundle if status == "completed" and
                             isinstance(bundle, ScanResultBundle) else None)

    def last_scan(self) -> Optional[Tuple[str, Optional[str], Any]]:
        """(status, serial, bundle-or-None) of this session's last
        terminal scan; ``status`` is the honest terminal word."""
        return self._scan_memory

    # -- report export jobs (SC-9) --------------------------------------------- #

    def start_export_job(
        self, bundle: ScanResultBundle,
        requested: Optional[Any] = None,
        output_dir: Optional[str] = None,
        device_info: Optional[Any] = None,
        serial: Optional[str] = None,
    ) -> JobHandle:
        """EXPORT job through the Stage 04 plan (fast, atomic write, exempt
        from cancellation by contract). ``requested`` maps each ``ReportFormat``
        to an explicit filename (a full path is honored by the service) or
        ``None`` for the legacy generated names."""
        report_service = ReportService(output_dir=output_dir or "reports")
        return self.manager().submit(
            JobKind.EXPORT,
            device_serial=serial,
            plan=export_reports_plan(
                report_service, bundle,
                requested=requested,
                output_dir=output_dir,
                device_info=device_info,
            ),
            params_summary={"target": "finished scan bundle"},
        )

    # -- scan history (T-08 store, counters only) ------------------------------ #

    def _history(self) -> ScanHistoryStore:
        if self._history_obj is None:
            self._history_obj = ScanHistoryStore(history_dir())
        return self._history_obj

    def history_entry(self, entry: HistoryEntry) -> Path:
        """Append one finished-scan summary (blocking file write; worker
        threads only — the scan screen records outcomes off the GUI)."""
        return self._history().append(entry)

    def history_recent(self) -> Tuple[HistoryEntry, ...]:
        return self._history().recent()
