"""Tool-manager characterization tests (Stage 02 — section D, part 1: URLs).

No network access: GitHub API responses are monkey-patched. The stale
scrcpy v2.4 fallback (R-11) is documented here, not blessed.
"""

from __future__ import annotations

import json

import pytest

import tools_manager as tm

SCRCPY_RELEASE_JSON = json.dumps({
    "assets": [
        {"name": "scrcpy-3.1-linux-x86_64.tar.gz",
         "browser_download_url": "https://github.com/Genymobile/scrcpy/releases/download/v3.1/scrcpy-3.1-linux-x86_64.tar.gz"},
        {"name": "scrcpy-3.1-win64-v2.zip",
         "browser_download_url": "https://github.com/Genymobile/scrcpy/releases/download/v3.1/scrcpy-3.1-win64-v2.zip"},
        {"name": "scrcpy-3.1-macos-arm64-v2.tar.gz",
         "browser_download_url": "https://github.com/Genymobile/scrcpy/releases/download/v3.1/scrcpy-3.1-macos-arm64-v2.tar.gz"},
        {"name": "scrcpy-3.1-macos-x86_64-v2.tar.gz",
         "browser_download_url": "https://github.com/Genymobile/scrcpy/releases/download/v3.1/scrcpy-3.1-macos-x86_64-v2.tar.gz"},
    ],
})


class FakeUrlOpen:
    def __init__(self, payload: bytes, headers: dict | None = None):
        self._payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return self._payload


class TestAdbUrls:
    @pytest.mark.parametrize("system,expected", [
        ("Windows", "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"),
        ("Darwin", "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"),
        ("Linux", "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"),
    ])
    def test_adb_url_per_platform(self, monkeypatch, system, expected):
        monkeypatch.setattr(tm, "OS_TYPE", system)
        assert tm.get_adb_download_url() == expected


class TestScrcpyUrlResolution:
    def test_windows_uses_latest_api_asset(self, monkeypatch):
        monkeypatch.setattr(tm, "OS_TYPE", "Windows")
        monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=10: FakeUrlOpen(SCRCPY_RELEASE_JSON.encode()))
        assert tm.get_scrcpy_download_url().endswith("scrcpy-3.1-win64-v2.zip")

    def test_linux_uses_latest_api_asset(self, monkeypatch):
        monkeypatch.setattr(tm, "OS_TYPE", "Linux")
        monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=10: FakeUrlOpen(SCRCPY_RELEASE_JSON.encode()))
        assert tm.get_scrcpy_download_url().endswith("scrcpy-3.1-linux-x86_64.tar.gz")

    @pytest.mark.parametrize("arch,suffix", [
        ("arm64", "scrcpy-3.1-macos-arm64-v2.tar.gz"),
        ("x86_64", "scrcpy-3.1-macos-x86_64-v2.tar.gz"),
    ])
    def test_macos_selects_arch_asset(self, monkeypatch, arch, suffix):
        monkeypatch.setattr(tm, "OS_TYPE", "Darwin")
        monkeypatch.setattr(tm, "ARCH", arch)
        monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=10: FakeUrlOpen(SCRCPY_RELEASE_JSON.encode()))
        assert tm.get_scrcpy_download_url().endswith(suffix)

    def test_api_failure_falls_back_to_stale_v2_4(self, monkeypatch):
        """R-11 characterization: when the release API is unreachable the code
        silently falls back to the pinned v2.4 asset (a stale, drifted link)."""
        monkeypatch.setattr(tm, "OS_TYPE", "Windows")

        def boom(url, timeout=10):
            raise OSError("network unavailable")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        url = tm.get_scrcpy_download_url()
        assert url == "https://github.com/Genymobile/scrcpy/releases/download/v2.4/scrcpy-2.4-win64-v4.zip"
