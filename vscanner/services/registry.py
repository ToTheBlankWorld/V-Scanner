"""ServiceRegistry — the Stage 03 composition seam.

Composes the engine services with one device selection (per-registry state,
never a module-level global — a documented improvement over the legacy
``ADB_PATH`` global). The Stage 04 job system will be layered ON TOP of
these instances; none of the services here require it.

Selection semantics (SC-1): ``select_device`` validates against a listing
of the *current* device set — unauthorized devices are reported through
:class:`DeviceUnauthorized` (caller decides whether to surface guidance),
non-actionable states through :class:`DeviceNotConnected` (details.serial).
``serial=None`` clears the binding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from vscanner.core.errors import (
    AdbNotAvailable,
    DeviceNotConnected,
    DeviceUnauthorized,
)
from vscanner.core.models import ConnectionInfo, DeviceIdentity, DeviceState
from vscanner.services.adb.client import SubprocessAdbClient
from vscanner.services.adb.devices import DeviceDiscoveryService, actionable_serials
from vscanner.services.reports.service import ReportService
from vscanner.services.scanning.app_inventory import PackageInventoryService
from vscanner.services.scanning.scanner import ScanService
__all__ = ["ServiceRegistry"]


@dataclass
class ServiceRegistry:
    """Session-level service container and current-device binding."""

    adb_path: Optional[str]
    _discovery: DeviceDiscoveryService = field(init=False, repr=False)
    _client: Optional[SubprocessAdbClient] = field(init=False, repr=False, default=None)
    reports: ReportService = field(default_factory=ReportService)
    selected_serial: Optional[str] = field(default=None, init=False)
    selected_identity: Optional[DeviceIdentity] = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not self.adb_path:
            raise AdbNotAvailable("no ADB path resolved; cannot build the registry")
        self._client = SubprocessAdbClient(self.adb_path)
        self._discovery = DeviceDiscoveryService(self._client)

    # -- device surface ---------------------------------------------------- #

    def discovery(self) -> DeviceDiscoveryService:
        return self._discovery

    def client(self, serial: Optional[str] = None) -> SubprocessAdbClient:
        adb_path = self.adb_path
        if not adb_path:  # narrowed for the type checker (post_init guards it)
            raise AdbNotAvailable("no ADB path resolved")
        return SubprocessAdbClient(
            adb_path, serial if serial is not None else self.selected_serial
        )

    def list_devices(self):
        return self._discovery.list_devices()

    def select_device(self, serial: Optional[str],
                      identity: Optional[DeviceIdentity] = None) -> DeviceIdentity:
        """Bind the current device, validating its present state first."""
        devices = self._discovery.list_devices()
        if serial is None:
            self.selected_serial = None
            self.selected_identity = None
            return identity if identity is not None else DeviceIdentity(serial="")
        match: Optional[ConnectionInfo] = None
        for info in devices:
            if info.serial == serial:
                match = info
                break
        if match is None:
            raise DeviceNotConnected(
                message=f"device {serial!r} is not connected right now",
                serial=serial,
            )
        if match.state is DeviceState.DEVICE:
            self.selected_serial = serial
            self.selected_identity = identity
            if identity is not None:
                return identity
            return DeviceIdentity(serial=serial)
        if match.state is DeviceState.UNAUTHORIZED:
            raise DeviceUnauthorized(serial=serial)
        raise DeviceNotConnected(
            message=f"device {serial!r} is present but not usable (state={match.state.value})",
            serial=serial,
        )

    # -- service surfaces --------------------------------------------------- #

    def inventory(self) -> PackageInventoryService:
        return PackageInventoryService(self.client())

    def device_info(self, serial: Optional[str] = None):
        """SC-4 face bound to the given (or current) device.

        Narrow Stage 06 accessor: the UI needs DeviceProfile probes for an
        explicitly selected device; the service composition stays here so
        widgets never construct transports themselves."""
        from vscanner.services.adb.device_info import DeviceInfoService

        return DeviceInfoService(self.client(serial))

    def scanner(self) -> ScanService:
        return ScanService(self.client())

    # -- Stage 08 service surfaces ------------------------------------------ #

    def monitor(self, serial: Optional[str] = None):
        """SC-6 monitoring face (Stage 08) bound to the given (or current)
        device; honest sensor readings + capability polls only."""
        from vscanner.services.monitoring import MonitoringService

        return MonitoringService(self.client(serial))

    def admin(self, serial: Optional[str] = None):
        """SC-5 administration face; destructive-capable operations MUST go
        through its confirmation gate (R-13 service-side)."""
        from vscanner.services.admin import AdministrationService

        return AdministrationService(self.client(serial))

    def root_status(self, serial: Optional[str] = None):
        """R-05 verified tri-state root detector bound to one device."""
        from vscanner.services.adb.root_probe import RootStatusService

        return RootStatusService(self.client(serial))

    def forensics(self, serial: Optional[str] = None, case_root=None):
        """Forensics face (Stage 08). The case store defaults to the A-07
        app-data ``cases_dir()``; tests may relocate with ``case_root``."""
        from pathlib import Path as _Path

        from vscanner.services.forensics import ForensicsService

        return ForensicsService(
            self.client(serial),
            base_dir=_Path(case_root) if case_root else None,
        )

    def provisioning(self):
        """Tool-status face: reuse the existing provisioning service lockup
        for validated-tool preconditions (never provision newly here)."""
        from vscanner.core.paths import tools_dir
        from vscanner.services.tools.manifest import DEFAULT_MANIFEST
        from vscanner.services.tools.provisioning import (
            ToolProvisioningService,
        )

        return ToolProvisioningService(tools_dir(), manifest=DEFAULT_MANIFEST)

    def mirror(self, serial: Optional[str] = None):
        """SC-8 mirroring face: validate → launch → stop lifecycle."""
        from vscanner.core.models import ToolId
        from vscanner.services.mirroring import ScreenMirrorService

        provisioning = self.provisioning()

        def status():
            return provisioning.tool_status(ToolId.SCRCPY)

        def scrcpy_path():
            path = provisioning.tool_path(ToolId.SCRCPY)
            return str(path) if path is not None else None

        return ScreenMirrorService(
            adb_path=lambda: self.adb_path or "",
            scrcpy_path=scrcpy_path,
            tool_status=status,
            serial=serial if serial is not None else self.selected_serial,
        )

    def demo(self):
        """SC-10 demo fixture face (no device involvement)."""
        from vscanner.services.demo import DemoService

        return DemoService()

    def actionable_serials(self) -> tuple:
        return actionable_serials(self._discovery.list_devices())
