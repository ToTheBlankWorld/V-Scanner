"""Tool-manager URL resolution tests (Stage 02, updated Stage 03).

No network access: GitHub API responses are monkey-patched. The stale
scrcpy v2.4 fallback (R-11) was REMOVED in Stage 03 — these tests now lock
in the no-fabricated-URL behavior (API failure / asset miss → None with an
actionable message, never a guessed link).
"""

from __future__ import annotations

import json
from pathlib import Path

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

    def test_api_failure_yields_no_url_after_hardening(self, monkeypatch, capsys):
        """R-11 remediated (Stage 03): an unreachable release API no longer
        falls back to the stale v2.4 asset. No URL is fabricated — the flow
        returns None and the setup path reports an actionable error."""
        monkeypatch.setattr(tm, "OS_TYPE", "Windows")

        def boom(url, timeout=10):
            raise OSError("network unavailable")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        assert tm.get_scrcpy_download_url() is None
        console_out = capsys.readouterr().out
        assert "scrcpy" in console_out.lower()

    def test_api_asset_miss_yields_no_url_after_hardening(self, monkeypatch):
        """R-11 required behavior: even when the API answers, a release with
        no supported asset for the platform returns None (no guessed asset)."""
        empty_release = json.dumps({"assets": [{"name": "scrcpy-9.9-future-os.tar.gz",
                                                "browser_download_url": "https://example.invalid/x"}]})
        monkeypatch.setattr(tm, "OS_TYPE", "Windows")
        monkeypatch.setattr("urllib.request.urlopen",
                            lambda url, timeout=10: FakeUrlOpen(empty_release.encode()))
        assert tm.get_scrcpy_download_url() is None

    def test_stale_v2_4_url_never_referenced_again(self):
        """R-11 regression lock: the removed fallback pin must stay removed —
        no v2.4 download URL may be rebuildable from this module."""
        source = Path(tm.__file__).read_text(encoding="utf-8")
        assert "/v2.4/" not in source and "releases/download/v2.4" not in source
        assert "scrcpy-2.4-" not in source
