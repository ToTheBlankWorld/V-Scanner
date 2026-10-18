"""Package dumpsys → AppInfo (SC-2/SC-3 parsing face).

Single source of truth for parsing ``dumpsys package <name>``. The legacy
``ADBInterface.get_package_info`` performs the same extraction, but falls
back to placeholder sentinels ("Unknown", 0) where data is missing — here,
absent data stays ``None`` (honesty rule), and only the legacy report writer
fills placeholder-equivalent values at the serialization boundary.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from vscanner.core.models import AppInfo, AppLabelSource

__all__ = ["parse_package_dump", "parse_pm_list_output", "derived_label"]

_VERSION_NAME_RE = re.compile(r"versionName=([^\s]+)")
_VERSION_CODE_RE = re.compile(r"versionCode=(\d+)")
_TARGET_SDK_RE = re.compile(r"targetSdk(?:Version)?=(\d+)")
_MIN_SDK_RE = re.compile(r"minSdk(?:Version)?=(\d+)")
_CODE_PATH_RE = re.compile(r"codePath=(.+)")
_FIRST_INSTALL_RE = re.compile(r"firstInstallTime=(.+)")
_LAST_UPDATE_RE = re.compile(r"lastUpdateTime=(.+)")

_DERIVED_LABEL_SOURCE = AppLabelSource.HEURISTIC


def parse_pm_list_output(stdout: str) -> tuple:
    """Parse ``pm list packages`` output into an ordered tuple of names."""
    names = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("package:"):
            name = line[len("package:"):].strip()
            if name:
                names.append(name)
    return tuple(names)


def derived_label(package_name: str) -> str:
    """Legacy-compatible heuristic label: last dotted segment, title-cased.

    Marked ``HEURISTIC`` upstream so UIs can badge derived labels instead of
    implying an authoritative app name."""
    try:
        return package_name.split(".")[-1].title() or "(unknown)"
    except IndexError:  # pragma: no cover - str.split never raises IndexError
        return "(unknown)"


def _parse_device_time(raw: Optional[str]) -> Optional[datetime]:
    """``firstInstallTime=2024-01-02 12:34:56`` → aware UTC datetime.

    Device-local timezone is not carried by dumpsys output; stamps are
    interpreted as UTC (documented approximation, no fabrication)."""
    if not raw:
        return None
    raw = raw.strip()
    for candidate in (raw, raw.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            continue
    return None


def parse_package_dump(package_name: str, stdout: str, is_system: bool = False) -> AppInfo:
    """Extract an AppInfo from a ``dumpsys package`` payload.

    Permission parsing mirrors the legacy section-walk: lines after the
    ``requested permissions:`` heading, terminated by the next unindented
    non-permission line. Unknown version fields stay ``None``.
    """
    info_kwargs: Dict[str, Any] = {
        "package_name": package_name,
        "label": derived_label(package_name),
        "label_source": _DERIVED_LABEL_SOURCE,
        "is_system": is_system,
    }
    if not stdout:
        return AppInfo(**info_kwargs)

    requested: list = []
    in_permissions = False
    for line in stdout.splitlines():
        stripped = line.strip()

        if "versionName=" in stripped:
            m = _VERSION_NAME_RE.search(stripped)
            if m:
                info_kwargs["version_name"] = m.group(1)
        if "versionCode=" in stripped:
            m = _VERSION_CODE_RE.search(stripped)
            if m:
                info_kwargs["version_code"] = int(m.group(1))
        if "targetSdk=" in stripped or "targetSdkVersion=" in stripped:
            m = _TARGET_SDK_RE.search(stripped)
            if m:
                info_kwargs["target_sdk"] = int(m.group(1))
        if "minSdk=" in stripped or "minSdkVersion=" in stripped:
            m = _MIN_SDK_RE.search(stripped)
            if m:
                info_kwargs["min_sdk"] = int(m.group(1))
        if "codePath=" in stripped:
            m = _CODE_PATH_RE.search(stripped)
            if m:
                info_kwargs["apk_path"] = m.group(1).strip()
        if "firstInstallTime=" in stripped:
            m = _FIRST_INSTALL_RE.search(stripped)
            if m:
                info_kwargs["first_install_time"] = _parse_device_time(m.group(1))
        if "lastUpdateTime=" in stripped:
            m = _LAST_UPDATE_RE.search(stripped)
            if m:
                info_kwargs["last_update_time"] = _parse_device_time(m.group(1))

        if "requested permissions:" in stripped.lower():
            in_permissions = True
            continue
        if in_permissions:
            if stripped.startswith("android.permission.") or stripped.startswith("com."):
                perm = stripped.split(":")[0].split()[0]
                requested.append(perm)
            elif stripped and not stripped.startswith(" ") and "permission" not in stripped.lower():
                in_permissions = False

    info_kwargs["requested_permissions"] = tuple(requested)
    return AppInfo(**info_kwargs)
