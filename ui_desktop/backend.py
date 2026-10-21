"""Production desktop-engine adapter (Stage 10; Stage 12 parity seam) — the
Qt counterpart of the TUI's ``ui_terminal/backend.py`` workspace seam.

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

from vscanner.core.errors import AdbNotAvailable, InputValidationError
from vscanner.core.models import (
    AppScanResult,
    ConnectionInfo,
    DeviceProfile,
    MirrorHandle,
    MirrorOptions,
    ScanConfiguration,
    ScanKind,
    ScanRequest,
    ScanResultBundle,
    SensorReading,
    ToolId,
    ToolStatusReflected,
)
from vscanner.core.paths import history_dir
from vscanner.services.config import ConfigService
from vscanner.services.history import HistoryEntry, ScanHistoryStore
from vscanner.services.jobs import JobHandle, JobKind, JobManager
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
        # ONE ScreenMirrorService per target per session (mirroring handle
        # continuity: launch/list/stop — see _mirror_service).
        self._mirror_clients: dict[str, Any] = {}

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

    # -- Stage 08 parity (Stage 12): monitoring / admin / forensics / mirror / demo -- #

    def read_sensors_once(self, serial: str) -> Tuple[SensorReading, ...]:
        """R-04 honest one-shot sensor read (worker threads only).

        Zero parseable output is a single UNAVAILABLE row with the reason —
        never invented names or values (the legacy Method-3 fabrication is
        not ported by the engine and must not be recreated here)."""
        return self._registry().monitor(serial).read_sensor_values_once()

    def start_monitoring_session(self, serial: str,
                                 interval_s: float = 2.0) -> JobHandle:
        """MONITORING_SESSION job (SC-6): polls the honest usage surface on
        the worker thread and emits typed snapshot payloads until the user
        stops it or three consecutive polls fail (engine abort)."""
        plan = monitoring_session_plan(
            self._registry().monitor(serial), serial, interval_s=interval_s)
        return self.manager().submit(
            JobKind.MONITORING_SESSION, device_serial=serial, plan=plan,
            params_summary={"device": serial, "interval_s": f"{interval_s:g}"},
        )

    def stop_monitoring(self, serial: str) -> None:
        """Targeted cancel of the device's monitoring session — a user
        stopping the monitor must NOT cancel a running scan/listing
        (unlike ``cancel_device_work``)."""
        handle = self.active_monitoring_handle(serial)
        if handle is not None:
            handle.cancel()

    def active_monitoring_handle(self, serial: str) -> Optional[JobHandle]:
        for handle in reversed(self.manager().active_for_device(serial)):
            if handle.kind is JobKind.MONITORING_SESSION:
                return handle
        return None

    def start_admin_job(self, serial: str, op: str, package: str,
                        confirmation: Any) -> JobHandle:
        """ADMIN_OP job (SC-5): the minted OperationConfirmation travels to
        the SERVICE gate (R-13) — this backend builds no gate of its own;
        ConfirmationRequired/Invalid re-raise typed from the service.

        ``op`` is one of the documented engine op names: ``launch_app`` |
        ``force_stop_app`` | ``uninstall_app`` (the only operations the
        AdministrationService supports — nothing else is exposed here)."""
        if op not in ("launch_app", "force_stop_app", "uninstall_app"):
            raise InputValidationError(
                f"unsupported administration operation {op!r}",
                {"field": "op"},
            )
        plan = admin_op_plan(self._registry().admin(serial), op, package,
                             confirmation)
        return self.manager().submit(
            JobKind.ADMIN_OP, device_serial=serial, plan=plan,
            params_summary={"device": serial, "op": op, "package": package},
        )

    def start_forensics_job(self, serial: str, op: str,
                            kwargs: Optional[dict] = None) -> JobHandle:
        """FORENSICS_OP job wrapper (TUI Stage 08 parity); ``op`` maps to
        documented engine ops: create_case | extract_app_data |
        system_logs | installed_packages | running_processes |
        wifi_cleartext | report. The wifi op sends the confirmation token
        ONLY when the UI obtained the exact typed acknowledgement (the
        service gate stays effective — acknowledge_cleartext_psk=None keeps
        the default REDACTED extraction)."""
        from vscanner.core.errors import InputValidationError as _IVE
        from vscanner.core.events import OperationConfirmation as _OC

        service = self._registry().forensics(serial)
        call_kwargs = dict(kwargs or {})

        def _runner(context: Any = None) -> Any:
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
                raise _IVE("forensics op requires case_id",
                           {"field": "case_id"})
            manifest = service.load_case(case_id)
            if op == "extract_app_data":
                return service.extract_app_data_files(
                    package=call_kwargs["package"],
                    sources=tuple(call_kwargs.get(
                        "sources",
                        ("databases", "shared_prefs", "files"))),
                    manifest=manifest,
                    context=context,
                )
            if op == "system_logs":
                return service.extract_system_logs(manifest)
            if op == "installed_packages":
                return service.extract_installed_packages(manifest)
            if op == "running_processes":
                return service.extract_running_processes(manifest)
            if op == "wifi_redacted":
                # R-12 default: unredacted acknowledgement absent, so the
                # engine writes the redacted wifi_networks.txt only
                if "confirmation" in call_kwargs:
                    raise _IVE(
                        "the wifi redacted op accepts no acknowledgement "
                        "(use wifi_cleartext)", {"field": "confirmation"})
                return service.extract_wifi_networks(manifest)
            if op == "wifi_cleartext":
                confirmation = call_kwargs.get("confirmation")
                if confirmation is not None and \
                        not isinstance(confirmation, _OC):
                    raise _IVE(
                        "wifi cleartext acknowledgement must be an "
                        "OperationConfirmation", {"field": "confirmation"})
                return service.extract_wifi_networks(
                    manifest, acknowledge_cleartext_psk=confirmation)
            if op == "report":
                report_path = service.generate_report(manifest)
                return manifest, report_path
            raise _IVE(f"unknown forensics op {op!r}", {"field": "op"})

        plan = forensics_job_plan(_runner, f"forensics {op}")
        summary: dict = {"device": serial, "op": op}
        if call_kwargs.get("case_id"):
            summary["case"] = str(call_kwargs["case_id"])[:64]
        return self.manager().submit(
            JobKind.FORENSICS_OP, device_serial=serial, plan=plan,
            params_summary=summary,
        )

    def forensics_load_case(self, case_id: str) -> Any:
        """Reopen a saved case manifest by id (worker thread; disk read)."""
        return self._registry().forensics(None).load_case(case_id)

    def demo_bundle(self) -> Any:
        """SC-10 deterministic demo bundle — built in-process; NO device,
        transport, or network is ever created (cheap enough to stay UI-
        thread safe by construction, exactly like the TUI screen)."""
        return self._registry().demo().scan()

    def mirror_tool_status(self) -> ToolStatusReflected:
        """Honest scrcpy tool state from the engine's provisioning face
        (worker thread; filesystem stats). Mirroring requires the tool to
        be ``ToolState.VALIDATED`` — anything else must surface as the
        typed refusal the engine raises on launch."""
        return self._registry().provisioning().tool_status(ToolId.SCRCPY)

    def _mirror_service(self, serial: str):
        """ONE ``ScreenMirrorService`` per target per application session.

        The registry ``mirror()`` face constructs a fresh (stateless)
        service instance on every call; the handle registry — launch/list/
        stop continuity and honest exit codes — lives on the INSTANCE,
        so the desktop backend caches one per serial for the session.
        Mirrors opened outside this session (another tool instance) are
        still invisible to it and are never claimed."""
        cached = self._mirror_clients.get(serial)
        if cached is None:
            cached = self._registry().mirror(serial)
            self._mirror_clients[serial] = cached
        return cached

    def mirror_launch(self, serial: str,
                      options: MirrorOptions) -> MirrorHandle:
        """SC-8 launch (worker thread; spawning is process creation)."""
        return self._mirror_service(serial).launch(options)

    def mirror_list(self, serial: Optional[str]) -> Tuple[MirrorHandle, ...]:
        """SC-8 registry snapshot (worker thread; process status reads;
        exit codes are honest when observed)."""
        return self._mirror_service(serial or "").list_running()

    def mirror_stop(self, serial: str, pid: Optional[int] = None
                    ) -> Tuple[int, ...]:
        """Stop the target's mirror(s); returns exactly what the service
        stopped (pids that received terminate)."""
        return self._mirror_service(serial).stop(pid)

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
