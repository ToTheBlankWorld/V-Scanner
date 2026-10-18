"""Device info collection (SC-4).

Every probe independently degrades to ``None`` (honesty rule): a device that
does not answer a getprop key never causes the service to skip the profile
or invent a value. ``root_status`` is the R-05 tri-state ``UNKNOWN`` until a
verified probe succeeds (Stage 08 wiring; nothing here claims ROOTED).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Protocol, Sequence

from vscanner.core.models import DeviceProfile, RootStatus

__all__ = ["DeviceInfoService", "GETPROP_KEYS", "MAC_RE"]

_PROBE_TIMEOUT = 5.0


class _AdbTransport(Protocol):
    def run_text(self, cmd, timeout: float = 30.0):
        ...


# ro.* keys probed once, property name → profile attribute mapping.
GETPROP_KEYS = (
    ("ro.product.manufacturer", "mfr"),
    ("ro.product.model", "model"),
    ("ro.product.brand", "brand"),
    ("ro.product.board", "board"),
    ("ro.product.device", "device"),
    ("ro.hardware", "hardware"),
    ("ro.build.id", "build_id"),
    ("ro.build.version.release", "android"),
    ("ro.build.version.sdk", "sdk_int"),
    ("ro.build.version.security_patch", "patch"),
    ("ro.build.fingerprint", "fingerprint"),
    ("ro.bootloader", "bootloader"),
    ("ro.product.locale", "locale"),
    ("persist.sys.timezone", "timezone"),
    ("dhcp.wlan0.ipaddress", "ip"),
    ("ro.boot.wifimac0", "mac"),
)

MAC_RE = re.compile(r"^[0-9a-fA-F:]{17}$")


class DeviceInfoService:
    """SC-4 device-info face against one selected transport (serial-bound)."""

    def __init__(self, transport: _AdbTransport) -> None:
        self._transport = transport

    # -- internal ----------------------------------------------------------
    def _shell(self, cmd: Sequence[str], timeout: float = _PROBE_TIMEOUT) -> str:
        """Run a shell payload; any failure degrades to "" (absent field)."""
        try:
            result = self._transport.run_text(["shell", *cmd], timeout=timeout)
        except Exception:
            return ""
        if result.returncode != 0:
            return ""
        return (result.stdout or "").strip()

    def _getprop(self, key: str, timeout: float = _PROBE_TIMEOUT) -> str:
        return self._shell(["getprop", key], timeout=timeout)

    # -- public ------------------------------------------------------------
    def get_basic_profile(self) -> DeviceProfile:
        """Build the basic profile from one getprop key + kernel read per
        attribute; failures degrade the field to ``None`` honestly."""
        profile_dict: Dict[str, Any] = {
            "root_status": RootStatus.UNKNOWN,  # R-05: no probe → no lie
        }
        for key, attr in GETPROP_KEYS:
            value = self._getprop(key)
            if not value:
                continue
            if attr == "sdk_int":
                try:
                    profile_dict[attr] = int(value)
                except ValueError:
                    continue
            elif attr == "mac":
                profile_dict[attr] = value if MAC_RE.match(value) else None
            else:
                profile_dict[attr] = value

        # kernel (shell uname -r, honest None on failure)
        kernel = self._shell(["uname", "-r"])
        if kernel:
            profile_dict["kernel"] = kernel

        return DeviceProfile(**profile_dict)

    def get_full_profile(self) -> DeviceProfile:
        """Alias: Stage 03 gets profile facts from the same getprop map.
        Legacy's extra panels (RAM, storage, screen) are display-layer work
        tracked at Stage 06 (C-F19) — data here stays getprop-only."""
        return self.get_basic_profile()
