"""Tool-provisioning characterization tests (Stage 02 — section D, part 2).

Fake archives are generated programmatically (no binaries committed).
Extraction safety behavior is documented: zipfile sanitizes traversal
members; tarfile (legacy default filters) does not — R-11 evidence.
All temporary directories are pytest-managed; nothing under cli/ is written.
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

import tools_manager as tm


class TestZipExtraction:
    def test_valid_archive_contents_extracted(self, tmp_path):
        archive = tmp_path / "good.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("platform-tools/adb.exe", b"MZ stub")
        out = tmp_path / "out"
        out.mkdir()
        tm.extract_windows_zip(archive, out)
        assert (out / "platform-tools" / "adb.exe").read_bytes() == b"MZ stub"

    def test_corrupt_archive_raises_zipfile_error(self, tmp_path):
        archive = tmp_path / "bad.zip"
        archive.write_bytes(b"definitely not a zip file" * 4)
        out = tmp_path / "out"
        out.mkdir()
        with pytest.raises(zipfile.BadZipFile):
            tm.extract_windows_zip(archive, out)

    def test_zipfile_sanitizes_traversal_members(self, tmp_path):
        """Safety probe: zipfile refuses '..' path members (defense exists —
        the legacy zip path is therefore not the leak)."""
        archive = tmp_path / "slip.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escape_should_not_exist.txt", b"x")
        out = tmp_path / "out"
        out.mkdir()
        tm.extract_windows_zip(archive, out)
        assert not (tmp_path / "escape_should_not_exist.txt").exists()


class TestTarExtraction:
    def test_valid_tar_contents_extracted(self, tmp_path):
        archive = tmp_path / "good.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            data = b"\x7fELF stub"
            info = tarfile.TarInfo("scrcpy-3.1/scrcpy")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        out = tmp_path / "out"
        out.mkdir()
        tm.extract_unix_tar(archive, out)
        assert (out / "scrcpy-3.1" / "scrcpy").read_bytes() == data

    def test_tar_traversal_member_writes_outside_target(self, tmp_path):
        """R-11 characterization (documented defect, not desired behavior):
        the legacy tar extraction member '..' escapes the destination dir."""
        archive = tmp_path / "slip.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo("../tar_escape_should_not_exist.txt")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
        out = tmp_path / "out"
        out.mkdir()
        tm.extract_unix_tar(archive, out)  # must not raise — that IS the defect
        assert (tmp_path / "tar_escape_should_not_exist.txt").exists()

    @pytest.mark.xfail(strict=False, reason="R-11 owned by Stage 03: extraction filter + checksum manifest")
    def test_required_tar_traversal_prevention(self, tmp_path):
        """R-11 required behavior (flips at Stage 03 hardening)."""
        archive = tmp_path / "slip.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo("../tar_escape_required.txt")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
        out = tmp_path / "out"
        out.mkdir()
        with pytest.raises(Exception):
            tm.extract_unix_tar(archive, out)
        assert not (tmp_path / "tar_escape_required.txt").exists()


class TestSetupFlowsOffline:
    def test_setup_adb_short_circuits_when_present(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(tm, "TOOLS_DIR", tmp_path)
        platform_tools = tmp_path / "platform-tools"
        platform_tools.mkdir()
        (platform_tools / "adb.exe").write_bytes(b"MZ stub")  # Windows current OS
        monkeypatch.setattr(tm, "OS_TYPE", "Windows")

        def no_download(url, dest_path):  # network access would fail the test
            raise AssertionError("network access attempted although tool present")

        monkeypatch.setattr(tm, "download_file", no_download)
        assert tm.setup_adb() is True
        assert not list(tmp_path.glob("adb.zip"))

    def test_setup_adb_failure_keeps_returning_false_with_kept_archive(self, tmp_path, monkeypatch):
        """Characterization (cleanup gap, R-11 adjacent): after a failed
        extraction the temp archive is NOT deleted."""
        monkeypatch.setattr(tm, "TOOLS_DIR", tmp_path)
        monkeypatch.setattr(tm, "OS_TYPE", "Windows")
        archive = tmp_path / "adb.zip"
        archive.write_bytes(b"corrupt" * 8)
        monkeypatch.setattr(tm, "download_file", lambda url, dest: True)  # fake success
        assert tm.setup_adb() is False
        assert archive.exists()  # documents the leftover archive

    def test_missing_executable_after_extraction(self, tmp_path, monkeypatch):
        """A valid archive that does not contain adb.exe reports failure."""
        monkeypatch.setattr(tm, "TOOLS_DIR", tmp_path)
        monkeypatch.setattr(tm, "OS_TYPE", "Windows")
        archive = tmp_path / "adb.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("whatever/readme.txt", "no adb here")
        monkeypatch.setattr(tm, "download_file", lambda url, dest: True)
        assert tm.setup_adb() is False
        assert not (tmp_path / "platform-tools" / "adb.exe").exists()

    def test_check_tool_exists_unknown_tool(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tm, "TOOLS_DIR", tmp_path)
        assert tm.check_tool_exists("unknown-tool") is False
