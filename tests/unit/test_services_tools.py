"""Tools-manifest + provisioning service tests (Stage 03, SC-7 / R-11).

Deterministic: no network (fake url opener), no device (scrcpy installs are
probe-free; adb failure paths never launch anything), no binaries committed
(archives are crafted in memory).
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from vscanner.core.errors import ProvisioningError
from vscanner.core.models import ToolId, ToolState
from vscanner.services.tools.manifest import (
    DEFAULT_MANIFEST,
    ToolManifest,
    ToolSpec,
    current_os_key,
    resolve_scrcpy_asset,
    select_manifest_tool,
)
from vscanner.services.tools.provisioning import (
    SCRCPY_API_URL,
    ToolProvisioningService,
)


class FakeResponse:
    def __init__(self, payload: bytes, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def read(self, size=-1):
        if size == -1:
            data, self._payload = self._payload, b""
        else:
            data, self._payload = self._payload[:size], self._payload[size:]
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _zip_bytes(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, blob in members.items():
            zf.writestr(name, blob)
    return buf.getvalue()


SCRCPY_MANIFEST = ToolManifest(entries=(
    ToolSpec(tool=ToolId.SCRCPY, platform_os="windows", arch=None,
             download_url=None, sha256=None, archive_format="zip"),
))


def _scrcpy_service(tools_dir: Path, responses, **kwargs) -> ToolProvisioningService:
    calls = []

    def opener(url, timeout):
        calls.append(url)
        payload_type, payload = responses.pop(0)
        headers = payload_type.get("headers") if isinstance(payload_type, dict) else None
        return FakeResponse(payload, headers=headers)

    service = ToolProvisioningService(
        tools_dir=tools_dir, manifest=SCRCPY_MANIFEST,
        url_opener=opener, platform_system="Windows",
        platform_arch="AMD64", **kwargs,
    )
    service.calls = calls  # type: ignore[attr-defined]  # test-only handle
    return service


def _api_response(asset="scrcpy-9.0-win64.zip"):
    release = json.dumps({"assets": [{"name": asset,
                                      "browser_download_url": f"https://example.invalid/{asset}"}]})
    return ({}, release.encode("utf-8"))


class TestManifest:
    def test_default_manifest_pins_all_three_platform_tools_urls(self):
        for plat, expected in (
            ("windows", "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"),
            ("darwin", "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"),
            ("linux", "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"),
        ):
            spec = select_manifest_tool(DEFAULT_MANIFEST, ToolId.ADB, plat)
            assert spec.download_url == expected
            assert spec.archive_format == "zip"
            assert spec.sha256 is None  # no upstream digest — documented

    def test_pinned_version_requests_fail_honestly(self):
        with pytest.raises(ProvisioningError):
            select_manifest_tool(DEFAULT_MANIFEST, ToolId.ADB, "windows", version="34.0.5")

    def test_missing_platform_entry_is_typed(self):
        with pytest.raises(ProvisioningError):
            select_manifest_tool(DEFAULT_MANIFEST, ToolId.SCRCPY, "windows")

    def test_unknown_platform_rejected(self):
        with pytest.raises(ProvisioningError):
            current_os_key("SunOS")
        assert current_os_key("Windows") == "windows"
        assert current_os_key("Darwin") == "darwin"
        assert current_os_key("Linux") == "linux"


class TestScrcpyAssetResolution:
    def test_windows_win64_zip(self):
        assets = ("scrcpy-9.0-win64.zip", "scrcpy-9.0-macos-arm64-v1.tar.gz")
        assert resolve_scrcpy_asset(assets, "windows", "x86_64") == "scrcpy-9.0-win64.zip"

    def test_darwin_arm64_vs_x86_64(self):
        assets = ("scrcpy-9.0-macos-arm64-v1.tar.gz", "scrcpy-9.0-macos-x86_64-v1.tar.gz")
        assert resolve_scrcpy_asset(assets, "darwin", "arm64") == "scrcpy-9.0-macos-arm64-v1.tar.gz"
        assert resolve_scrcpy_asset(assets, "darwin", "x86_64") == "scrcpy-9.0-macos-x86_64-v1.tar.gz"

    def test_darwin_arm64_accepts_upstream_v5_aarch64_naming(self):
        """Reviewed drift (Stage 03 live smoke): upstream v5.0.1 publishes
        ``scrcpy-macos-aarch64-*`` only — the arm64 branch must match it."""
        assets = ("scrcpy-macos-aarch64-v5.0.1.tar.gz",
                  "scrcpy-macos-x86_64-v5.0.1.tar.gz",
                  "scrcpy-server-v5.0.1")
        assert resolve_scrcpy_asset(assets, "darwin", "arm64") == "scrcpy-macos-aarch64-v5.0.1.tar.gz"
        assert resolve_scrcpy_asset(assets, "darwin", "x86_64") == "scrcpy-macos-x86_64-v5.0.1.tar.gz"

    def test_linux_tar_gz(self):
        assert resolve_scrcpy_asset(("scrcpy-9.0-linux-x86_64.tar.gz",),
                                    "linux", "x86_64") == "scrcpy-9.0-linux-x86_64.tar.gz"

    def test_no_match_lists_candidates_and_fails_typed(self):
        with pytest.raises(ProvisioningError) as exc:
            resolve_scrcpy_asset(("scrcpy-9.0-future.tar.gz",), "windows", "x86_64")
        assert exc.value.details["assets"].find("scrcpy-9.0-future.tar.gz") != -1


class TestProvisioningHappyPath:
    def test_scrcpy_end_to_end_staging_to_install(self, tmp_path):
        tools = tmp_path / "tools"
        service = _scrcpy_service(tools, [
            _api_response(),
            ("bin", _zip_bytes({
                "scrcpy-9.0/scrcpy.exe": b"MZ fake",
                "scrcpy-9.0/scrcpy-server": b"server jar",
            })),
        ])
        status = service.provision_tool(ToolId.SCRCPY)
        assert status.state is ToolState.FOUND_UNVALIDATED
        assert (tools / "scrcpy" / "scrcpy.exe").exists()
        assert (tools / "scrcpy" / "scrcpy-server").exists()
        # staging area drained; only the live API + download URLs were called
        staging = tools / ".staging"
        assert not any(staging.iterdir())
        assert service.calls == [
            SCRCPY_API_URL,
            "https://github.com/Genymobile/scrcpy/releases/latest/download/scrcpy-9.0-win64.zip",
        ]

    def test_progress_callback_receives_bytes(self, tmp_path):
        calls = []

        def progress(downloaded, total):
            calls.append((downloaded, total))

        tools = tmp_path / "tools"
        service = _scrcpy_service(tools, [
            _api_response(),
            ("bin", _zip_bytes({"scrcpy-9.0/scrcpy.exe": b"MZ"})),
        ], )
        service.provision_tool(ToolId.SCRCPY, progress=progress)
        payload_size = len(_zip_bytes({"scrcpy-9.0/scrcpy.exe": b"MZ"}))
        assert calls[-1][0] == payload_size

    def test_offline_short_circuit_when_present(self, tmp_path):
        tools = tmp_path / "tools"
        (tools / "scrcpy").mkdir(parents=True)
        (tools / "scrcpy" / "scrcpy.exe").write_bytes(b"MZ")
        service = ToolProvisioningService(
            tools_dir=tools, manifest=SCRCPY_MANIFEST,
            url_opener=lambda *a, **k: pytest.fail("network must not be used"),
            platform_system="Windows",
        )
        status = service.ensure_tool(ToolId.SCRCPY)
        assert status.state is ToolState.FOUND_UNVALIDATED
        # provision_tool short-circuits identically — no network, no download
        assert service.provision_tool(ToolId.SCRCPY).state is ToolState.FOUND_UNVALIDATED


class TestProvisioningFailures:
    def test_checksum_mismatch_cleans_staging(self, tmp_path):
        tools = tmp_path / "tools"
        manifest = ToolManifest(entries=(
            ToolSpec(tool=ToolId.SCRCPY, platform_os="windows", arch=None,
                     download_url="https://example.invalid/scrcpy.zip",
                     sha256="0" * 64, archive_format="zip"),
        ))
        service = ToolProvisioningService(
            tools_dir=tools, manifest=manifest,
            url_opener=lambda url, timeout: FakeResponse(_zip_bytes({"x/y.exe": b"1"})),
            platform_system="Windows",
        )
        with pytest.raises(ProvisioningError) as exc:
            service.provision_tool(ToolId.SCRCPY)
        assert exc.value.cleanup_done is True
        staging = tools / ".staging"
        if staging.exists():
            assert not any(staging.iterdir())

    def test_checksum_unpinned_is_documented_limitation_not_a_crash(self, tmp_path):
        """sha256=None means 'no upstream digest published' — provisioning
        proceeds and the installed tool is reported FOUND_UNVALIDATED."""
        tools = tmp_path / "tools"
        service = _scrcpy_service(tools, [
            _api_response(),
            ("bin", _zip_bytes({"scrcpy-9.0/scrcpy.exe": b"MZ"})),
        ])
        assert service.provision_tool(ToolId.SCRCPY).state is ToolState.FOUND_UNVALIDATED

    def test_archive_without_executable_never_installs(self, tmp_path):
        tools = tmp_path / "tools"
        service = _scrcpy_service(tools, [
            _api_response(),
            ("bin", _zip_bytes({"docs/readme.txt": b"no exe here"})),
        ])
        with pytest.raises(ProvisioningError) as exc:
            service.provision_tool(ToolId.SCRCPY)
        assert "did not contain a scrcpy executable" in exc.value.message
        assert exc.value.cleanup_done is True
        assert not (tools / "scrcpy").exists()

    def test_traversal_member_rejected(self, tmp_path):
        tools = tmp_path / "tools"
        service = _scrcpy_service(tools, [
            _api_response(),
            ("bin", _zip_bytes({"../escape.bin": b"x"})),
        ])
        with pytest.raises(ProvisioningError):
            service.provision_tool(ToolId.SCRCPY)
        assert not (tmp_path / "escape.bin").exists()
        assert not (tools / "scrcpy").exists()

    def test_api_failure_means_no_url_and_no_download(self, tmp_path):
        tools = tmp_path / "tools"

        def opener(url, timeout):
            raise OSError("network unavailable")

        service = ToolProvisioningService(
            tools_dir=tools, manifest=SCRCPY_MANIFEST,
            url_opener=opener, platform_system="Windows",
        )
        with pytest.raises(ProvisioningError) as exc:
            service.provision_tool(ToolId.SCRCPY)
        assert "no offline fallback" in exc.value.message
        if tools.exists():
            assert not list(tools.rglob("*_staged.*"))

    def test_empty_download_rejected(self, tmp_path):
        tools = tmp_path / "tools"
        manifest = ToolManifest(entries=(
            ToolSpec(tool=ToolId.SCRCPY, platform_os="windows", arch=None,
                     download_url="https://example.invalid/empty.zip",
                     sha256=None, archive_format="zip"),
        ))
        service = ToolProvisioningService(
            tools_dir=tools, manifest=manifest,
            url_opener=lambda url, timeout: FakeResponse(b""),
            platform_system="Windows",
        )
        with pytest.raises(ProvisioningError) as exc:
            service.provision_tool(ToolId.SCRCPY)
        assert "empty archive" in exc.value.message

    def test_unsupported_platform_fails_before_network(self, tmp_path):
        service = ToolProvisioningService(
            tools_dir=tmp_path / "tools", manifest=DEFAULT_MANIFEST,
            url_opener=lambda *a, **k: pytest.fail("network must not be used"),
            platform_system="SunOS",
        )
        with pytest.raises(ProvisioningError):
            service.provision_tool(ToolId.ADB)

    def test_status_not_found_is_honest(self, tmp_path):
        service = ToolProvisioningService(
            tools_dir=tmp_path / "tools", manifest=DEFAULT_MANIFEST,
            url_opener=lambda *a, **k: pytest.fail("network must not be used"),
            platform_system="Windows",
        )
        status = service.tool_status(ToolId.ADB)
        assert status.state is ToolState.NOT_FOUND
        assert status.path is None
