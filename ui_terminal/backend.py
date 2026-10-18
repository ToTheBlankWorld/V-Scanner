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
* No destructive operation exists on this seam EXCEPT through the Stage 08
  ADMIN_OP / FORENSICS_OP surfaces — and those carry
  :class:`~vscanner.core.events.OperationConfirmation` tokens down to the
  *service-side* gate (R-13); the backend builds no gate of its own and no
  destructive call ever runs synchronously on the UI thread.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Optional, Protocol, Tuple

from vscanner.core.errors import AdbNotAvailable, InputValidationError
from vscanner.core.events import JobEvent, JobKind, OperationConfirmation
from vscanner.core.models import (
    ConnectionInfo,
    DeviceProfile,
    MirrorHandle,
    MirrorOptions,
    ScanConfiguration,
    ScanKind,
    ScanRequest,
    ScanResultBundle,
    SensorReading,
)
from vscanner.services.config import ConfigService
from vscanner.services.history import HistoryEntry, ScanHistoryStore
from vscanner.services.jobs import JobHandle, JobManager
from vscanner.services.orchestration import (
    admin_op_plan,
    app_listing_rows_plan,
    demo_scan_plan,
    export_reports_plan,
    forensics_job_plan,
    full_device_scan_plan,
    monitoring_session_plan,
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

    def full_device_info(self, serial: str) -> DeviceProfile: ...

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

    # -- Stage 08 monitor / admin / forensics / mirror / demo ----------------- #

    def root_status_now(self, serial: str) -> tuple: ...

    def read_sensors_once(self, serial: str) -> tuple: ...

    def start_monitoring_session(self, serial: str,
                                 interval_s: float) -> JobHandle: ...

    def stop_monitoring(self, serial: str) -> None: ...

    def active_monitoring_handle(self, serial: str) -> Optional[JobHandle]: ...

    def start_admin_job(self, serial: str, op: str, package: str,
                        confirmation: OperationConfirmation) -> JobHandle: ...

    def start_forensics_job(self, serial: str, op: str,
                            kwargs: Optional[dict]) -> JobHandle: ...

    def forensics_load_case(self, case_id: str): ...

    def demo_bundle(self): ...

    def start_demo_job(self) -> JobHandle: ...

    def mirror_launch(self, serial: str, options: MirrorOptions) -> MirrorHandle: ...

    def mirror_list(self, serial: Optional[str]) -> Tuple[MirrorHandle, ...]: ...
    def mirror_stop(self, serial: str, pid: Optional[int]) -> Tuple[int, ...]: ...

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

    def full_device_info(self, serial: str) -> DeviceProfile:
        """Stage 08 full device info: full getprop surface + the VERIFIED
        root tri-state (R-05) recorded in the returned profile — the basic
        profile keeps the honest UNKNOWN default from Stage 06 (worker
        thread only; several shells are spent reading facts)."""
        service = self._registry().device_info(serial)
        profile = service.get_full_profile()
        status, _evidence = self._registry().root_status(
            serial).probe_evidence()
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

    # -- Stage 08: root tri-state, monitoring, admin, forensics, mirror, demo -- #

    def root_status_now(self, serial: str) -> tuple:
        """R-05 verified probe → (status-word, evidence lines).

        Blocking subprocess work — worker threads only. The word is one of
        ``rooted`` | ``not-rooted`` | ``unknown``; failures never become a
        claimed state."""
        return self._registry().root_status(serial).probe_evidence_words()

    def read_sensors_once(self, serial: str) -> Tuple[SensorReading, ...]:
        """R-04 honest one-shot sensor read (worker threads only)."""
        return self._registry().monitor(serial).read_sensor_values_once()

    def start_monitoring_session(self, serial: str,
                                 interval_s: float = 2.0) -> JobHandle:
        """MONITORING_SESSION job (SC-6): polls the honest usage surface on
        the worker thread and emits typed snapshot payloads until the user
        stops it or three consecutive polls fail (documented abort)."""
        plan = monitoring_session_plan(
            self._registry().monitor(serial), serial, interval_s=interval_s)
        return self._manager().submit(
            JobKind.MONITORING_SESSION, device_serial=serial, plan=plan,
            params_summary={"device": serial, "interval_s": f"{interval_s:g}"},
        )

    def stop_monitoring(self, serial: str) -> None:
        """Targeted cancel of the device's monitoring session — a user
        stopping the monitor must NOT cancel a running scan (unlike
        ``cancel_device_work``)."""
        handle = self.active_monitoring_handle(serial)
        if handle is not None:
            handle.cancel()

    def active_monitoring_handle(self, serial: str) -> Optional[JobHandle]:
        for handle in reversed(self._manager().active_for_device(serial)):
            if handle.kind is JobKind.MONITORING_SESSION:
                return handle
        return None

    def start_admin_job(self, serial: str, op: str,
                        package: str,
                        confirmation: OperationConfirmation) -> JobHandle:
        """ADMIN_OP job (SC-5): the confirmation travels to the SERVICE gate
        (R-13) — the backend builds no gate of its own and re-raises
        ConfirmationRequired/Invalid typed errors when calling without."""
        plan = admin_op_plan(self._registry().admin(serial), op, package,
                             confirmation)
        return self._manager().submit(
            JobKind.ADMIN_OP, device_serial=serial, plan=plan,
            params_summary={"device": serial, "op": op, "package": package},
        )

    def start_forensics_job(self, serial: str, op: str,
                            kwargs: Optional[dict] = None) -> JobHandle:
        """FORENSICS_OP job wrapper; ``op`` maps to documented engine ops:
        create_case | extract_app_data | system_logs | installed_packages |
        running_processes | wifi_cleartext | report."""
        service = self._registry().forensics(serial)
        call_kwargs = dict(kwargs or {})

        def _runner(context=None):  # plan passes its JobContext in
            if op == "create_case":
                return service.create_case(
                    device_serial=serial,
                    case_name=call_kwargs.get("case_name", ""),
                    note=call_kwargs.get("note", ""),
                    device_model=call_kwargs.get("device_model"),
                    android_version=call_kwargs.get("android_version"),
                )
            case_id = call_kwargs.get("case_id")
            if not case_id:
                raise InputValidationError(
                    "forensics op requires case_id", {"field": "case_id"})
            manifest = service.load_case(case_id)
            if op == "extract_app_data":
                return service.extract_app_data_files(
                    package=call_kwargs["package"],
                    sources=tuple(call_kwargs.get("sources",
                                                  ("databases", "shared_prefs",
                                                   "files"))),
                    manifest=manifest,
                    context=context,
                )
            if op == "system_logs":
                return service.extract_system_logs(manifest)
            if op == "installed_packages":
                return service.extract_installed_packages(manifest)
            if op == "running_processes":
                return service.extract_running_processes(manifest)
            if op == "wifi_cleartext":
                return service.extract_wifi_networks(
                    manifest,
                    acknowledge_cleartext_psk=call_kwargs.get("confirmation"),
                )
            if op == "report":
                report_path = service.generate_report(manifest)
                return manifest, report_path
            raise InputValidationError(
                f"unknown forensics op {op!r}", {"field": "op"})

        plan = forensics_job_plan(_runner, f"forensics {op}")
        summary: dict = {"device": serial, "op": op}
        if call_kwargs.get("case_id"):
            summary["case"] = str(call_kwargs["case_id"])[:64]
        return self._manager().submit(
            JobKind.FORENSICS_OP, device_serial=serial, plan=plan,
            params_summary=summary,
        )

    def forensics_load_case(self, case_id: str) -> "object":
        """Reopen a saved case manifest by id (worker thread; disk read)."""
        return self._registry().forensics(None).load_case(case_id)

    def demo_bundle(self) -> "object":
        """SC-10 deterministic demo bundle (no device contact at all)."""
        return self._registry().demo().scan()

    def start_demo_job(self) -> JobHandle:
        """DEMO job (SC-10): deterministic fixture bundle; never touches a
        device (device_serial=None keeps it outside device scopes)."""
        plan = demo_scan_plan(self._registry().demo())
        return self._manager().submit(
            JobKind.DEMO, device_serial=None, plan=plan,
            params_summary={"fixture": "deterministic demo set"},
        )

    def mirror_launch(self, serial: str,
                      options: MirrorOptions) -> MirrorHandle:
        """SC-8 launch (worker thread; spawn is process creation)."""
        return self._registry().mirror(serial).launch(options)

    def mirror_list(self, serial: Optional[str]) -> Tuple[MirrorHandle, ...]:
        """SC-8 registry snapshot (worker thread; process status reads)."""
        return self._registry().mirror(serial).list_running()

    def mirror_stop(self, serial: str, pid: Optional[int] = None) -> Tuple[int, ...]:
        return self._registry().mirror(serial).stop(pid)

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
