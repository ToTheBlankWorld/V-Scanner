"""ToolProvisioningService (SC-7): safe tool download → verify → extract.

R-11 workflow implemented end-to-end:

1. Offline short-circuit: an executable already present short-circuits into
   a VALIDATED (adb: launch-probed) or FOUND_UNVALIDATED (scrcpy) status —
   no network, no download.
2. Manifest or live-API URL resolution (no invented fallback assets).
3. Download into the tools tree staging area (``.staging``).
4. Manifest sha256 verification BEFORE extraction when pinned; no digest in
   the manifest ⇒ checksum skipped with an explicit status NOTE (limitation
   documented in SECURITY_AND_REMEDIATION_PLAN R-11).
5. Member-safe extraction into a fresh staging dir, then an atomic move into
   the final tool dir. Any failure removes the staging tree AND the staged
   archive, and reports INSTALL_FAILED with ``cleanup_done=True``.

The repository never ships binaries: provisioned tools land under the user
data dir (or the legacy tools dir when the caller explicitly configures it)
— R-15/R-09 hygiene rule.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform as _platform
import shutil
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable, cast, Optional, Protocol, Tuple
from urllib.request import urlopen

from vscanner.core.errors import JobCancelRequested, ProvisioningError
from vscanner.core.models import ToolId, ToolState, ToolStatusReflected
from vscanner.services.adb.executable import check_adb_valid
from vscanner.services.tools.manifest import (
    DEFAULT_MANIFEST,
    ToolManifest,
    ToolSpec,
    current_os_key,
    resolve_scrcpy_asset,
    select_manifest_tool,
)
from vscanner.services.tools import _extraction

if TYPE_CHECKING:  # pragma: no cover - import guard only
    from vscanner.services.jobs import JobContext  # noqa: F401

__all__ = ["ToolProvisioningService", "SCRCPY_API_URL", "DownloadProgress"]

SCRCPY_API_URL = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
CHUNK_SIZE = 8192
_READ_TIMEOUT = 30
_API_TIMEOUT = 10


def _chain_progress(
    progress: Optional[DownloadProgress], context: "JobContext"
) -> DownloadProgress:
    """Optional caller callback + job progress emission, in a stable order
    (caller first so legacy semantics are untouched; the job progress event
    is additive). Context-transient — never stored on the instance."""
    def chained(downloaded: int, total: Optional[int]) -> None:
        if progress is not None:
            progress(downloaded, total)
        context.progress(downloaded, total, unit="bytes", context="staged download")
    return chained


class DownloadProgress(Protocol):
    """Optional progress callback (bytes downloaded so far, total or None)."""

    def __call__(self, downloaded: int, total: Optional[int]) -> None:
        ...


class _UrlOpener(Protocol):
    """Injectable network boundary (tests pass fakes; no network in tests)."""

    def __call__(self, url: str, timeout: float):
        ...


class ToolProvisioningService:
    """SC-7 provisioning + status face (synchronous; Stage 04 wraps in jobs)."""

    def __init__(
        self,
        tools_dir: Path,
        manifest: ToolManifest = DEFAULT_MANIFEST,
        url_opener: Optional[_UrlOpener] = None,
        platform_system: Optional[str] = None,
        platform_arch: Optional[str] = None,
    ) -> None:
        self._tools_dir = Path(tools_dir)
        self._manifest = manifest
        self._url_opener: _UrlOpener = url_opener or cast(_UrlOpener, urlopen)
        self._system = platform_system
        self._arch = platform_arch

    # ------------------------------------------------------------------ #
    # platform & manifest resolution
    # ------------------------------------------------------------------ #

    @property
    def os_key(self) -> str:
        return current_os_key(self._system)

    def _spec(self, tool: ToolId, version: Optional[str] = None) -> ToolSpec:
        return select_manifest_tool(self._manifest, tool, self.os_key, version=version)

    def _arch_value(self) -> str:
        return (self._arch or _platform.machine() or "").lower()

    # ------------------------------------------------------------------ #
    # status
    # ------------------------------------------------------------------ #

    def tool_status(self, tool: ToolId) -> ToolStatusReflected:
        """Honest current state; ADB additionally launch-probes when found."""
        path = self.tool_path(tool)
        if path is None or not path.exists():
            return ToolStatusReflected(tool=tool, state=ToolState.NOT_FOUND)
        if tool is ToolId.ADB:
            validated = check_adb_valid(str(path))
            notes = () if validated else ("present but `adb version` probe failed",)
            return ToolStatusReflected(
                tool=tool,
                state=ToolState.VALIDATED if validated else ToolState.INSTALL_FAILED,
                path=str(path),
                last_validation_ok=validated,
                notes=notes,
            )
        return ToolStatusReflected(tool=tool, state=ToolState.FOUND_UNVALIDATED, path=str(path))

    def tool_path(self, tool: ToolId) -> Optional[Path]:
        if tool is ToolId.ADB:
            return self._tools_dir / "platform-tools" / (
                "adb.exe" if self.os_key == "windows" else "adb"
            )
        return self._tools_dir / "scrcpy" / ("scrcpy.exe" if self.os_key == "windows" else "scrcpy")

    # ------------------------------------------------------------------ #
    # offline short-circuit
    # ------------------------------------------------------------------ #

    def ensure_tool(self, tool: ToolId) -> ToolStatusReflected:
        """Return valid status if the tool already exists; do NOT download here."""
        status = self.tool_status(tool)
        if tool is ToolId.ADB and status.state is ToolState.VALIDATED:
            return status
        if tool is ToolId.SCRCPY and status.path and Path(status.path).exists():
            return status
        return status  # not-found installs go through provision_tool()

    # ------------------------------------------------------------------ #
    # provisioning
    # ------------------------------------------------------------------ #

    def provision_tool(self, tool: ToolId, version: Optional[str] = None,
                       progress: Optional[DownloadProgress] = None,
                       context: Optional["JobContext"] = None) -> ToolStatusReflected:
        """Download → verify → extract → install ``tool``.

        Raises :class:`JobCancelRequested` at the documented cooperative
        cancellation points (download-chunk boundaries; before extract;
        before the install move — the staged archive is discarded in that
        case by the cleanup below), and :class:`ProvisioningError`
        (network, checksum, extraction, unsupported platform) with
        ``cleanup_done=True`` after staging cleanup; re-raises
        :class:`AdbNotAvailable` through validation.
        """
        if context is not None:
            progress = _chain_progress(progress, context)
        status = self.ensure_tool(tool)
        if status.state is ToolState.VALIDATED or (
            tool is ToolId.SCRCPY and status.path and Path(status.path).exists()
        ):
            return status  # offline short-circuit: already satisfied

        spec = self._spec(tool, version)
        url = spec.download_url or self._resolve_live_url(tool)
        try:
            if self.os_key not in ("windows", "darwin", "linux"):
                raise ProvisioningError(
                    f"unsupported platform for tool provisioning: {self.os_key!r}",
                    {"platform": self.os_key},
                )

            staging_root = self._tools_dir / ".staging"
            staging_root.mkdir(parents=True, exist_ok=True)
            archive_path = staging_root / f"{tool.value}_staged.{spec.archive_format}"
            extract_dir = staging_root / f"{tool.value}_extract"

            try:
                self._download(url, archive_path, progress, context)
                if context is not None:
                    context.cancel_token.checkpoint("before_extract")
                self._verify_checksum(archive_path, spec.sha256)
                if extract_dir.exists():
                    shutil.rmtree(extract_dir)
                self._extract_archive(archive_path, extract_dir, spec.archive_format)
                if context is not None:
                    context.cancel_token.checkpoint("before_install_move")
                self._install_from_staging(tool, extract_dir)
            finally:
                self._cleanup_staging(archive_path, extract_dir)

        except (ProvisioningError, JobCancelRequested):
            raise
        except Exception as exc:
            raise ProvisioningError(
                f"provisioning {tool.value} failed: {exc}",
                {"url": url, "cause": str(exc)},
                cleanup_done=True,
            ) from exc

        return self.tool_status(tool)

    # -- internals -------------------------------------------------------- #

    def _resolve_live_url(self, tool: ToolId) -> str:
        """Live resolution for tools whose manifest has no pinned URL (scrcpy).

        NO fallback URL is invented when this fails (R-11: stale v2.4 pin
        removed). An unreachable release API yields a typed actionable error.
        """
        if tool is not ToolId.SCRCPY:
            raise ProvisioningError(
                f"{tool.value} has no pinned download URL and no live resolver",
                {"tool": tool.value},
            )
        try:
            with self._url_opener(SCRCPY_API_URL, _API_TIMEOUT) as response:
                release = json.load(response)
            assets = tuple(
                asset["name"]
                for asset in release.get("assets", [])
                if isinstance(asset, dict) and asset.get("name")
            )
            asset_name = resolve_scrcpy_asset(assets, self.os_key, self._arch_value())
            return "https://github.com/Genymobile/scrcpy/releases/latest/download/" + asset_name
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "could not resolve the current scrcpy release over the network "
                "(no offline fallback URL is shipped after R-11; retry online or "
                "install scrcpy manually)",
                {"url": SCRCPY_API_URL, "cause": str(exc)},
            ) from exc

    def _download(self, url: str, dest: Path,
                  progress: Optional[DownloadProgress],
                  context: Optional["JobContext"] = None) -> None:
        downloaded = 0
        total: Optional[int] = None
        try:
            with self._url_opener(url, _READ_TIMEOUT) as response:
                total_raw = response.headers.get("Content-Length") if hasattr(response, "headers") else None
                total = int(total_raw) if total_raw else None
                with open(dest, "wb") as fh:
                    while True:
                        chunk = response.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if progress is not None:
                            progress(downloaded, total)
                        if context is not None:
                            # Cancellation point (§5): between download chunks.
                            context.cancel_token.checkpoint("during_download")
        except (JobCancelRequested, KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise ProvisioningError(
                f"download failed: {exc}",
                {"url": url, "cause": str(exc)},
                cleanup_done=True,
            ) from exc
        if dest.stat().st_size == 0:
            raise ProvisioningError("download produced an empty archive", {"url": url})

    @staticmethod
    def _verify_checksum(archive_path: Path, sha256: Optional[str]) -> None:

        if not sha256:
            return  # documented limitation: no digest pinned for this entry
        digest = hashlib.sha256()
        with open(archive_path, "rb") as fh:
            for block in iter(lambda: fh.read(65536), b""):
                digest.update(block)
        if digest.hexdigest().lower() != sha256.lower():
            raise ProvisioningError(
                "downloaded archive failed checksum verification",
                {"expected": sha256, "actual": digest.hexdigest().lower()},
                cleanup_done=True,
            )

    def _extract_archive(self, archive_path: Path, extract_dir: Path,
                         archive_format: str) -> None:
        try:
            if archive_format == "zip":
                _extraction.safe_extract_zip(archive_path, extract_dir)
            else:
                _extraction.safe_extract_tar(archive_path, extract_dir)
        except Exception as exc:
            raise ProvisioningError(
                f"archive extraction failed: {exc}",
                {"cause": str(exc)},
                cleanup_done=True,
            ) from exc

    def _install_from_staging(self, tool: ToolId, extract_dir: Path) -> None:
        """Move the staged extraction into its final place (R-11: an archive
        without the expected executable must never produce a 'valid' tool)."""
        import shutil

        if tool is ToolId.ADB:
            exe_name = "adb.exe" if self.os_key == "windows" else "adb"
            candidates = list(extract_dir.rglob(exe_name))
            if not candidates:
                raise ProvisioningError(
                    "archive did not contain a platform-tools/adb executable",
                    cleanup_done=True,
                )
            adb_dir = extract_dir / "platform-tools"
            target = self._tools_dir / "platform-tools"
            if adb_dir.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(adb_dir), str(target))
            else:
                target.mkdir(parents=True, exist_ok=True)
                for candidate in candidates:
                    shutil.copy2(str(candidate), str(target / candidate.name))
            exe = target / exe_name
            if not exe.exists():
                raise ProvisioningError(
                    "adb executable missing after install", cleanup_done=True
                )
        else:
            exe_name = "scrcpy.exe" if self.os_key == "windows" else "scrcpy"
            candidates = list(extract_dir.rglob(exe_name))
            if not candidates:
                raise ProvisioningError(
                    "archive did not contain a scrcpy executable", cleanup_done=True
                )
            target = self._tools_dir / "scrcpy"
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(extract_dir / candidates[0].parent.name), str(target))
            exe = target / exe_name
            if not exe.exists():
                raise ProvisioningError(
                    "scrcpy executable missing after install", cleanup_done=True
                )

    def _cleanup_staging(self, archive_path: Path, extract_dir: Path) -> None:
        for path in (archive_path, extract_dir):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.is_file():
                    path.unlink()
            except OSError:
                pass  # best-effort; leftover junk in .staging is never treated as a tool
