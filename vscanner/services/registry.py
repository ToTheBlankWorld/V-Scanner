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

    def scanner(self) -> ScanService:
        return ScanService(self.client())

    def actionable_serials(self) -> tuple:
        return actionable_serials(self._discovery.list_devices())
