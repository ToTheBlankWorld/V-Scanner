"""Pinned tool-release manifest (R-11 / SC-7).

The manifest is the small, reviewable source of truth for provisioning.
Principles:

* A pinned ``sha256`` is enforced before extraction whenever one is present
  in the manifest (checksum-mismatch → :class:`ProvisioningError`, nothing
  half-installed).
* NO fabricated fallback URLs: the shipped manifest contains no invented
  asset name. For Google's platform-tools the canonical
  ``platform-tools-latest-<os>.zip`` links are pinned constants (no asset
  suffix guessing). For scrcpy the URL must come from the live GitHub
  release API; the stale hardcoded v2.4 fallback is REMOVED (R-11) and an
  offline lookup fails with a typed, actionable error — we never claim an
  asset exists without checking.
* The manifest dict is data: updatable only by a maintainer commit or a
  future explicit user action (Stage 05 settings), never overwritten at
  runtime.
"""

from __future__ import annotations

import platform as _platform
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from vscanner.core.errors import ProvisioningError
from vscanner.core.models import ToolId

__all__ = [
    "ToolSpec", "ToolManifest", "DEFAULT_MANIFEST",
    "select_manifest_tool", "resolve_scrcpy_asset",
]

_FORMAL_OS = {
    "Windows": "windows",
    "Darwin": "darwin",
    "Linux": "linux",
}


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One pinned release entry; ``sha256=None`` means "no published digest —
    checksum verification skipped with a NOTE in status" (honest limitation)."""

    tool: ToolId
    platform_os: str                 # windows | darwin | linux
    arch: Optional[str]              # None for adb; x86_64 | arm64 for scrcpy
    download_url: Optional[str]      # None → resolve live (GitHub release API)
    sha256: Optional[str]
    archive_format: str              # "zip" | "tar.gz"


@dataclass(frozen=True, slots=True)
class ToolManifest:
    entries: Tuple[ToolSpec, ...] = ()
    schema_version: int = 1


# Google platform-tools canonical URLs (not version-suffixed; published by
# Google directly). No digests published upstream → sha256 None, documented.
_PLATFORM_TOOLS_URLS = {
    "windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}

DEFAULT_MANIFEST = ToolManifest(entries=tuple(
    ToolSpec(
        tool=ToolId.ADB,
        platform_os=plat,
        arch=None,
        download_url=url,
        sha256=None,
        archive_format="zip",
    )
    for plat, url in _PLATFORM_TOOLS_URLS.items()
))

# Special-case: darwin platform-tools are also distributed as .zip (Google
# canonical links above), so archive format stays "zip" everywhere here.


def current_os_key(system: Optional[str] = None) -> str:
    """Map ``platform.system()`` to the manifest's platform keys."""
    system = system if system is not None else _platform.system()
    try:
        return _FORMAL_OS[system]
    except KeyError:
        raise ProvisioningError(
            f"unsupported platform for tool provisioning: {system!r}",
            {"platform": system},
        ) from None


def select_manifest_tool(manifest: ToolManifest, tool: ToolId,
                         platform_os: str, version: Optional[str] = None) -> ToolSpec:
    """Select a manifest entry; deterministic and testable.

    ``version`` is reserved for future pinned-version support; shipping
    manifest pins only the canonical latest links today, unknown version
    requests fail honestly instead of guessing another URL.
    """
    if version not in (None, "", "latest"):
        raise ProvisioningError(
            "pinned-version installs are not configured in the shipped manifest "
            "(update the manifest or use 'latest')",
            {"version": version, "tool": tool.value},
        )
    for spec in manifest.entries:
        if spec.tool is tool and spec.platform_os == platform_os:
            return spec
    raise ProvisioningError(
        f"manifest has no {tool.value} entry for platform {platform_os!r}",
        {"tool": tool.value, "platform": platform_os},
    )


def resolve_scrcpy_asset(assets: Tuple[str, ...], platform_os: str,
                         arch: str) -> str:
    """Pick the scrcpy release asset by deterministic rules, or fail clearly.

    Rules mirror the legacy selection (same substring matching) with ONE
    reviewed drift adjustment recorded during the Stage 03 live smoke
    (2026-10-18): upstream renamed macOS arm64 assets from ``arm64`` to
    ``aarch64`` as of v5.x (release v5.0.1 ships ``scrcpy-macos-aarch64-*.``
    only), so the arm64 branch accepts both tokens. x86_64 macOS, win64 and
    linux rules are unchanged. No asset matching → :class:`ProvisioningError`
    with the candidates listed.
    """
    lowered = [a.lower() for a in assets]
    if platform_os == "windows":
        wanted = [a for a in lowered if "win64" in a and a.endswith(".zip")]
    elif platform_os == "darwin":
        token = "arm64" if arch == "arm64" else "x86_64"
        if token == "arm64":  # upstream v5.x renamed arm64 -> aarch64
            wanted = [a for a in lowered
                      if "macos" in a
                      and ("arm64" in a or "aarch64" in a)
                      and a.endswith(".tar.gz")]
        else:
            wanted = [a for a in lowered
                      if "macos" in a and token in a and a.endswith(".tar.gz")]
    else:  # linux
        wanted = [a for a in lowered if "linux" in a and a.endswith(".tar.gz")]

    if not wanted:
        raise ProvisioningError(
            "scrcpy release assets did not match a supported build for this "
            "platform (platform=%s arch=%s)" % (platform_os, arch),
            {"platform": platform_os, "arch": arch, "assets": ", ".join(sorted(assets))},
        )
    # Deterministic order among multiple matches (rare): alphabetical.
    return wanted[0]
