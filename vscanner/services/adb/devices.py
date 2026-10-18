"""Device discovery and selection (SC-1).

Parsing is a pure function over ``adb devices`` output. Unknown status
tokens map to :attr:`DeviceState.ABSENT` (never to "device") with the raw
token preserved as a diagnostic — an unknown state must not look actionable.
The legacy ``get_available_devices()`` filter semantics ("only state ==
'device' rows count") live inside the legacy shim, not here.
"""

from __future__ import annotations

from typing import Optional, Protocol, Sequence

from vscanner.core.errors import AdbNotAvailable
from vscanner.core.models import (
    ConnectionInfo,
    DeviceIdentity,
    DeviceState,
    DeviceTransport,
)

__all__ = [
    "STATE_TOKEN_MAP",
    "parse_adb_devices_output",
    "actionable_serials",
    "DeviceDiscoveryService",
    "identity_from_connection",
]

_HEADER = "list of devices attached"

# Honest token mapping; anything absent from this map lands on ABSENT with
# the raw token recorded (parity with the parser's discovery invariant).
STATE_TOKEN_MAP = {
    "device": DeviceState.DEVICE,
    "offline": DeviceState.OFFLINE,
    "unauthorized": DeviceState.UNAUTHORIZED,
    "recovery": DeviceState.RECOVERY,
}


def parse_adb_devices_output(stdout: str) -> tuple:
    """Parse ``adb devices`` output into a tuple of :class:`ConnectionInfo`.

    Non-strict on noise (blank lines, vendor banners); ``rejects`` nothing —
    unparseable rows are skipped (they carry no device), while parseable rows
    with unknown state tokens are kept as ABSENT diagnostics.
    """
    devices = []
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith(_HEADER):
            continue
        parts = line.split()
        if len(parts) < 2:
            # Some adb transports emit ``serial=state`` on one token.
            if len(parts) == 1 and "=" in parts[0]:
                parts = parts[0].split("=", 1)
            if len(parts) < 2:
                continue
        serial, raw_state = parts[0], parts[1].lower()
        state = STATE_TOKEN_MAP.get(raw_state, DeviceState.ABSENT)
        props = {p.split(":", 1)[0]: p.split(":", 1)[1] if ":" in p else "" for p in parts[2:]}
        if raw_state not in STATE_TOKEN_MAP and state is DeviceState.ABSENT:
            props = dict(props)
            props["raw_state"] = raw_state
        devices.append(
            ConnectionInfo(
                serial=serial,
                transport=DeviceTransport.UNKNOWN,  # plain `adb devices` carries no transport
                state=state,
                usb_props=dict(props),
            )
        )
    return tuple(devices)


def actionable_serials(devices: Sequence[ConnectionInfo]) -> tuple:
    """Serum set of DEVICE-state serials — the legacy shim's filter."""
    return tuple(info.serial for info in devices if info.state is DeviceState.DEVICE)


def identity_from_connection(info: ConnectionInfo, model: str = "", manufacturer: str = "",
                             android_version: str = "", sdk_int: Optional[int] = None,
                             security_patch: str = "") -> DeviceIdentity:
    """Build a DeviceIdentity for a serial, enriched from device-info probes
    when available (absent facts keep their honest defaults)."""
    return DeviceIdentity(
        serial=info.serial,
        model=model or "",
        manufacturer=manufacturer or "",
        android_version=android_version or "",
        sdk_int=sdk_int,
        security_patch=security_patch or "",
    )


class _AdbTransport(Protocol):
    """The minimal client shape services around this module depend on."""

    def run_text(self, cmd, timeout: float = 30.0):
        ...


class DeviceDiscoveryService:
    """SC-1 listing face: one ``adb devices`` command, honestly typed."""

    def __init__(self, transport: _AdbTransport) -> None:
        self._transport = transport

    def list_devices(self, timeout: float = 10.0) -> tuple:
        try:
            result = self._transport.run_text(["devices"], timeout=timeout)
        except AdbNotAvailable:
            raise
        return parse_adb_devices_output(result.stdout)

    def current_serial(self) -> Optional[str]:
        """First actionable serial, or ``None`` when none is present.

        Used by callers that keep a live serial implicit (parity with the
        legacy "auto-detect" behavior); explicit selection remains
        ``ServiceRegistry.select_device``.
        """
        try:
            devices = self.list_devices()
        except AdbNotAvailable:
            return None
        actionable = actionable_serials(devices)
        return actionable[0] if actionable else None
