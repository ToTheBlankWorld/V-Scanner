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

from typing import Optional, Tuple

from vscanner.core.errors import AdbNotAvailable
from vscanner.core.models import ConnectionInfo, DeviceProfile
from vscanner.services.config import ConfigService
from vscanner.services.jobs import JobHandle, JobKind, JobManager
from vscanner.services.orchestration import app_listing_rows_plan
from vscanner.services.registry import ServiceRegistry
from vscanner.services.scanning.app_inventory import PackageInventoryService

__all__ = ["DesktopBackend"]


class DesktopBackend:
    """Session-scoped engine access for the desktop screens (Stage 10)."""

    def __init__(self, config_service: ConfigService) -> None:
        self._config = config_service
        self._registry_obj: Optional[ServiceRegistry] = None
        self._registry_adb_path: Optional[str] = None
        self._manager_obj: Optional[JobManager] = None

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
